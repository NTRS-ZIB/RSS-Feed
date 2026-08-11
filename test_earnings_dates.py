#!/usr/bin/env python3
"""Tests for earnings_dates. Standalone, stdlib only.

THE ONE THAT MATTERS: a results release is not an announcement. "Reports
Second Quarter 2026 Results" carries a date describing the period covered,
and reading it as a forthcoming report date posts a date already in the
past with no spread and no marker to soften it. That is the failure this
module exists to prevent, so it is tested from both directions: the
recognition stage must not match it, and the guard must reject it if
recognition ever does.
"""

import sys
from datetime import date

import earnings_dates as ed

PASS, FAIL = "PASS", "FAIL"
results = []


def check(name, ok, detail=""):
    results.append((PASS if ok else FAIL, name))
    print(f"  [{PASS if ok else FAIL}] {name}" + (f" — {detail}" if detail else ""))


TODAY = date(2026, 8, 10)

ANNOUNCEMENTS = [
    "Big Digital Energy to Report Second Quarter 2026 Results on August 12, 2026",
    "Cipher Mining Schedules Third Quarter 2026 Earnings Call for November 4, 2026",
    "IREN to Announce Fiscal 2026 Full Year Results on Sept. 7, 2026",
]

NOT_ANNOUNCEMENTS = [
    "American Bitcoin Reports Second Quarter 2026 Results",
    "Galaxy Announces Second Quarter 2026 Financial Results",
    "Bitdeer Announces $4.7 Billion, 16-Year AI/HPC Data Center Lease",
    "Soluna Announces Pricing of $3.507bn Notes Offering",
]


def main():
    print("RECOGNITION")
    for t in ANNOUNCEMENTS:
        check(f"matches: {t[:44]}", ed.looks_like_announcement(t))
    for t in NOT_ANNOUNCEMENTS:
        check(f"rejects: {t[:44]}", not ed.looks_like_announcement(t))

    print("\nDATE PARSING")
    check("full month name",
          ed.parse_date("... on August 12, 2026") == date(2026, 8, 12))
    check("abbreviated month with a full stop",
          ed.parse_date("... on Sept. 7, 2026") == date(2026, 9, 7))
    check("ordinal suffix",
          ed.parse_date("... on November 4th, 2026") == date(2026, 11, 4))
    check("a four-digit year is required",
          ed.parse_date("... to Report Results on August 12") is None,
          "a guessed year is a confident wrong answer")
    check("no date at all",
          ed.parse_date("Announces Date of Second Quarter Earnings Release")
          is None)

    print("\nTHE GUARD")
    when, reason = ed.extract(ANNOUNCEMENTS[0], TODAY)
    check("an announcement ahead of today is accepted",
          when == date(2026, 8, 12) and reason == "ok", f"{when} {reason}")
    when, reason = ed.extract(
        "Company to Report Second Quarter 2026 Results on July 20, 2026", TODAY)
    check("a date before today is rejected",
          when is None and reason == "past", f"{when} {reason}")
    when, reason = ed.extract(
        "Company to Report Second Quarter 2026 Results on August 10, 2026",
        TODAY)
    check("a date of today is accepted",
          when == TODAY and reason == "ok",
          "the calendar's own upcoming test is today <= expected")
    when, reason = ed.extract(NOT_ANNOUNCEMENTS[0], TODAY)
    check("a results release yields nothing",
          when is None and reason == "no-match", f"{when} {reason}")
    when, reason = ed.extract(
        "Announces Date of Second Quarter 2026 Earnings Release", TODAY)
    check("an announcement with no parsable date is counted separately",
          when is None and reason == "no-date", f"{when} {reason}")

    bad = sum(1 for r, _ in results if r == FAIL)
    print(f"\n{len(results) - bad}/{len(results)} checks passed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
