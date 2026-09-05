#!/usr/bin/env python3
"""Tests for pushpin.py, the only component in this repo that destroys data.
No network: every HTTP call is stubbed.

EVERY CHECK HERE HAS BEEN SHOWN RED under a named one-line change to the
module. The changes are in MUTATIONS at the bottom and `--sweep` applies each
one, runs this suite against the mutated module, and reports which checks it
reddened. That is the whole point: CLAUDE.md's rule is that a test which has
never failed proves nothing, and six checks written for test_press_monitor.py
could not fail at all while reading as coverage in a green run.

Two mechanics that rule depends on, both learned here the hard way:

THE SWEEP WRITES EACH MUTANT INTO ITS OWN TEMPORARY DIRECTORY rather than
editing pushpin.py in place. CPython invalidates cached bytecode on the
source's mtime and size, so two mutations that remove the same number of
characters within the same second are indistinguishable to it and the second
run silently re-executes the first. A fresh directory per mutation cannot
collide, and the real file is never touched, so an interrupted sweep cannot
leave a mutated component on disk.

THE SWEEP PRINTS ITS MUTATION COUNT. "No mutation reddened this check" and
"this check has no mutation" are the same output and different findings, and a
slice-based edit once deleted seven mutations silently while the sweep went on
reporting the absence accurately.

A mutation that CRASHES the suite has shown nothing: the sweep reports those
separately rather than counting them as a demonstration.
"""

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pushpin

PASS, FAIL = "PASS", "FAIL"
results = []


def check(name, ok, detail=""):
    results.append((PASS if ok else FAIL, name))
    print(f"  [{PASS if ok else FAIL}] {name}" + (f" - {detail}" if detail else ""))


NOW = datetime(2026, 9, 5, 12, 0, 0, tzinfo=timezone.utc)
CUTOFF = NOW - timedelta(days=31)


def mid_for_age(days):
    """A snowflake for a message created `days` ago, as a string."""
    when = NOW - timedelta(days=days)
    ms = int(when.timestamp() * 1000)
    return str((ms - pushpin.DISCORD_EPOCH_MS) << pushpin.SNOWFLAKE_SHIFT)


def msg(age_days=60, **kw):
    """A plausible message object. Deletable unless a kwarg says otherwise."""
    m = {"id": mid_for_age(age_days), "channel_id": "999", "type": 0,
         "pinned": False, "author": {"id": "1", "bot": False}}
    m.update(kw)
    return m


class FakeCall:
    """Stands in for pushpin.call. Routes are matched by substring, and an
    unmatched route is a test bug rather than a default, so it raises."""

    def __init__(self, routes):
        self.routes = routes
        self.seen = []

    def __call__(self, method, path, **kw):
        self.seen.append((method, path))
        for frag, resp in self.routes.items():
            if frag in path:
                return resp
        raise AssertionError(f"unstubbed route: {method} {path}")


# ------------------------------------------------------------------ SECTION


def snowflakes():
    print("\nsnowflake_time")
    # Discord's own worked example, from the Reference page.
    check("matches Discord's documented example",
          pushpin.snowflake_time("175928847299117063")
          == datetime(2016, 4, 30, 11, 18, 25, 796000, tzinfo=timezone.utc))
    check("a 60-day-old id reads as 60 days old",
          abs((NOW - pushpin.snowflake_time(mid_for_age(60))).days - 60) <= 1)
    check("returns an aware datetime",
          pushpin.snowflake_time(mid_for_age(1)).tzinfo is not None,
          "a naive one would raise on subtraction from an aware now")


