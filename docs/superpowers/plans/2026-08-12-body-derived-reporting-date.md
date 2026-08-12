# Body-derived reporting date Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Store a company's reporting date when it appears in the body of an
announcement rather than in the title, and show it as a date we read rather than
one the company put in its headline.

**Architecture:** The decision stays pure and testable in `earnings_dates.py`
(`date_from_body`), the network call stays in `press_monitor.py` behind a
four-condition gate, and the store records provenance in one new key. The
calendar reads that key to pick a marker and to decide overdue grace.

**Tech Stack:** Python 3.12, stdlib plus `requests`. Tests are standalone scripts
with the repo's own `check()` harness printing `N/M checks passed`, not pytest.

## Global Constraints

- **DO NOT BUMP `earnings_dates.SCHEMA`.** It is `1`. `load()` returns
  `({}, "unreadable")` when the file's schema does not match, and
  `record_disclosed_dates` then **skips the write entirely** to avoid clobbering
  a corrupt file. Bumping it would make the live `earnings_dates.json` unreadable
  on the first run after deploy and freeze the store permanently, visible only in
  a log line. The new `"source"` key is additive and needs no bump.
- **Monospace blocks stay at or under 28 characters.** The calendar row is
  currently 25. Adding a column is forbidden; changing a marker character is not.
- **Do not run the component scripts.** `press_monitor.py`, `earnings_calendar.py`
  and similar read secrets that exist only in GitHub Actions and several post to
  live Discord. **Do not run `probe_body_dates.py`** either; its `main()` makes
  real network calls. Safe: `python test_earnings_dates.py`,
  `python test_probe_body_dates.py`, `python watchlist.py`, `python -m py_compile`.
- **This working copy has no outbound network and no `feedparser`.** Nothing can
  be verified by fetching locally; use a dispatched workflow.
- **Every workflow dispatch carries `--ref <branch>`.** Without it it runs `main`.
- **`earnings_dates.json`, `state.json` and `snapshot.json` are outputs.** Never
  edit, delete, reformat or commit one locally.
- **A record with no `"source"` key means `"title"`.** Every date stored before
  this change came from a headline. Nothing is migrated.
- Suite baselines before this plan: `test_earnings_dates.py` **101/101**,
  `test_probe_body_dates.py` **32/32**.

## File Structure

| File | Responsibility |
|---|---|
| Modify `earnings_dates.py` | `date_from_body` (the pure rule), `upsert` gains a `source` parameter, `apply` carries provenance onto the row. |
| Modify `test_earnings_dates.py` | Tests for all of the above and for the calendar behaviour. |
| Modify `press_monitor.py` | The four-condition gate, the fetch, the counters and the log line. `fresh_uids` returns. |
| Modify `earnings_calendar.py` | The `+` marker, its key line, the blanking-key line, and the overdue grace branch. |
| Modify `docs/earnings.md` | Document the marker and the rule for a reader of the post. |

`probe_body_dates.py` is NOT modified. It deliberately shows every candidate
rather than applying the rule, which is what makes it a measurement.

---

### Task 1: The store records where a date came from

