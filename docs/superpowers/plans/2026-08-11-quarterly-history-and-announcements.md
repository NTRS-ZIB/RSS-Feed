# No Quarterly Projection Without Quarterly History — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the earnings calendar projecting a quarterly cadence for a company whose filings never described one, and start recognising the announcements it was silently missing.

**Architecture:** Three independent changes over data already fetched. `project()` gains an annual-only branch, keyed on the size of the quarterly pool rather than on any inferred company status. `build_message()` stops calling such a row overdue. `earnings_dates.looks_like_announcement()` gains one verb, and the body-fetch gate in `press_monitor` narrows to compensate.

**Tech Stack:** Python 3.12, stdlib only for `earnings_dates.py`. Tests are standalone scripts in `test_earnings_dates.py`, which already imports `earnings_calendar`.

Spec: [2026-08-11-quarterly-history-and-announcements-design.md](../specs/2026-08-11-quarterly-history-and-announcements-design.md)

## Global Constraints

- **Monospace blocks stay at or under 28 characters.** A new column means an existing one goes.
- **Never run `earnings_calendar.py` or `press_monitor.py` locally.** They read secrets that exist only in GitHub Actions and post to live Discord channels. `python test_earnings_dates.py` and `python watchlist.py` are safe.
- **Every dispatch carries `--ref <branch>`.** Without it the dispatch runs `main` and reports a clean pass for code GitHub never loaded. Push the branch first.
- **`earnings_dates.py` is stdlib only and makes no network calls.**
- **The predicate is observable, never inferred.** Key on the count of quarterly filings the component already fetched. Never on "is a foreign private issuer", which is a legal status.
- **"Absence of data" and "the source failed" never share a label or a log line.**
- Commit messages are plain declarative sentences, no `feat:`/`fix:` prefixes, ending with a blank line then `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.

## File Structure

| File | Responsibility |
|---|---|
| `earnings_calendar.py` (modify) | The annual-only projection branch, the overdue exclusion, and the log line naming which companies are treated that way. |
| `earnings_dates.py` (modify) | One entry in `ANNOUNCE_VERBS`. |
| `press_monitor.py` (modify) | The scheduling-word gate on body fetching. |
| `test_earnings_dates.py` (modify) | All new tests. It already imports both `earnings_dates` and `earnings_calendar`. |
| `docs/earnings.md` (modify) | What an annual-only row means and why it is never overdue. |

---

### Task 1: An annual-only projection for a company below the quarterly floor

**Files:**
- Modify: `earnings_calendar.py` (constants near line 48, `next_annual_period_end` new beside `next_period_end` at line 115, `project()` at line 141)
- Modify: `test_earnings_dates.py`

**Interfaces:**
- Consumes: `ANNUAL_FORMS`, `QUARTERLY_FORMS`, `LAG_SAMPLE`, `MIN_PERIODIC_FILINGS`, `roll_to_business_day`, `fiscal_year_end_month` — all already in `earnings_calendar.py`.
- Produces: `MIN_QUARTERLY_FILINGS = 2`; `next_annual_period_end(last_period) -> date`; and `project()` rows that may carry `"annual_only": True`. Tasks 2 and 3 read that key.

- [ ] **Step 1: Write the failing tests**

Add inside `main()` in `test_earnings_dates.py`, immediately before the `bad = ...` line:

```python
    print("\nANNUAL-ONLY PROJECTION")
    import earnings_calendar as ec

    def annual(year, lag_days):
        """One 20-F: period 31 Dec of `year`, filed `lag_days` later."""
        p = date(year, 12, 31)
        return (p, p + timedelta(days=lag_days), "20-F")

    def q(year, month, lag_days=45):
        p = date(year, month, 30)
        return (p, p + timedelta(days=lag_days), "10-Q")

    # BTDR's real shape: five annual filings, no quarterly ones.
    btdr = [annual(y, 111) for y in (2025, 2024, 2023, 2022, 2021)]
    row = ec.project("BTDR", "Bitdeer", btdr)
    check("a company with no quarterly filings still projects",
          row is not None)
    check("it projects the ANNUAL period end, twelve months on",
          row["period"] == date(2026, 12, 31), row["period"])
    check("its lag is the annual lag, not a pooled one", row["lag"] == 111)
    check("it is marked annual_only", row.get("annual_only") is True)
    check("it is not marked degraded, because nothing was degraded",
          row["degraded"] is False)
    check("its kind is annual", row["kind"] == "annual")

    # THE BOUNDARY, and where the first draft of the spec was wrong.
    one_q = btdr + [q(2026, 6)]
    row = ec.project("BTDR", "Bitdeer", one_q)
    check("ONE quarterly filing is still annual-only",
          row.get("annual_only") is True,
          "one filing cannot yield a lag; pooling annual into a quarter end "
          "is the bug this task removes")
    two_q = btdr + [q(2026, 6), q(2026, 3)]
    row = ec.project("BTDR", "Bitdeer", two_q)
    check("TWO quarterly filings flip it to normal treatment",
          not row.get("annual_only"),
          "a real quarterly lag can be measured now")
    check("and the normal projection uses a quarter end",
          row["period"] == date(2026, 9, 30), row["period"])

    check("below the quarterly floor AND under two annual filings: nothing",
          ec.project("X", "X", [annual(2025, 111)]) is None)

    print("\nTHE ANNUAL PERIOD STEP")
    check("twelve months on, not three",
          ec.next_annual_period_end(date(2025, 12, 31)) == date(2026, 12, 31))
    check("29 February falls back to the 28th",
          ec.next_annual_period_end(date(2024, 2, 29)) == date(2025, 2, 28))
