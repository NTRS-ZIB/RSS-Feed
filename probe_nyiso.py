#!/usr/bin/env python3
"""
DISPOSABLE PROBE — delete once its answer is recorded.

Question: can NYISO be added to grid_context.py as a third region?

Three things must be true before that dictionary is touched, and none of them
is safe to assume:

  1. The exact respondent code, taken from the facet list rather than guessed.
     The route carries 83 respondents; the codes are discoverable.
  2. That the code returns BOTH `D` (actual demand) and `DF` (day-ahead
     forecast). The component compares the two, so a region carrying only one
     is useless to it and would degrade to "no usable data" every run.
  3. That its hours are on the same UTC clock as ERCOT and PJM, so the three
     rows of one table stay comparable.

Read-only. Hits the same EIA route grid_context.py already uses, posts nothing,
writes nothing, and never prints the key.
"""
import os
import sys
from datetime import datetime, timedelta, timezone

import requests

API = "https://api.eia.gov/v2"
ROUTE = "electricity/rto/region-data"
KEY = os.environ.get("EIA_API_KEY", "").strip()

# ERCO and PJM are the controls: whatever the candidate does, it has to do the
# same thing these two already do.
CANDIDATES = ["NYIS", "NYISO", "NY"]
CONTROLS = ["ERCO", "PJM"]


def get(path, params=None):
    p = dict(params or {})
    p["api_key"] = KEY
    try:
        r = requests.get(f"{API}/{path}", params=p, timeout=(10, 30))
    except requests.RequestException as e:
        print(f"    request failed: {type(e).__name__}")
        return None
    if r.status_code != 200:
        print(f"    HTTP {r.status_code}: {r.text[:200]}")
        return None
    try:
        return r.json().get("response", {})
    except ValueError:
        print("    non-JSON response")
        return None


def facets():
    print("=" * 70)
    print("1. RESPONDENT FACET LIST")
    print("=" * 70)
    resp = get(f"{ROUTE}/facet/respondent")
    if resp is None:
        return []
    rows = resp.get("facets", [])
    print(f"{len(rows)} respondents returned\n")
    print("  matching 'ny', 'new york' or 'iso':")
    for f in rows:
        fid, name = str(f.get("id", "")), str(f.get("name", ""))
        hay = f"{fid} {name}".lower()
        if "new york" in hay or "iso" in hay or fid.upper().startswith("NY"):
            print(f"    id={fid:<8} name={name}")
    return [str(f.get("id", "")) for f in rows]


def series(code, kind, start):
    resp = get(f"{ROUTE}/data", {
        "data[]": "value", "facets[respondent][]": code,
        "facets[type][]": kind, "frequency": "hourly", "start": start,
        "sort[0][column]": "period", "sort[0][direction]": "desc",
        "length": "24"})
    return (resp or {}).get("data", [])


def probe(code, start):
    print(f"\n  {code}")
    ok = True
    for kind, label in (("D", "actual"), ("DF", "forecast")):
        rows = series(code, kind, start)
        if not rows:
            print(f"    {kind:<3} {label:<9} NO ROWS")
            ok = False
            continue
        newest = rows[0]
        print(f"    {kind:<3} {label:<9} {len(rows):>3} row(s)  "
              f"newest={newest.get('period')}  "
              f"value={newest.get('value')} {newest.get('value-units', '')}")
    return ok


def main():
    if not KEY:
        sys.exit("EIA_API_KEY is not set.")

    ids = facets()

    print()
    print("=" * 70)
    print("2. D AND DF   3. CLOCK — candidates against the two controls")
    print("=" * 70)
    now = datetime.now(timezone.utc)
    start = (now - timedelta(days=3)).strftime("%Y-%m-%dT%H")
    print(f"  window from {start}Z")

    print("\n  CONTROLS")
    for code in CONTROLS:
        probe(code, start)

    print("\n  CANDIDATES")
    for code in CANDIDATES:
        if ids and code not in ids:
            print(f"\n  {code}\n    not in the facet list — skipped")
            continue
        probe(code, start)

    print(f"\n  now: {now:%Y-%m-%dT%H}Z")
    print("\nCompare the newest `D` period across all of them. Equal means one "
          "clock.\nA candidate lagging the controls by a fixed offset would "
          "mean local time.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
