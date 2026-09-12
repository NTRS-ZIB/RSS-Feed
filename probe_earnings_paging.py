#!/usr/bin/env python3
"""What paging `filings.recent` would change in the earnings calendar.

`earnings_calendar.periodic_filings` reads `filings.recent` and stops. That
page is a ROLLING WINDOW of roughly the newest thousand filings, not the index,
and this repo has already fixed the same defect twice: `holder_events` in
c23a6eb, and `build_snapshot` which pages already.

WHY THIS NEEDS MEASURING RATHER THAN JUST FIXING. `holder_events`' paging was
safe because it provably added NOTHING to post: every newly visible filing was
already in `seen`. Nothing like that holds here. `filing_cadence.cadence`
truncates its lag pool POSITIONALLY -- `pool[:LAG_SAMPLE]` -- and its docstring
says the caller owns the order, so more filings can move the published median
lag, the +/- column, the expected date and the sample count. A company now too
thin to project could START projecting, which puts a new row in a live post.

So this prints the CURRENT published row and the PAGED one side by side for
every roster company, and diffs them field by field.

IT REFUSES TO SUMMARISE OVER AN EMPTY SET. The first run of `probe_holders`
printed "0 filings are about another company" over 22 failed reads, which reads
as good news. Every total here is printed beside the number of companies that
actually answered, and a phase with no successful reads says so instead of
reporting zeros.

Needs SEC_USER_AGENT. Responses are cached under the path in CACHE so a re-run
costs no requests; delete it to re-measure.
"""

import gzip
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

import watchlist
from filing_cadence import MIN_PERIODIC_FILINGS, PERIODIC_FORMS, cadence, covers_a_period

UA = os.environ.get("SEC_USER_AGENT", "").strip()
if not UA:
    raise SystemExit("SEC_USER_AGENT is not set. Use: 'Your Name your@email.com'")

CACHE = Path(os.environ.get("PROBE_CACHE", "probe_cache_earnings"))
GAP = 0.15
SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik}.json"
OLDER = "https://data.sec.gov/submissions/{name}"


def get(url, key):
    """Fetch with an on-disk cache. Returns None on any failure, like sec_get."""
    CACHE.mkdir(exist_ok=True)
    hit = CACHE / (key + ".json")
    if hit.exists():
        return json.loads(hit.read_text(encoding="utf-8"))
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept-Encoding": "gzip, deflate"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read()
            enc = r.headers.get("Content-Encoding")
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
        print(f"    FETCH FAILED {key}: {type(e).__name__} {e}")
        return None
    if enc == "gzip":
        raw = gzip.decompress(raw)
    time.sleep(GAP)
    try:
        data = json.loads(raw)
    except ValueError:
        print(f"    UNPARSEABLE {key}")
        return None
    hit.write_text(json.dumps(data), encoding="utf-8")
    return data


def rows_of(block):
    """(reportDate, filingDate, form) for periodic filings, in index order.

    The SAME filter earnings_calendar.periodic_filings applies, so the two
    sides of this comparison differ only in which pages were read.
    """
    forms = block.get("form") or []
    filed = block.get("filingDate") or []
    period = block.get("reportDate") or []
    out = []
    for i, form in enumerate(forms):
        if form not in PERIODIC_FORMS:
            continue
        try:
            rd = date.fromisoformat(period[i])
            fd = date.fromisoformat(filed[i])
        except (ValueError, IndexError, TypeError):
            continue
        if rd and fd and fd >= rd and covers_a_period(rd):
            out.append((rd, fd, form))
    return out


def all_dates(block):
    """Every filingDate on a page, for the window-span measurement."""
    return [d for d in (block.get("filingDate") or []) if d]


def published(filings):
    """The fields earnings_calendar actually prints, or None."""
    c = cadence(filings)
    if c is None:
        return None
    return {
        "expected": c["expected"].isoformat(),
        "period": c["period"].isoformat(),
        "lag": c["lag"],
        "spread": c["spread"],
        "plusminus": c["spread"] // 2,
        "samples": c["sample"],
        "kind": c["kind"],
        "degraded": c["degraded"],
        "annual_only": c["annual_only"],
        "fy_month": c["fy_month"],
    }


