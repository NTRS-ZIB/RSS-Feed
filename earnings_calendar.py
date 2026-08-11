#!/usr/bin/env python3
"""
Expected earnings calendar -> Discord.

Derives when each company is likely to report, from its own EDGAR filing
history. No external data provider: SEC's submissions API gives every 10-Q and
10-K with both the period covered (reportDate) and the day it was filed
(filingDate). The gap between them is stable per company, so the next report
can be projected from the next period end plus that company's typical lag.

Most rows are ESTIMATES, not announced dates. Companies announce actual dates
by press release; the press release monitor reads the date out of the release
title and this script overlays it, marked `!`, in place of the projection for
any row it covers. This exists to tell you what's coming before that
announcement lands, and to show the real date once it has.
"""

import json
import os
import statistics
import sys
import time
from datetime import date, datetime, timedelta, timezone

import requests

import watchlist
import earnings_dates as ed
# ------------------------------------------------------------------ CONFIG

# The watchlist lives in watchlist.py — one record per company, one edit to add
# one. Keyed by CIK, which is permanent; tickers are not.
COMPANIES = watchlist.ciks()           # {ticker: (cik, name)}

# Annual and quarterly lags differ by 20-50 days, so they must never be pooled.
# Doing so yields a median fitting neither and a spread spanning the gap.
ANNUAL_FORMS = {"10-K", "20-F", "40-F"}
QUARTERLY_FORMS = {"10-Q"}
PERIODIC_FORMS = ANNUAL_FORMS | QUARTERLY_FORMS

# How many past filings to use when estimating the lag.
LAG_SAMPLE = 8

# project() needs at least this many periodic filings before it will attempt
# a projection at all. Named so the "too little history" message can cite the
# same number it's measured against, rather than a magic 2 duplicated in a
# log line.
MIN_PERIODIC_FILINGS = 2

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


def probe_form_mix():
    """Who on this roster files what, and what a 6-K filer's 6-Ks look like.

    Throwaway. The question behind it: `PERIODIC_FORMS` is 10-K/20-F/40-F/10-Q,
    so a company that reports interim results on a 6-K is invisible to this
    component and its row can never clear. BTDR has sat overdue since 20 July
    for exactly that reason.

    The predicate worth building on is OBSERVABLE — "has no 10-Q history" —
    not the legal classification "foreign private issuer", which is inferred.
    So this counts forms rather than guessing status, and for the no-10-Q
    companies it dumps recent 6-Ks with their document descriptions, because
    whether a results 6-K can be told from the other ninety-odd decides
    whether projecting a date is reachable at all.
    """
    import collections
    print("=" * 78)
    print("ROSTER FORM MIX")
    print("=" * 78)
    print(f"{'':6}{'total':>7}{'10-K':>6}{'10-Q':>6}{'20-F':>6}{'40-F':>6}"
          f"{'6-K':>6}{'8-K':>6}  predicate")
    no_10q = []
    for label, (cik, _name) in COMPANIES.items():
        data = sec_get(SUBMISSIONS.format(cik=cik))
        recent = ((data or {}).get("filings") or {}).get("recent") or {}
        forms = recent.get("form") or []
        c = collections.Counter(forms)
        quarterly = c.get("10-Q", 0)
        verdict = "has 10-Q" if quarterly else "NO 10-Q"
        if not quarterly:
            no_10q.append((label, cik, recent))
        print(f"{label:<6}{len(forms):>7}{c.get('10-K', 0):>6}{quarterly:>6}"
              f"{c.get('20-F', 0):>6}{c.get('40-F', 0):>6}{c.get('6-K', 0):>6}"
              f"{c.get('8-K', 0):>6}  {verdict}")

    for label, cik, recent in no_10q:
        print("\n" + "=" * 78)
        print(f"{label} — most recent 6-K filings, with document descriptions")
        print("=" * 78)
        forms = recent.get("form") or []
        filed = recent.get("filingDate") or []
        period = recent.get("reportDate") or []
        desc = recent.get("primaryDocDescription") or []
        shown = 0
        for i, form in enumerate(forms):
            if form != "6-K":
                continue
            print(f"  filed {filed[i] if i < len(filed) else '?':<12}"
                  f"period {(period[i] if i < len(period) else '') or '-':<12}"
                  f"{(desc[i] if i < len(desc) else '') or '(no description)'}")
            shown += 1
            if shown >= 12:
                break
        if not shown:
            print("  none in the recent block")
    print("=" * 78 + "\n")


