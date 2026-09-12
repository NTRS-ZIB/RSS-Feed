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
from collections import namedtuple
from datetime import date, datetime, timedelta, timezone

import requests

import watchlist
# The cadence decision, shared with build_snapshot so the two cannot answer
# the same question differently again. Re-exported by name: existing readers
# of earnings_calendar.LAG_SAMPLE and friends still resolve, and
# test_earnings_dates.py monkeypatches through this module's namespace.
from filing_cadence import (ANNUAL_FORMS, FY_MONTH_SAMPLE, LAG_SAMPLE,
                            LOW_CONFIDENCE_SPREAD, MIN_ANNUAL_FILINGS,
                            MIN_PERIODIC_FILINGS, MIN_QUARTERLY_FILINGS,
                            PERIODIC_FORMS, QUARTERLY_FORMS, cadence,
                            covers_a_period, fiscal_year_end_month,
                            next_annual_period_end, next_period_end,
                            roll_to_business_day)
import earnings_dates as ed
# ------------------------------------------------------------------ CONFIG

# The watchlist lives in watchlist.py — one record per company, one edit to add
# one. Keyed by CIK, which is permanent; tickers are not.
COMPANIES = watchlist.ciks()           # {ticker: (cik, name)}

# Annual and quarterly lags differ by 20-50 days, so they must never be pooled.
# Doing so yields a median fitting neither and a spread spanning the gap.
# Cadence facts live in filing_cadence, imported below and re-exported here
# so existing readers of earnings_calendar.ANNUAL_FORMS still resolve.

# How many past filings to use when estimating the lag.


# project() needs at least this many periodic filings before it will attempt
# a projection at all. Named so the "too little history" message can cite the
# same number it's measured against, rather than a magic 2 duplicated in a
# log line.


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


# Horizon for the "upcoming" section.
HORIZON_DAYS = 45

# A company is flagged overdue this many days past its estimate.
OVERDUE_GRACE = 10
# Also used for a `+` row, whose date the company announced but we parsed
# out of a release body. That is reading risk rather than projection
# spread; the effect wanted is the same, so the constant is shared rather
# than duplicated. See is_overdue.

# LOW_CONFIDENCE_SPREAD moved to filing_cadence and is re-exported through the
# import above. It is not a presentation choice: build_snapshot gates its
# published `confidence` on the same number, and while each module held its
# own the two compared it against different quantities.

# ------------------------------------------------------------------ RUNTIME

WEBHOOK_URL = os.environ.get("WEBHOOK_URL_MARKET", "").strip()
SEC_USER_AGENT = os.environ.get("SEC_USER_AGENT", "").strip()
DRY_RUN = os.environ.get("DRY_RUN", "").strip().lower() in ("1", "true", "yes")

SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik}.json"
# The older index pages `filings.files` names. `filings.recent` is a rolling
# window, not the index; see periodic_filings().
OLDER = "https://data.sec.gov/submissions/{name}"

# Paid after EVERY request, including the ones that fail. SEC's fair-access
# limit is 10 req/sec; this run makes 27.
REQUEST_GAP = 0.15

UP, AMBER, FLAT = 0x3FB950, 0xD29922, 0x8B949E


def sec_get(url):
    try:
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
        try:
            return r.json()
        except ValueError:
            print("    unparseable JSON")
            return None
    finally:
        # ON EVERY PATH, AND THE FAILURES ARE THE ONES THAT NEEDED IT. The gap
        # used to be paid only after a 200, so a transport error or a non-200
        # returned immediately and the next company was requested with no wait
        # at all. That is backwards: the case where this component fires a
        # burst at SEC is precisely the case where every request is failing.
        # A wrong SEC_USER_AGENT returns 403 from every sec.gov endpoint, so
        # the whole roster fails in a row, and paging makes that 27 requests
        # rather than 22.
        time.sleep(REQUEST_GAP)


# NAMED, NOT POSITIONAL, and for the reason build_snapshot.Row carries the
# same note: on 2026-09-10 a plain tuple in holder_events gained a field, one
# of its two readers kept unpacking the old width, and every live run raised
# ValueError while four green dry runs missed it. `complete` was added to this
# return on 2026-09-12. A field added to a namedtuple cannot silently break a
# reader.
Read = namedtuple("Read", "filings complete")


