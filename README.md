# Watchlist monitor

Automated Discord feeds for a watchlist of digital infrastructure and bitcoin
mining companies. Runs entirely on GitHub Actions crons — no server, nothing to
maintain.

## Components

| Script | Workflow | Posts to | When |
|---|---|---|---|
| `press_monitor.py` | `monitor.yml` | `WEBHOOK_URL` + `WEBHOOK_URL_INSIDER` | Every 15 min, weekdays 12:00–23:59 UTC |
| `btc_context.py` | `btc.yml` | `WEBHOOK_URL_MARKET` | 21:15 UTC, weekdays |
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
.github/workflows/monitor.yml     monitor schedule and runner setup
.github/workflows/recap.yml       recap schedule and runner setup
.github/workflows/btc.yml         context schedule and runner setup
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
| `TWELVEDATA_KEY` | Free API key from twelvedata.com, used by the recap. |

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

**`MAX_POSTS_PER_RUN`** — flood guard, default 25. Items beyond the cap are
marked as seen without being posted, so they don't queue up for the next run.

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
| `MAX_POSTS_PER_RUN` | any size | Overflow is marked seen and **discarded**, not queued. |
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

**Twelve Data** (`TWELVEDATA_KEY`). Free tier is ~800 requests/day and
**8 requests/minute**; the recap needs 11, paced 8 seconds apart, so a run takes
roughly 90 seconds. Hence the 15-minute step timeout.

**Not Yahoo / yfinance.** Yahoo deprecated its API and discourages scraping.
Unofficial wrappers break without warning.

**Not Stooq**, despite being keyless — and this one cost a debugging cycle.
Stooq enforces a low **per-IP daily quota** and, when exceeded, returns the
plain text `Exceeded the daily hits limit` with **HTTP 200**, not an error
status. GitHub Actions runners share an Azure IP pool with a huge number of
unrelated jobs, so that quota is routinely already spent before the job starts.
The symptom is every ticker failing identically. Stooq remains as a fallback
when `TWELVEDATA_KEY` is unset, which works fine from a home IP.

The general lesson: keyless does not mean usable from CI. Check whether a
provider rate-limits by IP before depending on it from a shared runner.

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
