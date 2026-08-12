[← Watchlist monitor](../README.md)

# Press release monitor

Watches SEC EDGAR filings and company IR newsrooms, and posts anything new to a
Discord channel.

## How it works

Two sources, two output channels.

Sources:

1. **SEC EDGAR** — ten form types (see `FORM_TYPES`), read from the
   submissions API (`data.sec.gov/submissions/CIK##########.json`). One
   request per company returns every recent filing. Authoritative, but trails
   the newswire by minutes to hours.
2. **IR newsroom RSS** — the company's own feed. Faster than EDGAR, but not
   every company publishes one.

Channels:

- **Main** (`WEBHOOK_URL`) — press releases and filings.
- **Insider** (`WEBHOOK_URL_INSIDER`, optional) — Form 4 and 4/A only.

New items are deduped against `state.json` and posted once each.

**A second output file.** Every non-dry run also extracts announced reporting
dates out of item titles and writes `earnings_dates.json`, keyed by CIK. This
runs over every item fetched, not only the ones that post, and it runs before
the posting loop — a failure inside it is caught and logged rather than
allowed to abort `main()`, so it can never cost a press post. The [earnings
calendar](earnings.md) reads the file and overlays a disclosed date onto its
own projection, marked `!`. See `record_disclosed_dates()` in
`press_monitor.py` and `earnings_dates.py`.

## Schedule

`7 10-23 * * 1-5` — **once an hour**, weekdays, 10:00–23:59 UTC. The job then
polls internally on each fifteen-minute boundary until its budget runs out.

GitHub cron is UTC with no DST awareness, so the window is set wide enough to
cover the US pre/postmarket release windows year-round without seasonal edits:

- EDT (Mar–Nov): 06:00–19:59 Eastern
- EST (Nov–Mar): 05:00–18:59 Eastern

10:00 UTC is 06:00 Eastern, EDGAR's own opening time.

**That justification is weaker than it reads, and the window is very likely
wrong.** It was chosen on the reasoning that EDGAR opens at 10:00 UTC and that
pre-market releases cluster early — which came from a single morning's
filings, 10:31 to 11:37 on 2026-08-04. Measured against the roster's whole
history it is not what happens. See the distribution below.

### When filings actually arrive

Every `acceptanceDateTime` EDGAR reports for the roster: **7,886 weekday
filings, 2003 to 2026**, measured 2026-08-05. Times are UTC — that field is
UTC despite what the trap table used to say, see
[`CLAUDE.md`](../CLAUDE.md).

| UTC hour | filings | | UTC hour | filings |
|---|---|---|---|---|
| 10:00 | 218 | | 18:00 | 240 |
| 11:00 | 331 | | 19:00 | 303 |
| 12:00 | 445 | | **20:00** | **1442** |
| 13:00 | 371 | | **21:00** | **1590** |
| 14:00 | 217 | | **22:00** | **841** |
| 15:00 | 170 | | 23:00 | 438 |
| 16:00 | 208 | | 00:00 | 283 |
| 17:00 | 210 | | 01:00 | 305 |

- **20:00–23:00 UTC holds 4,311 filings — 55%.** That is 16:00–19:00 Eastern,
  the after-close filing rush, and it is where the mass is.
- **10:00–14:00 UTC holds 1,365 — 17%.** The pre-market morning the window was
  built around is the thin part of the day.
- **00:00–06:00 UTC holds about 1,090 — 14%** and sits outside the window
  entirely.

The lesson is not about the schedule. One morning's filings were treated as a
distribution, and a distribution measured across 23 years says something close
to the opposite. Anchoring on a single observation is how the window came to be
aimed at the quietest hours.

### The same distribution decides how much of the age window is real

The schedule is not the only thing this shape governs. `MAX_AGE_DAYS` is
measured from an item's publication time, and `filingDate` is a DATE with no
clock on it, so reading it alone puts publication at 00:00 UTC and charges
every filing for the whole of the day it was actually filed in.

With 55% of filings landing between 20:00 and 23:00, that is most of a day
thrown away for most of the roster. Measured across the 122 in-window tracked
filings on the nineteen-company roster, 2026-08-05:

| | hours recovered |
|---|---|
| mean | **17.7** |
| median | **20.1** |
| minimum | 6.0 |
| maximum | 25.7 |

**10.5% of the seven-day window**, and nothing gains less than six hours.
`acceptanceDateTime` carries the real time, is UTC, and was present on 10,201
of 10,201 filings across every company, form type and age, so `filed_time()`
now reads it and falls back to midnight only defensively.

The maximum exceeding 24 hours is correct rather than a parsing fault. SEC
credits a filing accepted after its cutoff to the previous business day, so an
item can carry `filingDate` 2026-07-08 and acceptance 2026-07-09T01:41Z. Seven
of the 122 are in that position. Age is measured backwards from now, so a later
publication time simply means a younger item; none reads as filed in the future.

**The collection horizon deliberately still uses the date.** `RETAIN_DAYS`
decides which filings are worth collecting, compares a date against a date, and
does not want a clock. Making the two consistent is the obvious tidy-up and it
would move a boundary that is correct where it is.

### The largest remaining gap, and why it is not being closed yet

Simulated against the measured filing and delay distributions, `07:07` catches
**85%** of filings within fifteen minutes, against 77% for the old `10:07`.
Inside an active run coverage is 100% for every half hour from 10:00 to 15:00 —
**the entire residual is one contiguous block, 00:00–06:00 UTC.** That is about
1,090 filings, 14% of the roster's history, or closer to **9.5%** once the
23:07 fire is credited for reaching past midnight, which the simulation did not
model.

**Extending the window end is the only thing that reaches it, and it is
deliberately deferred.** There is no delay measurement below 05:00 UTC at all —
the morning regime was measured from 05:00 and the evening to 23:59 — so
choosing an end time now would be reasoning from a distribution nobody has
measured, which is the same error the 10:00 start was built on.

The measurement arrives on its own: the new `07:07` and `08:07` fires sit in a
span that previously had no data, so about a week of them gives something to
reason from.

**A heartbeat is deferred for the same reason.** The failure notice below
catches failures, not absences, and absence is the more common failure here — a
dropped scheduled run produces no event at all. A heartbeat that complains when
no run has been seen in N hours is the thing that would catch it, but N is
unmeasured for a third of the day, and a heartbeat with a guessed threshold
either cries wolf or sleeps through the thing it exists for. **Deferred pending
the small-hours delay data, not overlooked.**

### Why the granularity moved off the cron and into the job

Asking GitHub for `*/15` did not produce a check every fifteen minutes. It
produced two or three runs a day out of 48 requested. Asking once an hour and
generating the fifteen-minute cadence inside the job puts the part that has to be
reliable somewhere GitHub cannot drop it.

`volume_spike.py` runs the same shape on the same reasoning — see
[volume-spikes.md](volume-spikes.md).

### Measured: scheduled runs on this repo are never on time

Measured 2026-08-04 across all 30 scheduled runs the repo had produced, comparing
each run's creation time against its own cron:

```
n=30   min=51m   median=70m   mean=95m   max=173m
within GitHub's documented 15-25 min drift: 0 of 30
```

**The delay is bimodal by time of day**, and the split is not subtle:

| regime | n | delay |
|---|---|---|
| 05:00–15:59 UTC (US morning) | 14 | 83–173 min, mean **134** |
| 16:00–23:59 UTC (US afternoon/evening) | 16 | 51–71 min, mean **61** |

Per workflow, delay of each run in minutes:

| workflow | cron | delays |
|---|---|---|
| threshold | `15 5 * * 2-6` | 142, 152 |
| snapshot | `0 11 * * 1-5` | 153, 113 |
| earnings | `30 12 * * 1` | 173 |
| ftd | `0 13 * * *` | 134, 83, 85, 159, 140 |
| letters | `30 13 * * 1-5` | 154, 147 |
| dilution | `0 15 * * 1-5` | 132, 116 |
| monitor | `7 10-23 * * 1-5` | 52 |
| spikes | `9 10-22 * * 1-5` | 51 |
| btc | `15 21 * * 1-5` | 63, 60, 61 |
| grid | `20 21 * * 1-5` | 66, 69 |
| recap | `30 21 * * 1-5` | 64, 61, 62 |
| crossings | `45 21 * * 1-5` | 55, 53 |
| shortinterest | `0 22 * * 1-5` | 60, 61 |
| regsho | `0 23 * * 1-5` | 63, 71 |

