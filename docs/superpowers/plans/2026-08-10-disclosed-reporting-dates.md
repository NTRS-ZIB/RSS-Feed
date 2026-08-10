# Disclosed Reporting Dates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When a company has announced its reporting date, the earnings calendar shows that date instead of its own projection.

**Architecture:** A new stdlib-only module `earnings_dates.py` holds the extraction, the store format and the lookup. `press_monitor.py` calls the extractor over items it has already fetched and writes `earnings_dates.json`. `earnings_calendar.py` reads that file and overlays disclosed dates on its projections. The two components never call each other; the file is the whole interface.

**Tech Stack:** Python 3.12, stdlib only for the new module. `requests` and `feedparser` stay where they already are. Tests are standalone scripts, matching `test_loop_verdict.py`.

Spec: [2026-08-10-disclosed-reporting-dates-design.md](../specs/2026-08-10-disclosed-reporting-dates-design.md)

## Corrections to the spec, found while planning

**Do these first, in Task 0. The spec as committed contains a contradiction and cannot be implemented as written.**

1. **The reader rule in the spec cannot produce the overdue behaviour the spec also requires.** It says a stored date is used "only when it is still in the future at run time", and it also says a passed announced date goes overdue with no grace. Both cannot hold: an ignored entry cannot drive a section. The rule becomes **use a disclosed date when it falls after the period end being projected**. A report date is always after the period it covers, so this applies while the company has not yet reported, keeps applying once the date passes (which is what puts the row in Overdue), and stops applying by itself the moment the company files, because the calendar's `upcoming` moves to the next period end and the stored date is now before it. No constant, and nothing to expire.

2. **There is no pruning.** The store is keyed by CIK and `upsert` overwrites in place, so it is bounded by the roster at nineteen records forever. The spec's "the writer prunes passed entries on its next pass" is both unnecessary and actively harmful, since it would delete the entry the Overdue section needs.

3. **The extractor guard rejects a date before today, not a date that is not strictly future.** The calendar's own upcoming test is `today <= expected`, so rejecting a same-day announcement would discard a date the calendar would happily display.

## Global Constraints

Every task's requirements implicitly include these.

- **Monospace blocks stay at or under 28 characters.** A new column means an existing one goes.
- **Key companies by CIK, never by ticker.** A ticker is a display label. Six of nineteen have renamed in eighteen months and one was previously a different company's.
- **`earnings_dates.json` is an output file.** Written by the press monitor workflow and by nothing else. Never hand-edited, never committed from a local clone.
- **`earnings_dates.py` is stdlib only and makes no network calls**, so it is safe to run and test locally. `watchlist.py` is the precedent.
- **Do not run the component scripts locally.** They read secrets that exist only in Actions and several post to live Discord channels. Verify with `gh workflow run "<name>" -f dry_run=true`.
- **Tests are standalone scripts**, run as `python test_earnings_dates.py`, stdlib only, printing `[PASS]`/`[FAIL]` per check and exiting non-zero if any failed. Match `test_loop_verdict.py`.
- **"Missing" and "empty" are different measurements and must never share a log line.**
- **A guard is not accepted until it has been shown to fire with the guard removed.**

## File Structure

| File | Responsibility |
|---|---|
| `earnings_dates.py` (create) | Recognition, date parsing, the guard, the store format, and the overlay. Pure logic plus file IO. No network, no Discord, no EDGAR. |
| `test_earnings_dates.py` (create) | Standalone tests for the above. |
| `press_monitor.py` (modify) | One new function and one call site. Writes the store. |
| `earnings_calendar.py` (modify) | Reads the store, overlays it, renders the marker and the Overdue section. |
| `.github/workflows/monitor.yml` (modify) | Refreshes and persists the new file alongside `state.json`. |
| `docs/earnings.md` (modify) | Marker table, section rename, known quirks. |
| `docs/superpowers/specs/2026-08-10-disclosed-reporting-dates-design.md` (modify) | The three corrections above. |

---

### Task 0: Correct the spec

**Files:**
- Modify: `docs/superpowers/specs/2026-08-10-disclosed-reporting-dates-design.md`

**Interfaces:**
- Consumes: nothing.
- Produces: a spec that later tasks can be checked against.

