[← Watchlist monitor](../../../README.md)

# Pushpin: design

**Status:** design, approved 2026-09-04. Not yet implemented.

Deletes messages older than 30 days from one named Discord channel, keeping
everything posted by a webhook. It is the first component here that destroys
rather than publishes, and every decision below is shaped by that.

## Why this exists at all

The channel mixes two kinds of traffic: the monitor's own webhook output, which
is the record and must persist, and human conversation around it, which should
age out. No off-the-shelf bot does that combination.

**EazyAutodelete, the obvious candidate, cannot express it at any price.** Its
free tier caps the age rule at 7 days and its premium tier at 13.96 days,
hardcoded. The requirement is 30. Its filter 1071 "Is Not Webhook" is exactly
the right keep rule and cannot be paired with the right threshold.

Its published reason for the ceiling is wrong, and believing it would have
killed this component before it started. The FAQ says "every Bot on Discord can
not delete messages that are more than 14 days old". Across all 1,302 lines of
Discord's message resource, "14 days" appears only inside the **Bulk Delete**
section. `DELETE /channels/{id}/messages/{id}` carries no age restriction. The
ceiling is a client-side constant in the vendor's own forked Eris at
`lib/Client.js:790`, where `1421280000000 - 1420070400000` is exactly 14 days,
and the single-message path returns before that guard runs.

That is also the warning attached to this component: taking the single-delete
route means deliberately operating without the only backstop that would have
stopped a mistake.

## Schedule and hosting

A GitHub Actions cron in this repo, like every other component.

The one real weakness of Actions here is punctuality, and it does not matter.
Measured on this repo: 148 scheduled runs came in a median **162 minutes late**.
Against a 30-day threshold that is 0.2% of the window, and a dropped run means a
message dies tomorrow instead of today. The alternative, an always-on host at
$5/month, buys deletion within minutes of the deadline, which is worth
approximately nothing at this granularity.

## Files

The Discord application is named **Pushpin**, after the keep-marker rather than
the deletion, and the component matches it so that an audit log entry reading
"Pushpin" points at an obvious file.

| Path | Role |
|---|---|
| `pushpin.py` | The component. |
| `.github/workflows/pushpin.yml` | Cron plus `workflow_dispatch` with a `dry_run` input, `concurrency: pushpin`. |
| `pushpin_state.json` | Output. Condemned ids and the permanent protected list. |
| `test_pushpin.py` | Tests, each demonstrated to fail with its guard removed. |
| `docs/pushpin.md` | Component doc, linked from the README table. |

The git committer for the state push is `pushpin`, matching `crossings` and the
rest.

## Configuration

| Variable | Purpose |
|---|---|
| `DISCORD_BOT_TOKEN` | New secret. Bot user registered in the Discord Developer Portal. |
| `PUSHPIN_CHANNEL_ID` | The one channel. Named explicitly, never discovered. |
| `PUSHPIN_AGE_DAYS` | Default 30. |
| `PUSHPIN_GRACE_DAYS` | Default 1. See "two independent margins" below. |
| `PUSHPIN_MAX_DELETES` | Per-run cap. Bounds a logic bug. |
| `WEBHOOK_URL_OPS` | Reports only on a run that deleted something. |
| `DRY_RUN` | House convention. Evaluates and logs, posts nothing, saves no state, deletes nothing. |

**The bot runs without the MESSAGE_CONTENT privileged intent**, and `content`,
`embeds`, `attachments` and `components` are dropped at the ingest boundary
before any log line is written.

### Critical: what the privacy claim may and may not say

| Claim | Verdict |
|---|---|
| "Never stores content: the four content fields are dropped at ingest, before any log line." | **True, and enforceable in our own code. This is the claim to make.** |
| "With the intent off, Discord returns empty values for those fields over REST." | True as stated, with documented exceptions. |
| "The bot cannot receive content." | **Overstated. Do not claim it.** |

The gate is a Developer Portal toggle, not a property of this code: HTTP
restrictions follow portal configuration and are unaffected by what the app
passes in IDENTIFY. Anyone with portal access flips it and nothing here changes.
Discord also delivers full plaintext regardless of the intent for the app's own
messages, DMs, **messages that @mention the app**, and replies to it. The gate
has failed open before (discord-api-docs#4552, where Discord staff confirmed a
dashboard bug that served message content over HTTP).

