[← Watchlist monitor](../README.md)

# Holder events

`holder_events.py` reads Schedule 13D/G and posts **events**, not a
concentration measure.

| event | trigger |
|---|---|
| **arrival** | a filer group's first filing on this company, at or above 5% |
| **change** | an amendment moving the percentage by ≥0.5 points **from the last figure published**, not from the last one seen |
| **declared exit** | a final amendment reporting 0% |
| **below 5%** | a first sighting already under the threshold |
| *silence* | a holder who stops filing — **never** reported as a departure |

Daily, weekdays 13:45 UTC, to `WEBHOOK_URL_INSIDER`. Posts only on an event.

## Why it is not a concentration measure

Anyone below 5% never files, so a sum of disclosed holders has a floor it
cannot state and invites a cross-company comparison it cannot support.

**And it never counts holders**, which is not modesty. Over 233 structured
filings, **184 distinct reporting-person names collapse to 70 filer groups**
once co-filing is taken into account — 83% of names sit inside a group. A
count would overstate by that much without a grouping rule.

An event feed needs none: **a group filing is one event with several
signatories**, and the filing carries its own signatory list.

## Filer groups are matched by co-filing, not by name

Two entities on one filing are one filer. A name-stem rule was tested and
fails in both directions:

- it merges **`BANK OF AMERICA CORP` with `BANK OF NOVA SCOTIA`**, and
  `David E. Shaw` with `David F. Craver`
- it misses **36 real groups** whose members share no word — WULF's nine span
  Beowulf, Heorot Power, Lucky Liefern, Riesling Power, Stammtisch Investments
  and Paul B. Prager personally

Signatory *overlap* rather than an exact set, so a group that gains one entity
between amendments does not read as a new arrival.

## Latency is measured, not quoted

Measured over 233 filings, 2026-08-07:

| | `dateOfEvent` | lag |
|---|---|---|
| **13D** | 77 of 77 — **100%** | median 3 days, 83% within 5, two over 45 |
| **13G** | 0 of 156 — **0%** | n/a |

**The absence is substantive, not a gap.** A 13D reports an *event* — crossing
5% with intent — so it carries the date that happened. A 13G reports a
*position as of a date* on a periodic schedule; there is no event to date, and
the schema omits the field.

```
13D  crossed 2025-06-24 · filed 2025-07-03 · 9 days
13G  filed 2025-06-04 · a 13G reports a position as of a date rather than an
     event, and files no event date — measured absent in 156 of 156
```

Neither quotes a statutory deadline. The 2024 amendments already changed those
once; a component asserting a rule goes stale when the rule changes, one
measuring the gap does not.

**The field is US-formatted.** `dateOfEvent` reads `09/03/2025` while
`filingDate` in the same payload is ISO. The first measurement pass reported
all 77 13D filings unparseable for that reason — a clean zero rather than an
error.

## The arrival caveat

A holder appearing for the first time in a short record may have arrived, or
may have held for years and filed legacy until the schema changed. Those read
identically and one is not news.

The structured era runs from **10.8 months (HUT) to 30.3 (IREN)**, and SPCX has
none at all. So an arrival states the record's length as a count against the
floor rather than a bare marker, and where the record begins on the same day it
says there is barely any record to have been absent from.

## Two schema variants, one per form family

Measured: every filing carries blocks of exactly one kind and none of the
other.

```
SCHEDULE 13D, 13D/A  ->  reportingPersons/reportingPersonInfo
SCHEDULE 13G, 13G/A  ->  coverPageHeaderReportingPersonDetails
```

A pass reading only the first found zero blocks in **156 of 233** filings and
reported an answer about two-thirds of nothing.

## Relationship to the press monitor

`press_monitor.FORM_TYPES` already posts every 13D/G to the main filings
channel. **It announces that a filing exists; this component reads it.** Same
source, different question — the relationship `regsho_volume.py` and
`short_interest.py` already have. Different channels, so the pair never reads
as a double post. The cross-reference is in both files; removing either leaves
a real gap.

## Why it cannot report a departure

Ageing a holder out was tested and refused. The gap between consecutive
filings has a **median of 92 days for holders still filing against 91 for
those gone silent** — the same distribution. No threshold separates them, and
`calibrate_staleness`'s formula applied to it yields 426 days, longer than the
structured era for most of the roster.

29 **declared** exits exist and are unambiguous. Silence is reported as
silence, or not at all.

