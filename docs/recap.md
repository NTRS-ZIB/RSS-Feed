[← Watchlist monitor](../README.md)

# Daily market recap

Posts a post-close performance table and a chart grid for the same watchlist.

## Schedule

`30 21 * * 1-5` — 21:30 UTC, weekdays. That lands after the US close in both
DST states (5:30pm ET in summer, 4:30pm in winter), so no seasonal edits.

## Output

A monospace table sorted by daily move, plus a PNG grid of intraday charts.

```
      Close    Chg  Vol 52w
--------------------------
IREN  37.18  26.9% 2.4x* 88
CLSK  14.40  19.9% 1.6x* 52
MARA  11.86  18.0% 1.2x  37
```

| Column | Meaning |
|---|---|
| `Close` | Last close |
| `Chg` | % change vs previous close |
| `Vol` | Multiple of the trailing 30-day average volume. A trailing `*` marks unusual volume — see below. |
| `52w` | Position in the 52-week range, 0 = low, 100 = high |

Absolute share counts are **not** in the grid — there is no room at mobile
width, and the ratio is what you act on. The raw figure appears in the footer
for flagged tickers only, where it is worth reading.

The header states the **actual date of the last bar** rather than assuming it
is today. Tickers with no data are named, and tickers whose latest bar is older
than the rest are flagged as `lagging`.

If the newest bar is today's and the US close hasn't happened, the header reads
`INTRADAY` instead of `Close`. Providers return the current, incomplete session
as a normal-looking bar; the tell is `x30d` collapsing across every ticker at
once, because partial volume is being compared to full-day averages.

The header also always names the data source (`via Alpaca sip`), so a silent
fallback to a lagging provider is impossible.

## The chart

A grid of **intraday** charts, two per row, one per ticker: today's regular
session in 5-minute bars, 09:30–16:00 ET.

- A dashed line marks the **previous close**, and the shaded fill sits between
  the line and that reference — so the shaded area reads directly as the day's
  gain or loss.
- The y-range always includes the previous close, so an opening gap is visible
  rather than being scaled off-screen.
- Colour comes from the **day's** move, the same figure shown in each panel's
  title.

That last point was a real bug in the first version. The chart plotted 60 days
of closes and coloured by the 60-day direction, while the title showed the
*one-day* change — so a stock up 27% on the day but below where it sat two
months earlier rendered as a red line labelled `+27.0%`. Charting the day
resolves it: one timeframe, one number, one colour.

`CHART_MODE = "daily"` restores the 60-day view; both paths stay live, and the
caption states which one you are looking at. `CHART_EXTENDED = True` widens the
window to 04:00–20:00 ET.

Note the boundary differs from the volume alerts on purpose: **alerts count
extended hours, the chart does not.** A ticker can trigger a premarket alert
whose bars never appear on that evening's chart.

Intraday needs Alpaca. On the fallback provider there is no usable intraday
data, so panels revert to the 60-day series and the caption says so.

### Image shape is deliberate

Discord caps the **height** of an embedded image, so a tall portrait image is
displayed *narrower* — the height limit binds before the width one. The first
two-column version was 884×1481 (aspect 1.68) and rendered as a thin column on
mobile. Reshaping the panels to 4.2×1.55 inches gives 1092×1209 (aspect 1.11),
which fills the available width.

`MAX_ASPECT` (1.15) enforces this. Adding tickers means more rows, which would
push the image tall again and reintroduce the problem; the cap squeezes panel
height instead. At 20 tickers it still renders 1092×1255.

## End-of-day volume flagging

Tickers closing above `VOLUME_FLAG_TIER` (1.5x) of their 30-day average get a
`*` on the `Vol` column and a summary line beneath the table. A quiet day
prints `No unusual volume.` rather than nothing, so you can tell the check ran.

Two guards:

- **Suppressed entirely on a partial session.** `flagged()` returns nothing
  when the header says `INTRADAY`. Incomplete volume against a full-day average
  understates every ratio, so flagging mid-session would be actively wrong.
- **`MIN_FLAG_VOLUME` (50,000 consolidated shares).** BGDE can show 3.1x on
  30,800 shares; that is noise, not a signal.

