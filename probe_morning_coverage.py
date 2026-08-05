#!/usr/bin/env python3
"""Probe: what fraction of the filing morning does an hourly poller actually cover?

TEMPORARY. Delete with .github/workflows/morning-coverage.yml once the question
is answered. Read-only: fetches, simulates, prints, exits.

TWO INPUTS, BOTH MEASURED RATHER THAN ASSUMED

1. When filings actually arrive. EDGAR `acceptanceDateTime` across the roster's
   whole history, which beats reasoning from one morning. NOTE: that field is
   EASTERN despite ending in `Z` — see the trap table in CLAUDE.md. Reading it
   as UTC would shift the entire distribution four or five hours and every
   number below would be wrong in a way nothing announces. The conversion is
   validated against EDGAR's own 06:00-22:00 ET operating hours.

2. When runs actually start. GitHub delays every scheduled run on this repo;
   the morning regime measured 83 to 173 minutes across 14 observations. Those
   14 are BOOTSTRAPPED rather than fitted to a shape nobody measured, and
   sampled PER FIRE rather than averaged — consecutive fires delayed 83 and 173
   put two runs on top of each other and leave the next hour empty, which an
   average would hide.

WHAT IS SIMULATED

Faithful to the loop in monitor.yml: a run passes immediately on start, then on
each wall-clock 15-minute boundary more than MIN_GAP away, until BUDGET_MIN
elapsed from its own start.

Supersession is modelled explicitly, because it decides how many fires ever run
at all. At most one run is in progress and at most one pending; a newer arrival
CANCELS the older pending one. So a configuration that looks dense on paper can
lose half its fires, and a longer budget buys coverage from the runs that do
execute while cancelling more of the ones that would have followed.

COVERAGE IS A LATENCY, NOT A COIN FLIP
The monitor is stateful, so anything missed now is caught by a later pass. The
honest question is how long a filing waits. Reported as the share of filings
seen within 15 minutes — the cadence the design intends — alongside 30 minutes
and the median and p90 waits.
"""

import os
import random
import re
import sys
import time
from bisect import bisect_left
from collections import Counter
from datetime import datetime, timedelta, timezone

import requests

from watchlist import WATCHLIST

UA = os.environ.get("SEC_USER_AGENT", "").strip()
SUBMISSIONS = "https://data.sec.gov/submissions/CIK%s.json"

# The 14 measured morning-regime delays, minutes, from docs/press-monitor.md.
MORNING_DELAYS = [142, 152, 153, 113, 173, 134, 83, 85, 159, 140, 154, 147,
                  132, 116]

MIN_GAP = 3          # minutes; matches the loop's boundary guard
BOUNDARY = 15
TRIALS = 20000
SEED = 20260805

# Candidate configurations: (label, first nominal hour, last hour, minute,
# fires per hour)
STARTS = [7, 8, 9, 10]
BUDGETS = [55, 75, 95, 115]
LAST_HOUR = 23
MINUTE = 7


