#!/usr/bin/env python3
"""
Measure the GLXY cross-host overlap before designing a dedupe rule.

TEMPORARY. Posts nothing, decides nothing.

TWO OVERLAPPING ITEMS IS NOT A SAMPLE. The feed carries 10 and the archive
carries 276 dated cards, so every overlap that exists can be enumerated rather
than inferred from the two that happened to be visible on one page.

WHAT IS ACTUALLY BEING ASKED. If the same release reaches press_monitor from
investor.galaxy.com and from www.galaxy.com under different URLs, `uid` — the
link — will not match and it posts twice. So:

  1. How many feed items have a counterpart in the newsroom at all?
  2. Of those, how many share a URL already? The archive's `newsroom-media`
     cards link OUT to investor.galaxy.com, so some overlaps may be free.
  3. Where the URLs differ, do the TITLES agree exactly after normalisation,
     or only approximately?
  4. And the question that decides everything: how close are two DIFFERENT
     releases to each other? A title rule is only safe if the gap between
     "same release, two hosts" and "two releases, same company" is wide. If
     the nearest non-match scores as high as the worst true match, no
     threshold exists and the rule cannot be built.

(4) IS THE POINT. (1)-(3) describe the matches; only (4) says whether a rule
can tell a match from a near-miss, and a near-miss is where the damage is —
failing to match posts twice, which is visible; matching too eagerly suppresses
a real release, which is silent.
"""

import re
import sys
from difflib import SequenceMatcher

import requests

import press_monitor as pm

FEED = "https://investor.galaxy.com/rss/news-releases.xml"
ARCHIVE = "https://www.galaxy.com/all-news/announcements"
NEWSROOM = "https://www.galaxy.com/newsroom"

STOP = re.compile(r"\b(?:a|an|the|and|of|to|for|in|on|with|its|at)\b")


def norm(t):
    t = re.sub(r"&[a-z]+;|&#\d+;", " ", (t or "").lower())
    t = re.sub(r"[^a-z0-9 ]+", " ", t)
    t = STOP.sub(" ", t)
    return re.sub(r"\s+", " ", t).strip()


def sim(a, b):
    return SequenceMatcher(None, norm(a), norm(b)).ratio()


def cards(url):
    r = requests.get(url, headers=pm.IR_HEADERS, timeout=(10, 30))
    out = []
    for cls, body in re.findall(
            r'(?is)<li[^>]*class="([^"]*post-list2__item[^"]*)"[^>]*>(.*?)</li>',
            r.text):
        t = re.search(r'class="card2__title"[^>]*>(.*?)</', body, re.S)
        h = re.search(r'href="([^"]+)"', body)
        d = re.search(r"(?:January|February|March|April|May|June|July|August|"
                      r"September|October|November|December)\s+\d{1,2},?\s+\d{4}",
                      body)
        if not t:
            continue
        kind = ("announcement" if "newsroom-announcements" in cls else
                "media" if "newsroom-media" in cls else
                "story" if "newsroom-our-stories" in cls else
                "video" if "newsroom-video" in cls else "other")
        out.append({
            "title": re.sub(r"\s+", " ",
                            re.sub(r"<[^>]+>", " ", t.group(1))).strip(),
            "href": h.group(1) if h else "",
            "date": d.group(0) if d else None,
            "kind": kind,
        })
    return out


def main():
    entries = pm.parse_feed(FEED)
    feed = [{"title": e.get("title") or "", "link": e.get("link") or "",
             "uid": e.get("id") or e.get("link") or ""} for e in entries]
    arch = cards(ARCHIVE)
    news = cards(NEWSROOM)
    print(f"feed {len(feed)} items | archive {len(arch)} cards | "
          f"newsroom {len(news)} cards\n")

    print("=" * 78)
    print("1-3. EACH FEED ITEM AGAINST THE NEWSROOM ARCHIVE")
    print("=" * 78)
    rows = []
    for f in feed:
        best = max(arch, key=lambda c: sim(f["title"], c["title"]))
        s = sim(f["title"], best["title"])
        # Does any card already point at this feed item's URL?
        url_hit = next((c for c in arch
                        if c["href"].rstrip("/") == f["link"].rstrip("/")), None)
        rows.append((f, best, s, url_hit))
        print(f"\n  FEED  {f['title'][:68]}")
        print(f"        {f['link'][:74]}")
        print(f"  BEST  {best['title'][:68]}")
        print(f"        {best['kind']:<13}{best['href'][:60]}")
        print(f"  score {s:.3f}   exact-after-norm "
              f"{norm(f['title']) == norm(best['title'])}   "
              f"URL already shared: {'YES' if url_hit else 'no'}")

    print("\n" + "=" * 78)
    print("SUMMARY OF THE MATCHES")
    print("=" * 78)
    strong = [r for r in rows if r[2] >= 0.90]
    exact = [r for r in rows if norm(r[0]["title"]) == norm(r[1]["title"])]
    shared = [r for r in rows if r[3]]
    print(f"  {len(feed)} feed items")
    print(f"  {len(exact)} match a card EXACTLY after normalisation")
    print(f"  {len(strong)} score >= 0.90")
    print(f"  {len(shared)} already share a URL with a card "
          f"(no dedupe needed at all)")
    print(f"  worst score among the exact matches: "
          f"{min([r[2] for r in exact], default=0):.3f}")

    print("\n" + "=" * 78)
    print("4. THE DANGEROUS PART — how close are DIFFERENT releases?")
    print("=" * 78)
    print("  Every archive announcement against every other. If the top of")
    print("  this distribution reaches the bottom of the matches above, no")
    print("  threshold separates them and a title rule cannot be built.\n")
    ann = [c for c in arch if c["kind"] in ("announcement", "media")]
    pairs = []
    for i, a in enumerate(ann):
        for b in ann[i + 1:]:
            if norm(a["title"]) == norm(b["title"]):
                continue          # the archive duplicates cards; not a pair
            pairs.append((sim(a["title"], b["title"]), a["title"], b["title"]))
    pairs.sort(reverse=True)
    print(f"  {len(pairs)} distinct pairs of DIFFERENT releases")
    print(f"  highest similarity between two different releases:")
    for s, a, b in pairs[:8]:
        print(f"    {s:.3f}  {a[:52]}")
        print(f"           {b[:52]}")
    if pairs and exact:
        ceiling = pairs[0][0]
        floor = min(r[2] for r in exact)
        print(f"\n  MARGIN: worst true match {floor:.3f} vs "
              f"closest false pair {ceiling:.3f}"
              + ("  -> a threshold exists" if floor > ceiling else
                 "  -> NO THRESHOLD SEPARATES THEM"))

    print("\n" + "=" * 78)
    print("SAME-DAY RELEASES — the weakness of date+company as a key")
    print("=" * 78)
    from collections import Counter
    c = Counter(x["date"] for x in ann if x["date"])
    multi = [(d, n) for d, n in c.most_common() if n > 1]
    print(f"  {len(multi)} dates carry more than one release; "
          f"max {multi[0][1] if multi else 0} on one day")
    for d, n in multi[:6]:
        print(f"    {d}: {n}")
        for x in ann:
            if x["date"] == d:
                print(f"        {x['title'][:62]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
