# Director/Worker Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the human copy-paste relay between the director and the worker, so a project runs start to finish and stops only for a judgement call.

**Architecture:** The driver (the main Claude Code session) is the worker and owns `docs/loop/state.json`. After each worker step it dispatches a **blind gate** — a subagent given only the project's result markdown and a rulebook, with no repo access and no session history. The gate returns per-rule results with verbatim quotes; a Python module verifies each quote actually appears in the report and *derives* the verdict from the rule results rather than trusting the gate's own summary.

**Tech Stack:** Python 3.12 standard library only. No third-party dependencies, no test framework — tests follow the repo's existing `test_baseline.py` convention (standalone script, `check()` helper, `return 1 if bad else 0`). Markdown for the rulebook, the skill and the relay artifacts.

## Scope

Spec stages 1–3 only: rulebook, gate, file relay, state, interrupts. **Stages 4–5 (planner, generative backlog) are a separate plan** — they depend on this working and change nothing in it. Plans are written by hand until then, which is what the human does today anyway.

## Global Constraints

- **The gate fails closed.** Every ambiguity — unparseable report, dead subagent, missing field — resolves to a non-`continue` verdict. Never a pass.
- **No auto-proceed.** No timeout default on any interrupt, preference or irreversible.
- **One writer.** Only the driver writes `state.json`. Gate and planner return values and never touch it.
- **Never infer state from files present.** A missing or corrupt `state.json` stops the loop and asks. Inferring "has step N run" from directory contents is how a week gets reposted.
- **No pytest.** Standalone test scripts, `check(name, ok, detail)`, PASS/FAIL lines, non-zero exit on failure. Match `test_baseline.py`.
- **Standard library only.** The repo installs dependencies ad hoc per workflow; these modules must import nothing outside stdlib.
- **No automatic merging.** Every merge to `main` is an interrupt, permanently.
- **Pull before writing.** Fourteen workflows commit to `main` through the day; non-fast-forward is the normal case.

---

## File Structure

| File | Responsibility |
|---|---|
| `loop_state.py` | Read, write, validate and advance `state.json`. Single-writer claim via heartbeat. Nothing else. |
| `loop_verdict.py` | Validate a gate verdict, verify every quote against the report text, coerce unsupported passes to fails, derive the verdict from rule results. |
| `test_loop_state.py` | Standalone tests for `loop_state`. |
| `test_loop_verdict.py` | Standalone tests for `loop_verdict`, including the fabricated-quote case. |
| `score_gate.py` | Compare recorded gate verdicts against expected verdicts for the fixtures. |
| `docs/loop/rules.md` | The gate's rulebook. Read by the gate, and by a human. |
| `docs/loop/README.md` | How the loop works and how to drive it by hand. |
| `docs/loop/fixtures/*.md` | Versioned copies of the known-answer reports. |
| `docs/loop/fixtures/expected.json` | Expected verdict per fixture. |
| `.claude/agents/loop-gate.md` | The gate subagent definition. |
| `.claude/skills/loop-driver/SKILL.md` | The driver's instructions: the cycle, interrupts, resume. |

`loop_state.py` and `loop_verdict.py` are split because they fail differently: state is a file-integrity concern, verdict is a trust concern. A change to the rulebook touches one and not the other.

---

### Task 1: Loop state

**Files:**
- Create: `loop_state.py`
- Test: `test_loop_state.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `SCHEMA: int`, `STATE_PATH: Path`, `HEARTBEAT_STALE_S: int`, `LoopStateError(Exception)`, `new_state(project: str, total_steps: int, run_id: str) -> dict`, `load(path: Path = STATE_PATH) -> dict`, `save(state: dict, path: Path = STATE_PATH) -> None`, `claim(state: dict, run_id: str, now: float) -> bool`, `beat(state: dict, run_id: str, now: float) -> dict`, `advance(state: dict, verdict: str, rule: int | None = None) -> dict`, `set_pending(state: dict, question: str, recommendation: str, asked_at: str) -> dict`, `clear_pending(state: dict, answer: str) -> dict`.

- [ ] **Step 1: Write the failing test**

Create `test_loop_state.py`:

```python
#!/usr/bin/env python3
"""Tests for loop_state. Standalone, stdlib only — see test_baseline.py.

WHAT THESE PROVE, and each is a failure the loop would otherwise have:
  * a corrupt state file RAISES rather than returning a default. Returning a
    default is how a loop restarts a project it already finished.
  * a second runner with a live heartbeat is refused, and one with a stale
    heartbeat is allowed. Both halves matter: refusing forever means a
    crashed session locks the loop out permanently.
  * three consecutive revises on the SAME rule block; a different rule resets
    the count. Without the reset, unrelated revises accumulate into a false
    block.
"""

import json
import sys
import tempfile
from pathlib import Path

import loop_state as ls

PASS, FAIL = "PASS", "FAIL"
results = []


def check(name, ok, detail=""):
    results.append((PASS if ok else FAIL, name))
    print(f"  [{PASS if ok else FAIL}] {name}" + (f" — {detail}" if detail else ""))


def raises(fn, exc):
    try:
        fn()
    except exc:
        return True
    except Exception:
        return False
    return False


