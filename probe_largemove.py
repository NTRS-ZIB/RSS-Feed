#!/usr/bin/env python3
"""
Part two: an absolute threshold cannot work, so measure the alternative.

TEMPORARY. Posts nothing, decides nothing.

WHAT PART ONE FOUND, AND WHY IT KILLS THE OBVIOUS DESIGN. Across 53 complete
weeks the count firing at each absolute threshold has a max of 14-17 tickers
of 19 at EVERY candidate from 10% to 25%:

    >=15%  mean 4.7/wk  max 17     >=20%  mean 3.0/wk  max 16
    >=18%  mean 3.5/wk  max 17     >=25%  mean 1.8/wk  max 14

The mean is fine and the max is the firehose. Those maxima are not noise: they
are SECTOR-WIDE WEEKS. When bitcoin moves 30% every miner on the roster moves
with it, and an absolute threshold cannot tell "this company had news" from
"everything moved". **Raising the bar does not fix it** — it empties the
ordinary weeks while the crash weeks still name three quarters of the roster,
which is the worst of both.

So this measures the rule that can separate them: LARGE IN ABSOLUTE TERMS AND
LARGE RELATIVE TO WHAT THE REST OF THE ROSTER DID THAT WEEK. On a sector week
the roster median rises with everything else and the relative test closes; on
an idiosyncratic week it stays low and the mover stands out.

Also measured: whether the price contributor already covers this. It flags a
move against the company's OWN 12-week return SD, which is a different
question — CIFR at -23.0% was routine there because CIFR is always volatile,
and that is exactly the case that motivated the section.
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
WEEKS_LONG = 52


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
    start = (date.today() - timedelta(weeks=WEEKS_LONG + 14)).isoformat()
    bars = fetch(roster, start)

    weekly = defaultdict(dict)
    for sym, rows in bars.items():
        byweek = defaultdict(list)
        for b in rows:
            d = datetime.fromisoformat(b["t"].replace("Z", "+00:00")).date()
            byweek[iso_week(d)].append(b)
        for wk, rs in byweek.items():
            rs.sort(key=lambda x: x["t"])
            if len(rs) < 2:
                continue
            if rs[0]["o"]:
                weekly[wk][sym] = (rs[-1]["c"] - rs[0]["o"]) / rs[0]["o"] * 100

    this = iso_week(date.today())
    weeks = sorted(w for w in weekly if w < this)[-53:]

    print("=" * 78)
    print("1. THE SECTOR WEEKS — what the maxima in part one actually are")
    print("=" * 78)
    rows = []
    for w in weeks:
        v = weekly[w]
        med = statistics.median(abs(x) for x in v.values())
        n20 = sum(1 for x in v.values() if abs(x) >= 20)
        rows.append((n20, med, w, len(v)))
    rows.sort(reverse=True)
    print(f"  {'week':<10}{'n>=20%':>8}{'roster median |ret|':>22}")
    for n20, med, w, n in rows[:8]:
        print(f"  {w:<10}{n20:>8}{med:>21.1f}%")
    print("  ...")
    for n20, med, w, n in rows[-4:]:
        print(f"  {w:<10}{n20:>8}{med:>21.1f}%")
    top = [r for r in rows if r[0] >= 8]
    print(f"\n  The {len(top)} weeks firing >=8 tickers at 20% have a roster "
          f"median |return| of "
          f"{statistics.median([r[1] for r in top]):.1f}% against "
          f"{statistics.median([r[1] for r in rows]):.1f}% overall.")
    print("  A sector week is visible in the roster median, which is what the")
    print("  relative test below keys on.")

    print("\n" + "=" * 78)
    print("2. ABSOLUTE AND RELATIVE TOGETHER")
    print("=" * 78)
    print("  fires when |return| >= ABS and |return| >= REL x the roster's")
    print("  own median |return| that week.\n")
    print(f"  {'rule':<18}{'mean/wk':>9}{'median':>8}{'max':>6}"
          f"{'wks>=1':>8}{'wks>=5':>8}{'total':>7}")
    best = []
    for abs_t in (15, 18, 20):
        for rel in (1.5, 2.0, 2.5):
            per = []
            for w in weeks:
                v = weekly[w]
                med = statistics.median(abs(x) for x in v.values()) or 0.01
                per.append(sum(1 for x in v.values()
                               if abs(x) >= abs_t and abs(x) / med >= rel))
            label = f">={abs_t}% & >={rel}x"
            print(f"  {label:<18}{statistics.mean(per):>9.1f}"
                  f"{statistics.median(per):>8.1f}{max(per):>6}"
                  f"{sum(1 for p in per if p):>8}"
                  f"{sum(1 for p in per if p >= 5):>8}{sum(per):>7}")
            best.append((abs_t, rel, max(per), statistics.mean(per)))

    print("\n" + "=" * 78)
    print("3. THE CANDIDATE ON EVERY WEEK — >=18% and >=2.0x the roster median")
    print("=" * 78)
    for w in weeks[-16:]:
        v = weekly[w]
        med = statistics.median(abs(x) for x in v.values()) or 0.01
        hits = sorted(((x, t) for t, x in v.items()
                       if abs(x) >= 18 and abs(x) / med >= 2.0),
                      key=lambda z: -abs(z[0]))
        print(f"  {w}  roster median {med:5.1f}%  ->  {len(hits)}  "
              + ", ".join(f"{t} {x:+.1f}%" for x, t in hits))

    print("\n" + "=" * 78)
    print("4. DOES THE PRICE CONTRIBUTOR ALREADY COVER IT?")
    print("=" * 78)
    print("  price fires at >=2.0x the company's OWN 12-week return SD.")
    print("  Overlap with the candidate, over the same weeks:\n")
    both = only_lm = only_px = 0
    for w in weeks:
        v = weekly[w]
        med = statistics.median(abs(x) for x in v.values()) or 0.01
        prior = [x for x in weeks if x < w][-12:]
        for t, x in v.items():
            hist = [weekly[p][t] for p in prior if t in weekly[p]]
            if len(hist) < 8:
                continue
            sd = statistics.pstdev(hist) or 0.01
            lm = abs(x) >= 18 and abs(x) / med >= 2.0
            px = abs(x) / sd >= 2.0
            both += lm and px
            only_lm += lm and not px
            only_px += px and not lm
    print(f"  both: {both}   large-move only: {only_lm}   price only: {only_px}")
    print(f"  -> the section adds {only_lm} findings the price contributor")
    print(f"     does not make, and {both} it duplicates.")

    print("\n" + "=" * 78)
    print("5. W32 UNDER THE CANDIDATE")
    print("=" * 78)
    v = weekly.get("2026-W32", {})
    med = statistics.median(abs(x) for x in v.values()) or 0.01
    print(f"  roster median |return| {med:.1f}%")
    for t, x in sorted(v.items(), key=lambda z: -abs(z[1])):
        fires = abs(x) >= 18 and abs(x) / med >= 2.0
        print(f"    {t:<6}{x:+7.1f}%  {abs(x)/med:5.2f}x  "
              f"{'FIRES' if fires else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
