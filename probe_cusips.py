#!/usr/bin/env python3
"""
THROWAWAY PROBE — not a component. Delete after use.

Closes a known gap in watchlist.py: retired CUSIPs.

Two are recorded — ANY's pre-reverse-split identifier and BKKT's
pre-reorganisation one — and BOTH were found by accident, one from a replay
that happened to reach far enough back and one from an 8-K12B read for an
unrelated reason. Nine companies have never been checked.

That matters because FTD_REPLAY is unbounded. A replay reaching past a CUSIP
change fails to match the company, and an unmatched symbol simply produces no
rows — the company under-reports with no error anywhere.

This sweeps the SEC's fails-to-deliver files and records, for every watchlist
company, every CUSIP and every SYMBOL it appears under. It answers two
questions:

  1. Which CUSIPs are missing from watchlist.py?
  2. Which former TICKERS are missing? A pinned CUSIP appearing under a symbol
     the roster does not know is a rename nobody recorded.

Read-only. Downloads zips, prints, exits. No webhook, no state, no commit.

    SEC_USER_AGENT="Your Name you@example.com" python -u probe_cusips.py

Set SWEEP_PERIODS to change the depth. Default 24 half-month periods, about
twelve months, which is roughly 30 MB of downloads.
"""

import io
import os
import re
import sys
import time
import zipfile
from collections import defaultdict
from urllib.parse import urljoin

import requests

import watchlist

INDEX_URL = "https://www.sec.gov/data-research/sec-markets-data/fails-deliver-data"
PERIOD_RE = re.compile(r'href="([^"]*?cnsfails(\d{4})(\d{2})([ab])[^"]*?\.zip)"', re.I)

SWEEP_PERIODS = int(os.environ.get("SWEEP_PERIODS", "24"))
USER_AGENT = os.environ.get("SEC_USER_AGENT", "").strip()
REQUEST_GAP = 0.3
TIMEOUT = 60


def session():
    s = requests.Session()
    s.headers.update({
        "User-Agent": USER_AGENT or "watchlist-probe contact@example.com",
        "Accept-Encoding": "gzip, deflate",
    })
    return s


def fetch_index(sess):
    r = sess.get(INDEX_URL, timeout=TIMEOUT)
    r.raise_for_status()
    found = {}
    for href, yyyy, mm, half in PERIOD_RE.findall(r.text):
        found.setdefault(f"{yyyy}{mm}{half}", urljoin(INDEX_URL, href))
    return sorted(found.items(), reverse=True)


def rows_of(sess, url):
    r = sess.get(url, timeout=TIMEOUT)
    r.raise_for_status()
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    member = next(n for n in zf.namelist() if not n.endswith("/"))
    for line in zf.read(member).decode("latin-1").splitlines():
        parts = line.split("|")
        if len(parts) < 4:
            continue
        date, cusip, symbol = (p.strip() for p in parts[:3])
        if date.isdigit() and len(date) == 8:
            yield date, cusip, symbol.upper()


