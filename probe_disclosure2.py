#!/usr/bin/env python3
"""
Probe: disclosure gap, part two — verify the three findings from part one.

TEMPORARY. Posts nothing, writes nothing, decides nothing.

PART ONE FOUND THREE THINGS AND ALL THREE NEED CHECKING BEFORE THEY ARE USED.

  1. Only BTDR is still on the FPI regime. DGXX, IREN and GLXY all file
     domestic forms now. Needs the transition DATES, because "has a 10-K" and
     "has stopped filing 6-Ks" are different claims and only the second one
     closes a gap.
  2. DGXX's 6-K exhibit 99.1 matched material-change-report language AND the
     51-102F3 item-3 heading. If true the primary Canadian document is on
     EDGAR. But the same regex also fired on `index-headers.html`, which is
     EDGAR's own metadata file and cannot contain a material change report —
     so at least one of those hits is an artefact and the finding is unsafe
     until the text is read rather than pattern-matched.
  3. BTDR's exhibits are press releases with no MCR language. Consistent with
     Cayman/Singapore having no continuous-disclosure regulator — but that is
     an argument, not a measurement, so this checks whether BTDR's 6-Ks ever
     carry a prescribed foreign document of any kind.

THE SECOND ONE IS THE PROBE. Everything else is scoping, again.
"""

import json
import os
import re
import sys
import time
import urllib.request
from collections import Counter

import watchlist

UA = os.environ.get("SEC_USER_AGENT", "").strip()
if not UA:
    raise SystemExit("SEC_USER_AGENT is not set.")

SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik}.json"
OLDER = "https://data.sec.gov/submissions/{name}"
ARCHIVE = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{doc}"
INDEX = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/index.json"
GAP = 0.15


def fetch(url, raw=False):
    req = urllib.request.Request(
        url, headers={"User-Agent": UA, "Accept-Encoding": "gzip, deflate"})
    with urllib.request.urlopen(req, timeout=90) as r:
        body = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            import gzip
            body = gzip.decompress(body)
    return body if raw else json.loads(body)


def all_filings(cik):
    data = fetch(SUBMISSIONS.format(cik=cik))
    rows = []

    def add(b):
        forms = b.get("form") or []
        for i, f in enumerate(forms):
            rows.append(((b.get("filingDate") or [""] * len(forms))[i], f,
                         (b.get("accessionNumber") or [""] * len(forms))[i]))

    add((data.get("filings") or {}).get("recent") or {})
    for extra in (data.get("filings") or {}).get("files") or []:
        time.sleep(GAP)
        add(fetch(OLDER.format(name=extra["name"])))
    return rows


def strip_tags(html):
    html = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
    txt = re.sub(r"(?s)<[^>]+>", " ", html)
    for a, b in (("&nbsp;", " "), ("&amp;", "&"), ("&#160;", " "),
                 ("&rsquo;", "'"), ("&#8217;", "'"), ("&quot;", '"')):
        txt = txt.replace(a, b)
    return re.sub(r"\s+", " ", txt).strip()


# ------------------------------------------------------------------- 1 ------

def transitions():
    print("=" * 78)
    print("1. TRANSITION DATES — has the FPI regime actually ENDED?")
    print("=" * 78)
    print("Having a 10-K and having stopped filing 6-Ks are different claims.")
    print("Only the second one closes a gap.\n")
    ciks = watchlist.ciks()
    out = {}
    for t in ("BTDR", "DGXX", "IREN", "GLXY"):
        rows = all_filings(ciks[t][0])
        out[t] = rows
        f = lambda k: sorted(d for d, fm, _a in rows           # noqa: E731
                             if fm.split("/")[0] == k)
        sixk, twentyf, tenk, eightk = f("6-K"), f("20-F"), f("10-K"), f("8-K")
        print(f"  {t}")
        print(f"    6-K   {len(sixk):>4}  "
              f"{(sixk[0] + ' to ' + sixk[-1]) if sixk else '—'}")
        print(f"    20-F  {len(twentyf):>4}  "
              f"{(twentyf[0] + ' to ' + twentyf[-1]) if twentyf else '—'}")
        print(f"    10-K  {len(tenk):>4}  "
              f"{(tenk[0] + ' to ' + tenk[-1]) if tenk else '—'}")
        print(f"    8-K   {len(eightk):>4}  "
              f"{(eightk[0] + ' to ' + eightk[-1]) if eightk else '—'}")
        if sixk and eightk:
            print(f"    -> last 6-K {sixk[-1]}, first 8-K {eightk[0]}; "
                  f"{'CLEAN CHANGEOVER' if eightk[0] > sixk[-1] else 'OVERLAP'}")
        time.sleep(GAP)
    return out


# ------------------------------------------------------------------- 2 ------

