#!/bin/sh
# Read the exact version of every named package from the pinned snapshot's Packages
# index, so build/apt-versions.txt is derived rather than typed. Networked, and not part
# of the build: it regenerates a checked-in file, which a human then reviews in a diff.
#
# It prints `name=version` lines to stdout and touches nothing. Editing
# build/apt-versions.txt is a release-affecting change — every version below feeds the
# ISO hash — so the pins land in a commit a person read, never in a build step.
#
# Both suites are consulted and the HIGHER version wins, which is what apt itself would
# do: at 20260901T000000Z, linux-image-amd64 is 6.12.94-1 in main and 6.12.107-1 in
# trixie-security, and the appliance must get the second one.
#
# usage: sh build/gather-apt-versions.sh [package ...]
#        sh build/gather-apt-versions.sh          # re-reads the names already pinned

set -eu

# `dpkg` is not optional and the fallback is not "compare as strings": at this snapshot
# that fallback picks linux-image-amd64 6.12.94-1 over 6.12.107-1, because "9" sorts
# after "1", and ships an appliance kernel thirteen point releases behind. Refuse instead.
command -v dpkg >/dev/null || {
    echo "dpkg is required to compare Debian versions correctly; run this in the container" >&2
    exit 1
}

cd "$(dirname "$0")/.."
. ./build/snapshot.env

if [ $# -gt 0 ]; then
    NAMES="$*"
else
    # The names currently pinned, both groups, comments and blank lines dropped.
    NAMES=$(sed -e 's/#.*//' -e '/^[[:space:]]*$/d' build/apt-versions.txt | cut -d= -f1)
fi

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

fetch() {
    # $1 archive (debian|debian-security), $2 dist
    url="https://snapshot.debian.org/archive/$1/${DEBIAN_SNAPSHOT}/dists/$2/main/binary-${DEBIAN_ARCH}/Packages.xz"
    curl -sSLf "$url" -o "$WORK/$1.xz" || { echo "cannot fetch $url" >&2; exit 1; }
    xz -dc "$WORK/$1.xz"
}

fetch debian "${DEBIAN_SUITE}" > "$WORK/index"
fetch debian-security "${DEBIAN_SUITE}-security" >> "$WORK/index"

NAMES="$NAMES" python3 - "$WORK/index" <<'PY'
import os, sys, subprocess

names = set(os.environ["NAMES"].split())
best = {}
pkg = ver = None
for line in open(sys.argv[1], errors="replace"):
    line = line.rstrip("\n")
    if line.startswith("Package: "):
        pkg = line[9:]
    elif line.startswith("Version: "):
        ver = line[9:]
    elif line == "":
        if pkg in names and ver is not None:
            prev = best.get(pkg)
            # dpkg is the only correct comparator for Debian version strings.
            if prev is None or subprocess.run(
                ["dpkg", "--compare-versions", ver, "gt", prev]
            ).returncode == 0:
                best[pkg] = ver
        pkg = ver = None

for name in sorted(names):
    if name in best:
        print(f"{name}={best[name]}")
    else:
        print(f"{name}=NOT-FOUND-AT-THIS-SNAPSHOT", file=sys.stderr)
        sys.exit(1)
PY
