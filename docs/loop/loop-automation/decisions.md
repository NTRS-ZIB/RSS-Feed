# Decisions — loop-automation

The build of the loop itself, recorded in the loop's own format.

## 2026-08-09 — Should the director seat be split, or kept whole?

**Recommended:** split it. The seat does three jobs — a gate that cannot be
self-granted, a lossy channel that forces the work onto the page, and product
ownership. Only the third needs judgement.
**Decided:** split — a cheap structural gate every step, an expensive planner
at boundaries.
**Reasoning:** paying planner prices for gate work on every step, forever.

## 2026-08-09 — What stops the loop and asks a human?

**Recommended:** preference, irreversible, and contradicted claims.
**Decided:** as recommended.
**Reasoning:** a measurable question decided from 959 ticker-weeks needs
attention if it moved, not approval. A contradicted claim stops because a
decision may already have been taken on the strength of it.

## 2026-08-09 — Rule 8: does the name or the body govern?

**Recommended:** the name. The gate checks the action is DECLARED; approval
moves to a precondition the driver runs before acting.
**Decided:** the name.
**Reasoning:** "the report must state it was approved" is satisfiable by
typing the sentence — a formatting rule wearing a safety rule's name, and the
same hole Task 2 had closed by verifying quotes rather than requiring them.
**Cost accepted:** approval is a check rather than an interlock. A driver that
skips the call is not stopped; it is made visible.

## 2026-08-09 — Merge the loop automation to main?

**Recommended:** merge. Six tasks, final whole-branch review clean after one
fix wave, 56/56 unit assertions and 4/4 gate fixtures passing.
**Decided:** yes.
**Reasoning:** the four Important findings the final review caught were all
cross-file, all fixed and re-reviewed. The remaining limits are recorded in
the code and the README rather than left implicit.
**Cost accepted:** the `tools: []` isolation is unverified until a session
where `loop-gate` is registered; the quote check does not verify relevance;
the stubbed dry run never exercised revise, replan or ask-user end to end.
**Authorises:** merge:loop-automation
