#!/usr/bin/env python3
"""Write snapshot.json: a dated summary of each watched issuer's EDGAR filing index.

This is a courier, not a source. It says what the index holds and where to look; the
filing itself remains the authority. Consumers cite the accession number to the form,
having opened it.

Reads the same CIK list the monitor uses. Writes one file at the repo root.
"""

import json
import time
import datetime
import pathlib
import statistics
import urllib.request
import urllib.error

ROOT = pathlib.Path(__file__).resolve().parent
OUT = ROOT / "snapshot.json"

# Contact string SEC asks for. Reuses the monitor's secret.
import os
UA = os.environ.get("SEC_USER_AGENT", "").strip()
if not UA:
    raise SystemExit("SEC_USER_AGENT is not set. SEC throttles anonymous traffic.")

CIKS = {
    "MARA": "0001507605", "CLSK": "0000827876", "BKKT": "0001820302",
    "NUAI": "0002028336", "IREN": "0001878848", "VIP":  "0001844971",
    "ANY":  "0001591956", "SLNH": "0000064463", "BGDE": "0001218683",
    "WYFI": "0002042022", "DGXX": "0001854368",
}

# Form families a sweep opens with. Prefix matched, so 8-K covers 8-K/A.
FORMS = ["8-K", "6-K", "10-Q", "10-K", "20-F", "40-F", "S-1", "S-3", "424",
         "SC 13D", "SC 13G", "NT 10-K", "NT 10-Q", "NT 20-F", "NT 40-F",
         "3", "4", "DEF 14A"]

ANNUAL = {"10-K", "20-F", "40-F"}
QUARTERLY = {"10-Q"}
LAG_SAMPLE = 8


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Accept-Encoding": "gzip, deflate"})
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read()
    if r.headers.get("Content-Encoding") == "gzip":
        import gzip
        raw = gzip.decompress(raw)
    return json.loads(raw)


def all_filings(cik):
    """Every filing in the index, recent page plus any older files it references."""
    data = fetch("https://data.sec.gov/submissions/CIK%s.json" % cik)
    recent = data.get("filings", {}).get("recent", {})
    rows = list(zip(recent.get("form", []), recent.get("filingDate", []),
                    recent.get("reportDate", []), recent.get("accessionNumber", []),
                    recent.get("primaryDocument", [])))
    for extra in data.get("filings", {}).get("files", []):
        time.sleep(0.15)
        older = fetch("https://data.sec.gov/submissions/" + extra["name"])
        rows += list(zip(older.get("form", []), older.get("filingDate", []),
                         older.get("reportDate", []), older.get("accessionNumber", []),
                         older.get("primaryDocument", [])))
    return data, rows


def matches(form, family):
    """EDGAR prefix semantics, but 3 and 4 must not swallow 40-F or 424."""
    if family in ("3", "4"):
        return form == family or form == family + "/A"
    return form.startswith(family)


def latest_per_form(rows, cik):
    out = {}
    for family in FORMS:
        hits = [r for r in rows if matches(r[0], family)]
        if not hits:
            out[family] = None
            continue
        hits.sort(key=lambda r: r[1], reverse=True)
        form, filed, period, acc, doc = hits[0]
        out[family] = {
            "form": form,
            "filed": filed,
            "period": period or None,
            "accession": acc,
            "url": ("https://www.sec.gov/Archives/edgar/data/%d/%s/%s"
                    % (int(cik), acc.replace("-", ""), doc)) if doc else None,
            "count": len(hits),
        }
    return out


def projection(rows):
    """Expected next report, from this issuer's own filing lags.

    Annual and quarterly lags are never pooled: annual reports are filed 60 to 90
    days after year end, quarterlies around 40, and a pooled median fits neither.
    """
    def lags(families):
        out = []
        for form, filed, period, _, _ in rows:
            if form in families and period and filed:
                try:
                    f = datetime.date.fromisoformat(filed)
                    p = datetime.date.fromisoformat(period)
                except ValueError:
                    continue
                out.append(((f - p).days, p))
        out.sort(key=lambda x: x[1], reverse=True)
        return out[:LAG_SAMPLE]

    ann, qtr = lags(ANNUAL), lags(QUARTERLY)
    if not ann and not qtr:
        return None

    # Fiscal year end: the most common period month among annual reports.
    fy_month = None
    if ann:
        months = [p.month for _, p in ann]
        fy_month = max(set(months), key=months.count)

    src = qtr or ann
    kind = "quarterly" if qtr else "annual"
    days = [d for d, _ in src]
    median = int(statistics.median(days))
    spread = (max(days) - min(days)) // 2 if len(days) > 1 else None
    last_period = src[0][1]

    # Next period end: three months on, rolled to month end.
    m = last_period.month + 3
    y = last_period.year + (m - 1) // 12
    m = (m - 1) % 12 + 1
    nxt = datetime.date(y, m, 1) - datetime.timedelta(days=1) \
        if m == 12 else datetime.date(y, m + 1, 1) - datetime.timedelta(days=1)

    if fy_month and nxt.month == fy_month and ann:
        adays = [d for d, _ in ann]
        median = int(statistics.median(adays))
        spread = (max(adays) - min(adays)) // 2 if len(adays) > 1 else None
        kind = "annual"

    expected = nxt + datetime.timedelta(days=median)
    while expected.weekday() >= 5:
        expected += datetime.timedelta(days=1)

    return {
        "period_end": nxt.isoformat(),
        "expected": expected.isoformat(),
        "kind": kind,
        "median_lag_days": median,
        "spread_days": spread,
        "sample": len(src),
        "fiscal_year_end_month": fy_month,
        "confidence": "low" if (spread or 0) > 30 or len(src) < 2 else "normal",
    }


def main():
    out = {
        "generated": datetime.datetime.now(datetime.timezone.utc)
                      .replace(microsecond=0).isoformat(),
        "note": ("Restatement of what the EDGAR submissions index holds. The filing is "
                 "the source; this is an index to it. Fields under 'filings' are FILED "
                 "and cite an accession number that must be opened before use. Fields "
                 "under 'projection' are ESTIMATE, derived from this issuer's own "
                 "filing lags, and carry their sample and spread."),
        "issuers": {},
    }
    problems = []

    for ticker, cik in sorted(CIKS.items()):
        try:
            data, rows = all_filings(cik)
        except Exception as e:
            problems.append("%s: %s" % (ticker, e))
            out["issuers"][ticker] = {"cik": cik, "error": str(e)}
            continue

        latest = max((r[1] for r in rows if r[1]), default=None)
        out["issuers"][ticker] = {
            "cik": cik,
            "name": data.get("name"),
            "former_names": [n.get("name") for n in data.get("formerNames", [])],
            "filing_count": len(rows),
            "latest_filing_date": latest,
            "filings": latest_per_form(rows, cik),
            "projection": projection(rows),
        }
        print("  %-5s %-42s %5d filings, latest %s"
              % (ticker, (data.get("name") or "")[:42], len(rows), latest))
        time.sleep(0.2)

    OUT.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n")
    print("\nWrote %s: %d issuers, %d problem(s)"
          % (OUT.name, len(out["issuers"]), len(problems)))
    for p in problems:
        print("  PROBLEM", p)
    if len(problems) == len(CIKS):
        raise SystemExit("Every issuer failed. Not committing a snapshot of nothing.")


if __name__ == "__main__":
    main()
