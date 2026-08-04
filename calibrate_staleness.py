#!/usr/bin/env python3
"""Re-calibrate the staleness thresholds in press_monitor.py against live data.

WHAT THIS ANSWERS
`check_staleness()` fires when a source's newest item is older than
`max(STALE_MULTIPLE x median_gap, STALE_FLOOR_DAYS, override)`. Those two
numbers are not arbitrary and they are not permanent. This measures every
source's real publication cadence and reports what each candidate multiple
would do, so the thresholds can be re-derived rather than re-guessed.

WHEN TO RUN IT
- After adding or removing a source, since the calibration is only as good as
  the population it was measured over.
- When a source is found to have died quietly. That is a new control, and one
  control is thin evidence — see KNOWN_DEAD below.
- If a STALE warning turns out to be a false positive. That means the multiple
  or the floor is too tight, and this shows by how much.

HOW TO READ THE OUTPUT
Every live source is healthy by assumption: they are all currently publishing,
so ANYTHING THAT FIRES IS A FALSE POSITIVE and the multiple is too tight. The
known-dead control must fire, or the detector is not worth having. The usable
window is between the worst healthy ratio and the control's ratio; the chosen
multiple should sit just above the former with room to spare below the latter.

The numbers in press_monitor.py came from this script on 2026-08-03: fourteen
live sources with a worst healthy ratio of 5.0x, one control at 31.8x, and 6x
the tightest multiple with no false positives.

Read-only. Fetches the same feeds the monitor already fetches, posts nothing,
writes nothing, and needs no secrets.
"""

import os
import statistics
import sys
import time
from datetime import datetime, timezone

import press_monitor as pm

# Sources confirmed to have stopped updating while still serving valid content.
# These are the controls: a detector that does not fire on them is useless.
#
# DGXX moved from GlobeNewswire to ACCESS Newswire around 2026-01. This feed
# still returns 20 well-formed items with resolvable ids and correct
# timestamps, none newer than 2025-12-24. It is kept here precisely because it
# has not been fixed and presumably never will be — a permanent control.
KNOWN_DEAD = {
    "DEAD-dgxx-gnw": ("https://www.globenewswire.com/rssfeed/organization/"
                      "zgLApiCrgUf6P184m_M8NA=="),
}

CANDIDATE_MULTIPLES = (2, 3, 4, 5, 6, 8, 10, 12)


def cadence(times):
    """(items, distinct days, median gap, newest age, ratio) for one source.

    Same-day items are collapsed, exactly as check_staleness() does. Three
    releases in one morning are one publication event; their zero-day gaps drag
    the median down until an ordinary quiet spell looks like a failure.
    """
    times = [t for t in times if t]
    if not times:
        return None
    days = sorted({datetime.fromtimestamp(t, timezone.utc).date()
                   for t in times}, reverse=True)
    age = (time.time() - max(times)) / 86400
    if len(days) < 2:
        return (len(times), len(days), None, age, None)
    gaps = [(days[i] - days[i + 1]).days for i in range(len(days) - 1)]
    med = statistics.median(gaps)
    return (len(times), len(days), med, age, (age / med) if med else None)


def raw_median(times):
    """Median gap WITHOUT collapsing same-day items, to show why we collapse."""
    ts = sorted((t for t in times if t), reverse=True)
    if len(ts) < 2:
        return None
    return statistics.median((ts[i] - ts[i + 1]) / 86400
                             for i in range(len(ts) - 1))


def gather():
    """Every source the monitor reads, plus the known-dead controls."""
    out = []
    for label, url in pm.IR_FEEDS.items():
        entries = pm.parse_feed(url)
        out.append((label, "feed", [pm.entry_time(e) for e in entries]))
    out.append(("HUT", "scrape", [i["published"] for i in pm.scrape_hut8()]))
    out.append(("DGXX", "cms", [i["published"] for i in pm.read_dgxx()]))
    for label, url in KNOWN_DEAD.items():
        entries = pm.parse_feed(url)
        out.append((label, "control", [pm.entry_time(e) for e in entries]))
    return out


