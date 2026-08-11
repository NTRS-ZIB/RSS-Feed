#!/usr/bin/env python3
"""Tests for loop_verdict. Standalone, stdlib only.

THE TWO THAT MATTER:

  * A FABRICATED QUOTE IS CAUGHT. The anti-rubber-stamp mechanism is worthless
    if the gate can invent a supporting quote, so the quote is checked against
    the report text rather than merely required to exist.

  * THE VERDICT IS DERIVED, NOT REPORTED. The gate does not get to announce
    its own conclusion. A gate that fails rule 5 and says "continue" yields
    "ask-user", because the verdict is computed from the rule results.
"""

import sys

import loop_verdict as lv

PASS, FAIL = "PASS", "FAIL"
results = []


def check(name, ok, detail=""):
    results.append((PASS if ok else FAIL, name))
    print(f"  [{PASS if ok else FAIL}] {name}" + (f" — {detail}" if detail else ""))


REPORT = """
# Result

The threshold is 18% and 2.0x the roster median, derived over 53 complete
weeks and 959 ticker-weeks. It fires 2.0 a week with a maximum of 6.

Verified by reading the committed file: `git show HEAD:watchlist.py` lists
16 feeds.
"""


def rule(i, result, quote):
    return {"id": i, "name": lv.RULES[i], "result": result, "quote": quote}


def pad(rules):
    """Fill in any rule ids missing from `rules` with n/a entries, so a test
    can pass one or two rules and still satisfy the rule-completeness check
    (validate() now raises if any of the eight rule ids is absent)."""
    present = {r["id"] for r in rules}
    return list(rules) + [rule(i, "n/a", "") for i in lv.RULES
                          if i not in present]


def v(rules, announced="continue"):
    return {"schema": lv.SCHEMA, "verdict": announced, "rules": pad(rules),
            "reason": "test"}


