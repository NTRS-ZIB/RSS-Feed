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
watchlist.py                      the roster: one record per company
ftd_monitor.py                    SEC fails-to-deliver
threshold_list.py                 Reg SHO threshold list (exception report)
.github/workflows/monitor.yml     monitor schedule and runner setup
.github/workflows/recap.yml       recap schedule and runner setup
.github/workflows/btc.yml         context schedule and runner setup
.github/workflows/earnings.yml    calendar schedule and runner setup
.github/workflows/spikes.yml      spike schedule and runner setup
.github/workflows/shortinterest.yml  short interest schedule and runner setup
.github/workflows/regsho.yml      short volume schedule and runner setup
.github/workflows/ftd.yml         FTD schedule and runner setup
.github/workflows/threshold.yml   threshold schedule and runner setup
spike_state.json                  auto-generated; per-day alert tiers
shortinterest_state.json          auto-generated; last posted settlement date
regsho_state.json                 auto-generated; last posted trade date
ftd_state.json                    auto-generated; last posted period, learned CUSIPs
threshold_state.json              auto-generated; companies currently listed
state.json                        auto-generated; do not hand-edit except to reset
docs/                             per-component documentation
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

**Secrets must also be mapped in the workflow that needs them.** Adding one
under repository settings is not enough — it has to be listed in the `env:`
block of the run step in that workflow's YAML, or the script never sees it. An
unmapped secret reads as an empty string, which most of these scripts treat as
"feature disabled" rather than an error, so the failure is silent.

Any component that reads sec.gov needs `SEC_USER_AGENT` in its own workflow's
`env:` block — mapping it once does not cover the others. `ftd.yml` includes
it.
