# JSON payload body text Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Recover the release text that a site ships inside a JSON script payload,
so HUT's reporting date stops being deleted by our own extractor.

**Architecture:** HTML-to-text extraction moves out of `press_monitor.py` into a
new stdlib-only `page_text.py`, first unchanged and then extended to recover
strings from `application/json` payloads. The move is what makes the extraction
testable at all: `press_monitor` imports `feedparser`, which is absent locally, so
anything tested only there cannot be tested.

**Tech Stack:** Python 3.12, stdlib only for the new module. Tests are standalone
scripts with the repo's own `check()` harness printing `N/M checks passed`, not
pytest.

## Global Constraints

- **`page_text.py` must import nothing outside the standard library.** That is the
  whole reason it exists. No `requests`, no `feedparser`, no `press_monitor`.
- **Join recovered strings with `" | "`, never whitespace.** `DATE_RE` accepts
  `\s+` between month and day, so a space or newline lets a date be manufactured
  across a boundary present in neither string. The separator must contain a
  non-whitespace character.
- **Exclude `application/ld+json`.** Only `type="application/json"` is in scope.
- **`announcement_body` never raises** and returns `None` only when the fetch
  failed. A malformed payload is skipped in silence and must never discard the
  visible text already extracted.
- **The final text stays capped at `BODY_MAX_BYTES`** (400,000).
- **Do not run the component scripts.** `press_monitor.py` and
  `earnings_calendar.py` read secrets that exist only in GitHub Actions and post
  to live Discord. **Do not run `probe_body_dates.py`**; its `main()` makes real
  network calls. Safe: `python test_page_text.py`, `python test_earnings_dates.py`,
  `python test_probe_body_dates.py`, `python watchlist.py`, `python -m py_compile`.
- **This working copy has no outbound network.** Nothing can be verified by
  fetching; use a dispatched workflow.
- **Every workflow dispatch carries `--ref <branch>`.**
- **`earnings_dates.json`, `state.json` and `snapshot.json` are outputs.** Never
  edit, delete, reformat or commit one.
- **Branch:** `hut-json-payload`, already created, spec committed at `9bbdf13`.
- Suite baselines: `test_earnings_dates.py` **130/130**,
  `test_probe_body_dates.py` **32/32**.

## File Structure

| File | Responsibility |
|---|---|
| Create `page_text.py` | Turn a page's HTML into the text a date parser should read. Stdlib only, no network, no knowledge of feeds or Discord. |
| Create `test_page_text.py` | Fixture-driven tests for the above. No network. |
| Modify `press_monitor.py` | `announcement_body` keeps the fetch and delegates extraction. |
| Modify `docs/press-monitor.md` | Replace the HUT passage, which states the opposite of what is true. |

`earnings_dates.py`, `probe_body_dates.py` and `earnings_calendar.py` are NOT
modified. The rule, its gate and its markers are out of scope: this makes one more
source readable, and what happens to a readable body is already shipped.

---

### Task 1: Move extraction into a module that can be tested

**Files:**
- Create: `page_text.py`
- Create: `test_page_text.py`
- Modify: `press_monitor.py` (`announcement_body`, the last three lines of it)

**Interfaces:**
- Consumes: nothing.
- Produces: `page_text.extract_text(html) -> str`. Task 2 extends this same
  function; Task 3 relies on its behaviour through `announcement_body`.

**This task must not change behaviour.** It moves three lines and proves they
still do exactly what they did.

- [ ] **Step 1: Write the failing tests**

Create `test_page_text.py`:

```python
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
```

- [ ] **Step 2: Run it to verify it fails**

```bash
python test_page_text.py
```

Expected: `ModuleNotFoundError: No module named 'page_text'`.

- [ ] **Step 3: Write the module**

Create `page_text.py`:

