#!/usr/bin/env python3
"""
52-week high/low crossings -> Discord.

Alerts when a watchlist ticker closes beyond its own 52-week extreme. Silent
otherwise, which is most days.

WHY HYSTERESIS IS THE WHOLE DESIGN
A naive rule — "close above the prior 252-day high" — fires every session while
a stock grinds in one direction, and several of these do. Measured over 297
sessions of real bars, a naive rule produced 253 alerts across eleven tickers;
IREN alone accounted for 38 highs and ANY for 32 lows.

Alerting daily on the same move is not a signal, it is a stock ticker. So an
alert ARMS only once the price has returned to the middle of its range
(REARM_LOW..REARM_HIGH). The same measurement put that at 55 alerts — 78%
quieter, roughly one a week across the whole watchlist.

WHAT A CROSSING IS AND IS NOT
It is a closing price beyond the extreme of the prior 252 sessions. It is not
an intraday touch, and it is not adjusted for anything except splits and
dividends, which Alpaca handles via adjustment=all.

Note what these companies actually do: single-session moves of +112% (ANY),
+94% (SLNH) and +84% (NUAI) all occur inside the measured window, none of them
at a split date. A 52-week high here is a lower bar than it would be for an
ordinary equity, and the hysteresis is what keeps it meaningful.

THREE REASONS A TICKER IS ABSENT, NOT ONE
A company listed six weeks ago, a company whose feed failed, and a company that
has reported for years and returned three bars today are different findings.
They were one line — "No data this run" — which reads as a fault for all three.
See classify(). The distinction survives in the post, not only the log: a
reader looking at an absent ticker is asking the same question this component
answers correctly for every ticker it does report, where a window shorter than
WINDOW carries a `~`.

Companion to daily_recap.py, which shows position in the 52-week range as a
column every day. This fires only on the boundary, and to a different channel.
Both now mark a short window with `~` and name the tickers, so the claim that
the two cannot disagree about what "52 weeks" means holds for the missing case
as well as the present one — they previously agreed on the window and
disagreed on what to do when it was not there.

They still differ in one deliberate place: this component SKIPS a ticker below
MIN_BARS, because a crossing measured against 37 sessions is not a 52-week
crossing, while the recap keeps the row, because close, change and volume do
not depend on how much history sits behind them. Only its 52w column is
caveated.
"""

import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

import watchlist
from first_run import backfill_note, backfilled, baseline_by_cik, summary

# ------------------------------------------------------------------ CONFIG

# Trading sessions in the lookback. Matches daily_recap.py's `closes[-252:]`
# so the two cannot disagree about what "52 weeks" means.
WINDOW = 252

# Calendar days of bars to request. 430 comfortably covers 252 sessions plus
# weekends and holidays — measured, not assumed: every ticker came back with
# 297 bars, WYFI with 247 as a 2025 listing.
FETCH_DAYS = 430

# After an alert, suppress further alerts in that direction until the price has
# returned inside this band of its range. This is the noise control; see the
# module docstring for the measured effect.
REARM_LOW, REARM_HIGH = 25.0, 75.0

# Below this many bars a ticker has no usable window and is skipped entirely
# rather than compared against a few weeks of history.
MIN_BARS = 60

STATE_FILE = Path(os.environ.get("CROSSINGS_STATE", "crossings_state.json"))

# ----------------------------------------------------------------- RUNTIME

# Alerts channel, falling back to market data. A crossing is an event, which is
# why it does not ride along in the recap's daily table.
WEBHOOK_URL = (os.environ.get("WEBHOOK_URL_ALERTS", "").strip()
               or os.environ.get("WEBHOOK_URL_MARKET", "").strip())
ALPACA_KEY_ID = os.environ.get("ALPACA_KEY_ID", "").strip()
ALPACA_SECRET = os.environ.get("ALPACA_SECRET_KEY", "").strip()
DRY_RUN = os.environ.get("DRY_RUN", "").strip().lower() in ("1", "true", "yes")

ALPACA_BARS = "https://data.alpaca.markets/v2/stocks/bars"
ALPACA_FEED = "sip"
ALPACA_DELAY_MINUTES = 20

GREEN, RED, GREY = 0x3FB950, 0xF85149, 0x5A6672


# ------------------------------------------------------------------- STATE


def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except json.JSONDecodeError:
            pass
    return {}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=1, sort_keys=True))


# ------------------------------------------------------------------- FETCH


