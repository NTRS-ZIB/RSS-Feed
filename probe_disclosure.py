#!/usr/bin/env python3
"""
Probe: is the repo missing disclosure by reading EDGAR only?

TEMPORARY. Posts nothing, writes nothing, decides nothing.

THE GAP AS STATED. Every SEC-backed component keys off data.sec.gov, and the
footprint table's boundary is that it takes filings. For a foreign private
issuer the annual 20-F is a summary and a 6-K is furnished rather than filed,
so a company whose primary record is a home-jurisdiction regulator would reach
EDGAR only in abstract. Four of nineteen have a non-US home jurisdiction:
BTDR, IREN, DGXX, GLXY.

ONE THING NARROWS THIS BEFORE IT STARTS. A foreign domicile is not a gap. A
foreign private issuer may elect, or be required by losing FPI status, to file
on domestic forms — 10-K, 10-Q, 8-K — in which case EDGAR carries the complete
disclosure and the domicile is irrelevant. IREN is the named suspect here: it
is Australian and is believed to file 10-K. So phase 1 reads the form types
each of the four ACTUALLY files rather than reasoning from where they are
incorporated.

THE DECISIVE EDGAR-SIDE CHECK IS THE 6-K EXHIBIT LIST, and it is cheap.
A Canadian issuer's material change report is a prescribed document under
National Instrument 51-102. If it is FURNISHED AS AN EXHIBIT to a 6-K, then
EDGAR already carries the primary document rather than a summary of it, and
the SEDAR+ comparison is settled before it is run: both records hold the same
file. If the 6-K instead carries a press release or a cover-page narrative
while the material change report exists only in Canada, the gap is real.

That distinction cannot be made from form types, which is why this probe reads
document filenames and descriptions inside each 6-K accession rather than
counting them.

A CAUTION CARRIED FROM THE XSL TRAP. A parse failure is evidence about the URL
before it is evidence about the data. Every fetch here is checked for what it
actually returned, and anything unexpected is reported as a fetch problem, not
as a finding about the filing.
"""

import json
import os
import re
import sys
import time
import urllib.request
from collections import Counter, defaultdict

import watchlist

UA = os.environ.get("SEC_USER_AGENT", "").strip()
if not UA:
    raise SystemExit("SEC_USER_AGENT is not set.")

SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik}.json"
OLDER = "https://data.sec.gov/submissions/{name}"
ARCHIVE = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{doc}"
INDEX = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/index.json"
GAP = 0.15

# The four with a non-US home jurisdiction, per docs/watchlist.md.
FOREIGN = {
    "BTDR": "Cayman incorporation, Singapore HQ",
    "IREN": "Australia",
    "DGXX": "Canada (Ontario/British Columbia)",
    "GLXY": "Cayman until the 2025 Delaware redomiciliation",
}

# Forms that mark a foreign private issuer using the FPI regime.
FPI_FORMS = ("20-F", "40-F", "6-K")
# Forms only a domestic filer uses. An issuer filing these is not using the
# FPI regime whatever its domicile.
DOMESTIC_FORMS = ("10-K", "10-Q", "8-K")


def fetch(url, raw=False):
    req = urllib.request.Request(
        url, headers={"User-Agent": UA, "Accept-Encoding": "gzip, deflate"})
    with urllib.request.urlopen(req, timeout=90) as r:
        body = r.read()
        enc = r.headers.get("Content-Encoding")
        ctype = r.headers.get("Content-Type", "")
    if enc == "gzip":
        import gzip
        body = gzip.decompress(body)
    if raw:
        return body, ctype
    return json.loads(body)


