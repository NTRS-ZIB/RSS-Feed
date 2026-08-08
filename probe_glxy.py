#!/usr/bin/env python3
"""Prototype the GLXY extraction against live markup, before it goes into
press_monitor.py. TEMPORARY. Posts nothing.

The structure, read off the dump rather than guessed:

    <a href="/newsroom/<slug>" ...>
        <figure><picture>... ~1,500 chars of srcset ...</picture></figure>
        <p class="card2__eyebrow"><span class="post-type">Research &bull;</span>
            August 07, 2026</p>
        <h3 class="card2__title">Weekly Research Brief: ...</h3>

Both regex pairing directions failed on the first dump because the image block
sits between the anchor and the text. So the title is the anchor point and the
date and href are found by looking BACKWARD from it.
"""

import html as htmlmod
import re
import sys
import time
from calendar import timegm
from collections import Counter
from urllib.parse import urljoin

import requests

import press_monitor as pm

URL = "https://www.galaxy.com/newsroom"
DATE = re.compile(
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+"
    r"\d{1,2},?\s+20\d{2}")


def text_of(fragment):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", fragment)).strip()


def main():
    r = requests.get(URL, headers=pm.IR_HEADERS, timeout=(10, 30))
    h = r.text
    print(f"HTTP {r.status_code}, {len(h):,} chars\n")

    print("=" * 78)
    print("CLASS INVENTORY — is card2__ the only card shape on the page?")
    print("=" * 78)
    c = Counter(re.findall(r'class="([a-z0-9_]*__(?:title|eyebrow))"', h))
    for k, v in c.most_common():
        print(f"  {v:>4}  {k}")
    print(f"  post-type values: "
          f"{Counter(text_of(m) for m in re.findall(r'<span class=\"post-type\">(.*?)</span>', h, re.S)).most_common()}")

    print("\n" + "=" * 78)
    print("EXTRACTION — title as the anchor point, date and href found backward")
    print("=" * 78)
    items, seen = [], set()
    for m in re.finditer(r'<h\d[^>]*class="[a-z0-9_]*__title"[^>]*>(.*?)</h\d>',
                         h, re.S):
        title = text_of(m.group(1))
        if not title:
            continue
        before = h[max(0, m.start() - 4000):m.start()]
        # nearest preceding eyebrow date
        eyes = re.findall(r'class="[a-z0-9_]*__eyebrow"[^>]*>(.*?)</p>',
                          before, re.S)
        when = None
        kind = None
        if eyes:
            d = DATE.search(text_of(eyes[-1]))
            when = d.group(0) if d else None
            k = re.search(r'<span class="post-type">(.*?)</span>', eyes[-1], re.S)
            kind = text_of(k.group(1)).rstrip("• ").strip() if k else None
        hrefs = re.findall(r'href="(/[^"]+)"', before)
        link = hrefs[-1] if hrefs else None
        items.append((when, kind, link, title))

    print(f"  {len(items)} cards\n")
    print(f"  {'date':<20}{'type':<14}{'href':<46}title")
    for when, kind, link, title in items:
        print(f"  {str(when):<20}{str(kind)[:13]:<14}{str(link)[:45]:<46}"
              f"{title[:40]}")

    print("\n" + "=" * 78)
    print("WHAT A PRESS-RELEASE FILTER WOULD KEEP")
    print("=" * 78)
    keep = [i for i in items
            if i[2] and re.fullmatch(r"/newsroom/[a-z0-9\-]+", i[2])]
    print(f"  {len(keep)} of {len(items)} have an href of /newsroom/<slug>")
    for when, kind, link, title in keep:
        print(f"    {str(when):<20}{str(kind)[:12]:<13}{title[:52]}")

    print("\n" + "=" * 78)
    print("DOCUMENT ORDER vs DATE ORDER — the thing the sort exists for")
    print("=" * 78)
    parsed = []
    for when, kind, link, title in keep:
        t = 0
        if when:
            for fmt in ("%B %d, %Y", "%b %d, %Y"):
                try:
                    t = timegm(time.strptime(when.replace(",", "") + "",
                                             fmt.replace(",", "")))
                    break
                except ValueError:
                    continue
        parsed.append((t, when, title))
    print("  as delivered:")
    for t, when, title in parsed[:8]:
        print(f"    {when:<20}{title[:52]}")
    print("  sorted by date:")
    for t, when, title in sorted(parsed, key=lambda x: -x[0])[:8]:
        print(f"    {when:<20}{title[:52]}")
    unsorted_first = parsed[0][0] if parsed else 0
    sorted_first = max((p[0] for p in parsed), default=0)
    print(f"\n  rows[0] {'HAPPENS to be newest' if unsorted_first == sorted_first else 'IS NOT the newest'}"
          f"; {sum(1 for a, b in zip(parsed, parsed[1:]) if a[0] < b[0])} "
          f"out-of-order adjacent pairs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
