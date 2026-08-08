#!/usr/bin/env python3
"""
Probe: does a company's filing rate detect it going quiet?

TEMPORARY. Posts nothing, writes nothing, decides nothing.

TWO THINGS NARROW THIS BEFORE IT STARTS, and both are recorded so the probe is
not mistaken for an open question.

  * press_monitor.check_staleness() ALREADY detects a source that stops
    publishing, at max(6 x median, 60 days), calibrated per source. Twelve of
    nineteen companies are covered through their IR feed and the rest through
    scrapers or wire feeds. "This company stopped issuing press releases" is
    already answered.
  * The motivating case is closed. One of nineteen still publishes monthly
    production reports; DGXX stopping in autumn 2025 was part of a sector-wide
    shift that has completed. A component built now would mostly detect a
    transition that is over.

So the question is only whether a filing rate, measured against a company's own
history, separates a real change from ordinary variation — and the heartbeat
outcome is the expected one.

WHO FILES MATTERS, AND THE SUBMISSIONS PAYLOAD DOES NOT SEPARATE THEM.
A company's EDGAR index carries filings made BY OTHERS about it: Schedule
13D/G by holders, Forms 3/4/5 by insiders, Form 144 by sellers. On this roster
that is the majority of the index — 707 13D/G filings alone. Counting those as
"the company's filing rate" measures its shareholders' behaviour, not its own,
and would move for reasons that have nothing to do with the company going
quiet. Every figure below is reported both ways for that reason.
"""

import json
import os
import statistics
import sys
import time
import urllib.request
from collections import Counter, defaultdict
from datetime import date

import watchlist

UA = os.environ.get("SEC_USER_AGENT", "").strip()
if not UA:
    raise SystemExit("SEC_USER_AGENT is not set.")

SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik}.json"
OLDER = "https://data.sec.gov/submissions/{name}"
GAP = 0.15

# Filed BY someone other than the company, about the company.
NOT_THE_COMPANY = ("SC 13D", "SC 13G", "SCHEDULE 13D", "SCHEDULE 13G",
                   "3", "4", "5", "144")
# Capital-raising forms, which end in a burst rather than a decline.
BURST = ("424", "S-1", "S-3", "S-8", "POS AM", "EFFECT", "RW")


def filed_by_company(form):
    core = form.split("/")[0].strip()
    if core in ("3", "4", "5", "144"):
        return False
    return not any(form.startswith(p) for p in NOT_THE_COMPANY)


def fetch(url):
    req = urllib.request.Request(
        url, headers={"User-Agent": UA, "Accept-Encoding": "gzip, deflate"})
    with urllib.request.urlopen(req, timeout=60) as r:
        raw = r.read()
        enc = r.headers.get("Content-Encoding")
    if enc == "gzip":
        import gzip
        raw = gzip.decompress(raw)
    return json.loads(raw)


def all_filings(cik):
    data = fetch(SUBMISSIONS.format(cik=cik))
    rows = []

    def add(b):
        forms = b.get("form") or []
        dates = b.get("filingDate") or []
        for i, f in enumerate(forms):
            if i < len(dates) and dates[i]:
                rows.append((dates[i], f))

    add((data.get("filings") or {}).get("recent") or {})
    for extra in (data.get("filings") or {}).get("files") or []:
        time.sleep(GAP)
        add(fetch(OLDER.format(name=extra["name"])))
    return rows


def months_between(a, b):
    return (b[0] - a[0]) * 12 + (b[1] - a[1])


def monthly(rows, company_only):
    out = Counter()
    for d, f in rows:
        if company_only and not filed_by_company(f):
            continue
        out[(int(d[:4]), int(d[5:7]))] += 1
    return out


def series(counts, first, last):
    """Dense monthly series from first to last, zeros included."""
    out, cur = [], first
    while cur <= last:
        out.append((cur, counts.get(cur, 0)))
        y, m = cur
        cur = (y + (m == 12), m % 12 + 1)
    return out


# Companies whose circumstances demonstrably changed, with the month it
# happened. Dates from docs/watchlist.md, not from this probe.
EVENTS = {
    "DGXX": (2025, 10),   # production reporting stopped, autumn 2025
    "BGDE": (2026, 4),    # rename and wire migration, 2026-04-30
    "VIP": (2026, 7),     # rename, 2026-07-24
    "HUT": (2023, 11),    # combination under a new registrant
    "NUAI": (2025, 8),    # rename, 2025-08-13
    "ABTC": (2025, 9),    # reverse merger, 2025-09-03
}
TRAIL, AFTER = 12, 3


def rate_change(ser, at):
    """(trailing-12 mean, following-3 mean, log ratio) at a month, or None."""
    idx = {m: i for i, (m, _c) in enumerate(ser)}
    if at not in idx:
        return None
    i = idx[at]
    before = [c for _m, c in ser[max(0, i - TRAIL):i]]
    after = [c for _m, c in ser[i:i + AFTER]]
    if len(before) < TRAIL or len(after) < AFTER:
        return None
    b = statistics.mean(before)
    a = statistics.mean(after)
    if b <= 0:
        return None
    import math
    return b, a, math.log((a + 0.5) / (b + 0.5))


