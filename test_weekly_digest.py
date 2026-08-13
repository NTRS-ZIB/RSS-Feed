#!/usr/bin/env python3
"""Tests for weekly_digest's pure functions. Standalone, no network.

feedparser is stubbed below because it is absent from a plain working copy.
That is safe ONLY because feedparser is touched solely by parse_feed in
press_monitor.py (imported transitively for its item-taxonomy constants),
which none of the functions tested here calls. If a test ever needs a
feed-parsing function, REMOVE THE STUB rather than extending it: a stub
that grows is a stub that starts hiding things.

THIS TASK COVERS THE PUBLICATION-WINDOW FUNCTIONS: week_sessions,
recent_weeks, monday_of, iso_week_key, publication_week, period_published_in,
short_interest_publishes and ftd_publishes. Later tasks append sections below
main() rather than rewriting this scaffold.

THE ONE THAT MATTERS: publication_week assigns a settlement date to EXACTLY
ONE week. An earlier draft tested whether an 8-to-16-day publication window
overlapped the week -- nine days wide, so it overlapped two consecutive
weeks, and one settlement was counted twice toward convergence. Short
interest, which publishes twice a month, fired 7.3 times a week. The checks
below call the real short_interest_publishes across a run of consecutive
Mondays and require that exactly one of them claims a given settlement; a
window test would have claimed two.
"""

import sys
import types

sys.modules.setdefault("feedparser", types.ModuleType("feedparser"))

import weekly_digest as wd
import digest_render as dr
from datetime import date, timedelta

PASS, FAIL = "PASS", "FAIL"
results = []


def check(name, ok, detail=""):
    results.append((PASS if ok else FAIL, name))
    print(f"  [{PASS if ok else FAIL}] {name}" + (f" - {detail}" if detail else ""))


