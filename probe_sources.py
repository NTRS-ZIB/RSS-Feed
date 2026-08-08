#!/usr/bin/env python3
"""
Probe: GLXY's /all-news/announcements, and a proper scope for ABTC.

TEMPORARY. Posts nothing, writes nothing, changes no roster entry.

PART 1 — GLXY. scrape_galaxy() reads /newsroom and keeps 7 of 17 cards. The 10
it skips are a `newsroom-media` block mixing Galaxy's own wire-hosted releases
with third-party write-ups, with nothing in the markup separating them, and
that block currently holds the ERCOT 830 MW Helios approval — close to the most
relevant item this repo could carry.

A path of /all-news/announcements suggests a FILTERED view. The question is not
whether the Helios release is on it. It is whether "company announcement" and
"third-party article about the company" are separable by MARKUP there.

AND IF THE SEPARATION IS EDITORIAL RATHER THAN STRUCTURAL, that is a different
kind of source and must be recorded as one. A curated list can silently change
what it includes, and nothing in a fetch would show it.

PART 2 — ABTC. Four routes, ruled in or out:

  (a) slugs        titles are recoverable from them; are DATES?
  (b) sitemap      24 distinct lastmod values, so not the DGXX rebuild trap —
                   but lastmod is when a page CHANGED, not when a release was
                   published, and this checks whether they track.
  (c) backing API  an infinite scroll fetches from somewhere. The JS bundles
                   are named in the assets and are readable.
  (d) release page ld+json NewsArticle with datePublished would mean the list
                   gives URLs and each page gives its own date — more fetches,
                   no guesswork.

THE FAILURE MODE IS THE ACCEPTANCE CRITERION, not a detail. ABTC publishes
irregularly, so a parse that silently returns nothing is indistinguishable from
a quiet month. Every route below is judged on whether it has a countable floor
that never empties — the property that makes scrape_hut8()'s zero-item check
mean something.
"""

import json
import re
import sys
import time
from collections import Counter
from urllib.parse import urljoin, urlparse

import requests

import press_monitor as pm

GLXY_NEWSROOM = "https://www.galaxy.com/newsroom"
GLXY_ANNOUNCE = "https://www.galaxy.com/all-news/announcements"
GLXY_ALL = "https://www.galaxy.com/all-news"
ABTC_NEWS = "https://www.abtc.com/news"

DATE = re.compile(
    r"(?:January|February|March|April|May|June|July|August|September|October|"
    r"November|December)\s+\d{1,2},?\s+\d{4}")


def get(url, timeout=(10, 30)):
    try:
        return requests.get(url, headers=pm.IR_HEADERS, timeout=timeout)
    except requests.RequestException as e:
        print(f"      fetch failed: {type(e).__name__}")
        return None


def text_of(f):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", f)).strip()


def autodiscover(url, html):
    out = []
    for m in re.finditer(r"(?is)<link\b[^>]*>", html):
        tag = m.group(0)
        if re.search(r"(?i)rel\s*=\s*[\"']?alternate", tag) and \
           re.search(r"(?i)application/(rss|atom)\+xml", tag):
            h = re.search(r"(?i)href\s*=\s*[\"']([^\"']+)", tag)
            if h:
                out.append(urljoin(url, h.group(1)))
    return out


def galaxy_cards(url, html):
    """The same extraction scrape_galaxy() uses, so the two pages compare."""
    cards = list(re.finditer(r'<a[^>]+class="card2__link"[^>]*href="([^"]+)"',
                             html))
    rows = []
    for i, m in enumerate(cards):
        stop = cards[i + 1].start() if i + 1 < len(cards) else len(html)
        block = html[m.end():stop]

        def part(cls):
            g = re.search(rf'class="card2__{cls}"[^>]*>(.*?)</', block, re.S)
            return text_of(g.group(1)) if g else None

        title = part("title")
        if not title:
            continue
        eyebrow = part("eyebrow") or ""
        d = DATE.search(eyebrow)
        # The <li> wrapper is where /newsroom carries its media marker.
        back = html[max(0, m.start() - 700):m.start()]
        li = re.findall(r"<li[^>]*>", back)
        rows.append({
            "href": m.group(1),
            "title": title,
            "date": d.group(0) if d else None,
            "eyebrow": eyebrow,
            "li": li[-1][:190] if li else "",
        })
    return rows


