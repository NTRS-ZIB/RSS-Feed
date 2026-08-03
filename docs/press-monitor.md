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

**`EXTRA_CIKS`** — `watchlist.ciks()`. The roster, pinned by CIK rather than
ticker. CIKs are permanent; tickers are not. This sector renames constantly
(BGDE renamed Apr 2026, VIP Jul 2026, ANY has a pending change to
DarkHorse/DRK), and SEC's ticker lookup file lags renames by weeks. Pinning by
CIK sidesteps that entirely. `TICKERS` is left empty as a result, but still
works if you'd rather add a company by symbol. See
[the watchlist](watchlist.md).

**`IR_FEEDS`** — `watchlist.ir_feeds()`, **ticker → URL**. Accepts either a
direct feed URL or a newsroom page; if the URL isn't a feed, the script reads
the page's `<link rel="alternate">` tag and uses whatever feed it finds.

This map was previously keyed by *display label* — a mix of tickers (`MARA`,
`IREN`) and company names (`CleanSpark`, `Soluna`, `Bakkt`). Nothing joined a
feed to its company, so a company could be dropped from the watchlist while its
feed kept being polled, and nothing would notice. Keying by ticker makes the
join structural. Feed URLs are unchanged; only the log labels differ.

**`FORM_TYPES`** — ten forms, exploiting EDGAR's prefix matching so that
`8-K` also catches `8-K/A`, `424` catches `424B1`–`424B8`, and `SC 13D` catches
its amendments:

| Form | Why |
|---|---|
| `8-K` / `6-K` | Material events; press releases as EX-99 |
| `424` | Prospectus supplements — offerings being priced. Dilution. |
| `10-Q` / `10-K` | Quarterly and annual financials |
| `20-F` / `40-F` | Annual reports, foreign and Canadian MJDS filers |
| `SC 13D` + `SCHEDULE 13D` | Activist / >5% stake disclosures. **Both spellings are required** — see below |
| `NT ` | Late filing notices under Rule 12b-25 — `NT 10-K`, `NT 10-Q`, `NT 20-F`, `NT 40-F`. Rare, high signal |

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

### Critical: `SC 13D` and `SCHEDULE 13D` are different form types

The SEC moved Schedule 13D/G to structured XML filings, and the EDGAR
form-type string changed from `SC 13D` to `SCHEDULE 13D`.

Prefix matching does not bridge them. `"SCHEDULE 13D".startswith("SC 13D")` is
**False** — the fourth character is `H`, not a space. A `FORM_TYPES` list
containing only `SC 13D` therefore matched nothing from the changeover onward.

It was found only because a real filing went unposted: Endeavor Blockchain
disclosing 6.5% of Sphere 3D on 2026-07-31, with stated intent to engage with
the board. Nothing in the logs indicated a problem, because **a form type that
matches no filings is indistinguishable from one whose filings never occur.**

Both spellings are now listed; `SC 13D` still matches filings made before the
change.

The general lesson: an entry in `FORM_TYPES` is an assumption until a filing of
that type has actually been posted. The others were confirmed by observing real
posts. This one never had been.

### The drift detector

So it cannot happen silently again. Every run collects the distinct form types
seen across the watchlist and flags any that **resemble** something tracked but
do not match it:

```
WARNING: 1 form type(s) resemble something in FORM_TYPES but do not match it.
  seen 'SCHEDULE 13D'  vs tracked 'SC 13D'
```

The rule needs no advance knowledge of the new spelling. It strips each form to
its alphanumeric core, drops leading `SC` / `SCHEDULE` / `NT` / `FORM`, and
flags an unmatched form whose core contains a tracked stem of three characters
or more. `SCHEDULE 13D` → `SCHEDULE13D` contains `13D`; `SC 13D` → `SC13D`
contains `13D`.

Verified against the actual bug: with `SCHEDULE 13D` removed from
`FORM_TYPES`, the detector flags it and its amendments. It would equally catch
a future `FORM 20-F` or `NOTIFICATION 10-Q`.

It is deliberately conservative. `SCHEDULE 13G`, `SCHEDULE 13F-HR`, `DEF 14A`,
`S-8` and `144` are all seen and none is flagged — they are different filings,
not renamings of something tracked. A detector that fired on every untracked
form would be ignored within a week.

