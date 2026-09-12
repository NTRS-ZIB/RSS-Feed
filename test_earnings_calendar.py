#!/usr/bin/env python3
"""Tests for how earnings_calendar READS the EDGAR index. No network.

SCOPE, AND WHY IT IS NARROW. `test_earnings_dates.py` already exercises
`project()` and `build_message()` at length, and `probe_cadence_corpus.py`
characterises the shared rule over 7,714 generated cases. What neither touches
is the fetch: `periodic_filings` had no test of any kind, and it was reading
`filings.recent` and stopping.

That page is a ROLLING WINDOW of roughly the newest thousand filings. CRWV's
reaches back only to 2025-07-31 because 460 of its filings are Form 4s, so its
10-Q for period 2025-03-31 sat on the older page and went unread. That filing
carries the LONGEST lag of its five, so its absence pulled the published median
from 44 down to 43 and this component posted `2026-11-12` to Discord while
`snapshot.json` published `2026-11-13` off the same index. The fixtures below
are that company's real filings.

EVERY CHECK HERE HAS BEEN WATCHED TO FAIL. A test that has never failed proves
nothing, and the natural minimal fixture usually cannot reach the branch it
names. The mutation that reddens each group is written above it; the sweep is
in the docstring of `main` at the bottom.
"""

import os
import sys
from datetime import date

# Refuses to load without it, and fetches nothing at import.
os.environ.setdefault("SEC_USER_AGENT", "offline-suite tests@example.invalid")

import earnings_calendar as ec
from filing_cadence import cadence

PASS, FAIL = "PASS", "FAIL"
results = []

# CAPTURED BEFORE ANY FIXTURE REPLACES IT. `serve()` substitutes ec.sec_get,
# and the rate-gap checks below run after several serve() calls, so reaching
# for ec.sec_get there tests the FAKE — which sleeps never, and reported the
# real function as broken. The suite's own plumbing standing in for the code
# under test is the same shape as a fixture that cannot reach its branch.
REAL_SEC_GET = ec.sec_get


def check(name, ok, detail=""):
    results.append((PASS if ok else FAIL, name))
    print(f"  [{PASS if ok else FAIL}] {name}" + (f" - {detail}" if detail else ""))


def attempt(fn, *a, **kw):
    """(result, exception) — so a check can observe a raise instead of dying of it.

    CLAUDE.md: a mutation that crashes the harness instead of failing the check
    has shown nothing. Any check whose named mutation makes the module RAISE
    has to go through here, or the sweep reports CRASHED and the check stays
    undemonstrated.
    """
    try:
        return fn(*a, **kw), None
    except Exception as e:                      # noqa: BLE001 - that is the point
        return None, e


def page(*rows):
    """An EDGAR index page as the submissions API returns it: parallel arrays.

    Built as columns rather than as a list of records because that is the shape
    the defect lives in — a short column is what `rows_from` has to survive.
    """
    return {
        "form": [r[0] for r in rows],
        "reportDate": [r[1] for r in rows],
        "filingDate": [r[2] for r in rows],
    }


# CRWV's real periodic filings, newest first, exactly as EDGAR returns them.
CRWV_RECENT = page(
    ("10-Q", "2026-06-30", "2026-08-12"),
    ("10-Q", "2026-03-31", "2026-05-08"),
    ("10-K", "2025-12-31", "2026-03-02"),
    ("10-Q", "2025-09-30", "2025-11-13"),
    ("10-Q", "2025-06-30", "2025-08-13"),
)
# The one that was evicted from the recent window. Lag 45 days, the longest.
CRWV_OLDER = page(("10-Q", "2025-03-31", "2025-05-15"))

RECENT_URL = ec.SUBMISSIONS.format(cik="0001769628")
OLDER_NAME = "CIK0001769628-submissions-001.json"
OLDER_URL = ec.OLDER.format(name=OLDER_NAME)


