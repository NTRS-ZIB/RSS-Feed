#!/usr/bin/env python3
"""
THROWAWAY PROBE — not a component. Delete after use.

Measures three things before a 52-week crossing component is written, because
the last two "cheap" additions both turned out not to be, and both times the
data had properties nobody had measured.

  1. HISTORY DEPTH. daily_recap.py computes its 52w column as closes[-252:]
     from a 430-calendar-day fetch. A ticker with fewer than 252 bars silently
     gets a shorter window — its "52-week" range is really an N-week range and
     nothing says so. WYFI, NUAI and BGDE are already flagged as thin in the
     recap docs.

  2. SPLIT ADJUSTMENT. Bars are requested with adjustment=all, so a reverse
     split should leave the series continuous. ANY split in Feb 2026 and BGDE
     in Nov 2025 — recent enough to sit inside the window. If adjustment has
     failed, the series contains a cliff, and every high and low either side
     of it is meaningless. This looks for the cliff directly.

  3. ALERT RATE. A crossing component is only useful if it fires rarely. The
     recap's own last run put BKKT at 1% of its 52-week range, BGDE at 12 and
     ANY at 14 — several names sitting at or near their lows. A naive rule
     would alert on those daily and be ignored within a week. This counts how
     often a naive rule fires versus one with a hysteresis band, over the
     actual history.

Read-only. Fetches bars, prints, exits. No webhook, no state, no commit.

    ALPACA_KEY_ID=... ALPACA_SECRET_KEY=... python -u probe_52w.py
"""

import os
import sys
from datetime import datetime, timedelta, timezone

import requests

import watchlist

ALPACA_BARS = "https://data.alpaca.markets/v2/stocks/bars"
ALPACA_FEED = "sip"
ALPACA_DELAY_MINUTES = 20
FETCH_DAYS = 430                  # matches daily_recap.py
WINDOW = 252                      # trading days, matches daily_recap.py

# A single-day close-to-close move beyond this is almost certainly an
# unadjusted corporate action rather than a real move. Even in this sector.
CLIFF_PCT = 60.0

# Hysteresis: after a crossing, suppress further alerts in that direction
# until the price returns inside this band of its range.
REARM_LOW, REARM_HIGH = 25.0, 75.0

KEY = os.environ.get("ALPACA_KEY_ID", "").strip()
SECRET = os.environ.get("ALPACA_SECRET_KEY", "").strip()


def fetch(symbols):
    out, token, pages = {}, None, 0
    now = datetime.now(timezone.utc)
    start = (now - timedelta(days=FETCH_DAYS)).date().isoformat()
    end = (now - timedelta(minutes=ALPACA_DELAY_MINUTES)).isoformat(
        timespec="seconds").replace("+00:00", "Z")
    while pages < 6:
        params = {"symbols": ",".join(symbols), "timeframe": "1Day",
                  "start": start, "end": end, "limit": 10000,
                  "feed": ALPACA_FEED, "adjustment": "all"}
        if token:
            params["page_token"] = token
        r = requests.get(ALPACA_BARS, params=params, timeout=(10, 30),
                         headers={"APCA-API-KEY-ID": KEY,
                                  "APCA-API-SECRET-KEY": SECRET})
        if r.status_code != 200:
            sys.exit(f"Alpaca HTTP {r.status_code}: {r.text[:200]}")
        data = r.json()
        for sym, rows in (data.get("bars") or {}).items():
            out.setdefault(sym, []).extend(rows)
        token = data.get("next_page_token")
        pages += 1
        if not token:
            break

    series = {}
    for sym, rows in out.items():
        parsed = []
        for b in rows:
            try:
                parsed.append((
                    datetime.fromisoformat(b["t"].replace("Z", "+00:00")).date(),
                    float(b["c"])))
            except (KeyError, ValueError, TypeError):
                continue
        series[sym] = sorted(parsed)
    return series


def cliffs(rows):
    """Single-day moves large enough to be an unadjusted corporate action."""
    out = []
    for (d0, c0), (d1, c1) in zip(rows, rows[1:]):
        if c0 and abs((c1 - c0) / c0 * 100) >= CLIFF_PCT:
            out.append((d0, c0, d1, c1, (c1 - c0) / c0 * 100))
    return out