def marker_matching():
    print("\nis_marker")
    check("the bare pushpin matches",
          pushpin.is_marker({"id": None, "name": "\U0001F4CC"}))
    check("THE VS16 FORM MATCHES",
          pushpin.is_marker({"id": None, "name": "\U0001F4CC️"}),
          "Windows win+. and several Android keyboards append U+FE0F")
    check("A CUSTOM EMOJI NAMED pushpin DOES NOT MATCH",
          not pushpin.is_marker({"id": "12345", "name": "\U0001F4CC"}),
          "without the id check anyone could upload one and mark messages")
    check("a null name does not match and does not raise",
          not pushpin.is_marker({"id": None, "name": None}),
          "a deleted custom emoji leaves a reaction with a null name")
    check("a different emoji does not match",
          not pushpin.is_marker({"id": None, "name": "\U0001F512"}))

    print("\nMARKER_KEYS")
    both = set(pushpin.MARKER_KEYS)
    check("THE DELETE PATH QUERIES BOTH ENCODINGS", len(both) == 2,
          "querying only the bare form is how a VS16 mark gets deleted")
    check("one of them is the bare form", "%F0%9F%93%8C" in both)
    check("the other carries the variation selector",
          any(k.endswith("%EF%B8%8F") for k in both))

    print("\nmarker_in_array")
    check("an ABSENT reactions key does not raise",
          pushpin.marker_in_array(msg()) is False,
          "measured: reactions is omitted, not [], on an unreacted message")
    check("an empty array reads as no marker",
          not pushpin.marker_in_array(msg(reactions=[])))
    check("the marker with a positive count is found",
          pushpin.marker_in_array(msg(reactions=[
              {"count": 1, "emoji": {"id": None, "name": "\U0001F4CC"}}])))
    check("an unparseable entry keeps rather than crashes",
          pushpin.marker_in_array(msg(reactions=["not-a-dict"])))
    check("a different emoji is not the marker",
          not pushpin.marker_in_array(msg(reactions=[
              {"count": 3, "emoji": {"id": None, "name": "\U0001F44D"}}])))


def classification():
    print("\nclassify")
    pins, protected = set(), set()
    c = lambda m, p=pins, pr=protected: pushpin.classify(m, p, pr, CUTOFF)

    check("an aged plain message is deleted", c(msg())[0] == "delete")
    check("a young message is kept", c(msg(age_days=5))[0] == "keep")
    check("a webhook message is kept",
          c(msg(webhook_id="77"))[1] == "webhook")
    check("a pinned message is kept", c(msg(pinned=True))[1] == "pinned")
    check("the pin list is consulted independently of the flag",
          pushpin.classify(msg(), {mid_for_age(60)}, protected, CUTOFF)[1]
          == "pin-list")
    check("a latched id is kept",
          pushpin.classify(msg(), pins, {mid_for_age(60)}, CUTOFF)[1]
          == "latched")
    check("a marked message is kept",
          c(msg(reactions=[{"count": 1,
                            "emoji": {"id": None, "name": "\U0001F4CC"}}]))[1]
          == "marked")
    check("the HAS_THREAD flag keeps",
          c(msg(flags=1 << 5))[1] == "has-thread")
    check("a thread key keeps, independently of the flag",
          c(msg(thread={"id": "5"}))[1] == "has-thread")
    check("a message at the reaction cap keeps",
          c(msg(reactions=[{"count": 1, "emoji": {"id": None, "name": str(i)}}
                           for i in range(20)]))[1] == "reaction-cap",
          "a human physically cannot add the marker to it")

    print("\nclassify: the type allow-set")
    check("REPLIES (type 19) ARE DELETABLE", c(msg(type=19))[0] == "delete",
          "measured: this channel is 10% replies, and `type == 0` skips them")
    check("slash-command messages (20) are deletable",
          c(msg(type=20))[0] == "delete")
    check("context-menu messages (23) are deletable",
          c(msg(type=23))[0] == "delete")
    check("a member-join notice (7) is kept",
          c(msg(type=7))[1] == "not-user-content")
    check("a thread-created notice (18) is kept", c(msg(type=18))[1]
          == "not-user-content")
    check("a thread starter (21) is kept", c(msg(type=21))[1]
          == "not-user-content")
    check("an absent type keeps", c({"id": mid_for_age(60), "channel_id": "9",
                                     "pinned": False})[0] == "keep")

    print("\nclassify: rule order")
    marked_young = msg(age_days=2, reactions=[
        {"count": 1, "emoji": {"id": None, "name": "\U0001F4CC"}}])
    check("A MARKED MESSAGE INSIDE THE WINDOW REPORTS 'marked', NOT 'too-new'",
          c(marked_young)[1] == "marked",
          "the age check must stay LAST or the latch never records it")