def all_filings(cik):
    """(date, form, accession, primaryDocument, description) for every filing."""
    data = fetch(SUBMISSIONS.format(cik=cik))
    rows = []

    def add(b):
        forms = b.get("form") or []
        for i, f in enumerate(forms):
            rows.append((
                (b.get("filingDate") or [""] * len(forms))[i],
                f,
                (b.get("accessionNumber") or [""] * len(forms))[i],
                (b.get("primaryDocument") or [""] * len(forms))[i],
                (b.get("primaryDocDescription") or [""] * len(forms))[i],
            ))

    add((data.get("filings") or {}).get("recent") or {})
    for extra in (data.get("filings") or {}).get("files") or []:
        time.sleep(GAP)
        add(fetch(OLDER.format(name=extra["name"])))
    return rows


def strip_tags(html):
    html = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
    txt = re.sub(r"(?s)<[^>]+>", " ", html)
    txt = (txt.replace("&nbsp;", " ").replace("&amp;", "&")
              .replace("&#160;", " ").replace("&rsquo;", "'"))
    return re.sub(r"\s+", " ", txt)


# ---------------------------------------------------------------- phase 1 ----

def phase1():
    print("=" * 78)
    print("1. WHICH COMPANIES ACTUALLY HAVE A GAP")
    print("=" * 78)
    print("Domicile does not decide this. Form types do.\n")

    ciks = watchlist.ciks()
    out = {}
    for t in sorted(ciks):
        cik, _n = ciks[t]
        try:
            rows = all_filings(cik)
        except Exception as e:                                   # noqa: BLE001
            print(f"  {t}: FETCH FAILED {type(e).__name__} — reported as a "
                  f"fetch problem, not as a finding")
            continue
        out[t] = rows
        time.sleep(GAP)

    print(f"  {'':6}{'20-F':>6}{'40-F':>6}{'6-K':>6}{'10-K':>7}{'10-Q':>7}"
          f"{'8-K':>6}   regime")
    regime = {}
    for t in sorted(out):
        c = Counter(f for _d, f, _a, _p, _x in out[t])
        n = {k: sum(v for f, v in c.items() if f.split("/")[0] == k)
             for k in ("20-F", "40-F", "6-K", "10-K", "10-Q", "8-K")}
        fpi = n["20-F"] + n["40-F"] + n["6-K"]
        dom = n["10-K"] + n["10-Q"] + n["8-K"]
        if fpi and dom:
            r = "BOTH — transitioned"
        elif fpi:
            r = "FPI"
        elif dom:
            r = "domestic"
        else:
            r = "neither seen"
        regime[t] = (r, n)
        mark = "  <-" if t in FOREIGN else ""
        print(f"  {t:<6}{n['20-F']:>6}{n['40-F']:>6}{n['6-K']:>6}"
              f"{n['10-K']:>7}{n['10-Q']:>7}{n['8-K']:>6}   {r}{mark}")

    print("\n  THE FOUR WITH A NON-US HOME JURISDICTION")
    affected = []
    for t, why in sorted(FOREIGN.items()):
        if t not in regime:
            print(f"    {t:<6} not fetched")
            continue
        r, n = regime[t]
        # A company that has since moved to domestic forms has no ongoing gap
        # even if its history is full of 20-Fs.
        recent = [f for d, f, _a, _p, _x in out[t] if d >= "2025-01-01"]
        rc = Counter(f.split("/")[0] for f in recent)
        ongoing_fpi = sum(rc[k] for k in FPI_FORMS)
        ongoing_dom = sum(rc[k] for k in DOMESTIC_FORMS)
        verdict = ("GAP POSSIBLE" if ongoing_fpi and not ongoing_dom
                   else "NO GAP — files domestic forms" if ongoing_dom
                   else "no recent filings of either kind")
        if ongoing_fpi and not ongoing_dom:
            affected.append(t)
        print(f"    {t:<6} {why}")
        print(f"           since 2025-01-01: {ongoing_fpi} FPI-regime, "
              f"{ongoing_dom} domestic-form  ->  {verdict}")

    print(f"\n  Affected: {', '.join(affected) if affected else 'none'}")
    return out, affected


# ---------------------------------------------------------------- phase 2 ----

