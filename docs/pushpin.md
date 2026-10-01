[← Watchlist monitor](../README.md)

# Pushpin

Deletes messages older than 30 days from one Discord channel, keeping
everything a webhook posted and everything a human marked with 📌.

It is the only component here that destroys anything. The design record and the
evidence behind every guard are in
[the design doc](superpowers/specs/2026-09-04-pushpin-design.md); this page is
what an operator needs.

## Schedule

`40 3 * * *`, 03:40 UTC daily. The 00:00 to 05:00 window is otherwise empty,
which keeps it clear of the two poll-loop workflows that hold a runner for
about 45 minutes each between 07:00 and 23:59.

Punctuality does not matter here, which is unusual for this repo. Scheduled runs
land 51 to 173 minutes late, measured. Against a 30-day threshold that is 0.2%
of the window, and a dropped run means a message dies tomorrow instead of today.

## How to keep a message

**React to it with 📌.** Once any run sees the mark, the message id is recorded
in `pushpin_state.json` permanently, so removing the reaction later does not
expose it again. Pinning works too.

Two honest limitations, both worth knowing before you rely on the mark:

**It does not work inside threads.** Discord blocks adding reactions to an
archived thread, the maximum auto-archive is 7 days, and the threshold here is
30, so every thread message that ever reaches this sweep is in an archived
thread. Pushpin never sweeps inside threads for that reason, but if that ever
changes, the mark cannot be applied there.

**Anyone who can see the channel can pile onto an existing 📌.** Discord's
`ADD_REACTIONS` permission does not apply to reacting with an emoji already on
a message. Reactor identity is deliberately not checked: an over-broad
protector list costs a message surviving that could have been swept, while an
identity check costs a marked message being deleted, and those are not
comparable.

## What is kept

In the order the code checks them. Every ambiguity keeps.

| Rule | Why |
|---|---|
| Latched | Seen carrying 📌 on any past run |
| `webhook_id` present | The monitor's own record |
| 📌 in the message's reactions | The live mark |
| Pinned, or in the pin list | Checked twice, independently |
| 20 or more distinct reactions | At Discord's cap, so a human physically cannot add 📌 |
| Anchors a thread | Deleting the anchor orphans the thread |
| Type not in `{0, 19, 20, 23}` | System messages, joins, boosts, thread notices |
| Newer than 31 days | Age plus a grace day |

**Type 19 is a reply and type 20 is a slash-command message.** Both are ordinary
user messages, and this channel measured 10% replies, so the intuitive
`type == 0` rule would silently skip a tenth of real conversation while
reporting a complete sweep.

## What you cannot do

**You will never be able to review what was deleted.** Discord's audit entry for
a message delete carries a channel id and a count: no ids, no content, kept 45
days. This component adds nothing to that, deliberately: the Actions log on this
repo is world-readable, so it logs verdict counts and a bucketed age histogram
and never per-message ids or ages, either of which reconstructs a timeline of
activity in a private channel.

A dry run shows you that the **rule** is right. Nothing will ever show you what
went. If a message matters, copy it somewhere else rather than trusting the
mark.

## Running it

```bash
gh workflow run "Pushpin" -f dry_run=true
```

Never run `pushpin.py` locally. It reads secrets that exist only in Actions and
a live run deletes real messages.

To check the bot's permissions are still scoped to the one channel, which
Discord provides no first-party view of:

```bash
gh workflow run "Pushpin scope probe"
```

## Rollout, in three stages

**Stage 2 since 2026-10-01. The cron is still dry. A dispatch with the box
unticked is LIVE and permanently deletes messages.**

Stage 1 was the hardcoded literal `"true"`, which could not delete under any
circumstances. It earned its keep: 27 dry runs, and the first eligible day
exposed a cap deadlock that a live run would have hit instead.

1. ~~Hardcoded `"true"`.~~ Done, 2026-09-05 to 2026-10-01.
2. **`${{ github.event_name == 'schedule' && 'true' || inputs.dry_run }}`.**
   Where it is now. Cron dry, dispatch can go live and be watched.
3. **`${{ inputs.dry_run }}`.** The house pattern. Cron is live. Only after a
   supervised live dispatch has been read and the backlog has drained.

Do not write `${{ inputs.dry_run || 'true' }}`: an unticked box is boolean
false, which is falsy there, so a live dispatch would silently stay dry and
stage 2 would be unreachable.

