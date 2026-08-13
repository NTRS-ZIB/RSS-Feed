# Testing the weekly digest's verdicts and its guards

Design, 2026-08-13.

## What this covers

`weekly_digest.py` (2,051 lines) and `digest_render.py` (1,163) hold **43 pure
functions between them and no test of either runs anywhere.** The digest is the
component that makes claims *about* the other components — it re-derives from
source and publishes a verdict per company per week — so a wrong rule here is a
wrong statement about work that was itself correct.

Both modules import cleanly with only a `feedparser` stub and no secrets, so
this suite runs in CI exactly like the other seven.

### Scope, and what is deliberately left out

**In:** the six areas where something has actually gone wrong, and the ten
`derive_*` contributor rules that decide what the digest says each week.

**Out:** `render_markdown` (313 lines), `render_post` (168), `report` (165) and
`build_week` (135). They assemble output rather than decide anything, their
output is already guarded by `check_post()`, and a 313-line renderer is exactly
where a check that cannot fail is easiest to write and hardest to notice. That
judgement comes from this repo's own experience the same week: covering
`press_monitor` exhaustively produced six checks that could not fail, and every
one was in the padding rather than in the incident-bearing core.

## Tier 1: the six that have already gone wrong

Each is recorded in `docs/weekly-digest.md` with the measurement that found it.

### `publication_week` and `period_published_in`

**A short-interest publication window is nine days wide and therefore overlaps
two consecutive weeks.** The first version tested for overlap, so one
settlement was counted twice and short interest fired **7.3 times a week from a
source that publishes twice a month** — a number that would have set the
convergence threshold wrongly while looking like a finding.

`publication_week` now returns the Monday of the ISO week a settlement becomes
visible in, at settlement + `SHORT_INTEREST_PUBLICATION_LAG` (12) days, and
`short_interest_publishes` compares that Monday for **equality** with
`sessions[0]`. Equality is the whole fix, and `sessions[0]` is safe to compare
against because `week_sessions` returns calendar Monday to Friday whatever the
market did.

The check that pins the incident: **across a run of consecutive weeks, exactly
one claims any given settlement.** A range test would claim two.

`period_published_in` is the FTD sibling and is genuinely a range test, because
what it places is a single publication date rather than a window. Both arms of
its month arithmetic need exercising, including the December wrap.

### `silent` and `failed_sources`

**Silence is the one claim a missing source turns into a lie.** A dry run with
EDGAR unavailable reported **eleven companies as having filed nothing**, which
nothing had measured. Every other section understates when a source fails; this
one asserts, because absence is its subject.

Three independent reasons a company must be kept out of the silent list:
convergence count or `source_failed`, a `filings` verdict at `NOT_TESTABLE`,
and a non-empty `filings_in_week`. Each needs its own check, because each was
added for a different failure and any one of them silently dropping would
reintroduce the invention.

`unmeasured` must contain contributors that were never **fetched**, and must
NOT contain a contributor that was fetched and simply did not publish — a
fortnightly source being quiet is the normal case and does not undermine the
claim.

### `derive_ftd`, bounded to `ftd_monitor.BASELINE_PERIODS`

**A verdict must not depend on how much history the caller happened to fetch.**
`derive_ftd` took its median over every prior period in the fetch, so ABTC
converged in a three-week render that pulled 8 half-month periods and did not
in the ten-week backfill that pulled 11 — the same week, two answers.

The check is the incident: **the same week, given more history than the rule
uses, produces the same verdict.** Call it twice with 8 and with 11 periods of
context and compare, rather than asserting a hard-coded number.

### The detail-key namespace

**Detail keys are a shared namespace even though the dicts are not.**
`baseline_median` meant a volume median to one contributor and a median of
half-month fail peaks to another; the renderer matched the first and read a
field only the second carries.

This is a structural check rather than a behavioural one: **no two contributors
claim the same detail key**, asserted over `CONTRIBUTORS` and whatever the
`derive_*` functions emit. It is the one check here that guards a class of
future mistake rather than a past one, which is why it belongs in the suite
rather than only in the backfill's diagnostics.

### `check_post` and `mono_table`

**Discord accepts an over-wide code block silently and wraps it on mobile.**
The recap and the earnings calendar were both rebuilt narrower rather than
accept the wrap, so a renderer that could exceed the ceiling would undo that.

`check_post` returns a list of problems; every limit it enforces needs a check
that it is enforced, and — more importantly — a check that a **compliant** post
returns no problems, since a guard that always complains is one nobody reads.
The monospace arm only inspects fields whose value starts with a fence, which
is a real branch and needs a fixture on each side of it.

`mono_table` builds those blocks and is where a width regression would start.

### `already_produced`

**The file for week N is the record that week N was produced.** There is no
state file, deliberately. It reads the working tree, which is only current if
the job pulled first, and that is the mechanism behind the duplicate-post
incident of 2026-08-04.

Cheap to test with a temporary directory, and worth it because the whole
no-state-file design rests on this one line.

## Tier 2: the ten contributor rules

`derive_price`, `derive_volume`, `derive_crossings`, `derive_filings`,
`derive_letters`, `derive_threshold`, `derive_dilution`, `derive_holders`,
`derive_short_interest`, and `derive_ftd` (already Tier 1).

These decide whether a contributor fires at all, and two facts from
`docs/weekly-digest.md` shape how they must be tested:

- **`dilution` has fired for no company in ten weeks, and the rule is not the
  reason:** only 3 of 190 ticker-weeks had a new XBRL observation, and the
  largest step was HUT at +9.50% against a 10.0% threshold. So a fixture is the
  only way its firing arm has ever been executed, which is the same argument
  that justifies `carries_press_release`'s no-items branch in `press_monitor`.
- **The run separates *not fetched*, *fetched but never fired*, and
  *exercised*.** Collapsing any two hides exactly the above, so a rule's
  no-data path and its did-not-fire path must be checked separately.

Each rule gets its firing arm, its not-firing arm, and its no-data arm. Not
more: these are ten similar functions and a suite that tests each one five ways
is padding, which is where unfailable checks come from.

## The `feedparser` stub, and its limit

`weekly_digest` imports `press_monitor`, which imports `feedparser`, absent
from a plain working copy. The suite stubs it in `sys.modules` before
importing, exactly as `test_press_monitor.py` does, and the same limit applies:
that is safe only while no tested function parses a feed. If one ever does,
**remove the stub rather than extend it.**

## Verification

**Every check must be demonstrated to fail**, by naming a one-line change to
the module under test, making it, and watching that check go red. Clear
`__pycache__` between mutations: two edits removing the same number of
characters within the same second are indistinguishable to CPython's bytecode
cache, and the second run silently re-executes the first.

**Read the implementation, not this spec.** Every check that could not fail in
the `press_monitor` suite came from a plan describing what a function ought to
do rather than what it does. Where this document and the code disagree, the
code is right and this document gets amended.

A check that passes both with and without the behaviour it names is worse than
no check, because it reads as coverage.
