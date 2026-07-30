#!/usr/bin/env python3
"""
Intraday volume spike alerts -> Discord.

Alerts when a ticker's cumulative session volume crosses a multiple of its own
30-day average daily volume.

Data: Alpaca market data, free tier. No daily call cap.

Volume is accumulated from HOURLY bars, not daily bars. Alpaca's daily bars are
only emitted once the regular session opens, so before 9:30 ET there is no
daily bar for today and premarket activity is invisible. Hourly bars cover the
full extended session (4:00-20:00 ET), so premarket and after-hours volume are
both counted.

Both sides of the ratio are built the same way from the same bars. Comparing an
extended-hours session total against a regular-hours-only baseline would
inflate every ratio.

IMPORTANT — why the absolute numbers are not real volume:
The free tier serves the IEX feed only. IEX is a single exchange, a few percent
of consolidated US volume, so the share counts here are a fraction of true
volume. That is fine for this purpose because the alert is a RATIO: today's IEX
volume against the same ticker's 30-day IEX average. The exchange-share factor
appears in numerator and denominator and cancels.

This only holds if both sides come from the same feed. Never mix an IEX session
volume with a consolidated (SIP) average — the ratio becomes meaningless and
would fire constantly.
"""

import json
import os
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

try:
    from zoneinfo import ZoneInfo
    EASTERN = ZoneInfo("America/New_York")
except Exception:              # no tzdata available
    EASTERN = timezone(timedelta(hours=-4))

# ------------------------------------------------------------------ CONFIG

TICKERS = ["BGDE", "ANY", "NUAI", "SLNH", "DGXX", "BKKT",
           "MARA", "WYFI", "IREN", "CLSK", "VIP"]

# Alert tiers. Each ticker alerts at most once per tier per day, so a stock
# that keeps climbing escalates rather than spamming or going quiet.
TIERS = [1.5, 3.0, 5.0, 10.0]

# Trading days used for the baseline.
BASELINE_DAYS = 30

# Ignore tickers whose baseline is thinner than this — too noisy to trust.
MIN_BASELINE_BARS = 10

# Liquidity floors, in IEX shares. Some names trade only a few hundred shares a
# day on IEX, where one ordinary block is a 3x "spike". Two separate guards:
#   BASELINE — below this the average is statistically meaningless
#   ALERT    — a spike must also represent real activity, not 3x of nothing
MIN_BASELINE_VOLUME = 10_000
MIN_ALERT_VOLUME = 25_000

FEED = "iex"          # free tier. Must match on both sides; see module docstring.

# Calendar days fetched to yield ~30 sessions of hourly bars.
LOOKBACK_DAYS = 50

# Pagination guard. Raised well above the observed requirement; hitting it
# means the baseline is truncated, which the log now says explicitly.
MAX_PAGES = 40

# ------------------------------------------------------------------ RUNTIME

KEY_ID = os.environ.get("ALPACA_KEY_ID", "").strip()
SECRET = os.environ.get("ALPACA_SECRET_KEY", "").strip()
# Falls back to the market channel if no dedicated alerts webhook is set.
WEBHOOK_URL = (os.environ.get("WEBHOOK_URL_ALERTS", "").strip()
               or os.environ.get("WEBHOOK_URL_MARKET", "").strip())
DRY_RUN = os.environ.get("DRY_RUN", "").strip().lower() in ("1", "true", "yes")
STATE_FILE = Path(os.environ.get("SPIKE_STATE", "spike_state.json"))

DATA = "https://data.alpaca.markets/v2/stocks"
AUTH = {"APCA-API-KEY-ID": KEY_ID, "APCA-API-SECRET-KEY": SECRET}

UP, DOWN, FLAT = 0x3FB950, 0xF85149, 0x8B949E


