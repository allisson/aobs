#!/bin/sh
# The input archive: every file `build/inputs.sha256` names, as one uncompressed tar.
#
#     sh build/pack-inputs.sh            # writes out/aobs-inputs-<sha256>.tar and prints its digest
#     sh build/pack-inputs.sh sources    # the source archive: build/sources.sha256, aobs-sources-*.tar
#     tar -xf aobs-inputs-<sha256>.tar   # at the repository root: the way back
#
# The archive is what keeps a release rebuildable after snapshot.debian.org and PyPI stop serving
# these bytes (`docs/roadmap.md` M4). Two packings of the same pinned set must be the same bytes,
# so nothing about the packing host reaches the tar: the member list and its order come from
# `build/inputs.sha256`, there are files and no directory entries, and owner, group, mtime and mode
# are fixed. Uncompressed, because every member is already a compressed `.deb` or `.whl`.
# CI packs it twice under varied conditions and fails on a differing byte.
#
# Nothing is fetched here; `build/fetch-inputs.sh` is the networked step. Unpacking needs no script:
# after `tar -xf`, `build/mkiso.sh`'s stage 0 judges the result exactly as it judges a fetch.

set -eu
cd "$(dirname "$0")/.."

# `inputs` or `sources`: the same packing, so the two published archives cannot differ in how.
WHAT=${1:-inputs}
case "$WHAT" in inputs|sources) ;; *) echo "pack-inputs: inputs or sources, not $WHAT" >&2; exit 1 ;; esac

# GNU tar: the flags below are its. macOS's tar is bsdtar and has none of them.
TAR=tar
command -v gtar >/dev/null 2>&1 && TAR=gtar
"$TAR" --version 2>/dev/null | grep -q 'GNU tar' || {
    echo "pack-inputs: needs GNU tar (on macOS: brew install gnu-tar)" >&2
    exit 1
}

# The same judgment stage 0 makes, so a pool that would fail the build is never packed.
sha256sum -c --quiet "build/$WHAT.sha256"
named=$(wc -l < "build/$WHAT.sha256")
present=$(find "build/$WHAT" -type f | wc -l)
[ "$named" -eq "$present" ] || {
    echo "pack-inputs: build/$WHAT has $present files and build/$WHAT.sha256 names $named." >&2
    exit 1
}

mkdir -p out
list=$(mktemp)
trap 'rm -f "$list" "out/aobs-$WHAT.tar.partial"' EXIT INT TERM
cut -d' ' -f3- "build/$WHAT.sha256" > "$list"

LC_ALL=C TZ=UTC "$TAR" --create --file="out/aobs-$WHAT.tar.partial" \
    --format=gnu --no-recursion --verbatim-files-from --files-from="$list" \
    --owner=0 --group=0 --numeric-owner --mtime=@0 --mode='a=r,u+w'

digest=$(sha256sum "out/aobs-$WHAT.tar.partial" | cut -d' ' -f1)
rm -f "out/aobs-$WHAT"-*.tar
mv "out/aobs-$WHAT.tar.partial" "out/aobs-$WHAT-$digest.tar"
echo "out/aobs-$WHAT-$digest.tar"
echo "sha256: $digest"
