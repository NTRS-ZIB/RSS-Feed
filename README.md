# Watchlist monitor

Automated Discord feeds for a watchlist of digital infrastructure and bitcoin
mining companies. Runs entirely on GitHub Actions crons — no server, nothing to
maintain.

## Components

| Script | Workflow | Posts to | When |
|---|---|---|---|
| `press_monitor.py` | `monitor.yml` | `WEBHOOK_URL` + `WEBHOOK_URL_INSIDER` | Every 15 min, weekdays 12:00–23:59 UTC |
| `btc_context.py` | `btc.yml` | `WEBHOOK_URL_MARKET` | 21:15 UTC, weekdays |
| `earnings_calendar.py` | `earnings.yml` | `WEBHOOK_URL_MARKET` | 12:30 UTC, Mondays |
| `volume_spike.py` | `spikes.yml` | `WEBHOOK_URL_ALERTS` | Every 15 min, weekdays 11:00–22:59 UTC |
| `daily_recap.py` | `recap.yml` | `WEBHOOK_URL_MARKET` | 21:30 UTC, weekdays |

They are deliberately separate workflows: a failure in one data provider must
not take down the others. The context posts 15 minutes before the recap so it
lands above the performance table in the channel.

---

# Press release monitor

Watches SEC EDGAR filings and company IR newsrooms, and posts anything new to a
Discord channel.

## How it works

Two sources, two output channels.

Sources:

1. **SEC EDGAR** — ten form types (see `FORM_TYPES`). Press releases arrive as
   EX-99 exhibits on 8-K/6-K; offerings, financials and stake disclosures come
   through the other forms. Authoritative, but trails the newswire by minutes
   to hours.
2. **IR newsroom RSS** — the company's own feed. Faster than EDGAR, but not
   every company publishes one.

Channels:

- **Main** (`WEBHOOK_URL`) — press releases and filings.
- **Insider** (`WEBHOOK_URL_INSIDER`, optional) — Form 4 and 4/A only.

New items are deduped against `state.json` and posted once each.

## Layout

```
press_monitor.py                  press release / filing monitor
daily_recap.py                    post-close market recap
btc_context.py                    bitcoin network context
earnings_calendar.py              projected reporting dates
volume_spike.py                   intraday unusual-volume alerts
.github/workflows/monitor.yml     monitor schedule and runner setup
.github/workflows/recap.yml       recap schedule and runner setup
.github/workflows/btc.yml         context schedule and runner setup
.github/workflows/earnings.yml    calendar schedule and runner setup
.github/workflows/spikes.yml      spike schedule and runner setup
spike_state.json                  auto-generated; per-day alert tiers
state.json                        auto-generated; do not hand-edit except to reset
```

## Secrets

Settings → Secrets and variables → Actions:

| Secret | Value |
|---|---|
| `WEBHOOK_URL` | Discord webhook URL. Slack incoming webhooks also work — payload shape is detected from the host. |
| `SEC_USER_AGENT` | Real name and email, e.g. `Jane Doe jane@example.com`. SEC throttles anonymous traffic. |
| `WEBHOOK_URL_INSIDER` | *Optional.* Webhook for a separate Form 4 channel. If unset, the insider check is skipped entirely. |
| `WEBHOOK_URL_MARKET` | Webhook for the daily recap channel. |
| `ALPACA_KEY_ID` / `ALPACA_SECRET_KEY` | Free Alpaca account (Market Data). Used by the recap and the spike alerts. Paper-trading keys work. |
| `TWELVEDATA_KEY` | *Optional fallback only.* See the recap's data source notes — its free tier lags intraday. |
| `WEBHOOK_URL_ALERTS` | *Optional.* Webhook for the volume alerts channel. Falls back to `WEBHOOK_URL_MARKET` if unset. |

**Secrets must also be mapped in the workflow.** Adding one under repository
settings is not enough — it has to be listed in the `env:` block of the
`Run monitor` step in `.github/workflows/monitor.yml` or the script never sees
it.

