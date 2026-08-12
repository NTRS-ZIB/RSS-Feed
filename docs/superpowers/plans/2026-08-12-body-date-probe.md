# Body-date probe Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the body-date measurement out of `press_monitor.py` into a hand-run
`probe_body_dates.py`, so it samples all twenty undated announcements at once
instead of waiting on new items that arrive twice a day.

**Architecture:** A read-only maintenance script in the shape
`calibrate_staleness.py` establishes, plus a dispatch-only workflow. The script's
selection, probing and summarising are pure functions taking their inputs as
arguments, so they are tested locally against fixtures; only `main()` touches the
network. The body fetch and its freshness gate are then deleted from
`press_monitor.py`.

**Tech Stack:** Python 3.12, stdlib plus `requests` and `feedparser` on the runner.
Tests are a standalone script with the repo's own `check()` harness, not pytest.

## Global Constraints

- **The probe is read-only.** No webhook, no state file, no commit, no schedule,
  no secrets. Never import or call anything that posts.
- **`probe_body_dates.py` must import at module level without `press_monitor`.**
  `press_monitor` imports `feedparser`, which is NOT installed in this working
  copy, so a top-level import makes the whole module and its tests unrunnable
  locally. Import it inside `main()`.
- **Do not run the component scripts locally.** They read secrets that exist only
  in GitHub Actions and several post to live Discord. `watchlist.py`,
  `earnings_dates.py`, the test files and `probe_body_dates.py`'s pure half are
  the only things run directly.
- **Every workflow dispatch carries `--ref <branch>`.** Without it the dispatch
  runs `main` and verifies nothing.
- **`workflow_dispatch` only registers on the default branch.** A new workflow
  cannot be dispatched from a branch; `gh workflow run` returns *could not find
  any workflows named*. Task 5 handles this.
- **`earnings_dates.json`, `state.json` and `snapshot.json` are outputs.** Never
  edit, delete, reformat or commit one locally.
- **Branch:** `body-date-probe`, already created, spec committed at `2d4ce22`.
- Run the full suite with `python test_earnings_dates.py` and
  `python test_probe_body_dates.py`. Each prints `N/M checks passed` and exits
  non-zero on any failure.

## File Structure

| File | Responsibility |
|---|---|
| Create `probe_body_dates.py` | Select undated announcements, fetch each body, print a table and the counts. Pure functions plus a thin `main()`. |
| Create `test_probe_body_dates.py` | Tests for the pure half, using fixture items and a fake fetcher. No network. |
| Create `.github/workflows/probe-body-dates.yml` | Dispatch-only, `contents: read`, no secrets. |
| Modify `press_monitor.py` | Delete `announcement_body`, `BODY_TIMEOUT`, `BODY_MAX_BYTES`, the fetch gate, the two counters and the `Bodies fetched` clause. |
| Modify `docs/press-monitor.md` | Record the probe as the second maintenance tool beside `calibrate_staleness.py`. |

`earnings_dates.py` is NOT modified. `names_a_scheduled_event`,
`also_reports_results` and `candidate_dates` stay exactly where they are, with
their existing tests, because the probe calls all three.

---

### Task 1: Selecting the undated announcements

**Files:**
- Create: `probe_body_dates.py`
- Create: `test_probe_body_dates.py`

**Interfaces:**
- Consumes: `earnings_dates.extract(title, today, released=None) -> (date|None, reason)`
  where reason is `"no-match"`, `"no-date"`, `"past"` or `"ok"`;
  `earnings_dates.names_a_scheduled_event(title) -> bool`;
  `earnings_dates.also_reports_results(title) -> bool`;
  `watchlist.ciks() -> {ticker: (cik, name)}`.
- Produces: `released_date(item) -> date|None` and
  `undated_announcements(items, today, roster=None) -> list[dict]`. Each dict has
  keys `ticker`, `title`, `link`, `released`, `scheduled`, `mixed`. Tasks 2 and 3
  add `chars` and `candidates` to the same dicts.

- [ ] **Step 1: Write the failing test**

Create `test_probe_body_dates.py`:

