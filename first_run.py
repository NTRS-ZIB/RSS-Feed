#!/usr/bin/env python3
"""Has this component ever seen this thing before?

WHY THIS EXISTS
On 2026-08-14 `holder_events` posted EIGHTY-SIX messages in one run. Three
companies had been added the day before, and for a company absent from
`holder_state.json` every 13D/G filing on record is a first appearance —
which is precisely what that component is built to report.

The guard already existed and did not apply. `press_monitor` suppressed the
same three companies correctly in the same window; its rule lives inside that
one component, and `holder_events` keys on its own state.

`CLAUDE.md` records the judgement that "a population of one does not want a
framework", made when this shape had been found in exactly one place. That was
right then. It is five components now — holder_events, comment_letters,
crossings, dilution and threshold_list — and one of them has cost 86 messages,
so the judgement is overtaken rather than wrong.

WHAT IS SHARED AND WHAT IS NOT
Only the DECISION is here: which keys this component has never recorded, and
recording them. What suppression MEANS stays in the component, because it
genuinely differs — accessions for holders, letters for correspondence, armed
flags for crossings, a share count for dilution, membership for the threshold
list. A helper that tried to own that would need to understand five state
shapes and would be wrong about all of them eventually.

This module prints nothing, for the same reason. Only the caller knows how
many items its suppression covered, and a count is the whole value of the log
line — a name in a list is an excuse, a count is a measurement.

IT WORKS OVER CAPABILITIES TOO, which is the axis that will bite next. When
`144` joined the insider forms on 2026-08-13, every Form 144 across all
twenty-two companies was unseen; it did not flood only because the press
monitor's seven-day age floor happened to cover it, which is incidental rather
than designed. `baseline(state, FORM_TYPES, namespace="forms")` gives a
component the same protection when it starts collecting something new.
"""

from datetime import date


def baseline(state, keys, namespace="companies", today=None):
    """Keys this component has never seen. Records them. Returns them sorted.

    ABSENT AND EMPTY MEAN OPPOSITE THINGS, and this is the part to get right.

    An ABSENT namespace is the backfill run: this rule has just been added to
    a component that has been running for weeks, so everything it currently
    watches is established BY DEFINITION and nothing is new. All keys are
    recorded and an empty list comes back.

    An EMPTY dict means the opposite — the rule has run before and knows about
    nothing — so every key is genuinely new.

    Reversing those either floods on the day the rule is added, or silently
    suppresses a real backlog forever, and neither announces itself.

    NOT "does this key appear anywhere in the component's existing state".
    That question cannot be asked reliably: `press_monitor`'s seen-id list is
    capped and actively evicting, and its uids carry no company at all, so a
    company whose ids had aged out would look brand new and have its real
    backlog suppressed without a word. A dedicated record is the only thing
    that distinguishes "never seen" from "seen and forgotten".

    IF THE STATE FILE IS LOST, the namespace is absent, so this returns
    nothing new and the component's own whole-file first-run path decides what
    happens. It degrades into existing behaviour rather than into a new one.
    """
    today = today or date.today().isoformat()
    known = state.get(namespace)
    if known is None:
        state[namespace] = {k: today for k in sorted(keys)}
        return []
    new = sorted(k for k in keys if k not in known)
    for k in new:
        state[namespace][k] = today
    return new


def summary(component, new, counts=None):
    """The line a component prints when it suppresses a first run.

    Shared only because the WORDING matters and drifts: this has to read as a
    deliberate act rather than as a failure, or the next person reads a quiet
    run as a broken one and goes looking. The counts are the caller's, because
    only the caller knows what it suppressed.
    """
    if not new:
        return ""
    line = (f"FIRST RUN for {', '.join(new)} in {component} — their existing "
            f"record is stored and NOTHING posts. This is the intended "
            f"behaviour of adding a ticker, not a loss:")
    for k in new:
        n = (counts or {}).get(k)
        if n is None:
            line += f"\n    {k}: recorded"
        else:
            line += f"\n    {k}: {n} item(s) suppressed"
    return line
