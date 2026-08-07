#!/usr/bin/env python3
"""
Probe: can holder concentration be backfilled from EDGAR Schedule 13D/G?

TEMPORARY. Posts nothing, writes nothing, decides nothing. It answers four
questions in order, because each one bounds the next:

  inventory   how many 13D/G filings exist per company, both spellings, split
              initial vs amendment. Decides whether this is a small table or a
              different component entirely.
  structured  does primary_doc.xml carry reporting person, aggregate amount,
              percent of class and CUSIP as ELEMENTS rather than prose — and
              is the XML changeover the same date as the form-string
              changeover of 2024-12-16? They may not be.
  legacy      is the pre-changeover HTML parseable? A clean negative bounds
              any component to the structured era rather than leaving the
              question open.
  timeline    THE ONE THAT DECIDES IT. Reconstruct above-5% holders over time.
              If every company sits at the same three institutions forever,
              the component reports a constant and there is nothing to build.

    HOLDERS_PHASE=inventory python -u probe_holders.py
    HOLDERS_PHASE=structured HOLDERS_TICKERS=ANY,MARA python -u probe_holders.py

Needs SEC_USER_AGENT. Run it through the workflow.

A CENSUS OVER A TAG LIST IS ONLY AS GOOD AS THE TAG LIST, AND IT FAILS AS A
PLAUSIBLE NUMBER RATHER THAN AS AN ERROR.

The census phase reported "group filings: 233 (100%)" and "310 distinct
reporting persons". Both were wrong. It took the first element anywhere in the
document whose tag was in a candidate list, and `personName` under
`coverPageHeader/authorizedPersons/notificationInfo` precedes the reporting
persons in document order — so every filing was credited to its notification
contact, the filing agent's clerk.

Nothing errored. Both numbers were the right order of magnitude and would have
been reported as findings. What caught it was a single visibly wrong name:
ANY's July 13D read "Joshua Kilgore" where the filer is Endeavor Blockchain,
LLC. **Without that name being recognisable, the contamination was invisible.**

So: when a census counts occurrences of a tag, check that the tag it found is
the tag it meant, on a case whose answer is known independently. A count over
the wrong element looks exactly like a count over the right one.

WHAT THIS PROBE MUST NOT CONCLUDE
Two things are known before it starts and no output here can overturn them:

  * A 13D/G reports a HOLDER'S position, not a company's ownership structure.
    Anyone below 5% never files, so any concentration figure built from these
    has a floor and is not an institutional total.
  * A stale 13G is not a departure. A holder dropping below 5% files a final
    amendment; a holder who simply stops filing may still hold. That is the
    young-versus-failed distinction again, and it decides whether a component
    could report a holder LEAVING at all.
"""

import json
import os
import statistics
import re
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from datetime import date

import watchlist

UA = os.environ.get("SEC_USER_AGENT", "").strip()
if not UA:
    raise SystemExit("SEC_USER_AGENT is not set.")

PHASE = os.environ.get("HOLDERS_PHASE", "inventory").strip()
ONLY = [t.strip().upper() for t in
        os.environ.get("HOLDERS_TICKERS", "").split(",") if t.strip()]

SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik}.json"
OLDER = "https://data.sec.gov/submissions/{name}"
ARCHIVE = "https://www.sec.gov/Archives/edgar/data/{cik}/{nodash}/{doc}"

# Both spellings. "SCHEDULE 13D" does not start with "SC 13D" — the fourth
# character is H, not a space — which is how 117 filings went silently
# unmatched for eight months. See press_monitor.FORM_TYPES.
FAMILIES = ("SC 13D", "SC 13G", "SCHEDULE 13D", "SCHEDULE 13G")

# Never a silent cap.
MAX_DOCS = int(os.environ.get("HOLDERS_MAX_DOCS", "400"))
GAP = 0.12


def fetch(url, as_json=True):
    req = urllib.request.Request(
        url, headers={"User-Agent": UA, "Accept-Encoding": "gzip, deflate"})
    with urllib.request.urlopen(req, timeout=60) as r:
        raw = r.read()
        enc = r.headers.get("Content-Encoding")
    if enc == "gzip":
        import gzip
        raw = gzip.decompress(raw)
    return json.loads(raw) if as_json else raw.decode("utf-8", "replace")


