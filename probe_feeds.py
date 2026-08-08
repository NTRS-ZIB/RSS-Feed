#!/usr/bin/env python3
"""
Probe: do the five 2026-08-05 additions have IR feeds?

TEMPORARY. Posts nothing, writes nothing, changes no roster entry.

GLXY, APLD, BTDR, SPCX and ABTC are all `ir_feed: None` pending verification,
so a press release reaches the channel only when its 8-K does — hours later,
and not at all when it is not 8-K-worthy.

THE ORDER MATTERS AND IS NOT THE OBVIOUS ONE.

1. AUTODISCOVERY BEFORE GUESSING. WYFI's feed lives on
   whitefiber.investorroom.com, not whitefiber.com. Anyone checking only the
   company domain concludes there is no feed, and this repo concluded exactly
   that twice. The <link rel="alternate"> tag is what found it, and it can
   point anywhere.

2. NEWEST ITEM DATE BEFORE ANYTHING ELSE. DGXX's GlobeNewswire feed parsed
   perfectly, returned 20 valid items and was seven months stale — a company
   that changes wire leaves the old feed serving old items at HTTP 200
   forever. A feed that parses is not a feed that works, and this repo has hit
   that twice. Every feed found here is reported newest-date first.

3. WHOSE FEED IT IS. BGDE's is GlobeNewswire's organisation feed, with an
   opaque token readable only from an individual release page. If any of these
   five distribute through a wire, a recent release dateline names it.

parse_feed() rather than feedparser directly, so this uses the component's own
headers, timeouts and single retry. A feed that only works with different
headers is not a feed this repo can read.

MARA IS THE CONTROL. A harness that has never passed proves nothing about the
failures it reports, so a known-good feed runs through the same path.

TWO OUTCOMES THAT ARE NOT FAILURES, and both must be reported as what they
are rather than as "unreachable":

  * No feed, server-rendered pages. That is HUT. A scraper, and much cheaper
    than it sounds.
  * No feed, client-side rendering. Thought to need Playwright four times and
    turned out not to every time. Before concluding it, this checks the three
    routes that worked: embedded JSON in the delivered HTML, a backing API the
    page calls, and the sitemap.
"""

import json
import re
import sys
import time
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

import requests

import press_monitor as pm
import watchlist

NEWSROOMS = {
    "GLXY": "https://www.galaxy.com/newsroom",
    "APLD": "https://ir.applieddigital.com/news-events/press-releases",
    "BTDR": "https://ir.bitdeer.com/news-events/news-releases",
    "SPCX": "https://ir.spacex.com/updates/default.aspx",
    "ABTC": "https://www.abtc.com/news",
}
CONTROL = ("MARA", watchlist.ir_feeds()["MARA"])

# Suffixes seen on this roster, plus the obvious generics. Tried only AFTER
# autodiscovery, and only to confirm a shape autodiscovery already suggested
# or to cover a page that ships no <link> tag.
SUFFIXES = [
    "/rss", "/rss.xml", "/feed", "/feed/", "/rss/news-releases.xml",
    "/rss/pressrelease.aspx", "/index.php?s=43&pagetemplate=rss",
]
# Platform roots worth trying at the HOST rather than the path, because Q4 and
# gcs-web serve the feed from the site root regardless of the page path.
HOST_PATHS = [
    "/rss/news-releases.xml", "/rss/pressrelease.aspx", "/rss/events.xml",
    "/feed", "/rss", "/sitemap.xml", "/news-events/press-releases/rss",
]

WIRES = {
    "globenewswire": "GlobeNewswire",
    "businesswire": "Business Wire",
    "prnewswire": "PR Newswire",
    "accesswire": "ACCESSWIRE",
    "newsfile": "Newsfile",
    "einpresswire": "EIN Presswire",
    "issuerdirect": "Issuer Direct",
}

FEEDISH = re.compile(r"(?i)\b(rss|atom|feed)\b")


def get(url, timeout=(10, 30)):
    try:
        return requests.get(url, headers=pm.IR_HEADERS, timeout=timeout,
                            allow_redirects=True)
    except requests.RequestException as e:
        print(f"      {type(e).__name__}")
        return None


