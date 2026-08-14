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
import sys
from datetime import date

import comment_letters
import crossings
import dilution
import first_run
import holder_events
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
              "baseline(state," in src,
              "recording is what stops the NEXT run flooding")
        check(f"{mod.__name__} prints the first-run summary",
              "summary(" in src,
              "a silent suppression reads as a broken component")
        check(f"{mod.__name__} announces the backfill run",
              "backfilled(state)" in src and "backfill_note(" in src,
              "or a rule that ran and one never wired log identically")
        # backfilled() answers about the NEXT call, so asking after baseline
        # always says False and the note never prints — green, and useless.
        check(f"{mod.__name__} asks backfilled() BEFORE baseline()",
              src.index("backfilled(state)") < src.index("baseline(state,"),
              "asked afterwards it is always False")


def event(ticker):
    """A holder_events event tuple. Only field 0 is read by the filter, but
    the arity has to match or the unpack in drop_newly_watched would pass
    here and fail in production."""
    return (ticker, "Name", {}, "ARRIVAL", ["A Holder"], 7.5, None, None, None)


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
    check("a newly watched ticker starts DISARMED",
          crossings.initial_flags("CORZ", {"CORZ"})
          == {"armed_hi": False, "armed_lo": False},
          "a company added at a 52w extreme crossed nothing while watched")
    check("an established ticker starts ARMED",
          crossings.initial_flags("RIOT", {"CORZ"})
          == {"armed_hi": True, "armed_lo": True},
          "the disarm must not leak to everyone else")
    check("the backfill run arms everybody",
          crossings.initial_flags("CORZ",
                                  set(first_run.baseline({}, ["RIOT", "CORZ"])))
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
    wiring()

    bad = sum(1 for r, _ in results if r == FAIL)
    print(f"\n{len(results) - bad}/{len(results)} checks passed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
