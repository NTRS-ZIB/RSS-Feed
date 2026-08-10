#!/usr/bin/env python3
"""Score recorded gate verdicts against the known answers.

The gate is a subagent, so its verdicts are produced by dispatch rather than by
this script. The driver writes each verdict to
docs/loop/fixtures/verdicts/<case>.json and this scores them — so the
ASSERTION is mechanical and versioned even though the generation is not.

Re-run after any change to rules.md. A rulebook edit that breaks the negative
control is exactly the regression this exists to catch.
"""

import json
import sys
from pathlib import Path

import loop_verdict as lv

FIXTURES = Path("docs/loop/fixtures")
VERDICTS = FIXTURES / "verdicts"

PASS, FAIL = "PASS", "FAIL"


def main():
    spec = json.loads((FIXTURES / "expected.json").read_text(encoding="utf-8"))
    results = []
    print("=" * 78)
    print("GATE SCORE")
    print("=" * 78)

    for case in spec["cases"]:
        name = case["name"]
        path = VERDICTS / f"{name}.json"
        if not path.exists():
            print(f"  [{FAIL}] {name}: no recorded verdict at {path}")
            print(f"         dispatch the gate on this case first")
            results.append(False)
            continue

        reports = [(FIXTURES / r).read_text(encoding="utf-8")
                   for r in case["reports"]]
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            verdict, notes = lv.validate(raw, reports)
        except (json.JSONDecodeError, lv.VerdictError) as e:
            # Fails closed: an unparseable verdict is a failed case, never a
            # skipped one.
            print(f"  [{FAIL}] {name}: verdict unusable — {e}")
            results.append(False)
            continue

        got = verdict["verdict"]
        want = case["expect_verdict"]
        fails = sorted(r["id"] for r in verdict["rules"]
                       if r["result"] == "fail")
        want_fails = sorted(case["expect_rule_fails"])

        ok = got == want and fails == want_fails
        results.append(ok)
        print(f"  [{PASS if ok else FAIL}] {name}: verdict {got} "
              f"(want {want}), rule fails {fails} (want {want_fails})")
        if notes:
            print(f"         coerced: {'; '.join(notes)}")
        if not ok:
            print(f"         why this case exists: {case['why']}")

    print("=" * 78)
    bad = results.count(False)
    print(f"{len(results) - bad}/{len(results)} cases matched")
    print("=" * 78)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
