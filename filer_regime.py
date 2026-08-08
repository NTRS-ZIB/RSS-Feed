#!/usr/bin/env python3
"""
Which regime does each company file under, and does anything sit outside EDGAR?

MAINTENANCE TOOL. Posts nothing, writes nothing. Run it when a company is
added, and when one changes listing or domicile.

WHY THIS RECURS. Every SEC-backed component keys off data.sec.gov. A company
on the foreign-private-issuer regime furnishes 6-Ks rather than filing 8-Ks,
and its annual report is a 20-F rather than a 10-K. Whether that costs the
repo anything depends on two conditions holding AT ONCE:

    1. the company is on the FPI regime, and
    2. it has a home regulator holding a record EDGAR does not.

**Neither one alone is a gap, and this roster has never had both at once.**
BTDR has the regime and no second regulator — Nasdaq-only, Cayman/Singapore.
DGXX has the regulator and left the regime on 2025-12-29. See
docs/rejected.md, entry eleven.

Condition 1 is mechanical and is what this tool checks. Condition 2 is a
judgement about listings and is left to the reader — the tool flags who to ask
it about rather than answering it.

DOMICILE DOES NOT DECIDE CONDITION 1, WHICH IS THE WHOLE REASON THIS EXISTS.
GLXY has Cayman history and never filed a 6-K or 20-F in its life; IREN is
Australian and moved to domestic forms on 2025-07-01. Reading incorporation
instead of form types puts both on a suspect list they do not belong on, and
that is the mistake the 2026-08-08 probe was scoped around before measuring
anything.

A SECOND CLAIM THIS CHECKS, because it is in the same family and was wrong.
probe_sites.incorporation_state() derives the state to ignore from the cover
page and finds nothing for BTDR. The docstring said a foreign private issuer
"has no such line". A 20-F cover page DOES carry a jurisdiction line — the
wording differs, "(Jurisdiction of incorporation or organization)" against the
10-K's "(State or other jurisdiction of incorporation or organization)". The
outcome is unchanged and correct; the reason given was not. This prints the
cover-page line for every FPI annual report so the claim stays checked rather
than remembered.
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
GAP = 0.15

FPI_FORMS = ("20-F", "40-F", "6-K")
DOMESTIC_FORMS = ("10-K", "10-Q", "8-K")
# A company can have years of 6-Ks and have stopped. Only recent filings say
# which regime it is on NOW, and the changeovers measured were clean to within
# a day, so a wide window is safe and a narrow one would misread a quiet month.
RECENT_FROM = "-24 months"

JURISDICTION = re.compile(
    r"\(\s*(?:State or other jurisdiction|Jurisdiction)\s+of\s+"
    r"incorporation[^)]*\)", re.I)


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
                         (b.get("primaryDocument") or [""] * len(forms))[i]))

    add((data.get("filings") or {}).get("recent") or {})
    for extra in (data.get("filings") or {}).get("files") or []:
        time.sleep(GAP)
        add(fetch(OLDER.format(name=extra["name"])))
    return rows


def strip_tags(html):
    html = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
    txt = re.sub(r"(?s)<[^>]+>", " ", html)
    for a, b in (("&nbsp;", " "), ("&amp;", "&"), ("&#160;", " ")):
        txt = txt.replace(a, b)
    return re.sub(r"\s+", " ", txt).strip()


def cutoff():
    from datetime import date
    t = date.today()
    y, m = (t.year - 2, t.month)
    return f"{y:04d}-{m:02d}-01"


def main():
    since = cutoff()
    print(f"Filing regime by company. 'Recent' means since {since}.\n")
    ciks = watchlist.ciks()
    rows = {}
    for t in sorted(ciks):
        try:
            rows[t] = all_filings(ciks[t][0])
        except Exception as e:                                   # noqa: BLE001
            print(f"  {t}: FETCH FAILED {type(e).__name__} — a fetch problem, "
                  f"not a finding about the company")
        time.sleep(GAP)

    print(f"  {'':6}{'20-F':>6}{'40-F':>6}{'6-K':>6}{'10-K':>7}{'10-Q':>7}"
          f"{'8-K':>6}   regime now")
    fpi_now = []
    for t in sorted(rows):
        c = Counter(f.split("/")[0] for _d, f, _a, _p in rows[t])
        recent = Counter(f.split("/")[0] for d, f, _a, _p in rows[t]
                         if d >= since)
        nf = sum(recent[k] for k in FPI_FORMS)
        nd = sum(recent[k] for k in DOMESTIC_FORMS)
        if nf and not nd:
            r = "FPI"
            fpi_now.append(t)
        elif nd and nf:
            r = "domestic (FPI history)"
        elif nd:
            r = "domestic"
        else:
            r = "no recent filings"
        print(f"  {t:<6}{c['20-F']:>6}{c['40-F']:>6}{c['6-K']:>6}"
              f"{c['10-K']:>7}{c['10-Q']:>7}{c['8-K']:>6}   {r}")

    print(f"\n  ON THE FPI REGIME NOW: "
          f"{', '.join(fpi_now) if fpi_now else 'none'}")
    if fpi_now:
        print("  Condition 1 holds for these. Condition 2 is a judgement:")
        print("  does the company have a home regulator holding a record")
        print("  EDGAR does not? A Nasdaq-only listing means no.")
        print("  See docs/rejected.md entry eleven before re-opening it.")

    # Anyone who has LEFT the regime, with the changeover date. A transition
    # is the moment to re-ask condition 2, and it is invisible in the census
    # above once it has happened.
    print("\n  CHANGEOVERS — the moment to re-ask, and easy to miss later")
    for t in sorted(rows):
        six = sorted(d for d, f, _a, _p in rows[t] if f.split("/")[0] == "6-K")
        eig = sorted(d for d, f, _a, _p in rows[t] if f.split("/")[0] == "8-K")
        if six and eig:
            print(f"    {t:<6} last 6-K {six[-1]}, first 8-K {eig[0]}"
                  f"{'  <- still on the FPI regime' if t in fpi_now else ''}")

    print("\n  COVER-PAGE JURISDICTION LINE on the latest annual report")
    print("  A 20-F carries one; the wording differs from a 10-K's, which is")
    print("  why probe_sites.incorporation_state() finds nothing for an FPI.")
    for t in sorted(rows):
        ann = sorted(((d, f, a, p) for d, f, a, p in rows[t]
                      if f.split("/")[0] in ("20-F", "40-F", "10-K") and p),
                     reverse=True)
        if not ann:
            continue
        d, f, a, p = ann[0]
        if f.split("/")[0] == "10-K" and t not in fpi_now:
            continue                      # the domestic wording is not in doubt
        try:
            txt = strip_tags(fetch(ARCHIVE.format(cik=int(ciks[t][0]),
                                                  acc=a.replace("-", ""),
                                                  doc=p), raw=True)
                             .decode("utf-8", "replace"))
        except Exception as e:                                   # noqa: BLE001
            print(f"    {t:<6}{f:<6} fetch failed {type(e).__name__}")
            continue
        m = JURISDICTION.search(txt)
        if m:
            s = max(0, m.start() - 60)
            print(f"    {t:<6}{f:<6}{d}  ...{txt[s:m.end()]}")
        else:
            print(f"    {t:<6}{f:<6}{d}  no jurisdiction line found")
        time.sleep(GAP)
    return 0


if __name__ == "__main__":
    sys.exit(main())