def fetch(symbols):
    """{symbol: [(date, close)]} oldest first, or None if the feed is refused."""
    out, token, pages = {}, None, 0
    now = datetime.now(timezone.utc)
    start = (now - timedelta(days=FETCH_DAYS)).date().isoformat()
    end = (now - timedelta(minutes=ALPACA_DELAY_MINUTES)).isoformat(
        timespec="seconds").replace("+00:00", "Z")
    while pages < 6:
        params = {"symbols": ",".join(symbols), "timeframe": "1Day",
                  "start": start, "end": end, "limit": 10000,
                  "feed": ALPACA_FEED, "adjustment": "all"}
        if token:
            params["page_token"] = token
        try:
            r = requests.get(ALPACA_BARS, params=params, timeout=(10, 30),
                             headers={"APCA-API-KEY-ID": ALPACA_KEY_ID,
                                      "APCA-API-SECRET-KEY": ALPACA_SECRET})
        except requests.RequestException as e:
            print(f"  Alpaca request failed: {type(e).__name__}")
            return None
        if r.status_code != 200:
            print(f"  Alpaca: HTTP {r.status_code} {r.text[:160]}")
            return None
        data = r.json()
        for sym, rows in (data.get("bars") or {}).items():
            out.setdefault(sym, []).extend(rows)
        token = data.get("next_page_token")
        pages += 1
        if not token:
            break

    series = {}
    for sym, rows in out.items():
        parsed = []
        for b in rows:
            try:
                parsed.append((
                    datetime.fromisoformat(b["t"].replace("Z", "+00:00")).date(),
                    float(b["c"])))
            except (KeyError, ValueError, TypeError):
                continue
        series[sym] = sorted(parsed)
    return series


# ---------------------------------------------------------------- ANALYSIS


def initial_flags(ticker, newly_watched, crossed):
    """The armed flags a ticker gets the first time it is stored.

    A NEWLY WATCHED TICKER IS DISARMED IN THE DIRECTION IT IS ALREADY
    CROSSING, and only that one. A company added while sitting above its
    52-week high did not cross anything while we were watching — the crossing
    predates the watch, so announcing it asserts an event that did not happen.

    DISARMING BOTH DIRECTIONS WOULD BE WORSE THAN THE BUG IT FIXES, and an
    earlier version of this did. Re-arming needs `REARM_LOW <= pos <=
    REARM_HIGH`, so a ticker added at 85% of its range — crossing nothing,
    suppressing nothing, logging nothing — would have `armed_hi` False and
    never recover it until the price fell back to 75%. A genuine breakout the
    next day, observed start to finish, would be silently dropped: the exact
    direction of failure this whole rule exists to avoid, reached without any
    unusual conditions.
    """
    if ticker not in newly_watched:
        return {"armed_hi": True, "armed_lo": True}
    return {"armed_hi": crossed != "H", "armed_lo": crossed != "L"}


def classify(ticker, rows, state):
    """Why a ticker produced no reading: 'ok', 'young', 'regressed' or 'nodata'.

    THESE ARE THREE DIFFERENT MEASUREMENTS AND WERE ONE LABEL. A company
    listed six weeks ago and a company whose price feed failed both used to
    appear as "No data this run", which reads as a fault in both cases. One of
    them is not a fault — it is a fact about the company, and the same kind of
    fact this component already reports for every ticker it does cover, where
    a window shorter than WINDOW gets a `~`. Below MIN_BARS the grading simply
    stopped and the ticker fell off the edge.

    'young' vs 'regressed' is the part that has to be right in the general
    case rather than for whichever company happens to be new today. Bar count
    alone cannot separate them: three bars looks identical whether the company
    listed on Tuesday or the feed returned a stub. STATE separates them. A
    ticker only gets an entry here once it has been assessed successfully, so
    an entry means it HAS had enough history — and a ticker that once had 300
    sessions and now has 3 has not become young. That is a source failure
    wearing a young company's shape, and it is reported as one.

    Returns (verdict, bars). `bars` is the count actually received, so the log
    and the post can state the measurement rather than assert an absence.
    """
    bars = len(rows)
    if bars == 0:
        return "nodata", 0
    if bars >= MIN_BARS:
        return "ok", bars
    # Seen before with a usable window, and now too short. Not youth.
    if state.get(ticker, {}).get("last_seen"):
        return "regressed", bars
    return "young", bars


