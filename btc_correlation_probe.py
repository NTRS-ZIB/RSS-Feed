#!/usr/bin/env python3
"""Probe: is a BTC-decoupling measure worth building?

Research tool, not a component. Read-only: fetches price history, prints a
table, exits. No webhook, no state, no commit, no schedule. Delete it with
`.github/workflows/btc-correlation.yml` if the answer turns out to be no.

It answers three questions before any component gets written:

1. Where does the BTC series come from, and does it align with equity days?
   Bitcoin trades every calendar day and equities do not, so a correlation
   computed without an inner join on trading dates would be wrong and would
   look entirely plausible.

2. Does the measure discriminate? A spread — MARA at 0.8 while WULF sits at
   0.3 — is a finding worth reading weekly. Everything inside 0.6-0.75 is a
   column that says the same thing on every row, which is noise with extra
   steps.

3. Is any apparent spread bigger than sampling noise? A correlation from 30
   observations carries roughly +/-0.3 at 95% confidence, so two tickers can
   look far apart and not be. Reported as Fisher-z intervals rather than left
   for the reader to assume.

Correlation is of daily RETURNS, never of prices. Two rising series correlate
near 1.0 whatever their relationship.
"""

import math
import os
import sys
from datetime import datetime, timedelta, timezone

import requests

from watchlist import WATCHLIST

# Alpaca crypto market data needs no authentication — confirmed by request
# with no headers. Same provider and same clock as the equity bars below,
# which is what makes the dates line up.
CRYPTO_BARS = "https://data.alpaca.markets/v1beta3/crypto/us/bars"
STOCK_BARS = "https://data.alpaca.markets/v2/stocks/bars"

ALPACA_KEY_ID = os.environ.get("ALPACA_KEY_ID", "").strip()
ALPACA_SECRET = os.environ.get("ALPACA_SECRET_KEY", "").strip()
# Consolidated feed, matching daily_recap.py. IEX alone gives a wrong close.
FEED = "sip"
DELAY_MINUTES = 20
LOOKBACK_DAYS = 430          # same as the recap, so this reuses proven ground

# Trading-day windows, not calendar days: the window length IS the sample
# size, and that is what the confidence interval depends on.
WINDOWS = [30, 60, 90, 180]

# A reverse split that Alpaca failed to adjust shows up as one enormous
# single-day return. Five of fourteen have done one.
SPLIT_SUSPECT = 0.60


def _get(url, params, headers=None):
    r = requests.get(url, params=params, timeout=(10, 30), headers=headers or {})
    if r.status_code != 200:
        print("  HTTP %s %s" % (r.status_code, r.text[:200]))
        return None
    return r.json()


def fetch_btc(days):
    """Daily BTC/USD closes, keyless. -> {date: close}"""
    now = datetime.now(timezone.utc)
    start = (now - timedelta(days=days)).date().isoformat()
    out, token, pages = {}, None, 0
    raw_t = []
    while pages < 8:
        params = {"symbols": "BTC/USD", "timeframe": "1Day",
                  "start": start, "limit": 10000}
        if token:
            params["page_token"] = token
        d = _get(CRYPTO_BARS, params)
        if d is None:
            return None, []
        for b in (d.get("bars") or {}).get("BTC/USD", []):
            ts = b["t"]
            if len(raw_t) < 3:
                raw_t.append(ts)
            day = datetime.fromisoformat(ts.replace("Z", "+00:00")).date()
            out[day] = float(b["c"])
        token = d.get("next_page_token")
        pages += 1
        if not token:
            break
    return out, raw_t


def fetch_equities(symbols, days):
    """Adjusted daily closes. -> ({symbol: {date: close}}, sample timestamps)"""
    now = datetime.now(timezone.utc)
    start = (now - timedelta(days=days)).date().isoformat()
    end = (now - timedelta(minutes=DELAY_MINUTES)).isoformat(
        timespec="seconds").replace("+00:00", "Z")
    rows, token, pages = {}, None, 0
    raw_t = []
    while pages < 8:
        params = {"symbols": ",".join(symbols), "timeframe": "1Day",
                  "start": start, "end": end, "limit": 10000,
                  "feed": FEED, "adjustment": "all"}
        if token:
            params["page_token"] = token
        d = _get(STOCK_BARS, params,
                 {"APCA-API-KEY-ID": ALPACA_KEY_ID,
                  "APCA-API-SECRET-KEY": ALPACA_SECRET})
        if d is None:
            return None, []
        for sym, bars in (d.get("bars") or {}).items():
            for b in bars:
                ts = b["t"]
                if len(raw_t) < 3:
                    raw_t.append("%s %s" % (sym, ts))
                day = datetime.fromisoformat(ts.replace("Z", "+00:00")).date()
                rows.setdefault(sym, {})[day] = float(b["c"])
        token = d.get("next_page_token")
        pages += 1
        if not token:
            break
    return rows, raw_t


