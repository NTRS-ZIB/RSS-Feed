# Running the test suites on push

Design, 2026-08-12.

## What this fixes

**No test suite runs anywhere in CI.** Measured on 2026-08-12:

- The only push-triggered workflow in the repo is `workflow-list-gate.yml`, which
  checks that workflows are watched, not that code works.
- `baseline-test.yml` is the sole workflow that runs a test file. It runs only
  `test_baseline.py`, and it is dispatch-only.
- The other six test files run nowhere.

That leaves **258 checks** executing only when a person remembers:

| suite | checks | third-party imports |
|---|---|---|
| `test_earnings_dates.py` | 130 | `requests`, via its `earnings_calendar` import |
| `test_page_text.py` | 36 | none |
| `test_probe_body_dates.py` | 32 | none |
| `test_loop_state.py` | 27 | none |
| `test_loop_verdict.py` | 22 | none |
| `test_loop_approval.py` | 11 | none |

A push that breaks `earnings_dates.py` or `page_text.py` is caught by nothing. It
surfaces at the next scheduled run, in production, on the path that posts to a
live Discord channel.

**This is the shape of two failures `CLAUDE.md` already records**: the body
measurement that ran for months producing nothing, and the state-push retry loop
that had never executed. Protection that exists somewhere, unexercised, and reads
as protection because it exists.

## The workflow

`.github/workflows/tests.yml`, named **Tests**.

- `on: push` filtered to `**.py`, plus `workflow_dispatch`.
- `permissions: contents: read`. It reads code and reports; it writes nothing and
  takes no secrets.
- Python 3.12, `pip install requests`.

### Every branch, not only `main`

The value is catching a break **before** it merges, so it has to run where the
work happens. A gate that only guards `main` tells you after the fact, which is
the position this design exists to leave.

### Filtered to `**.py`

Fourteen workflows commit state files to `main` through the day. Most carry
`[skip ci]`, but not all, and running six suites against a `snapshot.json` commit
proves nothing. The filter mirrors `workflow-list-gate.yml`, which already
triggers on `push` filtered to `.github/workflows/**`.

The filter is also what makes the verification below meaningful: a broken commit
touches a `.py`, so a wrong filter shows up as the workflow not firing rather than
as a pass.

### Six steps, not one

Each suite gets its own `run:` step, so a failure is named in the run's step list
and nobody has to open a log to learn which suite broke.

No pytest and no adapter. These are standalone scripts using the repo's own
`check()` harness; they print `N/M checks passed` and exit non-zero on failure, so
a plain `run:` fails the job.

### `test_baseline.py` stays out

It needs `SEC_USER_AGENT` and live SEC data. That makes it a live-data check
rather than a unit suite: it can fail because the SEC is slow, which is exactly
the kind of failure that teaches people to ignore a red mark. It keeps its own
dispatch-only workflow.

## Two things this must not break

**`failure-notice.yml` gains `- "Tests"` in its watched list.** `workflow-list-gate.yml`
fails any push that adds a workflow nothing watches, and that gate already caught
this repo out once today. The alternative, adding **Tests** to the gate's `EXEMPT`
set, was considered and rejected: a red push nobody notices is the same failure
mode as a test nobody runs, and `EXEMPT` should stay a one-entry special case for
the notifier itself rather than becoming a habit.

**README's Layout block gains an entry.** That inventory was made exactly correct
earlier today, verified in both directions. Adding a workflow without listing it
would re-break it in the same hour.

## Verification

**A guard is not trusted here until it has been demonstrated to fire, and that
standard is the whole reason this workflow exists.** Verifying it by watching it
pass would repeat the mistake it was built to prevent.

On the branch:

1. Break one assertion in one suite. Push. **Tests** must go red, and the step
   list must name that suite.
2. Revert. Push. **Tests** must go green.

Both run URLs belong in the report. Step 1 also verifies the path filter: the
breaking commit touches a `.py` file, so if the filter is wrong the workflow does
not fire at all, and a workflow that never ran is indistinguishable from one that
passed.

## Out of scope

Running the suites on a schedule, gating merges on them, adding coverage
measurement, and moving `test_baseline.py`. Each is a separate decision and none
is needed to close the gap this addresses.
