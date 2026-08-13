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
from datetime import date

import page_text
import watchlist

UA = os.environ.get("SEC_USER_AGENT", "").strip()
GAP = 0.15
SUBMISSIONS = "https://data.sec.gov/submissions/CIK%s.json"
OLDER = "https://data.sec.gov/submissions/%s"
ARCHIVE = "https://www.sec.gov/Archives/edgar/data/%s/%s/%s"

# TWO proxies per company, not one. A single year gives fifteen documents and
# four hits, and a precision figure off four hits is not a precision figure.
# The second year mostly adds NEGATIVES, which is the point: recall is
# measured by looking at what the rule rejected.
PROXIES_PER_COMPANY = 2
MAX_DOCS = 40
# Was 400,000, and HUT and IREN both came back at exactly that, which is a
# truncated read reported as a clean negative. Raised, and any document that
# still reaches it is flagged rather than counted as a "no".
TEXT_LIMIT = 1_500_000

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
# A REVERSE SPLIT DOES NOT RAISE THE AUTHORIZED COUNT. It lowers the issued
# count, so the unissued headroom rises RELATIVELY, and proxies describe that
# as an effect in these words. BGDE's 2025-09-04 proxy matched the proposal
# rule on exactly that sentence.
#
# The fragility is the reason this is a separate pattern rather than a tweak:
# SLNH's 2025-07-21 proxy carries the same reverse-split effect and was
# rejected, purely because it says "increase the relative amount of authorized
# but unissued" where BGDE says "relative increase in the number of
# authorized". One matched and one did not on word order alone, so the rule
# was never really 7 of 8 — it was a coin flip that landed well seven times.
EFFECT = re.compile(
    r"reverse\s+(stock\s+)?split|relative(ly)?\s+(increase|amount)"
    r"|increase\s+the\s+relative|but\s+unissued", re.I)
# How much text either side of a candidate is read for that effect language.
EFFECT_WINDOW = 200

# THE RECALL INSTRUMENT. Deliberately far too loose to use as a rule: any
# "increase" within 400 characters of "authorized". Run only over documents
# the strict rule REJECTED, and printed rather than counted, so a proposal
# the strict rule missed is visible instead of being absorbed into a "no".
# A rule can only be shown to have good recall by looking at its negatives.
LOOSE = re.compile(r"increase[^\n]{0,400}?authorized", re.I | re.S)
# THE PROPOSAL LIST, printed for any document that produced a near-miss. A
# near-miss is only adjudicable against what the meeting actually votes on: a
# proxy that DISCUSSES authorized-but-unissued shares while proposing nothing
# is a correct rejection, and one that lists an authorized-share increase as a
# numbered proposal the rule declined is a false negative. Nothing in the
# surrounding prose separates those two, which is why the first sweep left
# two ABTC documents unadjudicated.
PROPOSAL_LIST = re.compile(
    r"proposal\s+(?:no\.?\s*)?(?:\d+|one|two|three|four|five|six|seven)\b[^.]{0,110}",
    re.I)


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


def proposal_match(text):
    """The first candidate that is a PROPOSAL rather than a described effect.

    EVERY candidate is tested, not just the first. A proxy that proposes a
    reverse split AND an authorized increase is a common combination, and
    rejecting the whole document on the first effect-qualified sentence would
    lose the genuine proposal sitting further down it. Rejecting a document
    only when every candidate in it is effect-qualified is the difference
    between a filter and a blindfold.
    """
    for m in PROPOSES.finditer(text):
        around = text[max(0, m.start() - EFFECT_WINDOW):m.end() + EFFECT_WINDOW]
        if not EFFECT.search(around):
            return m
    return None


def lead_days(rows, after, prefixes):
    """Days from `after` to the next filing of any of these form prefixes.

    None when the company has filed none since. Both S-3 and 424 are already
    tracked by press_monitor, so this is the number that decides whether a
    proxy is worth carrying: it is how much earlier the reader would learn
    that the share ceiling is moving.
    """
    later = sorted(r[1] for r in rows
                   if r[1] > after
                   and any(r[0].upper().startswith(p) for p in prefixes))
    if not later:
        return None
    return (date.fromisoformat(later[0]) - date.fromisoformat(after)).days


CONCEPT = ("https://data.sec.gov/api/xbrl/companyconcept/CIK%s/us-gaap/"
           "CommonStockSharesAuthorized.json")


