#!/usr/bin/env python3
"""
Probe part two: the two leads part one turned up.

TEMPORARY. Posts nothing, writes nothing, changes no roster entry.

LEAD 1 — investor.galaxy.com. The ERCOT 830 MW release on /newsroom links to
`investor.galaxy.com/news-releases/...`, an IR HOST NOBODY HAS CHECKED. Every
feed check so far ran against www.galaxy.com. **This is the WYFI shape
exactly** — whitefiber.investorroom.com, found by autodiscovery off a shell
that had no headlines in it, and written off twice before anyone followed a
reference off-domain. A feed here would make the scraper unnecessary rather
than better.

LEAD 1b — I was wrong about the markup. `scrape_galaxy()`'s comment says
nothing in the markup separates Galaxy's own releases from third-party
write-ups. The <li> wrapper does:

    post-list2__item grid__item newsroom-announcements newsroom
    post-list2__item grid__item newsroom-media newsroomMedia | Article
    post-list2__item grid__item newsroom-our-stories newsroom
    post-list2__item grid__item newsroom-video newsroom
    post-list2__item grid__item research

I read `data-newsroom-media-type` and never looked at the class list two
attributes to its left. This checks whether `newsroom-announcements` is a
reliable filter, and — the part that decides whether the archive pages are
usable at all — WHETHER THOSE PAGES CARRY DATES. Part one found 278 cards and
zero dated on /all-news/announcements, which would make it unusable however
good the classification is.

LEAD 2 — ABTC is on Sanity. The bundle carries `sanity.io/manage/project/${e}`
and `sanity.io/help/`, so the infinite scroll is backed by a hosted CMS with a
public query API — the DGXX/Strapi shape, and the best outcome available. This
extracts the project id and dataset from the bundle and QUERIES IT, because a
config value is a lead and a returned document is a source.

ROUTE (d) IS ALREADY OUT: an individual release page carries one ld+json block
and it is `@type=Organization` with a name, no NewsArticle and no
datePublished.

AND THE SITEMAP CROSS-CHECK. lastmod is when a page changed, not when a release
published. This compares release lastmod values against ABTC's own 8-K filing
dates on EDGAR — an independent record of when the thing was announced.
"""

import json
import os
import re
import sys
import time
import urllib.request
from collections import Counter
from urllib.parse import urljoin

import requests

import press_monitor as pm
import watchlist

GLXY_IR = "https://investor.galaxy.com"
GLXY_NEWSROOM = "https://www.galaxy.com/newsroom"
GLXY_ANNOUNCE = "https://www.galaxy.com/all-news/announcements"
ABTC_NEWS = "https://www.abtc.com/news"

HOST_PATHS = ["/rss/news-releases.xml", "/rss/pressrelease.aspx",
              "/news-releases/rss", "/rss", "/feed", "/rss/events.xml",
              "/news-events/press-releases/rss",
              "/index.php?s=43&pagetemplate=rss"]


def get(url, timeout=(10, 30)):
    try:
        return requests.get(url, headers=pm.IR_HEADERS, timeout=timeout)
    except requests.RequestException as e:
        print(f"      {type(e).__name__}")
        return None


def looks_like_feed(r):
    if r is None or r.status_code != 200:
        return False
    head = r.content[:400].lstrip()
    return b"<?xml" in head[:200] or head[:5] in (b"<rss ", b"<feed", b"<rdf:")


def lead1():
    print("=" * 78)
    print("LEAD 1 — investor.galaxy.com, an IR host nobody has checked")
    print("=" * 78)
    r = get(GLXY_IR)
    if r is None:
        print("  unreachable")
    else:
        print(f"  {GLXY_IR} -> HTTP {r.status_code}, {len(r.text):,} chars, "
              f"final {r.url}")
        if r.status_code == 200:
            links = []
            for m in re.finditer(r"(?is)<link\b[^>]*>", r.text):
                tag = m.group(0)
                if re.search(r"(?i)rel\s*=\s*[\"']?alternate", tag) and \
                   re.search(r"(?i)application/(rss|atom)\+xml", tag):
                    h = re.search(r"(?i)href\s*=\s*[\"']([^\"']+)", tag)
                    if h:
                        links.append(urljoin(r.url, h.group(1)))
            print(f"  autodiscovery: {links if links else 'none'}")
            anchors = sorted({urljoin(r.url, m.group(1)) for m in
                              re.finditer(r'href="([^"]*rss[^"]*)"', r.text,
                                          re.I)})
            print(f"  rss-ish anchors: {anchors[:6] if anchors else 'none'}")

    print("\n  candidate feed paths on that host")
    working = []
    for p in HOST_PATHS:
        rr = get(GLXY_IR + p, timeout=(8, 20))
        if looks_like_feed(rr):
            print(f"    FEED  {rr.status_code}  {len(rr.content):>8,}b  {p}")
            working.append(GLXY_IR + p)
        time.sleep(0.2)
    if not working:
        print("    none returned XML")

    for u in working:
        entries = pm.parse_feed(u)
        if not entries:
            continue
        ts = [pm.entry_time(e) for e in entries if pm.entry_time(e)]
        import datetime as dt
        newest = (dt.datetime.fromtimestamp(max(ts), dt.timezone.utc).date()
                  if ts else None)
        print(f"\n    {u}")
        print(f"      {len(entries)} items, {len(ts)} dated, newest {newest}")
        for e in entries[:5]:
            t = pm.entry_time(e)
            d = (dt.datetime.fromtimestamp(t, dt.timezone.utc).date()
                 if t else "—")
            print(f"        {d}  {(e.get('title') or '')[:64]}")
        helios = [e for e in entries
                  if re.search(r"(?i)ercot|helios", e.get("title", ""))]
        print(f"      ERCOT/Helios items in the feed: {len(helios)}")


