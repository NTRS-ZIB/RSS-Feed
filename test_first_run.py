#!/usr/bin/env python3
"""Tests for first_run.baseline and its five call sites. No network.

THE ONE THAT MATTERS: an ABSENT namespace and an EMPTY one mean opposite
things. Absent is the backfill run and nothing is new; empty means the rule
has run before and knows about nothing, so everything is. Reversing them
either floods on the day the rule lands or silently suppresses a real backlog
forever, and neither announces itself in the logs.

The second half checks the WIRING, one section per component. The shared
module being right buys nothing if a component applies it to the wrong set,
and that failure is silent in the direction nobody watches: an established
company's real events held back, with a log line that says only that
something was suppressed.
"""

import inspect
import operator
import sys
import types
from datetime import date

import comment_letters
import crossings
import dilution
import first_run
import holder_events
# press_monitor imports feedparser, which the suites do not need and
# the offline runner does not install.
sys.modules.setdefault("feedparser", types.ModuleType("feedparser"))
import press_monitor
import threshold_list

PASS, FAIL = "PASS", "FAIL"
results = []


def check(name, ok, detail=""):
    results.append((PASS if ok else FAIL, name))
    print(f"  [{PASS if ok else FAIL}] {name}" + (f" - {detail}" if detail else ""))


COMPONENTS = [holder_events, comment_letters, crossings, dilution,
              threshold_list]


def wiring():
    """Every component calls baseline WITH ITS STATE, and says so in the log.

    The filters below are checked directly, which cannot see whether main()
    reaches them or whether the record is written. That is the half that
    matters — a component that computes `newly_watched` and never passes
    `state` suppresses correctly once and then floods on the next run, having
    recorded nothing. main() itself is unreachable offline (SEC, Alpaca, a
    webhook), so this reads its source. A source check is a weak check, and a
    weak check on the wiring beats the nothing that was here before.
    """
    print("\nWIRING — each main() calls baseline with its own state")
    for mod in COMPONENTS:
        src = inspect.getsource(mod.main)
        check(f"{mod.__name__} passes its state to baseline()",
              "baseline_by_cik(state," in src,
              "recording is what stops the NEXT run flooding")
        check(f"{mod.__name__} baselines the CIK roster, not the tickers",
              "baseline_by_cik(state, watchlist.ciks())" in src
              or "baseline_by_cik(state, CIKS)" in src,
              "watchlist.tickers() would key the record by display label")
        # Matched against the COMPANY-axis call specifically. A bare
        # `"summary(" in src` stopped being able to fail the moment these two
        # components grew a forms axis: deleting the company line left the
        # forms line to satisfy it.
        axes = 2 if mod in (holder_events, comment_letters) else 1
        check(f"{mod.__name__} prints the first-run summary",
              f'summary("{mod.__name__}", sorted(newly_watched)' in src,
              "a silent suppression reads as a broken component")
        check(f"{mod.__name__} announces the backfill run",
              "backfilled(state)" in src
              and src.count("backfill_note(") == axes,
              "or a rule that ran and one never wired log identically")
        # backfilled() answers about the NEXT call, so asking after baseline
        # always says False and the note never prints — green, and useless.
        check(f"{mod.__name__} asks backfilled() BEFORE baseline()",
              src.index("backfilled(state)") < src.index("baseline_by_cik(state,"),
              "asked afterwards it is always False")

    # THE RECORD MUST REACH DISK ON THE QUIET PATH. Both of these components
    # return early when nothing changed, and both originally saved only after
    # a successful post — which can be weeks away. Until then the `companies`
    # record was rebuilt and thrown away every run, so the rule was inert
    # while every log line said it had already run. Two save sites each is
    # the cheapest thing that distinguishes the two shapes from source.
    print()
    for mod in (dilution, threshold_list):
        src = inspect.getsource(mod.main)
        check(f"{mod.__name__} writes state on its no-change path too",
              src.count("save_state(state)") >= 2,
              "counts call sites, so a dead branch still reads as green")
    check("threshold_list persists the FOLDED list, not just the date",
          inspect.getsource(threshold_list.main).count(
              'state["on_list"] = sorted(current)') == 2,
          "otherwise the fold delays the unearned post by one run")
    check("crossings does not re-flag a ticker it already has",
          "state.setdefault(ticker," in inspect.getsource(crossings.main),
          "a plain assignment would wipe last_seen and break classify()")


