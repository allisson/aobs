# aobs
Amnesic Offline Bitcoin Signer

> [!WARNING]
> **This appliance cannot yet do the thing it exists to do. Do not point it at a key that holds
> money.**
>
> The repository is published while it is being built, so the design can be read and argued with
> before the code sets. What is missing is not detail work:
>
> - **No PSBT validation and no rejection policy.** Nothing checks what a transaction does.
> - **No transaction review screen.** The screen that is the entire security argument — *if the
>   user cannot verify what they are signing, no other property matters* — is not written.
> - **No signing path.** No derivation, no change re-derivation, no sighash, no `secp256k1` call.
>
> An ISO built from this tree boots, and it can generate a seed. Treat any key it produces or
> imports as **disclosed**: the paths that would protect it do not exist yet. There is no release
> and no signed artifact, and until there is, nothing here is a signer — it is the shape of one.

A Bitcoin signing appliance shipped as a bootable Debian LiveCD (`bitcoin-signer-amd64.iso`,
amd64 only). You boot it on a machine with no network, create or load a single-sig wallet,
review a transaction in full, sign it, and shut down. The wallet lives in RAM for one session
and nothing survives it — no config file, no wallet database, no history, no cache.

Transactions cross the air gap as QR codes in both directions. The keyboard is for entering a
seed phrase and a passphrase; there is no USB or SD data path, and no network stack to remove
because none is built in.

It exists for one reason, which decides every trade in the design:

> aobs trades away every hardware guarantee the dedicated signers have — secure element, rate
> limiting, physical air gap, hardware entropy, attestation — for the one thing none of them can
> buy at any price: a screen and a CPU big enough to show the user the entire transaction, in
> full, without truncation or paging.

## Status

**The v1 implementation spec is closed. Implementation has started at the walking skeleton, and
there is no release.**

Every design decision was worked as a ticket and recorded before any code was written. What the
repo currently holds:

| Path | What is in it |
|---|---|
| [`docs/specs/`](docs/specs/) | The v1 implementation spec, seven files: overview, boot layer, core, transport, screens, testing and release, code registry. |
| [`docs/adr/`](docs/adr/) | Eighteen architecture decision records — the *why* for the choices a newcomer would otherwise read as arbitrary. |
| [`docs/research/`](docs/research/) | Research findings, one file per question, every claim carrying a source URL. |
| [`docs/prototypes/`](docs/prototypes/) | Throwaway HTML prototypes built to settle specific UI questions. |
| [`docs/qa-checklist.md`](docs/qa-checklist.md) | The claims CI cannot answer, which need a person and a machine. |
| [`CONTEXT.md`](CONTEXT.md) | The glossary. |
| `aobs-core/` | Wallet logic. No screen, no camera, no filesystem, no clock. Currently empty. |
| `aobs/` | The appliance binary: Slint on KMS, and the raw `getrandom` syscall. |
| [`image/`](image/) | The live-build configuration that emits `bitcoin-signer-amd64.iso`. |
| [`ci/`](ci/) | The build environment and the gates that run against the built artifact. |

The full argument behind each decision lives in its ticket's resolution comment, indexed one line
each from [issue #1](https://github.com/allisson/aobs/issues/1).

Two things the spec deliberately leaves open, both listed under *What is still owed* in
[`docs/specs/00-overview.md`](docs/specs/00-overview.md): **eight measurements** owed on real
hardware, and **three verification obligations**. None of them blocks implementation; all of them
block a release.

## Building

Everything runs in one container, so CI and a developer's machine cannot resolve a different
compiler or a different `live-build`. `lb build` chroots and mounts, which is why the image step
is privileged.

```sh
docker build --platform linux/amd64 -f ci/build-env.Dockerfile -t aobs-build ci

# Tests and the mechanical gates that read the tree.
docker run --rm --platform linux/amd64 -v "$PWD:/src" -w /src aobs-build \
    sh -c 'cargo test --workspace && ci/check-source.sh && ci/check-source-test.sh'

# The two gates that are deliberately not part of the test run: region coverage
# (>= 95% on aobs-core, >= 98% on each of the nine components in
# ci/coverage-components.tsv) and the fuzz harness. Separate CI jobs, for the reason
# 05-testing-and-release.md §1 gives: coverage is necessary, not sufficient.
docker run --rm --platform linux/amd64 -v "$PWD:/src" -w /src aobs-build ci/check-coverage.sh
docker run --rm --platform linux/amd64 -v "$PWD:/src" -w /src aobs-build ci/check-fuzz.sh

# The ISO. Both steps, in this order.
docker run --rm --platform linux/amd64 -v "$PWD:/src" -w /src aobs-build ci/build-binary.sh
docker run --rm --platform linux/amd64 --privileged -v "$PWD:/src" -w /src aobs-build image/build.sh

# The gates that run against the artifact, not the source.
ci/check-image.sh bitcoin-signer-amd64.iso
ci/qemu-boot.sh   bitcoin-signer-amd64.iso
```

The appliance targets x86_64 Linux and only builds there — Slint's linuxkms backend and the raw
`getrandom` syscall have no other target. On a non-Linux host, `cargo test -p aobs-core` works
directly; the rest needs the container.

**On a macOS host, `lb build` cannot run on the bind-mounted source tree** — `debootstrap` extracts
`.deb` archives preserving ownership and device nodes, which Docker Desktop's shared filesystem
does not support, and it fails with `tar failed`. Build inside the container's own filesystem and
copy the artifacts out:

```sh
docker run --rm --platform linux/amd64 --privileged -v "$PWD:/src" aobs-build sh -c '
    set -eu
    mkdir -p /build && cp -a /src/image /src/ci /build/
    cd /build/image && sh build.sh
    cp -f /build/bitcoin-signer-amd64.iso /build/bitcoin-signer-amd64.packages /src/'
```

## Threat model, in brief

**Defended:** a compromised online host feeding malicious PSBTs — change-address substitution, fee
inflation, amount spoofing; hostile bytes arriving over the QR channel; theft of the machine or the
boot media after shutdown.

**Out of reach, and openly so:** malicious firmware or BIOS, hardware implants, cold-boot and DMA
attacks by an adversary who is present, and cameras in the room.

**Structurally unavailable:** rate limiting, PIN counters, wipe-on-failure, duress wallets. Amnesia
forecloses all of them — Jade buys rate limiting only by requiring network connectivity, which is
the property aobs exists to have. Security reduces to seed entropy plus the user's physical backup
discipline.

The consequence that shapes the most code: **the transaction review screen is the mitigation.** If
you cannot verify what you are signing, no other property matters.

## Licence

Copyright (C) 2026 Allisson Azevedo

aobs is free software: you can redistribute it and/or modify it under the terms of the
GNU General Public License, version 3, as published by the Free Software Foundation.

aobs is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY;
without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
See the [GNU General Public License](LICENSE) for more details.

`SPDX-License-Identifier: GPL-3.0-only`

The reasoning is recorded in [ADR-0001](docs/adr/0001-gpl-3-0-for-the-slint-ui-toolkit.md).
Note that this licence covers *this repository*. The released
`bitcoin-signer-amd64.iso` also aggregates Debian components, which carry their own
licences and are unaffected by this choice.
