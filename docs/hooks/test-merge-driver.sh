#!/bin/sh
# Sandbox proof that the state-file merge driver makes the REMOTE version win
# under BOTH `git pull` (merge) and `git pull --rebase`.
# Runs entirely in a temp dir. Touches nothing in the real repo.

set -e
SB="$1"                       # sandbox dir
DRIVER="$2"                   # path to state-merge.sh
rm -rf "$SB"; mkdir -p "$SB"; cd "$SB"

id() { git -C "$1" config user.name test; git -C "$1" config user.email test@example.com; \
       git -C "$1" config core.autocrlf false; }

# --- a fake origin, a "bot" clone that writes state, and our working clone ---
git init -q --bare origin.git
git clone -q origin.git seed; id seed
printf 'BASE\n' > seed/state.json
printf 'real source\n' > seed/README.md
git -C seed add -A; git -C seed commit -qm "base"; git -C seed push -q origin HEAD:main

git clone -q -b main origin.git bot;  id bot
git clone -q -b main origin.git work; id work

# --- install the strategy in the working clone (local config, nothing committed) ---
printf 'state.json merge=stateremote\n' > work/.git/info/attributes
git -C work config merge.stateremote.name "remote wins for bot-written state files"
git -C work config merge.stateremote.driver "sh '$DRIVER' %O %A %B"
git -C work config merge.stateremote.recursive binary

check() { # check <label> <expected>
  got=$(cat work/state.json)
  if [ "$got" = "$2" ]; then echo "  PASS  $1: state.json = '$got'"
  else echo "  FAIL  $1: state.json = '$got' (expected '$2')"; FAILED=1; fi
  if git -C work grep -q '<<<<<<<' -- state.json 2>/dev/null; then
    echo "  FAIL  $1: conflict markers present"; FAILED=1; fi
  if [ -n "$(git -C work ls-files -u)" ]; then
    echo "  FAIL  $1: left in a conflicted/unmerged state"; FAILED=1; fi
  if [ -e work/.git/MERGE_HEAD ] || [ -d work/.git/rebase-merge ] || [ -d work/.git/rebase-apply ]; then
    echo "  FAIL  $1: pull did not complete (merge/rebase still in progress)"; FAILED=1; fi
}

scenario() { # scenario <label> <pull-flag> <unique-remote-value>
  echo ""; echo "== $1 =="
  # reset the working clone to origin, clean
  git -C work fetch -q origin
  git -C work reset -q --hard origin/main
  # bot writes a new state file remotely
  git -C bot fetch -q origin && git -C bot reset -q --hard origin/main
  printf '%s\n' "$3" > bot/state.json
  git -C bot commit -qam "bot: update state [skip ci]"; git -C bot push -q origin main
  # meanwhile WE make a conflicting local edit to the same file, and a real edit elsewhere
  printf 'STALE-LOCAL-VALUE\n' > work/state.json
  printf 'my real work\n' >> work/README.md
  git -C work commit -qam "local: edit state + README"
  echo "  before pull: local state.json = $(cat work/state.json)   remote = $3"
  git -C work pull -q $2 origin main
  check "$1" "$3"
  # the genuine local edit must have SURVIVED
  if grep -q 'my real work' work/README.md; then echo "  PASS  $1: real local edit to README survived"
  else echo "  FAIL  $1: real local edit was lost"; FAILED=1; fi
  git -C work push -q origin main
  echo "  after push: origin state.json = $(git -C origin.git show main:state.json)"
}

FAILED=0
scenario "git pull --no-rebase  (merge)"  "--no-rebase" "REMOTE-BOT-VALUE-1"
scenario "git pull --rebase     (rebase)" "--rebase"    "REMOTE-BOT-VALUE-2"

echo ""
if [ "$FAILED" = "1" ]; then echo "RESULT: FAILURES ABOVE"; exit 1; else echo "RESULT: ALL CHECKS PASSED"; fi
