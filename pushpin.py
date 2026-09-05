#!/usr/bin/env python3
"""Delete messages older than 30 days from one Discord channel, keeping
everything a webhook posted and everything a human marked with a pushpin.

THIS IS THE ONLY COMPONENT IN THIS REPO THAT DESTROYS ANYTHING, and Discord
deletion cannot be undone. The audit entry Discord writes for a message delete
carries a channel id and a count: no ids, no content, retained 45 days. So
there is no artefact anywhere, ever, that says what went. Every guard below
exists because of a documented failure rather than a hypothesis; the design
notes and the evidence are in docs/superpowers/specs/2026-09-04-pushpin-design.md.

The asymmetry that shapes the whole file: FAILING TO DELETE SOMETHING IS
INVISIBLE AND COSTS NOTHING. Deleting a webhook post or a marked message is
permanent. Every ambiguity therefore keeps, every error keeps, and every
unrecognised shape keeps.

Run it through the workflow, never locally:

    gh workflow run "Pushpin" -f dry_run=true
"""

import json
import os
import sys
import time
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

API = "https://discord.com/api/v10"

TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "")
CHANNEL_ID = os.environ.get("PUSHPIN_CHANNEL_ID", "")
OPS_WEBHOOK = os.environ.get("WEBHOOK_URL_OPS", "")
DRY_RUN = os.environ.get("DRY_RUN", "").strip().lower() in ("1", "true", "yes")

STATE_FILE = Path("pushpin_state.json")

AGE_DAYS = int(os.environ.get("PUSHPIN_AGE_DAYS", "30"))

# A message is not eligible until AGE_DAYS + GRACE_DAYS. This buys the HUMAN
# time: somebody adding the marker on the day a message turns 30 is racing the
# sweep, and Discord's own docs warn that client actions "may be executed in
# any order (if executed at all)".
GRACE_DAYS = int(os.environ.get("PUSHPIN_GRACE_DAYS", "1"))

# An eligible message is CONDEMNED on one run and deleted on a later one. This
# buys the OPERATOR time: a logic error, a permissions change or a Discord API
# shift gets a full interval during which the ops line or the run log can be
# read and the workflow disabled. 20 hours rather than 24 so a daily cron whose
# fire time drifts (51-173 minutes late on this repo, measured) still clears it.
# max(1, ...) is not decoration: 0 collapses BOTH independent margins into a
# single run, so a message could be condemned and deleted before anyone could
# see it condemned.
CONDEMN_HOURS = max(1, int(os.environ.get("PUSHPIN_CONDEMN_HOURS", "20")))

# How many condemned messages a DRY RUN puts through the reaction check. Four
# read-only requests each, so this bounds a dry run's API cost while still
# exercising the code that authorises a delete.
DRY_SAMPLE = int(os.environ.get("PUSHPIN_DRY_SAMPLE", "25"))

# Bounds a logic bug. Sized well above one day of traffic in a quiet channel
# and well below "the whole channel".
MAX_DELETES = int(os.environ.get("PUSHPIN_MAX_DELETES", "200"))

# Discord returns 40333 to a request it considers poorly identified, which
# reads as a permissions problem rather than a header problem.
UA = "Pushpin (github.com/NTRS-ZIB/RSS-Feed)"

# Discord's epoch, and the shift that recovers a timestamp from a snowflake.
# Verified against Discord's own worked example.
DISCORD_EPOCH_MS = 1420070400000
SNOWFLAKE_SHIFT = 22

MARKER = "\U0001F4CC"  # pushpin. Escaped so it is auditable in a diff.
VS16 = "️"

# Message types this component may delete. NOT `type == 0`: REPLY is 19,
# CHAT_INPUT_COMMAND is 20 and CONTEXT_MENU_COMMAND is 23, all of them ordinary
# user messages. Measured on this channel on 2026-09-05: types were
# {0: 90, 19: 10}, so a `type == 0` rule would have silently skipped a tenth of
# real conversation while reporting a complete sweep. Everything outside this
# set keeps, including deletable system messages (USER_JOIN 7, boost notices
# 8-11, THREAD_CREATED 18) which are server history nobody meant to sweep.
DELETABLE_TYPES = {0, 19, 20, 23}

GUILD_TEXT = 0
HAS_THREAD = 1 << 5  # message flag