Three consequences worth carrying:

1. **A nominal time is not a real time.** `7 10-23` means the first check of the
   day lands somewhere between 11:00 and 13:00 UTC, not 10:07. The intended
   06:00 Eastern opening is really 07:00 Eastern at best.
2. **The morning half of this window is the slow half**, which is also when
   filings actually arrive.
3. **The old `*/15` "hit rate" was probably never a hit rate.** If every fire is
   delayed 50–170 minutes, pending fires coalesce and survivors emerge roughly
   one an hour. "48 asked, 3 arrived" is what that looks like counted as a rate.

### Supersession: the concurrency group already keeps the newest run

**Never build queue-position detection. The platform does it, and it keeps the
right one.**

With `cancel-in-progress: false` the obvious reading is that runs queue up and
drain in order. They do not. **At most one run is ever *pending*, and a newer
arrival cancels the older pending one** — so the survivor is always the newest,
and therefore the one with the freshest checkout.

Established by experiment, because the config reads the other way. Three
dispatches into `press-monitor`:

| | state |
|---|---|
| A | `in_progress` |
| B | `pending` |
| C arrives | B goes `cancelled`, C becomes `pending` |

**A queued run must not try to detect that it has been superseded and exit.**
The platform has already done it and kept the right one, and a run that does
start is not doing stale work anyway — "check for new items now" is a timeless
question, so a late start asks the same question with better data.

This is why the ~3% cancellation rate at `BUDGET_MIN=55` is routine rather
than a fault, and why `failure-notice.yml` never reports `cancelled`.

### Registration lag when a cron changes

A new or changed cron does not take effect immediately. Measured across all 17
cron epochs in the repo's history: **55 minutes to 2h 53m**, with changed crons
(1h 22m, 1h 51m, 1h 52m, 2h 22m) behaving no differently from new ones.

A schedule that has not fired an hour after landing is normal and not evidence of
anything. Wait before diagnosing.

### The poll budget is elapsed time, not the top of the hour

The loop runs one pass immediately and one on each fifteen-minute boundary until
`BUDGET_MIN` minutes have elapsed **since the job started**.

It was originally "run until the top of the next hour", which is wrong here for
exactly the reason above: a fire nominally at `:07` arrives near `:59`, so a
wall-clock-hour deadline granted it seconds rather than an hour. On 2026-08-04 a
live run started its step at 17:00:04 and ran four passes; six seconds earlier it
would have run one, and printed `1 pass(es), 0 failed` while doing it.

Swept across every start position in an hour:

| passes | wall-clock frame | elapsed frame |
|---|---|---|
| 1 | 30 | 0 |
| 2 | 30 | 0 |
| 3 | 30 | 0 |
| 4 | 30 | 64 |
| 5 | 0 | 56 |

75% of start positions gave fewer than four passes, a quarter gave exactly one,
and a fire landing on the half hour gave two.

Every run states its plan up front and names both numbers when it stops, so a run
that does one pass legitimately is distinguishable from one that does so through
bad arithmetic:

```
Poll plan: start 17:00:04Z, budget 55m, deadline 17:55:04Z, one pass now and one on each 15-minute boundary before it.
...
Next boundary 18:00:00Z is past the deadline 17:55:04Z. Stopping after 4 pass(es).
4 pass(es), 0 failed, 55m budget, ran 45m.
```

**`BUDGET_MIN` is 55 and is very likely wrong.** It was set from the only two
observations available at the time — 51 and 52 minutes — and both came from
16:07 and 17:09 fires, squarely in the fast regime. The morning half of the
window runs 83–173 minutes late, so morning arrivals will be spaced far wider
than 55 minutes and coverage will have gaps there. The budget *value* and the
window *start* are both open, and both need morning delay data that did not exist
when this was written.

### Overlapping runs need no handling

A ~60-minute arrival gap against a ~55-minute run means a fire can arrive while
the previous one is still going. This is safe and needs nothing added — see the
supersession trap in [`CLAUDE.md`](../CLAUDE.md).

## Configuration

Everything lives in the CONFIG block at the top of `press_monitor.py`.

**`EXTRA_CIKS`** — `watchlist.ciks()`. The roster, pinned by CIK rather than
ticker. CIKs are permanent; tickers are not. This sector renames constantly
(BGDE renamed Apr 2026, VIP Jul 2026, ANY has a pending change to
DarkHorse/DRK), and SEC's ticker lookup file lags renames by weeks. Pinning by
CIK sidesteps that entirely. `TICKERS` is left empty as a result, but still
works if you'd rather add a company by symbol. See
[the watchlist](watchlist.md).

**`IR_FEEDS`** — `watchlist.ir_feeds()`, **ticker → URL**. Accepts either a
direct feed URL or a newsroom page; if the URL isn't a feed, the script reads
the page's `<link rel="alternate">` tag and uses whatever feed it finds.

This map was previously keyed by *display label* — a mix of tickers (`MARA`,
`IREN`) and company names (`CleanSpark`, `Soluna`, `Bakkt`). Nothing joined a
feed to its company, so a company could be dropped from the watchlist while its
feed kept being polled, and nothing would notice. Keying by ticker makes the
join structural. Feed URLs are unchanged; only the log labels differ.

**`FORM_TYPES`** — ten forms, exploiting EDGAR's prefix matching so that
`8-K` also catches `8-K/A`, `424` catches `424B1`–`424B8`, and `SC 13D` catches
its amendments:

| Form | Why |
|---|---|
| `8-K` / `6-K` | Material events; press releases as EX-99 |
| `424` | Prospectus supplements — offerings being priced. Dilution. |
| `10-Q` / `10-K` | Quarterly and annual financials |
| `20-F` / `40-F` | Annual reports, foreign and Canadian MJDS filers |
| `SC 13D` + `SCHEDULE 13D` | Activist / >5% stake disclosures. **Both spellings are required** — see below |
| `NT ` | Late filing notices under Rule 12b-25 — `NT 10-K`, `NT 10-Q`, `NT 20-F`, `NT 40-F`. Rare, high signal |

Form 4 is deliberately absent; it has its own channel. Note that earnings news
arrives as an 8-K Item 2.02 press release, typically before the 10-Q, so the
10-Q gets you the statements rather than the announcement.

**`PRESS_RELEASE_EXHIBIT_ONLY`** — when true, an 8-K is only posted if its
**item codes** indicate a press release: `2.02` results, `7.01` Reg FD, `8.01`
other events (`PRESS_RELEASE_ITEMS`). Filters out administrative 8-Ks such as
`5.02` officer changes.

Item codes ship inside the submissions payload, so this costs **no extra
request**. The original implementation downloaded each filing's index page
looking for an EX-99 exhibit — roughly 80 extra requests per run.

That swap narrowed the definition slightly. An 8-K filed under, say, `1.01`
(material agreement) with a press release attached would have been caught by
the old exhibit check and is skipped now. Widen `PRESS_RELEASE_ITEMS` if you
notice gaps.

Applies **only** to the forms in `EXHIBIT_CHECK_FORMS` (`8-K`, `6-K`). 6-K has
no item numbers and is never filtered.

### Critical: the exhibit filter removes the filings you most want

**`ALWAYS_POST_ITEMS`** is checked *before* the exhibit filter and posts seven
item codes whether or not a press release accompanies them.

The filter above is sound for its stated purpose, but it has an inverted failure
mode: **a company restating its financials is the case least likely to announce
it.** Keying on "is there a press release" therefore removes exactly the filings
worth seeing. Measured across all fourteen companies' full histories — **1,986
8-K filings as of 2026-08-03**:

