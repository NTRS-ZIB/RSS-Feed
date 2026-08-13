[← Watchlist monitor](../README.md)

# Weekly digest

`weekly_digest.py` answers two questions about a week, and the second is the
one worth the build:

- **what happened** — the summary
- **what did I miss** — the filter

Things visible only across a week and invisible in any single post. Two shapes:
**convergence**, a company appearing in several independent measures at once,
and **persistence**, a measure holding for days rather than spiking once.
Neither is derivable from a single day.

**Nothing renders yet.** This file documents the derivation layer and the
verdict record, and the backfill measurement that set the one threshold in it.
There is no Discord post and no markdown artefact; `digest.yml` is
dispatch-only and writes nothing to the repo.

## It re-derives from source

It does not aggregate the week's posts. Measured over the run history
2026-07-29 to 2026-08-05: the daily workflows delivered **3–4 of their 5–6
nominal scheduled fires** each, the press monitor 42 of ~102, volume spikes 29
of ~80. [`docs/rejected.md`](rejected.md) records the same thing as a rate —
GitHub drops **30–45%** of scheduled fires on this repo. A digest built from
posts would inherit every gap and report a quiet monitor as a quiet week.

Two further reasons, either sufficient alone:

- **The change-only components post nothing in the interesting case.** The
  threshold list, crossings, dilution and comment letters post only on a
  change. ANY sat on the Reg SHO threshold list for five consecutive weeks and
  that produced at most two posts — added, and removed.
- Re-deriving decouples the digest from every component's output format.

## Three layers

```
derive  ->  the verdict record  ->  a Discord post      (not built)
                                ->  a markdown file     (not built)
```

The verdict record is not architecture for its own sake. To say *"SLNH, fourth
week running"* the digest must know what it concluded last week, and a digest
whose only stored output is prose would have to parse its own prose — which is
aggregating posts, one level in. The multi-week runs below exist only because
the record does.

## Cadence is the load-bearing field

Every contributor declares a cadence, and **persistence eligibility is derived
from it** in `mk()` rather than remembered by whoever writes the next one.

The rule: a measure may carry a persistence claim only if it produces **more
than one independent observation inside the week being described.**

| Cadence | Contributors | May claim persistence |
|---|---|---|
| `daily` | short volume, price, volume, crossings, threshold list | **yes** |
| `event` | filings, comment letters | no |
| `per-filing` | dilution | no |
| `twice-monthly` | short interest | no |
| `half-monthly` | fails to deliver | no |

**FTD is the case that needs the guard.** A half-month file holds about ten
settlement dates, so *"failed on eight of ten"* is a genuine persistence
statement — about a period that ended up to six weeks before the week being
described. That is the *number true about something adjacent to the question*
failure in [`CLAUDE.md`](../CLAUDE.md), and nothing downstream could catch it.
Its verdicts are keyed by **period**, never by week.

Demonstrated with the guard removed, per this repo's rule that a guard proves
nothing until it has been shown to fire:

```
WITH THE GUARD
  short_volume     daily          ACCEPTED a persistence claim
  threshold_list   daily          ACCEPTED
  ftd              half-monthly   REFUSED
  short_interest   twice-monthly  REFUSED
  dilution         per-filing     REFUSED
  filings          event          REFUSED

WITH THE GUARD REMOVED
  ftd accepted: {'hits': 8, 'of': 10, 'direction': 'up'}
```

## Nothing is restated that a component already owns

| Borrowed | From | Why not a local copy |
|---|---|---|
| `ALWAYS_POST_ITEMS`, `PRESS_RELEASE_ITEMS`, `ITEM_LABELS` | `press_monitor.py` | Carries measurements over 1,986 filings — 4.02 dropped ten times out of ten, 5.02 considered and excluded, never add 9.01 |
| `MIN_TOTAL_VOLUME`, `BASELINE_DAYS` | `regsho_volume.py` | The floor and baseline width are that component's judgement |
| `NOTABLE_CHANGE_PCT` | `short_interest.py` | |
| `NOTABLE_STEP_PCT`, `SPLIT_DROP_PCT`, `observations()` | `dilution.py` | |
| `fetch_period()`, `FLAG_MULTIPLE`, `MIN_FLAG_PERIODS` | `ftd_monitor.py` | **The three identity guards.** Reimplementing them is the most dangerous thing this file could do — see the SPCX case in [watchlist.md](watchlist.md) |