- [ ] **Step 1: Replace the reading rule**

In the "The calendar side" section, replace the paragraph beginning "**Reading rule.**" with:

```markdown
**Reading rule.** A stored date is used when it falls after the period end
being projected. A report date is always after the period it covers, so this
holds while the company has not yet reported, and keeps holding once the date
has passed, which is what puts the row in Overdue. It stops holding by itself
the moment the company files: `upcoming` moves to the next period end and the
stored date is now before it. There is no expiry to run and no constant to
choose.
```

- [ ] **Step 2: Remove the pruning claim**

In "The store", delete the line `**The writer prunes passed entries on its next pass.** The reader never writes.` and replace it with:

```markdown
**Nothing is pruned.** The store is keyed by CIK and `upsert` overwrites in
place, so it is bounded by the roster. Pruning a passed date would delete the
entry the Overdue section is built on.
```

- [ ] **Step 3: Correct the guard wording**

In "The extractor", replace `**The guard**: the parsed date must be in the future at extraction time.` with:

```markdown
**The guard**: the parsed date must not be before today. The calendar's own
upcoming test is `today <= expected`, so a stricter test here would discard a
same-day announcement the calendar would display.
```

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/specs/2026-08-10-disclosed-reporting-dates-design.md
git commit -m "Correct the reader rule: a disclosed date applies past its own date"
```

---

### Task 1: Recognition, date parsing and the guard

**Files:**
- Create: `earnings_dates.py`
- Create: `test_earnings_dates.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `looks_like_announcement(title: str) -> bool`, `parse_date(title: str) -> datetime.date | None`, `extract(title: str, today: datetime.date) -> tuple[datetime.date | None, str]` where the second element is one of `"no-match"`, `"no-date"`, `"past"`, `"ok"`.

- [ ] **Step 1: Write the failing test**

Create `test_earnings_dates.py`:

```python
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
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python test_earnings_dates.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'earnings_dates'`

- [ ] **Step 3: Write the minimal implementation**

Create `earnings_dates.py`:

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python test_earnings_dates.py`
Expected: PASS on every check, `18/18 checks passed`, exit 0

- [ ] **Step 5: Demonstrate the guard fires**

A test that has never failed proves nothing. Temporarily change the guard in `earnings_dates.py` from:

```python
    if when < today:
        return None, "past"
```

to:

```python
    if False:
        return None, "past"
```

Run: `python test_earnings_dates.py`
Expected: FAIL on "a date before today is rejected", showing `2026-07-20 ok`

Then restore the two lines exactly and re-run to confirm PASS. Record the observed failure line in the commit message.

- [ ] **Step 6: Commit**

```bash
git add earnings_dates.py test_earnings_dates.py
git commit -m "Extract an announced reporting date from a release title"
```

---

### Task 2: The store

**Files:**
- Modify: `earnings_dates.py`
- Modify: `test_earnings_dates.py`

**Interfaces:**
- Consumes: `SCHEMA`, `DEFAULT_PATH` from Task 1.
- Produces: `load(path=DEFAULT_PATH) -> tuple[dict, str]` with status `"missing"`, `"unreadable"`, `"empty"` or `"ok"`; `save(companies: dict, path=DEFAULT_PATH) -> None`; `upsert(companies, cik, ticker, when, uid, title, published) -> bool`; `parse_iso(value) -> datetime.date | None`.

- [ ] **Step 1: Write the failing test**

Append to `test_earnings_dates.py`, inside `main()` before the `bad = ...` line:

```python
    print("\nTHE STORE")
    import tempfile
    tmp = Path(tempfile.mkdtemp()) / "earnings_dates.json"

    companies, status = ed.load(tmp)
    check("a file that does not exist reports missing",
          companies == {} and status == "missing", status)

    ed.save({}, tmp)
    companies, status = ed.load(tmp)
    check("a file with no records reports empty, not missing",
          companies == {} and status == "empty", status)

    companies = {}
    wrote = ed.upsert(companies, "1218683", "BGDE", date(2026, 8, 12),
                      "uid-1", "title one", "2026-07-29T13:00:00+00:00")
    check("upsert writes", wrote and len(companies) == 1)
    check("the key is a zero-padded CIK",
          "0001218683" in companies, list(companies))

    wrote = ed.upsert(companies, "1218683", "BGDE", date(2026, 8, 14),
                      "uid-2", "title two", "2026-08-01T13:00:00+00:00")
    check("a later release overwrites",
          wrote and companies["0001218683"]["date"] == "2026-08-14")

    wrote = ed.upsert(companies, "1218683", "BGDE", date(2026, 8, 20),
                      "uid-3", "title three", "2026-07-01T13:00:00+00:00")
    check("an EARLIER release does not overwrite",
          not wrote and companies["0001218683"]["date"] == "2026-08-14",
          "a stale item resurfacing must not clobber a newer announcement")

    wrote = ed.upsert(companies, "1218683", "BGDE", date(2026, 9, 1),
                      "uid-4", "title four", None)
    check("a release with no timestamp does not overwrite",
          not wrote and companies["0001218683"]["date"] == "2026-08-14")

    ed.save(companies, tmp)
    reloaded, status = ed.load(tmp)
    check("a saved store round-trips", reloaded == companies and status == "ok")

    tmp.write_text("{not json", encoding="utf-8")
    companies, status = ed.load(tmp)
    check("unreadable is distinct from missing and empty",
          companies == {} and status == "unreadable", status)

    tmp.write_text(json.dumps({"schema": 99, "companies": {}}),
                   encoding="utf-8")
    companies, status = ed.load(tmp)
    check("a wrong schema is unreadable", status == "unreadable", status)
