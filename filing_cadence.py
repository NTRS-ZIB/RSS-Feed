#!/usr/bin/env python3
"""When does this issuer next report, and how confidently can we say so?

WHY THIS EXISTS
`earnings_calendar` and `build_snapshot` both project each issuer's next
report off the same EDGAR filing index, and until 2026-08-19 they were two
implementations giving DIFFERENT ANSWERS about the same companies, every day:

    BTDR   snapshot said period 2026-03-31, a quarter end a 20-F filer never
           reports on, with an `expected` date already a month in the past.
           The calendar had fixed the same bug and names BTDR in its docstring.
    SPCX   snapshot published `quarterly, sample 1` off a single 10-Q. The
           calendar refuses the same company and reports `SPCX 1/2`.
    APLD   snapshot rolled off the newest QUARTERLY period rather than the
           newest periodic filing, so it named as "next" a 10-K filed three
           weeks earlier. Measured: one issuer wrong on 2026-08-19, and about
           TWENTY wrong every February to May, when a December year end's
           10-K has landed and its Q1 10-Q has not. APLD only showed early
           because its fiscal year ends in May.

None of the three errored. `snapshot.json` is a wire format another project
reads every weekday, and it had no test suite at all.

WHAT IS SHARED AND WHAT IS NOT
Only the DECISION is here — which period comes next, when it is expected, and
how much the estimate is worth. Presentation stays in the components, because
they genuinely differ and sharing what differs is how a refactor moves a live
output. Three things were deliberately left OUT of the return value:

- **`spread` is not returned; `lags` is.** `earnings_calendar` reports the
  full range and thresholds it at 30 days; `build_snapshot` publishes half the
  range. Returning one number would either double every `spread_days` in the
  wire format or halve every `±Nd` in the Discord post. The divergence is real
  and is now visible here rather than buried in two files.
- **No vocabulary mapping.** This returns `"quarterly"`. The calendar maps it
  to `"10-Q"` at its own boundary; the snapshot uses it as-is. Both published
  strings are unchanged.
- **No label, name or CIK.** Identity belongs to the caller.

STDLIB ONLY, AND THAT IS LOAD-BEARING. `build_snapshot` imports this, and
`.github/workflows/snapshot.yml` has NO pip install step — five workflows
share that convention. Importing this module from `earnings_calendar` instead
pulled in `requests` transitively and would have killed the 11:00 UTC run with
`ModuleNotFoundError` before it read a single filing, freezing `snapshot.json`
on exactly the values this module exists to correct. The missing pip step is
the only tripwire that catches such an import: `tests.yml` installs `requests`,
so CI is blind to it. Never add a third-party import here.
"""

import statistics
from datetime import date, timedelta

# Periodic report families. A form outside these says nothing about cadence.
ANNUAL_FORMS = {"10-K", "20-F", "40-F"}
QUARTERLY_FORMS = {"10-Q"}
PERIODIC_FORMS = ANNUAL_FORMS | QUARTERLY_FORMS

# How many recent filings the lag median is taken over. Deep enough to survive
# one late filing, shallow enough that a cadence change shows within a year.
LAG_SAMPLE = 8

# Annual periods read when deciding the fiscal year end. Shorter than
# LAG_SAMPLE on purpose: a company that changed its fiscal year should be
# recognised by its recent history, not outvoted by its old one.
FY_MONTH_SAMPLE = 6

# Below this there is no history to project from at all.
MIN_PERIODIC_FILINGS = 2

# A company whose filings never described a quarterly cadence does not get one
# invented. It projects its annual cycle, which is real, and nothing else.
MIN_QUARTERLY_FILINGS = 2

# And an annual cycle needs two observations for the same reason. One filing
# gives a period with no lag worth the name — `build_snapshot` published
# exactly that, as `sample: 1`, with confidence reading "normal".
MIN_ANNUAL_FILINGS = 2


def next_period_end(last_period):
    """The quarter end following `last_period`, preserving the fiscal cycle."""
    month = last_period.month + 3
    year = last_period.year + (month - 1) // 12
    month = (month - 1) % 12 + 1
    # Last day of that month. December has to cross the year — January of
    # year+1, not year — and the case is reached by a SEPTEMBER period end,
    # not a December one, which rolls to March.
    if month == 12:
        return date(year, 12, 31)
    return date(year, month + 1, 1) - timedelta(days=1)


