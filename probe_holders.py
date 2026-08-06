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
import re
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict

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
                             doc=sample["doc"])
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
CUSIP_TAGS = ["issuerCUSIP", "cusip", "cusipNumber"]


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
                                 doc=r["doc"])
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


def main():
    print(f"phase: {PHASE}   roster: "
          f"{', '.join(sorted(roster())) if ONLY else 'all 19'}\n")
    {"inventory": phase_inventory,
     "structured": phase_structured,
     "legacy": phase_legacy,
     "timeline": phase_timeline}[PHASE]()
    return 0


if __name__ == "__main__":
    sys.exit(main())