def event(ticker, form="SCHEDULE 13D"):
    """A holder_events event tuple. Fields 0 and 2 are read by the filters,
    but the arity has to match or the unpack in drop_newly_watched would pass
    here and fail in production."""
    return (ticker, "Name", {"form": form}, "ARRIVAL", ["A Holder"], 7.5,
            None, None, None)


def per_component():
    """Each of the five, at its own suppression point.

    The shared module is checked above; this is the wiring, which is where a
    wrong change goes SILENT — it suppresses real events for an established
    company and nothing says so. Every check pairs the two directions: the
    newly watched company is held back, the established one is untouched.
    """
    print("\nholder_events — the component that posted 86 times")
    state = {"companies": {"RIOT": "2026-01-01"}}
    new = set(first_run.baseline(state, ["RIOT", "CORZ"], today="2026-08-14"))
    events, per = holder_events.drop_newly_watched(
        [event("RIOT"), event("CORZ"), event("CORZ")], new)
    check("a newly watched company's events are dropped",
          [e[0] for e in events] == ["RIOT"], f"kept {[e[0] for e in events]}")
    check("and are counted, per company", dict(per) == {"CORZ": 2})
    # The backfill: absent namespace, so nobody is new and nothing is held.
    kept, _ = holder_events.drop_newly_watched(
        [event("RIOT"), event("CORZ")],
        set(first_run.baseline({}, ["RIOT", "CORZ"])))
    check("the backfill run suppresses NOTHING", len(kept) == 2,
          "the rule landing must not itself be a silent outage")

    print("\ncomment_letters — the widest window in the repo, 180 days")
    rows = [{"ticker": "RIOT", "accessions": ["r-1"]},
            {"ticker": "CORZ", "accessions": ["c-1", "c-2", "c-3"]}]
    kept, per = comment_letters.drop_newly_watched(
        {"r-1", "c-1", "c-2", "c-3"}, rows, {"CORZ"})
    check("a newly watched company's letters are dropped", kept == {"r-1"})
    check("and are counted, per company", per == {"CORZ": 3})
    kept, _ = comment_letters.drop_newly_watched(
        {"r-1", "c-1"}, rows, set(first_run.baseline({}, ["RIOT", "CORZ"])))
    check("the backfill run suppresses NOTHING", kept == {"r-1", "c-1"})

    print("\ncrossings — one unearned post, not a flood")
    check("a newly watched ticker is disarmed WHERE IT IS CROSSING",
          crossings.initial_flags("CORZ", {"CORZ"}, "H")
          == {"armed_hi": False, "armed_lo": True},
          "a company added above its 52w high crossed nothing while watched")
    check("and in the other direction when it is crossing low",
          crossings.initial_flags("CORZ", {"CORZ"}, "L")
          == {"armed_hi": True, "armed_lo": False})
    # The bug this replaced: disarming both left a ticker added at 85% of its
    # range unable to re-arm (that needs 25-75%), so a genuine breakout the
    # next day was dropped silently. Nothing was suppressed on day one, so
    # nothing in the log pointed at it either.
    check("a newly watched ticker CROSSING NOTHING stays fully armed",
          crossings.initial_flags("CORZ", {"CORZ"}, None)
          == {"armed_hi": True, "armed_lo": True},
          "there is no first-run event to suppress, so suppress nothing")
    check("an established ticker starts ARMED even while crossing",
          crossings.initial_flags("RIOT", {"CORZ"}, "H")
          == {"armed_hi": True, "armed_lo": True},
          "the disarm must not leak to everyone else")
    check("the backfill run arms everybody",
          crossings.initial_flags("CORZ",
                                  set(first_run.baseline({}, ["RIOT", "CORZ"])),
                                  "H")
          == {"armed_hi": True, "armed_lo": True})

    print("\nthreshold_list — folded into previous, not dropped")
    previous, joining = threshold_list.fold_newly_watched(
        {"RIOT"}, {"RIOT", "CORZ"}, {"CORZ"})
    check("a newly watched company already listed is not an ADDITION",
          {"RIOT", "CORZ"} - previous == set() and joining == {"CORZ"},
          "it was listed before anyone here was looking")
    check("the existing previous set SURVIVES the fold", "RIOT" in previous,
          "widened, not replaced — everyone else's history is in there")
    previous, joining = threshold_list.fold_newly_watched(
        {"RIOT"}, {"RIOT"}, {"CORZ"})
    check("a newly watched company NOT on the list is not folded in",
          previous == {"RIOT"} and joining == set(),
          "or its first genuine listing would never post")
    previous, _ = threshold_list.fold_newly_watched(
        set(), {"RIOT"}, set(first_run.baseline({}, ["RIOT"])))
    check("the backfill run folds in NOTHING", previous == set())

    print("\ndilution — a first observation is not a move")
    m = {"shares": 300_000_000, "date": date(2026, 8, 1)}
    check("a newly watched company's first count is not a change",
          dilution.is_change("CORZ", {}, m, {"CORZ"}) is False,
          "or it posts a dilution alert dated to the day it joined")
    check("an established company with a moved count still counts",
          dilution.is_change(
              "RIOT", {"shares": 250_000_000, "date": "2026-05-01"}, m,
              {"CORZ"}) is True,
          "the suppression must not leak to everyone else")
    check("an established company with an unmoved count does not",
          dilution.is_change(
              "RIOT", {"shares": 300_000_000, "date": "2026-08-01"}, m,
              {"CORZ"}) is False)
    check("the backfill run counts a real move normally",
          dilution.is_change("RIOT", {"shares": 1, "date": "2026-05-01"}, m,
                             set(first_run.baseline({}, ["RIOT"]))) is True)


