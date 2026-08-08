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

`earnings_calendar.py` is the one case still naming tickers without a count.
It is correct, just less useful than it could be.

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

**A test that has never failed proves nothing.** Adding a guard means first
demonstrating the failure it prevents, with the guard removed. The drift
detector below was validated that way — `SCHEDULE 13D` was taken back out of
`FORM_TYPES` to confirm it flagged it.

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

**The `*_state.json` files and `snapshot.json` are outputs**, written by the
workflows several times a day. Never edit, delete or reformat one; a local edit
races the next bot commit and usually loses quietly.

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

**Group at roughly 18–20 rows, not before.** The clusters are already latent —
identifiers and the roster; what EDGAR's data actually contains; a source that
looks healthy and is not; scheduling and concurrency — and new traps land in an
existing one far more often than they create one. But adding that structure at
fifteen costs a reader a level of navigation to save them nothing, and the
clusters sitting there visibly is not a reason to build them.

| Trap | The case that proves it |
|---|---|
| **MONTHS OF FILING HISTORY IS NOT MONTHS OF COMPARABLE HISTORY, so it cannot be the young-versus-failed arm for anything read off EDGAR.** | SPCX shows **288 months** of filings, first 2002-08, which reads as the second-oldest company on the roster. It is the newest listing, with **two months** as a public filer — the CIK carries Form D private placements back to SpaceX's founding year. Any baseline built by counting months would be built from private-placement notices. The repo now draws the young-versus-failed distinction in five components and every one of them would get SPCX wrong on a month count; the arm has to be observations of the thing being measured, not age of the CIK. Found while measuring filing rates — see docs/rejected.md. |
| **EDGAR renames form types**, and prefix matching does not bridge a rename — `"SCHEDULE 13D".startswith("SC 13D")` is `False`. | `SC 13D` became `SCHEDULE 13D` around December 2024 and silently missed 117 filings, found only when a real one went unposted. `press_monitor.py` carries a drift detector. |
| **A CIK survives renames, reverse splits and a Rule 12g-3 succession — but not a combination creating a new registrant.** | HUT changed CIK while keeping its ticker, so nothing in `alt_symbols` would have caught it. The old CIK returns no filings and no error. |
| **A ticker can be RECYCLED from another company, and in three columns that is indistinguishable from a rename.** The `COLLISIONS` guard cannot catch it on a new company, because it needs a pinned CUSIP to collide with and a new company is added with `"cusips": []`. | `SPCX` was a SPAC ETF until 2026-04-07 and SpaceX from 2026-06-15. The first sweep after SPCX was added proposed the ETF's `19423L672` as a retired CUSIP for SpaceX — right shape, right dates, wrong company — with no collision reported. Only the `DESCRIPTION` column, which `audit_identifiers.py` does not parse, separates them. Refusals are now recorded in `watchlist.REFUSED` and enforced in `ftd_monitor.py`, because the audit re-proposes it on every run. |
| **EDGAR's `primaryDocument` for a structured filing points at the XSL-RENDERED VIEW, not the source. Parsing it as XML fails in a way that reads as "this filing is not structured after all".** | Structured Schedule 13D/G lists `xslSCHEDULE_13D_X02/primary_doc.xml`. Fetch that and you get HTML; `ElementTree` dies on the first unclosed tag, and the natural conclusion — *these are not really structured* — is wrong. **Three companies were written off that way before the pattern was spotted; the next reader would write off nineteen.** The source sits in the same accession directory with the stylesheet segment stripped. The lesson generalises past 13D/G: a parse failure is evidence about the URL before it is evidence about the data. |
| **A form type matching nothing looks exactly like one whose filings never occur.** | Both give no posts, no errors, no log lines. An entry in `FORM_TYPES` is an assumption until a filing of that type has actually posted. |
| **SEC's fair-access filter rejects a GitHub noreply address**; it wants a plain name and contact address. | The noreply form returns **403 from every sec.gov endpoint**, in both `urllib` and `requests`. Six components send `SEC_USER_AGENT`, so a wrong value fails all six at once and reads like an SEC outage. |
| **A source can die at HTTP 200 and look healthy in every check.** | DGXX's old GlobeNewswire feed serves 20 items, valid XML, good uid and timestamp on each, nothing newer than 2025-12-24; its sitemap lists 100 release URLs sharing one rebuild `lastmod`. Both passed every test this repo had. Bakkt's platform move broke loudly with a 404 — that is the rare case. See `check_staleness()` and `calibrate_staleness.py`. |
| **A soft-404 makes a wrong link indistinguishable from a right one.** | `digipowerx.com` answers 200 with wrong content for an unknown release URL, so a derived slug resolving 6 of 8 would have posted two dead links and logged nothing. Confirm a site actually 404s before trusting a constructed URL. See `read_dgxx()`. |
| **A default sort is not a date sort, and document order is not date order.** | DGXX's CMS returns a 2025-11-19 item first on an unsorted page 1, so `rows[0]` reports something eight months stale as newest; Hut 8's page interleaves recent and old in markup order. Sort explicitly by date; never trust position. |
| **EDGAR's web filing index renders EASTERN; the submissions API returns UTC. Mixing the two sources manufactures a four-hour error and a confirmation for it.** | This row previously said `acceptanceDateTime` is Eastern despite ending in `Z`, "confirmed twice". **Both confirmations were artefacts and the field is UTC.** The 8-K cited as proof is stamped `12:05:19` in the API — matching the IR feed's 12:05 UTC exactly, not sitting four hours behind it; the `08:05` was read off the web index, which renders ET. The second argument confused **dissemination** hours (06:00–22:00 ET) with acceptance, which EDGAR takes around the clock, so nothing is out of range. Settled by SEC's own next-business-day rule applied per form — 22:00 ET for Section 16 forms 3/4/5, 17:30 ET otherwise — which puts 98% of before-cutoff filings on a same-day `filingDate` under the UTC reading against 76% under Eastern, and by a Form 4 stamped `23:00:06` keeping a same-day date, impossible past a 22:00 ET cutoff but ordinary at 19:00 ET. **No production code reads the field, so nothing was ever mis-timestamped** — there is no damage to go looking for. The durable lesson is not the timezone: it is that a plausible cross-check can confirm the wrong answer, and that two of them agreeing means nothing when both draw on the same mistaken source. |
| **`concurrency` prevents overlap, not staleness. A queued run checks out the SHA fixed when the run was CREATED, not when its job starts.** | Two press-monitor runs were serialised exactly as the concurrency group intended, and the second still began from the commit before the first one's state push. It loaded a stale `state.json` and reposted three items to Discord; the two runs' logs are identical. The rejected push at the end was the symptom, not the harm. Both halves of the fix are needed: `git pull` before the monitor step so the run reads current state, and a fetch-and-retry loop around the push so it writes onto the current tip. **As of 2026-08-04 the retry loop had still never executed anywhere:** every run since it landed was a dry dispatch, which saves no state and stops before the push, and the last live scheduled runs predate the commit. Only a live run that finds something new will exercise it, and manufacturing one means real posts. Do not read the surrounding work looking finished as evidence that this part ran. |
| **A `concurrency` group already supersedes queued runs, so never build that yourself.** | At most one run is ever pending and a newer arrival cancels the older one, so the survivor is always the freshest checkout — the opposite of what `cancel-in-progress: false` reads like. Established by experiment; a queued run must never detect its own supersession and exit. [press-monitor.md → Supersession](docs/press-monitor.md#supersession-the-concurrency-group-already-keeps-the-newest-run) |
| **A scheduled run on this repo is never on time, and a changed cron does not take effect for hours.** | All 30 scheduled runs measured were 51–173 minutes late, none inside GitHub's documented drift; all 17 cron epochs took 55 minutes to 2h 53m to register. So a schedule that has not fired an hour after you push it is normal, and any interval reasoned from a nominal cron time is wrong. [press-monitor.md → never on time](docs/press-monitor.md#measured-scheduled-runs-on-this-repo-are-never-on-time) |
