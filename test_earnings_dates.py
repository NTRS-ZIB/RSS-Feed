#!/usr/bin/env python3
"""Tests for earnings_dates. Standalone, stdlib only, EXCEPT the display-half
checks at the end, which import earnings_calendar to drive build_message.
That module only runs code on __main__, so importing it here is safe, but
the import chain pulls in requests — the one place this file is not
stdlib-only.

THE ONE THAT MATTERS: a results release is not an announcement. "Reports
Second Quarter 2026 Results" carries a date describing the period covered,
and reading it as a forthcoming report date posts a date already in the
past with no spread and no marker to soften it. That is the failure this
module exists to prevent, so it is tested from both directions: the
recognition stage must not match it, and the guard must reject it if
recognition ever does.
"""

import json
import sys
from datetime import date, timedelta
from pathlib import Path

import earnings_dates as ed
import earnings_calendar as ec

PASS, FAIL = "PASS", "FAIL"
results = []


def check(name, ok, detail=""):
    results.append((PASS if ok else FAIL, name))
    print(f"  [{PASS if ok else FAIL}] {name}" + (f" — {detail}" if detail else ""))


TODAY = date(2026, 8, 10)

ANNOUNCEMENTS = [
    "Big Digital Energy to Report Second Quarter 2026 Results on August 12, 2026",
    "Cipher Mining Schedules Third Quarter 2026 Earnings Call for November 4, 2026",
    "IREN to Announce Fiscal 2026 Full Year Results on Sept. 7, 2026",
]

NOT_ANNOUNCEMENTS = [
    "American Bitcoin Reports Second Quarter 2026 Results",
    "Bitdeer Announces $4.7 Billion, 16-Year AI/HPC Data Center Lease",
    "Soluna Announces Pricing of $3.507bn Notes Offering",
]


