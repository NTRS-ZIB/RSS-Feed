#!/usr/bin/env python3
"""
Expected earnings calendar -> Discord.

Derives when each company is likely to report, from its own EDGAR filing
history. No external data provider: SEC's submissions API gives every 10-Q and
10-K with both the period covered (reportDate) and the day it was filed
(filingDate). The gap between them is stable per company, so the next report
can be projected from the next period end plus that company's typical lag.

These are ESTIMATES, not announced dates. Companies announce actual dates by
press release, which the press release monitor already catches. This exists to
tell you what's coming before that announcement lands.
"""

import json
import os
import statistics
import sys
import time
from datetime import date, datetime, timedelta, timezone

import requests

# ------------------------------------------------------------------ CONFIG

# Same watchlist as press_monitor.py, pinned by CIK.
COMPANIES = {
    "BGDE": ("0001218683", "Big Digital Energy"),
    "ANY":  ("0001591956", "Sphere 3D"),
    "NUAI": ("0002028336", "New Era Energy & Digital"),
    "SLNH": ("0000064463", "Soluna Holdings"),
    "DGXX": ("0001854368", "Digi Power X"),
    "BKKT": ("0001820302", "Bakkt Holdings"),
    "MARA": ("0001507605", "MARA Holdings"),
    "WYFI": ("0002042022", "WhiteFiber"),
    "IREN": ("0001878848", "IREN Limited"),
    "CLSK": ("0000827876", "CleanSpark"),
    "VIP":  ("0001844971", "Vulcan Infrastructure and Power"),
}

# Annual and quarterly lags differ by 20-50 days, so they must never be pooled.
# Doing so yields a median fitting neither and a spread spanning the gap.
ANNUAL_FORMS = {"10-K", "20-F", "40-F"}
QUARTERLY_FORMS = {"10-Q"}
PERIODIC_FORMS = ANNUAL_FORMS | QUARTERLY_FORMS

# How many past filings to use when estimating the lag.
LAG_SAMPLE = 8

# Horizon for the "upcoming" section.
HORIZON_DAYS = 45

# A company is flagged overdue this many days past its estimate.
OVERDUE_GRACE = 10

# Above this spread in its historical lags, a company files too erratically for
# the projection to mean much. Shown with ~ and called out separately.
LOW_CONFIDENCE_SPREAD = 30

# ------------------------------------------------------------------ RUNTIME

WEBHOOK_URL = os.environ.get("WEBHOOK_URL_MARKET", "").strip()
SEC_USER_AGENT = os.environ.get("SEC_USER_AGENT", "").strip()
DRY_RUN = os.environ.get("DRY_RUN", "").strip().lower() in ("1", "true", "yes")

SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik}.json"

UP, AMBER, FLAT = 0x3FB950, 0xD29922, 0x8B949E


def sec_get(url):
    try:
        r = requests.get(url, timeout=(10, 30), headers={
            "User-Agent": SEC_USER_AGENT,
            "Accept-Encoding": "gzip, deflate",
        })
    except requests.RequestException as e:
        print(f"    {type(e).__name__}")
        return None
    if r.status_code != 200:
        print(f"    HTTP {r.status_code}")
        return None
    time.sleep(0.15)          # stay well under SEC's 10 req/sec
    try:
        return r.json()
    except ValueError:
        print("    unparseable JSON")
        return None


def periodic_filings(cik):
    """[(reportDate, filingDate, form), ...] newest first, periodic forms only."""
    data = sec_get(SUBMISSIONS.format(cik=cik))
    if not data:
        return []
    recent = (data.get("filings") or {}).get("recent") or {}
    forms = recent.get("form") or []
    filed = recent.get("filingDate") or []
    period = recent.get("reportDate") or []

    out = []
    for i, form in enumerate(forms):
        if form not in PERIODIC_FORMS:
            continue
        try:
            rd = date.fromisoformat(period[i])
            fd = date.fromisoformat(filed[i])
        except (ValueError, IndexError, TypeError):
            continue
        if rd and fd and fd >= rd:
            out.append((rd, fd, form))
    return out


def next_period_end(last_period):
    """The quarter end following `last_period`, preserving the fiscal cycle."""
    month = last_period.month + 3
    year = last_period.year + (month - 1) // 12
    month = (month - 1) % 12 + 1
    # Last day of that month.
    if month == 12:
        return date(year, 12, 31)
    return date(year, month + 1, 1) - timedelta(days=1)


def roll_to_business_day(d):
    """Nobody files on a weekend; push Sat/Sun to the following Monday."""
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def fiscal_year_end_month(annual):
    """Most common month among annual report periods, or None."""
    months = [rd.month for rd, _, _ in annual[:6]]
    if not months:
        return None
    return max(set(months), key=months.count)


def project(label, name, filings):
    """Estimate the next report date, or None if history is too thin."""
    if len(filings) < 2:
        return None

    annual = [f for f in filings if f[2] in ANNUAL_FORMS]
    quarterly = [f for f in filings if f[2] in QUARTERLY_FORMS]

    last_period = max(rd for rd, _, _ in filings)
    last_filed = max(fd for _, fd, _ in filings)
    upcoming = next_period_end(last_period)

    # Is the next period end this company's fiscal year end?
    fy_month = fiscal_year_end_month(annual)
    is_annual = fy_month is not None and upcoming.month == fy_month

    pool = annual if is_annual else quarterly
    degraded = False
    if len(pool) < 2:
        # e.g. a foreign issuer with no 10-Q history at all.
        pool = annual if len(annual) >= 2 else quarterly
        degraded = True
    if len(pool) < 2:
        return None

    lags = [(fd - rd).days for rd, fd, _ in pool[:LAG_SAMPLE]]
    lag = int(statistics.median(lags))
    kind = "annual" if (is_annual or (degraded and pool is annual)) else "10-Q"

    return {
        "label": label,
        "name": name,
        "period": upcoming,
        "expected": roll_to_business_day(upcoming + timedelta(days=lag)),
        "lag": lag,
        "spread": max(lags) - min(lags),
        "kind": kind,
        "degraded": degraded,
        "last_period": last_period,
        "last_filed": last_filed,
        "samples": len(lags),
    }