```

- [ ] **Step 2: Run to verify it fails**

Run: `python test_earnings_dates.py`
Expected: FAIL, `module 'earnings_calendar' has no attribute 'next_annual_period_end'`

- [ ] **Step 3: Add the constant and the period step**

In `earnings_calendar.py`, beside `MIN_PERIODIC_FILINGS`:

```python
# Below this many QUARTERLY filings, a company gets no quarterly projection at
# all. Two is not a tuning knob: it is the number needed to compute a median
# lag, so below it there is no quarterly cadence to measure and any date
# produced would be assembled from parts that describe no company.
#
# KEYED ON THE POOL, NOT ON HAVING NO 10-Q. The difference only shows at the
# transition and that is where it matters. "Has no 10-Q" flips to normal
# treatment the moment a first 10-Q lands, and normal treatment then finds one
# filing in the quarterly pool, takes the degraded path, and applies an annual
# lag to a quarter end — the exact defect this exists to remove, back for the
# three months until a second one arrives.
MIN_QUARTERLY_FILINGS = 2
```

Beside `next_period_end`:

```python
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
```

- [ ] **Step 4: Add the branch to `project()`**

Replace the body of `project()` between the `MIN_PERIODIC_FILINGS` guard and the `lags = ...` line with:

```python
    annual = [f for f in filings if f[2] in ANNUAL_FORMS]
    quarterly = [f for f in filings if f[2] in QUARTERLY_FORMS]

    last_period = max(rd for rd, _, _ in filings)
    last_filed = max(fd for _, fd, _ in filings)

    # A company whose filings never described a quarterly cadence does not get
    # one invented. It projects its annual cycle, which is real, and nothing
    # else. See MIN_QUARTERLY_FILINGS.
    annual_only = len(quarterly) < MIN_QUARTERLY_FILINGS
    if annual_only:
        if len(annual) < 2:
            return None
        # The last ANNUAL period, not the last of any filing: a stray 10-Q
        # would otherwise set the cycle this projection is built on.
        upcoming = next_annual_period_end(max(rd for rd, _, _ in annual))
        pool, kind, degraded = annual, "annual", False
    else:
        upcoming = next_period_end(last_period)
        fy_month = fiscal_year_end_month(annual)
        is_annual = fy_month is not None and upcoming.month == fy_month
        pool = annual if is_annual else quarterly
        degraded = False
        if len(pool) < 2:
            pool = annual if len(annual) >= 2 else quarterly
            degraded = True
        if len(pool) < 2:
            return None
        kind = "annual" if (is_annual or (degraded and pool is annual)) else "10-Q"