```

Add `import json` and `from pathlib import Path` to the test file's imports.

- [ ] **Step 2: Run it to verify it fails**

Run: `python test_earnings_dates.py`
Expected: FAIL with `AttributeError: module 'earnings_dates' has no attribute 'load'`

- [ ] **Step 3: Write the minimal implementation**

Append to `earnings_dates.py`:

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python test_earnings_dates.py`
Expected: every check PASS, exit 0

- [ ] **Step 5: Commit**

```bash
git add earnings_dates.py test_earnings_dates.py
git commit -m "Store disclosed dates by CIK, newest release wins"
```

---

### Task 3: The press monitor writes the store

**Files:**
- Modify: `press_monitor.py` (add import near line 28; add function before `def main()` at line 1682; add call inside `main()` after the first-run block that ends near line 1737)

**Interfaces:**
- Consumes: `earnings_dates.load`, `.save`, `.upsert`, `.extract` from Tasks 1 and 2.
- Produces: `record_disclosed_dates(items: list[dict]) -> None`. No return value; later tasks read the file, not this function.

- [ ] **Step 1: Add the import**

In `press_monitor.py`, after `import watchlist` on line 28, add:

```python
import earnings_dates as ed
```

- [ ] **Step 2: Add the function**

Insert immediately before `def main():`:

```python
def record_disclosed_dates(items):
    """Extract announced reporting dates from item titles and store them.

    Runs over EVERY item, not only the ones that will post. An announcement
    dropped by the age floor or by MAX_POSTS_PER_RUN is still a valid date,
    and the calendar has no other way to learn it.
    """
    today = datetime.now(timezone.utc).date()
    companies, status = ed.load()
    if status == "unreadable":
        print("  earnings dates: existing file unreadable — starting fresh.")
    elif status == "missing":
        print("  earnings dates: no file yet — this run creates it.")

    counts = {"ok": 0, "no-date": 0, "past": 0, "no-match": 0}
    for item in items:
        entry = EXTRA_CIKS.get(item.get("ticker") or "")
        if not entry:
            continue
        when, reason = ed.extract(item.get("title"), today)
        counts[reason] += 1
        if reason == "no-date":
            # The informative miss: an announcement whose date is in the body
            # rather than the title. This count is what decides whether
            # fetching bodies is worth building.
            print(f"  earnings dates: {item['ticker']} announcement with no "
                  f"parsable date — {item.get('title')!r}")
        if when is None:
            continue
        published = item.get("published")
        iso = (datetime.fromtimestamp(published, timezone.utc).isoformat()
               if published else None)
        if ed.upsert(companies, entry[0], item["ticker"], when,
                     item.get("uid"), item.get("title"), iso):
            print(f"  earnings dates: {item['ticker']} -> {when} "
                  f"from {item.get('title')!r}")

    print(f"  earnings dates: {counts['ok']} recorded, {counts['no-date']} "
          f"announcement(s) with no parsable date, {counts['past']} rejected "
          f"as past, {len(companies)} on file.")
    if DRY_RUN:
        print("  earnings dates: dry run — nothing written.")
        return
    ed.save(companies)
```

