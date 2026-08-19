#!/usr/bin/env python3
"""Is the published `±` figure honest, and would a different rule be better?

TEMPORARY it is not. This is the evidence behind a rejection recorded in
`docs/rejected.md`, and a rejection without its numbers is an opinion that
happens to be older than yours.

WHAT IT ANSWERS
`filing_cadence.cadence()` publishes `period_end + int(median(lags))` as the
projected report date, and both components print `floor(range/2)` beside it as
a `±`. Two questions follow, and only measurement separates them:

  1. How often does the next filing actually land inside that interval?
  2. Would `max(lag - min, max - lag)`, the smallest symmetric interval around
     the published lag containing every observed lag, be better?

The answer to (1) is 75.7% at k=8. The answer to (2) is NO, and the way it is
no matters more than the verdict.

COVERAGE CANNOT RANK THESE RULES, AND THAT IS ARITHMETIC RATHER THAN A
FINDING. Every candidate here is symmetric about the same centre, and
`(lag - min) + (max - lag) = range` forces

    medhw  >=  ceil(range/2)  >=  floor(range/2)

pointwise. The intervals NEST, so the miss sets nest, so a wider rule cannot
score worse on any population at any k, ever. Comparing raw coverage reports
the width ordering back in coverage units and settles nothing. Every
comparison below therefore holds WIDTH equal, which is the only way the shape
of a rule can show.

Held at equal mean width the range family wins at every width measured, and a
flat additive constant beats both candidates outright: `floor+2` covers 89.5%
at 11.65d mean where `medhw` covers 87.9% at 14.96d. Same median width, less
mean width, more coverage.

WHY ADDITIVE WINS, which is the part worth keeping: the failures are
concentrated in the metronomic filers. 44% of all misses come from cases
publishing `±0d` to `±2d`, and the `±0d` bucket misses 48% of the time. A
multiplicative rule cannot fix a published zero, because two times zero is
zero. An additive one can.

WHAT THIS IS NOT MEASURING, stated because the percentages read more precise
than they are:

  * COVERAGE IS IN LAG SPACE. The published centre is
    `roll_to_business_day(period_end + lag)`, so for a row that rolls, the
    published window is shifted against the one measured here.
  * k=8 IS NOT EVERY ROW. `cadence` truncates with `pool[:LAG_SAMPLE]`, so the
    live k is `min(8, available)`: on the roster that is 8 for fourteen rows,
    5 for three, 4 for three and 2 for one.
  * THE ANNUAL ARM HOLDS NEITHER 20-F FILER. k>=8 needs nine same-family
    filings and BTDR and IREN hold five each, so the annual coverage figure is
    entirely 10-K filers under a different statutory deadline.
  * THE POPULATION IS EDGAR'S `recent` ARRAYS. `build_snapshot.all_filings`
    reads the full history, which is larger for the five issuers over the
    1,000-filing cap.

None of the four overturns the width-matched ordering, which is internal to
the same population. They do mean the absolute percentages are approximate.

Reads only. Posts nothing, writes nothing, decides nothing.
"""

import json
import os
import statistics as st
import sys
import time
import urllib.request
from datetime import date

import filing_cadence as fc
import watchlist

# URLLIB, NOT REQUESTS, so this stays runnable locally and needs no
# dependency the workflows do not already have. `filing_cadence` is
# stdlib-only for a harder reason; see its docstring.
SUBMISSIONS = "https://data.sec.gov/submissions/CIK%s.json"

# Windows to test. 8 is LAG_SAMPLE; the others say whether the answer is an
# artefact of that choice.
KS = (4, 6, 8, 12)