| item | label | appearances | dropped |
|---|---|---|---|
| `4.02` | Non-reliance on prior financials | 10 | **10 — all of them** |
| `4.01` | Auditor change | 32 | 94% |
| `3.01` | Delisting notice / listing rule | 65 | 75% |
| `5.01` | Change in control | 23 | 65% |
| `2.04` | Obligation accelerated | 4 | 50% |
| `2.06` | Material impairment | 2 | 100% |
| `1.03` | Bankruptcy or receivership | **0** | never occurred |

Every 4.02 ever filed by these companies was suppressed. `1.03` has never
occurred, which is the point of watching for it rather than an argument against.

**The case that prompted the change:** NUAI filed `items=4.02` alone on
2026-07-30 — a restatement, no other item code, no press release — five days
before this was written, inside `MAX_AGE_DAYS`. It was dropped.

Cost is small: about **1.3 extra posts a month** for all seven combined,
measured over 2025–26.

#### 5.02 was considered and excluded

Director or officer change is 75% dropped across 300 filings, so it looks like
an obvious inclusion. The concentration says otherwise:

```
MARA 52,  SLNH 52,  BGDE 31,  CLSK 23,  BKKT 23
BKKT filed 5.02 six times between 2025-08-12 and 2025-11-14
```

Six officer-or-director filings from one company in four months is **board
churn, not six CFO departures** — and the item code cannot separate the two. It
would add ~1.9 posts a month on its own, more than twice all seven others
combined, to catch something the insider channel already covers from the
people-acting side.

`1.02` (terminated agreement — more often an expiry than a rupture, and 59%
already post with a release) and `2.01` (one dropped filing in nineteen months)
were also considered and left out.

#### Never add 9.01

It appears on **1,530 of 1,986** filings as an attachment marker and means
nothing alone. Adding it would post essentially every 8-K and silently undo the
exhibit filter.

#### Re-deriving these numbers

`audit_8k_items.py` prints the whole distribution from live EDGAR data,
reading `ALWAYS_POST_ITEMS` and `PRESS_RELEASE_ITEMS` from `press_monitor` at
runtime so it stays honest if the sets change:

```bash
gh workflow run "Audit 8-K items"
```

**The absolute totals drift upward** as filings accumulate — a run the day after
these figures were taken returned 1,991 rather than 1,986. **The ratios are the
argument, not the counts**: 4.02 at 100% dropped, 4.01 at 94%, 3.01 at 75%, and
5.02's concentration in a handful of companies. Those have been stable.

Run it after adding or removing a company, when someone disagrees with the seven,
or before widening the exhibit filter any other way.

#### These render amber

A reader's prior on a main-channel post is "the company announced something".
These are the inverse — material filings the company chose *not* to announce —
so they post in amber rather than the default blue. The `ITEM_LABELS` text in
the title already carries the specifics, so no extra prose is needed. No
collision with the insider channel's amber: different webhook.

**Filing titles** are generated, not taken from SEC. The submissions payload
only supplies a document label, usually just `8-K`, which is redundant beside
the form type already in the embed footer. `ITEM_LABELS` translates item codes
into plain English — an earnings 8-K reads *Results of operations* — and
`FORM_LABELS` does the same for other forms, so a `424B5` reads *Prospectus
supplement — offering* and an `NT 10-Q` shouts *LATE FILING NOTICE*. Item
`9.01` is suppressed unless it is the only one listed, since it appears on
almost every 8-K with an attachment.

### Critical: `SC 13D` and `SCHEDULE 13D` are different form types

The SEC moved Schedule 13D/G to structured XML filings, and the EDGAR
form-type string changed from `SC 13D` to `SCHEDULE 13D`.

Prefix matching does not bridge them. `"SCHEDULE 13D".startswith("SC 13D")` is
**False** — the fourth character is `H`, not a space. A `FORM_TYPES` list
containing only `SC 13D` therefore matched nothing from the changeover onward.

It was found only because a real filing went unposted: Endeavor Blockchain
disclosing 6.5% of Sphere 3D on 2026-07-31, with stated intent to engage with
the board. Nothing in the logs indicated a problem, because **a form type that
matches no filings is indistinguishable from one whose filings never occur.**

Both spellings are now listed; `SC 13D` still matches filings made before the
change.

The general lesson: an entry in `FORM_TYPES` is an assumption until a filing of
that type has actually been posted. The others were confirmed by observing real
posts. This one never had been.

### The drift detector

So it cannot happen silently again. Every run collects the distinct form types
seen across the watchlist and flags any that **resemble** something tracked but
do not match it:

```
WARNING: 1 form type(s) resemble something in FORM_TYPES but do not match it.
  seen 'SCHEDULE 13D'  vs tracked 'SC 13D'
```

The rule needs no advance knowledge of the new spelling. It strips each form to
its alphanumeric core, drops leading `SC` / `SCHEDULE` / `NT` / `FORM`, and
flags an unmatched form whose core contains a tracked stem of three characters
or more. `SCHEDULE 13D` → `SCHEDULE13D` contains `13D`; `SC 13D` → `SC13D`
contains `13D`.

Verified against the actual bug: with `SCHEDULE 13D` removed from
`FORM_TYPES`, the detector flags it and its amendments. It would equally catch
a future `FORM 20-F` or `NOTIFICATION 10-Q`.

It is deliberately conservative. `SCHEDULE 13G`, `SCHEDULE 13F-HR`, `DEF 14A`,
`S-8` and `144` are all seen and none is flagged — they are different filings,
not renamings of something tracked. A detector that fired on every untracked
form would be ignored within a week.

#### What its first run found

Three flags, of which one was a real gap:

| Flagged | Verdict |
|---|---|
| `NT 20-F` vs `20-F` | **Real gap.** `NT 10-K` and `NT 10-Q` were listed individually, so the foreign-issuer late-filing notice was missing — precisely the form IREN or DGXX would file. Fixed by tracking the prefix `NT `, which now covers `NT 40-F` too. |
| `10KSB` vs `10-K` | Obsolete. Small-business annual report, discontinued around 2009. |
| `10QSB` vs `10-Q` | Obsolete, same. |

The two obsolete forms are in `DRIFT_IGNORE`. They sit in old filing histories
and would flag on every run otherwise — and a warning that always fires is one
nobody reads, which is the same failure as not having it.

Note the shape of the real finding: enumerating family members individually
(`NT 10-K`, `NT 10-Q`) left a sibling out. Tracking the family prefix (`NT `)
is both shorter and complete.

`SCHEDULE 13G` — the passive counterpart, filed by index funds and most
institutions — is deliberately **not** listed. A 13D signals intent; a 13G
signals that someone owns a lot and files an amendment each February. If it is
ever wanted, the insider channel is the better home, on the same reasoning that
put Form 4 there.

**`KEYWORDS`** — optional title filter. Empty means post everything.

**`MAX_AGE_DAYS` (7) — the age floor.** A filing older than this is recorded
but **never posted**, whatever `state.json` says.

The dedupe set alone is not enough. It answers *"have I seen this?"*, which
silently becomes *"no"* for thousands of old filings whenever state is reset or
the data source starts returning deeper history. The migration from
`browse-edgar` (40 filings per form) to the submissions API (~1,000 filings of
all types) did exactly that on 2026-08-06: 1,471 historical filings looked new
at once and 65 messages of old news reached the channel.

An age floor is independent of state, so backfill can never be mistaken for
news. Against that same event it would have posted 4 items instead of 40. It
also makes the `state.json` reset in Testing safe.

The trade-off: if the workflow is down for more than a week, genuinely missed
news older than seven days will not post.

**`RETAIN_DAYS` (30) — the dedupe horizon.** Only EDGAR filings from the last
30 days enter the dedupe set at all. Nothing older can post, so remembering it
is pure state-file bloat — the submissions endpoint returns ~1,000 filings per
company, which put 4,275 ids in `state.json` for a watchlist of eleven.

Keep it comfortably above `MAX_AGE_DAYS`; the 23-day gap is the safety margin
for an outage. Not applied to IR feed items, which are ~10 per feed and whose
timestamps are less reliable.

