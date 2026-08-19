#!/usr/bin/env python3
"""Tests for build_snapshot's projection arithmetic. No network.

`snapshot.json` is a WIRE FORMAT another project reads, rebuilt and pushed
every weekday, and until 2026-08-19 this module had no suite at all. Two of
its published values were wrong and neither errored: BTDR, a 20-F filer with
a December year end, carried `period_end 2026-03-31` — a period it never
reports on — with an `expected` date already a month in the past; and SPCX
carried a quarterly projection built from a single 10-Q.

Both were things `earnings_calendar` already refused, which is the shape
worth naming: two components projecting the same issuers off the same index
and publishing different answers, with only one of them tested.
"""

import os
import subprocess
import sys
from datetime import date

# Refuses to load without it, and fetches nothing at import.
os.environ.setdefault("SEC_USER_AGENT", "offline-suite tests@example.invalid")

import build_snapshot as bs

PASS, FAIL = "PASS", "FAIL"
results = []


def check(name, ok, detail=""):
    results.append((PASS if ok else FAIL, name))
    print(f"  [{PASS if ok else FAIL}] {name}" + (f" - {detail}" if detail else ""))


def rows(*spec):
    """`projection` reads (form, filed, period) out of a five-tuple."""
    return [(f, filed, period, None, None) for f, filed, period in spec]


def annual(*years, form="20-F", lag_days=120):
    out = []
    for y in years:
        p = date(y, 12, 31)
        out.append((form, (p.toordinal() + lag_days and
                           date.fromordinal(p.toordinal() + lag_days)).isoformat(),
                    p.isoformat()))
    return rows(*out)


def quarterly(*periods, lag_days=40):
    out = []
    for p in periods:
        out.append(("10-Q",
                    date.fromordinal(p.toordinal() + lag_days).isoformat(),
                    p.isoformat()))
    return rows(*out)