The digest asks a *different* question from each of these — "was this week
material for this company" against "should this be posted right now" — but it
must not maintain a second copy of the *answer*. `watchlist.py` exists because
the roster was once defined eight times in five shapes.

Its own thresholds stay local and are marked as calibrated for a weekly
question: `SHOVOL_POINTS`, `SHOVOL_DAYS`, `PRICE_SD_MULTIPLE`,
`VOLUME_MULTIPLE`, `CONVERGENCE_THRESHOLD`.

## The denominator correction

Thirteen components, but **`btc_context.py` and `grid_context.py` have no
per-company dimension at all** — bitcoin network data and ERCOT demand are not
facts about a company — so they are not registered and cannot contribute to a
per-company count. Of the ten that are, the fortnightly pair publishes nothing
in most weeks.

**The realistic denominator is 6 to 8, not 13.** "Three of thirteen" is really
three of about seven, and a threshold set against the wrong denominator is
wrong in a way that looks conservative.

### And contributors are not all independent

Co-occurrence over the backfill, against what independence would predict:

| pair | observed | expected | ratio |
|---|---|---|---|
| price + volume | 3 | 0.6 | **5.3x** |
| crossings + volume | 4 | 1.0 | **4.0x** |
| short_interest + threshold_list | 3 | 0.9 | 3.3x |
| short_interest + volume | 4 | 2.2 | 1.8x |
| short_volume + short_interest | 9 | 6.4 | 1.4x |
| crossings + short_interest | 3 | 2.9 | 1.0x |

price, volume and crossings are **three readings of one Alpaca bar series**.
VIP scored four in W30 on crossings + price + volume + filings, three of them
the same event. The filter's own purpose argues the same way: a big move on
heavy volume through a 52-week high is the thing a reader *cannot* miss, so it
must not be what pushes a company over the line. They are collapsed into one
`market` family, which moved `>=3` from eight ticker-weeks to five.

**The short-side measures are deliberately not collapsed.** A flow, a position,
a settlement failure and a regulatory listing run at 1.0–1.8x, which is what
genuinely different measurements of a related phenomenon look like rather than
one fact counted twice. Collapsing those would discard the convergence this
exists to find.

## The convergence threshold, and where it came from

Ten complete ISO weeks, **2026-W22 to 2026-W31**, 19 tickers, **190
ticker-weeks**, all ten contributors fetched.

```
week       denom     =0   =1   =2   =3   names at >=3
2026-W22       7      4   11    4    0   nothing converged this week
2026-W23       6     10    5    4    0   nothing converged this week
2026-W24       7     10    6    2    1   ANY
2026-W25       7     11    3    5    0   nothing converged this week
2026-W26       7      7    8    3    1   ABTC
2026-W27       7     11    4    4    0   nothing converged this week
2026-W28       7      6    8    4    1   ANY
2026-W29       7     12    4    3    0   nothing converged this week
2026-W30       6     14    3    2    0   nothing converged this week
2026-W31       8      9    5    2    3   ABTC, ANY, NUAI

pooled               94   57   33    6
                    49%  30%  17%   3%
```

| threshold | ticker-weeks | per week | share of roster |
|---|---|---|---|
| >=1 | 96 | 9.6 | 51% |
| >=2 | 39 | 3.9 | 21% |
| **>=3** | **6** | **0.6** | **3%** |

**Set at 3 families.** The decay runs 0.61, 0.58, then **0.18** — a real break
between two and three. This is not the heartbeat case in
[`rejected.md`](rejected.md), whose healthy and broken populations overlapped
and admitted no threshold at all.

At `>=2` the section would name 3.9 companies a week, a fifth of the roster,
which is a second firehose rather than a filter. At `>=3` it names 0.6 and is
**empty in six of the ten weeks**.