### Relationship to [`volume_spike.py`](volume-spikes.md)

Both use a 1.5x first threshold, deliberately, but they are not redundant:

| | Intraday alerter | This |
|---|---|---|
| Feed | IEX (free tier) | SIP (consolidated) |
| Absolute volume | A few percent of real | Accurate |
| Timing | During the session | After the close |
| Role | Early proxy | Authoritative confirmation |

That makes the pairing a useful cross-check. If a ticker fires intraday on IEX
but is *not* flagged at the close on SIP, the IEX proxy overstated it for that
name — its IEX market share is unstable. Repeated occurrences for the same
ticker make it a candidate for exclusion from the intraday alerts.

## Testing

Actions → Daily market recap → Run workflow. The **dry run** checkbox is ticked
by default: it fetches, prints the table to the log, and uploads the chart as a
downloadable artifact, but posts nothing. Untick to post for real.

Scheduled runs pass no input, which reads as empty and therefore false, so the
cron always posts.

## Data sources — and why

**Primary: Alpaca, `feed=sip`.** Consolidated all-exchange data. One request
covers every ticker, so the recap runs in seconds with no daily quota.

Two non-obvious details:

- `delayed_sip` is a **streaming / latest-quote** feed name. The historical
  bars endpoint rejects it with `HTTP 400 invalid feed: delayed_sip`. Bars use
  `sip`.
- Free plans are restricted on **recency**, not on the feed. Requests are sent
  with `end` set 20 minutes in the past (`ALPACA_DELAY_MINUTES`) to stay
  outside the real-time window. The recap runs ~90 minutes after the close, so
  this costs nothing.

**Not Alpaca `feed=iex` here**, even though the spike alerts use it. IEX sits
out the closing auction, so its last print is not the official close, and its
volume is a few percent of consolidated. Fine for ratios, wrong for the
absolute closes, volumes and 52-week ranges this table displays.

**Fallback: Twelve Data — with a documented accuracy problem.** Its free tier
lags intraday badly. Measured on 2026-07-30, same session, same tickers:

| | Twelve Data | Alpaca sip | ratio |
|---|---|---|---|
| IREN | 7.6M | 46.0M | 6.1x |
| MARA | 4.0M | 27.8M | 7.0x |
| CLSK | 5.2M | 19.7M | 3.8x |
| BKKT | 71.6K | 417.2K | 5.8x |

Every ticker understated by 3.1x–7.0x (median 5.8x) — systematic lag, not a
glitch. It also drove `x30d` to a nonsensical 0.1x across the whole watchlist.

The fallback is retained because a labelled, stale-but-directional recap beats
no recap during an Alpaca outage. **The posted header always names the source**
(`via Alpaca sip`) so a silent fallback is impossible, and the log prints an
explicit warning when Twelve Data is used.

**Not Yahoo / yfinance.** Yahoo deprecated its API and discourages scraping.

**Not Stooq**, despite being keyless. It enforces a low **per-IP daily quota**
and returns the plain text `Exceeded the daily hits limit` with **HTTP 200**,
not an error status. GitHub runners share an Azure IP pool, so the quota is
routinely spent by unrelated jobs before this one starts. The symptom is every
ticker failing identically.

The general lesson: keyless does not mean usable from CI, and a provider that
returns *plausible* numbers is more dangerous than one that fails outright.

## Known quirks

- **History is patchy for recent listings.** Bars are requested over a 430-day
  window — calendar days, not trading sessions — and recently listed tickers
  may only have a few months. The `52w` column is only as good as the history
  behind it; WYFI, NUAI and BGDE are the thin ones.
- **Split adjustment.** Requests use `adjustment=all`, so splits and dividends
  are accounted for. If a chart still shows an implausible cliff, check which
  source produced it — adjustment handling differs between providers.
- **Provider risk.** Unlike EDGAR and the IR feeds, this depends on commercial
  free tiers that can change. The fetch layer is isolated in
  `fetch_alpaca_all()` and `fetch_twelvedata()`, so a provider can be swapped
  without touching the table or chart code.