# NI 51-102F3 prescribes seven numbered items with fixed titles. A real
# material change report carries them; a press release does not.
F3_ITEMS = [
    (1, r"(?i)item\s*1[^a-z0-9]{0,6}name\s+and\s+address\s+of\s+company"),
    (2, r"(?i)item\s*2[^a-z0-9]{0,6}date\s+of\s+material\s+change"),
    (3, r"(?i)item\s*3[^a-z0-9]{0,6}news\s+release"),
    (4, r"(?i)item\s*4[^a-z0-9]{0,6}summary\s+of\s+material\s+change"),
    (5, r"(?i)item\s*5[^a-z0-9]{0,6}full\s+description\s+of\s+material\s+change"),
    (6, r"(?i)item\s*6[^a-z0-9]{0,6}reliance\s+on\s+subsection\s+7\.1\(2\)"),
    (7, r"(?i)item\s*7[^a-z0-9]{0,6}omitted\s+information"),
    (8, r"(?i)item\s*8[^a-z0-9]{0,6}executive\s+officer"),
]
LOOSE = re.compile(r"(?i)material\s+change\s+report|51-102F3")


def read_exhibits(t, rows, n=25):
    """Read every 6-K exhibit and classify it by what the TEXT says."""
    ciks = watchlist.ciks()
    cik = int(ciks[t][0])
    sixk = sorted(((d, a) for d, f, a in rows if f.split("/")[0] == "6-K"),
                  reverse=True)[:n]
    print(f"\n  {t}: reading exhibit TEXT of the {len(sixk)} most recent 6-Ks")
    tally = Counter()
    strict_hits = []
    for d, a in sixk:
        acc = a.replace("-", "")
        try:
            idx = fetch(INDEX.format(cik=cik, acc=acc))
        except Exception as e:                                   # noqa: BLE001
            print(f"    {d}: index fetch failed {type(e).__name__}")
            continue
        docs = [i.get("name", "") for i in
                ((idx.get("directory") or {}).get("item") or [])
                if i.get("name", "").lower().endswith((".htm", ".html"))
                and "index" not in i.get("name", "").lower()]
        best = None
        for doc in docs:
            try:
                txt = strip_tags(fetch(ARCHIVE.format(cik=cik, acc=acc,
                                                      doc=doc), raw=True)
                                 .decode("utf-8", "replace"))
            except Exception:                                    # noqa: BLE001
                continue
            hits = [n_ for n_, p in F3_ITEMS if re.search(p, txt)]
            loose = bool(LOOSE.search(txt))
            if best is None or len(hits) > len(best[2]):
                best = (doc, len(txt), hits, loose, txt)
            time.sleep(GAP)
        if best is None:
            tally["no readable exhibit"] += 1
            continue
        doc, ln, hits, loose, txt = best
        if len(hits) >= 4:
            kind = "MATERIAL CHANGE REPORT (>=4 prescribed items)"
            strict_hits.append((d, doc, hits, txt))
        elif hits:
            kind = f"partial — {len(hits)} prescribed item(s): {hits}"
        elif loose:
            kind = "phrase only, no prescribed items"
        else:
            kind = "no MCR marker"
        tally[kind] += 1
    print("    verdicts across those accessions:")
    for k, v in tally.most_common():
        print(f"      {v:>3}  {k}")
    return strict_hits, tally


def artefact_check(t, rows):
    """Part one's regex fired on index-headers.html. Find out why."""
    print("\n" + "=" * 78)
    print("2b. THE ARTEFACT — why the loose regex hit EDGAR's own metadata")
    print("=" * 78)
    ciks = watchlist.ciks()
    cik = int(ciks[t][0])
    sixk = sorted(((d, a) for d, f, a in rows if f.split("/")[0] == "6-K"),
                  reverse=True)
    if not sixk:
        return
    d, a = sixk[0]
    acc = a.replace("-", "")
    url = ARCHIVE.format(cik=cik, acc=acc,
                         doc=f"{a}-index-headers.html")
    try:
        txt = strip_tags(fetch(url, raw=True).decode("utf-8", "replace"))
    except Exception as e:                                       # noqa: BLE001
        print(f"  fetch failed {type(e).__name__}")
        return
    print(f"  {t} {d} index-headers.html, {len(txt):,} chars")
    for m in LOOSE.finditer(txt):
        s = max(0, m.start() - 120)
        print(f"    ...{txt[s:m.end() + 120]}...")
    if not LOOSE.search(txt):
        print("    no match here — the hit came from elsewhere")


def main():
    out = transitions()

    print("\n" + "=" * 78)
    print("2. WHAT THE 6-K EXHIBITS ACTUALLY ARE")
    print("=" * 78)
    print("NI 51-102F3 prescribes numbered items with fixed titles. A real")
    print("material change report carries them; a press release does not.")
    print("A loose phrase match is not enough — part one's fired on metadata.")

    quotes = {}
    for t in ("DGXX", "BTDR"):
        hits, _tally = read_exhibits(t, out[t])
        quotes[t] = hits

    artefact_check("DGXX", out["DGXX"])

    print("\n" + "=" * 78)
    print("3. THE ACTUAL TEXT — quoted, so the verdict can be checked")
    print("=" * 78)
    for t, hits in quotes.items():
        if not hits:
            print(f"\n  {t}: no exhibit carried >=4 prescribed items.")
            continue
        d, doc, items, txt = hits[0]
        print(f"\n  {t} {d} {doc} — prescribed items found: {items}")
        print(f"    first 700 characters:")
        print(f"    {txt[:700]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
