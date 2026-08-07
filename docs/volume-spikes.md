[← Watchlist monitor](../README.md)

# Volume spikes

Alerts when a ticker's session volume crosses a multiple of its own 30-day
average, including premarket and after-hours.

## Schedule

`9 7-22 * * 1-5` — **once an hour**, weekdays, 07:00–22:59 UTC. The job then
polls internally on each fifteen-minute boundary until its budget runs out:

- EDT (summer, UTC-4): 3am – 6pm ET
- EST (winter, UTC-5): 2am – 5pm ET

Covers premarket through the close year-round without seasonal edits.

The mechanics, the measured scheduling behaviour behind them and the open
questions are documented once, in
[press-monitor.md → Schedule](press-monitor.md#schedule). This workflow runs the
same shape for the same reasons; only the minute (`:09`, staggered) and the
per-pass timeout differ.

**The window used to open at 10:00 UTC and no longer does.** That start was
inherited from the press monitor, where it is EDGAR's opening time and means
something; here it meant the window opened *inside* the session, six hours after
Alpaca's extended feed does. It now opens at 07:00 UTC — 03:00 ET in EDT, an
hour ahead of the 04:00 ET extended open — so the first fire of the day arrives
before there is anything to measure rather than after.

A fire before 04:00 ET has no bars for the day and simply finds nothing, which
is the correct behaviour for a window that is meant to be ahead of its session.

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

Alpaca's daily bars are only emitted once the regular session opens, so before
9:30 ET there is no daily bar for today and premarket activity is invisible —
exactly the case most worth alerting on. Hourly bars span the full extended
session (4:00–20:00 ET).

The baseline is built from the same hourly bars. Comparing an extended-hours
session total against a regular-hours-only baseline would inflate every ratio.

Bars are grouped by **Eastern date, not UTC**. A 19:00 ET after-hours bar is
the next UTC day in winter; grouping on UTC would split single sessions across
two days and corrupt the baseline.

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
