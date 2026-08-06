#!/usr/bin/env python3
"""
Read each company's most recent annual report for grid operators and sites.

Temporary probe, not a component. Posts nothing, writes nothing. It exists to
resolve the UNSWEPT rows in docs/watchlist.md's operating footprint table, and
the output is READ by a person — it does not decide anything itself.

WHY IT PRINTS EXCERPTS RATHER THAN A RANKING
--------------------------------------------
Counts narrow, they do not answer. The first sweep produced four findings that
a count alone would have got wrong, and each is a distinct failure mode:

  glossary        SLNH's ERCOT appears 19 times and every one is a definition,
                  not an operation. Tagged ESTIMATE for that reason.
  executive bio   HUT's single Duke Energy hit is a list of where its
                  executives previously worked, beside NextEra and Exelon. A
                  count would have made it a fourth Duke company.
  office not site CIFR's New York is leased office space; every data centre it
                  describes is in Texas or Ohio.
  state != grid   WULF's Texas site is in the Panhandle and the 10-K places it
                  in SPP, not ERCOT.

So every hit is printed with its surrounding sentence, and Delaware and
California are excluded from the state ranking outright — they are
incorporation and counsel addresses.

    SITES_TICKERS=GLXY,APLD,BTDR,SPCX,ABTC python -u probe_sites.py

Needs SEC_USER_AGENT, so run it through the workflow rather than locally.
"""

import html
import os
import re
import sys
import time
import urllib.request

import watchlist

UA = os.environ.get("SEC_USER_AGENT", "").strip()
if not UA:
    raise SystemExit("SEC_USER_AGENT is not set. SEC's fair-access filter "
                     "returns 403 from every sec.gov endpoint without a plain "
                     "name and contact address.")

TICKERS = [t.strip().upper() for t in
           os.environ.get("SITES_TICKERS", "").split(",") if t.strip()]
if not TICKERS:
    raise SystemExit("Set SITES_TICKERS=GLXY,APLD,...")

# 40-F is included because a Canadian MJDS filer's annual report is its 40-F.
# 20-F for foreign private issuers — BTDR files one.
ANNUAL = ("10-K", "20-F", "40-F")

SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik}.json"
ARCHIVE = "https://www.sec.gov/Archives/edgar/data/{cik}/{nodash}/{doc}"

# Word boundaries throughout. "SPP" without one matches "supplier"; "MISO"
# without one matches nothing useful either.
GRIDS = {
    "ERCOT": r"\bERCOT\b|Electric Reliability Council of Texas",
    "PJM": r"\bPJM\b|PJM Interconnection",
    "NYISO": r"\bNYISO\b|New York Independent System Operator",
    "MISO": r"\bMISO\b|Midcontinent Independent System Operator",
    "SPP": r"\bSPP\b|Southwest Power Pool",
    "CAISO": r"\bCAISO\b|California Independent System Operator",
    "ISO-NE": r"\bISO-?NE\b|ISO New England",
    "AESO": r"\bAESO\b|Alberta Electric System Operator",
    "IESO": r"\bIESO\b|Independent Electricity System Operator",
    "WECC": r"\bWECC\b",
    # Vertically integrated utilities outside any RTO. WYFI and CLSK sit here,
    # and "no RTO" is a real answer rather than a gap.
    "Duke Energy": r"\bDuke Energy\b",
    "Georgia Power": r"\bGeorgia Power\b",
    "Entergy": r"\bEntergy\b",
    "TVA": r"\bTVA\b|Tennessee Valley Authority",
    "Dominion": r"\bDominion Energy\b",
    "Xcel": r"\bXcel Energy\b",
    "Basin Electric": r"\bBasin Electric\b",
    "Otter Tail": r"\bOtter Tail\b",
    "Montana-Dakota": r"\bMontana-Dakota\b",
    # Non-US. BTDR operates outside the US and "none — outside any US RTO" is
    # the legitimate answer there, but only if the filing is actually read for
    # what it does say.
    "Statnett / Nord Pool": r"\bStatnett\b|\bNord Pool\b|\bNordpool\b",
    "Bhutan": r"\bBhutan\b|\bDruk Green\b|\bDruk Holding\b",
    "Ethiopia": r"\bEthiopian Electric\b|\bEthiopia\b",
}