def main():
    print("WEEK SESSIONS")
    # week_sessions has no holiday awareness at all -- it returns five
    # consecutive calendar days from whatever Monday it is given. That is
    # what makes sessions[0] safe to compare a Monday against elsewhere
    # (period_published_in relies on exactly this).
    monday = date(2026, 7, 27)
    sessions = wd.week_sessions(monday)
    check("returns five days", len(sessions) == 5, str(sessions))
    check("starts on the Monday it was given", sessions[0] == monday)
    check("ends four calendar days later (Friday)",
          sessions[-1] == monday + timedelta(days=4))
    check("all five days are consecutive",
          sessions == [monday + timedelta(days=i) for i in range(5)])
    check("none of the five days is a Saturday or Sunday",
          all(d.weekday() < 5 for d in sessions))

    # 2026-09-07 is Labor Day, a US market holiday, and it is a Monday.
    # A holiday-aware function might skip or shift it; this one must not.
    holiday_monday = date(2026, 9, 7)
    holiday_sessions = wd.week_sessions(holiday_monday)
    check("a holiday Monday is still returned as sessions[0], unshifted",
          holiday_sessions[0] == holiday_monday,
          "no calendar consulted -- holidays fall out naturally downstream")
    check("the holiday week is still five calendar days",
          holiday_sessions == [holiday_monday + timedelta(days=i)
                               for i in range(5)])

    print("\nRECENT WEEKS")
    # recent_weeks(n, today) must exclude the week today sits inside while
    # it is still running, and include it once its Friday has passed. Both
    # arms are exercised through the `today` parameter, not through
    # date.today(), so the test is not calendar-dependent.
    mid_week = date(2026, 8, 12)             # Wednesday, week of Mon 8/10
    check("mid-week: the current (still-running) week is excluded",
          wd.recent_weeks(1, mid_week) == [date(2026, 8, 3)],
          str(wd.recent_weeks(1, mid_week)))
    check("mid-week, three weeks: oldest first, current week still excluded",
          wd.recent_weeks(3, mid_week)
          == [date(2026, 7, 20), date(2026, 7, 27), date(2026, 8, 3)],
          str(wd.recent_weeks(3, mid_week)))

    weekend = date(2026, 8, 15)              # Saturday, same week's Friday
    check("weekend: that week's Friday has passed, so it IS included",
          wd.recent_weeks(1, weekend) == [date(2026, 8, 10)],
          str(wd.recent_weeks(1, weekend)))
    # The other end of the same weekend, to confirm both Sat and Sun trip
    # the "Friday has passed" arm rather than just one of them.
    sunday = date(2026, 8, 16)
    check("Sunday also counts that week as complete",
          wd.recent_weeks(1, sunday) == [date(2026, 8, 10)],
          str(wd.recent_weeks(1, sunday)))

    print("\nWEEK KEYS (iso_week_key, monday_of)")
    check("iso_week_key names the ISO year and week",
          wd.iso_week_key(date(2026, 7, 27)) == "2026-W31",
          wd.iso_week_key(date(2026, 7, 27)))
    check("monday_of inverts a week key back to that week's Monday",
          wd.monday_of("2026-W31") == date(2026, 7, 27))
    check("monday_of accepts a lowercase week key",
          wd.monday_of("2026-w31") == date(2026, 7, 27))
    # Round trip from a day that is NOT itself a Monday: iso_week_key finds
    # its ISO week, monday_of must recover that week's Monday, not the
    # original day.
    wednesday = date(2026, 7, 29)
    check("the round trip recovers the week's Monday from a mid-week day",
          wd.monday_of(wd.iso_week_key(wednesday)) == date(2026, 7, 27),
          f"{wednesday} -> {wd.iso_week_key(wednesday)} -> "
          f"{wd.monday_of(wd.iso_week_key(wednesday))}")

    print("\nPUBLICATION WEEK")
    # publication_week must return a Monday regardless of which day of the
    # week the settlement date itself falls on -- the lag (12 days) does
    # not land on the same weekday it started from.
    week_start = date(2026, 7, 13)  # a Monday
    for offset in range(7):
        settlement = week_start + timedelta(days=offset)
        pub = wd.publication_week(settlement.isoformat())
        check(f"publication_week is a Monday for a {settlement.strftime('%A')} "
              f"settlement", pub is not None and pub.weekday() == 0,
              f"{settlement} -> {pub}")

    check("a malformed settlement date returns None, not a raise",
          wd.publication_week("not-a-date") is None)
    check("an out-of-range calendar date also returns None",
          wd.publication_week("2026-13-40") is None)
    check("an empty string also returns None",
          wd.publication_week("") is None)

    print("\nTHE SHORT-INTEREST INCIDENT")
    # THE INCIDENT, as a property of the real functions rather than of
    # arithmetic. This calls short_interest_publishes -- the function
    # CONTRIBUTORS actually uses to decide whether a week may claim a
    # settlement -- across eleven consecutive Mondays and requires exactly
    # one hit. The old window test (8 to 16 days) would have hit two.
    settlement = "2026-07-15"
    pub_monday = wd.publication_week(settlement)
    src = wd.Source("short_interest")
    src.data = {settlement: {}}
    ctx = {"short_interest": src}
    claiming_weeks = [
        pub_monday + timedelta(days=7 * i)
        for i in range(-5, 6)
        if wd.short_interest_publishes(ctx, wd.week_sessions(
            pub_monday + timedelta(days=7 * i)))
    ]
    check("EXACTLY ONE week, across eleven consecutive Mondays, claims "
          "this settlement",
          claiming_weeks == [pub_monday],
          f"claimed by {claiming_weeks}")
    check("the week that claims it is the settlement's own publication week",
          claiming_weeks == [pub_monday])

    print("\nPERIOD PUBLISHED IN")
    # First half of a month publishes at month end; second half publishes
    # around the 15th of the following month.
    a_week = wd.week_sessions(date(2026, 4, 27))       # contains 2026-04-30
    a_adjacent = wd.week_sessions(date(2026, 5, 4))
    check("the 'a' half publishes in the week containing month-end",
          wd.period_published_in("202604a", a_week))
    check("the 'a' half does not publish in the following week",
          not wd.period_published_in("202604a", a_adjacent))

    b_week = wd.week_sessions(date(2026, 5, 11))       # contains 2026-05-15
    b_adjacent = wd.week_sessions(date(2026, 5, 18))
    check("the 'b' half publishes in the week containing the 15th",
          wd.period_published_in("202604b", b_week))
    check("the 'b' half does not publish in the following week",
          not wd.period_published_in("202604b", b_adjacent))

    # THE DECEMBER WRAP: a 'b' period dated December publishes in JANUARY OF
    # THE NEXT CALENDAR YEAR. 202512b's own year field is 2025; the week it
    # publishes in is 2026. If the month arithmetic failed to roll the year,
    # this would resolve to January 2025 instead and never match any week
    # near the real publication date.
    dec_week = wd.week_sessions(date(2026, 1, 12))     # contains 2026-01-15
    dec_prior = wd.week_sessions(date(2026, 1, 5))
    check("a December 'b' period publishes in January of the NEXT year",
          wd.period_published_in("202512b", dec_week),
          "202512b names 2025; it must publish in 2026")
    check("it does not publish a week early",
          not wd.period_published_in("202512b", dec_prior))

    print("\nFTD PUBLISHES")
    # ftd_publishes aggregates period_published_in over every period in the
    # data, but must skip a period recorded with an "error" -- a failed
    # fetch says nothing about whether the period is actually available.
    ok_period_ctx = {"ftd": wd.Source("ftd")}
    ok_period_ctx["ftd"].data = {"202604a": {"AAPL": {}}}
    check("ftd_publishes is True when a clean period's window matches",
          wd.ftd_publishes(ok_period_ctx, a_week))
    check("ftd_publishes is False outside that period's window",
          not wd.ftd_publishes(ok_period_ctx, a_adjacent))

    errored_ctx = {"ftd": wd.Source("ftd")}
    errored_ctx["ftd"].data = {"202604a": {"error": "fetch failed"}}
    check("a period recorded with an error is NOT counted as published",
          not wd.ftd_publishes(errored_ctx, a_week),
          "a failed fetch is not evidence the period became available")

    empty_ctx = {"ftd": wd.Source("ftd")}
    empty_ctx["ftd"].data = {}
    check("no data at all means nothing published",
          not wd.ftd_publishes(empty_ctx, a_week))

    print("\nSILENT -- THE EDGAR-UNAVAILABLE INCIDENT")
    # THE INCIDENT: a dry run with EDGAR unavailable reported eleven companies
    # as having filed nothing, which nothing had measured. Every other section
    # of the digest UNDERSTATES when a source fails; this one ASSERTS, because
    # absence is its own subject. silent() has three independent exclusion
    # arms (count-or-source_failed, NOT_TESTABLE, filings_in_week) plus the
    # positive path that lists a company with none of those. The fixture below
    # mirrors the real shape build_week() produces (roster / contributors /
    # convergence / verdicts) rather than inventing one, and each exclusion
    # gets its own ticker so a check can fail on exactly one arm.
    #
    # QUIET is the positive control: without a company that IS genuinely
    # silent, every "excluded" check below would pass trivially, since an
    # empty result excludes everything.
    def verdict(level, basis=None, detail=None):
        return {"level": level, "figure": None, "basis": basis,
                "sources": [], "persistence": None, "detail": detail or {}}

    silent_roster = ["QUIET", "CONVG", "SFAIL", "UNTST", "FILED"]
    silent_verdicts = {
        "QUIET": {},
        "CONVG": {"price": verdict(wd.NOTABLE, basis="2.1x its own 12-week SD")},
        "SFAIL": {"filings": verdict(wd.SOURCE_FAILED,
                                     basis="EDGAR submissions fetch did not return")},
        "UNTST": {"filings": verdict(wd.NOT_TESTABLE)},
        "FILED": {"filings": verdict(wd.ROUTINE, detail={"filings_in_week": 3})},
    }
    silent_convergence = {
        "QUIET": {"count": 0, "source_failed": []},
        "CONVG": {"count": 1, "source_failed": []},
        "SFAIL": {"count": 0, "source_failed": ["filings"]},
        "UNTST": {"count": 0, "source_failed": []},
        "FILED": {"count": 0, "source_failed": []},
    }
    # "fetched" is what unmeasured names; "published_this_week" must NOT be
    # what it names -- a fortnightly source being quiet is the normal case.
    # bars mirrors build_week()'s own rule that an unfetched source is never
    # published either.
    silent_contributors = {
        "bars": {"fetched": False, "published_this_week": False},
        "short_interest": {"fetched": True, "published_this_week": False},
        "filings": {"fetched": True, "published_this_week": True},
    }
    silent_record = {
        "roster": silent_roster,
        "verdicts": silent_verdicts,
        "convergence": silent_convergence,
        "contributors": silent_contributors,
    }
    quiet, unmeasured = dr.silent(silent_record)

    check("the positive control: a genuinely silent company IS listed",
          "QUIET" in quiet, str(quiet))
    check("a company with a convergence count is excluded even though "
          "nothing filed -- it is not silent, it fired elsewhere",
          "CONVG" not in quiet, str(quiet))
    check("a company whose filings source failed is excluded, not "
          "reported as having filed nothing",
          "SFAIL" not in quiet, str(quiet))
    check("a company whose filings verdict is NOT_TESTABLE is excluded, "
          "not reported as silent",
          "UNTST" not in quiet, str(quiet))
    check("a company with a non-empty filings_in_week is excluded",
          "FILED" not in quiet, str(quiet))
    check("exactly the positive control is listed, nothing else leaks in",
          quiet == ["QUIET"], str(quiet))

    check("unmeasured names a contributor that was never fetched",
          "bars" in unmeasured, str(unmeasured))
    check("unmeasured does NOT name a contributor that was fetched but "
          "simply did not publish this week",
          "short_interest" not in unmeasured, str(unmeasured))
    check("unmeasured does NOT name a contributor that was fetched and "
          "did publish",
          "filings" not in unmeasured, str(unmeasured))

    print("\nFAILED SOURCES")
    # failed_sources treats "partial" as not-failed -- a deliberate choice,
    # matching fetch_filings()'s own comment: a partial EDGAR fetch still
    # carries real data for the issuers that answered, and the missing ones
    # are already visible per-company. This is the kind of choice that gets
    # "tidied" away, so it gets its own check rather than an implicit one.
    fs_record = {"sources": {
        "bars": {"status": "ok"},
        "filings": {"status": "partial"},
        "threshold": {"status": "failed"},
        "dilution": {"status": "unavailable"},
    }}
    bad_sources = dr.failed_sources(fs_record)
    check("an 'ok' source is not reported as failed",
          "bars" not in bad_sources, str(bad_sources))
    check("a 'partial' source is NOT treated as failed",
          "filings" not in bad_sources, str(bad_sources))
    check("a 'failed' source is reported",
          "threshold" in bad_sources, str(bad_sources))
    check("an 'unavailable' source is reported too, not only literal "
          "'failed'",
          "dilution" in bad_sources, str(bad_sources))
    check("failed_sources returns exactly the two non-ok/partial sources, "
          "sorted",
          bad_sources == ["dilution", "threshold"], str(bad_sources))

    print("\nNOT TESTABLE")
    # (ticker, contributor, basis) for every cell the rule could not be
    # applied to -- but only when there IS a basis to report. A NOT_TESTABLE
    # verdict with no basis would render an empty explanation, which is worse
    # than omitting the cell.
    nt_record = {"roster": ["AAAA", "BBBB", "CCCC", "DDDD"], "verdicts": {
        "AAAA": {"crossings": verdict(wd.NOT_TESTABLE,
                                       basis="34/60 bars minimum for a "
                                             "52-week window")},
        "BBBB": {"crossings": verdict(wd.NOT_TESTABLE, basis=None)},
        "CCCC": {"filings": verdict(wd.NOTABLE, basis="material filing")},
        "DDDD": {"volume": verdict(wd.ROUTINE)},
    }}
    untestable = dr.not_testable(nt_record)
    check("a NOT_TESTABLE cell carrying a basis is reported",
          ("AAAA", "crossings",
           "34/60 bars minimum for a 52-week window") in untestable,
          str(untestable))
    check("a NOT_TESTABLE cell with no basis is dropped, not reported as "
          "an empty explanation",
          not any(t == "BBBB" for t, _, _ in untestable), str(untestable))
    check("a NOTABLE cell is never reported here regardless of its basis",
          not any(t == "CCCC" for t, _, _ in untestable), str(untestable))
    check("a ROUTINE cell is not reported",
          not any(t == "DDDD" for t, _, _ in untestable), str(untestable))
    check("not_testable returns exactly the one qualifying cell",
          untestable == [("AAAA", "crossings",
                          "34/60 bars minimum for a 52-week window")],
          str(untestable))

    bad = sum(1 for r, _ in results if r == FAIL)
    print(f"\n{len(results) - bad}/{len(results)} checks passed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