**Files:**
- Modify: `earnings_dates.py` (`upsert` at line 214, `apply` at line 244)
- Modify: `test_earnings_dates.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `upsert(companies, cik, ticker, when, uid, title, published, source="title")`
  writing `"source": source` into the record. `apply()` sets
  `r["disclosed_source"]` to the record's `source`, or `"title"` when the key is
  absent. Tasks 2 and 3 both depend on these exact names.

- [ ] **Step 1: Write the failing tests**

In `test_earnings_dates.py`, find the `THE OVERLAY` section (it begins
`print("\nTHE OVERLAY")`). Add these checks at the end of that section, after the
existing overlay checks and before the next `print("\n...")` heading:

```python
    print("\nWHERE A STORED DATE CAME FROM")
    fresh = {}
    ed.upsert(fresh, "0001218683", "BGDE", date(2026, 9, 1), "u1", "t1",
              "2026-08-01T00:00:00+00:00")
    check("a date defaults to source 'title'",
          fresh["0001218683"]["source"] == "title",
          "every date stored before this change came from a headline")

    body = {}
    ed.upsert(body, "0001218683", "BGDE", date(2026, 9, 1), "u1", "t1",
              "2026-08-01T00:00:00+00:00", source="body")
    check("a body-derived date records source 'body'",
          body["0001218683"]["source"] == "body")

    # A record written before this change has no "source" key at all. Its
    # absence is not unknown provenance — it is a title, because that was
    # the only way a date could be stored.
    LEGACY = {"0001218683": {"ticker": "BGDE", "date": "2026-09-01",
                             "source_uid": "u", "source_title": "t",
                             "source_published": "2026-08-01T00:00:00+00:00"}}
    lrows = [row("BGDE", "0001218683", date(2026, 6, 30), date(2026, 9, 5))]
    lrows, lapplied, _ = ed.apply(lrows, LEGACY, date(2026, 8, 12))
    check("a legacy record with no source key applies", lapplied == 1)
    check("a legacy record reads as a title", lrows[0]["disclosed_source"] == "title",
          "absence of the key is a title, not an unknown")

    BODYSTORE = {"0001218683": {"ticker": "BGDE", "date": "2026-09-01",
                                "source_uid": "u", "source_title": "t",
                                "source_published": "2026-08-01T00:00:00+00:00",
                                "source": "body"}}
    brows = [row("BGDE", "0001218683", date(2026, 6, 30), date(2026, 9, 5))]
    brows, _, _ = ed.apply(brows, BODYSTORE, date(2026, 8, 12))
    check("a body record carries its provenance onto the row",
          brows[0]["disclosed_source"] == "body")
    check("provenance rides alongside disclosed, not instead of it",
          brows[0]["disclosed"] is True)
```

The local helper `row(label, cik, period, expected, spread=6)` is already defined
in that section; reuse it rather than defining another.

- [ ] **Step 2: Run them to verify they fail**

```bash
python test_earnings_dates.py
```

Expected: FAIL on `a date defaults to source 'title'` with a `KeyError`, and
FAIL on the `disclosed_source` checks.

- [ ] **Step 3: Add the parameter and the key**

In `earnings_dates.py`, change `upsert`'s signature and record:

```python
def upsert(companies, cik, ticker, when, uid, title, published,
           source="title"):
```

Add to its docstring, after the existing paragraphs:

```
    `source` is "title" when the date was in the headline and "body" when it
    was read out of the release text. It records how much of the reading was
    ours: the company announced the date either way. PROVENANCE NEVER
    DECIDES WHICH RECORD WINS — that is the release timestamp's job above,
    and a body-derived date from a later release supersedes a title-derived
    one from an earlier release exactly as it should.
```

And in the record it writes:

```python
    companies[cik] = {
        "ticker": ticker,
        "date": when.isoformat(),
        "source_uid": uid,
        "source_title": title,
        "source_published": published,
        "source": source,
    }
```

- [ ] **Step 4: Carry it onto the row in `apply`**

In `apply()`, beside the existing `r["disclosed"] = True`:

```python
        r["projected"] = r["expected"]
        r["expected"] = when
        r["disclosed"] = True
        # Absent means "title": every date stored before provenance existed
        # came from a headline, so the default is a fact about the old
        # records rather than a guess about them.
        r["disclosed_source"] = rec.get("source") or "title"
        applied += 1
```

- [ ] **Step 5: Run the tests**

```bash
python test_earnings_dates.py
```

Expected: `107/107 checks passed`.

- [ ] **Step 6: Commit**

```bash
git add earnings_dates.py test_earnings_dates.py
git commit -m "Record whether a stored date came from a title or a body"
```

---

### Task 2: The calendar marks a body-derived row and keeps its grace

**Files:**
- Modify: `earnings_calendar.py` (`is_overdue`, `marker`, and the key block)
- Modify: `test_earnings_dates.py`

**Interfaces:**
- Consumes: `r["disclosed_source"]` from Task 1, `"title"` or `"body"`.
- Produces: no new functions. `marker(r)` returns `"+"` for a body-derived
  disclosed row and `"!"` for a title-derived one.

- [ ] **Step 1: Write the failing tests**

In `test_earnings_dates.py`, find the `THE DISPLAY HALF (build_message)` section
and its local helper `calendar_row(label, expected, spread=6, disclosed=False, degraded=False)`.
**Extend that helper** to take provenance, since later checks need it:

```python
    def calendar_row(label, expected, spread=6, disclosed=False,
                     degraded=False, source="title"):
        r = {"label": label, "cik": "0000000000",
             "period": date(2026, 6, 30), "expected": expected,
             "spread": spread, "kind": "10-Q", "degraded": degraded,
             "disclosed": disclosed}
        if disclosed:
            r["disclosed_source"] = source
        return r
