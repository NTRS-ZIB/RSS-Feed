---
name: loop-driver
description: Runs a project through the worker-gate loop for this repo. Use when starting or resuming a loop project. Reads docs/loop/state.json, executes plan steps, dispatches the blind gate between them, and stops for judgement calls.
---

# Loop driver

You are the worker AND the driver. You do the work, and you own
`docs/loop/state.json`. Nothing else writes it.

## Before anything

```bash
git pull
python -c "
import time, uuid, loop_state as ls
s = ls.load()
rid = 'run-' + uuid.uuid4().hex[:8]
print('state:', s['status'], 'step', s['step'], 'of', s['total_steps'])
print('claimable:', ls.claim(s, rid, time.time()))
print('pending:', s['pending'])
"
```

If `load()` raises, **stop and ask the human.** Do not create a state file to
recover, and do not infer the step from which result files exist. A missing
state file is a question, not a condition to repair.

If not claimable, another driver is live. Exit.

If `pending` is set, the loop is blocked on a human answer. Present the
question again and wait.

## The cycle

1. **Beat, then work.** `ls.beat(state, run_id, time.time())`, save, then
   execute step N from `docs/loop/<project>/plan.md`.
2. **Write the result** to `docs/loop/<project>/NN-result.md`. This is the only
   channel the gate has. Anything not on the page does not exist.
3. **Dispatch the gate.** `subagent_type: "loop-gate"`,
   `run_in_background: false`, prompt built as in Task 4 Step 4, with the
   step's acceptance criteria from the plan.
4. **Validate the verdict** with `loop_verdict.validate(raw, report_texts)`.
   If it raises, treat as `ask-user` — never as a pass.
5. **Advance** with `ls.advance(state, verdict, rule=first_failing_rule)`,
   save, and act:

| Verdict | Action |
|---|---|
| `continue` | Step N+1 |
| `revise` | Redo step N addressing the cited rule. The streak guard blocks after three on the same rule |
| `replan` | Stop. The planner does not exist yet — ask the human to amend the plan |
| `ask-user` | Interrupt (below) |
| `stop` | Halt. Do not continue on any account |

## Interrupts

Stop and ask on exactly three things:

- **Preference** — only the human can answer. Editorial scope, channel choice,
  timing.
- **Irreversible or outward-facing** — merge to `main`, posting to a live
  channel, deleting a component.
- **Contradicted claims** — you contradicted something an earlier result told
  the human, who may have decided on it. The gate raises these as rule 5.

**Measurable questions are decided and reported, never asked.** A threshold
derived from a distribution needs the human's attention if it moved, not their
approval.

Shape: **recommendation first, then the evidence, then the cost of the
alternative.** A position that can be overturned, not a neutral menu.

Record the question with `ls.set_pending(...)`, save, and use
`AskUserQuestion`. **There is no timeout and no default.** When answered,
append to `docs/loop/<project>/decisions.md`:

```markdown
## <date> — <the question>

**Recommended:** <what you recommended, and why>
**Decided:** <the answer>
**Reasoning:** <what the human said, or what you inferred>
**Cost accepted:** <what this rules out, if anything>
**Authorises:** <action token, or omit this line entirely>
```

Most decisions are preferences and carry no token; omitting the
`**Authorises:**` line grants nothing, which is deliberate — a decision that
silently granted permission would be the opposite of this design. Only add it
when the decision permits an irreversible action. Tokens are
`merge:<branch>`, `post:<component>`, `delete:<path>`, and they are matched
exactly — a prefix never authorises.

Then `ls.clear_pending(state, answer)`, save, and continue.

The decisions outlive the constants. "A near-miss was seen and declined" is
what makes a threshold defensible six months later.

## Finishing

When `status` becomes `done`, write `docs/loop/<project>/summary.md`: what was
built, what was decided, what was left open. Anything left open belongs in the
repo's own docs too, in the shape that repo uses — a trap row, a rejected
entry, an `OPEN` tag — because the next project's backlog is harvested from
there.

## What you must not do

- Do not merge to `main`, post to a live channel, or delete a component
  without first running the precondition and getting exit 0:

  ```bash
  python loop_approval.py merge:<branch> docs/loop/<project>/decisions.md
  ```

  The decisions path is a required argument, not optional — there is no
  repo-wide decisions file, only the current project's.

  A non-zero exit means no recorded decision authorises it. Ask, record the
  decision with an `**Authorises:**` line, and retry. Do not proceed on the
  reasoning that the human obviously meant to approve it — that reasoning is
  exactly what the precondition exists to interrupt.
- Do not treat a passing gate verdict's stated REASON as reliable evidence.
  Only `pass` results are quote-checked; a `fail` may cite any real text in
  the report, and one observed case cited a different changed figure than the
  one it had actually detected. The verdict is load-bearing; its prose is
  advisory.
- Do not merge to `main` without an interrupt. Ever.
- Do not write `state.json` from a subagent.
- Do not treat a gate failure as a pass, however obviously right you think you
  are. That is the configuration the gate exists to prevent.
- Do not edit a result report after the gate has seen it. Write a new one.