**That is the intended behaviour.** A renderer must print *"nothing converged
this week"* rather than dropping the section. Absence is a measurement.

`CONVERGENCE_THRESHOLD = 3`, with `CONVERGENCE_BASIS` carrying the week count
beside it, so the number can never be read without knowing what it was
measured over.

## Per-contributor rate

| contributor | cadence | persistence | notable | /wk | not-testable |
|---|---|---|---|---|---|
| short_volume | daily | yes | 35 | 3.5 | 5 |
| short_interest | twice-monthly | no | 35 | 3.5 | 0 |
| filings | event | no | 18 | 1.8 | 0 |
| crossings | daily | yes | 16 | 1.6 | 10 |
| ftd | half-monthly | no | 13 | 1.3 | 2 |
| volume | daily | yes | 12 | 1.2 | 5 |
| price | daily | yes | 9 | 0.9 | 9 |
| threshold_list | daily | yes | 5 | 0.5 | 0 |
| comment_letters | event | no | 3 | 0.3 | 0 |
| **dilution** | per-filing | no | **0** | 0.0 | 0 |

### The short-volume rule is calibrated, not chosen

Four consecutive weeks of real FINRA data, 19 tickers:

| rule | wk1 | wk2 | wk3 | wk4 |
|---|---|---|---|---|
| any single day \|dev\| >= 12 pts — **the shipped daily rule** | 12 | 8 | 9 | 12 |
| same-sign \|dev\| >= 8 pts on 3 of 5 | 4 | 4 | 3 | 3 |
| **that, AND \|week median\| >= 1 baseline SD** | **3** | **2** | **2** | **1** |

The first row is the firehose quantified: over half the roster, every week,
which is what a digest keyed on "did the component flag it" would inherit.

**Both conditions are required.** Points alone let a chronically noisy ticker
qualify on ordinary noise; dispersion alone lets a very quiet one qualify on a
move too small to mean anything. The dispersion half does a second job:
[`rejected.md`](rejected.md) closed the BTC-correlation weekly table because
the metric moved when its **baseline** moved, not when the companies did.
Expressing the claim in the ticker's own dispersion is regime-aware by
construction, and the baseline and its SD are carried into the record so the
arithmetic can be disagreed with.

## Filings: presence is useless, and the item-code route is rare

| rule | ticker-weeks | share of roster-weeks | per week |
|---|---|---|---|
| any filing (presence) | 108 | **57%** | 10.8 |
| 8-K press-release item | 34 | 18% | 3.4 |
| form class: passive (13G) | 17 | 9% | 1.7 |
| form class: control (13D) | 11 | 6% | 1.1 |
| form class: capital (424/S-1/S-3) | 8 | 4% | 0.8 |
| **8-K `ALWAYS_POST` item** | **1** | **1%** | **0.1** |
| form class: periodic | 1 | 1% | 0.1 |

Presence at 57% is why the rule cannot key on it. The headline rule is
`ALWAYS_POST` item **or** capital **or** control **or** late — periodic reports
are excluded because a quarterly is scheduled and expected and would fire for
most of the roster inside an earnings window, and 13G is index funds doing
their February housekeeping.

The **one** `ALWAYS_POST` hit in 190 ticker-weeks is **NUAI, 2026-W31, 8-K item
4.02, non-reliance on prior financials** — the exact filing `press_monitor.py`'s
own comment cites as the case that motivated the set, re-derived independently.
The route is rare and right, not rare and broken.

## Persistence across weeks

The claim only the stored record can make:

```
ANY   threshold_list  5 weeks: W24, W25, W26, W27, W28
NUAI  short_volume    4 weeks: W22, W23, W26, W28
ANY   volume          4 weeks: W23, W24, W25, W31
SLNH  short_volume    4 weeks: W26, W29, W30, W31
IREN / GLXY / DGXX / BGDE / ABTC   short_volume   3 weeks each
WYFI  volume          3 weeks
```

ANY's threshold-list run is the worked example of the whole design:

