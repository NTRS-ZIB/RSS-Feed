# Weekly digest test suite — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** `test_weekly_digest.py`, covering the six areas of `weekly_digest.py`
and `digest_render.py` where something has gone wrong, plus the ten contributor
rules, wired into the `Tests` workflow.

**Architecture:** One new standalone file in the repo's existing `check()`
style, printing `N/M checks passed` and exiting non-zero. No test framework.

**Tech Stack:** Python 3.12 stdlib. `feedparser` stubbed in `sys.modules`
before importing, as `test_press_monitor.py` does.

## Global Constraints

- **`weekly_digest.py` and `digest_render.py` must not change.** This is a test
  branch. If a real defect is found, report it and leave it; changing behaviour
  under cover of a test branch is how a regression ships unnoticed.
- **Every check must be demonstrated to fail.** Name the one-line change to the
  module that turns it red, make that change, run the suite, watch that check
  fail and confirm it fails alone or explain why not. Restore afterwards.
- **Delete `__pycache__` between mutations.** Two edits removing the same
  number of characters within the same second are indistinguishable to
  CPython's bytecode cache, and the second run silently re-executes the first.
- **A mutation that crashes the harness instead of failing the check has shown
  nothing.** Say so rather than counting it.
- **Read the implementation before writing a check.** Every unfailable check in
  the `press_monitor` suite came from a plan describing what a function ought
  to do. Where the spec and the code disagree, the code is right.
- **Do not run the component scripts.** They read secrets that exist only in
  GitHub Actions and several post to live Discord. `python -u
  test_weekly_digest.py` is the only thing to run.
- Import as `import weekly_digest as wd` and `import digest_render as dr`.
- Section headers printed with `print("\nSECTION NAME")`, matching
  `test_press_monitor.py`.
- Check names are lowercase sentences; the ones that encode a recorded incident
  are SHOUTED, as in the existing suites.
- Every check whose subject is a recorded incident carries the measured number
  in its detail string or a comment above it. The numbers are in
  `docs/weekly-digest.md`; quote them, do not invent them.

---

### Task 1: Scaffold, and the publication windows

**Files:** Create `test_weekly_digest.py`.

**Interfaces produced:** the `check()` harness, the `feedparser` stub, and the
import of both modules, which every later task appends to.

- [ ] Read `week_sessions`, `recent_weeks`, `monday_of`, `iso_week_key`,
      `publication_week`, `period_published_in`, `short_interest_publishes`,
      `ftd_publishes` in `weekly_digest.py`.
- [ ] Build the file's scaffold: stub, imports, `check()`, `main()`, exit code.
- [ ] **THE INCIDENT:** a nine-day publication window overlapped two
      consecutive weeks, so one settlement was counted twice and short interest
      fired **7.3 times a week from a source that publishes twice a month**.
      Check that across a run of consecutive Mondays, **exactly one** claims a
      given settlement. A range test would claim two.
- [ ] `publication_week` returns a Monday for any input day of the week, and
      `None` rather than raising for a malformed date.
- [ ] `period_published_in`: the `a` half and the `b` half both, and the
      December wrap, where the month arithmetic rolls the year.
- [ ] `week_sessions` returns calendar Monday to Friday regardless of holidays
      — this is what makes `sessions[0]` safe to compare a Monday against.
- [ ] `recent_weeks` excludes a week still running and includes it once its
      Friday has passed, both arms, using its `today` parameter.
- [ ] Demonstrate every check, then commit.

### Task 2: Silence, the one claim a missing source turns into a lie

**Files:** Modify `test_weekly_digest.py`.

- [ ] Read `silent`, `failed_sources`, `not_testable` in `digest_render.py`,
      and enough of the record shape to build a fixture (`build_week` shows it).
- [ ] **THE INCIDENT:** a dry run with EDGAR unavailable reported **eleven
      companies as having filed nothing**, which nothing had measured.
- [ ] Three separate checks, one per exclusion arm, because each was added for
      a different failure: a company with a convergence count, one with
      `source_failed`, one whose `filings` verdict is `NOT_TESTABLE`, and one
      with a non-empty `filings_in_week`. Each must stay out of the list, and
      each check must fail if only its own arm is removed.
- [ ] A genuinely silent company IS listed — the positive control, without
      which every arm above passes trivially.