def part1():
    print("=" * 78)
    print("PART 1 — GLXY: is /all-news/announcements a better source?")
    print("=" * 78)

    pages = {}
    for label, url in (("newsroom", GLXY_NEWSROOM),
                       ("all-news", GLXY_ALL),
                       ("announcements", GLXY_ANNOUNCE)):
        r = get(url)
        if r is None:
            continue
        print(f"\n  {label:<14} HTTP {r.status_code}  {len(r.text):>9,} chars  "
              f"-> {r.url}")
        if r.status_code != 200:
            continue
        pages[label] = r
        feeds = autodiscover(r.url, r.text)
        print(f"                 autodiscovery: "
              f"{feeds if feeds else 'none'}")
        rows = galaxy_cards(r.url, r.text)
        dates = [x["date"] for x in rows if x["date"]]
        print(f"                 {len(rows)} cards, {len(dates)} dated")
        helios = [x for x in rows
                  if re.search(r"(?i)helios|ercot|interconnection", x["title"])]
        print(f"                 Helios/ERCOT items: {len(helios)}")
        for x in helios:
            print(f"                   {x['date']}  {x['href'][:56]}")
            print(f"                     {x['title'][:88]}")

    if "announcements" not in pages:
        print("\n  /all-news/announcements did not return 200. Nothing further.")
        return

    print("\n" + "-" * 78)
    print("  SAME CONTENT OR DIFFERENT? overlap of hrefs")
    print("-" * 78)
    sets = {k: {x["href"] for x in galaxy_cards(v.url, v.text)}
            for k, v in pages.items()}
    for k, v in sets.items():
        print(f"    {k:<14} {len(v)} distinct hrefs")
    if "newsroom" in sets and "announcements" in sets:
        a, b = sets["newsroom"], sets["announcements"]
        print(f"    shared {len(a & b)}; only on newsroom {len(a - b)}; "
              f"only on announcements {len(b - a)}")
        for h in sorted(b - a)[:12]:
            print(f"      +announcements only: {h[:82]}")

    print("\n" + "-" * 78)
    print("  IS THE SEPARATION IN THE MARKUP? the <li> wrappers, both pages")
    print("-" * 78)
    for k in ("newsroom", "announcements"):
        if k not in pages:
            continue
        rows = galaxy_cards(pages[k].url, pages[k].text)
        c = Counter()
        for x in rows:
            m = re.findall(r'(?:class|data-[a-z-]+)="([^"]*)"', x["li"])
            c[" | ".join(m)[:120]] += 1
        print(f"\n    {k}:")
        for kk, vv in c.most_common(8):
            print(f"      {vv:>3}  {kk}")
        ext = sum(1 for x in rows if x["href"].startswith("http"))
        print(f"      {ext}/{len(rows)} cards link OFF-DOMAIN")

    print("\n" + "-" * 78)
    print("  CURATED OR STRUCTURAL? what the announcements page contains")
    print("-" * 78)
    rows = galaxy_cards(pages["announcements"].url, pages["announcements"].text)
    print(f"    {len(rows)} cards")
    for x in rows:
        off = "OFF-DOMAIN" if x["href"].startswith("http") else ""
        print(f"      {str(x['date']):<20}{off:<11}{x['href'][:44]:<45}"
              f"{x['title'][:34]}")