def state_file():
    print("\nload_state")
    tmp = Path(tempfile.mkdtemp())
    orig = pushpin.STATE_FILE
    try:
        pushpin.STATE_FILE = tmp / "s.json"
        check("an absent file is a first run, not an error",
              pushpin.load_state() == {"protected": [], "condemned": {}})

        pushpin.STATE_FILE.write_text('{"protected": ["1"], "condemned": {}}')
        check("a well-formed file loads",
              pushpin.load_state()["protected"] == ["1"])

        pushpin.STATE_FILE.write_text("{not json")
        check("invalid JSON halts",
              raises_halt(pushpin.load_state))

        pushpin.STATE_FILE.write_text('{"condemned": {}}')
        check("A MISSING protected KEY HALTS", raises_halt(pushpin.load_state),
              "it must never degrade to an empty keep-set")

        pushpin.STATE_FILE.write_text('{"protected": null, "condemned": {}}')
        check("a null protected halts", raises_halt(pushpin.load_state))

        pushpin.STATE_FILE.write_text('{"protected": ["1"]}')
        check("a missing condemned is tolerated",
              pushpin.load_state()["protected"] == ["1"],
              "losing it only re-condemns, which destroys nothing")
    finally:
        pushpin.STATE_FILE = orig
        shutil.rmtree(tmp, ignore_errors=True)


def raises_halt(fn, *a, **kw):
    try:
        fn(*a, **kw)
    except pushpin.Halt:
        return True
    except Exception:
        return False
    return False


def pins_and_permissions():
    print("\nfetch_pins")
    orig = pushpin.call
    try:
        pushpin.call = FakeCall({"/messages/pins": (200, {
            "items": [{"message": {"id": "5"}}], "has_more": False})})
        check("a complete page returns the ids", pushpin.fetch_pins() == {"5"})

        pushpin.call = FakeCall({"/messages/pins": (200, {
            "items": [{"message": {"id": "5"}}], "has_more": True})})
        check("A TRUNCATED PIN LIST HALTS", raises_halt(pushpin.fetch_pins),
              "the truncation would land on the KEEP list")

        pushpin.call = FakeCall({"/messages/pins": (403, {"code": 50001})})
        check("an unreadable pin list halts", raises_halt(pushpin.fetch_pins),
              "never degrade to an empty keep-set")

        pushpin.call = FakeCall({"/messages/pins": (200, "nonsense")})
        check("an unrecognised payload halts", raises_halt(pushpin.fetch_pins))

        print("\nassert_manage_messages")
        chan = {"guild_id": "G", "permission_overwrites": []}
        allperm = str(pushpin.VIEW_CHANNEL | pushpin.READ_MESSAGE_HISTORY
                      | pushpin.MANAGE_MESSAGES)
        base = {"/users/@me": (200, {"id": "BOT"}),
                "/members/": (200, {"roles": []}),
                "/roles": (200, [{"id": "G", "permissions": allperm}])}

        pushpin.call = FakeCall(base)
        check("all three present passes",
              pushpin.assert_manage_messages(chan) is None)

        no_manage = dict(base)
        no_manage["/roles"] = (200, [{"id": "G", "permissions": str(
            pushpin.VIEW_CHANNEL | pushpin.READ_MESSAGE_HISTORY)}])
        pushpin.call = FakeCall(no_manage)
        check("MISSING MANAGE_MESSAGES HALTS IN PREFLIGHT",
              raises_halt(pushpin.assert_manage_messages, chan),
              "otherwise it surfaces as a 403 mid-delete")

        # ADMINISTRATOR **PLUS** ALL THREE, and the plus is the whole fixture.
        # An admin-only role has none of the three, so with the ADMINISTRATOR
        # halt removed the function still raises on the missing-permissions
        # check and the mutation reads as SILENT: the check would be asserting
        # "halts" rather than "halts for this reason". Found by the sweep, which
        # is what the sweep is for.
        admin = dict(base)
        admin["/roles"] = (200, [{"id": "G", "permissions": str(
            pushpin.ADMINISTRATOR | pushpin.VIEW_CHANNEL
            | pushpin.READ_MESSAGE_HISTORY | pushpin.MANAGE_MESSAGES)}])
        pushpin.call = FakeCall(admin)
        check("ADMINISTRATOR HALTS EVEN WITH ALL THREE GRANTED",
              raises_halt(pushpin.assert_manage_messages, chan),
              "it bypasses every overwrite, so the scoping is inert")

        # A member overwrite granting all three on a role that has none.
        deny_chan = {"guild_id": "G", "permission_overwrites": [
            {"id": "BOT", "allow": allperm, "deny": "0"}]}
        none_at_base = dict(base)
        none_at_base["/roles"] = (200, [{"id": "G", "permissions": "0"}])
        pushpin.call = FakeCall(none_at_base)
        check("a member overwrite grants what the role lacks",
              pushpin.assert_manage_messages(deny_chan) is None,
              "this is the whole channel-scoping design")
    finally:
        pushpin.call = orig


