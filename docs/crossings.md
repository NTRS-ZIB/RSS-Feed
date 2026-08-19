[← Watchlist monitor](../README.md)

# 52-week crossings

Alerts when a ticker closes beyond its own 52-week extreme. Silent otherwise,
which is most days.

## Schedule

`45 21 * * 1-5` — 21:45 UTC weekdays, after the US close in both DST states and
fifteen minutes after the [recap](recap.md). It uses daily closing bars, so
there is nothing to gain from running intraday, and Alpaca's free tier
restricts recency in any case.

## Critical: hysteresis is the whole design

A naive rule — "close above the prior 252-day high" — fires **every session**
while a stock grinds in one direction. Several of these do.

Measured over 297 sessions of real bars before this was built:

| | Naive | With hysteresis |
|---|---|---|
| Alerts across 11 tickers | **253** | **55** |
| IREN | 38 highs | 3 |
| ANY | 32 lows | 2 |

78% quieter, or roughly one alert a week across the whole watchlist. Alerting
daily on the same move is not a signal, it is a stock ticker.

So an alert **arms** only once the price has returned inside
`REARM_LOW`–`REARM_HIGH` (25–75%) of its range. A ticker that breaks out, keeps
running, and never comes back alerts once. One that breaks out, retraces
through the middle, and breaks out again alerts twice — which is correct, since
those are two events.

`crossings_state.json` holds the armed flag per ticker per direction.

### A newly watched ticker starts disarmed, in one direction only

A company added to the roster while already sitting above its 52-week high
would fire on its first run under the default flags. **It crossed nothing
while we were watching** — the crossing predates the watch, so announcing it
asserts an event that did not happen. Since 2026-08-14 a ticker seen for the
first time is created disarmed in whichever direction it is currently
crossing, and the re-arm above restores it the moment the price comes back
through the middle of the range.

**Disarming BOTH directions is worse than the bug it fixes**, and the first
version of this did exactly that. Re-arming needs `REARM_LOW <= pos <=
REARM_HIGH`, so a company added at 85% of its range — crossing nothing,
suppressing nothing, printing nothing — would have `armed_hi` false and no way
to recover it until the price fell back to 75%. A genuine breakout the next
day, observed start to finish, would be dropped in silence. Caught in review
before it merged.

Unlike `holder_events`, the cost here was never a flood: this component posts
crossings, not history, so an unguarded first run is worth **one** unearned
post. It has the rule anyway, because a guard that lives in some components
and not others is how the 86-message incident happened — see
[holder-events.md](holder-events.md#critical-a-company-added-to-the-roster-posts-nothing).

There is no capability axis here. Nothing in this component is a configurable
set of things it collects; the window and the band are thresholds, not a
roster of form types.

### A ticker this run did not measure is not established

The rotation of the same bug, found 2026-08-18 and dated: `baseline_by_cik`
recorded every roster company on the backfill run whether or not this
component had assessed it. SPCX was recorded on 2026-08-14 while sitting at
**46 of MIN_BARS=60 sessions**, so on the run it cleared the floor
`state.setdefault` would have created it ARMED — `initial_flags` disarms only
a ticker in `newly_watched`, and SPCX was no longer in it. It would have
announced a 52-week crossing that predates the watch, which is the single
assertion this component must never make.

**Pruned only when the component holds NO state for it**, and that second
condition is the whole safety of the rule rather than a belt on it. The first
version pruned on "not measured this run" alone, which un-established a
company on a transient failure — and because a suppressed item is already in
`seen`, or already overwritten by `record()`, the next run then lost a real
event permanently, under a log line reading "not a loss". Caught in review
before merge. A company with per-company state has been measured before and is
established whatever this particular run managed.

`measured_tickers()` is the roster minus the young and the unusable, and
`first_run.prune_unmeasured` deletes anything else from the record before it
is saved. Deleting rather than withholding is what repairs the run already on
disk, without hand-editing an output file.

Nothing starves. The suppression is only REACHABLE through `setdefault`, so a
ticker that never clears the floor is never suppressed — there is nothing to
suppress. It carries no record until the day it is measured, and on that day
exactly one crossing direction is disarmed.

## What a crossing is, and what it is worth here

A **closing** price beyond the extreme of the prior 252 sessions. Not an
intraday touch. The window excludes today, or the close would be compared
against itself and nothing could ever cross.

Worth calibrating expectations against what these companies actually do.
Single-session moves inside the measured window, none at a split date:

| | Move |
|---|---|
| ANY | +112% |
| SLNH | +94% |
| NUAI | +84% |
| BGDE | +61% |

A 52-week high here is a lower bar than for an ordinary equity. The hysteresis
is what keeps the alert meaningful rather than the threshold.

## Output

```
       Close      Mgn  Ago
--------------------------
IREN   38.42 H +92.1% 251
BKKT    7.05 L -21.7%  43
WYFI   26.10 H +30.5%  99~
```

| Column | Meaning |
|---|---|
| `Close` | Closing price that triggered the alert |
| `H`/`L` | Direction — above the high, or below the low |
| `Mgn` | How far beyond the prior extreme |
| `Ago` | Sessions since that prior extreme was set |
| `~` | Fewer than 252 sessions of history — window shorter than 52 weeks |

**`Ago` is the column that adds meaning.** Breaking a high set 251 sessions ago
is a different event from breaking one set last week; the margin alone does not
distinguish them.

Embed colour: green for highs only, red for lows only, grey when both occur.

## Data

Alpaca daily bars, `feed=sip`, `adjustment=all`, over a 430-day window — the
same request `daily_recap.py` makes, and `WINDOW` matches its `closes[-252:]`
so the two cannot disagree about what "52 weeks" means.

Split adjustment was verified rather than assumed: a scan for single-day moves
above 60% found four, and **none of them at a known split date**. ANY split in
Feb 2026, BGDE in Nov 2025, both inside the window, and neither produced a
discontinuity. Adjustment is working; those four were real moves.

History depth was also measured. Every ticker returned 297 bars except WYFI at
247 — a 2025 listing, five short of the window, so its range covers about 49
weeks and it carries the `~` marker.

## A partial fetch does not block the post

If a ticker has no usable bars it is named and the run continues.

This is **deliberately different** from [dilution](dilution.md#a-partial-fetch-is-not-a-partial-post)
and [comment letters](comment-letters.md#a-partial-fetch-is-not-a-partial-post),
which refuse to post at all. Those assert something about every company on the
watchlist, so a silent omission inverts a row's meaning. This one asserts only
"these tickers crossed", which stays true whatever is missing. The missing names
are listed in the embed regardless.

## Relationship to the recap

The [recap](recap.md) shows `52w` as position in the range, every weekday, in a
table that always appears. This fires only on the boundary, to a different
channel.

They share the fetch parameters but not the fetch — this makes its own request
rather than importing from the recap, so a failure in one cannot take down the
other. That costs one Alpaca call a day.

## Known quirks

- **Silence is the normal output.** The log names every ticker with its
  position in range on every run, so a quiet day is still distinguishable from
  a broken one.
- **A crossing is not a breakout.** No volume confirmation, no trend filter.
  Cross-reference with [volume spikes](volume-spikes.md) if that matters.
- **Dilution is not adjusted for.** `adjustment=all` handles splits, not share
  issuance. A company diluting heavily can make new lows on the share count
  alone — see [shares outstanding](dilution.md), where SLNH shows 13x growth
  in a year.
- **`MIN_BARS` (60) skips a ticker outright** rather than comparing it against
  a few weeks of history. A recent listing is silent until it has enough.