def api(path, params):
    try:
        r = requests.get(f"{DATA}{path}", headers=AUTH, params=params,
                         timeout=(10, 30))
    except requests.RequestException as e:
        print(f"  request failed: {type(e).__name__}")
        return None
    if r.status_code != 200:
        print(f"  HTTP {r.status_code}: {r.text[:160]}")
        return None
    try:
        return r.json()
    except ValueError:
        print("  unparseable JSON")
        return None


def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except json.JSONDecodeError:
            pass
    return {"date": "", "alerted": {}}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=1))


def hourly_bars():
    """All hourly bars for the watchlist over the lookback window.

    Hourly bars span the extended session, so premarket and after-hours
    trades are included on both today's figure and the baseline.
    """
    start = (date.today() - timedelta(days=LOOKBACK_DAYS)).isoformat()
    bars, token, pages = defaultdict(list), None, 0

    while pages < MAX_PAGES:
        params = {
            "symbols": ",".join(TICKERS),
            "timeframe": "1Hour",
            "start": start,
            "limit": 10000,
            "feed": FEED,
            "adjustment": "all",
        }
        if token:
            params["page_token"] = token
        data = api("/bars", params)
        if not data:
            break
        for symbol, rows in (data.get("bars") or {}).items():
            bars[symbol].extend(rows)
        token = data.get("next_page_token")
        pages += 1
        if not token:
            break
    total = sum(len(v) for v in bars.values())
    print(f"  {pages} page(s), {total} bar(s)")
    if token:
        print(f"  WARNING: stopped at the {MAX_PAGES}-page limit with more "
              f"data available — baselines are truncated and ratios will be "
              f"overstated. Raise MAX_PAGES.")
    return bars


def daily_totals(rows):
    """Collapse hourly bars into {ET date: (volume, last close)}."""
    vols, closes = defaultdict(float), {}
    for b in rows:
        stamp, volume = b.get("t"), b.get("v")
        if not stamp or volume is None:
            continue
        try:
            ts = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        except ValueError:
            continue
        day = ts.astimezone(EASTERN).date()
        vols[day] += volume
        # Bars arrive in order, so the last write is the latest close.
        if b.get("c"):
            closes[day] = b["c"]
    return {d: (vols[d], closes.get(d)) for d in vols}


def build_metrics(bars):
    """Per ticker: today's volume, baseline, latest close, previous close.

    Returns (metrics, excluded) so the caller can distinguish a ticker that is
    missing data from one deliberately filtered out for illiquidity.
    """
    today = datetime.now(EASTERN).date()
    out, excluded = {}, {}
    for symbol, rows in bars.items():
        totals = daily_totals(rows)
        if today not in totals:
            print(f"  {symbol}: no bars yet today")
            continue

        history = sorted(d for d in totals if d < today)
        past = history[-BASELINE_DAYS:]
        if len(past) < MIN_BASELINE_BARS:
            print(f"  {symbol}: only {len(past)} baseline session(s) — skipping")
            continue

        volume, close = totals[today]
        base = sum(totals[d][0] for d in past) / len(past)
        if base <= 0:
            continue
        if base < MIN_BASELINE_VOLUME:
            print(f"  {symbol}: baseline {base:,.0f} shares/day on IEX — "
                  f"too illiquid for a reliable ratio, skipping")
            excluded[symbol] = base
            continue
        out[symbol] = {
            "volume": volume,
            "base": base,
            "close": close,
            "prev_close": totals[history[-1]][1] if history else None,
            "sessions": len(past),
        }
    return out, excluded


def tier_for(ratio):
    """Highest tier this ratio has crossed, or None."""
    crossed = [t for t in TIERS if ratio >= t]
    return max(crossed) if crossed else None


