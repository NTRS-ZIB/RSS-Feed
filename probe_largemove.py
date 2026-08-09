#!/usr/bin/env python3
"""
Derive a large-move threshold from the distribution, rather than choosing one.

TEMPORARY. Posts nothing, writes nothing, decides nothing.

THE FAILURE TO AVOID IS ALREADY ON RECORD. The persistence rule began as a
single-day test that fired for 12, 8, 9 and 12 tickers of 19 — a section
naming half the roster every week is the firehose the digest exists to filter.
So the question is not "what counts as a big move" but "where does the
distribution separate", and the answer has to be reported as WHAT FIRES ACROSS
EVERY BACKFILL WEEK, not as a percentile.

THE POPULATION MATTERS AND THERE ARE TWO OF THEM. The convergence threshold
was set over 2026-W22..2026-W31, 190 ticker-weeks. That is the comparable
window and it is reported first. But ten weeks is 190 draws for a tail
statistic, so a longer window is measured beside it — and the two are kept
apart rather than pooled, because a number true of one population is not an
answer about the other.

ROSTER MEMBERSHIP IS NOT APPLIED, DELIBERATELY. A ticker-week is included
whenever bars exist, including weeks before a company joined the roster. The
digest re-derives from source and does exactly the same, so measuring the
threshold over roster-only weeks would set it on a different population from
the one it will run against. SPCX simply has no bars before 2026-06.
"""

import os
import statistics
import sys
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

import requests

import watchlist

KEY = os.environ.get("ALPACA_KEY_ID", "").strip()
SECRET = os.environ.get("ALPACA_SECRET_KEY", "").strip()
if not (KEY and SECRET):
    raise SystemExit("ALPACA_KEY_ID / ALPACA_SECRET_KEY not set.")