# Permission bits, named rather than inlined because a wrong shift computes a
# plausible number for a different permission.
ADMINISTRATOR = 1 << 3
VIEW_CHANNEL = 1 << 10
MANAGE_MESSAGES = 1 << 13
READ_MESSAGE_HISTORY = 1 << 16

# A message carrying this many distinct reactions has hit Discord's per-message
# cap (error 30010), so a human physically CANNOT add the marker to it. Keeping
# it is the only honest choice: the absence of the mark says nothing.
REACTION_CAP = 20

# Pacing, not a limit. Discord publishes no rate limit for any route and says
# not to hard-code one, so this only spaces requests enough to stay clear of
# the per-IP invalid-request ceiling (10,000 per 10 minutes on 401/403/429,
# counted against the runner's IP rather than the token).
PACE = 0.35


# --------------------------------------------------------------------- HTTP


class Halt(Exception):
    """Something the run must not continue past. Never raised for a condition
    that merely keeps a message."""


def call(method, path, **kw):
    """One Discord request. Returns (status, body). Retries only on 429 and
    only as long as Discord asks.

    NEVER retries 401 or 403: both count toward the per-IP invalid-request
    ceiling, and neither becomes true by being asked again.
    """
    url = API + path
    for attempt in range(3):
        try:
            r = requests.request(
                method,
                url,
                headers={"Authorization": f"Bot {TOKEN}", "User-Agent": UA},
                timeout=(10, 30),
                **kw,
            )
        except requests.RequestException as e:
            print(f"    {method} failed: {type(e).__name__}")
            return None, {}

        if r.status_code == 429:
            wait = 5.0
            try:
                wait = float(r.json().get("retry_after", 5))
            except (ValueError, AttributeError, TypeError):
                pass
            wait = min(wait + 0.5, 30.0)
            print(f"    rate limited, waiting {wait:.1f}s")
            time.sleep(wait)
            continue

        # Proactive pacing off Discord's own headers, which is the only pacing
        # it endorses. Falls back to PACE when the headers are absent.
        remaining = r.headers.get("X-RateLimit-Remaining")
        reset_after = r.headers.get("X-RateLimit-Reset-After")
        if remaining == "0" and reset_after:
            try:
                time.sleep(min(float(reset_after) + 0.1, 10.0))
            except ValueError:
                time.sleep(PACE)
        else:
            time.sleep(PACE)

        if r.status_code == 204:
            return 204, {}
        try:
            return r.status_code, r.json()
        except ValueError:
            return r.status_code, {}
    return None, {}


def snowflake_time(mid):
    """UTC datetime a snowflake was created. The id carries its own timestamp,
    which is why this component needs no stored dates and no content."""
    return datetime.fromtimestamp(
        ((int(mid) >> SNOWFLAKE_SHIFT) + DISCORD_EPOCH_MS) / 1000, timezone.utc
    )


# ------------------------------------------------------------------- MARKER


def is_marker(emoji):
    """True if this reaction's emoji is the pushpin.

    Three checks, each load-bearing:

    `id is not None` rejects a CUSTOM emoji. Without it, anyone could upload a
    custom emoji named "pushpin" and mark messages the operator never marked.

    A non-str name is unparseable. `name` is documented `?string (can be null
    only in reaction emoji objects)`, so a deleted custom emoji leaves a
    reaction with a null name, and `None.replace` would crash the run.

    The VS16 strip is the one Unicode trap the pushpin does not dodge. U+1F4CC
    is a single code point with no skin-tone variants, but U+1F4CC and
    U+1F4CC U+FE0F compare unequal and NORMALISATION DOES NOT FIX IT (NFC
    leaves both unchanged, measured). Windows `win + .` and several Android
    keyboards append U+FE0F, so which client the human used decides what got
    stored.
    """
    if emoji.get("id") is not None:
        return False
    name = emoji.get("name")
    if not isinstance(name, str):
        return False
    return name.replace(VS16, "") == MARKER


def marker_in_array(msg):
    """True if the message object itself reports the marker.

    Measured 2026-09-05: `reactions` is OMITTED on an unreacted message, never
    present as []. `.get()` is therefore load-bearing rather than defensive
    style: `msg["reactions"]` raises, and a broad except around that would turn
    "unmarked" into a delete.
    """
    for r in msg.get("reactions") or []:
        if not isinstance(r, dict):
            return True  # unparseable entry: keep
        if is_marker(r.get("emoji") or {}) and (r.get("count", 1) or 0) > 0:
            return True
    return False