def evaluate(metrics, state):
    """Return alerts worth posting, updating state as it goes."""
    today = datetime.now(EASTERN).date().isoformat()
    if state.get("date") != today:
        state["date"] = today
        state["alerted"] = {}

    alerts = []
    for symbol, m in metrics.items():
        ratio = m["volume"] / m["base"]
        tier = tier_for(ratio)
        if tier is None:
            continue
        if m["volume"] < MIN_ALERT_VOLUME:
            continue          # 3x of almost nothing is still almost nothing
        if state["alerted"].get(symbol, 0) >= tier:
            continue          # already alerted at this level or higher today

        state["alerted"][symbol] = tier
        prev = m.get("prev_close")
        close = m.get("close")
        alerts.append({
            "symbol": symbol,
            "ratio": ratio,
            "tier": tier,
            "volume": m["volume"],
            "close": close,
            "pct": ((close - prev) / prev * 100) if (prev and close) else None,
        })
    return sorted(alerts, key=lambda a: a["ratio"], reverse=True)


def human(v):
    for div, suf in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if v >= div:
            return f"{v/div:.1f}{suf}"
    return f"{v:.0f}"


def build_embed(alerts):
    lines = []
    for a in alerts:
        move = f"{a['pct']:+.1f}%" if a["pct"] is not None else "n/a"
        lines.append(f"{a['symbol']:<6}{a['ratio']:>5.1f}x ADV   "
                     f"${a['close']:>8.2f}  {move:>7}   {human(a['volume']):>7}")

    return {
        "title": "Unusual volume",
        "description": (
            "Session volume against each ticker's own 30-day average, "
            "including premarket and after-hours.\n"
            "Share counts are IEX-only and far below consolidated volume — "
            "the ratio is the signal, not the absolute figure."
        ),
        "color": UP if any((a["pct"] or 0) > 0 for a in alerts) else DOWN,
        "fields": [{"name": "\u200b", "value": "```\n" + "\n".join(lines) + "\n```"}],
        "footer": {"text": "Alpaca IEX feed"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def post(embed):
    try:
        r = requests.post(WEBHOOK_URL, json={"embeds": [embed]}, timeout=25)
    except requests.RequestException as e:
        print(f"webhook failed: {type(e).__name__}")
        return False
    if r.status_code >= 300:
        print(f"webhook returned {r.status_code}: {r.text[:200]}")
        return False
    return True


def main():
    if not (KEY_ID and SECRET):
        sys.exit("ALPACA_KEY_ID / ALPACA_SECRET_KEY not set.")
    if DRY_RUN:
        print("DRY RUN — nothing will be posted.\n")
    elif not WEBHOOK_URL:
        sys.exit("No webhook set (WEBHOOK_URL_ALERTS or WEBHOOK_URL_MARKET).")

    print("Fetching hourly bars...")
    bars = hourly_bars()
    if not bars:
        sys.exit("No bar data returned.")

    metrics, excluded = build_metrics(bars)
    print(f"  {len(metrics)} ticker(s) with today's volume and a baseline")

    state = load_state()
    alerts = evaluate(metrics, state)

    # Always show the full picture in the log, not just what alerted.
    print("\nCurrent ratios (incl. extended hours):")
    firing = {a["symbol"] for a in alerts}
    for symbol in TICKERS:
        m = metrics.get(symbol)
        if not m:
            if symbol in excluded:
                print(f"  {symbol:<6}   excluded — {excluded[symbol]:,.0f} "
                      f"shares/day baseline, below the {MIN_BASELINE_VOLUME:,} "
                      f"floor")
            else:
                print(f"  {symbol:<6}   no data")
            continue
        mark = "*" if symbol in firing else " "
        print(f" {mark}{symbol:<6}{m['volume']/m['base']:>6.2f}x   "
              f"({human(m['volume'])} vs {human(m['base'])} avg, "
              f"{m['sessions']}d)")

    if not alerts:
        print("\nNothing above threshold.")
        save_state(state)
        return

    embed = build_embed(alerts)
    print(f"\n{len(alerts)} alert(s):")
    print(embed["fields"][0]["value"])

    if DRY_RUN:
        print("Dry run — state not saved, nothing posted.")
        return

    if post(embed):
        save_state(state)
        print(f"Posted {len(alerts)} alert(s).")
    else:
        sys.exit("Post failed; state not saved so it retries next run.")


if __name__ == "__main__":
    main()