def main():
    if not USER_AGENT:
        print("WARNING: SEC_USER_AGENT not set. SEC throttles anonymous traffic.\n")

    for problem in watchlist.validate():
        print(f"WARNING: watchlist.py — {problem}")

    known_cusips = watchlist.cusip_pins()            # cusip -> ticker
    known_symbols = watchlist.symbol_to_ticker()     # symbol -> ticker

    print(f"Roster: {len(watchlist.tickers())} tickers, "
          f"{len(known_cusips)} CUSIPs, {len(known_symbols)} symbols\n")

    sess = session()
    periods = fetch_index(sess)[:SWEEP_PERIODS]
    if not periods:
        sys.exit("No cnsfails links found on the index page — layout changed?")
    print(f"Sweeping {len(periods)} periods, "
          f"{periods[-1][0][:4]}-{periods[-1][0][4:6]} to "
          f"{periods[0][0][:4]}-{periods[0][0][4:6]}\n")

    # ticker -> {cusip: (first_seen, last_seen)}  and  ticker -> {symbol: ...}
    cusips = defaultdict(dict)
    symbols = defaultdict(dict)
    collisions = []

    for period, url in sorted(periods):
        print(f"  {period[:4]}-{period[4:6]}{period[6]} ...", end=" ", flush=True)
        try:
            hits = 0
            for date, cusip, symbol in rows_of(sess, url):
                by_sym = known_symbols.get(symbol)
                by_cus = known_cusips.get(cusip)

                if by_sym and by_cus and by_sym != by_cus:
                    collisions.append((period, date, symbol, cusip, by_sym, by_cus))
                    continue

                ticker = by_sym or by_cus
                if not ticker:
                    continue
                hits += 1
                for store, key in ((cusips[ticker], cusip), (symbols[ticker], symbol)):
                    if key not in store:
                        store[key] = [date, date]
                    else:
                        store[key][0] = min(store[key][0], date)
                        store[key][1] = max(store[key][1], date)
            print(f"{hits} matching row(s)")
        except Exception as e:
            print(f"FAILED {type(e).__name__}: {e}")
        time.sleep(REQUEST_GAP)

    def span(v):
        a, b = v
        return f"{a[:4]}-{a[4:6]}-{a[6:]} to {b[:4]}-{b[4:6]}-{b[6:]}"

    print("\n" + "=" * 72)
    print("CUSIPs seen per company")
    print("=" * 72)
    new_cusips = defaultdict(list)
    for ticker in sorted(watchlist.tickers()):
        seen = cusips.get(ticker, {})
        if not seen:
            print(f"\n{ticker}: no rows in the swept window")
            continue
        print(f"\n{ticker}:")
        for cu, v in sorted(seen.items(), key=lambda kv: kv[1][0]):
            known = known_cusips.get(cu) == ticker
            if not known:
                new_cusips[ticker].append(cu)
            print(f"  {'ok ' if known else 'NEW'} {cu}   {span(v)}")

    print("\n" + "=" * 72)
    print("Symbols seen per company")
    print("=" * 72)
    new_symbols = defaultdict(list)
    for ticker in sorted(watchlist.tickers()):
        seen = symbols.get(ticker, {})
        if not seen:
            continue
        extra = [s for s in seen if known_symbols.get(s) != ticker]
        marker = "" if not extra else "   <- unrecorded symbol(s)"
        print(f"\n{ticker}:{marker}")
        for sym, v in sorted(seen.items(), key=lambda kv: kv[1][0]):
            known = known_symbols.get(sym) == ticker
            if not known:
                new_symbols[ticker].append(sym)
            print(f"  {'ok ' if known else 'NEW'} {sym:<8} {span(v)}")

    if collisions:
        print("\n" + "=" * 72)
        print("COLLISIONS — a row whose symbol and CUSIP name different companies")
        print("=" * 72)
        for period, date, sym, cu, a, b in collisions[:20]:
            print(f"  {period} {date}  {sym} -> {a}  but  {cu} -> {b}")
        print(f"  ({len(collisions)} total)")
        print("  This means the roster is wrong somewhere. Investigate before")
        print("  trusting anything above.")

    print("\n" + "=" * 72)
    print("VERDICT")
    print("=" * 72)
    if not new_cusips and not new_symbols:
        print(f"Nothing unrecorded across {len(periods)} periods. The roster is")
        print("complete for this window. Deeper history could still hold more —")
        print("re-run with SWEEP_PERIODS higher if a replay ever goes further back.")
    else:
        if new_cusips:
            print("\nCUSIPs to add to watchlist.py:")
            for t, cus in sorted(new_cusips.items()):
                for cu in cus:
                    ok = watchlist.cusip_check_digit(cu) == cu[8] and len(cu) == 9
                    print(f'  {t}: "{cu}"   check digit {"valid" if ok else "INVALID"}')
        if new_symbols:
            print("\nSymbols to add to alt_symbols in watchlist.py:")
            for t, syms in sorted(new_symbols.items()):
                print(f'  {t}: {syms}')
            print("\n  A symbol found only via a pinned CUSIP is a rename nobody")
            print("  recorded. Check it is the same company before adding it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