```

and add `"annual_only": annual_only,` to the returned dict, beside `"degraded"`.

Note `degraded` stays `False` for an annual-only row. `degraded` means the
projection fell back to a form type it did not want; an annual-only projection
is using exactly the form type it should, so marking it `?` would tell the
reader its history is thin when it is not.

- [ ] **Step 5: Run to verify it passes**

Run: `python test_earnings_dates.py`
Expected: every check passes, count rises by 11.

- [ ] **Step 6: Commit**

```bash
git add earnings_calendar.py test_earnings_dates.py
git commit -m "Project the annual cycle when there is no quarterly one"
```

---

### Task 2: An annual-only row is never overdue

**Files:**
- Modify: `earnings_calendar.py` (`is_overdue` inside `build_message`, near line 194)
- Modify: `test_earnings_dates.py`

**Interfaces:**
- Consumes: `"annual_only"` from Task 1.
- Produces: nothing later tasks call.

- [ ] **Step 1: Write the failing test**

Add inside `main()` in `test_earnings_dates.py`, before the `bad = ...` line:

```python
    print("\nANNUAL-ONLY IS NEVER OVERDUE")
    long_past = date.today() - timedelta(days=400)

    def crow(label, **kw):
        r = {"label": label, "name": label, "period": date(2025, 12, 31),
             "expected": long_past, "lag": 111, "spread": 4, "kind": "annual",
             "degraded": False, "cik": "0001899123"}
        r.update(kw)
        return r

    text = ec.build_message([crow("BTDR", annual_only=True)])
    check("an annual-only row 400 days past does not reach Overdue",
          "Overdue" not in text, text)
    text = ec.build_message([crow("PROJ")])
    check("an ordinary row 400 days past still does",
          "Overdue" in text and "PROJ" in text)
```

- [ ] **Step 2: Run to verify it fails**

Run: `python test_earnings_dates.py`
Expected: FAIL on "an annual-only row 400 days past does not reach Overdue"

- [ ] **Step 3: Implement**

In `build_message`, replace `is_overdue` with:

```python
    def is_overdue(r):
        # A COMPANY WE CANNOT SEE REPORT IS NEVER REPORTED LATE. Overdue
        # asserts that something should have arrived and has not, and for an
        # annual-only company the only forms this component reads are the ones
        # it barely files — its interim results arrive on a 6-K, which carries
        # no period and is not in PERIODIC_FORMS. The row would go overdue and
        # stay there for a quarter, which is what it did for 22 days before
        # this. A claim we cannot check does not belong in the post.
        #
        # This is a real loss: if such a company goes genuinely silent, nothing
        # here says so. Its releases still reach the press channel.
        if r.get("annual_only"):
            return False
        # OVERDUE_GRACE exists to allow for the spread in OUR projection. A
        # company's own announced date has no spread to allow for, so it gets
        # none: announced the 12th and nothing filed by the 13th is late.
        grace = 0 if r.get("disclosed") else OVERDUE_GRACE
        return r["expected"] < today - timedelta(days=grace)
```

- [ ] **Step 4: Run to verify it passes**

Run: `python test_earnings_dates.py`
Expected: every check passes, count rises by 2.

- [ ] **Step 5: Commit**

```bash
git add earnings_calendar.py test_earnings_dates.py
git commit -m "Never call a company late when we cannot see it arrive"
```

---

### Task 3: Say which companies are being projected annually

**Files:**
- Modify: `earnings_calendar.py` (`main()`, after the rows are built and before `build_message` is called)

**Interfaces:**
- Consumes: `"annual_only"` from Task 1.
- Produces: nothing.

- [ ] **Step 1: Add the line**

In `main()`, after the loop that appends to `rows` and before `text = build_message(rows)`, add:

```python
    annual_only = [r["label"] for r in rows if r.get("annual_only")]
    if annual_only:
        print(f"\nProjected annually, with no quarterly estimate and no "
              f"overdue: {', '.join(annual_only)}. Each files fewer than "
              f"{MIN_QUARTERLY_FILINGS} quarterly reports, so no quarterly "
              f"cadence can be measured.")
    else:
        print("\nNo company is below the quarterly filing floor.")
