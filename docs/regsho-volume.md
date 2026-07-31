[← Watchlist monitor](../README.md)

# Short sale volume

Posts each ticker's daily short sale volume as a share of its reported volume,
against its own trailing average.

## Schedule

`0 23 * * 1-5` — daily on weekdays, posting only when the trade date is newer
than the one in `regsho_state.json`. FINRA publishes with about a one-day lag
and the release time varies, so deduping on trade date is more reliable than
guessing the publication window.

## Critical: this is not short interest

**Short interest is a position. Short volume is a flow.**

| | [Short interest](short-interest.md) | This |
|---|---|---|
| Measures | Shares held short | Shares sold short during a session |
| Frequency | Twice monthly | Daily |
| Lag | ~2 weeks | ~1 day |
| Persistence | Open positions | Mostly closed same day |

A large share of daily short volume is **market-maker hedging**. When you buy,
the market maker sells to you and books it as a short, then flattens the
position. Ratios of 40–60% are ordinary for a liquid stock and say nothing
about sentiment.

This is probably the most misread number in retail market data, and the design
exists to prevent that misreading:

- The table shows each ticker's ratio **beside its own trailing average**, not
  in isolation.
- Rows sort by **absolute deviation** from that average.
- The caveat appears in the embed description on every post.

An absolute 60% is meaningless. 60% against a 40% average might not be.

## Output

```
      Short   Avg     Vol
--------------------------
SLNH    33%   47%-  11.9M
ANY     58%   48%  342.1K
MARA    60%   65%   22.5M
BKKT    61%   61%  343.8K
```

| Column | Meaning |
|---|---|
| `Short` | Short volume ÷ total reported volume, this session |
| `Avg` | Same ratio averaged over the prior `BASELINE_DAYS` (20) sessions |
| `Vol` | Total reported volume — see the caveat below |

The marker after `Avg` shows direction: `+` above average, `-` below, blank
within `NOTABLE_DELTA_POINTS` (12 points).

**Falls are flagged as well as rises.** A sharp drop in the ratio after a
run-up can mean shorts have stopped pressing, which is information. Flagging
only rises would hide half the signal — SLNH's 14-point fall was the largest
deviation on the first live day and would otherwise have gone unmarked.

## Vol is off-exchange only

`Vol` is FINRA-reported volume — trades through the TRFs and the ADF — **not
consolidated volume**. It is a subset.

On 2026-07-30 IREN showed 27.2M here against roughly 46M consolidated in the
[recap](recap.md), about 59%, which is a normal off-exchange share.

Do not reconcile this column against the recap's. They measure different
things, and the footer says so on every post.

## Market-centre aggregation

FINRA reports **separately per reporting facility** — the ADF and each TRF — so
a single symbol-day arrives as several rows that must be summed.

Treating one row as the day's total would understate volume badly and distort
every ratio. `parse()` accumulates into `{ticker: {date: [short, total]}}` for
this reason. The test covers a symbol split across three centres.

## Aliases

Shared with [short interest](short-interest.md#aliases) and for the same
reason: FINRA files by the symbol in force on the trade date, so a rename
splits history.

```python
ALIASES = {
    "VIP": ["GREE"],   # renamed from Greenidge, 2026-07-24
    "ANY": ["DRK"],    # pending change to DarkHorse Technologies
}
```

Add on a rename rather than editing `TICKERS`. Both files must be kept in sync.

## Guards

| Constant | Purpose |
|---|---|
| `MIN_TOTAL_VOLUME` (25,000) | Below this a ratio is noise. BGDE sits just above it on a normal day and will drop out on quiet ones. |
| `STALE_WARN_DAYS` (10) | This dataset publishes daily; a much older newest date means the wrong dataset. Exits rather than posting stale figures as current. |
| `BASELINE_DAYS` (20) | Sessions in the trailing average. Tickers with fewer than half that are noted in the log as a thin baseline. |

## Schema discovery

Field names differ between FINRA datasets. `SYMBOL_FIELDS`, `DATE_FIELDS`,
`SHORT_FIELDS`, `EXEMPT_FIELDS` and `TOTAL_FIELDS` are each probed in order,
and if the symbol column matches none the script prints the dataset's real
schema from `/metadata`.

This dataset matched on the first attempt, unlike
`consolidatedShortInterest` — see the
[dataset selection notes](short-interest.md#critical-dataset-selection) for why
that machinery exists.

## Known quirks

- **Short exempt is included.** `shortExemptParQuantity` is added to
  `shortParQuantity`. It is normally a rounding error, but it belongs in the
  numerator.
- **Authentication is not required**, same as short interest.
