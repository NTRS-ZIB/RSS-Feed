# Tests on push Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run the six offline test suites on every push that touches Python, so
258 checks stop depending on someone remembering.

**Architecture:** One new dispatch-and-push workflow running each suite as its own
step, wired into `failure-notice.yml` so a red run is announced, and listed in
README so the inventory stays true. Then demonstrated by breaking a suite and
watching it go red.

**Tech Stack:** GitHub Actions, Python 3.12, `requests`. No pytest: the suites are
standalone scripts using the repo's own `check()` harness, which exit non-zero.

## Global Constraints

- **The path filter is `['*.py', '**/*.py']`, both patterns.** All 42 Python files
  in this repo are at the root. A filter that fails to match root files means the
  workflow **never fires and says nothing**, which is the exact failure this
  workflow exists to end. Do not "simplify" it to one pattern.
- **`test_baseline.py` is NOT in this workflow.** It exits without
  `SEC_USER_AGENT` and fetches `data.sec.gov`, so it can go red because the SEC is
  slow. It keeps its own dispatch-only workflow.
- **`failure-notice.yml` must gain `- "Tests"`.** `workflow-list-gate.yml` fails
  any push adding a workflow nothing watches, and it caught this repo out once
  already today.
- **`permissions: contents: read`.** The workflow reads code and reports. It
  writes nothing, commits nothing and takes no secrets.
- **Do not run the component scripts.** `press_monitor.py`, `earnings_calendar.py`
  read secrets that exist only in GitHub Actions and post to live Discord.
  **Do not run `probe_body_dates.py`** (real network). Safe: every `test_*.py`
  except `test_baseline.py`, `python watchlist.py`, `python -m py_compile`.
- **This working copy has no outbound network**, so nothing here can be verified
  by fetching.
- **`earnings_dates.json`, `state.json` and `snapshot.json` are outputs.** Never
  edit, delete, reformat or commit one.
- **Branch:** `tests-on-push`, already created, spec committed at `0374642`.
- Suite baselines, all of which must still hold:
  `test_page_text.py` **36**, `test_earnings_dates.py` **130**,
  `test_probe_body_dates.py` **32**, `test_loop_state.py` **27**,
  `test_loop_verdict.py` **22**, `test_loop_approval.py` **11**.

## File Structure

| File | Responsibility |
|---|---|
| Create `.github/workflows/tests.yml` | Run the six offline suites on push and on demand. |
| Modify `.github/workflows/failure-notice.yml` | Watch the new workflow, so a red run is announced. |
| Modify `README.md` | Keep the Layout inventory true. |

No Python changes. This plan adds no code and alters no behaviour of anything the
components do; it only starts running tests that already exist and already pass.

---

### Task 1: The workflow, watched and listed

**Files:**
- Create: `.github/workflows/tests.yml`
- Modify: `.github/workflows/failure-notice.yml` (the `workflows:` list)
- Modify: `README.md` (the Layout block)

**Interfaces:**
- Consumes: nothing.
- Produces: a workflow named exactly **`Tests`**. Task 2 refers to it by that
  name and `failure-notice.yml` watches it by that string; the two must match
  character for character.

- [ ] **Step 1: Create the workflow**

Create `.github/workflows/tests.yml`:

```yaml
name: Tests

# The offline suites, on every push that touches Python. Before this existed
# NOTHING ran them: the only push-triggered workflow was the list gate, which
# checks that workflows are watched rather than that code works, and
# baseline-test.yml is dispatch-only and runs one file. That left 258 checks
# executing only when a person remembered.
#
# test_baseline.py is deliberately absent. It needs SEC_USER_AGENT and fetches
# data.sec.gov, so it can go red because the SEC is slow, and a red mark that
# fires for reasons outside the repository is how people learn to ignore red
# marks. It keeps baseline-test.yml.
#
# BOTH path patterns are required. Every Python file in this repo is at the
# root, and a filter that misses the root would mean this never fires and never
# says so, which is the failure it exists to end.

on:
  push:
    paths:
      - "*.py"
      - "**/*.py"
  workflow_dispatch:

permissions:
  contents: read

jobs:
  tests:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v5
      - uses: actions/setup-python@v6
        with:
          python-version: "3.12"
      # Only test_earnings_dates.py needs this, through its earnings_calendar
      # import. The other five are stdlib-only.
      - name: Install dependencies
        run: pip install requests
      # One step per suite so a failure is named in the run's step list and
      # nobody has to open a log to learn which one broke.
      - name: page_text
        run: python -u test_page_text.py
      - name: earnings_dates
        run: python -u test_earnings_dates.py
      - name: probe_body_dates
        run: python -u test_probe_body_dates.py
      - name: loop_state
        run: python -u test_loop_state.py
      - name: loop_verdict
        run: python -u test_loop_verdict.py
      - name: loop_approval
        run: python -u test_loop_approval.py
```