## Critical: a company added to the roster posts nothing

**This component sent 86 messages on 2026-08-14** — CORZ 39 of 39, CRWV 30 of
32 — because three companies had been added the day before, and for a company
absent from `holder_state.json` every 13D/G on record is a first appearance,
which is exactly what this file reports. Every one of those posts was
individually correct.

The cold-start rule below did not cover it and was never going to. It asks
whether the STATE FILE exists, which is a fact about this component's history,
not about the company's. A roster that has been running for months has a state
file; a company added to it this morning has no record in that file at all.
The two questions look identical in the log and are not the same question.

Since 2026-08-14 the rule is per company, and it lives in
[`first_run.py`](../first_run.py) because five components shared the shape.
What suppression MEANS stays here: the filings are still read and still
recorded — accessions into `seen`, percentages into `holders`, the era floor
into `era` — and only the OUTPUT is withheld, so the next genuine change for
that company posts normally.

**It filters in a dry run too**, unlike the cold-start rule. That exception
exists so an unrendered embed can be previewed on the only run where events
are available; these embeds render every week, and a dry run that showed the
suppressed events could not demonstrate that they were suppressed, which is
the one thing anyone verifying the change needs to see.

**The same rule runs over FORM TYPES**, in its own namespace. `FORMS_TRACKED`
is `STRUCTURED` only — adding a prefix there makes every filing matching it a
first appearance at once, and this component has no age floor to blunt that.
`LEGACY` is deliberately excluded: legacy filings never become events, so
guarding them would print a first-run line claiming a suppression that could
not have happened.

**The backfill announces itself.** On the one run where the namespace is
absent, every key is recorded, nothing is suppressed, and a `FIRST-RUN RULE:`
line says so. Without it a component that ran the rule and one where it was
never wired produce identical logs — which is what the first five dry runs
looked like, all green and all silent.

## A company this run could not reach is not established

Nothing is wrong here today, and that is ORDERING rather than construction.
The fetch-failure path records a company whose 13D/G were never read, and the
next run then posts every one of them — 2026-08-14 exactly, arriving through
a transient instead of a floor. `dilution` and `crossings` were both found
genuinely wrong on 2026-08-18; this one was one bad SEC response away.

**Pruned only when the component has never successfully read it**, and that
second condition is the whole safety of the rule. The first version pruned
on "not measured this run" alone, so one 503 un-established a company — and
because an event's accession enters `seen` before the suppression runs, the
next run's genuinely new 13D/G was dropped and no later run could recover
it. Caught in review before merge.

The held-state signal is `read`, a record of every successful fetch, UNIONED
with the older `era` floor. `era` alone answers the wrong question: it is
written only when structured filings exist, so a company read cleanly every
run that simply has no 13D/G would hold nothing — and that is precisely the
case where pruning is catastrophic rather than harmless.

`measured` is added inside the loop only after the submissions request
succeeds, which is the whole distinction: an empty result means the company
has no 13D/G, an exception means this run does not know.

## Three outcomes shared one bare `None`

`read_filing` returned `None` for three different things and printed for only
one of them:

| Outcome | Before | Now |
|---|---|---|
| fetch or parse failed | one line, accession and exception class | a reason naming the exception |
| parsed, no known reporting-person block | **silent** | a reason **naming the tags actually present** |
| a block with an empty name field | **silent**, the rest of the group kept | counted per company |

The middle one is the dangerous one. A block-name rename at EDGAR hits every
filing at once, so the component would go quiet while the per-company counts
read normally and the run stayed green. That is this repo's oldest shape: a
pattern matching nothing looks exactly like one whose matches never occur. The
reason names the tags present because the useful question after a rename is
what the document calls them now, and answering it by hand means downloading
the filing again.

The third has **never been measured**. A group of five read as three gets a
different signature and can read as an ARRIVAL a year later. It is counted
rather than acted on: a guard built on an unmeasured case is a guess with a log
line attached.

### The reconciliation is the part that cannot be faked

```
read N filing(s): E classified, F below the floor, U unreadable,
  C about another roster company, O about an off-roster company,
  S naming no subject
```

Every filing fetched has exactly one outcome, so they must sum to `N`. When
they do not, the run says so and says that the summaries above it cannot be
trusted either. Reconciling the 2026-08-17 run by hand was the only way anyone
knew a schema change had not already happened, and nothing in the component
kept that arithmetic.