# Both encodings of the marker, because BOTH CAN BE STORED. The module cannot
# hold at once that a client may store either form (which is why is_marker
# strips VS16) and that querying one form is enough to authorise a delete.
# Querying only the bare form is exactly the compound failure the two-store
# design exists to prevent: a Windows `win + .` mark stored as U+1F4CC U+FE0F,
# an empty `reactions` array from the denormalised cache, a bare-form query
# that legitimately returns 200 with [], and both stores agree a visibly
# marked message is unmarked.
MARKER_KEYS = (
    urllib.parse.quote(MARKER),
    urllib.parse.quote(MARKER + VS16),
)


def marker_state(message_id):
    """'present', 'absent' or 'unknown', from the authoritative reactor store.

    The message object's `reactions` array is a denormalised cache. Discord's
    own root-cause comment on discord-api-docs#2750 calls it a hint "which we
    use as a hint to load the users + count", and it has been observed EMPTY at
    HTTP 200 on a message that genuinely carried a reaction. So the array may
    only ever ADD protection: it can never authorise a delete on its own.

    Four queries: two encodings by two reaction types. `GET Reactions` defaults
    to type=0 (normal) and SUPER REACTIONS ARE type=1, so querying only the
    default returns an empty user list for a super-react-only mark while the
    message object correctly reports count >= 1.

    THREE STATES, NOT TWO. The first version returned a bool, which collapsed
    "a reactor was found" and "the API would not answer" into one value, and
    the caller latched permanently on both. That records a keep-fact the run
    never measured, which is `first_run.baseline_by_cik` in CLAUDE.md's trap
    table rotated onto this component. Worse, a reactions route returning 403
    would latch every ripe message and `continue`, so no DELETE is ever issued
    and the 401/403 halt never fires: both operator tripwires bypassed by the
    branch that looks safest.

    'unknown' means keep this run and re-confirm next run, at no cost. A long
    outage then pushes len(condemned) toward MAX_DELETES and halts visibly,
    which is the right way for this to fail.
    """
    for key in MARKER_KEYS:
        for rtype in (0, 1):
            st, body = call(
                "GET",
                f"/channels/{CHANNEL_ID}/messages/{message_id}"
                f"/reactions/{key}?type={rtype}&limit=1",
            )
            if st != 200:
                # Includes 10014 Unknown Emoji, which must never be read as
                # "no reactors". Measured 2026-09-05: an unused marker returns
                # 200 with [], so a non-200 here is a genuine anomaly.
                print(f"    reaction check HTTP {st}; unknown, keeping")
                return "unknown"
            if not isinstance(body, list):
                return "unknown"
            if body:
                return "present"
    return "absent"


# -------------------------------------------------------------------- STATE


def load_state():
    """The latch, or a halt. Never a silent empty keep-set.

    THE FILE BEING ABSENT AND THE FILE BEING DAMAGED ARE DIFFERENT FACTS. Only
    absence is evidence of a first run; anything else that yields an empty
    `protected` is evidence of damage, and continuing would treat every marked
    message as unmarked and delete it.

    `fetch_pins` already refuses to run on a truncated or unreadable pin list
    for exactly this reason. The latch is the other keep-set and was not
    getting the same protection: `state.get("protected") or []` reads a missing
    key, a null and a real empty list identically, and a hand edit or a
    hand-resolved merge conflict produces the first two.

    `condemned` is deliberately NOT gated. Losing it only re-condemns, which
    costs one extra CONDEMN_HOURS of waiting and destroys nothing.
    """
    if not STATE_FILE.exists():
        return {"protected": [], "condemned": {}}
    try:
        data = json.loads(STATE_FILE.read_text())
    except json.JSONDecodeError:
        raise Halt("pushpin_state.json is not valid JSON")
    if not isinstance(data, dict) or not isinstance(data.get("protected"), list):
        raise Halt("pushpin_state.json has no readable `protected` list. "
                   "Refusing to run with an empty keep-set.")
    return data


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=1, sort_keys=True))