*Never receives* is a claim about Discord's current configuration state and must
be re-verified whenever somebody touches the portal. *Never stores* is a claim
about our own ingest boundary and holds regardless of what arrives.

**Empty content does not mean no personal data.** `author`, `mentions`,
`mention_roles`, `timestamp` and `type` are all ungated, and a social graph plus
a per-user activity timeline is reconstructable from them with content
permanently empty. Whatever this component logs is the exposure, not what the
API returned.

## Permissions

`VIEW_CHANNEL`, `READ_MESSAGE_HISTORY`, `MANAGE_MESSAGES`, scoped to the one
channel.

**Never `MANAGE_THREADS`.** See trap 1 below.

Note that `MANAGE_MESSAGES` is 2FA-elevated. In a guild with 2FA required whose
app owner lacks 2FA, every delete fails as a 403, silently.

## The algorithm

```
PREFLIGHT   assert channel type is GUILD_TEXT      (refuse forum and media)
            assert VIEW_CHANNEL, READ_MESSAGE_HISTORY, MANAGE_MESSAGES
            fetch pin list via GET /channels/{id}/messages/pins
            assert has_more == false
            load protected_ids from pushpin_state.json
            ANY error above halts the run. Never degrade to an empty keep-set.

SNAPSHOT    page history, limit=100 EXPLICIT (the default is 50)
            cursor = last id of each page (newest-to-oldest, so `before`
              takes the LAST id; `after` would take the first)
            skip any message whose channel_id != PUSHPIN_CHANNEL_ID
            drop content/embeds/attachments/components at ingest
            classify each message. Mutate nothing in this phase.

GATE        log every id with age, verdict, reason, and the signals read
            HALT if webhook_id was SEEN in the sample and none was kept
            HALT if condemned count > PUSHPIN_MAX_DELETES
            WARN if zero messages carry the marker
            exit here if DRY_RUN

CONDEMN     record newly-eligible ids with a timestamp in pushpin_state.json

DELETE      only ids condemned for a full extra interval, re-confirmed
            unmarked immediately before each call.
            pace from response headers only. Never retry 401 or 403.
```

Snapshot-first is structural, not stylistic. Paging a collection while mutating
it either skips messages or never terminates, and the non-terminating case ends
when it hits Discord's invalid-request ceiling of 10,000 per 10 minutes, which
is applied per IP address rather than per token.

### Two independent margins, and why both

`PUSHPIN_GRACE_DAYS` and the condemn-then-delete pass look redundant. They are
not, and neither substitutes for the other.

| Margin | Protects against |
|---|---|
| **Grace days.** A message is not eligible until age plus grace. | The boundary race. Somebody adds the marker to a message on the day it turns 30, and Discord's own docs warn that client actions "may be executed in any order (if executed at all)". Grace means nothing is destroyed within one sweep interval of becoming eligible. |
| **Condemn, then delete next run.** An eligible message is recorded on run N and deleted no earlier than run N+1. | A bad classification being acted on immediately. A logic error, a permissions change, a Discord API shift: all get one full interval during which a human can read the ops post or the run log and stop it. |

The first buys the human time to mark. The second buys the operator time to
notice. Both are one line and neither is load-bearing on the other.

## State

`pushpin_state.json`, holding condemned ids with timestamps and the permanent
`protected` id list. **Message ids and flags only. No content, no authors, no
text.**

It matches the `*_state.json` pattern, so it inherits everything that pattern
means in this repo: it is an **output**, written by the workflow, never edited
locally, and protected by the merge driver and pre-commit hook described in
[local-workflow.md](../../local-workflow.md). The workflow needs the same
refresh-from-origin step before the run and the fetch-and-retry loop around the
push that `crossings.yml` carries, for the same reason: a queued run checks out
the SHA fixed when it was created, not when its job started.

The `protected` list is append-only and grows only when somebody marks a
message, so unbounded growth is not a practical concern. Un-protecting a
message means editing an output file, which races the next bot commit. If that
is ever needed, do it as a deliberate commit on a quiet workflow window rather
than as a casual edit.