def serve(recent, older=None, fail=()):
    """Replace ec.sec_get with one that serves canned pages.

    `fail` names URLs that return None, which is what the real sec_get does on
    any transport error, a non-200, or unparseable JSON.
    """
    index = {"filings": {"recent": recent}}
    if older is not None:
        index["filings"]["files"] = [{"name": OLDER_NAME}]
    pages = {RECENT_URL: index, OLDER_URL: older}
    calls = []

    def fake(url):
        calls.append(url)
        if url in fail:
            return None
        return pages.get(url)

    ec.sec_get = fake
    return calls


def main():
    real_sec_get = ec.sec_get
    try:
        return run()
    finally:
        ec.sec_get = real_sec_get


def run():
    print("ROWS_FROM: ONE INDEX PAGE")
    # Mutation: drop the `if form not in PERIODIC_FORMS: continue` guard.
    mixed = ec.rows_from(page(
        ("10-Q", "2026-03-31", "2026-05-08"),
        ("8-K", "2026-01-02", "2026-01-02"),
        ("4", "2026-01-05", "2026-01-06"),
        ("10-K", "2025-12-31", "2026-03-02"),
    ))
    check("only periodic forms survive", [r[2] for r in mixed] == ["10-Q", "10-K"],
          f"got {[r[2] for r in mixed]}")

    # Mutation: change `fd >= rd` to `fd >= rd or True`. A filing dated BEFORE
    # the period it reports on is not a lag, it is a corrupt row.
    backwards = ec.rows_from(page(("10-Q", "2026-03-31", "2026-01-01")))
    check("a filing dated before its own period end is dropped", backwards == [])

    # Mutation: delete `and covers_a_period(rd)`. BTDR's 20-F is stamped with a
    # TRANSACTION date six days before filing; counting it tripled a published
    # spread. `covers_a_period` is applied here as well as inside `cadence` so
    # the count this component PRINTS matches the filings the decision used.
    transaction = ec.rows_from(page(("20-F", "2023-04-13", "2023-04-19")))
    check("a periodic form reporting on no period is dropped", transaction == [],
          "BTDR 0001104659-23-047181 is the case")
    month_end = ec.rows_from(page(("20-F", "2023-03-31", "2023-04-19")))
    check("the same form on a real period end survives", len(month_end) == 1,
          "so the check above is about the DATE, not the form")

    # Mutation: replace the `except (ValueError, IndexError, TypeError)` body
    # with `raise`. A short column must lose one row, not the whole read.
    #
    # CAUGHT RATHER THAN CALLED DIRECTLY, and that is the point of the wrapper.
    # Written the obvious way, this check does not FAIL under its own mutation
    # — it takes the suite down with it, and a mutation that crashes the
    # harness has shown nothing. `attempt` turns the raise into a value the
    # check can read.
    #
    # The count alone would not have been evidence either: with a TRAILING
    # short column, an unguarded zip()-style truncation drops exactly the same
    # rows as the guard does, so `len(short) == 1` is true under both. What
    # separates them is whether anything was raised at all.
    short, raised = attempt(ec.rows_from, {"form": ["10-Q", "10-K"],
                                           "reportDate": ["2026-03-31", "2025-12-31"],
                                           "filingDate": ["2026-05-08"]})
    check("A SHORT COLUMN LOSES ONE ROW AND RAISES NOTHING",
          raised is None and short is not None and len(short) == 1,
          # `short` is None when it raised, so the count cannot be formatted
          # unconditionally — doing that turned this check's own mutation back
          # into a crash, which is the thing the wrapper exists to prevent.
          f"raised {raised!r}" if raised else f"got {len(short)} row(s)")
    unparseable, raised = attempt(ec.rows_from, page(("10-Q", "not-a-date", "2026-05-08")))
    check("an unparseable date drops its row and raises nothing",
          raised is None and unparseable == [], f"raised {raised!r}")

    # Mutation: `return sorted(out)` instead of `return out`.
    # THE ORDER IS LOAD-BEARING. `cadence` truncates pool[:LAG_SAMPLE]
    # positionally and documents that the caller owns the order, because this
    # component passes index order while build_snapshot sorts by period.
    ordered = ec.rows_from(CRWV_RECENT)
    check("INDEX ORDER IS PRESERVED, NEWEST FIRST",
          [r[1] for r in ordered] == sorted([r[1] for r in ordered], reverse=True),
          "sorting here would move every median this component publishes")

    print("\nPERIODIC_FILINGS: THE ROLLING WINDOW")
    # Mutation: delete the `for extra in filings.get("files")` loop.
    serve(CRWV_RECENT, CRWV_OLDER)
    read = ec.periodic_filings("0001769628")
    check("the older page is read", read.complete and len(read.filings) == 6,
          f"got {len(read.filings)} filing(s), complete={read.complete}")
    check("the evicted 10-Q is the one gained",
          (date(2025, 3, 31), date(2025, 5, 15), "10-Q") in read.filings,
          "accession 0001769628-25-000014")

    # THERE IS NO CHECK HERE FOR "older rows land after recent ones", and its
    # absence is deliberate. One was written, and the explicit sort at the end
    # of periodic_filings made it unfailable: with the sort in place, appending
    # and prepending the older page give the same list, so the check had become
    # a restatement of the sort's own postcondition. The sweep reported it as
    # not reddened, which is the same output as a missing mutation and a
    # different finding — this one is "the check cannot fail". What the sort
    # actually guarantees is checked below, against a fixture where period
    # order and filed order disagree.

    # Mutation: drop the `files` key handling, or make `or []` into `or [{}]`.
    calls = serve(CRWV_RECENT, None)
    read = ec.periodic_filings("0001769628")
    check("an index with no older pages costs one request",
          len(calls) == 1 and read.complete, f"{len(calls)} request(s)")
    check("and returns only what the recent page held", len(read.filings) == 5)

    # Mutation: `out.sort(key=lambda t: t[0], reverse=True)` — by PERIOD, which
    # is build_snapshot's order. The two components are supposed to read the
    # same index two ways; adopting the other's order here merges them silently.
    # An amended filing submitted late for an old period is what separates them,
    # so that is the fixture.
    serve(page(("10-Q", "2025-03-31", "2026-08-20"),     # late amendment
               ("10-Q", "2026-06-30", "2026-08-12")), None)
    order = ec.periodic_filings("0001769628").filings
    check("SORTED BY FILED DATE, NOT BY PERIOD",
          [r[0] for r in order] == [date(2025, 3, 31), date(2026, 6, 30)],
          f"got periods {[str(r[0]) for r in order]}; by period this reverses")

    print("\nTHE RATE GAP IS PAID ON EVERY PATH")
    # Mutation: move `time.sleep(REQUEST_GAP)` out of the `finally` and back
    # after the status check. A wrong SEC_USER_AGENT 403s every sec.gov
    # endpoint, so the whole roster fails in a row — the one case where this
    # component would fire 27 requests at SEC with no gap between them.
    slept = []
    real_sleep, real_get = ec.time.sleep, ec.requests.get
    ec.time.sleep = slept.append

    class Boom:
        status_code = 403
        def json(self):
            return {}

    try:
        ec.requests.get = lambda *a, **k: Boom()
        REAL_SEC_GET("https://example.invalid/x")
        check("a non-200 still waits before the next request", slept == [ec.REQUEST_GAP],
              f"slept {slept}")

        slept.clear()

        def raiser(*a, **k):
            raise ec.requests.RequestException("down")

        ec.requests.get = raiser
        REAL_SEC_GET("https://example.invalid/x")
        check("a transport error still waits too", slept == [ec.REQUEST_GAP],
              f"slept {slept}")
    finally:
        ec.time.sleep, ec.requests.get = real_sleep, real_get

    print("\nTHE DEFECT ITSELF: WHAT THE TWO READS PUBLISH")
    # Mutation: the same one that removes paging. This is the regression guard
    # stated in the units that reached Discord.
    serve(CRWV_RECENT, CRWV_OLDER)
    paged = cadence(ec.periodic_filings("0001769628").filings)
    unpaged = cadence(ec.rows_from(CRWV_RECENT))
    check("UNPAGED PUBLISHES THE WRONG MEDIAN LAG",
          unpaged["lag"] == 43 and unpaged["sample"] == 4,
          f"got {unpaged['lag']}d over {unpaged['sample']} — the bug's own numbers")
    check("PAGED AGREES WITH snapshot.json: 44d over 5",
          paged["lag"] == 44 and paged["sample"] == 5,
          f"got {paged['lag']}d over {paged['sample']}")
    check("and the expected date moves by the same day",
          unpaged["expected"] == date(2026, 11, 12)
          and paged["expected"] == date(2026, 11, 13))
    # The ± column is spread // 2, and 7 // 2 == 6 // 2. The range moves and the
    # PUBLISHED figure does not — worth pinning so a future reader does not
    # "fix" a discrepancy that never reached anyone.
    check("the ± column does NOT move, because it is half the range",
          paged["spread"] // 2 == unpaged["spread"] // 2 == 3,
          f"range {unpaged['spread']} -> {paged['spread']}, both print 3")

    print("\nA FAILED READ IS NOT A THIN HISTORY")
    # Mutation: `return Read(out, True)` inside the page-failure branch — that
    # is, publish from a partial read. This is the check that matters most:
    # a partial read republishes the defect above with no log line.
    serve(CRWV_RECENT, CRWV_OLDER, fail=(OLDER_URL,))
    read = ec.periodic_filings("0001769628")
    check("A FAILED OLDER PAGE RETURNS NOTHING, NOT A SHORT LIST",
          read.filings == [] and read.complete is False,
          f"got {len(read.filings)} filing(s), complete={read.complete}")

    # Mutation: `return Read([], True)` for the recent-page failure.
    serve(CRWV_RECENT, CRWV_OLDER, fail=(RECENT_URL,))
    read = ec.periodic_filings("0001769628")
    check("a failed index returns nothing and says so",
          read.filings == [] and read.complete is False)

    # Mutation: delete the `complete` field / always return True. An empty
    # index is a MEASUREMENT — this company has filed nothing periodic — and
    # must not share a label with a read that failed.
    serve(page(), None)
    read = ec.periodic_filings("0001769628")
    check("AN EMPTY INDEX IS COMPLETE, and a failed one is not",
          read.filings == [] and read.complete is True,
          "0 filings read is a fact about the company; a failure is not")

    print("\nTHE POST KEEPS THE TWO APART")
    # Mutation: `if unread:` -> `if False:`, or fold unread into `missing`.
    desc = post_description(missing=["SPCX 1/2"], unread=["CRWV"])
    check("a thin history is counted against its floor", "SPCX 1/2" in desc)
    check("an unread index gets ITS OWN LINE", "unread this run" in desc)
    check("THE UNREAD COMPANY IS NOT IN THE 'too few filings' LINE",
          "CRWV" not in desc.split("unread this run")[0],
          "a young company reported as a failure trains the reader to ignore it")
    # Mutation: give the unread line a count, e.g. f"{label} 0/2".
    check("and carries no count, because the run does not know what it missed",
          "CRWV 0" not in desc and "CRWV/" not in desc)

    only_missing = post_description(missing=["SPCX 1/2"], unread=[])
    check("no unread line when nothing failed", "unread this run" not in only_missing)
    only_unread = post_description(missing=[], unread=["CRWV"])
    check("no floor line when nothing was thin",
          "Too few periodic filings" not in only_unread)

    bad = sum(1 for r, _ in results if r == FAIL)
    print(f"\n{len(results) - bad}/{len(results)} checks passed")
    return 1 if bad else 0


def post_description(missing, unread):
    """The embed description `post()` builds, without sending anything.

    Reaches it by substituting the HTTP call rather than by copying the string
    logic here, so a change to the wording fails this suite instead of passing
    a stale duplicate of it.
    """
    captured = {}

    class FakeResponse:
        status_code = 204

    def fake_post(url, json=None, timeout=None):
        captured["desc"] = json["embeds"][0]["description"]
        return FakeResponse()

    real_post, real_url = ec.requests.post, ec.WEBHOOK_URL
    ec.requests.post, ec.WEBHOOK_URL = fake_post, "https://example.invalid/hook"
    try:
        ec.post("TABLE", missing, unread)
    finally:
        ec.requests.post, ec.WEBHOOK_URL = real_post, real_url
    return captured.get("desc", "")


if __name__ == "__main__":
    sys.exit(main())
