[← Watchlist monitor](../README.md)

# Local working copy

How to edit this repo from a clone instead of the GitHub web UI. Unlike the rest
of `docs/`, this documents no component — it documents working on the repo
itself.

## Critical: the bots commit to `main` all day

Fourteen workflows run on crons and commit their own state back to `main`,
several times a day, unattended. Ten files at the repo root are written this way
and by nothing else:

```
state.json                crossings_state.json
spike_state.json          dilution_state.json
shortinterest_state.json  ftd_state.json
regsho_state.json         letters_state.json
threshold_state.json      snapshot.json
```

Two consequences follow, and both bite:

- **A clone goes stale within hours.** Not days. Pull before you touch anything.
- **A push without pulling first will be rejected**, or worse, will succeed and
  overwrite a bot commit with a state file from this morning.

These are outputs. Nothing local should ever author them.

## Daily sequence

Before starting work:

```bash
git pull
```

`pull.rebase` and `rebase.autoStash` are set locally, so this rebases rather
than merging and stashes uncommitted work around it. State files resolve to the
remote version silently — no prompt, no conflict.

When done:

```bash
git add -A
git commit -m "your message"
git pull
git push
```

**The `git pull` before `push` is not optional.** With fourteen crons running, a
non-fast-forward rejection is the common case, not the exception.

## Critical: `merge=ours` means the opposite of what it looks like

A merge driver receives two sides, `%A` ("ours") and `%B` ("theirs"). Which
physical side is the *remote* inverts between operations:

- During a **merge**, `HEAD` is the local branch, so `%A` is local.
- During a **rebase**, local commits are replayed on top of the upstream, so
  `%A` is the **remote**.

So neither built-in driver is correct for both:

| driver | `git pull` (merge) | `git pull --rebase` |
|---|---|---|
| `merge=ours` (keep `%A`) | keeps **local** ✗ | keeps **remote** ✓ |
| `merge=theirs` (keep `%B`) | keeps **remote** ✓ | keeps **local** ✗ |

A configuration that behaves correctly under `git pull --rebase` does the exact
opposite under a plain `git pull`, silently, with no conflict raised. That is
how a stale local state file ends up overwriting a bot commit.

The fix is a driver that detects which operation is running rather than assuming
one. `.git/state-merge.sh` checks for `.git/rebase-merge` or `.git/rebase-apply`
and keeps `%A` during a rebase, or copies `%B` over `%A` otherwise.

Verified both ways before being relied on: with a stale local commit and a
conflicting bot commit on the same file, the remote version survives under
`git pull` and under `git pull --rebase`, with no conflict markers and no
unmerged state, while an unrelated local edit in the same commit is preserved.
The naive `merge=ours` configuration was run as a control and failed the merge
case, pushing the stale value over the bot commit.

## Second layer: the pre-commit hook

A merge driver only runs when **both** sides changed a file. A local-only change
to a state file produces no conflict, so it would commit and push cleanly and
clobber whatever the bot writes next.

`.git/hooks/pre-commit` refuses any commit that stages one of the ten files
above, including when it is mixed in with a legitimate change. Override with
`git commit --no-verify` — which is almost never the right answer.

## Setup after a fresh clone

None of the above is committed. Merge drivers cannot be, in any case — the
driver definition always lives in local config, so a committed `.gitattributes`
would only carry half the setup and imply the other half was present.

To rebuild it in a new clone:

```bash
STATES="state.json crossings_state.json dilution_state.json ftd_state.json \
letters_state.json regsho_state.json shortinterest_state.json \
spike_state.json threshold_state.json snapshot.json"

for f in $STATES; do echo "/$f merge=stateremote"; done > .git/info/attributes

git config merge.stateremote.name "bot-written state files: remote wins"
git config merge.stateremote.driver "sh '$PWD/.git/state-merge.sh' %O %A %B"
git config merge.stateremote.recursive binary
git config pull.rebase true
git config rebase.autoStash true
```

Then recreate `.git/state-merge.sh` and `.git/hooks/pre-commit`, and
`chmod +x` both.

## If a state file conflict happens anyway

Which flag you need depends on the operation, and `--ours`/`--theirs` invert the
same way the merge driver does. This form is unambiguous in both:

```bash
git fetch origin
git checkout origin/main -- <file>
git add <file>
```

Then `git rebase --continue`, or `git merge --continue`.

If the pre-commit hook blocks a commit, a state file has been modified locally.
Discard it rather than reaching for `--no-verify`:

```bash
git checkout -- <file>
```

## Known quirks

- **Identity is set per-repo**, in `.git/config`, with the same values as a
  global fallback. Commits use `96786524+NTRS-ZIB@users.noreply.github.com`;
  the numeric prefix is what makes GitHub attribute them to the account.
- **`.claude/` is excluded locally**, via `.git/info/exclude` rather than
  `.gitignore`, so tooling artefacts stay out of the repo without committing a
  rule about them.
- **The clone lives under a OneDrive-synced path.** OneDrive syncing `.git`
  can occasionally produce lock or corruption errors during git operations. It
  has not so far, but an unexplained git error is worth checking against this
  first.
- **`workflow_dispatch` only registers on the default branch.** A workflow
  committed to a branch cannot be triggered: `gh workflow run` returns *could
  not find any workflows named*, and the workflow does not appear in the
  registry at all.

  The consequence is a real asymmetry. **The branch-then-dry-run pattern that
  works for components does not work for workflows.** A component change can be
  pushed to a branch and exercised with `gh workflow run --ref <branch>`,
  because the workflow already exists on `main`. A *new* workflow, or a new tool
  plus its workflow, is unverifiable in Actions until it is merged — so verify
  the script locally, merge, then dispatch to close the gap. `calibrate.yml` was
  handled that way; every probe before it went straight to `main`, which is why
  this had not surfaced.
- **Never round-trip a file through PowerShell `Get-Content`/`Set-Content`.**
  `Set-Content -Encoding utf8` re-encodes content that was read as ANSI, which
  on this repo means a UTF-8 BOM prepended and every em-dash mangled. It
  happened once to `docs/press-monitor.md`: **67 lines corrupted** and the diff
  inflated to 191 lines, from what was meant to be a two-line edit. Nothing
  errors, and the damage is invisible in a terminal that renders the mojibake
  back.

  Use an editor that preserves encoding. To check a file after any bulk
  rewrite:

  ```bash
  head -c 3 docs/press-monitor.md | od -An -tx1        # ef bb bf means a BOM
  grep -c $'\xc3\xa2\xe2\x82\xac' docs/press-monitor.md   # non-zero = mojibake
  ```

  The second command searches for the bytes an em-dash becomes when UTF-8 is
  decoded as cp1252 and re-encoded. **The pattern is written as byte escapes
  deliberately**, so this file does not contain the sequence it searches for —
  the literal form matched itself here and returned a hit on a clean file,
  which is exactly the ambiguity the check exists to remove.

  Both commands were verified against a genuinely corrupted copy, reproduced by
  replaying the same transformation: 84 lines flagged and `ef bb bf` present on
  the damaged file, zero and absent on every clean one. A more general
  search for the Unicode replacement character (U+FFFD) was tried and
  **rejected**: it found nothing on the same damaged file, because a cp1252
  decode mostly succeeds into wrong-but-valid characters rather than failing.
- **`watchlist.py` has no workflow.** It is the shared roster imported by the
  others, not a scheduled job, which is why there are fifteen workflows for
  sixteen root scripts.
- **Running the scripts locally does not work** and should not be attempted.
  They read secrets that exist only in GitHub Actions, and several post to live
  Discord channels.
