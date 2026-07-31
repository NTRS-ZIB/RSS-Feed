[← Watchlist monitor](../README.md)

# Volume spikes

Alerts when a ticker's session volume crosses a multiple of its own 30-day
average, including premarket and after-hours.

## Schedule

`*/15 11-22 * * 1-5` — every 15 minutes, weekdays, 11:00–22:59 UTC:

- EDT (summer, UTC-4): 7am – 6pm ET
- EST (winter, UTC-5): 6am – 5pm ET

Covers premarket through the close year-round without seasonal edits.

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
- **Pagination.** `MAX_PAGES` guards the bar fetch. If it is ever hit with data
  still pending, the log warns explicitly — a truncated baseline understates
  the average and overstates every ratio, which otherwise looks like normal
  output. Observed requirement is 8 pages; the cap is 40.
- **Thresholds are untested against a real event.** Tune after observing a
  genuine earnings or news day rather than in advance.
