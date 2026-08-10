#!/usr/bin/env python3
"""Has this exact irreversible action been authorised?

THE GATE CANNOT ANSWER THIS AND SHOULD NOT BE ASKED TO. It never sees the
approval, and a rule of the form "the report must state it was approved" is
satisfied by writing the sentence — a worker who never asked passes it by
typing the words. So approval is checked here, against the decisions file, and
checked BEFORE the action rather than after it.

EXACT TOKENS, NEVER PREFIXES. The repo's standing trap is that prefix matching
does not bridge a rename; the danger here runs the other way, where matching on
`merge:` would turn one approval into a standing licence for every future
merge. `authorised()` compares whole tokens.

WHAT THIS IS NOT: a hard interlock. A driver that skips the call is not
stopped. It is one of three layers — the check, rule 8 making the action
visible in the report, and the decisions file as the durable record — and its
real contribution is that an unapproved action becomes VISIBLE rather than
impossible.
"""

import re
import sys
from pathlib import Path

DECISIONS_PATH = Path("docs/loop/decisions.md")

# The kinds of action that need one. Anything not here is either reversible or
# has not been thought about — and an unrecognised kind raises rather than
# quietly refusing, because a typo in an action name would otherwise read as
# "not authorised" and look like a missing approval.
ACTIONS = ("merge", "post", "delete")

TOKEN_LINE = re.compile(r"^\s*\*\*Authorises:\*\*\s*(.+?)\s*$", re.M)


class ApprovalError(Exception):
    """A malformed action token. Never a refusal — refusals return False."""


def _split_kind(action):
    if ":" not in action:
        raise ApprovalError(f"action {action!r} has no kind — expected "
                            f"one of {ACTIONS} followed by a colon")
    kind = action.split(":", 1)[0]
    if kind not in ACTIONS:
        raise ApprovalError(f"unknown action kind {kind!r} in {action!r}; "
                            f"known kinds are {ACTIONS}")
    return kind


def parse_tokens(text):
    """Every token on every `**Authorises:**` line."""
    out = set()
    for line in TOKEN_LINE.findall(text or ""):
        for tok in line.split(","):
            tok = tok.strip()
            if tok:
                out.add(tok)
    return out


def authorised(action, decisions_text):
    _split_kind(action)
    return action in parse_tokens(decisions_text)


def main(argv):
    if not 2 <= len(argv) <= 3:
        print("usage: python loop_approval.py <action> [decisions_path]",
              file=sys.stderr)
        return 2
    action = argv[1]
    path = Path(argv[2]) if len(argv) == 3 else DECISIONS_PATH
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    try:
        ok = authorised(action, text)
    except ApprovalError as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        return 1
    if ok:
        print(f"authorised: {action}")
        return 0
    print(f"REFUSED: no decision in {path} authorises {action!r}. "
          f"Ask, record the decision with an **Authorises:** line, and retry.",
          file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
