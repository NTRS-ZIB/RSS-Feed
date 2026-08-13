# Press monitor pure-function tests Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Test all 18 functions in `press_monitor.py` that decide something without a network, so the component that posts to Discord stops having no test in CI.

**Architecture:** One new standalone suite in the repo's own `check()` style, wired into the `Tests` workflow in its first commit because that workflow's coverage gate fails on an unlisted `test_*.py`. Tiered by evidence: the six functions behind recorded incidents first, then the five that shape what posts, then the small helpers.

**Tech Stack:** Python 3.12, standard library only in the test file itself. `feedparser` is stubbed at import.

## Global Constraints

- **`test_press_monitor.py` must be added to `.github/workflows/tests.yml` in the
  same commit that creates it.** That workflow's "Every suite is run by this
  workflow" step fails when a `test_*.py` exists that it does not run, so
  creating the file alone turns CI red.
- **Stub `feedparser` before importing `press_monitor`.** It is absent from a
  plain working copy. The stub is safe only because `feedparser` is touched
  solely by `parse_feed`, which none of these 18 functions calls. **If a future
  test needs a feed-parsing function, remove the stub rather than extend it.**
- **Do not modify `press_monitor.py`.** This plan adds tests. If a test cannot be
  made to pass, that is a finding to report, not a licence to edit the module.
- **Do not modify `test_baseline.py`.** It checks `baseline_companies` against a
  real recorded event with live SEC data, and that is complementary to the
  fixtures here, not duplicated by them.
- **Mutations must be reverted.** Tier 1 requires temporarily breaking the module
  to prove a test fires. Every mutation is undone in the same step, and
  `git status` must be clean before any commit.
- **Do not run the component scripts.** `press_monitor.py`, `earnings_calendar.py`
  read secrets and post to live Discord. **Do not run `probe_body_dates.py`**
  (real network) or **`test_baseline.py`** (needs a secret, hits the SEC). Safe:
  every other `test_*.py`, `python watchlist.py`, `python -m py_compile`.
- **`earnings_dates.json`, `state.json` and `snapshot.json` are outputs.** Never
  edit, delete, reformat or commit one.
- **Branch:** `press-monitor-tests`, already created, spec committed at `4685553`.
- Suite baselines that must still hold: `test_page_text.py` **36**,
  `test_earnings_dates.py` **130**, `test_probe_body_dates.py` **32**,
  `test_loop_state.py` **27**, `test_loop_verdict.py` **22**,
  `test_loop_approval.py` **11**.

## Values verified against the module, for use in tests

```
FORM_TYPES            8-K, 6-K, 424, S-1, S-3, 10-Q, 10-K, 20-F, 40-F,
                      SC 13D, SCHEDULE 13D, SC 13G, SCHEDULE 13G, "NT "
INSIDER_ALLOWED_FORMS 3, 3/A, 4, 4/A
ALWAYS_POST_ITEMS     1.03, 2.04, 2.06, 3.01, 4.01, 4.02, 5.01
PRESS_RELEASE_ITEMS   2.02, 7.01, 8.01
GENERIC_ITEMS         9.01
HOST_HEADERS          one key: www.globenewswire.com
CROSS_HOST_DAYS 7   STALE_MIN_DAYS 4   STALE_MULTIPLE 6   STALE_FLOOR_DAYS 60
MAX_AGE_DAYS 7      RETAIN_DAYS 30
ARCHIVE  https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nodash}/{acc}-index.htm
```

**Note that `FORM_TYPES` already carries both spellings** of 13D and 13G. The
rename is handled; the drift detector exists to catch the *next* one.

## File Structure

| File | Responsibility |
|---|---|
| Create `test_press_monitor.py` | Every check in this plan. Standalone, stdlib, no network. |
| Modify `.github/workflows/tests.yml` | Run the new suite; required by its own coverage gate. |

---

### Task 1: Scaffold, wiring, and the form-matching group

**Files:**
- Create: `test_press_monitor.py`
- Modify: `.github/workflows/tests.yml`

**Interfaces:**
- Produces: `test_press_monitor.py` with a `check(name, ok, detail="")` helper, a
  `results` list, and a `main()` returning 0 or 1. Tasks 2 to 5 append sections
  inside `main()` and rely on those exact names.

