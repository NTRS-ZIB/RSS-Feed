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
import sys
from datetime import date
from pathlib import Path

SCHEMA = 1
DEFAULT_PATH = Path("earnings_dates.json")

# BOTH are required, and that is the whole recognition stage. A verb alone
# matches operational releases; a results word alone matches the results
# release itself, which is the case that would store a date already past.

# Bare "announces" is deliberate and it widens this. BTDR's real advance
# notice — "Bitdeer Announces Second Quarter 2026 Earnings Conference Call for
# August 10th 2026" — was missed for nine days because the list carried
# "announces date" and not "announces", and the date was in the title the
# whole time.
#
# It also makes a results release recognisable, and that is safe rather than
# accidental: THE DATE GUARD IS THE REAL FILTER and recognition is the cheap
# first pass. "Galaxy Announces Second Quarter 2026 Financial Results" carries
# no date, so it is a no-date miss; one that carried a date would carry a past
# one and be rejected.
ANNOUNCE_VERBS = ("to report", "to announce", "to release", "announces",
                  "schedules", "sets date")
RESULTS_WORDS = ("results", "earnings")

# Words that name a FORTHCOMING EVENT. An advance notice schedules something;
# a results release reports something. probe_body_dates.py is the only
# production caller, where this is a pure label applied to every selected
# row rather than a gate on what gets fetched — so a phrasing missing from
# this list does not skip a sample, it misfiles that row into "not scheduled"
# inside the very table built to decide whether this list discriminates.
SCHEDULED_EVENT_WORDS = ("conference call", "webcast", "call for",
                         "schedules", "to be held", "will host")


def names_a_scheduled_event(title):
    """Does this title announce a forthcoming event rather than report one?"""
    t = (title or "").lower()
    return any(w in t for w in SCHEDULED_EVENT_WORDS)


# SCHEDULED_EVENT_WORDS above is not a clean split. A title can genuinely
# announce results and a call in the same breath — "...Third Quarter 2026
# Financial Results and Will Host Conference Call" — and no word list
# separates that from a pure advance notice, because both use the same
# scheduling language. RESULTS_WORDS is too broad to use as the signal here:
# "earnings" alone names the call itself ("Earnings Conference Call",
# "Earnings Release and Webcast") and would flag every clean advance notice
# as mixed. "results" is the narrower word that shows up when the release is
# actually reported, not merely named as an event. This is a second, finer
# label on top of names_a_scheduled_event's — both are pure labels applied
# to every row probe_body_dates.py selects, so probe_body_dates.py's table
# can be split by label rather than read wholesale.
RESULTS_RELEASE_WORDS = ("results",)


def also_reports_results(title):
    """Does this title ALSO read as a results release, not purely an advance
    notice of a scheduled event?
    """
    t = (title or "").lower()
    return any(w in t for w in RESULTS_RELEASE_WORDS)


MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
          "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}

# Month name (abbreviated or full, optional full stop), day, optional ordinal
# suffix, optional comma, four-digit year. The year is not optional: see
# parse_date.
DATE_RE = re.compile(
    r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+"
    r"(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b", re.I)

# Month and day with NO four-digit year following. The negative lookahead is
# what stops this stealing a match from DATE_RE.
DATE_NOYEAR_RE = re.compile(
    r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+"
    r"(\d{1,2})(?:st|nd|rd|th)?\b(?!\s*,?\s*\d{4})", re.I)


def looks_like_announcement(title):
    """Does this title look like an advance notice of a reporting date?"""
    t = (title or "").lower()
    return (any(v in t for v in ANNOUNCE_VERBS)
            and any(w in t for w in RESULTS_WORDS))


def parse_date(title, released=None):
    """The first month-day-year in the title, or None.

    A four-digit year in the title always wins. When there is none, the year
    is taken from `released`, the release's own publication date — WHICH IS
    NOT A GUESS. The release date is known data, and the ambiguity it leaves
    is resolved by a fact rather than a preference: A COMPANY DOES NOT
    ANNOUNCE A FORTHCOMING EVENT IN THE PAST, so of the two candidate years
    the answer is the first that is not before the release.

    Without `released` it still refuses. "on August 12" alone would have to be
    guessed at, and a guessed year is wrong every time a release crosses a
    year boundary.

    The edge it gets wrong: a release published days AFTER the date it names,
    which rolls forward a year. Recognition already requires an announcement
    verb, so such a headline is unusual, and the stored provenance makes the
    mistake diagnosable rather than mysterious.
    """
    m = DATE_RE.search(title or "")
    if m:
        try:
            return date(int(m.group(3)), MONTHS[m.group(1)[:3].lower()],
                        int(m.group(2)))
        except (KeyError, ValueError):
            return None
    if released is None:
        return None
    m = DATE_NOYEAR_RE.search(title or "")
    if not m:
        return None
    try:
        month, day = MONTHS[m.group(1)[:3].lower()], int(m.group(2))
    except (KeyError, ValueError):
        return None
    for year in (released.year, released.year + 1):
        try:
            candidate = date(year, month, day)
        except ValueError:
            continue
        if candidate >= released:
            return candidate
    return None