#### What its first run found

Three flags, of which one was a real gap:

| Flagged | Verdict |
|---|---|
| `NT 20-F` vs `20-F` | **Real gap.** `NT 10-K` and `NT 10-Q` were listed individually, so the foreign-issuer late-filing notice was missing — precisely the form IREN or DGXX would file. Fixed by tracking the prefix `NT `, which now covers `NT 40-F` too. |
| `10KSB` vs `10-K` | Obsolete. Small-business annual report, discontinued around 2009. |
| `10QSB` vs `10-Q` | Obsolete, same. |

The two obsolete forms are in `DRIFT_IGNORE`. They sit in old filing histories
and would flag on every run otherwise — and a warning that always fires is one
nobody reads, which is the same failure as not having it.

Note the shape of the real finding: enumerating family members individually
(`NT 10-K`, `NT 10-Q`) left a sibling out. Tracking the family prefix (`NT `)
is both shorter and complete.

`SCHEDULE 13G` — the passive counterpart, filed by index funds and most
institutions — is deliberately **not** listed. A 13D signals intent; a 13G
signals that someone owns a lot and files an amendment each February. If it is
ever wanted, the insider channel is the better home, on the same reasoning that
put Form 4 there.

**`KEYWORDS`** — optional title filter. Empty means post everything.

**`MAX_AGE_DAYS` (7) — the age floor.** A filing older than this is recorded
but **never posted**, whatever `state.json` says.

The dedupe set alone is not enough. It answers *"have I seen this?"*, which
silently becomes *"no"* for thousands of old filings whenever state is reset or
the data source starts returning deeper history. The migration from
`browse-edgar` (40 filings per form) to the submissions API (~1,000 filings of
all types) did exactly that on 2026-08-06: 1,471 historical filings looked new
at once and 65 messages of old news reached the channel.

An age floor is independent of state, so backfill can never be mistaken for
news. Against that same event it would have posted 4 items instead of 40. It
also makes the `state.json` reset in Testing safe.

The trade-off: if the workflow is down for more than a week, genuinely missed
news older than seven days will not post.

**`RETAIN_DAYS` (30) — the dedupe horizon.** Only EDGAR filings from the last
30 days enter the dedupe set at all. Nothing older can post, so remembering it
is pure state-file bloat — the submissions endpoint returns ~1,000 filings per
company, which put 4,275 ids in `state.json` for a watchlist of eleven.

Keep it comfortably above `MAX_AGE_DAYS`; the 23-day gap is the safety margin
for an outage. Not applied to IR feed items, which are ~10 per feed and whose
timestamps are less reliable.

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
| TeraWulf | 0001083301 | Equisolve |
| Hut 8 Corp | 0001964789 | none — EDGAR only |
| Cipher Digital | 0001819989 | gcs-web |

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

Four companies have no feed, and they are not all the same problem.

Big Digital Energy, WhiteFiber and Digi Power X render their newsrooms
client-side (QuoteMedia widget, Webflow, and Next.js respectively), so the
headlines aren't in the delivered HTML. Neither autodiscovery nor a plain HTML
scraper can see them; a headless browser or Google Alerts RSS would be needed.

Hut 8 is different. `hut8.com` is a custom site that simply publishes no feed —
none linked from the press releases page, and no RSS entry under its investor
resources, unlike TeraWulf and Cipher Digital which both list one. But its press
releases render **server-side** and come back complete in a plain HTTP fetch, so
a scraper for it would not need a headless browser. That makes Hut 8 the
cheapest of the four to solve if a scraper is ever built.

All four remain fully covered by EDGAR for anything material.

## Scaling

**Requests per run: 24** — one submissions call per company (14) plus one per
IR feed (10). Both channels are served from the same payload, so the insider
check costs nothing extra.

This replaced the legacy `cgi-bin/browse-edgar` endpoint, which needed one call
per company *per form type* plus an index fetch per candidate filing — about
**201 requests**. That endpoint is slow and times out under load: on 2026-07-30
a run reached only 4 of 11 companies before hitting the step timeout. Worst
case with every request stalling fell from roughly 600 minutes to 10.

