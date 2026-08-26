[← Watchlist monitor](../README.md)

# Handoff, 2026-08-26

**Built from all sixteen session transcripts before they were deleted.** Those
transcripts held 608 user turns and 1.6 MB of assistant prose covering
2026-08-03 to 2026-08-26, and they are gone. Everything below is what a future
session needs that **cannot be recovered from the repository**, because the
repository is unusually good at recording itself: `CLAUDE.md` carries the traps
with the case that proves each, [`rejected.md`](rejected.md) carries the closed
ideas with their numbers, `docs/` has one file per component, and the commit
bodies are long. Anything already in those is deliberately absent here.

Claims were verified against the working tree, `origin/main` and full-text
greps on 2026-08-26. Ten claims that reader agents made were checked and found
already recorded, and were dropped rather than softened.

**A second workstream is handed off separately.** Roughly half of what this
folder has been used for is public writing about the roster, and none of it is
in this document. It lives in `docs/x-posts.md`, which is untracked and
local-only for the same reason the article draft is. A future session working
on the components does not need it; one asked about a post does.

**A point-in-time document: replace it rather than append to it.**

---

## 0. Before anything else

**This clone was 65 commits behind and 1 ahead when this was written.** Rebased
to `5bcb257`. Fourteen workflows commit to `main` all day, so a checkout goes
stale within hours. **A stale local state file reads exactly like a stalled
component**: `snapshot.json` looked 137 hours old and appeared to be a silent
outage, and it was a stale checkout. Fetch before diagnosing anything.

**`5bcb257` (was `40e4f72`) is committed and NOT pushed.** It adds
`scripts/backup.mjs` (524 lines), a `.gitignore` entry and 40 lines of README.
Evidence from the transcripts says this was **deliberate**: the repository is
public and "yes, commit them" was not read as authorisation to publish. Do not
push it without asking. The script itself is safe regardless, because it backs
itself up to `B:\Claude Backup\Infra Monitor\local\scripts\backup.mjs`.