```python
#!/usr/bin/env python3
"""Tests for probe_body_dates. Standalone, stdlib only.

THE ONE THAT MATTERS: the probe must NOT apply press_monitor's
scheduled-event gate. That gate exists to keep date-dense results releases
out of the measurement, and whether it actually discriminates is the
question this probe was built to answer. A probe that pre-filters by the
gate can only ever confirm it.
"""

import sys
from datetime import date, datetime, timezone

import probe_body_dates as pb

PASS, FAIL = "PASS", "FAIL"
results = []


def check(name, ok, detail=""):
    results.append((PASS if ok else FAIL, name))
    print(f"  [{PASS if ok else FAIL}] {name}" + (f" — {detail}" if detail else ""))


TODAY = date(2026, 8, 10)
ROSTER = {"MARA": ("0001507605", "MARA Holdings"),
          "HUT": ("0001964789", "Hut 8 Corp")}


def epoch(y, m, d):
    return datetime(y, m, d, tzinfo=timezone.utc).timestamp()


# One item per case the selector has to get right. The three labels are
# taken from real titles and their predicates were measured, not assumed:
# MARA's actual advance notice says "...Second Quarter 2026 Financial
# Results", so also_reports_results() is TRUE for it. A pure advance notice
# is the rarer phrasing that never says "results" at all.
ADVANCE_NOTICE = {            # scheduled, not mixed
    "ticker": "MARA", "link": "https://example.test/a", "published": epoch(2026, 8, 5),
    "title": "MARA Schedules Conference Call for Second Quarter 2026 Earnings",
}
MIXED_NOTICE = {              # scheduled AND reports results
    "ticker": "MARA", "link": "https://example.test/b", "published": epoch(2026, 8, 5),
    "title": "MARA Schedules Conference Call for Second Quarter 2026 Financial Results",
}
RESULTS_RELEASE = {           # not scheduled
    "ticker": "MARA", "link": "https://example.test/c", "published": epoch(2026, 8, 5),
    "title": "MARA Announces Second Quarter 2026 Results",
}
HAS_A_DATE = {
    "ticker": "HUT", "link": "https://example.test/d", "published": epoch(2026, 8, 5),
    "title": "Hut 8 to Report Second Quarter 2026 Results on August 20, 2026",
}
UNRELATED = {
    "ticker": "MARA", "link": "https://example.test/e", "published": epoch(2026, 8, 5),
    "title": "MARA Announces $4.7 Billion Data Center Lease",
}
OFF_ROSTER = {
    "ticker": "ZZZZ", "link": "https://example.test/f", "published": epoch(2026, 8, 5),
    "title": "Zzzz Schedules Conference Call for Second Quarter 2026 Results",
}


def main():
    print("SELECTION")
    rows = pb.undated_announcements(
        [ADVANCE_NOTICE, MIXED_NOTICE, RESULTS_RELEASE, HAS_A_DATE, UNRELATED,
         OFF_ROSTER],
        TODAY, roster=ROSTER)
    titles = [r["title"] for r in rows]

    check("an advance notice with no title date is selected",
          ADVANCE_NOTICE["title"] in titles)
    check("a mixed notice is selected", MIXED_NOTICE["title"] in titles)
    check("a results release with no title date is ALSO selected",
          RESULTS_RELEASE["title"] in titles,
          "the gate is what this probe is measuring, not a filter it applies")
    check("an announcement whose date parsed is not selected",
          HAS_A_DATE["title"] not in titles)
    check("an unrelated release is not selected",
          UNRELATED["title"] not in titles)
    check("a ticker off the roster is not selected",
          OFF_ROSTER["title"] not in titles,
          "mirrors record_disclosed_dates, so the count matches the log")
    check("exactly three rows selected", len(rows) == 3, f"got {len(rows)}")

    print("\nROW SHAPE")
    notice = next(r for r in rows if r["title"] == ADVANCE_NOTICE["title"])
    mixed = next(r for r in rows if r["title"] == MIXED_NOTICE["title"])
    release = next(r for r in rows if r["title"] == RESULTS_RELEASE["title"])
    check("release date read from the published epoch",
          notice["released"] == date(2026, 8, 5))
    check("an advance notice is labelled scheduled", notice["scheduled"] is True)
    check("an advance notice is not labelled mixed", notice["mixed"] is False)
    check("a mixed notice is labelled scheduled", mixed["scheduled"] is True)
    check("a mixed notice is labelled mixed", mixed["mixed"] is True,
          "the real MARA title says 'Financial Results' and must not read as pure")
    check("a results release is not labelled scheduled",
          release["scheduled"] is False)
    check("a results release is labelled mixed", release["mixed"] is True)
    check("the link is carried through", notice["link"] == "https://example.test/a")

    print("\nRELEASE DATE")
    check("an item with no published epoch has no release date",
          pb.released_date({"ticker": "MARA"}) is None,
          "candidate_dates treats None as no lower bound")

    bad = sum(1 for r, _ in results if r == FAIL)
    print(f"\n{len(results) - bad}/{len(results)} checks passed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Run it to make sure it fails**

```bash
python test_probe_body_dates.py
```

Expected: `ModuleNotFoundError: No module named 'probe_body_dates'`.

- [ ] **Step 3: Write the minimal implementation**

Create `probe_body_dates.py`:

```python
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
```

- [ ] **Step 4: Run the tests and make sure they pass**

```bash
python test_probe_body_dates.py
```

Expected: `16/16 checks passed`, exit 0.

- [ ] **Step 5: Confirm the existing suite still passes**

```bash
python test_earnings_dates.py
```

Expected: `98/98 checks passed`.

- [ ] **Step 6: Commit**

```bash
git add probe_body_dates.py test_probe_body_dates.py
git commit -m "Select every undated announcement, gate and all"
```

---

### Task 2: Probing the bodies and counting the result

**Files:**
- Modify: `probe_body_dates.py`
- Modify: `test_probe_body_dates.py`

**Interfaces:**
- Consumes: rows from `undated_announcements` (Task 1);
  `earnings_dates.candidate_dates(text, released, limit=6) -> list[date]`.
- Produces: `probe_rows(rows, fetch) -> list[dict]` where `fetch(link) -> str|None`,
  adding keys `chars` (int, or None when the fetch failed) and `candidates`
  (list of dates). Also `label_of(row) -> str`, `bucket_of(row) -> str`,
  `summarise(rows) -> {label: {bucket: count}}` with buckets
  `"one"`, `"several"`, `"none"`, `"failed"`.

- [ ] **Step 1: Write the failing tests**

Append these fixtures to `test_probe_body_dates.py`, above `def main():`:

```python
# Bodies keyed by link, so the fake fetcher is a dict lookup. The advance
# notice carries one forward date; the results release carries several,
# which is the shape the scheduled-event gate assumes.
BODIES = {
    "https://example.test/a":
        "MARA will report second quarter results on August 20, 2026 "
        "and host a call the same day.",
    "https://example.test/c":
        "MARA today reported results for the quarter ended June 30, 2026. "
        "A replay is available until September 1, 2026, and the company "
        "will file its report on August 29, 2026.",
}