def main():
    print("=" * 78)
    print("loop_state")
    print("=" * 78)

    s = ls.new_state("demo", 4, "run-a")
    check("new_state starts at step 1", s["step"] == 1)
    check("new_state is running", s["status"] == "running")
    check("new_state has no pending question", s["pending"] is None)

    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "state.json"
        ls.save(s, p)
        check("save then load round-trips", ls.load(p) == s)

        p.write_text("{not json", encoding="utf-8")
        check("corrupt state RAISES rather than defaulting",
              raises(lambda: ls.load(p), ls.LoopStateError))

        p.write_text(json.dumps({"schema": ls.SCHEMA, "project": "x"}),
                     encoding="utf-8")
        check("missing keys RAISE",
              raises(lambda: ls.load(p), ls.LoopStateError))

        p.write_text(json.dumps(dict(s, schema=ls.SCHEMA + 1)), encoding="utf-8")
        check("a future schema RAISES",
              raises(lambda: ls.load(p), ls.LoopStateError))

        missing = Path(d) / "absent.json"
        check("a missing state file RAISES",
              raises(lambda: ls.load(missing), ls.LoopStateError))

    live = ls.beat(ls.new_state("demo", 4, "run-a"), "run-a", 1000.0)
    check("the owning runner may claim", ls.claim(live, "run-a", 1000.0))
    check("a second runner is refused while the heartbeat is live",
          not ls.claim(live, "run-b", 1000.0 + ls.HEARTBEAT_STALE_S - 1))
    check("a second runner may claim once the heartbeat is stale",
          ls.claim(live, "run-b", 1000.0 + ls.HEARTBEAT_STALE_S + 1))

    a = ls.advance(ls.new_state("demo", 3, "r"), "continue")
    check("continue advances the step", a["step"] == 2)

    b = ls.new_state("demo", 1, "r")
    b = ls.advance(b, "continue")
    check("continue past the last step finishes the project",
          b["status"] == "done")

    c = ls.new_state("demo", 9, "r")
    for _ in range(3):
        c = ls.advance(c, "revise", rule=2)
    check("three revises on one rule block the loop", c["status"] == "blocked")
    check("and the blocked reason names the rule", "2" in str(c["blocked_reason"]))

    d2 = ls.new_state("demo", 9, "r")
    d2 = ls.advance(d2, "revise", rule=2)
    d2 = ls.advance(d2, "revise", rule=4)
    check("a different rule resets the streak",
          d2["revise_streak"]["count"] == 1 and d2["status"] == "running")

    e = ls.advance(ls.new_state("demo", 9, "r"), "revise", rule=1)
    e = ls.advance(e, "continue")
    check("continue clears the streak", e["revise_streak"]["count"] == 0)

    check("an unknown verdict RAISES",
          raises(lambda: ls.advance(ls.new_state("d", 2, "r"), "looks-fine"),
                 ls.LoopStateError))

    f = ls.set_pending(ls.new_state("demo", 4, "r"), "Split by direction?",
                       "No — the asymmetry is the ten-week window",
                       "2026-08-09T12:00:00Z")
    check("set_pending blocks the loop", f["status"] == "blocked")
    check("set_pending records the recommendation",
          "ten-week" in f["pending"]["recommendation"])
    g = ls.clear_pending(f, "agreed, do not split")
    check("clear_pending unblocks", g["status"] == "running")
    check("clear_pending drops the question", g["pending"] is None)

    print("=" * 78)
    bad = sum(1 for r, _ in results if r == FAIL)
    print(f"{len(results) - bad}/{len(results)} passed")
    for r, name in results:
        if r == FAIL:
            print(f"  FAILED: {name}")
    print("=" * 78)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python test_loop_state.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'loop_state'`

- [ ] **Step 3: Write minimal implementation**

Create `loop_state.py`:

```python
#!/usr/bin/env python3
"""The loop's state file. One writer: the driver.

WHY IT RAISES RATHER THAN DEFAULTING. press_monitor.load_state() returns a
fresh baseline when state.json is unreadable, and that is right there — a lost
baseline costs one silent run. Here it is wrong: a lost loop state would
restart a project that already finished, or re-run a step that already merged.
Absence of state is not a state; it is a question for the human.

THE HEARTBEAT IS TWO-SIDED. Refusing a second runner while the first is live
prevents two drivers writing the same file. Allowing one once the heartbeat is
stale prevents a crashed session locking the loop out forever. Only one of
those is obvious and both are load-bearing.
"""

import json
from pathlib import Path

SCHEMA = 1
STATE_PATH = Path("docs/loop/state.json")

# Longer than a slow worker step, shorter than a human noticing a dead loop.
# A driver beats before each step, so anything past this is a dead session.
HEARTBEAT_STALE_S = 900

VERDICTS = ("continue", "revise", "replan", "ask-user", "stop")
REVISE_LIMIT = 3

REQUIRED = ("schema", "project", "step", "total_steps", "status", "run_id",
            "heartbeat", "pending", "revise_streak")


class LoopStateError(Exception):
    """Anything wrong with the state file. Always fatal to the loop."""