## An unreadable filing is marked seen only if it could not have posted

The accession used to be appended to `seen` before the failure check, so one
bad HTTP response deleted a 13D/G event permanently. The same file had applied
the opposite reasoning to a failed POST 110 lines later, with the comment "a
failed post must not be marked seen or it is lost silently".

**The obvious fix is worse than the bug.** Moving the append below the check
unconditionally reads as the correction and is not: `measured` and
`state["read"]` are written the instant the submissions request returns, before
any document is fetched, so a company whose index read fine is recorded
established however many of its documents failed. Leave those unseen and the
company drops out of `newly_watched` on the next run, and its unreadable back
catalogue posts one run after its suppression window closed. That is
2026-08-14 reached through a transient instead of a floor.

So the append is **paired** with `suppressed_run()`, which asks whether an
event from this filing could have reached the channel on this run at all. All
three suppression axes count, because all three end the same way: a cold start,
a company added since the last run, and a form prefix newly tracked since the
last run. If any holds, the filing is marked seen, because that costs exactly
what today costs. Otherwise it stays unseen and retries.

`suppressed_run` sits at module level rather than inside `main()` so it can be
tested. The behaviour it guards is only reachable through `main()`; the
decision does not have to be.

## `filings.recent` is a window, not the index

EDGAR's `filings.recent` page holds roughly a thousand filings and rolls. For a
heavy filer it sweeps past the company's own 13D/G era with no error and no log
line. Until 2026-09-10 `filings_for()` read only that page.

**The eviction was live, not theoretical.** CoreWeave's printed structured
count fell across scheduled runs while three *new* filings arrived:

```
CRWV  32 (08-14)  35 (08-17)  25 (08-21)  23 (08-27)  23 (09-02)  23 (09-09)
CORZ  39          42          42          42          42          42
```

CORZ sits at 664 filings, comfortably under the cap, and is flat. A count going
down reads as a data correction, not as a truncated page.

Measured over all 22 roster CIKs: five companies have a second index page,
CRWV, MARA, RIOT, SLNH and WULF. **Only CRWV has structured 13D/G on it**,
twelve of them. The other four carry only legacy SC-spelling filings there, so
the legacy footnote has been reporting a floor rather than a count and its
numbers rise when this lands.

**This adds nothing to post, which is the whole reason it is safe.** All twelve
CRWV filings are already in `seen`: they were read on 2026-08-14 while still on
the recent page, and eviction from the window does not un-record them. The
probe put unseen filings across the whole roster at **zero** after dropping the
misattributed ones, so this needs no suppression axis. Landing it without that
number would have been the 2026-08-14 flood shape reached by editing a fetch
function, and neither the company axis nor the form axis would have covered it,
because neither the company nor the form is new.

**It cannot move an era floor either.** `era` is stored as `min(prior, oldest)`
so it only ever moves earlier, and the stored floor already equals the oldest
over the paginated set for all 22 companies. Checked before the change, not
after.

Cost is five extra requests per run, one per company with a second page, each
behind `REQUEST_GAP`. The company loop itself still has no gap between
companies; that is unchanged and not addressed here.

## Critical: which company is this filing about

EDGAR lists a Schedule 13D/G under **every reporting person's CIK as well as
the subject's**. Until 2026-09-10 the main loop labelled each filing with the
ticker of the roster iteration it was read under and never asked, so a roster
company that filed about somebody else was recorded as holding a stake in
itself.

**It published.** Run `31810564097`, 2026-08-14, posted nine embeds opening

```
RIOT — activist stake disclosed
Riot Platforms, Inc.
16.30% of class
```

and walking down 14.60, 13.40, 12.30, 11.20, 9.80, 8.30, 7.20, 4.60. Every one
is Riot's own filing about Bitfarms Ltd. The arrival caveat on the first cites
`2025-04-09`, which is that same filing's date, so the line written to qualify
a false arrival was calibrated off the thing that should not have been there.

**Measured on the runner over all 350 structured 13D/G under the 22 roster
CIKs, every index page** (`probe_holders.py`, phase `subjects`):

| Read under | Count | Actually about |
|---|---|---|
| RIOT | 9 | Bitfarms Ltd. |
| CRWV | 2 | Applied Digital (on the roster) |
| APLD | 2 | ChronoScale Corp |
| CIFR | 1 | Canaan Inc. |
| HUT | 1 | American Bitcoin (on the roster) |

