# Watchlist monitor

Automated Discord feeds for a watchlist of digital infrastructure and bitcoin
mining companies. Runs entirely on GitHub Actions crons — no server, nothing to
maintain.

## Components

| Script | Workflow | Posts to | When |
|---|---|---|---|
| [`press_monitor.py`](docs/press-monitor.md) | `monitor.yml` | `WEBHOOK_URL` + `WEBHOOK_URL_INSIDER` | Every 15 min, weekdays 12:00–23:59 UTC |
| [`btc_context.py`](docs/btc-context.md) | `btc.yml` | `WEBHOOK_URL_MARKET` | 21:15 UTC, weekdays |
| [`earnings_calendar.py`](docs/earnings.md) | `earnings.yml` | `WEBHOOK_URL_MARKET` | 12:30 UTC, Mondays |
| [`volume_spike.py`](docs/volume-spikes.md) | `spikes.yml` | `WEBHOOK_URL_ALERTS` | Every 15 min, weekdays 11:00–22:59 UTC |
| [`daily_recap.py`](docs/recap.md) | `recap.yml` | `WEBHOOK_URL_MARKET` | 21:30 UTC, weekdays |
| [`short_interest.py`](docs/short-interest.md) | `shortinterest.yml` | `WEBHOOK_URL_MARKET` | Daily check, posts ~2x/month |
| [`regsho_volume.py`](docs/regsho-volume.md) | `regsho.yml` | `WEBHOOK_URL_MARKET` | 23:00 UTC, weekdays |
| [`ftd_monitor.py`](docs/fails-to-deliver.md) | `ftd.yml` | `WEBHOOK_URL_MARKET` | Daily check, posts ~2x/month |
| [`threshold_list.py`](docs/threshold-list.md) | `threshold.yml` | `WEBHOOK_URL_ALERTS` | 05:15 UTC Tue–Sat, posts only on a change |
| [`comment_letters.py`](docs/comment-letters.md) | `letters.yml` | `WEBHOOK_URL` | 13:30 UTC weekdays, posts only on a change |
| [`dilution.py`](docs/dilution.md) | `dilution.yml` | `WEBHOOK_URL_MARKET` | 15:00 UTC weekdays, posts only on a change |
| [`crossings.py`](docs/crossings.md) | `crossings.yml` | `WEBHOOK_URL_ALERTS` | 21:45 UTC weekdays, posts only on a crossing |
| [`grid_context.py`](docs/grid-context.md) | `grid.yml` | `WEBHOOK_URL_MARKET` | 21:20 UTC, weekdays |
| [`weekly_digest.py`](docs/weekly-digest.md) | `digest.yml` | `WEBHOOK_URL_DIGEST` | 17:00 UTC daily, posts once per ISO week |
| [`holder_events.py`](docs/holder-events.md) | `holders-events.yml` | `WEBHOOK_URL_INSIDER` | 13:45 UTC weekdays, posts only on an event |

They are deliberately separate workflows: a failure in one data provider must
not take down the others. The context posts 15 minutes before the recap so it
lands above the performance table in the channel.

**One roster, nine consumers.** Which companies are tracked, and how they are
identified, lives once in [`watchlist.py`](docs/watchlist.md). Adding a company
is one record. Each component derives the shape it needs — symbols, CIKs,
CUSIPs, former tickers, IR feeds — so the same company cannot be spelled two
ways or aliased in two directions.

**They do not share a sense of "now."** Latency runs from minutes for the press
monitor to two-to-six weeks for
[fails to deliver](docs/fails-to-deliver.md), whose data the SEC publishes
twice a month well after the fact. Each post carries its own timing in the
footer, because a stale figure read as a live one is the easiest mistake this
channel invites.

**What was tried and rejected is recorded too.**
[`docs/rejected.md`](docs/rejected.md) carries the ideas that were measured and
closed, with the numbers that closed them. Check it before probing something —
it exists to stop a re-probe six months later.

## Output width

Every monospace block is kept to **≤28 characters**. Discord mobile wraps code
blocks past roughly that width, and a wrapped table splits each row across two
lines and becomes unreadable. The earnings calendar was originally 52 characters
wide and the recap 47; both were rebuilt narrower rather than accepting the
wrap. When adding a column, something else has to give.

## Layout