**Insider channel** — Form 4 and 4/A filings go to `WEBHOOK_URL_INSIDER`
instead of the main channel, with their own `MAX_INSIDER_POSTS_PER_RUN` cap and
amber embeds. Form 4 volume across eleven companies would swamp a press release
feed, which is why it's separate rather than another entry in `FORM_TYPES`.

One subtlety: EDGAR's type filter is a prefix match, so querying `4` also
returns `40-F` and `424B*`. Entries are filtered against
`INSIDER_ALLOWED_FORMS` using the form type EDGAR reports per entry, so those
collisions are discarded rather than mis-routed.

**`MAX_POSTS_PER_RUN`** — flood guard, default 40 (insider channel: 25). Sized
for earnings season, when ~10 companies each produce an 8-K, a 10-Q and an IR
item within a short window.

Two different outcomes, easily confused:

- **Beyond the cap** — marked seen, never posted. Deliberate. A backlog must not
  queue up and drip into the channel for hours.
- **Failed to post** — un-marked and retried on the next run. Also deliberate;
  see the rate limiting note below.

### A filter change only ever applies forward

Everything fresh is marked seen **up front**, before any filter runs. That is
what stops a backlog re-flooding the channel, and it is correct. Its cost is
invisible until it surprises someone:

**A filing passed over by a filter is already in `state.json`, so widening that
filter later can never reach it.** It will not reappear as a candidate on the
next run, or any run.

This is not a defect and needs no fix. It is a property worth knowing, because
the natural expectation after relaxing a filter is that the newly-qualifying
filings from the recent past will show up — and they will not, with nothing in
the logs to say why.

The case that established it: NUAI filed a `4.02` restatement on 2026-07-30. A
scheduled run marked it seen, then dropped it at the exhibit filter. When
`ALWAYS_POST_ITEMS` was added five days later — while the filing was still
inside `MAX_AGE_DAYS` — it did not appear, because its uid was already in
`state.json`. Establishing that took a full end-to-end trace; "it did not
appear" was the symptom, not the explanation.

So when a filter widens, expect the effect to start with the *next* qualifying
filing. Recovering an earlier one means editing `state.json`, which is
bot-written and guarded by the pre-commit hook — see
[local workflow](local-workflow.md). Posting it by hand is usually the better
answer.

## Coverage

| Company | CIK | IR feed |
|---|---|---|
| MARA Holdings | 0001507605 | Equisolve |
| CleanSpark | 0000827876 | Q4 Inc |
| Bakkt, Inc. | 0001820302 | gcs-web |
| New Era Energy & Digital | 0002028336 | Q4 Inc |
| IREN Limited | 0001878848 | gcs-web |
| Vulcan Infrastructure and Power | 0001844971 | gcs-web |
| Sphere 3D | 0001591956 | gcs-web |
| Soluna Holdings | 0000064463 | WordPress (`/news/feed/`) |
| Big Digital Energy | 0001218683 | **GlobeNewswire** (the wire, not the newsroom) |
| WhiteFiber | 0002042022 | **investorroom** (separate IR host) |
| Digi Power X | 0001854368 | none — **CMS API**, see below |
| TeraWulf | 0001083301 | Equisolve |
| Hut 8 Corp | 0001964789 | none — **scraped**, see below |
| Cipher Digital | 0001819989 | gcs-web |

The three IR platforms use different feed conventions:

- Equisolve: `/news-events/press-releases/rss`
- Q4 Inc: `/rss/pressrelease.aspx`
- Notified / gcs-web: `/rss/news-releases.xml`

Note that IR platforms migrate. Bakkt moved from Q4 to gcs-web, which broke
its feed URL with a 404. If a previously working feed starts failing, check
whether the site changed platforms before assuming the feed was removed.

Soluna is plain WordPress. Its press releases live in the `/news/` archive
(feed at `/news/feed/`), while the site-root `/feed/` is a near-dormant blog
feed. Autodiscovery finds the latter, because the archive's own feed isn't
declared in the page HTML — so the correct URL had to be set explicitly.

SpaceX is Q4 as well, despite a newsroom URL of `updates/default.aspx` that
reads like a fourth platform. `default.aspx` is Q4's page naming.

Bitdeer is the counter-case to the conventions above. Its newsroom is
`/news-events/news-releases`, one word away from the Equisolve shape, and
`/news-events/news-releases/rss` **returns nothing** — the feed is the gcs-web
one at the host root. **The newsroom path does not identify the platform.**

Applied Digital's platform returns **byte-identical responses for `/rss`,
`/rss/news-releases.xml` and `/rss/pressrelease.aspx`** — 7,741 bytes each. It
serves the feed for anything under `/rss`, so on that platform a constructed
URL that works today is not evidence the platform means it. Record the
autodiscovered URL, not the one you guessed correctly.

### Two rules for adding a feed

Both come from failures, and both are cheap.

**Never rank feed candidates by newest item.** Discovery on `ir.bitdeer.com`
returned two feeds, and picking the freshest chose `/rss/events.xml` over
`/rss/news-releases.xml` — because an events calendar carries **future-dated**
entries, in that case an earnings call two days out.

That is not a near miss that happened to go wrong. **An events feed will look
newer than a press-release feed permanently, by construction**, so the metric
is not noisy — it is inverted, and it fails hardest on exactly the companies
that publish most regularly. The wrong URL would have entered the roster with
a date beside it that looked like evidence. If feed selection is ever
automated, the tiebreak must be what the feed *is*, never how fresh it looks.

**Check a candidate feed against the newsroom page it claims to mirror, not
against today's date.** One extra fetch, and it is the difference between the
two DGXX dead feeds being caught and being adopted. A feed abandoned when a
company changes wire keeps serving its last items at HTTP 200 forever, so
"newest item is 30 days old" reads as healthy for the first ninety days;
"newest item is 30 days old and the newsroom published yesterday" reads as
dead immediately.

Of the three feeds added on 2026-08-08, APLD and BTDR matched their pages to
the day. **SPCX could not be checked** — its newsroom ships zero dates in the
delivered HTML — so it went in with that recorded in `watchlist.py` rather
than rounded up to the same confidence as the other two.

### Four ways a company is covered

Eighteen of nineteen are now read from something faster than EDGAR. Five
publish no feed on their own newsroom, and each turned out to be a different
problem, so there are four mechanisms rather than one:

| Mechanism | Companies | Source |
|---|---|---|
| **Own IR feed** | thirteen | the company's own newsroom RSS |
| **Newswire feed** | BGDE | GlobeNewswire's organization feed |
| **Separate IR host** | WYFI | `whitefiber.investorroom.com` |
| **Scrape** | HUT, GLXY | server-side HTML, `scrape_hut8()`, `scrape_galaxy()` |
| **CMS API** | DGXX, ABTC | public Strapi / Sanity, `read_dgxx()`, `read_abtc()` |

**All nineteen are now covered.** ABTC was the last holdout and was recorded as
EDGAR-only for three days on a true observation with a wrong conclusion: its
list is a client-rendered infinite scroll with no date-adjacent-to-title
structure, so the cheap scrape does not apply. **That is a fact about the page,
not about the source.** The list is backed by a public Sanity dataset — see
`read_abtc()` — which is the DGXX shape and strictly better than a scrape.

The two routes that did not work are worth recording, because both look
plausible and one nearly got built:

- **Slugs.** They carry the headline text, so a title is recoverable. A date is
  not: 28 release slugs against **3 distinct dates** in the delivered markup.
  Pairing those by proximity is guesswork rather than a hard parse.
- **Sitemap `lastmod`.** 28 release pages with 24 distinct values, so not the
  single-rebuild-stamp trap that makes `digipowerx.com/sitemap.xml` useless.
  But against ABTC's own 8-K dates the median gap is 4 days and the worst is
  21. **That cross-check is inconclusive rather than damning** — ABTC has 167
  8-Ks, so "nearest 8-K" is too dense a baseline to be discriminating, and the
  worst rows are earnings-*scheduling* announcements that plausibly have no
  8-K at all. It is moot either way: Sanity supplies a real publication date.

