# The one build environment, used by CI and reproducible on a developer's machine.
#
# Debian 13 (trixie), amd64 — the same distribution the ISO is built from
# (01-boot-layer.md), so the binary that goes into the image is linked against the
# libraries that will be on the image.
#
#   docker build --platform linux/amd64 -f ci/build-env.Dockerfile -t aobs-build ci
#   docker run --rm --platform linux/amd64 -v "$PWD:/src" -w /src aobs-build \
#          cargo test --workspace
#
# `lb build` additionally needs `--privileged`.
FROM debian:trixie-slim

# Keep in step with AOBS_LIVE_BUILD_VERSION in ci/env.sh; image/build.sh fails loudly if
# they diverge.
ARG LIVE_BUILD_VERSION=1:20250505+deb13u1

ENV DEBIAN_FRONTEND=noninteractive \
    RUSTUP_HOME=/usr/local/rustup \
    CARGO_HOME=/usr/local/cargo \
    PATH=/usr/local/cargo/bin:$PATH

RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl build-essential pkg-config \
    # Slint on backend-linuxkms-noseat + renderer-software (01-boot-layer.md §2,
    # ADR-0016). libseat-dev is gone with the seat daemon: -noseat opens /dev/fb0 with a
    # plain open(2), and a build container that still offered libseat would let the crate
    # drift back onto it without anyone noticing.
      libinput-dev libxkbcommon-dev libudev-dev \
      libfontconfig-dev libfreetype-dev \
    # Building and inspecting the image. live-build is version-pinned (01-boot-layer.md
    # §1); image/build.sh refuses to run against any other, so the two must agree.
      "live-build=${LIVE_BUILD_VERSION}" \
      debootstrap xorriso squashfs-tools initramfs-tools-core \
      dosfstools mtools grub-efi-amd64-bin grub-common \
    && rm -rf /var/lib/apt/lists/*

# Pinned to the same toolchain rust-toolchain.toml names, so the container does not
# quietly resolve a different compiler than a developer's machine.
ARG RUST_VERSION=1.97.1
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \
      | sh -s -- -y --no-modify-path --profile minimal \
        --default-toolchain "${RUST_VERSION}" \
        --component rustfmt --component clippy \
    && chmod -R a+w "${RUSTUP_HOME}" "${CARGO_HOME}"
