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
    check("an obsolete form in DRIFT_IGNORE is not flagged",
          pm.drift_candidates({"10-K405"}) == [],
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

    bad = sum(1 for r, _ in results if r == FAIL)
    print(f"\n{len(results) - bad}/{len(results)} checks passed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
