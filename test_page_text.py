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

    print("\nPAYLOAD RECOVERY")
    # The HUT shape: the article is inside a JSON payload and the visible
    # half is furniture. Measured 2026-08-12: the real page yields 1,227
    # characters of furniture and hides its reporting date in here.
    HUT_SHAPE = (
        '<p>Posted Jul 13, 2026</p>'
        '<script type="application/json" id="__NUXT_DATA__" data-ssr="false">'
        '["MIAMI, July 13, 2026 ",'
        ' "Date: Tuesday, August 4, 2026\\nTime: 8:30 a.m. ET",'
        ' {"slug": "hut-8-schedules"}]'
        '</script>'
    )
    got = pt.extract_text(HUT_SHAPE)
    check("payload prose is recovered", "August 4, 2026" in got, got)
    check("the visible half survives alongside it", "Posted Jul 13, 2026" in got)
    check("nested object strings are recovered too", "hut-8-schedules" in got)
    check("newlines inside a recovered string are collapsed",
          "August 4, 2026 Time:" in got, got)

    check("payload_strings returns the strings in document order",
          pt.payload_strings(HUT_SHAPE)[0].startswith("MIAMI"),
          str(pt.payload_strings(HUT_SHAPE)[:2]))

    print("\nTHE JOIN MUST NOT MANUFACTURE A DATE")
    # Two unrelated neighbours. Joined by a space this reads "...in August
    # 4, 2026 was...", a date published by nobody. This check is the whole
    # reason PAYLOAD_SEP is not " ".
    FABRICATION = (
        '<script type="application/json">'
        '["Revenue grew in August", "4, 2026 was a record"]'
        '</script>'
    )
    check("adjacent strings cannot fabricate a date",
          "August 4, 2026" not in pt.extract_text(FABRICATION),
          pt.extract_text(FABRICATION))
    check("the separator carries a non-whitespace character",
          any(not c.isspace() for c in pt.PAYLOAD_SEP),
          f"PAYLOAD_SEP={pt.PAYLOAD_SEP!r}; a newline would not prevent this")

    print("\nWHAT MUST NOT BREAK")
    check("a malformed payload is skipped, not raised",
          pt.extract_text('<p>keep</p><script type="application/json">{oops'
                          '</script>') == "keep",
          "broken JSON costs the recovered half, never the visible half")
    check("a page with no payload is unchanged",
          pt.extract_text("<p>hello there</p>") == "hello there")
    check("ld+json is left alone",
          "2026" not in pt.extract_text(
              '<script type="application/ld+json">'
              '["reported on August 4, 2026"]</script>'),
          "excluded deliberately; no roster source is known to need it")
    check("a plain script is still dropped",
          pt.extract_text('<script>var d = "August 4, 2026";</script>') == "")
    check("empty strings do not litter the output",
          "|  |" not in pt.extract_text(
              '<script type="application/json">["a", "", "b"]</script>'))

    # A date the visible half already carries, repeated in the payload.
    # candidate_dates deduplicates, so this must not become two candidates.
    # Checked here because that guarantee is what stops a source with both
    # rendered prose and a payload being pushed from "one" into "several".
    BOTH_HALVES = (
        '<p>The call is on August 4, 2026.</p>'
        '<script type="application/json">'
        '["The call is on August 4, 2026."]</script>'
    )
    both = pt.extract_text(BOTH_HALVES)
    check("a date in both halves appears in the text twice",
          both.count("August 4, 2026") == 2, both)
    check("and the two halves are separated, not run together",
          pt.PAYLOAD_SEP in both, both)

    bad = sum(1 for r, _ in results if r == FAIL)
    print(f"\n{len(results) - bad}/{len(results)} checks passed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
