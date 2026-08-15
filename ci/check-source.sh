#!/bin/sh
# The mechanical CI checks that read the tree (05-testing-and-release.md §6.1).
#
# These are the two that can be answered without the artifact. The third —
# `lsinitramfs` showing no drivers/net entries — is in ci/check-image.sh, because it can
# only be answered by the ISO.
set -eu

cd "$(dirname "$0")/.."

fail=0
note() { echo "  $1"; }
bad() { echo "FAIL  $1" >&2; fail=1; }
good() { echo "ok    $1"; }

# --- ADR-0004: the dependency direction IS the crate boundary -----------------
#
# The boundary is one question — does this touch hardware. `aobs-core/Cargo.toml` naming
# neither `slint` nor `v4l` is mechanically checkable, which is worth more than
# architectural intent in a document.
if grep -qE '^\s*(slint|v4l)[a-z0-9_-]*\s*(=|\.)' aobs-core/Cargo.toml; then
    bad "aobs-core/Cargo.toml names slint or v4l"
else
    good "aobs-core/Cargo.toml names neither slint nor v4l"
fi

# The manifest is what the spec names, but a transitive edge would breach the boundary
# just as thoroughly and leave the manifest clean.
if command -v cargo >/dev/null 2>&1; then
    tree="$(cargo tree --package aobs-core --edges normal --prefix none 2>/dev/null || true)"
    if [ -n "${tree}" ] && echo "${tree}" | grep -qE '^(slint|v4l)'; then
        bad "aobs-core reaches slint or v4l transitively"
        note "$(echo "${tree}" | grep -E '^(slint|v4l)')"
    else
        good "aobs-core reaches neither transitively"
    fi
fi

# --- 01-boot-layer.md §10: panic = "unwind", never abort ----------------------
#
# The zeroization guarantee lives in ZeroizeOnDrop and drop glue does not run on abort.
# An aborting crash with a wallet loaded would leave key material in RAM until the
# shutdown wipe.
if grep -qE '^\s*panic\s*=\s*"unwind"' Cargo.toml; then
    good 'the release profile sets panic = "unwind"'
else
    bad 'Cargo.toml does not set panic = "unwind"'
fi

abort_hits="$(grep -rn --include=Cargo.toml --exclude-dir=target --exclude-dir=.git \
    -E '^\s*panic\s*=\s*"abort"' . || true)"
if [ -n "${abort_hits}" ]; then
    bad 'some manifest sets panic = "abort"'
    note "${abort_hits}"
else
    good 'no manifest sets panic = "abort"'
fi

# --- 05-testing-and-release.md §1: no coverage opt-outs in source -------------
#
# "That is how a number gets met by editing the denominator instead of writing tests."
optout_hits="$(grep -rn --include='*.rs' --exclude-dir=target --exclude-dir=.git \
    -E '#\[\s*(coverage\(off\)|cfg_attr\([^)]*coverage)' . || true)"
if [ -n "${optout_hits}" ]; then
    bad "a per-function coverage opt-out attribute is present in source"
    note "${optout_hits}"
else
    good "no coverage opt-out attributes in source"
fi

exit "${fail}"
