#!/usr/bin/env python3
"""
Grid and fuel context -> Discord.

The cost side of mining margin. btc_context.py covers revenue — hashprice,
difficulty, network hashrate. Nothing covered cost until this.

WHAT THIS IS NOT: A POWER PRICE
It was meant to be. EIA's open API has no wholesale electricity prices for any
region — `electricity/wholesale/prices` returns 404, because the hub prices in
EIA's own Electricity Monthly Update come from S&P Global under licence and are
not redistributed.

The two things it does have were measured before this was written:

  retail industrial price   MONTHLY, and 91 days stale when checked. Texas
                            industrial read 6.26, 6.33, 6.33 c/kWh across three
                            months — genuinely the price these companies pay,
                            and almost perfectly flat. Not a signal.

  Henry Hub spot            DAILY, 4 days stale, and moving: $2.92 -> $2.87 ->
                            $2.63 inside a week. Gas is the marginal fuel
                            setting power prices in both ERCOT and PJM.

So this reports gas as the fuel proxy and grid demand as the curtailment proxy.
Neither is a power bill. Read it as pressure on cost, not cost.

WHY GRID DEMAND AT ALL
These companies are switchable load. When a grid is stressed they are paid to
stop mining, and that payment is a real revenue line. Demand approaching a
recent peak is when that happens, so a day-ahead forecast running above the
trailing norm is the signal — not the absolute megawatts.

CRITICAL: FORECAST IS NOT ACTUAL
The RTO route carries four types: D (demand), DF (day-ahead forecast), NG (net
generation), TI (interchange). Sorting by newest period returns DF first,
because forecasts extend into the future. Anything that failed to filter on
`type` would report a prediction as a measurement and never say so. Both are
used here, and both are labelled.

Data: EIA open API v2. One key, free, EIA_API_KEY.
"""

import os
import sys
from datetime import datetime, timedelta, timezone

import requests

# ------------------------------------------------------------------ CONFIG

# Balancing authorities that matter for this watchlist. ERCOT covers NUAI
# (Midland, Texas); PJM covers BGDE (Midland, Pennsylvania) and is where the
# data-centre demand story is loudest.
#
# NOT a complete mapping of watchlist companies to grids — facility locations
# come from filings and have not been audited. Treat these as the two regions
# most likely to matter, not as coverage.
REGIONS = {"ERCO": "ERCOT", "PJM": "PJM"}

# Trailing days of ACTUAL demand the forecast peak is measured against.
BASELINE_DAYS = 7

# Forecast peak this far above the trailing actual peak is called out.
NOTABLE_PEAK_PCT = 5.0

# Henry Hub daily spot. RNGWHHD is the series id, confirmed against the API.
GAS_SERIES = "RNGWHHD"
GAS_DAYS = 45

API = "https://api.eia.gov/v2"
EIA_KEY = os.environ.get("EIA_API_KEY", "").strip()

# ----------------------------------------------------------------- RUNTIME

WEBHOOK_URL = os.environ.get("WEBHOOK_URL_MARKET", "").strip()
DRY_RUN = os.environ.get("DRY_RUN", "").strip().lower() in ("1", "true", "yes")

AMBER, GREY = 0xD29922, 0x5A6672


def get(path, params):
    p = dict(params)
    p["api_key"] = EIA_KEY
    try:
        r = requests.get(f"{API}/{path}", params=p, timeout=(10, 30))
    except requests.RequestException as e:
        print(f"    request failed: {type(e).__name__}")
        return None
    if r.status_code != 200:
        print(f"    HTTP {r.status_code}: {r.text[:160]}")
        return None
    try:
        return r.json().get("response", {}).get("data", [])
    except ValueError:
        print("    non-JSON response")
        return None


# ------------------------------------------------------------------- GRID


def parse_hour(period):
    """EIA hourly periods look like 2026-08-01T05, in UTC."""
    try:
        return datetime.strptime(period, "%Y-%m-%dT%H").replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def region_demand(code):
    """Trailing actual peak and forward forecast peak, both in MW.

    `type` is filtered explicitly. Without it the newest rows are forecasts,
    and the component would silently compare a prediction against itself.
    """
    now = datetime.now(timezone.utc)
    start = (now - timedelta(days=BASELINE_DAYS + 1)).strftime("%Y-%m-%dT%H")

    out = {}
    for kind, label in (("D", "actual"), ("DF", "forecast")):
        rows = get("electricity/rto/region-data/data", {
            "data[]": "value", "facets[respondent][]": code,
            "facets[type][]": kind, "frequency": "hourly", "start": start,
            "sort[0][column]": "period", "sort[0][direction]": "desc",
            "length": "5000"})
        if rows is None:
            return None
        vals = []
        for r in rows:
            when, v = parse_hour(r.get("period", "")), r.get("value")
            if when is None or v in (None, ""):
                continue
            try:
                vals.append((when, float(v)))
            except (TypeError, ValueError):
                continue
        out[kind] = vals
        print(f"    {label:<9} {len(vals):>5} hour(s)"
              + (f", newest {max(v[0] for v in vals):%Y-%m-%d %H}Z" if vals else ""))

    actual = [v for w, v in out.get("D", []) if w >= now - timedelta(days=BASELINE_DAYS)]
    forward = [v for w, v in out.get("DF", []) if w >= now]
    if not actual or not forward:
        return None
    return {"actual_peak": max(actual), "forecast_peak": max(forward),
            "hours_ahead": len(forward)}


