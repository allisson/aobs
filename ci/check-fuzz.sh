#!/bin/sh
# The fuzz gate (05-testing-and-release.md §4).
#
# §4 names three targets we write ourselves and none of the code they fuzz exists yet, so
# what this proves today is the harness: cargo-fuzz builds inside the one build
# environment, links libFuzzer, and runs a target to completion. Wiring it now means the
# first real target is a file and not a toolchain investigation.
#
# A separate gate from the test run and from coverage, because §1 says coverage is
# necessary and not sufficient: the fuzz targets are not a subset of the coverage run.
set -eu

cd "$(dirname "$0")/.."

# The one unpinned toolchain in this repo, and it is unpinned for a reason that is not
# laziness: cargo-fuzz's sanitizer and its default `-Zbuild-std` are nightly-only, and a
# dated nightly pinned here would go stale silently between releases. Pin it by setting
# AOBS_FUZZ_TOOLCHAIN to a dated nightly when a nightly regression bites.
: "${AOBS_FUZZ_TOOLCHAIN:=nightly}"

# 20 000 runs is a wiring proof, not a fuzzing campaign — long enough for libFuzzer to
# mutate, mmap the corpus dir and exit 0, short enough to sit in a CI job. A real campaign
# is `-max_total_time`, run by hand against a real target.
: "${AOBS_FUZZ_RUNS:=20000}"

echo "== cargo fuzz list"
cargo "+${AOBS_FUZZ_TOOLCHAIN}" fuzz list

echo "== cargo fuzz build"
cargo "+${AOBS_FUZZ_TOOLCHAIN}" fuzz build

echo "== cargo fuzz run placeholder -runs=${AOBS_FUZZ_RUNS}"
cargo "+${AOBS_FUZZ_TOOLCHAIN}" fuzz run placeholder -- "-runs=${AOBS_FUZZ_RUNS}"

echo "ok    the fuzz harness builds and runs end to end"
