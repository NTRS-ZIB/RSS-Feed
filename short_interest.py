#!/usr/bin/env python3
"""
Short interest -> Discord.

FINRA publishes consolidated short interest twice a month: mid-month and
end-of-month settlement dates, released roughly eight business days later. This
posts once per new settlement date and stays silent otherwise.

Data: FINRA Query API, group `otcMarket`, dataset `EquityShortInterest`.

The `otcMarket` group name is LEGACY. Before June 2021 the dataset really was
OTC-only; since then it covers all exchange-listed securities too — Nasdaq,
NYSE, NYSE American, NYSE Arca and Cboe BZX. Do not conclude from the URL that
Nasdaq names are missing.

NOTE ON KEYING: this is the only component keyed by TICKER rather than CIK.
FINRA reports by symbol, so a rename breaks the lookup silently. Every run
prints which tickers were not found — treat that list as a maintenance alarm,
not noise. See TICKERS below.
"""

import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import requests

# ------------------------------------------------------------------ CONFIG

# Ticker -> display name. MUST be kept in sync by hand when a company renames;
# FINRA has no CIK to pin to. Sphere 3D has a pending change to DarkHorse/DRK.
TICKERS = {
    "BGDE": "Big Digital Energy",
    "ANY":  "Sphere 3D",
    "NUAI": "New Era Energy & Digital",
    "SLNH": "Soluna Holdings",
    "DGXX": "Digi Power X",
    "BKKT": "Bakkt",
    "MARA": "MARA Holdings",
    "WYFI": "WhiteFiber",
    "IREN": "IREN Limited",
    "CLSK": "CleanSpark",
    "VIP":  "Vulcan Infrastructure and Power",
}

# How many recent settlement dates to search when looking for fresh data.
LOOKBACK_RECORDS = 5000

# Highlight a company whose short interest moved more than this, either way.
NOTABLE_CHANGE_PCT = 15.0

# ------------------------------------------------------------------ RUNTIME

WEBHOOK_URL = os.environ.get("WEBHOOK_URL_MARKET", "").strip()
DRY_RUN = os.environ.get("DRY_RUN", "").strip().lower() in ("1", "true", "yes")
STATE_FILE = Path(os.environ.get("SI_STATE", "shortinterest_state.json"))

API = "https://api.finra.org/data/group/otcMarket/name/EquityShortInterest"
HEADERS = {"Content-Type": "application/json", "Accept": "application/json"}

UP, DOWN, FLAT = 0x3FB950, 0xF85149, 0x8B949E


def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except json.JSONDecodeError:
            pass
    return {"last_settlement": ""}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=1))


def fetch():
    """Rows for our tickers, newest settlement dates first."""
    payload = {
        "compareFilters": [],
        "domainFilters": [{
            "fieldName": "issueSymbolIdentifier",
            "values": list(TICKERS),
        }],
        "limit": LOOKBACK_RECORDS,
    }
    try:
        r = requests.post(API, headers=HEADERS, json=payload, timeout=(10, 40))
    except requests.RequestException as e:
        print(f"request failed: {type(e).__name__}")
        return None

    if r.status_code in (401, 403):
        print(f"HTTP {r.status_code} — this endpoint needs credentials from "
              f"this IP. A free FINRA API account would be required.")
        return None
    if r.status_code != 200:
        print(f"HTTP {r.status_code}: {r.text[:200]}")
        return None
    try:
        return r.json()
    except ValueError:
        print("unparseable JSON")
        return None


def num(row, *keys):
    """First present numeric field among `keys`, or None.

    FINRA field names have shifted over time, so each value is looked up
    under several plausible spellings rather than one hardcoded key.
    """
    for k in keys:
        v = row.get(k)
        if v not in (None, "", "null"):
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    return None


