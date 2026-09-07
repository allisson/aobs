#!/bin/sh
# Regenerate the version half of build/wheel-versions.txt from pyproject.toml + uv.lock.
# Prints the two groups as `name==version` lines to stdout and touches nothing: the pins
# land in a commit a person read, never in a build step.
#
# It deliberately does NOT emit hashes. uv.lock already holds a sha256 for every artifact
# and build/fetch-inputs.sh reads them from there; a second copy would be a second place
# for one fact with nothing keeping the two equal.
#
# usage: sh build/gather-wheel-versions.sh

set -eu
cd "$(dirname "$0")/.."

command -v uv >/dev/null || { echo "uv is required" >&2; exit 1; }

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

pins() {
    # $@: extra uv export arguments
    uv export --frozen --no-emit-project --no-annotate --no-header "$@" \
        | grep -oE '^[a-z0-9._-]+==[^ ]+' | sort
}

pins            > "$WORK/appliance"
pins --extra test > "$WORK/both"

echo "# @group appliance"
cat "$WORK/appliance"

echo
echo "# @group harness"
# Set difference on the whole `name==version` token, so a package present in both groups
# is listed once — on the appliance side, which is the side that governs whether it may
# reach the rootfs. Comparing whole tokens rather than bare names also means a version
# that differs between the two exports shows up here instead of being silently dropped.
comm -13 "$WORK/appliance" "$WORK/both"
