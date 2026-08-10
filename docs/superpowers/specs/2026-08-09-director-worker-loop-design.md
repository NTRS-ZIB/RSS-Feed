# Automating the director/worker loop

Design, 2026-08-09.

## The problem

Work on this repo currently runs as a two-model loop with a human relay in the
middle:

1. A director (Claude chat) decides what to work on and writes a prompt.
2. A worker (Claude Code) does the work and emits a markdown report.
3. The human pastes the report back to the director.
4. The director issues the next prompt, or declares the project done.
5. Repeat, then move to the next project — a build or a probe.

**The relay is the thing to automate, not the work.** Steps 1, 2 and 4 are
producing value. Step 3 is a human moving a file between two contexts.

The target: the loop runs unattended and stops only for a judgement call.

## What the separation is actually for

The weak case for a separate director — "a second model catches what the first
missed" — is not what the record shows. Over the 2026-08-08/09 session the
worker caught and reported most of its own errors unprompted: a feed URL
written into the wrong roster entry, a regex that under-matched, an overlap
figure measured against the wrong population, a claimed refactor that was a
scope change.

The separation is load-bearing for three different reasons that happen to share
a seat:

1. **A gate cannot be self-granted.** Every time the relay changed an outcome,
   it was because a *stop* existed, not because a critic was clever. "Show me
   the threshold before building" forced a re-derivation that changed the
   week's output from four names to two. A context that produced the work is
   the wrong context to judge it, not through dishonesty but through shared
   premises.
2. **The report is a lossy channel, and that is a feature.** The director only
   ever sees what was written down. Rationalisations do not survive the
   handoff. Collapse the contexts and that forcing function disappears
   silently — nothing looks different, the work just gets worse.
3. **Product ownership** — what is next, when a project is done, what needs a
   human. Not review at all.

(1) and (2) are structural and cheap. (3) needs judgement and is expensive.
**So the director seat is split rather than kept or collapsed.**

## Vocabulary

A **project** is one plan with one goal — *add the large-move section*, *probe
whether SEDAR+ carries unique disclosure*, *fix the tilde inversion*. It ends
when its acceptance criteria are met or when it is abandoned, and it produces
one directory under `docs/loop/`. Everything in this session was a project by
this definition; there were about a dozen.

A **step** is one worker turn within a project, producing one result markdown.

## Architecture

Four roles, three of them cheap.

```
planner ──> plan.md (steps + acceptance criteria)
              │
              ├─> step N ──> WORKER (main session, full repo context, tools)
              │                    │
              │                    └─> NN-result.md
              │                             │
              │                  GATE (subagent: sees ONLY the project's
              │                        result MDs + rules.md.
              │                        No repo. No session history.)
              │                             │
              │        ┌─────────┬──────────┼──────────┬─────────┐
              └ replan ┤       revise    continue   ask-user   stop
                       │         │          │          │         │
                  plan broke  worker     step N+1    human     done
                              retries               pinged
```

**The planner writes a plan once, not a prompt per step.** Prompt authoring
leaves the hot loop. The expensive seat wakes at project start, on `replan`,
and at project end. Everything between is cheap.

**`replan` preserves the reactive quality of the human loop.** When a result
invalidates the plan — *an absolute threshold cannot work at any value* — the
gate escalates and the planner rewrites the remaining steps.

**The worker keeps its context.** Only the gate needs to be blind. Rebuilding
repo context every step is a real tax for isolation the worker does not need;
knowing that `bar_figure()` existed is what made finding the same bug in
`silent()` cheap.

### Files

The relay is on disk, so a dead session resumes rather than restarts.

```
docs/loop/rules.md                  the gate's rulebook
docs/loop/state.json                project, step, status, pending question,
                                    run id + heartbeat
docs/loop/<project>/plan.md         steps and acceptance criteria
docs/loop/<project>/NN-result.md    what the worker produced
docs/loop/<project>/decisions.md    every human call, with its reasoning
```

The gate receives the current result **and the project's earlier results**.
That is what makes contradiction detection structural rather than dependent on
the worker volunteering it. It still never sees the repo or the worker's
reasoning.

**`state.json` is written by the driver — the main session — and by nothing
else.** The gate and planner are subagents that return values; they do not
touch state. One writer, so a partial write has one possible cause and the
heartbeat means anything else that finds the file busy exits rather than
merging.

## The gate's rules

Every rule is checkable from the markdown alone, and every one has a case from
this repo that bites.