## Schedule

`*/15 12-23 * * 1-5` — every 15 minutes, weekdays, 12:00–23:59 UTC.

GitHub cron is UTC with no DST awareness, so the window is set wide enough to
cover the US pre/postmarket release windows year-round without seasonal edits:

- EDT (Mar–Nov): 08:00–19:59 Eastern
- EST (Nov–Mar): 07:00–18:59 Eastern

Change `12-23` to `11-23` to also catch 7:00am ET premarket releases in summer.

## Configuration

Everything lives in the CONFIG block at the top of `press_monitor.py`.

**`EXTRA_CIKS`** — the watchlist, pinned by CIK rather than ticker. CIKs are
permanent; tickers are not. This sector renames constantly (BGDE renamed Apr
2026, VIP Jul 2026, ANY has a pending change to DarkHorse/DRK), and SEC's
ticker lookup file lags renames by weeks. Pinning by CIK sidesteps that
entirely. `TICKERS` is left empty as a result, but still works if you'd rather
add a company by symbol.

**`IR_FEEDS`** — label → URL. Accepts either a direct feed URL or a newsroom
page; if the URL isn't a feed, the script reads the page's
`<link rel="alternate">` tag and uses whatever feed it finds.

**`FORM_TYPES`** — ten forms, exploiting EDGAR's prefix matching so that
`8-K` also catches `8-K/A`, `424` catches `424B1`–`424B8`, and `SC 13D` catches
its amendments:

| Form | Why |
|---|---|
| `8-K` / `6-K` | Material events; press releases as EX-99 |
| `424` | Prospectus supplements — offerings being priced. Dilution. |
| `10-Q` / `10-K` | Quarterly and annual financials |
| `20-F` / `40-F` | Annual reports, foreign and Canadian MJDS filers |
| `SC 13D` | Activist / >5% stake disclosures |
| `NT 10-K` / `NT 10-Q` | Late filing notices — rare, high signal |

Form 4 is deliberately absent; it has its own channel. Note that earnings news
arrives as an 8-K Item 2.02 press release, typically before the 10-Q, so the
10-Q gets you the statements rather than the announcement.

**`PRESS_RELEASE_EXHIBIT_ONLY`** — when true, a filing is only posted if it
attaches an EX-99 exhibit, filtering out administrative 8-Ks. Costs one extra
request per candidate filing.

Applies **only** to the forms in `EXHIBIT_CHECK_FORMS` (`8-K`, `6-K`). A 10-Q or
424 carries no EX-99, so applying the check to them would silently discard every
one. If you add a press-release-bearing form, add it to that set too.

**`KEYWORDS`** — optional title filter. Empty means post everything.

**Insider channel** — Form 4 and 4/A filings go to `WEBHOOK_URL_INSIDER`
instead of the main channel, with their own `MAX_INSIDER_POSTS_PER_RUN` cap and
amber embeds. Form 4 volume across eleven companies would swamp a press release
feed, which is why it's separate rather than another entry in `FORM_TYPES`.

One subtlety: EDGAR's type filter is a prefix match, so querying `4` also
returns `40-F` and `424B*`. Entries are filtered against
`INSIDER_ALLOWED_FORMS` using the form type EDGAR reports per entry, so those
collisions are discarded rather than mis-routed.

**`MAX_POSTS_PER_RUN`** — flood guard, default 40 (insider channel: 25). Sized
for earnings season, when ~10 companies each produce an 8-K, a 10-Q and an IR
item within a short window.

Two different outcomes, easily confused:

- **Beyond the cap** — marked seen, never posted. Deliberate. A backlog must not
  queue up and drip into the channel for hours.
- **Failed to post** — un-marked and retried on the next run. Also deliberate;
  see the rate limiting note below.

## Coverage