def main():
    print("=" * 78)
    print("loop_verdict")
    print("=" * 78)

    ok, notes = lv.validate(
        v([rule(1, "pass", "derived over 53 complete weeks")]), [REPORT])
    check("a pass whose quote is in the report survives",
          ok["rules"][0]["result"] == "pass" and not notes)

    ok, notes = lv.validate(v([rule(1, "pass", "")]), [REPORT])
    check("a pass with no quote becomes a fail",
          ok["rules"][0]["result"] == "fail", str(notes))

    ok, notes = lv.validate(
        v([rule(1, "pass", "derived over 400 years of data")]), [REPORT])
    check("A FABRICATED QUOTE BECOMES A FAIL",
          ok["rules"][0]["result"] == "fail", str(notes))

    ok, _ = lv.validate(
        v([rule(1, "pass", "DERIVED   over 53\n  complete weeks")]), [REPORT])
    check("quote matching ignores case and whitespace",
          ok["rules"][0]["result"] == "pass")

    ok, _ = lv.validate(v([rule(4, "n/a", "")]), [REPORT])
    check("n/a needs no quote", ok["rules"][0]["result"] == "n/a")

    ok, _ = lv.validate(v([rule(5, "fail", "")], announced="continue"),
                        [REPORT])
    check("THE VERDICT IS DERIVED, NOT ANNOUNCED — rule 5 fail yields ask-user",
          ok["verdict"] == "ask-user", f"got {ok['verdict']}")

    ok, _ = lv.validate(v([rule(1, "fail", ""), rule(8, "fail", "")]), [REPORT])
    check("precedence: an undeclared irreversible action outranks a revise",
          ok["verdict"] == "stop", f"got {ok['verdict']}")

    ok, _ = lv.validate(v([rule(1, "fail", ""), rule(7, "fail", "")]), [REPORT])
    check("precedence: replan outranks revise", ok["verdict"] == "replan")

    ok, _ = lv.validate(
        v([rule(1, "pass", "derived over 53 complete weeks"),
           rule(3, "pass", "git show HEAD:watchlist.py")]), [REPORT])
    check("all passes yield continue", ok["verdict"] == "continue")

    ok, notes = lv.validate(v([rule(1, "pass", "959 ticker-weeks")]), [REPORT])
    check("a pass with a quote at or above MIN_QUOTE_CHARS that is in report passes",
          ok["rules"][0]["result"] == "pass" and not notes)

    ok, notes = lv.validate(v([rule(1, "pass", "derived")]), [REPORT])
    check("a pass with a quote below MIN_QUOTE_CHARS becomes a fail",
          ok["rules"][0]["result"] == "fail" and "quote too short" in str(notes))

    check("a duplicate rule id RAISES",
          _raises(lambda: lv.validate(
              v([rule(1, "pass", "derived over 53 complete weeks"),
                 rule(1, "fail", "")]), [REPORT])))

    check("a missing schema RAISES",
          _raises(lambda: lv.validate({"rules": []}, [REPORT])))
    check("an unknown rule id RAISES",
          _raises(lambda: lv.validate(
              v([{"id": 99, "name": "x", "result": "pass", "quote": "x"}]),
              [REPORT])))
    check("an unknown result value RAISES",
          _raises(lambda: lv.validate(v([rule(1, "probably", "x")]), [REPORT])))
    check("no rules at all RAISES",
          _raises(lambda: lv.validate(
              {"schema": lv.SCHEMA, "verdict": "continue", "rules": [],
               "reason": "test"}, [REPORT])))

    check("a verdict omitting a rule RAISES",
          _raises(lambda: lv.validate(
              {"schema": lv.SCHEMA, "verdict": "continue",
               "rules": [rule(i, "n/a", "") for i in range(1, 8)],
               "reason": "test"}, [REPORT])))

    ok, _ = lv.validate(v([rule(2, "pass", "959 ticker-weeks")]),
                        ["irrelevant", REPORT])
    check("a quote may come from any of the supplied reports",
          ok["rules"][0]["result"] == "pass")

    # MARKDOWN EMPHASIS IS NOT PART OF THE CLAIM. These reports are dense with
    # bold and inline code, and requiring a gate to reproduce the markup byte
    # for byte recorded real quotes as fabricated — it cost the `reconciled`
    # fixture a case on 2026-08-11.
    ok, _ = lv.validate(
        v([rule(3, "pass", "git show HEAD:watchlist.py lists 16 feeds")]),
        [REPORT])
    check("a quote may drop the report's backticks",
          ok["rules"][0]["result"] == "pass",
          "the report writes that span inside `...`")

    ok, _ = lv.validate(
        v([rule(1, "pass", "**The threshold is 18%** and 2.0x the roster")]),
        [REPORT])
    check("a quote may ADD emphasis the report does not have",
          ok["rules"][0]["result"] == "pass",
          "stripped from both sides, so it cannot matter either way")

    # The property that must survive the change: this is the whole mechanism.
    ok, _ = lv.validate(
        v([rule(1, "pass", "derived over 92 complete weeks")]), [REPORT])
    check("A FABRICATED QUOTE IS STILL CAUGHT",
          ok["rules"][0]["result"] == "fail"
          and "does not appear" in ok["rules"][0].get("coerced", ""),
          "emphasis is dropped; content is not")

    ok, _ = lv.validate(
        v([rule(1, "pass", "derived over 53 complete weeks_and_more")]),
        [REPORT])
    check("an underscore is NOT stripped, so an identifier still has to match",
          ok["rules"][0]["result"] == "fail",
          "half these reports' nouns are snake_case identifiers")

    print("=" * 78)
    bad = sum(1 for r, _ in results if r == FAIL)
    print(f"{len(results) - bad}/{len(results)} passed")
    for r, name in results:
        if r == FAIL:
            print(f"  FAILED: {name}")
    print("=" * 78)
    return 1 if bad else 0


def _raises(fn):
    try:
        fn()
    except lv.VerdictError:
        return True
    except Exception:
        return False
    return False


if __name__ == "__main__":
    sys.exit(main())