```

Then add these checks at the end of that section:

```python
    print("\nA BODY-DERIVED DATE IS MARKED APART")
    btext = ec.build_message([calendar_row("WYFI", today + timedelta(days=5),
                                           disclosed=True, source="body")])
    check("a body-derived row is marked +", "WYFI+" in btext, btext)
    check("a body-derived row is not marked !", "WYFI!" not in btext, btext)
    check("the key explains +", "+ date read from body" in btext, btext)
    check("the key line fits the 28-char ceiling",
          max(len(l) for l in btext.splitlines()) <= 28, btext)

    ttext = ec.build_message([calendar_row("BGDE", today + timedelta(days=5),
                                           disclosed=True, source="title")])
    check("a title-derived row is still marked !", "BGDE!" in ttext, ttext)
    check("the + key is absent when no + row is shown",
          "+ date read from body" not in ttext, ttext)

    # THE ONE THAT MATTERS. Same past date, same everything else: the
    # company's own headline date is late immediately, while a date we read
    # out of prose gets the projection grace, because the uncertainty is
    # OURS. If this ever collapses to one behaviour, a misreading becomes an
    # accusation that a company missed its own date.
    late = today - timedelta(days=3)
    otext = ec.build_message([calendar_row("BGDE", late, disclosed=True,
                                           source="title")])
    check("a title-derived row past its date is overdue at once",
          "Overdue" in otext, otext)
    gtext = ec.build_message([calendar_row("WYFI", late, disclosed=True,
                                           source="body")])
    check("a body-derived row past its date keeps the grace",
          "Overdue" not in gtext, gtext)
    vlate = today - timedelta(days=ec.OVERDUE_GRACE + 1)
    vtext = ec.build_message([calendar_row("WYFI", vlate, disclosed=True,
                                           source="body")])
    check("a body-derived row is overdue once the grace runs out",
          "Overdue" in vtext, vtext)
```

`timedelta` is already imported in this file. Confirm before running; if it is
not, add it to the existing `from datetime import ...` line.

- [ ] **Step 2: Run them to verify they fail**

```bash
python test_earnings_dates.py
```

Expected: FAIL on `a body-derived row is marked +` (it renders `WYFI!`), on the
`+` key check, and on `a body-derived row past its date keeps the grace` (it is
overdue immediately).

- [ ] **Step 3: Change the marker**

In `earnings_calendar.py`'s `marker(r)`, replace the disclosed branch:

```python
    def marker(r):
        # First, and it outranks the rest: `*`, `~` and `?` all describe a
        # projection, and this row no longer has one.
        if r.get("disclosed"):
            # `+` is a date the company announced in the body of a release
            # and we parsed out; `!` is one it put in the headline. The
            # company stated both. What differs is how much of the reading
            # was ours, and the reader is entitled to know which they are
            # looking at. `?` would read better than `+` and is taken.
            return "+" if r.get("disclosed_source") == "body" else "!"
        if r["degraded"]:
            return "?"
```

Leave the rest of the function unchanged.

- [ ] **Step 4: Change the grace**

In `is_overdue`, replace the `grace` line and extend the comment above it:

```python
        # OVERDUE_GRACE exists to allow for the spread in OUR projection. A
        # company's own announced date has no spread to allow for, so it gets
        # none: announced the 12th and nothing filed by the 13th is late.
        #
        # A `+` row is the company's own date too, but read out of prose by a
        # rule measured over THREE companies. The uncertainty there is ours,
        # not theirs, so it keeps the grace: a misreading must not accuse a
        # company of missing a date it never gave us. This reuses a constant
        # justified for projection spread to cover reading risk instead,
        # which is deliberate and is recorded where OVERDUE_GRACE is defined.
        grace = 0 if r.get("disclosed_source") == "title" else OVERDUE_GRACE
        return r["expected"] < today - timedelta(days=grace)
