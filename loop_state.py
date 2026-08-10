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
            "heartbeat", "pending", "blocked_reason", "revise_streak")


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