- [ ] `unmeasured` names contributors never fetched, and does NOT name one that
      was fetched and simply did not publish.
- [ ] `failed_sources` treats `partial` as not-failed, which is a deliberate
      choice and the kind that gets "tidied" away.
- [ ] Demonstrate every check, then commit.

### Task 3: The output guards

**Files:** Modify `test_weekly_digest.py`.

- [ ] Read `check_post`, `mono_table`, `week_title`, `week_url`,
      `already_produced` in `digest_render.py`, and the limit constants.
- [ ] **A compliant post returns no problems.** First, and load-bearing: a
      guard that always complains is one nobody reads.
- [ ] One check per limit `check_post` enforces, each breaching only that limit.
- [ ] **The monospace arm only inspects fields whose value starts with a
      fence.** A wide line inside a fence is a problem; the same wide line
      outside one is not. Both sides, or the branch is untested.
- [ ] `mono_table` output fits the monospace ceiling.
- [ ] `already_produced` is true when the week's file exists and false
      otherwise, using a temporary directory. It is one line and the whole
      no-state-file design rests on it.
- [ ] Demonstrate every check, then commit.

### Task 4: A verdict that does not depend on fetch depth, and the key namespace

**Files:** Modify `test_weekly_digest.py`.

- [ ] Read `derive_ftd` and `ftd_monitor.BASELINE_PERIODS`.
- [ ] **THE INCIDENT:** ABTC converged in a three-week render that pulled 8
      half-month periods and did not in a ten-week backfill that pulled 11 —
      the same week, two answers.
- [ ] Call `derive_ftd` for one week with 8 periods of context and again with
      11, and check the verdicts are **equal to each other**. Do not assert a
      hard-coded verdict: the property is independence from fetch depth, and a
      hard-coded expectation would pin today's arithmetic instead.
- [ ] **The detail-key namespace:** assert that no two contributors claim the
      same detail key. Derive the mapping from `CONTRIBUTORS` and the
      `derive_*` functions rather than hard-coding a list, or the check stops
      tracking the module the first time a contributor is added.
- [ ] Demonstrate both, then commit. For the namespace check, the demonstration
      is a deliberate collision introduced into a `derive_*` function.

### Task 5: Contributor rules, first five

**Files:** Modify `test_weekly_digest.py`.

- [ ] Read `derive_price`, `derive_volume`, `derive_crossings`,
      `derive_filings`, `derive_letters`, and `form_in`.
- [ ] For each: its firing arm, its not-firing arm, and its no-data arm. Three
      checks each, not five — ten similar functions tested five ways each is
      padding, and padding is where unfailable checks come from.
- [ ] **The no-data arm and the did-not-fire arm are different states** and
      must not be checked with the same fixture: the run output separates *not
      fetched*, *fetched but never fired* and *exercised* precisely because
      collapsing them hides a rule that never runs.
- [ ] Demonstrate every check, then commit.

### Task 6: Contributor rules, remaining four

**Files:** Modify `test_weekly_digest.py`.

- [ ] Read `derive_threshold`, `derive_dilution`, `derive_holders`,
      `derive_short_interest`.
- [ ] Same three arms each.
- [ ] **`derive_dilution`'s firing arm has never executed against real data:**
      only 3 of 190 ticker-weeks had a new XBRL observation and the largest
      step was +9.50% against a 10.0% threshold. A fixture is the only way that
      arm has ever run, which is the argument for testing it at all — say so in
      a comment, as `press_monitor` does for `carries_press_release`.
- [ ] Demonstrate every check, then commit.

### Task 7: Wire it in

**Files:** Modify `.github/workflows/tests.yml`, `README.md`,
`docs/weekly-digest.md`.

- [ ] Add a `weekly_digest` step to `tests.yml`. The coverage gate at the top
      of that workflow will fail the push if the file is not listed, so this is
      not optional.
- [ ] Update the comments in `tests.yml` that count the suites — they will say
      seven and must say eight.
- [ ] Add the suite to the README layout inventory.
- [ ] Replace the "Untested is not the same as working" section's framing in
      `docs/weekly-digest.md` only to the extent it is now wrong; the
      measurement it reports is still true and must not be rewritten.
- [ ] Run the full suite, confirm CI is green, then commit.
