[← Watchlist monitor](../README.md)

# Investigated and rejected

Ideas that were measured and closed. **Check here before probing something —
the point of this file is to stop a re-probe six months later.**

The numbers are the argument. A verdict without them is just an opinion that
happens to be older than yours, and would rightly be ignored.

The precedent is the ISO power price decision, recorded in
[the watchlist](watchlist.md#why-there-is-no-per-company-power-price) for the
same reason and already worth having.

---

## Analyst ratings

**Would have added:** a rating change from a named bank on a named date, which
is traceable to a source. For small caps a downgrade often moves the stock more
than the quarter does.

**Coverage was better than expected** — seven of fourteen carry nine or more
analysts (WULF 18, HUT 17, CIFR 17, IREN 15, CLSK 13, MARA 11, WYFI 9). Five are
thin at one or two; ANY and BGDE have none. So depth was not what killed it.

**It failed on discrimination.** Of **721 rating actions** across the roster:

| action | count | share |
|---|---|---|
| maintain | 418 | 58% |
| reiterate | 156 | 22% |
| initiate | 106 | 15% |
| **upgrade + downgrade** | **41** | **5.7%** |

**In all of 2026: two upgrades and one downgrade, across fourteen companies.**

Against real events, every one drew attention and none drew a rating change:

| event | actions in −30d…+45d | up/down |
|---|---|---|
| HUT — Anthropic/Fluidstack deal | 8 | **0** |
| WULF — Anthropic lease | 10 | **0** |
| CIFR — rebrand + 49% divestment | 8 | **0** |
| ANY — activist 13D | **0** | 0 |
| SLNH — dilution | **0** | 0 |

The reiterations land one to two days *after* the press monitor already had the
news first-hand. It is a lagging echo of a source this repo already reads.

**Recorded separately, because it is a trap of a shape seen twice elsewhere:**
Yahoo's `recommendationTrend` module carries **no absolute dates at all** —
periods are `0m`, `-1m`, `-2m`. A consensus from 2023 is byte-identical to one
from this morning. The only dated field in the payload is
`upgradeDowngradeHistory`.

**Worth keeping if this returns:** two banks *initiated* coverage on WULF in the
three weeks before its Anthropic lease, and initiations are 106 of the 721
actions. Two cases is an anecdote, not a signal — but it is the only part of the
dataset that looked like it might lead rather than lag.

---

## BTC treasury holdings from XBRL

**Would have added:** treasury liquidation, the other half of the question
`dilution.py` answers. MARA held 52,850 BTC at 2025-09-30 and 35,303 at
2026-03-31 — a third of the treasury sold — and nothing here would show it.

**MARA tags no coin count anywhere in XBRL.** Checked exhaustively: every
non-USD unit it reports across its entire fact set is `Integer`, `Segment`,
`day`, `derivativeInstrument`. Its crypto tags are USD only —
`CryptoAssetCost` and `CryptoAssetFairValue`.

**USD fair value is the wrong quantity.** It conflates the coin count with the
BTC price, so a third of the treasury sold into a rising market can leave it
flat or up. It hides precisely the signal wanted.

**Only five of fourteen tag `CryptoAssetNumberOfUnits`** — CLSK, HUT, WULF,
DGXX, IREN — in **four different unit strings**: `Bitcoin`, `bitcoin`, `Unit`,
`item`. IREN reports 0, because it sells production rather than holding.

**HUT's series is actively corrupt.** The same tag appears under `item` (16,331
at 2026-03-31) *and* under `USD` (15,679,000) — the second is the coin count
multiplied by 1,000 and mislabelled. HUT's 10,171 BTC at end-2024 was never
worth $10,171,000. A consumer taking the USD unit reports a fabricated number
that looks plausible.

**Worth keeping:** `CryptoAssetFairValue` is tagged by **ten of fourteen** and
is current to 2026-03-31. It answers *"how large is the crypto balance sheet"*
cleanly, reusing `dilution.py`'s concept-probing exactly. It simply cannot
answer *"is this company selling"*.

---

## Monthly production reports

**Would have added:** blocks won, BTC produced, energized hashrate, monthly.

**One of fourteen still publishes.** CLSK, monthly and consistently titled
(`CleanSpark Releases June 2026 Operational Update`).

**MARA has stopped.** Its ten most recent releases are earnings calls, notes
repurchases and land acquisitions — no monthly update.

Everyone else stopped earlier: DGXX 2025-10, HUT 2025-03, ANY 2024-11, VIP
2024-10, WULF 2024-10, BGDE 2024-04, CIFR 2023-11, IREN 2022-05. BKKT, NUAI,
SLNH and WYFI never did.

**DGXX's exit is measurable** across its full 197-release history, and it
coincides with the AI/HPC pivot and the wire migration:

```
2026:  0 production releases of 20
2025:  9 of 42
2024: 14 of 26
2023: 11 of 17
2022: 13 of 25
```

**It also fails the same way the analyst work did.** The one survivor, CLSK, is
already among the busiest feeds. The companies that stopped are the ones whose
business changed — the interesting event — and that shows up as an *absence*,
which a production parser cannot report. Noticing a company has gone quiet is
the better instrument, and `check_staleness()` is already that shape.

---

## Contracted capacity from release bodies

**Would have added:** MW and contract value for the HPC leases that are the
sector's current story — HUT's $19.6bn base-term value, WULF's Anthropic lease,
CIFR's Fluidstack arrangement.

**Every figure extracts cleanly with a regex. That is not the problem.** Three
real HUT lease announcements:

| release | MW/GW found | $ found |
|---|---|---|
| Second 352 MW IT lease | 1 GW, 352, 352, 704, 949, 1,330 | 19.6bn, 26.6bn, 1.75bn, 50.2bn |
| First phase 352 MW | 1 GW, 352, 597, 352, 1,000 | 9.8bn, 25.1bn, 16.8bn |
| River Bend 245 MW | 245, 245 | 7.0bn, 7.0bn, 17.7bn |

**The problem is semantic.** Each release carries four to six MW values and
three to four dollar values meaning different things — the new lease, cumulative
phases, campus total, portfolio total; base-term value versus total including
extensions. A parser gets six numbers and no way to know which pair is the
subject of the announcement. Tightening the regex does not help.