def probe_btdr_announcements():
    """Does BTDR ever pre-announce a results date, and can a results 6-K be
    identified from its filing index?

    The design rests on one or the other. If it publishes an advance notice,
    the disclosed-date feature already covers it and almost no code is needed.
    If it does not, that route is dead for this company and the honest answer
    is an annual-only projection.

    Two sources because either alone could mislead: the IR feed shows what it
    publishes, the filing index shows what it files, and an advance notice
    might exist in one and not the other.
    """
    import re as _re
    import earnings_dates as _ed

    print("=" * 78)
    print("BTDR IR FEED — every title, and whether it reads as an announcement")
    print("=" * 78)
    feed = "https://ir.bitdeer.com/rss/news-releases.xml"
    # A BROWSER UA, not the SEC one. This is a gcs-web IR platform, and those
    # stall non-browser User-Agents — the exact opposite of GlobeNewswire.
    # Sending SEC_USER_AGENT here timed out, which is the per-host bet in
    # CLAUDE.md's trap table being lost in the other direction.
    try:
        r = requests.get(feed, timeout=(10, 30), headers={
            "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/126.0.0.0 Safari/537.36"),
            "Accept": ("application/rss+xml, application/atom+xml, "
                       "application/xml;q=0.9, text/html;q=0.8, */*;q=0.7"),
            "Accept-Language": "en-US,en;q=0.9",
            "Connection": "close"})
        xml = r.text if r.status_code == 200 else ""
        print(f"  HTTP {r.status_code}, {len(xml)} chars")
    except requests.RequestException as e:
        xml = ""
        print(f"  fetch failed: {type(e).__name__}")
    titles = _re.findall(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>",
                         xml, _re.S)
    dates = _re.findall(r"<pubDate>(.*?)</pubDate>", xml, _re.S)
    for i, t in enumerate(titles[1:], 0):          # [0] is the channel title
        t = " ".join(t.split())
        when = " ".join(dates[i].split())[:16] if i < len(dates) else "?"
        flag = "ANNOUNCEMENT" if _ed.looks_like_announcement(t) else ""
        print(f"  {when:<18}{flag:<13}{t[:80]}")

    print("\n" + "=" * 78)
    print("BTDR 6-K FILING INDEXES — document descriptions inside each filing")
    print("=" * 78)
    cik = COMPANIES["BTDR"][0]
    data = sec_get(SUBMISSIONS.format(cik=cik))
    recent = ((data or {}).get("filings") or {}).get("recent") or {}
    forms = recent.get("form") or []
    accs = recent.get("accessionNumber") or []
    filed = recent.get("filingDate") or []
    shown = 0
    for i, form in enumerate(forms):
        if form != "6-K" or i >= len(accs):
            continue
        acc = accs[i].replace("-", "")
        url = (f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc}"
               f"/index.json")
        idx = sec_get(url)
        docs = ((idx or {}).get("directory") or {}).get("item") or []
        names = [f"{d.get('name', '')} ({d.get('type', '')})" for d in docs
                 if not d.get("name", "").endswith((".xml", ".xsd", ".jpg"))]
        print(f"  filed {filed[i] if i < len(filed) else '?'}  {', '.join(names)[:120]}")
        shown += 1
        if shown >= 8:
            break
    print("=" * 78 + "\n")


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
    if len(filings) < MIN_PERIODIC_FILINGS:
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
    def is_overdue(r):
        # OVERDUE_GRACE exists to allow for the spread in OUR projection. A
        # company's own announced date has no spread to allow for, so it gets
        # none: announced the 12th and nothing filed by the 13th is late.
        grace = 0 if r.get("disclosed") else OVERDUE_GRACE
        return r["expected"] < today - timedelta(days=grace)

    overdue = sorted((r for r in rows if is_overdue(r)),
                     key=lambda r: r["expected"])
    later = sorted((r for r in rows if r["expected"] > horizon),
                   key=lambda r: r["expected"])

    def marker(r):
        # First, and it outranks the rest: `*`, `~` and `?` all describe a
        # projection, and this row no longer has one.
        if r.get("disclosed"):
            return "!"
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
        # A spread is a property of a projection. On an announced row there is
        # nothing for it to describe, and printing 0 would read as a claim of
        # perfect precision rather than as absence. Four spaces keeps the
        # column aligned against "  6d".
        tail = "    " if r.get("disclosed") else f"{r['spread']:>3}d"
        return (f"{r['label']:<4}{marker(r)} {when}"
                f"{days:>4}d {tail}")

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
        # "Past estimate" stops being true once a row can be past a date the
        # company announced rather than one we projected.
        lines.append("Overdue")
        lines.append("-" * 26)
        for r in overdue:
            late = (today - r["expected"]).days
            # Same width, so the column does not move between the two cases.
            what = "due" if r.get("disclosed") else "est"
            lines.append(f"{r['label']:<4}{marker(r)} {what} "
                         f"{r['expected']:%d %b}{late:>4}d ago")

    if later:
        lines.append("")
        for r in later:
            lines.append(f"{r['label']:<4}{marker(r)} {r['expected']:%a %d %b}"
                         f"  later")

    # Built from the markers marker() actually assigns, not from the row
    # conditions independently — those disagree whenever a row is both
    # disclosed and, say, erratic: marker() shows `!` for it since that
    # outranks `~`, so a key built from "any row has a high spread" would
    # advertise a `~` that appears nowhere in the table.
    shown = {marker(r) for r in rows}
    key = []
    if "*" in shown:
        key.append("* annual report")
    if "~" in shown:
        key.append("~ erratic filer")
    if "?" in shown:
        key.append("? thin history")
    if "!" in shown:
        key.append("! announced by company")
    if key:
        lines.append("")
        lines.extend(key)
        lines.append("last col = +/- spread")
        if "!" in shown:
            lines.append("(blank on ! rows)")

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
    # Kept so the "announced but not applied" note below can cite how many
    # periodic filings were actually seen for that CIK, rather than asserting
    # why project() returned nothing — periodic_filings() returns [] on a
    # fetch failure exactly as it does on genuine thin history, so a stated
    # cause would be a guess dressed as an observation.
    filing_counts = {}
    for label, (cik, name) in COMPANIES.items():
        print(f"  {label}...")
        filings = periodic_filings(cik)
        filing_counts[cik] = len(filings)
        projection = project(label, name, filings)
        if projection:
            projection["cik"] = cik
            rows.append(projection)
            print(f"    {len(filings)} periodic filing(s), "
                  f"median lag {projection['lag']}d "
                  f"(±{projection['spread']}d over {projection['samples']})")
        else:
            missing.append(label)
            print(f"    only {len(filings)} periodic filing(s) — cannot project")

    if not rows:
        sys.exit("No projections possible; not posting.")

    disclosed, status = ed.load()
    if status == "missing":
        print("\nNo earnings_dates.json — the press monitor has not written "
              "one yet. Every row below is a projection.")
    elif status == "unreadable":
        print("\nearnings_dates.json is unreadable — every row below is a "
              "projection.")
    elif status == "empty":
        print("\nearnings_dates.json holds no announced dates.")
    elif status == "ok":
        print(f"\nearnings_dates.json loaded: {len(disclosed)} record(s).")
    rows, applied, notes = ed.apply(rows, disclosed, date.today())
    for note in notes:
        print(f"  {note}")
    print(f"{applied} row(s) use an announced date.")

    # apply() only knows the rows it was handed, which are the rows that
    # projected — it has no view of the roster, so it cannot tell a company
    # that's absent from watchlist.py from one that's on it but hasn't filed
    # enough to project yet. That distinction belongs here, where COMPANIES
    # is in scope.
    cik_to_label = {cik: label for label, (cik, name) in COMPANIES.items()}
    projected_ciks = {r["cik"] for r in rows}
    for cik in sorted(disclosed):
        if cik in projected_ciks:
            continue
        label = cik_to_label.get(cik)
        if label is not None:
            # What was observed, not why: periodic_filings() returns []
            # both on genuine thin history and on an SEC fetch failure, so
            # asserting a cause here would be right by luck rather than by
            # evidence. The count against the floor is the useful part.
            n = filing_counts.get(cik, 0)
            print(f"  {label} has an announced date; {n}/"
                  f"{MIN_PERIODIC_FILINGS} periodic filing(s) seen — not "
                  f"enough to project a period end, so the announced date "
                  f"is not applied")
        else:
            rec = disclosed[cik]
            ticker = rec.get("ticker") if isinstance(rec, dict) else rec
            print(f"  stored date for CIK {cik} ({ticker}) is not on the "
                  f"roster")

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
    probe_btdr_announcements()
    sys.exit(0)   # throwaway probe branch: measure, post nothing, stop
    main()