- [ ] **Step 2: Watch it, or the gate fails the push**

In `.github/workflows/failure-notice.yml`, the `workflows:` list is alphabetical.
Insert between `- "Short sale volume"` and `- "Volume spikes"`:

```yaml
      - "Tests"
```

- [ ] **Step 3: List it, so the inventory stays true**

In `README.md`'s Layout block, immediately after the
`.github/workflows/workflow-list-gate.yml` line, add:

```
.github/workflows/tests.yml       the offline test suites, on every push touching Python
```

- [ ] **Step 4: Confirm the YAML parses and takes no secrets**

```bash
python -c "import yaml; yaml.safe_load(open('.github/workflows/tests.yml')); yaml.safe_load(open('.github/workflows/failure-notice.yml')); print('ok')"
grep -n "secrets\." .github/workflows/tests.yml
```

Expected: `ok`, then no output from the grep. A `secrets.` match means the
read-only contract is broken.

- [ ] **Step 5: Confirm the watched name matches the workflow name exactly**

```bash
grep -n '^name:' .github/workflows/tests.yml
grep -n '"Tests"' .github/workflows/failure-notice.yml
```

Expected: `name: Tests` and one list entry `- "Tests"`. A mismatch here is
invisible until a failure goes unannounced.

- [ ] **Step 6: Confirm the inventory is true in both directions**

```bash
for f in .github/workflows/*.yml; do grep -qF ".github/workflows/$(basename "$f")" README.md || echo "MISSING: $(basename "$f")"; done
grep -oE "\.github/workflows/[a-z-]+\.yml" README.md | sort -u | while read p; do [ -e "$p" ] || echo "PHANTOM: $p"; done
```

Match the full path, not the bare basename: a bare-basename `grep -q "$b"` is
substring matching, not anchoring, and `metric-regime.yml` contains
`regime.yml` as a substring — that exact collision let
`.github/workflows/regime.yml` go missing from the Layout block undetected.
Matching the full path removes the false positive.

Expected: no output from either. The second loop matters as much as the first: a
listed file that does not exist misleads exactly like an omitted one.

- [ ] **Step 7: Confirm every suite still passes locally**

```bash
python test_page_text.py && python test_earnings_dates.py && python test_probe_body_dates.py && python test_loop_state.py && python test_loop_verdict.py && python test_loop_approval.py
```

Expected: `36/36`, `130/130`, `32/32`, `27/27`, `22/22`, `11/11`.

- [ ] **Step 8: Commit and push**

```bash
git add .github/workflows/tests.yml .github/workflows/failure-notice.yml README.md
git commit -m "Run the offline test suites on every push touching Python"
git push -u origin tests-on-push
```

- [ ] **Step 9: Confirm the list gate passes on that push**

```bash
gh run list --workflow="Workflow list gate" --limit 1 --json conclusion,headBranch,createdAt
```

Expected: `"conclusion": "success"` on `tests-on-push`. A failure means Step 2 did
not land, and the log names the unwatched workflow.

**Expect `Tests` NOT to have run on this push.** This commit touches two YAML
files and a README and no `.py` file at all, so the path filter correctly skips
it. That is the filter working, not a fault. Step 10 proves the job itself runs.

- [ ] **Step 10: Do not attempt a manual dispatch. It cannot work here.**

