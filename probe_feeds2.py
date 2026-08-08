#!/usr/bin/env python3
"""
Probe: verify the three feeds found, against the pages they claim to mirror.

TEMPORARY. Posts nothing, writes nothing, changes no roster entry.

PART ONE FOUND THREE FEEDS AND MADE ONE MISTAKE THAT MATTERS.

Its summary picked BTDR's `/rss/events.xml` over `/rss/news-releases.xml`,
because it ranked candidates by newest item and the events feed carries a
FUTURE-DATED earnings call. **"Freshest" is the wrong selector when one
candidate is a calendar** — an events feed will always look newer than a
press-release feed, and it is not the thing the channel wants. Recorded
because it would have put the wrong URL in the roster silently.

AND NOTHING WAS CHECKED AGAINST ITS OWN NEWSROOM. That is the DGXX failure
exactly: a feed that parses, returns valid items and is months behind the site
it claims to mirror. Comparing the feed's newest item against the newest date
on the page is the only check that catches it, and part one did not run it —
it compared the feed against today's date, which a dead feed passes for the
first ninety days.

This also settles a smaller thing. APLD returned identical bytes for
/rss, /rss/news-releases.xml and /rss/pressrelease.aspx, so that platform
serves the feed for anything under the /rss path. Path-guessing cannot
distinguish a real endpoint from a soft match there, which is an argument for
recording the autodiscovered URL rather than a constructed one.
"""

import re
import sys
import time
from datetime import datetime, timezone

import requests

import press_monitor as pm

PAIRS = {
    "APLD": ("https://ir.applieddigital.com/news-events/press-releases",
             "https://ir.applieddigital.com/news-events/press-releases/rss"),
    "BTDR": ("https://ir.bitdeer.com/news-events/news-releases",
             "https://ir.bitdeer.com/rss/news-releases.xml"),
    "SPCX": ("https://ir.spacex.com/updates/default.aspx",
             "https://ir.spacex.com/rss/pressrelease.aspx"),
}
# The two with no feed, to pin what a scraper would be reading.
PAGES = {
    "GLXY": "https://www.galaxy.com/newsroom",
    "ABTC": "https://www.abtc.com/news",
}

MONTHS = ("jan feb mar apr may jun jul aug sep oct nov dec").split()
DATE_PATTERNS = [
    r"\b(20\d{2})-(\d{2})-(\d{2})\b",
    r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+"
    r"(\d{1,2}),?\s+(20\d{2})\b",
]


def page_dates(url):
    try:
        r = requests.get(url, headers=pm.IR_HEADERS, timeout=(10, 30))
    except requests.RequestException as e:
        print(f"      page fetch failed: {type(e).__name__}")
        return [], None
    if r.status_code != 200:
        print(f"      page HTTP {r.status_code}")
        return [], None
    txt = re.sub(r"(?is)<(script|style).*?</\1>", " ", r.text)
    out = []
    for m in re.finditer(DATE_PATTERNS[0], txt):
        y, mo, d = m.groups()
        out.append((int(y), int(mo), int(d)))
    for m in re.finditer(DATE_PATTERNS[1], txt, re.I):
        mon, d, y = m.groups()
        out.append((int(y), MONTHS.index(mon[:3].lower()) + 1, int(d)))
    return out, r


def main():
    today = datetime.now(timezone.utc).date()
    print("=" * 78)
    print("FEED vs ITS OWN NEWSROOM — the check that catches the DGXX failure")
    print("=" * 78)
    print("Against today's date a dead feed passes for ninety days. Against")
    print("the page it claims to mirror, it fails the same day.\n")

    for t, (page, feed) in PAIRS.items():
        print(f"  {t}")
        entries = pm.parse_feed(feed)
        ft = [pm.entry_time(e) for e in entries if pm.entry_time(e)]
        fnew = (datetime.fromtimestamp(max(ft), timezone.utc).date()
                if ft else None)
        dates, r = page_dates(page)
        past = [d for d in dates if datetime(*d).date() <= today]
        pnew = max(past) if past else None
        pnew = datetime(*pnew).date() if pnew else None
        print(f"      feed newest {fnew}   page newest {pnew}   "
              f"({len(entries)} items, {len(dates)} dates on the page)")
        if fnew and pnew:
            lag = (pnew - fnew).days
            verdict = ("IN STEP" if lag <= 2 else
                       f"FEED IS {lag} DAYS BEHIND THE PAGE  <-- the DGXX shape")
            print(f"      {verdict}")
        elif not ft:
            print("      no dated feed items")
        else:
            print("      could not read dates off the page; feed unverified "
                  "against its source")
        time.sleep(0.3)

    print("\n" + "=" * 78)
    print("BTDR: press releases vs events, because part one picked the wrong one")
    print("=" * 78)
    for label, u in (("news-releases", "https://ir.bitdeer.com/rss/news-releases.xml"),
                     ("events", "https://ir.bitdeer.com/rss/events.xml")):
        entries = pm.parse_feed(u)
        ts = [pm.entry_time(e) for e in entries if pm.entry_time(e)]
        if not ts:
            print(f"  {label}: no dated items")
            continue
        newest = datetime.fromtimestamp(max(ts), timezone.utc).date()
        future = sum(1 for x in ts
                     if datetime.fromtimestamp(x, timezone.utc).date() > today)
        print(f"  {label:<14} newest {newest}  "
              f"{future} item(s) dated in the FUTURE"
              + ("   <- why 'freshest' selected the wrong feed"
                 if future else ""))
        for e in entries[:2]:
            print(f"                 {(e.get('title') or '')[:64]}")

    print("\n" + "=" * 78)
    print("THE TWO WITH NO FEED — what a scraper would actually be reading")
    print("=" * 78)
    for t, url in PAGES.items():
        dates, r = page_dates(url)
        past = [d for d in dates if datetime(*d).date() <= today]
        print(f"\n  {t}  {url}")
        if r is None:
            continue
        print(f"      {len(r.text):,} chars delivered, {len(dates)} dates, "
              f"newest {max(past) if past else '—'}")
        # Does the delivered HTML carry titles and links, or only dates?
        links = re.findall(r"(?i)href=[\"']([^\"']*(?:news|press|release|article|post)[^\"']*)[\"']",
                           r.text)
        uniq = sorted(set(links))
        print(f"      {len(uniq)} distinct news-ish links in the delivered HTML")
        for u in uniq[:6]:
            print(f"        {u[:96]}")
        # A title next to a date is what makes a scraper cheap.
        near = re.findall(
            r"(?is)(20\d{2}-\d{2}-\d{2}|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|"
            r"Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+20\d{2}).{0,300}?"
            r"<(?:h[1-6]|a)[^>]*>\s*([^<]{16,120})", r.text)
        print(f"      {len(near)} date-then-title pairs found in markup order")
        for d, title in near[:4]:
            print(f"        {d:<18} {re.sub(r'\\s+', ' ', title).strip()[:62]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
