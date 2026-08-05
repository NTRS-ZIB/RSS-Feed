#!/usr/bin/env python3
"""
Identifier audit for the watchlist. A maintenance tool, not a component:
it posts nothing, saves nothing, and runs only when started by hand.

WHAT IT ANSWERS
For every company on the watchlist, which CUSIPs and which SYMBOLS does it
actually appear under in SEC data? That surfaces two things watchlist.py can
otherwise only get by accident:

  1. Retired CUSIPs. A CUSIP survives a rename but not a reverse split, and
     FTD_REPLAY is unbounded — a replay reaching past a change fails to match
     the company and under-reports it with no error anywhere.
  2. Former tickers. A pinned CUSIP appearing under a symbol the roster does
     not know is a rename nobody recorded.

Both were previously found by accident. The first sweep, over twelve months,
turned up BGDE's retired CUSIP 57778N307 and NUAI's former ticker NEHC, and
confirmed every other company.

WHAT IT CANNOT ANSWER
This reads three columns — settlement date, CUSIP, symbol — and a RECYCLED
TICKER looks exactly like a rename in all three. A symbol released by one
company and taken by another produces the same shape as a company that changed
identifiers: rows under one ticker, two CUSIPs, one ending where the other
begins. Nothing here can tell them apart.

The COLLISIONS section below is the check meant to catch it, and it has a
STRUCTURAL BLIND SPOT: it fires only when a row's symbol and CUSIP resolve to
DIFFERENT companies, so it needs a pinned CUSIP to collide with. A newly added
company sits at "cusips": [] by design, exactly as docs/watchlist.md instructs,
so there is nothing to collide with — and a new listing is precisely where a
recycled ticker is most likely, because a symbol only becomes available after
its previous holder gives it up.

SPCX established this. The ticker belonged to a SPAC ETF until 2026-04-07 and
to Space Exploration Technologies from 2026-06-15, and the first sweep after
SPCX was added proposed the ETF's CUSIP under this company with no collision
reported and no other signal. What settled it was the DESCRIPTION column,
which this tool does not parse: the files name the issuer outright.

So: when a proposed CUSIP predates the company's own listing, read the
description before accepting it, and record the refusal in watchlist.py's
REFUSED list rather than in your memory of the verdict.

WHEN TO RUN IT
- After adding a company, to learn what it has traded as. See the two-pass
  note in docs/watchlist.md — a new company usually needs two runs.
- After any reverse split, reorganisation or ticker change.
- Before trusting a deep FTD_REPLAY, since that is the one place an
  unrecorded identifier silently loses data.

Source: the SEC fails-to-deliver files, the same ones ftd_monitor.py reads.

    SEC_USER_AGENT="Your Name you@example.com" python -u audit_identifiers.py

SWEEP_PERIODS sets the depth in half-month periods. Default 24, about twelve
months and roughly 30 MB of downloads.
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
    refused = watchlist.refused_cusips()             # cusip -> record

    print(f"Roster: {len(watchlist.tickers())} tickers, "
          f"{len(known_cusips)} CUSIPs, {len(known_symbols)} symbols, "
          f"{len(refused)} refused\n")

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
    refused_hits = []
    for ticker in sorted(watchlist.tickers()):
        seen = cusips.get(ticker, {})
        if not seen:
            print(f"\n{ticker}: no rows in the swept window")
            continue
        print(f"\n{ticker}:")
        for cu, v in sorted(seen.items(), key=lambda kv: kv[1][0]):
            known = known_cusips.get(cu) == ticker
            # `ref` is a THIRD state, and the reason this loop is not a
            # boolean. A refused identifier is not unknown — it has been seen,
            # checked against the SEC's description and rejected — so
            # reporting it as NEW would ask the reader to take the same
            # decision again, and eventually somebody takes it differently.
            if cu in refused:
                refused_hits.append((ticker, cu, span(v)))
                print(f"  ref {cu}   {span(v)}   <- REFUSED, "
                      f"{refused[cu]['belongs_to']}")
                continue
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

    if refused_hits:
        print("\n" + "=" * 72)
        print("REFUSED — matched, and rejected by record in watchlist.py")
        print("=" * 72)
        for ticker, cu, when in refused_hits:
            r = refused[cu]
            print(f"\n  {ticker}: {cu}   {when}")
            print(f"    belongs to : {r['belongs_to']}")
            print(f"    handover   : traded as {r['symbol']} to {r['handover']}")
            print(f"    why        : {r['why']}")
        print("\n  These are NOT proposals. Do not add them. If you believe one")
        print("  is wrong, change REFUSED in watchlist.py and say why there —")
        print("  not here, and not by adding the identifier back.")

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
