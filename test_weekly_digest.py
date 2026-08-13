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

import inspect
import os
import re
import sys
import tempfile
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

    # The 'a' half carries its OWN year roll, on a separate line from the 'b'
    # half's. Mutating one leaves the other passing, so the December wrap
    # needs both: 202512a resolves to 2025-12-31 and would resolve to
    # 2024-12-31 if its roll were dropped.
    check("a December 'a' period publishes at the END of that December",
          wd.period_published_in("202512a", wd.week_sessions(date(2025, 12, 29))),
          "its own year roll, not the 'b' half's")

    # THE WEEKEND GAP, FIXED 2026-08-13 AND PINNED THE OTHER WAY ROUND.
    # `sessions` is Monday to Friday, so a nominal publication date on a
    # Saturday or Sunday fell between one week's Friday and the next week's
    # Monday and was claimed by NO week at all -- permanently unsatisfiable
    # rather than late. Measured when this suite found it: 8 of 24 half-month
    # periods in 2026. The previous version of this check pinned that
    # behaviour deliberately, so that a fix would have something to break.
    # This is that fix, and this is the check it broke.
    weekend_period = "202601a"                     # nominal 2026-01-31, a Saturday
    claimed = [m for m in (date(2026, 1, 5) + timedelta(days=7 * i)
                           for i in range(12))
               if wd.period_published_in(weekend_period, wd.week_sessions(m))]
    check("A WEEKEND PUBLICATION DATE IS CLAIMED BY EXACTLY ONE WEEK",
          len(claimed) == 1, f"claimed by {claimed}")
    # Forward, not back. Rolling back to the Friday would claim the period in
    # a week that ENDED BEFORE its nominal date, reporting data as available
    # before it was; rolling forward claims it in a week where the file
    # certainly exists.
    check("it rolls FORWARD to the following Monday, never back",
          claimed == [date(2026, 2, 2)],
          f"nominal Sat 2026-01-31 -> claimed by {claimed}")

    # THE PROPERTY, over the whole year rather than one example: every period
    # is claimed, and none is claimed twice. A count alone would not separate
    # "all fine" from "half of them silently invisible", which is exactly the
    # state this component was in.
    counts = []
    for month in range(1, 13):
        for half in "ab":
            p = f"2026{month:02d}{half}"
            n = sum(1 for i in range(60)
                    if wd.period_published_in(
                        p, wd.week_sessions(date(2025, 12, 29)
                                            + timedelta(days=7 * i))))
            counts.append((p, n))
    check("EVERY 2026 PERIOD IS CLAIMED BY EXACTLY ONE WEEK, none by zero",
          all(n == 1 for _, n in counts),
          f"not exactly once: {[p for p, n in counts if n != 1]}")

    # Load-bearing beyond formatting: digest filenames sort lexically and the
    # renderer compares week keys as strings, so an unpadded week 9 would sort
    # after week 10.
    check("iso_week_key zero-pads the week number",
          wd.iso_week_key(date(2026, 3, 2)) == "2026-W10"
          and wd.iso_week_key(date(2026, 2, 23)) == "2026-W09",
          wd.iso_week_key(date(2026, 2, 23)))

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

    print("\nCHECK_POST -- THE OUTPUT GUARDS")
    # check_post returns a list of problems against Discord's own limits plus
    # this repo's MONO_WIDTH. The first check is the one most likely to be
    # missing: a guard that always complains is one nobody reads, so a
    # compliant post has to come back clean before anything else is trusted.
    def mk_embed(title="T", desc="d" * 10, fields=None, footer="f" * 10):
        return {"title": title, "description": desc,
                "fields": fields if fields is not None else [],
                "footer": {"text": footer}}

    compliant = mk_embed(fields=[{"name": "n", "value": "```\nAAAA +1.0%\n```"}])
    check("a compliant embed returns no problems -- a guard that always "
          "complains is one nobody reads",
          dr.check_post(compliant) == [], str(dr.check_post(compliant)))

    # One check per limit, each fixture breaching only that one limit so the
    # returned problem list is exactly one entry.
    desc_over = mk_embed(desc="x" * (dr.DESC_LIMIT + 1))
    problems = dr.check_post(desc_over)
    check("a description over DESC_LIMIT is reported, and only that limit",
          problems == [f"description {dr.DESC_LIMIT + 1} > {dr.DESC_LIMIT}"],
          str(problems))

    field_over = mk_embed(fields=[{"name": "n",
                                   "value": "y" * (dr.FIELD_LIMIT + 1)}])
    problems = dr.check_post(field_over)
    check("a field value over FIELD_LIMIT is reported, and only that "
          "limit -- it does not start with a fence, so the monospace arm "
          "never runs",
          problems == [f"field 'n' {dr.FIELD_LIMIT + 1} > {dr.FIELD_LIMIT}"],
          str(problems))

    # Each field value and the description individually sit under their own
    # limits; only the sum crosses EMBED_LIMIT.
    total_over = mk_embed(desc="d" * 4000,
                          fields=[{"name": "n1", "value": "a" * 1000},
                                  {"name": "n2", "value": "b" * 1000}])
    problems = dr.check_post(total_over)
    computed_total = (len(total_over["title"]) + len(total_over["description"])
                      + len(total_over["footer"]["text"])
                      + sum(len(f["name"]) + len(f["value"])
                            for f in total_over["fields"]))
    check("an embed total over EMBED_LIMIT is reported, and only that "
          "limit, even though every individual piece is within its own",
          problems == [f"embed total {computed_total} > {dr.EMBED_LIMIT}"],
          str(problems))

    # THE FENCE ASYMMETRY: the monospace arm only inspects a field whose
    # value STARTS WITH a fence. The identical wide line needs a fixture on
    # both sides, or the branch that skips non-fenced fields is untested.
    wide_line = "x" * (dr.MONO_WIDTH + 1)
    fenced = mk_embed(fields=[{"name": "n",
                               "value": "```\n" + wide_line + "\n```"}])
    problems = dr.check_post(fenced)
    check("a line over MONO_WIDTH inside a fenced field is reported, and "
          "only that limit",
          problems == [f"monospace line {len(wide_line)} > {dr.MONO_WIDTH}: "
                       f"{wide_line!r}"],
          str(problems))

    unfenced = mk_embed(fields=[{"name": "n", "value": wide_line}])
    check("the identical wide line OUTSIDE a fence is not a monospace "
          "problem -- the arm only inspects fields whose value starts "
          "with a fence",
          dr.check_post(unfenced) == [], str(dr.check_post(unfenced)))

    exact_line = "x" * dr.MONO_WIDTH
    at_ceiling = mk_embed(fields=[{"name": "n",
                                   "value": "```\n" + exact_line + "\n```"}])
    check("a monospace line exactly at MONO_WIDTH is not a problem -- the "
          "check is a ceiling (>), not an exclusive bound",
          dr.check_post(at_ceiling) == [], str(dr.check_post(at_ceiling)))

    print("\nMONO_TABLE")
    # mono_table's own claim is that every line it produces fits MONO_WIDTH.
    # Exercised over a realistic-shaped record: five real-length tickers,
    # both marks (hi/lo), both reasons for the tilde (cross_untestable and
    # short_window), a missing volume verdict (volx -> "n/a"), and a company
    # with no return figure at all (dropped from the table, not blanked).
    mt_record = {
        "roster": ["MARA", "CLSK", "BKKT", "NUAI", "WYFI"],
        "verdicts": {
            "MARA": {
                "price": verdict(wd.ROUTINE,
                                 detail={"week_return_pct": -87.3,
                                         "close": 12.34}),
                "volume": verdict(wd.ROUTINE, detail={"peak_multiple": 42.7}),
                "crossings": verdict(wd.ROUTINE, detail={"new_lows": True}),
            },
            "CLSK": {
                "price": verdict(wd.ROUTINE,
                                 detail={"week_return_pct": 156.2,
                                         "close": 5.0}),
                "volume": verdict(wd.ROUTINE, detail={"peak_multiple": 3.1}),
                "crossings": verdict(wd.ROUTINE,
                                     detail={"new_highs": True,
                                             "short_window": True}),
            },
            "BKKT": {
                "price": verdict(wd.ROUTINE,
                                 detail={"week_return_pct": 0.4,
                                         "close": 3.0}),
                # no volume verdict at all -- volx must read as "n/a"
                "crossings": verdict(wd.NOT_TESTABLE),
            },
            "NUAI": {},  # no price verdict -- ret is None
            "WYFI": {
                "price": verdict(wd.ROUTINE,
                                 detail={"week_return_pct": -3.2,
                                         "close": 1.11}),
                "volume": verdict(wd.ROUTINE, detail={"peak_multiple": 1.0}),
            },
        },
    }
    mt_table = dr.mono_table(mt_record)
    mt_widths = [len(line) for line in mt_table]
    check("every line mono_table produces -- header, rule and data rows "
          "alike -- fits the monospace ceiling",
          max(mt_widths) <= dr.MONO_WIDTH,
          f"widths={mt_widths} table={mt_table!r}")

    print("\nWEEK_TITLE")
    same_month = {"monday": "2026-07-27", "friday": "2026-07-31"}
    check("same calendar month: one month name, one year, day range joined "
          "by a dash with no surrounding spaces",
          dr.week_title(same_month) == "27–31 Jul 2026",
          dr.week_title(same_month))

    cross_month = {"monday": "2026-07-29", "friday": "2026-08-02"}
    check("crossing a calendar month: each end names its own month",
          dr.week_title(cross_month) == "29 Jul – 2 Aug 2026",
          dr.week_title(cross_month))

    print("\nWEEK_URL")
    url_record = {"week": "2026-W32"}
    check("week_url appends '<week>.md' to the committed blob path",
          dr.week_url(url_record) == f"{dr.REPO_BLOB}/2026-W32.md",
          dr.week_url(url_record))

    print("\nALREADY_PRODUCED -- THE WHOLE NO-STATE-FILE DESIGN")
    # The file for week N IS the record that week N was produced. One line,
    # checked from both directions, plus the cases that would silently break
    # the design if this drifted: a different week's file present, only the
    # JSON sibling present, and a directory that does not exist at all.
    with tempfile.TemporaryDirectory() as tmp:
        check("false when the directory exists but the week's file does "
              "not",
              dr.already_produced(tmp, "2026-W32") is False)
        with open(os.path.join(tmp, "2026-W32.md"), "w") as fh:
            fh.write("placeholder")
        check("true once <week>.md exists in that directory",
              dr.already_produced(tmp, "2026-W32") is True)
        check("false for a different week, even in the same non-empty "
              "directory",
              dr.already_produced(tmp, "2026-W31") is False)

    with tempfile.TemporaryDirectory() as tmp2:
        with open(os.path.join(tmp2, "2026-W32.json"), "w") as fh:
            fh.write("{}")
        check("the JSON record alone does not count -- only the markdown "
              "file is the produced record",
              dr.already_produced(tmp2, "2026-W32") is False)

    missing_dir = os.path.join(tempfile.gettempdir(), "no-such-digest-dir-xyz")
    check("a directory that does not exist at all is also false, not a "
          "raise",
          dr.already_produced(missing_dir, "2026-W32") is False)

    print("\nTHE FTD FETCH-DEPTH INCIDENT")
    # derive_ftd once took its baseline median over EVERY PRIOR PERIOD IN THE
    # FETCH rather than a fixed window, so the verdict for one week changed
    # depending on how much history the caller happened to pull: ABTC
    # converged in a three-week render (8 half-month periods fetched) and did
    # not in the ten-week backfill (11 periods) -- the same week, two
    # answers. It is now bounded to ftd_monitor.BASELINE_PERIODS (6).
    #
    # The check is the incident itself: call derive_ftd for the SAME week
    # with 8 periods of context and again with 11, and require the two
    # verdicts to be EQUAL TO EACH OTHER. Not a hard-coded verdict -- that
    # would pin today's arithmetic rather than the property under test,
    # which is independence from fetch depth.
    #
    # The extra periods in the deeper fetch must be OLDER than
    # BASELINE_PERIODS or the two calls would legitimately differ and the
    # check would be asserting the wrong thing. `common_prior` below is the
    # 6 most-recent prior periods, identical in both fetches; the "older"
    # periods sit further back. Demonstrated: with the bound removed, the
    # median itself can still land unchanged (it is a robust statistic and
    # a minority of outliers does not move it) but the PERIOD COUNT read
    # into `baseline_periods` and quoted in `basis` ("N-period median")
    # does not, and that alone is enough to make the same week's verdict
    # text disagree between the two fetches -- which is what the check
    # below actually catches.
    ftd_target = "202606b"                 # publishes the week of 2026-07-15
    ftd_week_monday = date(2026, 7, 13)
    ftd_sessions = wd.week_sessions(ftd_week_monday)
    ftd_contributor = next(c for c in wd.CONTRIBUTORS if c["key"] == "ftd")

    common_prior = ["202606a", "202605b", "202605a",
                     "202604b", "202604a", "202603b"]         # the 6 in-window
    older_shallow = ["202603a"]                                # +1 -> 8 total
    older_deep = ["202603a", "202602b", "202602a", "202601b"]  # +4 -> 11 total

    def ftd_fixture(older):
        d = {ftd_target: {"ABTC": {"peak": 200000.0, "days": 6}}}
        for p in common_prior:
            d[p] = {"ABTC": {"peak": 50000.0, "days": 3}}
        for p in older:
            d[p] = {"ABTC": {"peak": 5000000.0, "days": 10}}
        return d

    shallow_src = wd.Source("ftd")
    shallow_src.data = ftd_fixture(older_shallow)
    deep_src = wd.Source("ftd")
    deep_src.data = ftd_fixture(older_deep)

    check("fixture sanity: the shallow fetch carries 8 half-month periods",
          len(shallow_src.data) == 8, sorted(shallow_src.data))
    check("fixture sanity: the deep fetch carries 11 half-month periods",
          len(deep_src.data) == 11, sorted(deep_src.data))
    check("fixture sanity: the 3 extra periods in the deep fetch are all "
          "older than every period in the shallow fetch, so they sit "
          "outside a 6-period bound in both cases",
          max(older_deep) < min(common_prior),
          f"older_deep={older_deep} common_prior={common_prior}")

    shallow_verdict = wd.derive_ftd(ftd_contributor, {"ftd": shallow_src},
                                     ftd_week_monday, ftd_sessions)["ABTC"]
    deep_verdict = wd.derive_ftd(ftd_contributor, {"ftd": deep_src},
                                  ftd_week_monday, ftd_sessions)["ABTC"]

    check("both fetches actually resolve the same target period -- "
          "otherwise an equal verdict would prove nothing",
          shallow_verdict["detail"].get("period") == ftd_target
          == deep_verdict["detail"].get("period"),
          f"{shallow_verdict['detail'].get('period')} vs "
          f"{deep_verdict['detail'].get('period')}")
    check("the baseline actually used is bounded to BASELINE_PERIODS in "
          "both cases, not the full prior history each fetch happened to "
          "carry",
          shallow_verdict["detail"].get("baseline_periods")
          == wd.ftd_monitor.BASELINE_PERIODS
          == deep_verdict["detail"].get("baseline_periods"),
          f"shallow={shallow_verdict['detail'].get('baseline_periods')} "
          f"deep={deep_verdict['detail'].get('baseline_periods')}")

    check("THE INCIDENT: the SAME week's verdict is identical whether the "
          "fetch pulled 8 periods of context or 11 -- level, figure and "
          "basis all agree",
          (shallow_verdict["level"], shallow_verdict["figure"],
           shallow_verdict["basis"])
          == (deep_verdict["level"], deep_verdict["figure"],
              deep_verdict["basis"]),
          f"shallow={shallow_verdict!r}\ndeep={deep_verdict!r}")

    print("\nTHE DETAIL-KEY NAMESPACE")
    # `baseline_median` once meant a volume median to one contributor and a
    # median of half-month fail peaks to another. digest_render.md_detail is
    # where that bit: for each NOTABLE verdict it scans a FIXED set of
    # detail-field names with d.get(...), NOT scoped to which contributor
    # produced `d` -- so if two contributors' derive_* functions emit the
    # same field name, the renderer cannot tell whose number it is holding.
    #
    # The set of field names below is read out of md_detail's own source,
    # never typed by hand. It is the set of BRANCH GUARD keys -- the names
    # md_detail tests with `if d.get(...)` to decide whether to emit a line --
    # and NOT every name it reads: it also reads keys by subscript inside
    # those branches, and those are scoped by the guard that admitted them.
    # The guard is where a collision does its damage, because it is what
    # decides whose dict is being read at all.
    #
    # WHY DOUBLE QUOTES ONLY, WHICH LOOKS LIKE A BUG AND IS NOT. In
    # md_detail every branch guard is written `if d.get("x")`, and every read
    # INSIDE a branch is written `d.get('x')` -- single quotes, forced by the
    # enclosing double-quoted f-string. The quote style therefore separates
    # guards from reads exactly, and it is the guards that matter: a guard
    # decides whose dict is being read at all, while a read inside one is
    # already scoped by the guard that admitted it.
    #
    # MEASURED: widening this to accept both quote styles makes the check
    # FAIL against correct code, on `baseline_sessions` (volume and
    # short_volume) and `sd_multiple` (price and short_volume) -- both read
    # only inside f-strings, in branches a guard has already scoped. So the
    # obvious "fix" here is a regression, and the next reader is owed that
    # rather than left to discover it. The set of contributors is
    # wd.CONTRIBUTORS, never a hand-typed name list, so a newly added
    # contributor is picked up too.
    # Ownership of a field is decided by literally searching each
    # contributor's OWN derive_* source for that field as a dict key -- what
    # the function actually emits, not what a comment claims it emits.
    #
    # NOTE ON SCOPE: several detail keys ARE shared across contributors
    # today (e.g. "count" between comment_letters and holders, or
    # "baseline_sessions" between short_volume and volume) and the module's
    # own backfill diagnostic says so is fine -- "shared is fine where the
    # quantity is the same". Those keys are never read back out of a detail
    # dict by name anywhere in digest_render.py, so no renderer branch can
    # ever attribute one contributor's figure to another under one of them.
    # This check is therefore scoped to exactly the keys md_detail DOES read
    # by name -- the set where a collision is the baseline_median failure
    # mode, not a merely coincidental name.
    renderer_src = inspect.getsource(dr.md_detail)
    renderer_keys = sorted(set(re.findall(r'd\.get\("([a-zA-Z_]+)"\)',
                                          renderer_src)))
    check("sanity: md_detail's own field scan was actually found in its "
          "source and is not accidentally empty",
          len(renderer_keys) >= 5, renderer_keys)
    check("sanity: the renderer-scanned keys include the two ends of the "
          "actual incident",
          {"baseline_median", "baseline_volume_median"} <= set(renderer_keys),
          renderer_keys)

    def key_owners(key):
        owners = set()
        for c in wd.CONTRIBUTORS:
            if f'"{key}"' in inspect.getsource(c["derive"]):
                owners.add(c["key"])
        return owners

    check("THE INCIDENT ITSELF, as a positive control: 'baseline_median' "
          "is claimed by ftd and only ftd",
          key_owners("baseline_median") == {"ftd"}, key_owners("baseline_median"))
    check("its fix: 'baseline_volume_median' is claimed by volume and "
          "only volume -- the rename that ended the collision",
          key_owners("baseline_volume_median") == {"volume"},
          key_owners("baseline_volume_median"))

    key_collisions = {k: key_owners(k) for k in renderer_keys
                      if len(key_owners(k)) > 1}
    check("no two contributors' derive_* functions claim the same "
          "renderer-scanned detail key",
          key_collisions == {}, str(key_collisions))

    print("\nCONTRIBUTOR RULES -- PRICE, VOLUME, CROSSINGS, FILINGS, LETTERS")
    # Three arms each: firing, not-firing, no-data. Not five -- ten similar
    # functions tested five ways each is padding, and padding is where checks
    # that cannot fail come from (this repo's press_monitor suite the same
    # week).
    #
    # THE NO-DATA ARM AND THE NOT-FIRING ARM ARE DIFFERENT STATES and get
    # separate fixtures throughout: no-data means the ticker's own entry is
    # missing from the source entirely (mirrors "not fetched" / "never
    # returned a row for this company"); not-firing means the source
    # answered for this ticker -- there is a real, sufficient series -- and
    # the rule looked and declined to fire. Collapsing them into one empty
    # fixture would prove nothing about a rule that runs and stays quiet.
    #
    # These five derive_* functions loop over the real wd.TICKERS (the
    # roster), not over a roster passed by the caller, so the fixtures below
    # key their data by an actual roster ticker rather than an invented one.
    price_c = next(c for c in wd.CONTRIBUTORS if c["key"] == "price")
    volume_c = next(c for c in wd.CONTRIBUTORS if c["key"] == "volume")
    crossings_c = next(c for c in wd.CONTRIBUTORS if c["key"] == "crossings")
    filings_c = next(c for c in wd.CONTRIBUTORS if c["key"] == "filings")
    letters_c = next(c for c in wd.CONTRIBUTORS
                     if c["key"] == "comment_letters")

    cr_monday = date(2026, 7, 27)
    cr_sessions = wd.week_sessions(cr_monday)
    T = wd.TICKERS[0]

    print("\nDERIVE_PRICE")
    # Week return against the ticker's own trailing 12-week return dispersion
    # (PRICE_SD_MULTIPLE = 2.0 x PRICE_BASELINE_WEEKS-week SD). 13 trailing
    # Friday closes alternating 10.10/10.00 give a small, non-zero baseline
    # SD (~1pt); the target week's close is what moves between the firing
    # and not-firing fixtures.
    price_baseline = [(cr_monday - timedelta(days=7 * i) + timedelta(days=4),
                       10.10 if i % 2 else 10.00) for i in range(13, 0, -1)]

    firing_price_rows = [(d, px, 1000.0) for d, px in price_baseline]
    firing_price_rows.append((cr_sessions[-1], 20.00, 1000.0))
    firing_price_src = wd.Source("bars")
    firing_price_src.data = {T: firing_price_rows}
    firing_price = wd.derive_price(price_c, {"bars": firing_price_src},
                                   cr_monday, cr_sessions)[T]
    check("a week return far past the trailing weekly-SD multiple is "
          "NOTABLE",
          firing_price["level"] == wd.NOTABLE
          and firing_price["figure"] == "+98.0%",
          firing_price)

    routine_price_rows = [(d, px, 1000.0) for d, px in price_baseline]
    routine_price_rows.append((cr_sessions[-1], 10.05, 1000.0))
    routine_price_src = wd.Source("bars")
    routine_price_src.data = {T: routine_price_rows}
    routine_price = wd.derive_price(price_c, {"bars": routine_price_src},
                                    cr_monday, cr_sessions)[T]
    check("the identical baseline with an ordinary week return is ROUTINE, "
          "not NOTABLE -- fetched, computed, did not cross the threshold",
          routine_price["level"] == wd.ROUTINE
          and routine_price["figure"] == "-0.5%",
          routine_price)

    nodata_price_src = wd.Source("bars")
    nodata_price_src.data = {}
    nodata_price = wd.derive_price(price_c, {"bars": nodata_price_src},
                                   cr_monday, cr_sessions)[T]
    check("a ticker with no bars at all is NOT_TESTABLE with basis 'no "
          "bars' -- the source never returned a row for this company, "
          "distinct from the routine fixture which is fully populated",
          nodata_price["level"] == wd.NOT_TESTABLE
          and nodata_price["basis"] == "no bars",
          nodata_price)

    print("\nDERIVE_VOLUME")
    # Daily volume against a 30-session trailing MEDIAN, VOLUME_DAYS (3) of
    # 5 sessions at >= VOLUME_MULTIPLE (2.0x) required to fire.
    vol_prior = [(cr_monday - timedelta(days=i), 5.0, 1000.0)
                for i in range(1, 45) if (cr_monday - timedelta(days=i)).weekday() < 5][:30]

    firing_vol_week = [(cr_sessions[0], 5.0, 3000.0), (cr_sessions[1], 5.0, 3000.0),
                       (cr_sessions[2], 5.0, 3000.0), (cr_sessions[3], 5.0, 500.0),
                       (cr_sessions[4], 5.0, 500.0)]
    firing_vol_src = wd.Source("bars")
    firing_vol_src.data = {T: vol_prior + firing_vol_week}
    firing_vol = wd.derive_volume(volume_c, {"bars": firing_vol_src},
                                  cr_monday, cr_sessions)[T]
    check("3 of 5 sessions at >= 2x the trailing 30-session median volume "
          "is NOTABLE",
          firing_vol["level"] == wd.NOTABLE and firing_vol["figure"] == "3.0x peak",
          firing_vol)

    routine_vol_week = [(d, 5.0, 1000.0) for d in cr_sessions]
    routine_vol_src = wd.Source("bars")
    routine_vol_src.data = {T: vol_prior + routine_vol_week}
    routine_vol = wd.derive_volume(volume_c, {"bars": routine_vol_src},
                                   cr_monday, cr_sessions)[T]
    check("the identical baseline with every session at 1x the median is "
          "ROUTINE -- fetched, computed, never crossed 2x",
          routine_vol["level"] == wd.ROUTINE and routine_vol["figure"] == "1.0x peak",
          routine_vol)

    nodata_vol_src = wd.Source("bars")
    nodata_vol_src.data = {}
    nodata_vol = wd.derive_volume(volume_c, {"bars": nodata_vol_src},
                                  cr_monday, cr_sessions)[T]
    check("a ticker with no bars at all is NOT_TESTABLE with basis "
          "'baseline 0/30 sessions' -- no series to build a median from, "
          "distinct from the routine fixture's full 30-session baseline",
          nodata_vol["level"] == wd.NOT_TESTABLE
          and nodata_vol["basis"] == "baseline 0/30 sessions",
          nodata_vol)

    print("\nDERIVE_CROSSINGS")
    # A 52-week high or low touched during the week, against a trailing
    # window of at least CROSSINGS_MIN_BARS (60) prior bars.
    cx_before_days = [cr_monday - timedelta(days=i) for i in range(1, 130)
                      if (cr_monday - timedelta(days=i)).weekday() < 5][:60]

    firing_cx_before = [(d, 10.0, 1.0) for d in cx_before_days]
    firing_cx_src = wd.Source("bars")
    firing_cx_src.data = {T: firing_cx_before
                          + [(cr_sessions[0], 10.0, 1.0),
                             (cr_sessions[1], 15.0, 1.0)]}
    firing_cx = wd.derive_crossings(crossings_c, {"bars": firing_cx_src},
                                    cr_monday, cr_sessions)[T]
    check("a close above the trailing 60-bar window's high is NOTABLE as "
          "a 52-week high",
          firing_cx["level"] == wd.NOTABLE
          and firing_cx["figure"] == f"52-week high 15.00 on {cr_sessions[1]}",
          firing_cx)

    routine_cx_before = [(d, 10.0 if i % 2 == 0 else 12.0, 1.0)
                         for i, d in enumerate(cx_before_days)]
    routine_cx_src = wd.Source("bars")
    routine_cx_src.data = {T: routine_cx_before + [(cr_sessions[0], 11.0, 1.0)]}
    routine_cx = wd.derive_crossings(crossings_c, {"bars": routine_cx_src},
                                     cr_monday, cr_sessions)[T]
    check("the identical window with a week close inside the trailing "
          "high/low range is ROUTINE -- fetched, computed, touched "
          "neither bound",
          routine_cx["level"] == wd.ROUTINE, routine_cx)

    nodata_cx_src = wd.Source("bars")
    nodata_cx_src.data = {}
    nodata_cx = wd.derive_crossings(crossings_c, {"bars": nodata_cx_src},
                                    cr_monday, cr_sessions)[T]
    check("a ticker with no bars at all is NOT_TESTABLE with basis "
          "'0/60 bars minimum for a 52-week window' -- no window to "
          "compare against, distinct from the routine fixture's full "
          "60-bar window",
          nodata_cx["level"] == wd.NOT_TESTABLE
          and nodata_cx["basis"] == "0/60 bars minimum for a 52-week window",
          nodata_cx)

    print("\nDERIVE_FILINGS")
    # Material filings (FILING_CLASSES in MATERIAL_CLASSES, or 8-K item codes
    # in ALWAYS_POST_ITEMS) filed inside the week.
    def mkfiling(form, filed):
        return {"form": form, "filed": filed, "accepted": "", "items": "",
                "description": "", "accession": "acc-1",
                "url": "https://example.sec.gov/x"}

    fl_in_week = cr_sessions[2].isoformat()

    firing_fl_src = wd.Source("filings")
    firing_fl_src.data = {T: [mkfiling("424B3", fl_in_week)]}
    firing_fl = wd.derive_filings(filings_c, {"filings": firing_fl_src},
                                  cr_monday, cr_sessions)[T]
    check("a capital-class form (424B3) filed in the week is NOTABLE",
          firing_fl["level"] == wd.NOTABLE and firing_fl["figure"] == "1 capital",
          firing_fl)

    routine_fl_src = wd.Source("filings")
    routine_fl_src.data = {T: []}
    routine_fl = wd.derive_filings(filings_c, {"filings": routine_fl_src},
                                   cr_monday, cr_sessions)[T]
    check("a ticker that was fetched and filed nothing this week is "
          "ROUTINE, not the same state as an unfetched ticker",
          routine_fl["level"] == wd.ROUTINE and routine_fl["figure"] == "0 filings",
          routine_fl)

    nodata_fl_src = wd.Source("filings")
    nodata_fl_src.data = {}
    nodata_fl = wd.derive_filings(filings_c, {"filings": nodata_fl_src},
                                  cr_monday, cr_sessions)[T]
    check("a ticker absent from the filings source entirely is "
          "SOURCE_FAILED, not ROUTINE -- the EDGAR fetch never returned a "
          "row for this company at all",
          nodata_fl["level"] == wd.SOURCE_FAILED
          and nodata_fl["basis"] == "EDGAR submissions fetch did not return",
          nodata_fl)

    print("\nDERIVE_LETTERS")
    # SEC review correspondence (LETTER_FORMS: UPLOAD, CORRESP) released
    # inside the week.
    firing_lt_src = wd.Source("filings")
    firing_lt_src.data = {T: [mkfiling("UPLOAD", fl_in_week)]}
    firing_lt = wd.derive_letters(letters_c, {"filings": firing_lt_src},
                                  cr_monday, cr_sessions)[T]
    check("an UPLOAD (SEC staff letter) released in the week is NOTABLE",
          firing_lt["level"] == wd.NOTABLE
          and firing_lt["figure"] == f"SEC staff letter {fl_in_week}",
          firing_lt)

    routine_lt_src = wd.Source("filings")
    routine_lt_src.data = {T: []}
    routine_lt = wd.derive_letters(letters_c, {"filings": routine_lt_src},
                                   cr_monday, cr_sessions)[T]
    check("a ticker that was fetched and had no correspondence this week "
          "is ROUTINE with count 0",
          routine_lt["level"] == wd.ROUTINE
          and routine_lt["detail"]["count"] == 0,
          routine_lt)

    nodata_lt_src = wd.Source("filings")
    nodata_lt_src.data = {}
    nodata_lt = wd.derive_letters(letters_c, {"filings": nodata_lt_src},
                                  cr_monday, cr_sessions)[T]
    check("a ticker absent from the filings source entirely is "
          "SOURCE_FAILED, not ROUTINE",
          nodata_lt["level"] == wd.SOURCE_FAILED
          and nodata_lt["basis"] == "EDGAR submissions fetch failed",
          nodata_lt)

    print("\nCONTRIBUTOR RULES -- THRESHOLD, DILUTION, HOLDERS, SHORT INTEREST")
    # Same three arms as the block above: firing, not-firing, no-data -- ten
    # similar functions tested five ways each is padding, and padding is
    # where checks that cannot fail come from.
    threshold_c = next(c for c in wd.CONTRIBUTORS if c["key"] == "threshold_list")
    dilution_c = next(c for c in wd.CONTRIBUTORS if c["key"] == "dilution")
    holders_c = next(c for c in wd.CONTRIBUTORS if c["key"] == "holders")
    short_interest_c = next(c for c in wd.CONTRIBUTORS
                            if c["key"] == "short_interest")

    print("\nDERIVE_THRESHOLD")
    # Reg SHO threshold list, persistence-eligible (cadence DAILY). The
    # no-data arm here is shaped differently from the other three: it is not
    # "this ticker's own row is missing" but "no threshold file parsed for
    # the whole week at all" -- fetch_threshold's own way of saying the
    # parse failed for every settlement day, not just for one company.
    th_days = [d.isoformat() for d in cr_sessions]

    firing_th_days = {d: {} for d in th_days}
    firing_th_days[th_days[0]] = {T: "0.50"}
    firing_th_days[th_days[2]] = {T: "0.50"}
    firing_th_src = wd.Source("threshold")
    firing_th_src.data = {"by_day": firing_th_days,
                          "flagged_totals": {d: 1 for d in th_days}}
    firing_th = wd.derive_threshold(threshold_c, {"threshold": firing_th_src},
                                    cr_monday, cr_sessions)[T]
    check("listed on 2 of 5 settlement days this week is NOTABLE, carrying "
          "a persistence claim",
          firing_th["level"] == wd.NOTABLE
          and firing_th["figure"]
          == "on the threshold list 2 of 5 settlement days"
          and firing_th["persistence"]
          == {"hits": 2, "of": 5, "direction": "listed"},
          firing_th)

    routine_th_days = {d: {} for d in th_days}
    routine_th_src = wd.Source("threshold")
    routine_th_src.data = {"by_day": routine_th_days,
                           "flagged_totals": {d: 1 for d in th_days}}
    routine_th = wd.derive_threshold(threshold_c, {"threshold": routine_th_src},
                                     cr_monday, cr_sessions)[T]
    check("5 files parsed and this ticker never listed is ROUTINE -- "
          "fetched, computed, never crossed onto the list; not the same "
          "state as no files parsed at all",
          routine_th["level"] == wd.ROUTINE
          and routine_th["detail"]
          == {"files_read": 5, "days_listed": 0, "dates": []},
          routine_th)

    nodata_th_src = wd.Source("threshold")
    nodata_th_src.data = {"by_day": {}, "flagged_totals": {}}
    nodata_th = wd.derive_threshold(threshold_c, {"threshold": nodata_th_src},
                                    cr_monday, cr_sessions)[T]
    check("no threshold file parsed for any settlement day this week is "
          "SOURCE_FAILED for every ticker, not ROUTINE",
          nodata_th["level"] == wd.SOURCE_FAILED
          and nodata_th["basis"] == "no threshold file parsed for this week",
          nodata_th)

    print("\nDERIVE_DILUTION")
    # THIS FIRING ARM HAS NEVER EXECUTED AGAINST REAL DATA. Measured across
    # the ten-week backfill (190 ticker-weeks), only 3 ticker-weeks had a
    # new XBRL share-count observation in the week at all, and the largest
    # step among those three was HUT at +9.50% -- half a point under
    # NOTABLE_STEP_PCT (10.0%). A fixture is the only way this branch has
    # ever run, which is the argument for testing it at all, not a reason to
    # skip it -- the same argument press_monitor.py records above
    # carries_press_release's untested no-items branch.
    dl_prior_date = (cr_monday - timedelta(days=30)).isoformat()

    firing_dl_src = wd.Source("dilution")
    firing_dl_src.data = {T: {"series": [
        (dl_prior_date, 1000000, "10-Q"),
        (cr_sessions[2].isoformat(), 1250000, "10-Q")],
        "concept": "CommonStockSharesOutstanding"}}
    firing_dl = wd.derive_dilution(dilution_c, {"dilution": firing_dl_src},
                                   cr_monday, cr_sessions)[T]
    check("a new share count stepping +25% against the 10% threshold is "
          "NOTABLE (fabricated -- see the comment above; real data has "
          "never crossed this line)",
          firing_dl["level"] == wd.NOTABLE
          and firing_dl["figure"] == "+25.0% to 1,250,000 shares",
          firing_dl)

    routine_dl_src = wd.Source("dilution")
    routine_dl_src.data = {T: {"series": [
        (dl_prior_date, 1000000, "10-Q"),
        (cr_sessions[2].isoformat(), 1020000, "10-Q")],
        "concept": "CommonStockSharesOutstanding"}}
    routine_dl = wd.derive_dilution(dilution_c, {"dilution": routine_dl_src},
                                    cr_monday, cr_sessions)[T]
    check("the identical baseline with a +2% step is ROUTINE -- fetched, "
          "computed, did not cross the threshold",
          routine_dl["level"] == wd.ROUTINE and routine_dl["figure"] == "+2.0%",
          routine_dl)

    nodata_dl_src = wd.Source("dilution")
    nodata_dl_src.data = {}
    nodata_dl = wd.derive_dilution(dilution_c, {"dilution": nodata_dl_src},
                                   cr_monday, cr_sessions)[T]
    check("a ticker absent from the dilution source entirely is "
          "SOURCE_FAILED, not ROUTINE -- the XBRL fetch never returned a "
          "row for this company",
          nodata_dl["level"] == wd.SOURCE_FAILED
          and nodata_dl["basis"] == "XBRL fetch did not return",
          nodata_dl)

    print("\nDERIVE_HOLDERS")
    # A >5% holder disclosure (SC/SCHEDULE 13D or 13G) filed inside the
    # week. Cadence EVENT, so no persistence claim is possible here.
    firing_hd_src = wd.Source("filings")
    firing_hd_src.data = {T: [mkfiling("SCHEDULE 13D", fl_in_week)]}
    firing_hd = wd.derive_holders(holders_c, {"filings": firing_hd_src},
                                  cr_monday, cr_sessions)[T]
    check("an initial SCHEDULE 13D filed in the week is NOTABLE",
          firing_hd["level"] == wd.NOTABLE
          and firing_hd["figure"] == "1 >5% disclosure, 1 initial",
          firing_hd)

    routine_hd_src = wd.Source("filings")
    routine_hd_src.data = {T: []}
    routine_hd = wd.derive_holders(holders_c, {"filings": routine_hd_src},
                                   cr_monday, cr_sessions)[T]
    check("a ticker that was fetched and filed no >5% disclosure this week "
          "is ROUTINE, not the same state as an unfetched ticker",
          routine_hd["level"] == wd.ROUTINE
          and routine_hd["detail"]["count"] == 0,
          routine_hd)

    nodata_hd_src = wd.Source("filings")
    nodata_hd_src.data = {}
    nodata_hd = wd.derive_holders(holders_c, {"filings": nodata_hd_src},
                                  cr_monday, cr_sessions)[T]
    check("holders: a ticker absent from the filings source entirely is "
          "SOURCE_FAILED, not ROUTINE",
          nodata_hd["level"] == wd.SOURCE_FAILED
          and nodata_hd["basis"] == "EDGAR submissions fetch failed",
          nodata_hd)

    print("\nDERIVE_SHORT_INTEREST")
    # UNLIKE THE OTHER THREE, THIS FUNCTION HAS NO PER-TICKER SOURCE_FAILED
    # BRANCH AT ALL. "the whole source never fetched" and "fetched, but no
    # settlement published this week" both fall through the same
    # `if not fresh` branch to ROUTINE -- consistent with this repo's rule
    # that absence of data is a measurement, not a gap (see derive_ftd's
    # zero-fails case), and with the twice-monthly cadence, where most
    # weeks legitimately have nothing new to report. The no-data fixture
    # below still gets its own setup rather than reusing the not-firing
    # one, so a mutation breaking only one of the two paths is still caught.
    si_settlement = "2026-07-15"
    si_prior = "2026-06-15"          # publishes a different week (2026-06-22)
    si_monday = wd.publication_week(si_settlement)
    si_sessions = wd.week_sessions(si_monday)

    firing_si_src = wd.Source("short_interest")
    firing_si_src.data = {
        si_prior: {T: {"current": 1000000.0, "revised": False,
                       "split": False, "days_to_cover": 1.0,
                       "change_pct": None}},
        si_settlement: {T: {"current": 1300000.0, "revised": False,
                            "split": False, "days_to_cover": 1.0,
                            "change_pct": None}},
    }
    firing_si = wd.derive_short_interest(
        short_interest_c, {"short_interest": firing_si_src},
        si_monday, si_sessions)[T]
    check("a settlement published this week at +30% against the prior "
          "settlement is NOTABLE",
          firing_si["level"] == wd.NOTABLE
          and firing_si["figure"] == "+30% to 1,300,000 shares",
          firing_si)

    routine_si_src = wd.Source("short_interest")
    routine_si_src.data = {
        si_prior: {T: {"current": 1000000.0, "revised": False,
                       "split": False, "days_to_cover": 1.0,
                       "change_pct": None}},
        si_settlement: {T: {"current": 1050000.0, "revised": False,
                            "split": False, "days_to_cover": 1.0,
                            "change_pct": None}},
    }
    routine_si = wd.derive_short_interest(
        short_interest_c, {"short_interest": routine_si_src},
        si_monday, si_sessions)[T]
    check("the identical settlement with a +5% change is ROUTINE -- "
          "fetched, computed, did not cross the 15% threshold",
          routine_si["level"] == wd.ROUTINE
          and routine_si["detail"]["change_pct"] == 5.0,
          routine_si)

    nodata_si_src = wd.Source("short_interest")
    nodata_si_src.data = None
    nodata_si = wd.derive_short_interest(
        short_interest_c, {"short_interest": nodata_si_src},
        si_monday, si_sessions)[T]
    check("no settlement in the source at all is ROUTINE with basis 'no "
          "settlement published this week' -- its own fixture, distinct "
          "from the not-firing case above even though both are ROUTINE",
          nodata_si["level"] == wd.ROUTINE
          and nodata_si["basis"] == "no settlement published this week",
          nodata_si)

    print("\nFORM_IN")
    # form_in(form, prefixes): EDGAR-style prefix match, any() over the
    # prefix list. The no-data arm here is an empty prefix list -- there is
    # nothing to test against, which is a different state from a non-empty
    # prefix list that simply does not match this form.
    check("a form matching one of several prefixes is True",
          wd.form_in("SCHEDULE 13D", ["SC 13D", "SCHEDULE 13D"]) is True)
    check("a form matching none of a real, non-empty prefix list is False",
          wd.form_in("10-K", ["SC 13D", "SCHEDULE 13D"]) is False)
    check("an empty prefix list is False -- no prefixes to test against, "
          "not the same state as a real list that failed to match",
          wd.form_in("10-K", []) is False)

    bad = sum(1 for r, _ in results if r == FAIL)
    print(f"\n{len(results) - bad}/{len(results)} checks passed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
