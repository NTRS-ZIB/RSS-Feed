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

    print("\n" + "=" * 78)
    print("5. IS THE SPREAD REAL, OR IS IT ONE OUTLIER AND ONE OUTLIER TICKER?")
    print("=" * 78)

    # ANY is the low extreme at every window, and ANY also carries a real
    # +112% single day inside the 60/90/180 windows. A move that size against
    # 60 observations dominates the covariance on its own, so the question is
    # whether ANY is decoupled or merely disfigured. Rank correlation answers
    # it: Spearman is indifferent to how large the largest move was.
    def spearman(xs, ys):
        pairs = [(a, b) for a, b in zip(xs, ys)
                 if a is not None and b is not None]
        if len(pairs) < 5:
            return None, len(pairs)

        def rank(vals):
            order = sorted(range(len(vals)), key=lambda i: vals[i])
            rk = [0.0] * len(vals)
            i = 0
            while i < len(order):
                j = i
                while j + 1 < len(order) and vals[order[j + 1]] == vals[order[i]]:
                    j += 1
                avg = (i + j) / 2.0 + 1
                for k in range(i, j + 1):
                    rk[order[k]] = avg
                i = j + 1
            return rk
        rx = rank([a for a, _ in pairs])
        ry = rank([b for _, b in pairs])
        return pearson(rx, ry)

    print("\n  Pearson vs Spearman, 90-day window. A large gap means the")
    print("  Pearson number is being set by a handful of outsized days.\n")
    print("    %-6s %10s %10s %8s" % ("", "pearson", "spearman", "diff"))
    for s in symbols:
        if s not in eq:
            continue
        days = sorted(set(eq[s]) & set(btc))[-91:]
        er, br = returns_on(days, eq[s]), returns_on(days, btc)
        p, _ = pearson(er, br)
        sp, _ = spearman(er, br)
        if p is None or sp is None:
            continue
        print("    %-6s %10s %10s %8s" %
              (s, "%+.2f" % p, "%+.2f" % sp, "%+.2f" % (sp - p)))

    # Drop each ticker's single largest absolute move and recompute. If a
    # correlation swings, it was one day's story, not a repricing.
    print("\n  90-day Pearson with each ticker's single largest |return| removed:\n")
    print("    %-6s %10s %10s %8s  %s" %
          ("", "with", "without", "shift", "day dropped"))
    for s in symbols:
        if s not in eq:
            continue
        days = sorted(set(eq[s]) & set(btc))[-91:]
        er, br = returns_on(days, eq[s]), returns_on(days, btc)
        base, _ = pearson(er, br)
        if base is None:
            continue
        idx = max((i for i in range(len(er)) if er[i] is not None),
                  key=lambda i: abs(er[i]))
        er2 = list(er)
        er2[idx] = None
        alt, _ = pearson(er2, br)
        print("    %-6s %10s %10s %8s  %s (%+.0f%%)" %
              (s, "%+.2f" % base, "%+.2f" % alt, "%+.2f" % (alt - base),
               days[idx + 1], er[idx] * 100))

    print("\n" + "=" * 78)
    print("6. THE THESIS COMPARISON, AND WHETHER THE LEVEL OR THE CHANGE CARRIES IT")
    print("=" * 78)
    # Grouping the roster the way the thesis states it, rather than by the
    # extremes the spread happens to land on. Correlating an equal-weight
    # group return against BTC is stronger than averaging the members'
    # correlations: it is one estimate on n observations, not a mean of
    # fourteen noisy ones.
    GROUPS = {
        "BTC proxies (MARA CLSK BKKT)": ["MARA", "CLSK", "BKKT"],
        "AI/HPC pivots (WULF HUT CIFR IREN)": ["WULF", "HUT", "CIFR", "IREN"],
    }
    for w in WINDOWS:
        print("\n  %d-day window" % w)
        for label, members in GROUPS.items():
            days = sorted(set(btc).intersection(*[set(eq[m]) for m in members
                                                  if m in eq]))[-(w + 1):]
            if len(days) < 6:
                continue
            br = returns_on(days, btc)
            per = [returns_on(days, eq[m]) for m in members if m in eq]
            idx_ret = []
            for i in range(len(br)):
                vals = [p[i] for p in per if p[i] is not None]
                idx_ret.append(sum(vals) / len(vals) if vals else None)
            r, n = pearson(idx_ret, br)
            lo, hi = fisher_ci(r, n)
            print("    %-38s %+.2f  [%+.2f..%+.2f]  n=%d" %
                  (label, r, lo, hi, n))

    print("\n  Recent 90 days vs the 90 before that — is anything actually moving?\n")
    print("    %-6s %10s %10s %8s" % ("", "prior 90", "recent 90", "change"))
    for s in symbols:
        if s not in eq:
            continue
        days = sorted(set(eq[s]) & set(btc))
        if len(days) < 185:
            print("    %-6s %10s" % (s, "insufficient history"))
            continue
        recent = days[-91:]
        prior = days[-182:-90]
        rr, _ = pearson(returns_on(recent, eq[s]), returns_on(recent, btc))
        pr, _ = pearson(returns_on(prior, eq[s]), returns_on(prior, btc))
        if rr is None or pr is None:
            continue
        print("    %-6s %10s %10s %8s" %
              (s, "%+.2f" % pr, "%+.2f" % rr, "%+.2f" % (rr - pr)))

    # ------------------------------------------------------------------
    # A second reference series. Thirteen of fourteen falling against BTC
    # at once is equally consistent with "decoupled from bitcoin" and with
    # "recoupled to something else, and the bitcoin number fell as a side
    # effect". One series cannot tell those apart, and they are different
    # claims about what this watchlist is looking at.
    #
    # QQQ and NVDA both: QQQ is the sector without single-name risk, NVDA is
    # the purest AI/HPC proxy available but is one company's news. Keeping
    # both separates "recoupled to tech broadly" from "recoupled to AI
    # infrastructure specifically", and costs one symbol on a request that is
    # already being made.
    # ------------------------------------------------------------------
    REFS = ["QQQ", "NVDA"]
    print("\n" + "=" * 78)
    print("7. A SECOND REFERENCE SERIES")
    print("=" * 78)
    ref_eq, _ = fetch_equities(REFS, LOOKBACK_DAYS)
    if not ref_eq:
        print("  could not fetch reference series")
        return
    refs = {"BTC": btc}
    for rsym in REFS:
        if rsym in ref_eq:
            refs[rsym] = ref_eq[rsym]
            print("  %-5s %4d bars  %s .. %s" %
                  (rsym, len(ref_eq[rsym]), min(ref_eq[rsym]),
                   max(ref_eq[rsym])))

    def aligned(series_list, window):
        """Return-vectors for several series on their common dates."""
        common = sorted(set.intersection(*[set(s) for s in series_list]))
        use = common[-(window + 1):]
        if len(use) < 6:
            return None
        return [returns_on(use, s) for s in series_list], use

    # The confound. If BTC and QQQ moved together over the window, then a
    # fall against one and a rise against the other is a stronger finding
    # than it looks. If they are near-identical, the second series adds
    # nothing and it is better to know that now.
    print("\n  Do the reference series themselves move together?\n")
    names = list(refs)
    print("    %-14s" % "pair" + "".join("%12s" % ("%dd" % w) for w in WINDOWS))
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = names[i], names[j]
            line = "    %-14s" % ("%s vs %s" % (a, b))
            for w in WINDOWS:
                got = aligned([refs[a], refs[b]], w)
                if not got:
                    line += "%12s" % "-"
                    continue
                (ra, rb), _ = got
                r, n = pearson(ra, rb)
                line += "%12s" % ("%+.2f" % r if r is not None else "-")
            print(line)

    print("\n  And over the two halves, the same split as the tickers:\n")
    print("    %-14s %10s %10s %8s" % ("pair", "prior 90", "recent 90", "change"))
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = names[i], names[j]
            common = sorted(set(refs[a]) & set(refs[b]))
            if len(common) < 185:
                continue
            rec, pri = common[-91:], common[-182:-90]
            rr, _ = pearson(returns_on(rec, refs[a]), returns_on(rec, refs[b]))
            pr, _ = pearson(returns_on(pri, refs[a]), returns_on(pri, refs[b]))
            print("    %-14s %10s %10s %8s" %
                  ("%s vs %s" % (a, b), "%+.2f" % pr, "%+.2f" % rr,
                   "%+.2f" % (rr - pr)))

    print("\n" + "=" * 78)
    print("8. DECOUPLED, OR RECOUPLED? PRIOR 90 vs RECENT 90, EVERY REFERENCE")
    print("=" * 78)
    print("  A fall against BTC with a RISE against QQQ/NVDA is rotation.")
    print("  A fall against everything is idiosyncratic risk taking over.\n")
    hdr = "    %-6s" % ""
    for rname in names:
        hdr += "%22s" % rname
    print(hdr)
    print("    %-6s" % "" + "".join("%22s" % "prior  recent  chg"
                                    for _ in names))
    falls = {rname: [] for rname in names}
    for s in symbols:
        if s not in eq:
            continue
        line = "    %-6s" % s
        for rname in names:
            common = sorted(set(eq[s]) & set(refs[rname]))
            if len(common) < 185:
                line += "%22s" % "-"
                continue
            rec, pri = common[-91:], common[-182:-90]
            rr, _ = pearson(returns_on(rec, eq[s]), returns_on(rec, refs[rname]))
            pr, _ = pearson(returns_on(pri, eq[s]), returns_on(pri, refs[rname]))
            if rr is None or pr is None:
                line += "%22s" % "-"
                continue
            falls[rname].append((s, rr - pr))
            line += "%22s" % ("%+.2f  %+.2f  %+.2f" % (pr, rr, rr - pr))
        print(line)
    print()
    for rname in names:
        ch = [c for _, c in falls[rname]]
        if not ch:
            continue
        down = sum(1 for c in ch if c < 0)
        print("    %-5s %2d of %2d fell   mean change %+.2f   median %+.2f"
              % (rname, down, len(ch), sum(ch) / len(ch),
                 sorted(ch)[len(ch) // 2]))

    print("\n" + "=" * 78)
    print("9. SPEARMAN THROUGHOUT? THE ANY PROBLEM AGAINST EVERY REFERENCE")
    print("=" * 78)
    print("  ANY's +112% day is a property of ANY, not of bitcoin, so it")
    print("  recurs against every series. 90-day window.\n")
    print("    %-6s" % "" + "".join("%26s" % rname for rname in names))
    print("    %-6s" % "" + "".join("%26s" % "pears  spear   diff"
                                    for _ in names))
    worst = {rname: (None, 0.0) for rname in names}
    for s in symbols:
        if s not in eq:
            continue
        line = "    %-6s" % s
        for rname in names:
            got = aligned([eq[s], refs[rname]], 90)
            if not got:
                line += "%26s" % "-"
                continue
            (a, b), _ = got
            p, _ = pearson(a, b)
            sp, _ = spearman(a, b)
            if p is None or sp is None:
                line += "%26s" % "-"
                continue
            if abs(sp - p) > abs(worst[rname][1]):
                worst[rname] = (s, sp - p)
            line += "%26s" % ("%+.2f  %+.2f  %+.2f" % (p, sp, sp - p))
        print(line)
    print()
    for rname in names:
        s, d = worst[rname]
        print("    %-5s largest Pearson/Spearman gap: %s %+.2f" % (rname, s, d))

    print("\n" + "=" * 78)
    print("10. DO THE EXTREMES SURVIVE LOSING THE OUTLIER TICKER?")
    print("=" * 78)
    for rname in names:
        print("\n  vs %s" % rname)
        for w in WINDOWS:
            vals = []
            for s in symbols:
                if s not in eq:
                    continue
                got = aligned([eq[s], refs[rname]], w)
                if not got:
                    continue
                (a, b), _ = got
                r, n = pearson(a, b)
                if r is None:
                    continue
                lo, hi = fisher_ci(r, n)
                vals.append((s, r, lo, hi))
            if len(vals) < 3:
                continue
            for label, subset in (("all", vals),
                                  ("ex-ANY", [v for v in vals if v[0] != "ANY"])):
                subset = sorted(subset, key=lambda x: -x[1])
                top, bot = subset[0], subset[-1]
                ov = top[2] <= bot[3]
                print("    %4dd %-7s %s %+.2f [%+.2f..%+.2f]  vs  %s %+.2f "
                      "[%+.2f..%+.2f]  %s"
                      % (w, label, top[0], top[1], top[2], top[3],
                         bot[0], bot[1], bot[2], bot[3],
                         "OVERLAP" if ov else "disjoint"))

    print("\n" + "=" * 78)
    print("11. GROUP COMPARISON AGAINST EVERY REFERENCE")
    print("=" * 78)
    print("  If the pivots carry HIGHER tech correlation than the miners,")
    print("  that is the thesis holding in a form BTC alone cannot show.\n")
    for rname in names:
        print("  vs %s" % rname)
        for w in WINDOWS:
            out = []
            for label, members in GROUPS.items():
                series = [eq[m] for m in members if m in eq] + [refs[rname]]
                got = aligned(series, w)
                if not got:
                    continue
                vecs, _ = got
                br = vecs[-1]
                per = vecs[:-1]
                idx = []
                for i in range(len(br)):
                    v = [p[i] for p in per if p[i] is not None]
                    idx.append(sum(v) / len(v) if v else None)
                r, n = pearson(idx, br)
                lo, hi = fisher_ci(r, n)
                out.append((label, r, lo, hi))
            if len(out) == 2:
                (l1, r1, lo1, hi1), (l2, r2, lo2, hi2) = out
                sep = hi2 < lo1 or hi1 < lo2
                print("    %4dd  proxies %+.2f [%+.2f..%+.2f]   pivots %+.2f "
                      "[%+.2f..%+.2f]   %s"
                      % (w, r1, lo1, hi1, r2, lo2, hi2,
                         "disjoint" if sep else "overlap"))

    print("\n" + "=" * 78)
    print("12. PARTIAL CORRELATION — IS THE BTC NUMBER JUST TECH BETA?")
    print("=" * 78)
    print("  r(ticker,BTC | QQQ) strips out whatever both share with the")
    print("  Nasdaq. If a ticker's BTC correlation collapses once QQQ is")
    print("  controlled for, it was never bitcoin exposure.  90-day window.\n")
    print("    %-6s %9s %9s %11s %11s" %
          ("", "r_BTC", "r_QQQ", "BTC|QQQ", "QQQ|BTC"))
    if "QQQ" in refs:
        for s in symbols:
            if s not in eq:
                continue
            got = aligned([eq[s], refs["BTC"], refs["QQQ"]], 90)
            if not got:
                continue
            (rt, rb, rq), _ = got
            r_tb, _ = pearson(rt, rb)
            r_tq, _ = pearson(rt, rq)
            r_bq, _ = pearson(rb, rq)
            if None in (r_tb, r_tq, r_bq):
                continue
            den1 = math.sqrt((1 - r_tq ** 2) * (1 - r_bq ** 2))
            den2 = math.sqrt((1 - r_tb ** 2) * (1 - r_bq ** 2))
            p_tb = (r_tb - r_tq * r_bq) / den1 if den1 > 0 else float("nan")
            p_tq = (r_tq - r_tb * r_bq) / den2 if den2 > 0 else float("nan")
            print("    %-6s %9s %9s %11s %11s" %
                  (s, "%+.2f" % r_tb, "%+.2f" % r_tq,
                   "%+.2f" % p_tb, "%+.2f" % p_tq))

    # ------------------------------------------------------------------
    # Before any of the above can be called rotation, the mechanical
    # explanation has to be ruled out.
    #
    # Correlation is scale-invariant, so bitcoin simply moving LESS does not
    # by itself reduce anything: multiply every BTC return by 0.5 and every
    # correlation is unchanged. The mechanism only bites through
    #
    #     r = beta * sigma_btc / sigma_ticker
    #
    # so a fall in r comes from a fall in beta, a fall in sigma_btc relative
    # to sigma_ticker, or both. Beta is the discriminating quantity: if beta
    # held while sigma_btc fell, the relationship is intact and bitcoin just
    # moved less — nothing repriced, and "rotation" would be reporting a
    # measurement artefact as a market event.
    # ------------------------------------------------------------------
    ANN = math.sqrt(252)

    def stdev(vals):
        v = [x for x in vals if x is not None]
        if len(v) < 3:
            return None
        m = sum(v) / len(v)
        return math.sqrt(sum((x - m) ** 2 for x in v) / (len(v) - 1))

    def halves(series_a, series_b):
        """(prior, recent) aligned return vectors for two series."""
        common = sorted(set(series_a) & set(series_b))
        if len(common) < 185:
            return None
        rec, pri = common[-91:], common[-182:-90]
        return ((returns_on(pri, series_a), returns_on(pri, series_b)),
                (returns_on(rec, series_a), returns_on(rec, series_b)))

    print("\n" + "=" * 78)
    print("13. REALISED VOLATILITY ACROSS THE TWO HALVES")
    print("=" * 78)
    print("  Annualised stdev of daily returns, %.0f trading days each half.\n"
          % 90)
    print("    %-6s %10s %10s %8s" % ("", "prior 90", "recent 90", "ratio"))
    vol_rows = {}
    for label, ser in list(refs.items()) + [(s, eq[s]) for s in symbols
                                            if s in eq]:
        common = sorted(set(ser) & set(refs["QQQ"]))
        if len(common) < 185:
            continue
        rec, pri = common[-91:], common[-182:-90]
        sp = stdev(returns_on(pri, ser))
        sr = stdev(returns_on(rec, ser))
        if not sp or not sr:
            continue
        vol_rows[label] = (sp * ANN, sr * ANN, sr / sp)
        mark = "  <<<" if label in refs else ""
        print("    %-6s %9.0f%% %9.0f%% %8.2f%s" %
              (label, sp * ANN * 100, sr * ANN * 100, sr / sp, mark))
    roster_ratios = [v[2] for k, v in vol_rows.items() if k not in refs]
    if roster_ratios:
        roster_ratios.sort()
        print("\n    roster median volatility ratio: %.2f" %
              roster_ratios[len(roster_ratios) // 2])
    for r in ("BTC", "QQQ"):
        if r in vol_rows:
            print("    %-5s volatility ratio:              %.2f"
                  % (r, vol_rows[r][2]))

    print("\n" + "=" * 78)
    print("14. BETA vs CORRELATION — WHICH ONE MOVED?")
    print("=" * 78)
    print("  r = beta * sigma_btc / sigma_ticker. If beta held and only the")
    print("  sigma ratio moved, the relationship is intact and the fall in r")
    print("  is mechanical. If beta fell, the relationship weakened.\n")
    print("    %-6s %16s %16s %16s" %
          ("", "corr  pri->rec", "beta  pri->rec", "sig_b/sig_t"))
    beta_changes, corr_changes = [], []
    for s in symbols:
        if s not in eq:
            continue
        h = halves(eq[s], refs["BTC"])
        if not h:
            continue
        (tp, bp), (tr, br) = h
        rp, _ = pearson(tp, bp)
        rr, _ = pearson(tr, br)
        if rp is None or rr is None:
            continue

        def beta(t, b):
            pairs = [(x, y) for x, y in zip(t, b)
                     if x is not None and y is not None]
            mb = sum(y for _, y in pairs) / len(pairs)
            mt = sum(x for x, _ in pairs) / len(pairs)
            vb = sum((y - mb) ** 2 for _, y in pairs)
            cv = sum((x - mt) * (y - mb) for x, y in pairs)
            return cv / vb if vb > 0 else None
        bp_, br_ = beta(tp, bp), beta(tr, br)
        if bp_ is None or br_ is None:
            continue
        sbp, sbr = stdev(bp), stdev(br)
        stp, str_ = stdev(tp), stdev(tr)
        ratio_p = sbp / stp if stp else float("nan")
        ratio_r = sbr / str_ if str_ else float("nan")
        beta_changes.append((s, br_ - bp_, bp_))
        corr_changes.append((s, rr - rp))
        print("    %-6s %16s %16s %16s" %
              (s, "%+.2f -> %+.2f" % (rp, rr),
               "%+.2f -> %+.2f" % (bp_, br_),
               "%.2f -> %.2f" % (ratio_p, ratio_r)))
    if beta_changes:
        drops = [d for _, d, _ in beta_changes if d < 0]
        rel = [d / b for _, d, b in beta_changes if b and abs(b) > 0.05]
        rel.sort()
        print("\n    betas that fell: %d of %d" %
              (len(drops), len(beta_changes)))
        if rel:
            print("    median RELATIVE change in beta: %+.0f%%"
                  % (100 * rel[len(rel) // 2]))
        cc = sorted(d for _, d in corr_changes)
        print("    median change in correlation:   %+.2f" % cc[len(cc) // 2])

    print("\n" + "=" * 78)
    print("15. ARE THE CHANGES BIGGER THAN SAMPLING NOISE?")
    print("=" * 78)
    print("  Fisher z difference across two independent 90-day samples.")
    print("  |dz| > 1.96*sqrt(2/87) = 0.297 to call a change real.\n")

    def z(r):
        return 0.5 * math.log((1 + r) / (1 - r)) if abs(r) < 1 else None
    crit = 1.96 * math.sqrt(2.0 / 87.0)
    print("    %-6s %22s %22s" % ("", "vs BTC", "vs QQQ"))
    print("    %-6s %22s %22s" % ("", "chg    dz    verdict",
                                  "chg    dz    verdict"))
    tally = {"BTC": 0, "QQQ": 0}
    for s in symbols:
        if s not in eq:
            continue
        line = "    %-6s" % s
        for rname in ("BTC", "QQQ"):
            h = halves(eq[s], refs[rname])
            if not h:
                line += "%22s" % "-"
                continue
            (tp, bp), (tr, br) = h
            rp, _ = pearson(tp, bp)
            rr, _ = pearson(tr, br)
            if rp is None or rr is None:
                line += "%22s" % "-"
                continue
            dz = z(rr) - z(rp)
            sig = abs(dz) > crit
            if sig:
                tally[rname] += 1
            line += "%22s" % ("%+.2f %+.2f  %s" %
                              (rr - rp, dz, "REAL" if sig else "noise"))
        print(line)
    print("\n    changes exceeding noise:  BTC %d of 14   QQQ %d of 14"
          % (tally["BTC"], tally["QQQ"]))

    print("\n" + "=" * 78)
    print("16. DO THE PARTIALS SURVIVE, HALF BY HALF?")
    print("=" * 78)
    print("    %-6s %20s %20s" % ("", "BTC|QQQ  pri->rec", "QQQ|BTC  pri->rec"))
    for s in symbols:
        if s not in eq:
            continue
        common = sorted(set(eq[s]) & set(refs["BTC"]) & set(refs["QQQ"]))
        if len(common) < 185:
            continue
        out = []
        for span in (common[-182:-90], common[-91:]):
            rt = returns_on(span, eq[s])
            rb = returns_on(span, refs["BTC"])
            rq = returns_on(span, refs["QQQ"])
            r_tb, _ = pearson(rt, rb)
            r_tq, _ = pearson(rt, rq)
            r_bq, _ = pearson(rb, rq)
            if None in (r_tb, r_tq, r_bq):
                out.append((None, None))
                continue
            d1 = math.sqrt((1 - r_tq ** 2) * (1 - r_bq ** 2))
            d2 = math.sqrt((1 - r_tb ** 2) * (1 - r_bq ** 2))
            out.append(((r_tb - r_tq * r_bq) / d1 if d1 else None,
                        (r_tq - r_tb * r_bq) / d2 if d2 else None))
        if out[0][0] is None or out[1][0] is None:
            continue
        print("    %-6s %20s %20s" %
              (s, "%+.2f -> %+.2f" % (out[0][0], out[1][0]),
               "%+.2f -> %+.2f" % (out[0][1], out[1][1])))


if __name__ == "__main__":
    main()