def authorized_history(cik):
    """[(filed, value)] for the authorized share count, oldest first.

    Read from XBRL rather than from a filing body. The count is a tagged
    fact, so this needs no parsing and cannot be fooled by the surrounding
    prose — which is the whole difficulty everywhere else in this probe.

    Deduplicated by value: the same figure is restated in every periodic
    report, and what matters here is when it CHANGED.
    """
    data = fetch_json(CONCEPT % cik.zfill(10))
    if not data:
        return []
    rows = []
    for fact in (data.get("units") or {}).get("shares", []):
        if fact.get("filed") and fact.get("val") is not None:
            rows.append((fact["filed"], int(fact["val"])))
    rows.sort()
    out = []
    for filed, val in rows:
        if not out or out[-1][1] != val:
            out.append((filed, val))
    return out


def time_to_increase(history, proxy_date):
    """(days, before, after, filed) for the first RISE after a proxy.

    None when the ceiling has not risen since. The gap is measured to the
    filing date of the report that first carries the higher number, which is
    when a reader watching financial data rather than proxies would have
    learned it. That is the comparison the whole idea rests on.
    """
    before = None
    for filed, val in history:
        if filed <= proxy_date:
            before = val
        elif before is not None and val > before:
            days = (date.fromisoformat(filed) - date.fromisoformat(proxy_date)).days
            return days, before, val, filed
    return None


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
                for filed, acc, prim in hits[-PROXIES_PER_COMPANY:]:
                    targets.append((ticker, filed, acc, prim, want))
                break
    targets.sort(key=lambda t: t[1], reverse=True)
    targets = targets[:MAX_DOCS]

    print(f"\nREADING THE MOST RECENT DEFINITIVE PROXY FOR "
          f"{len(targets)} COMPANIES")
    proposes, mentions, unreadable = [], 0, 0
    truncated, misses, proposal_lists = 0, [], []
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
        hit = proposal_match(text)
        # The form and the size are printed because they are how a wrong
        # document announces itself: a two-thousand-character "proxy" is a
        # covering letter, not a statement. Truncation is flagged for the
        # same reason — a cut-off read must not be counted as a clean "no".
        cut = "  TRUNCATED" if len(text) >= TEXT_LIMIT else ""
        if cut:
            truncated += 1
        print(f"  {ticker} {filed} {form:<8} {len(text):>7} chars, "
              f"mentions authorized={'yes' if says else 'no':<3} "
              f"proposes increase={'YES' if hit else 'no'}{cut}")
        if not hit and says:
            near = [snippet(text, m) for m in list(LOOSE.finditer(text))[:2]]
            for n in near:
                misses.append((ticker, filed, n, url))
            if near:
                votes = []
                for m in PROPOSAL_LIST.finditer(text):
                    one = " ".join(m.group(0).split())
                    if one.lower() not in [v.lower() for v in votes]:
                        votes.append(one)
                proposal_lists.append((ticker, filed, votes[:12], url))
        if hit:
            proposes.append((ticker, filed, snippet(text, hit), url,
                             lead_days(rows_by_ticker[ticker], filed,
                                       ("S-3",)),
                             lead_days(rows_by_ticker[ticker], filed,
                                       ("424",))))
            pair = FROM_TO.search(text[hit.start():hit.start() + 600])
            if pair:
                print(f"      from {pair.group(1)} to {pair.group(2)}")

    print(f"\n{len(targets) - unreadable} proxies read, {mentions} mention "
          f"authorized shares, {len(proposes)} appear to PROPOSE an increase.")
    if unreadable:
        print(f"{unreadable} could not be read at all.")
    if truncated:
        print(f"{truncated} hit the extraction limit, so their 'no' is a "
              f"truncated read rather than a clean negative.")

    if proposes:
        print("\nEVERY MATCH, IN ITS OWN WORDS — judge the rule on these, "
              "not on the count")
        for ticker, filed, text, url, to_s3, to_424 in proposes:
            print(f"\n  {ticker} {filed}")
            print(f"    {text}")
            print(f"    {url}")
            print(f"    next S-3 {to_s3 if to_s3 is not None else '-':>4}d "
                  f"later, next 424 {to_424 if to_424 is not None else '-':>4}d later")
    else:
        print("\nNo proxy in this sweep proposes an increase. Read that "
              "against the census above:\nproxies filed and none proposing "
              "is a measurement that these companies have\nheadroom today. "
              "It is not evidence that the language is unrecognisable, and "
              "not\nevidence the signal never fires — only that it is not "
              "firing now.")

    # RECALL. Everything above measures what the rule accepted. This is the
    # only part that can show what it wrongly rejected, and it is printed in
    # full because a count of near-misses would say nothing at all.
    print(f"\nWHAT THE RULE REJECTED: {len(misses)} loose hit(s) in documents "
          f"it called 'no'")
    print("A real proposal appearing below is a FALSE NEGATIVE and the rule "
          "is too narrow.\nBoilerplate below is the rule working.")
    for ticker, filed, text, url in misses:
        print(f"\n  {ticker} {filed}")
        print(f"    {text}")
        print(f"    {url}")

    # WHAT THOSE MEETINGS ACTUALLY VOTED ON. Without this a near-miss can only
    # be argued about; with it the question is answered by the document.
    print("\nWHAT THOSE MEETINGS ACTUALLY VOTED ON")
    for ticker, filed, votes, url in proposal_lists:
        print(f"\n  {ticker} {filed}  {url}")
        for v in votes:
            print(f"    - {v}")
        if not votes:
            print("    (no numbered proposal language found)")
    return proposes


