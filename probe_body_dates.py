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

    The filter and the extract() call match record_disclosed_dates exactly,
    so this count can be compared against the "N announcement(s) with no
    parsable date" the monitor logs. But the source sets differ: the monitor
    scans all_items (EDGAR + IR + insider items), while this reads only
    pm.collect_ir(). EDGAR items get form-derived titles from filing_title()
    and have never matched the announcement shape, with the residual being
    filing_title()'s fallback to SEC's free-text description field — so a
    mismatch on the EDGAR side is that difference showing up, not drift.
    """
    roster = watchlist.ciks() if roster is None else roster
    out = []
    for item in items:
        if not roster.get(item.get("ticker") or ""):
            continue
        title = item.get("title")
        released = released_date(item)
        _when, reason = ed.extract(title, today, released)
        if reason != "no-date":
            continue
        out.append({
            "ticker": item.get("ticker"),
            "title": title,
            "link": item.get("link"),
            "released": released,
            "scheduled": ed.names_a_scheduled_event(title),
            "mixed": ed.also_reports_results(title),
        })
    return out


def probe_rows(rows, fetch):
    """Fetch each selected row's body and attach its candidate dates.

    THERE IS DELIBERATELY NO SCHEDULED-EVENT GATE HERE. press_monitor fetched
    only titles naming a forthcoming event, to keep date-dense results
    releases out of the measurement. Whether that gate actually discriminates
    is the question this probe exists to answer, and a probe that pre-filters
    by the gate can only ever confirm it. Every row is fetched; the labels
    already on the row separate the populations when the output is read.
    """
    for row in rows:
        text = fetch(row["link"])
        row["chars"] = len(text) if text is not None else None
        row["candidates"] = (ed.candidate_dates(text, row["released"])
                             if text is not None else [])
    return rows


BUCKETS = ("one", "several", "none", "failed")

# The only three labels a row can carry, in the same order sorted() used to
# print them. Named once here so summarise() can zero-fill every label up
# front instead of only the ones a row happened to produce, and
# print_summary() can report "no rows selected" rather than guessing.
LABELS = ("advance notice", "not scheduled", "scheduled + results")


def label_of(row):
    """Which population a row belongs to. See HOW TO READ THE OUTPUT."""
    if not row["scheduled"]:
        return "not scheduled"
    return "scheduled + results" if row["mixed"] else "advance notice"


def bucket_of(row):
    """How usable this body's dates are.

    "failed" is separate from "none" on purpose: a source that did not answer
    has told us nothing, while a body carrying no forward date has told us
    the date is not recoverable there. Merging them would let an outage read
    as evidence.
    """
    if row["chars"] is None:
        return "failed"
    n = len(row["candidates"])
    return "none" if n == 0 else ("one" if n == 1 else "several")


def summarise(rows):
    """{label: {bucket: count}}, every label and every bucket present even
    at zero. A label with no rows selected is itself a measurement — see
    the module docstring — so it must appear zeroed rather than be left out
    for print_summary() to rescue or miss."""
    out = {label: dict.fromkeys(BUCKETS, 0) for label in LABELS}
    for row in rows:
        out[label_of(row)][bucket_of(row)] += 1
    return out


def print_rows(rows):
    print("\n" + "=" * 82)
    print("UNDATED ANNOUNCEMENTS  (every one, gate not applied)")
    print("=" * 82)
    print(f"{'ticker':<8}{'released':<12}{'label':<21}{'chars':>7}  candidates")
    print("-" * 82)
    for row in sorted(rows, key=lambda r: (label_of(r), r["ticker"] or "")):
        cands = (", ".join(d.isoformat() for d in row["candidates"])
                 or ("fetch failed" if row["chars"] is None else "none"))
        chars = row['chars'] if row['chars'] is not None else '-'
        print(f"{row['ticker'] or '?':<8}"
              f"{(row['released'].isoformat() if row['released'] else '-'):<12}"
              f"{label_of(row):<21}"
              f"{chars:>7}  {cands}")
        print(f"        {(row['title'] or '')[:74]!r}  {row['link'] or ''}")


def print_summary(summary):
    print("\n" + "=" * 82)
    print("WHAT A RULE WOULD HAVE HAD TO CHOOSE BETWEEN")
    print("=" * 82)
    print(f"{'label':<21}{'one':>6}{'several':>9}{'none':>7}{'failed':>8}")
    print("-" * 82)
    for label in LABELS:
        c = summary[label]
        line = (f"{label:<21}{c['one']:>6}{c['several']:>9}"
                f"{c['none']:>7}{c['failed']:>8}")
        if sum(c.values()) == 0:
            line += "  (no rows selected)"
        print(line)
    notice = summary["advance notice"]
    print("\n  A rule is possible if 'advance notice' is concentrated in 'one'.")
    if sum(notice.values()) == 0:
        print("  No 'advance notice' rows were selected this run — there is "
              "nothing to judge, not zero evidence against a rule.")
    else:
        print(f"  It is: one={notice['one']}, several={notice['several']}, "
              f"none={notice['none']}, failed={notice['failed']}.")


def main():
    # Imported HERE, not at module level. press_monitor imports feedparser,
    # which is not installed in a plain working copy, so a top-level import
    # would make this module and its tests unrunnable outside the runner.
    # Everything above this line is stdlib plus earnings_dates and watchlist.
    import press_monitor as pm

    today = datetime.now(timezone.utc).date()
    items, _feed_ok = pm.collect_ir()
    rows = undated_announcements(items, today)
    print(f"\n{len(items)} item(s) collected, {len(rows)} undated "
          f"announcement(s) selected.")
    if not rows:
        # Not a success. The monitor logs a non-zero no-date count every run,
        # so zero here means the two populations have drifted apart.
        print("  NOTHING SELECTED. Compare against the monitor's "
              "'announcement(s) with no parsable date' count before "
              "concluding there is nothing to measure.")
        return 1
    probe_rows(rows, pm.announcement_body)
    print_rows(rows)
    print_summary(summarise(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
