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
    nothing new and the component behaves exactly as it did before this rule
    existed. That degradation is deliberate but it is NOT a safety net, and
    an earlier draft of this docstring claimed it was: only `holder_events`
    of the five actually suppresses on a cold start. `comment_letters` and
    `crossings` compute a `first_run` flag and use it as a log annotation, so
    a lost state file means 180 days of correspondence and every ticker
    sitting at an extreme post at once. That is unchanged by this rule and
    out of its scope; it is written down so the next reader does not take the
    absence of a complaint for a guarantee.
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


def baseline_by_cik(state, companies, namespace="companies", today=None):
    """Newly watched TICKERS, recorded by CIK. Takes `watchlist.ciks()`.

    KEYED BY CIK BECAUSE A TICKER IS A DISPLAY LABEL. Six of nineteen
    companies renamed in eighteen months, and under a ticker key a rename
    reads as a brand-new company: one run of its real events is suppressed,
    and in `holder_events` and `comment_letters` those events are marked seen
    in the same run, so they never post at all. The failure is silent and the
    log reads as a deliberate first-run suppression.

    The inverse matters as much. A RECYCLED ticker — `SPCX` was a SPAC ETF
    until 2026-04-07 and SpaceX from 2026-06-15 — is already in the record
    under a ticker key, so the new company would get no suppression and flood.

    Returns tickers because that is what a reader recognises; the record on
    disk is CIKs. `docs/watchlist.md` records the one case where a CIK does
    not survive, a combination creating a new registrant, and that correctly
    reads as a new company here.
    """
    cik_of = {t: c for t, (c, _) in companies.items()}
    new = set(baseline(state, cik_of.values(), namespace, today))
    return sorted(t for t, c in cik_of.items() if c in new)


def newly_tracked(value, new_keys, old_keys, matches):
    """Which newly tracked key covers `value` — or None if it is not new.

    THE CAPABILITY AXIS. `baseline` answers "have I recorded this key", which
    for a company is the whole question. For a form type it is not, because
    three of the four tracked sets are matched by PREFIX.

    A VALUE ALREADY COVERED BY AN ESTABLISHED KEY IS NOT NEW, and this is the
    trap the axis brings with it. Adding `SCHEDULE 13D/A` beside an existing
    `SCHEDULE 13D` adds no filings whatsoever — every one of them already
    matched — so treating them as newly tracked would go quiet on a form the
    channel has carried for months. The question is whether the PREVIOUS set
    would have matched the value, not whether the new key does.

    `old_keys` MUST COME FROM THE RECORD, `set(state[namespace]) - new`, and
    NOT from the current config minus the new keys. The two differ exactly
    when an edit REPLACES a key, and the repo has already made that edit
    once: `NT 10-K` and `NT 10-Q` were deleted and `NT ` added in their
    place. Under the config reading, `NT ` is new, the deleted keys are gone,
    so every NT filing looks newly tracked and is suppressed — a form the
    channel has carried for months, gone quiet, with a log line calling it a
    first run. `baseline` never removes a key, so the record still holds them
    and answers the question the docstring above actually asks.

    `matches(value, key)` is the component's own matcher: `str.startswith` for
    a prefix set, `operator.eq` for an exact one, `press_monitor.form_matches`
    for `FORM_TYPES`. It stays in the component because the components
    genuinely disagree about it, and getting it wrong here would be wrong
    everywhere at once.

    Longest key first, so the returned key is the most specific one that
    matched and the log names something a reader can find in the config.
    """
    if any(matches(value, k) for k in old_keys):
        return None
    for k in sorted(new_keys, key=len, reverse=True):
        if matches(value, k):
            return k
    return None