def capability_axis():
    """The other axis: a form type tracked for the first time.

    `baseline` answers "have I recorded this key", which for a company is the
    whole question and for a form type is not — three of the four tracked
    sets are matched by PREFIX, so a value can be covered by a key that was
    already there.
    """
    print("\nNEWLY TRACKED, WHICH IS NOT THE SAME AS NEWLY RECORDED")
    pre = str.startswith
    check("a value covered only by a new key IS newly tracked",
          first_run.newly_tracked("SC 13G", {"SC 13G"}, {"SC 13D"}, pre)
          == "SC 13G")
    # The trap the axis brings with it.
    check("a value an ESTABLISHED key already matched is NOT",
          first_run.newly_tracked("S-3/A", {"S-3/A"}, {"S-3"}, pre) is None,
          "adding S-3/A beside S-3 adds no filings; suppressing would go quiet")
    check("a value nothing matches is not tracked at all",
          first_run.newly_tracked("10-K", {"S-3"}, {"8-K"}, pre) is None)
    check("the MOST SPECIFIC new key is the one reported",
          first_run.newly_tracked("SCHEDULE 13D", {"SCHEDULE", "SCHEDULE 13D"},
                                  set(), pre) == "SCHEDULE 13D",
          "so the log names something findable in the config")
    check("an exact matcher does not match a prefix",
          first_run.newly_tracked("144/A", {"144"}, set(), operator.eq) is None,
          "INSIDER_ALLOWED_FORMS is matched exactly, and 144/A is its own entry")
    # NOT CHECKED, deliberately: "an empty new_keys tracks nothing". No
    # one-line change to newly_tracked makes it fail — the loop simply does
    # not run — so it would be a green line asserting the shape of a `for`.

    print("\nholder_events — no age floor, so a new prefix is the whole record")
    state = {"forms": {f: "2026-01-01" for f in holder_events.FORMS_TRACKED
                       if f != "SC 13G"}}
    new = set(first_run.baseline(state, holder_events.FORMS_TRACKED,
                                 namespace="forms", today="2026-08-15"))
    check("the newly tracked prefix is the only one that is new",
          new == {"SC 13G"})
    kept, per = holder_events.drop_newly_tracked(
        [event("A", "SCHEDULE 13D"), event("B", "SC 13G"),
         event("C", "SC 13G/A")], new,
        set(holder_events.FORMS_TRACKED) - new)
    check("events of a newly tracked form are dropped",
          [e[2]["form"] for e in kept] == ["SCHEDULE 13D"])
    check("including the ones matching it by PREFIX", per == {"SC 13G": 2},
          "SC 13G/A is covered by the new prefix and by nothing established")
    kept, _ = holder_events.drop_newly_tracked(
        [event("A", "SCHEDULE 13D")],
        set(first_run.baseline({}, holder_events.FORMS_TRACKED,
                               namespace="forms")),
        set(holder_events.FORMS_TRACKED))
    check("the forms backfill suppresses NOTHING", len(kept) == 1)

    print("\ncomment_letters — exact matching, 180-day window")
    found = {"a": "UPLOAD", "b": "CORRESP", "c": "CORRESP"}
    kept, per = comment_letters.drop_newly_tracked(
        {"a", "b", "c"}, found, {"CORRESP"}, {"UPLOAD"})
    check("accessions of a newly tracked form are dropped", kept == {"a"})
    check("and counted", per == {"CORRESP": 2})
    kept, _ = comment_letters.drop_newly_tracked({"a", "b"}, found, set(),
                                                 {"UPLOAD", "CORRESP"})
    check("the forms backfill suppresses NOTHING", kept == {"a", "b"})

    print("\npress_monitor — two sets, two namespaces, two matchers")
    item = lambda u, f: {"uid": u, "form": f, "ticker": "T"}
    press = [item("a", "8-K"), item("b", "S-3"), item("c", "S-3/A")]
    ins = [item("x", "4"), item("y", "144")]

    state = {}
    p_b, i_b = press_monitor.baseline_forms(state, press, ins,
                                            today="2026-08-15")
    # NOT CHECKED: "the backfill suppresses nothing here". On a backfill
    # `baseline` returns nothing new, so no mutation of baseline_forms can
    # make it block — the property belongs to `baseline`, where it IS
    # checked, and asserting it again here only looks like coverage.
    check("the backfill records BOTH sets, separately",
          set(state["forms"]) == set(press_monitor.FORM_TYPES)
          and set(state["insider_forms"])
          == set(press_monitor.INSIDER_ALLOWED_FORMS),
          "a form can be tracked for one channel and not the other")

    state = {"forms": {f: "d" for f in press_monitor.FORM_TYPES if f != "S-3"},
             "insider_forms": {f: "d" for f in
                               press_monitor.INSIDER_ALLOWED_FORMS
                               if f != "144"}}
    p_b, i_b = press_monitor.baseline_forms(state, press, ins,
                                            today="2026-08-15")
    check("a newly tracked press form blocks its items, by PREFIX",
          p_b == {"b", "c"}, "S-3 and S-3/A; form_matches is a prefix match")
    check("an established press form is untouched", "a" not in p_b)
    check("the insider namespace blocks independently", i_b == {"y"},
          "144, the addition that escaped by luck on 2026-08-13")
    check("and does not block an established insider form", "x" not in i_b)

    state = {"forms": {f: "d" for f in press_monitor.FORM_TYPES},
             "insider_forms": {f: "d" for f in
                               press_monitor.INSIDER_ALLOWED_FORMS}}
    check("no new forms suppresses nothing",
          press_monitor.baseline_forms(state, press, ins, today="2026-08-15")
          == (set(), set()))

    print("\nTHE WORDING FOLLOWS THE AXIS")
    check("a forms suppression does not say 'adding a ticker'",
          "adding a form type" in
          first_run.summary("x forms", ["144"], {"144": 1}, "form type"),
          "or the reader goes to watchlist.py looking for a roster change")
    check("the backfill note names what it recorded",
          "6 form types" in first_run.backfill_note("x", 6, "form types"))
    check("and still reads correctly for companies",
          "22 companies" in first_run.backfill_note("x", 22)
          and "a company added to the roster" in first_run.backfill_note("x", 22))