def assess(rows):
    """Where today's close sits against the prior WINDOW sessions.

    The window EXCLUDES today, or today's close would be compared against
    itself and no crossing could ever be detected.
    """
    today, close = rows[-1]
    prior = rows[-(WINDOW + 1):-1]
    if len(prior) < MIN_BARS - 1:
        return None
    closes = [c for _, c in prior]
    hi, lo = max(closes), min(closes)
    rng = hi - lo

    # How many sessions back the prior extreme was set — a breakout of a
    # months-old high reads differently from one set last week.
    hi_ago = len(closes) - 1 - max(range(len(closes)), key=lambda i: closes[i])
    lo_ago = len(closes) - 1 - min(range(len(closes)), key=lambda i: closes[i])

    return {
        "date": today, "close": close, "hi": hi, "lo": lo,
        "pos": ((close - lo) / rng * 100) if rng else 50.0,
        "crossed": "H" if close > hi else ("L" if close < lo else None),
        "margin": ((close - hi) / hi * 100) if close > hi else
                  (((close - lo) / lo * 100) if close < lo else 0.0),
        "ago": hi_ago if close > hi else lo_ago,
        "bars": len(prior) + 1,
        "short": len(prior) + 1 < WINDOW,
    }


# ------------------------------------------------------------------ FORMAT


def build_table(rows):
    """Kept to 24 characters. See the output-width note in the README."""
    out = [f"{'':<5}{'Close':>7}{'':>2}{'Mgn':>7}{'Ago':>5}", "-" * 26]
    for r in rows:
        m = r["m"]
        mark = "~" if m["short"] else " "
        out.append(f"{r['ticker']:<5}{m['close']:>7.2f}{m['crossed']:>2}"
                   f"{m['margin']:>+6.1f}%{m['ago']:>4}{mark}")
    return "\n".join(out)