def main():
    print("AN ANNUAL FILER'S NEXT PERIOD IS TWELVE MONTHS ON")
    # BTDR: 20-F only, December year end. Published against 31 March.
    p = bs.projection(annual(2025, 2024, 2023))
    check("an annual-only filer rolls a YEAR, not a quarter",
          p["period_end"] == "2026-12-31",
          "three months gave 2026-03-31, a period a 20-F filer never reports")
    check("and is labelled annual", p["kind"] == "annual")
    check("its expected date is built from that period",
          p["expected"] > "2026-12-31",
          "the old value, 2026-07-20, was already in the past when published")

    # The roll PRESERVES the fiscal date rather than doing month-end
    # arithmetic, so a non-December year end stays on its own day.
    p = bs.projection(rows(("20-F", "2025-09-28", "2025-06-30"),
                           ("20-F", "2024-09-28", "2024-06-30")))
    check("a non-December annual filer keeps its own fiscal day",
          p["period_end"] == "2026-06-30")

    # 29 February cannot be preserved; the rule steps back to the 28th rather
    # than raising, which is the behaviour earnings_calendar already has.
    check("a 29 February period end does not raise",
          bs.next_annual_period_end(date(2024, 2, 29)) == date(2025, 2, 28))

    print("\nONE FILING IS NOT A CADENCE")
    # SPCX: exactly one 10-Q, and it was published as kind "quarterly",
    # sample 1. earnings_calendar refuses the same company on the same floor.
    one = bs.projection(quarterly(date(2026, 6, 30)))
    check("a single 10-Q does not produce a quarterly projection",
          one["available"] is False and one["period_end"] is None,
          "sample 1 was published as a confident cadence")
    # NOT null, and not a bare absence either. CLAUDE.md: absence is a
    # measurement, reported with a COUNT AGAINST THE FLOOR.
    check("and it says how far short it is",
          one["reason"] == "1/2 quarterly and 0/2 annual filings",
          "a name in a list is an excuse; a count is a measurement")
    two = bs.projection(quarterly(date(2026, 6, 30), date(2026, 3, 31)))
    check("two 10-Qs clear the floor", two is not None
          and two["kind"] == "quarterly")
    check("the floor is earnings_calendar's, imported not restated",
          bs.MIN_QUARTERLY_FILINGS == 2,
          "two components projecting the same issuers must not disagree")

    # Below the floor but WITH annual filings, it projects the annual cycle,
    # which is real. Only a company with neither gets nothing.
    mixed = bs.projection(rows(("10-Q", "2026-08-10", "2026-06-30"),
                               ("10-K", "2026-02-20", "2025-12-31"),
                               ("10-K", "2025-02-20", "2024-12-31")))
    check("one 10-Q beside real annuals still projects the ANNUAL cycle",
          mixed["kind"] == "annual" and mixed["period_end"] == "2026-12-31",
          "a stray quarterly must not set the cycle")
    none = bs.projection(rows(("8-K", "2026-08-01", "2026-08-01")))
    check("a company with no periodic filings at all projects nothing",
          none["available"] is False and none["reason"].startswith("0/2"))

    print("\nTHE QUARTERLY ROLL, WHICH DECEMBER BREAKS")
    # Fixed by 5fc24a1 and left unguarded: the roll is "first of the FOLLOWING
    # month minus a day", so a December period end has to cross the year.
    # Getting it wrong returned 30 November, and most of this roster has a
    # December year end.
    # A SEPTEMBER period end is the one that reaches the year-crossing branch,
    # because the roll LANDS on December. The first version of this check used
    # a December period end, which rolls to March and never touches it —
    # named after the bug and exercising the other path.
    dec = bs.projection(quarterly(date(2026, 9, 30), date(2026, 6, 30),
                                  date(2026, 3, 31)))
    check("a roll that LANDS on December stays in the right year",
          dec["period_end"] == "2026-12-31",
          "the bug returned 2025-12-31, a year early and silently")
    later = bs.projection(quarterly(date(2025, 12, 31), date(2025, 9, 30)))
    check("and a December period end rolls on to March",
          later["period_end"] == "2026-03-31")
    sep = bs.projection(quarterly(date(2026, 6, 30), date(2026, 3, 31)))
    check("an ordinary quarter rolls three months to a month end",
          sep["period_end"] == "2026-09-30")

    print("\nWHEN THE NEXT QUARTER IS THE FISCAL YEAR END")
    # APLD's shape: a quarterly filer whose next period end IS its year end
    # files an annual report, so the projection must switch to ANNUAL lags.
    # This is correct today and is the case most easily broken by the fix
    # above, because it is the other branch.
    apld = bs.projection(rows(
        ("10-Q", "2026-04-10", "2026-02-28"), ("10-Q", "2026-01-09", "2025-11-30"),
        ("10-Q", "2025-10-09", "2025-08-31"), ("10-K", "2025-08-01", "2025-05-31"),
        ("10-K", "2024-08-02", "2024-05-31")))
    check("a quarterly filer whose next period is its FY end reads annual",
          apld["kind"] == "annual" and apld["period_end"] == "2026-05-31")
    check("and uses the annual lag, not the quarterly one",
          apld["median_lag_days"] > 50,
          "annual reports file 60-90 days out, quarterlies around 40")

    print("\nONE PUBLISHED SHAPE, BOTH PATHS")
    a = bs.projection(annual(2025, 2024))
    q = bs.projection(quarterly(date(2026, 6, 30), date(2026, 3, 31)))
    unavail = bs.projection(quarterly(date(2026, 6, 30)))
    check("and the unavailable shape carries them too",
          set(a) - set(unavail) == set(),
          "a strict superset, which is why this can ship without warning")
    check("the annual and quarterly paths publish the same keys",
          set(a) == set(q),
          "a consumer must not find a field that depends on the branch")
    # `in ("low", "normal")` was written here first, which is every possible
    # value and so asserts nothing. Confidence is the field a consumer uses to
    # decide whether to believe the date, so it gets a real boundary.
    # This used to pin `sample: 1` as an intended output, which was the
    # behaviour the published note denied. A single annual filing is now
    # refused, matching cadence() and making that note true.
    lone = bs.projection(rows(("20-F", "2026-04-30", "2025-12-31")))
    check("a single annual filing is refused outright",
          lone["available"] is False,
          "one observation is a period with no lag worth the name")
    check("and every estimate key is still present, so nothing raises",
          all(k in lone for k in ("period_end", "expected", "kind",
                                  "median_lag_days", "spread_days",
                                  "sample", "confidence")),
          "a consumer reading projection['expected'] gets None, not a crash")
    wide = bs.projection(rows(("20-F", "2026-06-30", "2025-12-31"),
                              ("20-F", "2025-03-01", "2024-12-31")))
    check("a wide spread is low confidence too",
          wide["spread_days"] > 30 and wide["confidence"] == "low")
    check("a tight, deep sample is normal",
          bs.projection(annual(2025, 2024, 2023))["confidence"] == "normal")

    # THE BOUNDARY THAT MOVED. `confidence` compares LOW_CONFIDENCE_SPREAD
    # against the RANGE; it used to compare it against `spread_days`, which is
    # half of it, so the effective threshold here was 60 days while the
    # Discord post used 30 and the two published different verdicts about the
    # same issuer. Both cases below read `normal` under the old rule: 31 // 2
    # is 15 and 60 // 2 is 30, and neither exceeds 30.
    def spread_of(days):
        """Two quarterlies whose lags differ by exactly `days`."""
        return bs.projection(rows(
            ("10-Q", date.fromordinal(date(2026, 6, 30).toordinal() + 40).isoformat(),
             "2026-06-30"),
            ("10-Q", date.fromordinal(date(2026, 3, 31).toordinal() + 40 + days).isoformat(),
             "2026-03-31")))

    just_over = spread_of(31)
    check("a range of 31 is low confidence",
          just_over["confidence"] == "low",
          "spread_days is 15 here, so the old rule read this as normal")
    check("and it still publishes HALF the range",
          just_over["spread_days"] == 15,
          "the published figure did not move; only the verdict on it did")
    check("a range of exactly 30 is not low",
          spread_of(30)["confidence"] == "normal",
          "the threshold is exclusive, matching the calendar's ~ marker")
    check("a range of 60 is low here, as it always was in the post",
          spread_of(60)["confidence"] == "low")

    print("\nSTDLIB ONLY, WHICH IS NOT A STYLE PREFERENCE")
    # snapshot.yml has NO pip install step, so a third-party import anywhere in
    # build_snapshot's transitive closure kills the 11:00 UTC run before it
    # reads a filing. tests.yml installs requests, so CI cannot see it — this
    # check is the only thing that can. It caught a real one: importing the
    # shared rule from earnings_calendar, which imports requests at module
    # scope, would have frozen snapshot.json on the values it was correcting.
    probe = "\n".join([
        "import sys, glob, os",
        "LOCAL = {os.path.basename(p)[:-3] for p in glob.glob('*.py')}",
        "class B:",
        "    def find_spec(self, name, path=None, target=None):",
        "        root = name.split('.')[0]",
        "        if root not in sys.stdlib_module_names and root not in LOCAL:",
        "            raise ModuleNotFoundError(name)",
        "        return None",
        "sys.meta_path.insert(0, B())",
        "import build_snapshot, filing_cadence",
        "print('ok')",
    ])
    r = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True,
        cwd=os.path.dirname(os.path.abspath(__file__)) or ".",
        env={**os.environ, "SEC_USER_AGENT": "probe t@example.invalid"})
    check("build_snapshot imports with no third-party module available",
          r.stdout.strip().endswith("ok"),
          (r.stderr.strip().splitlines() or ["?"])[-1][:70])

    print("\nFORM MATCHING")
    # EDGAR prefix semantics, except that 4 would swallow 424. NOT CHECKED:
    # "3 does not match 40-F", which the docstring names but no implementation
    # can get wrong — "40-F" does not start with "3" under any rule, so the
    # check passed under every mutation and asserted nothing.
    check("4 does not match 424", not bs.matches("424B5", "4"))
    check("4 still matches its own amendment", bs.matches("4/A", "4"))
    check("an ordinary family matches by prefix", bs.matches("10-K/A", "10-K"))
    check("and does not match an unrelated form",
          not bs.matches("8-K", "10-K"))

    bad = sum(1 for r, _ in results if r == FAIL)
    print(f"\n{len(results) - bad}/{len(results)} checks passed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
