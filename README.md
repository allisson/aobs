# aobs
Amnesic Offline Bitcoin Signer

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

**The v1 implementation spec is closed. There is no product code yet, and no release.**

Every design decision was worked as a ticket and recorded before any code was written. What the
repo currently holds:

| Path | What is in it |
|---|---|
| [`docs/specs/`](docs/specs/) | The v1 implementation spec, six files: overview, boot layer, core, transport, screens, testing and release. |
| [`docs/adr/`](docs/adr/) | Fifteen architecture decision records — the *why* for the choices a newcomer would otherwise read as arbitrary. |
| [`docs/research/`](docs/research/) | Research findings, one file per question, every claim carrying a source URL. |
| [`docs/prototypes/`](docs/prototypes/) | Throwaway HTML prototypes built to settle specific UI questions. |
| [`CONTEXT.md`](CONTEXT.md) | The glossary. |

The full argument behind each decision lives in its ticket's resolution comment, indexed one line
each from [issue #1](https://github.com/allisson/aobs/issues/1).

Two things the spec deliberately leaves open, both listed under *What is still owed* in
[`docs/specs/00-overview.md`](docs/specs/00-overview.md): **eight measurements** owed on real
hardware, and **three verification obligations**. None of them blocks implementation; all of them
block a release.

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
