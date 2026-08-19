# Working on this repo

Fifteen components post to Discord from GitHub Actions crons. [`README.md`](README.md)
lists them; [`docs/`](docs/) covers one per component;
[`docs/watchlist.md`](docs/watchlist.md) holds the roster and identifier rules;
[`docs/local-workflow.md`](docs/local-workflow.md) holds the git mechanics.

**This file is the conventions, and the hazards that are not visible from the
code.** The second half is now the larger one, and that is correct rather than
drift: the code shows what a component does, and nothing in it shows that a
source can die at HTTP 200, that a plausible cross-check can confirm the wrong
answer, or that a window finding nothing has only shown it was too short. A
conventions document would be shorter and less useful.

## Output conventions

**Monospace blocks stay at or under 28 characters.** The README gives the
mechanics. What matters is that it is a ceiling, not a preference: Discord
mobile wraps past that width and splits every table row in two, which is worse
than showing less. A new column means an existing one goes.

**Never identify a company by ticker alone.** Six of nineteen have renamed in
eighteen months, and one ticker on the roster was previously a *different
company's*. A ticker is a display label; pin by CIK for EDGAR and CUSIP for
FINRA and SEC data, both of which survive a rename.

**Show a metric against that ticker's own trailing baseline, never as a bare
absolute.** Is 400,000 fails a lot? For one company it is a normal week, for
another it has never happened. A bare number invites the reader to supply a
baseline from intuition, and intuition here is wrong.

**Every post states its own data latency.** Sources run from minutes old to
three months, and the reader cannot tell by looking. A stale figure read as a
live one is the easiest mistake this channel invites.

**Absence of data is a measurement, not a gap — so report it.** The SEC lists
only non-zero fails, so a ticker missing from a file had zero, and the FTD
monitor stores a literal zero rather than skipping the period. Median over only
the periods where a ticker appeared would average its non-zero periods and erase
the most informative case there is: a name that never fails suddenly failing.

**"Too little history yet" and "the source failed" are different measurements
and must never share a label.** The roster gains listings regularly — WYFI
2025-08, ABTC 2025-09, SPCX 2026-06 — and each one arrives with less history
than every threshold in the repo. A young company reported as a failure trains
the reader to ignore the failure line; worse, a *cause* attached to it stops
them checking at all. `short_interest.py` told the reader that every absent
ticker "usually means a symbol change", which for a new listing is a confident
wrong answer where silence would at least have invited a look.

There is **no shared helper for this, deliberately.** The floors are component
thresholds and belong nowhere near `watchlist.py`, which carries facts about
companies and no behaviour; and the units genuinely differ — sessions, bars,
half-month periods, settlement dates, filings. What is shared is the shape:

| Situation | Treatment |
|---|---|
| In the table, figure computed over a short window | `~` on **the affected column only**, plus a line naming the tickers and the threshold |
| Absent, too little history | Its own line, with a **count against the floor** — `SPCX 37/60 sessions` |
| Absent, source failed | A separate line, no count |

**The count is the part that matters.** A name in a list is an excuse; a count
is a measurement, and it tells the reader both that nothing is wrong and
roughly when it resolves.

Marking the affected column rather than the row is equally deliberate: a short
history invalidates a 52-week position, and leaves close, change and volume
untouched. Marking the ticker would overstate the damage.

Components may still differ on **whether to show the row at all** —
`crossings.py` skips below `MIN_BARS` because a crossing against 37 sessions
is not a 52-week crossing, while `daily_recap.py` keeps the row and caveats one
column. That is a real difference in what the number means, not an
inconsistency to iron out.

`earnings_calendar.py` was the one case still naming tickers without a count.
It now reports `SPCX 1/2` against the periodic-filing floor, so every component
on the roster states a count. Closed 2026-08-12.

## Verification

**Nothing is trusted until a dry run against live data confirms it.** Every
component takes `DRY_RUN`, which evaluates and logs while posting nothing and
saving no state. Reasoning that a URL or a form type is right does not count as
confirming it.

