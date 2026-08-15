#!/bin/sh
# Runs INSIDE the build container, for a host whose filesystem cannot hold a chroot.
#
# `lb build` needs ownership, device nodes and hardlinks that Docker Desktop's shared
# filesystem does not provide, so on macOS debootstrap dies with `tar failed`. This copies
# the live-build config into a container-native volume, builds there, and copies the two
# artifacts back to the bind mount. On a Linux host, run image/build.sh directly instead.
#
#   docker volume create aobs-work
#   docker run --rm --privileged --platform linux/amd64 \
#       -v "$PWD:/src" -v aobs-work:/build aobs-build ci/local-inner.sh
set -eu

mkdir -p /build/image
rm -rf /build/ci /build/image/config /build/image/auto
cp -a /src/ci /build/
cp -a /src/image/config /src/image/auto /src/image/cmdline.sh /src/image/build.sh /build/image/

cd /build/image
sh build.sh

cp -f /build/bitcoin-signer-amd64.iso /build/bitcoin-signer-amd64.packages /src/
echo "copied bitcoin-signer-amd64.iso and .packages to the source tree"