An earlier version of this step said to run `gh workflow run "Tests" --ref
tests-on-push` to prove the job works before Task 2 proves the trigger works.
**That is impossible and the step was wrong.** GitHub registers
`workflow_dispatch` only for workflows present on the **default** branch, so a
brand new workflow cannot be dispatched from a feature branch; `gh workflow run`
returns *could not find any workflows named*. `docs/local-workflow.md` records
this, and `calibrate.yml` and `probe-body-dates.yml` were both merged before they
could first be run.

The consequence is that Task 2 now proves both things at once, and its Step 4
carries the diagnosis for each. Do not work around this by merging early.

- [ ] **Step 11: Record the run URL in your report**

The list-gate run's URL and conclusion from Step 9. There is no dispatched run to
record.

---

### Task 2: Demonstrate it goes red

**Files:** none permanently. This task makes a breaking commit and reverts it.

**Interfaces:**
- Consumes: the `Tests` workflow from Task 1.
- Produces: evidence, and no net change to the tree.

**This is the task the whole plan exists for.** A guard nobody has seen fire is
not a guard, and verifying *this* workflow by watching it pass would repeat the
mistake it was built to prevent. It also tests the path filter: the breaking
commit touches a `.py`, so a wrong filter shows up as the workflow not firing,
and a workflow that never ran looks exactly like one that passed.

- [ ] **Step 1: Break one assertion**

In `test_page_text.py`, find the check:

```python
    check("tags are removed",
          pt.extract_text("<p>hello <b>there</b></p>") == "hello there")
```

Change the expected string so it cannot match:

```python
    check("tags are removed",
          pt.extract_text("<p>hello <b>there</b></p>") == "DELIBERATELY WRONG")
```

`test_page_text.py` is chosen because it is stdlib-only and first in the step
list, so the run fails fast and the failing step is unambiguous.

- [ ] **Step 2: Confirm it fails locally first**

```bash
python test_page_text.py; echo "exit=$?"
```

Expected: `35/36 checks passed` and `exit=1`. If the exit code is 0 the workflow
cannot detect it either, and that is a finding about the harness rather than
about the workflow.

- [ ] **Step 3: Push the break**

```bash
git add test_page_text.py
git commit -m "TEMPORARY: break a check to prove Tests fires"
git push
```

- [ ] **Step 4: Confirm Tests fired and went red**

```bash
gh run list --workflow="Tests" --limit 1 --json databaseId,conclusion,headSha
```

Expected: `"conclusion": "failure"`, on the commit you just pushed.

Then confirm the step list names the suite:

```bash
gh run view <id> --json jobs -q '.jobs[].steps[] | "\(.conclusion) \(.name)"'
```

Expected: `failure page_text`, and the later suites `skipped`.

**If `Tests` did not run at all, stop and diagnose before doing anything else.**
There are two causes and they need telling apart, because Task 1's manual
dispatch could not be performed on a feature branch:

- **The path filter is wrong.** Check the run list for the workflow across the
  whole branch: `gh run list --workflow="Tests" --limit 5`. Empty means it has
  never fired for any commit.
- **The workflow file is invalid.** GitHub surfaces a parse failure separately
  from a job failure. Check `gh api repos/:owner/:repo/actions/workflows --jq
  '.workflows[] | select(.name=="Tests") | {state, path}'`; a workflow with a
  problem does not report `active`.

Either way this is the defect the step exists to catch, not a reason to move on.
Report which cause it was.

- [ ] **Step 5: Revert**

```bash
git revert --no-edit HEAD
git push
```

- [ ] **Step 6: Confirm it goes green again**

```bash
gh run list --workflow="Tests" --limit 1 --json databaseId,conclusion
```

Expected: `success`.

- [ ] **Step 7: Confirm the tree is back to where it started**

```bash
python test_page_text.py
git status --porcelain
git log --oneline -3
```

Expected: `36/36 checks passed`, no output from `git status`, and the last three
commits being the revert, the deliberate break, and Task 1's commit.

- [ ] **Step 8: Report**

Give both run URLs, the red one and the green one, and the step-list output from
Step 4 showing which suite failed. Those are the evidence that the workflow
guards something.

---

## Out of scope

Running the suites on a schedule, gating merges on them, coverage measurement, and
moving `test_baseline.py`. Each is a separate decision and none is needed to close
the gap this addresses.
