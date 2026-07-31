#!/usr/bin/env python3
"""
THROWAWAY PROBE — not a component. Delete after use.

Establishes where these companies actually operate, which is the gating step
for anything using ISO prices.

WHY THIS IS NEEDED
An LMP is priced at a specific node. Using one means choosing a PJM
transmission zone or an ERCOT settlement point on a company's behalf — and this
repo records no facility locations at all. The only site information anywhere
in it is that BGDE is headquartered in Midland, Pennsylvania and NUAI in
Midland, Texas, both taken from press release datelines.

A headquarters is not a data centre. Picking a node from a dateline would give
precise prices for the wrong place, which is worse than the current proxy
because it looks authoritative.

WHERE THE ANSWER LIVES
Item 2 of Form 10-K is "Properties", and the SEC requires principal facilities
to be described there. Foreign private issuers file 20-F or 40-F with different
structure — IREN and DGXX are the cases here.

WHAT THIS DOES
Fetches each company's most recent annual filing, strips the markup, and
reports:

  - which grid operators are named, and how often
  - which US states are named, ranked
  - the Item 2 Properties heading and a bounded excerpt around it
  - a few sentences of context around each grid mention

It does NOT decide the mapping. Filings describe owned sites, leased sites,
hosted capacity at third-party facilities and sites under development, often in
the same paragraph. Reading is required. This makes the reading tractable.

    SEC_USER_AGENT="Your Name you@example.com" python -u probe_sites.py
"""

import os
import re
import sys
import time
from collections import Counter

import requests

import watchlist

SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik}.json"
ARCHIVE = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{doc}"
ANNUAL_FORMS = ("10-K", "20-F", "40-F")

GRIDS = {
    "ERCOT": "Texas",
    "PJM": "Mid-Atlantic / Ohio Valley",
    "MISO": "Midwest",
    "NYISO": "New York",
    "NEW YORK ISO": "New York",
    "SPP": "Southwest Power Pool",
    "CAISO": "California",
    "TVA": "Tennessee Valley",
    "DUKE ENERGY": "Carolinas",
    "GEORGIA POWER": "Georgia",
}

STATES = [
    "Alabama", "Alaska", "Arizona", "Arkansas", "California", "Colorado",
    "Connecticut", "Delaware", "Florida", "Georgia", "Idaho", "Illinois",
    "Indiana", "Iowa", "Kansas", "Kentucky", "Louisiana", "Maine", "Maryland",
    "Massachusetts", "Michigan", "Minnesota", "Mississippi", "Missouri",
    "Montana", "Nebraska", "Nevada", "New Hampshire", "New Jersey",
    "New Mexico", "New York", "North Carolina", "North Dakota", "Ohio",
    "Oklahoma", "Oregon", "Pennsylvania", "Rhode Island", "South Carolina",
    "South Dakota", "Tennessee", "Texas", "Utah", "Vermont", "Virginia",
    "Washington", "West Virginia", "Wisconsin", "Wyoming",
]

MAX_DOC_BYTES = 25_000_000
CONTEXT = 220
MAX_SNIPPETS = 3
REQUEST_GAP = 0.3

UA = os.environ.get("SEC_USER_AGENT", "").strip()
TAG = re.compile(r"<[^>]+>")
WS = re.compile(r"\s+")


def sec_get(url, as_text=True):
    r = requests.get(url, headers={"User-Agent": UA or "watchlist-probe c@example.com",
                                   "Accept-Encoding": "gzip, deflate"},
                     timeout=(10, 60))
    r.raise_for_status()
    return r.text if as_text else r.json()


def latest_annual(cik):
    """(form, accession, primary document) for the most recent annual report."""
    data = sec_get(SUBMISSIONS.format(cik=cik), as_text=False)
    rec = data.get("filings", {}).get("recent", {})
    forms = rec.get("form", [])
    n = min(len(forms), len(rec.get("accessionNumber", [])),
            len(rec.get("primaryDocument", [])), len(rec.get("filingDate", [])))
    for i in range(n):
        if forms[i] in ANNUAL_FORMS:
            return (forms[i], rec["accessionNumber"][i],
                    rec["primaryDocument"][i], rec["filingDate"][i])
    return None