| Company | CIK | IR feed |
|---|---|---|
| MARA Holdings | 0001507605 | Equisolve |
| CleanSpark | 0000827876 | Q4 Inc |
| Bakkt, Inc. | 0001820302 | gcs-web |
| New Era Energy & Digital | 0002028336 | Q4 Inc |
| IREN Limited | 0001878848 | gcs-web |
| Vulcan Infrastructure and Power | 0001844971 | gcs-web |
| Sphere 3D | 0001591956 | gcs-web |
| Soluna Holdings | 0000064463 | WordPress (`/news/feed/`) |
| Big Digital Energy | 0001218683 | none — EDGAR only |
| WhiteFiber | 0002042022 | none — EDGAR only |
| Digi Power X | 0001854368 | none — EDGAR only |

The three IR platforms use different feed conventions:

- Equisolve: `/news-events/press-releases/rss`
- Q4 Inc: `/rss/pressrelease.aspx`

Note that IR platforms migrate. Bakkt moved from Q4 to gcs-web, which broke
its feed URL with a 404. If a previously working feed starts failing, check
whether the site changed platforms before assuming the feed was removed.
- Notified / gcs-web: `/rss/news-releases.xml`

Soluna is plain WordPress. Its press releases live in the `/news/` archive
(feed at `/news/feed/`), while the site-root `/feed/` is a near-dormant blog
feed. Autodiscovery finds the latter, because the archive's own feed isn't
declared in the page HTML — so the correct URL had to be set explicitly.

The three companies without feeds render their newsrooms client-side
(QuoteMedia widget, Webflow, and Next.js respectively), so the headlines aren't
in the delivered HTML. Neither autodiscovery nor a plain HTML scraper can see
them; a headless browser or Google Alerts RSS would be needed. They remain
fully covered by EDGAR for anything material.

## Scaling

Calibrated against a real run: 11 companies, 10 forms, 8 IR feeds and the
insider channel produced **129 requests and 1,631 item IDs** per run.

Per company that's ~11 requests and ~140 item IDs (~112 from the press forms,
~29 from Form 4).

Note that several companies return exactly 40 Form 4 filings — the `count=40`
ceiling in `EDGAR_ATOM`. Lowering it to 15 costs nothing at a 15-minute cadence
and cuts insider IDs per run from ~315 to ~120.

| Limit | Binds at | Failure mode |
|---|---|---|
| `state.json` retention | ~60 companies | Items age out of state, reappear as new, get re-posted. Silent. |
| 10-min step timeout | ~90 companies | Run killed mid-way; state never saved. |
| `MAX_POSTS_PER_RUN` | any size | Overflow beyond the cap is marked seen and **discarded**, not queued. Posts that *fail* are retried. |
| SEC rate limit | not binding | Requests are sequential with a 0.15s gap, well under 10/sec. |

The retained ID list must stay longer than the number of items one run can see,
or the dedupe breaks. `save_state` therefore scales its cap with observed run
volume (`max(4000, items × 3)`) rather than using a fixed number. The cost is
file size — roughly 240KB at 11 companies, 540KB at 25, over 1MB at 50 —
committed up to 48 times a day.

To go beyond ~60 companies, in order of effect:

1. **Trim `FORM_TYPES`.** A straight multiplier on requests, runtime and state
   size. Ten forms down to four (`8-K`, `6-K`, `424`, `10-Q`) nearly triples the
   ceiling in one edit. `NT 10-K`/`NT 10-Q` cost a request per company per run
   to catch a once-a-year event.
2. **Lower `count=40` in `EDGAR_ATOM`.** Only the newest items ever post, so
   pulling 40 historical filings per form is waste. Dropping to 15 cuts
   items-seen by ~60%.
3. **Raise `MAX_POSTS_PER_RUN`** so a busy morning can't silently overflow it.

Past that, the right redesign is storing a per-company high-water timestamp
instead of a list of every ID seen. That stays constant-size regardless of
watchlist length. Not worth the complexity below ~60 companies.

## Testing

To force a live run that posts:

1. Replace the contents of `state.json` with `{"seen": [], "initialized": true}`
2. Commit
3. Actions → Press release monitor → Run workflow

The very first run on a fresh state file posts nothing by design — it records a
baseline so a backlog can't flood the channel.