def build_message(rows):
    """Compact layout. Discord mobile wraps code blocks past ~28 characters,
    so every column here is earning its width. Form type and period end are
    pushed into markers and a header rather than per-row columns."""
    today = date.today()
    horizon = today + timedelta(days=HORIZON_DAYS)

    upcoming = sorted((r for r in rows if today <= r["expected"] <= horizon),
                      key=lambda r: r["expected"])
    overdue = sorted((r for r in rows
                      if r["expected"] < today - timedelta(days=OVERDUE_GRACE)),
                     key=lambda r: r["expected"])
    later = sorted((r for r in rows if r["expected"] > horizon),
                   key=lambda r: r["expected"])

    def marker(r):
        if r["degraded"]:
            return "?"
        if r["spread"] > LOW_CONFIDENCE_SPREAD:
            return "~"
        if r["kind"] == "annual":
            return "*"
        return " "

    def row(r, weekday=True):
        days = (r["expected"] - today).days
        when = f"{r['expected']:%a %d %b}" if weekday else f"{r['expected']:%d %b}"
        return (f"{r['label']:<4}{marker(r)} {when}"
                f"{days:>4}d {r['spread']:>3}d")

    lines = []
    if upcoming:
        periods = {r["period"] for r in upcoming}
        head = f"Next {HORIZON_DAYS}d"
        if len(periods) == 1:
            head += f" · P/E {upcoming[0]['period']:%b %Y}"
        lines.append(head)
        lines.append("-" * 26)
        # A period column only appears when period ends differ. Drop the
        # weekday to pay for it rather than overflow the phone width.
        mixed = len(periods) > 1
        for r in upcoming:
            line = row(r, weekday=not mixed)
            if mixed:
                line += f" {r['period']:%b}"
            lines.append(line)
    else:
        lines.append(f"Nothing expected in {HORIZON_DAYS}d.")

    if overdue:
        lines.append("")
        lines.append("Past estimate")
        lines.append("-" * 26)
        for r in overdue:
            late = (today - r["expected"]).days
            lines.append(f"{r['label']:<4}{marker(r)} est {r['expected']:%d %b}"
                         f"{late:>4}d ago")

    if later:
        lines.append("")
        for r in later:
            lines.append(f"{r['label']:<4}{marker(r)} {r['expected']:%a %d %b}"
                         f"  later")

    key = []
    if any(r["kind"] == "annual" for r in rows):
        key.append("* annual report")
    if any(r["spread"] > LOW_CONFIDENCE_SPREAD for r in rows):
        key.append("~ erratic filer")
    if any(r["degraded"] for r in rows):
        key.append("? thin history")
    if key:
        lines.append("")
        lines.extend(key)
        lines.append("last col = +/- spread")

    return "\n".join(lines)


def post(text, missing):
    desc = ("Projected from each company's own filing history — period end plus "
            "its median filing lag. These are estimates, not announced dates; "
            "the ± figure is the spread in that company's past lags.")
    if missing:
        desc += f"\n\nInsufficient history: {', '.join(missing)}"

    embed = {
        "title": "Expected reporting dates",
        "description": desc,
        "color": AMBER,
        "fields": [{"name": "\u200b", "value": f"```\n{text}\n```"}],
        "footer": {"text": "Derived from SEC EDGAR"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    try:
        r = requests.post(WEBHOOK_URL, json={"embeds": [embed]}, timeout=25)
    except requests.RequestException as e:
        print(f"webhook failed: {type(e).__name__}")
        return False
    if r.status_code >= 300:
        print(f"webhook returned {r.status_code}: {r.text[:200]}")
        return False
    return True


def main():
    if DRY_RUN:
        print("DRY RUN — nothing will be posted.\n")
    elif not WEBHOOK_URL:
        sys.exit("WEBHOOK_URL_MARKET is not set.")
    if not SEC_USER_AGENT:
        sys.exit("SEC_USER_AGENT is not set. Use: 'Your Name your@email.com'")

    rows, missing = [], []
    for label, (cik, name) in COMPANIES.items():
        print(f"  {label}...")
        filings = periodic_filings(cik)
        projection = project(label, name, filings)
        if projection:
            rows.append(projection)
            print(f"    {len(filings)} periodic filing(s), "
                  f"median lag {projection['lag']}d "
                  f"(±{projection['spread']}d over {projection['samples']})")
        else:
            missing.append(label)
            print(f"    only {len(filings)} periodic filing(s) — cannot project")

    if not rows:
        sys.exit("No projections possible; not posting.")

    text = build_message(rows)
    print(f"\n{text}\n")
    if missing:
        print(f"Insufficient history: {', '.join(missing)}\n")

    if DRY_RUN:
        print(f"Dry run complete: {len(rows)} projected, {len(missing)} skipped.")
        return

    if post(text, missing):
        print(f"Posted calendar for {len(rows)} company(s).")
    else:
        sys.exit("Post failed.")


if __name__ == "__main__":
    main()