# What operational detail looks like in text. Not a semantic reading — a
# count of the vocabulary an Item 2 Properties section cannot avoid.
OPS = {
    "capacity MW": r"\b\d[\d,\.]*\s*(?:MW|megawatt)",
    "hashrate": r"\b\d[\d,\.]*\s*(?:EH/s|PH/s|TH/s|exahash|petahash)",
    "site/facility": r"\b(?:site|facility|facilities|campus|data cent)",
    "named grid": r"\b(?:ERCOT|PJM|MISO|NYISO|SPP|AESO|IESO|WECC|CAISO)\b",
    "properties item": r"(?i)item\s*2[^a-z0-9]{0,4}\s*propert",
}


def measure_ops(text):
    return {k: len(re.findall(p, text)) for k, p in OPS.items()}


def phase2(out, affected):
    print("\n" + "=" * 78)
    print("2. WHAT THE FPI FORMS OMIT — operational detail, measured")
    print("=" * 78)
    if not affected:
        print("  No company is on the FPI regime. Nothing to measure.")
        return
    print("Counts of the vocabulary an Item 2 Properties section cannot avoid.")
    print("A 20-F against domestic peers' 10-Ks, same measure both sides.\n")

    ciks = watchlist.ciks()

    def latest(t, forms):
        best = None
        for d, f, a, p, _x in out.get(t, []):
            if f.split("/")[0] in forms and p and (best is None or d > best[0]):
                best = (d, f, a, p)
        return best

    targets = [(t, "20-F/40-F", FPI_FORMS[:2]) for t in affected]
    # Domestic comparators: the two largest domestic filers on the roster with
    # a recent 10-K, so the count has something to be a count AGAINST.
    peers = [t for t in ("MARA", "CLSK", "RIOT", "CIFR", "WULF", "HUT")
             if latest(t, ("10-K",))]
    targets += [(t, "10-K", ("10-K",)) for t in peers[:3]]

    print(f"  {'':6}{'form':<7}{'date':<12}{'chars':>9}", end="")
    for k in OPS:
        print(f"{k:>15}", end="")
    print()
    for t, label, forms in targets:
        got = latest(t, forms)
        if not got:
            print(f"  {t:<6}{label:<7}— none found")
            continue
        d, f, a, p = got
        acc = a.replace("-", "")
        url = ARCHIVE.format(cik=int(ciks[t][0]), acc=acc, doc=p)
        try:
            body, ctype = fetch(url, raw=True)
        except Exception as e:                                   # noqa: BLE001
            print(f"  {t:<6}{label:<7}FETCH FAILED {type(e).__name__} — "
                  f"a fetch problem, not a finding about the filing")
            continue
        txt = strip_tags(body.decode("utf-8", "replace"))
        m = measure_ops(txt)
        print(f"  {t:<6}{f:<7}{d:<12}{len(txt):>9,}", end="")
        for k in OPS:
            print(f"{m[k]:>15,}", end="")
        print()
        time.sleep(GAP)


# ---------------------------------------------------------------- phase 3 ----

MCR_HINT = re.compile(
    r"(?i)material\s+change\s+report|form\s*51-102|51-102f3")
PR_HINT = re.compile(r"(?i)press\s+release|news\s+release")
FIN_HINT = re.compile(
    r"(?i)interim|financial\s+statement|MD&A|management.s\s+discussion")