def persist(protected, condemned):
    """Write state now rather than at the end of the run.

    A LATCH IS A PURE KEEP-FACT. Writing it early can only ever preserve more,
    and writing it only after the deletes lets the destructive act proceed with
    the keep-fact unwritten. The first version had a single save_state call
    after the whole delete loop, with three `raise Halt` sites between the
    latch and it: a run that saw a marked message and then halted on a
    transient 403 discarded the latch entirely, and if the reaction was wiped
    before the next run (the exact event the latch exists for) that message was
    deleted with nothing anywhere recording that a human had marked it.
    """
    if DRY_RUN:
        return
    save_state({"protected": sorted(protected), "condemned": condemned})


# ---------------------------------------------------------------- PREFLIGHT


def preflight():
    """Establish everything the run depends on, or refuse to run. Every failure
    here halts; none degrades to a permissive default. A pin fetch that fell
    back to an empty set would silently unprotect every pinned message."""
    if not TOKEN:
        raise Halt("DISCORD_BOT_TOKEN is not set")
    if not CHANNEL_ID.isdigit():
        # Snowflakes serialise as JSON strings. "123" == 123 is silently False
        # in Python, and an int channel id would match nothing.
        raise Halt(f"PUSHPIN_CHANNEL_ID is not a snowflake: {CHANNEL_ID!r}")

    st, channel = call("GET", f"/channels/{CHANNEL_ID}")
    if st != 200:
        raise Halt(f"cannot read the target channel: HTTP {st} {channel.get('code', '')}")
    if channel.get("type") != GUILD_TEXT:
        # Deleting a forum or media post's first message is undocumented and
        # destructive: the first message IS the post and shares its id.
        raise Halt(f"channel type is {channel.get('type')}, not GUILD_TEXT(0)")

    assert_manage_messages(channel)
    pins = fetch_pins()
    print(f"  channel #{channel.get('name')}, {len(pins)} pinned")
    return pins


def assert_manage_messages(channel):
    """Refuse to run without MANAGE_MESSAGES in the target channel.

    Without this the permission is discovered by a 403 in the middle of the
    delete loop, which is the safe direction but happens after the latch has
    been computed and after some messages may already be gone. Failing in
    preflight moves it to before anything is at risk.

    The computation mirrors Discord's documented order and the audit in
    probe_pushpin_scope.py: base role permissions, then the @everyone channel
    overwrite, then the union of role overwrites, then the member overwrite
    last. Getting the order wrong yields a confident number for a
    configuration that does not exist.

    It cannot catch everything, and the gap is named rather than hidden:
    MANAGE_MESSAGES is 2FA-elevated, so in a guild requiring 2FA whose app
    owner has none, every field below reads correct and every delete still
    fails 403. That case is caught in the delete loop.
    """
    st, me = call("GET", "/users/@me")
    if st != 200:
        raise Halt(f"GET /users/@me returned {st}: the token is wrong or revoked")
    my_id, guild_id = me["id"], channel.get("guild_id")

    st, member = call("GET", f"/guilds/{guild_id}/members/{my_id}")
    if st != 200:
        raise Halt(f"cannot read the bot's guild member object: HTTP {st}")
    st, roles = call("GET", f"/guilds/{guild_id}/roles")
    if st != 200:
        raise Halt(f"cannot read guild roles: HTTP {st}")

    rolemap = {r["id"]: int(r["permissions"]) for r in roles}
    my_roles = set(member.get("roles") or []) | {guild_id}
    perms = 0
    for rid in my_roles:
        perms |= rolemap.get(rid, 0)

    if perms & ADMINISTRATOR:
        # Administrator bypasses every channel overwrite, so the scoping this
        # component relies on is inert and the blast radius is the whole guild.
        raise Halt("the bot holds ADMINISTRATOR. Every channel overwrite is "
                   "bypassed and the scoping is inert. Refusing to run.")

    ow = {o["id"]: o for o in channel.get("permission_overwrites") or []}
    if guild_id in ow:
        perms &= ~int(ow[guild_id]["deny"])
        perms |= int(ow[guild_id]["allow"])
    allow = deny = 0
    for rid in my_roles - {guild_id}:
        if rid in ow:
            allow |= int(ow[rid]["allow"])
            deny |= int(ow[rid]["deny"])
    perms &= ~deny
    perms |= allow
    if my_id in ow:
        perms &= ~int(ow[my_id]["deny"])
        perms |= int(ow[my_id]["allow"])

    missing = [
        name for name, bit in (
            ("VIEW_CHANNEL", VIEW_CHANNEL),
            ("READ_MESSAGE_HISTORY", READ_MESSAGE_HISTORY),
            ("MANAGE_MESSAGES", MANAGE_MESSAGES),
        )
        if not perms & bit
    ]
    if missing:
        raise Halt(f"missing in the target channel: {', '.join(missing)}")


