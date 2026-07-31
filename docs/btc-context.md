[← Watchlist monitor](../README.md)

# Bitcoin network context

Posts the variables that move every miner on the watchlist at once. When
difficulty rises, all eleven companies get less profitable on the same day —
which the press release and recap channels cannot explain on their own.

## Schedule

`15 21 * * 1-5` — 21:15 UTC weekdays, 15 minutes ahead of the recap.

Weekdays only, to sit alongside the equity data. Bitcoin doesn't stop at the
weekend, so change to `15 21 * * *` for seven-day coverage.

## Output

A Discord embed with five fields:

| Field | Contents |
|---|---|
| Bitcoin | Spot USD, 24h change |
| Network hashrate | Current EH/s, plus 7-day mean vs prior 7-day mean |
| Hashprice | USD per PH/s per day, and fees as a share of revenue |
| Difficulty | Current, next adjustment estimate, ETA, blocks remaining |
| Block | Height and current subsidy |

Hashprice is the number to watch: it is the revenue each company earns per unit
of deployed capacity, and it explains correlated moves across the watchlist
better than any single-company metric.

Fee share matters too. When fees are a low percentage of revenue, miners depend
almost entirely on the block subsidy and margins are fully exposed to BTC price
and difficulty.

## Data source

**mempool.space public REST API.** No authentication, roughly 10 requests per
second, ~6 requests per run. Unlike per-IP-quota services (see the Stooq note in
[the recap docs](recap.md#data-sources--and-why)), this works reliably from shared CI runners.

Every endpoint degrades independently — if one fails, the embed is built from
whatever else succeeded rather than the run failing. Only a total outage
produces no post.

## Design notes

**Block subsidy is derived from height** (`50 / 2^(height // 210000)`), not
hardcoded. The 2028 halving needs no code change.

**Hashprice uses realised revenue**, from `reward-stats/144` — actual sats paid
to miners over the last 144 blocks — rather than assuming `144 × subsidy`. That
captures real block times and real fee revenue instead of a theoretical figure.

**The hashrate trend is smoothed, deliberately.** Hashrate is not measured; it
is inferred from block intervals, which are Poisson-distributed and very noisy
day to day. A point-in-time comparison against a single day a week ago swings
wildly on variance alone.

Tested against a synthetic series with genuinely *flat* hashrate and realistic
daily noise, a point-to-point comparison reported **−16.6%** while the 7-day
mean vs prior 7-day mean reported **+1.8%** — roughly a 9x reduction in false
signal. The first live run showed +22.6% alongside a −3.0% difficulty
projection, which is close to self-contradictory; after smoothing it read
−0.4%, consistent with the difficulty forecast.

Do not replace this with a simpler point-to-point comparison. The trend line is
omitted entirely when fewer than 14 days of history are available.