BARS = "https://data.alpaca.markets/v2/stocks/bars"
FEED = "sip"
WEEKS_LONG = 52
COMPARABLE = [f"2026-W{w}" for w in range(22, 32)]


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
    start = (date.today() - timedelta(weeks=WEEKS_LONG + 2)).isoformat()
    print(f"Fetching {len(roster)} tickers from {start}, feed={FEED}\n")
    bars = fetch(roster, start)

    # weekly return = last close / first open of that ISO week
    weekly = defaultdict(dict)          # week -> ticker -> pct
    for sym, rows in bars.items():
        byweek = defaultdict(list)
        for b in rows:
            d = datetime.fromisoformat(b["t"].replace("Z", "+00:00")).date()
            byweek[iso_week(d)].append(b)
        for wk, rs in byweek.items():
            rs.sort(key=lambda x: x["t"])
            if len(rs) < 2:
                continue            # a one-session week is not a week return
            o, c = rs[0]["o"], rs[-1]["c"]
            if o:
                weekly[wk][sym] = (c - o) / o * 100.0

    this_week = iso_week(date.today())
    complete = sorted(w for w in weekly if w < this_week)
    print(f"{len(complete)} complete ISO weeks, "
          f"{sum(len(v) for w, v in weekly.items() if w in complete)} "
          f"ticker-weeks\n")

    def describe(label, weeks):
        vals = [v for w in weeks for v in weekly.get(w, {}).values()]
        if not vals:
            print(f"  {label}: no data")
            return []
        a = sorted(abs(v) for v in vals)
        s = sorted(vals)
        print(f"  {label}: {len(vals)} ticker-weeks over {len(weeks)} weeks")
        print(f"    signed   p05 {s[len(s)//20]:+6.1f}  p25 {s[len(s)//4]:+6.1f}"
              f"  p50 {statistics.median(s):+6.1f}"
              f"  p75 {s[len(s)*3//4]:+6.1f}  p95 {s[len(s)*19//20]:+6.1f}")
        print(f"    |return| p50 {a[len(a)//2]:5.1f}  p75 {a[len(a)*3//4]:5.1f}"
              f"  p90 {a[int(len(a)*0.90)]:5.1f}  p95 {a[int(len(a)*0.95)]:5.1f}"
              f"  p98 {a[int(len(a)*0.98)]:5.1f}  max {a[-1]:5.1f}")
        return vals

    print("=" * 78)
    print("1. THE DISTRIBUTION, over two populations kept apart")
    print("=" * 78)
    comp = [w for w in COMPARABLE if w in weekly]
    describe("comparable  (W22-W31, the convergence basis)", comp)
    print()
    describe(f"long        (all {len(complete)} complete weeks)", complete)

    print("\n" + "=" * 78)
    print("2. WHAT EACH CANDIDATE FIRES, WEEK BY WEEK")
    print("=" * 78)
    print("The number that decides it. A section naming half the roster is the")
    print("firehose; the persistence rule's rejected version fired 12/19.\n")
    cands = [10, 12, 15, 18, 20, 25]
    print(f"  {'week':<10}{'n':>4}" + "".join(f"{c:>6}%" for c in cands))
    for w in complete[-14:]:
        row = weekly[w]
        print(f"  {w:<10}{len(row):>4}"
              + "".join(f"{sum(1 for v in row.values() if abs(v) >= c):>7}"
                        for c in cands))
    print()
    for label, weeks in (("comparable", comp), ("long", complete)):
        print(f"  {label}:")
        for c in cands:
            per = [sum(1 for v in weekly[w].values() if abs(v) >= c)
                   for w in weeks]
            fired = sum(1 for p in per if p)
            print(f"    >={c:>2}%  mean {statistics.mean(per):4.1f}/wk  "
                  f"median {statistics.median(per):4.1f}  max {max(per):>2}  "
                  f"weeks with >=1: {fired}/{len(weeks)}  "
                  f"weeks naming >=5: {sum(1 for p in per if p >= 5)}")
        print()

    print("=" * 78)
    print("3. SYMMETRY — are down moves rarer than up moves?")
    print("=" * 78)
    for label, weeks in (("comparable", comp), ("long", complete)):
        vals = [v for w in weeks for v in weekly.get(w, {}).values()]
        for c in (15, 18, 20):
            up = sum(1 for v in vals if v >= c)
            dn = sum(1 for v in vals if v <= -c)
            print(f"  {label:<11} >=+{c}%: {up:>3}   <=-{c}%: {dn:>3}"
                  f"   ratio {up / dn if dn else float('inf'):.2f}")
        print()

    print("=" * 78)
    print("4. W32 AGAINST THE CANDIDATES — the week that motivated this")
    print("=" * 78)
    w32 = weekly.get("2026-W32", {})
    for c in cands:
        hits = sorted(((v, t) for t, v in w32.items() if abs(v) >= c),
                      key=lambda x: -abs(x[0]))
        print(f"  >={c}%: {len(hits)} — "
              + ", ".join(f"{t} {v:+.1f}%" for v, t in hits))

    print("\n" + "=" * 78)
    print("5. OVERLAP WITH WHAT ALREADY FIRES — double-counting check")
    print("=" * 78)
    print("A large move on heavy volume through a 52-week high is already")
    print("three market-family contributors. This is how often a large mover")
    print("would ALSO be the week's volume or crossing story.\n")
    # Volume multiple against a 30-session median, same shape the digest uses.
    for c in (15, 18, 20):
        both = tot = 0
        for w in complete:
            for t, v in weekly[w].items():
                if abs(v) < c:
                    continue
                tot += 1
                rows = sorted(bars.get(t, []), key=lambda x: x["t"])
                idx = [i for i, b in enumerate(rows)
                       if iso_week(datetime.fromisoformat(
                           b["t"].replace("Z", "+00:00")).date()) == w]
                if not idx or idx[0] < 30:
                    continue
                base = statistics.median(
                    r["v"] for r in rows[idx[0] - 30:idx[0]])
                peak = max(rows[i]["v"] for i in idx)
                if base and peak / base >= 2.0:
                    both += 1
        print(f"  >={c}%: {both}/{tot} large movers also had a >=2x volume "
              f"session ({both / tot * 100:.0f}%)" if tot else "")
    return 0


if __name__ == "__main__":
    sys.exit(main())
