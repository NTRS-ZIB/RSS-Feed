#!/usr/bin/env python3
"""
Part three: re-derive the constant against the digest's own return definition.

TEMPORARY. Posts nothing, decides nothing.

PARTS ONE AND TWO USED FIRST-OPEN -> LAST-CLOSE. The digest uses PRIOR CLOSE ->
LAST CLOSE:

    open_px, close_px = before[-1][1], inside[-1][1]

which includes the weekend gap and the Monday open, and excludes Monday's
intraday move from the open. On W32 the two disagree by about two points —
CIFR -23.0 against -21.2, SPCX +22.8 against +25.1 — and a threshold derived
on one and applied to the other is the adjacent-population mistake in a new
place. So every table below is recomputed on the digest's definition, and the
two are printed side by side so the size of the difference is visible rather
than asserted.

The candidate to confirm or move: |return| >= 18% AND >= 2.0x the roster's
median |return| that week.
"""

import os
import statistics
import sys
import time
from collections import defaultdict
from datetime import date, datetime, timedelta

import requests

import watchlist

KEY = os.environ.get("ALPACA_KEY_ID", "").strip()
SECRET = os.environ.get("ALPACA_SECRET_KEY", "").strip()
if not (KEY and SECRET):
    raise SystemExit("ALPACA_KEY_ID / ALPACA_SECRET_KEY not set.")

BARS = "https://data.alpaca.markets/v2/stocks/bars"
FEED = "sip"


def fetch(symbols, start):
    out = defaultdict(list)
    token = None
    while True:
        params = {"symbols": ",".join(symbols), "timeframe": "1Day",
                  "start": start, "limit": 10000, "feed": FEED,
                  "adjustment": "all"}
        if token:
            params["page_token"] = token
        r = requests.get(BARS, params=params, timeout=(10, 60),
                         headers={"APCA-API-KEY-ID": KEY,
                                  "APCA-API-SECRET-KEY": SECRET})
        r.raise_for_status()
        d = r.json()
        for sym, rows in (d.get("bars") or {}).items():
            out[sym] += rows
        token = d.get("next_page_token")
        if not token:
            break
        time.sleep(0.2)
    return out


def iso_week(day):
    y, w, _ = day.isocalendar()
    return f"{y}-W{w:02d}"


