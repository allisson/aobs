#!/bin/sh
# `out/bitcoin-signer-amd64.iso` on a machine that is not an `ubuntu-24.04` runner.
#
#     sh build/mkiso-docker.sh
#
# This is a *host*, not a build: it builds `build/Dockerfile.isohost`, mounts the working tree at
# `/work`, and runs `build/mkiso.sh` inside it unprivileged. The build is still the one in
# `build/mkiso.sh` and the inputs are still the ones in `build/inputs/` — nothing here touches the
# ISO's contents. `docs/boot-pipeline.md` holds why this file exists at all.
#
# Two things about it are load-bearing rather than convenient.

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

say "the build, unprivileged, inside it"
# `--security-opt seccomp=unconfined` IS NEEDED AND IS NOT A PRIVILEGE. Docker's default seccomp
# profile denies `unshare(CLONE_NEWUSER)` — the exact syscall `mmdebstrap --mode=unshare` is named
# after — so without it stage 1 dies with `unshare syscall failed: Operation not permitted`. It
# widens the *host's* syscall filter for this container; it grants the build nothing. There is no
# `--privileged` here, no `--cap-add`, and the process inside is uid 1001. If that ever stops being
# true, `docs/boot-pipeline.md` says what to do: write it down, do not reach for root.
#
# And the output is NOT piped anywhere. A `| tail` here once reported success for a build whose
# stage 1 had failed, because the exit status of a pipeline is the last command's.
docker run --rm --platform linux/amd64 \
    --security-opt seccomp=unconfined \
    -v "$ROOT:/work" \
    "$IMAGE" sh build/mkiso.sh

say "$ISO"
ls -l "$ISO"
# Whatever this host calls it. The number is the thing a rebuild is compared against.
if command -v sha256sum >/dev/null 2>&1; then sha256sum "$ISO"; else shasum -a 256 "$ISO"; fi
