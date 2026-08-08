#!/usr/bin/env python3
"""
Probe: disclosure gap, part three — did DGXX's move to domestic forms LOSE the
material change report?

TEMPORARY. Posts nothing, writes nothing, decides nothing.

PARTS ONE AND TWO SETTLED THE QUESTION AS ASKED AND OPENED A BETTER ONE.

Settled: 20 of DGXX's 25 most recent 6-Ks furnish the actual Form 51-102F3
Material Change Report as Exhibit 99.1, prescribed items and all. During the
6-K era EDGAR carried the primary Canadian document, not a summary of it.

The better question: DGXX stopped filing 6-Ks on 2025-12-29 and started filing
8-Ks on 2026-01-06. It is STILL a Canadian reporting issuer — it uplisted to
Cboe Canada on 2026-02-27 — so it still files material change reports in
Canada. **A 6-K furnishes whatever the issuer published at home; an 8-K
reports enumerated items on a US template.** So the transition may have CLOSED
the FPI gap and OPENED a document gap at the same moment, which would be the
opposite of what the premise expected and is testable on EDGAR alone.

If the 8-K era carries no material change reports, then for DGXX the repo has
been reading the abstract since 2026-01-06 — and would not have been in 2025.

IREN is the control. It made the same transition on 2025-07-01 and is
Australian, where there is no material change report to lose. If the 8-K era
looks the same for both, the change is about the form and not the jurisdiction.
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

F3 = [
    r"(?i)item\s*1[^a-z0-9]{0,6}name\s+and\s+address\s+of\s+company",
    r"(?i)item\s*2[^a-z0-9]{0,6}date\s+of\s+material\s+change",
    r"(?i)item\s*3[^a-z0-9]{0,6}news\s+release",
    r"(?i)item\s*4[^a-z0-9]{0,6}summary\s+of\s+material\s+change",
    r"(?i)item\s*5[^a-z0-9]{0,6}full\s+description\s+of\s+material\s+change",
    r"(?i)item\s*7[^a-z0-9]{0,6}omitted\s+information",
    r"(?i)item\s*8[^a-z0-9]{0,6}executive\s+officer",
]
OPS = {
    "MW": r"\b\d[\d,\.]*\s*(?:MW|megawatt)",
    "hash": r"\b\d[\d,\.]*\s*(?:EH/s|PH/s|TH/s)",
    "site": r"\b(?:site|facility|facilities|campus|data cent)",
    "grid": r"\b(?:ERCOT|PJM|MISO|NYISO|SPP|AESO|IESO|WECC|CAISO)\b",
}


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
                         (b.get("accessionNumber") or [""] * len(forms))[i],
                         (b.get("primaryDocDescription") or [""] * len(forms))[i],
                         (b.get("items") or [""] * len(forms))[i]))

    add((data.get("filings") or {}).get("recent") or {})
    for extra in (data.get("filings") or {}).get("files") or []:
        time.sleep(GAP)
        add(fetch(OLDER.format(name=extra["name"])))
    return rows


def strip_tags(html):
    html = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
    txt = re.sub(r"(?s)<[^>]+>", " ", html)
    for a, b in (("&nbsp;", " "), ("&amp;", "&"), ("&#160;", " "),
                 ("&rsquo;", "'"), ("&#8217;", "'"), ("&ldquo;", '"'),
                 ("&rdquo;", '"')):
        txt = txt.replace(a, b)
    return re.sub(r"\s+", " ", txt).strip()


def scan(t, rows, form, n, label):
    """Read every exhibit of the n most recent filings of `form`."""
    cik = int(watchlist.ciks()[t][0])
    sel = sorted(((d, a, x) for d, f, a, x, _i in rows
                  if f.split("/")[0] == form), reverse=True)[:n]
    print(f"\n  {t} {label}: {len(sel)} {form} filings, "
          f"{sel[-1][0] if sel else '—'} to {sel[0][0] if sel else '—'}")
    if not sel:
        return Counter(), 0, 0
    tally = Counter()
    ops_total = Counter()
    chars = 0
    for d, a, desc in sel:
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
        best = 0
        for doc in docs:
            try:
                txt = strip_tags(fetch(ARCHIVE.format(cik=cik, acc=acc,
                                                      doc=doc), raw=True)
                                 .decode("utf-8", "replace"))
            except Exception:                                    # noqa: BLE001
                continue
            best = max(best, sum(1 for p in F3 if re.search(p, txt)))
            chars += len(txt)
            for k, p in OPS.items():
                ops_total[k] += len(re.findall(p, txt))
            time.sleep(GAP)
        tally["MATERIAL CHANGE REPORT" if best >= 4 else
              f"partial ({best} items)" if best else "no MCR"] += 1
    for k, v in tally.most_common():
        print(f"      {v:>3}  {k}")
    print(f"      {chars:,} chars of exhibit text; "
          + "  ".join(f"{k}={v}" for k, v in ops_total.items()))
    return tally, chars, sum(ops_total.values())


def main():
    print("=" * 78)
    print("DID THE MOVE TO DOMESTIC FORMS LOSE THE MATERIAL CHANGE REPORT?")
    print("=" * 78)

    rows = {}
    for t in ("DGXX", "IREN"):
        rows[t] = all_filings(watchlist.ciks()[t][0])
        time.sleep(GAP)

    print("\nDGXX — the same company either side of 2026-01-06")
    scan("DGXX", rows["DGXX"], "6-K", 15, "BEFORE (FPI regime)")
    scan("DGXX", rows["DGXX"], "8-K", 15, "AFTER (domestic regime)")

    print("\nIREN — the control. Australian; no MCR to lose either side.")
    scan("IREN", rows["IREN"], "6-K", 8, "BEFORE")
    scan("IREN", rows["IREN"], "8-K", 8, "AFTER")

    # The submissions API carries an `items` field for 8-Ks. What DGXX now
    # reports under, which is the whole difference between the two regimes.
    print("\n" + "=" * 78)
    print("WHAT DGXX'S 8-Ks REPORT UNDER")
    print("=" * 78)
    c = Counter()
    for d, f, _a, _x, items in rows["DGXX"]:
        if f.split("/")[0] == "8-K":
            for it in (items or "").split(","):
                if it.strip():
                    c[it.strip()] += 1
    for k, v in c.most_common():
        print(f"    {v:>3}  Item {k}")

    # And the descriptions, which is where part two's 'artefact' turned out to
    # be a real EDGAR metadata field worth reading directly.
    print("\n  primaryDocDescription on DGXX filings mentioning MCR:")
    n = 0
    for d, f, _a, desc, _i in sorted(rows["DGXX"], reverse=True):
        if desc and re.search(r"(?i)material change", desc):
            n += 1
            if n <= 12:
                print(f"    {d}  {f:<6} {desc[:60]}")
    print(f"    {n} filings total with a material-change description")
    latest = max((d for d, f, _a, desc, _i in rows["DGXX"]
                  if desc and re.search(r"(?i)material change", desc)),
                 default=None)
    print(f"    most recent: {latest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
