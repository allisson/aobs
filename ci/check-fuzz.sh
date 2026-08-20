#!/bin/sh
# The fuzz gate (05-testing-and-release.md §4).
#
# §4 names three targets we write ourselves and all three now exist — the PSBT parser on
# raw bytes and the validator (#79, #80), and the fountain decoder through our clamping
# wrapper (#77). The gate was wired before any of them, on a placeholder, so that the first
# real target was a file and not a toolchain investigation — and that is why this runs every
# target `cargo fuzz list` reports rather than a name written here: adding a target must not
# also mean editing this script.
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

# §4 asks the PSBT target for *no unbounded allocation*, which is a limit libFuzzer enforces
# rather than an assertion we write: `-malloc_limit_mb` aborts on a single allocation above
# the bound. 64 MiB against a 64 KiB input is three orders of magnitude of headroom over the
# dependency's own 4 MB per-vector cap, so anything tripping it is the finding.
#
# `-max_len` is the transport bound itself (03-transport.md §2): fuzzing above it would spend
# the budget on inputs the QR channel cannot deliver.
: "${AOBS_FUZZ_MAX_LEN:=65536}"
: "${AOBS_FUZZ_MALLOC_LIMIT_MB:=64}"

echo "== cargo fuzz list"
targets="$(cargo "+${AOBS_FUZZ_TOOLCHAIN}" fuzz list)"
echo "${targets}"
if [ -z "${targets}" ]; then
    echo "FAIL  no fuzz targets at all" >&2
    exit 1
fi

echo "== cargo fuzz build"
cargo "+${AOBS_FUZZ_TOOLCHAIN}" fuzz build

for target in ${targets}; do
    echo "== cargo fuzz run ${target} -runs=${AOBS_FUZZ_RUNS}"
    cargo "+${AOBS_FUZZ_TOOLCHAIN}" fuzz run "${target}" -- \
        "-runs=${AOBS_FUZZ_RUNS}" \
        "-max_len=${AOBS_FUZZ_MAX_LEN}" \
        "-malloc_limit_mb=${AOBS_FUZZ_MALLOC_LIMIT_MB}"
done

echo "ok    every fuzz target builds and runs end to end"
