#!/bin/sh
# THE ONE NETWORKED STEP, and it is not part of any build.
#
# It populates `build/inputs/` with every byte the image build and the test tier consume — the
# `.deb` closure of each apt group, and the wheel closure of each Python group — and writes
# `build/inputs.sha256` over the result. Nothing downstream touches the network: `Dockerfile.test`
# and (at M2) `mkiso.sh` install from these local files with `apt-get install ./*.deb` and
# `pip --no-index`, and refuse to start unless every byte matches the checked-in hash file.
#
#     sh build/fetch-inputs.sh              # populate build/inputs/, verify against inputs.sha256
#     sh build/fetch-inputs.sh --refresh    # populate, then REWRITE inputs.sha256 (pin change)
#
# WHY THIS EXISTS RATHER THAN APT-FROM-SNAPSHOT IN THE DOCKERFILE. snapshot.debian.org is a
# low-capacity archive service that rate-limits: measured on 2026-09-07, five consecutive
# `InRelease` fetches returned `503 TooManyRequests / No healthy backends`, and the same URL
# returned 200 once `--retry 3 --retry-all-errors` was added. A tier that fetched from it on every
# push, every pull request and every dev rebuild would be flaky and would be abusing the service.
# This runs once per pin change, and CI caches its output keyed on the pin files' own hash.
#
# WHY HTTP INSIDE THE CONTAINER. `debian:trixie-slim` ships no `ca-certificates`, so HTTPS apt
# fetches fail certificate verification — and installing certificates first would mean pulling an
# unpinned package from an unpinned mirror *before* the step that does the pinning. apt's integrity
# does not come from TLS: it comes from the GPG signature on the `InRelease` file, checked against
# the archive keyring already in the base image, and then from per-file SHA-256 in the indexes. TLS
# would add transport privacy, which this step does not need and which the resulting hash file does
# not depend on. Every byte fetched here is hashed into `build/inputs.sha256` and reviewed in a
# diff, which is a stronger statement than "it arrived over TLS".
#
# Resolution is done by apt itself, in a container, rather than by a dependency solver written
# here. A solver of our own would be a second opinion about what Debian's dependencies mean, and
# the first time it disagreed with apt the appliance would be the place we found out.

set -eu
cd "$(dirname "$0")/.."

REFRESH=0
[ "${1:-}" = "--refresh" ] && REFRESH=1

command -v docker >/dev/null || { echo "docker is required" >&2; exit 1; }

INPUTS=build/inputs
HASHES=build/inputs.sha256

. ./build/snapshot.env

# --- The apt closures ---------------------------------------------------------------------------
#
# Two pools, not one. `mkiso.sh` installs the appliance group into the rootfs and nothing else, so
# it needs that group's closure to be complete on its own; the tier installs both. Downloading the
# union into a single directory would leave the appliance pool missing whatever it shares with the
# harness group, and the failure would appear at image-build time as an unsatisfiable dependency.
group() {
    # $1: "appliance" | "harness" — print that group's pinned name=version lines
    awk -v want="$1" '
        /^# @group / { g = $3; next }
        /^[[:space:]]*#/ { next }
        /^[[:space:]]*$/ { next }
        { if (g == "") { print "package outside any group: " $0 > "/dev/stderr"; exit 1 }
          if (g == want) print $0 }
    ' build/apt-versions.txt
}

APPLIANCE_PINS=$(group appliance)
HARNESS_PINS=$(group harness)
[ -n "$APPLIANCE_PINS" ] || { echo "no appliance packages parsed" >&2; exit 1; }
[ -n "$HARNESS_PINS" ] || { echo "no harness packages parsed" >&2; exit 1; }

mkdir -p "$INPUTS/deb/appliance" "$INPUTS/deb/harness" "$INPUTS/wheels/appliance" "$INPUTS/wheels/test"

