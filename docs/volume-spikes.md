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

- **The threshold means different things through the day.** It compares session
  volume to a *full-day* average with no intraday curve, so 1.5x at 9:45am is
  extraordinary while 1.5x at 3:55pm is merely a busy day. This is deliberate —
  it needs no volume-curve model and cannot produce false positives from
  comparing a partial day against a full one. The cost is late detection: a
  stock at 1.1x by midday is running at roughly double pace but won't alert.
  Dividing by the fraction of session elapsed would fix this, at the cost of
  wild extrapolation in the first few minutes.

  **The post now says where in the session it was taken**, because for a long
  time this was documented here and nowhere the reader could see it. The footer
  carries the Eastern clock and the elapsed fraction:

  ```
  Alpaca IEX feed · read 15:55 ET, 74% through the 04:00-20:00 session,
  against full-session averages
  ```

  It sits in the footer rather than the table because the monospace block is
  held to 28 characters and prose is not. Every other component in this repo
  states its own latency; this one stated its feed and not its position in the
  session, which is the same omission wearing different clothes.

- **Pagination.** `MAX_PAGES` guards the bar fetch. If it is ever hit with data
  still pending, the log warns explicitly — a truncated baseline understates
  the average and overstates every ratio, which otherwise looks like normal
  output. Observed requirement is 8 pages; the cap is 40.
- **Thresholds are untested against a real event.** Tune after observing a
  genuine earnings or news day rather than in advance.

## Running it outside its window

**A run after the session closes is the most complete reading of the day, not
a degraded one.** This inverts the obvious intuition and matters after a missed
evening, so it is written down rather than rediscovered.

`today` is an **Eastern** date and the extended session runs to 20:00 ET. A run
at 19:18 ET therefore sums a session that is roughly 95% complete and compares
it against thirty complete baselines. Every *scheduled* fire compares a partial
session against full ones and understates the ratio; a late one understates it
least.

| run at | session elapsed | the ratio is |
|---|---|---|
| 07:09 ET | 19% | understated ~5x |
| 09:45 ET | 35% | understated ~3x |
| 15:55 ET | 74% | understated ~1.3x |
| 19:18 ET | 95% | very nearly true |

So after an outage or a dropped evening, **dispatch it rather than writing the
day off.** It is barely late in its own terms either: the last scheduled fire
is 22:09 UTC, and at the measured 51–71 minute drift that normally lands
23:00–23:20 UTC anyway.

The one thing it cannot recover is a *tier* that was crossed and receded. State
resets on a new Eastern date and records only the highest tier reached, so a
ticker that touched 3x at noon and fell back to 1.8x by the close alerts at 1.8x
on a single late run, where the hourly schedule would have caught the 3x. Late
is the most accurate reading of the session; it is not a substitute for having
watched it.