def end_to_end(proposals, ciks, rows_by_ticker):
    """Run press_monitor's OWN proxy chain against a real proposing proxy.

    A dry run shows the monitor collects proxies, but it can only show it
    posts one when a proxy is fresh enough to survive the age floor, and
    these arrive once or twice a year per company. Everything between
    collection and the post would otherwise be assumed: the URL built from
    primaryDocument, the fetch, the extraction, the title, and the decision
    to keep the item at all.
    """
    import press_monitor as pm                       # noqa: E402

    if not proposals:
        return
    ticker, filed = proposals[0][0], proposals[0][1]
    row = next((r for r in rows_by_ticker[ticker]
                if r[1] == filed and r[0].upper().startswith(("DEF 14A",
                                                              "PRE 14A"))), None)
    if not row:
        print("\nEND TO END: could not re-find the filing row")
        return
    item = {"ticker": ticker, "form": row[0], "accession": row[2],
            "cik": ciks[ticker][0], "primary": row[3],
            "title": pm.filing_title(row[0], "", "")}
    print(f"\nEND TO END through press_monitor, on {ticker} {filed}")
    print(f"  url:          {pm.filing_document(item['cik'], row[2], row[3])}")
    print(f"  title before: {item['title']}")
    kept = pm.keep_proxy(item)
    print(f"  keep_proxy:   {kept}")
    print(f"  title after:  {item['title']}")
    print(f"  amber:        {item.get('unannounced', False)}")


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

    def report_leads(proposals):
        """The number the build decision rests on, measured per proposal."""
        print("\nHOW LONG BEFORE THE CEILING ACTUALLY MOVED")
        print("Days from the proxy to the first filing carrying a HIGHER "
              "authorized count,\nfrom XBRL rather than from any body text. "
              "The S-3 and 424 columns above are\nnot this number: these "
              "companies file both continuously, so 'the next S-3' is\nsoon "
              "whatever the proxy said.")
        gaps = []
        for ticker, filed, _text, _url, _s3, _424 in proposals:
            time.sleep(GAP)
            history = authorized_history(ciks[ticker][0])
            if not history:
                print(f"  {ticker} {filed}: no CommonStockSharesAuthorized "
                      f"tagged at all")
                continue
            got = time_to_increase(history, filed)
            if not got:
                # "IT HAS NOT RISEN" AND "WE CANNOT SEE IT" ARE DIFFERENT
                # MEASUREMENTS AND MUST NOT SHARE A LABEL. ABTC's last tagged
                # value is from 2022 while its proxy is from 2025, so the
                # probe is blind there rather than observing no change. Under
                # one label that reads as evidence the proposal went nowhere.
                last_filed, current = history[-1]
                if last_filed < filed:
                    print(f"  {ticker} {filed}: NOT MEASURABLE — the concept "
                          f"was last tagged {last_filed}, before this proxy")
                else:
                    print(f"  {ticker} {filed}: no rise yet; still "
                          f"{current:,} as of {last_filed}")
                continue
            days, before, after, when = got
            gaps.append(days)
            print(f"  {ticker} {filed}: {before:,} -> {after:,} first seen "
                  f"{when} — {days}d after the proxy")
        if gaps:
            gaps.sort()
            mid = gaps[len(gaps) // 2]
            print(f"\n  {len(gaps)} measured: median {mid}d, "
                  f"min {gaps[0]}d, max {gaps[-1]}d")
        return gaps

    if not census(rows_by_ticker):
        print("\nNo proxy statements at all. That is a fact about the source "
              "or the form\nmatching, not about the companies: a US listed "
              "issuer holding an annual\nmeeting files one. Check is_proxy "
              "before concluding anything.")
        return 0
    proposals = read_proposals(rows_by_ticker, ciks)
    if proposals:
        report_leads(proposals)
        end_to_end(proposals, ciks, rows_by_ticker)
    return 0


if __name__ == "__main__":
    sys.exit(main())
