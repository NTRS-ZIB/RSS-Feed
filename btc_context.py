#!/usr/bin/env python3
"""
Bitcoin network context -> Discord.

Posts the variables that drive every miner on the watchlist simultaneously:
BTC price, network hashrate, difficulty and its next adjustment, and hashprice
(revenue per PH/s per day).

Data: mempool.space public REST API. No authentication, ~10 req/sec limit,
roughly 6 requests per run. Unlike per-IP-quota services, this works fine from
shared CI runners.
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone

import requests

API = "https://mempool.space/api"
WEBHOOK_URL = os.environ.get("WEBHOOK_URL_MARKET", "").strip()
DRY_RUN = os.environ.get("DRY_RUN", "").strip().lower() in ("1", "true", "yes")

HEADERS = {"User-Agent": "watchlist-monitor/1.0 (personal use)"}
SATS = 1e8
BLOCKS_PER_DAY = 144
HALVING_INTERVAL = 210_000

UP, DOWN, FLAT = 0x3FB950, 0xF85149, 0x8B949E


def get(path, default=None):
    """GET a mempool.space endpoint. Returns parsed JSON or `default`."""
    try:
        r = requests.get(f"{API}{path}", headers=HEADERS, timeout=(10, 25))
        if r.status_code != 200:
            print(f"  {path}: HTTP {r.status_code}")
            return default
        return r.json()
    except (requests.RequestException, ValueError) as e:
        print(f"  {path}: {type(e).__name__}")
        return default


def block_subsidy(height):
    """Current block subsidy in BTC, derived from height rather than hardcoded."""
    return 50 / (2 ** (height // HALVING_INTERVAL))


def pct(new, old):
    return ((new - old) / old * 100) if old else 0.0


def fmt_signed(v, unit="%", dp=1):
    return f"{v:+.{dp}f}{unit}"


def collect():
    """Gather everything, tolerating individual endpoint failures."""
    d = {}

    prices = get("/v1/prices", {})
    d["btc"] = prices.get("USD")

    # 24h ago, for the change figure.
    yday = int((datetime.now(timezone.utc) - timedelta(days=1)).timestamp())
    hist = get(f"/v1/historical-price?currency=USD&timestamp={yday}", {})
    series = hist.get("prices") or []
    d["btc_24h"] = series[0].get("USD") if series else None

    # One call covers current hashrate, current difficulty, and 30d of history.
    mining = get("/v1/mining/hashrate/1m", {})
    d["hashrate"] = mining.get("currentHashrate")
    d["difficulty"] = mining.get("currentDifficulty")
    hashrates = mining.get("hashrates") or []
    d["hashrate_7d"] = (hashrates[-8]["avgHashrate"]
                        if len(hashrates) >= 8 else None)

    d["adj"] = get("/v1/difficulty-adjustment", {})
    d["height"] = get("/blocks/tip/height")

    # Actual realised revenue over the last 144 blocks, in sats.
    d["rewards"] = get(f"/v1/mining/reward-stats/{BLOCKS_PER_DAY}", {})
    return d


def hashprice(d):
    """USD per PH/s per day, from realised revenue rather than theory."""
    rewards, btc, hashrate = d.get("rewards"), d.get("btc"), d.get("hashrate")
    if not (rewards and btc and hashrate):
        return None, None
    try:
        total_btc = float(rewards["totalReward"]) / SATS
        fee_btc = float(rewards["totalFee"]) / SATS
    except (KeyError, TypeError, ValueError):
        return None, None
    ph = hashrate / 1e15
    if ph <= 0:
        return None, None
    fee_share = (fee_btc / total_btc * 100) if total_btc else 0.0
    return (total_btc * btc) / ph, fee_share


def build_embed(d):
    fields = []

    btc, btc_24h = d.get("btc"), d.get("btc_24h")
    if btc:
        chg = pct(btc, btc_24h) if btc_24h else None
        val = f"${btc:,.0f}"
        if chg is not None:
            val += f"  ({fmt_signed(chg)} 24h)"
        fields.append({"name": "Bitcoin", "value": val, "inline": True})
        colour = UP if (chg or 0) >= 0 else DOWN
    else:
        colour = FLAT

    hr, hr7 = d.get("hashrate"), d.get("hashrate_7d")
    if hr:
        val = f"{hr/1e18:,.0f} EH/s"
        if hr7:
            val += f"  ({fmt_signed(pct(hr, hr7))} 7d)"
        fields.append({"name": "Network hashrate", "value": val,
                       "inline": True})

    hp, fee_share = hashprice(d)
    if hp:
        fields.append({
            "name": "Hashprice",
            "value": f"${hp:,.2f} / PH / day\nfees {fee_share:.1f}% of revenue",
            "inline": True,
        })

    diff, adj = d.get("difficulty"), d.get("adj") or {}
    if diff:
        val = f"{diff/1e12:,.2f} T"
        change = adj.get("difficultyChange")
        if change is not None:
            when = adj.get("estimatedRetargetDate")
            blocks = adj.get("remainingBlocks")
            eta = ""
            if when:
                target = datetime.fromtimestamp(when / 1000, timezone.utc)
                days = (target - datetime.now(timezone.utc)).days
                eta = f" in ~{max(days, 0)}d"
            val += (f"\nnext {fmt_signed(change)}{eta}"
                    f"{f', {blocks} blocks' if blocks else ''}")
        fields.append({"name": "Difficulty", "value": val, "inline": True})

    height = d.get("height")
    if isinstance(height, int):
        fields.append({
            "name": "Block",
            "value": f"{height:,}\nsubsidy {block_subsidy(height):g} BTC",
            "inline": True,
        })

    return {
        "title": "Bitcoin network",
        "description": ("Drivers shared by every miner on the watchlist. "
                        "Rising difficulty cuts revenue for all of them at once."),
        "color": colour,
        "fields": fields,
        "footer": {"text": "mempool.space"},
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
        print("DRY RUN — nothing will be posted.\n")
    elif not WEBHOOK_URL:
        sys.exit("WEBHOOK_URL_MARKET is not set.")

    print("Fetching mempool.space...")
    d = collect()
    embed = build_embed(d)

    if not embed["fields"]:
        sys.exit("No data retrieved; not posting.")

    print()
    for f in embed["fields"]:
        print(f"  {f['name']}: {f['value']}".replace("\n", " | "))
    print()

    if DRY_RUN:
        print(f"Dry run complete: {len(embed['fields'])} field(s) built.")
        return

    if post(embed):
        print("Posted network context.")
    else:
        sys.exit("Post failed.")


if __name__ == "__main__":
    main()
