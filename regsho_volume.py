#!/usr/bin/env python3
"""
Reg SHO daily short sale volume -> Discord.

FINRA publishes daily short sale volume per security. This posts once per new
trade date, showing each ticker's short volume as a share of its total reported
volume, alongside its own trailing average.

Data: FINRA Query API, group `otcMarket`, dataset `regShoDaily`. No auth.

WHAT THIS IS NOT
Short VOLUME is not short INTEREST. Short interest is a position: shares
actually held short. Short volume is a flow: shares sold short during a
session, most of which are closed the same day.

A large share of daily short volume is market-maker hedging. When you buy, the
market maker sells to you and books it as a short, then flattens. Ratios in the
40-60% range are ORDINARY for a liquid stock and say nothing about sentiment.

This is the single most misread number in retail market data. The report is
therefore built around each ticker's deviation from ITS OWN trailing average,
not the absolute ratio, and the embed says so on every post.

Companion to short_interest.py: that one is a position, published twice monthly
with a two-week lag. This one is a flow, published daily. Neither substitutes
for the other.
"""

import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

import watchlist
# ------------------------------------------------------------------ CONFIG

# The watchlist lives in watchlist.py — one record per company, one edit to add
# one. These two names are DERIVED, not restated: these three components need
# canonical -> [former symbols], while ftd_monitor.py needs the exact inverse.
# Hand-maintaining both directions is how GREE was once mapped to Soluna,
# merging two companies' data under a plausible number with no error anywhere.
TICKERS = watchlist.names()            # {ticker: display name}
ALIASES = watchlist.alt_by_ticker()    # {ticker: [former or pending symbols]}

# Calendar days of history to pull. Needs to comfortably cover BASELINE_DAYS
# of trading sessions plus weekends and holidays.
LOOKBACK_DAYS = 45

# Trading sessions used for each ticker's trailing average ratio.
BASELINE_DAYS = 20

# Flag a ticker whose ratio deviates this far from its own trailing average,
# IN EITHER DIRECTION. Points, not percent — 45% to 60% is 15 points.
#
# Falls matter as much as rises. A sharp drop in the short volume ratio after
# a run-up can mean shorts have stopped pressing, which is information; only
# flagging rises would hide half the signal.
NOTABLE_DELTA_POINTS = 12.0

# Ignore sessions thinner than this; tiny volume makes meaningless ratios.
MIN_TOTAL_VOLUME = 25_000

# Stop and complain rather than posting stale data as current.
STALE_WARN_DAYS = 10

# ------------------------------------------------------------------ RUNTIME

WEBHOOK_URL = os.environ.get("WEBHOOK_URL_MARKET", "").strip()
DRY_RUN = os.environ.get("DRY_RUN", "").strip().lower() in ("1", "true", "yes")
STATE_FILE = Path(os.environ.get("SHO_STATE", "regsho_state.json"))

DATASET = "regShoDaily"
API = f"https://api.finra.org/data/group/otcMarket/name/{DATASET}"
METADATA = f"https://api.finra.org/metadata/group/otcMarket/name/{DATASET}"
HEADERS = {"Content-Type": "application/json", "Accept": "application/json"}

# Field names vary between FINRA datasets and are not guessable. These are
# probed in order; if none match, the real schema is printed from /metadata.
SYMBOL_FIELDS = [
    "securitiesInformationProcessorSymbolIdentifier",
    "symbolCode",
    "issueSymbolIdentifier",
]
DATE_FIELDS = ["tradeReportDate", "tradeDate", "reportDate", "settlementDate"]
SHORT_FIELDS = ["shortParQuantity", "shortQuantity", "shortVolume"]
EXEMPT_FIELDS = ["shortExemptParQuantity", "shortExemptQuantity"]
TOTAL_FIELDS = ["totalParQuantity", "totalQuantity", "totalVolume"]

UP, DOWN, FLAT = 0x3FB950, 0xF85149, 0x8B949E


def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except json.JSONDecodeError:
            pass
    return {"last_trade_date": ""}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=1))


def query_symbols():
    out = list(TICKERS)
    for alts in ALIASES.values():
        out.extend(alts)
    return out


def canonical(symbol):
    symbol = (symbol or "").upper()
    if symbol in TICKERS:
        return symbol
    for ticker, alts in ALIASES.items():
        if symbol in (a.upper() for a in alts):
            return ticker
    return None