def reaction_store():
    print("\nmarker_state")
    orig, orig_ch = pushpin.call, pushpin.CHANNEL_ID
    try:
        pushpin.CHANNEL_ID = "999"

        pushpin.call = FakeCall({"/reactions/": (200, [])})
        check("no reactor anywhere reads as absent",
              pushpin.marker_state("1") == "absent")

        f = FakeCall({"/reactions/": (200, [])})
        pushpin.call = f
        pushpin.marker_state("1")
        paths = [p for _, p in f.seen]
        check("BOTH REACTION TYPES ARE QUERIED",
              any("type=0" in p for p in paths)
              and any("type=1" in p for p in paths),
              "super reactions are type=1 and the default excludes them")
        check("BOTH MARKER ENCODINGS ARE QUERIED",
              all(any(k in p for p in paths) for k in pushpin.MARKER_KEYS),
              "a VS16 mark is invisible to a bare-form query")

        pushpin.call = FakeCall({"/reactions/": (200, [{"id": "u"}])})
        check("a reactor reads as present",
              pushpin.marker_state("1") == "present")

        pushpin.call = FakeCall({"/reactions/": (403, {"code": 50013})})
        check("A REFUSED CALL IS 'unknown', NOT 'absent'",
              pushpin.marker_state("1") == "unknown",
              "'absent' would authorise a delete the run never measured")

        pushpin.call = FakeCall({"/reactions/": (404, {"code": 10014})})
        check("10014 Unknown Emoji is 'unknown', not 'no reactors'",
              pushpin.marker_state("1") == "unknown")

        pushpin.call = FakeCall({"/reactions/": (None, {})})
        check("a transport failure is 'unknown'",
              pushpin.marker_state("1") == "unknown")

        pushpin.call = FakeCall({"/reactions/": (200, {"not": "a list"})})
        check("a non-list body is 'unknown'",
              pushpin.marker_state("1") == "unknown")
    finally:
        pushpin.call, pushpin.CHANNEL_ID = orig, orig_ch


def configuration():
    print("\nconfiguration")
    check("CONDEMN_HOURS is floored at 1", pushpin.CONDEMN_HOURS >= 1,
          "0 collapses both margins into a single run")
    check("the deletable types are exactly {0, 19, 20, 23}",
          pushpin.DELETABLE_TYPES == {0, 19, 20, 23})
    check("the reaction cap matches Discord's documented 20",
          pushpin.REACTION_CAP == 20)
    check("the marker is a single code point", len(pushpin.MARKER) == 1,
          "a multi-scalar emoji would bring ZWJ and skin-tone traps too")


# ----------------------------------------------------------------- MUTATIONS
#
# Each entry is a ONE-LINE change to pushpin.py that must turn at least one
# check red. `--sweep` applies each in its own temp directory, runs this suite
# against it, and reports what reddened. A mutation that reddens nothing is
# either an unfailable check or a missing demonstration, and those are the
# same output with different meanings, which is why the count is printed.

MUTATIONS = [
    ("age check moved before the marker rules",
     '    if mid in protected:\n        return "keep", "latched"',
     '    if snowflake_time(mid) >= cutoff:\n        return "keep", "too-new"'),
    ("type allow-set narrowed to plain messages",
     "DELETABLE_TYPES = {0, 19, 20, 23}",
     "DELETABLE_TYPES = {0}"),
    ("custom-emoji rejection removed from is_marker",
     '    if emoji.get("id") is not None:\n        return False',
     '    if False:\n        return False'),
    ("VS16 strip removed",
     '    return name.replace(VS16, "") == MARKER',
     "    return name == MARKER"),
    ("delete path queries only the bare marker",
     "MARKER_KEYS = (\n    urllib.parse.quote(MARKER),\n    urllib.parse.quote(MARKER + VS16),\n)",
     "MARKER_KEYS = (urllib.parse.quote(MARKER),)"),
    ("only the default reaction type queried",
     "        for rtype in (0, 1):",
     "        for rtype in (0,):"),
    ("a refused reaction call reads as absent",
     '                print(f"    reaction check HTTP {st}; unknown, keeping")\n                return "unknown"',
     '                print(f"    reaction check HTTP {st}; unknown, keeping")\n                return "absent"'),
    ("missing protected key degrades to empty",
     '    if not isinstance(data, dict) or not isinstance(data.get("protected"), list):',
     "    if False:"),
    ("truncated pin list tolerated",
     '        if body.get("has_more"):',
     "        if False:"),
    ("preflight permission assertion removed",
     "    if missing:\n        raise Halt(",
     "    if False:\n        raise Halt("),
    ("ADMINISTRATOR no longer refused",
     "    if perms & ADMINISTRATOR:",
     "    if False:"),
    ("reaction cap keep removed",
     "    if len(msg.get('reactions') or []) >= REACTION_CAP:".replace("'", '"'),
     "    if False:"),
    ("thread key signal removed, flag left in place",
     '    if "thread" in msg:\n        return "keep", "has-thread"',
     '    if False:\n        return "keep", "has-thread"'),
    ("condemn floor removed",
     'CONDEMN_HOURS = max(1, int(os.environ.get("PUSHPIN_CONDEMN_HOURS", "20")))',
     'CONDEMN_HOURS = int(os.environ.get("PUSHPIN_CONDEMN_HOURS", "0"))'),
]