def phase3(out):
    """The decisive EDGAR-side check: what is INSIDE DGXX's 6-Ks."""
    print("\n" + "=" * 78)
    print("3. WHAT IS INSIDE THE 6-Ks — the check that settles the comparison")
    print("=" * 78)
    print("If the Canadian material change report is furnished as an exhibit,")
    print("EDGAR carries the primary document and the gap is empty.\n")

    ciks = watchlist.ciks()
    for t in ("DGXX", "BTDR", "IREN", "GLXY"):
        sixk = [(d, a, p, x) for d, f, a, p, x in out.get(t, [])
                if f.split("/")[0] == "6-K"]
        if not sixk:
            print(f"  {t}: no 6-K filings")
            continue
        sixk.sort(reverse=True)
        print(f"  {t}: {len(sixk)} 6-K filings, "
              f"{sixk[-1][0]} to {sixk[0][0]}")

        kinds = Counter()
        exhibit_names = Counter()
        sample = sixk[:20]
        print(f"    reading the document list inside the {len(sample)} most "
              f"recent")
        for d, a, p, x in sample:
            acc = a.replace("-", "")
            try:
                idx = fetch(INDEX.format(cik=int(ciks[t][0]), acc=acc))
            except Exception as e:                               # noqa: BLE001
                print(f"      {d} {a}: index fetch failed {type(e).__name__}")
                continue
            items = (idx.get("directory") or {}).get("item") or []
            names = [i.get("name", "") for i in items]
            for n in names:
                if n.lower().endswith((".htm", ".html", ".txt", ".pdf")):
                    exhibit_names[re.sub(r"\d+", "#", n.lower())] += 1
            # Classify the accession by what its documents look like.
            blob = " ".join(names) + " " + (x or "")
            hit = set()
            if MCR_HINT.search(blob):
                hit.add("material change report")
            if PR_HINT.search(blob):
                hit.add("press release")
            if FIN_HINT.search(blob):
                hit.add("financials/MD&A")
            kinds["+".join(sorted(hit)) or "unclassified from names"] += 1
            time.sleep(GAP)

        print("    what the accessions look like:")
        for k, v in kinds.most_common():
            print(f"      {v:>3}  {k}")
        print("    most common document filenames (digits masked):")
        for k, v in exhibit_names.most_common(8):
            print(f"      {v:>3}  {k}")

        # Filenames are weak evidence. Read the exhibit text of the most
        # recent few and look for the prescribed MCR headings.
        print("    reading exhibit TEXT of the 3 most recent, because a "
              "filename is weak evidence:")
        for d, a, p, x in sixk[:3]:
            acc = a.replace("-", "")
            try:
                idx = fetch(INDEX.format(cik=int(ciks[t][0]), acc=acc))
            except Exception:                                    # noqa: BLE001
                continue
            docs = [i.get("name", "") for i in
                    ((idx.get("directory") or {}).get("item") or [])
                    if i.get("name", "").lower().endswith((".htm", ".html"))]
            found = []
            for doc in docs[:6]:
                try:
                    body, _c = fetch(
                        ARCHIVE.format(cik=int(ciks[t][0]), acc=acc, doc=doc),
                        raw=True)
                except Exception:                                # noqa: BLE001
                    continue
                txt = strip_tags(body.decode("utf-8", "replace"))
                tags = []
                if MCR_HINT.search(txt):
                    tags.append("MCR language")
                # NI 51-102F3 prescribes numbered items; these are its
                # distinctive ones.
                if re.search(r"(?i)full\s+description\s+of\s+material\s+change",
                             txt):
                    tags.append("51-102F3 item 3")
                if re.search(r"(?i)reliance\s+on\s+subsection\s+7\.1\(2\)",
                             txt):
                    tags.append("51-102F3 item 6")
                if PR_HINT.search(txt[:2000]):
                    tags.append("press release")
                ops = measure_ops(txt)
                found.append((doc, len(txt), tags, ops))
                time.sleep(GAP)
            print(f"      {d} {a}")
            for doc, n, tags, ops in found:
                opsum = " ".join(f"{k.split()[0]}={v}"
                                 for k, v in ops.items() if v)
                print(f"        {doc[:44]:<44} {n:>7,}ch  "
                      f"{', '.join(tags) or 'no marker'}  {opsum}")
        print()


def main():
    out, affected = phase1()
    phase2(out, affected)
    phase3(out)
    print("=" * 78)
    print("SEDAR+ usability is assessed outside this probe — it needs no SEC")
    print("credentials and the question is whether it is machine-readable.")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
