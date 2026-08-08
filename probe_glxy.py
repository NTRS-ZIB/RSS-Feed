#!/usr/bin/env python3
"""Structure dump for galaxy.com/newsroom, so the scraper is written against
observed markup rather than a guess. TEMPORARY. Posts nothing."""

import re
import sys
from collections import Counter

import requests

import press_monitor as pm

URL = "https://www.galaxy.com/newsroom"


def main():
    r = requests.get(URL, headers=pm.IR_HEADERS, timeout=(10, 30))
    print(f"HTTP {r.status_code}, {len(r.text):,} chars, final {r.url}\n")
    h = r.text

    print("=" * 78)
    print("ANCHOR HREF SHAPES — which path prefix carries individual releases")
    print("=" * 78)
    pref = Counter()
    for m in re.finditer(r'href="(/[^"#?]*)"', h):
        parts = m.group(1).strip("/").split("/")
        pref["/" + "/".join(parts[:2])] += 1
    for k, v in pref.most_common(18):
        print(f"  {v:>4}  {k}")

    print("\n" + "=" * 78)
    print("A RELEASE ANCHOR IN CONTEXT — 1,400 chars around the first August item")
    print("=" * 78)
    m = re.search(r"August 0?7,? 2026", h)
    if m:
        s = max(0, m.start() - 900)
        print(h[s:m.start() + 500])
    else:
        print("no 'August 07, 2026' found; dumping around the first 2026 date")
        m2 = re.search(r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
                       r"[a-z]*\.?\s+\d{1,2},?\s+2026", h)
        if m2:
            s = max(0, m2.start() - 900)
            print(h[s:m2.start() + 500])

    print("\n" + "=" * 78)
    print("CLASS NAMES near dates — what a selector could key on")
    print("=" * 78)
    cls = Counter()
    for m in re.finditer(r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
                         r"[a-z]*\.?\s+\d{1,2},?\s+20\d{2}", h):
        window = h[max(0, m.start() - 400):m.start()]
        for c in re.findall(r'class="([^"]{0,120})"', window)[-3:]:
            cls[c.strip()] += 1
    for k, v in cls.most_common(14):
        print(f"  {v:>4}  {k[:100]}")

    print("\n" + "=" * 78)
    print("DATE + NEAREST FOLLOWING ANCHOR — the pairing a scraper would use")
    print("=" * 78)
    pairs = re.findall(
        r'(?is)((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+'
        r'\d{1,2},?\s+20\d{2}).{0,600}?<a[^>]+href="([^"]+)"[^>]*>(.{0,140}?)</a>',
        h)
    print(f"  {len(pairs)} date->anchor pairs\n")
    for d, href, text in pairs[:14]:
        t = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", text)).strip()
        print(f"  {d:<20} {href[:52]:<52} {t[:44]}")

    print("\n" + "=" * 78)
    print("REVERSE PAIRING — anchor then following date, in case order differs")
    print("=" * 78)
    rev = re.findall(
        r'(?is)<a[^>]+href="(/[^"]*)"[^>]*>(.{10,140}?)</a>.{0,400}?'
        r'((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+'
        r'\d{1,2},?\s+20\d{2})', h)
    print(f"  {len(rev)} anchor->date pairs\n")
    for href, text, d in rev[:14]:
        t = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", text)).strip()
        print(f"  {href[:50]:<50} {t[:40]:<40} {d}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
