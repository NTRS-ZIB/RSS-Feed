# Testing every decision the press monitor makes without a network

Design, 2026-08-13.

## What this covers

`press_monitor.py` is 2,183 lines and is the component that posts to Discord.
**No test of it runs in CI.**

Stating that carefully, because a first draft of this spec said "no tests at all"
and that was wrong. `test_baseline.py` imports `press_monitor` and calls
`form_matches`, `filing_uid` and `baseline_companies`. But it tests only the last
of those: the other two are used as helpers while building its fixtures, so they
are exercised rather than checked, and a wrong answer from either would likely
pass unnoticed. And that suite fetches live SEC data and exits without
`SEC_USER_AGENT`, which is why it is excluded from `Tests` and runs only when a
person dispatches it.

So the state to fix is: one function tested, against live data, by a suite nobody
runs on a push. Until the parse and import steps landed on 2026-08-12, a typo in
this file merged green.

**This spec covers all 18 pure functions**: every decision the module makes that
needs no network and no file IO. A first draft counted 17 and missed `filed_time`,
which is 48 lines and carries a measurement of its own.

The 20 remaining functions are out of scope because they fetch, scrape, read a
file or post. They need a different technique and a different spec.

## Tier 1: the decisions that have already gone wrong

These six are the reason to do this work at all. Each encodes a failure this
repository has suffered and recorded, so each test can be shown to catch a real
incident rather than merely asserted to be useful.

### `form_matches`, `form_core`, `drift_candidates`

The SEC renamed `SC 13D` to `SCHEDULE 13D` around December 2024. `FORM_TYPES`
still held the old spelling, prefix matching does not bridge a rename, and **117
filings went unposted** until a real activist stake in a watchlist company was
noticed missing.

- `form_matches("8-K/A", ["8-K"])` is true. Prefix matching handles amendments and
  is not the bug.
- `form_matches("SCHEDULE 13D", ["SC 13D"])` is **false**. The whole incident in
  one line, asked of the module rather than of Python. A first draft asserted
  `"SCHEDULE 13D".startswith("SC 13D")` directly, which is a fact about the
  language: true regardless of what `press_monitor` does, and therefore a check
  that could never fail. Calling `form_matches` fails if anyone makes it fuzzy or
  substring-based in an attempt to survive the next rename.
- `form_core("SC 13D/A") == "SC13D"`.
- `drift_candidates` flags `SCHEDULE 13D` against a tracked `SC 13D` **without
  knowing the new spelling in advance**, which is the property that serves the
  next rename rather than only the last one.
- A form in `DRIFT_IGNORE` is never flagged. A warning that always fires is one
  nobody reads.
- A stem shorter than three characters never matches, or the rule flags
  everything and the detector is effectively off.

### `headers_for`

A browser-like User-Agent is a per-host bet. GlobeNewswire stalls a
Chrome-claiming request and answers a plain one in 0.1 seconds; **not knowing that
cost 22 hours of silent outage**, because a stall is indistinguishable from a dead
host until you vary the header.

- A host in `HOST_HEADERS` gets its override.
- Any other host gets `IR_HEADERS`.
- The netloc lookup is case-insensitive, since a miss silently reverts the host to
  the losing bet.

### `check_staleness`

A source can die at HTTP 200 and look healthy in every check.

- **Same-day items collapse before measuring.** The docstring carries the
  measurement: HUT's median gap reads 5.5 days uncollapsed and 18 collapsed.
- Below `STALE_MIN_DAYS` of history it reports a **count** and returns rather than
  warning. Too little history and a dead source must not share a label.
- It warns above the horizon and stays silent below it.
- The log names whichever term set the horizon: median multiple, floor, or
  per-source override.
- It returns `None` and never raises. One source going dark must not affect the
  other thirteen or the EDGAR sweep.

### `suppress_cross_host`

The one where a wrong answer silently eats a real post rather than adding a
spurious one.

- **Exact normalised title only.** 23,771 measured pairs included two genuinely
  different releases at 0.984 similarity, and the near-collisions cluster in
  quarterly results, the highest-value items the channel carries. A test that
  `First Quarter 2022` is not suppressed as a duplicate of `First Quarter 2021`
  is a test that no threshold crept in.
- Outside `CROSS_HOST_DAYS`, nothing is suppressed. The window is what makes exact
  matching safe by construction rather than by tuning.
- **An empty newsroom skips the comparison entirely.** A failed scrape must not be
  mistaken for a successful match against nothing. The bias is to post twice,
  never to suppress.

## Tier 2: the decisions that shape what gets posted

No recorded incident, but each one changes what a reader sees or whether an item
appears at all.

### `always_post_items`

Set intersection, so a filing listing `4.02,9.01` matches on either code whatever
the order. Tests: a matching code in any position posts; a non-matching set does
not; a non-8-K form is never considered; a missing or empty `items` field is safe.

### `carries_press_release`

Decides whether an 8-K is likely to carry a release, from item codes alone rather
than by fetching each index page.

**Its no-items branch has never executed**, and the docstring says so: 1,986 of
1,986 8-Ks across the roster's full history carry item codes. It fails open
deliberately, and the comment warns against "simplifying" it away because it never
fires. **A fixture can execute a branch real data never has**, which is the
cheapest possible insurance against someone deleting it as dead.