# -------------------------------------------------------------------- GAS


def gas():
    start = (datetime.now(timezone.utc) - timedelta(days=GAS_DAYS)).date().isoformat()
    rows = get("natural-gas/pri/fut/data", {
        "data[]": "value", "facets[series][]": GAS_SERIES, "frequency": "daily",
        "start": start, "sort[0][column]": "period",
        "sort[0][direction]": "desc", "length": "200"})
    if not rows:
        return None
    series = []
    for r in rows:
        try:
            series.append((r["period"], float(r["value"])))
        except (KeyError, TypeError, ValueError):
            continue
    if len(series) < 2:
        return None
    latest_d, latest = series[0]
    week = series[min(5, len(series) - 1)][1]
    month = series[-1][1]
    return {"date": latest_d, "price": latest,
            "wk": (latest - week) / week * 100 if week else 0.0,
            "mo": (latest - month) / month * 100 if month else 0.0,
            "n": len(series)}


# ------------------------------------------------------------------ FORMAT


def build_table(grids):
    """Kept to 24 characters. See the output-width note in the README."""
    out = [f"{'':<6}{'Fcst':>6}{'7d pk':>7}{'':>5}", "-" * 24]
    for code, g in grids.items():
        delta = (g["forecast_peak"] - g["actual_peak"]) / g["actual_peak"] * 100
        mark = "*" if delta >= NOTABLE_PEAK_PCT else ""
        out.append(f"{REGIONS[code]:<6}{g['forecast_peak'] / 1000:>6.1f}"
                   f"{g['actual_peak'] / 1000:>7.1f}{f'{delta:+.0f}%' + mark:>5}")
    return "\n".join(out)


def build_embed(grids, g):
    lines = []
    if grids:
        lines.append(f"```\n{build_table(grids)}\n```")
        lines.append("_GW. `Fcst` is the day-ahead forecast peak, `7d pk` the "
                     "highest actual demand of the last 7 days._")
        for code, d in grids.items():
            delta = (d["forecast_peak"] - d["actual_peak"]) / d["actual_peak"] * 100
            if delta >= NOTABLE_PEAK_PCT:
                lines.append(
                    f"**{REGIONS[code]}** day-ahead peak {d['forecast_peak']/1000:.1f} GW, "
                    f"{delta:+.0f}% above its 7-day high — curtailment is likelier "
                    f"on days like this")
    else:
        lines.append("_No grid data this run._")

    if g:
        lines.append(f"**Henry Hub** ${g['price']:.2f}/MMBtu "
                     f"({g['wk']:+.0f}% w/w, {g['mo']:+.0f}% vs {GAS_DAYS}d ago) "
                     f"— as of {g['date']}")

    lines.append(
        "_Not a power price. EIA's open API carries none for any region, and "
        "its retail series runs about three months stale. Gas is the marginal "
        "fuel in both grids; demand is what drives curtailment. Read this as "
        "pressure on cost, not cost._")

    hot = any((d["forecast_peak"] - d["actual_peak"]) / d["actual_peak"] * 100
              >= NOTABLE_PEAK_PCT for d in grids.values()) if grids else False
    return {
        "title": "Grid and fuel context",
        "description": "\n".join(lines),
        "color": AMBER if hot else GREY,
        "footer": {"text": "EIA open API · demand hourly, gas daily"},
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
        print("DRY RUN — nothing posted.\n")
    elif not WEBHOOK_URL:
        sys.exit("WEBHOOK_URL_MARKET is not set.")
    if not EIA_KEY:
        sys.exit("EIA_API_KEY is not set. Free at "
                 "https://www.eia.gov/opendata/register.php")

    grids = {}
    for code, name in REGIONS.items():
        print(f"  {name} ({code}):")
        d = region_demand(code)
        if d:
            delta = (d["forecast_peak"] - d["actual_peak"]) / d["actual_peak"] * 100
            print(f"    forecast peak {d['forecast_peak']/1000:.1f} GW over "
                  f"{d['hours_ahead']}h ahead, 7d actual peak "
                  f"{d['actual_peak']/1000:.1f} GW  ({delta:+.0f}%)")
            grids[code] = d
        else:
            print("    no usable data")

    print("  Henry Hub:")
    g = gas()
    if g:
        print(f"    ${g['price']:.2f}/MMBtu as of {g['date']}  "
              f"({g['wk']:+.0f}% w/w, {g['mo']:+.0f}% vs {GAS_DAYS}d, "
              f"{g['n']} obs)")
    else:
        print("    no usable data")

    if not grids and not g:
        # Every endpoint degraded at once is an outage or a bad key, not a
        # quiet day. Say so rather than posting an empty embed.
        sys.exit("No data from any EIA endpoint. Not posting.")

    embed = build_embed(grids, g)
    print()
    print(embed["description"])

    if DRY_RUN:
        print("\nDry run: would post. Nothing sent.")
        return 0
    if not post(embed):
        return 1
    print("\nPosted.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