- [ ] **Step 3: Add the call site**

In `main()`, immediately after the first-run block that ends with

```python
        print("First run complete — baseline recorded, nothing posted.")
        return
```

add:

```python
    record_disclosed_dates(all_items)
```

- [ ] **Step 4: Verify by dispatch, not locally**

The script reads secrets that exist only in Actions and posts to live Discord channels. Do not run it here.

Run: `gh workflow run "Press release monitor" -f dry_run=true`

Then, once it completes:

```bash
gh run list --workflow=monitor.yml --limit 1 --json databaseId -q '.[0].databaseId'
gh run view <id> --log | grep "earnings dates"
```

Expected: a summary line reading `earnings dates: N recorded, ...` followed by `earnings dates: dry run — nothing written.` The `no file yet` line is expected on this first run.

- [ ] **Step 5: Commit**

```bash
git add press_monitor.py
git commit -m "Record announced reporting dates as the press monitor sees them"
```

---

### Task 4: The calendar applies disclosed dates

**Files:**
- Modify: `earnings_dates.py`
- Modify: `test_earnings_dates.py`
- Modify: `earnings_calendar.py` (import near line 25; one line in `main()` near line 295; call before `build_message` near line 306)

**Interfaces:**
- Consumes: `load`, `parse_iso` from Task 2.
- Produces: `apply(rows, companies, today) -> tuple[list[dict], int, list[str]]`. Rows gain `"disclosed": True` and `"projected"` (the date that was replaced). Task 5 and Task 6 read `r.get("disclosed")`.

- [ ] **Step 1: Write the failing test**

Append inside `main()` in `test_earnings_dates.py`, before the `bad = ...` line:

```python
    print("\nTHE OVERLAY")

    def row(label, cik, period, expected, spread=6):
        return {"label": label, "cik": cik, "period": period,
                "expected": expected, "spread": spread, "kind": "10-Q",
                "degraded": False}

    store = {"0001218683": {"ticker": "BGDE", "date": "2026-08-12",
                            "source_uid": "u", "source_title": "t",
                            "source_published": "2026-07-29T13:00:00+00:00"}}

    rows = [row("BGDE", "0001218683", date(2026, 6, 30), date(2026, 8, 14))]
    rows, applied, notes = ed.apply(rows, store, date(2026, 8, 10))
    check("the announced date replaces the projection",
          applied == 1 and rows[0]["expected"] == date(2026, 8, 12))
    check("the replaced projection is kept for the log",
          rows[0]["projected"] == date(2026, 8, 14))
    check("the row is marked disclosed", rows[0].get("disclosed") is True)

    rows = [row("BGDE", "0001218683", date(2026, 6, 30), date(2026, 8, 14))]
    rows, applied, notes = ed.apply(rows, store, date(2026, 8, 20))
    check("a date that has passed STILL applies",
          applied == 1 and rows[0]["expected"] == date(2026, 8, 12),
          "this is what puts the row in Overdue")

    rows = [row("BGDE", "0001218683", date(2026, 9, 30), date(2026, 11, 13))]
    rows, applied, notes = ed.apply(rows, store, date(2026, 8, 20))
    check("once the company files, the stale entry stops applying",
          applied == 0 and rows[0]["expected"] == date(2026, 11, 13),
          "the disclosed date is before the new period end")

    rows = [row("MARA", "0001507605", date(2026, 6, 30), date(2026, 8, 14))]
    rows, applied, notes = ed.apply(rows, store, date(2026, 8, 10))
    check("a company with no stored date is untouched",
          applied == 0 and rows[0]["expected"] == date(2026, 8, 14))

    bad_store = {"0001218683": {"ticker": "BGDE", "date": "not a date"}}
    rows = [row("BGDE", "0001218683", date(2026, 6, 30), date(2026, 8, 14))]
    rows, applied, notes = ed.apply(rows, bad_store, date(2026, 8, 10))
    check("an unparseable stored date is skipped and noted",
          applied == 0 and any("not a date" in n for n in notes), notes)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python test_earnings_dates.py`