**The lesson took four attempts to learn: a newsroom with no readable HTML does
not mean there is no feed.** Three of those four had a machine-readable source
somewhere other than the company's own domain — a newswire, an IR platform, a
CMS backend — and checking the company domain alone is what kept concluding
otherwise. BGDE and WYFI were both written off twice before anyone followed a
reference off-domain.

**It has now happened three times — BGDE, WYFI, GLXY — and the sharper form of
the rule is not "check other hosts". It is that THE REFERENCE IS USUALLY
ALREADY IN FRONT OF YOU.**

Galaxy is the case that makes it concrete. `www.galaxy.com` was swept
thoroughly and written off as having no feed, and a scraper was built. The
release that motivated re-opening it — the ERCOT 830 MW Helios approval — was
sitting on the page the whole time with
`href="https://investor.galaxy.com/news-releases/..."`. The IR host was in the
markup being parsed. `investor.galaxy.com/rss/news-releases.xml` is a standard
gcs-web feed and had been there all along.

So the check is cheap and specific: **enumerate the distinct hosts the newsroom
links out to, and probe each one.** A company that publishes through an IR
platform links to it from somewhere, because that is what the platform is for.

**And autodiscovery is necessary, not sufficient — the rule above overstates
it.** It says autodiscovery first because that is what found WYFI, which is
true and is why it stays first. But on `investor.galaxy.com` autodiscovery
finds **nothing at all** — no `<link rel="alternate">`, no RSS anchor anywhere
on the page — and only probing the known platform host-paths found the feed.

That matters because a method that worked once, stated as *the* method, is what
stops the next person looking further. **Autodiscovery finding nothing is not
evidence there is no feed. Run the host-path list too, and only then conclude
absence.**

#### WhiteFiber — found by autodiscovery out of a shell

The Webflow page carries no headlines, but it references an IR platform host,
and that host declares a feed in a `<link rel="alternate">`. Nothing on
`whitefiber.com` says a feed exists.

#### Digi Power X — read from the CMS behind the newsroom

DGXX is the only company with no feed anywhere: not on its own domain, and not
on either wire it has used. It moved from GlobeNewswire to ACCESS Newswire
around January 2026, and ACCESS's only advertised feed is a marketing blog of
144 posts about writing earnings-call scripts.

Its newsroom is a Next.js shell backed by a **public Strapi CMS**, which
`read_dgxx()` reads directly — 197 releases reaching back to 2020. A JSON
contract is more stable than scraped markup, but this one sits on weaker
ground than any other source here, and the code says so.

**Two query parameters are load-bearing.** Neither announces itself if dropped:

| Parameter | If omitted |
|---|---|
| `sort=date:desc` | The default order is **not** by date — unsorted page 1 returns a 2025 item first. Taking the first row as newest would be wrong and would look right. |
| `populate=*` | `pdf_file` is absent from the default field set, so every item parses fine and has nothing to link to. |

**Items link to a PDF**, and the post label says so — `DGXX · IR newsroom
(PDF)` — because every other item in the channel opens a web page and a reader
should know before clicking.

That is not a preference. There is no `slug` field (Strapi answers
`400 Invalid key slug`), and reconstructing the web URL as
`slugify(title) + "-" + documentId` resolves only **6 of 8** recent releases —
the failures being titles containing double spaces. Worse,
`digipowerx.com` **soft-404s**: a wrong release URL returns HTTP 200 with the
wrong content, so a bad link would be indistinguishable from a good one in
every log line. The PDF URL is *present in the payload* rather than
reconstructed, covers 8 of 8, and can be checked per item.

**Three distinct failures, three distinct log lines.** DGXX's median gap between
releases is 8 days, so a silent failure would sit a long time before anyone
wondered:

```
  DGXX: FETCH FAILED (ConnectionError) — the CMS host did not respond...
  DGXX: EMPTY RESPONSE — HTTP 200 with 0 items...
  DGXX: STALE — 25 items parsed but the newest is 141d old (limit 90d)...
```

The staleness limit is **90 days**, chosen from DGXX's own history rather than
intuition: across the last 24 months it published 75 releases with a median gap
of 8 days, a 90th-percentile gap of 20, and a longest gap of **34**. Ninety days
is about 2.6x that worst observed case — deliberately generous, because a
warning that cries wolf gets ignored, which is the same reasoning that put the
obsolete forms in `DRIFT_IGNORE`.

**The hostname is the weak point.** `thankful-miracle-1ed8bdfdaf.strapiapp.com`
is a Strapi Cloud default, not a contract on the company's own domain. A
redeploy would move it and nothing would announce that — the same silent shape
as a wire migration. That is what the FETCH FAILED line exists to name.

### Critical: the staleness check

The loud failures were always handled — a fetch error, a non-200 and a parse
error each log distinctly. **The quiet one was not**: a source returning HTTP
200 with valid content, correct timestamps, and nothing new for months.

Two sources failed exactly that way in a single day, both below. A company
changing IR platform, changing newswire, or having a feed quietly retired all
produce the same shape, and none of it shows up in a log.

**No fixed horizon works**, because cadences differ by an order of magnitude
across the roster — measured, with same-day items collapsed:

```
NUAI  5d   IREN  6d   WYFI  6d   SLNH  7d   MARA  8d   DGXX  8d   WULF  9d
BKKT 13d   BGDE 13d   CIFR 14d   VIP  15d   ANY  15d   CLSK 15d   HUT  18d
```

So every source is judged against **its own median gap** — the principle the
rest of the repo uses for every metric. One check covers the feeds, the scraper
and the CMS reader alike:

```
fire when age > max(6 x median_gap, 60 days, explicit override)
```

**The multiple and the floor do different jobs.** The multiple makes slow feeds
wait longer than 60 days — CLSK, VIP and ANY fire at 90d, HUT at 111d — because
a flat floor would fire on them during an ordinary lull. The floor stops fast
feeds firing during a normal quiet spell: at 6x alone NUAI would fire after
**30 days**, which is an unremarkable month for a company that usually publishes
weekly.

**Calibration.** 6x is the tightest multiple with no false positives across all
fourteen live sources. The worst healthy source sits at 5.0x; the dead control
at 31.8x.

| multiple | false positives | catches the control |
|---|---|---|
| x4, x5 | NUAI | yes |
| **x6** | **none** | **yes** |
| x8 and above | none | yes |

**These numbers are reproducible, not folklore.** `calibrate_staleness.py`
measures every source's cadence and prints the table above from live data.
Re-run it after adding or removing a source, when a source is found to have died
quietly, or when a STALE warning turns out to be a false positive:

```bash
gh workflow run "Calibrate staleness"
```

It is read-only, dispatch-only and needs no secrets. It carries the dead
GlobeNewswire feed as a permanent control in `KNOWN_DEAD` — a detector that
stops firing on that is broken, and one control is thin, so a second dead source
is worth adding there rather than only noting.

**Same-day items are collapsed before measuring**, and this is load-bearing
rather than tidiness. Uncollapsed, HUT's median reads 5.5d instead of 18d and
MARA's 4.4d instead of 8d — a single burst would drag the median down until an
ordinary quiet spell looked like a failure.

**Thin samples get their own state.** Below four distinct publication days the
check reports `insufficient history to judge staleness` rather than passing
silently. A median from two gaps is not evidence.

**DGXX carries an explicit 90-day override.** The shared check would compute 60d
from the 25 items it fetches; the override comes from the full 197-item history
— 75 releases over 24 months, longest observed gap 34 days. Better evidence than
the window, so the check takes the larger of the two.

It logs and returns. It never raises and never suppresses items: a stale source
may simply be quiet, its items still deduplicate normally, and one source going
dark must not affect the other thirteen or the EDGAR sweep.

`probe_body_dates.py` is the second maintenance tool, dispatched by hand
through **Probe body dates**. It collects the same IR sources, selects every
announcement whose title carried no parsable date, fetches each body and
prints the candidate dates it found, grouped by whether the title named a
forthcoming event. It exists because the same measurement inside the monitor
was gated on items new in a run and fetched nothing for as long as it lived
there: the twenty undated announcements had all been seen already. Read-only,
no secrets, no state, no commit.

