#!/usr/bin/env python3
"""Can a proxy statement tell us an authorized-share increase is coming?

WHAT THIS ANSWERS
`dilution.py` tracks shares OUTSTANDING. Nothing tracks the ceiling. For
companies that fund themselves by selling stock continuously, a proposal to
raise the authorized share count is the earliest public signal that the
ceiling is about to move: it is voted at the annual meeting, so the proxy
arrives weeks before the vote, and the vote comes before any S-3 or 424 that
uses the new capacity. `S-3` and `424` are already tracked; this would sit
months upstream of both.

THREE QUESTIONS, CHEAPEST FIRST
1. Do these companies file proxies at all, and how often? Index only.
2. Of the proxies filed, how many actually PROPOSE an increase? This is the
   question that decides the idea, and it needs the body.
3. Can the proposal be told apart from the boilerplate? Every proxy describes
   the company's capital stock, so "authorized shares" appears in all of them.
   A rule that matches the description rather than the proposal would fire
   every year for every company and mean nothing.

WHY IT PRINTS SNIPPETS RATHER THAN A VERDICT
`docs/rejected.md` already carries two probes that died on body-text
ambiguity — contracted capacity from release bodies, and again from titles.
The failure mode both times was a phrase that looked decisive in the abstract
and matched the wrong thing in the corpus. So this prints the matched text
with its surroundings for every hit and every near-miss, and counts the
population that produced them. Read the snippets before believing the count.

WHAT A NULL WOULD MEAN
If no proxy on the roster proposes an increase, that is not "the signal does
not exist" — it is "these companies currently have headroom". The census in
stage 1 is what separates those: a roster filing proxies every year with no
increase proposed is a real measurement, while a roster that files no proxies
at all means the source is wrong rather than the signal.

Read-only. Needs SEC_USER_AGENT. Posts nothing, writes nothing, no deps.
"""

import gzip
import os
import re
import sys
import time
import urllib.error
import urllib.request

import page_text
import watchlist

UA = os.environ.get("SEC_USER_AGENT", "").strip()
GAP = 0.15
SUBMISSIONS = "https://data.sec.gov/submissions/CIK%s.json"
OLDER = "https://data.sec.gov/submissions/%s"
ARCHIVE = "https://www.sec.gov/Archives/edgar/data/%s/%s/%s"

# One document per company: the most recent proxy. Enough to answer whether
# the language is recognisable; not a longitudinal study.
MAX_DOCS = 19
# Proxies run to megabytes. This is generous for the proposal summary, which
# sits in the first pages, and keeps the extraction bounded.
TEXT_LIMIT = 400_000

# THE PROPOSAL, not the description of existing capital stock. Every proxy
# says how many shares are authorized; only some ask to change it.
PROPOSES = re.compile(
    r"(increase|amend\w*\s+\w{0,12}\s*to\s+increase)[^.]{0,120}?"
    r"(number of authorized|authorized shares|authorized (?:shares of )?common)",
    re.I | re.S)
# The boilerplate the rule above must NOT fire on, counted so the difference
# between the two populations is visible rather than assumed.
MENTIONS = re.compile(r"authorized", re.I)
# "from 500,000,000 to 1,000,000,000" — the pair that makes a post worth
# reading. Reported when present; its absence does not disqualify a hit.
FROM_TO = re.compile(
    r"from\s+([\d,]{7,})\s+(?:shares\s+)?to\s+([\d,]{7,})", re.I)


def fetch(url):
    req = urllib.request.Request(
        url, headers={"User-Agent": UA, "Accept-Encoding": "gzip, deflate"})
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            raw = r.read()
            if r.headers.get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
            return raw
    except (urllib.error.URLError, OSError, ValueError) as e:
        print(f"    fetch failed: {type(e).__name__} {url[:90]}")
        return None


def fetch_json(url):
    import json
    raw = fetch(url)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


def all_filings(cik):
    data = fetch_json(SUBMISSIONS % cik)
    if not data:
        return []

    def take(b):
        return list(zip(b.get("form", []), b.get("filingDate", []),
                        b.get("accessionNumber", []),
                        b.get("primaryDocument", [])))

    filings = data.get("filings") or {}
    rows = take(filings.get("recent") or {})
    for extra in filings.get("files") or []:
        time.sleep(GAP)
        older = fetch_json(OLDER % extra["name"])
        if older:
            rows += take(older)
    return rows


def is_proxy(form):
    """Any proxy statement, definitive or preliminary.

    Matching on "14A" rather than a list of spellings: EDGAR carries DEF 14A,
    PRE 14A, DEFA14A, DEFR14A, PREM14A and more, and this repo has already
    been caught once by enumerating form spellings that later changed.
    """
    return "14A" in form.upper()


def document_url(cik, accession, primary):
    parts = [p for p in (primary or "").split("/")
             if not p.lower().startswith("xsl")]
    if not parts:
        return ""
    return ARCHIVE % (cik.lstrip("0"), accession.replace("-", ""),
                      "/".join(parts))