def show_schema():
    try:
        r = requests.get(METADATA, timeout=(10, 30))
        if r.status_code != 200:
            print(f"  (metadata returned HTTP {r.status_code})")
            return
        meta = r.json()
    except (requests.RequestException, ValueError) as e:
        print(f"  (metadata lookup failed: {type(e).__name__})")
        return
    fields = []
    if isinstance(meta, dict):
        for key in ("fields", "columns", "datasetFields"):
            if isinstance(meta.get(key), list):
                fields = meta[key]
                break
    names = [f.get("name") or f.get("fieldName") if isinstance(f, dict) else str(f)
             for f in fields]
    if names:
        print(f"  Dataset '{DATASET}' fields:")
        for n in sorted(n for n in names if n):
            print(f"    {n}")
    else:
        print(f"  Raw metadata: {json.dumps(meta)[:800]}")


def fetch_with(symbol_field):
    """One attempt. Returns (rows, should_try_next_field)."""
    since = (date.today() - timedelta(days=LOOKBACK_DAYS)).isoformat()
    payload = {
        "compareFilters": [{"fieldName": DATE_FIELDS[0],
                            "compareType": "gte", "fieldValue": since}],
        "domainFilters": [{"fieldName": symbol_field,
                           "values": query_symbols()}],
        "limit": 20000,
    }
    try:
        r = requests.post(API, headers=HEADERS, json=payload, timeout=(10, 45))
    except requests.RequestException as e:
        print(f"request failed: {type(e).__name__}")
        return None, False

    if r.status_code in (401, 403):
        print(f"HTTP {r.status_code} — this dataset needs credentials.")
        return None, False
    if r.status_code == 400 and "not available in this dataset" in r.text:
        return None, True
    if r.status_code != 200:
        print(f"HTTP {r.status_code}: {r.text[:200]}")
        return None, False
    try:
        return r.json(), False
    except ValueError:
        print("unparseable JSON")
        return None, False


def fetch():
    for field in SYMBOL_FIELDS:
        rows, retry = fetch_with(field)
        if rows is not None:
            if field != SYMBOL_FIELDS[0]:
                print(f"  (symbol field is '{field}' — move it to the front "
                      f"of SYMBOL_FIELDS)")
            globals()["ACTIVE_SYMBOL_FIELD"] = field
            return rows
        if not retry:
            return None
        print(f"  '{field}' not in this dataset, trying next...")
    print(f"None of {SYMBOL_FIELDS} exist in '{DATASET}'.")
    show_schema()
    return None


def pick(row, keys):
    for k in keys:
        v = row.get(k)
        if v not in (None, "", "null"):
            return v
    return None


def num(row, keys):
    v = pick(row, keys)
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def parse(rows):
    """Aggregate across market centres -> {ticker: {date: (short, total)}}.

    FINRA reports separately per reporting facility (ADF, the Nasdaq TRFs,
    the NYSE TRF), so a single symbol-day arrives as several rows and the
    quantities must be summed. Treating one row as the day's total would
    understate volume badly.
    """
    out = {}
    for row in rows or []:
        sym = canonical(str(pick(row, [globals().get("ACTIVE_SYMBOL_FIELD")]
                                 + SYMBOL_FIELDS) or ""))
        day = pick(row, DATE_FIELDS)
        if not sym or not day:
            continue
        day = str(day)[:10]
        short = num(row, SHORT_FIELDS) or 0.0
        exempt = num(row, EXEMPT_FIELDS) or 0.0
        total = num(row, TOTAL_FIELDS) or 0.0
        if total <= 0:
            continue
        bucket = out.setdefault(sym, {}).setdefault(day, [0.0, 0.0])
        bucket[0] += short + exempt
        bucket[1] += total
    return out


def summarise(series, latest):
    """Latest ratio plus the trailing average, for one ticker."""
    if latest not in series:
        return None
    short, total = series[latest]
    if total < MIN_TOTAL_VOLUME:
        return None

    prior = sorted(d for d in series if d < latest)[-BASELINE_DAYS:]
    ratios = []
    for d in prior:
        s, t = series[d]
        if t >= MIN_TOTAL_VOLUME:
            ratios.append(s / t * 100)
    avg = sum(ratios) / len(ratios) if ratios else None

    ratio = short / total * 100
    return {
        "ratio": ratio,
        "avg": avg,
        "delta": (ratio - avg) if avg is not None else None,
        "volume": total,
        "sessions": len(ratios),
    }


