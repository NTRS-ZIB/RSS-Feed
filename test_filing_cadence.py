#!/usr/bin/env python3
"""Tests for filing_cadence, the decision both projection components share.

Until this existed every check on the shared rule was INDIRECT, through one
of two callers, and neither caller can reach all of it: `earnings_calendar`
never sees `kind == "quarterly"` because it maps the string at its boundary,
and `build_snapshot` does not read `degraded` at all. A module two components
depend on and neither fully exercises is where a change goes quiet.

The cases are the real ones. Every defect named below was live in
`snapshot.json` on 2026-08-19 and none of them errored.
"""

import sys
from datetime import date

import filing_cadence as fc

PASS, FAIL = "PASS", "FAIL"
results = []


def check(name, ok, detail=""):
    results.append((PASS if ok else FAIL, name))
    print(f"  [{PASS if ok else FAIL}] {name}" + (f" - {detail}" if detail else ""))


def f(period, filed, form):
    return (date.fromisoformat(period), date.fromisoformat(filed), form)


def qtr(*periods, lag=40):
    """Quarterly filings, newest first, each filed `lag` days after period end."""
    from datetime import timedelta
    out = []
    for p in periods:
        d = date.fromisoformat(p)
        out.append((d, d + timedelta(days=lag), "10-Q"))
    return out


def ann(*periods, lag=90, form="10-K"):
    from datetime import timedelta
    out = []
    for p in periods:
        d = date.fromisoformat(p)
        out.append((d, d + timedelta(days=lag), form))
    return out


