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

# Below this many QUARTERLY filings, a company gets no quarterly projection at
# all. Two is not a tuning knob: it is the number needed to compute a median
# lag, so below it there is no quarterly cadence to measure and any date
# produced would be assembled from parts that describe no company.
#
# KEYED ON THE POOL, NOT ON HAVING NO 10-Q. The difference only shows at the
# transition and that is where it matters. "Has no 10-Q" flips to normal
# treatment the moment a first 10-Q lands, and normal treatment then finds one
# filing in the quarterly pool, takes the degraded path, and applies an annual
# lag to a quarter end — the exact defect this exists to remove, back for the
# three months until a second one arrives.
MIN_QUARTERLY_FILINGS = 2

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


def next_annual_period_end(last_period):
    """Twelve months on, preserving the fiscal date.

    next_period_end() advances three months unconditionally. Using it for an
    annual filer produces a quarter end the company never reports on, which is
    how BTDR came to be projected against 31 March.
    """
    try:
        return last_period.replace(year=last_period.year + 1)
    except ValueError:            # 29 February
        return last_period.replace(year=last_period.year + 1, day=28)


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

    # A company whose filings never described a quarterly cadence does not get
    # one invented. It projects its annual cycle, which is real, and nothing
    # else. See MIN_QUARTERLY_FILINGS.
    annual_only = len(quarterly) < MIN_QUARTERLY_FILINGS
    if annual_only:
        if len(annual) < 2:
            return None
        # The last ANNUAL period, not the last of any filing: a stray 10-Q
        # would otherwise set the cycle this projection is built on.
        upcoming = next_annual_period_end(max(rd for rd, _, _ in annual))
        pool, kind, degraded = annual, "annual", False
    else:
        upcoming = next_period_end(last_period)
        fy_month = fiscal_year_end_month(annual)
        is_annual = fy_month is not None and upcoming.month == fy_month
        pool = annual if is_annual else quarterly
        degraded = False
        if len(pool) < 2:
            pool = annual if len(annual) >= 2 else quarterly
            degraded = True
        if len(pool) < 2:
            return None
        kind = "annual" if (is_annual or (degraded and pool is annual)) else "10-Q"

    lags = [(fd - rd).days for rd, fd, _ in pool[:LAG_SAMPLE]]
    lag = int(statistics.median(lags))

    return {
        "label": label,
        "name": name,
        "period": upcoming,
        "expected": roll_to_business_day(upcoming + timedelta(days=lag)),
        "lag": lag,
        "spread": max(lags) - min(lags),
        "kind": kind,
        "degraded": degraded,
        "annual_only": annual_only,
        "last_period": last_period,
        "last_filed": last_filed,
        "samples": len(lags),
    }


def build_message(rows, announced=None):
    """Compact layout. Discord mobile wraps code blocks past ~28 characters,
    so every column here is earning its width. Form type and period end are
    pushed into markers and a header rather than per-row columns."""
    today = date.today()
    horizon = today + timedelta(days=HORIZON_DAYS)

    upcoming = sorted((r for r in rows if today <= r["expected"] <= horizon),
                      key=lambda r: r["expected"])
    def is_overdue(r):
        # An annual-only row projects the ANNUAL filing itself — 10-K, 20-F
        # and 40-F are all in PERIODIC_FORMS, so this component can see one
        # arrive exactly as it can for any other row. DGXX makes this
        # concrete: it files both a 10-K and a 10-Q. There is no longer a
        # class of row this check cannot check, so it is not exempted.
        #
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

    if announced:
        lines.append("")
        # Its own block, because these dates describe a DIFFERENT report from
        # the row that company has above. Overlaying one would put a row in
        # the upcoming table with a period end no other row shares, which
        # flips the whole table to mixed-period: the header loses its P/E
        # line, every row drops its weekday to buy a period column, and the
        # row itself prints an August date against a December period.
        lines.append("Announced")
        lines.append("-" * 26)
        for label, when in announced:
            days = (when - today).days
            lines.append(f"{label:<4}  {when:%a %d %b}{days:>4}d")

    if later:
        lines.append("")
        # Its own heading. Without one, "Announced" directly above reads as
        # the heading for this block too, and a company can be in both:
        # DGXX~ due in the Announced section on one date and a Later row on
        # another describing its actual annual projection, three lines apart
        # with no marker separating which block owns which line.
        lines.append("Later")
        lines.append("-" * 26)
        for r in later:
            lines.append(f"{r['label']:<4}{marker(r)} {r['expected']:%a %d %b}"
                         f"  later")

    # Built from the markers marker() actually assigns, not from the row
    # conditions independently — those disagree whenever a row is both
    # disclosed and, say, erratic: marker() shows `!` for it since that
    # outranks `~`, so a key built from "any row has a high spread" would
    # advertise a `~` that appears nowhere in the table.
    # From the rows that are actually RENDERED, not from every row. A row
    # whose date sits between `today - OVERDUE_GRACE` and `today` is in no
    # section: too late for upcoming, not yet overdue, not beyond the horizon.
    # Keying off `rows` would advertise its marker with nothing in the table
    # carrying it.
    rendered = upcoming + overdue + later
    shown = {marker(r) for r in rendered}
    key = []
    if "*" in shown:
        key.append("* annual report")
    if "~" in shown:
        key.append("~ erratic filer")
    if "?" in shown:
        key.append("? thin history")
    if "!" in shown:
        key.append("! announced by company")
    if announced:
        key.append("announced, not projected")
    if key:
        lines.append("")
        lines.extend(key)
        # Only when a rendered row actually populates that column. An `!` row
        # blanks it, so a table whose every row is announced would otherwise
        # explain a column nothing fills.
        has_spread = any(not r.get("disclosed") for r in rendered)
        if has_spread:
            lines.append("last col = +/- spread")
            if "!" in shown:
                lines.append("(blank on ! rows)")

    return "\n".join(lines)