def build_embed(rows, missing, young=()):
    highs = [r for r in rows if r["m"]["crossed"] == "H"]
    lows = [r for r in rows if r["m"]["crossed"] == "L"]
    lines = [f"```\n{build_table(rows)}\n```"]

    for r in rows:
        m = r["m"]
        if m["crossed"] == "H":
            lines.append(f"**{r['ticker']}** closed {m['close']:.2f}, above its "
                         f"52-week high of {m['hi']:.2f} set {m['ago']} "
                         f"session(s) ago")
        else:
            lines.append(f"**{r['ticker']}** closed {m['close']:.2f}, below its "
                         f"52-week low of {m['lo']:.2f} set {m['ago']} "
                         f"session(s) ago")

    short = [r["ticker"] for r in rows if r["m"]["short"]]
    if short:
        lines.append(f"`~` under {WINDOW} sessions of history, so the window is "
                     f"shorter than 52 weeks: {', '.join(short)}")
    # Stated as a count against the floor, not as an absence. "SPCX 37/60" is a
    # measurement a reader can act on — it says the ticker is fine and roughly
    # when it starts reporting. "No data this run" said neither.
    if young:
        lines.append(
            "Too little history to assess, and not an error — "
            + ", ".join(f"**{t}** {n}/{MIN_BARS} sessions"
                        for t, n in sorted(young))
            + ".")
    if missing:
        lines.append(f"No data this run: {', '.join(sorted(missing))}")

    lines.append(
        f"_Closing prices, split-adjusted. Re-arms only once a ticker returns "
        f"to {REARM_LOW:.0f}–{REARM_HIGH:.0f}% of its range, so a stock grinding "
        f"to new extremes alerts once, not daily._")

    if highs and lows:
        colour = GREY
    elif highs:
        colour = GREEN
    else:
        colour = RED
    return {
        "title": "52-week crossings",
        "description": "\n".join(lines),
        "color": colour,
        "footer": {"text": f"Alpaca {ALPACA_FEED} · {len(highs)} high(s), "
                           f"{len(lows)} low(s) · {WINDOW}-session window"},
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


# -------------------------------------------------------------------- MAIN


def main():
    if DRY_RUN:
        print("DRY RUN — nothing posted, state not saved.\n")
    elif not WEBHOOK_URL:
        sys.exit("No webhook set (WEBHOOK_URL_ALERTS or WEBHOOK_URL_MARKET).")
    if not (ALPACA_KEY_ID and ALPACA_SECRET):
        sys.exit("ALPACA_KEY_ID and ALPACA_SECRET_KEY must both be set.")

    for problem in watchlist.validate():
        print(f"WARNING: watchlist.py — {problem}")

    tickers = watchlist.tickers()
    print(f"Fetching {FETCH_DAYS} days of bars for {len(tickers)} tickers...")
    series = fetch(tickers)
    if series is None:
        sys.exit("No data from Alpaca. Not posting.")

    state = load_state()
    first_run = not STATE_FILE.exists()
    # Consulted below when a ticker's armed flags are created for the first
    # time. `first_run` covers a cold start; this covers a company added to a
    # roster the component has been watching for months, which is the shape
    # that cost holder_events 86 posts on 2026-08-14.
    backfill = backfilled(state)
    newly_watched = set(baseline_by_cik(state, watchlist.ciks()))
    if backfill:
        print("\n" + backfill_note("crossings", len(tickers)))
    if newly_watched:
        print()
        print(summary("crossings", sorted(newly_watched)))
    crossed, missing, young, rearmed = [], [], [], []

    for ticker in sorted(tickers):
        rows = series.get(ticker, [])
        verdict, bars = classify(ticker, rows, state)
        if verdict == "young":
            print(f"  {ticker}: {bars} of {MIN_BARS} session(s) — too little "
                  f"history yet, not an error")
            young.append((ticker, bars))
            continue
        if verdict == "regressed":
            print(f"  {ticker}: {bars} bar(s), but it has reported before — "
                  f"treating as a source failure, not a young listing")
            missing.append(ticker)
            continue
        if verdict == "nodata":
            print(f"  {ticker}: no bars returned")
            missing.append(ticker)
            continue
        m = assess(rows)
        if not m:
            # Unreachable while assess() and classify() share MIN_BARS, and
            # kept so they cannot drift apart silently.
            print(f"  {ticker}: {bars} bar(s) but assess() declined — "
                  f"MIN_BARS disagrees between classify() and assess()")
            missing.append(ticker)
            continue

        st = state.setdefault(ticker,
                              initial_flags(ticker, newly_watched, m["crossed"]))

        # Re-arm first: a ticker that has come back through the middle of its
        # range is eligible again, including on the same run it crosses.
        if REARM_LOW <= m["pos"] <= REARM_HIGH:
            if not (st["armed_hi"] and st["armed_lo"]):
                rearmed.append(ticker)
            st["armed_hi"] = st["armed_lo"] = True

        fires = False
        if m["crossed"] == "H" and st["armed_hi"]:
            fires, st["armed_hi"] = True, False
        elif m["crossed"] == "L" and st["armed_lo"]:
            fires, st["armed_lo"] = True, False

        flag = m["crossed"] or "-"
        note = "ALERT" if fires else ("suppressed" if m["crossed"] else "")
        print(f"  {ticker}: {m['close']:>8.2f}  {m['pos']:>5.1f}% of range  "
              f"{flag}  {note}")
        if fires:
            crossed.append({"ticker": ticker, "m": m})
        st["last_seen"] = m["date"].isoformat()

    if rearmed:
        print(f"\n  re-armed (back inside {REARM_LOW:.0f}–{REARM_HIGH:.0f}%): "
              f"{', '.join(rearmed)}")
    if young:
        print(f"\n  too little history (under {MIN_BARS} sessions): "
              + ", ".join(f"{t} at {n}" for t, n in young))
    if missing:
        # Unlike dilution.py or comment_letters.py, a missing ticker does not
        # invert the meaning of this post. Those assert something about every
        # company; this one says "these crossed", which stays true. So it is
        # named and the run continues.
        print(f"  no usable data: {', '.join(missing)}")

    crossed.sort(key=lambda r: (r["m"]["crossed"], -abs(r["m"]["margin"])))

    print()
    if not crossed:
        print("No crossings." + ("  (no state file — first run)" if first_run else ""))
        if DRY_RUN:
            print("\nDry run: nothing crossed, so a post would have nothing "
                  "to show.")
        else:
            save_state(state)
        return 0

    print(build_table(crossed))
    embed = build_embed(crossed, missing, young)

    if DRY_RUN:
        print(f"\nDry run: would post {len(crossed)} crossing(s). "
              f"State not saved.")
        return 0

    if not post(embed):
        print("Post failed — state not saved, will retry next run.")
        return 1

    save_state(state)
    # Not len(state): it also carries the first-run `companies` record.
    print(f"\nState written: {STATE_FILE.name} "
          f"({sum(1 for k in state if k != 'companies')} tickers)")
    print(f"Posted {len(crossed)} crossing(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
