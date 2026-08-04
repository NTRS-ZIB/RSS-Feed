#!/bin/sh
# Merge driver for bot-written state files: the REMOTE version always wins.
#
# Git calls this as:  state-merge.sh %O %A %B
#   $1 = %O  common ancestor
#   $2 = %A  "ours"   -- the side currently checked out
#   $3 = %B  "theirs" -- the side being merged in
# The result must be left in $2 ($A) and the script must exit 0.
#
# Which physical side is "remote" INVERTS between merge and rebase:
#   merge  : HEAD is the local branch      -> remote is %B  -> copy %B over %A
#   rebase : HEAD is the replayed upstream -> remote is %A  -> keep %A as-is
# So detect the operation instead of assuming one.

gitdir=$(git rev-parse --git-dir 2>/dev/null) || exit 1

if [ -d "$gitdir/rebase-merge" ] || [ -d "$gitdir/rebase-apply" ]; then
    : # rebase in progress: %A is already the remote side. Keep it.
else
    cat "$3" > "$2" # merge (or cherry-pick): remote is %B. Overwrite %A with it.
fi

exit 0