**What the first run measured, 2026-08-12.** 221 items collected, **20 undated
announcements selected — the same 20 the monitor logs**, so the two populations
agree. Zero failed fetches.

| label | one | several | none |
|---|---|---|---|
| advance notice | 1 | 5 | 0 |
| scheduled + results | 2 | 4 | 0 |
| not scheduled | 4 | 4 | 0 |

Read alone that says a rule is not possible: advance notices sit in *several*,
not *one*. **The counts were the thing that misled.** Every scheduled body opens
with its own dateline, and `candidate_dates` dropped a date only when
`when < released`, so the release date itself survived as candidate one.

The filter now excludes it, and the second run of the same twenty rows measured:

| label | one | several | none |
|---|---|---|---|
| advance notice | **5** | **0** | 1 |
| scheduled + results | 2 | 2 | 2 |
| not scheduled | 3 | 1 | 4 |

**So the scheduled-event gate does discriminate.** Five of six advance notices
offer exactly one forward date and none offers several, while the other two
populations scatter across all three buckets. One date that every press release
carries had hidden that completely.

The sixth advance notice is HUT's, and it is the one to check before a rule is
written: its extracted body is 1,227 characters against ABTC's ~2,650, which
looks like a short extraction rather than a release that names no date.

Both tables above are probe runs. The first reading of the second table was
arithmetic done by hand on the printed rows, and it agreed with the measurement
exactly — which is not evidence it was sound, only that it was lucky. It was
re-measured before it decided anything, per the `CLAUDE.md` trap about numbers
true of something adjacent to the question.

### Two dead sources that parse perfectly — both DGXX

Recorded because each looked like a solution, and one check caught both.

**The old GlobeNewswire organization feed.** Alive, valid XML, 20 items, every
one with a resolvable uid and a parseable timestamp. Nothing newer than
**2025-12-24**.

**`digipowerx.com/sitemap.xml`.** Lists **100 individual release URLs** — which
is exactly the per-company index ACCESS Newswire fails to provide, served as
plain dated XML. But every `lastmod` is the identical value
`2026-06-13T18:43:20`, a site-rebuild stamp rather than a per-release date; none
of five probed releases from 2025-12 onward appears; and 70 of the 100 slugs
predate the March 2025 rename from Digihost.

**Check the newest entry date before anything else.** It is the single check
that caught both, and neither would have announced itself any other way. A
source returning 200 with well-formed, correctly-timestamped, entirely obsolete
content is the hardest failure in this component to see.

**Hut 8 renders server-side and is scraped** — see below.

**Big Digital Energy is read from the newswire instead of the newsroom.** Its
own page is a QuoteMedia widget and unreadable, but it distributes through
GlobeNewswire, which publishes a per-organization feed. That is better than
scraping the mirror would have been: the wire publishes first and the newsroom
mirrors it, so the feed is the earlier source as well as a structured contract
rather than markup that can move.

### Reading a newswire feed instead of a newsroom

BGDE is the only entry of this kind, and it does not behave like the other ten.

- **The token is opaque.** `/rssfeed/organization/z9WJvxXYqqA-t7lWEcsvqw==` is
  not derivable from the company name. It has to be read off an individual
  release page, where GlobeNewswire embeds a "Subscribe via RSS" control.
  Organization pages carry no feed link and no autodiscovery, and `/RssFeed` is
  the global firehose of every publisher — mostly law-firm and paid promotional
  items, and useless here.
- **One token spanned the rename.** The same organization holds the Mawson
  Infrastructure releases and the Big Digital Energy ones.
- **It was checked for third-party content.** All 20 items are BGDE's own
  releases, so nothing needs filtering. A wire feed carrying paid or syndicated
  items would have changed the calculation.

**Check the newest item date before trusting any wire feed, and check which
wire the company uses now.** DGXX is the case that proves both. Its
GlobeNewswire feed is alive, parses cleanly and returns 20 items, none newer
than **2025-12-24** — the company moved to ACCESS Newswire around January 2026.
Adding that feed would have produced one that looks healthy in every log line
and reports nothing new forever: the same failure class as the `SC 13D` prefix,
and harder to spot, because the feed itself is not broken.

**A company can change wire the way it changes IR platform — but this failure is
silent where the platform one is loud.** Bakkt's move from Q4 to gcs-web broke
its feed URL with a 404, which announced itself. A wire migration leaves the old
organization feed serving its old items indefinitely: HTTP 200, valid XML, a
resolvable uid and a parseable timestamp on every entry. Nothing in a log
distinguishes it from a company that has simply stopped issuing releases.

Wire items are **not** deduplicated against the matching EDGAR filing, and that
is deliberate. A wire release and its 8-K are two different things about the
same event; the wire arrives hours earlier, and collapsing them would discard
the latency that makes the feed worth having.

### Galaxy is scraped too, and the page mixes four kinds of card

`galaxy.com/newsroom` has no feed — autodiscovery, footer anchors, every
platform path on this roster and the host roots were all tried on 2026-08-08 —
and its releases render server-side. So it is the HUT case, and
`scrape_galaxy()` is the HUT treatment.

Two things about the page shape the code:

**The card structure defeats regex pairing in both directions.** A ~1,500
character `<picture>` block of `srcset` variants sits between each card's
anchor and its text, so a date-to-title window small enough to be safe finds
nothing and one large enough reaches into the next card. The scraper walks
**forward from each anchor to the next anchor** and reads the block between.

**Document order is not date order, and here that is observed rather than
guarded against in the abstract.** In the 2026-08-08 fetch a `January 15, 2026`
card sat at byte 93,171 and an `August 07, 2026` card at 99,430 — the older one
first, because a media block precedes the release list. `rows[0]` was a newest
item that day by luck.

**Only `/newsroom/<slug>` is collected**, out of four kinds of card:

| | kept |
|---|---|
| `/newsroom/<slug>` | **yes** — the releases |
| `/newsroom/videos/<slug>` | no — excluded by the slug pattern, not a list |
| `/insights/research/<slug>` | no — weekly research briefs, editorial |
| external wire URLs | no — a `newsroom-media` block linking out to prnewswire |

**The last one is a real judgement call rather than an obvious exclusion.**
That block holds at least one item this repo actively wants — *"Galaxy
Completes ERCOT Interconnection Studies … 830 Megawatts at Helios"* — so
excluding it is not free. It is excluded because the cards are a
media-coverage list, `data-newsroom-media-type="Article"`, mixing Galaxy's own
wire-hosted releases with third-party write-ups about Galaxy, and **nothing in
the markup separates the two**. Posting another outlet's article as a company
release is the worse failure, and material items reach EDGAR as 8-Ks anyway.

So the run logs the skipped count — `7 items (scraped), 10 non-release cards
skipped` — rather than leaving it implicit. A reader seeing seven items and no
count would reasonably conclude the page holds seven.

### Hut 8 is scraped

`hut8.com` publishes no feed either — none linked from the press releases page,
no RSS entry under investor resources — but its releases render **server-side**
and come back complete in a plain fetch. `scrape_hut8()` reads
`/news-insights/press-releases` and yields items in exactly the shape
`collect_ir()` produces, so they rejoin the same dedupe and posting path and
nothing downstream knows the difference.

This closes a **latency gap, not a blind spot**. Everything material reaches
EDGAR as an 8-K eventually; the scraper gets it hours earlier.

Three properties of that page shape the code, and each would be a bug if
assumed away:

| Property | Consequence |
|---|---|
| Two overlapping lists — "Featured" and "All" — with the same release in both | Deduplicate by URL. 11 anchors currently yield 9 unique items. |
| Document order is not date order; the featured block mixes recent with old | Parse `Jul 20, 2026` and sort. Never trust position. |
| Hrefs are **relative** despite looking absolute in a browser | `urljoin` before using the URL as a dedupe key. |