def fake_fetch(link):
    """Stands in for press_monitor.announcement_body. Returns None for an
    unknown link, exactly as a failed fetch does."""
    return BODIES.get(link)
```

Add these blocks inside `main()`, after the `RELEASE DATE` block and before the
`bad = ...` tally:

```python
    print("\nPROBING")
    probed = pb.probe_rows(
        pb.undated_announcements([ADVANCE_NOTICE, RESULTS_RELEASE],
                                 TODAY, roster=ROSTER),
        fake_fetch)
    by_title = {r["title"]: r for r in probed}
    notice = by_title[ADVANCE_NOTICE["title"]]
    release = by_title[RESULTS_RELEASE["title"]]

    check("every selected row is fetched, gate or no gate", len(probed) == 2)
    check("an advance notice body yields its one forward date",
          notice["candidates"] == [date(2026, 8, 20)],
          f"got {notice['candidates']}")
    check("a results release body yields several",
          len(release["candidates"]) > 1, f"got {release['candidates']}")
    check("a date before the release is excluded",
          date(2026, 6, 30) not in release["candidates"],
          "the quarter ended June 30 is not a forthcoming report date")
    check("chars records the body length", notice["chars"] == len(BODIES[notice["link"]]))

    print("\nA FAILED FETCH IS NOT AN EMPTY BODY")
    failed = pb.probe_rows(
        [{"ticker": "MARA", "title": "t", "link": "https://example.test/gone",
          "released": date(2026, 8, 5), "scheduled": True, "mixed": False}],
        fake_fetch)[0]
    check("a failed fetch leaves chars None", failed["chars"] is None)
    check("a failed fetch yields no candidates", failed["candidates"] == [])
    check("a failed fetch buckets as failed, not none",
          pb.bucket_of(failed) == "failed",
          "a source that did not answer is not a body carrying no date")

    print("\nLABELS AND COUNTS")
    check("scheduled and not results is an advance notice",
          pb.label_of(notice) == "advance notice")
    check("not scheduled is its own label",
          pb.label_of(release) == "not scheduled")
    check("scheduled and results together is mixed",
          pb.label_of({"scheduled": True, "mixed": True}) == "scheduled + results")

    summary = pb.summarise(probed)
    check("one forward date counts as one",
          summary["advance notice"]["one"] == 1, f"got {summary}")
    check("several forward dates count as several",
          summary["not scheduled"]["several"] == 1, f"got {summary}")
    check("a body with no forward date counts as none",
          pb.summarise([{"scheduled": True, "mixed": False, "chars": 500,
                         "candidates": []}])["advance notice"]["none"] == 1)
    check("every bucket is present even at zero",
          set(summary["advance notice"]) == {"one", "several", "none", "failed"},
          "a missing key reads as a gap; a zero reads as a measurement")
