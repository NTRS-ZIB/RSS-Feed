#!/usr/bin/env python3
"""Tests for loop_state. Standalone, stdlib only — see test_baseline.py.

WHAT THESE PROVE, and each is a failure the loop would otherwise have:
  * a corrupt state file RAISES rather than returning a default. Returning a
    default is how a loop restarts a project it already finished.
  * a second runner with a live heartbeat is refused, and one with a stale
    heartbeat is allowed. Both halves matter: refusing forever means a
    crashed session locks the loop out permanently.
  * three consecutive revises on the SAME rule block; a different rule resets
    the count. Without the reset, unrelated revises accumulate into a false
    block.
"""

import json
import sys
import tempfile
from pathlib import Path

import loop_state as ls

PASS, FAIL = "PASS", "FAIL"
results = []


def check(name, ok, detail=""):
    results.append((PASS if ok else FAIL, name))
    print(f"  [{PASS if ok else FAIL}] {name}" + (f" — {detail}" if detail else ""))


def raises(fn, exc):
    try:
        fn()
    except exc:
        return True
    except Exception:
        return False
    return False


def main():
    print("=" * 78)
    print("loop_state")
    print("=" * 78)

    s = ls.new_state("demo", 4, "run-a")
    check("new_state starts at step 1", s["step"] == 1)
    check("new_state is running", s["status"] == "running")
    check("new_state has no pending question", s["pending"] is None)

    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "state.json"
        ls.save(s, p)
        check("save then load round-trips", ls.load(p) == s)

        p.write_text("{not json", encoding="utf-8")
        check("corrupt state RAISES rather than defaulting",
              raises(lambda: ls.load(p), ls.LoopStateError))

        p.write_text(json.dumps({"schema": ls.SCHEMA, "project": "x"}),
                     encoding="utf-8")
        check("missing keys RAISE",
              raises(lambda: ls.load(p), ls.LoopStateError))

        p.write_text(json.dumps(dict(s, schema=ls.SCHEMA + 1)), encoding="utf-8")
        check("a future schema RAISES",
              raises(lambda: ls.load(p), ls.LoopStateError))

        missing = Path(d) / "absent.json"
        check("a missing state file RAISES",
              raises(lambda: ls.load(missing), ls.LoopStateError))

    live = ls.beat(ls.new_state("demo", 4, "run-a"), "run-a", 1000.0)
    check("the owning runner may claim", ls.claim(live, "run-a", 1000.0))
    check("a second runner is refused while the heartbeat is live",
          not ls.claim(live, "run-b", 1000.0 + ls.HEARTBEAT_STALE_S - 1))
    check("a second runner may claim once the heartbeat is stale",
          ls.claim(live, "run-b", 1000.0 + ls.HEARTBEAT_STALE_S + 1))

    a = ls.advance(ls.new_state("demo", 3, "r"), "continue")
    check("continue advances the step", a["step"] == 2)

    b = ls.new_state("demo", 1, "r")
    b = ls.advance(b, "continue")
    check("continue past the last step finishes the project",
          b["status"] == "done")

    c = ls.new_state("demo", 9, "r")
    for _ in range(3):
        c = ls.advance(c, "revise", rule=2)
    check("three revises on one rule block the loop", c["status"] == "blocked")
    check("and the blocked reason names the rule", "2" in str(c["blocked_reason"]))

    d2 = ls.new_state("demo", 9, "r")
    d2 = ls.advance(d2, "revise", rule=2)
    d2 = ls.advance(d2, "revise", rule=4)
    check("a different rule resets the streak",
          d2["revise_streak"]["count"] == 1 and d2["status"] == "running")

    e = ls.advance(ls.new_state("demo", 9, "r"), "revise", rule=1)
    e = ls.advance(e, "continue")
    check("continue clears the streak", e["revise_streak"]["count"] == 0)

    check("an unknown verdict RAISES",
          raises(lambda: ls.advance(ls.new_state("d", 2, "r"), "looks-fine"),
                 ls.LoopStateError))

    f = ls.set_pending(ls.new_state("demo", 4, "r"), "Split by direction?",
                       "No — the asymmetry is the ten-week window",
                       "2026-08-09T12:00:00Z")
    check("set_pending blocks the loop", f["status"] == "blocked")
    check("set_pending records the recommendation",
          "ten-week" in f["pending"]["recommendation"])
    g = ls.clear_pending(f, "agreed, do not split")
    check("clear_pending unblocks", g["status"] == "running")
    check("clear_pending drops the question", g["pending"] is None)

    print("=" * 78)
    bad = sum(1 for r, _ in results if r == FAIL)
    print(f"{len(results) - bad}/{len(results)} passed")
    for r, name in results:
        if r == FAIL:
            print(f"  FAILED: {name}")
    print("=" * 78)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
