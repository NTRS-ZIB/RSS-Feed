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
    "Galaxy Announces Second Quarter 2026 Financial Results",
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

    def calendar_row(label, expected, spread=6, disclosed=False, degraded=False):
        return {"label": label, "cik": "0000000000",
                "period": date(2026, 6, 30), "expected": expected,
                "spread": spread, "kind": "10-Q", "degraded": degraded,
                "disclosed": disclosed}

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

    check("below the quarterly floor AND under two annual filings: nothing",
          ec.project("X", "X", [annual(2025, 111)]) is None)

    print("\nTHE ANNUAL PERIOD STEP")
    check("twelve months on, not three",
          ec.next_annual_period_end(date(2025, 12, 31)) == date(2026, 12, 31))
    check("29 February falls back to the 28th",
          ec.next_annual_period_end(date(2024, 2, 29)) == date(2025, 2, 28))

    bad = sum(1 for r, _ in results if r == FAIL)
    print(f"\n{len(results) - bad}/{len(results)} checks passed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