```

- [ ] **Step 2: Run them to make sure they fail**

```bash
python test_probe_body_dates.py
```

Expected: `AttributeError: module 'probe_body_dates' has no attribute 'probe_rows'`.

- [ ] **Step 3: Write the minimal implementation**

Append to `probe_body_dates.py`:

```python
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
    """{label: {bucket: count}}, every bucket present even at zero."""
    out = {}
    for row in rows:
        counts = out.setdefault(label_of(row), dict.fromkeys(BUCKETS, 0))
        counts[bucket_of(row)] += 1
    return out
```

- [ ] **Step 4: Run the tests and make sure they pass**

```bash
python test_probe_body_dates.py
```

Expected: `31/31 checks passed`, exit 0.

- [ ] **Step 5: Commit**

```bash
git add probe_body_dates.py test_probe_body_dates.py
git commit -m "Fetch every undated body and count what it offered"
```

---

### Task 3: The output and the workflow

**Files:**
- Modify: `probe_body_dates.py`
- Create: `.github/workflows/probe-body-dates.yml`

**Interfaces:**
- Consumes: `probe_rows`, `summarise`, `label_of`, `bucket_of` (Task 2);
  `press_monitor.collect_ir() -> (items, feed_ok)`;
  `press_monitor.announcement_body(link) -> str|None`.
- Produces: `main() -> int`, and a dispatch-only workflow named
  `Probe body dates`.

- [ ] **Step 1: Write `main()` and the printing**

Append to `probe_body_dates.py`:

```python
def print_rows(rows):
    print("\n" + "=" * 82)
    print("UNDATED ANNOUNCEMENTS  (every one, gate not applied)")
    print("=" * 82)
    print(f"{'ticker':<8}{'released':<12}{'label':<21}{'chars':>7}  candidates")
    print("-" * 82)
    for row in sorted(rows, key=lambda r: (label_of(r), r["ticker"] or "")):
        cands = (", ".join(d.isoformat() for d in row["candidates"])
                 or ("fetch failed" if row["chars"] is None else "none"))
        print(f"{row['ticker'] or '?':<8}"
              f"{(row['released'].isoformat() if row['released'] else '-'):<12}"
              f"{label_of(row):<21}"
              f"{(row['chars'] if row['chars'] is not None else 0):>7}  {cands}")
        print(f"        {(row['title'] or '')[:74]!r}")


def print_summary(summary):
    print("\n" + "=" * 82)
    print("WHAT A RULE WOULD HAVE HAD TO CHOOSE BETWEEN")
    print("=" * 82)
    print(f"{'label':<21}{'one':>6}{'several':>9}{'none':>7}{'failed':>8}")
    print("-" * 82)
    for label in sorted(summary):
        c = summary[label]
        print(f"{label:<21}{c['one']:>6}{c['several']:>9}"
              f"{c['none']:>7}{c['failed']:>8}")
    notice = summary.get("advance notice") or dict.fromkeys(BUCKETS, 0)
    print("\n  A rule is possible if 'advance notice' is concentrated in 'one'.")
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
```

- [ ] **Step 2: Confirm the module still imports and tests still pass**

```bash
python -c "import probe_body_dates" && python test_probe_body_dates.py
```

Expected: no import error (proving `press_monitor` is not pulled in at module
level), then `31/31 checks passed`.

- [ ] **Step 3: Create the workflow**

Create `.github/workflows/probe-body-dates.yml`:

```yaml
name: Probe body dates

