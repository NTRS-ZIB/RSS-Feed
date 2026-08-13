#!/usr/bin/env python3
"""Tests for press_monitor's pure functions. Standalone, no network.

feedparser is stubbed below because it is absent from a plain working copy.
That is safe ONLY because feedparser is touched solely by parse_feed, which
none of the functions tested here calls. If a test ever needs a
feed-parsing function, REMOVE THE STUB rather than extending it: a stub
that grows is a stub that starts hiding things.

THE ONE THAT MATTERS: prefix matching does not bridge a form-type rename.
The SEC renamed SC 13D to SCHEDULE 13D and 117 filings went unposted,
because "SCHEDULE 13D".startswith("SC 13D") is False and nothing said so.
drift_candidates exists to catch the next rename, and the checks below are
what stop it quietly ceasing to.
"""

import sys
import types

sys.modules.setdefault("feedparser", types.ModuleType("feedparser"))

import press_monitor as pm

PASS, FAIL = "PASS", "FAIL"
results = []


def check(name, ok, detail=""):
    results.append((PASS if ok else FAIL, name))
    print(f"  [{PASS if ok else FAIL}] {name}" + (f" — {detail}" if detail else ""))


def main():
    print("FORM MATCHING")
    check("a prefix matches its amendment",
          pm.form_matches("8-K/A", ["8-K"]))
    check("a prefix does not match an unrelated form",
          not pm.form_matches("DEF 14A", ["8-K"]))
    # THE 117-FILING INCIDENT, as a property of the module rather than of
    # Python. An earlier draft asserted not "SCHEDULE 13D".startswith(
    # "SC 13D"), which is true of the language and could not fail whatever
    # press_monitor did. This calls the real function, so it fails if anyone
    # makes form_matches fuzzy or substring-based to "fix" renames.
    check("PREFIX MATCHING DOES NOT BRIDGE A RENAME",
          not pm.form_matches("SCHEDULE 13D", ["SC 13D"]),
          "the rename the prefix could not follow, asked of the module")

    check("form_core strips the amendment suffix and spacing",
          pm.form_core("SC 13D/A") == "SC13D", pm.form_core("SC 13D/A"))
    check("form_core is case-insensitive",
          pm.form_core("sc 13d") == "SC13D")

    print("\nDRIFT DETECTION")
    # Both spellings are tracked today, so nothing should be flagged.
    check("a tracked form is not flagged as drift",
          pm.drift_candidates({"SCHEDULE 13D"}) == [])
    check("an unrelated form is not flagged",
          pm.drift_candidates({"DEF 14A"}) == [])
    # "10-K405" starts with "10-K", a tracked prefix in FORM_TYPES, so
    # form_matches short-circuits it at press_monitor.py:626 before
    # DRIFT_IGNORE is ever consulted. "10KSB" has no dash, so it matches no
    # FORM_TYPES prefix and only DRIFT_IGNORE keeps it quiet.
    check("an obsolete form in DRIFT_IGNORE is not flagged",
          pm.drift_candidates({"10KSB"}) == [],
          "a warning that always fires is one nobody reads")

    # The incident itself: with the new spelling untracked, the old one must
    # still recognise it, WITHOUT anyone having told it the new name.
    original = pm.FORM_TYPES[:]
    try:
        pm.FORM_TYPES = [f for f in original if f != "SCHEDULE 13D"]
        check("an untracked rename IS flagged against its old spelling",
              pm.drift_candidates({"SCHEDULE 13D"}) == [("SCHEDULE 13D", "SC 13D")],
              "this is the guard that would have caught the 2024 rename")
    finally:
        pm.FORM_TYPES = original
    check("FORM_TYPES is restored after the drift check",
          pm.FORM_TYPES == original)

    # A known limit, pinned so it is a decision rather than a surprise. The
    # docstring says a match fires when one core contains the other "or vice
    # versa", but the code tests only `stem in core`. Measured: with only the
    # NEW spelling tracked, a seen OLD spelling is NOT flagged.
    original = pm.FORM_TYPES[:]
    try:
        pm.FORM_TYPES = [f for f in original if f != "SC 13D"]
        check("the detector is ASYMMETRIC, and this pins which way",
              pm.drift_candidates({"SC 13D"}) == [],
              "docstring says 'or vice versa'; the code checks one direction")
    finally:
        pm.FORM_TYPES = original

    print("\nPER-HOST HEADERS")
    # A browser-like User-Agent is a per-host bet. GlobeNewswire stalls a
    # Chrome-claiming request from the runner and answers a plain one in
    # 0.1s; not knowing that cost 22 hours of silent outage.
    gnw = pm.headers_for("https://www.globenewswire.com/rss/organization/x")
    check("a host in HOST_HEADERS gets its override",
          gnw is pm.HOST_HEADERS["www.globenewswire.com"],
          "losing this bet presents as a dead host, not as a refusal")
    check("any other host gets IR_HEADERS",
          pm.headers_for("https://ir.mara.com/feed") is pm.IR_HEADERS)
    check("the netloc lookup is case-insensitive",
          pm.headers_for("https://WWW.GlobeNewswire.COM/x") is gnw,
          "a casing miss silently reverts the host to the losing bet")
    check("a path does not affect the lookup",
          pm.headers_for("https://www.globenewswire.com/") is gnw)

    print("\nSTALENESS")
    import io as _io, time as _time, contextlib as _ctx

    def staleness_log(times, **kw):
        """check_staleness RETURNS None ON EVERY PATH; it logs and returns.

        So asserting on its return value cannot discriminate: `is None` is
        true whether the horizon fired, the history was too short, or the
        collapse was deleted. An earlier draft of this suite did exactly
        that, and a mutation removing the same-day collapse passed it. The
        log is the only observable, so the log is what these check.
        """
        buf = _io.StringIO()
        with _ctx.redirect_stdout(buf):
            pm.check_staleness("T", times, **kw)
        return buf.getvalue()

    now = _time.time()
    day = 86400

    # Three releases in one morning are ONE publication event. Measured on
    # real data: HUT's median gap reads 5.5d uncollapsed and 18d collapsed,
    # so this is what makes the horizon mean anything.
    check("same-day items collapse to ONE publication day",
          "1 publication day(s)" in staleness_log(
              [now - 1, now - 2, now - 3, now - 4, now - 5]),
          "uncollapsed these five would read as five days of history")
    check("genuinely distinct days are counted as distinct",
          "2 publication day(s)" in staleness_log([now - day, now - 2 * day]))

    # Below STALE_MIN_DAYS it reports a COUNT rather than warning. Too little
    # history and a dead source are different measurements.
    check("too little history says so rather than warning",
          "insufficient history" in staleness_log([now - day, now - 2 * day]))

    check("a fresh source logs NOTHING",
          staleness_log([now - i * day for i in range(10)]) == "",
          "silence is the healthy signal; a warning here would be noise")

    # Ten daily items whose newest is a year old: median gap 1d, so the
    # horizon is the 60d floor rather than 6x1d, and age is ~365d.
    dead = staleness_log([now - 365 * day - i * day for i in range(10)])
    check("a source dead a year is called STALE", "STALE" in dead, dead[:60])
    check("the log names the term that actually set the horizon",
          "60d floor" in dead,
          "a warning that cannot explain its threshold invites dismissal")

    check("no timestamps at all logs nothing", staleness_log([]) == "")
    check("all-zero timestamps are treated as no timestamps",
          staleness_log([0, 0]) == "")

    print("\nCROSS-HOST SUPPRESSION")
    base = _time.time()

    def item(title, when):
        return {"title": title, "published": when, "uid": title}

    Q1_2021 = "Galaxy Digital Announces First Quarter 2021 Financial Results"
    Q1_2022 = "Galaxy Digital Announces First Quarter 2022 Financial Results"

    # An exact repeat inside the window is a genuine duplicate.
    kept = pm.suppress_cross_host([item(Q1_2022, base)],
                                  [item(Q1_2022, base - 3600)], "T")
    check("an exact title inside the window is suppressed", kept == [])

    # THE ONE THAT MATTERS. These two scored 0.984 similarity across 23,771
    # measured pairs. Any threshold below 1.000 suppresses one as a duplicate
    # of the other, silently, once a quarter, on the highest-value item the
    # channel carries.
    kept = pm.suppress_cross_host([item(Q1_2022, base)],
                                  [item(Q1_2021, base - 3600)], "T")
    check("A 0.984-SIMILAR TITLE IS NOT SUPPRESSED", len(kept) == 1,
          "no similarity threshold may creep in here")

    # The window is what makes exact matching safe by construction.
    old = base - (pm.CROSS_HOST_DAYS + 1) * 86400
    kept = pm.suppress_cross_host([item(Q1_2022, base)],
                                  [item(Q1_2022, old)], "T")
    check("an exact title outside the window is not suppressed", len(kept) == 1)

    # A failed scrape must not read as a successful match against nothing.
    # Comparing against an empty list would ALSO return every feed item
    # unsuppressed even with the early-return removed, since nothing in an
    # empty index can match, so the return value alone cannot tell "skipped
    # the comparison" apart from "ran the comparison and it found nothing".
    # The SKIPPED log line at press_monitor.py:1551 is the only observable
    # that distinguishes them, so that is what this checks, using the same
    # stdout-capture technique as staleness_log above.
    feed = [item(Q1_2022, base), item(Q1_2021, base)]
    buf = _io.StringIO()
    with _ctx.redirect_stdout(buf):
        empty_result = pm.suppress_cross_host(feed, [], "T")
    check("an empty newsroom suppresses nothing at all",
          empty_result == feed,
          "the bias is to post twice, never to suppress")
    check("an empty newsroom SKIPS the comparison, logged as such",
          "SKIPPED" in buf.getvalue(),
          "disabling the early return still returns every item unsuppressed; "
          "only the log line proves the comparison itself was skipped")

    # A missing timestamp on either side cannot satisfy the window.
    kept = pm.suppress_cross_host([item(Q1_2022, 0)],
                                  [item(Q1_2022, base)], "T")
    check("a feed item with no timestamp is not suppressed", len(kept) == 1)
    kept = pm.suppress_cross_host([item(Q1_2022, base)],
                                  [item(Q1_2022, 0)], "T")
    check("a newsroom item with no timestamp suppresses nothing", len(kept) == 1)

    print("\nTITLE NORMALISATION")
    check("punctuation and case do not change a normalised title",
          pm.norm_title("Q1 2026 Results!") == pm.norm_title("q1 2026 results"))
    check("an HTML entity is stripped",
          "amp" not in pm.norm_title("Smith &amp; Co Results"))
    check("two different titles do not normalise equal",
          pm.norm_title(Q1_2021) != pm.norm_title(Q1_2022),
          "this is what stops the year being normalised away")

    print("\nALWAYS-POST ITEMS")
    check("a matching code posts whatever its position",
          pm.always_post_items({"form": "8-K", "items": "9.01,4.02"}))
    check("a matching code posts when listed first",
          pm.always_post_items({"form": "8-K", "items": "4.02,9.01"}))
    check("an unrelated item set does not post",
          not pm.always_post_items({"form": "8-K", "items": "7.01"}))
    check("a non-8-K form is never considered",
          not pm.always_post_items({"form": "10-Q", "items": "4.02"}))
    check("a missing items field is safe",
          not pm.always_post_items({"form": "8-K"}))

    print("\nPRESS RELEASE DETECTION")
    check("a press-release item code passes",
          pm.carries_press_release("8-K", "2.02,9.01"))
    check("an unrelated item code does not",
          not pm.carries_press_release("8-K", "5.02"))
    # Non-empty items, so only the 6-K exemption at press_monitor.py:657 can
    # produce True; an empty-items fixture would hit the fail-open branch at
    # :659 instead and pass whether or not the exemption exists.
    check("a 6-K is never filtered, having no item numbers",
          pm.carries_press_release("6-K", "5.02"))
    # 1,986 of 1,986 real 8-Ks carry item codes, so this branch has never
    # once executed in production. A fixture can exercise what real data
    # never has, which is the cheapest insurance against someone deleting
    # it as dead code.
    check("AN 8-K WITH NO ITEM CODES FAILS OPEN",
          pm.carries_press_release("8-K", ""),
          "a branch real data has never reached; do not simplify it away")

    print("\nFORM LABELS AND TITLES")
    # No two FORM_LABELS keys currently form a prefix pair, so form_label's
    # longest-first sort is real code no live data exercises. Do not fake a
    # test for it by inventing a key; check what is actually true.
    check("a late-notice form gets its specific label",
          pm.form_label("NT 10-K") != "",
          "NT is not itself a label key, so this must not fall through")
    check("an amendment is labelled as one",
          pm.form_label("10-Q/A").endswith("(amended)"))
    check("an unknown form has no label", pm.form_label("DEF 14A") == "")

    check("8-K item labels beat the SEC document label",
          pm.filing_title("8-K", "2.02", "8-K") == pm.ITEM_LABELS["2.02"])
    check("a generic item yields to a meaningful one",
          pm.filing_title("8-K", "9.01,2.02", "8-K") == pm.ITEM_LABELS["2.02"],
          "9.01 is in GENERIC_ITEMS and says nothing on its own")
    check("a generic item alone is still used rather than nothing",
          pm.filing_title("8-K", "9.01", "8-K") == pm.ITEM_LABELS["9.01"])
    check("a repeated label appears once",
          pm.filing_title("8-K", "2.02,2.02", "8-K").count(
              pm.ITEM_LABELS["2.02"]) == 1)
    check("an amended 8-K title says so",
          pm.filing_title("8-K/A", "2.02", "8-K").endswith("(amended)"))
    check("with no items it falls back to the form label",
          pm.filing_title("10-Q", "", "") == pm.form_label("10-Q"))
    # BOTH form_label and description present, or the fallback order is
    # untestable: the two existing checks around this one each leave one term
    # empty, so swapping press_monitor.py:698 to "description or form_label(...)"
    # would survive either alone. form_label("10-Q") is "Quarterly report",
    # which differs from the description "10-Q" here, so only the real order
    # (form_label first) satisfies this.
    check("the form label wins over the description when both are present",
          pm.filing_title("10-Q", "", "10-Q") == pm.form_label("10-Q"))
    check("with no label it falls back to the description",
          pm.filing_title("DEF 14A", "", "Proxy statement") == "Proxy statement")
    check("with nothing at all it names the form",
          pm.filing_title("DEF 14A", "", "") == "DEF 14A filing")

    print("\nFILING TIMESTAMPS")
    # filingDate is a DATE ONLY. Reading it alone puts publication at 00:00
    # UTC and discards a mean of 17.7 hours across 122 measured filings,
    # 10.5% of the MAX_AGE_DAYS window, because 48% of filings land between
    # 20:00 and 23:00 UTC.
    noon = pm.filed_time("2026-08-12", "2026-08-12T12:00:00Z")
    midnight = pm.filed_time("2026-08-12")
    check("acceptanceDateTime is preferred over the date", noon > midnight)
    check("the acceptance stamp is read as UTC, not Eastern",
          noon - midnight == 12 * 3600,
          "the field ends in Z and IS UTC; CLAUDE.md records the two "
          "confirmations that wrongly said otherwise")
    check("a malformed acceptance stamp falls back to the date",
          pm.filed_time("2026-08-12", "not-a-timestamp") == midnight)
    check("a malformed date returns 0 rather than raising",
          pm.filed_time("not-a-date") == 0)

    print("\nIDENTIFIERS AND FEED HELPERS")
    check("filing_uid keeps the Atom-era format",
          pm.filing_uid("0001193125-26-000123")
          == "urn:tag:sec.gov,2008:accession-number=0001193125-26-000123",
          "changing this makes every historical filing look new")
    url = pm.filing_url("1507605", "0001193125-26-000123")
    check("filing_url carries the accession dashed and undashed",
          "000119312526000123" in url and "0001193125-26-000123" in url, url)

    check("no keywords configured passes everything",
          pm.passes_keywords({"title": "anything at all"})
          if not pm.KEYWORDS else True,
          "KEYWORDS is empty in this repo, so this is the live path")

    # KEYWORDS is empty in production, so the match/no-match arms below are
    # otherwise unreachable and `return True` in their place would still pass
    # the whole suite. Monkeypatched, in the idiom already used above for
    # FORM_TYPES, so the two real arms of the spec get exercised at all.
    original_keywords = pm.KEYWORDS
    try:
        pm.KEYWORDS = ["dividend"]
        check("a matching keyword passes, case-insensitively",
              pm.passes_keywords({"title": "Special DIVIDEND Announced"}))
        check("an unrelated title does not pass",
              not pm.passes_keywords({"title": "Quarterly Results"}))
    finally:
        pm.KEYWORDS = original_keywords

    # BOTH keys present, or the check cannot test preference at all. A
    # fixture carrying only one key returns the same epoch whatever order
    # the function reads them in, so reversing the preference would not
    # fail it. The two dates differ by a day so the answer is unambiguous.
    check("entry_time PREFERS published_parsed over updated_parsed",
          pm.entry_time({"published_parsed": (2026, 8, 12, 0, 0, 0, 0, 0, 0),
                         "updated_parsed": (2026, 8, 11, 0, 0, 0, 0, 0, 0)})
          == 1786492800,
          "reversing the preference returns the 11th, one day earlier")
    check("entry_time falls through when published_parsed is absent",
          pm.entry_time({"updated_parsed": (2026, 8, 12, 0, 0, 0, 0, 0, 0)})
          == 1786492800)
    check("entry_time returns 0 when nothing is usable",
          pm.entry_time({}) == 0,
          "that 0 becomes a released of None, which the body-date rule refuses")

    # TWO tags, or "first" is untestable for the same reason. A single-tag
    # fixture proves only that a term is read and stripped.
    check("entry_form takes the FIRST tag's term, and strips it",
          pm.entry_form({"tags": [{"term": " 8-K "}, {"term": "4"}]}) == "8-K",
          "taking the last would return 4")
    check("entry_form skips a tag whose term is empty",
          pm.entry_form({"tags": [{"term": ""}, {"term": "4"}]}) == "4",
          "the `if term:` guard, which a single-tag fixture cannot reach")
    check("entry_form uses the fallback when there are no tags",
          pm.entry_form({}, "6-K") == "6-K")

    print("\nBASELINE SUPPRESSION FOR A NEW COMPANY")
    # Adding a ticker must produce NO backdated posts AT ALL. Not "none older
    # than MAX_AGE_DAYS", none. An item six days old is unseen and inside the
    # window, and on 2026-08-05 exactly that posted a handful of backdated
    # items. The record lives in state["baselined"], NOT in "seen": seen is
    # capped at 1000 and actively evicting, and a uid carries no company, so
    # "has this company any ids in seen" cannot be asked of the file at all.
    old_item = {"uid": "o", "ticker": "NEW", "published": 1,
                "title": "Old", "form": "8-K"}
    new_item = {"uid": "r", "ticker": "NEW", "published": 2,
                "title": "Recent", "form": "8-K"}
    est_item = {"uid": "e", "ticker": "MARA", "published": 3,
                "title": "Established", "form": "8-K"}
    every = [old_item, new_item, est_item]

    # An ABSENT key is the backfill run: every roster company has been posting
    # for weeks, so all are recorded and nothing is suppressed.
    state = {}
    new_co, sup = pm.baseline_companies(state, ["NEW", "MARA"], every,
                                        today="2026-08-13")
    check("an absent baselined key suppresses nothing",
          (new_co, sup) == ([], []),
          "first run under the rule; everyone is established by definition")
    check("the backfill records the whole roster",
          set(state["baselined"]) == {"NEW", "MARA"},
          "so a later run can tell a genuinely new company from these")

    # A company missing from a PRESENT dict is the new one.
    state = {"baselined": {"MARA": "2026-08-01"}}
    new_co, sup = pm.baseline_companies(state, ["NEW", "MARA"], every,
                                        today="2026-08-13")
    check("a company absent from a present dict is new", new_co == ["NEW"])
    check("EVERY item from a new company is suppressed, whatever its age",
          {i["uid"] for i in sup} == {"o", "r"},
          "not only the aged ones; a six-day-old item posted on 2026-08-05")
    check("an established company's item is untouched",
          "e" not in {i["uid"] for i in sup})
    check("the new company is recorded, so it is new only once",
          state["baselined"]["NEW"] == "2026-08-13")

    state = {"baselined": {"MARA": "2026-08-01", "NEW": "2026-08-10"}}
    check("a roster with no new companies suppresses nothing",
          pm.baseline_companies(state, ["NEW", "MARA"], every,
                                today="2026-08-13") == ([], []))

    print("\nWHAT COUNTS AS NEW, AND AS RECENT")
    # These three were nested inside main() until 2026-08-13 and so could not
    # be reached by any test, though all three decide what posts.

    legacy = ("https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany"
              "&CIK=0001507605&type=8-K&accession-number=0001507605-26-000042")
    check("an accession is read out of a legacy uid",
          pm.seen_accessions([legacy]) == {"0001507605-26-000042"},
          "the half of the rename guard that reads OLD state")
    # A uid with no accession segment must contribute NOTHING. Without the
    # filter, rsplit returns the whole uid and a bare feed id lands in the
    # set of accessions, where it can never match but is not obviously wrong.
    check("a uid carrying no accession contributes nothing",
          pm.seen_accessions([legacy, "https://ir.example.com/2026/q2"])
          == {"0001507605-26-000042"},
          "an IR feed id is not an accession")
    # An empty-input check was written here and removed: seen_accessions([])
    # is empty under every mutation of the function, so it could not fail.

    seen = {"uid-a"}
    accs = {"0001507605-26-000042"}
    check("an item whose uid was seen is not unseen",
          not pm.is_unseen({"uid": "uid-a"}, seen, accs))
    # THE POINT OF THE SECOND IDENTIFIER. A new uid for a filing already
    # posted is what a change of uid format looks like, and matching on the
    # accession is what stops that reposting the entire history at once.
    check("A NEW UID FOR AN ALREADY-SEEN ACCESSION IS NOT UNSEEN",
          not pm.is_unseen(
              {"uid": "reshaped-uid", "accession": "0001507605-26-000042"},
              seen, accs),
          "the flood this guard exists to prevent")
    check("an item new by both identifiers is unseen",
          pm.is_unseen({"uid": "uid-b", "accession": "0001507605-26-000099"},
                       seen, accs))
    check("an item with an empty uid is never unseen",
          not pm.is_unseen({"uid": "", "accession": "0001507605-26-000099"},
                           seen, accs),
          "it could not be recorded, so it would post every run forever")
    check("an item with no accession key at all is unseen",
          pm.is_unseen({"uid": "uid-c"}, seen, accs),
          "IR feed items have no accession and must not be filtered by one")

    now = 1_700_000_000.0
    day = 86400
    check("an item published now is within the window",
          pm.within_age({"published": now}, now))
    check("an item older than MAX_AGE_DAYS is not",
          not pm.within_age({"published": now - (pm.MAX_AGE_DAYS + 1) * day},
                            now))
    check("an item exactly on the boundary is within",
          pm.within_age({"published": now - pm.MAX_AGE_DAYS * day}, now),
          "the floor is inclusive")
    # Documented rather than endorsed: an unparseable feed timestamp becomes
    # 0 in entry_time, which reads here as 1970 and silently drops a real
    # item. Changing that is a separate decision; this pins what it does now.
    check("an item with NO timestamp is dropped, not kept",
          not pm.within_age({"title": "no published key"}, now),
          "0 reads as 1970, against this component's post-twice bias")

    bad = sum(1 for r, _ in results if r == FAIL)
    print(f"\n{len(results) - bad}/{len(results)} checks passed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