```python
#!/usr/bin/env python3
"""Turn a page's HTML into the text a date parser should read.

Stdlib only, and that is load-bearing rather than incidental. This logic
used to sit inside press_monitor.announcement_body, where it could not be
tested: press_monitor imports feedparser, which is absent from a plain
working copy, so importing it to test three lines of regex was impossible.
Extraction is the half worth testing and the fetch is the half that needs
the network, so they are separated.
"""

import re

SCRIPT_OR_STYLE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.S | re.I)
TAG = re.compile(r"<[^>]+>")


def extract_text(html):
    """The visible text of a page, whitespace collapsed."""
    stripped = SCRIPT_OR_STYLE.sub(" ", html or "")
    return " ".join(TAG.sub(" ", stripped).split())
```

- [ ] **Step 4: Run the tests**

```bash
python test_page_text.py
```

Expected: `6/6 checks passed`.

- [ ] **Step 5: Delegate from `announcement_body`**

In `press_monitor.py`, add `import page_text` to the import block, beside the
other first-party imports (`import watchlist`, `import earnings_dates as ed`).

Then replace the last three lines of `announcement_body`:

```python
    html = bytes(raw[:BODY_MAX_BYTES]).decode("utf-8", "replace")
    html = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html,
                  flags=re.S | re.I)
    return " ".join(re.sub(r"<[^>]+>", " ", html).split())
```

with:

```python
    html = bytes(raw[:BODY_MAX_BYTES]).decode("utf-8", "replace")
    return page_text.extract_text(html)
```

Update the docstring's first line from "The visible text of a release page" to
"The text of a release page, or None. Never raises." and add a sentence saying
extraction lives in `page_text` so it can be tested without `feedparser`.

- [ ] **Step 6: Confirm nothing else broke**

```bash
python -m py_compile press_monitor.py && python test_page_text.py && python test_earnings_dates.py && python test_probe_body_dates.py
```

Expected: compiles, `6/6`, `130/130`, `32/32`.

Then confirm the old inline extraction is gone and nothing else used it:

```bash
grep -nF 'script|style' press_monitor.py; grep -nF '<[^>]+>' press_monitor.py
```

Expected: no output from either. A match means some other function kept its own
copy of the same extraction; report that rather than editing it, since this task
is meant to be behaviour-preserving.

- [ ] **Step 7: Commit**

```bash
git add page_text.py test_page_text.py press_monitor.py
git commit -m "Move page text extraction where it can be tested"
```

---

### Task 2: Recover the strings a site ships as JSON

**Files:**
- Modify: `page_text.py`
- Modify: `test_page_text.py`

**Interfaces:**
- Consumes: `extract_text(html)` from Task 1.
- Produces: the same `extract_text(html)`, now appending payload text.
  Also `page_text.PAYLOAD_SEP` (the string `" | "`) and
  `page_text.payload_strings(html) -> list[str]`, both used by the tests.

- [ ] **Step 1: Write the failing tests**

Add to `test_page_text.py`, inside `main()` after the `VISIBLE TEXT` block:

```python
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
```

- [ ] **Step 2: Run them to verify they fail**

```bash
python test_page_text.py
```

Expected: FAIL on `payload prose is recovered` (the script block is stripped, so
the date is absent) and `AttributeError` on `pt.payload_strings` /
`pt.PAYLOAD_SEP`.

- [ ] **Step 3: Implement the recovery**

Add to `page_text.py`, above `extract_text`:

```python
# Only application/json. ld+json is schema.org metadata whose dates are
# ISO-formatted and so invisible to the date parser anyway; including it
# would be a guess about a source nobody has measured.
JSON_SCRIPT = re.compile(
    r"""<script[^>]*\btype=["']?application/json["']?[^>]*>(.*?)</script>""",
    re.S | re.I)

# NOT A SPACE, AND THE REASON IS NOT COSMETIC. Concatenating unrelated
# strings with whitespace can manufacture a date across a boundary present
# in neither: ["Revenue grew in August", "4, 2026 was a record"] joined with
# a space matches "August 4, 2026". The date pattern accepts \s+ between the
# month and the day, so a newline would not prevent it; a literal "|" cannot
# appear inside a match and ends it.
PAYLOAD_SEP = " | "


def _strings(node, out):
    """Every string value in a parsed JSON structure, in document order."""
    if isinstance(node, str):
        out.append(node)
    elif isinstance(node, list):
        for child in node:
            _strings(child, out)
    elif isinstance(node, dict):
        for child in node.values():
            _strings(child, out)


def payload_strings(html):
    """String values from every application/json block, in document order.

    Strings only, never the raw payload: keys, structure and escaping are
    noise the date parser would have to read past. A block that will not
    parse is skipped, because a site shipping broken JSON should cost the
    recovered text and nothing else.
    """
    out = []
    for m in JSON_SCRIPT.finditer(html or ""):
        try:
            data = json.loads(m.group(1))
        except ValueError:
            continue
        _strings(data, out)
    return out
```

Add `import json` at the top of `page_text.py`, above `import re`.

Then replace `extract_text` with:

```python
def extract_text(html, limit=None):
    """The text of a page: what it renders, plus what it ships as JSON.

    SOME SITES SERVER-RENDER THE ARTICLE INTO A JSON PAYLOAD RATHER THAN
    INTO MARKUP, and stripping <script> then deletes the article and keeps
    the furniture. HUT is such a site: its release page returns 121,286
    bytes, of which the visible half is 1,227 characters of headline,
    posting date and a signup form, while the reporting date sits in a
    __NUXT_DATA__ payload. Recovering it is the difference between a body
    that offers no date and one that offers exactly the right one.
    """
    stripped = SCRIPT_OR_STYLE.sub(" ", html or "")
    visible = " ".join(TAG.sub(" ", stripped).split())
    recovered = [" ".join(s.split()) for s in payload_strings(html)]
    recovered = [s for s in recovered if s]
    text = PAYLOAD_SEP.join([visible] + recovered) if recovered else visible
    return text[:limit] if limit else text
```

- [ ] **Step 4: Run the tests**

```bash
python test_page_text.py
```

Expected: `20/20 checks passed`.

- [ ] **Step 5: Demonstrate the separator guard actually fires**

A guard is not trusted here until the failure it prevents has been shown. Change
`PAYLOAD_SEP` to `" "` temporarily and re-run:

```bash
python test_page_text.py
```

Expected: FAIL on `adjacent strings cannot fabricate a date` and on `the
separator carries a non-whitespace character`. **Put `" | "` back** and re-run to
confirm `20/20`. Record both outputs in your report.

- [ ] **Step 6: Apply the cap at the call site**

In `press_monitor.py`, pass the cap through so a large payload cannot make the
body unbounded:

```python
    html = bytes(raw[:BODY_MAX_BYTES]).decode("utf-8", "replace")
    return page_text.extract_text(html, limit=BODY_MAX_BYTES)
```

- [ ] **Step 7: Confirm the whole suite**

```bash
python -m py_compile press_monitor.py && python test_page_text.py && python test_earnings_dates.py && python test_probe_body_dates.py
```

Expected: compiles, `20/20`, `130/130`, `32/32`.

- [ ] **Step 8: Commit**

```bash
git add page_text.py test_page_text.py press_monitor.py
git commit -m "Recover the release text a site ships as JSON"
```

---

### Task 3: Correct the record, and measure the result

**Files:**
- Modify: `docs/press-monitor.md:918-930`

**Interfaces:** none.

- [ ] **Step 1: Replace the passage that is wrong**

`docs/press-monitor.md:918-930` currently reads, in part:

> **It is not a parsing failure and not a fixable one: hut8.com serves no release
> body to a plain fetch.** ... The release text is rendered client-side, so
> `announcement_body` is not losing the date; the date was never in the response.
> ... **No rule reading bodies will ever recover it from this source**, and the
> fix, if one is wanted, is a route to the content rather than a better parser.