STATES = [
    "Alabama", "Alaska", "Arizona", "Arkansas", "California", "Colorado",
    "Connecticut", "Delaware", "Florida", "Georgia", "Hawaii", "Idaho",
    "Illinois", "Indiana", "Iowa", "Kansas", "Kentucky", "Louisiana", "Maine",
    "Maryland", "Massachusetts", "Michigan", "Minnesota", "Mississippi",
    "Missouri", "Montana", "Nebraska", "Nevada", "New Hampshire", "New Jersey",
    "New Mexico", "New York", "North Carolina", "North Dakota", "Ohio",
    "Oklahoma", "Oregon", "Pennsylvania", "Rhode Island", "South Carolina",
    "South Dakota", "Tennessee", "Texas", "Utah", "Vermont", "Virginia",
    "Washington", "West Virginia", "Wisconsin", "Wyoming",
]
# Incorporation and counsel addresses. Excluded from the RANKING, still
# counted and printed, because "excluded" must not mean "invisible".
IGNORE_IN_RANKING = {"Delaware", "California"}

COUNTRIES = ["Norway", "Bhutan", "Ethiopia", "Canada", "Alberta", "Iceland",
             "Sweden", "Finland", "Paraguay", "Singapore", "Germany",
             "United Kingdom", "Ireland", "Japan", "Australia"]

MAX_EXCERPTS = 8
CONTEXT = 150


def fetch(url, binary=False):
    req = urllib.request.Request(
        url, headers={"User-Agent": UA, "Accept-Encoding": "gzip, deflate"})
    with urllib.request.urlopen(req, timeout=90) as r:
        raw = r.read()
        enc = r.headers.get("Content-Encoding")
    if enc == "gzip":
        import gzip
        raw = gzip.decompress(raw)
    return raw if binary else raw.decode("utf-8", errors="replace")


def strip_markup(doc):
    """HTML/iXBRL -> plain text, with whitespace normalised.

    Tags are replaced with a SPACE rather than removed. Filings put table cells
    hard against their tags, so deleting them welds `Texas</td><td>ERCOT` into
    `TexasERCOT` and both words stop matching.
    """
    doc = re.sub(r"(?is)<(script|style|head)[^>]*>.*?</\1>", " ", doc)
    doc = re.sub(r"(?s)<[^>]+>", " ", doc)
    doc = html.unescape(doc)
    doc = doc.replace("\xa0", " ")
    return re.sub(r"\s+", " ", doc).strip()


def latest_annual(cik):
    """(form, filed, period, accession, doc, entity_name, former_names)."""
    data = __import__("json").loads(fetch(SUBMISSIONS.format(cik=cik)))
    recent = (data.get("filings") or {}).get("recent") or {}
    forms = recent.get("form") or []
    best = None
    for i, form in enumerate(forms):
        core = form.split("/")[0]
        if core not in ANNUAL:
            continue
        filed = (recent.get("filingDate") or [""] * (i + 1))[i]
        if best is None or filed > best[1]:
            best = (form, filed,
                    (recent.get("reportDate") or [""] * (i + 1))[i],
                    (recent.get("accessionNumber") or [""] * (i + 1))[i],
                    (recent.get("primaryDocument") or [""] * (i + 1))[i])
    names = [n.get("name") for n in data.get("formerNames") or []]
    if best is None:
        # Not a gap. A company that has not reached its first annual report
        # cannot be swept by this method, and that resolves on a known date
        # rather than by trying harder.
        return None, data.get("name"), names, forms
    return best, data.get("name"), names, forms


def excerpts(text, pattern, limit=MAX_EXCERPTS):
    out, seen = [], set()
    for m in re.finditer(pattern, text, re.I):
        lo = max(0, m.start() - CONTEXT)
        hi = min(len(text), m.end() + CONTEXT)
        frag = text[lo:hi].strip()
        key = frag[:80].lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(frag)
        if len(out) >= limit:
            break
    return out