def extract(title, today, released=None):
    """(date, reason) for one item title. See parse_date for `released`.

    reason is "no-match", "no-date", "past" or "ok". The caller counts them
    separately: "no-date" is the informative miss, "no-match" is every
    unrelated release on the roster and means nothing on its own.
    """
    if not looks_like_announcement(title):
        return None, "no-match"
    when = parse_date(title, released)
    if when is None:
        return None, "no-date"
    if when < today:
        return None, "past"
    return when, "ok"


def parse_iso(value):
    """An ISO date string as a date, or None. Never raises."""
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def load(path=DEFAULT_PATH):
    """(companies, status) where status is "missing", "unreadable", "empty"
    or "ok".

    MISSING AND EMPTY ARE DIFFERENT MEASUREMENTS and the caller logs them
    differently. No file means the writer has never run, which is expected
    once and a fault afterwards. An empty one means nothing is currently
    announced. Collapsing them is how a broken writer reads as a quiet week.
    """
    p = Path(path)
    if not p.exists():
        return {}, "missing"
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}, "unreadable"
    if not isinstance(raw, dict) or raw.get("schema") != SCHEMA:
        return {}, "unreadable"
    companies = raw.get("companies")
    if not isinstance(companies, dict):
        return {}, "unreadable"
    return companies, ("ok" if companies else "empty")


def save(companies, path=DEFAULT_PATH):
    """Write the store. indent=1 matches state.json."""
    Path(path).write_text(
        json.dumps({"schema": SCHEMA, "companies": companies}, indent=1),
        encoding="utf-8")


def upsert(companies, cik, ticker, when, uid, title, published):
    """Record a disclosed date. Returns True if the store changed.

    A LATER RELEASE WINS, JUDGED BY THE RELEASE rather than by when we read
    it. A company that moves its date issues a second release, and comparing
    the releases' own timestamps is what stops an old item resurfacing in a
    feed from clobbering the newer announcement. A release carrying no
    timestamp never overwrites: unknown is not newer.

    The store is keyed by CIK and overwrites in place, so it is bounded by
    the roster. Nothing is pruned; a passed date is what the Overdue section
    is built on.
    """
    cik = str(cik).zfill(10)
    prior = companies.get(cik)
    if prior is not None:
        if not published:
            return False
        if (prior.get("source_published") or "") >= published:
            return False
    companies[cik] = {
        "ticker": ticker,
        "date": when.isoformat(),
        "source_uid": uid,
        "source_title": title,
        "source_published": published,
    }
    return True


def apply(rows, companies, today):
    """Overlay disclosed dates onto projected rows. (rows, applied, notes).

    A STORED DATE APPLIES WHEN IT FALLS AFTER THE PERIOD END BEING PROJECTED.
    A report date is always after the period it covers, so this holds while
    the company has not reported, and keeps holding once the date has passed,
    which is what puts the row in Overdue rather than quietly reverting it to
    an estimate. It stops holding by itself the moment the company files:
    `upcoming` moves to the next period end and the stored date is now before
    it. Nothing expires and no constant is chosen.

    `today` is taken for symmetry with the rest of the module and for future
    callers; the rule above does not need it.
    """
    applied, notes = 0, []
    for r in rows:
        rec = companies.get(r.get("cik"))
        if not rec:
            continue
        if not isinstance(rec, dict):
            notes.append(f"{r['label']}: stored record for CIK {r.get('cik')} "
                         f"is not a dict ({rec!r}); keeping the projection")
            continue
        when = parse_iso(rec.get("date"))
        if when is None:
            notes.append(f"{r['label']}: stored date {rec.get('date')!r} is "
                         f"unparseable; keeping the projection")
            continue
        if when <= r["period"]:
            # This branch catches two different populations, and the note
            # must say which one fired. A date that is still ahead of `today`
            # is real and useful — it just describes a different report than
            # this row projects — so it is shown in the Announced section
            # (see announced_elsewhere). A date that has already PASSED hits
            # this same `when <= period` test, because a past date is always
            # <= a future period end, but announced_elsewhere's own
            # `when < today` guard means it is never surfaced there either.
            # Claiming otherwise for that case is the same defect this note
            # was rewritten to remove, just relocated to a narrower case.
            if when < today:
                notes.append(f"{r['label']}: stored date {when} is not after "
                             f"the period end {r['period']} being projected, "
                             f"and is itself before today; it is not applied "
                             f"and not shown anywhere")
            else:
                notes.append(f"{r['label']}: stored date {when} is not after "
                             f"the period end {r['period']} being projected, "
                             f"so it describes a different report than this "
                             f"row; shown in the Announced section instead")
            continue
        if when != r["expected"]:
            notes.append(f"{r['label']}: projected {r['expected']}, company "
                         f"announced {when}")
        r["projected"] = r["expected"]
        r["expected"] = when
        r["disclosed"] = True
        applied += 1

    return rows, applied, notes