def fetch_raw_closes(symbols, days):
    """Unadjusted closes, to prove the adjustment is actually being applied."""
    now = datetime.now(timezone.utc)
    start = (now - timedelta(days=days)).date().isoformat()
    end = (now - timedelta(minutes=DELAY_MINUTES)).isoformat(
        timespec="seconds").replace("+00:00", "Z")
    rows, token, pages = {}, None, 0
    while pages < 8:
        params = {"symbols": ",".join(symbols), "timeframe": "1Day",
                  "start": start, "end": end, "limit": 10000,
                  "feed": FEED, "adjustment": "raw"}
        if token:
            params["page_token"] = token
        d = _get(STOCK_BARS, params,
                 {"APCA-API-KEY-ID": ALPACA_KEY_ID,
                  "APCA-API-SECRET-KEY": ALPACA_SECRET})
        if d is None:
            return None
        for sym, bars in (d.get("bars") or {}).items():
            for b in bars:
                day = datetime.fromisoformat(
                    b["t"].replace("Z", "+00:00")).date()
                rows.setdefault(sym, {})[day] = float(b["c"])
        token = d.get("next_page_token")
        pages += 1
        if not token:
            break
    return rows


def returns_on(dates, closes):
    """Simple returns between CONSECUTIVE ENTRIES OF `dates`.

    dates must already be the inner join, so a Friday->Monday step is one
    observation and the weekend BTC moves are folded into it. Taking BTC's
    own consecutive-calendar-day returns instead would compare a 1-day equity
    move against a 3-day crypto move every week.
    """
    out = []
    for prev, cur in zip(dates, dates[1:]):
        p0, p1 = closes.get(prev), closes.get(cur)
        if p0 and p1 and p0 > 0:
            out.append(p1 / p0 - 1.0)
        else:
            out.append(None)
    return out


def pearson(xs, ys):
    pairs = [(a, b) for a, b in zip(xs, ys) if a is not None and b is not None]
    n = len(pairs)
    if n < 5:
        return None, n
    mx = sum(a for a, _ in pairs) / n
    my = sum(b for _, b in pairs) / n
    sxy = sum((a - mx) * (b - my) for a, b in pairs)
    sxx = sum((a - mx) ** 2 for a, _ in pairs)
    syy = sum((b - my) ** 2 for _, b in pairs)
    if sxx <= 0 or syy <= 0:
        return None, n
    return sxy / math.sqrt(sxx * syy), n


def fisher_ci(r, n, z=1.96):
    """95% interval via Fisher z. The honest width of a short-window number."""
    if r is None or n < 5 or abs(r) >= 1:
        return None, None
    zr = 0.5 * math.log((1 + r) / (1 - r))
    se = 1.0 / math.sqrt(n - 3)
    lo, hi = zr - z * se, zr + z * se
    return (math.tanh(lo), math.tanh(hi))