- [ ] **Step 1: Write the suite scaffold and the first checks**

Create `test_press_monitor.py`:

```python
#!/usr/bin/env python3
"""Tests for press_monitor's pure functions. Standalone, no network.

feedparser is stubbed below because it is absent from a plain working copy.
That is safe ONLY because feedparser is touched solely by parse_feed, which
none of the functions tested here calls. If a test ever needs a
feed-parsing function, REMOVE THE STUB rather than extending it: a stub
that grows is a stub that starts hiding things.

THE ONE THAT MATTERS: prefix matching does not bridge a form-type rename.
The SEC renamed SC 13D to SCHEDULE 13D and 117 filings went unposted,
because "SCHEDULE 13D".startswith("SC 13D") is False and nothing said so.
drift_candidates exists to catch the next rename, and the checks below are
what stop it quietly ceasing to.
"""

import sys
import types

sys.modules.setdefault("feedparser", types.ModuleType("feedparser"))

import press_monitor as pm

PASS, FAIL = "PASS", "FAIL"
results = []


def check(name, ok, detail=""):
    results.append((PASS if ok else FAIL, name))
    print(f"  [{PASS if ok else FAIL}] {name}" + (f" — {detail}" if detail else ""))


def main():
    print("FORM MATCHING")
    check("a prefix matches its amendment",
          pm.form_matches("8-K/A", ["8-K"]))
    check("a prefix does not match an unrelated form",
          not pm.form_matches("DEF 14A", ["8-K"]))
    # THE 117-FILING INCIDENT, as a property of the module rather than of
    # Python. An earlier draft asserted not "SCHEDULE 13D".startswith(
    # "SC 13D"), which is true of the language and could not fail whatever
    # press_monitor did. This calls the real function, so it fails if anyone
    # makes form_matches fuzzy or substring-based to "fix" renames.
    check("PREFIX MATCHING DOES NOT BRIDGE A RENAME",
          not pm.form_matches("SCHEDULE 13D", ["SC 13D"]),
          "the rename the prefix could not follow, asked of the module")

    check("form_core strips the amendment suffix and spacing",
          pm.form_core("SC 13D/A") == "SC13D", pm.form_core("SC 13D/A"))
    check("form_core is case-insensitive",
          pm.form_core("sc 13d") == "SC13D")

    print("\nDRIFT DETECTION")
    # Both spellings are tracked today, so nothing should be flagged.
    check("a tracked form is not flagged as drift",
          pm.drift_candidates({"SCHEDULE 13D"}) == [])
    check("an unrelated form is not flagged",
          pm.drift_candidates({"DEF 14A"}) == [])
    check("an obsolete form in DRIFT_IGNORE is not flagged",
          pm.drift_candidates({"10-K405"}) == [],
          "a warning that always fires is one nobody reads")

    # The incident itself: with the new spelling untracked, the old one must
    # still recognise it, WITHOUT anyone having told it the new name.
    original = pm.FORM_TYPES[:]
    try:
        pm.FORM_TYPES = [f for f in original if f != "SCHEDULE 13D"]
        check("an untracked rename IS flagged against its old spelling",
              pm.drift_candidates({"SCHEDULE 13D"}) == [("SCHEDULE 13D", "SC 13D")],
              "this is the guard that would have caught the 2024 rename")
    finally:
        pm.FORM_TYPES = original
    check("FORM_TYPES is restored after the drift check",
          pm.FORM_TYPES == original)

    # A known limit, pinned so it is a decision rather than a surprise. The
    # docstring says a match fires when one core contains the other "or vice
    # versa", but the code tests only `stem in core`. Measured: with only the
    # NEW spelling tracked, a seen OLD spelling is NOT flagged.
    original = pm.FORM_TYPES[:]
    try:
        pm.FORM_TYPES = [f for f in original if f != "SC 13D"]
        check("the detector is ASYMMETRIC, and this pins which way",
              pm.drift_candidates({"SC 13D"}) == [],
              "docstring says 'or vice versa'; the code checks one direction")
    finally:
        pm.FORM_TYPES = original

    bad = sum(1 for r, _ in results if r == FAIL)
    print(f"\n{len(results) - bad}/{len(results)} checks passed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Run it and confirm it passes**

```bash
python test_press_monitor.py
```

Expected: `11/11 checks passed`.

- [ ] **Step 3: Wire it into the workflow, or CI goes red**

In `.github/workflows/tests.yml`, add a step after the `page_text` step and
before `earnings_dates`, keeping the existing one-step-per-suite shape:

```yaml
      - name: press_monitor
        run: python -u test_press_monitor.py
