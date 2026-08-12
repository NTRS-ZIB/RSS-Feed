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
        ' {"slug": "hut-8-schedules", "title": "Earnings call scheduled"}]'
        '</script>'
    )
    got = pt.extract_text(HUT_SHAPE)
    check("payload prose is recovered", "August 4, 2026" in got, got)
    check("the visible half survives alongside it", "Posted Jul 13, 2026" in got)
    check("nested object strings with whitespace are recovered", "Earnings call scheduled" in got)
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
    check("a deeply nested payload does not propagate RecursionError",
          pt.extract_text('<p>keep this text</p><script type="application/json">'
                          + '['*1000 + ']'*1000 +
                          '</script>') == "keep this text",
          "the walk in _strings exceeds the recursion limit on deeply nested"
          " JSON, even though json.loads itself accepts it; must not discard"
          " visible text")
    # A RecursionError raised partway through _strings must not leak the
    # strings appended before the raise. Two candidate dates sit either side
    # of a deeply nested element in the same array; if the block is truncated
    # rather than skipped, the first candidate survives and the second is
    # lost, turning a body that should be refused (several candidates) into
    # one that gets stored (one candidate) -- silently choosing the wrong
    # date. See CLAUDE.md and the 2026-08-12 json-payload-body-text review.
    deep = '[' * 1200 + ']' * 1200
    LEAK_SHAPE = (
        '<p>visible furniture</p><script type="application/json">'
        '["Call replay available until August 20, 2026", ' + deep +
        ', "Results will be released on August 4, 2026"]</script>'
    )
    check("a block that cannot be fully walked contributes nothing, not a "
          "truncated prefix",
          pt.extract_text(LEAK_SHAPE) == "visible furniture",
          pt.extract_text(LEAK_SHAPE))
    check("payload_strings returns no strings from an unwalkable block",
          pt.payload_strings(LEAK_SHAPE) == [],
          str(pt.payload_strings(LEAK_SHAPE)))
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
              '<script type="application/json">["a phrase", "", "another phrase"]</script>') and
          "a phrase" in pt.extract_text(
              '<script type="application/json">["a phrase", "", "another phrase"]</script>') and
          "another phrase" in pt.extract_text(
              '<script type="application/json">["a phrase", "", "another phrase"]</script>'),
          "empty strings must be dropped without creating a double-separator artefact; both phrases must survive")

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

    print("\nNOISE FILTERING: WHITESPACE GATE")
    # Real payloads carry non-prose data: URLs, UUIDs, base64 blobs, single-word
    # tokens. None of these can contain a date (dates have the form "Month D,
    # YYYY" which requires whitespace). Strings without whitespace are noise
    # that inflate the probe's chars column. Only recover strings containing
    # whitespace, which cannot lose a date since any date must contain it.
    check("URLs in a payload are not recovered",
          pt.extract_text('<p>visible</p><script type="application/json">'
                          '["https://example.test/a/b"]</script>') == "visible",
          "whitespace-free strings are noise")
    check("a UUID in a payload is not recovered",
          pt.extract_text('<p>visible</p><script type="application/json">'
                          '["550e8400-e29b-41d4-a716-446655440000"]</script>') == "visible",
          "whitespace-free strings are noise")
    check("a base64 blob in a payload is not recovered",
          pt.extract_text('<p>visible</p><script type="application/json">'
                          '["eJyNUQFuAyEM1B1vGUviHKQdewgqZJ0XX"]</script>') == "visible",
          "whitespace-free strings are noise")
    check("a mix of junk and prose keeps only the prose",
          pt.extract_text('<p>visible</p><script type="application/json">'
                          '["https://example.test/a/b", '
                          '"Date: August 4, 2026", '
                          '"550e8400-e29b-41d4-a716"]</script>') == "visible | Date: August 4, 2026",
          "only strings with whitespace are recovered")
    check("a bare date with no surrounding words is still recovered",
          "August 4, 2026" in pt.extract_text(
              '<p>visible</p><script type="application/json">'
              '["August 4, 2026"]</script>'),
          "the date contains whitespace, so it passes the gate")

    bad = sum(1 for r, _ in results if r == FAIL)
    print(f"\n{len(results) - bad}/{len(results)} checks passed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