def main():
    if not ALPACA_KEY_ID or not ALPACA_SECRET:
        sys.exit("ALPACA_KEY_ID / ALPACA_SECRET_KEY not set.")

    symbols = [c["ticker"] for c in WATCHLIST]
    print("Probing %d tickers against BTC, %d-day lookback.\n" %
          (len(symbols), LOOKBACK_DAYS))

    print("=" * 78)
    print("1. SOURCES AND ALIGNMENT")
    print("=" * 78)

    btc, btc_t = fetch_btc(LOOKBACK_DAYS)
    if not btc:
        sys.exit("No BTC series.")
    print("BTC/USD  (%s, no auth sent)" % CRYPTO_BARS)
    print("  bars: %d   range: %s .. %s" %
          (len(btc), min(btc), max(btc)))
    print("  raw timestamps: %s" % ", ".join(btc_t))

    eq, eq_t = fetch_equities(symbols, LOOKBACK_DAYS)
    if not eq:
        sys.exit("No equity series.")
    print("\nEquities (%s, adjustment=all, feed=%s)" % (STOCK_BARS, FEED))
    print("  raw timestamps: %s" % ", ".join(eq_t))

    # Does BTC carry weekend bars the equities do not have? It must, and the
    # inner join must remove them.
    all_eq_days = set()
    for s in eq:
        all_eq_days |= set(eq[s])
    common = sorted(set(btc) & all_eq_days)
    weekend_btc = [d for d in btc if d.weekday() >= 5]
    print("\n  BTC calendar days:            %d" % len(btc))
    print("  BTC days falling on a weekend: %d" % len(weekend_btc))
    print("  union of equity trading days:  %d" % len(all_eq_days))
    print("  intersection used for returns: %d" % len(common))
    if weekend_btc:
        print("  -> weekends present in BTC and dropped by the join, as required")

    print("\n  per-ticker coverage (bars, first, last):")
    for s in symbols:
        ser = eq.get(s)
        if not ser:
            print("    %-6s NO DATA" % s)
            continue
        print("    %-6s %4d bars  %s .. %s" %
              (s, len(ser), min(ser), max(ser)))

    print("\n" + "=" * 78)
    print("2. SPLIT / ADJUSTMENT CHECK")
    print("=" * 78)
    raw = fetch_raw_closes(symbols, LOOKBACK_DAYS) or {}
    print("Comparing adjustment=all against adjustment=raw, and scanning for")
    print("single-day moves over %.0f%% that would signal an unadjusted split.\n"
          % (SPLIT_SUSPECT * 100))
    for s in symbols:
        ser = eq.get(s)
        if not ser:
            continue
        days = sorted(ser)
        rets = returns_on(days, ser)
        big = [(days[i + 1], r) for i, r in enumerate(rets)
               if r is not None and abs(r) >= SPLIT_SUSPECT]
        r_ser = raw.get(s, {})
        differs = sum(1 for d in days
                      if d in r_ser and abs(r_ser[d] - ser[d]) > 1e-9)
        note = "adjusted on %d of %d days" % (differs, len(days)) if differs \
            else "identical to raw (no adjustment applied)"
        print("  %-6s %-42s" % (s, note), end="")
        if big:
            print("EXTREME: " + ", ".join("%s %+.0f%%" % (d, r * 100)
                                          for d, r in big[:4]))
        else:
            print("no move >= %.0f%%" % (SPLIT_SUSPECT * 100))

    print("\n" + "=" * 78)
    print("3. CORRELATION OF DAILY RETURNS vs BTC")
    print("=" * 78)
    print("Windows are TRADING days (= sample size). Returns are simple,")
    print("computed across the inner-joined dates so weekend BTC moves fold")
    print("into the Friday->Monday step.\n")

    hdr = "  %-6s" % "" + "".join("%18s" % ("%dd" % w) for w in WINDOWS)
    print(hdr)
    print("  " + "-" * (6 + 18 * len(WINDOWS)))
    results = {}
    for s in symbols:
        ser = eq.get(s)
        if not ser:
            print("  %-6s  no data" % s)
            continue
        days = sorted(set(ser) & set(btc))
        line = "  %-6s" % s
        results[s] = {}
        for w in WINDOWS:
            use = days[-(w + 1):]
            if len(use) < 6:
                line += "%18s" % "-"
                results[s][w] = (None, 0, None, None)
                continue
            er = returns_on(use, ser)
            br = returns_on(use, btc)
            r, n = pearson(er, br)
            lo, hi = fisher_ci(r, n)
            results[s][w] = (r, n, lo, hi)
            line += "%18s" % ("%+.2f (n=%d)" % (r, n) if r is not None else "-")
        print(line)

    print("\n  95%% confidence intervals (Fisher z):")
    for s in symbols:
        if s not in results:
            continue
        parts = []
        for w in WINDOWS:
            r, n, lo, hi = results[s][w]
            parts.append("%dd %s" % (w, "%+.2f..%+.2f" % (lo, hi)
                                     if lo is not None else "-"))
        print("    %-6s %s" % (s, "   ".join(parts)))

    print("\n" + "=" * 78)
    print("4. DOES IT DISCRIMINATE?")
    print("=" * 78)
    for w in WINDOWS:
        vals = [(s, results[s][w][0]) for s in results
                if results[s][w][0] is not None]
        if len(vals) < 3:
            continue
        vals.sort(key=lambda x: -x[1])
        rs = [v for _, v in vals]
        spread = max(rs) - min(rs)
        # Do the extremes' intervals overlap? If they do, the spread is not
        # distinguishable from sampling noise at this window length.
        top_s, top_r = vals[0]
        bot_s, bot_r = vals[-1]
        _, _, tlo, thi = results[top_s][w]
        _, _, blo, bhi = results[bot_s][w]
        overlap = (tlo is not None and blo is not None and tlo <= bhi)
        print("\n  %d-day window   n=%d tickers   range %+.2f .. %+.2f   spread %.2f"
              % (w, len(vals), min(rs), max(rs), spread))
        print("    highest: %-6s %+.2f  [%+.2f..%+.2f]" % (top_s, top_r, tlo, thi))
        print("    lowest:  %-6s %+.2f  [%+.2f..%+.2f]" % (bot_s, bot_r, blo, bhi))
        print("    extremes' 95%% intervals %s"
              % ("OVERLAP -> spread not distinguishable from noise"
                 if overlap else
                 "are DISJOINT -> the spread is real at this window"))
        print("    ordered: " + "  ".join("%s %+.2f" % (s, r) for s, r in vals))


if __name__ == "__main__":
    main()