def all_filings(cik):
    """Every filing on the index, recent page plus older files."""
    data = fetch(SUBMISSIONS.format(cik=cik))
    rows = []

    def add(block):
        forms = block.get("form") or []
        for i, form in enumerate(forms):
            def at(k):
                seq = block.get(k) or []
                return seq[i] if i < len(seq) else ""
            rows.append({"form": form, "filed": at("filingDate"),
                         "accession": at("accessionNumber"),
                         "doc": at("primaryDocument"),
                         "desc": at("primaryDocDescription")})

    add((data.get("filings") or {}).get("recent") or {})
    for extra in (data.get("filings") or {}).get("files") or []:
        time.sleep(GAP)
        add(fetch(OLDER.format(name=extra["name"])))
    return rows, data.get("name")


def is_13x(form):
    return any(form.startswith(f) for f in FAMILIES)


def family(form):
    for f in FAMILIES:
        if form.startswith(f):
            return f
    return None


# EDGAR's `primaryDocument` for a structured 13D/G is
# `xslSCHEDULE_13D_X02/primary_doc.xml` — the XSL-RENDERED HTML VIEW, not the
# XML. Fetching it returns HTML and ElementTree dies on the first unclosed tag,
# which reads exactly like "the filing is not structured after all". The raw
# document sits in the same accession directory with the stylesheet segment
# removed.
XSL_SEGMENT = re.compile(r"^xsl[A-Z0-9_]+/", re.I)


def raw_xml_path(doc):
    return XSL_SEGMENT.sub("", doc)


def roster():
    ciks = watchlist.ciks()
    return {t: v for t, v in ciks.items() if not ONLY or t in ONLY}


# ------------------------------------------------------------- INVENTORY ----


def phase_inventory():
    print("=" * 78)
    print("INVENTORY — 13D/G across full EDGAR history, both spellings")
    print("=" * 78)
    print(f"{'':6}{'13D':>5}{'13D/A':>7}{'13G':>5}{'13G/A':>7}{'total':>7}"
          f"{'initial':>9}   {'earliest':<12}{'newest':<12} legacy->structured")
    grand = Counter()
    per_company = {}
    changeover = {}
    for ticker, (cik, _name) in sorted(roster().items()):
        try:
            rows, _entity = all_filings(cik)
        except Exception as e:                                  # noqa: BLE001
            print(f"{ticker:<6} FAILED {type(e).__name__}")
            continue
        hits = [r for r in rows if is_13x(r["form"])]
        per_company[ticker] = hits
        c = Counter()
        for r in hits:
            fam = family(r["form"])
            amend = r["form"].endswith("/A")
            key = ("13D" if "13D" in fam else "13G") + ("/A" if amend else "")
            c[key] += 1
            grand[key] += 1
        dates = sorted(r["filed"] for r in hits if r["filed"])
        # The form-string changeover, measured per company rather than assumed:
        # the oldest SCHEDULE-spelling filing against the newest SC-spelling one.
        old = [r["filed"] for r in hits if family(r["form"]).startswith("SC ")]
        new = [r["filed"] for r in hits
               if family(r["form"]).startswith("SCHEDULE")]
        span = ""
        if old and new:
            span = f"{max(old)} -> {min(new)}"
            changeover[ticker] = (max(old), min(new))
        elif new:
            span = f"structured only, from {min(new)}"
        elif old:
            span = "legacy only"
        initial = c["13D"] + c["13G"]
        print(f"{ticker:<6}{c['13D']:>5}{c['13D/A']:>7}{c['13G']:>5}"
              f"{c['13G/A']:>7}{sum(c.values()):>7}{initial:>9}   "
              f"{(dates[0] if dates else '-'):<12}"
              f"{(dates[-1] if dates else '-'):<12}{span}")

    total = sum(grand.values())
    initial = grand["13D"] + grand["13G"]
    print()
    print(f"  {total} filings across {len(per_company)} companies — "
          f"{initial} initial, {total - initial} amendments "
          f"({(total - initial) / total * 100:.0f}% amendments)"
          if total else "  no filings")
    print(f"  13D {grand['13D']} + {grand['13D/A']} amendments · "
          f"13G {grand['13G']} + {grand['13G/A']} amendments")
    if changeover:
        lastold = max(v[0] for v in changeover.values())
        firstnew = min(v[1] for v in changeover.values())
        print(f"\n  FORM-STRING CHANGEOVER, measured: newest 'SC 13x' anywhere "
              f"is {lastold}, oldest 'SCHEDULE 13x' anywhere is {firstnew}")

    by_year = Counter()
    for hits in per_company.values():
        for r in hits:
            if r["filed"]:
                by_year[r["filed"][:4]] += 1
    print("\n  by year: " + "  ".join(f"{y} {n}"
                                      for y, n in sorted(by_year.items())))
    return per_company