Both blocks label their parts `class="date"` and `class="title"`, but the
featured block wraps them in `<p>` and the "All" block in `<div>`, so the tag is
deliberately not matched. Extracting by structure also avoids splitting the
concatenated link text, which carries a `press release` category label in one
block and not the other.

The "All" list is truncated behind a "Show All" control and only five of its
items are in the delivered HTML. **That truncation is not worked around.** If
"Show All" loads more via JavaScript it is the client-side case this scraper
exists to avoid, and nine items against a fifteen-minute schedule is already
comparable to the ten an RSS feed returns.

### A probe that finds nothing looks exactly like a source that has nothing

The scraper rule below — HTTP 200 with zero items is a parse failure, not a
quiet week — applies to the tools used to investigate a source, and that is
not obvious until it costs something. Twice in the 2026-08-08 sweep:

| reported | actually | would have cost |
|---|---|---|
| `/all-news/announcements`: **278 cards, 0 dated** | 276 cards, **all dated** — the extractor's window fell outside the archive layout | ruling out a usable source |
| ABTC's page: **0 bundles, 0 chars of JS** | 8 bundles, 637,688 chars — a regex matching `src=` where the assets use `href=` | ruling out the Sanity backend, the only route that worked |

**Both read as findings about the source and were failures of the tool**, and
both pointed the same way — toward *there is nothing here*, which is the
conclusion that ends an investigation rather than continuing it.

So a probe reporting zero needs the same treatment a component does: a floor
it should clear, checked against a second signal. In both cases above the
second signal already existed and went unread — the page obviously renders
dates in a browser, and a React app obviously ships JavaScript.

### Critical: a scraper fails differently from a feed

A feed that breaks usually errors. A scraper whose selectors stop matching
returns zero items and looks exactly like a quiet week — and HUT publishes only
two to four releases a month, so a silent failure could sit for a long time.

What separates the two states here is that **the page lists roughly nine
historical releases and never empties**. A genuinely quiet month still returns
nine. So zero items from an HTTP 200 cannot mean "no news"; it can only mean the
markup moved. The log says so in those words rather than reporting `0 items`,
because the two states need different responses from a reader:

```
  HUT: 9 items (scraped)
  HUT: HTTP 503
  HUT: PARSE FAILURE — HTTP 200 but 0 items. This page lists ~9 historical
       releases and never empties, so this is the markup moving, not a quiet week.
```

It never raises. One scraper must not take down thirteen feeds and the EDGAR
sweep with it, which is the isolation the whole repo is built on.

## Scaling

**Requests per run: 28** — one submissions call per company (14), one per IR
feed (12), one for the Hut 8 scrape and one for the Digi Power X CMS. Both channels are served from the same
payload, so the insider check costs nothing extra.

This replaced the legacy `cgi-bin/browse-edgar` endpoint, which needed one call
per company *per form type* plus an index fetch per candidate filing — about
**201 requests**. That endpoint is slow and times out under load: on 2026-07-30
a run reached only 4 of 11 companies before hitting the step timeout. Worst
case with every request stalling fell from roughly 600 minutes to 10.

**Item IDs per run: 128** — 48 EDGAR filings within `RETAIN_DAYS` plus 80 IR
feed entries. `state.json` settles around 56KB.

Retention is `max(1000, items × 3)`. The multiplier is the real protection: the
retained list must stay longer than one run's visibility or items age out,
reappear as unseen, and get re-posted. The constant is only a sane minimum, and
it was lowered from 4,000 once `RETAIN_DAYS` cut a run's visibility to ~130 —
at the old value the file would have been pinned at ~250KB of dead history.

That figure has moved twice and the history is instructive:

| | IDs per run | state.json |
|---|---|---|
| browse-edgar, 40 per form | 1,631 | ~100KB |
| submissions, unfiltered | 4,275 | ~265KB |
| submissions + `RETAIN_DAYS` | 128 | ~56KB |

The middle row is what caused the 2026-08-06 flood. The bloat was a symptom of
the same mistake: remembering filings that could never be posted anyway.

| Limit | Binds at | Failure mode |
|---|---|---|
| `state.json` retention | not binding at current scale | Was ~60 companies before `RETAIN_DAYS`. Items ageing out of state now cannot post anyway, so the failure mode is gone. |
| 15-min step timeout | not binding at current scale | Run killed mid-way; state never saved. This was the binding limit under the old endpoint. |
| `MAX_POSTS_PER_RUN` | any size | Overflow beyond the cap is marked seen and **discarded**, not queued. Posts that *fail* are retried. |
| SEC rate limit | not binding | Requests are sequential with a 0.15s gap, well under 10/sec. |

The retained ID list must stay longer than the number of items one run can see,
or the dedupe breaks. `save_state` therefore scales its cap with observed run
volume (`max(4000, items × 3)`) rather than using a fixed number. The cost is
file size — roughly 240KB at 11 companies, 540KB at 25, over 1MB at 50 —
committed up to 48 times a day.

To go beyond ~60 companies, in order of effect:

1. **Raise `MAX_POSTS_PER_RUN`** so a busy morning can't silently overflow it.
   This is the first thing that binds now.
2. **Lower `RETAIN_DAYS`** toward `MAX_AGE_DAYS` to shrink state further,
   at the cost of outage margin.
3. **Trim `FORM_TYPES`.** No longer a multiplier on *requests* — one call
   returns everything regardless — and with `RETAIN_DAYS` in place it barely
   moves state size either. Mostly a noise-reduction lever now.

Past that, the right redesign is storing a per-company high-water timestamp
instead of a list of every ID seen. That stays constant-size regardless of
watchlist length. Not worth the complexity below ~60 companies.

## Testing

**Dry run.** Actions → Press release monitor → Run workflow. The checkbox is
ticked by default: it fetches, evaluates, and prints exactly what *would* post,
but posts nothing.

Critically it also does **not save state**. Saving would mark everything seen
and the next real run would post nothing at all — a quieter failure than a
flood. Scheduled runs pass no input, so they always post normally.

```
2 candidate(s) checked, 2 to post.
  [press]   MARA Holdings (MARA) · SEC 8-K — Results of operations
  [press]   MARA Holdings (MARA) · SEC 10-Q — Quarterly report
  [insider] MARA Holdings (MARA) · Form 4 — FORM 4

Dry run: would post 2 press and 1 insider item(s). State not saved.
```

**Forcing a live post.** Replace `state.json` with
`{"seen": [], "initialized": true}`, commit, and run with the checkbox
unticked. The age floor means only filings from the last 7 days can post, so
this no longer risks a backlog flood.

The very first run on a fresh state file posts nothing by design — it records a
baseline.

## Known quirks

- **Scheduled workflows are disabled after 60 days of repo inactivity.** GitHub
  emails first. The `state.json` commits normally keep this from triggering.
- **Cron drift.** Scheduled jobs are queued at low priority; `*/15` is
  realistically 15–25 minutes and can be skipped under peak load.
- **IR feeds behind WAFs.** Some IR platforms stall non-browser User-Agents
  instead of returning an error, which surfaces as `ReadTimeout`. The script
  sends browser-like headers to the IR hosts for this reason. SEC still gets
  the real contact string from `SEC_USER_AGENT`.
- **Public repo.** Workflow logs are publicly readable. Secrets are encrypted
  and masked as `***`, but the watchlist and feed URLs are visible.
- **`state.json` grows with the watchlist.** Retention scales with run volume
  by design — see Scaling. Don't replace it with a fixed cap.
- **Discord rate limits are handled, and must stay handled.** Items are marked
  seen before posting, so a dropped post would be lost permanently. `post()`
  honours Discord's `retry_after` (capped at 30s, one retry), and anything
  still failing is removed from `state["seen"]` so the next run retries it.
  Rate limiting is most likely during earnings season — exactly when the items
  matter most. Do not simplify this into a fire-and-forget POST.
- **Don't add a `pull_request` trigger.** Only `schedule` and
  `workflow_dispatch` are safe here.

## Reading the log

