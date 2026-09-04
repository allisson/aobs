#!/bin/sh
#
# The four refusals a human passes without noticing. Runs them, exits non-zero, and does nothing
# else.
#
#     SOURCE_DATE_EPOCH=$(git log -1 --format=%ct) ./build/release-preflight.sh
#     ./build/release-preflight.sh path/to/etc-aobs-release
#     ./build/release-preflight.sh path/to/etc-aobs-release manifest-v0.1.0.txt
#
# **Run it twice, and the second run is the one that matters.** Before the build there is no
# `/etc/aobs-release` and no manifest, so the first form checks the tree and the tag and takes
# `SOURCE_DATE_EPOCH` from the environment — which catches a hand-set value in *that shell* and
# nothing more, because `build/mkiso.sh` derives its own and ignores the environment. Given the file
# the build wrote, refusal 3 judges the epoch the build **actually used**, which is the version of the
# check that would catch a future edit letting the build honour an inherited variable. Given the
# manifest as well, all four bite.
#
# `docs/release.md` holds the ordered checklist. **The split between that document and this script is
# deliberate and specific: the script enforces what a human cannot reliably check, the prose holds
# what a human must actually look at.** Signing, publishing and the post-publish stranger's-eye
# verification stay manual with the commands written out, because those are precisely the steps where
# a human's attention *is* the control, and a script that performs them hides the thing being checked.
#
# The four:
#
#   1. a dirty working tree
#   2. HEAD not at a signed annotated tag matching `vMAJOR.MINOR[.PATCH]`
#   3. the epoch the build ran under not equal to the tagged commit's date — a mismatch means it was
#      set by hand rather than derived
#   4. a manifest whose `git-commit` is not HEAD (only when a manifest is named)
#
# Each one fails only when something is genuinely wrong. That is the design constraint: a guard that
# fires during ordinary work gets disabled, and then it guards nothing on the day it mattered. A
# development build trips none of them, because a development build never runs this.
#
# Already hard stops elsewhere and unchanged: the input-set equality and the rootfs assertions in
# `build/mkiso.sh` stage 0 and 1, and the embedded-version check in stage 3.
#
# **The judgement is not here.** Every one of the four is a pure function in `build/verify.py`, fed a
# `GitFacts` value object gathered by `build/gather.py`, so `tests/test_build_verifier.py` drives each
# refusal with a hostile input in milliseconds — instead of cutting a release to find out whether a
# shell condition still bites.

set -eu

SRC=${SRC:-$(git rev-parse --show-toplevel)}

exec python3 "$SRC/build/gather.py" release-preflight "$SRC" "$@"