# ------------------------------------------------------------ STRUCTURED ----


def dump_tree(elem, path="", out=None, depth=0):
    out = out if out is not None else []
    tag = elem.tag.split("}")[-1]
    here = f"{path}/{tag}"
    text = (elem.text or "").strip()
    if text:
        out.append((here, text[:80]))
    for child in elem:
        dump_tree(child, here, out, depth + 1)
    return out


def phase_structured():
    print("=" * 78)
    print("STRUCTURED ERA — does primary_doc.xml carry the fields?")
    print("=" * 78)
    fetched = 0
    first_xml = {}
    for ticker, (cik, _name) in sorted(roster().items()):
        rows, _ = all_filings(cik)
        hits = sorted((r for r in rows if is_13x(r["form"])),
                      key=lambda r: r["filed"])
        if not hits:
            continue
        print(f"\n--- {ticker} — {len(hits)} filings, "
              f"{sum(1 for h in hits if h['doc'].endswith('.xml'))} with an "
              f".xml primary document")
        # primaryDocument tells us the shape without a fetch.
        shapes = Counter(("xml" if r["doc"].endswith(".xml")
                          else "htm" if r["doc"] else "none") for r in hits)
        print(f"    primaryDocument shapes: {dict(shapes)}")
        xmls = [r for r in hits if r["doc"].endswith(".xml")]
        htms = [r for r in hits if not r["doc"].endswith(".xml")]
        if xmls:
            first_xml[ticker] = xmls[0]["filed"]
            print(f"    oldest .xml {xmls[0]['filed']} ({xmls[0]['form']})"
                  f"   newest .htm "
                  f"{max((h['filed'] for h in htms), default='-')}")
        if fetched >= MAX_DOCS or not xmls:
            continue
        sample = xmls[-1]
        url = ARCHIVE.format(cik=int(cik),
                             nodash=sample["accession"].replace("-", ""),
                             doc=raw_xml_path(sample["doc"]))
        try:
            raw = fetch(url, as_json=False)
            fetched += 1
        except Exception as e:                                  # noqa: BLE001
            print(f"    fetch failed: {type(e).__name__}")
            continue
        print(f"    sample {sample['form']} {sample['filed']} {url}")
        try:
            root = ET.fromstring(raw)
        except ET.ParseError as e:
            print(f"    NOT XML: {e}")
            continue
        for path, text in dump_tree(root):
            print(f"      {path} = {text}")
        time.sleep(GAP)
    print(f"\n  oldest .xml primary document per company:")
    for t, d in sorted(first_xml.items(), key=lambda kv: kv[1]):
        print(f"    {t:<6} {d}")
    if first_xml:
        print(f"  earliest anywhere: {min(first_xml.values())}")
    print(f"\n  documents fetched: {fetched}"
          + (f" — HIT THE {MAX_DOCS} CEILING, sample is truncated"
             if fetched >= MAX_DOCS else ""))


# ---------------------------------------------------------------- LEGACY ----

PCT_PATTERNS = [
    r"PERCENT OF CLASS REPRESENTED BY AMOUNT IN ROW.{0,80}?([\d.]+)\s*%",
    r"Percent of [Cc]lass.{0,120}?([\d.]+)\s*%",
    r"([\d.]+)\s*%\s*of the (?:outstanding )?[Cc]ommon [Ss]tock",
]