# Maintenance tool, not a component. Read-only: collects the same IR sources
# the press monitor already collects, fetches the body of every announcement
# whose title carried no date, prints what dates each body offered, exits.
# No webhook, no state, no commit, no schedule, no secrets.
#
# Run it before writing any rule that reads a reporting date out of a body,
# and after changing recognition in earnings_dates.py. See probe_body_dates.py
# and docs/press-monitor.md.

on:
  workflow_dispatch:

permissions:
  contents: read

jobs:
  probe:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
      - uses: actions/setup-python@v6
        with:
          python-version: "3.12"
      - name: Install dependencies
        run: pip install feedparser requests
      - name: Probe
        timeout-minutes: 10
        env:
          PYTHONUNBUFFERED: "1"
        run: python -u probe_body_dates.py
```

- [ ] **Step 4: Confirm the workflow parses**

```bash
python -c "import yaml,sys; yaml.safe_load(open('.github/workflows/probe-body-dates.yml')); print('ok')"
```

Expected: `ok`. If PyYAML is not installed, skip this step and rely on the
`workflow-list-gate.yml` check after merge.

- [ ] **Step 5: Confirm it takes no secrets**

```bash
grep -n "secrets\." .github/workflows/probe-body-dates.yml
```

Expected: no output. A match here means the read-only contract is broken.

- [ ] **Step 6: Commit**

```bash
git add probe_body_dates.py .github/workflows/probe-body-dates.yml
git commit -m "Print the table, and a workflow to run it by hand"
```

---

### Task 4: Take the body fetch out of the press monitor

**Files:**
- Modify: `press_monitor.py:1852-1896` (the constants and `announcement_body`)
- Modify: `press_monitor.py:1947-1982` (the fetch gate inside `record_disclosed_dates`)
- Modify: `press_monitor.py:1925` and `1992-1996` (the counters and the summary clause)
- Modify: `docs/press-monitor.md`

**Interfaces:**
- Consumes: nothing new.
- Produces: `record_disclosed_dates(items, fresh_uids)` keeps its signature
  unchanged. `fresh_uids` becomes unused inside it; leave the parameter in place
  and say why in the docstring, so the caller does not have to change.

- [ ] **Step 1: Record the before state**

```bash
grep -n "Bodies fetched\|body_seen\|body_with_dates\|announcement_body\|BODY_TIMEOUT\|BODY_MAX_BYTES" press_monitor.py
```

Expected: 12 matches. Save this output; Step 5 confirms it is empty.

- [ ] **Step 2: Delete `announcement_body` and its constants**

Delete `press_monitor.py` lines 1852 to 1896 inclusive: the
`# One body fetch per undated announcement...` comment block, `BODY_TIMEOUT`,
`BODY_MAX_BYTES`, and the whole `announcement_body` function. Leave the two
blank lines that separate the surrounding definitions.

- [ ] **Step 3: Delete the fetch gate and the counters**

In `record_disclosed_dates`:

Delete `body_seen = body_with_dates = 0` from the counters line, leaving:

```python
    counts = {"ok": 0, "no-date": 0, "past": 0, "no-match": 0}
    no_date_examples = []
```

Replace the entire block from `# MEASUREMENT ONLY — nothing here is stored.`
through the closing `f"from {item.get('title')!r}")` with nothing. The
`if reason == "no-date":` branch keeps only its example-collecting half:

```python
        if reason == "no-date":
            if len(no_date_examples) < 3:
                # The informative miss: an announcement whose date is in the
                # body rather than the title. This count is what decides
                # whether a rule over bodies is worth building, and
                # probe_body_dates.py is what measures it — by hand, over
                # every undated announcement at once, rather than from here
                # over the two items that are new in a given run.
                no_date_examples.append(
                    f"{item['ticker']}: {item.get('title')!r}")
```

Then drop the `Bodies fetched` clause from the summary:

```python
    print(f"  earnings dates: {counts['ok']} recorded, {counts['no-date']} "
          f"announcement(s) with no parsable date, {counts['past']} rejected "
          f"as past, {len(companies)} on file.")
```

- [ ] **Step 4: Explain the now-unused parameter**

Add to `record_disclosed_dates`'s docstring, after the existing paragraph:

```python
    `fresh_uids` is unused. It gated a body fetch that has moved to
    probe_body_dates.py, and it is kept in the signature because the
    freshness of an item is the natural thing for any future per-item work
    here to gate on. The caller passes it either way.
```

- [ ] **Step 5: Confirm every trace is gone**