**Titles remained open, and are now closed too.** Headlines are written to
disambiguate — *"…with Second 352 MW IT Lease, Bringing Campus-Level Base-Term
Contract Value to $19.6 Billion"* carries term, MW and value. But this was
tested on HUT only, and HUT writes unusually structured headlines. WULF's and
CIFR's were checked, along with six others: see
[contracted capacity from titles](#contracted-capacity-from-release-titles)
below. **Do not read this section as leaving a lead open.**

---

## BTC decoupling — rolling correlation against bitcoin

**Would have added:** a weekly table of each ticker's rolling return
correlation against bitcoin, answering the question the watchlist is built
around — which of these are still bitcoin proxies, and which have repriced as
something else, now that WULF, HUT and CIFR have all pivoted toward AI/HPC.

**It got further than any other rejected idea, and that is why it is here.**
The other four failed on coverage or discrimination before anything was
measured. This one was built, produced a clean finding, and the finding turned
out to be an artefact of the measurement.

### The sources were not the problem

Alpaca's crypto bars need **no authentication at all** — same provider and
clock as the equity bars `daily_recap.py` already fetches, so dates align by
construction. 431 bars, of which 124 fall on weekends and are dropped by an
inner join against the 295 equity trading days. Splits were confirmed rather
than assumed by fetching `adjustment=raw` alongside `adjustment=all`: ANY is
adjusted on 174 of 295 days and BGDE on 121, matching the Feb 2026 and Nov
2025 splits recorded in [crossings.md](crossings.md).

### The finding, and how good it looked

Over the recent 90 trading days, **thirteen of fourteen fell against bitcoin**
— MARA 0.76 to 0.41, CLSK 0.73 to 0.46, SLNH 0.66 to 0.24 — while Nasdaq
correlation held or rose. It read as a sector rotating out of a bitcoin proxy
and into an AI-infrastructure proxy, which is exactly the kind of repricing
this watchlist exists to notice.

### What actually happened

| | prior 90 | recent 90 | ratio |
|---|---|---|---|
| **BTC realised volatility** | **54%** | **34%** | **0.63** |
| **QQQ realised volatility** | **16%** | **25%** | **1.54** |
| roster median | — | — | **1.05** |

Bitcoin went quiet, the Nasdaq got noisy, and the companies did neither.

Correlation is scale-invariant, so bitcoin moving less cannot reduce it
directly. The mechanism runs through `r = beta x sigma_btc / sigma_ticker`,
which makes **beta** — how far the stock moves per 1% of bitcoin — the
discriminating quantity, and yields a falsifiable signature: a pure rescaling
of bitcoin leaves `r` unchanged and raises beta by 1/ratio, or **+58%**.

| | |
|---|---|
| median change in correlation | **−0.20** |
| median RELATIVE change in beta | **+4%** |
| betas that fell | **7 of 14** — a coin flip |
| the `sigma_btc/sigma_ticker` term | **fell for all 14** |

**Beta did not move.** Sensitivity to bitcoin was unchanged at roughly 0.85 to
1.5 across the roster. The entire fall is the sigma-ratio term. The
relationship was intact; bitcoin simply explained less of a variance that had
not itself changed.

### It did not clear noise either

Fisher z across the two independent 90-day halves, critical |dz| = 0.30:

- **4 of 14** real falls against bitcoin (MARA, CLSK, ANY, SLNH)
- **2 of 14** real rises against the Nasdaq — **NUAI and BGDE, the roster's two
  biggest idiosyncratic stories**

So the Nasdaq column read "held", not "rose".

### The Nasdaq half is the same artefact, in mirror image

Decomposing against QQQ as well as against bitcoin — which the original probe
could not do, see below — gives the stronger version of that, and it is a
separate finding rather than a restatement:

| vs QQQ | |
|---|---|
| a pure rescaling would move beta | **−35%** |
| betas that fell | **11 of 14** |
| median RELATIVE change in beta | **−23%** |
| median change in correlation | **+0.09** |
| the `sigma_qqq/sigma_ticker` term | **rose for 13 of 14** |

MARA 0.18 → 0.30, WULF 0.16 → 0.28, BKKT 0.13 → 0.27. The one exception is ANY,
whose own volatility rose 2.36x and so outran even the Nasdaq's.

**Correlation to the Nasdaq rose while sensitivity to it fell 23%**, against a
−35% pure-rescaling prediction. The Nasdaq got noisier, so it explained more of
a variance that had not itself changed — precisely as bitcoin going quieter
made it explain less.

Both halves of "these rotated out of a bitcoin proxy and into an
AI-infrastructure proxy" are the same artefact seen from two sides. Neither
side is a market event.

### The tool found what the probe it was cut from could not

A note about the tool rather than the rejection, but it is why the tool was
kept rather than deleted along with the idea.

The original probe decomposed against **bitcoin only**, because bitcoin was the
question. `check_metric_regime.py` loops the decomposition over every
reference, so it produced the QQQ mirror image above the first time it ran —
evidence that did not exist while the probe it was trimmed from was the thing
being run.

That is the reason the reference list is configurable rather than hardcoded. A
single series cannot separate "the subject moved away from A" from "A went
quiet", and a second reference moving the *other* way is what turns a
suspicion into a two-sided demonstration.

### The confound was in the finding that started it

The result that made the idea look worth building was a 180-day separation
between the groups: **BTC proxies +0.70 against AI/HPC pivots +0.45**. But
`r` is penalised directly by a high `sigma_ticker`, and the pivots are the more
volatile group — WULF 90%, HUT 113%, CIFR 122%, against MARA 82%, CLSK 88%,
BKKT 93%. Comparing betas instead gives **1.21 against 1.03**.

A meaningful part of "the pivots are less bitcoin-correlated" is just "the
pivots are more volatile stocks."

Partial correlations inherited it too, being built from the same numbers:
WULF's independent bitcoin exposure read 0.36 in the prior half and 0.09 in the
recent one. The sharpest-looking result was the one most contaminated.

### Verdict

**A weekly table would have reported a sector-wide decoupling event in a
quarter whose honest answer is "bitcoin was quiet and nothing changed."** The
metric moves for at least two reasons that have nothing to do with the
companies: bitcoin's volatility regime, and each ticker's own volatility.

### If it comes back

Build **beta**, not correlation. Beta is what "still a bitcoin proxy" means and
is confounded by neither. But measure its stability and its intervals first —
its standard error is large when the fit is poor, and WYFI's 1.78 comes with an
`r` of 0.42. Reaching for beta immediately, on the strength of this
investigation alone, would repeat the same mistake in a new variable.

**And state bitcoin's own realised volatility in the post alongside whatever is
reported**, so a reader can tell "the link weakened" from "bitcoin went quiet".
Without it, no reader can.

The decomposition is kept as [`check_metric_regime.py`](../check_metric_regime.py),
because any metric shaped as a ratio of two moving quantities has this failure
mode and the next one should be cheap to check rather than expensive to
discover.

---

## Two findings worth keeping, from the same corpus

**EDGAR and the IR feeds disagree, and the feed is right.** EDGAR full-text
search says CLSK stopped publishing production updates in April 2025; its IR
feed shows a June 2026 update. CleanSpark issues these as press releases without
always furnishing an 8-K. **EDGAR alone would have wrongly concluded CLSK had
stopped too.** Generalises: a company's own feed and its filing history are
different corpora, and neither is a superset of the other.

**Coverage that is thin in the wrong places is worse than none.** Both the
analyst and production investigations failed the same way: the companies that
were well covered were the ones already generating abundant news, and the ones
where a signal would have been most valuable had nothing. Check *where* coverage
falls before counting how much of it there is.

---

## A "no run in N hours" heartbeat

**Would have added:** an alert when a workflow has not run recently.
[`failure-notice.yml`](../.github/workflows/failure-notice.yml) says in its own
header that it catches failures and not absences, and absence is this repo's
more common failure mode. It was deferred there pending a measurable threshold.

**The threshold was measured, and it does not exist.** Not "is hard to choose"
— the healthy and broken distributions overlap, so no number separates them.

### The unit, which is worth keeping regardless

Hours cannot express this. Every weekday-only workflow shows a **72-hour**
maximum gap between successful runs, and that gap is the weekend. A threshold
set above the observed maximum in hours would let a daily job die from Friday
to Wednesday before complaining.

The unit that works is **nominal fire opportunities elapsed since the last
success**, expanded from the workflow's own cron. Weekends contain no fires,
out-of-window hours contain no fires, and a roster spanning hourly to weekly
normalises onto one scale. Window correctness stops being logic to get wrong
and becomes a property of the unit. **Use this unit for anything that reasons
about schedule adherence here.**

### The measurement

Six days, 2026-07-29 16:27 to 2026-08-05 15:59 UTC — 279 runs, which is the
entire run history `gh run list` holds. Elapsed fire opportunities between
consecutive successful scheduled runs:

| Group | Fires | Runs | Distribution | Max |
|---|---|---|---|---|
| 12 daily/weekly workflows, pooled | 60 | 40 | `1:27` | **1** |
| Press release monitor | 69 | 38 | `1:36, 2:19, 3:8, 4:4, 5:1` | **5** |
| Volume spikes | 64 | 26 | `1:24, 2:17, 3:7, 4:2` | **4** |

The daily workflows are pooled because individually they hold 2–5 observations,
which cannot support a threshold; they share a cadence shape and a common drop
process, which is the same pooling `calibrate_staleness.py` used.

Proposed thresholds were max + 2: **7** for the press monitor, **6** for volume
spikes, **3** for the daily group, with a 240-hour absolute cap for the weekly
`earnings.yml`, where three missed fires would mean three weeks.

### Why it was rejected

**The threshold would not have fired on the incident that prompted it.** On
2026-08-05 the press monitor had gone quiet after 12:07. That is **4** elapsed
fire opportunities, against a proposed threshold of **7** and an observed
healthy maximum of **5**. The gap was inside normal range and the heartbeat
would correctly have said nothing.

Lowering N to 4 to catch it means firing on ordinary behaviour: elapsed reached
4 or more **five times in 68 fires** on the press monitor alone, none of them a
fault.

**The cause is structural, not calibration.** GitHub drops 30–45% of scheduled
fires on this repo, so routine gaps and outages are drawn from the same
distribution. No threshold separates them, and one tuned until it looked right
would be a number chosen to look right.

A monitor calibrated to stay silent on the one incident that motivated it is
not worth building.

### Two measurement errors, recorded because both looked like findings

The first pass reported a 45% hit rate for the press monitor and a 15-fire miss
streak for volume spikes. Both were artefacts.

1. **A cron that changed underneath the measurement.** `monitor.yml` went
   `7 10-23` → `7 7-23` and `spikes.yml` `9 10-22` → `9 7-22`, both at
   2026-08-05T14:28Z. Expanding today's cron across the whole week invents
   three morning fires a day that did not exist, and they all read as misses.
2. **A tolerance wider than the interval.** Attributing a success to any
   nominal fire within 3 hours lets ONE run satisfy THREE consecutive hourly
   fires, which inflates hits in the other direction.

Corrected, the press monitor made 38 successes against **69** real fires, not
85. **Any measurement of schedule adherence has to use the cron that was in
force at the time**, and the delay tolerance has to be shorter than the
interval it is applied to.

### The limitation on all of it

**Six days is not a calibration window.** `calibrate_staleness.py` had months
of publication history; this had six days and one live incident inside it. The
daily-group threshold rests on 27 observations, and fires preceding a
workflow's first success in the window had no baseline and were excluded —
several of those were real misses, so the true daily maximum may be 2 or 3
rather than 1. Re-measure before reviving this.

### What replaced it

The question the measurement pointed at is not *has it run* but **has anything
been lost**. An item ageing past `MAX_AGE_DAYS` with no run in between is a
consequence rather than a cadence, and it has no false positives — which is
exactly what the heartbeat could not offer. It is also what actually happened
on 2026-08-05: APLD's 10-K aged out unseen and seven press items were left to
be marked seen and silently dropped, and a heartbeat would have said nothing
about either, correctly, by its own thresholds.

---

## Contracted capacity from release TITLES

The lead left open by
[contracted capacity from release bodies](#contracted-capacity-from-release-bodies)
above, measured 2026-08-05 across the whole roster rather than HUT alone.

**Would have added:** MW and contract value for the HPC leases, taken from the
headline instead of the body, on the theory that headlines are written to
disambiguate what a body leaves ambiguous.

### Two corpora, and they must not be pooled

Pooling them is what makes this look workable.

| corpus | what it is | size |
|---|---|---|
| **headline only** | the twelve RSS `<title>` values plus HUT's scraped page titles — *exactly* what `press_monitor.py` holds today | **134 titles, 13 sources** |
| **headline + subhead** | first block of each 8-K/6-K EX-99 exhibit since 2024-06-01, for HUT WULF CIFR GLXY APLD BTDR IREN | **217 blocks** |

The second corpus exists because six companies have no feed, and it reaches
further back than a ten-item window. It is **not** what the monitor sees, and
the gap between the two is the finding.

### The headline-only result

18 of the 134 are capacity or contract announcements. Financing releases are
excluded — they carry a dollar figure for a different reason.

| headline carries | count | share |
|---|---|---|
| any MW/GW | 6/18 | 33% |
| any `$` | 5/18 | 28% |
| a term in years | 3/18 | 17% |
| **both MW and `$`** | **3/18** | **17%** |
| term + MW + `$` | 2/18 | 11% |

**All three of the MW+`$` headlines are HUT.** Every one:

```
Hut 8 Signs 15-Year, 245 MW AI Data Center Lease at River Bend Campus
  with Total Contract Value of $7.0 Billion
Hut 8 Commercializes First Phase of 1 GW Beacon Point AI Data Center Campus
  with 15-Year, 352 MW IT Lease with Base-Term Contract Value of $9.8 Billion
Hut 8 Fully Commercializes 1 GW Beacon Point AI Data Center Campus with Second
  352 MW IT Lease, Bringing Campus-Level Base-Term Contract Value to $19.6 Billion
```

Nine companies have at least one capacity headline and **none** with MW+`$`:
ANY, BGDE (3), BKKT, CLSK, IREN (4), NUAI, SLNH, WULF, WYFI.

The hypothesis was that HUT writes unusually structured headlines. **It is not
unusual, it is unique**, and n=3 is one company's house style rather than a
sector convention. A component built on it covers one company and reports
silence for eighteen.

### The decisive case

WULF's Anthropic lease — the sector's second-largest of the year:

```
RSS title : TeraWulf Announces Anthropic Lease at Justified Data Campus and Sale
            of Majority Interest in Abernathy Joint Venture to Fluidstack
exhibit   : ...to Fluidstack | Long-Term AI Infrastructure Lease Expected to
            Generate ~$19 Billion of Contracted Revenue Over Init[ial term]
```

**The title the monitor sees contains no digit at all.** The figure is in the
subhead, and RSS discards subheads.

Matched-pair test on the same releases seen both ways: **7 matched, 5 where the
exhibit carries figures the feed title does not.** The matched set is small
because feed windows are shallow, but the direction is not in doubt and this
case alone settles it.

### And the subhead reintroduces the ambiguity that killed the bodies

Of the 20 capacity blocks carrying an MW value, **5 — 25% — carry two or more
distinct MW values**; 7 of 33 carry two or more distinct dollar values.

| block | MW values in one block |
|---|---|
| WULF 2025-08-18 | 160 (this lease) / 360 (cumulative) |
| APLD 2025-08-29 | 150 (this lease) / 400 (campus total) |
| CIFR 2025-11-20 | 56 (this lease) / 39 (delivery tranche) |
| **HUT 2026-07-20** | **352 / 704 / 1000** |

**Even HUT's best headline carries three.** The body rejection above said a
parser gets six numbers and no way to know which pair is the subject.
Descending to the subhead does not escape that — it inherits a smaller version
of it.

### One case that is its own argument

On **2025-12-17** HUT published both of these, same day, same transaction:

```
Hut 8 Signs 15-Year, 245 MW AI Data Center Lease at River Bend Campus with
  Total Contract Value of $7.0 Billion
Hut 8 Announces AI Infrastructure Partnership with Anthropic and Fluidstack
```

One fully specified, one carrying nothing. A headline parser posts the first and
is silent on who the counterparty is.

### Verdict

**Titles are not prose — a third of them carry a figure — and it still dies.**
No company but HUT pairs MW with a dollar value in a headline; the
disambiguating figure lives in the subhead the feed throws away; and the subhead
carries the multiple-MW problem forward. Both halves of this idea are now
closed.

---

## Debt and convertible maturities

**Would have added:** when each company's obligations come due — the maturity
wall behind the $4.25B, $3.2B, $2.35B and $2.0B senior secured notes issued
across this roster in the last year, and the converts several carry.

**The expectation going in was that this was the most tractable of three
probes. It was wrong, and the reason generalises: the structured route has the
worse data.**

### Route A — XBRL. Enumerated, not guessed.

`companyfacts` was pulled for all 19 and filtered, rather than probing a
hand-written list of concept names: **1,335 debt-related concept/unit series**
across the roster.

**That choice is the method note worth keeping.** Probing a guessed concept name
and getting a 404 is indistinguishable from the concept not existing — the same
trap `dilution.py` and [short interest](short-interest.md#schema-discovery)
already work around. Enumerating first turns "does this exist" into a lookup.

`LongTermDebtMaturitiesRepaymentsOfPrincipal*` is tagged by **8 of 19**: CIFR,
HUT, MARA, NUAI, SLNH, SPCX, VIP, WULF.

**Ten tag nothing** — ABTC, ANY, APLD, BGDE, BKKT, CLSK, DGXX, GLXY, IREN,
WYFI — including four of the largest issuers of the past year. BTDR is an
eleventh by a different route: it files IFRS and has no `us-gaap` facts at all,
not even `Assets`.

#### The buckets do not reconcile

Sum of the buckets at the newest period, against that period's balance-sheet
debt:

| | sum of buckets | balance-sheet debt | ratio |
|---|---|---|---|
| **HUT** | $7,735,104,000 | $7,735,104,000 | **1.00x** |
| SLNH | $28.7M | $25.9M | 1.11x |
| **CIFR** | $2.39B | $5.45B | **0.44x** |
| **SPCX** | $13.2B | $38.3B | **0.35x** |
| **MARA** | $831M | $2.42B | **0.34x** |

**HUT is the only coherent one.** CIFR and SPCX tag no `InYearFive` and no
`AfterYearFive` at all, so the long-dated tail — **56% and 65% of their debt** —
is simply absent from the schedule. A maturity wall built from this reports
CIFR's near-term obligations and silently omits the majority of what it owes,
which is the [absence-is-a-measurement](../CLAUDE.md) rule violated by the
source rather than by the component.

#### Per-instrument detail is unreachable, and that was checked rather than assumed

`DebtInstrumentMaturityDate` returns 404 for all seven companies tested. **A 404
is not a finding**, so it was checked against HUT's raw 10-Q XBRL instance
(`hut-20260630x10q_htm.xml`, 3.8MB): **0 occurrences.** Filers genuinely do not
tag it.

What *is* in that instance and still invisible to the API:

| concept | facts in instance | dimensional | served by `companyfacts` |
|---|---|---|---|
| `DebtInstrumentInterestRateStatedPercentage` | 20 | **20** | no |
| `DebtInstrumentTerm` | 2 | **2** | no |
| `DebtInstrumentFaceAmount` | 4 | **4** | no |
| `DebtInstrumentCarryingAmount` | 13 | 12 | the one plain value only |
| `LongTermDebtMaturities…InYearTwo` | 1 | 0 | yes |

Everything per-instrument is qualified by `DebtInstrumentAxis`, and
`companyconcept`/`companyfacts` serve **only undimensioned facts**. "The $4.25B
notes mature 30 November 2042" is in the filing and cannot be reached this way;
it needs raw instance parsing, which is a different and much larger machine than
`dilution.py`.

### The second currency-test catch

The currency test built for GLXY's share count on the same day caught this
immediately, on a different concept and a different company.

**WULF's newest maturity bucket period is 2024-06-30 — 639 days behind its own
latest balance sheet.** The stale schedule sums to **$75.9M**. WULF's
`LongTermDebt` at 2026-03-31 is **$3.10B**, after $3.2B of senior secured notes
and $1.025B of converts in October 2025 alone.

**A component taking each concept's newest value publishes a $75.9M maturity
wall for a company carrying $3.10B — 41x wrong, correctly parsed, correctly
attributed, and reading as entirely valid.** NUAI is 365 days behind by the same
test.

That is now two independent concepts where the first hit was not the current
one. Treat it as the default expectation for any XBRL series, not as a GLXY
quirk.

### The Frankenstein schedule — the one a future implementer will walk into

**Taking each concept's newest value is the obvious implementation, and it is
the shape `dilution.py` invites**, because a single series has one newest
observation and a schedule has seven.

MARA's `InYearFive` and `AfterYearFive` were last tagged at **2025-12-31** while
its other buckets are **2026-03-31**. Newest-per-concept gives:

```
831M (2026-03-31 buckets) + 1.0B + 2.25B (2025-12-31 buckets)
  = $4.08B   against $2.42B of actual debt
```

**Two filings stitched into one schedule, no error anywhere, no log line, and a
number 69% too high.** The buckets must be read at a **single `end` date**, and
a bucket absent at that date must be distinguished from a bucket not re-tagged
— see the method note below.

### Route B — 8-K item 2.03. Better than expected, and the wrong shape.

**46** 8-Ks carrying item 2.03 since 2024-06-01 across nine companies:

```
APLD 11 · HUT 7 · WULF 7 · CIFR 7 · MARA 4 · IREN 4 · CLSK 3 · GLXY 3 · BTDR 0
```

Sampled 30 bodies: **25 — 83% — state a maturity date or year**, and **20 give
an exact date**: `will mature on November 30, 2042`, `June 15, 2031`,
`May 1, 2032`. Far more legible than the XBRL that was expected to win.

**It is the better EVENT signal and the worse STATE signal**, and the
distinction is the whole verdict:

1. **It is a creation ledger.** Repayments and repurchases never arrive as a
   2.03. **MARA repurchased $1.0B of its 0.00% converts due 2030 and 2031 on
   2026-03-26**; a 2.03-only ledger would still be carrying them today.
2. **BTDR scores 0 because a 6-K has no item codes.** Foreign private issuers
   are invisible to this route entirely — the same class the earnings calendar
   reaches only through its 20-F/6-K fallback.
3. **The accompanying press release is not a substitute.** Of 55 financing
   announcements in the exhibit corpus, **5 — 9% — state a maturity year.**

### Verdict

**Rejected as "maturity structure". A narrower thing is buildable and should be
recognised as narrower**: a near-term wall for the six companies whose schedule
is current, read at one `end` date, with a footer naming the ten that tag
nothing *and the share of debt each shown schedule omits*. The omission is the
number, not a caveat on it. WULF must be withheld by the currency test rather
than displayed.

Item 2.03 belongs in the press monitor as "obligation created, matures 2042" —
an event, which is what it is — and not in a schedule, which is what it is not.

---

## Lock-up expirations

**Would have added:** the date on which restricted shares become sellable — for
SPCX, which IPO'd 2026-06-12, and for the other recent listings.

**The interesting part is that extraction WORKS and the component still fails.**
Every other rejection here died on coverage, discrimination or a confounded
metric. This one dies on the terms themselves being real, stated, and not
generalisable.

### Coverage

| | filing | `lock-up` mentions | period stated |
|---|---|---|---|
| **SPCX** | 424B4 2026-06-12 | **104** | a dated table — see below |
| **WYFI** | 424B4 2025-08-08 | 3 | plain **180 days after the date of this prospectus** |
| **ABTC** | S-4/A 2025-07-29 | **1** | none — the single hit sits inside a fairness-opinion disclaimer |
| **GLXY** | 424B3 2026-05-21 | **0** | none |

WYFI is the derivable case and its expiry has passed: 2025-08-08 + 180 =
**2026-02-04**. ABTC's reverse merger states no lock-up at all, which is an
**absence rather than a parsing failure** — the two must not share a label.
**Four of five companies state nothing usable.**

### SPCX, where the terms are fully stated and the derivation still fails

The prospectus is dated 11 June 2026 and carries an **explicit dated release
table**. Extraction is not the obstacle.

**Calendar-dated** — Aug 20 (70th day, 319.0M) · Sep 9 (90th, 319.0M) · Sep 10
(91st, 59.1M affiliates) · Sep 24 (105th, 328.4M) · Oct 9 (120th, 328.4M) ·
Oct 24 (135th, 328.4M) · **Dec 8 (180th, 328.4M or 797.6M)** · Mar 18 2027
(280th, 176.0M) · May 17 2027 (340th)

**Contingent** — second trading day after the First Earnings Release Date,
**911.5M** · a further **455.8M** if the close is at least 30% above the IPO
price for 5 of the 10 trading days ending on that date · second day after Q3'26
results, **1.3 billion (28%)** · after Q4'26 results, 351.9M · after Q1'27
results, 351.9M

Plus Musk on a **366-day** lock-up and an "extended lock-up period" running to
Q2 2027 results — together **~7.8B shares, over 63% of pre-IPO shares
outstanding**.

### What the cheap derivation would have said

180 days from 11 June 2026 is **8 December**, so the arithmetic lands **one day**
from the stated 180-day date. **The answer is still wrong three ways:**

- the **first release is 20 August 2026**, 110 days earlier
- the largest single tranche, **1.3 billion shares**, is contingent on the Q3
  earnings date and is **reachable by no arithmetic**
- **63% of the shares are on a 366-day or earnings-anchored clock**, so the
  180-day date is not even the principal event

**A generic parser would report the wrong date and the wrong quantity while
appearing to work** — the failure mode this repo treats as the serious one.

### Verdict

**Rejected.** There is no consistent standard term to derive from: 180 / 366 /
earnings-anchored / price-contingent, four of five companies silent, and the one
richly specified case bespoke enough that generalising from it produces
confident wrong answers.

### Live at time of writing, and recorded because nothing here will show it

SPCX's **First Earnings Release Date has already passed** — the prospectus
defines it as the release of results for the quarter ended 30 June 2026, and
SPCX filed an 8-K carrying item **2.02 on 2026-08-04**. The second full trading
day following is **2026-08-06**, on which up to **911.5 million shares** become
transferable, plus a further **455.8 million** if the 30% price condition was
met.

No component in this repo shows it, and none is being built to. Recorded so the
date is on paper rather than in one session's memory.

---

## Method notes from the three probes above

Kept rather than discarded with the ideas, because each is a way of getting a
measurement wrong that looked right first.

**Enumerate the schema; do not probe a guessed name.** Pulling `companyfacts`
and filtering gave 1,335 debt series and a definitive coverage count. Probing a
hand-written concept list would have produced a set of 404s, and **a miss on a
guessed concept name is indistinguishable from an absence.** This is the one
that generalises past these three probes — it applies to any XBRL question this
repo asks.

**An under-specified corpus is the wrong error when the question is whether
something is specified.** The first headline extractor cut at the first line
break, truncating `TeraWulf Signs 200+ MW, 10-Year AI Hosting Agreements with
Fluidstack` to its first half. Uncaught, it would have made headlines look
*less* specified than they are and produced the right verdict from wrong
numbers. Fixed before anything was counted.

**"Not re-tagged" and "zero, and therefore omitted" are different measurements.**
The stale-bucket check written for probe 2 cannot tell them apart. HUT trips it
on two buckets and is entirely fine — its five remaining buckets sum to its
carrying amount exactly. Read that flag as a prompt to look, never as a verdict.
It is the same distinction the roster already draws between a young listing and
a failed source.

---

## Filing rate as a "company has gone quiet" signal

**Would have added:** a per-company alert when its EDGAR filing rate falls
against its own history — the general form of the question the monthly
production probe raised, which was whether a company that stops reporting can
be detected at all.

**DGXX sits at the 51st percentile.**

The company whose going-quiet motivated the entire question — production
reporting stopped in autumn 2025 — falls at the **exact median of ordinary
variation**. Its filing rate went from 5.1 a month to 4.7. Measured over
2,266 company-months of null distribution, that is the middle of the pack.

Three other events, dated from `watchlist.md` rather than from the probe:

| | month | before | after | log | percentile |
|---|---|---|---|---|---|
| ABTC reverse merger | 2025-09 | 4.7 | 3.0 | −0.39 | 24% |
| BGDE rename + wire migration | 2026-04 | 4.0 | 2.7 | −0.35 | 25% |
| **DGXX production reporting stops** | 2025-10 | 5.1 | 4.7 | −0.08 | **51%** |
| NUAI rename | 2025-08 | 3.9 | 6.0 | +0.39 | 82% |

**Zero of four below the null's 5th percentile.** Median event at the 38th.
HUT's 2023 reorganisation and VIP's rename have insufficient history either
side to test.

### Why this is final rather than a calibration problem

**What went quiet was press releases. A press release only reaches EDGAR if it
is 8-K-worthy, and a monthly production update is not.** The thing that
stopped was never in the filing rate to begin with.

That is a statement about the instrument, not the threshold. **A longer
window, a different statistic or a tuned threshold cannot recover a signal
that is not in the data** — which forecloses the obvious next attempt, and is
the reason this entry is a closure rather than a deferral.

### The base rate is why the null is so wide

```
month-on-month log change, company-filed only (2,756 months)
  p05 -1.61   p25 -0.51   p50 +0.00   p75 +0.51   p95 +1.61
```

**One ordinary month in five is at least a halving.** The mean is **2.14
company filings per month**, so the series is dominated by counting noise: 1,
2 and 4 in consecutive months is an unremarkable sequence that reads as a 75%
fall followed by a quadrupling.

### Calendar was checked and ruled out

The first thing anyone would reach for, so it is recorded as measured rather
than assumed.

```
01:1.6  02:1.9  03:2.6  04:2.4  05:2.9  06:1.8
07:1.6  08:2.7  09:1.9  10:2.0  11:2.5  12:1.8
```

Quarterly reporting is visible at **1.78x peak to trough**, against a **5x**
ordinary monthly swing. Deseasonalising would not have rescued it.

### Verdict

**EDGAR filing counts cannot answer this question, and no amount of tuning
changes that.**

**The question itself is not closed — only this instrument.** A company going
quiet is a real thing to want to know, and `press_monitor.check_staleness()`
already watches the IR feed at `max(6 × median, 60 days)` calibrated per
source. That is where the signal actually is: the press releases that stopped
are in the feed and never reached EDGAR.

### If a sector-wide shift is ever the worry

The thing to reach for is a **roster-level reading of the staleness check** —
several sources going stale at once. That uses a signal which already exists
and already fires per source, and is a far smaller change than a component.
The 2025 production-reporting shift would have shown as exactly that.

## A note on the same corpus: half of it is not the company

Not about this idea, and needed by anyone measuring anything per-company over
EDGAR.

**A company's submissions index is mostly filings made BY OTHERS about it** —
Schedule 13D/G by holders, Forms 3/4/5 by insiders, Form 144 by sellers.
Across 11,092 filings on this roster, **5,946 are the company's own — 54%**.

Per company it runs from **CIFR at 32%** to **DGXX and SPCX at 84%**. A
measure built over the raw index would, for CIFR, be two-thirds a reading of
its shareholders' behaviour rather than its own.

It did not change the outcome above — 21% of ordinary months halve on
company-only against 23% on everything — and it was measured both ways for
that reason. It would have changed a component built without noticing.

## SEDAR+ as a ninth source, for disclosure that never reaches EDGAR

Probed 2026-08-08. **Rejected.** Every SEC-backed component keys off
data.sec.gov, and four companies have a non-US home jurisdiction — BTDR, IREN,
DGXX, GLXY. A 20-F is a summary and a 6-K is furnished rather than filed, so a
company whose primary record sits with a home regulator would reach EDGAR only
in abstract.

### The gap needs two conditions at once, and this roster has never had both

That is the durable finding, and the one to check first if this is re-opened.

1. **The company is on the FPI regime** — furnishing 6-Ks rather than filing
   8-Ks, annual report a 20-F rather than a 10-K.
2. **It has a home regulator holding a record EDGAR does not.**

| | condition 1 | condition 2 |
|---|---|---|
| **BTDR** | **yes** — 100 6-Ks, 5 20-Fs, zero domestic forms | **no** — Nasdaq-only, Cayman incorporation, Singapore HQ |
| **DGXX** | no — last 6-K 2025-12-29 | yes — still a Canadian reporting issuer, Cboe Canada |
| **IREN** | no — last 6-K 2025-06-30 | moot |
| **GLXY** | **never** — zero 6-Ks and zero 20-Fs, ever | moot |

**The one company still furnishing has no second regulator to furnish from,
and the one company with a second regulator left the regime seven months
ago.** Neither condition alone is a gap.

This sits first because it is **structural rather than circumstantial**. The
access findings below could change — a bot manager can be reconfigured, an API
can appear. The condition either recurs or it does not, and it recurs only if a
roster company takes a second listing in a jurisdiction with its own
continuous-disclosure regime while remaining an FPI. `filer_regime.py` checks
the mechanical half on demand.

**GLXY should never have been a suspect**, which is a method point rather than
a detail. Its Cayman history is real and it never produced a single FPI filing
on EDGAR. Reading incorporation put it on the list; a census of what each
company actually files would not have.

### The named unknown dissolves rather than resolves

**The sharpest result, and the one most likely to be re-attempted**, because it
was the strongest single argument for the source.

DGXX's material change reports say a press release went out through *"an
approved Canadian newswire service"* without naming it, and the standing
assumption was that SEDAR+ would identify which. **It would not.**

That phrase is **Item 3 of the material change report itself** — and 20 of
DGXX's 25 most recent 6-Ks furnish that report, the actual Form 51-102F3, as
Exhibit 99.1. The 2025-12-29 filing, verbatim:

> Exhibit 99.1 FORM 51-102F3 MATERIAL CHANGE REPORT Item 1 Name and Address of
> Company Digi Power X Inc. … Item 3 News Release The press release attached
> as Schedule "A" was released on December 24, 2025 through an approved
> Canadian newswire service.

SEDAR+ holds the same prescribed document — the same file, filed to two
regulators. **The vagueness is inside the document, not in which copy you
read.** The question is unanswerable by that source in principle rather than
merely unmeasured, which is a stronger closure than a measurement would give.

BTDR is the control at **0 of 25** — its exhibits are press releases, which is
what a company with no continuous-disclosure regulator has to furnish.

### The transition did not lose it either

DGXX moved to 8-Ks on 2026-01-06 and is **still** a Canadian reporting issuer,
so it still files material change reports at home. A 6-K furnishes whatever the
issuer published; an 8-K reports enumerated items on a US template — so the
changeover could plausibly have closed the FPI gap and opened a document gap in
the same week. It was checked for that reason, not because anything suggested
it had.

| DGXX | period | MCR present |
|---|---|---|
| 6-K era | 2025-09-04 → 2025-12-29 | **12 of 15** |
| 8-K era | 2026-02-23 → 2026-08-04 | **11 of 15** |

Unchanged within noise. DGXX still attaches the report, now under Item 7.01
with a 9.01 exhibit list. IREN as the control is 0 of 8 either side —
Australian, no material change report to lose — which is what says the measure
detects the document rather than firing on anything long enough.

**So "the repo has been reading the abstract all along" is specifically
excluded, in both regimes, for the only company it could have applied to.**

### The 20-F is not a summary — a corrected premise, not a supporting point

Counted over the vocabulary an Item 2 Properties section cannot avoid, same
measure both sides:

| | form | chars | MW figures | hashrate | site/facility | **named grid** |
|---|---|---|---|---|---|---|
| **BTDR** | 20-F | **1,041,504** | **36** | **19** | 141 | **0** |
| MARA | 10-K | 419,979 | 24 | 6 | 135 | **0** |
| CLSK | 10-K | 570,790 | 15 | 8 | 235 | **0** |
| CIFR | 10-K | 485,042 | 28 | 0 | 470 | 30 |

**BTDR's 20-F is twice the length of the peer 10-Ks and carries more capacity
and hashrate figures than any of them.** Whatever a 20-F is, on this roster it
is not the shorter document.

The only structural difference found is the heading — a 20-F uses Item 4.D
where a 10-K uses Item 2 — which is different signposting over the same
material. This corrected the stated reason for BTDR's `OPEN` grid tag in
[`watchlist.md`](watchlist.md); the tag itself was right.

### SEDAR+ as a source — independently sufficient, and a category not a cost

Three findings, in increasing order of how decisive they are:

1. **No official API.** The CSA publishes none. Commercial access is via
   FactSet or LSEG — paid redistribution, not the source.
2. **It was in a planned maintenance window during the probe**, serving a
   static bilingual "temporarily unavailable" page. One observation; recorded
   because it happened, not weighted as a reliability measurement.
3. **It is behind Radware Bot Manager.** A non-browser request to
   `sedarplus.ca` is 302'd to `validate.perfdrive.com` with a bot-validation
   challenge.

**The third ends it, and it is a different category of work rather than a
larger amount of it.** The four existing scrapers read sites that were merely
awkward — a soft-404, an unsorted CMS, a rebuilt sitemap. This one is
adversarial by design: the work is specifically evading bot detection, it
breaks silently whenever they change anything, and there is no version of it
that fails loudly. **Declining to attempt it is the position, not a
limitation** — the challenge was not attempted and nothing should be built to
it.

### Verdict

**Do not add SEDAR+.** No unique disclosure was found; the one company it could
serve has its primary Canadian document on EDGAR verbatim in both regimes; the
named unknown it was expected to resolve is unanswerable by it; and access
would mean defeating a commercial anti-bot system. Any one of those is
sufficient.

**What is not closed** is the two-condition test, which is why
`filer_regime.py` was kept rather than deleted with the rest of the probe. A
company added to the roster, or one taking a second listing, can make the two
conditions hold together for the first time. The census makes that a
one-command check instead of a probe.

---

## A first-run guard for newly added IR feeds

**Would have added:** the first-run rule over `watchlist.ir_feeds()`, so that
adding a feed suppresses its backlog the way adding a company or a form type
now does. It was proposed as the last set in the repo protected only by
`MAX_AGE_DAYS`, which [`press-monitor.md`](press-monitor.md) itself calls
incidental rather than designed — the same wording used about Form 144, which
did need the guard.

**The event had already happened and was never measured.** Commit `20a42ac`,
2026-08-08, added IR feeds for **APLD, BTDR and SPCX**, all three already on
the roster for months. That is exactly the case: a new capability on a company
already being watched. The first scheduled run afterwards, 2026-08-10 08:44
UTC, reports it in its own log:

```
313 items seen, 60 new, 0 new insider.
55 item(s) older than 7d — recorded, not posted.
5 candidate(s) checked, 5 to post.
Posted 4 press item(s).
```

| | |
|---|---|
| items the three new feeds served | 27 — APLD 10, BTDR 10, SPCX 7 |
| new items that run, feeds and EDGAR together | 60 |
| dropped by the age floor | **55** |
| posted | **4**, and not all four came from the new feeds |

So the measured cost of adding three feeds is at most four posts, or roughly
one per feed. The guard would have prevented about one post.

### Why this axis is not the other two

The count is not the argument on its own — `crossings` and `dilution` carry the
rule for one unearned post each. **What separates this case is whether the
company was being watched at all.**

| Adding | Watched before? | What the unguarded first run posts |
|---|---|---|
| a **company** | no | every item on record — 86 messages on 2026-08-14 |
| a **form type** to `holder_events` | yes, but no age floor | every filing matching the new prefix |
| a **feed** to a watched company | **yes, through EDGAR** | only items from the last 7 days |

A three-day-old press release from a company already on the roster is not
backfill. It is current news that the component just gained a second view of,
and letting it through is the job `MAX_AGE_DAYS` was given. A new company's
backlog is items that should never have been seen; a new feed's recent items
are items that were wanted and could not yet be seen. Suppressing the second
because it resembles the first would trade a real post for a theoretical one.

### Verdict

**Do not guard `ir_feeds`.** The age floor already bounds it to seven days,
and inside that window the items are legitimate. This is deliberately left as
the one tracked set with no first-run namespace, and the reason is in
`MAX_AGE_DAYS`' own comment so nobody has to find this file first.

**What is not closed**, and would reopen it: a feed source that serves items
whose timestamps do not parse. `entry_time` returns `0` for those, which reads
as 1970, so the floor drops them and `main()` has already marked them seen —
they are lost rather than posted, which is a different failure and is tracked
in [press-monitor.md](press-monitor.md). Measured 0 of 223 items across all
twenty IR sources on 2026-08-13, so it is not currently occurring.

This idea was proposed three times in one day on 2026-08-17 before anybody
looked at what the 2026-08-08 addition had actually cost. **That is the reason
this file exists.**

---

## A median-based half-width for the published spread

**Would have changed:** the uncertainty figure both components print beside a
projected report date. Today that is `floor(range/2)`. The proposal was
`medhw = max(lag - min, max - lag)`, the smallest symmetric interval around
the published lag that contains every observed lag. The motivating argument
was strong and correct as far as it went: the published lag is a MEDIAN, so a
half-width should be measured from the median, and `range/2` is a half-width
around the MIDRANGE. Measured on the roster with the period-end guard on,
**18 of 21 published intervals do not contain a lag they were computed from.**

**It failed on the only comparison that discriminates.** Every candidate is
symmetric about the same centre, and `(lag - min) + (max - lag) = range`
forces `medhw >= ceil(range/2) >= floor(range/2)` POINTWISE. The intervals
nest, so the miss sets nest, so a wider rule cannot score worse on any
population at any `k`. Ranking by raw coverage reports the width ordering back
in coverage units. The 75.7% against 87.9% headline was a theorem, not a
measurement.

Held at equal width, over 371 real next-filing events at k=8
([`probe_lag_coverage.py`](../probe_lag_coverage.py)):

| mean width | `range/2` scaled | `medhw` scaled |
|---|---|---|
| 5.0d | **60.6%** | 57.1% |
| 10.0d | **80.1%** | 76.8% |
| 15.0d | **90.0%** | 87.9% |
| 20.0d | **94.1%** | 92.5% |

And a flat additive constant beats it outright at every `k` tested, on both
axes at once:

| k | `floor+2` | `medhw` |
|---|---|---|
| 4 | **80.8%** at 8.40d | 78.5% at 9.74d |
| 6 | **87.2%** at 10.38d | 85.3% at 12.92d |
| 8 | **89.5%** at 11.65d | 87.9% at 14.96d |
| 12 | **91.7%** at 13.33d | 91.0% at 17.99d |

**Why additive wins is the part worth keeping.** The failures are concentrated
in the metronomic filers, not the erratic ones:

| published | cases | misses | miss rate | share of all misses |
|---|---|---|---|---|
| `±0d` | 23 | 11 | **48%** | 12% |
| `±1-2d` | 85 | 29 | 34% | 32% |
| `±3-5d` | 86 | 25 | 29% | 28% |
| `±6-10d` | 91 | 13 | 14% | 14% |
| `±11+d` | 86 | 12 | 14% | 13% |

**44% of all misses come from rows publishing `±0d` to `±2d`**, and a
multiplicative rule cannot fix a published zero. `medhw` barely helps there
either: SLNH's `[44,45,45,45,45,45,45,45]` goes from 0 to 1.

`medhw` also manufactures bounds nothing supports. WYFI's
`[43, 44, 44, 79]` would publish a window opening **9 days after quarter end**,
fifteen days below the roster's all-time quarterly minimum of 24.

**MAD was measured and is much worse than either**: 42.6% at k=8, because it
publishes `±1d` for a company whose lags run 34 to 45.

**What is NOT closed, and is the real finding.** The column has never had a
stated coverage target, which is why this argument could run at all: with no
criterion, every candidate is defensible by redefining the goal. Set one and
the rule falls out arithmetically, with no estimator debate needed:

| target | rule | mean width |
|---|---|---|
| 75.7% | `floor(range/2)`, today | 9.65d |
| 83.8% | `floor+1` | 10.65d |
| 89.5% | `floor+2` | 11.65d |

That is a decision about what `±` promises a reader, not a measurement, and it
is open.

**Four population caveats**, recorded because the percentages read more precise
than they are: coverage is measured in LAG space while the published centre is
weekend-rolled; k=8 covers fourteen of twenty-one live rows, since `cadence`
truncates at `min(8, available)`; the annual arm contains NEITHER 20-F filer it
would govern, because BTDR and IREN hold five annual filings each against the
nine k=8 needs; and the corpus is EDGAR's `recent` arrays while
`build_snapshot` reads full history. None of the four touches the width-matched
ordering, which is internal to one population.