def simulate(rows):
    """Count crossings under a naive rule and under hysteresis.

    A crossing is a close beyond the prior WINDOW's extreme, the prior window
    excluding the day itself. Hysteresis arms only once the price has returned
    inside REARM_LOW..REARM_HIGH percent of its range.
    """
    naive_hi = naive_lo = hyst_hi = hyst_lo = 0
    armed_hi = armed_lo = True
    first = None
    for i in range(2, len(rows)):
        window = [c for _, c in rows[max(0, i - WINDOW):i]]
        if len(window) < 20:
            continue
        d, c = rows[i]
        first = first or d
        hi, lo = max(window), min(window)
        rng = hi - lo
        pos = ((c - lo) / rng * 100) if rng else 50.0

        if c > hi:
            naive_hi += 1
            if armed_hi:
                hyst_hi += 1; armed_hi = False
        if c < lo:
            naive_lo += 1
            if armed_lo:
                hyst_lo += 1; armed_lo = False
        if REARM_LOW <= pos <= REARM_HIGH:
            armed_hi = armed_lo = True
    return naive_hi, naive_lo, hyst_hi, hyst_lo, first


def main():
    if not (KEY and SECRET):
        sys.exit("ALPACA_KEY_ID and ALPACA_SECRET_KEY must both be set.")

    tickers = watchlist.tickers()
    print(f"Fetching {FETCH_DAYS} days of daily bars for {len(tickers)} "
          f"tickers, feed={ALPACA_FEED}, adjustment=all\n")
    series = fetch(tickers)

    print("=" * 74)
    print("1. HISTORY DEPTH   (the 52w window is closes[-252:])")
    print("=" * 74)
    print(f"{'':6}{'bars':>6}{'first':>13}{'last':>13}   window actually used")
    print("-" * 74)
    thin = []
    for t in sorted(tickers):
        rows = series.get(t, [])
        if not rows:
            print(f"{t:6}{'0':>6}   NO DATA"); thin.append(t); continue
        n = len(rows)
        used = min(n, WINDOW)
        note = "full 52w" if n >= WINDOW else f"only {used} bars (~{used/21:.0f} months)"
        if n < WINDOW:
            thin.append(t)
        print(f"{t:6}{n:>6}{str(rows[0][0]):>13}{str(rows[-1][0]):>13}   {note}")
    print(f"\n  thin: {', '.join(thin) if thin else 'none — every ticker has a full year'}")

    print("\n" + "=" * 74)
    print(f"2. SPLIT ADJUSTMENT   (single-day moves >= {CLIFF_PCT:.0f}%)")
    print("=" * 74)
    any_cliff = False
    for t in sorted(tickers):
        for d0, c0, d1, c1, pct in cliffs(series.get(t, [])):
            any_cliff = True
            print(f"  {t:6}{d0} {c0:>9.2f}  ->  {d1} {c1:>9.2f}   {pct:+.0f}%")
    if not any_cliff:
        print("  none — adjustment=all appears to be working, including for")
        print("  ANY (split Feb 2026) and BGDE (Nov 2025), both inside the window.")

    print("\n" + "=" * 74)
    print("3. ALERT RATE   (how often would a crossing component fire?)")
    print("=" * 74)
    print(f"{'':6}{'naive hi':>9}{'naive lo':>9}{'hyst hi':>9}{'hyst lo':>9}"
          f"{'days':>7}   naive rate")
    print("-" * 74)
    tot = [0, 0, 0, 0]
    for t in sorted(tickers):
        rows = series.get(t, [])
        if len(rows) < 30:
            continue
        nh, nl, hh, hl, first = simulate(rows)
        days = len(rows)
        tot = [a + b for a, b in zip(tot, (nh, nl, hh, hl))]
        rate = (nh + nl) / days * 100
        print(f"{t:6}{nh:>9}{nl:>9}{hh:>9}{hl:>9}{days:>7}   "
              f"{rate:.0f}% of sessions")
    print("-" * 74)
    print(f"{'ALL':6}{tot[0]:>9}{tot[1]:>9}{tot[2]:>9}{tot[3]:>9}")
    naive, hyst = tot[0] + tot[1], tot[2] + tot[3]
    print(f"\n  naive rule: {naive} alerts across the window")
    print(f"  hysteresis: {hyst} alerts  ({naive - hyst} suppressed, "
          f"{(1 - hyst / naive) * 100:.0f}% quieter)" if naive else "")
    print("\n  WHAT TO LOOK FOR: if the hysteresis count is still more than")
    print("  roughly one alert per ticker per month, the band needs widening")
    print("  or the component is not worth building.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
