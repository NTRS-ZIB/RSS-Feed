# Verifying the gate's isolation

**Status: OPEN as of 2026-08-09.** Delete this file once the run below passes.

## What is unverified, and why

`.claude/agents/loop-gate.md` declares `tools: []`. That is the property the
whole design rests on: the gate cannot read the repository, so it can only
judge what the worker wrote down.

**It has never been exercised.** Agent definitions load at session start, so
`loop-gate` was not dispatchable in the session that created it — attempting it
returned `Agent type 'loop-gate' not found`. All four fixtures were instead run
on a `general-purpose` agent with tool use restricted *by instruction* and
confirmed by counting tool calls (0, 2, 2, 2). Clean in practice, unenforced in
principle.

## What re-running `score_gate.py` alone would prove

**Nothing.** It scores the verdict JSON already sitting in
`docs/loop/fixtures/verdicts/`. Those files do not change when you re-run it.
The gate must be re-dispatched and the verdicts overwritten first.

## The procedure

Run this from a session started **after** `.claude/agents/loop-gate.md` was
committed.

### 1. Confirm the agent is registered

Dispatch anything trivial with `subagent_type: "loop-gate"`. If it errors with
`Agent type 'loop-gate' not found`, the restart did not pick it up and nothing
below is meaningful — stop and work out why.

### 2. Re-dispatch each of the four cases

Read `docs/loop/fixtures/expected.json` for the case list. For each case build
the prompt with **everything inline** — the gate has no tools and cannot read
files, which is the point:

```
<rulebook>
{the full contents of docs/loop/rules.md}
</rulebook>

<acceptance-criteria>
None supplied for this case.
</acceptance-criteria>

<earlier-reports>
{contents of every report in case["reports"] except the last, oldest first,
 or "None." if there is only one}
</earlier-reports>

<current-report>
{contents of the last report in case["reports"]}
</current-report>
```

Dispatch with `subagent_type: "loop-gate"`, `run_in_background: false`. Write
the returned JSON **verbatim** to
`docs/loop/fixtures/verdicts/<case name>.json`.

**Do not edit the returned JSON.** If it is not valid JSON, save it anyway. A
gate that cannot emit JSON is a finding, not something to tidy up.

### 3. Check the thing you are actually testing

For each dispatch, confirm the result reports **`tool_uses: 0`**.

With `tools: []` this should be structurally impossible to violate. If any
dispatch shows a non-zero count, `tools: []` is not being honoured by the
platform and the isolation claim is false — that is the finding, and it is more
important than the scores.

### 4. Score

```bash
python score_gate.py
```

Expect `4/4 cases matched`.

## Interpreting the result

| Outcome | Meaning |
|---|---|
| 4/4, all `tool_uses: 0` | Isolation verified. Delete this file and the caveat in `README.md`. |
| 4/4, some `tool_uses > 0` | **Worse than a failure.** The scores are right and the isolation is fake. Report it. |
| `reconciled` escalates | The gate is behaving as a differ. Fix rule 5's wording in `rules.md`, never the fixture. |
| `silent` returns `continue` | Rule 5 no longer detects an unowned contradiction. |
| Fewer than 4 scored | A verdict is unparseable. `score_gate.py` fails closed, so this is a real result. |

## One thing that may differ from the recorded run

The four recorded verdicts were produced with the reports supplied by **file
path** and read with two `Read` calls. Under `tools: []` they arrive **inline
in the prompt**. That is a different presentation of identical content, so a
changed verdict is informative rather than alarming — but it is a change in
conditions and should be noted if the scores move.

It is also the real cost of the design: every gate dispatch in production
carries the full report text in its prompt. Worth measuring here.