### The first live run

The backlog is larger than the cap, so a live run needs its own cap. Pass it on
the dispatch rather than editing the file, because a cap raised in the file to
clear an expected backlog stays raised long after the reason for it is gone, and
then no longer bounds the bug it exists for.

```bash
gh workflow run "Pushpin" -f dry_run=false -f max_deletes=800
```

Watch it, then put nothing back: the input is blank on a schedule and
`env_int` reads blank as 200. Once the backlog has drained, a normal day's
intake sits well under 200.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `DISCORD_BOT_TOKEN` | | Bot token. Never `MANAGE_THREADS`. |
| `PUSHPIN_CHANNEL_ID` | | The one channel, named explicitly. |
| `PUSHPIN_AGE_DAYS` | 30 | |
| `PUSHPIN_GRACE_DAYS` | 1 | Buys a human time to mark near the boundary. |
| `PUSHPIN_CONDEMN_HOURS` | 20 | Buys the operator time to notice. Floored at 1. |
| `PUSHPIN_MAX_DELETES` | 200 | Halts above this many condemned at once. |
| `PUSHPIN_DRY_SAMPLE` | 25 | How many a dry run puts through the reaction check. |

Every one of these is read through `env_int`, which treats an EMPTY value as
the default. That matters because `${{ inputs.x }}` renders empty on a schedule
event, and `int("")` raises: wiring any of them to a dispatch input without it
would crash every cron run at import, before a single guard ran.

## When it halts

A halt is a refusal to act, not a crash. It exits non-zero so the run goes red
and `failure-notice.yml` posts a line, because a sweeper that silently declines
to delete looks exactly like one with nothing to do.

| Halt | What to check |
|---|---|
| `webhook_id ... condemned` | The webhook exemption broke. Nothing was deleted. |
| `no readable protected list` | `pushpin_state.json` is damaged. Do not delete it: restore it. |
| `pin list is truncated` | More than 50 pins. The keep-set would be short. |
| `missing in the target channel` | Channel overwrites changed. |
| `holds ADMINISTRATOR` | Every overwrite is bypassed and the scoping is inert. |
| `over the ... cap` | More condemned than `PUSHPIN_MAX_DELETES`. Expected once a backlog accumulates. **A LIVE run halts; a dry run reports and continues.** See below. |
| `HTTP 403 code ...` | In order: the channel overwrite, `MANAGE_MESSAGES`, then whether the guild requires 2FA while the app owner has none. |

## The cap, and the deadlock it caused

`PUSHPIN_MAX_DELETES` bounds a logic bug: if the classifier suddenly condemns
the channel, a live run stops rather than acting on it.

**It tripped for real on 2026-09-29**, and the first version deadlocked. The
halt sat before the `DRY_RUN` exit, so a dry run could not get past it either,
and because a dry run saves no state nothing was ever deleted, so the backlog
only grew. Measured:

| Date | Condemned | Run |
|---|---|---|
| 2026-09-28 | 54 | success |
| 2026-09-29 | over 200 | **failure** |
| 2026-10-01 | 545 | **failure** |

Twenty-seven good dry runs, then a permanent red that could never clear, whose
only output was the halt itself: the one state that says nothing about whether
the cap is right.

A dry run now reports `OVER CAP` and continues. A live run still refuses. If a
live run halts on the cap, the choice is to raise `PUSHPIN_MAX_DELETES`
deliberately or to work the backlog down in bounded runs, and neither should be
done by reflex: a cap raised to clear a backlog is a cap that no longer bounds
the bug it exists for.

## Tests

```bash
python -u test_pushpin.py           # 60 checks
python -u test_pushpin.py --sweep   # 14 mutations, each must redden a check
```

The sweep is the part that matters. It applies each named one-line change to
`pushpin.py` in its own temporary directory and asserts every one turns a check
red, because a test that has never failed proves nothing. Both run in CI.

It has already earned that: on its first run it reported 0 of 14 mutations
reddening anything, which looked like fourteen unfailable checks and was
actually a harness bug (`PYTHONPATH` loses to the script's own directory at
`sys.path[0]`, so no mutant was ever imported). After that was fixed, one
genuine unfailable check remained: the `ADMINISTRATOR` fixture granted only the
admin bit, so removing the guard still halted on the missing-permissions check
and the assertion was "halts" rather than "halts for this reason".
