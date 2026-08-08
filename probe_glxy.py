#!/usr/bin/env python3
"""Why four GLXY cards resolved to a wrong href or none. TEMPORARY.

The backward search gave `/all-news/media` for "Galaxy Completes ERCOT
Interconnection Study", which is a real release and exactly what this repo
wants. A WRONG LINK IS WORSE THAN A MISSING ONE — it posts and it resolves —
so the block those cards sit in has to be read before a selector is fixed.
"""

import re
import sys

import requests

import press_monitor as pm

URL = "https://www.galaxy.com/newsroom"


def main():
    h = requests.get(URL, headers=pm.IR_HEADERS, timeout=(10, 30)).text
    print(f"{len(h):,} chars\n")

    for needle in ("Galaxy Completes ERCOT Interconnection",
                   "Galaxy Announces Initial Closing"):
        print("=" * 78)
        print(needle)
        print("=" * 78)
        m = re.search(re.escape(needle), h)
        if not m:
            print("  not found\n")
            continue
        s, e = max(0, m.start() - 2600), min(len(h), m.start() + 1200)
        chunk = h[s:e]
        # Strip the srcset noise so the structure is readable.
        chunk = re.sub(r'srcset="[^"]*"', 'srcset="..."', chunk)
        chunk = re.sub(r'src="[^"]*"', 'src="..."', chunk)
        chunk = re.sub(r"\n\s*\n+", "\n", chunk)
        print(chunk)
        print()

    print("=" * 78)
    print("ALL hrefs in document order, with the card titles interleaved")
    print("=" * 78)
    marks = []
    for m in re.finditer(r'href="(/[^"]+)"', h):
        marks.append((m.start(), "href", m.group(1)))
    for m in re.finditer(r'<h\d[^>]*class="[a-z0-9_]*__title"[^>]*>(.*?)</h\d>',
                         h, re.S):
        t = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", m.group(1))).strip()
        marks.append((m.start(), "TITLE", t[:56]))
    marks.sort()
    for pos, kind, val in marks:
        if kind == "TITLE":
            print(f"  {pos:>7}  TITLE  {val}")
        elif not val.startswith(("/static", "/insights/podcasts")):
            print(f"  {pos:>7}  href   {val[:70]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