def human(v):
    for div, suf in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(v) >= div:
            return f"{v/div:.1f}{suf}"
    return f"{v:.0f}"


def build_table(data):
    """<=28 chars: Discord mobile wraps code blocks past that."""
    lines = [f"{'':5}{'Short':>6}{'Avg':>6}{'':1}{'Vol':>7}"]
    lines.append("-" * 26)
    # Sort by absolute deviation: the biggest movers surface first whichever
    # way they went.
    for sym, m in sorted(data.items(),
                         key=lambda kv: -abs(kv[1]["delta"] or 0)):
        avg = f"{m['avg']:.0f}%" if m["avg"] is not None else "n/a"
        mark = " "
        if m["delta"] is not None and abs(m["delta"]) >= NOTABLE_DELTA_POINTS:
            mark = "+" if m["delta"] > 0 else "-"
        lines.append(f"{sym:<5}{m['ratio']:>5.0f}%{avg:>6}{mark}"
                     f"{human(m['volume']):>7}")
    return "\n".join(lines)


def build_embed(day, data, missing):
    movers = [s for s, m in data.items()
              if m["delta"] is not None
              and abs(m["delta"]) >= NOTABLE_DELTA_POINTS]

    desc = (f"Trade date {day}. Short **volume** as a share of reported "
            f"volume, against each ticker's own {BASELINE_DAYS}-session "
            f"average.\n\n"
            f"This is a flow, not a position — much of it is market-maker "
            f"hedging, and 40-60% is ordinary. Only the deviation from a "
            f"ticker's own average carries information, in either direction.")
    if missing:
        desc += f"\n\nNo data: {', '.join(missing)}"

    return {
        "title": "Short sale volume",
        "description": desc,
        "color": DOWN if movers else FLAT,
        "fields": [{"name": "\u200b",
                    "value": f"```\n{build_table(data)}\n```"}],
        "footer": {"text": "FINRA Reg SHO · Vol = off-exchange (TRF/ADF) "
                           "only, not consolidated"
                           + (f" · +/- = >{NOTABLE_DELTA_POINTS:.0f}pts from "
                              f"average" if movers else "")},
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
    if DRY_RUN:
        print("DRY RUN — nothing posted, state not saved.\n")
    elif not WEBHOOK_URL:
        sys.exit("WEBHOOK_URL_MARKET is not set.")

    print(f"Querying FINRA Reg SHO for {len(TICKERS)} ticker(s)...")
    rows = fetch()
    if rows is None:
        sys.exit("No data returned.")

    by_ticker = parse(rows)
    if not by_ticker:
        sys.exit("No matching records; check the ticker list.")

    all_days = {d for series in by_ticker.values() for d in series}
    latest = max(all_days)

    try:
        age = (date.today() - date.fromisoformat(latest)).days
    except ValueError:
        age = None
    if age is not None and age > STALE_WARN_DAYS:
        sys.exit(f"Newest trade date is {age} days old — FINRA publishes this "
                 f"daily, so '{DATASET}' is likely wrong. Not posting.")

    data = {}
    for sym, series in by_ticker.items():
        m = summarise(series, latest)
        if m:
            data[sym] = m
    missing = sorted(set(TICKERS) - set(data))

    print(f"Latest trade date: {latest} — {len(data)} of {len(TICKERS)} found")
    if missing:
        print(f"  no usable data: {', '.join(missing)}")

    state = load_state()
    if state.get("last_trade_date") == latest and not DRY_RUN:
        print(f"Already posted {latest}. Nothing to do.")
        return

    if not data:
        sys.exit("Nothing to report.")

    embed = build_embed(latest, data, missing)
    print()
    print(embed["fields"][0]["value"])
    thin = [s for s, m in data.items() if m["sessions"] < BASELINE_DAYS // 2]
    if thin:
        print(f"  thin baseline (<{BASELINE_DAYS//2} sessions): "
              f"{', '.join(sorted(thin))}")

    if DRY_RUN:
        print(f"\nDry run: would post trade date {latest}. State not saved.")
        return

    if post(embed):
        state["last_trade_date"] = latest
        save_state(state)
        print(f"Posted trade date {latest}.")
    else:
        sys.exit("Post failed; state not saved so it retries next run.")


if __name__ == "__main__":
    main()