```
ANY   W22 0/4  W23 0/5  W24 5/5  W25 4/4  W26 5/5  W27 4/4  W28 3/5  W29 0/5
```

Five consecutive weeks listed, from a component that posts only on a change.

## A publication date that falls on a weekend was claimed by no week at all

**Found and fixed 2026-08-13, on separate branches and in that order.**

`period_published_in` computes a bare calendar publication date — month end for
the `a` half, the 15th of the following month for `b` — and asks whether it
falls inside `sessions`, which `week_sessions` fills with Monday to Friday. So
**when that nominal date lands on a Saturday or Sunday, no week can contain it,
ever.** Not delayed: permanently unsatisfiable.

Measured across every week of 2026: **8 of 24 half-month periods are affected**
— `202601a`, `202601b`, `202602a`, `202602b`, `202605a`, `202607b`, `202610a`
and `202610b`.

The consequence reaches the output. `ftd_publishes` returns `False`, so
`published` is `False`, so `counted_in_denominator` is `False`, and the
convergence denominator is short by one contributor for those weeks. The
contributor lands in *fetched but did not publish* — the innocuous-looking one
of the three states this component separates precisely so that this class of
thing stays visible. No error, no log line.

It was left alone at first, deliberately: it was found on a branch whose rule
was that the module under test must not change, because changing behaviour
under cover of a test branch is how a regression ships unnoticed. The suite
shipped with a check pinning the defect as it was, precisely so that a fix
would have something to break.

**The fix rolls the nominal date FORWARD to the following Monday**, so the
period is claimed by a week in which the file certainly exists. Rolling back
to the preceding Friday would also close the gap and is the worse choice: it
would claim the period in a week that ended before the nominal publication
date, reporting data as available before it was.

The check that pinned the defect was replaced by one that pins the fix, and
two more were added: that the roll is forward rather than back, and that
**every one of the 24 periods in 2026 is claimed by exactly one week** — none
by zero, none by two. A count alone would not separate "all fine" from "half
of them silently invisible", which is the state this was in. Restoring the
original arithmetic turns all three red.

**Verified against live data**, ten-week backfills on the fixed branch and on
`main`, same sources minutes apart. Exactly one line of ten differs:

```
2026-W23  main   denominator 7 families (9/11)   converged: CIFR
2026-W23  fixed  denominator 8 families (10/11)  converged: CIFR
```

That is `202605a`, nominal publication Sunday 2026-05-31, now rolled to Monday
2026-06-01 and claimed by the week beginning that day. The nine other weeks are
identical and **no company's verdict changed** in the sample. The correction is
to the denominator the convergence threshold is measured against, which is what
the denominator section above is about, not to any week's names.

## Untested is not the same as working

**As of 2026-08-13 there is a suite**: `test_weekly_digest.py`, 113 checks over
the publication windows, the silence section, the output guards, fetch-depth
independence and all ten contributor rules. It runs in `Tests` on every push.
What follows is still true and is a different claim — a rule with a check
against a fixture has still never met the occurrence it exists for.

`dilution` fired for no company in ten weeks, and **the rule is not the
reason**: only **3 of 190 ticker-weeks had a new XBRL observation at all**, and
the largest step was HUT at **+9.50% against a 10.0% threshold** — half a point
under the line.

So it is genuinely low-rate rather than broken, but its rule has never been
exercised against a real occurrence and an empty section from it cannot yet be
read as a working one. The run output separates three states — **not fetched**,
**fetched but never fired**, and **exercised** — because collapsing any two of
them hides exactly this.

## Cost

**103 requests, 49.7 s of fetching**, whole job about a minute, for ten weeks
and all ten contributors.

| source | requests | seconds | note |
|---|---|---|---|
| short_volume | 1 | 4.8 | 4,906 rows, 91 sessions |
| short_interest | 1 | 6.0 | 206 settlement dates |
| bars | 1 | 0.6 | 6,113 bars, SIP |
| filings | 19 | 4.5 | **10,205 filings** |
| threshold | 50 | 17.5 | 47 daily files |
| dilution | 19 | 8.4 | |
| ftd | 12 | 8.1 | 11 half-month periods |