def main():
    # Imported here, not just at module level: a local name makes `ec` local
    # to this whole function under Python's scoping rules, so it must be
    # bound before any use in main() rather than beside the checks that
    # exercise it. A later task's tests reuse this name — keep it here.
    import earnings_calendar as ec

    print("RECOGNITION")
    for t in ANNOUNCEMENTS:
        check(f"matches: {t[:44]}", ed.looks_like_announcement(t))
    for t in NOT_ANNOUNCEMENTS:
        check(f"rejects: {t[:44]}", not ed.looks_like_announcement(t))

    print("\nDATE PARSING")
    check("full month name",
          ed.parse_date("... on August 12, 2026") == date(2026, 8, 12))
    check("abbreviated month with a full stop",
          ed.parse_date("... on Sept. 7, 2026") == date(2026, 9, 7))
    check("ordinal suffix",
          ed.parse_date("... on November 4th, 2026") == date(2026, 11, 4))
    check("a four-digit year is required",
          ed.parse_date("... to Report Results on August 12") is None,
          "a guessed year is a confident wrong answer")
    check("no date at all",
          ed.parse_date("Announces Date of Second Quarter Earnings Release")
          is None)

    print("\nTHE GUARD")
    when, reason = ed.extract(ANNOUNCEMENTS[0], TODAY)
    check("an announcement ahead of today is accepted",
          when == date(2026, 8, 12) and reason == "ok", f"{when} {reason}")
    when, reason = ed.extract(
        "Company to Report Second Quarter 2026 Results on July 20, 2026", TODAY)
    check("a date before today is rejected",
          when is None and reason == "past", f"{when} {reason}")
    when, reason = ed.extract(
        "Company to Report Second Quarter 2026 Results on August 10, 2026",
        TODAY)
    check("a date of today is accepted",
          when == TODAY and reason == "ok",
          "the calendar's own upcoming test is today <= expected")
    when, reason = ed.extract(NOT_ANNOUNCEMENTS[0], TODAY)
    check("a results release yields nothing",
          when is None and reason == "no-match", f"{when} {reason}")
    when, reason = ed.extract(
        "Announces Date of Second Quarter 2026 Earnings Release", TODAY)
    check("an announcement with no parsable date is counted separately",
          when is None and reason == "no-date", f"{when} {reason}")

    print("\nTHE STORE")
    import tempfile
    tmp = Path(tempfile.mkdtemp()) / "earnings_dates.json"

    companies, status = ed.load(tmp)
    check("a file that does not exist reports missing",
          companies == {} and status == "missing", status)

    ed.save({}, tmp)
    companies, status = ed.load(tmp)
    check("a file with no records reports empty, not missing",
          companies == {} and status == "empty", status)

    companies = {}
    wrote = ed.upsert(companies, "1218683", "BGDE", date(2026, 8, 12),
                      "uid-1", "title one", "2026-07-29T13:00:00+00:00")
    check("upsert writes", wrote and len(companies) == 1)
    check("the key is a zero-padded CIK",
          "0001218683" in companies, list(companies))

    wrote = ed.upsert(companies, "1218683", "BGDE", date(2026, 8, 14),
                      "uid-2", "title two", "2026-08-01T13:00:00+00:00")
    check("a later release overwrites",
          wrote and companies["0001218683"]["date"] == "2026-08-14")

    wrote = ed.upsert(companies, "1218683", "BGDE", date(2026, 8, 20),
                      "uid-3", "title three", "2026-07-01T13:00:00+00:00")
    check("an EARLIER release does not overwrite",
          not wrote and companies["0001218683"]["date"] == "2026-08-14",
          "a stale item resurfacing must not clobber a newer announcement")

    wrote = ed.upsert(companies, "1218683", "BGDE", date(2026, 9, 1),
                      "uid-4", "title four", None)
    check("a release with no timestamp does not overwrite",
          not wrote and companies["0001218683"]["date"] == "2026-08-14")

    ed.save(companies, tmp)
    reloaded, status = ed.load(tmp)
    check("a saved store round-trips", reloaded == companies and status == "ok")

    tmp.write_text("{not json", encoding="utf-8")
    companies, status = ed.load(tmp)
    check("unreadable is distinct from missing and empty",
          companies == {} and status == "unreadable", status)

    tmp.write_text(json.dumps({"schema": 99, "companies": {}}),
                   encoding="utf-8")
    companies, status = ed.load(tmp)
    check("a wrong schema is unreadable", status == "unreadable", status)

    print("\nTHE OVERLAY")

    def row(label, cik, period, expected, spread=6):
        return {"label": label, "cik": cik, "period": period,
                "expected": expected, "spread": spread, "kind": "10-Q",
                "degraded": False}

    store = {"0001218683": {"ticker": "BGDE", "date": "2026-08-12",
                            "source_uid": "u", "source_title": "t",
                            "source_published": "2026-07-29T13:00:00+00:00"}}

    rows = [row("BGDE", "0001218683", date(2026, 6, 30), date(2026, 8, 14))]
    rows, applied, notes = ed.apply(rows, store, date(2026, 8, 10))
    check("the announced date replaces the projection",
          applied == 1 and rows[0]["expected"] == date(2026, 8, 12))
    check("the replaced projection is kept for the log",
          rows[0]["projected"] == date(2026, 8, 14))
    check("the row is marked disclosed", rows[0].get("disclosed") is True)

    rows = [row("BGDE", "0001218683", date(2026, 6, 30), date(2026, 8, 14))]
    rows, applied, notes = ed.apply(rows, store, date(2026, 8, 20))
    check("a date that has passed STILL applies",
          applied == 1 and rows[0]["expected"] == date(2026, 8, 12),
          "this is what puts the row in Overdue")

    rows = [row("BGDE", "0001218683", date(2026, 9, 30), date(2026, 11, 13))]
    rows, applied, notes = ed.apply(rows, store, date(2026, 8, 20))
    check("once the company files, the stale entry stops applying",
          applied == 0 and rows[0]["expected"] == date(2026, 11, 13),
          "the disclosed date is before the new period end")

    rows = [row("MARA", "0001507605", date(2026, 6, 30), date(2026, 8, 14))]
    rows, applied, notes = ed.apply(rows, store, date(2026, 8, 10))
    check("a company with no stored date is untouched",
          applied == 0 and rows[0]["expected"] == date(2026, 8, 14))

    bad_store = {"0001218683": {"ticker": "BGDE", "date": "not a date"}}
    rows = [row("BGDE", "0001218683", date(2026, 6, 30), date(2026, 8, 14))]
    rows, applied, notes = ed.apply(rows, bad_store, date(2026, 8, 10))
    check("an unparseable stored date is skipped and noted",
          applied == 0 and any("not a date" in n for n in notes), notes)

    malformed_store = {"0001218683": "not a record"}
    rows = [row("BGDE", "0001218683", date(2026, 6, 30), date(2026, 8, 14))]
    rows, applied, notes = ed.apply(rows, malformed_store, date(2026, 8, 10))
    check("a non-dict stored record is skipped and noted, not raised",
          applied == 0 and rows[0]["expected"] == date(2026, 8, 14)
          and any("not a dict" in n for n in notes), notes)

    print("\nWHERE A STORED DATE CAME FROM")
    fresh = {}
    ed.upsert(fresh, "0001218683", "BGDE", date(2026, 9, 1), "u1", "t1",
              "2026-08-01T00:00:00+00:00")
    check("a date defaults to source 'title'",
          fresh["0001218683"]["source"] == "title",
          "every date stored before this change came from a headline")

    body = {}
    ed.upsert(body, "0001218683", "BGDE", date(2026, 9, 1), "u1", "t1",
              "2026-08-01T00:00:00+00:00", source="body")
    check("a body-derived date records source 'body'",
          body["0001218683"]["source"] == "body")

    # A record written before this change has no "source" key at all. Its
    # absence is not unknown provenance — it is a title, because that was
    # the only way a date could be stored.
    LEGACY = {"0001218683": {"ticker": "BGDE", "date": "2026-09-01",
                             "source_uid": "u", "source_title": "t",
                             "source_published": "2026-08-01T00:00:00+00:00"}}
    lrows = [row("BGDE", "0001218683", date(2026, 6, 30), date(2026, 9, 5))]
    lrows, lapplied, _ = ed.apply(lrows, LEGACY, date(2026, 8, 12))
    check("a legacy record with no source key applies", lapplied == 1)
    check("a legacy record reads as a title", lrows[0]["disclosed_source"] == "title",
          "absence of the key is a title, not an unknown")

    BODYSTORE = {"0001218683": {"ticker": "BGDE", "date": "2026-09-01",
                                "source_uid": "u", "source_title": "t",
                                "source_published": "2026-08-01T00:00:00+00:00",
                                "source": "body"}}
    brows = [row("BGDE", "0001218683", date(2026, 6, 30), date(2026, 9, 5))]
    brows, _, _ = ed.apply(brows, BODYSTORE, date(2026, 8, 12))
    check("a body record carries its provenance onto the row",
          brows[0]["disclosed_source"] == "body")
    check("provenance rides alongside disclosed, not instead of it",
          brows[0]["disclosed"] is True)

    print("\nYEAR FROM THE RELEASE DATE")
    check("year taken from the release",
          ed.parse_date("... Results on August 14th", date(2026, 7, 29))
          == date(2026, 8, 14))
    check("a four-digit year in the title still wins",
          ed.parse_date("... on August 12, 2026", date(2026, 7, 29))
          == date(2026, 8, 12))
    check("rolls to next year when the release is later in the year",
          ed.parse_date("... on January 5th", date(2026, 12, 20))
          == date(2027, 1, 5),
          "a company does not announce a forthcoming date in the past")
    check("without a release date it still refuses to guess",
          ed.parse_date("... Results on August 14th") is None)
    when, reason = ed.extract(
        "Digi Power X to Announce 2026 Q2 Financial Results and Provide "
        "Operations Update on August 14th", date(2026, 8, 1), date(2026, 7, 29))
    check("the real DGXX headline now extracts",
          when == date(2026, 8, 14) and reason == "ok", f"{when} {reason}")
    when, reason = ed.extract(
        "Company to Report Results on August 14th", date(2026, 8, 1))
    check("no release date still counts as a no-date miss",
          when is None and reason == "no-date", f"{when} {reason}")

    print("\nTHE DISPLAY HALF (build_message)")
    today = date.today()

    def calendar_row(label, expected, spread=6, disclosed=False,
                     degraded=False, source="title"):
        r = {"label": label, "cik": "0000000000",
             "period": date(2026, 6, 30), "expected": expected,
             "spread": spread, "kind": "10-Q", "degraded": degraded,
             "disclosed": disclosed}
        if disclosed:
            r["disclosed_source"] = source
        return r

    # (a) and (b): an announced row in the upcoming window shows the
    # announced date and the `!` marker, and its spread column is blank
    # rather than zero. 999 is a sentinel: if the spread ever leaked into
    # an announced row's display, this is what would show up.
    upcoming_date = today + timedelta(days=5)
    disclosed_row = calendar_row("TEST", upcoming_date, spread=999,
                                 disclosed=True)
    text = ec.build_message([disclosed_row])
    line = next(l for l in text.split("\n") if l.startswith("TEST"))
    check("an announced row shows the announced date and the ! marker",
          line.startswith(f"TEST! {upcoming_date:%a %d %b}"), line)
    check("an announced row's spread column is blank, not zero",
          "999d" not in line and line.endswith("    "), repr(line))

    # THE COLUMN IS LABELLED `+/-`, SO IT PRINTS HALF THE RANGE. It used to
    # print the range itself, which claimed a window twice as wide as anything
    # ever observed: a company whose lags spanned 33 days was published as
    # ±33d. `r["spread"]` is still the range, because that is what the marker
    # reads, and 31 is the value that separates the two: it is `~` on the
    # range and would not be if the marker read the halved figure.
    halved = calendar_row("HALF", upcoming_date, spread=33)
    line = next(l for l in ec.build_message([halved]).split("\n")
                if l.startswith("HALF"))
    check("the +/- column prints HALF the range", line.endswith(" 16d"),
          repr(line) + " - the range 33 would have printed 33d")
    check("and a 33-day range still carries the ~ marker",
          line.startswith("HALF~"), repr(line))

    boundary = calendar_row("EDGE", upcoming_date, spread=31)
    line = next(l for l in ec.build_message([boundary]).split("\n")
                if l.startswith("EDGE"))
    check("a range of 31 is still ~, though half of it is only 15",
          line.startswith("EDGE~") and line.endswith(" 15d"), repr(line))
    line = next(l for l in ec.build_message(
        [calendar_row("EVEN", upcoming_date, spread=30)]).split("\n")
        if l.startswith("EVEN"))
    check("a range of exactly 30 is not ~", not line.startswith("EVEN~"),
          repr(line))

    # (c) a passed announced date lands in Overdue with no grace, while a
    # projected row the same number of days past its estimate — inside
    # OVERDUE_GRACE — keeps its grace and is not flagged.
    past_date = today - timedelta(days=3)
    assert 3 < ec.OVERDUE_GRACE, "test assumes 3d is inside the grace window"
    disclosed_overdue = calendar_row("DISC", past_date, disclosed=True)
    projected_within_grace = calendar_row("PROJ", past_date, disclosed=False)
    text = ec.build_message([disclosed_overdue, projected_within_grace])
    overdue_section = text.split("Overdue")[1] if "Overdue" in text else ""
    check("an announced date past due lands in Overdue with no grace",
          "DISC" in overdue_section, overdue_section)
    check("a projected row inside the grace window is not marked overdue",
          "PROJ" not in overdue_section, overdue_section)

    print("\nBODY DATE CANDIDATES")
    BODY = (
        "MARA Schedules Conference Call for Second Quarter 2026 Financial "
        "Results. MARA Holdings will report results for the quarter ended "
        "June 30, 2026 after market close on Tuesday, August 12, 2026. A "
        "conference call will be held on August 12, 2026 at 5:00 PM ET. A "
        "replay is available until August 19, 2026. In the prior year, "
        "results were reported August 1, 2025."
    )
    got = ed.candidate_dates(BODY, date(2026, 7, 30))
    check("finds the forward-looking dates",
          date(2026, 8, 12) in got and date(2026, 8, 19) in got, got)
    check("drops dates before the release",
          date(2025, 8, 1) not in got and date(2026, 6, 30) not in got, got)
    check("deduplicates a date repeated in the body",
          got.count(date(2026, 8, 12)) == 1, got)
    check("keeps document order",
          got == [date(2026, 8, 12), date(2026, 8, 19)], got)
    check("respects the limit",
          len(ed.candidate_dates(BODY, date(2026, 7, 30), limit=1)) == 1)
    check("a yearless date in prose is not inferred",
          ed.candidate_dates("the call will be held on August 12", None) == [],
          "DATE_RE only; a bare month-day in a body is usually a period")
    check("released=None with real dates returns them all, unfiltered",
          ed.candidate_dates(BODY, None) == [
              date(2026, 6, 30), date(2026, 8, 12), date(2026, 8, 19),
              date(2025, 8, 1)],
          "no released date means no past-date filter is applied at all")

    # Measured 2026-08-12, first probe_body_dates run: EVERY scheduled body
    # opened with its own dateline, and it survived as candidate one because
    # the filter dropped only dates strictly before the release. It made
    # five of six advance notices look like they offered two dates when
    # they offered one. See docs/press-monitor.md.
    DATELINED = (
        "MIAMI, Aug. 4, 2026 -- WhiteFiber today announced it will report "
        "second quarter results on August 12, 2026."
    )
    check("the release-date dateline is not a candidate",
          ed.candidate_dates(DATELINED, date(2026, 8, 4))
          == [date(2026, 8, 12)],
          "a body is stamped with its own date; that is never the "
          "forthcoming report date")
    check("a body offering only its own dateline offers nothing",
          ed.candidate_dates("MIAMI, Aug. 4, 2026 -- no other date here",
                             date(2026, 8, 4)) == [],
          "an empty list is the honest answer, not the dateline")
    check("released=None still returns a dateline, having no baseline",
          ed.candidate_dates(DATELINED, None)
          == [date(2026, 8, 4), date(2026, 8, 12)],
          "with no release date there is nothing to recognise it as")

    print("\nTHE RULE OVER A BODY")
    REL = date(2026, 8, 4)
    NOW = date(2026, 8, 5)
    check("exactly one forward date is the date",
          ed.date_from_body("will report on August 12, 2026", REL, NOW)
          == (date(2026, 8, 12), "ok"))
    check("several candidates yield nothing",
          ed.date_from_body("report August 12, 2026, replay to August 19, 2026",
                            REL, NOW) == (None, "several"),
          "choosing between them is the guess this rule exists to refuse")
    check("no candidate yields nothing",
          ed.date_from_body("no dates here at all", REL, NOW)
          == (None, "no-candidates"))
    check("an empty body yields nothing",
          ed.date_from_body("", REL, NOW) == (None, "no-candidates"))
    check("a body that offers only its own dateline yields nothing",
          ed.date_from_body("MIAMI, Aug. 4, 2026 -- nothing else", REL, NOW)
          == (None, "no-candidates"),
          "candidate_dates already drops the dateline")
    check("a single past date is rejected, not stored",
          ed.date_from_body("reported on August 1, 2026", date(2026, 7, 1),
                            date(2026, 8, 20)) == (None, "past"),
          "the guard is on our reading, not on the company")
    check("several and no-candidates are different reasons",
          ed.date_from_body("a August 12, 2026 b August 19, 2026", REL, NOW)[1]
          != ed.date_from_body("nothing", REL, NOW)[1],
          "one means we could not choose; the other means there was nothing")

    # THE ONE THAT MATTERS. With no release timestamp, candidate_dates has no
    # baseline to recognise the body's own dateline against, so the dateline
    # itself survives as the only candidate and looks like a perfectly good
    # answer. Stored, it becomes today's date presented as an announced date.
    NO_BASELINE_BODY = ("MIAMI, Aug. 20, 2026 -- Acme will host its call "
                        "next Tuesday.")
    check("with no release date, the rule refuses rather than storing the "
          "dateline",
          ed.date_from_body(NO_BASELINE_BODY, None, date(2026, 8, 12))
          == (None, "no-baseline"),
          "released=None must not let the dateline read as a real date")
    check("the same shape with a real release date still yields its one date",
          ed.date_from_body(
              "MIAMI, Aug. 20, 2026 -- Acme will host its call on "
              "August 25, 2026.",
              date(2026, 8, 20), date(2026, 8, 21))
          == (date(2026, 8, 25), "ok"),
          "the fix must not disable the rule when a release date IS known")

    check("date_from_body's reasons are a closed set",
          {ed.date_from_body(*a)[1] for a in [
              ("will report on August 12, 2026", REL, NOW),
              ("a August 12, 2026 b August 19, 2026", REL, NOW),
              ("no dates here", REL, NOW),
              ("reported on August 1, 2026", date(2026, 7, 1),
               date(2026, 8, 20)),
              ("MIAMI, Aug. 20, 2026 -- nothing else", None,
               date(2026, 8, 12)),
          ]} == {"ok", "several", "no-candidates", "past", "no-baseline"},
          "press_monitor indexes its counter dict by these strings")

    print("\nANNUAL-ONLY PROJECTION")

    def annual(year, lag_days):
        """One 20-F: period 31 Dec of `year`, filed `lag_days` later."""
        p = date(year, 12, 31)
        return (p, p + timedelta(days=lag_days), "20-F")

    def q(year, month, lag_days=45):
        p = date(year, month, 30)
        return (p, p + timedelta(days=lag_days), "10-Q")

    # BTDR's real shape: five annual filings, no quarterly ones.
    btdr = [annual(y, 111) for y in (2025, 2024, 2023, 2022, 2021)]
    row = ec.project("BTDR", "Bitdeer", btdr)
    check("a company with no quarterly filings still projects",
          row is not None)
    check("it projects the ANNUAL period end, twelve months on",
          row["period"] == date(2026, 12, 31), row["period"])
    check("its lag is the annual lag, not a pooled one", row["lag"] == 111)
    check("it is marked annual_only", row.get("annual_only") is True)
    check("it is not marked degraded, because nothing was degraded",
          row["degraded"] is False)
    check("its kind is annual", row["kind"] == "annual")

    # THE BOUNDARY, and where the first draft of the spec was wrong.
    one_q = btdr + [q(2026, 6)]
    row = ec.project("BTDR", "Bitdeer", one_q)
    check("ONE quarterly filing is still annual-only",
          row.get("annual_only") is True,
          "one filing cannot yield a lag; pooling annual into a quarter end "
          "is the bug this task removes")
    two_q = btdr + [q(2026, 6), q(2026, 3)]
    row = ec.project("BTDR", "Bitdeer", two_q)
    check("TWO quarterly filings flip it to normal treatment",
          not row.get("annual_only"),
          "a real quarterly lag can be measured now")
    check("and the normal projection uses a quarter end",
          row["period"] == date(2026, 9, 30), row["period"])

    # A single filing never reaches project()'s annual_only branch at all: the
    # pre-existing MIN_PERIODIC_FILINGS guard at the top of the function
    # returns None first. This checks that outer floor, not the new guard.
    check("a single filing never reaches project() at all: the outer floor",
          ec.project("X", "X", [annual(2025, 111)]) is None)

    # To actually exercise the NEW guard (annual_only and len(annual) < 2),
    # the company needs >= MIN_PERIODIC_FILINGS filings in total, so the outer
    # floor does not fire first, while staying below the quarterly floor and
    # under two annual filings. One annual + one quarterly does exactly that:
    # two filings total, one quarterly (annual_only True), one annual (fails
    # the new guard's own len(annual) < 2 check).
    thin = [annual(2025, 111), q(2026, 6)]
    check("below the quarterly floor AND under two annual filings: "
          "the new guard fires",
          ec.project("X", "X", thin) is None)
    # Proves the guard above is load-bearing rather than incidental: the same
    # shape with a second annual filing added (still only one quarterly, so
    # still annual_only) DOES project, because it now clears len(annual) >= 2.
    thin_plus_one_annual = [annual(2025, 111), annual(2024, 111), q(2026, 6)]
    row = ec.project("X", "X", thin_plus_one_annual)
    check("a second annual filing clears the new guard and projects",
          row is not None)
    check("that projection is still annual_only, since quarterly count "
          "never changed",
          row is not None and row.get("annual_only") is True)

    print("\nTHE ANNUAL PERIOD STEP")
    check("twelve months on, not three",
          ec.next_annual_period_end(date(2025, 12, 31)) == date(2026, 12, 31))
    check("29 February falls back to the 28th",
          ec.next_annual_period_end(date(2024, 2, 29)) == date(2025, 2, 28))

    print("\nANNUAL-ONLY REACHES OVERDUE LIKE ANY OTHER ROW")
    # The old rule exempted annual-only rows from Overdue entirely, written
    # when the projection was a fabricated quarterly date that could never be
    # seen satisfied. The projection is now the annual filing itself — 10-K,
    # 20-F and 40-F are all in PERIODIC_FORMS, and DGXX files both a 10-K and
    # a 10-Q — so the component CAN see it arrive, and the exemption is gone.
    long_past = date.today() - timedelta(days=400)
    within_grace = date.today() - timedelta(days=3)
    assert 3 < ec.OVERDUE_GRACE, "test assumes 3d is inside the grace window"

    def crow(label, **kw):
        r = {"label": label, "name": label, "period": date(2025, 12, 31),
             "expected": long_past, "lag": 111, "spread": 4, "kind": "annual",
             "degraded": False, "cik": "0001899123"}
        r.update(kw)
        return r

    text = ec.build_message([crow("BTDR", annual_only=True)])
    check("an annual-only row past the grace by more than OVERDUE_GRACE "
          "DOES reach Overdue",
          "Overdue" in text and "BTDR" in text, text)
    text = ec.build_message(
        [crow("BTDR", annual_only=True, expected=within_grace)])
    check("the ordinary OVERDUE_GRACE still applies to an annual-only row",
          "Overdue" not in text, text)
    text = ec.build_message([crow("PROJ")])
    check("an ordinary row 400 days past still does",
          "Overdue" in text and "PROJ" in text)

    print("\nBARE \"ANNOUNCES\"")
    BTDR_REAL = ("Bitdeer Announces Second Quarter 2026 Earnings Conference "
                 "Call for August 10th 2026")
    check("BTDR's real advance notice is recognised",
          ed.looks_like_announcement(BTDR_REAL))
    when, reason = ed.extract(BTDR_REAL, date(2026, 8, 1), date(2026, 8, 1))
    check("and its date parses straight from the title",
          when == date(2026, 8, 10) and reason == "ok", f"{when} {reason}")
    check("an operations update is still not an announcement",
          not ed.looks_like_announcement(
              "Bitdeer Announces June 2026 Production and Operations Update"),
          "no results or earnings word")
    check("a financing release is still not an announcement",
          not ed.looks_like_announcement(
              "Bitdeer Announces $4.7 Billion, 16-Year AI/HPC Data Center "
              "Lease for Tydal, Norway"))
    # Now recognised, and that is intended: the date guard is the real filter.
    RESULTS = "Galaxy Announces Second Quarter 2026 Financial Results"
    check("a results release is now recognised", ed.looks_like_announcement(RESULTS))
    when, reason = ed.extract(RESULTS, date(2026, 8, 11), date(2026, 8, 11))
    check("but carries no date, so it stores nothing",
          when is None and reason == "no-date", f"{when} {reason}")

    print("\nSCHEDULED-EVENT GATE")
    check("an advance notice names a scheduled event",
          ed.names_a_scheduled_event(BTDR_REAL))
    check("so does a webcast announcement",
          ed.names_a_scheduled_event(
              "Company Announces Q2 Earnings Release and Webcast"))
    check("a results release does NOT",
          not ed.names_a_scheduled_event(RESULTS),
          "its body is dense with dates and would poison the measurement")
    check("nor does a bare results headline",
          not ed.names_a_scheduled_event(
              "American Bitcoin Reports Second Quarter 2026 Results"))

    print("\nRESULTS-AND-CALL, THE MIXED CASE THE GATE CANNOT SEPARATE")
    MIXED = ("Company Announces Third Quarter 2026 Financial Results and "
             "Will Host Conference Call")
    check("it still passes the scheduling gate — the gate is not the fix",
          ed.names_a_scheduled_event(MIXED))
    check("but the results signal flags it as mixed",
          ed.also_reports_results(MIXED))
    check("the pure advance notice is NOT flagged by the results signal",
          not ed.also_reports_results(BTDR_REAL),
          "no 'results' word — only names the call, does not report results")
    check("nor is the webcast-only announcement",
          not ed.also_reports_results(
              "Company Announces Q2 Earnings Release and Webcast"))

    print("\nANNOUNCED BUT NOT OVERLAID")
    soon = date.today() + timedelta(days=3)
    store = {"0001854368": {"ticker": "DGXX", "date": soon.isoformat(),
                            "source_uid": "u", "source_title": "t",
                            "source_published": "2026-07-20T00:00:00+00:00"}}

    # An annual-only row: its period end is a year out, so apply() refuses.
    arow = {"label": "DGXX", "name": "Digi Power X", "cik": "0001854368",
            "period": date.today() + timedelta(days=200),
            "expected": date.today() + timedelta(days=290), "lag": 90,
            "spread": 40, "kind": "annual", "degraded": False,
            "annual_only": True}
    rows, applied, _ = ed.apply([dict(arow)], store, date.today())
    check("apply still refuses to overlay it", applied == 0)
    got = ed.announced_elsewhere([dict(arow)], store, date.today())
    check("but the date is surfaced separately",
          got == [("DGXX", soon)], got)

    # A row where the date WAS overlaid must not also appear in the section.
    qrow = dict(arow, period=date.today() - timedelta(days=10),
                annual_only=False)
    rows, applied, _ = ed.apply([dict(qrow)], store, date.today())
    check("a date that was overlaid is applied", applied == 1)
    # Reuses `rows`, the same objects apply() just mutated — not a fresh
    # dict(qrow) — because announced_elsewhere()'s contract is that it reads
    # `disclosed` off rows apply() has already run over. A fresh copy would
    # never carry that flag and this check would be testing nothing.
    check("and is NOT repeated in the section",
          ed.announced_elsewhere(rows, store, date.today()) == [],
          "it is already on the row")

    past = {"0001854368": dict(store["0001854368"],
                               date=(date.today() - timedelta(days=5)).isoformat())}
    check("a date already past is not surfaced",
          ed.announced_elsewhere([dict(arow)], past, date.today()) == [],
          "the section is about what is coming")

    # THE SELF-EXPIRY NOTE. `arow`'s period end is 200 days out (future) and
    # `past`'s stored date is 5 days ago, so apply()'s `when <= r["period"]`
    # test fires for the same reason it does for a real forthcoming
    # announcement — but this date is not forthcoming, it is stale. The note
    # for this population must not claim the date is shown in the Announced
    # section: announced_elsewhere's own `when < today` guard means a passed
    # date never reaches it, so that claim would be false — the same defect
    # Step 6 rewrote the note to remove, just relocated to this branch.
    rows, applied, notes = ed.apply([dict(arow)], past, date.today())
    check("a date already past does not apply", applied == 0)
    check("its note says the date is not shown anywhere, not that it is in "
          "the Announced section",
          any("not shown anywhere" in n for n in notes)
          and not any("Announced section" in n for n in notes), notes)

    text = ec.build_message([dict(arow)], announced=[("DGXX", soon)])
    check("the section renders with its own heading",
          "Announced" in text and "DGXX" in text, text)
    widest = max(len(l) for l in text.splitlines())
    check("and nothing in the block exceeds 28 characters",
          widest <= 28, widest)

    # arow's own expected date (290d out) is past HORIZON_DAYS, so the same
    # DGXX label appears a second time, in Later — under Announced's own
    # date (`soon`). Without a heading of its own, Later's rows read as
    # still belonging to Announced, and the label appears to contradict
    # itself. Later must have its own heading, and DGXX's Later row must be
    # findable under that heading rather than under Announced's.
    check("Later gets its own heading too",
          "Later" in text, text)
    later_section = text.split("Later", 1)[1]
    announced_section = text.split("Announced", 1)[1].split("Later", 1)[0]
    check("DGXX's own (annual) date is under Later, not Announced",
          "DGXX~" in later_section and "DGXX~" not in announced_section,
          text)

    print("\nTHE KEY DESCRIBES ONLY WHAT THE TABLE SHOWS")

    def krow(label, expected, **kw):
        r = {"label": label, "name": label, "cik": "000000000" + label[0],
             "period": date.today() - timedelta(days=90), "expected": expected,
             "lag": 45, "spread": 5, "kind": "10-Q", "degraded": False}
        r.update(kw)
        return r

    # A row between `today - OVERDUE_GRACE` and `today` renders in NO section:
    # too late for upcoming, not yet overdue, not beyond the horizon. Its
    # marker must not reach the key.
    assert 3 < ec.OVERDUE_GRACE, "fixture assumes 3 days is inside the grace"
    limbo = krow("LIMB", date.today() - timedelta(days=3), degraded=True)
    visible = krow("VIS", date.today() + timedelta(days=5))
    text = ec.build_message([limbo, visible])
    check("a row rendered in no section is really absent from the table",
          "LIMB" not in text, text)
    check("and its marker is not advertised in the key",
          "? thin history" not in text,
          "the key described a row the reader cannot see")

    # Every rendered row announced, so every last column is blank.
    only_disclosed = krow("DISC", date.today() + timedelta(days=5),
                          disclosed=True)
    text = ec.build_message([only_disclosed])
    check("no spread footnote when nothing populates that column",
          "last col" not in text, text)
    # And the ordinary case still explains it.
    text = ec.build_message([only_disclosed, visible])
    check("the footnote returns as soon as one row has a spread",
          "last col = +/- spread" in text and "(blank on ! rows)" in text)

    print("\nA BODY-DERIVED DATE IS MARKED APART")
    btext = ec.build_message([calendar_row("WYFI", today + timedelta(days=5),
                                           disclosed=True, source="body")])
    check("a body-derived row is marked +", "WYFI+" in btext, btext)
    check("a body-derived row is not marked !", "WYFI!" not in btext, btext)
    check("the key explains +", "+ date read from body" in btext, btext)
    check("the key line fits the 28-char ceiling",
          max(len(l) for l in btext.splitlines()) <= 28, btext)

    ttext = ec.build_message([calendar_row("BGDE", today + timedelta(days=5),
                                           disclosed=True, source="title")])
    check("a title-derived row is still marked !", "BGDE!" in ttext, ttext)
    check("the + key is absent when no + row is shown",
          "+ date read from body" not in ttext, ttext)

    # A table showing BOTH markers at once is the only path that produces
    # "(blank on ! and + rows)" — every test above shows just one, which
    # only ever exercises "(blank on ! rows)" or "(blank on + rows)". A third,
    # projected row is needed too: with every row disclosed there is nothing
    # in the spread column at all, and the footnote does not print — see
    # "no spread footnote when nothing populates that column" above.
    both_text = ec.build_message([
        calendar_row("BGDE", today + timedelta(days=5), disclosed=True,
                     source="title"),
        calendar_row("WYFI", today + timedelta(days=6), disclosed=True,
                     source="body"),
        calendar_row("PROJ", today + timedelta(days=7), disclosed=False),
    ])
    check("both markers appear together", "BGDE!" in both_text
          and "WYFI+" in both_text, both_text)
    check("the footnote names both markers",
          "(blank on ! and + rows)" in both_text, both_text)
    check("every line still fits the 28-char ceiling",
          max(len(l) for l in both_text.splitlines()) <= 28, both_text)
    check("the widest line for this table is 26",
          max(len(l) for l in both_text.splitlines()) == 26, both_text)

    # THE ONE THAT MATTERS. Same past date, same everything else: the
    # company's own headline date is late immediately, while a date we read
    # out of prose gets the projection grace, because the uncertainty is
    # OURS. If this ever collapses to one behaviour, a misreading becomes an
    # accusation that a company missed its own date.
    late = today - timedelta(days=3)
    otext = ec.build_message([calendar_row("BGDE", late, disclosed=True,
                                           source="title")])
    check("a title-derived row past its date is overdue at once",
          "Overdue" in otext, otext)
    gtext = ec.build_message([calendar_row("WYFI", late, disclosed=True,
                                           source="body")])
    check("a body-derived row past its date keeps the grace",
          "Overdue" not in gtext, gtext)
    vlate = today - timedelta(days=ec.OVERDUE_GRACE + 1)
    vtext = ec.build_message([calendar_row("WYFI", vlate, disclosed=True,
                                           source="body")])
    check("a body-derived row is overdue once the grace runs out",
          "Overdue" in vtext, vtext)

    bad = sum(1 for r, _ in results if r == FAIL)
    print(f"\n{len(results) - bad}/{len(results)} checks passed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