Expected: FAIL with `AttributeError: module 'earnings_dates' has no attribute 'apply'`

- [ ] **Step 3: Write the minimal implementation**

Append to `earnings_dates.py`:

```python
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
        when = parse_iso(rec.get("date"))
        if when is None:
            notes.append(f"{r['label']}: stored date {rec.get('date')!r} is "
                         f"unparseable; keeping the projection")
            continue
        if when <= r["period"]:
            notes.append(f"{r['label']}: stored date {when} is not after the "
                         f"period end {r['period']} being projected; it "
                         f"belongs to a period already reported")
            continue
        if when != r["expected"]:
            notes.append(f"{r['label']}: projected {r['expected']}, company "
                         f"announced {when}")
        r["projected"] = r["expected"]
        r["expected"] = when
        r["disclosed"] = True
        applied += 1

    unknown = set(companies) - {r.get("cik") for r in rows}
    for cik in sorted(unknown):
        notes.append(f"stored date for CIK {cik} "
                     f"({companies[cik].get('ticker')}) is not on the roster")
    return rows, applied, notes
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python test_earnings_dates.py`
Expected: every check PASS, exit 0

- [ ] **Step 5: Wire it into the calendar**

In `earnings_calendar.py`, after `import watchlist` on line 25, add:

```python
import earnings_dates as ed
```

In `main()`, inside the loop over `COMPANIES.items()`, immediately after `projection = project(label, name, filings)` add the CIK to the row so the overlay can match on it:

```python
        if projection:
            projection["cik"] = cik
```

so the block reads:

```python
        projection = project(label, name, filings)
        if projection:
            projection["cik"] = cik
            rows.append(projection)
```

Then, after the `if not rows:` guard and before `text = build_message(rows)`, add:

```python
    disclosed, status = ed.load()
    if status == "missing":
        print("\nNo earnings_dates.json — the press monitor has not written "
              "one yet. Every row below is a projection.")
    elif status == "unreadable":
        print("\nearnings_dates.json is unreadable — every row below is a "
              "projection.")
    elif status == "empty":
        print("\nearnings_dates.json holds no announced dates.")
    rows, applied, notes = ed.apply(rows, disclosed, date.today())
    for note in notes:
        print(f"  {note}")
    print(f"{applied} row(s) use an announced date.")
```

- [ ] **Step 6: Verify by dispatch**

Run: `gh workflow run "Earnings calendar" -f dry_run=true`

Then check the log for the new lines. Expected on the first run, before the press monitor has written anything: `No earnings_dates.json — the press monitor has not written one yet.` and `0 row(s) use an announced date.` Every projected date must be unchanged from the previous run.

- [ ] **Step 7: Commit**

```bash
git add earnings_dates.py test_earnings_dates.py earnings_calendar.py
git commit -m "Overlay announced dates on the calendar's projections"
```

---

### Task 5: Mark the row and blank the spread

**Files:**
- Modify: `earnings_calendar.py` (`marker()` near line 191, `row()` near line 200, the key block near line 240)

**Interfaces:**
- Consumes: `r.get("disclosed")` set by Task 4.
- Produces: nothing later tasks call. Task 6 reuses `marker()` unchanged.

- [ ] **Step 1: Put the new marker first in `marker()`**

Replace:

```python
    def marker(r):
        if r["degraded"]:
            return "?"
```

with:

```python
    def marker(r):
        # First, and it outranks the rest: `*`, `~` and `?` all describe a
        # projection, and this row no longer has one.
        if r.get("disclosed"):
            return "!"
        if r["degraded"]:
            return "?"
```

- [ ] **Step 2: Blank the spread column for a disclosed row**

Replace:

```python
    def row(r, weekday=True):
        days = (r["expected"] - today).days
        when = f"{r['expected']:%a %d %b}" if weekday else f"{r['expected']:%d %b}"
        return (f"{r['label']:<4}{marker(r)} {when}"
                f"{days:>4}d {r['spread']:>3}d")
```

