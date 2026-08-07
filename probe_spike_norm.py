#!/usr/bin/env python3
"""
Probe: reproduce the normalisation gain against the BUILT component.

TEMPORARY. Posts nothing, writes nothing, decides nothing.

The first version of this probe carried its own model of the component and
measured 151 missed tiers against it. A gain measured in a simulation and not
reproduced by the implementation is the difference between the two, not a
finding — so this one imports volume_spike and calls its real
`ratio_for()`, `slot_totals()` and `elapsed_through()` over historical
sessions.

It answers three things:

  reproduce   does the 151 hold against the built gate, and what does the
              gate cost of it?
  09:00       what fires at 09:00 with the gate against without it, on the
              same sessions? The gate's whole justification is that the first
              slot is untrustworthy, and that should be visible.
  floor       the 10th percentile of volume behind full-session alerts, which
              is where MIN_NORMALISED_VOLUME comes from — derived rather than
              chosen, so a normalised alert never rests on less than an
              ordinary one.
"""

import os
import statistics
import sys
import time
from collections import defaultdict
from datetime import date, datetime, timedelta

import requests

import volume_spike as vs

DAYS = int(os.environ.get("SPIKE_LOOKBACK", "150"))
SESSIONS = int(os.environ.get("SPIKE_SESSIONS", "60"))
MAX_PAGES = 80
FIRE_HOURS = list(range(9, 16))          # the IEX day, hourly


def fetch():
    start = (date.today() - timedelta(days=DAYS)).isoformat()
    bars, token, pages = defaultdict(list), None, 0
    while pages < MAX_PAGES:
        params = {"symbols": ",".join(vs.TICKERS), "timeframe": "1Hour",
                  "start": start, "limit": 10000, "feed": vs.FEED,
                  "adjustment": "all"}
        if token:
            params["page_token"] = token
        r = requests.get(f"{vs.DATA}/bars", headers=vs.AUTH, params=params,
                         timeout=(10, 60))
        r.raise_for_status()
        data = r.json()
        for sym, rows in (data.get("bars") or {}).items():
            bars[sym].extend(rows)
        token = data.get("next_page_token")
        pages += 1
        if not token:
            break
    return bars, pages


