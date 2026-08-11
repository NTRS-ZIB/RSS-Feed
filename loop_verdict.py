#!/usr/bin/env python3
"""Validating a gate verdict, and refusing to take its word for anything.

TWO MECHANISMS, AND NEITHER IS POLITENESS.

1. EVERY PASS MUST QUOTE THE REPORT, AND THE QUOTE IS CHECKED. A subagent told
   to review something says it looks good. Requiring a quote removes the slot
   for that; checking the quote against the report removes the slot for
   inventing one. Without the second half the first is theatre.

   THE QUOTE IS VERIFIED TO EXIST AND BE SUBSTANTIAL, BUT NOT RELEVANT. A quote
   is confirmed to appear in the report and to exceed a minimum length (to
   exclude degenerate tokens like "the" or "a"), but no automatic check verifies
   that the quote actually supports the rule's claim. A gate could cite a long,
   real, unrelated sentence. That residual risk is handled by the rulebook's
   instructions, not by this module.

2. THE VERDICT IS DERIVED FROM THE RULE RESULTS, NOT READ OFF THE GATE. The
   gate reports per-rule outcomes and this module computes the verdict. A gate
   that fails rule 5 and announces "continue" yields "ask-user" anyway. This
   is the same principle the repo applies to thresholds — derived, not chosen
   — turned on the gate itself.

Fails closed throughout: anything malformed raises, and the driver treats a
raise as ask-user.
"""

import re

SCHEMA = 1

RULES = {
    1: "derived-not-chosen",
    2: "named-population",
    3: "verified-by-content",
    4: "absence-is-a-measurement",
    5: "contradiction",
    6: "caveats-surfaced",
    7: "acceptance-criteria",
    8: "irreversible-declared",
}

# What a FAILURE of each rule escalates to.
ESCALATION = {
    1: "revise", 2: "revise", 3: "revise", 4: "revise", 6: "revise",
    5: "ask-user",
    7: "replan",
    8: "stop",
}

# Most severe first. The verdict is the most severe outcome present.
PRECEDENCE = ["stop", "ask-user", "replan", "revise", "continue"]

RESULTS = ("pass", "fail", "n/a")

# Minimum length for a quote to be considered substantial. Degenerate one-word
# tokens like "the" (3), "a" (1), "it" (2) are too short to support a claim.
# Real short citations from these reports: "959 ticker-weeks" (16 chars),
# "2.0x the roster" (15), "derived over 53" (15). Short ones at the floor:
# "34/60 bars" (10, rejected). The floor of 12 kills degenerate cases while
# keeping common short citations.
MIN_QUOTE_CHARS = 12


class VerdictError(Exception):
    """A malformed verdict. The driver treats this as ask-user."""


# Backtick and asterisk are dropped before comparison. THE QUOTE IS EVIDENCE
# ABOUT WHAT THE REPORT SAID, NOT ABOUT HOW IT WAS FORMATTED, and these reports
# are dense with markdown emphasis: a gate quoting a bolded sentence or an
# inline-code span has to reproduce the markup byte for byte or be recorded as
# having fabricated the quote.
#
# It has already cost a case. On 2026-08-11 the `reconciled` fixture failed
# rule 3 because the gate quoted `SPCX still count=1, families=['market']`
# where the report writes that span inside backticks. The quote was real, the
# reading was right, and the checker called it invented.
#
# Underscore is deliberately NOT stripped. It is markdown emphasis too, but it
# is also a character in half the identifiers these reports discuss —
# `week_return_pct`, `SOURCE_FAMILY`, `filings_in_week` — and dropping it would
# let a quote match text that differs in the identifier it names, which is the
# one thing the check exists to catch.
EMPHASIS = str.maketrans("", "", "`*")


def normalise(text):
    """Lowercase, collapse whitespace, drop markdown emphasis. For quote
    comparison only."""
    return re.sub(r"\s+", " ", (text or "")).translate(EMPHASIS).strip().lower()


def derive_verdict(rules):
    outcomes = {ESCALATION[r["id"]] for r in rules if r["result"] == "fail"}
    for v in PRECEDENCE:
        if v in outcomes:
            return v
    return "continue"


def validate(verdict, report_texts):
    """Check a verdict against the reports it claims to be about.

    Returns (corrected_verdict, coercion_notes). The returned verdict's
    "verdict" key is always computed here.
    """
    if not isinstance(verdict, dict):
        raise VerdictError("verdict is not an object")
    if verdict.get("schema") != SCHEMA:
        raise VerdictError(f"verdict schema {verdict.get('schema')!r}, "
                           f"expected {SCHEMA}")
    rules = verdict.get("rules")
    if not isinstance(rules, list) or not rules:
        raise VerdictError("verdict carries no rule results")

    haystack = normalise(" ".join(report_texts))
    notes = []
    seen = set()
    for r in rules:
        if not isinstance(r, dict):
            raise VerdictError("a rule result is not an object")
        rid = r.get("id")
        if rid not in RULES:
            raise VerdictError(f"unknown rule id {rid!r}")
        if rid in seen:
            raise VerdictError(f"rule {rid} reported twice")
        seen.add(rid)
        if r.get("result") not in RESULTS:
            raise VerdictError(f"rule {rid} has result {r.get('result')!r}")

        if r["result"] != "pass":
            continue
        quote = normalise(r.get("quote"))
        if not quote:
            r["result"] = "fail"
            r["coerced"] = "passed without quoting the report"
            notes.append(f"rule {rid}: no quote")
        elif len(quote) < MIN_QUOTE_CHARS:
            r["result"] = "fail"
            r["coerced"] = "quote too short to support a claim"
            notes.append(f"rule {rid}: quote too short")
        elif quote not in haystack:
            r["result"] = "fail"
            r["coerced"] = "the quote does not appear in the report"
            notes.append(f"rule {rid}: quote not found")

    missing = sorted(set(RULES) - seen)
    if missing:
        raise VerdictError(f"verdict omits rule(s) {missing}; the rulebook "
                           f"requires all of {sorted(RULES)}. A dropped rule "
                           f"is a missing field, and a missing field must not "
                           f"resolve to a pass.")

    verdict["verdict"] = derive_verdict(rules)
    return verdict, notes
