#!/bin/sh
#
# The four refusals a human passes without noticing. Runs them, exits non-zero, and does nothing
# else.
#
#     SOURCE_DATE_EPOCH=$(git log -1 --format=%ct) ./build/release-preflight.sh
#     SOURCE_DATE_EPOCH=$(git log -1 --format=%ct) ./build/release-preflight.sh manifest-v1.0.txt
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
#   2. HEAD not at a signed annotated tag matching `vMAJOR.MINOR`
#   3. `SOURCE_DATE_EPOCH` not equal to the tagged commit's date — a mismatch means it was set by hand
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