```

Both branches print, deliberately. A line that appears only when something is
unusual is indistinguishable from a check that did not run, and the day a
company changes treatment is exactly the day you want that visible.

- [ ] **Step 2: Verify by dispatch**

The branch must be pushed first.

```bash
gh workflow run "Earnings calendar" --ref "$(git rev-parse --abbrev-ref HEAD)" -f dry_run=true
```

Expected: `Projected annually, ...: BTDR.` and BTDR absent from the Overdue
section, which should now be empty or gone. Every other company's row must be
unchanged from the previous run — that is the check that matters, because
Task 1 touched the path all nineteen flow through.

- [ ] **Step 3: Commit**

```bash
git add earnings_calendar.py
git commit -m "Name the companies projected annually, every run"
```

---

### Task 4: Recognise "announces"

**Files:**
- Modify: `earnings_dates.py` (`ANNOUNCE_VERBS`, line 34)
- Modify: `test_earnings_dates.py`

**Interfaces:**
- Consumes: `looks_like_announcement`, `extract` from the existing module.
- Produces: no signature change.

- [ ] **Step 1: Write the failing tests**

Add inside `main()` in `test_earnings_dates.py`, before the `bad = ...` line:

```python
    print("\nBARE \"ANNOUNCES\"")
    BTDR_REAL = ("Bitdeer Announces Second Quarter 2026 Earnings Conference "
                 "Call for August 10th 2026")
    check("BTDR's real advance notice is recognised",
          ed.looks_like_announcement(BTDR_REAL))
    when, reason = ed.extract(BTDR_REAL, date(2026, 8, 1), date(2026, 8, 1))
    check("and its date parses straight from the title",
          when == date(2026, 8, 10) and reason == "ok", f"{when} {reason}")
    check("an operations update is still not an announcement",
          not ed.looks_like_announcement(
              "Bitdeer Announces June 2026 Production and Operations Update"),
          "no results or earnings word")
    check("a financing release is still not an announcement",
          not ed.looks_like_announcement(
              "Bitdeer Announces $4.7 Billion, 16-Year AI/HPC Data Center "
              "Lease for Tydal, Norway"))
    # Now recognised, and that is intended: the date guard is the real filter.
    RESULTS = "Galaxy Announces Second Quarter 2026 Financial Results"
    check("a results release is now recognised", ed.looks_like_announcement(RESULTS))
    when, reason = ed.extract(RESULTS, date(2026, 8, 11), date(2026, 8, 11))
    check("but carries no date, so it stores nothing",
          when is None and reason == "no-date", f"{when} {reason}")
```

- [ ] **Step 2: Run to verify it fails**

Run: `python test_earnings_dates.py`
Expected: FAIL on "BTDR's real advance notice is recognised"

- [ ] **Step 3: Implement**

Replace the `ANNOUNCE_VERBS` tuple with:

```python
ANNOUNCE_VERBS = ("to report", "to announce", "to release", "announces",
                  "schedules", "sets date")
```

`"announces date"` and `"announces the date"` are removed because bare
`"announces"` subsumes both. Add above the tuple:

```python
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
```

- [ ] **Step 4: Run to verify it passes**

Run: `python test_earnings_dates.py`
Expected: every check passes, count rises by 6.

- [ ] **Step 5: Commit**

```bash
git add earnings_dates.py test_earnings_dates.py
git commit -m "Recognise a bare announces, which is how BTDR phrases it"
```

---

### Task 5: The body-fetch gate requires a scheduled event

**Files:**
- Modify: `earnings_dates.py` (beside `RESULTS_WORDS`)
- Modify: `press_monitor.py` (`record_disclosed_dates`, the fetch gate near line 1955)
- Modify: `test_earnings_dates.py`

**Interfaces:**
- Consumes: nothing from Task 4 beyond the widened recognition it compensates for.
- Produces: `names_a_scheduled_event(title) -> bool` in `earnings_dates.py`.

- [ ] **Step 1: Write the failing tests**

Add inside `main()` in `test_earnings_dates.py`, before the `bad = ...` line:

```python
    print("\nSCHEDULED-EVENT GATE")
    check("an advance notice names a scheduled event",
          ed.names_a_scheduled_event(BTDR_REAL))
    check("so does a webcast announcement",
          ed.names_a_scheduled_event(
              "Company Announces Q2 Earnings Release and Webcast"))
    check("a results release does NOT",
          not ed.names_a_scheduled_event(RESULTS),
          "its body is dense with dates and would poison the measurement")
    check("nor does a bare results headline",
          not ed.names_a_scheduled_event(
              "American Bitcoin Reports Second Quarter 2026 Results"))