```

The workflow's own coverage gate fails when a `test_*.py` exists that it does not
run, so this is not optional and cannot wait for a later task.

- [ ] **Step 4: Confirm the coverage gate is satisfied**

```bash
python - <<'PY'
import glob, re, sys
EXCLUDED = {"test_baseline.py"}
wf = open(".github/workflows/tests.yml", encoding="utf-8").read()
run = set(re.findall(r"python -u (test_\w+\.py)", wf))
missing = sorted(set(glob.glob("test_*.py")) - run - EXCLUDED)
print("missing:", missing or "none")
print("suites run:", len(run))
PY
```

Expected: `missing: none` and `suites run: 7`.

- [ ] **Step 5: DEMONSTRATE the drift check fires**

A guard is not trusted here until its failure has been seen. The check above
restores `FORM_TYPES` itself, so prove it differently: break the detector, not
the data.

In `press_monitor.py`, temporarily change `drift_candidates`'s stem-length guard
from `if len(stem) >= 3 and stem in core:` to `if False:`. Then:

```bash
python test_press_monitor.py; echo "exit=$?"
```

Expected: FAIL on `an untracked rename IS flagged against its old spelling`, and
`exit=1`.

**Restore the line**, re-run, and confirm `11/11` and `exit=0`. Record both
outputs in your report. Then confirm the module is untouched:

```bash
git diff --stat press_monitor.py
```

Expected: no output.

- [ ] **Step 6: Confirm nothing else broke and commit**

```bash
python test_page_text.py && python test_earnings_dates.py && python test_probe_body_dates.py
git add test_press_monitor.py .github/workflows/tests.yml
git commit -m "Test the form matching that missed 117 filings"
```

Expected before committing: `36/36`, `130/130`, `32/32`.

---

### Task 2: `headers_for` and `check_staleness`

**Files:**
- Modify: `test_press_monitor.py`

**Interfaces:**
- Consumes: `check`, `results`, `main` from Task 1.
- Produces: nothing new. Later tasks append further sections to `main()`.

- [ ] **Step 1: Add the checks**

In `main()`, after the `DRIFT DETECTION` section and before the `bad = ...`
tally, add:

```python
    print("\nPER-HOST HEADERS")
    # A browser-like User-Agent is a per-host bet. GlobeNewswire stalls a
    # Chrome-claiming request from the runner and answers a plain one in
    # 0.1s; not knowing that cost 22 hours of silent outage.
    gnw = pm.headers_for("https://www.globenewswire.com/rss/organization/x")
    check("a host in HOST_HEADERS gets its override",
          gnw is pm.HOST_HEADERS["www.globenewswire.com"],
          "losing this bet presents as a dead host, not as a refusal")
    check("any other host gets IR_HEADERS",
          pm.headers_for("https://ir.mara.com/feed") is pm.IR_HEADERS)
    check("the netloc lookup is case-insensitive",
          pm.headers_for("https://WWW.GlobeNewswire.COM/x") is gnw,
          "a casing miss silently reverts the host to the losing bet")
    check("a path does not affect the lookup",
          pm.headers_for("https://www.globenewswire.com/") is gnw)

    print("\nSTALENESS")
    import io as _io, time as _time, contextlib as _ctx

    def staleness_log(times, **kw):
        """check_staleness RETURNS None ON EVERY PATH; it logs and returns.

        So asserting on its return value cannot discriminate: `is None` is
        true whether the horizon fired, the history was too short, or the
        collapse was deleted. An earlier draft of this suite did exactly
        that, and a mutation removing the same-day collapse passed it. The
        log is the only observable, so the log is what these check.
        """
        buf = _io.StringIO()
        with _ctx.redirect_stdout(buf):
            pm.check_staleness("T", times, **kw)
        return buf.getvalue()

    now = _time.time()
    day = 86400

    # Three releases in one morning are ONE publication event. Measured on
    # real data: HUT's median gap reads 5.5d uncollapsed and 18d collapsed,
    # so this is what makes the horizon mean anything.
    check("same-day items collapse to ONE publication day",
          "1 publication day(s)" in staleness_log(
              [now - 1, now - 2, now - 3, now - 4, now - 5]),
          "uncollapsed these five would read as five days of history")
    check("genuinely distinct days are counted as distinct",
          "2 publication day(s)" in staleness_log([now - day, now - 2 * day]))

    # Below STALE_MIN_DAYS it reports a COUNT rather than warning. Too little
    # history and a dead source are different measurements.
    check("too little history says so rather than warning",
          "insufficient history" in staleness_log([now - day, now - 2 * day]))

    check("a fresh source logs NOTHING",
          staleness_log([now - i * day for i in range(10)]) == "",
          "silence is the healthy signal; a warning here would be noise")

    # Ten daily items whose newest is a year old: median gap 1d, so the
    # horizon is the 60d floor rather than 6x1d, and age is ~365d.
    dead = staleness_log([now - 365 * day - i * day for i in range(10)])
    check("a source dead a year is called STALE", "STALE" in dead, dead[:60])
    check("the log names the term that actually set the horizon",
          "60d floor" in dead,
          "a warning that cannot explain its threshold invites dismissal")

    check("no timestamps at all logs nothing", staleness_log([]) == "")
    check("all-zero timestamps are treated as no timestamps",
          staleness_log([0, 0]) == "")