```
press_monitor.py                  press release / filing monitor
daily_recap.py                    post-close market recap
btc_context.py                    bitcoin network context
earnings_calendar.py              projected reporting dates
volume_spike.py                   intraday unusual-volume alerts
short_interest.py                 twice-monthly FINRA short interest
regsho_volume.py                  daily FINRA short sale volume
weekly_digest.py                  weekly digest: derivation and verdict record
digest_render.py                  weekly digest: the post and the file
watchlist.py                      the roster: one record per company
earnings_dates.py                 shared: announced reporting dates, stored by CIK
page_text.py                      shared: a page's HTML reduced to readable text
filer_regime.py                   shared: which regime each company files under
build_snapshot.py                 writes snapshot.json from each issuer's filing index
audit_identifiers.py              maintenance: what each company trades as
calibrate_staleness.py            maintenance: publication cadence per source
audit_8k_items.py                 maintenance: 8-K item distribution
check_metric_regime.py            maintenance: is a metric's move real or a regime shift
probe_sites.py                    maintenance: grid operators and states a filing names
probe_holders.py                  maintenance: what 13D/G filings carry
probe_proxy_shares.py             maintenance: does a proxy propose more authorized shares
probe_body_dates.py               maintenance: what a release body offers
probe_filing_rate.py              maintenance: would a filing rate catch a company going quiet
probe_form_144.py                 maintenance: does Form 144 precede the Form 4
probe_premarket.py                maintenance: is a missing premarket the feed, request or venue
probe_spike_norm.py               maintenance: reproduce the spike normalisation gain
probe_undated_items.py            maintenance: date material each IR source offers
loop_state.py                     loop harness: the state file, one writer
loop_approval.py                  loop harness: has this irreversible action been authorised
loop_verdict.py                   loop harness: validate a gate verdict, trusting none of it
score_gate.py                     loop harness: score recorded verdicts against known answers
holder_events.py                  >5% holder arrivals, changes and exits
ftd_monitor.py                    SEC fails-to-deliver
threshold_list.py                 Reg SHO threshold list (exception report)
comment_letters.py                SEC review correspondence
dilution.py                       shares outstanding / ATM issuance
crossings.py                      52-week high/low crossings
grid_context.py                   grid demand and natural gas
.github/workflows/monitor.yml     monitor schedule and runner setup
.github/workflows/recap.yml       recap schedule and runner setup
.github/workflows/btc.yml         context schedule and runner setup
.github/workflows/earnings.yml    calendar schedule and runner setup
.github/workflows/spikes.yml      spike schedule and runner setup
.github/workflows/shortinterest.yml  short interest schedule and runner setup
.github/workflows/regsho.yml      short volume schedule and runner setup
.github/workflows/ftd.yml         FTD schedule and runner setup
.github/workflows/threshold.yml   threshold schedule and runner setup
.github/workflows/letters.yml     comment letter schedule and runner setup
.github/workflows/dilution.yml    dilution schedule and runner setup
.github/workflows/crossings.yml   crossings schedule and runner setup
.github/workflows/grid.yml        grid context schedule and runner setup
.github/workflows/digest.yml      digest schedule and runner setup
.github/workflows/holders-events.yml  holder event schedule and runner setup
.github/workflows/snapshot.yml    snapshot rebuild schedule; writes a file, posts nothing
.github/workflows/sites.yml       operating footprint sweep, manual only
.github/workflows/audit.yml       identifier audit, manual only
.github/workflows/calibrate.yml   staleness calibration, manual only
.github/workflows/probe-body-dates.yml  body-date probe, manual only
.github/workflows/items.yml       8-K item audit, manual only
.github/workflows/metric-regime.yml  metric regime check, manual only
.github/workflows/holders.yml     13D/G content probe, manual only
.github/workflows/probe-proxy-shares.yml  proxy share-count probe, manual only
.github/workflows/filing-rate.yml  filing rate probe, manual only
.github/workflows/probe-form-144.yml  Form 144 lead-time probe, manual only
.github/workflows/premarket.yml   premarket probe, manual only
.github/workflows/spike-norm.yml  spike normalisation probe, manual only
.github/workflows/probe-undated-items.yml  undated item census, manual only
.github/workflows/regime.yml      filing regime census, manual only
.github/workflows/baseline-test.yml  baseline rule test, manual only
.github/workflows/failure-notice.yml  fires on a watched workflow finishing; posts failures to ops
.github/workflows/workflow-list-gate.yml  fails a push that adds a workflow nothing watches
.github/workflows/tests.yml       every module parses and imports, then the eight offline suites; on every push touching Python
spike_state.json                  auto-generated; per-day alert tiers
shortinterest_state.json          auto-generated; last posted settlement date
regsho_state.json                 auto-generated; last posted trade date
ftd_state.json                    auto-generated; last posted period, learned CUSIPs
threshold_state.json              auto-generated; companies currently listed
letters_state.json                auto-generated; accessions seen in the window
dilution_state.json               auto-generated; last reported share count
crossings_state.json              auto-generated; armed flags per ticker
holder_state.json                 auto-generated; accessions seen, last percent per filer group
state.json                        auto-generated; do not hand-edit except to reset
earnings_dates.json               auto-generated; announced reporting dates by CIK
docs/                             per-component documentation
digest/                           auto-generated; one file per ISO week, never rewritten
docs/local-workflow.md            working from a clone; state-file merges
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
| `TWELVEDATA_KEY` | *Optional fallback only.* Its free tier lags intraday — see [data sources](docs/recap.md#data-sources--and-why). |
| `WEBHOOK_URL_ALERTS` | *Optional.* Webhook for the volume alerts channel. Falls back to `WEBHOOK_URL_MARKET` if unset. |
| `WEBHOOK_URL_DIGEST` | Webhook for the weekly digest channel. |
| `EIA_API_KEY` | Free key from <https://www.eia.gov/opendata/register.php>. Used only by the grid context. |

**Secrets must also be mapped in the workflow that needs them.** Adding one
under repository settings is not enough — it has to be listed in the `env:`
block of the run step in that workflow's YAML, or the script never sees it. An
unmapped secret reads as an empty string, which most of these scripts treat as
"feature disabled" rather than an error, so the failure is silent.

Any component that reads sec.gov needs `SEC_USER_AGENT` in its own workflow's
`env:` block — mapping it once does not cover the others. `ftd.yml` includes
it.
