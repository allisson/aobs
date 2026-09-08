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
# TWO ROLES, TWO SOURCES, and the difference is which one decides what the hashes ARE.
#
# `--refresh` is run by a human when a pin changes, and it fetches from snapshot.debian.org. That
# archive is what will still serve these exact versions in a year, which is the whole reason a
# release stays rebuildable after the live mirror has moved on. It is slow and it rate-limits;
# both are acceptable for a step that runs on a pin change and produces a diff someone reads.
#
# Every other run — CI, a fresh clone — fetches from the live mirror and verifies the result
# against the committed `build/inputs.sha256`. Same bytes or the gate fails. Reproducibility does
# not depend on which host served a byte; it depends on the hash file, exactly as this script s
# integrity does not depend on TLS. Anything the live mirror no longer carries falls back to
# snapshot automatically.
#
# Measured 2026-09-07: snapshot.debian.org from a GitHub runner hung past ten minutes in apt s
# retry loop ("Tried to start delayed item ... but failed"), while all 17 pinned versions were
# present on deb.debian.org. Runner address ranges are throttled far harder than a laptop.
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
#
# THE SAME FAILURE ARRIVED THROUGH THE BASE IMAGE, TWICE, and by two different mechanisms. It is
# why the appliance group resolves against an empty dpkg status AND asks for `?essential`.
#
# First mechanism, measured 2026-09-07 in the M2 unshare probe: `mmdebstrap` refused the appliance
# pool with `libc6 ... not installable`, `dpkg ... not installable`, and thirty-nine more. The pool
# held 37 packages. The missing ones are
# exactly what `debian:trixie-slim` already had installed when this script resolved — `libc6`,
# `dpkg`, `tar`, `coreutils`, `debconf`, `tzdata`, `libpam-*`. `--reinstall` re-downloads the
# packages NAMED on the command line; it does not re-download a transitive dependency apt
# considers already satisfied. The pool was therefore complete relative to the container that
# built it, which is the one place it never has to be: `Dockerfile.test` starts FROM that image,
# and `mkiso.sh` starts from nothing.
#
# `Dir::State::status` pointed at an empty file is what makes apt resolve as if nothing were
# installed. It replaces `--reinstall` rather than joining it.
#
# Second mechanism, and the first fix did not cover it: **apt never lists an `Essential: yes`
# package as a dependency**, with or without an empty status file. It assumes they are present.
# So the empty-root resolution produced 57 packages that still had no `bash`, no `coreutils`, no
# `base-files` — and mmdebstrap got all 57 into the chroot and then died with
# `chroot: failed to run command 'dpkg'`, because that tree is not a working userland.
#
# THE HONEST CLOSURE IS 88, not 57, and the 57 figure was published before it was tested. See the
# `?essential` note in fetch_debs.
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

mkdir -p "$INPUTS/deb/appliance" "$INPUTS/deb/kernel" "$INPUTS/deb/harness" "$INPUTS/wheels/appliance" "$INPUTS/wheels/test"