def main():
    print("ABSENT VERSUS EMPTY")
    # The backfill run: the rule has just been added to a component that has
    # been running for weeks, so everything it watches is established.
    state = {}
    new = first_run.baseline(state, ["AAA", "BBB"], today="2026-08-14")
    check("an ABSENT namespace suppresses NOTHING", new == [],
          "the backfill run; these companies have been posting for weeks")
    check("the backfill still RECORDS every key",
          state["companies"] == {"AAA": "2026-08-14", "BBB": "2026-08-14"},
          "or the next run would call them all new")

    # The opposite: the rule has run and knows about nothing.
    state = {"companies": {}}
    new = first_run.baseline(state, ["AAA"], today="2026-08-14")
    check("an EMPTY namespace makes every key NEW", new == ["AAA"],
          "empty is not absent")

    print("\nA NEW KEY AGAINST A POPULATED RECORD")
    state = {"companies": {"AAA": "2026-01-01"}}
    new = first_run.baseline(state, ["AAA", "BBB", "CCC"], today="2026-08-14")
    check("only keys missing from a PRESENT dict are new", new == ["BBB", "CCC"])
    check("an established key keeps its ORIGINAL date",
          state["companies"]["AAA"] == "2026-01-01",
          "or every run would look like a first run")
    check("a new key is recorded with today's date",
          state["companies"]["BBB"] == "2026-08-14")
    check("nothing is new on the very next run",
          first_run.baseline(state, ["AAA", "BBB", "CCC"],
                             today="2026-08-15") == [],
          "the whole point: it fires once")

    print("\nNAMESPACES")
    # The axis that will bite next: a capability, not a company. When 144
    # joined the insider forms every instance of it was unseen across the
    # whole roster.
    state = {"companies": {"AAA": "2026-01-01"}}
    new = first_run.baseline(state, ["4", "144"], namespace="forms",
                             today="2026-08-14")
    check("a namespace is independent of the companies record", new == [],
          "absent 'forms' is its own backfill")
    check("the companies record is untouched by a forms baseline",
          state["companies"] == {"AAA": "2026-01-01"})
    state["forms"] = {"4": "2026-01-01"}
    check("a newly tracked FORM is new the way a company is",
          first_run.baseline(state, ["4", "144"], namespace="forms",
                             today="2026-08-14") == ["144"])

    print("\nKEYED BY CIK, BECAUSE A TICKER IS A DISPLAY LABEL")
    # Six of nineteen renamed in eighteen months. Under a ticker key a rename
    # reads as a new company and one run of its real events is suppressed —
    # and in holder_events and comment_letters marked seen in the same run,
    # so they never post at all.
    state = {}
    first_run.baseline_by_cik(state, {"FOO": ("0001000", "Foo Inc")},
                              today="2026-01-01")
    check("the record on disk is CIKs, not tickers",
          state["companies"] == {"0001000": "2026-01-01"})
    check("a RENAMED company is not newly watched",
          first_run.baseline_by_cik(state, {"BAR": ("0001000", "Bar Inc")},
                                    today="2026-08-14") == [],
          "same CIK, new symbol — this is the case that loses filings")
    check("a genuinely new company still is",
          first_run.baseline_by_cik(state, {"BAR": ("0001000", "Bar Inc"),
                                            "NEW": ("0002000", "New Co")},
                                    today="2026-08-14") == ["NEW"],
          "and it comes back as a TICKER, which is what a reader recognises")
    # The inverse, and the reason a ticker key fails in both directions:
    # SPCX was a SPAC ETF until 2026-04-07 and SpaceX from 2026-06-15.
    check("a RECYCLED ticker is a new company",
          first_run.baseline_by_cik(state, {"NEW": ("0009999", "Someone Else")},
                                    today="2026-08-15") == ["NEW"],
          "same symbol, different CIK — a ticker key would suppress it")

    print("\nTHE BACKFILL ANNOUNCES ITSELF")
    # Met head-on: the five components were dry-run against live data, all
    # five went green and all five printed nothing about the rule, so the log
    # could not distinguish a backfill from a rule that was never called.
    check("backfilled() is True while the namespace is ABSENT",
          first_run.backfilled({}) is True)
    check("and False for an EMPTY one", first_run.backfilled({"companies": {}})
          is False, "the same distinction baseline() draws")
    state = {}
    was = first_run.backfilled(state)
    first_run.baseline(state, ["AAA"], today="2026-08-14")
    check("it answers about the NEXT call, so it is False afterwards",
          was is True and first_run.backfilled(state) is False,
          "which is why the components capture it first")
    note = first_run.backfill_note("crossings", 22)
    check("the note names the component and the count",
          "crossings" in note and "22" in note)
    check("the note says nothing was suppressed", "nothing suppressed" in note,
          "a reader seeing it must not go looking for lost posts")

    print("\nTHE LINE A COMPONENT PRINTS")
    check("no line when nothing is new", first_run.summary("holders", []) == "")
    line = first_run.summary("holders", ["CORZ", "CRWV"],
                             {"CORZ": 39, "CRWV": 30})
    check("the line names the component", "holders" in line)
    # 86 messages went out because this did not happen. The count is the part
    # that makes a quiet run readable as deliberate rather than broken.
    check("the line carries a COUNT per company",
          "CORZ: 39 item(s) suppressed" in line
          and "CRWV: 30 item(s) suppressed" in line, line[:60])
    check("it says this is intended, not a loss", "not a loss" in line)
    check("a company with no count still appears",
          "AAA: recorded" in first_run.summary("x", ["AAA"]),
          "a component that suppresses state rather than items has no count")

    per_component()
    capability_axis()
    wiring()

    bad = sum(1 for r, _ in results if r == FAIL)
    print(f"\n{len(results) - bad}/{len(results)} checks passed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