def sweep(ticker, cik, name):
    print("=" * 78)
    print(f"{ticker}  CIK {cik}  {name}")
    print("=" * 78)

    best, entity, formers, all_forms = latest_annual(cik)
    print(f"  EDGAR entity name : {entity}")
    if formers:
        print(f"  former names      : {', '.join(formers)}")
    if best is None:
        from collections import Counter
        print("  NO ANNUAL REPORT ON FILE.")
        print(f"  forms present     : "
              f"{', '.join(f'{f}x{n}' for f, n in Counter(all_forms).most_common(8))}")
        print("  This company cannot be swept by this method. That is a "
              "different state from 'not read yet' and it resolves on a known "
              "date — its first annual report.")
        print()
        return None

    form, filed, period, acc, doc = best
    url = ARCHIVE.format(cik=int(cik), nodash=acc.replace("-", ""), doc=doc)
    print(f"  latest annual     : {form} filed {filed}, period {period}")
    print(f"  accession         : {acc}")
    print(f"  {url}")

    try:
        raw = fetch(url)
    except Exception as e:                                  # noqa: BLE001
        print(f"  FETCH FAILED: {type(e).__name__}: {e}")
        print()
        return None
    text = strip_markup(raw)
    print(f"  document          : {len(raw) / 1e6:.1f} MB markup, "
          f"{len(text) / 1e3:.0f}k characters of text")

    # WHICH ENTITY DOES THIS FILING DESCRIBE? A reverse merger leaves the
    # predecessor's annual report as the most recent one on the successor's
    # CIK, and its properties are the predecessor's.
    print(f"  cover page opens  : {text[:300]}")
    print()

    print("  GRID OPERATORS AND UTILITIES")
    hits = {}
    for label, pattern in GRIDS.items():
        n = len(re.findall(pattern, text, re.I))
        if n:
            hits[label] = n
    if not hits:
        print("    none of the searched operators appear anywhere in the "
              "document.")
    for label, n in sorted(hits.items(), key=lambda kv: -kv[1]):
        print(f"    --- {label}: {n} mention(s) ---")
        for frag in excerpts(text, GRIDS[label]):
            print(f"        ...{frag}...")
    print()

    print("  STATES  (Delaware and California excluded from the ranking — "
          "incorporation and counsel)")
    counts = {s: len(re.findall(r"\b" + re.escape(s) + r"\b", text))
              for s in STATES}
    ranked = [(s, n) for s, n in counts.items()
              if n and s not in IGNORE_IN_RANKING]
    for s, n in sorted(ranked, key=lambda kv: -kv[1])[:8]:
        print(f"    --- {s}: {n} ---")
        for frag in excerpts(text, r"\b" + re.escape(s) + r"\b", 4):
            print(f"        ...{frag}...")
    excluded = [(s, n) for s, n in counts.items()
                if n and s in IGNORE_IN_RANKING]
    if excluded:
        print("    excluded from ranking but present: "
              + ", ".join(f"{s} {n}" for s, n in excluded))
    print()

    print("  NON-US")
    for c in COUNTRIES:
        n = len(re.findall(r"\b" + re.escape(c) + r"\b", text, re.I))
        if n:
            print(f"    --- {c}: {n} ---")
            for frag in excerpts(text, r"\b" + re.escape(c) + r"\b", 3):
                print(f"        ...{frag}...")
    print()

    # Arbitrary follow-up terms, for the second pass. The first pass narrows —
    # it says which operators and states are worth asking about — and a
    # question raised by the first pass is almost never answerable from the
    # same fixed vocabulary. APLD's MISO hit is the case: three mentions, all
    # about a generation project, and whether its own campuses sit on MISO
    # needs "interconnection", "substation" and the site names instead.
    extra = [e.strip() for e in
             os.environ.get("SITES_EXTRA", "").split("|") if e.strip()]
    if extra:
        print("  FOLLOW-UP TERMS")
        for term in extra:
            n = len(re.findall(term, text, re.I))
            print(f"    --- {term}: {n} ---")
            for frag in excerpts(text, term, 6):
                print(f"        ...{frag}...")
        print()

    # Item 2 Properties (10-K) / Item 4.D Property (20-F) is where the answer
    # usually is, when the filing has not incorporated it by reference.
    print("  PROPERTIES SECTION")
    for pat in (r"Item\s*2\.?\s*Propert", r"Item\s*4\.?\s*D\.?\s*Propert",
                r"Propert(?:y|ies),?\s*Plant"):
        m = list(re.finditer(pat, text, re.I))
        if m:
            start = m[-1].start()
            print(f"    matched {pat!r} at offset {start}")
            print(f"    ...{text[start:start + 2500]}...")
            break
    else:
        print("    no properties heading matched.")
    print()
    return hits


def main():
    ciks = watchlist.ciks()
    for ticker in TICKERS:
        if ticker not in ciks:
            print(f"{ticker} is not on the roster.")
            continue
        cik, name = ciks[ticker]
        try:
            sweep(ticker, cik, name)
        except Exception as e:                              # noqa: BLE001
            print(f"{ticker}: FAILED {type(e).__name__}: {e}")
        time.sleep(0.3)
    return 0


if __name__ == "__main__":
    sys.exit(main())