def autodiscover(url):
    """<link rel=alternate type=...rss/atom...>, wherever it points."""
    r = get(url)
    if r is None:
        return [], None, None
    if r.status_code != 200:
        print(f"    HTTP {r.status_code} on the newsroom page itself")
        return [], None, r
    html = r.text
    found = []
    for m in re.finditer(r"(?is)<link\b[^>]*>", html):
        tag = m.group(0)
        if not re.search(r"(?i)rel\s*=\s*[\"']?alternate", tag):
            continue
        if not re.search(r"(?i)type\s*=\s*[\"']?application/(rss|atom)\+xml",
                         tag):
            continue
        href = re.search(r"(?i)href\s*=\s*[\"']([^\"']+)", tag)
        if href:
            found.append(urljoin(r.url, href.group(1).strip()))
    # A <link> tag is the documented route. Some platforms only put the feed in
    # an <a> in the footer, which is how a human would find it.
    anchors = []
    for m in re.finditer(r"(?is)<a\b[^>]*href\s*=\s*[\"']([^\"']+)[^>]*>(.{0,80}?)</a>",
                         html):
        href, text = m.group(1), re.sub(r"(?s)<[^>]+>", "", m.group(2))
        if FEEDISH.search(href) or FEEDISH.search(text):
            u = urljoin(r.url, href.strip())
            if u not in anchors:
                anchors.append(u)
    return found, anchors[:8], r


def looks_like_feed(resp):
    if resp is None or resp.status_code != 200:
        return False
    ctype = (resp.headers.get("Content-Type") or "").lower()
    head = resp.content[:400].lstrip()
    if b"<?xml" in head[:200] or head[:5] in (b"<rss ", b"<feed", b"<rdf:"):
        return True
    return ("xml" in ctype or "rss" in ctype) and b"<" in head


def try_candidates(ticker, page_url):
    """Everything worth trying, in the order the brief demands."""
    print(f"\n{'=' * 78}\n{ticker}  {page_url}\n{'=' * 78}")
    print("  1. autodiscovery <link rel=alternate>")
    links, anchors, page = autodiscover(page_url)
    for u in links:
        print(f"      LINK TAG: {u}")
    if not links:
        print("      none")
    if anchors:
        print("  1b. feed-ish anchors in the page (how a human would find it)")
        for u in anchors:
            print(f"      {u}")

    cands = list(links) + list(anchors or [])
    parsed = urlparse(page_url)
    root = f"{parsed.scheme}://{parsed.netloc}"
    print("  2. path and host candidates")
    for s in SUFFIXES:
        cands.append(page_url.rstrip("/") + s)
    for s in HOST_PATHS:
        cands.append(root + s)

    seen, working = set(), []
    for u in cands:
        if u in seen:
            continue
        seen.add(u)
        r = get(u, timeout=(8, 20))
        code = r.status_code if r is not None else "—"
        if looks_like_feed(r):
            n = len(r.content)
            print(f"      FEED  {code}  {n:>8,}b  {u}")
            working.append(u)
        elif r is not None and r.status_code == 200:
            pass  # a 200 HTML page is the soft-404 case; not noise worth printing
        time.sleep(0.2)
    if not working:
        print("      no candidate returned XML")
    return working, page


def report_feed(label, url):
    """Newest date FIRST, then structure. In that order deliberately."""
    print(f"\n  --- {label}: {url}")
    entries = pm.parse_feed(url)
    if not entries:
        print("      parse_feed returned nothing")
        return None
    times = [pm.entry_time(e) for e in entries]
    dated = [t for t in times if t]
    if not dated:
        print(f"      {len(entries)} items, NONE with a parseable timestamp")
        return None
    newest = max(dated)
    age = (datetime.now(timezone.utc)
           - datetime.fromtimestamp(newest, timezone.utc)).days
    stamp = datetime.fromtimestamp(newest, timezone.utc).strftime("%Y-%m-%d")
    flag = ("  <-- STALE, the DGXX failure" if age > 90 else
            "  <-- check, quiet for a while" if age > 45 else "")
    print(f"      NEWEST ITEM {stamp}, {age} days old{flag}")
    uids = [e.get("id") or e.get("link") for e in entries]
    print(f"      {len(entries)} items; "
          f"{sum(1 for u in uids if u)}/{len(entries)} with a uid; "
          f"{len(dated)}/{len(entries)} with a timestamp")
    if len(set(u for u in uids if u)) != len([u for u in uids if u]):
        print("      WARNING: uids are not unique")
    order = sorted(zip(times, entries), key=lambda x: -x[0])
    for t, e in order[:3]:
        d = datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d") if t \
            else "no date"
        print(f"        {d}  {(e.get('title') or '')[:66]}")
    # Whose feed is it?
    host = urlparse(url).netloc.lower()
    wire = next((v for k, v in WIRES.items() if k in host), None)
    blob = " ".join((e.get("title", "") + " " +
                     str(e.get("summary", ""))[:400]) for e in entries[:5])
    dateline = next((v for k, v in WIRES.items()
                     if k in blob.lower().replace(" ", "")), None)
    print(f"      host {host}"
          + (f"  -> {wire} organisation feed" if wire else "  -> company host")
          + (f"; dateline names {dateline}" if dateline and not wire else ""))
    return {"url": url, "n": len(entries), "newest": stamp, "age": age}