**Item IDs per run: 128** — 48 EDGAR filings within `RETAIN_DAYS` plus 80 IR
feed entries. `state.json` settles around 56KB.

Retention is `max(1000, items × 3)`. The multiplier is the real protection: the
retained list must stay longer than one run's visibility or items age out,
reappear as unseen, and get re-posted. The constant is only a sane minimum, and
it was lowered from 4,000 once `RETAIN_DAYS` cut a run's visibility to ~130 —
at the old value the file would have been pinned at ~250KB of dead history.

That figure has moved twice and the history is instructive:

| | IDs per run | state.json |
|---|---|---|
| browse-edgar, 40 per form | 1,631 | ~100KB |
| submissions, unfiltered | 4,275 | ~265KB |
| submissions + `RETAIN_DAYS` | 128 | ~56KB |

The middle row is what caused the 2026-08-06 flood. The bloat was a symptom of
the same mistake: remembering filings that could never be posted anyway.

| Limit | Binds at | Failure mode |
|---|---|---|
| `state.json` retention | not binding at current scale | Was ~60 companies before `RETAIN_DAYS`. Items ageing out of state now cannot post anyway, so the failure mode is gone. |
| 15-min step timeout | not binding at current scale | Run killed mid-way; state never saved. This was the binding limit under the old endpoint. |
| `MAX_POSTS_PER_RUN` | any size | Overflow beyond the cap is marked seen and **discarded**, not queued. Posts that *fail* are retried. |
| SEC rate limit | not binding | Requests are sequential with a 0.15s gap, well under 10/sec. |

The retained ID list must stay longer than the number of items one run can see,
or the dedupe breaks. `save_state` therefore scales its cap with observed run
volume (`max(4000, items × 3)`) rather than using a fixed number. The cost is
file size — roughly 240KB at 11 companies, 540KB at 25, over 1MB at 50 —
committed up to 48 times a day.

To go beyond ~60 companies, in order of effect:

1. **Raise `MAX_POSTS_PER_RUN`** so a busy morning can't silently overflow it.
   This is the first thing that binds now.
2. **Lower `RETAIN_DAYS`** toward `MAX_AGE_DAYS` to shrink state further,
   at the cost of outage margin.
3. **Trim `FORM_TYPES`.** No longer a multiplier on *requests* — one call
   returns everything regardless — and with `RETAIN_DAYS` in place it barely
   moves state size either. Mostly a noise-reduction lever now.

Past that, the right redesign is storing a per-company high-water timestamp
instead of a list of every ID seen. That stays constant-size regardless of
watchlist length. Not worth the complexity below ~60 companies.

## Testing

**Dry run.** Actions → Press release monitor → Run workflow. The checkbox is
ticked by default: it fetches, evaluates, and prints exactly what *would* post,
but posts nothing.

Critically it also does **not save state**. Saving would mark everything seen
and the next real run would post nothing at all — a quieter failure than a
flood. Scheduled runs pass no input, so they always post normally.

```
2 candidate(s) checked, 2 to post.
  [press]   MARA Holdings (MARA) · SEC 8-K — Results of operations
  [press]   MARA Holdings (MARA) · SEC 10-Q — Quarterly report
  [insider] MARA Holdings (MARA) · Form 4 — FORM 4

Dry run: would post 2 press and 1 insider item(s). State not saved.
```

**Forcing a live post.** Replace `state.json` with
`{"seen": [], "initialized": true}`, commit, and run with the checkbox
unticked. The age floor means only filings from the last 7 days can post, so
this no longer risks a backlog flood.

The very first run on a fresh state file posts nothing by design — it records a
baseline.

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
  MARA: 1001 filing(s), 959 older than 30d -> 25 tracked, 17 insider
Checking 8 IR feeds...
  MARA: 10 items
Insider channel: 98 Form 4 filing(s).
332 items seen, 2 new, 1 new insider.
2 candidate(s) checked, 2 to post.
Posted 2 press item(s).
Posted 1 insider item(s).
State: 334 ids retained (cap 4000).
```

Each company and feed name prints *before* it is attempted, so if a run stalls,
the last line names the culprit. The per-company line reads
`total filings, dropped by age -> forms we track, Form 4 count`.

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
