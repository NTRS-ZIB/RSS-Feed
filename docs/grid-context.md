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

### The cost framing has one exception

This component is framed throughout as pressure on cost, and for thirteen of
the fourteen companies **swept** that is right — the roster is 19, and GLXY,
APLD, BTDR, SPCX and ABTC have not been read for sites or operators. **VIP is on the other side of it.** It
owns and operates a 106 MW generation facility connected to NYISO and sells
into the market, so a rising power price is revenue for VIP and cost for
everybody else.

The component still reports grid conditions rather than per-company economics,
and a hot grid is a hot grid whichever side of it you sit on. But NYISO is now
a row someone reads every weekday, so the exception is stated in the embed
beside the table rather than only here — a caveat at the foot of a page is not
where a reader meets the number. Anything built later that turns a price into a
per-company cost has VIP backwards in sign. See
[the watchlist's grid section](watchlist.md#grid-operators-and-sites).

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
2. **Which pricing node?** An LMP is location-specific, and picking a zone means
   choosing on a company's behalf. `docs/watchlist.md` now carries the states
   and operators each filing names, but four of fourteen rows are inferred from
   keyword frequency, two companies sit outside any RTO entirely, and five of
   the nineteen have no row at all.

If a real cost signal matters more than a proxy, that is the direction — but
read [why the plan was closed](watchlist.md#why-there-is-no-per-company-power-price)
first. The obstacle was never API access.

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

| Code | Grid | Companies naming it |
|---|---|---|
| `NYIS` | NYISO | **4** — VIP, DGXX, WULF, HUT |
| `ERCO` | ERCOT | **3** — IREN, CIFR, HUT, plus the inferred rows |
| `PJM` | PJM | **1** operating — BGDE |

Those counts come from the grid table in
[the watchlist](watchlist.md#how-many-companies-sit-on-each-grid), not from
impressions. NYISO was added once that sweep covered the whole roster: the
original ERCOT/PJM pair rested on BGDE being in Midland, **Pennsylvania** and
NUAI in Midland, **Texas** — a coincidence of town names, and thin reasoning
that understated NYISO badly.

**PJM stays despite the count of one.** CIFR's Ulysses site energizes in Q4
2027 and MARA has Ohio sites with no operator named, so dropping it now would
mean adding it back inside eighteen months. Three regions cost one table row.

`NYIS` is the ISO respondent, taken from the facet list of 83 rather than
assumed — `NYISO` is not a code at all.

**Do not substitute `NY` for it.** That respondent also exists, and returns
byte-identical values on the same clock: same demand, same forecast, no error.
It is a **state aggregate**, while `ERCO` and `PJM` are RTO respondents, so
swapping it in would make the three rows inconsistent in a way nothing
downstream could detect — the numbers would simply keep matching. The two are
distinguishable only in the facet list, which is why the probe queried the
controls alongside the candidates rather than the candidates alone.

**This is still not a complete mapping.** SPP (WULF's Abernathy site) and AESO
(HUT, in Alberta) have one company each and neither is read here. AESO is
outside every US source in any case.

## Critical: the horizon is hours, not a day

EIA publishes the day-ahead forecast **with a lag**, so `DF` extends only about
8–10 hours past the present at any moment. Measured on the first live run:
ERCOT 9 hours ahead, PJM 8.

Calling that a "day-ahead peak" would be wrong, and at the 21:20 UTC schedule
the window does **not** reach the following afternoon's peak. It reaches the
end of the current evening. Every post therefore states the horizon it actually
had rather than implying a day.

## Output

```
        7d pk   Now  Fcst
-------------------------
ERCOT    90.1   92%   99%
PJM     133.9   94%   95%
NYISO    24.7   87%   93%
```

| Column | Meaning |
|---|---|
| `7d pk` | Highest **actual** demand of the last 7 days, GW |
| `Now` | Latest actual demand, as a percentage of that peak |
| `Fcst` | Peak of the available forecast window, same percentage basis |

**Both figures are percentages of the 7-day peak** because absolute gigawatts
say nothing without a reference, and ERCOT and PJM are not comparable in
absolute terms — 90 GW versus 134 GW is a difference in grid size, not stress.

`*` marks a forecast at or above `NOTABLE_PEAK_PCT` (5%) over the trailing
peak, which also gets a prose line and turns the embed amber.

An earlier version compared the forecast peak against the 7-day peak as a bare
percentage change. Both regions read `+0%` on the first live run, and that is
structural rather than coincidental: an 8-hour forecast window compared against
a 7-day peak that already contains yesterday's equivalent hours will nearly
always land at parity. Showing where demand sits **now** carries the
information that comparison did not.

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