def lead1b():
    print("\n" + "=" * 78)
    print("LEAD 1b — is newsroom-announcements a usable filter, and do the")
    print("          archive pages carry DATES at all?")
    print("=" * 78)
    for label, url in (("newsroom", GLXY_NEWSROOM),
                       ("announcements", GLXY_ANNOUNCE)):
        r = get(url)
        if r is None or r.status_code != 200:
            continue
        h = r.text
        # Split on <li> so each card is inspected inside its own wrapper.
        lis = re.findall(r"(?is)<li[^>]*class=\"([^\"]*post-list2__item[^\"]*)\""
                         r"[^>]*>(.*?)</li>", h)
        print(f"\n  {label}: {len(lis)} <li> cards")
        kinds = Counter()
        dated = Counter()
        offdomain = Counter()
        for cls, body in lis:
            kind = ("announcements" if "newsroom-announcements" in cls else
                    "media" if "newsroom-media" in cls else
                    "our-stories" if "newsroom-our-stories" in cls else
                    "video" if "newsroom-video" in cls else
                    "research" if "research" in cls else "other")
            kinds[kind] += 1
            if re.search(r"card2__eyebrow", body):
                d = re.search(r"(?:January|February|March|April|May|June|July|"
                              r"August|September|October|November|December)"
                              r"\s+\d{1,2},?\s+\d{4}", body)
                if d:
                    dated[kind] += 1
            href = re.search(r'href="([^"]+)"', body)
            if href and href.group(1).startswith("http"):
                offdomain[kind] += 1
        print(f"    {'kind':<16}{'cards':>7}{'dated':>7}{'off-domain':>12}")
        for k in sorted(kinds):
            print(f"    {k:<16}{kinds[k]:>7}{dated[k]:>7}{offdomain[k]:>12}")

        ann = [(c, b) for c, b in lis if "newsroom-announcements" in c]
        off = [b for c, b in ann
               if (re.search(r'href="([^"]+)"', b) or
                   re.match("", "")) and
               re.search(r'href="http', b)]
        print(f"    announcements cards linking off-domain: {len(off)}/"
              f"{len(ann)}"
              + ("   <- own releases hosted on the IR domain"
                 if off else "   <- all on-domain"))
        for b in off[:4]:
            u = re.search(r'href="(http[^"]+)"', b)
            t = re.search(r'class="card2__title"[^>]*>(.*?)</', b, re.S)
            print(f"      {u.group(1)[:60] if u else '?'}")
            if t:
                print(f"        {re.sub(r'<[^>]+>', '', t.group(1))[:66]}")