with:

```python
    def row(r, weekday=True):
        days = (r["expected"] - today).days
        when = f"{r['expected']:%a %d %b}" if weekday else f"{r['expected']:%d %b}"
        # A spread is a property of a projection. On an announced row there is
        # nothing for it to describe, and printing 0 would read as a claim of
        # perfect precision rather than as absence. Four spaces keeps the
        # column aligned against "  6d".
        tail = "    " if r.get("disclosed") else f"{r['spread']:>3}d"
        return (f"{r['label']:<4}{marker(r)} {when}"
                f"{days:>4}d {tail}")
```

- [ ] **Step 3: Add the key line**

In the key block, after the three existing `if any(...)` clauses and before `if key:`, add:

```python
    if any(r.get("disclosed") for r in rows):
        key.append("! announced by company")
```

- [ ] **Step 4: Check the width by hand**

`! announced by company` is 22 characters, inside the 28-character ceiling. A disclosed row renders as `BGDE! Wed 12 Aug   2d     `, which is the same width as `BGDE  Fri 14 Aug   4d   6d`. Confirm both by counting in the dry-run output in Step 5; the existing `LIMITS OK` style check does not cover this component.

- [ ] **Step 5: Verify by dispatch**

Run: `gh workflow run "Earnings calendar" -f dry_run=true`

Expected while the store is still empty: output byte-identical to the previous run, no `!` marker and no new key line. That is the correct result and confirms the change is inert until a date is recorded.

- [ ] **Step 6: Commit**

```bash
git add earnings_calendar.py
git commit -m "Mark an announced row and blank its spread column"
```

---

### Task 6: Overdue with no grace, and the docs

**Files:**
- Modify: `earnings_calendar.py` (the `overdue` list near line 185, the section block near line 225)
- Modify: `docs/earnings.md`

**Interfaces:**
- Consumes: `r.get("disclosed")` from Task 4.
- Produces: nothing.

- [ ] **Step 1: Give a disclosed row no grace**

Replace:

```python
    overdue = sorted((r for r in rows
                      if r["expected"] < today - timedelta(days=OVERDUE_GRACE)),
                     key=lambda r: r["expected"])
```

with:

```python
    def is_overdue(r):
        # OVERDUE_GRACE exists to allow for the spread in OUR projection. A
        # company's own announced date has no spread to allow for, so it gets
        # none: announced the 12th and nothing filed by the 13th is late.
        grace = 0 if r.get("disclosed") else OVERDUE_GRACE
        return r["expected"] < today - timedelta(days=grace)

    overdue = sorted((r for r in rows if is_overdue(r)),
                     key=lambda r: r["expected"])
```

- [ ] **Step 2: Rename the section and label the row honestly**

Replace:

```python
    if overdue:
        lines.append("")
        lines.append("Past estimate")
        lines.append("-" * 26)
        for r in overdue:
            late = (today - r["expected"]).days
            lines.append(f"{r['label']:<4}{marker(r)} est {r['expected']:%d %b}"
                         f"{late:>4}d ago")
```

with:

```python
    if overdue:
        lines.append("")
        # "Past estimate" stops being true once a row can be past a date the
        # company announced rather than one we projected.
        lines.append("Overdue")
        lines.append("-" * 26)
        for r in overdue:
            late = (today - r["expected"]).days
            # Same width, so the column does not move between the two cases.
            what = "due" if r.get("disclosed") else "est"
            lines.append(f"{r['label']:<4}{marker(r)} {what} "
                         f"{r['expected']:%d %b}{late:>4}d ago")
```

- [ ] **Step 3: Update the docs**

In `docs/earnings.md`, add a row to the markers table immediately above the `*(none)*` row:

```markdown
| `!` | The company announced this date. Not a projection, so no spread is shown. |
```

Replace the "Past estimate" bullet in the Sections block with:

```markdown
**Overdue** — a company past its own announced date with nothing filed, or
more than 10 days beyond its typical lag. An announced date gets no grace,
because the grace exists to allow for the spread in our projection and an
announced date has none. This corroborates the `NT 10-Q` / `NT 10-K`
late-filing notices the press monitor watches for; seeing both is a strong
signal.
```

