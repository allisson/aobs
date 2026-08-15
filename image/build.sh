#!/bin/sh
# Build bitcoin-signer-amd64.iso.
#
# Needs root and Debian: `lb build` chroots and mounts. In CI and on a developer's
# machine this runs inside ci/build-env.Dockerfile with --privileged:
#
#   ci/build-binary.sh                     # inside the container, unprivileged
#   image/build.sh                         # inside the container, privileged
#
# Two artifacts come out, and the second is not optional: ADR-0012 and
# 05-testing-and-release.md §7.4 publish the package manifest alongside the ISO, because
# §3's stripped-network claim is otherwise uncheckable without building the image.
set -eu

cd "$(dirname "$0")"
. ../ci/env.sh

if [ "$(id -u)" != "0" ]; then
    echo "image/build.sh must run as root: lb build chroots and mounts." >&2
    exit 1
fi

# 01-boot-layer.md §1: the live-build version is pinned. A silent upgrade changes
# reproducibility behaviour, which is exactly the drift the pin exists to catch.
installed="$(dpkg-query -W -f='${Version}' live-build)"
if [ "${installed}" != "${AOBS_LIVE_BUILD_VERSION}" ]; then
    echo "live-build is ${installed}, pinned at ${AOBS_LIVE_BUILD_VERSION} (ci/env.sh)." >&2
    echo "Change the pin deliberately, or rebuild ci/build-env.Dockerfile." >&2
    exit 1
fi

if [ ! -x config/includes.chroot/usr/bin/aobs ]; then
    echo "config/includes.chroot/usr/bin/aobs is missing. Run ci/build-binary.sh first." >&2
    exit 1
fi

lb clean --purge
lb config
lb build

mv -f bitcoin-signer-amd64.hybrid.iso ../bitcoin-signer-amd64.iso
cp -f bitcoin-signer-amd64.packages ../bitcoin-signer-amd64.packages

echo
echo "bitcoin-signer-amd64.iso           $(du -h ../bitcoin-signer-amd64.iso | cut -f1)"
echo "bitcoin-signer-amd64.packages      $(wc -l < ../bitcoin-signer-amd64.packages) packages"
echo "SOURCE_DATE_EPOCH                  ${SOURCE_DATE_EPOCH}"