```

- [ ] **Step 2: Run to verify it fails**

Run: `python test_earnings_dates.py`
Expected: FAIL, `module 'earnings_dates' has no attribute 'names_a_scheduled_event'`

- [ ] **Step 3: Implement the predicate**

In `earnings_dates.py`, beside `RESULTS_WORDS`:

```python
# Words that name a FORTHCOMING EVENT. An advance notice schedules something;
# a results release reports something. This gates body FETCHING only, never
# storing, so a phrasing missing from this list costs one measurement sample
# and nothing else.
SCHEDULED_EVENT_WORDS = ("conference call", "webcast", "call for",
                         "schedules", "to be held", "will host")


def names_a_scheduled_event(title):
    """Does this title announce a forthcoming event rather than report one?"""
    t = (title or "").lower()
    return any(w in t for w in SCHEDULED_EVENT_WORDS)
```

- [ ] **Step 4: Gate the fetch**

In `press_monitor.record_disclosed_dates`, change the fetch condition from:

```python
            if item.get("uid") in fresh_uids:
```

to:

```python
            # Widening recognition to bare "announces" made results releases
            # recognised and undated, and A RESULTS RELEASE BODY IS DENSE WITH
            # DATES — the period covered, prior-year comparatives, the figures
            # themselves. Fetching those would poison the very measurement
            # this body probe exists to produce.
            if (item.get("uid") in fresh_uids
                    and ed.names_a_scheduled_event(item.get("title"))):
```

- [ ] **Step 5: Run to verify it passes**

Run: `python test_earnings_dates.py`
Expected: every check passes, count rises by 4.

- [ ] **Step 6: Commit**

```bash
git add earnings_dates.py press_monitor.py test_earnings_dates.py
git commit -m "Fetch a body only when the title names a scheduled event"
```

---

### Task 6: Verify against live data, and write down what changed

**Files:**
- Modify: `docs/earnings.md`

**Interfaces:**
- Consumes: everything above.
- Produces: nothing.

- [ ] **Step 1: Run the full local suite**

```bash
python test_earnings_dates.py
python watchlist.py
python test_loop_state.py
python test_loop_verdict.py
python test_loop_approval.py
python score_gate.py
```

Expected: every script exits 0. Record the counts.

- [ ] **Step 2: Dispatch both components**

```bash
gh workflow run "Earnings calendar" --ref "$(git rev-parse --abbrev-ref HEAD)" -f dry_run=true
gh workflow run "Press release monitor" --ref "$(git rev-parse --abbrev-ref HEAD)" -f dry_run=true
```

From the calendar run, confirm all three: BTDR appears under "later" with a
2027 annual date and a `*` marker rather than `?`; the Overdue section no
longer contains it; **and every other company's row is identical to the
previous run.** The third is the one that can fail silently.

From the press monitor run, confirm the `earnings dates:` summary still
reports and that the recorded count has not fallen. A rise in `no-date` is
expected from Task 4 and is not a regression.

- [ ] **Step 3: Update the docs**

In `docs/earnings.md`, add to the markers table, below the `!` row:

```markdown
| `*` on a 2027-ish date | Projected annually, because the company files fewer than two quarterly reports. It gets no quarterly estimate and is never marked overdue. |
```

And add to Known quirks:

```markdown
- **A company below the quarterly filing floor is never reported overdue, and
  that is deliberate.** Marking something overdue claims it should have
  arrived and has not. For a company that reports interim results on a 6-K,
  this component cannot see it arrive at all: a 6-K is not in `PERIODIC_FORMS`
  and carries no period covered, since `reportDate` equals `filingDate` on
  every one of them. BTDR's row read "est 20 Jul" and climbed for 22 days on
  exactly that. The cost is real — if such a company goes genuinely silent
  nothing here will say so — and it is preferred to a claim that cannot be
  checked. Its releases still reach the press channel.