**The latch is the reason this component has state at all.** Without it,
protection is only as durable as Discord's live reaction state, and the
documented ways a mark disappears without the human touching it (a reaction-role
or starboard bot calling Delete All Reactions, a moderator clearing them, the
2021 custom-emoji mass wipe where one user un-reacting removed everyone's mark)
would each expose the message on the very next sweep.

### Keep rules

Evaluated in order. Every ambiguity keeps.

```python
if msg["id"] in protected_ids:          keep  # the latch, permanent
if "webhook_id" in msg:                 keep  # the monitor's record
if marker_in_array(msg):                keep  # pushpin, decisive
if msg["pinned"]:                       keep
if msg["id"] in pin_list:               keep  # independent of the boolean
if len(msg.get("reactions", [])) >= 20: keep  # human cannot add the mark
if msg.get("flags", 0) & (1 << 5):      keep  # HAS_THREAD
if "thread" in msg:                     keep  # both signals, independently
if msg["type"] not in {0, 19, 20, 23}:  keep  # system messages
if snowflake_time(msg["id"]) >= cutoff: keep
if not marker_confirmed_absent(msg):    keep  # second store, fails open
else:                                   delete
```

`"webhook_id" in msg` works on a raw JSON dict and **fails open on a library
object**, where it becomes `hasattr` and is always true. That keeps everything,
so a totally broken sweep looks like a quiet one. This is why the component
stays on raw dicts throughout.

The asymmetry is the whole design. Failing to delete something is invisible and
costs nothing. Deleting a webhook post or a marked message is permanent, and
there is no forensic record: Discord's `MESSAGE_DELETE` audit entry carries only
a channel id and a count, no ids and no content, retained 45 days. **Our own
pre-deletion log is the only artefact that will ever exist.**

## Critical: the six traps this component is built around

### 1. A thread and its starter message share one snowflake

That single number is simultaneously a valid message id and a valid channel id.
`DELETE /channels/{id}/messages/{id}` removes a message. `DELETE /channels/{id}`
removes a thread and everything in it, and Discord Support cannot restore it.
Both return success and log a plausible line naming the correct id.

**Guard:** no code path in this component constructs a channel-scoped delete
route at all. Message ids and channel ids are typed separately rather than
passed as bare snowflakes. The bot is never granted `MANAGE_THREADS`.

### 2. `type == 0` is the intuitive rule and it is wrong

REPLY is 19, CHAT_INPUT_COMMAND is 20, CONTEXT_MENU_COMMAND is 23. All are
ordinary user messages. A `type == 0` rule silently skips most real conversation
while reporting a complete sweep.

**Guard:** an explicit allow-set `{0, 19, 20, 23}`, re-checked whenever Discord
adds a type. Everything else keeps, including deletable system messages such as
USER_JOIN (7), boost notices (8 to 11) and THREAD_CREATED (18), which are
history nobody meant to sweep.

### 3. The reactions array is a cache, not the truth

Discord's own root-cause comment on discord-api-docs#2750 describes
`msg.reactions` as a denormalised hint "which we use as a hint to load the users
+ count" over an authoritative reactor store. It has been observed **empty at
HTTP 200 on a message that genuinely carried a reaction**, with nothing logged.
That specific bug was patched in 2021; the architecture it revealed was not, and
the docs never state when the array is present, never state it is complete, and
document no length guarantee.

**Guard:** the array may only ever ADD protection, never authorise a delete.

| Signal | Effect |
|---|---|
| Array shows the marker, `count > 0` | Keep, decisive, no further call |
| Array absent, empty, or marker not in it | **Not permission to delete.** Confirm against the reactions route |
| Reactions route returns any user, `type=0` **or** `type=1` | Keep |
| Route errors, 429s, times out, or returns `10014` | Keep |
| Both stores return 200 and empty | Delete |

`GET Reactions` defaults to `type=0` (normal). **Super reactions are `type=1`.**
Querying only the default returns an empty user list for a super-react-only
mark while the message object correctly reports `count >= 1`, which would delete
exactly the messages someone cared most about. Both types are queried, and an
empty list never overrules a non-empty `count`.

The route is addressed by `name:id` for custom emoji and by the raw character
for Unicode. Build that URL from the **configured** marker, never from the
payload, and treat error `10014` as keep rather than as "no reactors".

### 4. The marker is a Unicode emoji, and Unicode emoji do not compare cleanly

The marker is the pushpin, `U+1F4CC`, written escaped in source so it is
auditable in a diff.

Verified locally: it is a single code point, already NFC and NFKC normalised,
and has no skin-tone variants because it is an object rather than a person. That
removes two of the three Unicode traps outright. The third remains:
`U+1F4CC` and `U+1F4CC U+FE0F` compare unequal, and **normalisation does not fix
it** (`NFC` leaves both unchanged, measured). Windows `win + .` and several
Android keyboards append `U+FE0F`, so which client the human used decides what
got stored.

```python
MARKER = "\U0001F4CC"
VS16   = "️"

def is_marker(emoji: dict) -> bool:
    if emoji.get("id") is not None:
        return False              # a custom emoji named "pushpin" must not match
    name = emoji.get("name")
    if not isinstance(name, str):
        return False              # null name is unparseable; the caller keeps
    return name.replace(VS16, "") == MARKER
```

`emoji.get("id") is not None` is not decoration. Without it, any custom emoji
named `pushpin` matches.

**A run where zero messages carry the marker is a warning, not a halt.** The
first draft halted, on the reasoning that nobody being able to apply the marker
is indistinguishable from nobody wanting to. That reasoning was inherited from a
CUSTOM-emoji design, where the marker can be deleted from the server or become
`available: false` after a boost lapse. **A Unicode emoji cannot be deleted, so
that failure mode does not exist here**, and the measured marker density is 1 in
100 messages, which means an ordinary window legitimately contains none. Halting
on it would stop every run and delete nothing.

Snowflakes serialise as JSON strings. `"123" == 123` is silently False in
Python and would condemn the entire channel, so ids are type-asserted at
startup.

### 5. The marker cannot be applied inside a thread, with certainty

Discord: "Users cannot edit messages, add reactions, use application commands,
or join archived threads. The only operation that should happen within an
archived thread is messages being deleted."

Maximum `auto_archive_duration` is 10080 minutes, which is 7 days. The threshold
here is 30. So **every thread message that ever reaches this sweep is in an
archived thread**, under every available setting, guaranteed. The protective
gesture is disabled exactly where the destructive one still works.

**Guard:** never sweep inside threads. Only messages whose `channel_id` equals
`PUSHPIN_CHANNEL_ID` are candidates, checked explicitly rather than trusting the
API to have scoped the result.

### 6. Silence is indistinguishable from success in three separate ways

A bot missing `READ_MESSAGE_HISTORY` gets **HTTP 200 with an empty array**, not
an error. An empty pin fetch degraded to an empty set silently unprotects every
pin. A marker predicate comparing `int` against `str` snowflakes matches nothing
and condemns the channel. All three look like a clean, healthy run.

**Guard:** permissions asserted at startup; an empty first page on a channel
known to have content is an alert; type assertions on every snowflake; halt when
`webhook_id` appeared in the sample and nothing was kept for it.

That last one tests the CLASSIFIER rather than the channel's traffic mix, and
the difference is the whole guard. "Zero webhook messages were kept" was the
first draft and it is wrong here: the channel measured **1 webhook message in
100**, so an ordinary window contains none and the component would halt forever
without deleting anything. "Webhook messages were present and none survived" can
only be true if the detection broke.

The pin fetch has its own version of this. The deprecated `GET /channels/{id}/pins`
is still live and is what older libraries call. It returns "the first 50 pinned
messages" with no cursor and no `has_more`, so past 50 pins the protection set
is silently short, and the truncation lands on the **keep** list. Use
`GET /channels/{id}/messages/pins`, assert `has_more == false`, and treat any
error while building a never-delete set as halt-the-run.

## What it cannot do, stated now

- **You will never be able to review what was deleted.** With the intent off,
  content is empty, and the audit log holds only a count. The dry-run log proves
  the rule is right (ids, ages, verdicts, reasons); it can never show the text
  that went. This is the deliberate trade, not a defect.
- **Ephemeral messages never appear in channel history** and cannot be deleted,
  so "this channel is clean" is never literally true.
- **A visually identical pushpin from another guild** carries a different id and
  correctly will not match, but the human will believe it worked. No code guard
  catches this.
- **Anyone who can see the channel can pile onto an existing reaction.**
  `ADD_REACTIONS` "does not apply to reacting with an existing reaction", so
  once one person marks a message, anyone can. Reactor identity is deliberately
  not checked: an over-broad protector list costs a message surviving that could
  have been swept, while an identity check costs a marked message being deleted,
  and those are not comparable.

## Reporting

Posts to `WEBHOOK_URL_OPS` only on a run that actually deleted something: count
deleted, count kept, count protected, oldest survivor. Silent otherwise, which
will be every run until roughly 2026-09-27.

Output stays at or under 28 characters per monospace line, per the README.

## Testing

House rule, and CLAUDE.md is emphatic: **a test that has never failed proves
nothing.** For each guard, name the one-line change to the module that turns the
check red, make that change, and watch it. A mutation that crashes the harness
has shown nothing. Delete `__pycache__` between mutations, or the run measures
the previous one.

The guards whose demonstrations matter most, because each corresponds to a
documented failure rather than a hypothesis: the `type` allow-set, the
`emoji.id is not None` check, the VS16 strip, the `type=1` reaction query, the
zero-webhook halt, the zero-marker halt, and the pin-list `has_more` assertion.

## Rollout

Ships with the workflow's `dry_run` input defaulting to **true**.

Nothing in the channel is eligible until roughly 2026-09-27, so the component
will correctly propose nothing for about three weeks. That is a free dry run
against live data, and all of it should be spent.

Flip the default only after reading a log from a day on which it proposed real
deletions.

## Measured, 2026-09-05

The four items this spec could not settle by reading were settled against the
live channel by [`probe_pushpin_scope.py`](../../../probe_pushpin_scope.py),
sampling 100 messages. Run it again after any change to the bot's permissions.

| Question | Measured | What it changed |
|---|---|---|
| Is `reactions` omitted or `[]` when unreacted? | **Omitted.** 79 absent, 0 empty | `msg["reactions"]` raises. The `.get()` in the predicate is load-bearing, not defensive style |
| Unused marker on the reactions route: `200 []` or `10014`? | **200 with `[]`** | The two-store design works as written. An error genuinely means an error |
| Does `type=0` exclude burst reactors? | Same message: type 0 gave **1** reactor, type 1 gave **0** | Confirms the two queries return different sets. Does NOT prove a burst-only mark reads 0 on type 0, because no super-reaction existed to test. **The guard stays and this line stays open** |
| Does anything but a webhook carry `webhook_id`? | webhook 1, bot-not-webhook 0, human 99 | No evidence of a wider exemption. Only one webhook message in the sample, so this is weak: re-check when more have accumulated |

Two further measurements the probe returned that the spec had assumed:

- **Content gating is real.** 100 of 100 messages came back with empty
  `content`. The privacy claim in the Configuration section is now measured
  against this channel rather than argued from the docs.
- **Message types were `{0: 90, 19: 10}`.** Ten percent of the channel is
  replies. The `type == 0` trap was not hypothetical: that rule would have
  silently skipped one message in ten while reporting a complete sweep.

### Still open

- **Burst reactors.** Needs a super-reaction on one message, then a re-run.
- **The webhook sample is one message.** A rule protecting the monitor's record
  has been validated against a single instance of that record.
### Closed

- **Scope is clean as of 2026-09-05.** The probe reports "no other channel is
  visible to the bot" across all 13 channels, with the target holding all three
  permissions and eight other text channels answering 403.

  The one channel that had survived the first pass was `#General`, measured as
  **type 2, a voice channel**, whose in-channel text chat the bot could read.
  Worth recording because of *why* it survived: denying by category is the
  efficient way to do this, and a voice channel is exactly what that sweep is
  easiest to miss. The scope scan flagged it and the live probe did not, since
  the live probe only reads text-like types. **A disagreement between those two
  checks is a signal about channel type, not a bug in either.**