**The run history is a primary source, and it is the one nobody opens.** The
duplicate-post incident of 2026-08-04 was reconstructed from logs and reasoning
while `gh run list` showed the failed `Persist state` step directly, and the
same query turned up **nine** failures across 300 runs when the working
assumption was one. Query it before theorising:

```bash
gh run list --limit 300 --json name,event,conclusion,createdAt -q '.[] | select(.conclusion=="failure")'
```

**A number that is true about something adjacent to the question is not an
answer to the question.** This has now happened three times, and it looks like
evidence every time: one morning's filings taken for the filing-time
distribution, when 23 years of it say the opposite; a 20% hit rate measured on
*daily* workflows used to predict an *hourly* one; and "Alpaca's extended
session opens 4am ET" — which says when data exists, not when spikes occur —
used to argue a window start. Ask what population the number was measured over
before letting it decide anything.

**When one candidate is WIDER than another by construction, comparing them on
a metric that width improves measures nothing.** Three rules for the published
`±` figure were compared on how often the next filing landed inside, and the
winner beat the incumbent by 12 points. All three were symmetric about the same
centre and `(lag - min) + (max - lag) = range` forces them to NEST, so the
ranking was a theorem before the data was read and would hold on any
population, at any window, forever. Held at equal width the ordering reverses,
and a flat `+2` beats the proposal on coverage AND width at every window
tested. **Ask what the losing candidate would score if you simply gave it the
winner's width**, and if that is not measured, nothing has been. The numbers
are in [rejected.md](docs/rejected.md) and
[`probe_lag_coverage.py`](probe_lag_coverage.py).

**A test that has never failed proves nothing.** Adding a guard means first
demonstrating the failure it prevents, with the guard removed. The drift
detector below was validated that way — `SCHEDULE 13D` was taken back out of
`FORM_TYPES` to confirm it flagged it.

**The demonstration only counts if the fixture can reach the branch the check
names, and the natural minimal fixture usually cannot.** Six checks written for
`test_press_monitor.py` could not fail, all six the same shape: empty `items`
reaches `carries_press_release`'s fail-open branch before the 6-K exemption
matters; `10-K405` matches a tracked prefix before `DRIFT_IGNORE` is consulted;
an empty `KEYWORDS` makes the matching arm of `passes_keywords` unreachable; one
key cannot test a preference and one tag cannot test "first". Every one read as
coverage in a green run, and every one came from the plan rather than from the
implementation, so writing them carefully was not what caught them. **Name the
one-line change to the module that turns the check red, then make that change
and watch it.** A mutation that crashes the harness instead of failing the check
has also shown nothing.

**Delete `__pycache__` between mutations, or the run measures the previous
one.** CPython invalidates cached bytecode on the source's mtime and size, so
two mutations that remove the same number of characters within the same second
are indistinguishable to it and the second run silently re-executes the first.
That happened here: two 28-character deletions, and the second mutation
reported the first one's failing check. The wrong answer looks exactly like a
real measurement, which is the whole problem — read the mutated file back and
clear the cache before running.

**"No mutation reddened this check" and "this check cannot fail" are the same
output and different findings.** A mutation sweep reports the checks nothing
turned red. That means either the check is unfailable — the thing worth
knowing — or the mutation for it is simply absent, which looks identical. Six
checks were reported that way on 2026-08-18, hand-checking showed all six went
red under their named change, and the conclusion drawn was that the harness was
untrustworthy. It was not: a slice-based edit anchored on two labels had
deleted the seven mutations sitting between them, and the sweep was reporting
that accurately. **Print the mutation count**, so a list that quietly shrank is
visible; the absence of a mutation is not evidence about the check.

**Identifiers come from data a component actually reads, never from a filing.** A
filing is a lead to verify. The failure modes are not symmetric: a missing
identifier shows up as an unexplained gap, while a wrong one silently attributes
another security's rows to a company that never had them. `docs/watchlist.md`
records the BKKT case that established this.

**A window that finds nothing has shown only that it did not sweep far enough.**
Two identifiers were nearly deleted as phantoms on that mistake — BKKT's
`05759B107` (missed at 12 months, found at 36) and HUT's `44812T102` (missed at
48 periods, found at 120). Match depth to the company's history, not to habit.