def post(text, missing):
    desc = ("Projected from each company's own filing history — period end plus "
            "its median filing lag. These are estimates, not announced dates; "
            "the ± figure is the spread in that company's past lags.")
    if missing:
        # Each entry already carries its count against the floor, e.g.
        # "SPCX 1/2" — see where `missing` is built.
        desc += (f"\n\nToo few periodic filings to project: "
                 f"{', '.join(missing)}")

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
            # A COUNT AGAINST THE FLOOR, NOT A BARE NAME. A name in a list is
            # an excuse; a count tells the reader both that nothing is wrong
            # and roughly when it resolves. Every other component on this
            # roster does this — CLAUDE.md records earnings_calendar.py as the
            # one that did not.
            #
            # The count is stated without a cause. `project()` returns None
            # both when there are fewer than MIN_PERIODIC_FILINGS filings and
            # when no single form type reaches two, so citing the floor as the
            # reason would read "2/2 filings, not enough" whenever the second
            # case fires.
            missing.append(f"{label} {len(filings)}/{MIN_PERIODIC_FILINGS}")
            print(f"    {len(filings)} periodic filing(s), no projection "
                  f"derived from them")

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

    announced = ed.announced_elsewhere(rows, disclosed, date.today())
    if announced:
        print(f"{len(announced)} announced date(s) shown separately, because "
              f"the row for that company projects a different report: "
              f"{', '.join(f'{l} {d}' for l, d in announced)}")

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
            # The count, without naming which floor stopped it. project()
            # returns None both below MIN_PERIODIC_FILINGS and when no single
            # form type reaches two, so citing the former reads "2/2 seen, not
            # enough" whenever the latter is what fired.
            print(f"  {label} has an announced date; {n} periodic filing(s) "
                  f"seen and no projection derived from them, so there is no "
                  f"period end to apply it against")
        else:
            rec = disclosed[cik]
            ticker = rec.get("ticker") if isinstance(rec, dict) else rec
            print(f"  stored date for CIK {cik} ({ticker}) is not on the "
                  f"roster")

    annual_only = [r["label"] for r in rows if r.get("annual_only")]
    if annual_only:
        print(f"\nProjected annually, with no quarterly estimate: "
              f"{', '.join(annual_only)}. Each files fewer than "
              f"{MIN_QUARTERLY_FILINGS} quarterly reports, so no quarterly "
              f"cadence can be measured.")
    else:
        print("\nNo company is below the quarterly filing floor.")

    text = build_message(rows, announced=announced)
    print(f"\n{text}\n")
    if missing:
        print(f"Too few periodic filings to project: "
              f"{', '.join(missing)}\n")

    if DRY_RUN:
        print(f"Dry run complete: {len(rows)} projected, {len(missing)} skipped.")
        return

    if post(text, missing):
        print(f"Posted calendar for {len(rows)} company(s).")
    else:
        sys.exit("Post failed.")


if __name__ == "__main__":
    main()
