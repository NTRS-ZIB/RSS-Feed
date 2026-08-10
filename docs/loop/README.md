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

**The `tools: []` isolation is unverified as of 2026-08-09.** Agent definitions
load at session start, so the gate could not be dispatched in the session that
created it. All four fixtures were run on a general-purpose agent with tool
use restricted by instruction and confirmed by counting tool calls — clean in
practice, unenforced in principle. Re-run `score_gate.py` from a session where
`loop-gate` is registered to close this.

## Layout

```
docs/loop/rules.md                  the gate's rulebook
docs/loop/state.json                project, step, status, pending question
docs/loop/<project>/plan.md         steps and acceptance criteria
docs/loop/<project>/NN-result.md    what the worker produced
docs/loop/<project>/decisions.md    every human call, with its reasoning
docs/loop/fixtures/                 known-answer tests for the gate
```

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
python score_gate.py
```