def strip_html(doc):
    doc = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", doc)
    doc = re.sub(r"(?s)<[^>]+>", " ", doc)
    import html as _h
    return re.sub(r"\s+", " ", _h.unescape(doc)).strip()


def phase_legacy():
    print("=" * 78)
    print("LEGACY ERA — is the pre-changeover HTML parseable?")
    print("=" * 78)
    print("Expecting a negative. A clean one bounds any component to the")
    print("structured era instead of leaving the question open.\n")
    tried = 0
    parsed = 0
    for ticker, (cik, _name) in sorted(roster().items()):
        rows, _ = all_filings(cik)
        htms = sorted((r for r in rows if is_13x(r["form"])
                       and r["doc"] and not r["doc"].endswith(".xml")),
                      key=lambda r: r["filed"], reverse=True)
        for sample in htms[:2]:
            if tried >= MAX_DOCS:
                break
            url = ARCHIVE.format(cik=int(cik),
                                 nodash=sample["accession"].replace("-", ""),
                                 doc=sample["doc"])
            try:
                raw = fetch(url, as_json=False)
                tried += 1
            except Exception as e:                              # noqa: BLE001
                print(f"  {ticker} {sample['filed']}: fetch {type(e).__name__}")
                continue
            text = strip_html(raw)
            found = []
            for pat in PCT_PATTERNS:
                for m in re.finditer(pat, text, re.I):
                    found.append((pat[:34], m.group(1)))
            ok = "PARSED" if found else "no match"
            if found:
                parsed += 1
            print(f"  {ticker} {sample['form']:<14} {sample['filed']} "
                  f"{len(text) // 1000:>4}k chars  {ok}"
                  + (f"  {found[:4]}" if found else ""))
            if not found:
                idx = text.upper().find("PERCENT OF CLASS")
                if idx >= 0:
                    print(f"        ...{text[idx:idx + 200]}...")
                else:
                    print("        'PERCENT OF CLASS' does not appear at all")
            time.sleep(GAP)
    print(f"\n  {parsed}/{tried} legacy documents yielded a percent-of-class "
          f"by regex")


# -------------------------------------------------------------- TIMELINE ----

# Field names are not guessed — they are whatever the structured phase reports.
# These are probed in order and the one that hits is printed, the same shape
# regsho_volume.py uses for FINRA's shifting column names.
NAME_TAGS = ["reportingPersonName", "filerName", "name", "personName",
             "companyName", "rptOwnerName"]
PCT_TAGS = ["percentOfClass", "classPercent", "percentClass"]
AMT_TAGS = ["aggregateAmountOwned", "amountBeneficiallyOwned", "aggregateAmount"]
# Measured from a real filing, not guessed: the tag is
# issuerCusipNumber, nested under coverPageHeader/issuerInfo/issuerCusips.
CUSIP_TAGS = ["issuerCusipNumber", "issuerCUSIP", "cusip", "cusipNumber"]


def first_text(root, names):
    for el in root.iter():
        tag = el.tag.split("}")[-1]
        if tag in names and (el.text or "").strip():
            return tag, el.text.strip()
    return None, None


def all_text(root, names):
    out = []
    for el in root.iter():
        tag = el.tag.split("}")[-1]
        if tag in names and (el.text or "").strip():
            out.append(el.text.strip())
    return out


