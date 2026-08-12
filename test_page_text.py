#!/usr/bin/env python3
"""Tests for page_text. Standalone, stdlib only, no network.

THE ONE THAT MATTERS lands in task 2: recovered strings must be joined with
something a date pattern cannot span, because concatenating unrelated
strings with whitespace can manufacture a date that appears in neither.
"""

import sys

import page_text as pt

PASS, FAIL = "PASS", "FAIL"
results = []


def check(name, ok, detail=""):
    results.append((PASS if ok else FAIL, name))
    print(f"  [{PASS if ok else FAIL}] {name}" + (f" — {detail}" if detail else ""))


def main():
    print("VISIBLE TEXT")
    check("tags are removed",
          pt.extract_text("<p>hello <b>there</b></p>") == "hello there")
    check("script content is removed",
          pt.extract_text("<p>keep</p><script>var x = 'drop';</script>")
          == "keep")
    check("style content is removed",
          pt.extract_text("<p>keep</p><style>.a{color:red}</style>") == "keep")
    check("whitespace is collapsed",
          pt.extract_text("<p>a   b\n\nc</p>") == "a b c")
    check("an empty document yields an empty string",
          pt.extract_text("") == "")
    check("a document of only script yields an empty string",
          pt.extract_text("<script>var x = 1;</script>") == "",
          "this is the HUT shape, and task 2 is what fixes it")

    bad = sum(1 for r, _ in results if r == FAIL)
    print(f"\n{len(results) - bad}/{len(results)} checks passed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