def main():
    companies = watchlist.ciks()
    print(f"{len(companies)} companies on the roster.\n")

    read_ok, changed, newly_projecting, lost = 0, [], [], []
    ordering_breaks, page_stats = [], []

    for label, (cik, name) in sorted(companies.items()):
        print(f"{label} ({name})")
        data = get(SUBMISSIONS.format(cik=cik), f"CIK{cik}")
        if not data:
            print("    index unreadable, SKIPPED (not counted as anything)\n")
            continue

        recent = (data.get("filings") or {}).get("recent") or {}
        files = (data.get("filings") or {}).get("files") or []

        # --- the window span, which is what makes eviction possible at all ---
        rd_dates = sorted(all_dates(recent))
        span = f"{rd_dates[0]} -> {rd_dates[-1]}" if rd_dates else "EMPTY"

        now_rows = rows_of(recent)
        paged_rows = list(now_rows)
        older_ok, older_failed = 0, 0
        for extra in files:
            page = get(OLDER.format(name=extra["name"]), extra["name"])
            if page is None:
                older_failed += 1
                continue
            older_ok += 1
            paged_rows += rows_of(page)

        read_ok += 1
        page_stats.append({
            "label": label, "recent_rows": len(recent.get("form") or []),
            "span": span, "older_pages": len(files), "older_ok": older_ok,
            "older_failed": older_failed,
            "periodic_now": len(now_rows), "periodic_paged": len(paged_rows),
        })
        print(f"    recent page {len(recent.get('form') or [])} filings, {span}")
        print(f"    older pages: {len(files)} listed, {older_ok} read, "
              f"{older_failed} failed")
        print(f"    periodic filings: {len(now_rows)} now -> {len(paged_rows)} paged")

        # --- THE ORDERING INVARIANT ---
        # cadence() truncates pool[:LAG_SAMPLE] positionally and documents that
        # earnings_calendar passes rows newest-first by FILED date. If
        # concatenating older pages breaks that, the median moves for reasons
        # nobody intended.
        fds = [fd for _, fd, _ in paged_rows]
        if fds != sorted(fds, reverse=True):
            first_bad = next(i for i in range(1, len(fds)) if fds[i] > fds[i - 1])
            ordering_breaks.append({
                "label": label, "at": first_bad,
                "prev": fds[first_bad - 1].isoformat(),
                "next": fds[first_bad].isoformat(),
                "in_recent": first_bad < len(now_rows),
            })
            print(f"    ORDERING BREAKS at index {first_bad}: "
                  f"{fds[first_bad - 1]} then {fds[first_bad]} "
                  f"({'inside recent' if first_bad < len(now_rows) else 'at a page seam'})")

        now_pub = published(now_rows)
        paged_pub = published(paged_rows)

        if now_pub is None and paged_pub is None:
            print(f"    no projection either way "
                  f"({len(now_rows)}/{MIN_PERIODIC_FILINGS} -> "
                  f"{len(paged_rows)}/{MIN_PERIODIC_FILINGS})\n")
            continue
        if now_pub is None and paged_pub is not None:
            newly_projecting.append((label, paged_pub))
            print(f"    NEW ROW: does not project today, WOULD project paged: "
                  f"{paged_pub}\n")
            continue
        if now_pub is not None and paged_pub is None:
            lost.append((label, now_pub))
            print(f"    LOST ROW: projects today, would NOT project paged\n")
            continue

        diff = {k: (now_pub[k], paged_pub[k])
                for k in now_pub if now_pub[k] != paged_pub[k]}
        if diff:
            changed.append((label, diff))
            for k, (a, b) in sorted(diff.items()):
                print(f"    {k}: {a} -> {b}")
        else:
            print("    identical")
        print()

    # ----- totals, each stated against the number that actually answered -----
    print("=" * 64)
    if read_ok == 0:
        print("NO COMPANY WAS READ. Every total below would be a zero over an "
              "empty set, so none is printed.")
        return
    print(f"{read_ok} of {len(companies)} companies read.\n")

    with_pages = [p for p in page_stats if p["older_pages"]]
    print(f"Companies with a second index page: {len(with_pages)} of {read_ok}")
    for p in with_pages:
        delta = p["periodic_paged"] - p["periodic_now"]
        print(f"  {p['label']:6} {p['older_pages']} page(s), "
              f"periodic {p['periodic_now']} -> {p['periodic_paged']} "
              f"({delta:+d})")

    failed_pages = [p for p in page_stats if p["older_failed"]]
    print(f"\nOlder pages that failed to read: "
          f"{sum(p['older_failed'] for p in page_stats)} "
          f"across {len(failed_pages)} company(s)")

    print(f"\nPublished row CHANGES: {len(changed)} of {read_ok}")
    for label, diff in changed:
        print(f"  {label}: " + ", ".join(
            f"{k} {a}->{b}" for k, (a, b) in sorted(diff.items())))

    print(f"\nRows that would APPEAR (project only when paged): "
          f"{len(newly_projecting)} of {read_ok}")
    for label, pub in newly_projecting:
        print(f"  {label}: {pub}")

    print(f"\nRows that would DISAPPEAR: {len(lost)} of {read_ok}")
    for label, pub in lost:
        print(f"  {label}: {pub}")

    print(f"\nORDERING INVARIANT (cadence truncates pool[:LAG_SAMPLE] "
          f"positionally, newest-first by filed date assumed):")
    if not ordering_breaks:
        print(f"  holds for all {read_ok} companies over the PAGED list")
    else:
        print(f"  BREAKS for {len(ordering_breaks)} of {read_ok}")
        for b in ordering_breaks:
            where = "inside the recent page" if b["in_recent"] else "at a page seam"
            print(f"  {b['label']:6} index {b['at']}: {b['prev']} then "
                  f"{b['next']}, {where}")


if __name__ == "__main__":
    main()