def phase_timeline():
    print("=" * 78)
    print("TIMELINE — does holder concentration actually move?")
    print("=" * 78)
    print("The question that decides whether there is anything to build. A")
    print("roster of three institutions that never change is a constant.\n")
    fetched = 0
    for ticker, (cik, _name) in sorted(roster().items()):
        rows, _ = all_filings(cik)
        xmls = sorted((r for r in rows if is_13x(r["form"])
                       and r["doc"].endswith(".xml")),
                      key=lambda r: r["filed"])
        if not xmls:
            print(f"\n--- {ticker}: no structured filings")
            continue
        print(f"\n--- {ticker}: {len(xmls)} structured filings "
              f"{xmls[0]['filed']} .. {xmls[-1]['filed']}")
        events = []
        for r in xmls:
            if fetched >= MAX_DOCS:
                print(f"    HIT THE {MAX_DOCS}-DOCUMENT CEILING — "
                      f"this company is truncated")
                break
            url = ARCHIVE.format(cik=int(cik),
                                 nodash=r["accession"].replace("-", ""),
                                 doc=raw_xml_path(r["doc"]))
            try:
                root = ET.fromstring(fetch(url, as_json=False))
                fetched += 1
            except Exception as e:                              # noqa: BLE001
                print(f"    {r['filed']} {r['form']}: {type(e).__name__}")
                continue
            _t, holder = first_text(root, NAME_TAGS)
            pcts = all_text(root, PCT_TAGS)
            amts = all_text(root, AMT_TAGS)
            _c, cusip = first_text(root, CUSIP_TAGS)
            events.append((r["filed"], r["form"], holder, pcts, amts, cusip))
            time.sleep(GAP)
        for filed, form, holder, pcts, amts, cusip in events:
            print(f"    {filed}  {form:<14} {str(holder)[:38]:<38} "
                  f"pct={','.join(pcts[:3]) or '-':<14} "
                  f"amt={','.join(amts[:2]) or '-':<22} cusip={cusip or '-'}")

        # Above-5% holders over time, from the filings themselves.
        latest = {}
        for filed, form, holder, pcts, _a, _c in events:
            if not holder:
                continue
            try:
                pct = max(float(p) for p in pcts) if pcts else None
            except ValueError:
                pct = None
            latest[holder] = (filed, pct, form)
        print(f"    distinct reporting persons: {len(latest)}")
        for holder, (filed, pct, form) in sorted(latest.items(),
                                                 key=lambda kv: kv[1][0]):
            print(f"      {holder[:46]:<46} last {filed} "
                  f"{('%.2f%%' % pct) if pct is not None else '   -  '} {form}")
    print(f"\n  documents fetched: {fetched}")


NUMERIC = re.compile(r"^[\d,]+(?:\.\d+)?%?$")


def phase_census():
    """How much of the structured era is actually MACHINE-READABLE?

    The elements exist. Their CONTENTS do not always: a meaningful minority of
    filings put prose into percentOfClass and aggregateAmountOwned — "The
    information required by this item is set forth above on the cover page" is
    the common one, and some carry a whole explanatory paragraph. Structured is
    not the same as clean, and the difference decides whether a component reads
    these or parses them.
    """
    print("=" * 78)
    print("CENSUS — of the structured era, how much parses?")
    print("=" * 78)
    print(f"{'':6}{'xml':>5}{'read':>6}{'pct ok':>8}{'prose':>7}{'group':>7}"
          f"   {'holders':>8}  span")
    fetched = 0
    totals = Counter()
    for ticker, (cik, _n) in sorted(roster().items()):
        rows, _ = all_filings(cik)
        xmls = sorted((r for r in rows if is_13x(r["form"])
                       and r["doc"].endswith(".xml")), key=lambda r: r["filed"])
        if not xmls:
            print(f"{ticker:<6}{0:>5}   —      —      —      —          —")
            continue
        ok = prose = group = 0
        holders, read = set(), 0
        for r in xmls:
            if fetched >= MAX_DOCS:
                break
            url = ARCHIVE.format(cik=int(cik),
                                 nodash=r["accession"].replace("-", ""),
                                 doc=raw_xml_path(r["doc"]))
            try:
                root = ET.fromstring(fetch(url, as_json=False))
                fetched += 1
                read += 1
            except Exception:                                   # noqa: BLE001
                continue
            names = all_text(root, NAME_TAGS)
            holders.update(names)
            if len(names) > 1:
                group += 1
            pcts = all_text(root, PCT_TAGS)
            if pcts and all(NUMERIC.match(p) for p in pcts):
                ok += 1
            elif pcts:
                prose += 1
            time.sleep(GAP)
        totals["xml"] += len(xmls)
        totals["read"] += read
        totals["ok"] += ok
        totals["prose"] += prose
        totals["group"] += group
        totals["holders"] += len(holders)
        print(f"{ticker:<6}{len(xmls):>5}{read:>6}{ok:>8}{prose:>7}{group:>7}"
              f"   {len(holders):>8}  {xmls[0]['filed']}..{xmls[-1]['filed']}")
    print()
    r = totals["read"] or 1
    print(f"  {totals['xml']} structured filings, {totals['read']} read")
    print(f"  percentOfClass fully numeric in {totals['ok']} "
          f"({totals['ok'] / r * 100:.0f}%), prose in {totals['prose']} "
          f"({totals['prose'] / r * 100:.0f}%)")
    print(f"  group filings (more than one reporting person): "
          f"{totals['group']} ({totals['group'] / r * 100:.0f}%)")
    print(f"  distinct reporting persons summed across companies: "
          f"{totals['holders']}")
    if fetched >= MAX_DOCS:
        print(f"  HIT THE {MAX_DOCS}-DOCUMENT CEILING — counts are truncated")