The subject CIK is present in **350 of 350**, always at
`edgarSubmission/formData/coverPageHeader/issuerInfo/`, so there is no
cannot-determine case to design around today. **The spelling splits on form
family**: `issuerCIK` in 103 of 103 13Ds, `issuerCik` in 247 of 247 13Gs.
Tag comparison is case sensitive, so a rule accepting one spelling would drop
seven filings in ten. `filing_subject.subject_cik` lowercases the tag rather
than freezing a tuple of known spellings, because two measured is not two
guaranteed and this repo has the SC 13D rename on record.

### What each arm does, and why each one prints

| Subject | Action | `seen` |
|---|---|---|
| this company | posts as before | appended |
| another roster company | skipped, left for that company's own iteration | **not** appended |
| not on the roster | skipped | appended |
| the document does not say | **refused**, not attributed | **not** appended |

Skipping the filer's copy cannot delete the only copy: all three
roster-subject filings were measured **present under the subject's CIK as
well**, so the subject's own iteration records them. It is deliberately not
appended there, because appending would race the subject's iteration through
the `fresh` snapshot and could mark it seen before the right company reads it.

Suppression is on a **positive mismatch only**. Refusing whenever the subject
is merely missing would convert a visible wrong post into an invisible missing
one, which is the worse direction in a component whose normal state is a quiet
channel. The refusal arm is unreachable today at 0 of 350, and its retry is
unbounded by design: a filing that cannot be attributed must not fall back on
the index it happened to be read from, which is the assumption that produced
the nine embeds.

Every arm prints a count. A filing dropped because it is about somebody else is
the right outcome, and a silent right outcome is indistinguishable from a
filing dropped because something broke.

### What this does not fix

The wrong records are still on disk: `RIOT|Riot Platforms, Inc.` 4.6,
`HUT|American Bitcoin Holdings LLC | ...` 64.5, `APLD|Applied Digital
Corporation` 96.1, `CIFR|Cipher Digital Inc. | ...` 7.7, and two contaminated
era floors (HUT `2025-09-10` should be `2025-10-23`, RIOT `2025-04-09` should
be `2025-05-12`). `GLXY|Galaxy Group Investments LLC` 49.937 looks like the
same shape and is **not**: the probe did not flag it, so it is a genuine
holder. A name-based rule would have deleted it, and would also have deleted
ABTC's correct 64.5% record, whose lead signatory is "American Bitcoin
Holdings LLC".

`build_snapshot` labels by the same roster loop and publishes
`issuers/RIOT/filings/SCHEDULE 13D count 9` to `snapshot.json`, a public file,
where the true count is zero. It has not adopted this rule yet.
`press_monitor` is **not** exposed: it claims only that a filing exists under a
CIK, and "RIOT filed a SCHEDULE 13D" is true.

**A dry run cannot show this working**, and that is worth stating rather than
implying otherwise. All fifteen misattributed accessions are already in `seen`,
so they are never re-read and no arm fires. The evidence is the probe's census
over live data and the unit checks built from the real filing's structure. The
first observable proof will be either a new cross-filing arriving or the state
repair removing those accessions.

## The floor measures movement since the last PUBLISHED figure

`≥0.5 points` is measured against the last percentage this component actually
posted, not against the last one it read. Until 2026-09-10 it was the latter,
because the stored baseline was written for every parsed filing before the
sub-floor check ran. A holder could then travel any distance in steps under the
floor with nothing posted, and the eventual "down from X%" would cite a figure
the channel was never shown.

`advances_baseline(kind, pct)` gates the write on an event having been produced.
It tests `kind is None` rather than the truthiness of `pct`, because a declared
exit reports `0.0` and must still be recorded.

**Measured over the 22 committed revisions of `holder_state.json`, and it
changes nothing that has already happened.** 153 keys, 14 ever moved, 12
crossed the floor and posted, and 2 were sub-floor rebases: CORZ Christopher R.
Hansen / Valiant Capital 5.1 to 5.3, and NUAI Caracola Ventures 8.6 to 8.9. No
key has two sub-floor steps in a row, which is the only shape that makes the
two rules differ, so replaying both over that record gives 12 posts either way.
It is a correctness change for what has not happened yet.

That replay sees only committed state, so two moves of one key inside a single
run collapse into one transition and a sub-floor pair could hide there. The
claim is about the record, not about the world.

## Eviction from `seen` keeps the newest, not the largest string

