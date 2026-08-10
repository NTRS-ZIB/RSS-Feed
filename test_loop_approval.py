#!/usr/bin/env python3
"""Tests for loop_approval. Standalone, stdlib only.

THE ONE THAT MATTERS: an approval for one action must not authorise a
different one. Exact tokens, never prefixes — the repo's standing trap about
prefix matching runs in both directions, and here a loose match would turn one
approval into a standing licence.
"""

import sys

import loop_approval as la

PASS, FAIL = "PASS", "FAIL"
results = []


def check(name, ok, detail=""):
    results.append((PASS if ok else FAIL, name))
    print(f"  [{PASS if ok else FAIL}] {name}" + (f" — {detail}" if detail else ""))


DECISIONS = """
## 2026-08-09 — Merge the loop automation?

**Decided:** yes
**Authorises:** merge:loop-automation

## 2026-08-09 — Should a CEO letter count as a press release?

**Decided:** no, announcements only

## 2026-08-09 — Post the digest for W32?

**Authorises:** post:weekly_digest, delete:probe_largemove.py
"""


def main():
    print("=" * 78)
    print("loop_approval")
    print("=" * 78)

    check("an exact token is authorised",
          la.authorised("merge:loop-automation", DECISIONS))
    check("a second token on the same line is authorised",
          la.authorised("delete:probe_largemove.py", DECISIONS))
    check("an unlisted action is refused",
          not la.authorised("merge:main", DECISIONS))

    check("A PREFIX DOES NOT AUTHORISE — merge: is not a licence",
          not la.authorised("merge:something-else", DECISIONS))
    check("a longer token is not authorised by a shorter one",
          not la.authorised("delete:probe_largemove.py.bak", DECISIONS))
    check("a shorter token is not authorised by a longer one",
          not la.authorised("delete:probe_largemove", DECISIONS))

    check("a decision with no Authorises line grants nothing",
          not la.authorised("post:anything", DECISIONS))
    check("empty decisions authorise nothing",
          not la.authorised("merge:loop-automation", ""))

    check("tokens are parsed from every Authorises line",
          la.parse_tokens(DECISIONS) == {"merge:loop-automation",
                                         "post:weekly_digest",
                                         "delete:probe_largemove.py"},
          str(sorted(la.parse_tokens(DECISIONS))))

    check("an unknown action KIND raises rather than silently refusing",
          _raises(lambda: la.authorised("deploy:prod", DECISIONS)))
    check("a token with no colon raises",
          _raises(lambda: la.authorised("merge", DECISIONS)))

    print("=" * 78)
    bad = sum(1 for r, _ in results if r == FAIL)
    print(f"{len(results) - bad}/{len(results)} passed")
    for r, name in results:
        if r == FAIL:
            print(f"  FAILED: {name}")
    print("=" * 78)
    return 1 if bad else 0


def _raises(fn):
    try:
        fn()
    except la.ApprovalError:
        return True
    except Exception:
        return False
    return False


if __name__ == "__main__":
    sys.exit(main())