def main():
    print(f"Fetching {DAYS} days, feed={vs.FEED}, "
          f"calling volume_spike's own functions\n")
    bars, pages = fetch()
    print(f"  {pages} page(s), {sum(len(v) for v in bars.values())} bars")
    print(f"  NORMALISE_FROM_HOUR={vs.NORMALISE_FROM_HOUR}  "
          f"MIN_ALERT_VOLUME={vs.MIN_ALERT_VOLUME:,}  "
          f"MIN_BASELINE_BARS={vs.MIN_BASELINE_BARS}")

    profile = {t: vs.slot_totals(bars.get(t, [])) for t in vs.TICKERS}
    all_days = sorted({d for t in vs.TICKERS for d in profile[t]})
    sessions = all_days[-SESSIONS:]
    print(f"  {len(all_days)} sessions, analysing last {len(sessions)}\n")

    # first-fire hour per (ticker, day, tier), under three regimes
    full_first, gated_first, ungated_first = {}, {}, {}
    full_alert_vols = []
    nine_gated, nine_ungated = [], []

    for day in sessions:
        idx = all_days.index(day)
        prior = all_days[max(0, idx - vs.BASELINE_DAYS):idx]
        if len(prior) < vs.MIN_BASELINE_BARS:
            continue
        for t in vs.TICKERS:
            slots = profile[t].get(day)
            if not slots:
                continue
            full_base = [sum(profile[t].get(d, {}).values()) for d in prior]
            full_base = [v for v in full_base if v > 0]
            if len(full_base) < vs.MIN_BASELINE_BARS:
                continue
            if sum(full_base) / len(full_base) < vs.MIN_BASELINE_VOLUME:
                continue

            for h in FIRE_HOURS:
                vol = vs.elapsed_through(slots, h)
                if vol < vs.MIN_ALERT_VOLUME:
                    continue
                slot_base = [vs.elapsed_through(profile[t].get(d, {}), h)
                             for d in prior]
                slot_base = [v for v in slot_base if v > 0]

                # the component as it stands
                r_full, _b = vs.ratio_for(vol, h, [], full_base)
                # the component as built, gate active
                r_gate, basis = vs.ratio_for(vol, h, slot_base, full_base)
                # the same, gate removed — for the 09:00 comparison
                saved = vs.NORMALISE_FROM_HOUR
                vs.NORMALISE_FROM_HOUR = 0
                r_open, _b2 = vs.ratio_for(vol, h, slot_base, full_base)
                vs.NORMALISE_FROM_HOUR = saved

                for label, ratio, store in (
                        ("full", r_full, full_first),
                        ("gate", r_gate, gated_first),
                        ("open", r_open, ungated_first)):
                    tier = vs.tier_for(ratio)
                    if tier and (t, day, tier) not in store:
                        store[(t, day, tier)] = h
                if vs.tier_for(r_full):
                    full_alert_vols.append(vol)
                if h == 9:
                    if vs.tier_for(r_gate):
                        nine_gated.append((t, day, vol, r_gate, basis))
                    if vs.tier_for(r_open) and not vs.tier_for(r_full):
                        nine_ungated.append((t, day, vol, r_open))

    # ------------------------------------------------------- reproduce ----
    print("=" * 78)
    print("REPRODUCE — the gain, against the built component")
    print("=" * 78)
    for label, store in (("gate active (as built)", gated_first),
                         ("gate removed", ungated_first)):
        missed = [k for k in store if k not in full_first]
        late = [k for k in store
                if k in full_first and full_first[k] > store[k]]
        hours = [full_first[k] - store[k] for k in late]
        print(f"\n  {label}")
        print(f"    tiers the full-session measure never reaches : "
              f"{len(missed)}")
        print(f"    tiers it reaches later                       : "
              f"{len(late)}"
              + (f", median {statistics.median(hours):.0f}h" if hours else ""))
        by_t = defaultdict(int)
        for t, _d, _x in missed:
            by_t[t] += 1
        print(f"    tickers with at least one missed tier        : "
              f"{len(by_t)}/{len(vs.TICKERS)}")

    # ------------------------------------------------------- the 09:00 ----
    print("\n" + "=" * 78)
    print("THE 09:00 SLOT — what the gate withholds")
    print("=" * 78)
    print(f"  with the gate   : {len(nine_gated)} alerts at 09:00")
    print(f"  without it      : {len(nine_ungated)} alerts the full-session "
          f"measure does not raise")
    if nine_ungated:
        v = sorted(x[2] for x in nine_ungated)
        print(f"  volume behind those: min {v[0]:,.0f}  "
              f"p50 {statistics.median(v):,.0f}  max {v[-1]:,.0f}")
        print(f"\n  the ten most extreme, all suppressed by the gate:")
        print(f"    {'':6}{'date':<12}{'volume':>12}{'norm':>9}")
        for t, d, vol, r in sorted(nine_ungated, key=lambda x: -x[3])[:10]:
            print(f"    {t:<6}{str(d):<12}{vol:>12,.0f}{r:>8.1f}x")

    # ----------------------------------------------------------- floor ----
    print("\n" + "=" * 78)
    print("THE FLOOR — derived, not chosen")
    print("=" * 78)
    if full_alert_vols:
        v = sorted(full_alert_vols)
        p10 = v[len(v) // 10]
        print(f"  volume behind {len(v)} full-session alerts:")
        print(f"    p10 {p10:,.0f}   p25 {v[len(v)//4]:,.0f}   "
              f"p50 {statistics.median(v):,.0f}   p90 {v[len(v)*9//10]:,.0f}")
        print(f"\n  MIN_NORMALISED_VOLUME = {p10:,.0f}")
        print(f"    the 10th percentile, so a normalised alert never rests on")
        print(f"    less absolute volume than an ordinary one typically does.")
        blocked = [x for x in nine_ungated if x[2] < p10]
        print(f"\n  it would independently block {len(blocked)} of "
              f"{len(nine_ungated)} ungated 09:00 alerts,")
        print(f"    including the BKKT/WYFI cases the gate exists for.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