def main():
    roster = sorted(watchlist.ciks())
    start = (date.today() - timedelta(weeks=66)).isoformat()
    bars = fetch(roster, start)

    # Per ticker, an ordered (date, close) series — the shape the digest reads.
    series = {}
    for sym, rows in bars.items():
        rows.sort(key=lambda x: x["t"])
        series[sym] = [(datetime.fromisoformat(
            b["t"].replace("Z", "+00:00")).date(), b["c"], b["o"]) for b in rows]

    digest_r = defaultdict(dict)     # prior close -> last close
    probe_r = defaultdict(dict)      # first open  -> last close
    for sym, rows in series.items():
        byweek = defaultdict(list)
        for d, c, o in rows:
            byweek[iso_week(d)].append((d, c, o))
        for wk, seg in byweek.items():
            if len(seg) < 2:
                continue
            first = seg[0][0]
            before = [r for r in rows if r[0] < first]
            if before and before[-1][1]:
                digest_r[wk][sym] = (seg[-1][1] - before[-1][1]) \
                    / before[-1][1] * 100
            if seg[0][2]:
                probe_r[wk][sym] = (seg[-1][1] - seg[0][2]) / seg[0][2] * 100

    this = iso_week(date.today())
    weeks = sorted(w for w in digest_r if w < this)[-53:]

    print("=" * 78)
    print("1. HOW FAR APART THE TWO DEFINITIONS ARE")
    print("=" * 78)
    diffs = [abs(digest_r[w][t] - probe_r[w][t])
             for w in weeks for t in digest_r[w] if t in probe_r.get(w, {})]
    diffs.sort()
    print(f"  {len(diffs)} ticker-weeks measured both ways")
    print(f"  |difference|  p50 {diffs[len(diffs)//2]:.1f}pts  "
          f"p90 {diffs[int(len(diffs)*.9)]:.1f}  "
          f"p99 {diffs[int(len(diffs)*.99)]:.1f}  max {diffs[-1]:.1f}")

    print("\n" + "=" * 78)
    print("2. THE CANDIDATE GRID, ON THE DIGEST'S DEFINITION")
    print("=" * 78)
    print(f"  {'rule':<18}{'mean/wk':>9}{'median':>8}{'max':>6}"
          f"{'wks>=1':>8}{'wks>=5':>8}{'total':>7}")
    for abs_t in (15, 18, 20):
        for rel in (1.5, 2.0, 2.5):
            per = []
            for w in weeks:
                v = digest_r[w]
                med = statistics.median(abs(x) for x in v.values()) or 0.01
                per.append(sum(1 for x in v.values()
                               if abs(x) >= abs_t and abs(x) / med >= rel))
            print(f"  {'>=%d%% & >=%.1fx' % (abs_t, rel):<18}"
                  f"{statistics.mean(per):>9.1f}{statistics.median(per):>8.1f}"
                  f"{max(per):>6}{sum(1 for p in per if p):>8}"
                  f"{sum(1 for p in per if p >= 5):>8}{sum(per):>7}")

    print("\n  the same grid on the PROBE definition, for comparison")
    for abs_t in (18,):
        for rel in (2.0,):
            per = []
            for w in weeks:
                v = probe_r[w]
                med = statistics.median(abs(x) for x in v.values()) or 0.01
                per.append(sum(1 for x in v.values()
                               if abs(x) >= abs_t and abs(x) / med >= rel))
            print(f"  {'>=%d%% & >=%.1fx' % (abs_t, rel):<18}"
                  f"{statistics.mean(per):>9.1f}{statistics.median(per):>8.1f}"
                  f"{max(per):>6}{sum(1 for p in per if p):>8}"
                  f"{sum(1 for p in per if p >= 5):>8}{sum(per):>7}")

    print("\n" + "=" * 78)
    print("3. ABSOLUTE-ONLY, RECONFIRMED ON THE DIGEST'S DEFINITION")
    print("=" * 78)
    print("  the finding that killed it must survive the redefinition too\n")
    for c in (10, 15, 18, 20, 25):
        per = [sum(1 for x in digest_r[w].values() if abs(x) >= c)
               for w in weeks]
        print(f"  >={c:>2}%  mean {statistics.mean(per):4.1f}/wk  "
              f"max {max(per):>2}  weeks naming >=5: "
              f"{sum(1 for p in per if p >= 5)}/{len(weeks)}")

    print("\n" + "=" * 78)
    print("4. THE CANDIDATE WEEK BY WEEK, DIGEST DEFINITION")
    print("=" * 78)
    for w in weeks[-16:]:
        v = digest_r[w]
        med = statistics.median(abs(x) for x in v.values()) or 0.01
        hits = sorted(((x, t) for t, x in v.items()
                       if abs(x) >= 18 and abs(x) / med >= 2.0),
                      key=lambda z: -abs(z[0]))
        print(f"  {w}  median {med:5.1f}%  {len(hits)}  "
              + ", ".join(f"{t} {x:+.1f}%" for x, t in hits))

    print("\n" + "=" * 78)
    print("5. W32 UNDER BOTH DEFINITIONS")
    print("=" * 78)
    dv, pv = digest_r.get("2026-W32", {}), probe_r.get("2026-W32", {})
    dmed = statistics.median(abs(x) for x in dv.values())
    pmed = statistics.median(abs(x) for x in pv.values())
    print(f"  roster median  digest {dmed:.1f}%   probe {pmed:.1f}%\n")
    print(f"  {'':6}{'digest':>9}{'x':>7}{'fires':>7}   {'probe':>8}{'x':>7}")
    for t in sorted(dv, key=lambda k: -abs(dv[k])):
        d, p = dv[t], pv.get(t, 0)
        f = abs(d) >= 18 and abs(d) / dmed >= 2.0
        print(f"  {t:<6}{d:>+9.1f}{abs(d)/dmed:>7.2f}{'  FIRES' if f else '':>7}"
              f"   {p:>+8.1f}{abs(p)/pmed:>7.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