`save_state` used to write `sorted(state["seen"])[-2000:]`, which reads as
"keep the newest 2000" and does not. An accession is `TENDIGITS-YY-NNNNNN` and
the leading ten digits identify the **filing agent**, so lexicographic order is
agent-major and date-minor.

Measured on the live list of 348: `sorted()` puts three 2026 accessions first
and a 2025 one fifth, and at a cap of 100 it would **drop 117 filings from 2026
while keeping 3 from 2024**. Nothing about the expression says so.

It now keeps recording order, which is the order `main()` appended them, and
de-duplicates with `dict.fromkeys`. **The duplicate is real rather than
defensive**: `0000950170-25-114068` sits in the file twice, because it is the
Hut 8 filing about American Bitcoin and was read once under each company in the
same run. `state["seen"].remove()` on the failed-post path deletes one copy of
two, so an item could be un-marked and still be seen.

Inert today at 348 of `SEEN_CAP` 2000. That arithmetic is why this was safe to
change now rather than urgent, and the cap is a named constant rather than an
inline literal so the eviction can be tested at all: at the live size the slice
is the identity function and a check written against it would pass under any
implementation.

## A rename must not orphan a company's holders

`holders`, `era` and `read` are keyed by **ticker**, while the first-run record
is keyed by **CIK**. So on the run after a rename the CIK still reads as
established, which is correct, while every stored holder for that company
orphans, which is not. Each holder's next filing then classifies as an ARRIVAL,
and the arrival caveat attaches "first appearance in DRK's structured record,
which begins ..." to it: the line written to catch a false arrival supplies
evidence for one instead.

Six of nineteen roster members have renamed in eighteen months, so this is
routine rather than exotic. `first_run.held_by_cik` already resolved aliases,
for the prune and only for the prune; fixing the lookup there and nowhere else
is what left this open.

`migrate_symbols()` runs inside `load_state()`, **before anything reads**,
because a resolution added at three call sites is a resolution missing from the
fourth. It moves each namespace by what that namespace means:

| Namespace | Key | On collision |
|---|---|---|
| `holders` | `TICKER\|signature` | the current ticker's value wins, and the merge is printed |
| `era` | ticker | the **earlier** date, because it is a floor |
| `read` | ticker | the **later** date, because it is a high-water mark |
| `companies` | CIK | untouched |

**It moves onto tickers, not onto CIKs**, and that is the load-bearing choice
rather than a stylistic one. Re-keying to CIK is tidier and would silently
break `first_run.held_by_cik`, which expects ticker keys and drops anything
else with no error and no log line. `has_state` would quietly shrink and
`prune_unmeasured` would start pruning established companies on a transient
fetch failure, which is the permanent-loss bug recorded above as caught in
review before merge. A check asserts `held_by_cik` returns the same CIKs
before and after.

**An unmappable prefix is left in place and counted, never deleted.** A prefix
resolving to nothing is a company this roster no longer knows, and deleting its
history to tidy up is the silent loss this component cannot afford. The count
is the only warning that a rename landed without its former symbol reaching
`alt_symbols`, which is the one case the migration cannot repair.

Resolution comes from `watchlist.symbol_to_ticker()`, the same map
`ftd_monitor` and `audit_identifiers` use, rather than a private copy. Writing
that map out backwards by hand once attributed GREE to Soluna, merging two
companies under a plausible number with nothing raised anywhere.

Landed 2026-09-10, **before** the rename it is written for: Sphere 3D's
shareholders approved the change to DarkHorse on 2026-08-24 and the ticker has
not flipped yet. ANY holds six keys today, four holders plus one `era` and one
`read`.

## In the weekly digest

A `holders` contributor at cadence `event`, so `weekly_digest.mk()` refuses any
persistence claim about it — a holder position is not a daily measurement and
"filed on three of five sessions" would be meaningless. It reuses the
submissions payload the filings contributor already fetches.

## Known limits

- **Legacy `SC`-spelling filings are not read.** They predate the structured
  schema and carry no parseable holder record. The count per company is printed
  so their absence is a measurement rather than a gap.
- **A cold start posts nothing** — every filing is new when there is no state
  file at all. A dry run still shows them, because it saves no state. This is
  the WHOLE-FILE rule and it is not the one that matters; see *a company added
  to the roster posts nothing* above, which is the case that cost 86 messages
  while this bullet read as though the component were covered.
