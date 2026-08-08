#!/usr/bin/env python3
"""ABTC's Sanity dataset: enumerate the document types, then read the releases.

TEMPORARY. Posts nothing.

Part two found projectId=6zk22fw5, dataset=production, and the API answered
HTTP 200 — so it is public and reachable, which is the fact that matters. It
returned zero documents because my GROQ guessed the type names. Enumerate
first, query second.
"""

import json
import sys
import time

import requests

import press_monitor as pm

BASE = "https://6zk22fw5.apicdn.sanity.io/v2024-01-01/data/query/production"


def q(groq, label):
    url = BASE + "?query=" + requests.utils.quote(groq)
    try:
        r = requests.get(url, headers=pm.IR_HEADERS, timeout=(10, 30))
    except requests.RequestException as e:
        print(f"  {label}: {type(e).__name__}")
        return None
    print(f"\n  {label}  HTTP {r.status_code}  {len(r.content):,}b")
    if r.status_code != 200:
        print(f"    {r.text[:300]}")
        return None
    try:
        return r.json().get("result")
    except Exception:                                            # noqa: BLE001
        print(f"    not JSON: {r.text[:200]}")
        return None


def main():
    print("=" * 78)
    print("ABTC / Sanity — is this a readable source?")
    print("=" * 78)

    types = q("array::unique(*[]._type)", "document types")
    if types:
        print(f"    {len(types)} types: {sorted(t for t in types if t)}")

    counts = q('*[]{_type}', "type histogram")
    if counts:
        from collections import Counter
        c = Counter(d.get("_type") for d in counts)
        print(f"    {sum(c.values())} documents")
        for k, v in c.most_common(20):
            print(f"      {v:>4}  {k}")

    # Whatever the news type turns out to be, read it with every plausible
    # date field and let the output show which one is populated.
    for t in ("news", "newsArticle", "post", "article", "press", "pressRelease",
              "newsAndInsights", "insight"):
        res = q(f'*[_type == "{t}"] | order(_createdAt desc) [0...4]'
                '{_type,_id,_createdAt,_updatedAt,title,headline,'
                '"slug":slug.current,publishedAt,date,publishDate}',
                f'type "{t}"')
        if res:
            print(f"    {len(res)} document(s)")
            for d in res:
                print(f"      {json.dumps(d, default=str)[:230]}")
        time.sleep(0.2)

    # The count is the acceptance criterion: a floor that never empties is what
    # makes "zero items" mean a parse failure rather than a quiet month.
    total = q('count(*[_type match "*ews*" || _type match "*rticle*" || '
              '_type match "*ost*"])', "release-ish count")
    print(f"    {total}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