```

- [ ] **Step 4: Commit**

```bash
git add docs/earnings.md
git commit -m "Record what an annually projected row means"
```

---

### Task 7: An Announced section for dates that cannot be overlaid

Added 2026-08-11 after Task 3's dispatch exposed an interaction Tasks 1 and 4
create between them. **Task 4 widened the intake and Task 1 closed the outlet.**

`apply()` overlays a stored date only when it falls after the period end being
projected — a rule written so a stale date expires by itself once a company
files and its period moves on. An annual-only row projects a period end up to
twelve months out, so a quarterly announcement always falls before it and is
discarded. The live run showed exactly this:

```
DGXX: stored date 2026-08-14 is not after the period end 2026-12-31 being
projected; it belongs to a period already reported
```

DGXX published that date. BTDR's Q3 notice will meet the same fate. These are
the two companies whose projections are worst and the ones the disclosed-date
feature was built to help.

**Overlaying it anyway was rejected, with a measured reason.** Applying an
August date to a December-period row puts that row in the upcoming block with a
period end no other row shares, which flips the table to mixed-period mode: the
`· P/E Jun 2026` header goes, every row loses its weekday to buy a period
column, and the row prints as `DGXX! 14 Aug 3d Dec` — an August date on a
December-period report. One applied date degrades every other row and prints a
self-contradiction.

So the announced date gets its own block, where it can be stated as what it is.

**Files:**
- Modify: `earnings_dates.py`
- Modify: `earnings_calendar.py`
- Modify: `test_earnings_dates.py`

**Interfaces:**
- Consumes: `apply(rows, companies, today)`, `parse_iso`, and rows carrying
  `annual_only` from Task 1.
- Produces: `announced_elsewhere(rows, companies, today) -> list[tuple[str, date]]`
  in `earnings_dates.py`, sorted by date, and an `Announced` block in
  `build_message`.

- [ ] **Step 1: Write the failing tests**

Add inside `main()` in `test_earnings_dates.py`, before the `bad = ...` line:

```python
    print("\nANNOUNCED BUT NOT OVERLAID")
    soon = date.today() + timedelta(days=3)
    store = {"0001854368": {"ticker": "DGXX", "date": soon.isoformat(),
                            "source_uid": "u", "source_title": "t",
                            "source_published": "2026-07-20T00:00:00+00:00"}}

    # An annual-only row: its period end is a year out, so apply() refuses.
    arow = {"label": "DGXX", "name": "Digi Power X", "cik": "0001854368",
            "period": date.today() + timedelta(days=200),
            "expected": date.today() + timedelta(days=290), "lag": 90,
            "spread": 40, "kind": "annual", "degraded": False,
            "annual_only": True}
    rows, applied, _ = ed.apply([dict(arow)], store, date.today())
    check("apply still refuses to overlay it", applied == 0)
    got = ed.announced_elsewhere([dict(arow)], store, date.today())
    check("but the date is surfaced separately",
          got == [("DGXX", soon)], got)

    # A row where the date WAS overlaid must not also appear in the section.
    qrow = dict(arow, period=date.today() - timedelta(days=10),
                annual_only=False)
    rows, applied, _ = ed.apply([dict(qrow)], store, date.today())
    check("a date that was overlaid is applied", applied == 1)
    check("and is NOT repeated in the section",
          ed.announced_elsewhere([dict(qrow)], store, date.today()) == [],
          "it is already on the row")

    past = {"0001854368": dict(store["0001854368"],
                               date=(date.today() - timedelta(days=5)).isoformat())}
    check("a date already past is not surfaced",
          ed.announced_elsewhere([dict(arow)], past, date.today()) == [],
          "the section is about what is coming")

    text = ec.build_message([dict(arow)], announced=[("DGXX", soon)])
    check("the section renders with its own heading",
          "Announced" in text and "DGXX" in text, text)
    widest = max(len(l) for l in text.splitlines())
    check("and nothing in the block exceeds 28 characters",
          widest <= 28, widest)