def rows_from(block):
    """[(period_end, filed, form)] for the periodic filings on one index page.

    INDEX ORDER IS PRESERVED AND THAT IS LOAD-BEARING. `cadence` truncates its
    lag pool positionally at LAG_SAMPLE and documents that the caller owns the
    order, because this component passes EDGAR's arrays newest-first by FILED
    date while build_snapshot sorts by PERIOD. Sorting here would silently move
    every median this component publishes.
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
        # `covers_a_period` here as well as inside `cadence`, so the count
        # this component prints and the count it reports against the floor
        # ("SPCX 1/2") describe the same filings the decision used.
        if rd and fd and fd >= rd and covers_a_period(rd):
            out.append((rd, fd, form))
    return out


def periodic_filings(cik):
    """Read(filings, complete) — every periodic filing on the index, newest first.

    `filings.recent` IS A ROLLING WINDOW, NOT THE INDEX. It holds roughly the
    newest thousand filings, and for an issuer that files a lot of Form 4s that
    window can be shorter than the cadence history this component projects
    from. This read only that page until 2026-09-12, and the loss was live:

      CRWV's recent page holds 1001 filings reaching back only to 2025-07-31,
      because 460 of them are Form 4s. Its 10-Q for period 2025-03-31, filed
      2025-05-15, accession 0001769628-25-000014, sits on the older page. That
      filing's lag is 45 days, THE LONGEST of its five, so dropping it pulled
      the published median down and the range in:

          unpaged  lags [43, 38, 44, 44]      median 43  range 6  sample 4
          paged    lags [43, 38, 44, 44, 45]  median 44  range 7  sample 5

      and this component posted `expected 2026-11-12` to Discord while
      `snapshot.json` — built by build_snapshot, which has paged all along —
      published 2026-11-13 off the same index. Two components answering the
      same question from the same source and disagreeing, with the untested one
      wrong, is the exact shape CLAUDE.md names.

    MEASURED ACROSS THE ROSTER, 2026-09-12, recent-only against paged
    (probe_earnings_paging.py, all 22 companies read, no page failures):

      * five companies have a second index page: CRWV, MARA, RIOT, SLNH, WULF
      * ONE published row moves, CRWV's, exactly as above. The other four gain
        8, 19, 51 and 5 periodic filings and publish IDENTICAL rows, because
        each already had LAG_SAMPLE=8 on the recent page and `pool[:LAG_SAMPLE]`
        takes the same eight either way

    CRWV IS NOT SPECIAL, AND THE RULE IS WORTH MORE THAN THE CASE. A company is
    exposed when BOTH hold: its selected pool is under LAG_SAMPLE, and it has a
    second index page. Positional truncation makes everything else invisible —
    SLNH gains 51 periodic filings and publishes the same row. Measured over
    BOTH pools for all 22, annual and quarterly separately, exactly one moved
    and exactly one gained filings while under the floor, and they are the same
    pool. Today's roster puts every company on the quarterly branch, so the
    annual arm was measured directly rather than inferred from the post: RIOT,
    MARA and SLNH gain 4, 2 and 12 annual filings and their annual median,
    range and fiscal-year-end month are unchanged.

    The rule is what to re-check when the roster changes. A new listing starts
    under LAG_SAMPLE by definition, and it becomes exposed the moment it also
    acquires a second page.
      * no row APPEARS and none DISAPPEARS, so this cannot flood the post the
        way a roster addition does
      * the `±` column does not move even for CRWV: it prints `spread // 2`,
        and 7 // 2 == 6 // 2 == 3. The range is nowhere near
        LOW_CONFIDENCE_SPREAD = 30, so no `~` moves and no confidence flips
      * the newest-first-by-filed-date order HOLDS over the concatenated list
        for all 22, so `cadence`'s positional truncation still sees what it
        was written to see

    WHY A FAILED OLDER PAGE RETURNS NOTHING RATHER THAN A SHORT LIST. A
    partial read still projects, and it projects the pre-fix number without
    saying so — the defect above, reappearing on any transient failure with no
    log line. Both siblings already refuse this: holder_events.sec_get raises,
    and build_snapshot catches per company and skips it. `complete` is False so
    main() can report the company as a SOURCE FAILURE rather than as thin
    history, which CLAUDE.md requires be different lines. That distinction was
    impossible before this change: `[]` meant both, and two comments in main()
    said so and worked around it by refusing to state a cause.

    Five extra requests per run across the roster, one per company with a
    second page, each behind the 0.15s gap sec_get already takes.
    """
    data = sec_get(SUBMISSIONS.format(cik=cik))
    if not data:
        return Read([], False)
    filings = (data.get("filings") or {})
    out = rows_from(filings.get("recent") or {})
    for extra in filings.get("files") or []:
        page = sec_get(OLDER.format(name=extra.get("name") or ""))
        if page is None:
            return Read([], False)
        out += rows_from(page)
    # NEWEST FIRST BY CONSTRUCTION, not by assumption about how EDGAR orders
    # its pages. `cadence` truncates pool[:LAG_SAMPLE] positionally and takes
    # the caller's order as given, so what that order IS has to be a fact about
    # this function rather than about a page layout nobody here controls. The
    # concatenation happens to arrive ordered for all 22 companies today
    # (probe_earnings_paging.py checks it explicitly and it held), so this sorts
    # nothing at present; that is the point. "A default sort is not a date sort,
    # and document order is not date order" is a trap this repo has already paid
    # for once, on DGXX's CMS returning an eight-month-old item first.
    #
    # By FILED date, never by period. Sorting by period is build_snapshot's
    # order, deliberately different, and adopting it here would silently merge
    # two components that are supposed to read the same index two ways.
    # Python's sort is stable, so filings sharing a date keep index order.
    out.sort(key=lambda t: t[1], reverse=True)
    return Read(out, True)


def project(label, name, filings):
    """Estimate the next report date, or None if history is too thin.

    THE DECISION LIVES IN `filing_cadence`, shared with `build_snapshot`,
    which projected the same issuers off the same index and disagreed with
    this component about three of them. Only the presentation is here: the
    `10-Q` label this post prints, and the halving of `spread` at the point it
    is rendered.

    `spread` HERE IS THE RANGE, which is what `marker()` thresholds, and
    `row()` prints half of it because the column is labelled `+/-`. Returning
    the halved figure instead would move every `~` on a range of exactly 31.
    """
    c = cadence(filings)
    if c is None:
        return None
    return {
        "label": label,
        "name": name,
        "period": c["period"],
        "expected": c["expected"],
        "lag": c["lag"],
        "spread": c["spread"],
        "kind": "10-Q" if c["kind"] == "quarterly" else c["kind"],
        "degraded": c["degraded"],
        "annual_only": c["annual_only"],
        "last_period": c["last_period"],
        "last_filed": c["last_filed"],
        "samples": c["sample"],
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
        #
        # A `+` row is the company's own date too, but read out of prose by a
        # rule measured over THREE companies. The uncertainty there is ours,
        # not theirs, so it keeps the grace: a misreading must not accuse a
        # company of missing a date it never gave us. This reuses a constant
        # justified for projection spread to cover reading risk instead,
        # which is deliberate and is recorded where OVERDUE_GRACE is defined.
        grace = 0 if r.get("disclosed_source") == "title" else OVERDUE_GRACE
        return r["expected"] < today - timedelta(days=grace)

    overdue = sorted((r for r in rows if is_overdue(r)),
                     key=lambda r: r["expected"])
    later = sorted((r for r in rows if r["expected"] > horizon),
                   key=lambda r: r["expected"])

    def marker(r):
        # First, and it outranks the rest: `*`, `~` and `?` all describe a
        # projection, and this row no longer has one.
        if r.get("disclosed"):
            # `+` is a date the company announced in the body of a release
            # and we parsed out; `!` is one it put in the headline. The
            # company stated both. What differs is how much of the reading
            # was ours, and the reader is entitled to know which they are
            # looking at. `?` would read better than `+` and is taken.
            return "+" if r.get("disclosed_source") == "body" else "!"
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
        #
        # HALVED, BECAUSE THE COLUMN IS LABELLED `+/-`. `r["spread"]` is the
        # full range of the company's past lags, and a ±N beside a date claims
        # a 2N-day window: printing the range there doubled every figure in
        # this column against its own header. The marker above still reads the
        # range, so no row's `~` moves.
        tail = "    " if r.get("disclosed") else f"{r['spread'] // 2:>3}d"
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
    if "+" in shown:
        key.append("+ date read from body")
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
            # Both announced markers blank that column, so the note must
            # name whichever are actually on screen. Naming `!` alone was
            # correct only while it was the only one.
            blanking = [m for m in ("!", "+") if m in shown]
            if blanking:
                lines.append(f"(blank on {' and '.join(blanking)} rows)")

    return "\n".join(lines)


def post(text, missing, unread):
    # `unread` IS REQUIRED, WITHOUT A DEFAULT, and that is deliberate. Given
    # one, a future caller that forgets the third argument drops the
    # source-failure line from the embed while the console still prints it —
    # the run looks complete to the reader and correct to whoever is watching
    # the log. The two places that must agree are a function signature apart,
    # so let the signature enforce it.
    desc = ("Projected from each company's own filing history — period end plus "
            "its median filing lag. These are estimates, not announced dates; "
            "the ± figure is half the spread in that company's past lags.")
    if missing:
        # Each entry already carries its count against the floor, e.g.
        # "SPCX 1/2" — see where `missing` is built.
        desc += (f"\n\nToo few periodic filings to project: "
                 f"{', '.join(missing)}")
    if unread:
        # ITS OWN LINE, AND NO COUNT. "Too little history yet" and "the source
        # failed" are different measurements and must never share a label —
        # a young company reported as a failure trains the reader to ignore the
        # failure line. The count belongs on the line above, where it measures
        # something; here there is no count to give, because the run does not
        # know what it did not read.
        desc += (f"\n\nEDGAR index unread this run, so no projection: "
                 f"{', '.join(unread)}")

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

    rows, missing, unread = [], [], []
    # Kept so the "announced but not applied" note below can cite how many
    # periodic filings were actually seen for that CIK. A CIK whose index did
    # not read is ABSENT from this map rather than holding 0, because 0 is a
    # measurement — "this company has filed nothing periodic" — and a failed
    # read has not earned it. `filing_counts.get(cik)` returning None is what
    # the note below branches on.
    filing_counts = {}
    for label, (cik, name) in COMPANIES.items():
        print(f"  {label}...")
        read = periodic_filings(cik)
        if not read.complete:
            # NOT `missing`. That line says "too few periodic filings", which
            # is a claim about the company; this is a claim about the run.
            unread.append(label)
            print("    EDGAR index did not read in full; no projection "
                  "attempted, and this is not a filing count")
            continue
        filings = read.filings
        filing_counts[cik] = len(filings)
        projection = project(label, name, filings)
        if projection:
            projection["cik"] = cik
            rows.append(projection)
            print(f"    {len(filings)} periodic filing(s), "
                  f"median lag {projection['lag']}d "
                  f"(±{projection['spread'] // 2}d over {projection['samples']})")
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
            n = filing_counts.get(cik)
            if n is None:
                # The index did not read, so there is no count to state. Saying
                # "0 periodic filing(s) seen" here would report a failed read
                # as a company that has never filed.
                print(f"  {label} has an announced date; its EDGAR index did "
                      f"not read this run, so there is no period end to apply "
                      f"it against")
                continue
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
    if unread:
        print(f"EDGAR index unread this run, so no projection: "
              f"{', '.join(unread)}\n")

    if DRY_RUN:
        print(f"Dry run complete: {len(rows)} projected, "
              f"{len(missing)} below the floor, {len(unread)} unread.")
        return

    if post(text, missing, unread):
        print(f"Posted calendar for {len(rows)} company(s).")
    else:
        sys.exit("Post failed.")


if __name__ == "__main__":
    main()