## Working locally

**Do not run the component scripts.** They read secrets that exist only in
GitHub Actions, and several post to live Discord channels — a local run is a
real post. Use the workflow:

```bash
gh workflow run "Press release monitor" -f dry_run=true
```

That dispatches against a ref on GitHub, so it tests committed code and cannot
see local edits.

**`watchlist.py` is the exception, and safe to run directly.** It imports only
`sys`, makes no network calls, and its docstring says to run it. It prints and
validates the roster — the fastest check that an edit is sound.

**The `*_state.json` files, `snapshot.json` and `earnings_dates.json` are
outputs**, written by the workflows several times a day. Never edit, delete or
reformat one; a local edit races the next bot commit and usually loses
quietly. `earnings_dates.json` matches neither pattern by name — it is the
press monitor's second output file, protected the same way as the rest; see
`docs/local-workflow.md`.

**Their protection does not survive a re-clone.** The merge driver and
pre-commit hook live in `.git/`, which cannot be committed. Rebuild both from
`docs/local-workflow.md` before working in a fresh clone.

**Pull before pushing, always.** Fourteen workflows commit to `main` through the
day, so a non-fast-forward rejection is the normal case, not the exception.

## Standing traps

Each has happened once. They are listed because none announces itself in the
logs.

**A row with an empty case column has stopped being a row.** The two columns
are the mechanism rather than the decoration — the claim is scanned, the case
is read only on a hit. A row carrying its whole argument in the claim cannot be
skipped, and a table that cannot be skipped is a document. Two rows reached 788
and 657 characters of claim with nothing in the case column before this was
noticed; both moved to `docs/press-monitor.md` and left a claim and a pointer.

That is the test for whether a future trap belongs here at all: **if it cannot
be stated as a claim short enough to skip, it belongs in the component's doc
with a pointer from here.** The longest cases in this table run past 1,100
characters behind claims of 140–160 and are fine, so length is not the measure.

**Grouped 2026-08-13, at eighteen rows.** The rule was to group at roughly
18 to 20 and not before, because the structure costs a reader a level of
navigation and buys nothing while the table is still scannable in one pass.

**A new trap almost always belongs in an existing group. Put it there, and do
not add a group to hold one row.** Four groups were predicted when this was
still one table; the fifth is the split between a source that misled us and a
source that was fine while our own reading of it lost the content, and that
turned out to be the more useful line. Nothing was rewritten in the grouping:
every row is the text it had before.

### Which company is this

Two ways the roster ends up pointing at the wrong company: an identifier that
quietly stops resolving, and one that resolves to somebody else.

| Trap | The case that proves it |
|---|---|
| **A CIK survives renames, reverse splits and a Rule 12g-3 succession — but not a combination creating a new registrant.** | HUT changed CIK while keeping its ticker, so nothing in `alt_symbols` would have caught it. The old CIK returns no filings and no error. |
| **A ticker can be RECYCLED from another company, and in three columns that is indistinguishable from a rename.** The `COLLISIONS` guard cannot catch it on a new company, because it needs a pinned CUSIP to collide with and a new company is added with `"cusips": []`. | `SPCX` was a SPAC ETF until 2026-04-07 and SpaceX from 2026-06-15. The first sweep after SPCX was added proposed the ETF's `19423L672` as a retired CUSIP for SpaceX — right shape, right dates, wrong company — with no collision reported. Only the `DESCRIPTION` column, which `audit_identifiers.py` does not parse, separates them. Refusals are now recorded in `watchlist.REFUSED` and enforced in `ftd_monitor.py`, because the audit re-proposes it on every run. |

### What EDGAR's data actually contains

Each is a place where the obvious reading of an EDGAR field is wrong, and the
wrong reading presents as a fact about the company rather than a fact about EDGAR.