Replace the first known-quirks bullet with:

```markdown
- **Most rows are estimates; a `!` row is not.** Companies announce actual
  dates by press release, the [press release monitor](press-monitor.md) reads
  the announcement out of the release title, and `earnings_dates.json` carries
  it here. A company whose announcement puts the date in the body rather than
  the title is still an estimate; the press monitor logs a count of those.
```

- [ ] **Step 4: Verify by dispatch**

Run: `gh workflow run "Earnings calendar" -f dry_run=true`

Expected: the section that read `Past estimate` now reads `Overdue`, and BTDR still appears in it as `BTDR? est 20 Jul  NNd ago`, unchanged apart from the header. BTDR is a projection, not an announcement, so it must keep `est` and keep its grace.

- [ ] **Step 5: Commit**

```bash
git add earnings_calendar.py docs/earnings.md
git commit -m "An announced date gets no grace, and the section is renamed"
```

---

### Task 7: Persist the file from the workflow

**Files:**
- Modify: `.github/workflows/monitor.yml` (`refresh_state` near line 93, `persist_state` near line 115)

**Interfaces:**
- Consumes: `earnings_dates.json` written by Task 3.
- Produces: nothing.

**This is the task most likely to be got wrong.** `persist_state` does `git reset --hard origin/<branch>` and then copies back only `state.json`. Adding a second file without adding it to both the save and the restore means the reset silently discards it every run, and the symptom is an `earnings_dates.json` that is always empty with nothing in the log.

- [ ] **Step 1: Refresh the new file too**

Replace the body of `refresh_state()` between `git fetch` and the `after=` line with:

```bash
            # Via a temp file — a redirect truncates first, so a failed show
            # would leave an empty state file and repost everything.
            git show "origin/$GITHUB_REF_NAME:state.json" \
              > "$RUNNER_TEMP/origin_state.json" || return 1
            mv "$RUNNER_TEMP/origin_state.json" state.json || return 1
            # The dates file may not exist on origin yet, and absent is not an
            # error: the first run that finds an announcement creates it.
            if git show "origin/$GITHUB_REF_NAME:earnings_dates.json" \
                 > "$RUNNER_TEMP/origin_dates.json" 2>/dev/null; then
              mv "$RUNNER_TEMP/origin_dates.json" earnings_dates.json || return 1
            else
              echo "No earnings_dates.json on origin yet."
            fi
```

- [ ] **Step 2: Persist the new file too**

Replace `persist_state()` in full with:

```bash
          persist_state() {
            if [[ -z "$(git status --porcelain state.json earnings_dates.json)" ]]; then
              echo "No state change."
              return 0
            fi
            cp state.json "$RUNNER_TEMP/state.json" || return 1
            # Copied BEFORE the reset below and restored after it, exactly like
            # state.json. A file that is written but not carried across the
            # reset is discarded every run, silently.
            if [[ -f earnings_dates.json ]]; then
              cp earnings_dates.json "$RUNNER_TEMP/earnings_dates.json" || return 1
            fi
            for attempt in 1 2 3 4 5; do
              git fetch -q origin "$GITHUB_REF_NAME" || return 1
              git reset -q --hard "origin/$GITHUB_REF_NAME" || return 1
              cp "$RUNNER_TEMP/state.json" state.json || return 1
              if [[ -f "$RUNNER_TEMP/earnings_dates.json" ]]; then
                cp "$RUNNER_TEMP/earnings_dates.json" earnings_dates.json || return 1
              fi
              if [[ -z "$(git status --porcelain state.json earnings_dates.json)" ]]; then
                echo "State already current on origin; nothing to push."
                return 0
              fi
              git add state.json earnings_dates.json || return 1
              git commit -q -m "Update seen items [skip ci]" || return 1
              if git push -q origin "HEAD:$GITHUB_REF_NAME"; then
                echo "State pushed on attempt $attempt."
                return 0
              fi
              echo "Push rejected (attempt $attempt); another run pushed first. Retrying."
              sleep $((attempt * 3))
            done
            echo "Could not persist state.json after 5 attempts." >&2
            return 1
          }
```