fetch_debs() {
    # $1: output subdirectory; $2: space-separated pins
    out=$1
    pins=$2
    echo "==> resolving and downloading the $(basename "$out") closure (source: $SOURCE)"
    docker run --rm --platform=linux/amd64 \
        -e DEBIAN_SNAPSHOT="$DEBIAN_SNAPSHOT" -e DEBIAN_SUITE="$DEBIAN_SUITE" \
        -e PINS="$pins" -e SOURCE="$SOURCE" \
        -v "$PWD/$out:/out" \
        debian:trixie-slim sh -euc '
            # http, and the reason is in this script s header: no ca-certificates in slim, and
            # apt s integrity is the signed InRelease, not the transport.
            #
            # snapshot serves the archive as it stood; the live mirror serves it as it stands, and
            # for a stable suite eight days on those are the same bytes. Which host is used is
            # decided by SOURCE and never changes what is accepted: build/inputs.sha256 does that.
            if [ "$SOURCE" = "snapshot" ]; then
                printf "deb [check-valid-until=no] http://snapshot.debian.org/archive/debian/%s/ %s main\n" \
                    "$DEBIAN_SNAPSHOT" "$DEBIAN_SUITE" > /etc/apt/sources.list.d/pinned.list
                printf "deb [check-valid-until=no] http://snapshot.debian.org/archive/debian-security/%s/ %s-security main\n" \
                    "$DEBIAN_SNAPSHOT" "$DEBIAN_SUITE" >> /etc/apt/sources.list.d/pinned.list
                # Retries are not optional against snapshot.debian.org; see the header.
                printf "Acquire::Retries \"8\";\nAcquire::http::Timeout \"60\";\n" \
                    > /etc/apt/apt.conf.d/99retries
            else
                printf "deb http://deb.debian.org/debian %s main\n" "$DEBIAN_SUITE" \
                    > /etc/apt/sources.list.d/pinned.list
                printf "deb http://deb.debian.org/debian-security %s-security main\n" "$DEBIAN_SUITE" \
                    >> /etc/apt/sources.list.d/pinned.list
                # Short and few: if the mirror has moved past a pin, failing fast into the
                # snapshot fallback beats grinding through eight retries per file.
                printf "Acquire::Retries \"2\";\nAcquire::http::Timeout \"30\";\n" \
                    > /etc/apt/apt.conf.d/99retries
            fi
            rm -f /etc/apt/sources.list /etc/apt/sources.list.d/debian.sources

            apt-get update

            # RESOLVE AGAINST AN EMPTY DPKG STATUS. What is already installed in this container is
            # not a fact about the rootfs mkiso.sh builds, and `--reinstall` does not cover it: it
            # re-downloads the packages named on the command line, never a transitive dependency
            # apt considers already satisfied. See the header of the closures section.
            : > /tmp/empty-status

            # AND ASK FOR THE ESSENTIAL SET BY NAME, because an empty status file is not enough.
            # apt never lists an `Essential: yes` package as a dependency — it assumes those are
            # always installed, and it goes on assuming it with `Dir::State::status` pointed at
            # nothing. trixie/main has 22 such packages; resolving the pins alone yields 5 of them
            # and silently omits `base-files`, `base-passwd`, `bash`, `coreutils`, `grep`, `sed`,
            # `gzip`, `libc-bin`, `ncurses-base`, `perl-base`, `sysvinit-utils`, `hostname`,
            # `bsdutils`, `diffutils`, `findutils`, `init-system-helpers` and `ncurses-bin`.
            #
            # Measured: mmdebstrap got all 57 packages into the chroot and then died with
            # `chroot: failed to run command 'dpkg': No such file or directory` while installing
            # the essential packages, because the tree it had was not yet a working userland.
            # With `?essential` the closure is 88 (87 against `main` alone; `trixie-security` pulls
            # `libstdc++6`) and it has one.
            #
            # `?essential` is an apt PATTERN, so the set stays derived from the archive. Listing
            # the 22 names in `build/apt-versions.txt` instead would be a closure maintained by
            # hand, which drifts the first time Debian changes the set — the exact failure mode of
            # the 37-package pool this replaced.
            apt-get install -y --no-install-recommends --download-only \
                -o Dir::State::status=/tmp/empty-status '?essential' $PINS
            cp /var/cache/apt/archives/*.deb /out/
            ls -1 /out | wc -l
        '
}

# The kernel is FETCHED, NEVER RESOLVED, and never installed into the rootfs.
#
# `docs/overview.md` says the whole rootfs is the initramfs, so the kernel is a file sitting beside
# it on the ISO rather than a package inside it. Letting apt resolve it drags in the machinery for
# building the very thing this project builds itself: measured 2026-09-07,
# `linux-image-amd64` -> `linux-image-6.12.107+deb13-amd64` -> `initramfs-tools` -> `udev` ->
# `systemd`, which would have put an init system in a pool for an appliance whose first published
# claim is that it has none. Dropping the kernel from the resolution removes `systemd`, `udev`,
# `initramfs-tools`, `libsystemd-shared` and `dracut-install` from the pool outright — 57 packages
# with none of them, against 78 with all of them.
#
# `mkiso.sh` unpacks these two with `dpkg-deb -x` into a staging directory: `vmlinuz` goes on the
# ISO, `/lib/modules` is pruned to the allowlist and copied into the rootfs, and dpkg is never told
# a kernel was installed, so no maintainer script runs and no bootloader is invoked.
#
# `libsystemd0` and `libudev1` DO remain in the closure, pulled by `util-linux`. Those are shared
# libraries, not daemons: there is no `systemd` PID 1 and no `udevd` in the image, and that is the
# claim `build/verify.py` checks. Naming the distinction here because "no systemd" and "no
# libsystemd0" are different statements and only the first one is true.
fetch_kernel() {
    # $1: output subdirectory; $2: space-separated pins
    out=$1
    pins=$2
    echo "==> downloading the kernel packages, unresolved (source: $SOURCE)"
    docker run --rm --platform=linux/amd64 \
        -e DEBIAN_SNAPSHOT="$DEBIAN_SNAPSHOT" -e DEBIAN_SUITE="$DEBIAN_SUITE" \
        -e PINS="$pins" -e SOURCE="$SOURCE" \
        -v "$PWD/$out:/out" \
        debian:trixie-slim sh -euc '
            if [ "$SOURCE" = "snapshot" ]; then
                printf "deb [check-valid-until=no] http://snapshot.debian.org/archive/debian/%s/ %s main\n" \
                    "$DEBIAN_SNAPSHOT" "$DEBIAN_SUITE" > /etc/apt/sources.list.d/pinned.list
                printf "deb [check-valid-until=no] http://snapshot.debian.org/archive/debian-security/%s/ %s-security main\n" \
                    "$DEBIAN_SNAPSHOT" "$DEBIAN_SUITE" >> /etc/apt/sources.list.d/pinned.list
                printf "Acquire::Retries \"8\";\nAcquire::http::Timeout \"60\";\n" \
                    > /etc/apt/apt.conf.d/99retries
            else
                printf "deb http://deb.debian.org/debian %s main\n" "$DEBIAN_SUITE" \
                    > /etc/apt/sources.list.d/pinned.list
                printf "deb http://deb.debian.org/debian-security %s-security main\n" "$DEBIAN_SUITE" \
                    >> /etc/apt/sources.list.d/pinned.list
                printf "Acquire::Retries \"2\";\nAcquire::http::Timeout \"30\";\n" \
                    > /etc/apt/apt.conf.d/99retries
            fi
            rm -f /etc/apt/sources.list /etc/apt/sources.list.d/debian.sources

            apt-get update

            # `download`, not `install --download-only`: it fetches exactly the named .debs and
            # resolves nothing. That is the whole point — resolving is what drags in an init
            # system.
            #
            # But `linux-image-amd64` is a 1.5 KB METAPACKAGE that carries no kernel, so the
            # concrete image has to be named too. It is derived from the metapackage rather than
            # pinned a second time in `build/apt-versions.txt`: the version is already fixed by the
            # snapshot, and two lines naming one kernel is two places for one fact — the second
            # would go stale the moment the pin moved and nothing would re-read it.
            #
            # `apt-cache depends` reads the index, not the dependency solver, so this stays a
            # lookup and never becomes a resolution.
            real=$(apt-cache depends --no-recommends --no-suggests $PINS \
                   | awk "/Depends:/ { print \$2 }" | grep "^linux-image-" || true)
            [ -n "$real" ] || { echo "no concrete linux-image behind $PINS" >&2; exit 1; }
            echo "==> metapackage $PINS resolves to $real"

            cd /out && apt-get download $PINS $real
            ls -1 /out | wc -l
        '
}

# --refresh decides what the hashes are, so it comes from the archive that will still have these
# versions in a year. Everything else takes the fast path and is judged by the hash file.
if [ "$REFRESH" -eq 1 ]; then
    SOURCE=snapshot
else
    SOURCE=${AOBS_DEB_SOURCE:-mirror}
fi

fetch_group() {
    # $1 output dir; $2 pins; $3 fetcher (fetch_debs | fetch_kernel). Try $SOURCE; on failure fall
    # back to snapshot, which is the only host guaranteed to still carry a version the live mirror
    # has moved past.
    _fetch=${3:-fetch_debs}
    if "$_fetch" "$1" "$2"; then
        return 0
    fi
    if [ "$SOURCE" = "snapshot" ]; then
        echo "==> snapshot.debian.org failed and there is no further fallback" >&2
        return 1
    fi
    echo "==> the live mirror could not satisfy every pin; falling back to snapshot" >&2
    rm -f "$1"/*.deb
    # A prefix assignment does not scope to a shell function in POSIX sh, so set and restore.
    _prev=$SOURCE
    SOURCE=snapshot
    "$_fetch" "$1" "$2"
    _rc=$?
    SOURCE=$_prev
    return $_rc
}

# The kernel pins are split out of the appliance group before resolution. They stay in the
# appliance group in `build/apt-versions.txt`, because that group answers "may this survive into
# the shipped rootfs?" and the pruned modules tree does — it is the INSTALL METHOD that differs,
# not the destination. See fetch_kernel above for why resolving them puts an init system in the
# pool of an appliance whose first published claim is that it has none.
KERNEL_PINS=$(echo "$APPLIANCE_PINS" | grep '^linux-image' || true)
ROOTFS_PINS=$(echo "$APPLIANCE_PINS" | grep -v '^linux-image' || true)
[ -n "$KERNEL_PINS" ] || { echo "no linux-image pin in the appliance group" >&2; exit 1; }
[ -n "$ROOTFS_PINS" ] || { echo "the appliance group is nothing but the kernel" >&2; exit 1; }

fetch_group "$INPUTS/deb/appliance" "$(echo "$ROOTFS_PINS" | tr '\n' ' ')"
fetch_group "$INPUTS/deb/kernel" "$(echo "$KERNEL_PINS" | tr '\n' ' ')" fetch_kernel
# The harness pool is what `Dockerfile.test` installs on top of `debian:trixie-slim`, and the tier
# needs the appliance packages too. The kernel is deliberately absent: no test installs a kernel.
fetch_group "$INPUTS/deb/harness" "$(echo "$ROOTFS_PINS" "$HARNESS_PINS" | tr '\n' ' ')"

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
