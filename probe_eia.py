#!/usr/bin/env python3
"""
THROWAWAY PROBE — not a component. Delete after use.

Answers what EIA's free API actually exposes before a power-price component is
designed around it, because the useful-looking numbers may not be there.

THE CONCERN
EIA's Electricity Monthly Update publishes wholesale prices at ERCOT, PJM,
NYISO and other hubs — exactly what a miner's cost side needs. But that report
states it is "based on S&P Global Market Intelligence data", which is licensed.
Licensed inputs are routinely absent from the open API even when they appear in
EIA's own publications.

If wholesale hub prices are missing, the fallbacks are:

  - electricity/retail-sales    industrial price by state, MONTHLY, and EIA
                                publishes it roughly two months in arrears
  - natural-gas/pri/fut         Henry Hub spot, DAILY, and gas is the marginal
                                fuel setting power prices in ERCOT and PJM

Those are very different components. One is a slow contextual post like fails
to deliver; the other is timely enough to sit beside the bitcoin context.
Deciding between them needs measurement, not assumption.

WHAT THIS REPORTS
For each candidate route: whether it exists, what frequencies and facets it
offers, the newest period actually available, and the lag in days.

Read-only. No webhook, no state, no commit.

    EIA_API_KEY=... python -u probe_eia.py

Get a free key instantly at https://www.eia.gov/opendata/register.php
"""

import os
import sys
from datetime import date, datetime

import requests

BASE = "https://api.eia.gov/v2"
KEY = os.environ.get("EIA_API_KEY", "").strip()

# Routes worth knowing about, in the order they would be preferred.
ROUTES = [
    ("electricity/rto/region-data",
     "RTO region data — does it carry PRICE, or only demand/generation?"),
    ("electricity/wholesale/prices",
     "wholesale hub prices, if the open API has them at all"),
    ("electricity/retail-sales",
     "retail price by state and sector; industrial is the relevant one"),
    ("natural-gas/pri/fut",
     "Henry Hub and futures — daily, and the marginal fuel in ERCOT/PJM"),
    ("natural-gas/pri/sum",
     "natural gas prices by sector and state"),
]

# Sample pulls, tried only if the route exists. (label, path, params)
SAMPLES = [
    ("industrial retail price, TX",
     "electricity/retail-sales/data",
     {"data[]": "price", "facets[sectorid][]": "IND",
      "facets[stateid][]": "TX", "frequency": "monthly",
      "sort[0][column]": "period", "sort[0][direction]": "desc", "length": "3"}),
    ("industrial retail price, US",
     "electricity/retail-sales/data",
     {"data[]": "price", "facets[sectorid][]": "IND",
      "facets[stateid][]": "US", "frequency": "monthly",
      "sort[0][column]": "period", "sort[0][direction]": "desc", "length": "3"}),
    ("Henry Hub spot, daily",
     "natural-gas/pri/fut/data",
     {"data[]": "value", "frequency": "daily",
      "sort[0][column]": "period", "sort[0][direction]": "desc", "length": "3"}),
]


def get(path, params=None):
    p = dict(params or {})
    p["api_key"] = KEY
    try:
        r = requests.get(f"{BASE}/{path}", params=p, timeout=(10, 30))
    except requests.RequestException as e:
        return None, f"{type(e).__name__}"
    if r.status_code != 200:
        body = r.text[:160].replace("\n", " ")
        return None, f"HTTP {r.status_code}: {body}"
    try:
        return r.json(), None
    except ValueError:
        return None, "non-JSON response"


def lag_days(period):
    """Days between a period string (yyyy, yyyy-mm or yyyy-mm-dd) and today."""
    for fmt, pad in (("%Y-%m-%d", None), ("%Y-%m", "-01"), ("%Y", "-01-01")):
        try:
            s = period + (pad or "")
            return (date.today() - datetime.strptime(s, "%Y-%m-%d").date()).days
        except ValueError:
            continue
    return None


def main():
    if not KEY:
        sys.exit("EIA_API_KEY is not set. Register free at "
                 "https://www.eia.gov/opendata/register.php")

    print("=" * 74)
    print("1. WHICH ROUTES EXIST")
    print("=" * 74)
    alive = []
    for path, why in ROUTES:
        payload, err = get(path)
        if err:
            print(f"\n  {path}\n      {why}\n      NOT AVAILABLE — {err}")
            continue
        meta = (payload or {}).get("response", {})
        freqs = [f.get("id") for f in meta.get("frequency", []) if isinstance(f, dict)]
        facets = [f.get("id") for f in meta.get("facets", []) if isinstance(f, dict)]
        cols = list((meta.get("data") or {}).keys())
        print(f"\n  {path}")
        print(f"      {why}")
        print(f"      OK   period {meta.get('startPeriod')} to {meta.get('endPeriod')}")
        print(f"      frequencies: {', '.join(freqs) or '-'}")
        print(f"      facets:      {', '.join(facets) or '-'}")
        print(f"      data cols:   {', '.join(cols) or '-'}")
        if "price" in " ".join(cols).lower() or "value" in " ".join(cols).lower():
            alive.append(path)

    print("\n" + "=" * 74)
    print("2. WHAT THE DATA ACTUALLY LOOKS LIKE, AND HOW STALE")
    print("=" * 74)
    for label, path, params in SAMPLES:
        payload, err = get(path, params)
        print(f"\n  {label}")
        print(f"    {path}")
        if err:
            print(f"    FAILED — {err}")
            continue
        rows = (payload or {}).get("response", {}).get("data", [])
        if not rows:
            print("    no rows returned")
            continue
        for row in rows[:3]:
            period = row.get("period", "?")
            val = row.get("price", row.get("value", "?"))
            units = row.get("price-units") or row.get("units") or ""
            extra = " ".join(str(row.get(k)) for k in ("stateid", "sectorid", "series")
                             if row.get(k))
            print(f"      {period:>12}  {str(val):>10} {units:<12} {extra}")
        newest = rows[0].get("period", "")
        d = lag_days(newest)
        if d is not None:
            verdict = ("timely" if d <= 10 else
                       "slow — contextual only" if d <= 45 else
                       "very stale — comparable to fails-to-deliver")
            print(f"    newest period {newest}, {d} days old — {verdict}")

    print("\n" + "=" * 74)
    print("VERDICT")
    print("=" * 74)
    print("""  Read section 1 for whether a WHOLESALE price route exists at all. If it
  does not, the choice is between monthly retail prices (slow, state-level,
  but genuinely the cost these companies pay) and daily Henry Hub gas (timely,
  national, but a proxy one step removed from a power bill).

  Read section 2 for the lag. A two-month lag makes this a contextual post
  like fails-to-deliver rather than something to sit beside the daily recap,
  and the component's schedule and framing should follow from that rather than
  the other way round.""")
    return 0


if __name__ == "__main__":
    sys.exit(main())
