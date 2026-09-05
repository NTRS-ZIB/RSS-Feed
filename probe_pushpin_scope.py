#!/usr/bin/env python3
"""Read-only audit for the Pushpin bot. Deletes nothing, posts nothing, writes
no state.

Two jobs, both of which have to pass before `pushpin.py` is written:

1. PROVE THE PERMISSION SCOPING. Discord has no first-party view of a bot's
   effective permissions in a given channel, so the only real check is to
   compute them the way Discord does and then probe every channel to confirm
   the computation. A bot still holding VIEW_CHANNEL server-wide looks
   identical in the UI to one correctly scoped.

2. SETTLE THE FOUR OPEN QUESTIONS in the design spec that reading the docs
   could not. Each one is load-bearing for a keep rule, and each is currently
   a defensive inference rather than a measured fact.

Run it through the workflow, never locally:

    gh workflow run "Pushpin scope probe"

WHAT THIS DELIBERATELY DOES NOT PRINT: message ids, message content, author
names or ids, and timestamps of individual messages. The Actions log on this
repo is world-readable, and a list of message snowflakes is a public timeline
of activity in a private channel. Channel NAMES are printed, because a leak you
cannot name is a leak you cannot fix.
"""

import os
import sys
import time
import json
import urllib.parse

import requests

API = "https://discord.com/api/v10"

TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "")
CHANNEL_ID = os.environ.get("PUSHPIN_CHANNEL_ID", "")

# Discord returns error 40333 to requests it considers poorly identified, and
# that reads as a permissions problem rather than a header problem. Same shape
# as the SEC_USER_AGENT trap in CLAUDE.md: a wrong value fails everything at
# once and looks like an outage.
UA = "Pushpin-scope-probe (github.com/NTRS-ZIB/RSS-Feed)"

# Permission bits. Named rather than inlined because a wrong shift here is
# silent: it computes a plausible number for the wrong permission.
ADMINISTRATOR = 1 << 3
VIEW_CHANNEL = 1 << 10
MANAGE_MESSAGES = 1 << 13
READ_MESSAGE_HISTORY = 1 << 16

# Channel types worth probing. Voice channels can 403 for missing CONNECT
# rather than for missing VIEW_CHANNEL, which would read as a pass for the
# wrong reason.
GUILD_TEXT, GUILD_ANNOUNCEMENT = 0, 5
TEXTLIKE = {GUILD_TEXT, GUILD_ANNOUNCEMENT}
GUILD_CATEGORY = 4

# The keep-marker. Written escaped so it is auditable in a diff: a bare emoji
# in source is one invisible variation selector away from a different string.
MARKER = "\U0001F4CC"
VS16 = "️"

# Discord publishes no rate limit for any route and says not to hard-code one.
# This is pacing, not a limit: enough to keep a scan of a few dozen channels
# from tripping the per-IP invalid-request ceiling (10,000 per 10 minutes,
# counted on 401/403/429, and applied to the runner's IP rather than to us).
PACE = 0.35

# Bounds a server with an unexpected number of channels. Every 403 the scan
# generates counts toward that ceiling, so an unbounded sweep of a large guild
# is the one way this read-only probe could cause harm.
MAX_PROBE_CHANNELS = 200


def call(path):
    """GET one endpoint. Returns (status, parsed_body). Never raises for HTTP
    status: a 403 is the answer to some of the questions below, not a fault."""
    url = API + path
    for attempt in range(3):
        try:
            r = requests.get(
                url,
                headers={"Authorization": f"Bot {TOKEN}", "User-Agent": UA},
                timeout=(10, 30),
            )
        except requests.RequestException as e:
            print(f"    request failed: {type(e).__name__}")
            return None, {}

        if r.status_code == 429:
            # Honour Discord's own figure. Retrying early generates the status
            # that trips the ban, so a self-invented floor is worse than none.
            wait = 5.0
            try:
                wait = float(r.json().get("retry_after", 5))
            except (ValueError, AttributeError, TypeError):
                pass
            wait = min(wait + 0.5, 30.0)
            print(f"    rate limited, waiting {wait:.1f}s")
            time.sleep(wait)
            continue

        time.sleep(PACE)
        try:
            return r.status_code, r.json()
        except ValueError:
            return r.status_code, {}
    return None, {}


