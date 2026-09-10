#!/bin/sh
# `out/bitcoin-signer-amd64.iso` on a machine that is not an `ubuntu-24.04` runner.
#
#     sh build/mkiso-docker.sh
#
# This is a *host*, not a build: it builds `build/Dockerfile.isohost`, mounts the working tree at
# `/work`, and runs `build/mkiso.sh` inside it. The build is still the one in `build/mkiso.sh` and
# the inputs are still the ones in `build/inputs/` — nothing here touches the ISO's contents.
#
# **THIS PATH IS PRIVILEGED, AND `build/mkiso.sh` IS NOT.** The script it runs says "unprivileged,
# start to finish" and means it; this file hands the container `--privileged` anyway, because on a
# Docker whose kernel refuses an unprivileged range mapping there is no other way to reach stage 1.
# The claim that the build needs no privilege is CI's, measured on `ubuntu-24.04` and nowhere else.
# A build produced by this script is NOT evidence for it. `docs/boot-pipeline.md` states the
# deviation in full, including how to get a local host where it is not needed.

set -eu

ROOT=$(cd "$(dirname "$0")/.." && pwd)
IMAGE=aobs-iso-host
ISO=$ROOT/out/bitcoin-signer-amd64.iso

say() { printf '\n==> %s\n' "$*"; }

command -v docker >/dev/null 2>&1 || {
    echo "docker is not on PATH; on an ubuntu-24.04 host run 'sh build/mkiso.sh' directly" >&2
    exit 1
}

# The one networked step is `build/fetch-inputs.sh` and it is not part of any build — including
# this one. Stage 0 would say so too, twenty seconds later and less clearly.
[ -d "$ROOT/build/inputs/deb" ] || {
    echo "build/inputs/ is not populated; run 'sh build/fetch-inputs.sh' first" >&2
    exit 1
}

say "the host image"
# No build context at all — the Dockerfile copies nothing, and `build/` as a context would hand the
# daemon the 250 MiB of pinned inputs for no reason.
docker build --platform linux/amd64 -t "$IMAGE" - < "$ROOT/build/Dockerfile.isohost"

say "the build, privileged (see the header), inside it"
# The escalation this line is the end of, so it is not walked a fourth time. Measured here, and
# each step is what the one above it failed with:
#
#   plain                            stage 1: `unshare syscall failed: Operation not permitted`
#                                    — Docker's default seccomp profile denies `unshare(CLONE_NEWUSER)`
#   --security-opt seccomp=unconfined stage 1: `newuidmap: write to uid_map failed: Operation not
#                                    permitted` — the unshare succeeds, the range mapping does not
#   --privileged                     builds
#
# The middle failure is not a missing capability and not the setuid bit: `newuidmap` is setuid-root
# and does elevate here (verified: euid 0, ruid 1001), the bounding set carries `CAP_SETUID`, the
# container is in no user namespace of its own, and the same mapping written by container root
# succeeds. The same test fails identically on a native `linux/arm64` container, so it is not the
# amd64 emulation either. It is this Docker's kernel, and it is the finding
# `docs/boot-pipeline.md` asks for rather than a reason to stop looking.
#
# And the output is NOT piped anywhere. A `| tail` here once reported success for a build whose
# stage 1 had failed, because the exit status of a pipeline is the last command's — the same
# truncated-tail reading that document already warns about, and it cost this script a full run.
docker run --rm --platform linux/amd64 \
    --privileged \
    -v "$ROOT:/work" \
    "$IMAGE" sh build/mkiso.sh

say "$ISO"
ls -l "$ISO"
# Whatever this host calls it. The number is the thing a rebuild is compared against.
if command -v sha256sum >/dev/null 2>&1; then sha256sum "$ISO"; else shasum -a 256 "$ISO"; fi
