[← Watchlist monitor](../README.md)

# Handoff, 2026-08-19

Where the repo stands after the first-run and filing-cadence work, what is
genuinely finished, what is **merged but not yet observed**, and what to pick
up next. **A point-in-time document: replace it rather than append to it.**

Everything below is on `main`. Working tree clean, Tests green, no branches
open.

---

## Merged, and already confirmed against live data

**The first-run rule, both axes.** A company added to the roster, and a form
type added to a config, both suppress their backlog on the run they appear
and post normally afterwards. Six components, ten namespaces. Verified across
51 live scheduled runs: each printed its `FIRST-RUN RULE:` backfill line
exactly once and has been silent since. See [`first_run.py`](../first_run.py)
and the trap rows in [`CLAUDE.md`](../CLAUDE.md).

**`prune_unmeasured`.** The rule was recording companies the run never
measured — `dilution_state.json` held 22 CIKs against 18 share counts. It now
prunes a key only when the run did not measure it **and** the component holds
no per-company state for it. Both conditions are load-bearing; pruning on the
first alone lost real events permanently and is written up in `first_run.py`.

---

## Merged, NOT yet observed

**`snapshot.json` has not been rebuilt since the merge.** The committed file
was generated `2026-08-19T11:16:36Z`, before it landed, so it still carries
the old values and no `schema` key. The first write is the next weekday
**11:00 UTC** run.

What that run will do, measured by dry run against live SEC data:

| | was | will be |
|---|---|---|
| APLD | `2026-05-31`, expected `2026-08-03` | `2026-08-31`, expected `2026-10-12` |
| BTDR | `2026-03-31`, expected `2026-07-20` | `2026-12-31`, expected `2027-04-21` |
| IREN | `sample 3` | `sample 4` |
| SPCX | `quarterly, sample 1` | no estimate, `1/2 quarterly and 0/2 annual filings` |
| all 22 | — | two fields added: `available`, `reason` |

**Check that run.** It is the only thing that confirms the change reached the
consumer, and `build_snapshot` now takes `DRY_RUN` if you want to preview
again first:

```bash
gh workflow run "Build snapshot" -f dry_run=true
```

**The equity research project has not been told.** It does not strictly need
to be — the published shape is a strict superset, so every key it reads is
still present and `projection["expected"]` returns `null` rather than raising
— but `schema: 1` and the rewritten `note` exist so it can be pointed at
them.

---

## Open, ranked

**1. Two components still disagree about `spread`.** `earnings_calendar`
publishes the full lag range (`max - min`, thresholded at 30 for the `~`
marker); `build_snapshot` publishes **half** of it. Both read the same
`lags` list from `filing_cadence`. This is now visible in one docstring
instead of buried in two files, which is an improvement and not a fix: it is
still two answers to one question, which is the shape the whole exercise was
about. Deliberately not unified, because either choice moves a live output.

**2. `press_monitor` records companies it never read, and it is documented
rather than fixed.** `company_filings()` returns `[]` on a fetch fault and
`collect_all()` prints "no filings returned" and continues, so a quiet
company and a failed request are the same value — there is nothing to test.
A roster addition landing on a failing run is recorded as established and its
filings post next run, bounded to seven days by `MAX_AGE_DAYS`. The prune
used elsewhere is unsafe here: items are marked seen before filtering, so it
would convert a bounded flood into permanent loss. **The real fix is
upstream** — make `company_filings` distinguish a fault from an empty result
— and belongs in its own session. Reasoning is at the `baseline_companies`
call site.

**3. The characterisation corpus lives in scratch and will vanish.** It is
what proved `earnings_calendar` unchanged across 2,570 cases, and the next
person to touch `project()` or `cadence()` will want it. It needs
`earnings_calendar`, so it cannot be a stdlib-only suite; committing it as
`probe_cadence_corpus.py` alongside the other probes is the obvious home.
**It asserts branch coverage and fails if a branch is never reached** — keep
that if it is moved, it is the only reason the result means anything.

**4. `degraded` has no field in the wire format.** It folds into
`confidence: "low"`. A consumer cannot distinguish "annual date, quarterly
lag" the way the Discord post's `?` marker does. Cheap to add if anyone wants
it; nobody has asked.

**5. There is no `docs/snapshot.md`.** Every other component has a doc; the
one with an external consumer does not. The `note` inside the file is
currently the whole contract.

**6. Two scheduled tasks are redundant.** `first-run-backfill-check-1` and
`-2` were set up to verify the backfill; it was verified directly instead.
They can be deleted.

---

## What is NOT proven, and would be easy to assume is

**The suppression path has never fired for a real addition.** Every namespace
backfilled and has been silent since, which is correct — but no company has
been added since the rule landed, so the branch that actually withholds a
backlog has run zero times in production. It has 135 offline checks and a
demonstration for each; it has no live evidence. The next roster addition is
the test.

**`press_monitor`'s carve-out is an argument, not a measurement.** Nobody has
measured how often the SEC submissions endpoint fails per company, so the
frequency of item 2 above is unknown — only its cost.

**The mutation harnesses live in scratch.** 118 mutations for
`test_first_run.py` and 20 for `test_build_snapshot.py`. Both print their
mutation count, which exists because a slice-based edit silently deleted
seven of them once and the resulting "never red" report was misread as a tool
fault. If you re-run one and the count has dropped, that is the reason.

---

## Three things this session got wrong, that the code does not show

Recorded because each cost real time and each is the kind of mistake that
looks like diligence while it is happening.

**A guard can be worse than the bug.** Two branches this week introduced a
defect more serious than the one being fixed — the prune lost events
permanently where a missed run had cost nothing, and the shared-rule import
would have killed the snapshot workflow outright. Both were caught by review,
neither by tests. **The pattern is touching something shared without checking
what depends on it**, and the tell is a change that reads as obviously
correct in the file you are editing.

**A green corpus over a grid that cannot reach the branch proves nothing.**
3,382 cases reported zero differences and reached the two branches most
likely to move exactly zero times, because the fixtures anchored quarterly
and annual periods on the same fiscal month. It was presented as strong
evidence. This is `CLAUDE.md`'s existing rule about fixtures reaching the
branch they name, arriving in the verification rather than in a test.

**"No mutation reddened this" and "this cannot be reddened" are the same
output.** Six checks were reported as never-red, hand-checking showed all six
went red under their named change, and the conclusion drawn was that the
harness was untrustworthy. The mutations had been deleted by a slice edit.
Print the count.
