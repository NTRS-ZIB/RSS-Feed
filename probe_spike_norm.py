#!/usr/bin/env python3
"""
Probe: is volume_spike.py's partial-session understatement worth fixing?

TEMPORARY. Posts nothing, writes nothing, decides nothing.

THE KNOWN FACT, from docs/volume-spikes.md: today's figure sums all hourly bars
for the current Eastern date while the baseline is the mean of thirty COMPLETE
sessions, so every scheduled fire compares a partial session against full ones.
The ratio is understated roughly fivefold at 07:09 ET and very nearly true at
19:18.

THE QUESTION IS NOT WHETHER IT IS WRONG. It is whether fixing it changes what
the component reports. Four measurements:

  1  alert delta   over the last 60 sessions, at every scheduled fire time,
                   the tier the component WOULD have reported against the tier
                   a session-normalised baseline would report. Missed tiers,
                   and tiers caught late.
  2  fetch cost    what the fix would actually cost, which is the measurement
                   most likely to be assumed rather than taken.
  3  profile depth the normalised baseline needs a per-slot mean, and IEX is
                   sparse. A slot with three observations in thirty sessions
                   is not a baseline.
  4  thin days     a normalised ratio divides by a small number early in the
                   session. The current understatement is conservative in the
                   direction that avoids false alerts; the fix removes that.

And the clustering question: if missed alerts land on a few tickers rather than
spreading, the fix helps some companies and does nothing for others, which
changes the argument.

    SPIKE_SESSIONS=60 python -u probe_spike_norm.py

Needs the Alpaca keys. Run it through the workflow.
"""

import os
import statistics
import sys
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

import requests

import watchlist

try:
    from zoneinfo import ZoneInfo
    EASTERN = ZoneInfo("America/New_York")
except Exception:                                               # noqa: BLE001
    EASTERN = timezone(timedelta(hours=-4))

TICKERS = watchlist.tickers()
KEY_ID = os.environ.get("ALPACA_KEY_ID", "").strip()
SECRET = os.environ.get("ALPACA_SECRET_KEY", "").strip()
if not (KEY_ID and SECRET):
    raise SystemExit("ALPACA_KEY_ID / ALPACA_SECRET_KEY are not set.")

DATA = "https://data.alpaca.markets/v2/stocks"
AUTH = {"APCA-API-KEY-ID": KEY_ID, "APCA-API-SECRET-KEY": SECRET}

# volume_spike.py's own constants, imported in spirit rather than restated
# loosely — if these drift the probe stops describing the component.
FEED = "iex"
TIERS = [1.5, 3.0, 5.0, 10.0]
BASELINE_DAYS = 30
MIN_BASELINE_BARS = 10
MIN_BASELINE_VOLUME = 10_000
MIN_ALERT_VOLUME = 25_000

SESSIONS = int(os.environ.get("SPIKE_SESSIONS", "60"))
# Enough calendar days for SESSIONS plus a BASELINE_DAYS run-up.
LOOKBACK_DAYS = int(os.environ.get("SPIKE_LOOKBACK", "150"))
MAX_PAGES = 80

# The schedule, in ET hours. Cron is `9 7-22 * * 1-5` UTC; in EDT that is
# 03:09 to 18:09 ET. The job then polls each quarter hour, but the hour is
# enough to answer the question.
FIRE_HOURS_ET = list(range(3, 19))

# The extended session, matching daily_totals()'s grouping.
OPEN_H, CLOSE_H = 4, 20


def api(path, params):
    r = requests.get(f"{DATA}{path}", headers=AUTH, params=params,
                     timeout=(10, 60))
    r.raise_for_status()
    return r.json()


def fetch_hourly():
    """Every hourly bar, and the cost of getting them."""
    start = (date.today() - timedelta(days=LOOKBACK_DAYS)).isoformat()
    bars, token, pages, t0 = defaultdict(list), None, 0, time.time()
    payload = 0
    while pages < MAX_PAGES:
        params = {"symbols": ",".join(TICKERS), "timeframe": "1Hour",
                  "start": start, "limit": 10000, "feed": FEED,
                  "adjustment": "all"}
        if token:
            params["page_token"] = token
        data = api("/bars", params)
        payload += len(str(data))
        for sym, rows in (data.get("bars") or {}).items():
            bars[sym].extend(rows)
        token = data.get("next_page_token")
        pages += 1
        if not token:
            break
    return bars, pages, time.time() - t0, payload