**`memory/` lives inside the folder holding the session transcripts**, at
`C:\Users\zamzi\.claude\projects\C--Users-zamzi-OneDrive-Documents-Claude-Infra-Monitor\memory\`.
Deleting the project folder to clear sessions destroys all eleven memory files.
They were copied by hand on 2026-08-26 to `backup/local/claude-memory/` and to
drive B, `cmp`-verified. **That copy will go stale**: `scripts/backup.mjs` has
an eight-entry `LOCAL_ONLY` list and memory is not in it, so `mirror()` will
keep pushing frozen copies to B and reporting OK. Wiring it needs two changes,
`path.join(PROJECT, item.from)` to `path.resolve` so an absolute source works,
and directory support so new memory files are picked up.

---

## 1. How the user wants work done

This is the section the repository cannot supply, and the most expensive to
relearn.

**Show the diff, the table, or the dry-run output before committing.** Stated
in six of nineteen turns in one session and repeatedly elsewhere. It is the
main review control. Commit in separate pieces, not one blob.

**The user has no coding experience and wants the whole job done**, stopping
only at a genuine sign-in, decision or approval, with exact click instructions.
The prompts read as technical; the register is not.

**Always finish with options and a recommendation**, each with its cost, and
lead with the one you would pick. Never a bare status summary.

**Only one session works in this repo at a time.** Adopted 2026-08-05 after a
concurrent session committed all 201 lines of a five-company `watchlist.py`
addition inside commit `946e303`, whose subject is about filing delay regimes.

**Write the file before quoting its path.** Three times in one session a
Windows path was cited before the file existed, and the reply was "I dont see
the file".

**In a session spanning days, read dates off the filing rather than saying
"this morning".** A day of drift put a wrong date into a public draft on
2026-08-12. This recurred on 2026-08-26: the session believed it was the 20th.

**Never dispatch a component live to beat a clock.** Decided three times. A
live run marks every item seen whether or not it posts, so a late dispatch
burns the queue irreversibly.

**`EIA_API_KEY` stays in Actions secrets and is never exported into a local
shell.** Stated with "please do not propose the local route again".
`SEC_USER_AGENT` is different, being a contact string. The user edits
repository secrets himself. A second API key is a decision for him, and it has
never actually been put to him.

**Positioning data over opinion data**, as a standing boundary: Form 4, short
interest, short volume, 13D stakes and 52-week position are "people acting
rather than talking". Do not offer sentiment, ratings or price targets without
weighing them against this.

**A number justifying live behaviour needs a committed, re-runnable tool. A
number justifying a decision NOT to build does not**, because the answer to
disagreeing with the latter is re-measuring, and `rejected.md` enables that by
naming sources and methods. The user adopted this over his own earlier rule and
deleted fourteen scripts on it.

**Probes are disposable.** It is fine to commit one with a dispatch-only
workflow and later delete it. Five precedents: `probe_comment_letters`,
`probe_cusips`, `probe_52w`, `probe_eia`, `probe_sites`. `probe_cusips` became
`audit_identifiers.py`.

---

## 2. Open threads, ranked

**1. `press_monitor` records companies it never read.** `company_filings()`
returns `[]` both for a quiet company and for a fetch fault, so a roster
addition landing on a failing run is recorded as established. Bounded to seven
days by `MAX_AGE_DAYS`. The prune used elsewhere is unsafe here because items
are marked seen before filtering. **The real fix is upstream**, in
`company_filings`, and it wants its own session.

**2. Six remote branches are unmerged**, while the previous handoff said "no
branches open": `disclosed-reporting-dates` (19 commits),
`no-quarterly-history` (15), `bgde-source-probe` (11), `gnw-header-override`
(5), `fpi-form-mix-probe` (3), `bgde-feed-timeout` (3). Several have names
matching work that landed on `main` by another route. Somebody has to decide
superseded versus stranded. `fpi-form-mix-probe` carries a 134-line addition to
`earnings_calendar.py` that may be superseded by the shared `filing_cadence`
work.

**3. `ftd_monitor.py:572` names thin tickers with no count**, though the count
is already stored as `"periods": n`. `weekly_digest.py:1277` renders exactly
this measurement correctly, so the repair is a two-line copy. This contradicts
`CLAUDE.md:78`, which says every component now states a count and calls it
closed on 2026-08-12.

**4. The `±` column has no stated coverage target.** Measured: the published
interval contains the next filing **75.7%** of the time over 371 real events at
k=8; `floor+1` gives 83.8% and `floor+2` gives 89.5%. The estimator question is
closed in [`rejected.md`](rejected.md#a-median-based-half-width-for-the-published-spread).
What remains is a decision about what `±` promises a reader, and it is the
user's, not a task.

**5. `press_monitor.keep_proxy` loses a proposing proxy silently on a
non-200.** `body = ""`, falsy title, `return False`, no log. Items are marked
seen before the filter runs, so the DEF 14A never returns. Its docstring claims
nothing is lost.

**6. `grid_context.region_demand()` returns a bare `None`**, so a timeout and
EIA answering 200 with all-past forecast rows are indistinguishable, and the
embed does not mark the absence. Measured once: 4 of 14 runs degraded, every
one `conclusion: success`.

**7. Two sources named as genuine gaps on 2026-08-13 and never probed.** EDGAR
full-text search at `efts.sec.gov`, for roster companies named in *other*
filers' documents, which is the only idea that would add a new kind of source.
And the `EFFECT` form type, the invisible middle between an S-3 and a 424,
which exists in `probe_filing_rate.py` but not in `press_monitor.FORM_TYPES`.

**8. The FINRA 5,000-row silent cap is documented in one component and ignored
by two.** `weekly_digest.py:284` records the measurement and paginates;
`short_interest.py:93` sends one unpaginated request across 39 query symbols
with no row-count check; `regsho_volume.py:169` asks for `limit: 20000`.

**9. The first-run suppression path has never fired for a real addition.** 135
offline checks, zero live evidence. The next company added is the test.

**10. The loop harness has never driven a live project.** No
`docs/loop/state.json` has ever existed, the Planner was never built, and every
project since 2026-08-10 went through `docs/superpowers/` SDD instead, which is
the workflow the loop was built to replace. Decide whether it is live
infrastructure or an artefact and say so in `docs/loop/README.md`. Its
isolation procedure survives only at
`git show 8517359:docs/loop/VERIFY-ISOLATION.md`, and its key point is that a
4/4 score with a non-zero tool count is worse than a failing one.

**11. `docs/superpowers/` (10 specs, 9 plans) and `docs/loop/` are referenced
from nothing** in the README layout block, `CLAUDE.md` or
`docs/local-workflow.md`. The specs carry reasoning found nowhere else.

**12. HIVE, BTBT and CANG** were surveyed as roster candidates on 2026-08-13
and never resolved. Only BITF's rejection reached `docs/watchlist.md:388`.

**13. `GRID_COLS = 3` for the recap chart** was offered as a one-line fix and
never answered. Panel height measured ~1.38in at 14 tickers and ~0.97in at 19.
The roster is 22 now.

---

## 3. Stale facts inside the repo itself

Found by cross-checking documentation against code. Each is small and each will
mislead.

- **`docs/watchlist.md:329` says "Twenty-one companies"** and **`:385` says
  CRWV "was considered and not added"**. `watchlist.py` holds **22 including
  CRWV**.
- **`CLAUDE.md:22` says "Six of nineteen have renamed"**. The roster is 22.
- **`docs/watchlist.md:539` and `docs/grid-context.md:120` say BGDE is PJM
  only.** It operates in ERCOT: a 30-acre Hood County, Texas joint venture
  (Texas Load House LLC, 50/50 with 10NetZero) had 17 MW energized at
  2026-07-20.
- **All fifteen workflow `concurrency` groups are ref-independent literals**, so
  the `gh workflow run --ref <branch> -f dry_run=true` verification that
  `CLAUDE.md` prescribes contends with the live scheduled run of the same
  component on `main`.
- **`scripts/backup.mjs:59` names the private article by path and is tracked**,
  which defeats the deliberate rewording of the README's Backups section to
  avoid naming it.

---

## 4. Facts about the data that are not written down

- **A Charles Schwab trading restriction sat on BGDE** from roughly December
  2025 to 2026-08-12, inherited from the MIGI ticker. It falls inside the
  52-week and trailing windows that `crossings.py`, `short_interest.py` and
  `ftd_monitor.py` grade BGDE against. Float near 4M shares on 5,648,751
  outstanding at 2026-06-30.
- **"Six Thirty AI", BGDE's affiliate controlled by its Executive Chairman, CEO
  and COO, was formerly named "Big Digital Energy, LLC"**, the public company's
  own name. Any name-based filing or news sweep conflates the two.
- **CIFR and NUAI may be contesting the same 207 MW of Ector County
  generation.** Cipher's Odessa Luminant PPA (~$0.028/kWh, take-or-pay on
  66.7%) expires end of July 2027. The settling test agreed at the time was the
  delivery point named in New Era's Item 1.01 8-K. Zero repo hits for Luminant,
  Vistra, Odessa or Calpine.
- **SPCX's dilution row reads n/a until roughly February 2027 for a stronger
  reason than "does not tag a share count"**: its companyfacts payload carries
  no `dei` taxonomy at all, only `ffd` and `us-gaap`, so adding concepts to
  `CONCEPTS` cannot help.
- **EDGAR Form 4 index hrefs need not sit under the CIK used to reach the
  index.** Three of six GLXY Form 4 indexes listed their source XML under a
  different CIK. Seven files interpolate a CIK into an Archives URL.

---

## 5. Verification mechanics that produce confident wrong answers

- **`$?` after a pipe is the last command's status**, not the pipeline's.
- **A single-line grep needle cannot match a line-wrapped markdown sentence.**
  This cost a partial commit, and produced false absences inside the audit that
  produced this document.
- **`gh run list` can return a stale listing**, so an apparently stuck run is
  not evidence.
- **`.claude/` agent and skill definitions load at session start**, so a file
  created mid-session cannot be dispatched in that session.
- **`git add -A` is unsafe whenever the tree is not clean.** It swept an
  untracked private draft into a public commit on 2026-08-20. Stage explicit
  paths.
- **Windows `cp1252` breaks on arrows and dashes when printing.** Use
  `python -X utf8` for anything that echoes transcript or EDGAR text.

---

## 6. What could not be determined

- Whether the GitHub Support request to purge orphaned objects from this
  repository was ever sent. On 2026-08-20 an untracked file was swept into a
  public commit by `git add -A`, force-pushed out, and the orphaned commit was
  confirmed still reachable by SHA afterwards. A Support request was drafted.
  `.git/info/exclude` now carries the file, and that exclusion does not survive
  a re-clone.
- Whether the NUAI 4.02 restatement of 2026-07-30, deliberately left stranded
  rather than recovered by editing `state.json`, was ever posted by hand.
- Whether the two `first-run-backfill-check` scheduled tasks are armed or
  dormant. Both fired and died within seconds (21s and 2s) producing nothing
  and no failure signal, and both `SKILL.md` files are still on disk despite
  commit `ca4c9db` saying "both are deleted".
- Whether `regsho_volume.py` and `comment_letters.py` carry undocumented
  threshold reasoning. No session examined them and no gap was found, but no
  evidence exists that anyone checked.

---

## 7. What is confirmed healthy

Last checked 2026-08-26 04:30 UTC.

- **Zero failed workflow runs in the last 200.**
- **`snapshot.json` current**, generated 2026-08-25T11:18:08Z, 22 issuers,
  `schema: 1`. `confidence: "low"` is BTDR, CLSK and WYFI, matching the three
  the calendar marks `~`.
- **All eleven offline suites green**, and `probe_cadence_corpus.py --branches`
  reaches all eighteen branches over 7,714 cases.
- **The backup ran 2026-08-25 12:30** and mirrors to `B:\Claude Backup\Infra
  Monitor`.