def main():
    print("Reading full EDGAR history for 19 companies...\n")
    raw = {}
    for t, (cik, _n) in sorted(watchlist.ciks().items()):
        try:
            raw[t] = all_filings(cik)
        except Exception as e:                                  # noqa: BLE001
            print(f"  {t}: FAILED {type(e).__name__}")
        time.sleep(GAP)

    print("=" * 78)
    print("WHO FILES — the payload is mostly not the company")
    print("=" * 78)
    print(f"  {'':6}{'total':>8}{'company':>9}{'others':>8}{'  company share'}")
    gt = gc = 0
    for t in sorted(raw):
        n = len(raw[t])
        c = sum(1 for d, f in raw[t] if filed_by_company(f))
        gt += n
        gc += c
        print(f"  {t:<6}{n:>8}{c:>9}{n - c:>8}{c / n * 100:>13.0f}%")
    print(f"\n  {gt} filings, {gc} by the company ({gc / gt * 100:.0f}%), "
          f"{gt - gc} by holders and insiders")

    # ------------------------------------------------------ 1. baseline ----
    print("\n" + "=" * 78)
    print("1. BASELINE SHAPE — what ordinary variation looks like")
    print("=" * 78)
    allser = {}
    for t in sorted(raw):
        cm = monthly(raw[t], company_only=True)
        if not cm:
            continue
        allser[t] = series(cm, min(cm), max(cm))

    import math
    for label, only in (("company-filed only", True), ("everything", False)):
        deltas = []
        for t in sorted(raw):
            cm = monthly(raw[t], company_only=only)
            if not cm:
                continue
            s = series(cm, min(cm), max(cm))
            for (_m1, a), (_m2, b) in zip(s, s[1:]):
                deltas.append(math.log((b + 0.5) / (a + 0.5)))
        deltas.sort()
        print(f"\n  month-on-month log change, {label} ({len(deltas)} months)")
        print(f"    p05 {deltas[len(deltas)//20]:+.2f}  "
              f"p25 {deltas[len(deltas)//4]:+.2f}  "
              f"p50 {statistics.median(deltas):+.2f}  "
              f"p75 {deltas[len(deltas)*3//4]:+.2f}  "
              f"p95 {deltas[len(deltas)*19//20]:+.2f}")
        print(f"    a halving is {math.log(0.5):+.2f}; "
              f"{sum(1 for d in deltas if d <= math.log(0.5)) / len(deltas) * 100:.0f}%"
              f" of ORDINARY months are at least that")

    print("\n  how much is calendar — mean company filings by month of year")
    bymonth = defaultdict(list)
    for t, s in allser.items():
        for (y, m), c in s:
            bymonth[m].append(c)
    means = {m: statistics.mean(v) for m, v in sorted(bymonth.items())}
    grand = statistics.mean([v for vs in bymonth.values() for v in vs])
    print("    " + "  ".join(f"{m:02d}:{means[m]:.1f}" for m in sorted(means)))
    print(f"    grand mean {grand:.2f}; peak/trough "
          f"{max(means.values()) / min(means.values()):.2f}x")

    # ---------------------------------------------------- 2. separation ----
    print("\n" + "=" * 78)
    print("2. SEPARATION — do known events look different from anything else?")
    print("=" * 78)
    null = []
    for t, s in allser.items():
        for m, _c in s:
            r = rate_change(s, m)
            if r:
                null.append(r[2])
    null.sort()
    print(f"  the NULL: {len(null)} company-months with a full "
          f"{TRAIL}-month baseline and {AFTER} months after")
    print(f"    p05 {null[len(null)//20]:+.2f}  p25 {null[len(null)//4]:+.2f}  "
          f"p50 {statistics.median(null):+.2f}  "
          f"p75 {null[len(null)*3//4]:+.2f}  p95 {null[len(null)*19//20]:+.2f}")

    print(f"\n  THE EVENTS, and where each falls in that distribution")
    print(f"    {'':6}{'month':<9}{'before':>8}{'after':>7}{'log':>7}"
          f"{'percentile':>12}")
    hits = []
    for t, at in sorted(EVENTS.items()):
        s = allser.get(t)
        r = rate_change(s, at) if s else None
        if not r:
            print(f"    {t:<6}{at[0]}-{at[1]:02d}  — insufficient history")
            continue
        b, a, lg = r
        pct = sum(1 for x in null if x <= lg) / len(null) * 100
        hits.append((t, lg, pct))
        print(f"    {t:<6}{at[0]}-{at[1]:02d}  {b:>8.1f}{a:>7.1f}{lg:>7.2f}"
              f"{pct:>11.0f}%")
    if hits:
        print(f"\n    median event percentile: "
              f"{statistics.median([p for _t, _l, p in hits]):.0f}%")
        print(f"    events below the null's 5th percentile: "
              f"{sum(1 for _t, _l, p in hits if p <= 5)}/{len(hits)}")

    # --------------------------------------------------------- 3. burst ----
    print("\n" + "=" * 78)
    print("3. BURSTS — does a finished offering dominate the measure?")
    print("=" * 78)
    for t in sorted(raw):
        b = sum(1 for d, f in raw[t]
                if filed_by_company(f) and f.startswith(BURST))
        c = sum(1 for d, f in raw[t] if filed_by_company(f))
        if c:
            print(f"  {t:<6}{b:>5}/{c:<5} {b / c * 100:>5.0f}% of company "
                  f"filings are capital-raising")

    # --------------------------------------------------------- 4. young ----
    print("\n" + "=" * 78)
    print("4. HISTORY AVAILABLE — the young-versus-failed arms")
    print("=" * 78)
    today = (date.today().year, date.today().month)
    for t in sorted(allser, key=lambda x: len(allser[x])):
        s = allser[t]
        n = months_between(s[0][0], today)
        flag = "  <- no usable baseline" if n < TRAIL else ""
        print(f"  {t:<6}{n:>5} months of company filings, "
              f"first {s[0][0][0]}-{s[0][0][1]:02d}{flag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
