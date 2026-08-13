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
    # Was DEF 14A until proxies became tracked. A check that names an
    # "unknown" form has to be updated when that form stops being unknown,
    # which is the check doing its job rather than a nuisance.
    check("an unknown form has no label", pm.form_label("SC 13E3") == "")

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
          pm.filing_title("SC 13E3", "", "Going private") == "Going private")
    check("with nothing at all it names the form",
          pm.filing_title("SC 13E3", "", "") == "SC 13E3 filing")

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

    print("\nUNDATED ITEMS")
    # Measured 2026-08-13: 0 of 223 items across all twenty IR sources. So
    # these checks guard a path that live data does not currently reach, which
    # is exactly why fixtures are the only way to hold it.
    dated = {"ticker": "MARA", "published": now}
    no_key = {"ticker": "DGXX"}
    zero = {"ticker": "DGXX", "published": 0}
    check("an item with a timestamp is not counted",
          pm.undated_items([dated]) == {})
    # Both shapes reach the same place: entry_time RETURNS 0 rather than
    # omitting the key, while a scraper may never set one.
    check("a MISSING published key counts",
          pm.undated_items([no_key]) == {"DGXX": 1})
    check("a published of literally 0 counts",
          pm.undated_items([zero]) == {"DGXX": 1},
          "entry_time returns 0; the key is present and falsy")
    check("counts aggregate per ticker",
          pm.undated_items([zero, no_key, dated, {"ticker": "HUT"}])
          == {"DGXX": 2, "HUT": 1},
          "every item from one source is that source's format having changed")
    check("an undated item with no ticker is still counted",
          pm.undated_items([{"published": 0}]) == {"?": 1},
          "an unattributable loss is still a loss")

    check("no undated items yields no notice",
          pm.undated_notice({}) == "",
          "silence is the healthy signal")
    # The line itself is never echoed into a detail: it carries the same
    # warning emoji as the other ops notices, and printing that to a cp1252
    # console raises, which would take the whole suite down rather than fail
    # one check.
    line = pm.undated_notice({"DGXX": 2, "HUT": 1})
    check("the notice carries the TOTAL", "3 item(s)" in line,
          "2 + 1, summed rather than restated")
    check("the notice names every source and its count",
          "DGXX 2" in line and "HUT 1" in line,
          "the shape of the loss is the diagnosis, not the total")
    check("the notice says the items cannot return",
          "cannot return" in line,
          "they are marked seen before the age floor drops them")

    print("\nFORM 144: A PROPOSED SALE")
    # Measured 2026-08-13 (probe_form_144.py): 338 filings across the roster,
    # median 2 days ahead of the Form 4 that follows, and one filer who files
    # 144s and NO Form 4 under any CIK, so the channel cannot see him at all
    # without this.
    check("144 is carried on the insider channel",
          "144" in pm.INSIDER_ALLOWED_FORMS and "144/A" in pm.INSIDER_ALLOWED_FORMS)
    check("144 has a label of its own",
          pm.form_label("144") == "Proposed insider sale")
    # An earlier check here asserted that INSIDER_ALLOWED_FORMS contains no
    # "14A" or "1445". It was removed: it inspected the constant rather than
    # any behaviour, so no change to the module could break it. What the set
    # is actually for is exact membership, which collect_all applies over the
    # network and no fixture here can reach.
    check("an amended 144 keeps the label and is marked amended",
          pm.form_label("144/A") == "Proposed insider sale (amended)")

    # THE XSL TRAP. primaryDocument points at the rendered view; parsing that
    # as XML fails in a way that reads as the filing not being structured.
    check("the stylesheet segment is stripped from the source url",
          pm.form_144_source("0001144879", "0001950047-26-007614",
                             "xslFORM144X01/primary_doc.xml")
          == "https://www.sec.gov/Archives/edgar/data/1144879/"
             "000195004726007614/primary_doc.xml",
          "parsing the rendered view reads as 'not structured after all'")
    check("a primary document that is not xml yields no url",
          pm.form_144_source("0001144879", "0001950047-26-007614",
                             "form144.htm") == "",
          "better no fetch than a fetch that cannot parse")
    check("a missing primary document yields no url",
          pm.form_144_source("0001144879", "0001950047-26-007614", "") == "")

    xml144 = """<?xml version="1.0"?>
    <edgarSubmission>
      <headerData><filerInfo><filer><filerCredentials>
        <cik>0001166816</cik></filerCredentials></filer></filerInfo></headerData>
      <formData>
        <issuerInfo>
          <issuerName>APPLIED DIGITAL CORPORATION</issuerName>
          <nameOfPersonForWhoseAccountTheSecuritiesAreToBeSold>RICHARD N NOTTENBURG</nameOfPersonForWhoseAccountTheSecuritiesAreToBeSold>
          <relationshipsToIssuer><relationshipToIssuer>Director</relationshipToIssuer></relationshipsToIssuer>
        </issuerInfo>
        <securitiesInformation>
          <brokerOrMarketmakerDetails><name>Morgan Stanley</name></brokerOrMarketmakerDetails>
          <noOfUnitsSold>75000</noOfUnitsSold>
          <aggregateMarketValue>2336107.50</aggregateMarketValue>
          <noOfUnitsOutstanding>291469000</noOfUnitsOutstanding>
          <approxSaleDate>08/04/2026</approxSaleDate>
        </securitiesInformation>
      </formData>
    </edgarSubmission>"""
    got = pm.parse_144(xml144)
    # THE SELLER IS NESTED INSIDE issuerInfo, AND THE BROKER HAS A FIELD
    # LITERALLY CALLED name. A tolerant extractor written for the probe
    # returned "Morgan Stanley" here and reported a clean, wrong zero.
    check("the SELLER is read, not the broker",
          got.get("seller") == "RICHARD N NOTTENBURG", got.get("seller"))
    check("the relationship to the issuer is read",
          got.get("relationship") == "Director")
    check("the size and the float are both read",
          (got.get("shares"), got.get("outstanding")) == ("75000", "291469000"))
    check("malformed xml yields no details rather than raising",
          pm.parse_144("<edgarSubmission><formData>") == {})
    check("empty input yields no details", pm.parse_144("") == {})

    line = pm.sale_title(got)
    check("the title names the seller and their relationship",
          "Richard N Nottenburg (Director)" in line, line[:60])
    check("the title carries the share count", "75,000 sh" in line)
    check("the title carries the value in millions", "$2.34M" in line)
    # A bare share count invites a baseline from intuition, and this roster's
    # share counts run from tens of millions to billions.
    check("THE TITLE CARRIES THE FRACTION OF SHARES OUTSTANDING",
          "0.026% of shares out" in line, line)
    check("a sale under a million is shown in dollars, not millions",
          "$40,000" in pm.sale_title({"seller": "X", "shares": "1000",
                                      "value": "40000"}))
    check("no seller means no title, so the plain one is kept",
          pm.sale_title({"shares": "1000"}) == "",
          "an intent to sell is worth posting even without the detail")
    check("missing numbers drop their phrase rather than the title",
          pm.sale_title({"seller": "Jane Roe"}) == "Proposed sale — Jane Roe")
    check("an unparsable number is dropped, not printed raw",
          pm.sale_title({"seller": "Jane Roe", "shares": "n/a"})
          == "Proposed sale — Jane Roe")
    check("a zero float does not divide",
          pm.sale_title({"seller": "Jane Roe", "shares": "10",
                         "outstanding": "0"}) == "Proposed sale — Jane Roe: 10 sh")

    print("\nPROXY: A PROPOSAL TO RAISE THE SHARE CEILING")
    # The strings below are REAL, from the proxies named, via
    # probe_proxy_shares.py run 31730368424. Invented proposal text would
    # prove the rule can match text written to be matched.
    real = {
        "BKKT": "To approve an amendment of the Company's Certificate of "
                "Incorporation to increase the number of authorized shares of "
                "Class A Common Stock.",
        "CIFR": "CHARTER AMENDMENT PROPOSAL - INCREASE IN AUTHORIZED SHARES "
                "Purpose of the Charter Amendment We are asking you to adopt "
                "an amendment",
        "APLD": "the best interests of the Company and our stockholders to "
                "amend the Articles to increase the number of authorized "
                "shares of common stock.",
    }
    for ticker, text in sorted(real.items()):
        check(f"a real {ticker} proposal is recognised",
              bool(pm.proposes_increase(text)))

    # THE ONE THAT WOULD HAVE POSTED WRONGLY. A reverse split does not raise
    # the ceiling; it lowers the issued count so the unissued headroom rises
    # relatively. This exact sentence matched the rule before the effect
    # filter existed.
    bgde = ("to issue, the proposed Reverse Stock Split Amendment would "
            "result in a relative increase in the number of authorized and "
            "unissued shares of our Common Stock.")
    check("A REVERSE SPLIT IS NOT A PROPOSAL TO RAISE THE CEILING",
          pm.proposes_increase(bgde) is None,
          "the relative increase is an effect of the issued count falling")
    # Same effect, opposite word order, from a different company. Before the
    # filter, one of these matched and one did not, which is why the rule was
    # never really seven of eight.
    slnh = ("An additional effect of a Reverse Stock Split would be to "
            "increase the relative amount of authorized but unissued shares "
            "of common stock")
    # A PIN RATHER THAN A TEST OF THE FILTER, and worth saying so. This
    # phrasing is rejected because PROPOSES_INCREASE never matches it, not
    # because INCREASE_IS_AN_EFFECT catches it: "authorized but unissued
    # shares" is neither "authorized shares" nor "number of authorized".
    # Breaking it takes two changes at once — widening the phrase list AND
    # dropping the effect filter — which was measured rather than assumed.
    # It earns its place by guarding against exactly that widening.
    check("the same effect in the other word order is also rejected",
          pm.proposes_increase(slnh) is None)

    # Real near-misses the rule must keep rejecting, from the same run.
    for name, text in [
        ("an increase in DIRECTORS is not an increase in shares",
         "Newly created directorships resulting from any increase in our "
         "authorized number of directors or any vacancies in our Board"),
        ("an equity plan increase is not a charter amendment",
         "2021 Equity Incentive Plan to increase the number of shares of "
         "Class A common stock authorized for issuance under the 2021 Plan"),
        ("a constitutional power to alter capital is not a proposal",
         "increase, reduce or eliminate the maximum number of shares that "
         "the Company is authorized to issue"),
    ]:
        check(name, pm.proposes_increase(text) is None)

    # A proxy proposing BOTH is common, and the real proposal must survive
    # the reverse-split discussion sitting elsewhere in the same document.
    both = bgde + (" x" * 300) + " " + real["APLD"]
    check("a proposal survives a reverse split elsewhere in the document",
          bool(pm.proposes_increase(both)),
          "every candidate is tested, not just the first")

    sized = ("to increase the number of authorized shares of common stock "
             "from 500,000,000 to 1,000,000,000.")
    check("the title carries the from and to when the proxy states them",
          pm.proxy_title(sized)
          == "Proposes raising authorized shares: 500,000,000 -> 1,000,000,000",
          pm.proxy_title(sized))
    check("the title still posts when no pair is stated",
          pm.proxy_title(real["BKKT"]) == "Proposes raising authorized shares")
    # "" is what stops a proxy posting at all, so it is load-bearing.
    check("A PROXY THAT PROPOSES NOTHING GETS NO TITLE",
          pm.proxy_title("We are authorized to issue 900,000,000 shares.") == "",
          "26 of 28 proxies mention authorized shares; 7 propose a rise")
    check("no body at all yields no title", pm.proxy_title("") == "")

    check("the proxy forms are tracked",
          pm.form_matches("DEF 14A", pm.FORM_TYPES)
          and pm.form_matches("PRE 14A", pm.FORM_TYPES))
    # DEFA14A is soliciting material — a vote reminder or a slide deck. It is
    # not the statement, and the fourth character is what keeps it out.
    check("SOLICITING MATERIAL IS NOT SWEPT IN WITH THE PROXY",
          not pm.form_matches("DEFA14A", pm.FORM_TYPES),
          "DEFA14A does not start with 'DEF 14A'")

    bad = sum(1 for r, _ in results if r == FAIL)
    print(f"\n{len(results) - bad}/{len(results)} checks passed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