```

- [ ] **Step 2: Run to verify it fails**

Run: `python test_earnings_dates.py`
Expected: FAIL, `module 'earnings_dates' has no attribute 'announced_elsewhere'`

- [ ] **Step 3: Implement the collector**

Append to `earnings_dates.py`:

```python
def announced_elsewhere(rows, companies, today):
    """Announced dates that are real, still ahead, and NOT on any row.

    `apply()` overlays a stored date only when it falls after the period end
    being projected, so a stale one expires by itself. An annual-only row's
    period end is up to twelve months out, so a QUARTERLY announcement always
    falls before it and is refused — correctly, because that row is about the
    annual filing and an August date on it would be a claim about the wrong
    report.

    The date is still true and still useful, so it is surfaced here instead of
    being dropped to a log line. Returns [(label, date), ...] sorted by date.
    """
    applied_ciks = {r.get("cik") for r in rows if r.get("disclosed")}
    out = []
    for r in rows:
        cik = r.get("cik")
        if cik in applied_ciks:
            continue
        rec = companies.get(cik)
        if not isinstance(rec, dict):
            continue
        when = parse_iso(rec.get("date"))
        if when is None or when < today:
            continue
        out.append((r["label"], when))
    return sorted(out, key=lambda t: t[1])
```

Note it takes rows AFTER `apply()` has run, so `disclosed` marks the ones
already shown. Call it in that order.

- [ ] **Step 4: Render the section**

Change `build_message(rows)` to `build_message(rows, announced=None)`, and add
after the overdue block and before the `later` block:

```python
    if announced:
        lines.append("")
        # Its own block, because these dates describe a DIFFERENT report from
        # the row that company has above. Overlaying one would put a row in
        # the upcoming table with a period end no other row shares, which
        # flips the whole table to mixed-period: the header loses its P/E
        # line, every row drops its weekday to buy a period column, and the
        # row itself prints an August date against a December period.
        lines.append("Announced")
        lines.append("-" * 26)
        for label, when in announced:
            days = (when - today).days
            lines.append(f"{label:<4}  {when:%a %d %b}{days:>4}d")
```

Add to the key block, beside the other conditional lines:

```python
    if announced:
        key.append("announced, not projected")
```

- [ ] **Step 5: Wire it in `main()`**

After the `ed.apply(...)` call and its note printing, add:

```python
    announced = ed.announced_elsewhere(rows, disclosed, date.today())
    if announced:
        print(f"{len(announced)} announced date(s) shown separately, because "
              f"the row for that company projects a different report: "
              f"{', '.join(f'{l} {d}' for l, d in announced)}")
```

and pass it through: `text = build_message(rows, announced=announced)`.

- [ ] **Step 6: Correct the false clause in `apply()`'s note**

The rejection note currently ends "it belongs to a period already reported",
which is false: DGXX's 2026-08-14 is a forthcoming Q2 event that has not been
reported. Asserting a cause the data does not support is the mistake this repo
records against `short_interest.py`. Replace that clause so the note states the
comparison and stops, and says the date is surfaced separately instead:

```python
            notes.append(f"{r['label']}: stored date {when} is not after the "
                         f"period end {r['period']} being projected, so it "
                         f"describes a different report than this row; shown "
                         f"in the Announced section instead")
```

- [ ] **Step 7: Run to verify it passes**

Run: `python test_earnings_dates.py`
Expected: every check passes, count rises by 7.

- [ ] **Step 8: Commit**

```bash
git add earnings_dates.py earnings_calendar.py test_earnings_dates.py
git commit -m "Show an announced date that belongs to no row"
```

---

## Self-review

**Spec coverage.** Change 1 of the spec is Tasks 1 to 3: the annual-only
branch, the twelve-month period step, the overdue exclusion, and the log line
announcing the flip. Change 2 is Task 4. Change 3 is Task 5. The spec's
verification section is Task 6, which includes the "every other row unchanged"
check the spec calls the one that matters. The boundary test the spec demands —
one quarterly filing still annual-only, two flipping over — is Task 1 Step 1.

**Not covered, deliberately.** Identifying a results 6-K and projecting
quarterly reporting for a 6-K filer. The spec puts both out of scope and gives
the measurement that closes them off.

**Type consistency.** `annual_only` is set in Task 1 and read in Tasks 2 and 3
under that exact name. `next_annual_period_end` is defined in Task 1 and tested
there. `names_a_scheduled_event` is defined in Task 5 and used in the same
task. `MIN_QUARTERLY_FILINGS` is defined in Task 1 and quoted in Task 3's log
line. `crow()` in Task 2's test supplies `cik`, which `apply()` expects on a
row, so `build_message` can be driven without the overlay.