Every sentence there is false. Replace the whole passage with:

```markdown
The sixth advance notice is HUT's, and the first explanation recorded here
was wrong in every particular. It said hut8.com served no release body, that
the date was never in the response, and that no body-reading rule could ever
recover it. **The date was in the response the whole time, and
`announcement_body` was deleting it.**

hut8.com server-renders its article into a `__NUXT_DATA__` JSON payload
rather than into markup, and the extractor stripped `<script>` blocks before
reading. Replaying that pipeline over the page's 121,286 bytes yields exactly
1,227 characters, the figure logged here, which is the furniture: headline,
"Posted Jul 13, 2026", and a signup form. The payload holds two dates, the
dateline and **August 4, 2026**, so once the dateline is discounted the body
offers exactly one forward date.

**Two checks agreed the body was absent, and both were blind the same way.**
The probe's own fetch and a WebFetch of the same URL each render to text
before anyone sees them, so each dropped the payload for the same reason.
Agreement between two readings of the same blind spot is one reading.
`page_text.extract_text()` now recovers payload strings, and the fix is not
HUT-specific: any source that ships its article as JSON is readable.
```

- [ ] **Step 2: Confirm no other passage still claims the old story**

```bash
grep -n "rendered client-side\|never in the response\|no release" docs/press-monitor.md docs/earnings.md CLAUDE.md README.md
```

Expected: no output. Any match is another copy of the same wrong claim and must
be corrected in this task.

- [ ] **Step 3: Commit**

```bash
git add docs/press-monitor.md
git commit -m "Correct the HUT passage: the date was there all along"
```

- [ ] **Step 4: Push and re-run the probe**

`workflow_dispatch` reads the workflow from the default branch but runs the code
at `--ref`, and **Probe body dates** already exists on `main`, so a branch
dispatch works here:

```bash
git push -u origin hut-json-payload
gh workflow run "Probe body dates" --ref hut-json-payload
```

- [ ] **Step 5: Read the result strictly**

```bash
gh run list --workflow="Probe body dates" --limit 1 --json databaseId,conclusion
```

Then `gh run view <id> --log`. Compare against the table in
`docs/press-monitor.md`:

| label | one | several | none |
|---|---|---|---|
| advance notice | 5 | 0 | 1 |
| scheduled + results | 2 | 2 | 2 |
| not scheduled | 3 | 1 | 4 |

**Exactly one row may change its RESULT: HUT moves from `none` to `one` carrying
`2026-08-04`, taking advance notice to `6 / 0 / 0`.**

Compare **candidate dates and buckets**, not the `chars` column. Any other row
whose candidates or bucket change is a **finding to investigate and report, not a
bonus to accept.** If one does, stop and report which row, its old and new
candidates, and what in its page carries a JSON payload. Do not adjust the
expectation to fit the result.

**Do not gate on `chars`, and disregard a new row appearing.** The probe reads
live pages, so both drift for reasons that have nothing to do with this change.
Measured on 2026-08-12: GLXY fell 89 characters and a MARA row fell 23, decreases
that adding text cannot cause, and a BGDE release published that morning arrived
as a twenty-first row. Expect a small positive drift on sources carrying UI
strings in a payload, such as BKKT's `"Show All"`, `"Hide All"`,
`"Choose from list"`, 38 characters across all three of its rows. Read `chars` to
explain a result that moved; never to decide whether one did.

- [ ] **Step 6: Record what was measured**

Add the new counts and the run id beside the existing table in
`docs/press-monitor.md`, in the same style as the runs already recorded there.

```bash
git add docs/press-monitor.md
git commit -m "Record the probe run after payload recovery"
```

---

## Out of scope

Any change to the body-date rule, its four-condition gate, the `+` marker or the
overdue grace. Those shipped today and are unaffected: this task makes one more
source readable, and what happens to a readable body is already settled.
