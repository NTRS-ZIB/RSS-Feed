#!/usr/bin/env python3
"""What EDGAR currently says about a company someone wants to add.

WHY THIS EXISTS
A roster addition starts as a name somebody remembers, and this repository has
written three separate warnings against acting on that. Six of nineteen
companies renamed in eighteen months; one ticker on the roster was previously
a DIFFERENT company's; and the first audit after SPCX was added proposed the
ticker's previous owner's CUSIP — right shape, right dates, wrong company.

So before a record is written, the questions are: does this ticker still
resolve at all, to which CIK, under what name today, with what former names,
and is the registrant still filing. All of that is in two SEC endpoints and
none of it is in anybody's memory.

WHAT IT DELIBERATELY DOES NOT DO
It does not propose a CUSIP. A CUSIP comes from data a component actually
reads — the FINRA and SEC files ftd_monitor and short_interest parse — never
from a filing and never from here. `audit_identifiers.py` owns that, and it
needs two passes. This probe answers only the questions that come first.

HOW TO READ THE OUTPUT
  ticker does not resolve   acquired, delisted or renamed. Do not add it.
  name differs from yours   you are remembering an old name, or the wrong
                            company. Read formerNames before deciding.
  CIK already on the roster the company is already tracked under another
                            ticker; this would be a duplicate, not an addition
  no recent filings         a registrant that has stopped filing is not a
                            live company for this repo's purposes

Read-only. Needs SEC_USER_AGENT. Posts nothing, writes nothing.
"""

import gzip
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import date, timedelta

import watchlist

# Edit this before running. These are the candidates as of 2026-08-13; the
# point of the probe is that none of them is trusted until it answers.
CANDIDATES = ["RIOT", "CORZ", "BITF", "HIVE", "CRWV", "BTBT", "CANG"]

UA = os.environ.get("SEC_USER_AGENT", "").strip()
GAP = 0.15
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS = "https://data.sec.gov/submissions/CIK%s.json"
RECENT_DAYS = 120


def fetch_json(url):
    req = urllib.request.Request(
        url, headers={"User-Agent": UA, "Accept-Encoding": "gzip, deflate"})
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            raw = r.read()
            if r.headers.get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
        return json.loads(raw)
    except (urllib.error.URLError, OSError, ValueError) as e:
        print(f"    fetch failed: {type(e).__name__} {url[:80]}")
        return None


def main():
    if not UA:
        sys.exit("SEC_USER_AGENT is not set. Use: 'Your Name your@email.com'")

    roster = watchlist.ciks()
    on_roster = {cik.lstrip("0"): t for t, (cik, _n) in roster.items()}

    print(f"Resolving {len(CANDIDATES)} candidate(s) against EDGAR's own "
          f"ticker index...")
    index = fetch_json(TICKERS_URL)
    if not index:
        sys.exit("EDGAR's ticker index did not return; nothing can be checked.")
    by_ticker = {}
    for row in index.values():
        by_ticker.setdefault(str(row.get("ticker", "")).upper(),
                             (str(row.get("cik_str")), row.get("title", "")))
    print(f"  {len(by_ticker)} tickers in the index\n")

    cutoff = (date.today() - timedelta(days=RECENT_DAYS)).isoformat()
    for want in CANDIDATES:
        hit = by_ticker.get(want.upper())
        print(f"{want}")
        if not hit:
            # The most decision-relevant answer there is: a ticker that does
            # not resolve has been acquired, delisted or renamed, and adding
            # it would create a record that matches nothing and says nothing.
            print("  DOES NOT RESOLVE in EDGAR's ticker index — acquired, "
                  "delisted or renamed. Do not add.\n")
            continue
        cik, title = hit
        print(f"  CIK {cik.zfill(10)}  {title}")
        if cik.lstrip('0') in on_roster:
            print(f"  ALREADY ON THE ROSTER as {on_roster[cik.lstrip('0')]} — "
                  f"this would be a duplicate, not an addition")
        time.sleep(GAP)
        sub = fetch_json(SUBMISSIONS % cik.zfill(10))
        if not sub:
            print("  submissions index did not return\n")
            continue
        former = [f.get("name") for f in (sub.get("formerNames") or [])]
        if former:
            print(f"  former names: {', '.join(filter(None, former))}")
        print(f"  exchanges: {', '.join(sub.get('exchanges') or []) or '-'}"
              f"   SIC: {sub.get('sicDescription') or '-'}")
        recent = (sub.get("filings") or {}).get("recent") or {}
        forms = recent.get("form", [])
        dates = recent.get("filingDate", [])
        fresh = [(d, f) for d, f in zip(dates, forms) if d >= cutoff]
        if not fresh:
            print(f"  NO FILINGS in {RECENT_DAYS} days — not a live filer\n")
            continue
        newest = max(fresh)
        kinds = sorted({f for _, f in fresh})
        print(f"  {len(fresh)} filing(s) in {RECENT_DAYS}d, newest "
              f"{newest[0]} {newest[1]}")
        print(f"  forms seen: {', '.join(kinds[:14])}")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