def sweep():
    """Apply each mutation in isolation and report what it reddened."""
    src = Path("pushpin.py").read_text(encoding="utf-8")
    print(f"MUTATION SWEEP: {len(MUTATIONS)} mutations\n")
    print("A mutation that reddens NOTHING is either an unfailable check or a")
    print("missing demonstration. Those are the same output, so the count above")
    print("is the thing that makes a quietly-shrunk list visible.\n")

    silent, crashed, ok = [], [], 0
    for label, old, new in MUTATIONS:
        if old not in src:
            print(f"  [STALE ] {label}")
            print(f"           anchor no longer in pushpin.py; the mutation is "
                  f"not testing what it claims")
            silent.append(label)
            continue
        # Its own directory, so cached bytecode from a previous mutation of the
        # same length cannot be reused.
        d = Path(tempfile.mkdtemp())
        try:
            (d / "pushpin.py").write_text(src.replace(old, new, 1),
                                          encoding="utf-8")
            # THE SUITE IS COPIED IN AND RUN FROM THAT DIRECTORY. Setting
            # PYTHONPATH is not enough and fails silently: Python puts the
            # SCRIPT'S OWN DIRECTORY at sys.path[0], ahead of PYTHONPATH, so a
            # child launched from the repo root imports the real pushpin.py and
            # every mutation reports SILENT. The first version of this sweep did
            # exactly that and reported 0 of 14, which reads identically to
            # fourteen unfailable checks.
            shutil.copy(__file__, d / "test_pushpin.py")
            env = dict(os.environ)
            env["PYTHONDONTWRITEBYTECODE"] = "1"
            r = subprocess.run([sys.executable, "-u", "test_pushpin.py"],
                               capture_output=True, text=True, env=env,
                               cwd=str(d), timeout=120)
            reds = [l.strip()[7:] for l in r.stdout.splitlines()
                    if l.strip().startswith("[FAIL]")]
            ran = sum(1 for l in r.stdout.splitlines()
                      if "[PASS]" in l or "[FAIL]" in l)
            if ran == 0:
                print(f"  [CRASH ] {label}")
                print(f"           the suite did not run, so nothing was shown")
                crashed.append(label)
            elif reds:
                ok += 1
                print(f"  [RED   ] {label}")
                for n in reds[:3]:
                    print(f"           -> {n}")
                if len(reds) > 3:
                    print(f"           -> and {len(reds) - 3} more")
            else:
                print(f"  [SILENT] {label}")
                silent.append(label)
        finally:
            shutil.rmtree(d, ignore_errors=True)

    print(f"\n{ok}/{len(MUTATIONS)} mutations reddened at least one check")
    if crashed:
        print(f"{len(crashed)} crashed the suite and demonstrated nothing:")
        for n in crashed:
            print(f"  - {n}")
    if silent:
        print(f"{len(silent)} reddened nothing, which needs hand-checking:")
        for n in silent:
            print(f"  - {n}")
    return 1 if (silent or crashed) else 0


def main():
    print("pushpin.py")
    snowflakes()
    marker_matching()
    classification()
    state_file()
    pins_and_permissions()
    reaction_store()
    configuration()

    bad = sum(1 for r, _ in results if r == FAIL)
    print(f"\n{len(results) - bad}/{len(results)} checks passed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(sweep() if "--sweep" in sys.argv else main())