def new_state(project, total_steps, run_id):
    return {
        "schema": SCHEMA,
        "project": project,
        "step": 1,
        "total_steps": total_steps,
        "status": "running",
        "run_id": run_id,
        "heartbeat": 0.0,
        "pending": None,
        "blocked_reason": None,
        "revise_streak": {"rule": None, "count": 0},
    }


def load(path=STATE_PATH):
    path = Path(path)
    if not path.exists():
        raise LoopStateError(f"{path} does not exist — start a project or "
                             f"resume by hand. Do not infer state from the "
                             f"files present.")
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise LoopStateError(f"{path} is unreadable: {e}") from e
    if not isinstance(state, dict):
        raise LoopStateError(f"{path} is not an object")
    missing = [k for k in REQUIRED if k not in state]
    if missing:
        raise LoopStateError(f"{path} is missing {', '.join(missing)}")
    if state["schema"] != SCHEMA:
        raise LoopStateError(f"{path} is schema {state['schema']}, "
                             f"this code writes {SCHEMA}")
    return state


def save(state, path=STATE_PATH):
    """Write via a temporary file so a killed process cannot truncate state."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(state, indent=1) + "\n", encoding="utf-8")
    tmp.replace(path)


def claim(state, run_id, now):
    """True if `run_id` may drive the loop."""
    if state.get("run_id") == run_id:
        return True
    return (now - float(state.get("heartbeat") or 0)) > HEARTBEAT_STALE_S


def beat(state, run_id, now):
    state["run_id"] = run_id
    state["heartbeat"] = float(now)
    return state


def advance(state, verdict, rule=None):
    if verdict not in VERDICTS:
        raise LoopStateError(f"unknown verdict {verdict!r}")

    if verdict == "continue":
        state["revise_streak"] = {"rule": None, "count": 0}
        state["step"] += 1
        if state["step"] > state["total_steps"]:
            state["status"] = "done"
        return state

    if verdict == "revise":
        streak = state["revise_streak"]
        if streak.get("rule") == rule:
            streak["count"] += 1
        else:
            state["revise_streak"] = {"rule": rule, "count": 1}
        if state["revise_streak"]["count"] >= REVISE_LIMIT:
            state["status"] = "blocked"
            state["blocked_reason"] = (
                f"{REVISE_LIMIT} consecutive revise verdicts on rule {rule} — "
                f"the worker cannot satisfy the gate and is burning turns")
        return state

    state["status"] = {"replan": "replan",
                       "ask-user": "blocked",
                       "stop": "stopped"}[verdict]
    if verdict != "replan":
        state["blocked_reason"] = state.get("blocked_reason") or verdict
    return state


def set_pending(state, question, recommendation, asked_at):
    state["status"] = "blocked"
    state["pending"] = {"question": question,
                        "recommendation": recommendation,
                        "asked_at": asked_at}
    return state


def clear_pending(state, answer):
    if not state.get("pending"):
        raise LoopStateError("no pending question to clear")
    state["pending"] = None
    state["blocked_reason"] = None
    state["status"] = "running"
    state["last_answer"] = answer
    return state
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python test_loop_state.py`
Expected: PASS, `21/21 passed`, exit 0

- [ ] **Step 5: Commit**

```bash
git pull
git add loop_state.py test_loop_state.py
git commit -m "Loop state: raise rather than default, and a two-sided heartbeat

press_monitor.load_state() returns a fresh baseline when state.json is
unreadable and that is right there — a lost baseline costs one silent run.
Here it is wrong: a lost loop state would restart a finished project or re-run
a step that already merged. Absence of state is a question for the human.

The heartbeat refuses a second runner while the first is live AND admits one
once it is stale. Only the first is obvious; without the second a crashed
session locks the loop out forever.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: Verdict validation

**Files:**
- Create: `loop_verdict.py`
- Test: `test_loop_verdict.py`

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: `SCHEMA: int`, `RULES: dict[int, str]`, `ESCALATION: dict[int, str]`, `PRECEDENCE: list[str]`, `VerdictError(Exception)`, `normalise(text: str) -> str`, `derive_verdict(rules: list[dict]) -> str`, `validate(verdict: dict, report_texts: list[str]) -> tuple[dict, list[str]]`.
- `validate` returns `(corrected_verdict, coercion_notes)`. The corrected verdict always has key `"verdict"` set by `derive_verdict`, never by the gate.

- [ ] **Step 1: Write the failing test**

Create `test_loop_verdict.py`:

```python
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


def v(rules, announced="continue"):
    return {"schema": lv.SCHEMA, "verdict": announced, "rules": rules,
            "reason": "test"}


def rule(i, result, quote):
    return {"id": i, "name": lv.RULES[i], "result": result, "quote": quote}


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

    check("a missing schema RAISES",
          _raises(lambda: lv.validate({"rules": []}, [REPORT])))
    check("an unknown rule id RAISES",
          _raises(lambda: lv.validate(
              v([{"id": 99, "name": "x", "result": "pass", "quote": "x"}]),
              [REPORT])))
    check("an unknown result value RAISES",
          _raises(lambda: lv.validate(v([rule(1, "probably", "x")]), [REPORT])))
    check("no rules at all RAISES",
          _raises(lambda: lv.validate(v([]), [REPORT])))

    ok, _ = lv.validate(v([rule(2, "pass", "959 ticker-weeks")]),
                        ["irrelevant", REPORT])
    check("a quote may come from any of the supplied reports",
          ok["rules"][0]["result"] == "pass")

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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python test_loop_verdict.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'loop_verdict'`

- [ ] **Step 3: Write minimal implementation**

Create `loop_verdict.py`:

```python
#!/usr/bin/env python3
"""Validating a gate verdict, and refusing to take its word for anything.

