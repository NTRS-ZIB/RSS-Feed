#!/usr/bin/env python3
"""Tests for first_run.baseline. Standalone, no network.

THE ONE THAT MATTERS: an ABSENT namespace and an EMPTY one mean opposite
things. Absent is the backfill run and nothing is new; empty means the rule
has run before and knows about nothing, so everything is. Reversing them
either floods on the day the rule lands or silently suppresses a real backlog
forever, and neither announces itself in the logs.
"""

import sys

import first_run

PASS, FAIL = "PASS", "FAIL"
results = []


def check(name, ok, detail=""):
    results.append((PASS if ok else FAIL, name))
    print(f"  [{PASS if ok else FAIL}] {name}" + (f" - {detail}" if detail else ""))


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

    bad = sum(1 for r, _ in results if r == FAIL)
    print(f"\n{len(results) - bad}/{len(results)} checks passed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
