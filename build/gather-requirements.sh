#!/bin/sh
# Regenerate build/requirements.appliance.txt and build/requirements.test.txt from uv.lock.
#
# These are what `pip` can actually consume — `name==version` plus every artifact hash — and they
# are checked in because the image build and the test tier both need them without `uv` present.
# They are DERIVED: uv.lock is the source, and nothing here may be hand-edited.
#
# That is a second copy of the hashes, which docs/adr/0002 objects to on principle. The objection
# is answered by a mechanism rather than by care: `--check` regenerates both files and fails if
# either differs from what is committed, and CI runs it on every push. A copy a machine compares
# is not the failure mode that ADR describes; a copy a human is asked to remember is.
#
# usage: sh build/gather-requirements.sh            # rewrite both files
#        sh build/gather-requirements.sh --check    # fail if either is stale

set -eu
cd "$(dirname "$0")/.."

command -v uv >/dev/null || { echo "uv is required" >&2; exit 1; }

APPLIANCE=build/requirements.appliance.txt
TEST=build/requirements.test.txt

gen() {
    # $1 output path; remaining args passed to uv export
    out=$1
    shift
    uv export --frozen --no-emit-project --no-annotate --no-header "$@" > "$out"
}

if [ "${1:-}" = "--check" ]; then
    WORK=$(mktemp -d)
    trap 'rm -rf "$WORK"' EXIT
    gen "$WORK/appliance"
    gen "$WORK/test" --extra test
    status=0
    for pair in "$APPLIANCE:$WORK/appliance" "$TEST:$WORK/test"; do
        committed=${pair%%:*}
        fresh=${pair#*:}
        if ! diff -u "$committed" "$fresh" >/dev/null 2>&1; then
            echo "STALE: $committed does not match uv.lock" >&2
            diff -u "$committed" "$fresh" >&2 || true
            status=1
        fi
    done
    [ "$status" -eq 0 ] && echo "both requirement files match uv.lock"
    exit "$status"
fi

gen "$APPLIANCE"
gen "$TEST" --extra test
echo "wrote $APPLIANCE and $TEST"