### Substantive

| | Rule | The case that proves it |
|---|---|---|
| 1 | **Derived, not chosen.** Any constant, threshold or floor cites a distribution *and what it fires at* | The persistence rule's rejected first version fired 12, 8, 9 and 12 of 19 tickers. Means look fine; maxima are the firehose |
| 2 | **Named population.** Every number states what it was measured over | The repo's most-repeated trap: one morning's filings taken for 23 years of filing-time distribution; a hit rate measured on daily workflows used to predict an hourly one; a 6-of-10 overlap measured against a 276-card archive rather than the 4-card page actually read |
| 3 | **Verified by content, not exit status.** A claim that something landed cites *what was checked* | A two-part commit split that errored before truncating, so commit 1 took both parts. A feed URL that landed in the wrong company's entry while the roster validator passed |
| 4 | **Absence is a measurement.** Any "nothing found" carries a count against a floor, or names what was swept | `SPCX 34/60 bars`. And inverted: "278 cards, 0 dated" and "0 bundles, 0 chars of JS" were both broken tools reporting as findings about the source |
| 5 | **Contradiction.** Does this contradict a claim in an earlier result in this project? | Three occurrences in one session, each of which would have changed a decision already taken |

### Mechanical

6. Open caveats surfaced in the summary rather than buried.
7. The step's acceptance criteria from the plan met, and evidenced.
8. Any irreversible action declared, with its approval.

### The anti-rubber-stamp mechanism

For each rule the gate returns `pass | fail | n/a` **plus a verbatim quote from
the markdown**. A `pass` that cannot cite is recorded as a `fail`.

A subagent told to "review this" says "looks good". The output format has no
slot for that.

### What the gate does not do

It does not judge whether the work was a good idea, and it does not check
whether code is correct. It checks whether the *report* meets the repo's
evidence standard. Widen the remit and it becomes a second worker with no
tools, which is the worst of both.

### Escalation

| Fails | Verdict | Cost |
|---|---|---|
| 1, 2, 3, 4, 6 | `revise` — back to the worker, rule cited | cheap, no planner |
| 5 contradiction | `ask-user` | human, pinged |
| 7 acceptance | `replan` | planner wakes |
| 8 undeclared irreversible | `stop` | hard |

`revise` exists because "you asserted a threshold without a distribution" is a
fixable reporting failure. Waking the planner for it would make the expensive
seat the default path.

## Interrupts

### What stops the loop

Three categories, and only three:

- **Preference** — questions only the human can answer. *Is a CEO letter a
  press release? Which channel? Wait for a clean Saturday?*
- **Irreversible or outward-facing** — merge to `main`, anything that posts to
  Discord, deleting a component.
- **Contradicted claims** — the loop contradicting something it previously told
  the human, who may already have decided on the strength of it.

**Measurable questions are decided and reported, never asked.** A threshold
derived from 959 ticker-weeks does not need approval; it needs attention if it
moved.

Broken-tool self-corrections stay internal and appear in the result markdown.
They are the loop working.

### Blocking, not parking

An interrupt stops that project and waits. Parking the question and starting
another project doubles the in-flight state for throughput that is not needed.

The cost is real: a question raised at 02:00 blocks until the human sees it.

**So the plan declares its own decision points up front.** If the planner can
see at plan time that a step will need a preference call, it asks then, batched
with everything else. Three mid-project interrupts become one at the start.
This is the cheapest element of the design and probably the highest-leverage.

### Shape of an interrupt

Recommendation first, then the evidence, then the cost of the alternative. Not
a neutral menu — a position that can be overturned. *"HUT misses by 0.3 points
and I am not moving the constant"* is more useful than *"should the threshold be
17 or 18?"*.

### No auto-proceed

No timeout default, in either category. For irreversible actions that is
obvious. For preference it is the same argument: silent drift in taste is
precisely the failure that leaves no trace.

### Decisions are recorded

Each answer lands in `decisions.md` with the question, the recommendation, the
call and the reasoning. **The decisions outlive the constants.** "A near-miss
was seen and declined" is what makes a threshold defensible six months later.
The repo already believes this; it is why `docs/rejected.md` exists.

### Runaway guards

- **Step budget per project.** Exceeded → `ask-user`, not silent continuation.
- **Three consecutive `revise` on the same rule.** The worker cannot satisfy the
  gate and is burning turns. Without this, `revise → revise → revise` is an
  infinite loop that looks like progress.

