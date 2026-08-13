#!/usr/bin/env python3
"""Does Form 144 give useful advance notice of an insider sale?

WHAT THIS ANSWERS
The insider channel posts Forms 3 and 4, which report a sale AFTER it
settles. Form 144 is filed BEFORE: it states an intent to sell, a share
count and a broker. If it arrives meaningfully earlier than the Form 4 that
follows, it is the only forward-looking insider signal available from a
source this repo already fetches every run. If it arrives the same day, it
adds a restatement and nothing else.

THREE QUESTIONS, IN ORDER, AND THE FIRST CAN KILL THE OTHER TWO
1. Do Form 144 filings appear under the ISSUER's CIK at all? A 144 is filed
   by the selling person, not the company, so its presence in the issuer's
   submissions index is an ASSUMPTION until this prints a count. If it is
   zero everywhere, the feature is not available from the submissions call
   the press monitor already makes, and questions 2 and 3 are moot.
2. How many are there, per company, over what span? Electronic filing of
   Form 144 became the norm only recently, so history is short and a count
   from before that is not evidence about now.
3. How far ahead of the matching Form 4 does a 144 arrive?

WHY IT WALKS THE WHOLE INDEX
The submissions endpoint returns the most recent 1,000 filings and
references older pages separately. Several companies on this roster file
more than 1,000, and for a form type that may be rare the truncated page is
exactly where a null result would come from. A window that finds nothing has
only shown it did not sweep far enough.

WHY IT PRINTS THE SCHEMA BEFORE MATCHING
Nobody here has parsed a Form 144 before, so the element names are unknown.
Guessing them and reporting "0 matched" would look like a measurement of the
filings rather than of the guess. So the first 144 found is dumped in full,
and the matching below reports its own failures separately from its results.

Read-only. Needs SEC_USER_AGENT. Posts nothing, writes nothing.
"""

import collections
import gzip
import json
import os
import re
import statistics
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date

import watchlist

UA = os.environ.get("SEC_USER_AGENT", "").strip()
GAP = 0.15                      # SEC asks for <10 req/s; this is well inside
SUBMISSIONS = "https://data.sec.gov/submissions/CIK%s.json"
OLDER = "https://data.sec.gov/submissions/%s"
ARCHIVE = "https://www.sec.gov/Archives/edgar/data/%s/%s/%s"

# How far after a 144 to look for the Form 4 that reports the same sale. A
# 144 covers sales over the following three months, so a window shorter than
# that would count a real pair as unmatched.
MATCH_WINDOW_DAYS = 100
# Bound on the expensive half. Each sampled 144 costs one document fetch,
# plus one index fetch per filer not seen before.
MAX_SAMPLE = 40


