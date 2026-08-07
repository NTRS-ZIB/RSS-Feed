[← Watchlist monitor](../README.md)

# Volume spikes

Alerts when a ticker's session volume crosses a multiple of its own 30-day
average, over the IEX trading day — which is 09:00–15:59 ET, not the extended
session. See the schedule section.

## Schedule

`9 12-22 * * 1-5` — **once an hour**, weekdays, 12:00–22:59 UTC. The job then
polls internally on each fifteen-minute boundary until its budget runs out:

- EDT (summer, UTC-4): 8am – 6pm ET
- EST (winter, UTC-5): 7am – 5pm ET

Covers the IEX trading day year-round without seasonal edits.

The mechanics, the measured scheduling behaviour behind them and the open
questions are documented once, in
[press-monitor.md → Schedule](press-monitor.md#schedule). This workflow runs the
same shape for the same reasons; only the minute (`:09`, staggered) and the
per-pass timeout differ.

**The window has moved twice, and the second move corrected the first.**

It opened at 10:00 UTC originally, inherited from the press monitor where that
is EDGAR's opening time. It was moved to 07:00 UTC to sit an hour ahead of the
04:00 ET extended open — and that reasoning was wrong, because **the extended
open does not exist on the feed this component uses.**

Measured 2026-08-07 over 30 sessions, six liquid tickers:

| feed | bars seen | volume before 09:00 ET | after 16:00 |
|---|---|---|---|
| **IEX** | 08:00–16:59 ET, and 08:00 on 1–9 sessions of 23 | **0.02%** | **0.00%** |
| SIP | 04:00–19:59 ET, 23 of 23 sessions at every hour | 1.71% | 7.38% |

**The trades exist; IEX was not part of them.** IEX does not operate before
08:00 ET. It is the venue rather than the request or Alpaca's serving — the
request carries no `end`, no window boundary and no extended-hours parameter.

So a 07:00 UTC start spent its **first five fires of every day, six in EST**,
on an empty feed. It now opens at 12:00 UTC, which is 08:00 EDT and 07:00 EST
— the first IEX bar year-round, with at most one wasted winter fire.

**The effective IEX day is 09:00–15:59 ET, seven hours.** Everything this
component measures happens inside it.

## Alert tiers

`1.5x`, `3x`, `5x`, `10x` of the 30-day average. A ticker alerts **once per
tier per day**, so something running hot escalates as it climbs rather than
spamming every 15 minutes or going quiet after the first alert.
`spike_state.json` records the highest tier reached per ticker and resets on a
new Eastern date.

## Why IEX data is valid here but not in the recap

The free tier serves the IEX feed only. IEX is a single exchange, a few percent
of consolidated US volume, so the **share counts are a fraction of real
volume**. The embed says so explicitly.

That's acceptable because the alert is a **ratio**: today's IEX volume against
the same ticker's 30-day IEX average. The exchange-share factor appears in both
numerator and denominator and cancels.

**This only holds if both sides come from the same feed.** Never compare an IEX
session volume against a consolidated average — the ratio becomes meaningless
and would fire constantly. [The recap](recap.md) uses `sip` precisely because it displays absolute
figures, where IEX would be wrong.

## Why hourly bars, not daily bars

Hourly bars give **intraday granularity**: a daily bar is one number at the
close, and this component has to answer "how much has traded so far" at every
fire.

**Not for premarket.** That was the original reason given and it was wrong on
this feed — see the schedule section above. The claim and the IEX restriction
were introduced in the same commit, so it was never true here rather than
surviving a feed change.

The baseline is built from the same hourly bars, so both sides of the ratio
cover the same hours whatever those hours turn out to be. That property is what
survived the premarket finding intact.

Bars are grouped by **Eastern date, not UTC**, so a session is never split
across two days. The original example for this was a 19:00 ET after-hours bar
falling on the next UTC day in winter — which does not occur on IEX, since it
carries nothing after 16:59. The grouping is still right; a 15:00 ET bar is
20:00 UTC in EST and the boundary still has to be Eastern.

## Liquidity floors

Two separate guards, both necessary:

| Constant | Purpose |
|---|---|
| `MIN_BASELINE_VOLUME` (10,000) | Below this the average is statistically meaningless. BGDE averages ~1,400 IEX shares/day; one ordinary block would be a 3x "spike". Excluded tickers are named in the log with their baseline. |
| `MIN_ALERT_VOLUME` (25,000) | A spike must also represent real activity. 3x of 300 shares is still 300 shares. |

At time of writing BGDE and ANY are excluded by the first floor.

## Known quirks

- **The threshold meant different things through the day, and now mostly does
  not.** It compared session volume to a *full-day* average with no intraday
  curve, so 1.5x at 09:45 was extraordinary while 1.5x at 15:55 was a busy day.

  **From 10:00 ET the ratio is session-normalised** — elapsed volume against
  the same elapsed fraction of the trailing thirty sessions rather than
  against their totals. Measured over 60 sessions against the built code, that
  reaches **152 tiers** the old measure never does and catches **129** a
  median of **four hours** earlier, across **17 of 19** tickers.

  It costs nothing to fetch. `hourly_bars()` has always requested the intraday
  profile and `daily_totals()` has always discarded it, so this is a change to
  how data already in hand is aggregated.

  **Before 10:00 ET the old denominator still applies**, and so it does
  wherever a slot's baseline is thinner than `MIN_BASELINE_BARS`. The footer
  names which was used.

  | read at | elapsed of the 09:00–16:00 IEX day | basis |
  |---|---|---|
  | before 09:00 | **no data — IEX has not opened** | — |
  | 09:45 | 10% | full-session, understates |
  | 12:00 | 42% | normalised |
  | 15:55 | 98% | normalised |
  | after 16:00 | complete | normalised |

  The 09:45 row is the only one that still understates, and it is one hour in
  seven rather than the whole morning the old 04:00–20:00 framing implied.

- **Pagination.** `MAX_PAGES` guards the bar fetch. If it is ever hit with data
  still pending, the log warns explicitly — a truncated baseline understates
  the average and overstates every ratio, which otherwise looks like normal
  output. Observed requirement is 8 pages; the cap is 40.
- **Thresholds are untested against a real event.** Tune after observing a
  genuine earnings or news day rather than in advance.

## Running it outside its window

**A run after the close is the most complete reading of the day, not a
degraded one.** It matters after a missed evening, so it is written down.

`today` is an **Eastern** date and the IEX day ends at 15:59, so any run from
16:00 onward sums a complete session against complete baselines — and from
10:00 the two sides are normalised to the same elapsed fraction, which at the
close is all of it. The footer says `the complete 09:00-16:00 IEX day`.

So after an outage, **dispatch it rather than writing the day off.**

The one thing it cannot recover is a *tier crossed and receded*. State resets
on a new Eastern date and records only the highest tier reached, so a ticker
that touched 3x at noon and fell back to 1.8x by the close alerts at 1.8x on a
single late run, where the hourly schedule would have caught the 3x. Late is
the most accurate reading of the session; it is not a substitute for having
watched it.

## The gate, and why it is not just a floor

Ungated, normalising from 09:00 raises **149 alerts** the old measure does not,
led by **BKKT at 16.8x on 35,588 shares** — over `MIN_ALERT_VOLUME`, and not a
spike. The 09:00 denominator is one venue's opening sixty minutes.

With the gate, 09:00 raises **none**, and the cost is 47 of the 152 tiers.

`MIN_NORMALISED_VOLUME` (46,880) is a **second, independent** guard, derived
rather than chosen: the 10th percentile of volume behind 298 full-session
alerts, so a normalised alert never rests on less than an ordinary one.

**It is not a substitute for the gate**, and the measurement says so — alone it
blocks only 12 of those 149. The gate stops the hour; the floor stops the thin
ones anywhere.