def prune_unmeasured(state, measured, roster, has_state, namespace="companies"):
    """Drop recorded keys nothing has ever measured. Returns them, sorted.

    TWO CONDITIONS, AND THE SECOND ONE IS THE WHOLE SAFETY OF THIS FUNCTION.
    A key is pruned only when this run did not measure it AND the component
    holds no per-company state for it. The first draft pruned on the first
    condition alone, and that was a worse bug than the one it fixed.

    Why: in `dilution` and `holder_events` a suppressed item is ALREADY
    RECORDED by the time it is suppressed — accessions go into `seen` inside
    the loop, share counts are written by `record()` whatever `is_change`
    returned. Suppression there is only safe for a company that has nothing
    worth keeping. Prune an ESTABLISHED company on a transient fetch failure
    and the next run treats it as new: its genuinely new 13D/G is marked seen,
    then dropped, and no later run can return it. A missed run became a
    permanent loss, under a log line reading "not a loss".

    That is the same criterion used to exempt `press_monitor`, and the first
    draft applied the rule to two components the criterion also disqualifies.
    The second condition is what makes it safe: a company with per-company
    state has been measured before, so it is established whatever this
    particular run managed, and it is never pruned.

    Measured 2026-08-18, and the two conditions agree exactly with the damage:
    the roster members holding no per-company state were ABTC, CRWV, GLXY and
    SPCX in `dilution` and SPCX in `crossings` — precisely the five wrongly
    recorded, and nobody else.

    BOTH CONDITIONS ARE LOAD-BEARING, not one with a belt. `has_state` alone
    would prune a company on the very run it is first measured, because
    `dilution.record()` writes after this runs. `measured` alone is the bug
    above.

    RECORDING A COMPANY THE RUN NEVER OBSERVED IS THE SAME BUG AS NOT
    RECORDING ONE, ROTATED. `baseline_by_cik` marks every roster company
    established on the run the namespace is absent, whether or not the
    component produced the per-company state its suppression rests on. Measured
    2026-08-18, four days after the rule landed: `dilution_state.json` held 22
    CIKs against 18 share counts — ABTC, CRWV, GLXY and SPCX recorded and never
    measured — and `crossings_state.json` held 22 against 21 armed flags.

    What that costs is not theoretical and has a date. SPCX was at **46 of
    MIN_BARS=60 sessions** and already recorded, so on the run it clears the
    floor `state.setdefault` creates it ARMED — `initial_flags` disarms only a
    ticker in `newly_watched`, and SPCX is no longer in it. It would then fire
    "above its 52-week high" for a crossing the component never watched, which
    is the exact assertion `initial_flags` exists to refuse.

    PRUNING RATHER THAN RECORDING LATE, for two reasons. Both callers consume
    `newly_watched` INSIDE their per-company loop while the measured set only
    exists after it, so recording late means splitting `baseline` into a read
    half and a write half at every call site — duplicating the absent-versus-
    empty asymmetry that is the easiest thing here to get wrong. And `baseline`
    is append-only, so narrowing what it writes from now on would leave the
    four already-wrong records in place for ever; a delete repairs them on the
    next saving run, without hand-editing an output file.

    THREE PROPERTIES ARE LOAD-BEARING:

    - It never removes the namespace itself. Absent still means backfill, so a
      run that pruned everything must not read as the rule having never landed.
    - It never touches a key outside `roster`. A company REMOVED from the
      watchlist keeps its record, so re-adding it later does not flood.
    - An empty `measured` prunes nothing. A run that measured nothing has
      measured nothing about the record either, and a total outage must not
      quietly un-establish the whole roster.

    STARVATION IS NOT POSSIBLE. A company that legitimately never produces the
    state is never suppressed, because there is nothing to suppress: the
    suppression is only REACHABLE for a company being measured — `is_change`
    is called only for tickers in `rows`, `initial_flags` only through
    `setdefault`. It carries no record until the day it is measured, and on
    that day exactly one first observation is withheld and both the record and
    the per-company state are written, so it is never pruned again.

    An earlier version of this paragraph claimed the same thing while pruning
    on `measured` alone, and was wrong: it did not cover a company measured on
    an EARLIER run whose record this function had since deleted. That gap was
    the defect described above, and `has_state` is what closes it.

    `measured` and `roster` are both key sets in the namespace's own units,
    which for `companies` means CIKs and not tickers.
    """
    known = state.get(namespace)
    if not measured or known is None:
        return []
    gone = sorted(k for k in roster
                  if k in known and k not in measured and k not in has_state)
    for k in gone:
        del known[k]
    return gone


def backfilled(state, namespace="companies"):
    """Will the NEXT baseline() call be the backfill run? Ask before calling.

    The backfill is correct and it is also invisible: it records every key and
    returns nothing, so a component that ran it and a component where the rule
    was never wired produce identical logs. That is the trap `CLAUDE.md` states
    as "a pattern matching nothing looks exactly like one whose matches never
    occur", and it was met head-on the first time these five were dry-run —
    all five green, all five silent, with no way to tell from the output which
    had happened. Pair this with `backfill_note`.
    """
    return state.get(namespace) is None


def backfill_note(component, count, unit="companies"):
    """The line a component prints on the one run that establishes its record.

    `unit` names what was recorded, because the rule now runs over form types
    as well as companies and "22 companies" against a set of form types would
    be a confident wrong answer in a log nobody is reading closely.
    """
    thing = "a company added to the roster" if unit == "companies" else \
        f"a {unit[:-1] if unit.endswith('s') else unit} added to the config"
    return (f"FIRST-RUN RULE: {count} {unit} recorded as established in "
            f"{component}, nothing suppressed. This is the backfill and it "
            f"happens once; from here {thing} posts nothing on its first run.")


def summary(component, new, counts=None, unit="ticker"):
    """The line a component prints when it suppresses a first run.

    Shared only because the WORDING matters and drifts: this has to read as a
    deliberate act rather than as a failure, or the next person reads a quiet
    run as a broken one and goes looking. The counts are the caller's, because
    only the caller knows what it suppressed.

    `unit` names what was added. It exists because the rule now runs over form
    types too, and a form-type suppression that says "the intended behaviour
    of adding a ticker" sends the reader to `watchlist.py` to look for a
    roster change that never happened.
    """
    if not new:
        return ""
    line = (f"FIRST RUN for {', '.join(new)} in {component} — their existing "
            f"record is stored and NOTHING posts. This is the intended "
            f"behaviour of adding a {unit}, not a loss:")
    for k in new:
        n = (counts or {}).get(k)
        if n is None:
            line += f"\n    {k}: recorded"
        else:
            line += f"\n    {k}: {n} item(s) suppressed"
    return line
