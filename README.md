# Press release monitor

Watches SEC EDGAR filings and company IR newsrooms for a watchlist of digital
infrastructure and bitcoin mining companies, and posts anything new to a Discord
channel. Runs on a GitHub Actions cron — no server, no dependencies to maintain.

## How it works

Two sources per company:

1. **SEC EDGAR** — 8-K (US issuers) and 6-K (foreign private issuers). Material
   press releases are attached as EX-99 exhibits. Authoritative, but trails the
   newswire by minutes to hours.
2. **IR newsroom RSS** — the company's own feed. Faster, but not every company
   publishes one.

New items are deduped against `state.json` and posted once each.

## Layout

```
press_monitor.py                  all logic and configuration
.github/workflows/monitor.yml     schedule and runner setup
state.json                        auto-generated; do not hand-edit except to reset
```

## Secrets

Settings → Secrets and variables → Actions:

| Secret | Value |
|---|---|
| `WEBHOOK_URL` | Discord webhook URL. Slack incoming webhooks also work — payload shape is detected from the host. |
| `SEC_USER_AGENT` | Real name and email, e.g. `Jane Doe jane@example.com`. SEC throttles anonymous traffic. |

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

**`FORM_TYPES`** — `["8-K", "6-K"]`. Add `10-Q`/`10-K` for periodic reports.

**`PRESS_RELEASE_EXHIBIT_ONLY`** — when true, an EDGAR filing is only posted if
it attaches an EX-99 exhibit, filtering out administrative 8-Ks. Costs one
extra request per candidate filing.

**`KEYWORDS`** — optional title filter. Empty means post everything.

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
- **Don't add a `pull_request` trigger.** Only `schedule` and
  `workflow_dispatch` are safe here.

## Reading the log

```
VIP: pinned to CIK 0001844971 (Vulcan Infrastructure and Power)
  MARA: 10 items
  Soluna: discovered feed at https://www.solunacomputing.com/feed/
  WhiteFiber: NO FEED — needs a scraper or manual URL
532 items seen, 3 new.
6 candidate(s) checked, 3 to post.
Posted 3 item(s).
```

Each ticker and feed name prints *before* it is attempted, so if a run stalls,
the last line names the culprit.