Ten weeks costs about what one week costs: every source is fetched once for
the whole span and sliced per week, one EDGAR pass serves three contributors,
and every bulk source is a single call.

Record size is **51 KB/week** with full daily detail. That is at the line the
design set for collapsing the grid, and it will cross it as contributors are
added.

## The two renderings

`digest_render.py`. Both are **pure functions of the verdict record** — a
renderer that derived anything would be a second derivation to keep in step
with the first, and the two would disagree the week it mattered. Both take
`[older, ..., this week]`, so a claim spanning weeks reads the record rather
than recomputing it.

### The post

Filter first; the summary is what is left over. Convergence, then the
two-family tier, then persistence, then silence, then what could not be
measured — and only after all of that, the `<=28`-character table of the week's
moves and the material filings.

Measured on real weeks:

| | 2026-W31 (3 converged) | 2026-W30 (empty) |
|---|---|---|
| description | 1,397 / 4,096 | 1,092 / 4,096 |
| embed total | 2,171 / 6,000 | 1,832 / 6,000 |
| widest monospace line | 26 / 28 | 26 / 28 |

`check_post()` **fails the run** on any of those rather than trusting them.
Discord accepts an over-wide code block silently and wraps it on mobile, so
the ceiling cannot be verified by reading the post — which is how the recap
sat at 47 characters and the earnings calendar at 52 before both were rebuilt.

Three rules held in code, none of them stylistic:

1. **An empty convergence section prints.** Six of the ten backfilled weeks
   land there. A section that vanishes when empty teaches the reader that its
   absence means nothing happened, when it means the filter worked.
2. **The two-family tier is listed, never promoted** — `At 2 families, not
   promoted: BGDE, VIP`. Promoting 3.9 companies a week is the firehose the
   threshold exists to prevent.
3. **Never a silent cap.** When the post runs out of budget it says how many it
   dropped and where they are.

### The file

`digest/YYYY-Www.md`, written once and never rewritten. **11.3 KB** for a week
with three converged companies, 9.0 KB for an empty one — against 51 KB for
the same week's JSON record.

**The grid is what keeps that flat.** One glyph per company per *family*, not a
block per company per contributor:

```
| | letters | shares | filings | FTD | market | sh int | sh vol | thresh |
| **NUAI** | · | · | ● | ● | · | ● | · | · |
| **SPCX** | · | · | · | ~ | ~ | ● | · | · |
```

`●` above threshold · `·` measured, routine · `~` rule not applicable · `✕`
source failed · `–` nothing published.

A contributor added later joins a family or adds **one column**, and no other
section changes shape. The alternative — a subsection per company per
contributor — is 19xN blocks and needs restructuring the first time N grows,
which for a file article-writing reads for a year is the worse failure.

The cells that say nothing are the point. *Nobody else on the roster did this*
is a claim only the complete grid supports.

Detail blocks sit outside the grid and carry only the non-routine cells: the
figure, **the baseline it is measured against**, the per-session values, a
source citation per claim, and **latency per figure rather than per section**,
because an FTD number and a short-volume number in the same file are six weeks
apart.

## Two traps found by running it

**FINRA caps every response at 5,000 rows and says nothing about it.** Asking
for 20,000, 25,000, 50,000 or 60,000 all return exactly 5,000 — HTTP 200, no
marker of any kind. A 60-day window fits under the cap and a backfill-sized one
does not, so it truncates silently at exactly the point the window becomes long
enough to be worth running, and the damage is a baseline built from a fraction
of its sessions and reported as whole. Paginated by `offset`; an offset past
the end returns HTTP 400, which is treated as end-of-data only after a full
page has already come back. The page ceiling is reported, never capped quietly.

**A short-interest publication window is nine days wide and therefore overlaps
two consecutive weeks.** The first version tested for overlap, so one
settlement was counted twice and short interest fired 7.3 times a week from a
source that publishes twice a month — a number that would have set the
threshold wrongly while looking like a finding. Each settlement now lands in
exactly one week, at settlement + 12 calendar days.