def effective(base, channel, my_roles, my_id, guild_id):
    """Compute effective permissions for the bot in one channel, in Discord's
    documented order. Getting this order wrong produces a confident number for
    a configuration that does not exist."""
    if base & ADMINISTRATOR:
        return ~0  # bypasses every overwrite; the audit below is meaningless

    perms = base
    ow = {o["id"]: o for o in channel.get("permission_overwrites", [])}

    # 1. The @everyone overwrite, whose id is the guild id.
    if guild_id in ow:
        perms &= ~int(ow[guild_id]["deny"])
        perms |= int(ow[guild_id]["allow"])

    # 2. Every role overwrite, accumulated before being applied. Allows are
    #    unioned across roles, so one stale allow on any role the bot holds
    #    beats a deny on another.
    allow = deny = 0
    for rid in my_roles - {guild_id}:
        if rid in ow:
            allow |= int(ow[rid]["allow"])
            deny |= int(ow[rid]["deny"])
    perms &= ~deny
    perms |= allow

    # 3. The member overwrite, applied last. This is what the setup uses, and
    #    it is last precisely so nothing can widen or beat it.
    if my_id in ow:
        perms &= ~int(ow[my_id]["deny"])
        perms |= int(ow[my_id]["allow"])

    return perms


def describe(perms):
    return (
        f"view={bool(perms & VIEW_CHANNEL)} "
        f"history={bool(perms & READ_MESSAGE_HISTORY)} "
        f"manage={bool(perms & MANAGE_MESSAGES)}"
    )