def parse(rows):
    """Group by settlement date -> {date: {ticker: metrics}}."""
    by_date = {}
    for row in rows or []:
        sym = (row.get("issueSymbolIdentifier") or "").upper()
        settled = row.get("settlementDate") or ""
        if sym not in TICKERS or not settled:
            continue
        current = num(row, "currentShortPositionQuantity",
                      "currentShortShareNumber")
        previous = num(row, "previousShortPositionQuantity",
                       "previousShortShareNumber")
        if current is None:
            continue
        by_date.setdefault(settled[:10], {})[sym] = {
            "current": current,
            "previous": previous,
            "change_pct": num(row, "changePercent",
                              "percentageChangefromPreviousShort"),
            "days_to_cover": num(row, "daysToCoverQuantity",
                                 "averageDailyVolumeQuantity"),
            "avg_volume": num(row, "averageDailyVolumeQuantity"),
        }
    return by_date


def human(v):
    if v is None:
        return "n/a"
    for div, suf in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(v) >= div:
            return f"{v/div:.1f}{suf}"
    return f"{v:.0f}"


def build_table(data):
    """Kept to <=28 chars: Discord mobile wraps code blocks past that."""
    def sort_key(item):
        pct = item[1].get("change_pct")
        return -(pct if pct is not None else -999)

    lines = [f"{'':5}{'Short':>7}{'Chg':>7}{'DTC':>6}"]
    lines.append("-" * 25)
    for sym, m in sorted(data.items(), key=sort_key):
        pct = m.get("change_pct")
        chg = f"{pct:+.0f}%" if pct is not None else "n/a"
        dtc = m.get("days_to_cover")
        dtc_s = f"{dtc:.1f}" if dtc is not None else "n/a"
        mark = "*" if pct is not None and abs(pct) >= NOTABLE_CHANGE_PCT else " "
        lines.append(f"{sym:<5}{human(m['current']):>7}{chg:>7}{mark}{dtc_s:>5}")
    return "\n".join(lines)


def build_embed(settled, data, missing):
    movers = [s for s, m in data.items()
              if m.get("change_pct") is not None
              and abs(m["change_pct"]) >= NOTABLE_CHANGE_PCT]
    net = sum(m.get("change_pct") or 0 for m in data.values())

    desc = (f"Settlement {settled}. Reported twice monthly and published about "
            f"eight business days later, so this is positioning context rather "
            f"than a live signal.")
    if missing:
        desc += (f"\n\n**Not found: {', '.join(missing)}** — FINRA keys on "
                 f"ticker, so this usually means a symbol change.")

    return {
        "title": "Short interest",
        "description": desc,
        "color": UP if net > 0 else DOWN if net < 0 else FLAT,
        "fields": [{"name": "\u200b",
                    "value": f"```\n{build_table(data)}\n```"}],
        "footer": {"text": "FINRA · Short = shares short, DTC = days to cover"
                           + (f" · * moved >{NOTABLE_CHANGE_PCT:.0f}%"
                              if movers else "")},
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

    print(f"Querying FINRA for {len(TICKERS)} ticker(s)...")
    rows = fetch()
    if rows is None:
        sys.exit("No data returned.")

    by_date = parse(rows)
    if not by_date:
        sys.exit("No matching records; check the ticker list.")

    latest = max(by_date)
    data = by_date[latest]
    missing = sorted(set(TICKERS) - set(data))
    print(f"Latest settlement: {latest} — {len(data)} of {len(TICKERS)} found")
    if missing:
        print(f"  NOT FOUND: {', '.join(missing)}  (symbol change?)")

    state = load_state()
    if state.get("last_settlement") == latest and not DRY_RUN:
        print(f"Already posted {latest}. Nothing to do.")
        return

    embed = build_embed(latest, data, missing)
    print()
    print(embed["fields"][0]["value"])

    if DRY_RUN:
        print(f"\nDry run: would post settlement {latest}. State not saved.")
        return

    if post(embed):
        state["last_settlement"] = latest
        save_state(state)
        print(f"Posted settlement {latest}.")
    else:
        sys.exit("Post failed; state not saved so it retries next run.")


if __name__ == "__main__":
    main()