```

Note the inversion: the test is now on `disclosed_source == "title"` rather than
on `disclosed`, so a projected row (which has neither key) still gets the grace.

- [ ] **Step 5: Note the reuse where the constant is defined**

At `OVERDUE_GRACE = 10` in `earnings_calendar.py`, append to whatever comment is
already there (add one if there is none):

```python
# Also used for a `+` row, whose date the company announced but we parsed
# out of a release body. That is reading risk rather than projection
# spread; the effect wanted is the same, so the constant is shared rather
# than duplicated. See is_overdue.
```

- [ ] **Step 6: Add the key line and fix the blanking line**

In the key block, add the `+` entry after the `!` entry:

```python
    if "!" in shown:
        key.append("! announced by company")
    if "+" in shown:
        key.append("+ date read from body")
```

Then replace the blanking line, which currently names only `!`:

```python
        has_spread = any(not r.get("disclosed") for r in rendered)
        if has_spread:
            lines.append("last col = +/- spread")
            # Both announced markers blank that column, so the note must
            # name whichever are actually on screen. Naming `!` alone was
            # correct only while it was the only one.
            blanking = [m for m in ("!", "+") if m in shown]
            if blanking:
                lines.append(f"(blank on {' and '.join(blanking)} rows)")
```

- [ ] **Step 7: Run the tests**

```bash
python test_earnings_dates.py && python test_probe_body_dates.py
```

Expected: `116/116 checks passed` and `32/32 checks passed`.

- [ ] **Step 8: Commit**

```bash
git add earnings_calendar.py test_earnings_dates.py
git commit -m "Mark a body-derived date apart, and let it keep its grace"
```

---

### Task 3: The rule, and the fetch that feeds it

**Files:**
- Modify: `earnings_dates.py` (new `date_from_body`, placed after `candidate_dates`)
- Modify: `test_earnings_dates.py`
- Modify: `press_monitor.py` (`record_disclosed_dates`, and its call site)

**Interfaces:**
- Consumes: `candidate_dates(text, released, limit=6)` and
  `upsert(..., source="title")` from Task 1.
- Produces: `date_from_body(text, released, today) -> (date|None, reason)` where
  reason is `"ok"`, `"several"`, `"no-candidates"` or `"past"`.
  `record_disclosed_dates(items, fresh_uids)` regains its second parameter.

- [ ] **Step 1: Write the failing tests for the rule**

Add a new section to `test_earnings_dates.py`, immediately after the
`BODY DATE CANDIDATES` section:

```python
    print("\nTHE RULE OVER A BODY")
    REL = date(2026, 8, 4)
    NOW = date(2026, 8, 5)
    check("exactly one forward date is the date",
          ed.date_from_body("will report on August 12, 2026", REL, NOW)
          == (date(2026, 8, 12), "ok"))
    check("several candidates yield nothing",
          ed.date_from_body("report August 12, 2026, replay to August 19, 2026",
                            REL, NOW) == (None, "several"),
          "choosing between them is the guess this rule exists to refuse")
    check("no candidate yields nothing",
          ed.date_from_body("no dates here at all", REL, NOW)
          == (None, "no-candidates"))
    check("an empty body yields nothing",
          ed.date_from_body("", REL, NOW) == (None, "no-candidates"))
    check("a body that offers only its own dateline yields nothing",
          ed.date_from_body("MIAMI, Aug. 4, 2026 -- nothing else", REL, NOW)
          == (None, "no-candidates"),
          "candidate_dates already drops the dateline")
    check("a single past date is rejected, not stored",
          ed.date_from_body("reported on August 1, 2026", date(2026, 7, 1),
                            date(2026, 8, 20)) == (None, "past"),
          "the guard is on our reading, not on the company")
    check("several and no-candidates are different reasons",
          ed.date_from_body("a August 12, 2026 b August 19, 2026", REL, NOW)[1]
          != ed.date_from_body("nothing", REL, NOW)[1],
          "one means we could not choose; the other means there was nothing")