def eastern_offset(dt_naive):
    """US Eastern UTC offset in hours for a naive local timestamp.

    zoneinfo when tzdata exists; otherwise the second-Sunday-March to
    first-Sunday-November rule, which is what daily_recap.py falls back to.
    """
    try:
        from zoneinfo import ZoneInfo
        return -int(dt_naive.replace(tzinfo=ZoneInfo("America/New_York"))
                    .utcoffset().total_seconds() // 3600)
    except Exception:
        y = dt_naive.year
        mar = datetime(y, 3, 8)
        mar += timedelta(days=(6 - mar.weekday()) % 7)      # 2nd Sunday
        nov = datetime(y, 11, 1)
        nov += timedelta(days=(6 - nov.weekday()) % 7)      # 1st Sunday
        return 4 if mar <= dt_naive < nov else 5


def fetch_acceptance_times():
    """-> list of (utc_dt, raw_et_dt, filing_date, form) per filing."""
    out = []
    for c in WATCHLIST:
        cik = c["cik"].lstrip("0").zfill(10)
        # requests, not urllib: the SEC sends gzip and urllib does not
        # decompress it, which reads as a UnicodeDecodeError rather than as
        # anything to do with encoding. Same headers press_monitor.py sends.
        try:
            r = requests.get(SUBMISSIONS % cik, timeout=(8, 20),
                             headers={"User-Agent": UA,
                                      "Accept-Encoding": "gzip, deflate",
                                      "Host": "data.sec.gov"})
            if r.status_code != 200:
                print("  %-6s HTTP %s" % (c["ticker"], r.status_code))
                continue
            d = r.json()
            time.sleep(0.15)      # under SEC's 10 req/sec ceiling
        except Exception as e:
            print("  %-6s FAILED %s" % (c["ticker"], type(e).__name__))
            continue
        rec = (d.get("filings") or {}).get("recent") or {}
        acc = rec.get("acceptanceDateTime") or []
        forms = rec.get("form") or []
        fdates = rec.get("filingDate") or []
        n = 0
        for i, ts in enumerate(acc):
            if not ts:
                continue
            try:
                naive = datetime.fromisoformat(ts.replace("Z", "")
                                               .replace("+00:00", ""))
            except ValueError:
                continue
            # The raw stamp IS UTC, notwithstanding the trap row in CLAUDE.md
            # which says Eastern. Section 1 tests both readings and the data
            # decides it: a Form 4 stamped 23:00 keeps a same-day filingDate,
            # which is impossible past the 22:00 ET Section 16 cutoff but
            # ordinary at 19:00 ET.
            utc = naive
            out.append((utc.replace(tzinfo=timezone.utc), naive,
                        fdates[i] if i < len(fdates) else None,
                        forms[i] if i < len(forms) else "?"))
            n += 1
        print("  %-6s %4d filings with acceptance times" % (c["ticker"], n))
    return out


def passes_for(start_min, budget):
    """Pass times, in minutes-from-midnight, for a run starting at start_min."""
    out = [start_min]
    t = start_min
    deadline = start_min + budget
    while True:
        nxt = (int(t) // BOUNDARY + 1) * BOUNDARY
        if nxt - t < MIN_GAP:
            nxt += BOUNDARY
        if nxt > deadline:
            break
        out.append(nxt)
        t = nxt
    return out


def simulate(first_hour, budget, per_hour, rng):
    """One day. -> (sorted pass times, fires, cancelled)."""
    nominal = []
    for h in range(first_hour, LAST_HOUR + 1):
        for k in range(per_hour):
            nominal.append(h * 60 + MINUTE + k * (60 // per_hour))
    arrivals = sorted(n + rng.choice(MORNING_DELAYS) for n in nominal)

    passes, cancelled = [], 0
    running_until = None
    pending = None
    i = 0
    while i < len(arrivals) or pending is not None:
        if i < len(arrivals) and (running_until is None
                                  or arrivals[i] < running_until):
            a = arrivals[i]
            i += 1
            if running_until is None or a >= running_until:
                # free: start now
                p = passes_for(a, budget)
                passes.extend(p)
                running_until = p[-1]
            elif pending is None:
                pending = a
            else:
                cancelled += 1          # newer arrival supersedes the older
                pending = a
            continue
        # nothing new arrives before the current run ends
        if pending is not None:
            start = max(pending, running_until)
            p = passes_for(start, budget)
            passes.extend(p)
            running_until = p[-1]
            pending = None
        elif i < len(arrivals):
            running_until = None
        else:
            break
    return sorted(passes), len(arrivals), cancelled


def main():
    if not UA:
        sys.exit("SEC_USER_AGENT not set.")
    rng = random.Random(SEED)

    print("=" * 78)
    print("1. WHEN FILINGS ACTUALLY ARRIVE (EDGAR acceptanceDateTime)")
    print("=" * 78)
    rows = fetch_acceptance_times()
    if not rows:
        sys.exit("No acceptance times.")
    weekday = [r[0] for r in rows if r[0].weekday() < 5]
    print("\n  %d filings total, %d on weekdays" % (len(rows), len(weekday)))
    print("  range %s .. %s" % (min(r[0] for r in rows).date(),
                                max(r[0] for r in rows).date()))

    # VALIDATION. Two earlier attempts were both wrong tests rather than
    # wrong conversions, which is worth recording because each looked
    # conclusive.
    #
    #   1. Converted times against EDGAR's 06:00-22:00 ET window. Those are
    #      DISSEMINATION hours; EDGAR accepts around the clock, so a 23:30 ET
    #      acceptance is ordinary and proves nothing.
    #   2. A flat 17:30 ET cutoff for next-business-day filingDate. Real, but
    #      it does NOT apply to Section 16 forms: Forms 3, 4 and 5 keep a
    #      same-day filingDate until 22:00 ET. Those forms dominate this
    #      corpus, so a flat cutoff mostly measures their exemption.
    #
    # The test below applies the right cutoff per form and runs it against
    # BOTH readings of the raw stamp. Only one can produce a clean split, and
    # a four or five hour error breaks it loudly in the other direction.
    def cutoff_for(form):
        return 22 * 60 if re.sub(r"/A$", "", (form or "")) in ("3", "4", "5")             else 17 * 60 + 30

    print("")
    print("  Next-business-day rule, applied per form (22:00 ET for Sections")
    print("  16 forms 3/4/5, 17:30 ET otherwise), under both readings:")
    for label, shift in (("raw stamp IS Eastern", 0),
                         ("raw stamp is UTC", None)):
        before_same = before_tot = after_next = after_tot = 0
        for utc, naive, fdate, form in rows:
            if not fdate:
                continue
            if shift == 0:
                local, ldate = naive, naive.date()
            else:
                off = eastern_offset(naive)
                local = naive - timedelta(hours=off)
                ldate = local.date()
            mins = local.hour * 60 + local.minute
            same = str(ldate) == fdate
            if mins <= cutoff_for(form):
                before_tot += 1
                before_same += 1 if same else 0
            else:
                after_tot += 1
                after_next += 0 if same else 1
        b = 100.0 * before_same / before_tot if before_tot else 0
        a = 100.0 * after_next / after_tot if after_tot else 0
        print("    %-22s before cutoff same-day %3.0f%% (n=%d)"
              "   after cutoff next-day %3.0f%% (n=%d)"
              % (label, b, before_tot, a, after_tot))
    print("  -> the reading that puts BOTH near 100%% is the correct one.")
    print("")
    print("  Raw stamp samples (as returned by EDGAR):")
    for utc, naive, fdate, form in rows[:4]:
        print("    form %-6s raw %s   filingDate %s" % (form, naive, fdate))

    hours = Counter(t.hour for t in weekday)

    print("\n  by UTC hour:")
    for h in sorted(hours):
        print("    %02d:00  %5d  %s" % (h, hours[h],
                                        "#" * (hours[h] * 60 // max(hours.values()))))

    # The morning is what this is about. Weight coverage by real arrivals.
    # Weight by EVERY weekday filing rather than by an assumed morning. Where
    # the mass actually sits is the finding, and pre-selecting a window would
    # bury it.
    weights = Counter(t.hour * 60 + t.minute for t in weekday)
    cur = 10 * 60 + MINUTE
    inwin = sum(w for m, w in weights.items() if cur <= m < 24 * 60)
    print("")
    print("  %d of %d weekday filings (%.0f%%) land inside the CURRENT"
          % (inwin, len(weekday), 100.0 * inwin / len(weekday)))
    print("  10:07-23:59 UTC cron window; the rest cannot be caught same day.")

    print("\n" + "=" * 78)
    print("2. COVERAGE BY CONFIGURATION")
    print("=" * 78)
    print("  Delay bootstrapped per fire from the 14 measured morning values")
    print("  (%d..%d min, mean %.0f). %d simulated days each."
          % (min(MORNING_DELAYS), max(MORNING_DELAYS),
             sum(MORNING_DELAYS) / len(MORNING_DELAYS), TRIALS))
    print("  Coverage weighted by the real filing-time distribution above.\n")
    print("  %-22s %8s %8s %8s %8s %8s" %
          ("config", "<=15m", "<=30m", "median", "p90", "cancel"))
    print("  " + "-" * 66)

    results = {}
    for per_hour, tag in ((1, ""), (2, " x2/hr")):
        for start in STARTS:
            for budget in BUDGETS:
                if per_hour == 2 and budget not in (55, 95):
                    continue
                lat = []
                fires = canc = 0
                for _ in range(TRIALS):
                    p, f, c = simulate(start, budget, per_hour, rng)
                    fires += f
                    canc += c
                    if not p:
                        continue
                    for minute, w in weights.items():
                        j = bisect_left(p, minute)
                        lat.append((p[j] - minute if j < len(p) else 10000, w))
                tot = sum(w for _, w in lat)
                if not tot:
                    continue
                le15 = sum(w for l, w in lat if l <= 15) / tot
                le30 = sum(w for l, w in lat if l <= 30) / tot
                flat = sorted(lat)
                acc, med, p90 = 0, None, None
                for l, w in flat:
                    acc += w
                    if med is None and acc >= tot * 0.5:
                        med = l
                    if p90 is None and acc >= tot * 0.9:
                        p90 = l
                        break
                label = "%02d:%02d start, %dm%s" % (start, MINUTE, budget, tag)
                results[label] = (le15, le30, med, p90, canc / fires)
                print("  %-22s %7.0f%% %7.0f%% %6dm %6dm %7.0f%%" %
                      (label, le15 * 100, le30 * 100, med,
                       p90 if p90 is not None else -1, 100.0 * canc / fires))

    print("\n" + "=" * 78)
    print("3. WHERE THE HOLES ARE — best config, latency by half hour")
    print("=" * 78)
    best = max(results, key=lambda k: results[k][0])
    print("  %s\n" % best)
    sh = int(best[:2])
    bud = int(best.split(", ")[1].rstrip("m").split("m")[0])
    per = 2 if "x2" in best else 1
    buckets = {}
    for _ in range(2000):
        p, _f, _c = simulate(sh, bud, per, rng)
        for minute, w in weights.items():
            j = bisect_left(p, minute)
            l = p[j] - minute if j < len(p) else 10000
            buckets.setdefault((minute // 30) * 30, []).append((l, w))
    for slot in sorted(buckets):
        vals = buckets[slot]
        tot = sum(w for _, w in vals)
        le15 = sum(w for l, w in vals if l <= 15) / tot
        n_fil = weights_in = sum(w for m, w in weights.items()
                                 if slot <= m < slot + 30)
        print("    %02d:%02d-%02d:%02d  %5.0f%% within 15m   (%d filings)"
              % (slot // 60, slot % 60, (slot + 30) // 60, (slot + 30) % 60,
                 le15 * 100, n_fil))


if __name__ == "__main__":
    main()
