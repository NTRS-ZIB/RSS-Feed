#!/usr/bin/env python3
"""
Intraday volume spike alerts -> Discord.

Alerts when a ticker's cumulative session volume crosses a multiple of its own
30-day average daily volume.

Data: Alpaca market data, free tier. No daily call cap.

Volume is accumulated from HOURLY bars, not daily bars, and the reason is
intraday granularity: a daily bar gives one number at the close, while this
component has to answer "how much has traded so far" at every fire.

IT IS NOT FOR PREMARKET, AND THE ORIGINAL RATIONALE HERE WAS WRONG. This
docstring used to say hourly bars were chosen because "before 9:30 ET there is
no daily bar for today and premarket activity is invisible — exactly the case
most worth alerting on". Measured 2026-08-07 over 30 sessions:

    IEX   bars from 08:00 to 16:59 ET, and 08:00 is 1-9 sessions of 23.
          Effectively 09:00-15:59. Volume before 09:00: 0.02%.
    SIP   bars from 04:00 to 19:59 ET, 23 of 23 sessions at every hour.
          Volume before 09:00: 1.71%, after 16:00: 7.38%.

So the trades exist and IEX was not part of them — IEX does not operate before
08:00 ET. It is the VENUE, not the request and not Alpaca's serving: the
request carries no `end`, no window boundary and no extended-hours parameter.

And the claim was never true here rather than surviving a feed change: the
premarket rationale and `FEED = "iex"` were introduced in the same commit.

THE CONSEQUENCE FOR THE SCHEDULE is in spikes.yml — a window opening at 07:00
UTC spent its first five or six fires every day on an empty feed.

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
from datetime import date, datetime, time as dtime, timedelta, timezone
from pathlib import Path

import requests

import watchlist

try:
    from zoneinfo import ZoneInfo
    EASTERN = ZoneInfo("America/New_York")
except Exception:              # no tzdata available
    EASTERN = timezone(timedelta(hours=-4))
# ------------------------------------------------------------------ CONFIG

# The watchlist lives in watchlist.py — one record per company, one edit to add
# one. A list: this component uses symbols only.
TICKERS = watchlist.tickers()

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

# The session-normalised measure starts here, in Eastern hours. Not a
# preference — see ratio_for(). IEX trades 09:00-15:59, so this withholds
# normalisation from one hour in seven, and it is the hour the thin-day
# measurement flagged.
NORMALISE_FROM_HOUR = 10

# A NORMALISED alert must rest on at least this much absolute volume, over and
# above MIN_ALERT_VOLUME. Derived rather than chosen: it is the 10th percentile
# of the volume behind alerts the FULL-SESSION measure raises, so a normalised
# alert can never rest on less than an ordinary one does. Set from the
# measurement in probe_spike_norm.py; the value is recorded in
# docs/volume-spikes.md with the distribution it came from.
# Measured 2026-08-07 over 60 sessions: the volume behind 298 full-session
# alerts runs p10 46,880 / p25 105,080 / p50 616,713. The 10th percentile is
# the floor, so a normalised alert never rests on less absolute volume than an
# ordinary one typically does.
#
# IT IS NOT A SUBSTITUTE FOR THE GATE and the measurement says so: alone it
# blocks only 12 of the 149 alerts an ungated 09:00 would raise. The gate stops
# the hour; the floor stops the thin ones anywhere. Both, doing different jobs.
MIN_NORMALISED_VOLUME = 46_880

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

    Both sides of every ratio are built from these same bars, so whatever
    hours IEX happens to carry appear in numerator and denominator alike. On
    this feed that is 09:00-15:59 ET; see the module docstring.
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


def slot_totals(rows):
    """{ET date: {hour: volume}} — the intraday profile.

    hourly_bars() has always fetched this and daily_totals() has always thrown
    it away on the next line. The session-normalised baseline below needs no
    new request for that reason: it is a change to how already-fetched data is
    aggregated, not a new fetch, so there is no cache and no staleness.
    """
    out = defaultdict(lambda: defaultdict(float))
    for b in rows:
        stamp, volume = b.get("t"), b.get("v")
        if not stamp or volume is None:
            continue
        try:
            ts = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        except ValueError:
            continue
        et = ts.astimezone(EASTERN)
        out[et.date()][et.hour] += volume
    return out


def elapsed_through(day_slots, hour):
    """Volume from the session open through `hour` inclusive."""
    return sum(v for h, v in day_slots.items()
               if SESSION_OPEN.hour <= h <= hour)


def ratio_for(volume, hour, slot_base, full_base):
    """(ratio, basis) — the gated session-normalised measure.

    THE COMPONENT UNDERSTATES ALL DAY, because it divides a partial session by
    a full-session mean. Measured over 60 sessions: a normalised measure
    reaches 151 tiers this one never does, and catches 129 more a median of
    four hours earlier, across 17 of 19 tickers.

    SO WHY IS IT GATED. The gain concentrates in the first hour, and the first
    hour is where the denominator is one venue's opening sixty minutes. BKKT
    read 16.8x on 35,588 shares at 09:00 — comfortably over MIN_ALERT_VOLUME,
    and not a spike. The understatement is at least conservative in the
    direction that avoids that; removing it wholesale removes the protection
    too.

    The gate costs little because of what the feed actually is. IEX trades
    09:00-15:59, seven hours, so holding the first hour back on the old
    denominator withholds normalisation from ONE HOUR IN SEVEN rather than
    from a whole morning.

    Falls back to the full-session denominator whenever the slot baseline is
    too thin to lean on — 55% of (ticker, hour) cells fail that test across
    the roster, and every one of them sits outside 09:00-15:00.
    """
    full = sum(full_base) / len(full_base) if full_base else 0
    if hour >= NORMALISE_FROM_HOUR and len(slot_base) >= MIN_BASELINE_BARS:
        mean_slot = sum(slot_base) / len(slot_base)
        if mean_slot > 0:
            return volume / mean_slot, "normalised"
    return (volume / full if full else 0), "full-session"


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
        # The per-slot baseline for the hour this fire lands in. Built from
        # the same bars already in hand; see slot_totals().
        hour = datetime.now(EASTERN).hour
        slots = slot_totals(rows)
        slot_base = [elapsed_through(slots.get(d, {}), hour) for d in past]
        slot_base = [v for v in slot_base if v > 0]
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
            "slot_base": slot_base,
            "full_base": [totals[d][0] for d in past if totals[d][0] > 0],
            "hour": hour,
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
        ratio, basis = ratio_for(m["volume"], m["hour"], m["slot_base"],
                                 m["full_base"])
        m["basis"] = basis
        m["ratio"] = ratio
        tier = tier_for(ratio)
        if tier is None:
            continue
        if m["volume"] < MIN_ALERT_VOLUME:
            continue          # 3x of almost nothing is still almost nothing
        # The normalised measure divides by a smaller number, so it needs a
        # higher absolute floor. Derived, not chosen — see the constant.
        if basis == "normalised" and m["volume"] < MIN_NORMALISED_VOLUME:
            continue
        if state["alerted"].get(symbol, 0) >= tier:
            continue          # already alerted at this level or higher today

        state["alerted"][symbol] = tier
        prev = m.get("prev_close")
        close = m.get("close")
        alerts.append({
            "symbol": symbol,
            "ratio": ratio,
            "basis": basis,
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


# THE IEX TRADING DAY, in Eastern — not the extended session.
#
# This was 04:00-20:00, the extended session, and that is the wrong
# denominator for this feed. Measured over 30 sessions: IEX carries 0.02% of
# its volume before 09:00 and 0.00% after 16:00, so a reading at 15:55 was
# reported as "74% through the session" when it was within five minutes of the
# last bar of the day.
#
# A footer stating a false denominator is worse than no footer, because it
# reads as precision. The whole point of it is to say where in the session the
# number was taken, and 04:00-20:00 is not the session the number came from.
SESSION_OPEN = dtime(9, 0)
SESSION_CLOSE = dtime(16, 0)


def session_position(now=None):
    """(Eastern clock, fraction of the extended session elapsed).

    THE RATIO MEANS SOMETHING DIFFERENT AT EVERY HOUR AND THE POST NEVER SAID
    SO. Today's figure is a running total over a session still in progress; the
    baseline is thirty COMPLETE sessions. So the ratio is scaled by however
    much of the day has happened — 1.5x at 09:45 and 1.5x at 15:55 are not the
    same measurement, and a reader had no way to tell which one they were
    looking at.

    Every other component in this repo states its own latency in the footer.
    This one stated its feed and not its position in the session, which is the
    same omission wearing different clothes.

    Clamped at both ends. The window opens at 07:00 UTC, which is 03:00 ET in
    EDT, so a fire can genuinely land before the session opens — that reads as
    0%, which is true rather than an error.
    """
    now = now or datetime.now(EASTERN)
    start = datetime.combine(now.date(), SESSION_OPEN, tzinfo=EASTERN)
    end = datetime.combine(now.date(), SESSION_CLOSE, tzinfo=EASTERN)
    span = (end - start).total_seconds()
    elapsed = (now - start).total_seconds()
    return now.strftime("%H:%M"), max(0.0, min(1.0, elapsed / span))


def build_embed(alerts):
    # Kept under ~28 chars: Discord mobile wraps code blocks past that.
    # The IEX share count is deliberately omitted — it is a fraction of
    # consolidated volume and would invite misreading. The ratio is the signal.
    lines = []
    for a in alerts:
        move = f"{a['pct']:+.1f}%" if a["pct"] is not None else "n/a"
        lines.append(f"{a['symbol']:<5}{a['ratio']:>5.1f}x"
                     f"{a['close']:>8.2f}{move:>8}")
    clock, pct = session_position()
    bases = {a.get("basis", "full-session") for a in alerts}
    basis_note = ("same-hour averages" if bases == {"normalised"}
                  else "full-session averages" if bases == {"full-session"}
                  else "mixed baselines, see the log")
    # A COMPLETE SESSION IS NOT "100% THROUGH" ONE, and the two must not print
    # the same string. `{pct:.0%}` rounded 99.9% up, so a reading one minute
    # before the close was textually identical to one taken after it — and
    # telling those apart is exactly what docs/volume-spikes.md now asks a
    # reader to do when deciding whether a late run is worth dispatching.
    #
    # int() floors, so 99.9% reads 99% and only a genuinely finished session
    # reaches the other branch.
    elapsed = ("the complete 09:00-16:00 IEX day" if pct >= 1.0
               else f"{int(pct * 100)}% through the 09:00-16:00 IEX day")

    return {
        "title": "Unusual volume",
        "description": (
            "Session volume vs each ticker's own 30-day average, "
            "including extended hours. Ratio is the signal — IEX share "
            "counts are far below consolidated volume."
        ),
        "color": UP if any((a["pct"] or 0) > 0 for a in alerts) else DOWN,
        "fields": [{"name": "\u200b", "value": "```\n" + "\n".join(lines) + "\n```"}],
        # In the FOOTER, not the block. The monospace table is held to 28
        # characters and check_post()-style width rules bite there; the footer
        # is prose and has no such ceiling.
        # WHICH BASELINE, because the two answer different questions and the
        # reader cannot tell from the number. A normalised ratio compares
        # elapsed volume against the same elapsed fraction of prior sessions;
        # the full-session one compares it against their totals and therefore
        # understates. Before 10:00 ET, and wherever the slot baseline is too
        # thin, the second is used — see ratio_for().
        "footer": {"text": f"Alpaca IEX feed · read {clock} ET, {elapsed}, "
                           f"against {basis_note}"},
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
    print("\nCurrent ratios (IEX day, 09:00-15:59 ET):")
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
        # THE RATIO THE ALERT PATH USES, not a second one computed here.
        # evaluate() writes it back onto the metric, so the log cannot drift
        # from what fired — which it would have, silently, on any fire before
        # the two measures converge at the close.
        ratio = m.get("ratio", m["volume"] / m["base"])
        basis = m.get("basis", "full-session")
        print(f" {mark}{symbol:<6}{ratio:>6.2f}x   "
              f"({human(m['volume'])} vs {human(m['base'])} avg, "
              f"{m['sessions']}d, {basis})")

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