def slot_table(rows):
    """{ET date: {hour: volume}} — the intraday profile the fix would need."""
    out = defaultdict(lambda: defaultdict(float))
    for b in rows:
        try:
            ts = datetime.fromisoformat(b["t"].replace("Z", "+00:00"))
            v = float(b.get("v") or 0)
        except (KeyError, ValueError, TypeError):
            continue
        et = ts.astimezone(EASTERN)
        out[et.date()][et.hour] += v
    return out


def elapsed_to(day_slots, hour):
    """Volume from the session open through `hour` inclusive."""
    return sum(v for h, v in day_slots.items() if OPEN_H <= h <= hour)


def tier_for(ratio):
    crossed = [t for t in TIERS if ratio >= t]
    return max(crossed) if crossed else None


def main():
    print(f"Fetching {LOOKBACK_DAYS} days of hourly bars, {len(TICKERS)} "
          f"tickers, feed={FEED}...")
    bars, pages, secs, payload = fetch_hourly()
    total_bars = sum(len(v) for v in bars.values())

    print("\n" + "=" * 78)
    print("2. WHAT THE FIX WOULD COST — measured, not assumed")
    print("=" * 78)
    print(f"  {pages} page(s), {total_bars} bar(s), {payload / 1e6:.1f} MB, "
          f"{secs:.1f}s")
    print(f"\n  THE COMPONENT ALREADY FETCHES THIS. volume_spike.hourly_bars()")
    print(f"  requests 1Hour bars over LOOKBACK_DAYS=50 for every ticker, and")
    print(f"  daily_totals() collapses them to daily totals on the next line.")
    print(f"  The intraday profile is fetched and discarded.")
    print(f"\n  So a session-normalised baseline needs NO new request. It is a")
    print(f"  change to how already-fetched data is aggregated. The caching")
    print(f"  and staleness questions do not arise.")

    profile = {t: slot_table(bars.get(t, [])) for t in TICKERS}
    all_days = sorted({d for t in TICKERS for d in profile[t]})
    sessions = all_days[-SESSIONS:] if len(all_days) > SESSIONS else all_days
    print(f"\n  {len(all_days)} ET sessions in the window, "
          f"analysing the last {len(sessions)}")

    # ------------------------------------------------------- 3. density ----
    print("\n" + "=" * 78)
    print("3. PROFILE DEPTH — is there a per-slot baseline at all?")
    print("=" * 78)
    print("  IEX is one venue. A slot with three observations in thirty")
    print("  sessions is not a baseline, and the fix rests on every slot")
    print("  having one.\n")
    print(f"  {'':6}" + "".join(f"{h:>5}" for h in FIRE_HOURS_ET))
    thin_cells = 0
    total_cells = 0
    for t in TICKERS:
        counts = []
        for h in FIRE_HOURS_ET:
            n = sum(1 for d in sessions[-BASELINE_DAYS:]
                    if profile[t].get(d, {}).get(h, 0) > 0)
            counts.append(n)
            total_cells += 1
            if n < MIN_BASELINE_BARS:
                thin_cells += 1
        print(f"  {t:<6}" + "".join(f"{c:>5}" for c in counts))
    print(f"\n  slots with fewer than {MIN_BASELINE_BARS} observations in the "
          f"trailing {BASELINE_DAYS}: {thin_cells}/{total_cells} "
          f"({thin_cells / total_cells * 100:.0f}%)")

    # -------------------------------------------------- 1. alert delta -----
    print("\n" + "=" * 78)
    print("1. ALERT DELTA — what the understatement actually costs")
    print("=" * 78)
    missed = defaultdict(list)      # ticker -> [(day, tier)]
    late = defaultdict(list)        # ticker -> [(day, tier, hours earlier)]
    same = 0
    thin_alerts = []                # normalised fires on tiny absolute volume

    for i, day in enumerate(sessions):
        idx = all_days.index(day)
        prior = all_days[max(0, idx - BASELINE_DAYS):idx]
        if len(prior) < MIN_BASELINE_BARS:
            continue
        for t in TICKERS:
            day_slots = profile[t].get(day)
            if not day_slots:
                continue
            full_base = [sum(profile[t].get(d, {}).values()) for d in prior]
            full_base = [v for v in full_base if v > 0]
            if len(full_base) < MIN_BASELINE_BARS:
                continue
            base_total = statistics.mean(full_base)
            if base_total < MIN_BASELINE_VOLUME:
                continue

            cur_first, norm_first = {}, {}
            for h in FIRE_HOURS_ET:
                vol = elapsed_to(day_slots, h)
                if vol <= 0:
                    continue
                # what the component reports
                cur = vol / base_total
                # session-normalised: elapsed against the same elapsed
                # fraction of each trailing session
                slot_base = [elapsed_to(profile[t].get(d, {}), h)
                             for d in prior]
                slot_base = [v for v in slot_base if v > 0]
                if len(slot_base) < MIN_BASELINE_BARS:
                    continue
                norm = vol / statistics.mean(slot_base)

                if vol >= MIN_ALERT_VOLUME:
                    ct, nt = tier_for(cur), tier_for(norm)
                    if ct and ct not in cur_first:
                        cur_first[ct] = h
                    if nt and nt not in norm_first:
                        norm_first[nt] = h
                        if nt and not ct:
                            thin_alerts.append((t, day, h, vol, norm))

            for tier, nh in norm_first.items():
                ch = cur_first.get(tier)
                if ch is None:
                    missed[t].append((day, tier))
                elif ch > nh:
                    late[t].append((day, tier, ch - nh))
                else:
                    same += 1

    n_missed = sum(len(v) for v in missed.values())
    n_late = sum(len(v) for v in late.values())
    print(f"  over {len(sessions)} sessions and {len(FIRE_HOURS_ET)} fire "
          f"hours per session:\n")
    print(f"    tiers the normalised measure reaches and the current one "
          f"never does : {n_missed}")
    print(f"    tiers both reach, but the current one later               "
          f"       : {n_late}")
    print(f"    tiers both reach at the same hour                         "
          f"       : {same}")
    if late:
        allh = [h for v in late.values() for _d, _t, h in v]
        print(f"\n    when late, how late: median {statistics.median(allh):.0f}"
              f" hours, max {max(allh)}")

    print("\n  CLUSTERING — does this help the roster or three companies?")
    print(f"    {'':6}{'missed':>8}{'late':>8}")
    for t in sorted(TICKERS, key=lambda x: -(len(missed[x]) + len(late[x]))):
        if missed[t] or late[t]:
            print(f"    {t:<6}{len(missed[t]):>8}{len(late[t]):>8}")
    touched = sum(1 for t in TICKERS if missed[t] or late[t])
    print(f"    tickers affected at all: {touched}/{len(TICKERS)}")

    # ----------------------------------------------------- 4. thin days ----
    print("\n" + "=" * 78)
    print("4. THIN DAYS — what the fix would cost in false alerts")
    print("=" * 78)
    print("  Alerts the normalised measure raises that the current one does")
    print("  not, by the absolute volume behind them. The current")
    print("  understatement is conservative in the direction that avoids")
    print("  these; the fix removes that protection.\n")
    if thin_alerts:
        vols = sorted(v for _t, _d, _h, v, _r in thin_alerts)
        print(f"    {len(thin_alerts)} such alerts")
        print(f"    volume behind them: min {vols[0]:,.0f}  "
              f"p50 {statistics.median(vols):,.0f}  max {vols[-1]:,.0f}")
        early = [x for x in thin_alerts if x[2] <= 9]
        print(f"    raised before 10:00 ET: {len(early)}")
        print(f"\n    {'':6}{'date':<12}{'ET':>4}{'volume':>12}{'norm':>8}")
        for t, d, h, v, r in sorted(thin_alerts,
                                    key=lambda x: -x[4])[:12]:
            print(f"    {t:<6}{str(d):<12}{h:>4}{v:>12,.0f}{r:>8.1f}x")
    else:
        print("    none — the normalised measure raised no alert the current"
              " one missed at or above the volume floor")
    return 0


if __name__ == "__main__":
    sys.exit(main())
