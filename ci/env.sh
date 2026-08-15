# Values that must be identical in every place the image is built, or the image stops
# being reproducible. Sourced by ci/build-binary.sh and image/build.sh.

# 01-boot-layer.md §1: "Set SOURCE_DATE_EPOCH from the first build." This is that value.
# It is the one line that keeps the v2 reproducibility goal a pinning exercise rather
# than a rewrite, and it is also the build date the appliance displays (§10). Changing it
# changes every timestamp in the image, so it changes with a release and not otherwise.
: "${SOURCE_DATE_EPOCH:=1786752000}" # 2026-08-15T00:00:00Z
export SOURCE_DATE_EPOCH

# 01-boot-layer.md §1: "Pin the live-build version." image/build.sh refuses to run
# against any other, because live-build's reproducibility behaviour is version-specific
# and a silent upgrade is exactly the kind of drift the pin exists to catch.
: "${AOBS_LIVE_BUILD_VERSION:=1:20250505+deb13u1}"
export AOBS_LIVE_BUILD_VERSION

# The one target. 01-boot-layer.md §7: UEFI amd64 only.
: "${AOBS_RUST_TARGET:=x86_64-unknown-linux-gnu}"
export AOBS_RUST_TARGET
