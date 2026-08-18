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
    # ci/check-coverage.sh reads llvm-cov's JSON export. The alternative was a summary
    # parsed out of formatted text, which is a gate that breaks on a tooling reflow.
      jq \
    && rm -rf /var/lib/apt/lists/*

# Pinned to the same toolchain rust-toolchain.toml names, so the container does not
# quietly resolve a different compiler than a developer's machine.
ARG RUST_VERSION=1.97.1
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \
      | sh -s -- -y --no-modify-path --profile minimal \
        --default-toolchain "${RUST_VERSION}" \
        --component rustfmt --component clippy --component llvm-tools \
    && chmod -R a+w "${RUSTUP_HOME}" "${CARGO_HOME}"

# The two gates 05-testing-and-release.md §1 and §4 require, in the same environment as
# everything else. A gate that runs in a container of its own is a gate that can resolve a
# different compiler than the code it judges, and this repository exists because of a
# defect of exactly that shape (§6).
#
# `llvm-tools` above is what `cargo llvm-cov` calls; rust-toolchain.toml already asks for
# it, and naming it here keeps CI from reaching the network for a component mid-run.
#
# nightly is the one unpinned toolchain in this repo. cargo-fuzz's sanitizer and its
# default `-Zbuild-std` are nightly-only, and a dated nightly pinned here would go stale
# silently between releases; ci/check-fuzz.sh takes AOBS_FUZZ_TOOLCHAIN when one has to be
# pinned. `rust-src` is what `-Zbuild-std` needs.
ARG NIGHTLY_VERSION=nightly
RUN rustup toolchain install "${NIGHTLY_VERSION}" --profile minimal \
        --component rust-src --component llvm-tools \
    && chmod -R a+w "${RUSTUP_HOME}"

ARG CARGO_LLVM_COV_VERSION=0.8.7
ARG CARGO_FUZZ_VERSION=0.13.2
RUN cargo install --locked \
        "cargo-llvm-cov@${CARGO_LLVM_COV_VERSION}" \
        "cargo-fuzz@${CARGO_FUZZ_VERSION}" \
    && chmod -R a+w "${CARGO_HOME}"
