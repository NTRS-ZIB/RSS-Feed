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

`DRY_RUN` in [`pushpin.yml`](../.github/workflows/pushpin.yml) is currently the
hardcoded literal `"true"`, so **nothing can be deleted**, on the cron or on a
dispatch with the box unticked.

Going live takes two more commits, and the split is deliberate: the house
pattern (`${{ inputs.dry_run }}`, which is empty on a schedule and therefore
live) would take this from "can never delete" to "an unattended cron deletes for
real" in one step, with no state in between where a person can watch a live run.

1. **Now.** Dry on everything. Read a run that proposes real deletions.
2. **`${{ github.event_name == 'schedule' && 'true' || inputs.dry_run }}`.**
   Cron stays dry; a dispatch can go live and be watched.
3. **`${{ inputs.dry_run }}`.** The house pattern. Cron is live.

Do not write `${{ inputs.dry_run || 'true' }}`: an unticked box is boolean
false, which is falsy there, so a live dispatch would silently stay dry and
stage 2 would be unreachable.

Nothing in the channel is eligible before roughly **2026-09-27**, so every run
until then correctly proposes nothing, and a green run proves less than it
looks like it does.

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
| `over the ... cap` | More condemned than `PUSHPIN_MAX_DELETES`. Expected on the first eligible day if there is a backlog. |
| `HTTP 403 code ...` | In order: the channel overwrite, `MANAGE_MESSAGES`, then whether the guild requires 2FA while the app owner has none. |

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
