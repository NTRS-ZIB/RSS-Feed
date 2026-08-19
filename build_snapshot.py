#!/usr/bin/env python3
"""Write snapshot.json: a dated summary of each watched issuer's EDGAR filing index.

This is a courier, not a source. It says what the index holds and where to look; the
filing itself remains the authority. Consumers cite the accession number to the form,
having opened it.

Derives its roster from watchlist.py, the same source every other component reads.
Writes one file at the repo root.
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

# Derived from watchlist.py, never copied. A hardcoded duplicate drifts the moment
# a company is added or renamed, and it drifts SILENTLY: the script goes on
# producing a clean-looking snapshot of a stale roster, with no error and no gap in
# the output to notice. That is exactly what happened — WULF, HUT and CIFR were
# added to the roster and were missing from snapshot.json for a day, invisible to
# the consuming project, and CIFR would have carried its pre-rename name.
import watchlist

CIKS = {ticker: cik for ticker, (cik, _name) in watchlist.ciks().items()}
for problem in watchlist.validate():
    print("WARNING: watchlist.py -", problem)

# Form families a sweep opens with. Prefix matched, so 8-K covers 8-K/A.
#
# EDGAR emits both 13D/G spellings, and they are different form types rather than
# variants of one. Filings from the changeover onward carry SCHEDULE 13D and
# SCHEDULE 13G; older ones carry SC 13D and SC 13G. "SCHEDULE 13D" does not start
# with "SC 13D" — the fourth character is H, not a space — so the legacy prefix
# alone silently misses every recent one. Keep both.
#
# THERE IS NO CHANGEOVER DATE. This comment used to give one — 2024-12-16, "the
# oldest filing observed under the new spelling", offered as the date the
# spelling changed. A full-history sweep of 13D/G across all nineteen companies
# on 2026-08-06 measured 707 filings and found the two spellings INTERLEAVED
# for ten months:
#
#   oldest SCHEDULE spelling anywhere   2024-01-26   IREN
#   newest SC spelling anywhere         2024-11-29   APLD
#
# and the transition is per-filer, not per-calendar:
#
#   IREN   last SC 2024-02-14, first SCHEDULE 2024-01-26   <- overlaps itself
#   VIP    last SC 2023-02-09, first SCHEDULE 2025-01-28
#   ANY    last SC 2024-02-13, first SCHEDULE 2025-02-14
#   HUT    last SC 2024-11-12, first SCHEDULE 2025-09-10
#
# 2024-12-16 was NUAI's first filing of any kind, and NUAI files structured
# only. The old number was the oldest structured filing inside a window that
# never reached IREN's January 2024 — the CUSIP-sweep lesson a third time: a
# window that found nothing had not been swept far enough, and the figure sat
# in a comment as a fact.
#
# CORRECTING THE DATE IS THE SMALLER HALF. Recording a single date at all is the
# error, because a reader who takes 2024-01-26 as a boundary makes the same
# mistake one step later. It is a range, and within the range it is per-filer.
#
# None of this changes behaviour, and that is the point: FORMS carries both
# spellings, so an interleaved transition is handled by construction. Matching
# both was right for a reason better than the one originally given — not
# "filings before the changeover use the old spelling" but "there was no
# changeover to be before".
#
# Adding the prefix recovered 117 filings across eleven issuers. That count came
# from a measurement taken at the time and is recorded nowhere else in this
# repo, so it cannot be re-derived from anything here.
#
# NT is MATCHED as a family prefix but EMITTED per form. press_monitor.py moved
# to "NT " after hand-enumeration left NT 20-F missing for months — precisely the
# form IREN or DGXX would file — so matching the family is right here too.
#
# The output keys are a different question, and the two files have different
# obligations: press_monitor decides what to post, this one is a wire format
# another project reads. Collapsing the four into a single "NT " key would break
# a downstream index silently, which is the failure this file exists to avoid.
# So the family is matched, and each member is emitted under its own key with its
# own count, exactly as before.
FORMS = ["8-K", "6-K", "10-Q", "10-K", "20-F", "40-F", "S-1", "S-3", "424",
         "SC 13D", "SCHEDULE 13D", "SC 13G", "SCHEDULE 13G",
         "NT ",
         "3", "4", "DEF 14A"]

# Always emitted, null when the issuer has none, so the shape does not change
# run to run. A sibling outside this list is emitted under its own key rather
# than dropped — surfacing a form nobody enumerated is the point of matching the
# family, and silently discarding it would reopen the hole one level down.
NT_FAMILY = "NT "
NT_KNOWN = ["NT 10-K", "NT 10-Q", "NT 20-F", "NT 40-F"]

ANNUAL = {"10-K", "20-F", "40-F"}
QUARTERLY = {"10-Q"}
LAG_SAMPLE = 8

# DERIVED FROM earnings_calendar, never restated. Both components project the
# next report for the same issuers off the same EDGAR index, and they gave
# DIFFERENT ANSWERS about two companies until 2026-08-19: this one rolled three
# months for an annual-only filer and invented a quarterly cadence from a single
# 10-Q. Importing the rule is what stops them drifting again — the same reason
# threshold_list derives its two roster maps rather than hand-maintaining them.
from earnings_calendar import MIN_QUARTERLY_FILINGS, next_annual_period_end


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


def entry(hits, cik):
    """Newest of a group of filings, plus how many there are."""
    hits.sort(key=lambda r: r[1], reverse=True)
    form, filed, period, acc, doc = hits[0]
    return {
        "form": form,
        "filed": filed,
        "period": period or None,
        "accession": acc,
        "url": ("https://www.sec.gov/Archives/edgar/data/%d/%s/%s"
                % (int(cik), acc.replace("-", ""), doc)) if doc else None,
        "count": len(hits),
    }


def latest_per_form(rows, cik):
    out = {}
    for family in FORMS:
        hits = [r for r in rows if matches(r[0], family)]

        if family == NT_FAMILY:
            # Matched as a family, emitted per form. Amendments fold into their
            # parent — "NT 10-K/A" counts under "NT 10-K" — which is what the
            # old per-form prefix match did, so the wire format is unchanged.
            groups = {}
            for r in hits:
                groups.setdefault(r[0].split("/")[0], []).append(r)
            for key in NT_KNOWN:
                g = groups.pop(key, None)
                out[key] = entry(g, cik) if g else None
            for key in sorted(groups):
                out[key] = entry(groups[key], cik)
            continue

        out[family] = entry(hits, cik) if hits else None
    return out


def _projection(nxt, expected, kind, median, spread, sample, fy_month):
    """The published shape, built in one place.

    Both the annual-only path and the quarterly one return through here, so a
    field added to one cannot be missing from the other. `snapshot.json` is a
    wire format another project reads; a projection whose keys depend on which
    branch produced it is the kind of difference a consumer discovers in
    production.
    """
    return {
        "period_end": nxt.isoformat(),
        "expected": expected.isoformat(),
        "kind": kind,
        "median_lag_days": median,
        "spread_days": spread,
        "sample": sample,
        "fiscal_year_end_month": fy_month,
        "confidence": "low" if (spread or 0) > 30 or sample < 2 else "normal",
    }


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

    # A SINGLE 10-Q IS NOT A QUARTERLY CADENCE. `qtr or ann` accepted one
    # filing as evidence of a cycle, and SPCX has exactly one: it was published
    # with kind "quarterly" and sample 1, a confident projection off a sample
    # nobody would accept anywhere else in this repo. `earnings_calendar`
    # refuses the same company against the same floor and reports `SPCX 1/2`,
    # so the two components asserted different things about it every day.
    annual_only = len(qtr) < MIN_QUARTERLY_FILINGS
    src = ann if annual_only else qtr
    if not src:
        return None
    kind = "annual" if annual_only else "quarterly"
    days = [d for d, _ in src]
    median = int(statistics.median(days))
    spread = (max(days) - min(days)) // 2 if len(days) > 1 else None
    last_period = src[0][1]

    # AN ANNUAL FILER'S NEXT PERIOD IS TWELVE MONTHS ON, NOT THREE. Rolling a
    # quarter for a company that files only annually produces a period end it
    # never reports on: BTDR is a 20-F filer with a December year end and was
    # published against 31 March, with an `expected` date already a month in
    # the past. `earnings_calendar` fixed this and names BTDR in its own
    # docstring; the rule is imported from there so the two cannot disagree
    # about it again.
    if annual_only:
        nxt = next_annual_period_end(last_period)
        expected = nxt + datetime.timedelta(days=median)
        while expected.weekday() >= 5:
            expected += datetime.timedelta(days=1)
        return _projection(nxt, expected, kind, median, spread, len(src),
                           fy_month)

    # Next period end: three months on, rolled to month end.
    m = last_period.month + 3
    y = last_period.year + (m - 1) // 12
    m = (m - 1) % 12 + 1
    # The roll is "first of the FOLLOWING month, minus a day", so December has
    # to cross the year: January of y+1, not January of y. Getting this wrong
    # returned 30 November for every December period end, and December is the
    # case that matters most — most of this roster has a December year end, and
    # it is the annual report that carries the projection.
    nxt = (datetime.date(y + 1, 1, 1) if m == 12
           else datetime.date(y, m + 1, 1)) - datetime.timedelta(days=1)

    if fy_month and nxt.month == fy_month and ann:
        adays = [d for d, _ in ann]
        median = int(statistics.median(adays))
        spread = (max(adays) - min(adays)) // 2 if len(adays) > 1 else None
        kind = "annual"

    expected = nxt + datetime.timedelta(days=median)
    while expected.weekday() >= 5:
        expected += datetime.timedelta(days=1)

    return _projection(nxt, expected, kind, median, spread, len(src), fy_month)


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