fetch_debs() {
    # $1: output subdirectory; $2: space-separated pins
    out=$1
    pins=$2
    echo "==> resolving and downloading the $(basename "$out") closure"
    docker run --rm --platform=linux/amd64 \
        -e DEBIAN_SNAPSHOT="$DEBIAN_SNAPSHOT" -e DEBIAN_SUITE="$DEBIAN_SUITE" \
        -e PINS="$pins" \
        -v "$PWD/$out:/out" \
        debian:trixie-slim sh -euc '
            # http, and the reason is in this script s header: no ca-certificates in slim, and
            # apt s integrity is the signed InRelease, not the transport.
            printf "deb [check-valid-until=no] http://snapshot.debian.org/archive/debian/%s/ %s main\n" \
                "$DEBIAN_SNAPSHOT" "$DEBIAN_SUITE" > /etc/apt/sources.list.d/pinned.list
            printf "deb [check-valid-until=no] http://snapshot.debian.org/archive/debian-security/%s/ %s-security main\n" \
                "$DEBIAN_SNAPSHOT" "$DEBIAN_SUITE" >> /etc/apt/sources.list.d/pinned.list
            rm -f /etc/apt/sources.list /etc/apt/sources.list.d/debian.sources

            # Retries are not optional against snapshot.debian.org; see the header.
            printf "Acquire::Retries \"8\";\nAcquire::http::Timeout \"60\";\n" \
                > /etc/apt/apt.conf.d/99retries

            apt-get update
            # --reinstall so that packages already in the base image are still downloaded: the
            # rootfs mkiso.sh builds starts empty, and "already installed here" is not a fact
            # about the appliance.
            apt-get install -y --no-install-recommends --download-only --reinstall $PINS
            cp /var/cache/apt/archives/*.deb /out/
            ls -1 /out | wc -l
        '
}

fetch_debs "$INPUTS/deb/appliance" "$(echo "$APPLIANCE_PINS" | tr '\n' ' ')"
fetch_debs "$INPUTS/deb/harness" "$(echo "$APPLIANCE_PINS" "$HARNESS_PINS" | tr '\n' ' ')"

# --- The wheel closures -------------------------------------------------------------------------
#
# Explicit platform and Python version, because this may run on a macOS host and a macOS wheel is
# not what the appliance loads. `--only-binary :all:` is deliberate: a source distribution here
# would mean a compiler in the image build, which `docs/adr/0001` spent the Alpine kernel config to
# avoid. If a package has no matching wheel this step FAILS, which is the M1 question about
# manylinux coverage being answered rather than assumed.
fetch_wheels() {
    # $1: output subdirectory; $2: requirements file
    echo "==> downloading wheels for $(basename "$1")"
    python3 -m pip download \
        --quiet \
        --dest "$1" \
        --require-hashes \
        --only-binary :all: \
        --implementation cp \
        --python-version 3.13 \
        --platform manylinux_2_28_x86_64 \
        --platform manylinux2014_x86_64 \
        -r "$2"
}

fetch_wheels "$INPUTS/wheels/appliance" build/requirements.appliance.txt
fetch_wheels "$INPUTS/wheels/test" build/requirements.test.txt

# --- The gate -----------------------------------------------------------------------------------
#
# Hash AND set equality. A hash file that only checks the bytes of files it names would not notice
# an extra `.deb` appearing in the pool, which is how an unpinned package reaches an image that
# claims every input is pinned.
manifest() {
    find "$INPUTS" -type f | LC_ALL=C sort | while read -r f; do
        printf '%s  %s\n' "$(shasum -a 256 "$f" | cut -d' ' -f1)" "$f"
    done
}

if [ "$REFRESH" -eq 1 ]; then
    manifest > "$HASHES"
    echo "==> rewrote $HASHES ($(wc -l < "$HASHES" | tr -d ' ') files)"
    echo "    review this diff: it is the complete list of bytes the build consumes."
    exit 0
fi

if [ ! -f "$HASHES" ]; then
    echo "$HASHES does not exist. Run with --refresh to create it, then review the diff." >&2
    exit 1
fi

if manifest | diff -u "$HASHES" - > /tmp/inputs.diff 2>&1; then
    echo "==> build/inputs/ matches $HASHES ($(wc -l < "$HASHES" | tr -d ' ') files)"
else
    echo "==> build/inputs/ DOES NOT match $HASHES:" >&2
    cat /tmp/inputs.diff >&2
    echo "If a pin changed, rerun with --refresh and review the diff." >&2
    exit 1
fi