def fetch_pins():
    """Every pinned message id, or halt.

    The DEPRECATED `GET /channels/{id}/pins` is still live and is what older
    libraries call. It returns "the first 50 pinned messages" with no cursor
    and no has_more, so past 50 pins the protection set is silently short and
    THE TRUNCATION LANDS ON THE KEEP LIST. This uses the current route and
    refuses to proceed on a truncated page.
    """
    st, body = call("GET", f"/channels/{CHANNEL_ID}/messages/pins?limit=50")
    if st != 200:
        raise Halt(f"cannot read the pin list: HTTP {st}. Refusing to run with an "
                   f"empty keep-set.")

    # Tolerate both shapes rather than betting on one: the current route
    # returns {items: [...], has_more: bool}, the deprecated one a bare list.
    if isinstance(body, dict):
        items = body.get("items") or []
        if body.get("has_more"):
            raise Halt("the pin list is truncated (has_more), so the keep-set "
                       "would be short. Paginate before running.")
    elif isinstance(body, list):
        items = body
        if len(items) >= 50:
            raise Halt("the pin route returned a full page with no has_more, so "
                       "the keep-set may be truncated.")
    else:
        raise Halt(f"unrecognised pin payload: {type(body).__name__}")

    out = set()
    for entry in items:
        msg = entry.get("message") if isinstance(entry, dict) and "message" in entry else entry
        if isinstance(msg, dict) and msg.get("id"):
            out.add(msg["id"])
    return out


# ----------------------------------------------------------------- SNAPSHOT


def snapshot():
    """Every message in the channel, newest first, content stripped at ingest.

    Read-only. Nothing is deleted while paging, because paging a collection you
    are mutating either skips messages or never terminates, and the
    non-terminating case ends at Discord's invalid-request ceiling.
    """
    out, cursor, pages = [], None, 0
    while True:
        # limit=100 EXPLICIT. The default is 50, which would double the request
        # count and make any pacing estimate wrong by 2x.
        path = f"/channels/{CHANNEL_ID}/messages?limit=100"
        if cursor:
            path += f"&before={cursor}"
        st, page = call("GET", path)
        if st != 200 or not isinstance(page, list):
            raise Halt(f"history fetch returned HTTP {st} on page {pages + 1}")
        pages += 1

        if not page:
            if pages == 1:
                # A bot missing READ_MESSAGE_HISTORY gets 200 with an empty
                # array, not an error, and it is indistinguishable from an
                # empty channel.
                raise Halt("the first page of history is empty. Either the "
                           "channel is empty or READ_MESSAGE_HISTORY is missing, "
                           "and those are indistinguishable from here.")
            break

        for m in page:
            # Never assume the API scoped the result to the channel asked for.
            if m.get("channel_id") != CHANNEL_ID:
                continue
            # THE PRIVACY BOUNDARY. Dropped before anything is logged, counted
            # or stored, so a MESSAGE_CONTENT toggle flipped in the Developer
            # Portal changes nothing observable about this program.
            for field in ("content", "embeds", "attachments", "components"):
                m.pop(field, None)
            out.append(m)

        if len(page) < 100:
            break
        # Newest-to-oldest regardless of anchor, so `before` takes the LAST id
        # of the page. The intuitive first-id would re-read one window forever.
        cursor = page[-1]["id"]
    return out


# ----------------------------------------------------------------- CLASSIFY