# --------------------------------------------------------------- QUESTIONS --

# THE SCHEMA, READ OFF THE TREE DUMP RATHER THAN GUESSED. Two parallel
# structures carry the same facts, and the census only read one of them:
#
#   /formData/reportingPersons/reportingPersonInfo/     repeats, one per person
#       reportingPersonName, reportingPersonCIK, percentOfClass,
#       aggregateAmountOwned, sole/shared voting/dispositive power
#
#   /formData/coverPageHeaderReportingPersonDetails/    repeats, one per person
#       reportingPersonName, classPercent,
#       reportingPersonBeneficiallyOwnedAggregateNumberOfShares
#
# The second IS the cover page. That matters for question 1: when
# percentOfClass carries prose, classPercent may still be numeric, and the
# fallback is then reading the right element rather than regexing the wrong
# one.
# THE TWO STRUCTURES ARE NOT ALTERNATIVES WITHIN A FILING — THEY ARE ONE PER
# FORM FAMILY, and reading only the first is the tag-list mistake a third time.
# Measured 2026-08-07 over 233 structured filings: every one carries blocks of
# exactly one kind and none of the other.
#
#   SCHEDULE 13D, 13D/A   ->  reportingPersons/reportingPersonInfo
#   SCHEDULE 13G, 13G/A   ->  coverPageHeaderReportingPersonDetails
#
# A pass reading only reportingPersonInfo found zero blocks in 156 of 233
# filings and duly reported "no prose percentOfClass anywhere" — an answer
# about two-thirds of nothing. The block-count histogram is printed for that
# reason: `0x156` is what exposed it, and a census that does not show its own
# denominator cannot.
RP_BLOCK = "reportingPersonInfo"
CP_BLOCK = "coverPageHeaderReportingPersonDetails"
# (name, percent, amount) field names, per variant.
VARIANTS = {
    RP_BLOCK: ("reportingPersonName", "percentOfClass", "aggregateAmountOwned"),
    CP_BLOCK: ("reportingPersonName", "classPercent",
               "reportingPersonBeneficiallyOwnedAggregateNumberOfShares"),
}


def person_blocks(root):
    """[(name, percent_raw, amount_raw, variant)] across both schemas."""
    out = []
    for block_name, (n_tag, p_tag, a_tag) in VARIANTS.items():
        for b in blocks(root, block_name):
            out.append((field(b, n_tag), field(b, p_tag), field(b, a_tag),
                        block_name))
    return out

NUMERIC = re.compile(r"^\s*-?[\d,]*\.?\d+\s*%?\s*$")
# Last resort only, and measured against the cover page rather than trusted.
PROSE_PCT = re.compile(r"([\d]{1,3}(?:\.\d+)?)\s*%")


def tag_of(el):
    return el.tag.split("}")[-1]


def blocks(root, name):
    return [el for el in root.iter() if tag_of(el) == name]


def field(block, *names):
    for el in block.iter():
        if tag_of(el) in names and (el.text or "").strip():
            return el.text.strip()
    return None


def as_number(text):
    if text is None:
        return None
    t = text.strip().rstrip("%").replace(",", "")
    try:
        return float(t)
    except ValueError:
        return None