## Known quirks

- **Scheduled workflows are disabled after 60 days of repo inactivity.** GitHub
  emails first. The `state.json` commits normally keep this from triggering.
- **Cron drift.** Scheduled jobs are queued at low priority; `*/15` is
  realistically 15–25 minutes and can be skipped under peak load.
- **IR feeds behind WAFs.** Some IR platforms stall non-browser User-Agents
  instead of returning an error, which surfaces as `ReadTimeout`. The script
  sends browser-like headers to the IR hosts for this reason. SEC still gets
  the real contact string from `SEC_USER_AGENT`.
- **Public repo.** Workflow logs are publicly readable. Secrets are encrypted
  and masked as `***`, but the watchlist and feed URLs are visible.
- **`state.json` grows with the watchlist.** Retention scales with run volume
  by design — see Scaling. Don't replace it with a fixed cap.
- **Discord rate limits are handled, and must stay handled.** Items are marked
  seen before posting, so a dropped post would be lost permanently. `post()`
  honours Discord's `retry_after` (capped at 30s, one retry), and anything
  still failing is removed from `state["seen"]` so the next run retries it.
  Rate limiting is most likely during earnings season — exactly when the items
  matter most. Do not simplify this into a fire-and-forget POST.
- **Don't add a `pull_request` trigger.** Only `schedule` and
  `workflow_dispatch` are safe here.

## Reading the log

```
  VIP: pinned to CIK 0001844971 (Vulcan Infrastructure and Power)
Checking EDGAR for 11 companies...
  MARA (CIK 0001507605)...
Checking 8 IR feeds...
  MARA: 10 items
Checking insider filings (Form 4)...
  MARA: 4 insider filing(s)
1316 items seen, 2 new, 1 new insider.
2 candidate(s) checked, 2 to post.
Posted 2 press item(s).
Posted 1 insider item(s).
State: 1634 ids retained (cap 4893).
```

Each ticker and feed name prints *before* it is attempted, so if a run stalls,
the last line names the culprit.

A normal run reports `0 new` and posts nothing. That is success.

Lines worth reacting to:

| Line | Meaning |
|---|---|
| `WEBHOOK_URL_INSIDER not set — skipping insider channel` | Either intentional, or the secret isn't mapped into the workflow's `env:` block. An unmapped secret reads as empty, which is indistinguishable from disabled. |
| `HTTP 404` on one feed | Usually an IR site replatforming, not a removed feed. Check the platform before giving up. |
| `ReadTimeout` | A WAF stalling the request. Check the browser headers are still being sent. |
| `NO FEED` | Autodiscovery found nothing on that URL. |
| `Not found on EDGAR` | Only possible for `TICKERS` entries; pin the company by CIK in `EXTRA_CIKS` instead. |
| `rate limited, waiting Ns` | Discord 429. Normal during heavy bursts; the item is retried automatically. |
| `N item(s) failed to post; will retry next run` | Those items were removed from state and will be re-attempted in 15 minutes. Not a loss. |

---

# Daily market recap

Posts a post-close performance table and a chart grid for the same watchlist.

## Schedule

`30 21 * * 1-5` — 21:30 UTC, weekdays. That lands after the US close in both
DST states (5:30pm ET in summer, 4:30pm in winter), so no seasonal edits.

## Output

A monospace table sorted by daily move, plus a PNG grid of 60-day closing
sparklines, green or red by period direction.

| Column | Meaning |
|---|---|
| `Close` | Last close |
| `Chg` | % change vs previous close |
| `Vol` | Session volume |
| `x30d` | Volume as a multiple of the trailing 30-day average |
| `52w` | Position in the 52-week range, 0% = low, 100% = high |

The header states the **actual date of the last bar** rather than assuming it
is today. Tickers with no data are named, and tickers whose latest bar is older
than the rest are flagged as `lagging`.