```

- [ ] **Step 2: Run them to verify they fail**

```bash
python test_earnings_dates.py
```

Expected: FAIL with `AttributeError: module 'earnings_dates' has no attribute 'date_from_body'`.

- [ ] **Step 3: Write the rule**

In `earnings_dates.py`, directly after `candidate_dates`:

```python
def date_from_body(text, released, today):
    """(date, reason) for the ONE forward date a body offers, or (None, why).

    reason is "ok", "several", "no-candidates" or "past".

    EXACTLY ONE IS THE WHOLE RULE. A body carrying several forward dates
    offers no way to tell the report date from the call date, the replay
    expiry or a period end, and picking one is the guess this repo has paid
    for three times. Measured 2026-08-12 over the twelve announcements whose
    titles name a scheduled event: seven carried exactly one forward date
    and none of those was ambiguous, but they came from only THREE
    companies, so the rule is built to yield nothing rather than to try
    harder. See docs/superpowers/specs/2026-08-12-body-derived-reporting-date-design.md.

    "several" and "no-candidates" are separate reasons because they are
    separate measurements: one says the body was rich and we refused to
    choose, the other says the body offered nothing. Logging them as one
    number would hide which problem a future rule has to solve.
    """
    cands = candidate_dates(text, released)
    if not cands:
        return None, "no-candidates"
    if len(cands) > 1:
        return None, "several"
    when = cands[0]
    if when < today:
        return None, "past"
    return when, "ok"
```

- [ ] **Step 4: Run the rule's tests**

```bash
python test_earnings_dates.py
```

Expected: `123/123 checks passed`.

- [ ] **Step 5: Restore the freshness parameter**

In `press_monitor.py`, change the signature back and say why it is here:

```python
def record_disclosed_dates(items, fresh_uids):
    """Extract announced reporting dates from item titles and store them.

    Runs over EVERY item, not only the ones that will post. An announcement
    dropped by the age floor or by MAX_POSTS_PER_RUN is still a valid date,
    and the calendar has no other way to learn it.

    `fresh_uids` gates the BODY FETCH only, never the title path. Over every
    item it would re-fetch the same dozen pages on each pass, about eight
    times an hour, indefinitely, for an answer that does not change. That
    gate is also why the body measurement this rule is built on never
    sampled anything from here: the announcements were all old. Backfilling
    is probe_body_dates.py's job, and this is not that.
    """
```

At the call site (search for `record_disclosed_dates(all_items)`), restore the
second argument. Leave the `try`/`except` and the comment above it untouched:

```python
    try:
        record_disclosed_dates(all_items,
                               {i["uid"] for i in fresh + insider_fresh})
```

- [ ] **Step 6: Add the gate, the fetch and the counters**

In `record_disclosed_dates`, change the counters line:

```python
    counts = {"ok": 0, "no-date": 0, "past": 0, "no-match": 0}
    body = {"eligible": 0, "fetched": 0, "failed": 0,
            "ok": 0, "several": 0, "no-candidates": 0, "past": 0}
    no_date_examples = []
```

Then replace the whole `if reason == "no-date":` branch with this. The
example-collecting half is unchanged; the fetch is added after it:

```python
        if reason == "no-date":
            if len(no_date_examples) < 3:
                # The informative miss: an announcement whose date is in the
                # body rather than the title. probe_body_dates.py measures
                # this population in full; this is the sample in the log.
                no_date_examples.append(
                    f"{item['ticker']}: {item.get('title')!r}")
            # A title naming a forthcoming event is the only population the
            # rule was measured over. A results release is dense with dates
            # and was never in scope.
            if ed.names_a_scheduled_event(item.get("title")):
                body["eligible"] += 1
                if item.get("uid") in fresh_uids:
                    text = announcement_body(item.get("link"))
                    if text is None:
                        body["failed"] += 1
                    else:
                        body["fetched"] += 1
                        found, why = ed.date_from_body(text, released, today)
                        body[why] += 1
                        if found is not None:
                            when, reason = found, "ok"
```

Then, immediately after that branch and before the existing `if when is None:`,
the store call must learn where the date came from. Replace the existing
`ed.upsert(...)` call with:

```python
        if when is None:
            continue
        iso = (datetime.fromtimestamp(published, timezone.utc).isoformat()
               if published else None)
        source = "body" if body_hit else "title"
        if ed.upsert(companies, entry[0], item["ticker"], when,
                     item.get("uid"), item.get("title"), iso, source=source):
            print(f"  earnings dates: {item['ticker']} -> {when} "
                  f"({source}) from {item.get('title')!r}")