def part2():
    print("\n\n" + "=" * 78)
    print("PART 2 — ABTC: four routes")
    print("=" * 78)
    r = get(ABTC_NEWS)
    if r is None or r.status_code != 200:
        print("  news page unavailable")
        return
    h = r.text
    print(f"  {len(h):,} chars delivered\n")

    # ---------------------------------------------------------- (a) slugs --
    print("-" * 78)
    print("  (a) SLUGS — a title is recoverable; is a DATE?")
    print("-" * 78)
    slugs = sorted(set(re.findall(r'href="(/news-and-insights/[^"#?]+)"', h)))
    print(f"    {len(slugs)} distinct release slugs")
    for s in slugs[:8]:
        print(f"      {s[:96]}")
    dated = [s for s in slugs if re.search(r"/20\d{2}[-/]|\b20\d{2}\b", s)]
    print(f"    slugs containing a year: {len(dated)}/{len(slugs)}"
          + ("  <- no date in the slug" if not dated else ""))
    loose = DATE.findall(re.sub(r"(?is)<(script|style).*?</\1>", " ", h))
    print(f"    loose dates in the HTML: {len(loose)}; "
          f"{len(set(loose))} distinct")
    print(f"    pairing {len(slugs)} slugs to {len(set(loose))} distinct dates "
          f"by proximity is "
          + ("GUESSWORK" if len(slugs) != len(loose) else "arguable"))

    # -------------------------------------------------------- (b) sitemap --
    print("\n" + "-" * 78)
    print("  (b) SITEMAP — does lastmod track publication?")
    print("-" * 78)
    sm = get("https://www.abtc.com/sitemap.xml")
    entries = []
    if sm is not None and sm.status_code == 200:
        for m in re.finditer(r"<url>(.*?)</url>", sm.text, re.S):
            loc = re.search(r"<loc>([^<]+)</loc>", m.group(1))
            lm = re.search(r"<lastmod>([^<]+)</lastmod>", m.group(1))
            if loc:
                entries.append((loc.group(1),
                                lm.group(1)[:10] if lm else None))
        news = [e for e in entries if "/news-and-insights/" in e[0]]
        print(f"    {len(entries)} URLs, {len(news)} release pages")
        print(f"    distinct lastmod among releases: "
              f"{len({e[1] for e in news})}")
        for loc, lm in sorted(news, key=lambda x: x[1] or "")[-6:]:
            print(f"      {lm}  {urlparse(loc).path[:74]}")
    else:
        print("    sitemap unavailable")

    # ------------------------------------------------------------ (c) API --
    print("\n" + "-" * 78)
    print("  (c) BACKING API — read the bundles the scroll list uses")
    print("-" * 78)
    assets = sorted(set(re.findall(r'src="(/assets/[^"]+\.js)"', h)
                        + re.findall(r'href="(/assets/[^"]+\.js)"', h)))
    print(f"    {len(assets)} JS assets referenced")
    interesting = [a for a in assets
                   if re.search(r"(?i)news|scroll|index|api", a)] or assets[:6]
    endpoints = Counter()
    for a in interesting[:8]:
        rr = get(urljoin(ABTC_NEWS, a))
        if rr is None or rr.status_code != 200:
            continue
        body = rr.text
        print(f"      {a[:60]}  {len(body):,}b")
        for pat in (r"[\"'`](https?://[a-z0-9.\-]+/[^\"'`\s]{0,120})[\"'`]",
                    r"[\"'`](/(?:api|graphql|wp-json|_api)[^\"'`\s]{0,110})[\"'`]",
                    r"([a-z0-9\-]+\.(?:contentful|sanity|prismic|strapi|"
                    r"hygraph|datocms|builder)\.[a-z.]+/[^\"'`\s]{0,90})"):
            for m in re.finditer(pat, body):
                u = m.group(1)
                if re.search(r"(?i)\.(png|jpe?g|svg|woff2?|css|ico)$", u):
                    continue
                endpoints[u] += 1
        time.sleep(0.2)
    print(f"\n    {len(endpoints)} candidate endpoints:")
    for u, n in endpoints.most_common(20):
        print(f"      {n:>3}  {u[:104]}")

    # ---------------------------------------------------- (d) release page --
    print("\n" + "-" * 78)
    print("  (d) A RELEASE PAGE — does it carry NewsArticle/datePublished?")
    print("-" * 78)
    for s in slugs[:3]:
        rr = get(urljoin(ABTC_NEWS, s))
        if rr is None or rr.status_code != 200:
            print(f"    {s[:70]}: HTTP {rr.status_code if rr else '—'}")
            continue
        body = rr.text
        blocks = re.findall(
            r'(?s)<script[^>]+application/ld\+json[^>]*>(.*?)</script>', body)
        print(f"\n    {s[:74]}")
        print(f"      {len(body):,} chars, {len(blocks)} ld+json block(s)")
        for b in blocks:
            try:
                data = json.loads(b.strip())
            except Exception:                                    # noqa: BLE001
                print(f"        unparseable, {len(b)}b: {b[:80]}")
                continue
            for node in (data if isinstance(data, list) else [data]):
                t = node.get("@type")
                keys = [k for k in ("datePublished", "dateModified",
                                    "headline", "name") if k in node]
                print(f"        @type={t}  fields={keys}")
                for k in keys:
                    print(f"          {k}: {str(node[k])[:70]}")
        d = DATE.search(text_of(re.sub(r"(?is)<(script|style).*?</\1>", " ",
                                       body)))
        meta = re.findall(r'<meta[^>]+(?:property|name)="([^"]*(?:published|'
                          r'date|time)[^"]*)"[^>]*content="([^"]*)"', body, re.I)
        print(f"      first prose date: {d.group(0) if d else 'none'}")
        for k, v in meta[:6]:
            print(f"      meta {k}: {v[:50]}")
        time.sleep(0.2)


def main():
    part1()
    part2()
    return 0


if __name__ == "__main__":
    sys.exit(main())