If the newest bar is today's and the US close hasn't happened, the header reads
`INTRADAY` instead of `Close`. Providers return the current, incomplete session
as a normal-looking bar; the tell is `x30d` collapsing to ~0.1x across every
ticker at once, because partial volume is being compared to full-day averages.

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

- **Free-tier history is patchy for recent listings.** `outputsize=300` gives
  ~300 calendar days, not 252 trading days, and recently-listed tickers may
  have only a few months. The `52w` column is only as good as the history
  behind it.
- **Split adjustment varies by provider.** Several of these companies have done
  reverse splits. An implausible cliff in a chart is usually an unadjusted
  split, not a real move.
- **Provider risk.** Unlike EDGAR and the IR feeds, this depends on a
  commercial free tier that can change. If it disappears, the fetch layer is
  isolated in `fetch_twelvedata()` and can be swapped without touching the
  table or chart code.

---

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
second, ~6 requests per run. Unlike per-IP-quota services (see the Stooq note
under the recap), this works reliably from shared CI runners.

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

---

# Earnings calendar

Projects when each company will next report, so you know what's coming rather
than only reacting to what already happened.

## Schedule

`30 12 * * 1` — Mondays 12:30 UTC (8:30am ET summer, 7:30am winter), ahead of
the week's first open.

## Method

No external data provider. SEC's submissions API
(`data.sec.gov/submissions/CIK##########.json`) returns every filing with both
the period it covers (`reportDate`) and the date it was filed (`filingDate`).
The gap between them is stable per company, so:

```
expected = next period end + that company's median lag
```

The lag is the median of its last 8 periodic filings, and the `±` shown is the
spread across those. That spread is the honesty indicator: `±0d` means
metronomic, `±35d` means don't plan around it.

## Critical: annual and quarterly lags must never be pooled

Annual reports are filed 60–90 days after fiscal year end; quarterlies around
40. Averaging them produces a median fitting neither and a spread spanning the
difference.

The first working version pooled them. Real output: MARA ±33d, BGDE ±46d,
ANY ±52d, DGXX ±215d — spreads so wide the dates were meaningless. After
separating by form type the same companies read ±14d, ±6d, ±10d.

`ANNUAL_FORMS` and `QUARTERLY_FORMS` exist for this reason. Do not merge them.

## Fiscal year ends are detected, not assumed

Several companies here are not calendar-year filers — IREN's year ends in June,
CleanSpark's in September. The script infers the fiscal year end from the most
common month among past annual reports, then decides whether the next period
end is a year end (use the annual lag) or a quarter (use the quarterly lag).

Getting this wrong produces a plausible-looking date that is 30+ days out. IREN
correctly projects an `annual` filing for its June period, not a 10-Q.

## Output markers

| Marker | Meaning |
|---|---|
| *(none)* | Projection from ≥2 same-form filings. Treat the date as real. |
| `~` | Historical spread exceeds 30 days. Indicative only; named in a footnote. |
| `?` | Had to fall back to a different form type — e.g. a foreign issuer with no 10-Q history. Weakest case. |

Expected dates falling on a weekend roll forward to Monday.

## Sections

**Expected in the next 45 days** — the actionable list.

**Past estimate** — a company more than 10 days beyond its own typical lag with
nothing filed. This corroborates the `NT 10-Q` / `NT 10-K` late-filing notices
the press monitor watches for; seeing both is a strong signal.

**Later** — one-line summary of everything beyond the horizon.

## Known quirks

- **These are estimates, not announced dates.** Companies announce actual dates
  by press release, which the press release monitor already catches. This fills
  the gap before that announcement lands.
- **Recent listings have thin history.** WYFI had 4 periodic filings at time of
  writing, giving ±35d. Accurate reporting of low confidence, not a bug.
- **Validate against reality.** When a company actually files, compare to the
  projection. If established filers are consistently off by a fixed amount, an
  old restatement or late filing is likely skewing the 8-sample window — reduce
  `LAG_SAMPLE` to 4.

---

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
and would fire constantly. The recap uses `sip` precisely because it displays
absolute figures, where IEX would be wrong.

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
