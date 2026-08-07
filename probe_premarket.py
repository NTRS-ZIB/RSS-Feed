#!/usr/bin/env python3
"""
Probe: is the missing premarket the feed, the request, or the venue?

TEMPORARY. Posts nothing, writes nothing, decides nothing.

volume_spike.py gives premarket visibility as the reason it uses hourly bars —
"before 9:30 ET there is no daily bar for today and premarket activity is
invisible, exactly the case most worth alerting on". A 30-session census found
ZERO IEX bars before 08:00 ET across all nineteen tickers.

Three explanations produce that identical clean zero, and they need different
responses:

  the request  a window boundary, an `end`, or a missing extended-hours flag.
               A bug with a fix.
  the feed     IEX carries the trades but Alpaca's iex feed does not serve
               them at this timeframe. A feed question.
  the venue    IEX itself does not operate before 08:00 ET, so there are no
               trades to carry. A documentation error, and the window should
               be shortened.

The request is already ruled out by reading hourly_bars(): no `end`, no window
boundary, no extended-hours parameter — it asks for everything from `start`.

SO THIS COMPARES THE FEEDS. If SIP carries 04:00-08:00 bars for the same
symbols over the same window and IEX does not, the trades exist and IEX simply
was not part of them — the venue answer. If neither carries them, something
larger is wrong with the premise.

It also checks whether the docstring's claim was ever true HERE, by asking
whether SIP would have delivered it. daily_recap.py and crossings.py both use
SIP, so a rationale written against SIP that survived a feed change to IEX
would be history rather than error.
"""

import os
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

import requests

import watchlist

try:
    from zoneinfo import ZoneInfo
    EASTERN = ZoneInfo("America/New_York")
except Exception:                                               # noqa: BLE001
    EASTERN = timezone(timedelta(hours=-4))

TICKERS = watchlist.tickers()
KEY_ID = os.environ.get("ALPACA_KEY_ID", "").strip()
SECRET = os.environ.get("ALPACA_SECRET_KEY", "").strip()
if not (KEY_ID and SECRET):
    raise SystemExit("ALPACA_KEY_ID / ALPACA_SECRET_KEY are not set.")

DATA = "https://data.alpaca.markets/v2/stocks"
AUTH = {"APCA-API-KEY-ID": KEY_ID, "APCA-API-SECRET-KEY": SECRET}
DAYS = int(os.environ.get("PREMARKET_DAYS", "30"))
# A liquid subset. The question is whether the hours exist at all, and the
# thinnest names would confuse a venue-coverage answer with an illiquidity one.
SAMPLE = [t for t in ("MARA", "CLSK", "IREN", "WULF", "HUT", "CIFR")
          if t in TICKERS]


def bars(feed, symbols, timeframe="1Hour"):
    start = (date.today() - timedelta(days=DAYS)).isoformat()
    out, token, pages = defaultdict(list), None, 0
    while pages < 40:
        params = {"symbols": ",".join(symbols), "timeframe": timeframe,
                  "start": start, "limit": 10000, "feed": feed,
                  "adjustment": "all"}
        if token:
            params["page_token"] = token
        r = requests.get(f"{DATA}/bars", headers=AUTH, params=params,
                         timeout=(10, 60))
        if r.status_code != 200:
            return None, f"HTTP {r.status_code}: {r.text[:120]}"
        data = r.json()
        for sym, rows in (data.get("bars") or {}).items():
            out[sym].extend(rows)
        token = data.get("next_page_token")
        pages += 1
        if not token:
            break
    return out, f"{pages} page(s), {sum(len(v) for v in out.values())} bars"


def by_hour(rows):
    hours, days = defaultdict(float), defaultdict(set)
    for b in rows:
        try:
            ts = datetime.fromisoformat(b["t"].replace("Z", "+00:00"))
        except (KeyError, ValueError):
            continue
        et = ts.astimezone(EASTERN)
        hours[et.hour] += float(b.get("v") or 0)
        days[et.hour].add(et.date())
    return hours, days


def main():
    print(f"{DAYS} days, sample {', '.join(SAMPLE)}\n")
    results = {}
    for feed in ("iex", "sip"):
        data, note = bars(feed, SAMPLE)
        print(f"  feed={feed:<4} {note}")
        if data is None:
            results[feed] = None
            continue
        results[feed] = data

    print("\n" + "=" * 78)
    print("SESSIONS WITH ANY BAR, BY ET HOUR")
    print("=" * 78)
    print("  If SIP carries 04:00-08:00 and IEX does not, the trades exist and")
    print("  IEX was not part of them — the venue answer, not the feed's.\n")
    hours = list(range(3, 21))
    print(f"  {'feed':<6}{'ticker':<7}" + "".join(f"{h:>4}" for h in hours))
    for feed in ("iex", "sip"):
        if not results.get(feed):
            print(f"  {feed:<6} unavailable")
            continue
        for t in SAMPLE:
            _v, d = by_hour(results[feed].get(t, []))
            print(f"  {feed:<6}{t:<7}"
                  + "".join(f"{len(d.get(h, ())):>4}" for h in hours))
        print()

    print("=" * 78)
    print("SHARE OF VOLUME OUTSIDE 09:30-16:00, PER FEED")
    print("=" * 78)
    for feed in ("iex", "sip"):
        if not results.get(feed):
            continue
        pre = reg = post = 0.0
        for t in SAMPLE:
            v, _d = by_hour(results[feed].get(t, []))
            for h, vol in v.items():
                if h < 9:
                    pre += vol
                elif h <= 15:
                    reg += vol
                else:
                    post += vol
        tot = pre + reg + post or 1
        print(f"  {feed:<5} pre-09:00 {pre / tot * 100:5.2f}%   "
              f"09:00-15:59 {reg / tot * 100:5.2f}%   "
              f"16:00+ {post / tot * 100:5.2f}%   "
              f"({tot / 1e6:.1f}M shares)")

    print("\n" + "=" * 78)
    print("EARLIEST AND LATEST BAR SEEN, PER FEED")
    print("=" * 78)
    for feed in ("iex", "sip"):
        if not results.get(feed):
            continue
        allh = set()
        for t in SAMPLE:
            _v, d = by_hour(results[feed].get(t, []))
            allh |= {h for h, ds in d.items() if ds}
        if allh:
            print(f"  {feed:<5} {min(allh):02d}:00 .. {max(allh):02d}:59 ET")
    return 0


if __name__ == "__main__":
    sys.exit(main())