def classify(msg, pins, protected, cutoff):
    """(verdict, reason). Ordered so the cheapest and most certain keeps come
    first, and so nothing reaches the paid reaction check that a free signal
    already saved."""
    mid = msg["id"]

    if mid in protected:
        return "keep", "latched"          # marked once, protected forever
    if "webhook_id" in msg:
        return "keep", "webhook"          # the monitor's record
    if marker_in_array(msg):
        return "keep", "marked"
    if msg.get("pinned"):
        return "keep", "pinned"
    if mid in pins:
        return "keep", "pin-list"         # independent of the per-message flag
    if len(msg.get("reactions") or []) >= REACTION_CAP:
        return "keep", "reaction-cap"     # a human cannot add the marker here
    if msg.get("flags", 0) & HAS_THREAD:
        return "keep", "has-thread"
    if "thread" in msg:
        return "keep", "has-thread"       # both signals, checked independently
    if msg.get("type") not in DELETABLE_TYPES:
        return "keep", "not-user-content"
    # THE AGE CHECK IS LAST, AND MOVING IT IS THE ONE TIDY-UP THAT BREAKS THIS
    # FILE SILENTLY. Checking age first reads more naturally and would return
    # "too-new" for a marked message still inside the window, so it would never
    # reach `newly_marked` and would never be latched. The mark would then have
    # to survive on Discord's side for the full 31 days to protect anything,
    # which is exactly the durability the latch exists to remove.
    if snowflake_time(mid) >= cutoff:
        return "keep", "too-new"
    return "delete", "aged"


# ------------------------------------------------------------------- REPORT


def ops(text):
    """Post one line to the ops channel. Never silently.

    press_monitor and failure-notice.yml both decided this question in the
    opposite direction for this exact webhook: an unset value prints a line,
    and a non-2xx is reported rather than swallowed. `requests` does not raise
    on 4xx, so a rotated webhook's 404 is invisible without the check.
    """
    if DRY_RUN:
        return
    if not OPS_WEBHOOK:
        print("  WEBHOOK_URL_OPS is not set, not posted")
        return
    try:
        r = requests.post(OPS_WEBHOOK, json={"content": text}, timeout=15)
    except requests.RequestException as e:
        print(f"  ops post failed: {type(e).__name__}")
        return
    if r.status_code >= 300:
        print(f"  ops webhook returned {r.status_code}: {r.text[:120]}")


# --------------------------------------------------------------------- MAIN


