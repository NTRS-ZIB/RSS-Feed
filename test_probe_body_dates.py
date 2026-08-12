#!/usr/bin/env python3
"""Tests for probe_body_dates. Standalone, stdlib only.

THE ONE THAT MATTERS: the probe must NOT apply press_monitor's
scheduled-event gate. That gate exists to keep date-dense results releases
out of the measurement, and whether it actually discriminates is the
question this probe was built to answer. A probe that pre-filters by the
gate can only ever confirm it.
"""

import sys
from datetime import date, datetime, timezone

import probe_body_dates as pb

PASS, FAIL = "PASS", "FAIL"
results = []


def check(name, ok, detail=""):
    results.append((PASS if ok else FAIL, name))
    print(f"  [{PASS if ok else FAIL}] {name}" + (f" — {detail}" if detail else ""))


TODAY = date(2026, 8, 10)
ROSTER = {"MARA": ("0001507605", "MARA Holdings"),
          "HUT": ("0001964789", "Hut 8 Corp")}


def epoch(y, m, d):
    return datetime(y, m, d, tzinfo=timezone.utc).timestamp()


# One item per case the selector has to get right. The three labels are
# taken from real titles and their predicates were measured, not assumed:
# MARA's actual advance notice says "...Second Quarter 2026 Financial
# Results", so also_reports_results() is TRUE for it. A pure advance notice
# is the rarer phrasing that never says "results" at all.
ADVANCE_NOTICE = {            # scheduled, not mixed
    "ticker": "MARA", "link": "https://example.test/a", "published": epoch(2026, 8, 5),
    "title": "MARA Schedules Conference Call for Second Quarter 2026 Earnings",
}
MIXED_NOTICE = {              # scheduled AND reports results
    "ticker": "MARA", "link": "https://example.test/b", "published": epoch(2026, 8, 5),
    "title": "MARA Schedules Conference Call for Second Quarter 2026 Financial Results",
}
RESULTS_RELEASE = {           # not scheduled
    "ticker": "MARA", "link": "https://example.test/c", "published": epoch(2026, 8, 5),
    "title": "MARA Announces Second Quarter 2026 Results",
}
HAS_A_DATE = {
    "ticker": "HUT", "link": "https://example.test/d", "published": epoch(2026, 8, 5),
    "title": "Hut 8 to Report Second Quarter 2026 Results on August 20, 2026",
}
UNRELATED = {
    "ticker": "MARA", "link": "https://example.test/e", "published": epoch(2026, 8, 5),
    "title": "MARA Announces $4.7 Billion Data Center Lease",
}
OFF_ROSTER = {
    "ticker": "ZZZZ", "link": "https://example.test/f", "published": epoch(2026, 8, 5),
    "title": "Zzzz Schedules Conference Call for Second Quarter 2026 Results",
}

# Bodies keyed by link, so the fake fetcher is a dict lookup. The advance
# notice carries one forward date; the results release carries several,
# which is the shape the scheduled-event gate assumes.
BODIES = {
    "https://example.test/a":
        "MARA will report second quarter results on August 20, 2026 "
        "and host a call the same day.",
    "https://example.test/c":
        "MARA today reported results for the quarter ended June 30, 2026. "
        "A replay is available until September 1, 2026, and the company "
        "will file its report on August 29, 2026.",
}


def fake_fetch(link):
    """Stands in for press_monitor.announcement_body. Returns None for an
    unknown link, exactly as a failed fetch does."""
    return BODIES.get(link)


