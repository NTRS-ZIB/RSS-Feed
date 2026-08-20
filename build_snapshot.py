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

# EVERY OTHER COMPONENT TAKES THIS and this one did not, which is exactly why
# a change to the published projection could not be seen before it shipped. A
# dry run fetches normally, reports what would change, and writes nothing.
DRY_RUN = os.environ.get("DRY_RUN", "").strip().lower() in ("1", "true", "yes")

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
# obligations: press_monitor decides what to post, this one is a published wire
# format. Collapsing the four into a single "NT " key would break a downstream
# index silently, which is the failure this file exists to avoid.
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

# DERIVED FROM filing_cadence, never restated. ANNUAL, QUARTERLY and
# LAG_SAMPLE were hand-maintained duplicates two lines above this comment,
# which said "never restated" while three of the four cadence facts were.
# docs/earnings.md tells a maintainer to reduce LAG_SAMPLE to 4 if
# projections run late: under the duplicates that moved the Discord post and
# left the wire format on 8, silently. Both components project the
# next report for the same issuers off the same EDGAR index, and they gave
# DIFFERENT ANSWERS about three companies until 2026-08-19.
#
# IMPORTED FROM filing_cadence AND NOT FROM earnings_calendar, which is not a
# style preference. That module imports `requests` at module scope, this one
# is deliberately stdlib-only, and .github/workflows/snapshot.yml has NO pip
# install step — so importing it there killed the 11:00 UTC run with
# ModuleNotFoundError before it read a filing, freezing snapshot.json on the
# very values the change was making correct. The absent pip step is the only
# thing that catches this: tests.yml installs requests and cannot see it.
from filing_cadence import (ANNUAL_FORMS as ANNUAL, LAG_SAMPLE,
                            LOW_CONFIDENCE_SPREAD, MIN_ANNUAL_FILINGS,
                            MIN_QUARTERLY_FILINGS, PERIODIC_FORMS,
                            QUARTERLY_FORMS as QUARTERLY, cadence,
                            covers_a_period, fiscal_year_end_month,
                            next_annual_period_end)


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


def projection(rows):
    """Expected next report, from `filing_cadence`. The DECISION is not here.

    This was a second implementation of that rule and disagreed with
    `earnings_calendar` about three companies: it rolled three months for an
    annual-only filer, accepted a single 10-Q as a cadence, and took its roll
    base from the newest QUARTERLY period rather than the newest periodic
    filing — so it named as `next` a 10-K it had already recorded as filed.

    What stays here is the published SHAPE: this file's field names, and the
    halving of the range into `spread_days`. The Discord post now halves it
    too, at its own boundary, so the two publish the same quantity.

    `confidence` CHANGED ON 2026-08-19 and this is the one consumer-visible
    move. It gates on the RANGE against LOW_CONFIDENCE_SPREAD, where it used
    to gate on the halved figure against the same number: an effective
    threshold of 60 days where the Discord post used 30.

    MEASURED BY DRY RUN AGAINST LIVE SEC DATA, it moves exactly two issuers,
    CLSK and WYFI, `normal` to `low` with every other field of their block
    identical. BTDR was already `low`. APLD sat in the gap in the committed
    file at a range of 32 and does NOT move: the shared-rule merge earlier the
    same day switched it from an annual projection to a quarterly one, and its
    range on that pool is 8. That is worth knowing rather than tidying away -
    a company leaves this band because its own history changed, not only
    because a threshold did, so the set is not stable and reasoning from a
    stale copy of the file gets it wrong.
    """
    filings = []
    for form, filed, period, *_ in rows:
        if form not in PERIODIC_FORMS or not period or not filed:
            continue
        try:
            p = datetime.date.fromisoformat(period)
            f = datetime.date.fromisoformat(filed)
        except (TypeError, ValueError):
            continue
        # THE SAME GUARD `cadence` APPLIES, so the counts this file publishes
        # in `reason` describe the filings the decision actually used. Without
        # it an issuer refused for want of periods could report a count that
        # clears the floor it was refused against.
        if f >= p and covers_a_period(p):
            filings.append((p, f, form))
    # Newest period first: LAG_SAMPLE truncates positionally and this file has
    # always meant "most recent history". `cadence` deliberately does not sort,
    # because the other caller orders by FILED date instead.
    filings.sort(key=lambda t: t[0], reverse=True)

    annual = [f for f in filings if f[2] in ANNUAL]
    quarterly = [f for f in filings if f[2] in QUARTERLY]

    c = cadence(filings)
    if c is None:
        # NOT null. An absent projection is a MEASUREMENT — this issuer has
        # not filed enough to project from — and CLAUDE.md is explicit that
        # absence is reported with a COUNT AGAINST THE FLOOR rather than a
        # bare gap: "a name in a list is an excuse; a count is a measurement".
        #
        # It also keeps every key present, so a consumer reading
        # projection["expected"] gets None instead of raising on a null
        # object. The shape is a strict superset of the old one, which is why
        # this can ship without every reader being warned first.
        return {
            "available": False,
            "reason": ("%d/%d quarterly and %d/%d annual filings"
                       % (len(quarterly), MIN_QUARTERLY_FILINGS,
                          len(annual), MIN_ANNUAL_FILINGS)),
            "period_end": None, "expected": None, "kind": None,
            "median_lag_days": None, "spread_days": None,
            "sample": len(filings),
            "fiscal_year_end_month": fiscal_year_end_month(annual),
            "confidence": None,
        }
    # HALF THE RANGE, unchanged, and this file's published figure. What did
    # change is what `confidence` compares: it used to threshold this halved
    # number against 30, while the Discord post thresholded the RANGE against
    # the same 30, so one constant meant `range > 30` in one output and
    # `range > 60` in the other. APLD, WYFI and CLSK sat in that gap.
    spread = c["spread"] // 2
    return {
        "available": True,
        "reason": None,
        "period_end": c["period"].isoformat(),
        "expected": c["expected"].isoformat(),
        "kind": c["kind"],
        "median_lag_days": c["lag"],
        "spread_days": spread,
        "sample": c["sample"],
        "fiscal_year_end_month": c["fy_month"],
        # `degraded` joins the low-confidence condition rather than becoming a
        # field: it means the lag came from the other pool, which is exactly
        # what a consumer gating on confidence needs to know, and the file has
        # no way to say it otherwise.
        "confidence": ("low" if c["spread"] > LOW_CONFIDENCE_SPREAD
                       or c["sample"] < 2 or c["degraded"] else "normal"),
    }