def fallback_routes(ticker, page_url, page):
    """The three routes that worked the four times Playwright looked needed."""
    print(f"\n  NO FEED — checking the three routes before concluding "
          f"anything about rendering")
    if page is None or page.status_code != 200:
        print("      the page itself did not return 200; nothing to inspect")
        return
    html = page.text
    print(f"      delivered HTML: {len(html):,} chars")

    # (a) embedded JSON
    hits = []
    for pat, name in (
        (r"(?s)<script[^>]+id=[\"']__NEXT_DATA__[\"'][^>]*>(.*?)</script>",
         "__NEXT_DATA__"),
        (r"(?s)<script[^>]+application/ld\+json[^>]*>(.*?)</script>",
         "ld+json"),
        (r"(?s)self\.__next_f\.push\((.*?)\)</script>", "next flight data"),
        (r"(?s)window\.__NUXT__\s*=\s*(.*?)</script>", "__NUXT__"),
    ):
        for m in re.finditer(pat, html):
            body = m.group(1).strip()
            hits.append((name, len(body), body[:160]))
    if hits:
        print("      (a) EMBEDDED JSON present:")
        for name, n, head in hits[:6]:
            print(f"            {name:<18}{n:>9,}b  {head[:90]}")
    else:
        print("      (a) no embedded JSON blocks found")

    # Does the delivered HTML already contain the releases?
    dates = re.findall(r"(?i)\b(20(?:2[4-9])-\d{2}-\d{2}|"
                       r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
                       r"[a-z]*\.?\s+\d{1,2},\s+20\d{2})\b", html)
    print(f"      server-rendered dates in the HTML: {len(dates)}"
          + (f"  e.g. {dates[:4]}" if dates else
             "  <- suggests client-side rendering"))

    # (b) a backing API the page calls
    api = set()
    for m in re.finditer(r"[\"'](/(?:api|_next/data|graphql|wp-json)[^\"'\s]{3,120})[\"']",
                         html):
        api.add(m.group(1))
    for m in re.finditer(r"[\"'](https?://[^\"'\s]*(?:api|graphql)[^\"'\s]{0,90})[\"']",
                         html):
        api.add(m.group(1))
    if api:
        print("      (b) candidate backing endpoints:")
        for u in sorted(api)[:10]:
            print(f"            {u}")
    else:
        print("      (b) no obvious API path in the delivered HTML")

    # (c) sitemap
    root = f"{urlparse(page_url).scheme}://{urlparse(page_url).netloc}"
    print("      (c) sitemap")
    for s in ("/sitemap.xml", "/sitemap_index.xml", "/news-sitemap.xml",
              "/robots.txt"):
        r = get(root + s, timeout=(8, 20))
        if r is None or r.status_code != 200:
            continue
        body = r.text[:2000]
        if s == "/robots.txt":
            maps = re.findall(r"(?i)^sitemap:\s*(\S+)", r.text, re.M)
            print(f"            robots.txt lists {len(maps)} sitemap(s)")
            for u in maps[:5]:
                print(f"              {u}")
        else:
            locs = len(re.findall(r"<loc>", r.text))
            lastmods = re.findall(r"<lastmod>([^<]+)</lastmod>", r.text)
            uniq = len(set(lastmods))
            print(f"            {s}  {locs} <loc>, {len(lastmods)} lastmod, "
                  f"{uniq} distinct"
                  + ("  <- one rebuild stamp, the DGXX sitemap trap"
                     if lastmods and uniq == 1 else ""))
        time.sleep(0.2)


def main():
    print("=" * 78)
    print("CONTROL FIRST — the harness must be shown capable of passing")
    print("=" * 78)
    ok = report_feed(*CONTROL)
    if not ok:
        print("\n  CONTROL FAILED. Every result below is suspect; a harness")
        print("  that cannot read a known-good feed is measuring itself.")
    else:
        print("\n  Control passed. Failures below are about the sources.")

    results = {}
    for t, url in NEWSROOMS.items():
        working, page = try_candidates(t, url)
        got = []
        for u in working[:6]:
            r = report_feed(f"{t} candidate", u)
            if r:
                got.append(r)
        results[t] = got
        if not got:
            fallback_routes(t, url, page)

    print("\n" + "=" * 78)
    print("SUMMARY")
    print("=" * 78)
    for t in NEWSROOMS:
        if results[t]:
            best = min(results[t], key=lambda r: r["age"])
            print(f"  {t:<6} FEED  newest {best['newest']} "
                  f"({best['age']}d)  {best['n']} items  {best['url']}")
        else:
            print(f"  {t:<6} no feed found — see the routes above")
    return 0


if __name__ == "__main__":
    sys.exit(main())