```

**Expect the two count sets to disagree, and leave them disagreeing.**
`counts[reason] += 1` runs before this branch, so an item whose date comes from
the body is still counted in `no-date`. That is correct: `no-date` describes the
**title**, which genuinely carried none, and the summary line's job is to report
what titles offered. The `body rule` line reports what bodies offered. Collapsing
them would make it impossible to see the title path degrade while the body path
compensates. Do not "fix" this, and do not subtract body hits from `no-date`.

`body_hit` must be set per item. Initialise it to `False` at the top of the loop
body, immediately after `entry` is resolved, and set it to `True` on the line
where the body date is accepted:

```python
    for item in items:
        entry = EXTRA_CIKS.get(item.get("ticker") or "")
        if not entry:
            continue
        body_hit = False
```

and

```python
                        if found is not None:
                            when, reason = found, "ok"
                            body_hit = True
```

- [ ] **Step 7: Log the body counters so a silent rule is visible**

After the existing summary `print`, add:

```python
    # A RUN THAT STORES NOTHING IS NOT EVIDENCE THE RULE WORKS. The previous
    # body measurement logged "Bodies fetched 0" for months and read as
    # working. `eligible` is the number that separates "no candidate item
    # this run" from "fetched and found nothing", so it is printed even when
    # every other number is zero.
    print(f"  earnings dates: body rule — {body['eligible']} eligible, "
          f"{body['fetched']} fetched, {body['failed']} fetch failed; "
          f"{body['ok']} stored, {body['several']} had several dates, "
          f"{body['no-candidates']} had none, {body['past']} were past.")
```

- [ ] **Step 8: Verify nothing broke**

```bash
python -m py_compile press_monitor.py && python test_earnings_dates.py && python test_probe_body_dates.py
```

Expected: compiles, `123/123 checks passed`, `32/32 checks passed`.

Then confirm the parameter is threaded correctly:

```bash
grep -n "fresh_uids\|body_hit" press_monitor.py
```

Expected: `fresh_uids` in the signature, in the docstring, in the gate, and at
the call site. `body_hit` initialised once per item and set once.

- [ ] **Step 9: Commit**

```bash
git add earnings_dates.py test_earnings_dates.py press_monitor.py
git commit -m "Store the one forward date an advance notice's body offers"
```

---

### Task 4: Verify against live data, and document it

**Files:**
- Modify: `docs/earnings.md`

**Interfaces:** none.

- [ ] **Step 1: Dispatch a dry run on the branch**

```bash
gh workflow run "Press release monitor" --ref body-derived-date -f dry_run=true
```

Substitute the actual branch name if it differs. Wait for it, then read the log.

- [ ] **Step 2: Read the result honestly**

The `body rule` line must be present. Three cases, and they are not the same:

- `0 eligible` means no new advance notice occurred in that run. **That is not
  a passing test.** It tells you the rule did not run at all. Say so plainly in
  the report rather than reporting success.
- `N eligible, 0 fetched` means candidates existed but none was new this run.
  Also not a passing test, and expected on most runs.
- `N fetched` with any outcome means the rule ran. That is the only result that
  verifies anything.

Whatever happens, the pre-existing counts must be unchanged:
`2 recorded, 20 announcement(s) with no parsable date, 4 rejected as past`.
If those moved, the title path was disturbed and something is wrong.

- [ ] **Step 3: Document the marker for a reader of the post**

In `docs/earnings.md`, find where the `!` marker is described and add beside it:

```markdown
`+` is the same claim with one difference: the company announced the date in
the body of a release rather than in its headline, and the calendar parsed it
out. The company stated it either way, so the row shows no spread, exactly as
an `!` row does. What differs is that the reading was ours, so a `+` row keeps
the normal overdue grace where an `!` row gets none. The rule that produces it
stores a date only when the body offers exactly one forward date; several or
none stores nothing.
```

- [ ] **Step 4: Commit**

```bash
git add docs/earnings.md
git commit -m "Document the + marker in the earnings post"
```

- [ ] **Step 5: Report**

State whether the rule actually ran, and if it did not, say that the change is
unverified in production and name what would verify it: a new advance notice
from any roster company, which arrives roughly once per company per quarter.

---

## Out of scope

A rule for the `several` case; a route to HUT's body; any confidence score or
per-company allowlist. All three need evidence this measurement does not contain.