## And three found by rendering it

**Silence is the one section a missing source turns into an invention.** A dry
run with EDGAR unavailable reported eleven companies as having filed nothing,
which nothing had measured. Every other section *understates* when a source
fails; this one asserts, because absence is its subject. It now names what did
not run and downgrades to *"quiet on the measures that ran — NOT silence"*.

**A verdict must not depend on how much history the caller happened to fetch.**
`derive_ftd` took its median over every prior period in the fetch, so ABTC
converged in a three-week render that pulled 8 half-month periods and did not
in the ten-week backfill that pulled 11 — the same week, two answers. Bounded
to `ftd_monitor.BASELINE_PERIODS`. Every other contributor was already bounded;
this was the one reading *everything fetched*, and re-derivability is the
premise the component rests on.

**Detail keys are a shared namespace even though the dicts are not.**
`baseline_median` meant a volume median to one contributor and a median of
half-month fail peaks to another. The renderer matched the first and read a
field only the second carries. Renamed to carry the quantity, and the backfill
now prints every key claimed by more than one contributor so the next
collision is visible rather than latent.

## Adding a contributor

One derive function and one line in `CONTRIBUTORS`. Sections render in registry
order, the record gains a key, the denominator grows by one, and no existing
section changes.

Declare the `cadence` honestly — it is what decides whether the contributor may
claim persistence, and `mk()` enforces it rather than trusting the author.

If the new contributor reads a source another one already reads, add it to
`SOURCE_FAMILY`. Two readings of one series are one fact.

## Running it

```bash
gh workflow run "Weekly digest" -f backfill=10
```

Dispatch-only, posts nothing, commits nothing, uploads the record as an
artifact. It needs `SEC_USER_AGENT` and the Alpaca keys, so **do not run it
locally** — without them four of the ten contributors report `unavailable` and
the distribution is measured over the rest, which is not a distribution to set
a threshold from. The run says so explicitly rather than leaving the gap to be
noticed.

## The schedule

**Daily at 17:00 UTC, gated on the week file.** Both halves are measured
rather than chosen.

**Daily, not weekly.** The daily workflows delivered 3–4 of their 5–6 nominal
fires, so a once-a-week cron has roughly even odds of simply not running, and
nobody would notice until the following Saturday. Firing every day and gating
on *"has week N been produced?"* is the shape `short_interest.py` and
`ftd_monitor.py` have used for months to post twice a month off a daily check.

**17:00 UTC off the delay distribution.** Scheduled runs here are never on
time and the lateness is bimodal: 83–173 minutes in the 05:00–15:59 window
against 51–71 in the 16:00–23:59 one. Firing in the afternoon regime costs
about ninety minutes less drift, and drift is drop exposure. 17:00 lands
around 17:51–18:11.

**Saturday is the first eligible day, and it falls out of the gate rather than
the cron.** `recent_weeks()` only returns a week once its Friday has passed:

```
Sat 2026-08-08  -> targets 2026-W32     <- first chance
Sun 2026-08-09  -> targets 2026-W32
Mon 2026-08-10  -> targets 2026-W32
...
Fri 2026-08-14  -> targets 2026-W32     <- last chance
Sat 2026-08-15  -> targets 2026-W33
```

Seven fires at the same week. All seven dropping is about **0.4%** at the
measured 45% rate. A Friday digest was never an option regardless: FINRA short
volume is T+1 and `regsho.yml` runs at 23:00 UTC for the *previous* trade date,
so Friday evening would report a four-day week as five.

### The floor: `FIRST_LIVE_WEEK`

The schedule landed mid-week on 2026-08-05, when the gate's target was
**2026-W31** — a week that had ended the previous Friday. Left alone the first
live post would have been five days stale, which is a poor opening for a
component whose whole argument is that it reports a week while the week still
means something.

`FIRST_LIVE_WEEK = "2026-W32"`. Anything earlier is refused.