def diff_projections(out):
    """Every projection this run would change, against the committed file.

    THE ONLY WAY TO SEE THIS CHANGE BEFORE IT SHIPS. The `projection` block is
    derived from the FULL filing history, which `latest_per_form()` does not
    keep — it holds one entry per family. So the published file cannot be
    replayed through `projection()` to predict a change: doing that hands
    every issuer a single quarterly filing and answers a question about a
    different population. That was tried on 2026-08-19 and reported all
    twenty-two issuers changing to values none of them would ever have had.
    """
    try:
        old = json.loads(OUT.read_text())["issuers"]
    except (OSError, ValueError, KeyError):
        return "\nNo committed snapshot.json to compare against."

    def fmt(p):
        if not p:
            return "absent"
        if p.get("available") is False:
            return "no estimate (%s)" % p.get("reason")
        return ("%s exp %s %s sample %s spread %s %s"
                % (p["period_end"], p["expected"], p["kind"], p["sample"],
                   p["spread_days"], p["confidence"]))

    # COMPARED ON THE SHARED KEYS ONLY. Adding a field makes every dict
    # unequal, so a plain == reported "22 of 22 would change" on a run where
    # twenty of them held identical values — which is the kind of report that
    # gets skimmed once and ignored after. New and dropped keys are named
    # separately, because a shape change is a different fact from a value one.
    added, dropped = set(), set()
    lines, changed = [], 0
    for t in sorted(out["issuers"]):
        a = (old.get(t) or {}).get("projection") or {}
        b = (out["issuers"][t] or {}).get("projection") or {}
        added |= set(b) - set(a)
        dropped |= set(a) - set(b)
        shared = set(a) & set(b)
        if bool(a) == bool(b) and all(a[k] == b[k] for k in shared):
            continue
        changed += 1
        lines.append("  %-6s was  %s" % (t, fmt(a or None)))
        lines.append("  %-6s now  %s" % ("", fmt(b or None)))
    head = "\n%d of %d projection(s) change VALUE:" % (changed, len(out["issuers"]))
    shape = ""
    if added or dropped:
        shape = ("\nshape: %d field(s) added %s, %d dropped %s"
                 % (len(added), sorted(added), len(dropped), sorted(dropped)))
    return head + ("\n" + "\n".join(lines) if lines else " none") + shape


def main():
    out = {
        "generated": datetime.datetime.now(datetime.timezone.utc)
                      .replace(microsecond=0).isoformat(),
        # A VERSION, because this file is published for another project and
        # had no way to say its shape had changed. Raise it when a consumer
        # would have to alter code, not when a value moves.
        #
        # No consumer reads it yet: equity-research's `Get-Snapshot` is written
        # and tested and has never been given a file. The version is still
        # worth carrying, because the point of it is to be there BEFORE the
        # first consumer rather than after.
        "schema": 1,
        "note": ("Restatement of what the EDGAR submissions index holds. The filing is "
                 "the source; this is an index to it. Fields under 'filings' are FILED "
                 "and cite an accession number that must be opened before use. Fields "
                 "under 'projection' are ESTIMATE, derived from this issuer's own "
                 "filing lags, over the sample stated in that block. "
                 "'projection' ALWAYS carries the same keys. When the filing "
                 "history is too thin to project from, 'available' is false, every "
                 "estimate field is null, and 'reason' states the counts against the "
                 "floors, e.g. '1/2 quarterly and 0/2 annual filings' - an absence "
                 "reported as a measurement rather than a gap. An issuer whose fetch "
                 "failed is different again: it carries 'error' and no 'projection' "
                 "key. Neither means zero. "
                 "'spread_days' is HALF the observed range of filing lags. "
                 "'confidence' is 'low' when that RANGE exceeds 30 days, when "
                 "the sample is under 2, or when the lag had to be taken from "
                 "the other filing family for want of observations in this "
                 "one. Before 2026-08-19 the range test compared 30 against "
                 "the halved figure instead, an effective threshold of 60 "
                 "days, so some issuers previously published 'normal' now "
                 "read 'low' on unchanged filing history."),
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

    if DRY_RUN:
        print(diff_projections(out))
        print("\nDRY RUN — %s not written. %d issuer(s), %d problem(s)."
              % (OUT.name, len(out["issuers"]), len(problems)))
        for p in problems:
            print("  PROBLEM", p)
        return

    OUT.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n")
    print("\nWrote %s: %d issuers, %d problem(s)"
          % (OUT.name, len(out["issuers"]), len(problems)))
    for p in problems:
        print("  PROBLEM", p)
    if len(problems) == len(CIKS):
        raise SystemExit("Every issuer failed. Not committing a snapshot of nothing.")


if __name__ == "__main__":
    main()