def lead2():
    print("\n" + "=" * 78)
    print("LEAD 2 — ABTC is on Sanity. Get the project id and QUERY it.")
    print("=" * 78)
    r = get(ABTC_NEWS)
    if r is None or r.status_code != 200:
        print("  news page unavailable")
        return
    assets = sorted(set(re.findall(r'src="(/assets/[^"]+\.js)"', r.text)))
    blob = ""
    for a in assets:
        rr = get(urljoin(ABTC_NEWS, a))
        if rr is not None and rr.status_code == 200:
            blob += rr.text
        time.sleep(0.2)
    print(f"  {len(assets)} bundles, {len(blob):,} chars of JS\n")

    found = {}
    for key, pat in (
        ("projectId", r'projectId\s*[:=]\s*["\']([a-z0-9]{6,})["\']'),
        ("dataset", r'dataset\s*[:=]\s*["\']([a-z0-9_\-]{2,})["\']'),
        ("apiVersion", r'apiVersion\s*[:=]\s*["\']([0-9\-v]{4,})["\']'),
        ("sanity host", r'([a-z0-9]{6,})\.api(?:cdn)?\.sanity\.io'),
    ):
        hits = Counter(re.findall(pat, blob))
        found[key] = hits
        print(f"  {key:<12} {hits.most_common(4) if hits else 'not found'}")

    pid = next(iter(found["projectId"]), None) or \
        next(iter(found["sanity host"]), None)
    ds = next(iter(found["dataset"]), None) or "production"
    if not pid:
        print("\n  No project id in the bundles. It may be injected at build")
        print("  time into a request URL instead — dumping sanity mentions:")
        for m in list(re.finditer(r".{90}sanity.{90}", blob))[:6]:
            print(f"    ...{m.group(0)}...")
        return

    print(f"\n  Trying projectId={pid}, dataset={ds}")
    q = '*[_type match "*post*" || _type match "*news*" || _type match "*article*"]' \
        '[0...5]{_type,_id,_createdAt,_updatedAt,title,slug,publishedAt,date}'
    for host in (f"https://{pid}.apicdn.sanity.io", f"https://{pid}.api.sanity.io"):
        url = f"{host}/v2021-10-21/data/query/{ds}?query={requests.utils.quote(q)}"
        rr = get(url, timeout=(10, 30))
        print(f"\n    {host} -> HTTP {rr.status_code if rr else '—'}")
        if rr is None or rr.status_code != 200:
            if rr is not None:
                print(f"      {rr.text[:200]}")
            continue
        try:
            data = rr.json()
        except Exception:                                        # noqa: BLE001
            print(f"      not JSON: {rr.text[:160]}")
            continue
        res = data.get("result") or []
        print(f"      {len(res)} document(s)")
        for d in res:
            print(f"        {json.dumps(d)[:190]}")
        if res:
            types = Counter(d.get("_type") for d in res)
            print(f"      types: {types.most_common()}")
        break


def sitemap_vs_edgar():
    print("\n" + "=" * 78)
    print("SITEMAP lastmod vs EDGAR — does lastmod track publication?")
    print("=" * 78)
    ua = os.environ.get("SEC_USER_AGENT", "").strip()
    sm = get("https://www.abtc.com/sitemap.xml")
    if sm is None or sm.status_code != 200:
        print("  sitemap unavailable")
        return
    pages = []
    for m in re.finditer(r"<url>(.*?)</url>", sm.text, re.S):
        loc = re.search(r"<loc>([^<]+)</loc>", m.group(1))
        lm = re.search(r"<lastmod>([^<]+)</lastmod>", m.group(1))
        if loc and "/news-and-insights/" in loc.group(1) and lm:
            pages.append((lm.group(1)[:10], loc.group(1)))
    pages.sort()
    if not ua:
        print("  SEC_USER_AGENT unset; printing sitemap only")
        for d, u in pages[-10:]:
            print(f"    {d}  {u.rsplit('/', 1)[-1][:64]}")
        return
    cik = watchlist.ciks()["ABTC"][0]
    req = urllib.request.Request(
        f"https://data.sec.gov/submissions/CIK{cik}.json",
        headers={"User-Agent": ua, "Accept-Encoding": "gzip, deflate"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        raw = resp.read()
        if resp.headers.get("Content-Encoding") == "gzip":
            import gzip
            raw = gzip.decompress(raw)
    sub = json.loads(raw)
    rec = (sub.get("filings") or {}).get("recent") or {}
    eightk = sorted({d for d, f in zip(rec.get("filingDate") or [],
                                       rec.get("form") or [])
                     if f.split("/")[0] == "8-K"})
    print(f"  {len(pages)} release pages with lastmod; "
          f"{len(eightk)} ABTC 8-K dates on EDGAR\n")
    print(f"  {'lastmod':<12}{'nearest 8-K':<14}{'gap':>5}  slug")
    import datetime as dt
    gaps = []
    for d, u in pages[-12:]:
        dd = dt.date.fromisoformat(d)
        near = min(eightk, key=lambda x: abs(
            (dt.date.fromisoformat(x) - dd).days), default=None)
        g = (dt.date.fromisoformat(near) - dd).days if near else None
        if g is not None:
            gaps.append(abs(g))
        print(f"  {d:<12}{str(near):<14}{str(g):>5}  {u.rsplit('/', 1)[-1][:44]}")
    if gaps:
        gaps.sort()
        print(f"\n  |gap| median {gaps[len(gaps) // 2]}d, "
              f"max {gaps[-1]}d, {sum(1 for g in gaps if g <= 1)}/{len(gaps)} "
              f"within a day")


def main():
    lead1()
    lead1b()
    lead2()
    sitemap_vs_edgar()
    return 0


if __name__ == "__main__":
    sys.exit(main())