def main():
    if not TOKEN:
        sys.exit("DISCORD_BOT_TOKEN is not set.")
    if not CHANNEL_ID:
        sys.exit("PUSHPIN_CHANNEL_ID is not set.")
    if not CHANNEL_ID.isdigit():
        # Snowflakes serialise as strings and compare unequal to ints. A
        # non-numeric value here would match nothing and read as a clean run.
        sys.exit(f"PUSHPIN_CHANNEL_ID is not a snowflake: {CHANNEL_ID!r}")

    failures = []

    # ---------------------------------------------------------------- IDENTITY

    print("=" * 60)
    print("IDENTITY")
    print("=" * 60)

    st, me = call("/users/@me")
    if st != 200:
        sys.exit(f"GET /users/@me returned {st}. The token is wrong or revoked.")
    my_id = me["id"]
    print(f"  bot            {me.get('username')}  id {my_id}")

    # The guild id is derived from the channel rather than configured, so
    # there is one fewer secret to keep in step with reality.
    st, target = call(f"/channels/{CHANNEL_ID}")
    if st != 200:
        sys.exit(
            f"GET /channels/{{PUSHPIN_CHANNEL_ID}} returned {st} "
            f"{target.get('code', '')}. The bot cannot see the target channel, "
            f"so the overwrite granting VIEW_CHANNEL is missing."
        )
    guild_id = target.get("guild_id")
    print(f"  target channel #{target.get('name')}  type {target.get('type')}")
    print(f"  guild          {guild_id}")

    if target.get("type") != GUILD_TEXT:
        failures.append(
            f"target channel type is {target.get('type')}, not GUILD_TEXT(0). "
            f"pushpin.py must refuse forum and media channels: deleting a "
            f"forum post's first message is undocumented and destructive."
        )

    # ------------------------------------------------------------ BASE PERMS

    print()
    print("=" * 60)
    print("GUILD-LEVEL PERMISSIONS  (want: no MANAGE_MESSAGES here)")
    print("=" * 60)

    st, member = call(f"/guilds/{guild_id}/members/{my_id}")
    if st != 200:
        sys.exit(f"GET guild member returned {st}.")
    st, roles = call(f"/guilds/{guild_id}/roles")
    if st != 200:
        sys.exit(f"GET guild roles returned {st}.")

    rolemap = {r["id"]: int(r["permissions"]) for r in roles}
    my_roles = set(member.get("roles", [])) | {guild_id}
    base = 0
    for rid in my_roles:
        base |= rolemap.get(rid, 0)

    print(f"  roles held     {len(my_roles)}")
    print(f"  base perms     {describe(base)}")

    if base & ADMINISTRATOR:
        failures.append(
            "the bot holds ADMINISTRATOR. It bypasses every channel overwrite, "
            "so the entire scoping below is inert regardless of what the UI shows."
        )
    if base & MANAGE_MESSAGES:
        failures.append(
            "MANAGE_MESSAGES is granted at guild level, so the bot can delete "
            "in every channel that does not explicitly deny it. Remove it from "
            "the role rather than relying on channel denies."
        )
    if base & VIEW_CHANNEL:
        # Expected, and not a fault: @everyone grants this to everybody. It is
        # why the setup is a denylist and why the per-channel scan below is the
        # thing that actually establishes scope.
        print("  note: VIEW_CHANNEL present at base (@everyone grants it to all)")

    # ------------------------------------------------------- PER-CHANNEL SCAN

    print()
    print("=" * 60)
    print("PER-CHANNEL SCOPE  (want: the target only)")
    print("=" * 60)

    st, channels = call(f"/guilds/{guild_id}/channels")
    if st != 200:
        sys.exit(f"GET guild channels returned {st}.")

    leaks, latent, probed = [], [], 0
    print(f"  {len(channels)} channels in guild")

    for ch in channels:
        if ch.get("type") == GUILD_CATEGORY:
            continue
        perms = effective(base, ch, my_roles, my_id, guild_id)
        name, cid = ch.get("name"), ch["id"]
        view = bool(perms & VIEW_CHANNEL)
        manage = bool(perms & MANAGE_MESSAGES)

        if cid == CHANNEL_ID:
            print(f"  TARGET  #{name}: {describe(perms)}")
            need = VIEW_CHANNEL | READ_MESSAGE_HISTORY | MANAGE_MESSAGES
            if perms & need != need:
                failures.append(
                    f"the target channel #{name} is missing one of the three "
                    f"permissions: {describe(perms)}. Pushpin cannot work."
                )
        elif view:
            leaks.append((name, ch.get("type")))
        elif manage:
            latent.append(name)

    if leaks:
        print(f"  LEAK    {len(leaks)} other channels are visible to the bot:")
        for n, t in leaks[:40]:
            # The type is printed because it explains a disagreement between
            # this scan and the live probe below, which only reads text-like
            # channels. A leak the live probe stays silent about is not a
            # contradiction: it is a channel type it never asked about.
            note = "" if t in TEXTLIKE else "  (not live-probed: non-text type)"
            print(f"            #{n}  type {t}{note}")
        if len(leaks) > 40:
            print(f"            ... and {len(leaks) - 40} more")
        failures.append(
            f"{len(leaks)} channels other than the target grant VIEW_CHANNEL. "
            f"Deny it on their category, or on the channel if it is de-synced."
        )
    else:
        print("  no other channel is visible to the bot")

    if latent:
        # Not live access, because MANAGE_MESSAGES without VIEW_CHANNEL cannot
        # be exercised. Still worth naming: it means the role is not empty.
        print(f"  latent  {len(latent)} channels grant manage without view")

    # -------------------------------------------------- LIVE PROBE, READ ONLY

    print()
    print("=" * 60)
    print("LIVE PROBE  (want: 403/50001 everywhere but the target)")
    print("=" * 60)

    for ch in channels:
        if probed >= MAX_PROBE_CHANNELS:
            print(f"  stopped at {MAX_PROBE_CHANNELS} channels (cap)")
            break
        if ch.get("type") not in TEXTLIKE or ch["id"] == CHANNEL_ID:
            continue
        probed += 1
        st, body = call(f"/channels/{ch['id']}/messages?limit=1")
        code = body.get("code") if isinstance(body, dict) else None
        name = ch.get("name")
        if st == 403:
            continue  # the wanted outcome, printed only in aggregate below
        if st == 200:
            n = len(body) if isinstance(body, list) else "?"
            if n == 0:
                failures.append(
                    f"#{name} returned 200 with an empty list. That is NOT a "
                    f"denial: it is what a channel the bot can see but lacks "
                    f"READ_MESSAGE_HISTORY in returns, and it is indistinguishable "
                    f"from an empty channel."
                )
            else:
                failures.append(f"#{name} returned 200 with {n} message(s): readable.")
        else:
            print(f"  #{name}: unexpected status {st} code {code}")

    print(f"  probed {probed} other text channels")

    # ------------------------------------------- THE FOUR OPEN SPEC QUESTIONS

    print()
    print("=" * 60)
    print("OPEN QUESTIONS FROM THE SPEC")
    print("=" * 60)

    st, msgs = call(f"/channels/{CHANNEL_ID}/messages?limit=100")
    if st != 200 or not isinstance(msgs, list):
        print(f"  cannot read target channel history: {st}")
        msgs = []
    print(f"  sampled {len(msgs)} messages from the target channel\n")

    # Q0 (not in the spec, but the privacy claim rests on it): is content
    # actually empty? If it is not, the MESSAGE_CONTENT intent is enabled and
    # the design's central claim is false. Never print the content itself.
    with_content = sum(1 for m in msgs if m.get("content"))
    print(f"  content gating   {len(msgs) - with_content}/{len(msgs)} messages "
          f"have EMPTY content")
    if with_content:
        print(f"                   {with_content} carry text. Expected only for "
              f"messages that @mention the bot.")
        if with_content > len(msgs) * 0.5:
            failures.append(
                f"{with_content} of {len(msgs)} messages returned non-empty "
                f"content. The MESSAGE_CONTENT intent is almost certainly ON. "
                f"Turn it off in the Developer Portal."
            )

    # Q1: is `reactions` omitted, or present as []? The spec's predicate treats
    # absence as UNCONFIRMED rather than unmarked, so either answer is safe,
    # but knowing which lets the logging distinguish them.
    absent = sum(1 for m in msgs if "reactions" not in m)
    empty = sum(1 for m in msgs if m.get("reactions") == [])
    present = sum(1 for m in msgs if m.get("reactions"))
    print(f"\n  Q1 reactions     absent-key={absent}  empty-list={empty}  "
          f"populated={present}")
    if absent and not empty:
        print("                   -> OMITTED when unreacted. `m['reactions']` "
              "would KeyError.")
    elif empty and not absent:
        print("                   -> PRESENT AS [] when unreacted.")
    elif absent and empty:
        print("                   -> BOTH shapes occur. Handle each.")

    # Q4: do any messages carry webhook_id, and does anything unexpected?
    # A wider-than-intended exemption is the failure that keeps human messages
    # alive forever, which is harmless, and the one that keeps a bot's messages
    # alive, which may not be what was wanted.
    hooks = [m for m in msgs if "webhook_id" in m]
    bots = [m for m in msgs if m.get("author", {}).get("bot") and "webhook_id" not in m]
    humans = [m for m in msgs if not m.get("author", {}).get("bot")]
    print(f"\n  Q4 authorship    webhook={len(hooks)}  "
          f"bot-not-webhook={len(bots)}  human={len(humans)}")
    if bots:
        print("                   -> messages from bots WITHOUT webhook_id exist. "
              "These are DELETABLE under the current rule.")

    types = {}
    for m in msgs:
        types[m.get("type")] = types.get(m.get("type"), 0) + 1
    print(f"  message types    {dict(sorted(types.items()))}")
    unknown = set(types) - {0, 19, 20, 23}
    if unknown:
        print(f"                   -> types {sorted(unknown)} are outside the "
              f"delete allow-set and will be KEPT.")

    # Q2: what does the reactions route return for a marker nobody has used?
    # The two-store design rests on telling 200-with-[] apart from 10014.
    unreacted = next((m for m in msgs if not m.get("reactions")), None)
    if unreacted:
        emoji = urllib.parse.quote(MARKER)
        st, body = call(
            f"/channels/{CHANNEL_ID}/messages/{unreacted['id']}"
            f"/reactions/{emoji}?type=0",
        )
        code = body.get("code") if isinstance(body, dict) else None
        shape = "[]" if body == [] else f"code {code}"
        print(f"\n  Q2 unused marker HTTP {st}, {shape}")
        if st == 200 and body == []:
            print("                   -> 200 with []. Distinguishable from an error.")
        elif code == 10014:
            print("                   -> 10014 Unknown Emoji. MUST be treated as "
                  "KEEP, not as 'no reactors'.")
    else:
        print("\n  Q2 unused marker  no unreacted message in the sample; retry later")

    # Q3: does type=0 exclude burst (super) reactors? Only answerable if a
    # super-reacted message exists. Reporting that it could not be tested is a
    # finding, not a gap: the guard stays either way.
    marked = [
        m for m in msgs
        if any(
            (r.get("emoji") or {}).get("id") is None
            and isinstance((r.get("emoji") or {}).get("name"), str)
            and (r["emoji"]["name"]).replace(VS16, "") == MARKER
            for r in (m.get("reactions") or [])
        )
    ]
    print(f"\n  Q3 marker in use {len(marked)} message(s) carry {MARKER}")
    if marked:
        m = marked[0]
        r = next(r for r in m["reactions"]
                 if isinstance((r.get("emoji") or {}).get("name"), str)
                 and r["emoji"]["name"].replace(VS16, "") == MARKER)
        det = r.get("count_details") or {}
        print(f"                   count={r.get('count')} "
              f"normal={det.get('normal')} burst={det.get('burst')}")
        emoji = urllib.parse.quote(MARKER)
        for t in (0, 1):
            st, body = call(
                f"/channels/{CHANNEL_ID}/messages/{m['id']}"
                f"/reactions/{emoji}?type={t}",
            )
            n = len(body) if isinstance(body, list) else "err"
            print(f"                   type={t}: HTTP {st}, {n} reactor(s)")
        print("                   -> if type=0 and type=1 differ, querying only "
              "the default would delete super-reacted messages.")
    else:
        print(f"                   react {MARKER} to a message and re-run to "
              f"settle Q3.")

    # ------------------------------------------------------------- VERDICT

    print()
    print("=" * 60)
    if failures:
        print(f"FAILED: {len(failures)} problem(s)")
        print("=" * 60)
        for i, f in enumerate(failures, 1):
            print(f"  {i}. {f}")
        sys.exit(1)
    print("PASSED: the bot reaches exactly one channel, with all three permissions.")
    print("=" * 60)


if __name__ == "__main__":
    main()