def main():
    rows = [(label, kind, times, cadence(times)) for label, kind, times in gather()]

    print("\n" + "=" * 82)
    print("CADENCE  (same-day items collapsed, as check_staleness does)")
    print("=" * 82)
    print(f"{'source':<16}{'kind':<9}{'items':>6}{'days':>6}{'median':>8}"
          f"{'newest':>9}{'ratio':>8}")
    print("-" * 82)
    for label, kind, _, c in rows:
        if not c:
            print(f"{label:<16}{kind:<9}  no usable timestamps")
            continue
        n, d, med, age, ratio = c
        print(f"{label:<16}{kind:<9}{n:>6}{d:>6}"
              f"{(f'{med:.0f}d' if med is not None else '-'):>8}"
              f"{age:>8.0f}d"
              f"{(f'{ratio:.1f}x' if ratio is not None else '-'):>8}")

    live = [(l, c) for l, k, _, c in rows if k != "control" and c and c[4]]
    dead = [(l, c) for l, k, _, c in rows if k == "control" and c and c[4]]

    print("\n" + "=" * 82)
    print("WHAT EACH MULTIPLE WOULD DO")
    print("=" * 82)
    print("  Every live source is publishing, so anything that fires is a")
    print("  FALSE POSITIVE. Every control must fire.\n")
    for k in CANDIDATE_MULTIPLES:
        fp = [l for l, c in live if c[4] > k]
        missed = [l for l, c in dead if c[4] <= k]
        verdict = "OK" if not fp and not missed else "no"
        print(f"  x{k:<3} {verdict:<4} false positives: "
              f"{', '.join(fp) if fp else 'none':<34}"
              f"controls missed: {', '.join(missed) if missed else 'none'}")

    if live and dead:
        worst = max(live, key=lambda t: t[1][4])
        best_dead = min(dead, key=lambda t: t[1][4])
        print(f"\n  usable window: {worst[1][4]:.1f}x ({worst[0]}) "
              f".. {best_dead[1][4]:.1f}x ({best_dead[0]})")

    print("\n" + "=" * 82)
    print("WHY SAME-DAY COLLAPSING IS LOAD-BEARING")
    print("=" * 82)
    print(f"  {'source':<16}{'raw median':>12}{'collapsed':>12}")
    print("  " + "-" * 40)
    for label, _, times, c in rows:
        if not c or c[2] is None:
            continue
        raw = raw_median(times)
        if raw is None:
            continue
        mark = "  <-- differs" if abs(raw - c[2]) >= 1 else ""
        print(f"  {label:<16}{raw:>11.1f}d{c[2]:>11.0f}d{mark}")

    print("\n" + "=" * 82)
    print("EFFECTIVE THRESHOLD PER SOURCE, AT THE CONFIGURED SETTINGS")
    print("=" * 82)
    print(f"  STALE_MULTIPLE={pm.STALE_MULTIPLE}  "
          f"STALE_FLOOR_DAYS={pm.STALE_FLOOR_DAYS}  "
          f"STALE_MIN_DAYS={pm.STALE_MIN_DAYS}\n")
    for label, kind, _, c in rows:
        if not c or c[2] is None:
            continue
        override = pm.DGXX_STALE_DAYS if label == "DGXX" else 0
        horizon = max(pm.STALE_MULTIPLE * c[2], pm.STALE_FLOOR_DAYS, override)
        state = "WOULD FIRE" if c[3] > horizon else ""
        print(f"  {label:<16}fires after {horizon:>5.0f}d   "
              f"(newest {c[3]:.0f}d) {state}")

    thin = [l for l, _, _, c in rows if c and c[1] < pm.STALE_MIN_DAYS]
    print(f"\n  below STALE_MIN_DAYS ({pm.STALE_MIN_DAYS} distinct days): "
          f"{', '.join(thin) if thin else 'none'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