def main():
    if DRY_RUN:
        print("DRY RUN. Nothing is deleted, no state is saved.\n")

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=AGE_DAYS + GRACE_DAYS)
    print(f"Pushpin: deleting non-webhook messages older than "
          f"{AGE_DAYS}+{GRACE_DAYS} days (before {cutoff:%Y-%m-%d %H:%M}Z)")

    pins = preflight()
    state = load_state()
    protected = set(state.get("protected") or [])
    condemned = dict(state.get("condemned") or {})
    print(f"  {len(protected)} latched, {len(condemned)} already condemned")

    messages = snapshot()
    print(f"  {len(messages)} messages in channel\n")

    # WHAT IS DELIBERATELY NOT LOGGED: per-message ids and per-message ages.
    # This repo is public, so its Actions logs are world-readable, and either
    # one reconstructs a timeline of activity in a private channel. Hashing the
    # id would be theatre while the age is printed beside it, because at a known
    # run time an age IS a timestamp. Aggregates validate the rule, which is
    # what a dry run is for; they cannot tell you what was destroyed, and
    # nothing ever will.
    reasons, to_delete, newly_marked = {}, [], []
    webhook_seen = webhook_condemned = 0
    for m in messages:
        is_hook = "webhook_id" in m
        webhook_seen += is_hook
        verdict, reason = classify(m, pins, protected, cutoff)
        reasons[reason] = reasons.get(reason, 0) + 1
        if reason == "marked":
            newly_marked.append(m["id"])
        if verdict == "delete":
            to_delete.append(m["id"])
            webhook_condemned += is_hook

    print("  verdicts:")
    for reason, n in sorted(reasons.items(), key=lambda kv: -kv[1]):
        print(f"    {n:4d}  {reason}")

    # A BUCKETED HISTOGRAM, not per-message ages. It confirms the cutoff
    # arithmetic (nothing under AGE_DAYS+GRACE_DAYS may appear) while revealing
    # far less than a single message's exact age would. Without it the reason
    # counts alone cannot tell a correct cutoff from one a month out, and the
    # rollout plan rests on a person reading exactly that from a dry run.
    if to_delete:
        buckets = {}
        for mid in to_delete:
            days = (now - snowflake_time(mid)).days
            label = ("31-60d" if days < 61 else
                     "61-90d" if days < 91 else
                     "91-180d" if days < 181 else "180d+")
            buckets[label] = buckets.get(label, 0) + 1
        order = ["31-60d", "61-90d", "91-180d", "180d+"]
        print("  age of the delete set: "
              + ", ".join(f"{buckets[b]} {b}" for b in order if b in buckets))
        youngest = min((now - snowflake_time(m)).days for m in to_delete)
        if youngest < AGE_DAYS + GRACE_DAYS:
            raise Halt(f"a message {youngest} days old is in the delete set, "
                       f"under the {AGE_DAYS}+{GRACE_DAYS} day floor. The cutoff "
                       f"arithmetic is wrong.")

    # THE LATCH. A message seen carrying the marker is protected permanently,
    # so the documented ways a mark disappears without the human touching it (a
    # reaction-role or starboard bot calling Delete All Reactions, a moderator
    # clearing them, the 2021 custom-emoji mass wipe where one user un-reacting
    # removed everyone's mark) cannot expose it on a later run.
    protected |= set(newly_marked)
    if newly_marked:
        print(f"\n  latched {len(newly_marked)} newly marked message(s)")
    # PERSISTED HERE, before the webhook halt, before the cap halt, and before
    # any delete. See persist(). Everything after this line can fail without
    # losing a keep-fact this run measured.
    persist(protected, condemned)

    if reasons.get("marked", 0) + reasons.get("latched", 0) == 0:
        # A warning, not a halt. The first draft halted, reasoning from a
        # CUSTOM-emoji design where the marker can be deleted from the server.
        # A Unicode emoji cannot be deleted, and the measured marker density is
        # about 1 in 100, so an ordinary window legitimately contains none.
        print("\n  WARNING: no message carries the marker in this window")

    # HALT ON A BROKEN CLASSIFIER, not on a quiet channel.
    #
    # Two earlier versions of this guard were both wrong. "Zero webhook
    # messages were kept" halts forever on a channel measured at 1 webhook
    # message in 100, because an ordinary window contains none. "Webhook seen
    # but no `webhook` reason recorded" then false-fires on a webhook message
    # that is ALSO latched or marked, since classify() reaches those rules
    # first and returns their reason instead.
    #
    # This tests the only thing that actually matters and cannot be reached any
    # other way: a message carrying webhook_id was condemned. Nothing but a
    # broken exemption produces that.
    print(f"  webhook messages: {webhook_seen} seen, {webhook_condemned} condemned")
    if webhook_condemned:
        raise Halt(f"{webhook_condemned} message(s) carrying webhook_id were "
                   f"condemned. The webhook exemption is broken. Nothing deleted.")

    # ------------------------------------------------------------- CONDEMN

    stamp = now.isoformat()
    fresh = [mid for mid in to_delete if mid not in condemned]
    for mid in fresh:
        condemned[mid] = stamp
    # A condemned message that no longer qualifies (somebody marked or pinned
    # it after it was condemned) is released rather than left pending.
    released = [mid for mid in condemned if mid not in to_delete]
    for mid in released:
        condemned.pop(mid)
    print(f"\n  condemned {len(fresh)} new, released {len(released)}, "
          f"{len(condemned)} pending")

    if len(condemned) > MAX_DELETES:
        raise Halt(f"{len(condemned)} messages are condemned, over the "
                   f"{MAX_DELETES} cap. Refusing to run.")

    # --------------------------------------------------------------- DELETE

    ripe = [
        mid for mid, when in condemned.items()
        if now - datetime.fromisoformat(when) >= timedelta(hours=CONDEMN_HOURS)
    ]
    # key=int, not a bare sort. Snowflakes are STRINGS, and a lexicographic
    # sort orders "999..." (18 digits) after "1545..." (19 digits), which is
    # backwards. Harmless today because ids in one channel share a length, and
    # silently wrong the day they do not.
    ripe.sort(key=int)  # oldest first, so a truncated run makes real progress
    print(f"  {len(ripe)} have served the {CONDEMN_HOURS}h condemned period")

    if DRY_RUN:
        print("\nDRY RUN")
        # `ripe` IS ALWAYS ZERO ON A DRY RUN, and printing it as "would delete
        # N" is a lie that survives every review. A dry run saves no state, so
        # `condemned` on disk is permanently empty, every id is stamped with
        # the same `now` used in the ripeness comparison, and the delta is
        # exactly zero forever, including long after the channel has genuinely
        # eligible messages. Say which number means what.
        print(f"  ripe now: {len(ripe)}. This is ALWAYS 0 on a dry run, because")
        print(f"    no state is saved, so nothing has served the "
              f"{CONDEMN_HOURS}h period.")
        print(f"  the number that matters: {len(condemned)} would be condemned,")
        print(f"    and deletable no sooner than {CONDEMN_HOURS}h after a LIVE run.")

        # EXERCISE THE DELETE DECISION. Without this a green dry run proves the
        # classifier and NOTHING about the path that actually authorises a
        # delete: marker_state is where the two-store rule and both marker
        # encodings live, and it is the only code a dry run could reach that
        # decides whether something dies. The calls are read-only.
        sample = sorted(condemned, key=int)[:DRY_SAMPLE]
        if sample:
            tally = {}
            for mid in sample:
                s = marker_state(mid)
                tally[s] = tally.get(s, 0) + 1
            print(f"  reaction store, {len(sample)} sampled: "
                  + ", ".join(f"{v} {k}" for k, v in sorted(tally.items())))
            if tally.get("unknown"):
                print("    'unknown' means the API would not answer. Those keep.")
        print("\nNothing was deleted and no state was saved.")
        return

    deleted = rescued = unknown = 0
    for mid in ripe:
        # RE-CONFIRMED IMMEDIATELY BEFORE THE CALL, not once per sweep. The
        # mark can land between the snapshot and this line.
        state_of = marker_state(mid)

        if state_of == "present":
            # Measured, so it earns a permanent record.
            protected.add(mid)
            condemned.pop(mid, None)
            rescued += 1
            # Persisted immediately. This is the highest-value latch in the
            # file (a mark the live API confirmed at the moment of deletion)
            # and a Halt later in this loop must not discard it.
            persist(protected, condemned)
            continue

        if state_of == "unknown":
            # NOT latched. The run did not measure a mark, it failed to ask.
            # Left condemned, re-confirmed next run at no cost. A sustained
            # outage pushes len(condemned) at the MAX_DELETES halt, which is
            # the visible way for this to fail.
            unknown += 1
            continue

        # Only ever the message route. A thread shares its starter message's
        # id, so the same snowflake is valid on DELETE /channels/{id}, which
        # removes the thread and everything in it and cannot be restored by
        # anyone, including Discord Support. No code path here builds that URL.
        st, body = call("DELETE", f"/channels/{CHANNEL_ID}/messages/{mid}")
        if st in (204, 200):
            deleted += 1
            condemned.pop(mid, None)
        elif st == 404:
            condemned.pop(mid, None)  # already gone; not a fault
        elif st in (401, 403):
            code = body.get("code") if isinstance(body, dict) else None
            # The JSON code separates causes the status alone collapses:
            # 50013 is the permission removed, 50001 is the channel overwrite
            # gone, and a 2FA-required guild whose app owner lacks 2FA fails
            # here too. Blaming one of the three in the message would send the
            # next reader to the wrong screen.
            raise Halt(f"HTTP {st} code {code} on delete after {deleted} "
                       f"deleted. Check, in order: the channel overwrite, the "
                       f"bot's MANAGE_MESSAGES, and whether the guild requires "
                       f"2FA while the app owner has none.")
        else:
            code = body.get("code") if isinstance(body, dict) else None
            print(f"    unexpected HTTP {st} code {code}; leaving condemned")

    persist(protected, condemned)

    print(f"\ndeleted {deleted}, rescued {rescued}, unknown {unknown}, "
          f"{len(condemned)} still pending, {len(protected)} latched")
    if deleted or rescued:
        ops(f"pushpin: {deleted} deleted, {rescued} rescued, "
            f"{len(protected)} latched")


if __name__ == "__main__":
    try:
        main()
    except Halt as e:
        # A halt is a refusal to act, not a crash. It exits non-zero so the
        # run goes red and failure-notice.yml posts a line, because a component
        # that silently declines to delete looks exactly like one with nothing
        # to do.
        sys.exit(f"HALT: {e}")