**A floor, not a freshness window, and the difference is the catch-up.**
*"Only post a week whose Saturday is today"* would also have delayed the first
post, and would have destroyed the thing the daily cadence exists for: by
Sunday the Saturday has passed, so a dropped Saturday would never be
recovered. The floor leaves all seven fires per week intact and only ever
refuses weeks that predate the component.

```
Wed 2026-08-05  -> 2026-W31   no-op, below the floor
Thu 2026-08-06  -> 2026-W31   no-op
Fri 2026-08-07  -> 2026-W31   no-op
Sat 2026-08-08  -> 2026-W32   FIRST LIVE POST
Sun 2026-08-09  -> 2026-W32   posts only if Saturday dropped
```

It stays after go-live. A fresh clone, a reset, or a hand-run with `digest/`
absent would otherwise walk backwards through history and post weeks nobody
asked for.

### There is no state file

**The file for week N is itself the record that week N was produced.** A state
file would carry the same information, be written by the same commit, fail in
the same instant for the same reason, and add one more artefact for fifteen
workflows to race on.

It reads the **working tree**, so the job pulls first. A queued run checks out
the SHA fixed when the run was *created*, not when its job starts, so without
the pull it can ask "has this week been produced?" of a tip that already
answers yes — which is the mechanism behind the duplicate-post incident of
2026-08-04, where two runs were serialised exactly as the concurrency group
intended and the second still began from the commit before the first one's
push.

### Post first, then write

The ordering is a choice between two failures, and the quieter one is worse.

| order | failure | consequence |
|---|---|---|
| write, then post | commit succeeds, post fails | gate closed, **nothing ever posted** — silent |
| **post, then write** | post succeeds, push fails | the post repeats tomorrow — **loud** |

A duplicate is visible by reading the channel; a silent miss is not, and
silence is the failure this repo is worst at noticing. So: post, then write,
with `snapshot.yml`'s fetch-reset-retry loop around the push, and **the step
exits non-zero if the push still fails** — turning a silent
duplicate-tomorrow into a notice today.

Last writer does *not* win here, unlike `snapshot.json`. A week file is
written once and never rewritten, so the retry re-applies this run's new file
on top of whatever else landed meanwhile.

### DRY_RUN skips the post and the commit

And the dry-run render path **refuses to write the live target week**. A dry
run that wrote that file would close the gate and suppress the real post
permanently, with no error anywhere — the same shape as the state-file races
this repo already carries scars from. Backfilling an older week is harmless
and allowed.

## A company added mid-week is reported for the whole week

**Deliberate, and the exact opposite of what `press_monitor.py` does. Neither
is a bug.**

Five companies joined the roster on 2026-08-05, a Wednesday. The 2026-W32
digest reports all five across the full Monday-to-Friday week — GLXY's notable
verdict that week is a `SCHEDULE 13G/A` filed before it was on the roster at
all. Meanwhile `press_monitor.baseline_companies()`, added 2026-08-09,
suppresses **everything** from before a company joined, on the rule that
adding a ticker must produce no backdated posts.

The two rules disagree because the two components answer different questions.

| | |
|---|---|
| `press_monitor` | an **event feed**. A backdated post is noise: it announces as news something that already happened, hours or days late, to a reader who watches the channel continuously. |
| `weekly_digest` | a **summary of a week**. A week that omitted its first two days for five companies would be wrong about the week, and the omission would be invisible in the output. |

**It costs nothing to keep them different because the digest re-derives.** It
queries Alpaca, FINRA and EDGAR by symbol and CIK for the whole week rather
than accumulating what the repo saw, so a company joining on Wednesday has a
complete five-session week with full trailing baselines — verified on W32,
where all nineteen companies show five sessions and identical 12-week,
30-session and 20-session baselines. There is no partial-coverage state to
report because none arises.

**This is written down because the next person to notice it will reasonably
conclude one of the two is wrong and change it.** Changing the digest to
respect join dates would make weekly figures silently incomplete; changing the
monitor to post pre-join items would reintroduce the seventeen backdated posts
of 2026-08-05. See [`press-monitor.md`](press-monitor.md) for the monitor's
side.