def phase_questions():
    """Settle the three open questions, each measured rather than assumed."""
    print("=" * 78)
    print("THE THREE OPEN QUESTIONS")
    print("=" * 78)

    # (company, holder) -> [(filed, pct, form)]
    history = defaultdict(list)
    prose_cases = []
    missing = []
    per_filing = []
    fetched = 0

    for ticker, (cik, _name) in sorted(roster().items()):
        rows, _ = all_filings(cik)
        xmls = sorted((r for r in rows if is_13x(r["form"]) and r["doc"]),
                      key=lambda r: r["filed"])
        xmls = [r for r in xmls if r["doc"].endswith(".xml")]
        for r in xmls:
            if fetched >= MAX_DOCS:
                print(f"  HIT THE {MAX_DOCS}-DOCUMENT CEILING at {ticker}")
                break
            url = ARCHIVE.format(cik=int(cik),
                                 nodash=r["accession"].replace("-", ""),
                                 doc=raw_xml_path(r["doc"]))
            try:
                root = ET.fromstring(fetch(url, as_json=False))
                fetched += 1
            except Exception:                               # noqa: BLE001
                continue
            time.sleep(GAP)

            people = person_blocks(root)
            kinds = Counter(v for _n, _p, _a, v in people)
            per_filing.append((ticker, r["filed"], r["form"], len(people),
                               dict(kinds)))

            for name, pct_raw, _amt, variant in people:
                num = as_number(pct_raw) if pct_raw and NUMERIC.match(pct_raw)                     else None
                if name:
                    history[(ticker, name)].append((r["filed"], num, r["form"]))
                if pct_raw is not None and num is None:
                    m = PROSE_PCT.search(pct_raw)
                    prose_cases.append({
                        "ticker": ticker, "filed": r["filed"], "name": name,
                        "form": r["form"], "variant": variant,
                        "prose": " ".join(pct_raw.split())[:70],
                        "regex": float(m.group(1)) if m else None,
                    })
                if pct_raw is None and name:
                    missing.append((ticker, r["filed"], r["form"], variant))

    # ------------------------------------------------------------ Q1 -------
    print(chr(10) + "-" * 78)
    print("Q1  the prose rate — measured over BOTH schema variants")
    print("-" * 78)
    total_blocks = sum(p[3] for p in per_filing)
    print(f"  {total_blocks} reporting-person blocks across "
          f"{len(per_filing)} filings")
    print(f"  percent field absent entirely: {len(missing)}")
    print(f"  percent field non-numeric (prose): {len(prose_cases)} "
          f"({len(prose_cases) / total_blocks * 100:.1f}%)"
          if total_blocks else "")
    byvariant = Counter(c["variant"] for c in prose_cases)
    print(f"  by variant: {dict(byvariant) or 'none'}")
    got = [c for c in prose_cases if c["regex"] is not None]
    print(f"  a percentage recoverable from the prose by regex: {len(got)} "
          f"of {len(prose_cases)}")
    for c in prose_cases[:20]:
        print(f"    {c['ticker']:<6}{c['filed']}  {c['form']:<15}"
              f"regex={str(c['regex']):>6}  {str(c['name'])[:22]:<22} "
              f"{c['prose'][:40]}")
    if len(prose_cases) > 20:
        print(f"    ... and {len(prose_cases) - 20} more")

    # ------------------------------------------------------------ Q2 -------
    print("\n" + "-" * 78)
    print("Q2  group filings — the real rate, from the repeating block")
    print("-" * 78)
    multi = [p for p in per_filing if p[3] > 1]
    print(f"  {len(per_filing)} filings read")
    print(f"  more than one reportingPersonInfo block: {len(multi)} "
          f"({len(multi) / len(per_filing) * 100:.0f}%)"
          if per_filing else "")
    sizes = Counter(p[3] for p in per_filing)
    print(f"  blocks per filing: "
          + ", ".join(f"{n}x{c}" for n, c in sorted(sizes.items())))
    variants = Counter()
    for p in per_filing:
        for k, n in p[4].items():
            variants[k] += n
    print(f"  blocks by schema variant: {dict(variants)}")
    empty = [p for p in per_filing if p[3] == 0]
    print(f"  filings yielding NO person block under either schema: "
          f"{len(empty)}" + (f"  {[(e[0], e[1], e[2]) for e in empty[:4]]}"
                             if empty else ""))
    people = {k[1] for k in history}
    print(f"  distinct reporting persons, deduplicated by name: {len(people)}")
    print(f"  distinct (company, holder) pairs: {len(history)}")
    for probe in ("Citadel", "Susquehanna", "Vanguard", "FMR", "Endeavor",
                  "Armistice", "BlackRock"):
        hits = sorted({n for n in people if probe.lower() in n.lower()})
        if hits:
            print(f"    {probe}: {len(hits)} entity name(s)")
            for h in hits:
                print(f"      {h}")

    # ------------------------------------------------------------ Q3 -------
    print("\n" + "-" * 78)
    print("Q3  ageing a holder out — is there a threshold at all?")
    print("-" * 78)
    gaps = []
    explicit_exit, still, lapsed = [], [], []
    newest = max((d for v in history.values() for d, _p, _f in v), default="")
    for (ticker, name), rec in history.items():
        rec.sort()
        for a, b in zip(rec, rec[1:]):
            d0 = date.fromisoformat(a[0])
            d1 = date.fromisoformat(b[0])
            gaps.append((d1 - d0).days)
        last_date, last_pct, _form = rec[-1]
        age = (date.fromisoformat(newest) - date.fromisoformat(last_date)).days
        if last_pct is not None and last_pct == 0:
            explicit_exit.append((ticker, name, last_date))
        elif age <= 200:
            still.append((ticker, name, age, len(rec)))
        else:
            lapsed.append((ticker, name, age, len(rec)))
    if gaps:
        gaps.sort()
        med = statistics.median(gaps)
        print(f"  {len(gaps)} consecutive-filing gaps across "
              f"{len(history)} (company, holder) pairs")
        print(f"  percentiles  p10 {gaps[len(gaps)//10]}d  p50 {med:.0f}d  "
              f"p90 {gaps[len(gaps)*9//10]}d  max {gaps[-1]}d")
        print(f"  calibrate_staleness formula, max(6 x median, 60): "
              f"{max(6 * med, 60):.0f} days")
    print(f"\n  EXPLICIT EXITS — a final filing reporting 0%: "
          f"{len(explicit_exit)}")
    for t, n, d in explicit_exit[:10]:
        print(f"    {t:<6} {d}  {n[:50]}")
    print(f"\n  holders whose last filing is <=200 days old: {len(still)}")
    print(f"  holders silent longer than that: {len(lapsed)}")
    print("\n  THE SEPARATION TEST — median own-gap of each group. If these")
    print("  overlap, no threshold distinguishes gone from quiet.")
    for label, group in (("still filing", still), ("silent", lapsed)):
        owngaps = []
        for t, n, _age, _cnt in group:
            rec = sorted(history[(t, n)])
            g = [(date.fromisoformat(b[0]) - date.fromisoformat(a[0])).days
                 for a, b in zip(rec, rec[1:])]
            if g:
                owngaps.append(statistics.median(g))
        if owngaps:
            owngaps.sort()
            print(f"    {label:<14} n={len(owngaps):<4} "
                  f"median own-gap p10 {owngaps[len(owngaps)//10]:.0f}d  "
                  f"p50 {statistics.median(owngaps):.0f}d  "
                  f"p90 {owngaps[len(owngaps)*9//10]:.0f}d")
        else:
            print(f"    {label:<14} no holder with two or more filings")
    singles = sum(1 for v in history.values() if len(v) == 1)
    print(f"\n  holders with a SINGLE filing and no gap to measure: "
          f"{singles} of {len(history)}")
    print(f"  documents fetched: {fetched}")


def main():
    print(f"phase: {PHASE}   roster: "
          f"{', '.join(sorted(roster())) if ONLY else 'all 19'}\n")
    {"inventory": phase_inventory,
     "structured": phase_structured,
     "legacy": phase_legacy,
     "timeline": phase_timeline,
     "census": phase_census,
     "questions": phase_questions}[PHASE]()
    return 0


if __name__ == "__main__":
    sys.exit(main())
