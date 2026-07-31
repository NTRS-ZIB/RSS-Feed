[← Watchlist monitor](../README.md)

# Grid and fuel context

The cost side of mining margin. [Bitcoin context](btc-context.md) covers
revenue — hashprice, difficulty, network hashrate. Nothing covered cost until
this.

Stateless, like the bitcoin context: it posts every weekday whatever the
numbers say.

## Schedule

`20 21 * * 1-5` — 21:20 UTC weekdays, five minutes after the bitcoin context.
The two are the revenue and cost halves of the same question and read best
together.

## Critical: this is not a power price

It was meant to be. **EIA's open API has no wholesale electricity prices for
any region.** `electricity/wholesale/prices` returns 404 — the hub prices in
EIA's own Electricity Monthly Update come from S&P Global under licence and are
not redistributed.

Both alternatives were measured before this was written:

| Series | Frequency | Staleness when checked | Verdict |
|---|---|---|---|
| Retail industrial price, by state | Monthly | **91 days** | Rejected |
| Henry Hub spot | Daily | **4 days** | Used |

Texas industrial retail read **6.26, 6.33, 6.33 c/kWh** across three months.
That is genuinely what these companies pay, and it is almost perfectly flat and
a quarter out of date. Posting it would be reporting a constant.

Henry Hub over the same check: **$2.92 → $2.87 → $2.63** inside a week. Gas is
the marginal fuel setting power prices in both ERCOT and PJM, so it moves when
their cost of power moves.

**So this reports a fuel proxy and a curtailment proxy, not a power bill.** The
caveat is on every post.

### EIA is not the ceiling

**The ISOs publish their own prices, and their APIs are free.** This component
uses EIA because it needs one key and covers both regions from one source, not
because wholesale prices are unobtainable.

| Source | Carries | Access |
|---|---|---|
| PJM Data Miner 2 | Day-ahead and real-time hourly LMPs, split into energy, congestion and marginal-loss components, filterable by transmission zone | Free API key, non-members included |
| ERCOT public API | Settlement point prices | Registration required; not verified here |

Two things make that a bigger job than it sounds, which is why it is recorded
rather than done:

1. **A separate key and API shape per ISO.** No single source covers both.
2. **Which pricing node?** An LMP is location-specific, and this repo records
   no facility locations for any company — see the caveat above. Picking a zone
   would mean choosing on a company's behalf without evidence.

If a real cost signal matters more than a proxy, that is the direction. It
needs facility locations from the filings first.

## Why grid demand

These companies are switchable load. When a grid is stressed they are paid to
stop mining, and that payment is a real revenue line — for some of them a
material one.

Demand approaching a recent peak is when that happens. So the signal is the
**day-ahead forecast peak against the trailing actual peak**, not the absolute
megawatts, which are large and meaningless without a reference.

## Critical: forecast is not actual

The RTO route carries four types:

| Type | Meaning |
|---|---|
| `D` | Demand — actual |
| `DF` | Day-ahead demand forecast |
| `NG` | Net generation |
| `TI` | Total interchange |

**Sorting by newest period returns `DF` first**, because forecasts extend into
the future. A probe run before this component was written asked for the newest
rows without filtering and got day-ahead forecasts for both ERCOT and PJM,
looking exactly like current demand.

Anything that failed to filter on `type` would report a prediction as a
measurement and never say so. Both are used here, both are filtered explicitly,
and the table labels which is which.

## Regions

| Code | Grid | Why |
|---|---|---|
| `ERCO` | ERCOT | Covers NUAI (Midland, **Texas**) and most of the sector's Texas capacity |
| `PJM` | PJM | Covers BGDE (Midland, **Pennsylvania**); where the data-centre demand story is loudest |

Note the coincidence, because it is genuinely confusing: two watchlist
companies are headquartered in a town called Midland, in different states, on
different grids.

**This is not a complete mapping.** Facility locations come from filings and
have not been audited — `docs/watchlist.md` records no grid or site data at
all. These are the two regions most likely to matter, not coverage of the
watchlist. Treating the table as "the grids our companies are on" would be
wrong.

## Output

```
        Fcst  7d pk
------------------------
ERCOT   84.2   79.4 +6%*
PJM    151.3  148.9  +2%
```

| Column | Meaning |
|---|---|
| `Fcst` | Day-ahead forecast peak, GW |
| `7d pk` | Highest **actual** demand of the last 7 days, GW |
| `+n%` | Forecast against that trailing peak |

`*` marks a forecast at or above `NOTABLE_PEAK_PCT` (5%) over the trailing
peak, which also gets a prose line and turns the embed amber.

Henry Hub appears as a prose line with week-on-week and 45-day changes.

## Known quirks

- **Stateless and unconditional.** It posts every weekday, like the bitcoin
  context, because the numbers are always meaningful. It is not an exception
  report.
- **Degrades independently.** If the grid route fails the gas line still
  posts, and the reverse. Only a total failure produces no post — every
  endpoint failing at once is an outage or a bad key, not a quiet day.
- **Hours are UTC.** The route offers `local-hourly` as well; this uses
  `hourly` so both regions are on one clock and the comparison holds.
- **Gas is national, grids are regional.** Henry Hub is the US benchmark, not
  a delivered price in Texas or Pennsylvania. Basis differentials between hubs
  can be large, especially in winter.
- **Needs `EIA_API_KEY`.** The only component requiring a key no other one
  uses. Free and instant at
  <https://www.eia.gov/opendata/register.php>.