def snippet(text, match, width=160):
    a = max(0, match.start() - width // 2)
    return " ".join(text[a:match.end() + width].split())


def census(rows_by_ticker):
    print("\nCENSUS: proxy statements per company")
    head = f"{'ticker':<8}{'proxies':>9}  {'first':<12}{'last':<12}{'forms seen'}"
    print(head)
    print("-" * (len(head) + 20))
    total = 0
    for ticker, rows in sorted(rows_by_ticker.items()):
        proxies = sorted((r[1], r[0]) for r in rows if is_proxy(r[0]))
        total += len(proxies)
        forms = ", ".join(sorted({f for _, f in proxies}))
        print(f"{ticker:<8}{len(proxies):>9}  "
              f"{(proxies[0][0] if proxies else '-'):<12}"
              f"{(proxies[-1][0] if proxies else '-'):<12}{forms}")
    print(f"\n{total} proxy filing(s) across the roster.")
    return total


def read_proposals(rows_by_ticker, ciks):
    """Stage 2 and 3: what the most recent proxy per company actually says."""
    # THE STATEMENT ITSELF, NOT THE SOLICITING MATERIAL AROUND IT. A first
    # run of this probe took the most recent filing matching "14A", which for
    # most companies is a DEFA14A — a vote-reminder letter or a slide deck,
    # commonly one or two thousand characters. It read 1,055 characters for
    # CLSK and 1,411 for CIFR and reported that 1 of 15 proxies proposed an
    # increase, which measured which document happened to be most recent
    # rather than anything about proposals. The proposals live in the DEF 14A,
    # or in the PRE 14A before it.
    targets = []
    for ticker, rows in rows_by_ticker.items():
        for want in ("DEF 14A", "PRE 14A"):
            hits = sorted((r[1], r[2], r[3]) for r in rows
                          if r[0].upper() == want)
            if hits:
                targets.append((ticker, *hits[-1], want))
                break
    targets.sort(key=lambda t: t[1], reverse=True)
    targets = targets[:MAX_DOCS]

    print(f"\nREADING THE MOST RECENT DEFINITIVE PROXY FOR "
          f"{len(targets)} COMPANIES")
    proposes, mentions, unreadable = [], 0, 0
    for ticker, filed, acc, prim, form in targets:
        url = document_url(ciks[ticker][0], acc, prim)
        time.sleep(GAP)
        raw = fetch(url)
        if raw is None:
            unreadable += 1
            continue
        text = page_text.extract_text(raw.decode("utf-8", "replace"),
                                      limit=TEXT_LIMIT)
        if not text:
            print(f"  {ticker} {filed}: no text extracted from {url[:80]}")
            unreadable += 1
            continue
        says = MENTIONS.search(text)
        if says:
            mentions += 1
        hit = PROPOSES.search(text)
        # The form and the size are printed because they are how a wrong
        # document announces itself: a two-thousand-character "proxy" is a
        # covering letter, not a statement.
        print(f"  {ticker} {filed} {form:<8} {len(text):>7} chars, "
              f"mentions authorized={'yes' if says else 'no':<3} "
              f"proposes increase={'YES' if hit else 'no'}")
        if hit:
            proposes.append((ticker, filed, snippet(text, hit), url))
            pair = FROM_TO.search(text[hit.start():hit.start() + 600])
            if pair:
                print(f"      from {pair.group(1)} to {pair.group(2)}")

    print(f"\n{len(targets) - unreadable} proxies read, {mentions} mention "
          f"authorized shares, {len(proposes)} appear to PROPOSE an increase.")
    if unreadable:
        print(f"{unreadable} could not be read at all.")

    if proposes:
        print("\nEVERY MATCH, IN ITS OWN WORDS — judge the rule on these, "
              "not on the count")
        for ticker, filed, text, url in proposes:
            print(f"\n  {ticker} {filed}")
            print(f"    {text}")
            print(f"    {url}")
    else:
        print("\nNo proxy in this sweep proposes an increase. Read that "
              "against the census above:\nproxies filed and none proposing "
              "is a measurement that these companies have\nheadroom today. "
              "It is not evidence that the language is unrecognisable, and "
              "not\nevidence the signal never fires — only that it is not "
              "firing now.")
    return proposes


def main():
    if not UA:
        sys.exit("SEC_USER_AGENT is not set. Use: 'Your Name your@email.com'")
    ciks = watchlist.ciks()
    rows_by_ticker = {}
    print(f"Walking the filing index for {len(ciks)} companies...")
    for ticker, (cik, _name) in sorted(ciks.items()):
        time.sleep(GAP)
        rows = all_filings(cik)
        rows_by_ticker[ticker] = rows
        print(f"  {ticker}: {len(rows)} filings, "
              f"{sum(1 for r in rows if is_proxy(r[0]))} proxy")

    if not census(rows_by_ticker):
        print("\nNo proxy statements at all. That is a fact about the source "
              "or the form\nmatching, not about the companies: a US listed "
              "issuer holding an annual\nmeeting files one. Check is_proxy "
              "before concluding anything.")
        return 0
    read_proposals(rows_by_ticker, ciks)
    return 0


if __name__ == "__main__":
    sys.exit(main())
