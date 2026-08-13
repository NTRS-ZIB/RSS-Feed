# Testing the decisions that have already gone wrong

Design, 2026-08-13.

## What this covers

`press_monitor.py` is 2,183 lines and is the component that posts to Discord.
**No test of it runs in CI.**

Stating that carefully, because a first draft of this spec said "no tests at all"
and that was wrong. `test_baseline.py` imports `press_monitor` and calls
`form_matches`, `filing_uid` and `baseline_companies`. But it tests only the last
of those: the other two are used as helpers while building its fixtures, so they
are exercised rather than checked, and an incorrect answer from either would
likely pass unnoticed. And that suite fetches live SEC data and exits without
`SEC_USER_AGENT`, which is exactly why it is excluded from `Tests` and runs only
when a person dispatches it.

So the state to fix is: one function tested, against live data, by a suite nobody
runs on a push. Until the parse and import steps landed on 2026-08-12, a typo in
this file merged green.

It holds 17 pure functions: no network, no file IO, testable with fixtures alone.
This spec covers **five of them**, chosen on one criterion: each encodes a
failure this repository has actually suffered and recorded.

That criterion matters more than coverage. `CLAUDE.md` says a test that has never
failed proves nothing, and adding a guard means first demonstrating the failure it
prevents. Tests written against documented incidents satisfy that by construction:
the failure is on record, so the test can be shown to catch it rather than merely
asserted to.

## The five, and the incident behind each

### `form_matches`, `form_core`, `drift_candidates`

The SEC renamed `SC 13D` to `SCHEDULE 13D` around December 2024. `FORM_TYPES`
still held the old spelling, prefix matching does not bridge a rename, and **117
filings went unposted** until a real activist stake in a watchlist company was
noticed missing.

What must hold:

- `form_matches("8-K/A", ["8-K"])` is true. Prefix matching is what handles
  amendments, and it is not the bug.
- `"SCHEDULE 13D".startswith("SC 13D")` is **false**. This is the whole incident
  in one line, and it belongs in the suite as a bare fact about the language.
- `form_core("SC 13D/A") == "SC13D"`. Amendment suffix and spacing stripped.
- `drift_candidates` flags `SCHEDULE 13D` against a tracked `SC 13D` **without
  knowing the new spelling in advance**, which is the property that makes it
  useful for the next rename rather than only the last one.
- A form in `DRIFT_IGNORE` is never flagged. A warning that always fires is one
  nobody reads, which is why that set exists.
- A stem shorter than three characters never matches. Without that guard the
  rule flags everything, and a detector that flags everything is off.

### `headers_for`

A browser-like User-Agent is a per-host bet, not a safe default. GlobeNewswire
stalls a Chrome-claiming request from the runner and answers a plain one in 0.1
seconds. **The cost of not knowing that was 22 hours of silent outage**, because
a stall is indistinguishable from a dead host until you vary the header.

What must hold:

- A host present in `HOST_HEADERS` gets its override, not the default.
- Any other host gets `IR_HEADERS`.
- The lookup is case-insensitive on the netloc, since a URL may be spelled with
  any casing and a miss here silently reverts the host to the losing bet.

### `check_staleness`

A source can die at HTTP 200 and look healthy in every check: valid XML, good
timestamps, nothing newer than months ago.

What must hold:

- **Same-day items collapse before measuring.** The docstring carries the
  measurement: HUT's median gap reads 5.5 days uncollapsed and 18 collapsed. A
  test that three items on one morning count as one publication day is a test of
  the thing that makes the horizon meaningful.
- Below `STALE_MIN_DAYS` of history it reports a **count** and returns, rather
  than warning. Too little history and a dead source are different measurements
  and must not share a label.
- It warns above the horizon and stays silent below it.
- The log names whichever term set the horizon: the median multiple, the floor,
  or the per-source override. A warning that cannot explain its own threshold
  invites the reader to dismiss it.
- It returns `None` and never raises. One source going dark must not affect the
  other thirteen or the EDGAR sweep.

### `suppress_cross_host`

The one where a wrong answer silently eats a real post rather than adding a
spurious one.

What must hold:

- **Exact normalised title only.** The docstring records 23,771 measured pairs in
  which two genuinely different releases scored 0.984 similarity, and the
  near-collisions cluster in quarterly results, the highest-value items the
  channel carries. A test that `First Quarter 2022` is not suppressed as a
  duplicate of `First Quarter 2021` is a test that no threshold crept in.
- Outside `CROSS_HOST_DAYS`, nothing is suppressed. The window is what makes
  exact matching safe by construction rather than by tuning.
- **An empty newsroom skips the comparison entirely.** If the scraper failed or
  its markup moved, matching against an empty set must not be mistaken for
  matching successfully. The bias is to post twice, never to suppress.

## Where the tests live

A new `test_press_monitor.py`, in the repo's existing standalone `check()` style,
printing `N/M checks passed` and exiting non-zero. It joins `Tests`, and the
coverage gate in that workflow will require it to be listed there.

### The `feedparser` stub, and its limit

Importing `press_monitor` requires `feedparser`, which is not installed in a plain
working copy, so without a stub this file would be undevelopable locally even
though CI now installs it.

The test stubs `feedparser` in `sys.modules` before importing, with a comment
saying why. **That is safe for this spec's scope and only for it:** `feedparser`
is touched solely by `parse_feed`, which none of these five functions calls. If a
future test needs a function that does parse feeds, the stub must be removed
rather than extended, because a stub that grows is a stub that starts hiding
things.

## Verification

**Every check must be demonstrated to fail**, not merely to pass. That is the
repo's standard and it is the reason this spec chose incidents over coverage.

The precedent exists: `drift_candidates` was originally validated by taking
`SCHEDULE 13D` back out of `FORM_TYPES` and confirming it flagged. Each group
gets the equivalent:

- **form matching**: remove `SCHEDULE 13D` from `FORM_TYPES`, confirm the drift
  test fires; restore it.
- **`headers_for`**: temporarily empty `HOST_HEADERS`, confirm the override test
  fails; restore it.
- **`check_staleness`**: temporarily drop the same-day collapse, confirm the
  collapse test fails; restore it.
- **`suppress_cross_host`**: temporarily widen the match from exact title to a
  substring, confirm the 0.984-pair test fails; restore it.

Each demonstration's before-and-after output goes in the implementation report. A
check that passes both with and without the behaviour it names is worse than no
check, because it reads as coverage.

## Out of scope

The other 12 pure functions. Everything requiring network or mocking:
`parse_feed`, the scrapers, the CMS readers, `post`, `collect_all`, `collect_ir`.
And `baseline_companies`, whose test exists and merely needs freeing from live SEC
data, which is its own piece of work.

This spec buys confidence in five decisions, not in `press_monitor.py`.
