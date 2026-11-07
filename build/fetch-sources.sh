#!/bin/sh
# THE SOURCE ARCHIVE'S FETCH: the corresponding source for every binary in the input archive.
#
#     sh build/fetch-sources.sh              # populate build/sources/, verify against sources.sha256
#     sh build/fetch-sources.sh --refresh    # populate, then REWRITE sources.sha256 (pin change)
#
# An accompaniment, not an input: no build reads a byte of it (`CONTEXT.md`, *Source archive*). It
# exists because the input archive is published, and publishing a binary is what obliges the source.
# `docs/roadmap.md` M4 holds the three decisions this script implements:
#
#   - Debian: the source package of EVERY `.deb` under `build/inputs/deb/`, no licence filter, at the
#     exact version that built it. The set is `Source:` PLUS `Built-Using:`. The shipped kernel's
#     `Source:` is `linux-signed-amd64`, the signing template; the GPL source it was compiled from
#     is `linux`, named only in `Built-Using:`. `Source:` alone would ship an archive missing the
#     source that matters most.
#   - Python: each wheel's sdist from PyPI, checked against the sha256 PyPI publishes for it.
#   - The same `--refresh` discipline as `build/fetch-inputs.sh`, and the same pinned instant.
#
# It reads `build/inputs/` to know what to fetch, so that pool must be fetched and verified first.

set -eu
cd "$(dirname "$0")/.."

REFRESH=0
[ "${1:-}" = "--refresh" ] && REFRESH=1

command -v docker >/dev/null || { echo "docker is required" >&2; exit 1; }
sha256sum -c --quiet build/inputs.sha256 || {
    echo "fetch-sources: build/inputs does not match build/inputs.sha256; fetch the inputs first" >&2
    exit 1
}

SOURCES=build/sources
HASHES=build/sources.sha256
. ./build/snapshot.env
# The image `build/fetch-inputs.sh` resolves in, for the same reasons.
BASE_IMAGE=debian:trixie-20260824-slim@sha256:d7e12182ce18b85b93007c1dedf31f2d29e01ccf3182cc4017c709b6259bc132

# Deleted first on every run, for the reason `build/fetch-inputs.sh` gives at length: the gate is
# set equality, and a leftover file would be hashed as if it had been fetched.
rm -rf "$SOURCES"
mkdir -p "$SOURCES/deb" "$SOURCES/pypi"

# --- Debian -------------------------------------------------------------------------------------

echo "==> source packages behind build/inputs/deb (source: snapshot @ $DEBIAN_SNAPSHOT)"
docker run --rm --platform=linux/amd64 \
    -e DEBIAN_SNAPSHOT="$DEBIAN_SNAPSHOT" -e DEBIAN_SUITE="$DEBIAN_SUITE" \
    -v "$PWD/build/inputs/deb:/debs:ro" \
    -v "$PWD/$SOURCES/deb:/out" \
    "$BASE_IMAGE" sh -euc '
        # One "name=version" per line: `Source:` (its own version when it carries one, else the
        # binary version) and every `Built-Using:` entry, which always carries `(= version)`.
        for deb in /debs/*/*.deb; do
            pkg=$(dpkg-deb -f "$deb" Package)
            ver=$(dpkg-deb -f "$deb" Version)
            src=$(dpkg-deb -f "$deb" Source)
            [ -n "$src" ] || src=$pkg
            case "$src" in
                *"("*) echo "$src" | sed "s/^\([^ ]*\) (\(.*\))$/\1=\2/" ;;
                *) echo "$src=$ver" ;;
            esac
            dpkg-deb -f "$deb" Built-Using | tr "," "\n" \
                | sed -n "s/^ *\([^ ]*\) (= \(.*\)).*$/\1=\2/p"
        done | LC_ALL=C sort -u > /tmp/wanted
        echo "    $(wc -l < /tmp/wanted) source packages"

        printf "deb-src [check-valid-until=no] http://snapshot.debian.org/archive/debian/%s/ %s main\n" \
            "$DEBIAN_SNAPSHOT" "$DEBIAN_SUITE" > /etc/apt/sources.list.d/pinned.list
        printf "deb-src [check-valid-until=no] http://snapshot.debian.org/archive/debian-security/%s/ %s-security main\n" \
            "$DEBIAN_SNAPSHOT" "$DEBIAN_SUITE" >> /etc/apt/sources.list.d/pinned.list
        printf "Acquire::Retries \"8\";\nAcquire::http::Timeout \"60\";\n" > /etc/apt/apt.conf.d/99retries
        rm -f /etc/apt/sources.list /etc/apt/sources.list.d/debian.sources
        apt-get update -qq

        # `--only-source` so a name is read as a source package, never as a binary that happens to
        # share it. `--download-only`: the .dsc and its tarballs, nothing unpacked, no dpkg-source.
        cd /out
        while read -r want; do
            apt-get source -qq --download-only --only-source "$want" >/dev/null
        done < /tmp/wanted
        cp /tmp/wanted /out/.wanted
        echo "    $(ls -1 *.dsc | wc -l) .dsc files"
    '
# The list is the requirement `build/verify.py` judges the pool against; it is derived again in CI
# from the same `.deb`s, so it is not kept beside the files it describes.
rm -f "$SOURCES/deb/.wanted"

# --- PyPI ---------------------------------------------------------------------------------------

echo "==> sdists behind build/inputs/wheels (source: PyPI)"
python3 -I - "$SOURCES/pypi" build/inputs/wheels/*/*.whl <<'EOF'
import hashlib, json, sys, urllib.request
from pathlib import Path

out = Path(sys.argv[1])
wanted = sorted({tuple(Path(w).name.split("-")[:2]) for w in sys.argv[2:]})
for name, version in wanted:
    with urllib.request.urlopen(f"https://pypi.org/pypi/{name}/{version}/json", timeout=60) as r:
        files = json.load(r)["urls"]
    sdists = [f for f in files if f["packagetype"] == "sdist"]
    if len(sdists) != 1:
        sys.exit(f"fetch-sources: {name} {version} has {len(sdists)} sdists on PyPI, not one")
    sdist = sdists[0]
    with urllib.request.urlopen(sdist["url"], timeout=300) as r:
        body = r.read()
    if hashlib.sha256(body).hexdigest() != sdist["digests"]["sha256"]:
        sys.exit(f"fetch-sources: {sdist['filename']} does not match the sha256 PyPI publishes")
    (out / sdist["filename"]).write_bytes(body)
print(f"    {len(wanted)} sdists")
EOF

# --- The gate -----------------------------------------------------------------------------------
#
# As `build/fetch-inputs.sh`: hash and set equality, and `--refresh` is the only path that writes.
manifest() {
    find "$SOURCES" -type f | LC_ALL=C sort | while read -r f; do
        printf '%s  %s\n' "$(sha256sum "$f" | cut -d' ' -f1)" "$f"
    done
}

if [ "$REFRESH" -eq 1 ]; then
    manifest > "$HASHES"
    echo "==> rewrote $HASHES ($(wc -l < "$HASHES" | tr -d ' ') files, $(du -sh "$SOURCES" | cut -f1))"
    echo "    review this diff: it is the complete list of source the release publishes."
    exit 0
fi

[ -f "$HASHES" ] || { echo "$HASHES does not exist. Run with --refresh, then review the diff." >&2; exit 1; }
if manifest | diff -u "$HASHES" - >&2; then
    echo "==> build/sources/ matches $HASHES ($(wc -l < "$HASHES" | tr -d ' ') files)"
else
    echo "==> build/sources/ DOES NOT match $HASHES" >&2
    exit 1
fi
