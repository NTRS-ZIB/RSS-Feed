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

**Titles remain open.** Headlines are written to disambiguate — *"…with Second
352 MW IT Lease, Bringing Campus-Level Base-Term Contract Value to $19.6
Billion"* carries term, MW and value. But this was tested on HUT only, and HUT
writes unusually structured headlines. Before building, check WULF's and CIFR's.

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
