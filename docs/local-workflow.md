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

**The scripts themselves are committed**, in [`docs/hooks/`](hooks/):

| file | goes to | what it is |
|---|---|---|
| `state-merge.sh` | `.git/state-merge.sh` | the merge driver |
| `pre-commit` | `.git/hooks/pre-commit` | the hook |
| `test-merge-driver.sh` | run from anywhere | the sandbox proof, below |

**Those are reference copies, not the live files.** Editing
`docs/hooks/pre-commit` changes nothing — git only reads `.git/hooks/pre-commit`.
Change the live one, then copy it back here so the two do not drift.

Rebuild in a new clone, start to finish:

```bash
# 1. put the scripts in place and make them executable
cp docs/hooks/state-merge.sh .git/state-merge.sh
cp docs/hooks/pre-commit     .git/hooks/pre-commit
chmod +x .git/state-merge.sh .git/hooks/pre-commit

# 2. tell git which files the driver applies to
STATES="state.json crossings_state.json dilution_state.json ftd_state.json \
letters_state.json regsho_state.json shortinterest_state.json \
spike_state.json threshold_state.json snapshot.json"

for f in $STATES; do echo "/$f merge=stateremote"; done > .git/info/attributes

# 3. register the driver and the pull behaviour it assumes
git config merge.stateremote.name "bot-written state files: remote wins"
git config merge.stateremote.driver "sh '$PWD/.git/state-merge.sh' %O %A %B"
git config merge.stateremote.recursive binary
git config pull.rebase true
git config rebase.autoStash true
```

Verify it took:

```bash
git check-attr merge -- state.json        # -> state.json: merge: stateremote
ls -l .git/hooks/pre-commit               # -> executable
```

### Re-running the proof

`docs/hooks/test-merge-driver.sh` is the experiment the design rests on. It
builds a throwaway origin, a "bot" clone and a working clone in a temp
directory, has the bot and the working copy edit the same state file, and
checks that the remote value survives under **both** `git pull` and
`git pull --rebase` while an unrelated local edit is preserved. It touches
nothing in the real repo.

```bash
sh docs/hooks/test-merge-driver.sh /tmp/merge-sandbox "$PWD/.git/state-merge.sh"
```

Expect `RESULT: ALL CHECKS PASSED`. It is committed because
[the evidence above](#critical-mergeours-means-the-opposite-of-what-it-looks-like)
cites its result — that the naive `merge=ours` configuration fails the merge
case — and a cited experiment nobody can rerun is worth no more than an
assertion.

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
- **`.claude/` and `__pycache__/` are excluded twice, deliberately.** A
  committed `.gitignore` carries them, and `.git/info/exclude` still lists them
  too. The duplication is intentional: `.git/info/exclude` is local only and
  shares the re-clone weakness of the merge driver and the pre-commit hook, but
  unlike those two the cost of losing it is immediate rather than latent — the
  first `git add .` in a fresh clone would commit a bytecode cache.
  `watchlist.py` is the one script this repo tells you to run locally, and every
  run creates `__pycache__/`. Belt and braces costs nothing here.
- **A script that fails partway can leave the commit looking complete.** A
  two-part split — write the reduced file, commit, restore the rest, commit
  again — errored on the first write and never reached the truncation, so the
  commit took *both* parts under the first message. **The exit code was
  non-zero and the work was still half-done in the safe direction**, which is
  luck rather than design: the same failure one line later would have
  committed a truncated file.

  What made it a non-event was checking **what the commit contained** rather
  than that the command exited:

  ```bash
  git show HEAD:docs/rejected.md | grep -c "the section that should not be here"
  ```

  Caught before the push, so a `reset --soft` fixed it. Verify content, not
  exit status, whenever a commit is assembled by a script.

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
- **Never name a scratch file after a DOS device.** `prn`, `con`, `aux`, `nul`,
  `com1`–`com9` and `lpt1`–`lpt9` are reserved on Windows *with any extension*,
  so `prn.txt` is reserved too. Such a file can be created, and then
  `Get-ChildItem` lists it while `Remove-Item` reports it does not exist —
  ordinary path APIs cannot address it. Removing one needs an extended-length
  path:

  ```powershell
  [System.IO.File]::Delete("\\?\$path\prn.txt")
  ```

  The practical version is simply not to name a file that way. It happened here
  by abbreviating "PR Newswire" to `prn.txt`.
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