## Backlog

The planner has two sources.

**Harvested.** The repo maintains its own backlog as a side effect of its
recording conventions: 17 `OPEN` and 14 `ESTIMATE` tags in the operating
footprint table, never-fired warnings such as `dilution` at 0 of 190
ticker-weeks, deferred notes such as the heartbeat whose N is unmeasured below
05:00 UTC, and watch items such as the large-move empty rate. No second
artifact to keep in sync, and it goes stale exactly when the docs do.

**Generative.** The planner also proposes work the markers do not contain, with
the human in the loop. New ideas are a preference call by definition, so they
follow the interrupt rule rather than being adopted silently.

## Error handling

The gate fails closed. Every ambiguity resolves toward escalation.

| Failure | Response |
|---|---|
| Gate cannot parse the markdown | `fail`, never `continue` — a malformed report is a reporting failure |
| Gate subagent dies or returns nothing | One retry, then `ask-user`. Never a pass |
| Worker step fails | Recorded in the result. The gate distinguishes a **source** failure from a **work** failure, as the rest of the repo does |
| Planner produces an unexecutable plan | Two `replan`s at step 1 → `ask-user` |
| `state.json` missing or corrupt | **Stop and ask. Never infer state from the files present** — inferring "has week N been produced" from directory contents is how a week gets reposted |
| Two runners at once | `state.json` carries a run id and heartbeat; a second runner exits |
| Git conflict on write | Fourteen workflows commit to `main` through the day, so non-fast-forward is the normal case. Pull before writing and reuse the existing fetch-and-retry pattern |

## Testing

CLAUDE.md: *a test that has never failed proves nothing; adding a guard means
demonstrating the failure it prevents, with the guard removed.* The gate is
demonstrated against known answers before it drives anything.

Fixtures are this session's own reports, which exist and have been verified.

**1. Must escalate.** `response-34` then `response-35`. The first asserts *"6 of
10 feed items have a newsroom twin"* in a table and reasons from it; the second
says *"the live run says 2 of 10"*. The gate must return `ask-user` on rule 5.
If it returns `continue`, the gate does not work.

**2. Must NOT escalate — the test that proves it is not a differ.**
`response-39` then `response-40`. The numbers change substantially: a threshold
derived on open-to-close is re-derived on prior-close-to-close and the week's
output goes from four names to two. A naive gate sees contradictory figures and
fires. A working gate sees the result explicitly reconciling them and passes.
**A gate failing this is worse than no gate — it would escalate the most
careful step of the session.**

**3. Must fail on citation.** A stripped report asserting a threshold with no
distribution behind it. Rule 1 `fail`, and it must not be rescued by a
confident-sounding sentence.

Test 1 is passable by flagging any changed number. Only test 2 distinguishes a
gate from a diff, and it is the test a first implementation should be expected
to fail.

**Loop dry mode.** Run the full cycle against a completed project with the
worker stubbed, and confirm the verdicts match what actually happened.

## Implementation order

Not a phasing preference — a dependency. **The gate is the only component that
can be proven before anything else exists**, because its fixtures are already
on disk.

1. **`rules.md` and the gate, against the three fixtures.** No loop, no state,
   no planner. Invoke it by hand on the fixture pairs. If it cannot pass the
   negative control, the design is wrong and nothing built on top would reveal
   that.
2. **The file relay and `state.json`.** Driver advances state, worker writes
   results, gate runs between. Still no planner: plans written by hand.
3. **Interrupts.** The three categories, the recording of decisions, resume
   from a killed session.
4. **The planner.** Backlog harvest, plan generation with up-front decision
   points, `replan` on escalation.
5. **The generative strand.** New ideas proposed with the human in the loop.

Each stage is usable without the next. Stage 2 alone already removes the
copy-paste relay, which is the stated problem.

## Out of scope

- No dashboard, no metrics, no run history UI.
- Not a general framework for other repos. This encodes *these* conventions.
- No parallel projects.
- No automatic merging. Every merge is an interrupt, permanently.

## Success criteria

1. A project runs start to finish with no human input except the interrupts the
   rules define.
2. The gate passes all three fixtures, including the negative control.
3. A killed session resumes from `state.json` without repeating a step or
   losing a decision.
4. Interrupts per project are countable and low; the plan's up-front decision
   points are the mechanism.
5. `decisions.md` is readable six months later without the session.
