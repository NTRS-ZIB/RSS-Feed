# Press release monitor

Watches SEC EDGAR filings and company IR newsroom feeds for a list of tickers,
and posts anything new to a Discord channel via webhook. Runs on a GitHub
Actions cron — no server, no maintenance.

## Layout

```
press_monitor.py
.github/workflows/monitor.yml
state.json          <- created automatically on first run, do not edit by hand
```

## Required secrets

Settings → Secrets and variables → Actions:

| Secret | Value |
|---|---|
| `WEBHOOK_URL` | Your Discord webhook URL |
| `SEC_USER_AGENT` | Your name and email, e.g. `Jane Doe jane@example.com` — SEC throttles anonymous traffic |

## Configuring

Everything tunable sits in the CONFIG block at the top of `press_monitor.py`:

- `TICKERS` — the companies to watch. CIKs are resolved automatically.
- `IR_FEEDS` — label → RSS URL for company newsrooms.
- `FORM_TYPES` — `8-K` for US issuers, `6-K` for foreign private issuers.
- `PRESS_RELEASE_EXHIBIT_ONLY` — when true, only posts filings that attach an
  EX-99 exhibit, i.e. an actual press release rather than an administrative 8-K.
- `KEYWORDS` — optional title filter. Empty means post everything.

## First run

Posts nothing. It records a baseline of what already exists so you don't get
flooded with backlog. Every run after that posts only new items.

To force a live test, replace the contents of `state.json` with
`{"seen": [], "initialized": true}`, commit, and re-run the workflow.

## Known quirks

- GitHub disables scheduled workflows in repos with no activity for 60 days.
  It emails you first.
- Cron timing drifts under load; `*/15` is realistically 15–25 minutes.
- EDGAR trails the newswire by minutes to hours. The IR feeds are what catch a
  release close to when it actually drops.