def main():
    print("TOO LITTLE HISTORY IS A MEASUREMENT, NOT A FAILURE")
    check("nothing at all", fc.cadence([]) is None)
    check("one filing is below the periodic floor",
          fc.cadence(qtr("2026-06-30")) is None)
    check("two filings of no periodic family project nothing",
          fc.cadence([f("2026-06-30", "2026-07-01", "8-K"),
                      f("2026-03-31", "2026-04-01", "8-K")]) is None)

    print("\nAN ANNUAL-ONLY FILER ROLLS A YEAR")
    # BTDR: 20-F only, December year end, published against 31 March.
    c = fc.cadence(ann("2025-12-31", "2024-12-31", "2023-12-31", form="20-F"))
    check("its next period is twelve months on", c["period"] == date(2026, 12, 31))
    check("it is labelled annual", c["kind"] == "annual")
    check("and flagged annual_only", c["annual_only"] is True)
    check("a single annual filing is refused",
          fc.cadence(ann("2025-12-31", form="20-F")
                     + qtr("2026-06-30")) is None,
          "one observation is a period with no lag worth the name")

    print("\nTHE DEFECT THAT NAMED A FILING IT HAD ALREADY SEEN")
    # APLD: a May year end, so its 10-K period is NEWER than its latest 10-Q.
    # Rolling off the newest QUARTERLY period named as `next` a 10-K filed
    # three weeks earlier. One issuer wrong on 2026-08-19; about twenty every
    # February to May, when a December filer's 10-K has landed and its Q1 has
    # not. The floors are taken with max(), never by position.
    apld = (qtr("2026-02-28", "2025-11-30", "2025-08-31")
            + ann("2026-05-31", "2025-05-31", lag=59))
    c = fc.cadence(apld)
    check("the roll starts from the newest PERIODIC filing",
          c["last_period"] == date(2026, 5, 31),
          "not the newest quarterly, which is 2026-02-28")
    check("so the next period is one it has not reported",
          c["period"] == date(2026, 8, 31))
    # And the same list shuffled must give the same answer, because position
    # must not decide it.
    check("and the answer does not depend on list order",
          fc.cadence(list(reversed(apld)))["period"] == c["period"])

    print("\nTHE CALLER OWNS THE ORDER, BECAUSE LAG_SAMPLE TRUNCATES")
    # Nine quarterlies, the tenth-oldest carrying a wild lag. Which eight
    # enter the median depends on POSITION, so cadence() must not re-sort:
    # earnings_calendar passes EDGAR order (newest by FILED), build_snapshot
    # sorts by period, and an amendment filed late separates the two.
    many = qtr("2026-06-30", "2026-03-31", "2025-12-31", "2025-09-30",
               "2025-06-30", "2025-03-31", "2024-12-31", "2024-09-30")
    outlier = [(date(2024, 6, 30), date(2025, 6, 30), "10-Q")]   # 365-day lag
    check("only the first LAG_SAMPLE filings feed the median",
          fc.cadence(many + outlier)["sample"] == fc.LAG_SAMPLE)
    check("so an outlier past the window is not used at all",
          365 not in fc.cadence(many + outlier)["lags"])
    # Asserted on the LAGS rather than the median: a single outlier in eight
    # does not move a median, so comparing `lag` passed under both orders and
    # showed nothing. The list says which filings were actually read.
    check("but the same outlier FIRST is used",
          365 in fc.cadence(outlier + many)["lags"],
          "which is why sorting here would change a live Discord output")

    print("\nWHEN THE NEXT QUARTER IS THE FISCAL YEAR END")
    # A quarterly filer whose next period end IS its year end files an annual
    # report, so the lag must come from the ANNUAL pool, not the quarterly one.
    fy = qtr("2026-02-28", "2025-11-30", "2025-08-31") + ann("2025-05-31",
                                                             "2024-05-31",
                                                             lag=62)
    c = fc.cadence(fy)
    check("the fiscal year end is read from the annual periods",
          c["fy_month"] == 5)
    check("a next period landing on it reads annual", c["kind"] == "annual")
    check("and the lag comes from the annual pool", c["lag"] == 62,
          "the quarterly lag is 40; a pooled median would fit neither")

    print("\nDEGRADED: THE RIGHT POOL IS TOO THIN, AND IT SAYS SO")
    # Next period is the FY end but only ONE annual filing exists. Falling
    # back silently would publish a lag over one observation as a measurement.
    thin = qtr("2026-02-28", "2025-11-30", "2025-08-31") + ann("2025-05-31",
                                                               lag=62)
    c = fc.cadence(thin)
    check("it falls back to the pool that can carry a median",
          c is not None and c["lag"] == 40)
    check("and flags itself degraded", c["degraded"] is True,
          "a lag from the wrong pool must never read as a clean estimate")
    check("an undegraded projection says so", fc.cadence(fy)["degraded"] is False)
    check("if neither pool has two, it returns None",
          fc.cadence([f("2026-05-31", "2026-08-01", "10-K"),
                      f("2026-02-28", "2026-04-09", "10-Q")]) is None)

    print("\nWHAT IS DELIBERATELY NOT SHARED")
    c = fc.cadence(qtr("2026-06-30", "2026-03-31"))
    check("it returns the raw lags, not a spread",
          "lags" in c and "spread" not in c,
          "the calendar reports the full range, the snapshot half of it")
    check("and says 'quarterly', not '10-Q'", c["kind"] == "quarterly",
          "the calendar maps the vocabulary at its own boundary")
    check("it carries no label, name or cik",
          not {"label", "name", "cik"} & set(c))

    print("\nTHE PERIOD ROLLS")
    check("a quarter rolls three months to a month end",
          fc.next_period_end(date(2026, 6, 30)) == date(2026, 9, 30))
    # Reached by a SEPTEMBER period end, which lands ON December, not by a
    # December one, which rolls to March.
    check("a roll that lands on December stays in the right year",
          fc.next_period_end(date(2026, 9, 30)) == date(2026, 12, 31))
    check("a December period end rolls on to March",
          fc.next_period_end(date(2025, 12, 31)) == date(2026, 3, 31))
    check("February keeps its month end",
          fc.next_period_end(date(2026, 11, 30)) == date(2027, 2, 28))
    check("an annual roll preserves the fiscal date",
          fc.next_annual_period_end(date(2026, 6, 30)) == date(2027, 6, 30))
    check("and steps back from 29 February rather than raising",
          fc.next_annual_period_end(date(2024, 2, 29)) == date(2025, 2, 28))

    print("\nWEEKENDS AND FISCAL MONTHS")
    check("a Saturday expectation moves to Monday",
          fc.roll_to_business_day(date(2026, 8, 22)) == date(2026, 8, 24))
    check("a weekday is left alone",
          fc.roll_to_business_day(date(2026, 8, 20)) == date(2026, 8, 20))
    check("no annual filings means no fiscal month",
          fc.fiscal_year_end_month([]) is None)
    check("the most common month among annual periods wins",
          fc.fiscal_year_end_month(ann("2026-05-31", "2025-05-31",
                                       "2024-12-31")) == 5)
    # Only the recent ones count: a company that changed its fiscal year is
    # recognised by its new one, not outvoted by its history.
    old = ann("2026-05-31", "2025-05-31", "2024-05-31", "2023-05-31",
              "2022-05-31", "2021-05-31", "2020-12-31", "2019-12-31",
              "2018-12-31", "2017-12-31")
    check("older annual periods past FY_MONTH_SAMPLE do not vote",
          fc.fiscal_year_end_month(old) == 5,
          f"the last four are December and there are only {fc.FY_MONTH_SAMPLE} slots")

    bad = sum(1 for r, _ in results if r == FAIL)
    print(f"\n{len(results) - bad}/{len(results)} checks passed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
