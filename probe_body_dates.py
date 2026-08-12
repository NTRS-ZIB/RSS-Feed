#!/usr/bin/env python3
"""Measure what a release body offers, for announcements whose title had none.

WHAT THIS ANSWERS
Twenty of the twenty-six announcements the press monitor recognises carry no
parsable date in the title. Whether a reliable rule could pick the reporting
date out of the body is unknown: a body carries the period covered, the call
date, the replay expiry and often last year's comparative. This fetches every
one of them and prints what a rule would have had to choose between.

WHEN TO RUN IT
- Before writing any rule that reads a date out of a body.
- After changing recognition in earnings_dates.py, since that changes the
  population this measures.

HOW TO READ THE OUTPUT
The rows are grouped by label, and the label is the point. "advance notice"
is a title naming a forthcoming event and nothing else; "scheduled + results"
names an event and reports results in the same breath; "not scheduled" is
neither. If advance notices carry ONE forward date and the others carry
several, the press monitor's scheduled-event gate discriminates and a rule is
possible. If they look alike, the gate is doing nothing and the rule has to
come from somewhere else.

Read-only. Fetches the same sources the monitor already fetches, posts
nothing, writes nothing, and needs no secrets.
"""

import sys
from datetime import datetime, timezone

import earnings_dates as ed
import watchlist


def released_date(item):
    """The date an item was published, or None.

    None is not a fallback: candidate_dates takes it as "no lower bound", so
    an item with no timestamp yields every date in its body rather than only
    the forthcoming ones. That is the honest answer for an item whose release
    date is unknown.
    """
    published = item.get("published")
    if not published:
        return None
    return datetime.fromtimestamp(published, timezone.utc).date()


def undated_announcements(items, today, roster=None):
    """Every roster item that reads as an announcement but yielded no date.

    Mirrors record_disclosed_dates' population exactly — same roster filter,
    same extract() call — so this count can be compared against the
    "N announcement(s) with no parsable date" the monitor logs. A mismatch
    means the two have drifted apart, not that one of them is wrong.
    """
    roster = watchlist.ciks() if roster is None else roster
    out = []
    for item in items:
        if not roster.get(item.get("ticker") or ""):
            continue
        title = item.get("title")
        _when, reason = ed.extract(title, today, released_date(item))
        if reason != "no-date":
            continue
        out.append({
            "ticker": item.get("ticker"),
            "title": title,
            "link": item.get("link"),
            "released": released_date(item),
            "scheduled": ed.names_a_scheduled_event(title),
            "mixed": ed.also_reports_results(title),
        })
    return out