TWO MECHANISMS, AND NEITHER IS POLITENESS.

1. EVERY PASS MUST QUOTE THE REPORT, AND THE QUOTE IS CHECKED. A subagent told
   to review something says it looks good. Requiring a quote removes the slot
   for that; checking the quote against the report removes the slot for
   inventing one. Without the second half the first is theatre.

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


class VerdictError(Exception):
    """A malformed verdict. The driver treats this as ask-user."""


def normalise(text):
    """Lowercase, collapse whitespace. For quote comparison only."""
    return re.sub(r"\s+", " ", (text or "")).strip().lower()


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
        elif quote not in haystack:
            r["result"] = "fail"
            r["coerced"] = "the quote does not appear in the report"
            notes.append(f"rule {rid}: quote not found")

    verdict["verdict"] = derive_verdict(rules)
    return verdict, notes
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python test_loop_verdict.py`
Expected: PASS, `14/14 passed`, exit 0

- [ ] **Step 5: Commit**

```bash
git pull
git add loop_verdict.py test_loop_verdict.py
git commit -m "Verdict validation: check the quote, derive the verdict

A subagent told to review something says it looks good. Requiring a quote
removes the slot for that; CHECKING the quote against the report removes the
slot for inventing one. Without the second half the first is theatre.

And the verdict is computed from the rule results rather than read off the
gate — a gate that fails the contradiction rule and announces continue yields
ask-user anyway. Same principle the repo applies to thresholds, turned on the
gate itself.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: The rulebook and the fixtures

**Files:**
- Create: `docs/loop/rules.md`
- Create: `docs/loop/fixtures/contradiction-a.md`, `contradiction-b.md`, `reconciled-a.md`, `reconciled-b.md`, `uncited-threshold.md`
- Create: `docs/loop/fixtures/expected.json`

**Interfaces:**
- Consumes: `loop_verdict.RULES` ids and names — `rules.md` must use the same eight ids and the same short names.
- Produces: fixture files and their expected verdicts, consumed by Task 4's `score_gate.py`.

- [ ] **Step 1: Copy the four real fixtures out of the scratchpad**

These are this session's actual reports. They are copied into the repo so they are versioned — a fixture living in a temp directory is a fixture that disappears.

```bash
SP="$HOME/AppData/Local/Temp/claude/C--Users-zamzi-OneDrive-Documents-Claude-Infra-Monitor/82ae5946-b5da-4d88-b13e-01ae321e2c09/scratchpad"
mkdir -p docs/loop/fixtures
cp "$SP/response-34-abtc-and-dedupe-design.md" docs/loop/fixtures/contradiction-a.md
cp "$SP/response-35-cross-host-dedupe.md"      docs/loop/fixtures/contradiction-b.md
cp "$SP/response-39-largemove-threshold.md"    docs/loop/fixtures/reconciled-a.md
cp "$SP/response-40-five-changes.md"           docs/loop/fixtures/reconciled-b.md
```

- [ ] **Step 2: Verify the fixtures contain what the plan claims**

Run:

```bash
grep -c "6 of 10" docs/loop/fixtures/contradiction-a.md
grep -c "2 of 10" docs/loop/fixtures/contradiction-b.md
grep -c "18% and 2.0" docs/loop/fixtures/reconciled-a.md
grep -c "hold" docs/loop/fixtures/reconciled-b.md
```

Expected: all non-zero. If any is zero the fixture is wrong and the whole test suite is measuring nothing — stop and re-identify the file.

- [ ] **Step 3: Write the uncited fixture by hand**

Create `docs/loop/fixtures/uncited-threshold.md`:

```markdown
# Volume floor for the spike monitor

Set the minimum normalised volume to 50,000 shares.

Fifty thousand is a sensible floor for this roster — below that the ratio is
dominated by a handful of odd lots and the signal is not worth posting. The
larger names clear it every session and the smaller ones clear it most days,
so it will not suppress anything that matters.

Implemented in `volume_spike.py` and the workflow ran green.
```

This asserts a constant with no distribution, no count of what it fires at, and
claims success from a workflow going green rather than from what it produced.
Rules 1 and 3 must fail.

- [ ] **Step 4: Write the expected verdicts**

Create `docs/loop/fixtures/expected.json`:

```json
{
 "schema": 1,
 "cases": [
  {
   "name": "contradiction",
   "reports": ["contradiction-a.md", "contradiction-b.md"],
   "expect_verdict": "ask-user",
   "expect_rule_fails": [5],
   "why": "contradiction-a states 6 of 10 feed items have a newsroom twin and reasons from it; contradiction-b says the live run is 2 of 10. The gate must catch that the earlier claim was wrong, because a decision was taken on it."
  },
  {
   "name": "reconciled",
   "reports": ["reconciled-a.md", "reconciled-b.md"],
   "expect_verdict": "continue",
   "expect_rule_fails": [],
   "why": "THE NEGATIVE CONTROL. Numbers change substantially between the two — a threshold derived on open-to-close is re-derived on prior-close-to-close and the week's output goes from four names to two — but reconciled-b states the change and reconciles it. A gate that fires here is a differ, not a gate, and would have escalated the most careful step of the session."
  },
  {
   "name": "uncited",
   "reports": ["uncited-threshold.md"],
   "expect_verdict": "revise",
   "expect_rule_fails": [1, 3],
   "why": "A constant asserted with no distribution and no count of what it fires at, and success claimed from a green workflow rather than from what it produced."
  }
 ]
}
```

- [ ] **Step 5: Write the rulebook**

Create `docs/loop/rules.md`:

```markdown
# The gate's rulebook

You are the gate. You have been given one or more result reports from a single
project and nothing else — no repository, no session history, no knowledge of
how the work was done.

**That is deliberate. You can only judge what was written down.** If a claim is
not supported on the page, it is not supported.

## What you are judging

Whether the REPORT meets this repo's evidence standard.

**You are not judging** whether the work was a good idea, whether the code is
correct, or whether you would have done it differently. Those need the
repository and you do not have it. Staying inside this boundary is what makes
you cheap enough to run every step.

## Output

Return JSON and nothing else:

```json
{
 "schema": 1,
 "verdict": "continue",
 "rules": [
  {"id": 1, "name": "derived-not-chosen", "result": "pass",
   "quote": "verbatim text copied from the report"}
 ],
 "reason": "one sentence"
}
```

Report every rule from 1 to 8.

**Every `pass` MUST carry a verbatim quote from the report.** Copy the text
exactly. The quote is checked against the report automatically: a pass without
a quote, or with a quote that does not appear, is recorded as a **fail**. You
cannot pass a rule by asserting it.

Use `n/a` when a rule has nothing to apply to — a report with no constants in
it cannot fail rule 1. `n/a` needs no quote. **Do not use `n/a` to avoid a
judgement**; if the rule applies and is unmet, it is a `fail`.

The `verdict` field you write is advisory. The real verdict is computed from
your rule results.

## The rules

### 1. derived-not-chosen

Any constant, threshold, floor or cutoff cites a distribution **and what it
fires at**. A percentile alone is not enough — the report must say how often
the rule triggers and on how much data.

*The case:* a persistence rule was once proposed on a single-day test that
fired for 12, 8, 9 and 12 tickers of 19. The mean looked reasonable. The
maxima made it a firehose.

### 2. named-population

Every number states what it was measured over. A count, a rate or a
distribution without its population is unverifiable and frequently wrong.

*The case:* one morning's filings taken for a 23-year filing-time
distribution. A hit rate measured on daily workflows used to predict an hourly
one. An overlap of "6 of 10" measured against a 276-card archive rather than
the 4-card page actually read.

### 3. verified-by-content

A claim that something landed cites **what was checked**, not that a command
succeeded. "The workflow ran green", "the commit succeeded", "no errors" are
not evidence.

*The case:* a two-part commit split errored before truncating, so the first
commit took both parts — with a non-zero exit code that was never read. A feed
URL was written into the wrong company's entry and the roster validator passed,
because the file was structurally valid.

### 4. absence-is-a-measurement

Any "nothing found" carries a count against a floor, or names what was swept.
"No results" is not a finding until you know the search was capable of finding
something.

*The case:* `SPCX 34/60 bars` is a measurement. And inverted: "278 cards, 0
dated" and "0 bundles, 0 chars of JS" were both broken tools reporting as
findings about the source, and each would have ruled out a usable route.

### 5. contradiction

Does this report contradict a claim in an earlier report **from this same
project**?

Read the earlier reports for figures, verdicts and recommendations. If a number
or conclusion has changed, decide whether the report **acknowledges and
reconciles** the change.

- **Acknowledged and reconciled** — the report says what changed, why, and what
  it means for decisions already taken: `pass`.
- **Silently different** — the number changed and the report does not say so:
  `fail`.

**A changed number is not automatically a contradiction.** Re-measurement,
refinement and correction are the work going well. What fails is a change that
is not owned. This distinction is the difference between a gate and a diff, and
getting it wrong in the strict direction is worse than missing one: it would
escalate the most careful work.

### 6. caveats-surfaced

Anything the report calls unverified, assumed, not measured or uncertain
appears in its summary or conclusion, not only buried in the body.

*The case:* a feed added while its freshness could not be confirmed against its
own newsroom. That belonged next to the recommendation, not in paragraph nine.

### 7. acceptance-criteria

The step's acceptance criteria, supplied with this report, are met and
evidenced. `n/a` if no criteria were supplied.

### 8. irreversible-declared

If the report describes merging to `main`, posting to a live channel, deleting
a component or any other irreversible or outward-facing action, it states that
the action was approved. An irreversible action taken without a recorded
approval is a `fail`.
```

- [ ] **Step 6: Check the rulebook and the code agree**

Run:

```bash
python -c "
import json, re, loop_verdict as lv
md = open('docs/loop/rules.md', encoding='utf-8').read()
missing = [f'{i} {n}' for i, n in lv.RULES.items() if f'### {i}. {n}' not in md]
print('rules in code but not documented:', missing or 'none')
exp = json.load(open('docs/loop/fixtures/expected.json', encoding='utf-8'))
bad = [c['name'] for c in exp['cases']
       if c['expect_verdict'] not in lv.PRECEDENCE]
print('expected verdicts that are not real verdicts:', bad or 'none')
import pathlib
for c in exp['cases']:
    for r in c['reports']:
        p = pathlib.Path('docs/loop/fixtures') / r
        assert p.exists(), f'missing fixture {p}'
print('all fixture files present')
"
```

Expected: `none`, `none`, `all fixture files present`.

- [ ] **Step 7: Commit**

```bash
git pull
git add docs/loop/rules.md docs/loop/fixtures/
git commit -m "The gate's rulebook, and three known-answer fixtures

Eight rules, each with a case from this repo that bites. Every pass must quote
the report verbatim, and the quote is checked — a pass that cannot cite is
recorded as a fail.

Rule 5 carries the distinction the whole gate turns on: a changed number is not
a contradiction. Re-measurement and correction are the work going well; what
fails is a change that is not owned. Getting that wrong in the strict direction
would escalate the most careful work.

The fixtures are this session's own reports. The negative control is the
important one — a threshold re-derived on a different return definition, where
the figures change and the report reconciles them. A gate that flags it is a
differ.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: The gate subagent and its score

**Files:**
- Create: `.claude/agents/loop-gate.md`
- Create: `score_gate.py`
- Create: `docs/loop/fixtures/verdicts/.gitkeep`

**Interfaces:**
- Consumes: `loop_verdict.validate`, `loop_verdict.RULES`; `docs/loop/rules.md`; `docs/loop/fixtures/expected.json`.
- Produces: `score_gate.py` as a CLI — `python score_gate.py` reads every `docs/loop/fixtures/verdicts/<case>.json`, validates it against the case's reports, and compares the derived verdict to `expect_verdict`. Exit 0 only if every case matches.

- [ ] **Step 1: Write the gate agent definition**

Create `.claude/agents/loop-gate.md`:

```markdown
---
name: loop-gate
description: Judges whether a worker's result report meets the repo's evidence standard. Receives the report text inline and returns a JSON verdict. Has no repository access by design.
tools: []
model: sonnet
---

You are the gate for this repository's work loop.

You will be given, inline in the prompt:

1. The rulebook.
2. The acceptance criteria for the step, or a note that there are none.
3. The project's earlier result reports, oldest first, if any.
4. The current result report.

You have **no tools and no repository access**. This is deliberate: you can
only judge what was written down, which is the property that makes you useful.
Do not ask for files. Do not speculate about what the repository contains.

Apply every rule in the rulebook. Return the JSON object the rulebook
specifies and **nothing else** — no preamble, no code fence, no commentary.

Every `pass` must carry a verbatim quote copied from the report. The quote is
checked mechanically against the report text. A pass you cannot support with a
real quote will be recorded as a fail, so quoting accurately is in your
interest and inventing a quote is not.
```

`tools: []` is the isolation. It cannot read the repo even if it decides to.

- [ ] **Step 2: Write the failing scorer**

Create `score_gate.py`:

```python
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
```

Create the directory:

```bash
mkdir -p docs/loop/fixtures/verdicts && touch docs/loop/fixtures/verdicts/.gitkeep
```

- [ ] **Step 3: Run the scorer to verify it fails**

Run: `python score_gate.py`
Expected: FAIL — `0/3 cases matched`, each reporting `no recorded verdict`. This confirms the scorer refuses to pass an unrun case rather than skipping it.

- [ ] **Step 4: Dispatch the gate on each fixture and record the verdicts**

This step is performed by the driver using the Agent tool, once per case. For each case in `expected.json`, build the prompt as:

```
<rulebook>
{contents of docs/loop/rules.md}
</rulebook>

<acceptance-criteria>
None supplied for this case.
</acceptance-criteria>

<earlier-reports>
{contents of every report in case["reports"] except the last, oldest first;
 or "None." if there is only one}
</earlier-reports>

<current-report>
{contents of the last report in case["reports"]}
</current-report>
```

Dispatch with `subagent_type: "loop-gate"`, `run_in_background: false`. Write
the returned JSON verbatim to `docs/loop/fixtures/verdicts/<case name>.json`.

Do not edit the returned JSON. If it is not valid JSON, save it anyway — the
scorer must see the real output, and a gate that cannot emit JSON is a finding
rather than something to tidy up.

- [ ] **Step 5: Score, and interpret the negative control**

Run: `python score_gate.py`
Expected: `3/3 cases matched`.

**If `reconciled` fails with verdict `ask-user`,** the gate is behaving as a
differ. Do not tune the fixture. Revise rule 5's wording in `docs/loop/rules.md`
to sharpen the acknowledged-and-reconciled distinction, re-dispatch that case,
and re-score. Record what changed in the commit message.

**If `contradiction` passes with `continue`,** rule 5 is too weak to catch a
real contradiction and the gate does not work. Same loop, opposite direction.

**If both fail,** rule 5 is not expressible as written and the design needs
revisiting before anything is built on it — stop and raise it.

- [ ] **Step 6: Commit**

```bash
git pull
git add .claude/agents/loop-gate.md score_gate.py docs/loop/fixtures/verdicts/
git commit -m "The gate subagent, and a score against the known answers