Tests: a press-release item code passes; an unrelated one does not; **no items
passes**, exercising the branch; a 6-K is never filtered, since it has no item
numbers at all.

### `filing_title`

Chooses what a reader actually sees.

Tests: 8-K item labels beat SEC's generic document label; generic items yield to
meaningful ones; a duplicate label appears once; `/A` appends `(amended)`; with no
usable items it falls back through `form_label`, then `description`, then
`"{form} filing"`.

### `form_label`

Longest matching prefix wins, and `/A` appends `(amended)`. Tests: a longer prefix
beats a shorter one that also matches; an unknown form returns empty.

### `filed_time`

`filingDate` is a date only, so reading it alone puts publication at 00:00 UTC.
Measured across 122 in-window filings, that **discards a mean of 17.7 hours**,
10.5% of the `MAX_AGE_DAYS` window, and nothing gains less than six hours, because
48% of filings land between 20:00 and 23:00 UTC.

Tests: `acceptanceDateTime` is preferred when present; the date-only fallback is
used when it is not; a malformed value degrades rather than raising.

## Tier 3: the small helpers

Each is a handful of lines, and none has a recorded failure. They get one or two
checks apiece, not a section: enough that a rewrite cannot silently change them,
not so much that the suite reads as padded.

- `filing_uid`: the Atom-era id format, held so switching data sources does not
  make every historical filing look new. One check that the format is exactly the
  legacy string.
- `filing_url`: one check that the accession appears both dashed and undashed.
- `norm_title`: lowercasing, entity and punctuation stripping, stopword removal,
  whitespace collapse. Its output is what `suppress_cross_host` compares, so a
  check that two spellings of one title normalise equal and two different titles
  do not.
- `passes_keywords`: empty `KEYWORDS` passes everything; a match is
  case-insensitive; a non-match fails.
- `entry_time`: prefers `published_parsed`, falls through the alternatives,
  returns `0` when none is usable. That `0` is load-bearing elsewhere: it becomes
  a `released` of `None`, which the body-date rule now refuses.
- `entry_form`: first tag's term wins, whitespace stripped, fallback when absent.

## Tier 4: `baseline_companies`

Covered with fixtures here, and **`test_baseline.py` is left exactly as it is.**

The two are complementary rather than duplicative. `test_baseline.py` checks the
rule against a real recorded event, the 2026-08-05 roster addition, using live SEC
data, and its value is precisely that it is not a fixture. The new checks cover
the rule's arms: a company new to the roster suppresses items older than
`MAX_AGE_DAYS` at that moment, records them rather than dropping them silently,
and a company already on the roster is unaffected.

Replacing a working test that exercises a real incident, in order to make a
coverage number tidier, would be the wrong trade.

## Where the tests live

A new `test_press_monitor.py`, in the repo's existing standalone `check()` style,
printing `N/M checks passed` and exiting non-zero. It joins `Tests`, and that
workflow's coverage gate will require it to be listed there.

### The `feedparser` stub, and its limit

Importing `press_monitor` requires `feedparser`, absent from a plain working copy,
so without a stub this file would be undevelopable locally even though CI installs
it now.

The test stubs `feedparser` in `sys.modules` before importing, with a comment
saying why. **That is safe for this spec's scope and only for it:** `feedparser`
is touched solely by `parse_feed`, which none of these 18 functions calls. If a
future test needs a function that parses feeds, the stub must be removed rather
than extended. A stub that grows is a stub that starts hiding things.

## Verification

**Every check must be demonstrated to fail.** That is the repo's standard, and for
Tier 1 the mutation is named:

- **form matching**: remove `SCHEDULE 13D` from `FORM_TYPES`, confirm the drift
  test fires, restore it. This exact demonstration was used when the detector was
  first built.
- **`headers_for`**: empty `HOST_HEADERS`, confirm the override test fails,
  restore it.
- **`check_staleness`**: drop the same-day collapse, confirm the collapse test
  fails, restore it.
- **`suppress_cross_host`**: widen the match from exact title to substring,
  confirm the 0.984-pair test fails, restore it. This is the mutation that would
  silently eat a real quarterly-results post, so it is the most important of the
  four.

For Tiers 2 to 4, ordinary TDD suffices: each check is written before it passes
and its failure observed. The implementation report records that, and records the
four Tier 1 mutations with their before-and-after output.

A check that passes both with and without the behaviour it names is worse than no
check, because it reads as coverage.

## Out of scope

The 20 functions that fetch, scrape, read a file or post: `sec_get_json`,
`company_filings`, `parse_feed`, `discover_feed`, the two scrapers, the two CMS
readers, `collect_all`, `collect_ir`, `post`, `announcement_body`,
`record_disclosed_dates`, `load_state`, `save_state`, `resolve_ciks`,
`report_feed_health`, `_ops_notice`, `sec_headers`, `main`. Testing those needs
mocking or fixtures of fetched payloads, which is a different technique and its
own decision.

This spec buys confidence in every decision the module makes offline. It does not
buy confidence that the module fetches, parses or posts correctly.