def next_annual_period_end(last_period):
    """Twelve months on, preserving the fiscal date.

    next_period_end() advances three months unconditionally. Using it for an
    annual filer produces a quarter end the company never reports on, which is
    how BTDR came to be projected against 31 March.
    """
    try:
        return last_period.replace(year=last_period.year + 1)
    except ValueError:            # 29 February
        return last_period.replace(year=last_period.year + 1, day=28)


def roll_to_business_day(d):
    """Nobody files on a weekend; push Sat/Sun to the following Monday."""
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def fiscal_year_end_month(annual):
    """Most common month among annual report periods, or None."""
    months = [rd.month for rd, _, _ in annual[:FY_MONTH_SAMPLE]]
    if not months:
        return None
    return max(set(months), key=months.count)


def cadence(filings):
    """The next report and what the estimate is worth, or None.

    `filings` is [(period_end, filed, form)], any order — the period floors
    are taken with max() rather than by position, which is the defect that
    made `build_snapshot` name a 10-K it had already seen as the next report.

    THE ANNUAL AND QUARTERLY LAGS ARE NEVER POOLED. Annual reports file 60 to
    90 days after period end and quarterlies around 40; a pooled median fits
    neither and would be quietly wrong for every issuer.

    Returns None when there is nothing to say, which is a measurement rather
    than a failure: too few filings, or a cadence with too few observations to
    take a median over.
    """
    if len(filings) < MIN_PERIODIC_FILINGS:
        return None

    annual = [f for f in filings if f[2] in ANNUAL_FORMS]
    quarterly = [f for f in filings if f[2] in QUARTERLY_FORMS]
    if not annual and not quarterly:
        return None

    # THE CALLER OWNS THE ORDER, and this must not impose one. LAG_SAMPLE
    # truncates `pool` positionally, so sorting here would change which eight
    # filings the median is taken over — and the two callers order
    # differently: `earnings_calendar` passes EDGAR's `recent` arrays, which
    # run newest-first by FILED date, while `build_snapshot` sorts by PERIOD.
    # An amended filing submitted late for an old period separates the two.
    # Sorting was written here first and would have moved a live Discord
    # output while claiming to be a pure refactor.
    periodic = annual + quarterly

    last_period = max(rd for rd, _, _ in periodic)
    last_filed = max(fd for _, fd, _ in periodic)

    annual_only = len(quarterly) < MIN_QUARTERLY_FILINGS
    if annual_only:
        if len(annual) < MIN_ANNUAL_FILINGS:
            return None
        # The last ANNUAL period, not the last of any filing: a stray 10-Q
        # would otherwise set the cycle this projection is built on.
        upcoming = next_annual_period_end(max(rd for rd, _, _ in annual))
        pool, kind, degraded = annual, "annual", False
        fy_month = fiscal_year_end_month(annual)
    else:
        upcoming = next_period_end(last_period)
        fy_month = fiscal_year_end_month(annual)
        is_annual = fy_month is not None and upcoming.month == fy_month
        pool = annual if is_annual else quarterly
        degraded = False
        if len(pool) < 2:
            # Not enough of the right kind. Fall back to whichever pool can
            # carry a median and SAY SO, rather than publishing a lag taken
            # over one observation as though it were a measurement.
            pool = annual if len(annual) >= 2 else quarterly
            degraded = True
        if len(pool) < 2:
            return None
        kind = ("annual" if (is_annual or (degraded and pool is annual))
                else "quarterly")

    lags = [(fd - rd).days for rd, fd, _ in pool[:LAG_SAMPLE]]
    lag = int(statistics.median(lags))
    return {
        "period": upcoming,
        "expected": roll_to_business_day(upcoming + timedelta(days=lag)),
        "kind": kind,
        "lag": lag,
        "lags": lags,
        "sample": len(lags),
        "degraded": degraded,
        "annual_only": annual_only,
        "fy_month": fy_month,
        "last_period": last_period,
        "last_filed": last_filed,
    }