```
  VIP: pinned to CIK 0001844971 (Vulcan Infrastructure and Power)
Checking EDGAR for 11 companies...
  MARA: 1001 filing(s), 959 older than 30d -> 25 tracked, 17 insider
Checking 8 IR feeds...
  MARA: 10 items
Insider channel: 98 Form 4 filing(s).
332 items seen, 2 new, 1 new insider.
2 candidate(s) checked, 2 to post.
Posted 2 press item(s).
Posted 1 insider item(s).
State: 334 ids retained (cap 4000).
```

Each company and feed name prints *before* it is attempted, so if a run stalls,
the last line names the culprit. The per-company line reads
`total filings, dropped by age -> forms we track, Form 4 count`.

A normal run reports `0 new` and posts nothing. That is success.

Lines worth reacting to:

| Line | Meaning |
|---|---|
| `WEBHOOK_URL_INSIDER not set — skipping insider channel` | Either intentional, or the secret isn't mapped into the workflow's `env:` block. An unmapped secret reads as empty, which is indistinguishable from disabled. |
| `HTTP 404` on one feed | Usually an IR site replatforming, not a removed feed. Check the platform before giving up. |
| `ReadTimeout` | A WAF stalling the request. Check the browser headers are still being sent. |
| `NO FEED` | Autodiscovery found nothing on that URL. |
| `Not found on EDGAR` | Only possible for `TICKERS` entries; pin the company by CIK in `EXTRA_CIKS` instead. |
| `rate limited, waiting Ns` | Discord 429. Normal during heavy bursts; the item is retried automatically. |
| `N item(s) failed to post; will retry next run` | Those items were removed from state and will be re-attempted in 15 minutes. Not a loss. |

## Filings from before a company was added

The age floor is irreversible by design. Items are added to `seen` **before**
`MAX_AGE_DAYS` is applied, so a filing already older than seven days when a run
reads it is recorded and never posted. That is what stops a backlog re-flooding
the channel, and it is the right trade.

**This was reframed on 2026-08-09 and is no longer a loss.** It was recorded
here as filings *lost* to a roster change, and the question asked of it was how
to recover them. That was the wrong question. **Adding a ticker should produce
no backdated posts at all** — filings and press releases arrive as they happen
and never retroactively — so the twenty items were never lost, they were the
intended behaviour arriving by accident.

What was actually broken was that the age floor did the job **incompletely**.
`MAX_AGE_DAYS` is seven days rather than *since this company was added*, so an
item published inside that window but before the roster commit was unseen,
eligible, and posted. Rebuilt from EDGAR at the exact moment of the
2026-08-05 addition:

| | |
|---|---|
| items the five companies had in the `RETAIN_DAYS` window | **30** |
| silently recorded by the age floor, never posted | 13 |
| **posted, every one of them backdated** | **17** |

Nine of the seventeen were Form 4s, so the insider channel had the same
problem. `baseline_companies()` now suppresses all thirty, and the same
reconstruction confirms it: 0 posted, 30 recorded.

### How a first run is recognised

The record is a `baselined` dict in `state.json`, written once per company.
**Two other shapes were considered and one of them is a trap.**

*The company has no ids in `seen`* is the obvious test and it cannot be used.
`seen` is capped at `max(1000, items_this_run * 3)` and is **saturated at
exactly 1000**, so ids are actively evicted; and a uid is a bare accession
number carrying no company, so the question cannot be asked of the file at all
— only of an intersection with the current run, which an eviction silently
empties. **A company whose ids had aged out would look brand new and its real
backlog would be suppressed without a word** — the exact failure the rule
exists to prevent, arriving through the mechanism meant to prevent it.

*A separate file* is immune to that but needs a merge driver, a place in the
commit flow and a hand-written date for every company already running.
`state.json` has all three already, and `baselined` sits beside `initialized`
because it is the same kind of fact.

It **self-backfills**: if the key is absent, every company on the roster is
established by definition, so all are recorded and nothing is suppressed. And
if `state.json` is lost entirely, `initialized` is false too, so the
whole-file first-run path fires first — the behaviour degrades to exactly
what it is today rather than into something new.

### What `MAX_AGE_DAYS` still does

Its job changed and its value did not. It is no longer what stands between a
roster addition and a wall of backdated posts — `baseline_companies()` does
that completely.

What remains is narrower and is **not** the outage case: **a source that
changes what it serves.** `read_dgxx()` asks for 25 of the 197 releases its
CMS holds, and a default that moved would make the other 172 unseen, old and
eligible at once. Feeds do it too — BGDE's serves 20 where most serve 10.

The cost is worth stating rather than leaving implicit: an outage longer than
seven days would drop everything older than the window, silently. That has
never happened — it needs seven days of silence against a measured maximum gap
of about five hours — and an absent run is visible in the run history in a way
a suppressed post is not. Kept on that trade.

### `audit_pending.py` was deleted with this change

It existed to report items lost to the age floor on a roster addition, which
is now exactly what the monitor suppresses on purpose. A tool reporting
intended behaviour trains the reader to ignore it.

Its residual case — an outage long enough to lose filings — is real but it was
triggered by a push touching `watchlist.py`, which is the roster-addition
moment and the wrong trigger for an outage entirely. Building that would be a
different tool for a case with no demonstrated instance.

**The two things worth keeping from it are below**, and they are the reason it
is summarised here rather than only deleted: the audit of which components
share the failure mode, and the eviction measurement, which is now the
argument for how `baselined` is stored rather than an argument about `seen`.

### Which components share this failure mode

Audited on 2026-08-05, all fourteen. **This is the table worth keeping**: the
conclusion follows from it, and without it the next person to consider a loss
check re-derives the whole thing. The signature is *irreversibly marks an item
handled, then filters it out*, and severity is governed by the ratio of the
window to the cadence.

| Component | Window | At risk | Why |
|---|---|---|---|
| `press_monitor.py` | `MAX_AGE_DAYS` 7d | **yes** | Shortest window against its cadence, discrete events, and the only one that marks-then-drops inside a single run |
| `comment_letters.py` | `LOOKBACK_DAYS` 180d | no | Twenty-five times the margin; a missed run only delays |
| `threshold_list.py` | per-day file | lesser | An add or remove episode inside a gap is invisible, but the daily files persist and can be back-read |
| `crossings.py` | armed flags | lesser | A crossing on a day it does not run is never detected; the bars remain available and it does not look back |
| `short_interest.py` | `last_settlement` | no | Posts `max(by_date)` only, so an older period is skipped by design |
| `regsho_volume.py` | `last_trade_date` | no | Same shape; a skipped day is a stale snapshot, not a lost event |
| `dilution.py` | last share count | no | A missed run delays; the XBRL history persists |
| `ftd_monitor.py` | `BASELINE_PERIODS` | no | Absence is stored as a literal zero rather than skipped |
| `daily_recap.py`, `btc_context.py`, `grid_context.py`, `volume_spike.py`, `build_snapshot.py` | none | no | Snapshots recomputed from source every run |
| `earnings_calendar.py` | none | no | Projections recomputed from source every run; the one persisted input, `earnings_dates.json`, is written and protected by `press_monitor.py`, not by this component — see the disclosed-dates note above |

**One at risk, two lesser and recoverable from source data, eleven not.** The
conclusion drawn from it at the time — that a population of one does not want
a framework — held, and the eventual fix was smaller still: a rule inside the
one component rather than a tool watching it.

### Why `seen` cannot produce a false positive here

`state.json` retains the last `max(1000, items_this_run * 3)` ids and is
currently **saturated at exactly 1000**, so ids are being evicted. An item
posted weeks ago but since evicted would read as unseen, which for a company
already on the roster would be a false report.

It cannot be one for a company just added, because `press_monitor.py` has never
queried that CIK, so nothing under it can ever have entered `seen`. **The
trigger removes the dependency rather than managing it.**

Measured 2026-08-05 for the record: 253 of the 1000 slots sit before the
earliest 2026 accession, so the eviction frontier is deep in 2007 to 2025
baseline entries. That buffer erodes, which is exactly why correctness does not
rest on it.