def fetch(url):
    """Raw bytes, or None. Never raises: one dead URL must not end the run."""
    req = urllib.request.Request(
        url, headers={"User-Agent": UA, "Accept-Encoding": "gzip, deflate"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
            if r.headers.get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
            return raw
    except (urllib.error.URLError, OSError, ValueError) as e:
        print(f"    fetch failed: {type(e).__name__} {url[:90]}")
        return None


def fetch_json(url):
    raw = fetch(url)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        print(f"    not JSON: {url[:90]}")
        return None


def all_filings(cik):
    """(form, filed, accession, primaryDocument) for EVERY filing on record."""
    data = fetch_json(SUBMISSIONS % cik)
    if not data:
        return []
    rows = []

    def take(block):
        return list(zip(block.get("form", []), block.get("filingDate", []),
                        block.get("accessionNumber", []),
                        block.get("primaryDocument", [])))

    filings = data.get("filings") or {}
    rows += take(filings.get("recent") or {})
    for extra in filings.get("files") or []:
        time.sleep(GAP)
        older = fetch_json(OLDER % extra["name"])
        if older:
            rows += take(older)
    return rows


def is_144(form):
    """Form 144 and its amendments, and nothing else.

    No other EDGAR form type begins with these three characters, so a plain
    prefix test is safe here — unlike "4", which would swallow 424 and 40-F.
    """
    return form.upper().startswith("144")


def source_document(cik, accession, primary):
    """The URL of the filing's SOURCE xml, not EDGAR's rendered view.

    EDGAR's primaryDocument for a structured filing points at the XSL-rendered
    HTML, which parses as XML only by accident and usually not at all. The
    source sits in the same directory with the stylesheet segment removed.
    This repo has written off three companies as "not really structured" on
    that mistake; the segment is stripped here rather than rediscovered.
    """
    nodash = accession.replace("-", "")
    parts = [p for p in (primary or "").split("/") if not p.lower().startswith("xsl")]
    return ARCHIVE % (cik.lstrip("0"), nodash, "/".join(parts))


def strip_ns(tag):
    return tag.split("}", 1)[-1]


def parse_xml(raw):
    if raw is None:
        return None
    try:
        return ET.fromstring(raw)
    except ET.ParseError as e:
        print(f"    XML parse failed: {e}")
        return None


def flatten(node, prefix="", out=None):
    """{path: text} for every element carrying text. Schema-agnostic."""
    out = {} if out is None else out
    for child in node:
        name = strip_ns(child.tag)
        path = f"{prefix}/{name}" if prefix else name
        text = (child.text or "").strip()
        if text:
            out.setdefault(path, text)
        flatten(child, path, out)
    return out


# The exact leaf elements that name the person, one per form, read off the
# schema dump rather than guessed.
#
# A TOLERANT VERSION OF THIS RETURNED A CLEAN, WRONG ZERO. It skipped any
# path containing "issuer" and took the first leaf ending in "name" — but
# Form 144 nests the seller inside `issuerInfo`, so the skip removed the
# right answer and the fallback found `brokerOrMarketmakerDetails/name`. The
# probe then compared a brokerage against Form 4 owner names, matched
# nothing, and reported "no Form 4 by the same person in window: 12", which
# reads as a finding about insiders rather than a bug in the extractor.
PERSON_LEAVES = {
    "nameOfPersonForWhoseAccountTheSecuritiesAreToBeSold",   # Form 144
    "rptOwnerName",                                          # Forms 3, 4, 5
}


def filer_cik(fields):
    """The CIK of whoever FILED this, from the submission header.

    Not the issuer: a Form 144 is filed by the selling person, and this
    is the identifier that lets their own filing history be read.
    """
    for path, value in fields.items():
        if path.endswith("filerCredentials/cik"):
            return value.strip()
    return ""


def person_name(fields):
    """The name of the person the filing is about, or "" if absent."""
    for path, value in fields.items():
        if path.rsplit("/", 1)[-1] in PERSON_LEAVES:
            return value
    return ""


def norm_name(name):
    return re.sub(r"[^a-z]", "", (name or "").lower())


def census(rows_by_ticker):
    """Question 1 and 2: does it exist, how much, and over what span."""
    print("\nCENSUS: Form 144 under the ISSUER's CIK")
    head = f"{'ticker':<8}{'filings':>9}{'144s':>7}{'form 4s':>9}  {'first 144':<12}{'last 144':<12}"
    print(head)
    print("-" * len(head))
    total_144 = 0
    for ticker, rows in sorted(rows_by_ticker.items()):
        ones = sorted(r[1] for r in rows if is_144(r[0]))
        fours = sum(1 for r in rows if r[0].upper() in ("4", "4/A"))
        total_144 += len(ones)
        print(f"{ticker:<8}{len(rows):>9}{len(ones):>7}{fours:>9}  "
              f"{(ones[0] if ones else '-'):<12}{(ones[-1] if ones else '-'):<12}")
    print("-" * len(head))
    print(f"{total_144} Form 144 filing(s) across the roster.")
    return total_144


def lead_times(rows_by_ticker, ciks):
    """Question 3: how far ahead of the matching Form 4 does a 144 arrive?"""
    sample = []
    for ticker, rows in rows_by_ticker.items():
        for form, filed, acc, prim in rows:
            if is_144(form):
                sample.append((ticker, filed, acc, prim))
    sample.sort(key=lambda r: r[1], reverse=True)
    sample = sample[:MAX_SAMPLE]
    if not sample:
        return

    print(f"\nSCHEMA: the most recent Form 144, in full")
    ticker, filed, acc, prim = sample[0]
    cik = ciks[ticker][0]
    url = source_document(cik, acc, prim)
    print(f"  {ticker} {filed}  {url}")
    root = parse_xml(fetch(url))
    if root is None:
        print("  could not parse it, so the matching below is running blind")
    else:
        for path, value in flatten(root).items():
            print(f"    {path} = {value[:70]}")

    print(f"\nLEAD TIME over the {len(sample)} most recent 144s")
    leads, unmatched, seen_names = [], collections.Counter(), []
    person_index = {}          # filer CIK -> their whole filing index
    today = date.today()
    for ticker, filed, acc, prim in sample:
        cik = ciks[ticker][0]
        time.sleep(GAP)
        root = parse_xml(fetch(source_document(cik, acc, prim)))
        if root is None:
            unmatched["144 would not parse"] += 1
            continue
        raw_who = person_name(flatten(root))
        who = norm_name(raw_who)
        if not who:
            unmatched["no name found in the 144"] += 1
            continue
        seen_names.append(f"{ticker} {filed} {raw_who}")

        # THE FILER'S OWN CIK, from the 144's header. This is what makes the
        # unmatched cases explainable rather than merely counted. An earlier
        # version walked the issuer's next N Form 4s and fetched each one to
        # read its owner: that capped the lookahead, and on a company filing
        # 298 Form 4s the cap can span only days, so a real pair with a longer
        # lead was indistinguishable from no pair at all.
        #
        # Intersecting the PERSON's own filing index with the issuer's
        # accessions removes the cap entirely and costs one request per
        # person rather than one per candidate filing.
        filer = filer_cik(flatten(root))
        if not filer:
            unmatched["no filer CIK in the 144 header"] += 1
            continue
        if filer not in person_index:
            time.sleep(GAP)
            person_index[filer] = all_filings(filer.zfill(10))
        mine = person_index[filer]
        if not mine:
            unmatched["the filer's own index could not be read"] += 1
            continue

        issuer_form4 = {r[2]: r[1] for r in rows_by_ticker[ticker]
                        if r[0].upper() in ("4", "4/A")}
        # Their Form 4s FOR THIS ISSUER: same accession in both indexes.
        theirs = sorted((issuer_form4[r[2]], r[2]) for r in mine
                        if r[0].upper() in ("4", "4/A") and r[2] in issuer_form4)
        after = [(d, a) for d, a in theirs if d >= filed]
        if not after:
            age = (today - date.fromisoformat(filed)).days
            if theirs:
                unmatched[f"no Form 4 since; last was {theirs[-1][0]}"] += 1
                print(f"  {ticker}  144 {filed}  NO SALE REPORTED "
                      f"({age}d ago; this filer's last Form 4 {theirs[-1][0]})")
            else:
                unmatched["this filer has never filed a Form 4 here"] += 1
                print(f"  {ticker}  144 {filed}  NO FORM 4 EVER by this filer")
            continue
        days = (date.fromisoformat(after[0][0]) - date.fromisoformat(filed)).days
        if days > MATCH_WINDOW_DAYS:
            unmatched[f"next Form 4 was {days}d later, beyond the window"] += 1
            continue
        leads.append(days)
        print(f"  {ticker}  144 {filed} -> form 4 {after[0][0]}  {days:>3}d")

    if leads:
        leads.sort()
        print(f"\n  matched {len(leads)}: median {statistics.median(leads):.0f}d, "
              f"min {leads[0]}d, max {leads[-1]}d, "
              f"same-day {sum(1 for d in leads if d == 0)}")
    for reason, n in unmatched.most_common():
        print(f"  unmatched, {reason}: {n}")
    # The names actually compared. A silently wrong extractor is the failure
    # mode this whole section had on its first run, and a count alone hid it.
    print("\n  names read from the 144s:")
    for line in seen_names:
        print(f"    {line}")


def main():
    if not UA:
        sys.exit("SEC_USER_AGENT is not set. Use: 'Your Name your@email.com'")
    ciks = watchlist.ciks()
    rows_by_ticker = {}
    print(f"Walking the full filing index for {len(ciks)} companies...")
    for ticker, (cik, _name) in sorted(ciks.items()):
        time.sleep(GAP)
        rows = all_filings(cik)
        rows_by_ticker[ticker] = rows
        ones = sum(1 for r in rows if is_144(r[0]))
        print(f"  {ticker}: {len(rows)} filings, {ones} Form 144")

    total = census(rows_by_ticker)
    if not total:
        print("\nNo Form 144 appears under any issuer CIK on this roster.\n"
              "That answers question 1 and closes the other two: the filing is\n"
              "indexed under the selling person, not the company, so it is NOT\n"
              "available from the submissions call the press monitor already\n"
              "makes. Adding \"144\" to FORM_TYPES would match nothing, which is\n"
              "indistinguishable from a form whose filings never occur.")
        return 0
    lead_times(rows_by_ticker, ciks)
    return 0


if __name__ == "__main__":
    sys.exit(main())
