# Dry run — digest large-move (replay)

A replay of a completed project. The worker is stubbed: each step's result
already exists. This exercises the driver, the gate and the state machine
against real reports with a known outcome.

**It also exercises rule 7 for the first time.** Every fixture in
`docs/loop/fixtures/` supplies no acceptance criteria, so rule 7 has only ever
returned `n/a`. Here criteria are supplied and the rule is live.

## Step 1 — Review the first live digest

**Acceptance:** reports whether each of the three named checks passed, with
evidence; distinguishes a check that passed from one that could not be run.

## Step 2 — Derive a large-move threshold

**Acceptance:** the threshold cites a distribution and what it fires at per
week; names the population; states any caveat about the measurement basis.

## Step 3 — Build the five changes

**Acceptance:** states what was verified and how; declares any irreversible
action; reconciles any figure that changed since step 2.