# Every rule takes the prior window and the published lag, and returns a
# HALF-WIDTH. All are symmetric about the lag, which is what makes them
# comparable and what makes raw coverage useless for ranking them.
RULES = {
    "floor(range/2)": lambda w, lag: (max(w) - min(w)) // 2,
    "ceil(range/2)": lambda w, lag: -(-(max(w) - min(w)) // 2),
    "floor+1": lambda w, lag: (max(w) - min(w)) // 2 + 1,
    "floor+2": lambda w, lag: (max(w) - min(w)) // 2 + 2,
    "medhw": lambda w, lag: max(lag - min(w), max(w) - lag),
    "mad": lambda w, lag: int(st.median([abs(x - lag) for x in w])),
}


def history(cik, ua):
    """Every periodic filing in the index, oldest first, guard applied."""
    req = urllib.request.Request(SUBMISSIONS % cik, headers={"User-Agent": ua})
    data = json.loads(urllib.request.urlopen(req, timeout=30).read())
    recent = (data.get("filings") or {}).get("recent") or {}
    out = []
    for i, form in enumerate(recent.get("form") or []):
        if form not in fc.PERIODIC_FORMS:
            continue
        try:
            rd = date.fromisoformat(recent["reportDate"][i])
            fd = date.fromisoformat(recent["filingDate"][i])
        except (ValueError, IndexError, TypeError):
            continue
        # THE SAME GUARD `cadence` APPLIES. Without it BTDR's transaction 20-F
        # enters, and the cross-section it distorts is the one this probe was
        # written to check.
        if fd >= rd and fc.covers_a_period(rd):
            out.append((fd, rd, form, (fd - rd).days))
    out.sort(key=lambda t: t[0])
    return out


def collect(ua):
    """(window, actual) per k, walking each issuer forward by form family."""
    cases = {k: [] for k in KS}
    for ticker, (cik, _name) in sorted(watchlist.ciks().items()):
        try:
            h = history(cik, ua)
        except Exception as e:                       # noqa: BLE001
            print("  fetch failed %s: %s" % (ticker, e))
            continue
        time.sleep(0.15)                             # SEC asks for under 10/s
        for family in (fc.ANNUAL_FORMS, fc.QUARTERLY_FORMS):
            lags = [x[3] for x in h if x[2] in family]
            for k in KS:
                for i in range(k, len(lags)):
                    cases[k].append((lags[i - k:i], lags[i]))
    return cases


def score(cases, halfwidth):
    ins, widths = 0, []
    for window, actual in cases:
        lag = int(st.median(window))
        hw = halfwidth(window, lag)
        widths.append(hw)
        if lag - hw <= actual <= lag + hw:
            ins += 1
    return (100.0 * ins / len(cases), sum(widths) / len(widths),
            st.median(widths))


def coverage_at_width(cases, base, target):
    """Smallest multiple of `base` reaching `target` mean width, and its
    coverage. This is the comparison that means anything."""
    lo, hi = 0.05, 8.0
    for _ in range(50):
        mid = (lo + hi) / 2
        if score(cases, lambda w, l, c=mid: int(round(c * base(w, l))))[1] < target:
            lo = mid
        else:
            hi = mid
    return score(cases, lambda w, l, c=hi: int(round(c * base(w, l))))


def main():
    ua = os.environ.get("SEC_USER_AGENT", "").strip()
    if not ua:
        raise SystemExit("SEC_USER_AGENT is not set. SEC throttles anonymous "
                         "traffic and rejects a noreply address outright.")
    print("Collecting filing histories...")
    cases = collect(ua)

    print("\nRAW COVERAGE. Read the ordering as width, not as quality:")
    print("%2s %-16s %7s %9s %11s %13s"
          % ("k", "rule", "cases", "coverage", "mean width", "median width"))
    for k in KS:
        for name in RULES:
            cov, mean_w, med_w = score(cases[k], RULES[name])
            print("%2d %-16s %7d %8.1f%% %10.2fd %12.0fd"
                  % (k, name, len(cases[k]), cov, mean_w, med_w))
        print()

    print("COVERAGE AT MATCHED MEAN WIDTH, k=8. THIS is the comparison.")
    base = {"range/2": lambda w, l: (max(w) - min(w)) / 2.0,
            "medhw": lambda w, l: float(max(l - min(w), max(w) - l))}
    print("%11s %16s %16s" % ("mean width", "range/2 scaled", "medhw scaled"))
    for target in (5.0, 7.5, 10.0, 12.5, 15.0, 17.5, 20.0):
        row = "%10.1fd" % target
        for name in ("range/2", "medhw"):
            cov, mean_w, _ = coverage_at_width(cases[8], base[name], target)
            row += " %9.1f%% @%4.1f" % (cov, mean_w)
        print(row)

    print("\nWHERE floor(range/2) ACTUALLY FAILS, k=8.")
    print("A multiplier cannot fix a published zero; an additive constant can.")
    buckets = {}
    for window, actual in cases[8]:
        lag = int(st.median(window))
        hw = RULES["floor(range/2)"](window, lag)
        label = ("0" if hw == 0 else "1-2" if hw <= 2 else "3-5" if hw <= 5
                 else "6-10" if hw <= 10 else "11+")
        b = buckets.setdefault(label, [0, 0])
        b[1] += 1
        if not (lag - hw <= actual <= lag + hw):
            b[0] += 1
    total_missed = sum(v[0] for v in buckets.values())
    print("%-10s %7s %8s %11s %14s"
          % ("published", "cases", "misses", "miss rate", "share of all"))
    for label in ("0", "1-2", "3-5", "6-10", "11+"):
        if label in buckets:
            missed, n = buckets[label]
            print("%-10s %7d %8d %10.0f%% %13.0f%%"
                  % ("+/-" + label + "d", n, missed, 100.0 * missed / n,
                     100.0 * missed / total_missed))


if __name__ == "__main__":
    main()
