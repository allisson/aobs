#!/bin/sh
# Build /usr/bin/aobs and stage it where live-build will pick it up.
#
# live-build knows nothing about cargo, so the binary is placed into
# config/includes.chroot before `lb build` runs.
set -eu

cd "$(dirname "$0")/.."
. ./ci/env.sh

cargo build --release --locked --target "${AOBS_RUST_TARGET}" --package aobs

install -D -m 0755 \
    "target/${AOBS_RUST_TARGET}/release/aobs" \
    image/config/includes.chroot/usr/bin/aobs

echo "staged image/config/includes.chroot/usr/bin/aobs (SOURCE_DATE_EPOCH=${SOURCE_DATE_EPOCH})"