```bash
grep -n "Bodies fetched\|body_seen\|body_with_dates\|announcement_body\|BODY_TIMEOUT\|BODY_MAX_BYTES" press_monitor.py
```

Expected: no output.

- [ ] **Step 6: Confirm nothing else referenced what was deleted**

```bash
grep -rn "announcement_body\|BODY_MAX_BYTES\|BODY_TIMEOUT" --include=*.py . | grep -v "^./probe_body_dates.py"
```

Expected: no output. `probe_body_dates.py` reaches `announcement_body` through
`pm.`, so it is the one legitimate reference and it is excluded here.

- [ ] **Step 7: Confirm the module still compiles and the suite passes**

```bash
python -m py_compile press_monitor.py && python test_earnings_dates.py && python test_probe_body_dates.py
```

Expected: `98/98 checks passed` and `31/31 checks passed`.

- [ ] **Step 8: Document the second maintenance tool**

In `docs/press-monitor.md`, find where `calibrate_staleness.py` is described and
add beside it:

```markdown
`probe_body_dates.py` is the second maintenance tool, dispatched by hand
through **Probe body dates**. It collects the same IR sources, selects every
announcement whose title carried no parsable date, fetches each body and
prints the candidate dates it found, grouped by whether the title named a
forthcoming event. It exists because the same measurement inside the monitor
was gated on items new in a run and fetched nothing for as long as it lived
there: the twenty undated announcements had all been seen already. Read-only,
no secrets, no state, no commit.
```

- [ ] **Step 9: Commit**

```bash
git add press_monitor.py docs/press-monitor.md
git commit -m "Take the body fetch out of the path that posts"
```

---

### Task 5: Verify against live data

**Files:** none modified. This task runs things and records what they said.

**Interfaces:**
- Consumes: everything above.
- Produces: a measured result, and a decision about whether the scheduled-event
  gate discriminates.

**This task is gated on the user approving a merge to `main`.** A brand new
workflow cannot be dispatched from a branch, so the probe cannot run until
`probe-body-dates.yml` is on the default branch. Do not merge without asking.

- [ ] **Step 1: Confirm the press monitor is unharmed, before merging**

```bash
gh workflow run "Press release monitor" --ref body-date-probe -f dry_run=true
```

Wait for it, then read the log:

```bash
gh run list --workflow="Press release monitor" --limit 1 --json databaseId -q '.[0].databaseId'
```

Expected in the log: `earnings dates: 2 recorded, 20 announcement(s) with no
parsable date, 4 rejected as past, 2 on file.` with **no** `Bodies fetched`
clause and **no** `BODY` lines. The three counts must be unchanged from before
the removal; only the fetch has gone.

If the no-date count is not 20, stop. It means Task 4 changed the population
rather than only the fetch.

- [ ] **Step 2: Ask the user to approve the merge**

Report the dry-run result and ask before merging. The merge is what makes the
probe dispatchable.

- [ ] **Step 3: Merge and dispatch**

```bash
git checkout main && git pull && git merge --no-ff body-date-probe && git push
```

Then:

```bash
gh workflow run "Probe body dates" --ref main
```

- [ ] **Step 4: Read the result**

```bash
gh run list --workflow="Probe body dates" --limit 1 --json databaseId,conclusion
```

Then `gh run view <id> --log`. Check three things in order:

1. The selected count matches the monitor's no-date count. If it does not, the
   two populations have drifted and the table is measuring something else.
2. `failed` is zero, or near it. A high failed count means the table is mostly
   about a header problem, not about bodies. See `press_monitor.HOST_HEADERS`.
3. Where `advance notice` concentrates. `one` means a rule is possible;
   `several` means it is a judgement call; `none` means the bodies do not carry
   the date either.

- [ ] **Step 5: Record what was measured**

Add the counts and the date to `docs/press-monitor.md` beside the probe's
description, as `calibrate_staleness.py`'s numbers are recorded in its docstring.
A measurement nobody wrote down has to be taken again.

```bash
git add docs/press-monitor.md
git commit -m "Record what the first body probe measured"
```

- [ ] **Step 6: Report to the user**

State what the table showed, whether the scheduled-event gate discriminated, and
whether a rule for picking a date out of a body is now supportable. That decision
is out of scope here; this task ends by handing over the evidence for it.

---

## Out of scope

Deciding the rule. This plan produces the table. Whether a rule follows from it,
and what that rule is, is the next piece of work and only worth planning once the
numbers exist.
