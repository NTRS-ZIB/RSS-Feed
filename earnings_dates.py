#!/usr/bin/env python3
"""Disclosed reporting dates: extraction, storage and lookup.

The earnings calendar PROJECTS when a company will report, from its own filing
history. Once the company announces a date, the projection is strictly worse
information. This module is how the announced date reaches the calendar.

WHAT IS NOT TRUSTED IS OUR READING OF A HEADLINE, NOT THE COMPANY. The single
guard is that an extracted date cannot be in the past, which is a definition
rather than a suspicion: a forthcoming report date never is. That one test
kills both a results release misread as an announcement and a stale feed item
re-read as new, which are the two failures that actually happen here.

There is deliberately NO plausibility window, because the constant would have
no derivation, and NO period test on extraction, because that lets our own
arithmetic veto a correct announcement — and our arithmetic is known wrong for
foreign private issuers.

Stdlib only, no network. Safe to run directly:  python earnings_dates.py
"""

import json
import re
from datetime import date
from pathlib import Path

SCHEMA = 1
DEFAULT_PATH = Path("earnings_dates.json")

# BOTH are required, and that is the whole recognition stage. A verb alone
# matches operational releases; a results word alone matches the results
# release itself, which is the case that would store a date already past.
ANNOUNCE_VERBS = ("to report", "to announce", "to release", "announces date",
                  "announces the date", "schedules", "sets date")
RESULTS_WORDS = ("results", "earnings")

MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
          "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}

# Month name (abbreviated or full, optional full stop), day, optional ordinal
# suffix, optional comma, four-digit year. The year is not optional: see
# parse_date.
DATE_RE = re.compile(
    r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+"
    r"(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b", re.I)


def looks_like_announcement(title):
    """Does this title look like an advance notice of a reporting date?"""
    t = (title or "").lower()
    return (any(v in t for v in ANNOUNCE_VERBS)
            and any(w in t for w in RESULTS_WORDS))


def parse_date(title):
    """The first month-day-year in the title, or None.

    A FOUR-DIGIT YEAR IS REQUIRED. "on August 12" with no year would have to
    be guessed at, and the guess is wrong every time a release crosses a year
    boundary. Titles like that are counted as misses instead, and the count is
    what decides whether reading release bodies is worth building.
    """
    m = DATE_RE.search(title or "")
    if not m:
        return None
    try:
        return date(int(m.group(3)), MONTHS[m.group(1)[:3].lower()],
                    int(m.group(2)))
    except (KeyError, ValueError):
        return None


def extract(title, today):
    """(date, reason) for one item title.

    reason is "no-match", "no-date", "past" or "ok". The caller counts them
    separately: "no-date" is the informative miss, "no-match" is every
    unrelated release on the roster and means nothing on its own.
    """
    if not looks_like_announcement(title):
        return None, "no-match"
    when = parse_date(title)
    if when is None:
        return None, "no-date"
    if when < today:
        return None, "past"
    return when, "ok"