tools: [] is the isolation — it cannot read the repository even if it decides
to, so it can only judge what was written down.

Verdicts are produced by dispatch and scored by script, so the assertion is
mechanical and versioned even though the generation is not. The scorer fails an
unrun or unparseable case rather than skipping it.

The negative control is the one that matters. A gate that escalates the
reconciled pair is a differ, and the fix is rule 5's wording rather than the
fixture.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 5: The driver

**Files:**
- Create: `.claude/skills/loop-driver/SKILL.md`
- Create: `docs/loop/README.md`

**Interfaces:**
- Consumes: `loop_state` (all functions), `loop_verdict.validate`, `.claude/agents/loop-gate.md`, `docs/loop/rules.md`.
- Produces: the operating procedure. No new code.

- [ ] **Step 1: Write the driver skill**

Create `.claude/skills/loop-driver/SKILL.md`:

```markdown
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
```

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

- Do not merge to `main` without an interrupt. Ever.
- Do not write `state.json` from a subagent.
- Do not treat a gate failure as a pass, however obviously right you think you
  are. That is the configuration the gate exists to prevent.
- Do not edit a result report after the gate has seen it. Write a new one.
```

- [ ] **Step 2: Write the human-facing README**

Create `docs/loop/README.md`:

```markdown
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
```

- [ ] **Step 3: Verify the skill and the code agree on every function used**

Run:

```bash
python -c "
import re, loop_state as ls, loop_verdict as lv
skill = open('.claude/skills/loop-driver/SKILL.md', encoding='utf-8').read()
used = set(re.findall(r'ls\.([a-z_]+)', skill)) | set(re.findall(r'loop_verdict\.([a-z_]+)', skill))
have = set(dir(ls)) | set(dir(lv))
print('referenced but missing:', sorted(used - have) or 'none')
"
```

Expected: `none`.

- [ ] **Step 4: Commit**

```bash
git pull
git add .claude/skills/loop-driver/SKILL.md docs/loop/README.md
git commit -m "The driver: the cycle, the interrupts, and what it must not do

The worker and the driver are the same session — only the gate needs to be
blind. State is read before anything and a load failure stops the loop rather
than repairing itself: a missing state file is a question, not a condition to
fix, because inferring the step from which files exist is how a step gets
re-run after it merged.

Interrupts are three categories and no timeout. Measurable questions get
decided and reported; preference, irreversible and contradicted claims stop.
Decisions are recorded with their reasoning, because the decisions outlive the
constants.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 6: End-to-end dry run

**Files:**
- Create: `docs/loop/dry-run/plan.md`
- Create: `docs/loop/dry-run/01-result.md` … `03-result.md` (copied)
- Modify: `docs/loop/README.md` — add the dry-run result

**Interfaces:**
- Consumes: everything from Tasks 1–5.
- Produces: evidence that the loop drives a real project to `done` without a human, and the recorded verdicts to prove which rules fired.

- [ ] **Step 1: Build a replay project from a real completed one**

The digest large-move project ran three reporting steps this session. Replay it
with the worker stubbed — the results already exist, so the loop is exercised
on real reports with a known outcome.

```bash
SP="$HOME/AppData/Local/Temp/claude/C--Users-zamzi-OneDrive-Documents-Claude-Infra-Monitor/82ae5946-b5da-4d88-b13e-01ae321e2c09/scratchpad"
mkdir -p docs/loop/dry-run
cp "$SP/response-38-digest-w32-review.md"    docs/loop/dry-run/01-result.md
cp "$SP/response-39-largemove-threshold.md"  docs/loop/dry-run/02-result.md
cp "$SP/response-40-five-changes.md"         docs/loop/dry-run/03-result.md
```

- [ ] **Step 2: Write the plan the replay is judged against**

Create `docs/loop/dry-run/plan.md`:

```markdown
# Dry run — digest large-move (replay)

A replay of a completed project. The worker is stubbed: each step's result
already exists. This exercises the driver, the gate and the state machine
against real reports with a known outcome.

## Step 1 — Review the first live digest

**Acceptance:** reports whether each of the three named checks passed, with
evidence; distinguishes a check that passed from one that could not be run.

## Step 2 — Derive a large-move threshold

**Acceptance:** the threshold cites a distribution and what it fires at per
week; names the population; states any caveat about the measurement basis.

## Step 3 — Build the five changes

**Acceptance:** states what was verified and how; declares any irreversible
action and its approval; reconciles any figure that changed since step 2.
```

- [ ] **Step 3: Run the loop over the replay**

Initialise, then for each step dispatch the gate exactly as the driver would,
recording each verdict to `docs/loop/dry-run/verdict-NN.json`:

```bash
python -c "
import loop_state as ls
ls.save(ls.new_state('dry-run', 3, 'run-dry'), 'docs/loop/dry-run-state.json')
print('initialised')
"
```

Use `docs/loop/dry-run-state.json` rather than the real `state.json` so the dry
run cannot disturb a live project.

- [ ] **Step 4: Check the outcome against what actually happened**

Run:

```bash
python -c "
import json, pathlib, loop_state as ls, loop_verdict as lv
base = pathlib.Path('docs/loop/dry-run')
state = ls.load('docs/loop/dry-run-state.json')
for n in (1, 2, 3):
    raw = json.loads((base / f'verdict-{n:02d}.json').read_text(encoding='utf-8'))
    reports = [ (base / f'{i:02d}-result.md').read_text(encoding='utf-8')
                for i in range(1, n + 1) ]
    v, notes = lv.validate(raw, reports)
    fails = [r['id'] for r in v['rules'] if r['result'] == 'fail']
    print(f'step {n}: {v[\"verdict\"]:<9} fails {fails} coerced {len(notes)}')
    state = ls.advance(state, v['verdict'],
                       rule=fails[0] if fails else None)
print('final status:', state['status'], 'step', state['step'])
"
```

Expected: `final status: done`.

**Step 3's report corrects step 2's own numbers** — the threshold survives
redefinition but the week's output goes from four names to two, and the report
says so. Rule 5 must `pass`. If it fails, the gate is a differ and rule 5 needs
the same treatment as in Task 4 Step 5.

**Steps 1 and 2 may legitimately produce `revise`.** These reports were written
for a human, not against acceptance criteria. Record what fired and why — that
is the calibration this dry run exists to produce, and a `revise` on rule 7 for
a report that predates its own criteria is the gate working.

- [ ] **Step 5: Record the outcome in the README**

Append to `docs/loop/README.md`:

```markdown
## Dry run, <date>

Replayed the digest large-move project — three real reports, worker stubbed.

| step | verdict | rules failed |
|---|---|---|
| 1 | <verdict> | <ids> |
| 2 | <verdict> | <ids> |
| 3 | <verdict> | <ids> |

Final state: `<status>`.

The load-bearing result is step 3: it corrects step 2's own figures and rule 5
passed, so the gate distinguishes an owned correction from a silent one. That
is the property the whole design rests on and it is checked here rather than
assumed.
```

Fill in the real values. Do not write the table before running it.

- [ ] **Step 6: Commit**

```bash
git pull
git add docs/loop/dry-run/ docs/loop/dry-run-state.json docs/loop/README.md
git commit -m "Dry run: the loop drives a real completed project to done

Three real reports from the digest large-move project, worker stubbed, gate and
state machine live. Uses a separate state file so it cannot disturb a live
project.

The load-bearing result is step 3, which corrects step 2's own figures — the
threshold survives redefinition but the week's output changes — and rule 5
passes. That is the gate distinguishing an owned correction from a silent one,
checked rather than assumed.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Self-review

**Spec coverage.**

| Spec section | Task |
|---|---|
| Vocabulary — project, step | 5 (README), 6 (dry run demonstrates both) |
| Architecture — four roles | 4 (gate), 5 (driver/worker); planner out of scope, stated |
| Files layout | 1 (`state.json`), 3 (`rules.md`, fixtures), 5 (README documents all) |
| `state.json` single writer | 1 (`claim`/`beat`), 5 (skill forbids subagent writes) |
| Gate rules 1–8 | 3 (rulebook), 2 (ids, escalation, precedence) |
| Anti-rubber-stamp | 2 (quote verification + derived verdict) |
| Gate does not judge the work | 3 (rulebook boundary section) |
| Escalation table | 2 (`ESCALATION`, `PRECEDENCE`) |
| Interrupt categories | 5 (skill) |
| Blocking not parking | 5 (skill: no timeout, no default) |
| Up-front decision points | **planner's job — deferred with stage 4**, noted in Scope |
| Interrupt shape | 5 (skill) |
| Decisions recorded | 5 (`decisions.md` template) |
| Runaway guards | 1 (`REVISE_LIMIT`, `total_steps` bound) |
| Backlog | **deferred with stage 4**, noted in Scope |
| Error handling table | 1 (raise on corrupt/missing), 2 (raise on malformed), 4 (scorer fails closed), 5 (validate-raises → ask-user) |
| Testing — three fixtures | 3, 4 |
| Loop dry mode | 6 |
| Success criteria 1–5 | 6 (1, 3), 4 (2), 5 (5); criterion 4 needs the planner |

Two gaps, both deliberate and both stated in Scope: up-front decision points
and backlog harvesting are the planner's, deferred to the stage 4–5 plan.
Success criterion 4 (interrupts per project are low, via up-front decision
points) cannot be met until then — it is the planner's whole justification.

**Placeholder scan.** No TBD/TODO. Every code step carries real code. Task 6
Step 5 deliberately leaves table values blank with the instruction not to write
them before running — that is a measurement, not a placeholder.

**Type consistency.** `advance(state, verdict, rule=None)` is called with
`rule=` in Task 1's test, Task 5's skill and Task 6's check. `validate(verdict,
report_texts)` returns a 2-tuple everywhere it is used. `LoopStateError` and
`VerdictError` are distinct and each is caught where raised. `RULES` ids
1–8 match `ESCALATION` keys, the rulebook headings, and `expected.json`'s
`expect_rule_fails`. The rulebook/code agreement is checked mechanically in
Task 3 Step 6, and the skill/code agreement in Task 5 Step 3.