```

- [ ] **Step 2: Run and confirm**

```bash
python test_press_monitor.py
```

Expected: `23/23 checks passed`.

- [ ] **Step 3: DEMONSTRATE the same-day collapse check fires**

In `press_monitor.py`'s `check_staleness`, temporarily change

```python
    days = sorted({int(t // 86400) for t in times}, reverse=True)
```

to use a list rather than a set, so same-day items no longer collapse:

```python
    days = sorted([int(t // 86400) for t in times], reverse=True)
```

Then:

```bash
python test_press_monitor.py; echo "exit=$?"
```

Expected: FAIL on `same-day items collapse to ONE publication day`, and the suite
at **22/23**.

**It fails because the log goes EMPTY, not because it says `5`.** That is worth
stating exactly, because the obvious explanation is wrong and was written into an
earlier draft of this step. With the collapse removed, five items count as five
publication days, which CLEARS `STALE_MIN_DAYS` of 4. So the function never
reaches the insufficient-history message at all; it computes a horizon instead,
and five timestamps seconds apart give a median gap of 0, a 60-day floor and an
age of about zero. Healthy. Silent. The check fails because an empty string does
not contain `1 publication day(s)`.

Measured, not reasoned: `check_staleness` with the collapse removed logs `''` for
that input.

**Verified before this plan was written:** with the collapse removed the
staleness section drops to 7 of its 8 checks. An earlier draft asserted
`check_staleness(...) is None` instead, which passed under this exact mutation,
because the function returns `None` on every path. That is why these checks read
the log rather than the return value.

**Restore the set comprehension**, re-run, confirm `23/23`, and confirm
`git diff --stat press_monitor.py` is empty. Record both outputs.

- [ ] **Step 4: DEMONSTRATE the header override check fires**

Temporarily change `headers_for`'s body to `return IR_HEADERS`. Re-run.

Expected: FAIL on `a host in HOST_HEADERS gets its override` and on `the netloc
lookup is case-insensitive`.

**Restore it**, re-run, confirm `23/23` and a clean `git diff`. Record both.

- [ ] **Step 5: Commit**

```bash
git add test_press_monitor.py
git commit -m "Test the per-host header bet and the staleness horizon"
```

---

### Task 3: `suppress_cross_host`

**Files:**
- Modify: `test_press_monitor.py`

**Interfaces:**
- Consumes: `check`, `results`, `main` from Task 1.

**This is the function where a wrong answer silently eats a real post.** Every
other failure mode in this module adds noise; this one removes signal.

- [ ] **Step 1: Add the checks**

In `main()`, after the `STALENESS` section, add:

```python
    print("\nCROSS-HOST SUPPRESSION")
    base = _time.time()

    def item(title, when):
        return {"title": title, "published": when, "uid": title}

    Q1_2021 = "Galaxy Digital Announces First Quarter 2021 Financial Results"
    Q1_2022 = "Galaxy Digital Announces First Quarter 2022 Financial Results"

    # An exact repeat inside the window is a genuine duplicate.
    kept = pm.suppress_cross_host([item(Q1_2022, base)],
                                  [item(Q1_2022, base - 3600)], "T")
    check("an exact title inside the window is suppressed", kept == [])

    # THE ONE THAT MATTERS. These two scored 0.984 similarity across 23,771
    # measured pairs. Any threshold below 1.000 suppresses one as a duplicate
    # of the other, silently, once a quarter, on the highest-value item the
    # channel carries.
    kept = pm.suppress_cross_host([item(Q1_2022, base)],
                                  [item(Q1_2021, base - 3600)], "T")
    check("A 0.984-SIMILAR TITLE IS NOT SUPPRESSED", len(kept) == 1,
          "no similarity threshold may creep in here")

    # The window is what makes exact matching safe by construction.
    old = base - (pm.CROSS_HOST_DAYS + 1) * 86400
    kept = pm.suppress_cross_host([item(Q1_2022, base)],
                                  [item(Q1_2022, old)], "T")
    check("an exact title outside the window is not suppressed", len(kept) == 1)

    # A failed scrape must not read as a successful match against nothing.
    feed = [item(Q1_2022, base), item(Q1_2021, base)]
    check("an empty newsroom suppresses nothing at all",
          pm.suppress_cross_host(feed, [], "T") == feed,
          "the bias is to post twice, never to suppress")

    # A missing timestamp on either side cannot satisfy the window.
    kept = pm.suppress_cross_host([item(Q1_2022, 0)],
                                  [item(Q1_2022, base)], "T")
    check("a feed item with no timestamp is not suppressed", len(kept) == 1)
    kept = pm.suppress_cross_host([item(Q1_2022, base)],
                                  [item(Q1_2022, 0)], "T")
    check("a newsroom item with no timestamp suppresses nothing", len(kept) == 1)

    print("\nTITLE NORMALISATION")
    check("punctuation and case do not change a normalised title",
          pm.norm_title("Q1 2026 Results!") == pm.norm_title("q1 2026 results"))
    check("an HTML entity is stripped",
          "amp" not in pm.norm_title("Smith &amp; Co Results"))
    check("two different titles do not normalise equal",
          pm.norm_title(Q1_2021) != pm.norm_title(Q1_2022),
          "this is what stops the year being normalised away")
```

- [ ] **Step 2: Run and confirm**

```bash
python test_press_monitor.py
```

Expected: `32/32 checks passed`.

- [ ] **Step 3: DEMONSTRATE the similarity check fires**

This is the most important demonstration in the plan, because it is the mutation
that would silently eat a real quarterly-results post.

In `suppress_cross_host`, temporarily replace the exact-title index lookup

```python
        twins = index.get(norm_title(it["title"]), [])
```

with a substring match across all newsroom titles:

```python
        key = norm_title(it["title"])
        twins = [p for k, v in index.items() for p in v
                 if k[:40] == key[:40]]
```

That is a crude stand-in for a similarity threshold: it matches on the first 40
normalised characters, which `First Quarter 2021` and `First Quarter 2022` share.

```bash
python test_press_monitor.py; echo "exit=$?"
```

Expected: FAIL on `A 0.984-SIMILAR TITLE IS NOT SUPPRESSED`.

**Restore the original line**, re-run, confirm `32/32`, and confirm
`git diff --stat press_monitor.py` is empty. Record both outputs. This one goes
in the report verbatim.

- [ ] **Step 4: Commit**

```bash
git add test_press_monitor.py
git commit -m "Test that no similarity threshold can creep into dedupe"
```

---

### Task 4: The five functions that shape what posts

**Files:**
- Modify: `test_press_monitor.py`

**Interfaces:**
- Consumes: `check`, `results`, `main` from Task 1.

- [ ] **Step 1: Add the checks**

In `main()`, after the `TITLE NORMALISATION` section, add:

```python
    print("\nALWAYS-POST ITEMS")
    check("a matching code posts whatever its position",
          pm.always_post_items({"form": "8-K", "items": "9.01,4.02"}))
    check("a matching code posts when listed first",
          pm.always_post_items({"form": "8-K", "items": "4.02,9.01"}))
    check("an unrelated item set does not post",
          not pm.always_post_items({"form": "8-K", "items": "7.01"}))
    check("a non-8-K form is never considered",
          not pm.always_post_items({"form": "10-Q", "items": "4.02"}))
    check("a missing items field is safe",
          not pm.always_post_items({"form": "8-K"}))

    print("\nPRESS RELEASE DETECTION")
    check("a press-release item code passes",
          pm.carries_press_release("8-K", "2.02,9.01"))
    check("an unrelated item code does not",
          not pm.carries_press_release("8-K", "5.02"))
    check("a 6-K is never filtered, having no item numbers",
          pm.carries_press_release("6-K", ""))
    # 1,986 of 1,986 real 8-Ks carry item codes, so this branch has never
    # once executed in production. A fixture can exercise what real data
    # never has, which is the cheapest insurance against someone deleting
    # it as dead code.
    check("AN 8-K WITH NO ITEM CODES FAILS OPEN",
          pm.carries_press_release("8-K", ""),
          "a branch real data has never reached; do not simplify it away")

    print("\nFORM LABELS AND TITLES")
    # No two FORM_LABELS keys currently form a prefix pair, so form_label's
    # longest-first sort is real code no live data exercises. Do not fake a
    # test for it by inventing a key; check what is actually true.
    check("a late-notice form gets its specific label",
          pm.form_label("NT 10-K") != "",
          "NT is not itself a label key, so this must not fall through")
    check("an amendment is labelled as one",
          pm.form_label("10-Q/A").endswith("(amended)"))
    check("an unknown form has no label", pm.form_label("DEF 14A") == "")

    check("8-K item labels beat the SEC document label",
          pm.filing_title("8-K", "2.02", "8-K") == pm.ITEM_LABELS["2.02"])
    check("a generic item yields to a meaningful one",
          pm.filing_title("8-K", "9.01,2.02", "8-K") == pm.ITEM_LABELS["2.02"],
          "9.01 is in GENERIC_ITEMS and says nothing on its own")
    check("a generic item alone is still used rather than nothing",
          pm.filing_title("8-K", "9.01", "8-K") == pm.ITEM_LABELS["9.01"])
    check("a repeated label appears once",
          pm.filing_title("8-K", "2.02,2.02", "8-K").count(
              pm.ITEM_LABELS["2.02"]) == 1)
    check("an amended 8-K title says so",
          pm.filing_title("8-K/A", "2.02", "8-K").endswith("(amended)"))
    check("with no items it falls back to the form label",
          pm.filing_title("10-Q", "", "") == pm.form_label("10-Q"))
    check("with no label it falls back to the description",
          pm.filing_title("DEF 14A", "", "Proxy statement") == "Proxy statement")
    check("with nothing at all it names the form",
          pm.filing_title("DEF 14A", "", "") == "DEF 14A filing")

    print("\nFILING TIMESTAMPS")
    # filingDate is a DATE ONLY. Reading it alone puts publication at 00:00
    # UTC and discards a mean of 17.7 hours across 122 measured filings,
    # 10.5% of the MAX_AGE_DAYS window, because 48% of filings land between
    # 20:00 and 23:00 UTC.
    noon = pm.filed_time("2026-08-12", "2026-08-12T12:00:00Z")
    midnight = pm.filed_time("2026-08-12")
    check("acceptanceDateTime is preferred over the date", noon > midnight)
    check("the acceptance stamp is read as UTC, not Eastern",
          noon - midnight == 12 * 3600,
          "the field ends in Z and IS UTC; CLAUDE.md records the two "
          "confirmations that wrongly said otherwise")
    check("a malformed acceptance stamp falls back to the date",
          pm.filed_time("2026-08-12", "not-a-timestamp") == midnight)
    check("a malformed date returns 0 rather than raising",
          pm.filed_time("not-a-date") == 0)
```

- [ ] **Step 2: Run and confirm**

```bash
python test_press_monitor.py
```

Expected: `56/56 checks passed`.

- [ ] **Step 3: Confirm the never-executed branch is genuinely exercised**

The `AN 8-K WITH NO ITEM CODES FAILS OPEN` check covers a branch that real data
has never reached. Prove the check is load-bearing: in `carries_press_release`,
temporarily change

```python
    if not items:
        return True
```

to `return False`, re-run, and confirm that check FAILS. **Restore it**, re-run,
confirm `56/56` and a clean `git diff --stat press_monitor.py`. Record both.

- [ ] **Step 4: Commit**

```bash
git add test_press_monitor.py
git commit -m "Test the item rules, titles and timestamps that shape a post"
```

---

### Task 5: The small helpers and `baseline_companies`

**Files:**
- Modify: `test_press_monitor.py`

**Interfaces:**
- Consumes: `check`, `results`, `main` from Task 1.

- [ ] **Step 1: Add the checks**

In `main()`, after the `FILING TIMESTAMPS` section, add:

```python
    print("\nIDENTIFIERS AND FEED HELPERS")
    check("filing_uid keeps the Atom-era format",
          pm.filing_uid("0001193125-26-000123")
          == "urn:tag:sec.gov,2008:accession-number=0001193125-26-000123",
          "changing this makes every historical filing look new")
    url = pm.filing_url("1507605", "0001193125-26-000123")
    check("filing_url carries the accession dashed and undashed",
          "000119312526000123" in url and "0001193125-26-000123" in url, url)

    check("no keywords configured passes everything",
          pm.passes_keywords({"title": "anything at all"})
          if not pm.KEYWORDS else True,
          "KEYWORDS is empty in this repo, so this is the live path")

    # BOTH keys present, or the check cannot test preference at all. A
    # fixture carrying only one key returns the same epoch whatever order
    # the function reads them in, so reversing the preference would not
    # fail it. The two dates differ by a day so the answer is unambiguous.
    check("entry_time PREFERS published_parsed over updated_parsed",
          pm.entry_time({"published_parsed": (2026, 8, 12, 0, 0, 0, 0, 0, 0),
                         "updated_parsed": (2026, 8, 11, 0, 0, 0, 0, 0, 0)})
          == 1786492800,
          "reversing the preference returns the 11th, one day earlier")
    check("entry_time falls through when published_parsed is absent",
          pm.entry_time({"updated_parsed": (2026, 8, 12, 0, 0, 0, 0, 0, 0)})
          == 1786492800)
    check("entry_time returns 0 when nothing is usable",
          pm.entry_time({}) == 0,
          "that 0 becomes a released of None, which the body-date rule refuses")

    # TWO tags, or "first" is untestable for the same reason. A single-tag
    # fixture proves only that a term is read and stripped.
    check("entry_form takes the FIRST tag's term, and strips it",
          pm.entry_form({"tags": [{"term": " 8-K "}, {"term": "4"}]}) == "8-K",
          "taking the last would return 4")
    check("entry_form skips a tag whose term is empty",
          pm.entry_form({"tags": [{"term": ""}, {"term": "4"}]}) == "4",
          "the `if term:` guard, which a single-tag fixture cannot reach")
    check("entry_form uses the fallback when there are no tags",
          pm.entry_form({}, "6-K") == "6-K")

    print("\nBASELINE SUPPRESSION FOR A NEW COMPANY")
    # Adding a ticker must produce NO backdated posts AT ALL. Not "none older
    # than MAX_AGE_DAYS", none. An item six days old is unseen and inside the
    # window, and on 2026-08-05 exactly that posted a handful of backdated
    # items. The record lives in state["baselined"], NOT in "seen": seen is
    # capped at 1000 and actively evicting, and a uid carries no company, so
    # "has this company any ids in seen" cannot be asked of the file at all.
    old_item = {"uid": "o", "ticker": "NEW", "published": 1,
                "title": "Old", "form": "8-K"}
    new_item = {"uid": "r", "ticker": "NEW", "published": 2,
                "title": "Recent", "form": "8-K"}
    est_item = {"uid": "e", "ticker": "MARA", "published": 3,
                "title": "Established", "form": "8-K"}
    every = [old_item, new_item, est_item]

    # An ABSENT key is the backfill run: every roster company has been posting
    # for weeks, so all are recorded and nothing is suppressed.
    state = {}
    new_co, sup = pm.baseline_companies(state, ["NEW", "MARA"], every,
                                        today="2026-08-13")
    check("an absent baselined key suppresses nothing",
          (new_co, sup) == ([], []),
          "first run under the rule; everyone is established by definition")
    check("the backfill records the whole roster",
          set(state["baselined"]) == {"NEW", "MARA"},
          "so a later run can tell a genuinely new company from these")

    # A company missing from a PRESENT dict is the new one.
    state = {"baselined": {"MARA": "2026-08-01"}}
    new_co, sup = pm.baseline_companies(state, ["NEW", "MARA"], every,
                                        today="2026-08-13")
    check("a company absent from a present dict is new", new_co == ["NEW"])
    check("EVERY item from a new company is suppressed, whatever its age",
          {i["uid"] for i in sup} == {"o", "r"},
          "not only the aged ones; a six-day-old item posted on 2026-08-05")
    check("an established company's item is untouched",
          "e" not in {i["uid"] for i in sup})
    check("the new company is recorded, so it is new only once",
          state["baselined"]["NEW"] == "2026-08-13")

    state = {"baselined": {"MARA": "2026-08-01", "NEW": "2026-08-10"}}
    check("a roster with no new companies suppresses nothing",
          pm.baseline_companies(state, ["NEW", "MARA"], every,
                                today="2026-08-13") == ([], []))
```

- [ ] **Step 2: Run and confirm**

```bash
python test_press_monitor.py
```

Expected: `72/72 checks passed`.

The `baseline_companies` fixtures above were verified against the live function
before this plan was written: the record lives in `state["baselined"]`, `today` is
an ISO string, and the return is a `(new_companies, suppressed_items)` pair of
lists. If anything differs, report it rather than changing `press_monitor.py` to
fit the test.

- [ ] **Step 3: Confirm the whole suite and the workflow**

```bash
python test_press_monitor.py && python test_page_text.py && python test_earnings_dates.py && python test_probe_body_dates.py && python test_loop_state.py && python test_loop_verdict.py && python test_loop_approval.py
python -m py_compile press_monitor.py
git diff --stat press_monitor.py
```

Expected: `72/72`, `36/36`, `130/130`, `32/32`, `27/27`, `22/22`, `11/11`;
compiles; and **no output from the last command**, proving every Tier 1 mutation
was reverted.

- [ ] **Step 4: Commit and push**

```bash
git add test_press_monitor.py
git commit -m "Test the small helpers and the new-company baseline"
git push -u origin press-monitor-tests
```

- [ ] **Step 5: Confirm CI is green**

```bash
gh run list --workflow="Tests" --limit 1 --json databaseId,conclusion
```

The push touches a `.py` file, so `Tests` must fire. Expected: `success`, with a
`press_monitor` step in the list. Record the run URL.

---

## A finding to report, not to fix

`drift_candidates`' docstring says a match fires when an unmatched form's core
contains a tracked prefix's core **"or vice versa"**. The code implements only
`stem in core`, one direction. Measured: with only `SCHEDULE 13D` tracked, a seen
`SC 13D` is **not** flagged.

The direction that works is the one the 2024 incident needed, so nothing is
broken. But the docstring claims more than the code does, and Task 1 pins the real
behaviour in a check so it is a recorded decision rather than a surprise.

**Do not fix either side under this plan.** Whether to correct the docstring or
implement the second direction is a behaviour question for the repo owner.

## Out of scope

The 20 functions that fetch, scrape, read a file or post. Modifying
`press_monitor.py` for any reason. Changing `test_baseline.py`.