def announced_elsewhere(rows, companies, today):
    """Announced dates that are real, still ahead, and NOT on any row.

    `apply()` overlays a stored date onto a row only when it falls after the
    period end being projected; a date that does not clear that bar describes
    a different, earlier report than the one the row projects, and is left in
    `companies` untouched rather than applied. This function is what surfaces
    that date instead of letting it disappear into a log line — for any row
    apply() left untouched, not only an annual-only one. There is no
    `annual_only` condition here; the trigger is simply "apply() didn't".

    The clearest case is annual-only: a row's period end is up to twelve
    months out, so a QUARTERLY announcement always falls before it and is
    refused by apply() — correctly, because that row is about the annual
    filing and an August date on it would be a claim about the wrong report.
    But the same refusal fires identically for an ordinary row whenever the
    stored date describes an earlier period than the one currently projected.

    The date is still true and still useful, so it is surfaced here instead of
    being dropped to a log line. Returns [(label, date), ...] sorted by date.
    """
    # One row per CIK (COMPANIES is keyed that way), so "this row's own
    # `disclosed` flag" and "this row's CIK is in the set of disclosed CIKs"
    # are the same test. Reading it straight off the row skips building a set
    # that can only ever agree with what's already sitting in `rows`.
    out = []
    for r in rows:
        if r.get("disclosed"):
            continue
        rec = companies.get(r.get("cik"))
        if not isinstance(rec, dict):
            continue
        when = parse_iso(rec.get("date"))
        if when is None or when < today:
            continue
        out.append((r["label"], when))
    return sorted(out, key=lambda t: t[1])


def candidate_dates(text, released, limit=6):
    """Every plausible forthcoming date in a release body, in document order.

    THIS DELIBERATELY DOES NOT PICK ONE. A body carries the period end, the
    call date, the replay expiry and often last year's comparative, and which
    of them is the reporting date is exactly the question this measurement
    exists to answer with evidence rather than a guess. Returning candidates
    lets the log show what a rule would have had to choose between.

    Filtered only by facts: a date before the release cannot be a forthcoming
    report date, and a repeat is the same date said twice.

    DATE_RE only, never DATE_NOYEAR_RE. A bare "August 12" in running prose is
    far more often a period reference than an announcement, and inferring a
    year across a whole body multiplies that risk by every such phrase in it.
    """
    if not text:
        return []
    found, seen = [], set()
    for m in DATE_RE.finditer(text):
        try:
            when = date(int(m.group(3)), MONTHS[m.group(1)[:3].lower()],
                        int(m.group(2)))
        except (KeyError, ValueError):
            continue
        if released is not None and when < released:
            continue
        if when in seen:
            continue
        seen.add(when)
        found.append(when)
        if len(found) >= limit:
            break
    return found


def main():
    """Print what the store currently holds. No network, no writes.

    The diagnostic `watchlist.py` offers for the roster: load the default
    file and show what a reader would otherwise have to open and parse by
    hand.
    """
    companies, status = load()
    print(f"schema {SCHEMA}, default path {DEFAULT_PATH}")
    print(f"status: {status}, {len(companies)} record(s)")
    for cik, rec in sorted(companies.items()):
        if not isinstance(rec, dict):
            print(f"  {cik}: malformed record {rec!r}")
            continue
        print(f"  {cik} {rec.get('ticker')}: {rec.get('date')} "
              f"(from {rec.get('source_title')!r})")
    return 0 if status in ("missing", "empty", "ok") else 1


if __name__ == "__main__":
    sys.exit(main())
