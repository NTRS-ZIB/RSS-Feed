[← Watchlist monitor](../README.md)

# Press release monitor

Watches SEC EDGAR filings and company IR newsrooms, and posts anything new to a
Discord channel.

## How it works

Two sources, two output channels.

Sources:

1. **SEC EDGAR** — ten form types (see `FORM_TYPES`), read from the
   submissions API (`data.sec.gov/submissions/CIK##########.json`). One
   request per company returns every recent filing. Authoritative, but trails
   the newswire by minutes to hours.
2. **IR newsroom RSS** — the company's own feed. Faster than EDGAR, but not
   every company publishes one.

Channels:

- **Main** (`WEBHOOK_URL`) — press releases and filings.
- **Insider** (`WEBHOOK_URL_INSIDER`, optional) — Form 4 and 4/A only.

New items are deduped against `state.json` and posted once each.

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

**`PRESS_RELEASE_EXHIBIT_ONLY`** — when true, an 8-K is only posted if its
**item codes** indicate a press release: `2.02` results, `7.01` Reg FD, `8.01`
other events (`PRESS_RELEASE_ITEMS`). Filters out administrative 8-Ks such as
`5.02` officer changes.

Item codes ship inside the submissions payload, so this costs **no extra
request**. The original implementation downloaded each filing's index page
looking for an EX-99 exhibit — roughly 80 extra requests per run.

That swap narrowed the definition slightly. An 8-K filed under, say, `1.01`
(material agreement) with a press release attached would have been caught by
the old exhibit check and is skipped now. Widen `PRESS_RELEASE_ITEMS` if you
notice gaps.

Applies **only** to the forms in `EXHIBIT_CHECK_FORMS` (`8-K`, `6-K`). 6-K has
no item numbers and is never filtered.

**Filing titles** are generated, not taken from SEC. The submissions payload
only supplies a document label, usually just `8-K`, which is redundant beside
the form type already in the embed footer. `ITEM_LABELS` translates item codes
into plain English — an earnings 8-K reads *Results of operations* — and
`FORM_LABELS` does the same for other forms, so a `424B5` reads *Prospectus
supplement — offering* and an `NT 10-Q` shouts *LATE FILING NOTICE*. Item
`9.01` is suppressed unless it is the only one listed, since it appears on
almost every 8-K with an attachment.

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
- Notified / gcs-web: `/rss/news-releases.xml`

Note that IR platforms migrate. Bakkt moved from Q4 to gcs-web, which broke
its feed URL with a 404. If a previously working feed starts failing, check
whether the site changed platforms before assuming the feed was removed.

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

**Requests per run: 19** — one submissions call per company (11) plus one per
IR feed (8). Both channels are served from the same payload, so the insider
check costs nothing extra.

This replaced the legacy `cgi-bin/browse-edgar` endpoint, which needed one call
per company *per form type* plus an index fetch per candidate filing — about
**201 requests**. That endpoint is slow and times out under load: on 2026-07-30
a run reached only 4 of 11 companies before hitting the step timeout. Worst
case with every request stalling fell from roughly 600 minutes to 10.

> **Item-ID counts need recalibrating.** The pre-migration figure was 1,631 IDs
> per run. The submissions endpoint returns roughly the last 1,000 filings of
> *all* types per company, rather than 40 per form, so the tracked total will
> differ. Read `State: N ids retained` from a run and update this.

| Limit | Binds at | Failure mode |
|---|---|---|
| `state.json` retention | ~60 companies | Items age out of state, reappear as new, get re-posted. Silent. |
| 15-min step timeout | not binding at current scale | Run killed mid-way; state never saved. This was the binding limit under the old endpoint. |
| `MAX_POSTS_PER_RUN` | any size | Overflow beyond the cap is marked seen and **discarded**, not queued. Posts that *fail* are retried. |
| SEC rate limit | not binding | Requests are sequential with a 0.15s gap, well under 10/sec. |

The retained ID list must stay longer than the number of items one run can see,
or the dedupe breaks. `save_state` therefore scales its cap with observed run
volume (`max(4000, items × 3)`) rather than using a fixed number. The cost is
file size — roughly 240KB at 11 companies, 540KB at 25, over 1MB at 50 —
committed up to 48 times a day.

To go beyond ~60 companies, in order of effect:

1. **Trim `FORM_TYPES`.** No longer a multiplier on *requests* — one call
   returns everything regardless — but still a multiplier on tracked item IDs,
   and therefore on state size. `NT 10-K`/`NT 10-Q` are near-zero volume.
2. **Raise `MAX_POSTS_PER_RUN`** so a busy morning can't silently overflow it.
3. **Drop the insider channel** if Form 4 dominates the ID count. It is
   typically the largest share of filings per company.

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
  MARA: 847 filing(s) -> 6 tracked, 40 insider
Checking 8 IR feeds...
  MARA: 10 items
Insider channel: 312 Form 4 filing(s).
4102 items seen, 2 new, 1 new insider.
2 candidate(s) checked, 2 to post.
Posted 2 press item(s).
Posted 1 insider item(s).
State: 4105 ids retained (cap 12306).
```

Each company and feed name prints *before* it is attempted, so if a run stalls,
the last line names the culprit. The per-company line reads
`total filings -> forms we track, Form 4 count`.

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