| Trap | The case that proves it |
|---|---|
| **MONTHS OF FILING HISTORY IS NOT MONTHS OF COMPARABLE HISTORY, so it cannot be the young-versus-failed arm for anything read off EDGAR.** | SPCX shows **288 months** of filings, first 2002-08, which reads as the second-oldest company on the roster. It is the newest listing, with **two months** as a public filer — the CIK carries Form D private placements back to SpaceX's founding year. Any baseline built by counting months would be built from private-placement notices. The repo now draws the young-versus-failed distinction in five components and every one of them would get SPCX wrong on a month count; the arm has to be observations of the thing being measured, not age of the CIK. Found while measuring filing rates — see docs/rejected.md. |
| **A FORM FROM A PERIODIC FAMILY DOES NOT ALWAYS REPORT ON A PERIOD. `reportDate` can be a transaction date, and the filing is otherwise indistinguishable from an annual report.** | BTDR's 20-F `0001104659-23-047181` is stamped `2023-04-13` and filed six days later, from its April 2023 SPAC listing. It is a real 20-F and it reports on no year. It contributed a **six-day lag** beside four genuine ones of 88 to 120, which tripled the published spread from 32 to 114 and was the entire reason BTDR carried `~` and `confidence: "low"`. While it was the newest annual filing it also set the roll base, so `cadence` returned a next period of `2024-04-13` beside a fiscal year end of `12`: **one record contradicting itself, for about eleven months.** Nothing errored and nothing looked odd. Measured across the roster on 2026-08-19, **618 of 619 periodic `reportDate`s land exactly on a calendar month end and this one sits 13 days out**, so `covers_a_period` rejects at 6 days: the middle of an empty gap rather than a tuned threshold. The slack exists at all because a 52/53-week fiscal year ends on a fixed weekday and can miss a month end by four days; no roster member uses one, and a guard that fires on the first one added would be worse than the bug. |
| **EDGAR renames form types**, and prefix matching does not bridge a rename — `"SCHEDULE 13D".startswith("SC 13D")` is `False`. | `SC 13D` became `SCHEDULE 13D` around December 2024 and silently missed 117 filings, found only when a real one went unposted. `press_monitor.py` carries a drift detector. |
| **EDGAR's `primaryDocument` for a structured filing points at the XSL-RENDERED VIEW, not the source. Parsing it as XML fails in a way that reads as "this filing is not structured after all".** | Structured Schedule 13D/G lists `xslSCHEDULE_13D_X02/primary_doc.xml`. Fetch that and you get HTML; `ElementTree` dies on the first unclosed tag, and the natural conclusion — *these are not really structured* — is wrong. **Three companies were written off that way before the pattern was spotted; the next reader would write off nineteen.** The source sits in the same accession directory with the stylesheet segment stripped. The lesson generalises past 13D/G: a parse failure is evidence about the URL before it is evidence about the data. |
| **EDGAR's web filing index renders EASTERN; the submissions API returns UTC. Mixing the two sources manufactures a four-hour error and a confirmation for it.** | This row previously said `acceptanceDateTime` is Eastern despite ending in `Z`, "confirmed twice". **Both confirmations were artefacts and the field is UTC.** The 8-K cited as proof is stamped `12:05:19` in the API — matching the IR feed's 12:05 UTC exactly, not sitting four hours behind it; the `08:05` was read off the web index, which renders ET. The second argument confused **dissemination** hours (06:00–22:00 ET) with acceptance, which EDGAR takes around the clock, so nothing is out of range. Settled by SEC's own next-business-day rule applied per form — 22:00 ET for Section 16 forms 3/4/5, 17:30 ET otherwise — which puts 98% of before-cutoff filings on a same-day `filingDate` under the UTC reading against 76% under Eastern, and by a Form 4 stamped `23:00:06` keeping a same-day date, impossible past a 22:00 ET cutoff but ordinary at 19:00 ET. **No production code reads the field, so nothing was ever mis-timestamped** — there is no damage to go looking for. The durable lesson is not the timezone: it is that a plausible cross-check can confirm the wrong answer, and that two of them agreeing means nothing when both draw on the same mistaken source. |

### Silence, and output that looks normal and is not

The largest group, and the reason this file exists: not one of these produces
an error or anything in the logs worth looking at.