def plain_text(html):
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
    text = TAG.sub(" ", text)
    for a, b in (("&nbsp;", " "), ("&amp;", "&"), ("&#8217;", "'"),
                 ("&#8220;", '"'), ("&#8221;", '"'), ("&#151;", "-")):
        text = text.replace(a, b)
    return WS.sub(" ", text)


def snippets(text, needle, limit=MAX_SNIPPETS):
    out, start = [], 0
    low, nlow = text.lower(), needle.lower()
    while len(out) < limit:
        i = low.find(nlow, start)
        if i < 0:
            break
        out.append(text[max(0, i - CONTEXT):i + len(needle) + CONTEXT].strip())
        start = i + len(needle)
    return out


def main():
    if not UA:
        print("WARNING: SEC_USER_AGENT not set. SEC throttles anonymous traffic.\n")

    for ticker, (cik, name) in sorted(watchlist.ciks().items()):
        print("=" * 74)
        print(f"{ticker} — {name}")
        print("=" * 74)
        try:
            found = latest_annual(cik)
        except Exception as e:
            print(f"  submissions failed: {type(e).__name__}: {e}\n")
            continue
        if not found:
            print(f"  no {'/'.join(ANNUAL_FORMS)} on file\n")
            continue
        form, acc, doc, filed = found
        url = ARCHIVE.format(cik=int(cik), acc=acc.replace("-", ""), doc=doc)
        print(f"  {form} filed {filed}")
        print(f"  {url}")
        try:
            html = sec_get(url)
        except Exception as e:
            print(f"  fetch failed: {type(e).__name__}: {e}\n")
            continue
        if len(html) > MAX_DOC_BYTES:
            print(f"  document is {len(html)/1e6:.1f} MB — truncating")
            html = html[:MAX_DOC_BYTES]
        text = plain_text(html)
        print(f"  {len(text)/1000:.0f}k characters of text\n")

        grid_hits = {g: text.upper().count(g) for g in GRIDS}
        grid_hits = {g: c for g, c in grid_hits.items() if c}
        if grid_hits:
            print("  GRID OPERATORS NAMED")
            for g, c in sorted(grid_hits.items(), key=lambda kv: -kv[1]):
                print(f"    {g:<14} {c:>3}x   ({GRIDS[g]})")
        else:
            print("  GRID OPERATORS NAMED: none")

        counts = Counter()
        for st in STATES:
            c = len(re.findall(rf"\b{re.escape(st)}\b", text))
            if c:
                counts[st] = c
        print("\n  STATES NAMED (top 8)")
        for st, c in counts.most_common(8):
            print(f"    {st:<16} {c:>3}x")
        if not counts:
            print("    none")

        m = re.search(r"(?i)item\s*2[\.\s:—-]{0,4}\s*propert", text)
        print("\n  ITEM 2 — PROPERTIES")
        if m:
            print(f"    {text[m.start():m.start() + 700].strip()}")
        else:
            print("    heading not found — foreign issuers often use a different"
                  " structure")

        for g in sorted(grid_hits, key=lambda x: -grid_hits[x])[:2]:
            for s in snippets(text, g, 2):
                print(f"\n  ...{s}...")
        print()
        time.sleep(REQUEST_GAP)

    print("=" * 74)
    print("WHAT TO DO WITH THIS")
    print("=" * 74)
    print("""  Read it. The grid counts and state ranks narrow the search; they do not
  answer it. Filings mix owned sites, leased sites, hosted capacity at third-
  party facilities, and sites under development, often in one paragraph — a
  company can name Texas fifty times and own nothing there.

  What is worth extracting per company: the states with OPERATING capacity,
  roughly how many megawatts in each, and whether it is owned or hosted. That
  is what determines which ISO node, if any, represents its power cost.

  Companies whose capacity is hosted at a third party may have no meaningful
  node at all — they pay a contracted rate, not an LMP.""")
    return 0


if __name__ == "__main__":
    sys.exit(main())