def main():
    print("SELECTION")
    rows = pb.undated_announcements(
        [ADVANCE_NOTICE, MIXED_NOTICE, RESULTS_RELEASE, HAS_A_DATE, UNRELATED,
         OFF_ROSTER],
        TODAY, roster=ROSTER)
    titles = [r["title"] for r in rows]

    check("an advance notice with no title date is selected",
          ADVANCE_NOTICE["title"] in titles)
    check("a mixed notice is selected", MIXED_NOTICE["title"] in titles)
    check("a results release with no title date is ALSO selected",
          RESULTS_RELEASE["title"] in titles,
          "the gate is what this probe is measuring, not a filter it applies")
    check("an announcement whose date parsed is not selected",
          HAS_A_DATE["title"] not in titles)
    check("an unrelated release is not selected",
          UNRELATED["title"] not in titles)
    check("a ticker off the roster is not selected",
          OFF_ROSTER["title"] not in titles,
          "mirrors record_disclosed_dates, so the count matches the log")
    check("exactly three rows selected", len(rows) == 3, f"got {len(rows)}")

    print("\nROW SHAPE")
    notice = next(r for r in rows if r["title"] == ADVANCE_NOTICE["title"])
    mixed = next(r for r in rows if r["title"] == MIXED_NOTICE["title"])
    release = next(r for r in rows if r["title"] == RESULTS_RELEASE["title"])
    check("release date read from the published epoch",
          notice["released"] == date(2026, 8, 5))
    check("an advance notice is labelled scheduled", notice["scheduled"] is True)
    check("an advance notice is not labelled mixed", notice["mixed"] is False)
    check("a mixed notice is labelled scheduled", mixed["scheduled"] is True)
    check("a mixed notice is labelled mixed", mixed["mixed"] is True,
          "the real MARA title says 'Financial Results' and must not read as pure")
    check("a results release is not labelled scheduled",
          release["scheduled"] is False)
    check("a results release is labelled mixed", release["mixed"] is True)
    check("the link is carried through", notice["link"] == "https://example.test/a")

    print("\nRELEASE DATE")
    check("an item with no published epoch has no release date",
          pb.released_date({"ticker": "MARA"}) is None,
          "candidate_dates treats None as no lower bound")

    print("\nPROBING")
    probed = pb.probe_rows(
        pb.undated_announcements([ADVANCE_NOTICE, RESULTS_RELEASE],
                                 TODAY, roster=ROSTER),
        fake_fetch)
    by_title = {r["title"]: r for r in probed}
    notice = by_title[ADVANCE_NOTICE["title"]]
    release = by_title[RESULTS_RELEASE["title"]]

    check("every selected row is fetched, gate or no gate", len(probed) == 2)
    check("an advance notice body yields its one forward date",
          notice["candidates"] == [date(2026, 8, 20)],
          f"got {notice['candidates']}")
    check("a results release body yields several",
          len(release["candidates"]) > 1, f"got {release['candidates']}")
    check("a date before the release is excluded",
          date(2026, 6, 30) not in release["candidates"],
          "the quarter ended June 30 is not a forthcoming report date")
    check("chars records the body length", notice["chars"] == len(BODIES[notice["link"]]))

    print("\nA FAILED FETCH IS NOT AN EMPTY BODY")
    failed = pb.probe_rows(
        [{"ticker": "MARA", "title": "t", "link": "https://example.test/gone",
          "released": date(2026, 8, 5), "scheduled": True, "mixed": False}],
        fake_fetch)[0]
    check("a failed fetch leaves chars None", failed["chars"] is None)
    check("a failed fetch yields no candidates", failed["candidates"] == [])
    check("a failed fetch buckets as failed, not none",
          pb.bucket_of(failed) == "failed",
          "a source that did not answer is not a body carrying no date")

    print("\nLABELS AND COUNTS")
    check("scheduled and not results is an advance notice",
          pb.label_of(notice) == "advance notice")
    check("not scheduled is its own label",
          pb.label_of(release) == "not scheduled")
    check("scheduled and results together is mixed",
          pb.label_of({"scheduled": True, "mixed": True}) == "scheduled + results")

    summary = pb.summarise(probed)
    check("one forward date counts as one",
          summary["advance notice"]["one"] == 1, f"got {summary}")
    check("several forward dates count as several",
          summary["not scheduled"]["several"] == 1, f"got {summary}")
    check("a body with no forward date counts as none",
          pb.summarise([{"scheduled": True, "mixed": False, "chars": 500,
                         "candidates": []}])["advance notice"]["none"] == 1)
    check("every bucket is present even at zero",
          set(summary["advance notice"]) == {"one", "several", "none", "failed"},
          "a missing key reads as a gap; a zero reads as a measurement")

    no_advance_notice = pb.summarise(
        [{"scheduled": False, "mixed": False, "chars": 100,
          "candidates": []}])
    check("a label with no rows still appears, zeroed",
          no_advance_notice.get("advance notice") == dict.fromkeys(pb.BUCKETS, 0),
          f"got {no_advance_notice}")

    bad = sum(1 for r, _ in results if r == FAIL)
    print(f"\n{len(results) - bad}/{len(results)} checks passed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