| Trap | The case that proves it |
|---|---|
| **A pattern matching nothing looks exactly like one whose matches never occur**, and that is as true of a trigger as of data. | Both give no posts, no errors, no log lines. An entry in `FORM_TYPES` is an assumption until a filing of that type has actually posted, and a `paths:` filter is an assumption until a push has actually fired the workflow, which is why `tests.yml` carries both `*.py` and `**/*.py` rather than betting on one. |
| **SEC's fair-access filter rejects a GitHub noreply address**; it wants a plain name and contact address. | The noreply form returns **403 from every sec.gov endpoint**, in both `urllib` and `requests`. Six components send `SEC_USER_AGENT`, so a wrong value fails all six at once and reads like an SEC outage. |
| **A BROWSER-LIKE USER-AGENT IS A PER-HOST BET, NOT A SAFE DEFAULT, and losing the bet presents as a dead host rather than a refusal.** | GlobeNewswire stalls a browser-claiming request from the runner and answers a plain one in 0.1s. Measured across six header sets against two URLs — the org feed and an ordinary release page — Chrome/126, Chrome/140, Firefox/131 and a feed-reader UA all `ReadTimeout`; python-requests, curl, no UA and an identifying UA all return 200 with 20 entries. `press_monitor.py`'s own comment asserted the opposite as a general rule, and it is only true for the *other* fifteen sources. BGDE's feed was never dead: it served 20 entries throughout, to anyone not claiming to be Chrome. **The cost of not knowing this was 22 hours of silent outage and five probe dispatches**, because a stall is indistinguishable from a dead host until you vary the header. Overrides live in `press_monitor.HOST_HEADERS`; a new source needs measuring, not assuming. |
| **A SOURCE THAT KEEPS SERVING ITEMS AND STOPS SERVING READABLE DATES loses every one of them permanently, and passes all three checks meant to catch a broken source.** | A `published` of `0` reads as 1970, so the age floor drops the item — and `main()` marks items seen *before* that floor, so it is recorded as seen and never retried. Five paths mint that `0`: `entry_time` for an unparsable feed timestamp, and four scrapers and CMS readers whose own format strings can fail. `report_feed_health` passes because entries were returned; `check_staleness` passes because all-zero timestamps are treated as no timestamps and it logs nothing; the scraper's parse-failure line passes because the item count is normal. **Measured 0 of 223 items across all twenty IR sources on 2026-08-13**, so `undated_items()` will report zero for a long time — which is not a reason to delete it, any more than for `carries_press_release`'s no-items branch. [press-monitor.md → dates break](docs/press-monitor.md#critical-a-source-whose-dates-break-is-silent-in-all-three-checks) |
| **A source can die at HTTP 200 and look healthy in every check.** | DGXX's old GlobeNewswire feed serves 20 items, valid XML, good uid and timestamp on each, nothing newer than 2025-12-24; its sitemap lists 100 release URLs sharing one rebuild `lastmod`. Both passed every test this repo had. Bakkt's platform move broke loudly with a 404 — that is the rare case. See `check_staleness()` and `calibrate_staleness.py`. |
| **A GUARD THAT LIVES INSIDE ONE COMPONENT PROTECTS ONE COMPONENT, and every other component keying on its own state floods the day a company is added — with posts that are each individually correct.** | `holder_events` sent **86 messages** on 2026-08-14, CORZ 39 of 39 and CRWV 30 of 32, because for a company absent from its state file every 13D/G on record is a first appearance, which is what it reports. `press_monitor` had had the per-company rule since 2026-08-09 and suppressed the same three companies in the same window. **The audit that was read as settling this asked a different question**: [press-monitor.md](docs/press-monitor.md) scores components for what a MISSED RUN costs, where `comment_letters`' 180-day window is the safest on the roster; on the roster-addition axis the same number is the worst, and `holder_events` was not in the table at all. Five components shared the shape, so the decision moved to `first_run.py` and what suppression *means* stayed put. **Its backfill is invisible by construction** — it records every key and returns nothing, so all five dry runs went green printing nothing about the rule, and a component that ran it looked identical to one where it was never wired. That is why `backfill_note` exists. **The same shape rotated is a CAPABILITY added rather than a company** — every filing of a newly tracked form type is unseen at once, and Form 144's addition on 2026-08-13 escaped only because a seven-day age floor happened to cover it. Guarded since 2026-08-14, and the guard has its own trap: three of the four tracked sets are matched by PREFIX, so "newly tracked" must mean *the previous set would not have matched it* — measured against the RECORD, not the current config, or an edit that REPLACES a key silences a form that has been posting for months. |
| **A RECORD THAT SAYS A COMPANY IS ESTABLISHED IS A CLAIM THE RUN HAS TO HAVE EARNED, and recording one it never measured is the same bug rotated.** | `first_run.baseline_by_cik` marks the whole roster established on the backfill run, whether or not the component produced the per-company state its suppression rests on. Four days after the rule landed: `dilution_state.json` held **22 CIKs against 18 share counts** and `crossings_state.json` **22 against 21 armed flags**. The cost is dated rather than theoretical — SPCX sat at **46 of MIN_BARS=60 sessions** and was already recorded, so on the run it cleared the floor `setdefault` would have created it ARMED and it would have announced a 52-week crossing that predates the watch, which is the one assertion that component must never make. The skip that matters is NOT the fetch fault: an untagged filer or a ticker below a history floor is a settled fact rather than an error, prints nothing alarming, and is exactly what gets recorded. Fixed by PRUNING rather than recording late, because `baseline` is append-only and only a delete repairs a record already on disk. **THE PRUNE NEEDS TWO CONDITIONS, and the first draft had one**: pruning on "not measured this run" alone un-establishes a company on a transient failure, and since a suppressed item is already in `seen` or already overwritten, the next run loses a real event PERMANENTLY where a missed run used to cost nothing — the same criterion that exempts `press_monitor`, applied to two components it also disqualifies. The second condition is that the component holds no per-company state for the key. Measured: the roster members holding none were exactly the five wrongly recorded. **`press_monitor` has the same exposure and is deliberately not fixed**: there the record and the suppression are one lever and items are marked seen before filtering, so a prune converts a bounded flood into permanent item loss. |
| **TWO COMPONENTS ANSWERING THE SAME QUESTION FROM THE SAME SOURCE WILL DRIFT, and the one without a suite is the one that is wrong.** | `earnings_calendar` and `build_snapshot` both project each issuer's next report off the EDGAR index. Until 2026-08-19 the second had no tests and two defects the first had already fixed: it rolled THREE MONTHS for an annual-only filer, publishing BTDR against a period a 20-F filer never reports on with an `expected` date a month in the past; and it accepted a SINGLE 10-Q as a cadence, publishing SPCX as `quarterly, sample 1` while the other component refused the same company as `SPCX 1/2`. Neither errored, both look like ordinary values, and `snapshot.json` is a wire format another project reads every weekday. The fix is to IMPORT the rule, not to copy the corrected version across — `threshold_list` derives its two roster maps from `watchlist` for the same reason, after hand-maintaining both directions once mapped GREE to the wrong company. |
| **`max(set(xs), key=xs.count)` RESOLVES A TIE BY HASH SLOT, so two callers passing the same data in different orders get different answers.** Moving a rule into a shared module does not by itself make it order-independent. | `filing_cadence.fiscal_year_end_month` was exactly that expression. On a tie the winner is whichever month the set yields first, which is insertion order **only when the two collide in CPython's table** — the pairs `(1,9)`, `(2,10)`, `(3,11)` and `(4,12)`, everything else being stable. `earnings_calendar` passes filings newest by FILED date and `build_snapshot` newest by PERIOD, deliberately and documented, so the same issuer with one April and one December annual period publishes **fiscal year end 12 to Discord and 4 to `snapshot.json`**. Two lines demonstrate it. `(4,12)` is BTDR's exact shape. This is the drift the module was written to end, sitting inside the module, surviving the merge that closed it everywhere else: **sharing the code shares the decision, not the determinism.** The window is now taken by period rather than by position for the same reason, and the tie goes to the newer period — safe only because the row above removes transaction dates first, since recency alone would have handed BTDR April 2023. |
| **A soft-404 makes a wrong link indistinguishable from a right one.** | `digipowerx.com` answers 200 with wrong content for an unknown release URL, so a derived slug resolving 6 of 8 would have posted two dead links and logged nothing. Confirm a site actually 404s before trusting a constructed URL. See `read_dgxx()`. |

### What a page said, and what we read out of it

The source was healthy in all three. The loss happened in our own reading of it.

| Trap | The case that proves it |
|---|---|
| **A `<script>` block can hold the ARTICLE rather than code, so stripping scripts before reading deletes the text you were reading for, and the result is indistinguishable from a page that served no body.** | HUT's 121,286-byte release page reduced to 1,227 characters of headline, posting date and signup form, with the reporting date sitting in a `__NUXT_DATA__` payload. `docs/press-monitor.md` had recorded "no rule reading bodies will ever recover it from this source" as settled fact. `page_text.extract_text()` now recovers `application/json` string values, joined with `" | "` so no date can be manufactured across a string boundary. See `docs/press-monitor.md`. |
| **A default sort is not a date sort, and document order is not date order.** | DGXX's CMS returns a 2025-11-19 item first on an unsorted page 1, so `rows[0]` reports something eight months stale as newest; Hut 8's page interleaves recent and old in markup order. Sort explicitly by date; never trust position. |
| **A DATE FILTER THAT DROPS ONLY EARLIER DATES KEEPS THE BODY'S OWN DATELINE, and every release carries one. It inverts a measurement without failing anything.** | `candidate_dates` dropped a date only when `when < released`, so a date EQUAL to the release date survived, and a press release opens with exactly that: "MIAMI, Aug. 4, 2026 --". `probe_body_dates`' first run reported `advance notice one=1, several=5`, which reads as a plain verdict that no rule is possible. Excluding the dateline turned the same twenty rows into `one=5, several=0`. **The counts were the entire output and they were exactly backwards.** It then bit from the other side: `entry_time()` returns `0` for a feed entry whose timestamp will not parse, so `released` becomes `None`, and `candidate_dates` documents that with no baseline every date survives. The dateline would have been STORED as an announced date, marked `+`, and gone Overdue ten days later against a date no company ever gave; it is now refused as `no-baseline` and counted. The boundary is the whole trap: `<` against `<=`, and neither version errors, logs, or fails a test that was not written for it. |

### Scheduling and concurrency

GitHub Actions behaves differently from how its documentation reads, and every one of these was established by measurement here.

| Trap | The case that proves it |
|---|---|
| **`concurrency` prevents overlap, not staleness. A queued run checks out the SHA fixed when the run was CREATED, not when its job starts.** | Two press-monitor runs were serialised exactly as the concurrency group intended, and the second still began from the commit before the first one's state push. It loaded a stale `state.json` and reposted three items to Discord; the two runs' logs are identical. The rejected push at the end was the symptom, not the harm. Both halves of the fix are needed: `git pull` before the monitor step so the run reads current state, and a fetch-and-retry loop around the push so it writes onto the current tip. **As of 2026-08-04 the retry loop had still never executed anywhere:** every run since it landed was a dry dispatch, which saves no state and stops before the push, and the last live scheduled runs predate the commit. Only a live run that finds something new will exercise it, and manufacturing one means real posts. Do not read the surrounding work looking finished as evidence that this part ran. |
| **A `concurrency` group already supersedes queued runs, so never build that yourself.** | At most one run is ever pending and a newer arrival cancels the older one, so the survivor is always the freshest checkout — the opposite of what `cancel-in-progress: false` reads like. Established by experiment; a queued run must never detect its own supersession and exit. [press-monitor.md → Supersession](docs/press-monitor.md#supersession-the-concurrency-group-already-keeps-the-newest-run) |
| **A scheduled run on this repo is never on time, and a changed cron does not take effect for hours.** | All 30 scheduled runs measured were 51–173 minutes late, none inside GitHub's documented drift; all 17 cron epochs took 55 minutes to 2h 53m to register. So a schedule that has not fired an hour after you push it is normal, and any interval reasoned from a nominal cron time is wrong. [press-monitor.md → never on time](docs/press-monitor.md#measured-scheduled-runs-on-this-repo-are-never-on-time) |
