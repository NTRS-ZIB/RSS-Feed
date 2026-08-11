# The work loop

Removes the copy-paste relay between a director and a worker. A project runs
start to finish and stops only for a judgement call.

Design: [`../superpowers/specs/2026-08-09-director-worker-loop-design.md`](../superpowers/specs/2026-08-09-director-worker-loop-design.md)

## Roles

| | Who | Sees |
|---|---|---|
| **Worker/driver** | the main session | everything |
| **Gate** | a subagent, `tools: []` | one project's result reports and the rulebook. No repository |
| **Planner** | not built yet | plans are written by hand |

**The `tools: []` isolation was exercised on 2026-08-11 and the fixtures score
4/4.** All four cases were re-dispatched under `subagent_type: loop-gate` with
the rulebook and reports inline, and every dispatch reported `tool_uses: 0`.

**What that does and does not establish.** Six dispatches made zero tool calls,
including one that explicitly instructed the gate to read a file off disk —
it made no call and replied that it had no file-reading tool. That is as far
as this can be taken from inside a dispatch, and the residual is worth naming:
`.claude/agents/loop-gate.md` also *tells* the gate it has no tools, so a
well-behaved model reading its own instructions is indistinguishable from a
platform-enforced empty tool list. No evidence against isolation; no proof of
enforcement.

**Two things the run changed.** Rule 5 was rewritten because the gate passed
the positive control by quoting a figure both reports agreed on — agreement is
always available to quote, so that rule could never fail. And `loop_verdict`
now drops markdown emphasis before comparing quotes, because the `reconciled`
case failed on a real quote whose backticks the gate had not reproduced.

**Re-running `score_gate.py` alone proves nothing about the gate** — it scores
verdict JSON already on disk. Re-dispatch the fixtures first whenever
`rules.md` changes.

## Layout

```
docs/loop/rules.md                  the gate's rulebook
docs/loop/state.json                project, step, status, pending question
docs/loop/<project>/plan.md         steps and acceptance criteria
docs/loop/<project>/NN-result.md    what the worker produced
docs/loop/<project>/decisions.md    every human call, with its reasoning
docs/loop/fixtures/                 known-answer tests for the gate
```

`decisions.md` is per project, not repo-wide. `loop_approval.py` takes that
path as a required CLI argument — there is no default, so the driver must
name the current project's file every time it checks for authorisation.

## Running it

Start or resume with the `loop-driver` skill. It reads `state.json` and
continues from there.

To start a project: write `docs/loop/<project>/plan.md`, then

```bash
python -c "
import loop_state as ls
ls.save(ls.new_state('<project>', <total_steps>, 'run-manual'))
"
```

## Checking the gate still works

After any edit to `rules.md`:

```bash
python score_gate.py
```

Re-dispatch the fixtures first if the rulebook changed — a stale verdict scores
the old rulebook. **The negative control is the case that matters**: a gate that
escalates the `reconciled` pair is a differ, not a gate.

## Tests

```bash
python test_loop_state.py
python test_loop_verdict.py
python test_loop_approval.py
python score_gate.py
```

## Dry run, 2026-08-09

Replayed the digest large-move project — three real reports, worker stubbed,
gate and state machine live. A separate state file (`dry-run-state.json`) so it
cannot disturb a live project.

| step | verdict | rules failed | rule 7 |
|---|---|---|---|
| 1 — review the first live digest | `continue` | none | pass |
| 2 — derive a large-move threshold | `continue` | none | pass |
| 3 — build the five changes | `continue` | none | pass |

Final state: **`done`**.

**Two things this run establishes that the fixtures could not.**

Rule 7 had returned `n/a` in every fixture, because no fixture supplies
acceptance criteria. Here they are supplied and it is live on all three steps.
A rule that has only ever returned `n/a` is indistinguishable from one that is
broken — the same trap this repo records about an EDGAR form type matching
nothing.

And step 3 corrects step 2's own figures: the threshold survives being
re-derived on a different return definition but the week's output goes from
four names to two, and the report says so. **Rule 5 passed.** That is the gate
distinguishing an owned correction from a silent one, on a real sequence rather
than a constructed pair — the property the whole design rests on, checked twice
now by different means.

**What it does not establish.** The worker was stubbed, so nothing here
exercises a `revise`, `replan` or `ask-user` path end to end; those are covered
only by `test_loop_state.py`. And the reports were written for a human rather
than against acceptance criteria, so rule 7 passing says the criteria were
satisfiable in hindsight, not that a worker aiming at them would satisfy them.