Note that `git add earnings_dates.json` is safe when the file does not exist only if it is not passed to `git add` unconditionally. It is guarded by the `-f` check above producing the file, but on a run before the first write the file will not exist and `git add` would fail. Change the add line to:

```bash
              git add state.json || return 1
              [[ -f earnings_dates.json ]] && { git add earnings_dates.json || return 1; }
```

- [ ] **Step 3: Confirm the pre-commit hook does not block it**

`earnings_dates.json` is written by a workflow, not by a local clone, and the hook lists ten specific state files. It is not one of them, so the hook is not involved. Confirm the file list has not changed:

```bash
grep -c "earnings_dates" docs/hooks/pre-commit
```

Expected: `0`. If it is non-zero, the hook has been changed elsewhere and this task needs re-reading.

- [ ] **Step 4: Verify by dispatch**

A dry run saves no state and will not exercise the push. Dispatch a live single pass only when you are ready for real posts:

```bash
gh workflow run "Press release monitor" -f dry_run=true
```

Expected in the log: `No earnings_dates.json on origin yet.` from `refresh_state`, and `No state change.` or a normal push from `persist_state`. The dry run proves the refresh half and cannot prove the persist half.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/monitor.yml
git commit -m "Carry earnings_dates.json across the state refresh and push"
```

---

### Task 8: Close the verification gap deliberately

**Files:** none. This task produces a written record, not code.

**Interfaces:**
- Consumes: everything above.
- Produces: nothing.

**The write path has not been exercised and must not be allowed to look verified.** A dry run saves no state, so no dry run has ever written `earnings_dates.json` or pushed it. This is the same shape as the push retry loop, which sat in the repo for weeks looking finished while every run since it landed had been a dry dispatch.

- [ ] **Step 1: Run the full local test suite**

```bash
python test_earnings_dates.py
python test_loop_state.py
python test_loop_verdict.py
python test_loop_approval.py
python score_gate.py
python watchlist.py
```

Expected: every script exits 0. `score_gate.py` currently reports 3/4 with `reconciled` failing rule 3 on a coerced quote, which predates this work; confirm the failure is that one and not a new one.

- [ ] **Step 2: Record what is unverified**

Append to `docs/earnings.md`, in Known quirks:

```markdown
- **The write path is exercised only by a live run that finds an
  announcement.** A press monitor dry run saves no state, so it logs what it
  would record and writes nothing. Until a scheduled run has actually written
  `earnings_dates.json` and pushed it, the store side of this feature has
  never executed. Do not read the surrounding work looking finished as
  evidence that it has.
```

- [ ] **Step 3: Watch the first live write**

After the next scheduled press monitor run that reports a non-zero `earnings dates: N recorded`:

```bash
git pull
python -c "import json;print(json.load(open('earnings_dates.json'))['companies'])"
```

Expected: at least one record, with `source_title` naming a release you can open and read. Verify the date in the file against the date in that release by eye. This is the check that closes the gap, and nothing before it does.

- [ ] **Step 4: Commit**

```bash
git add docs/earnings.md
git commit -m "Record that the disclosed-date write path is not yet exercised"
```

---

## Self-review

**Spec coverage.** Extractor recognition and guard, Task 1. Store schema, CIK keying and newest-release-wins, Task 2. Press monitor writes and the miss count, Task 3. Calendar reads and overlays, Task 4. Marker and blanked spread, Task 5. Overdue with no grace, the rename and the docs, Task 6. Workflow persistence, Task 7, which the spec did not mention and which the feature does not work without. The unverifiable write path, Task 8. The spec's three errors, Task 0.

**Not covered, deliberately.** Fetching release bodies, gated on the count Task 3 produces. The foreign private issuer problem, which is a separate project.

**Type consistency.** `extract` returns `(date | None, str)` in Tasks 1 and 3. `load` returns `(dict, str)` in Tasks 2, 3 and 4. `upsert` returns `bool` in Tasks 2 and 3. `apply` returns `(rows, int, list[str])` in Task 4 and its `"disclosed"` key is read in Tasks 5 and 6. `parse_iso` is defined in Task 2 and used in Task 4.
