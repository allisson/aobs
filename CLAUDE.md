# aobs — Amnesic Offline Bitcoin Signer

A Bitcoin signing appliance shipped as a bootable Debian LiveCD (`bitcoin-signer-amd64.iso`, amd64 only). The user boots it, loads or creates a wallet, signs a PSBT, and shuts down. The wallet lives in RAM and nothing survives the session.

## Status: spec-first, no product code yet

The repo holds research and planning. The v1 implementation spec is still being written, so **the work right now is deciding, not building.** Scaffolding a crate, adding a dependency, or writing signer code ahead of the spec creates work the spec will contradict.

**The map is [issue #1](https://github.com/allisson/aobs/issues/1)** — the canonical planning artifact, on GitHub Issues. It carries the destination, the settled constraints, the fog, and what is out of scope. Its child issues are the open decisions. Read it before proposing any design, and work it with `/wayfinder 1`. Decisions are recorded as resolution comments on the child issues; the map indexes them one line each.

Research findings live in `docs/research/`, one file per resolved ticket, every claim carrying a source URL. Read the relevant file before reopening a question it already answers.

## Settled — do not silently revisit

These came out of grilling and research. Reopening one is a deliberate act with a reason, not a drive-by.

- **Slint, not Tauri.** Tauri was the original premise and lost on measurement: 268 packages / 650 MiB against Slint's 22 / 21 MiB, and `getUserMedia` cannot work in a stock Tauri app on Linux. The UI is Slint on `backend-linuxkms` + `renderer-software`, rendering to KMS/DRM with no X server and no compositor. See `docs/research/05-tauri-viability.md`. The licence question this raised is settled: **the repo is GPL-3.0-only**, which is what Slint's GPL option requires and what removes an unresolvable ambiguity in its royalty-free licence. See `docs/adr/0001-gpl-3-0-for-the-slint-ui-toolkit.md`.
- **Air-gapped by construction.** The appliance has no network stack, no cloud, no sync, no broadcasting, no telemetry, no update check. Every feature is designed to work with the machine's networking physically absent.
- **QR is the only data channel**, both directions, using BC-UR / UR2 (`ur:crypto-psbt`). The physical keyboard handles seed import and passphrase entry. QR decoding happens in Rust (`v4l` → `rqrr`), never in a webview.
- **Single-sig only** across BIP44/49/84/86, mainnet plus testnet/signet.
- **Amnesic.** State lives in RAM for one session. There is no config file, no wallet database, no transaction history, no cache.
- **Backup crypto**: Argon2id m=64 MiB/t=3/p=4 → ChaCha20-Poly1305 over the BIP-39 entropy. The user cannot choose the password; it is 8 words drawn independently from the EFF long list, ASCII-space separated. Whether this feature ships at all is still open at issue #7.

## Threat model

Defended: a compromised online host feeding malicious PSBTs, hostile bytes arriving over the QR channel, theft of the machine or boot media after shutdown.

Out of reach and openly so: malicious firmware, hardware implants, cold-boot and DMA attacks by a present adversary, cameras in the room.

The consequence that shapes the most code: **the transaction review screen is the mitigation.** If the user cannot verify what they are signing, no other property matters.

## Rules that bite while coding

- **Re-derive, never trust.** A PSBT's BIP32 derivation paths are an attacker-supplied assertion. Change outputs are re-derived from our own key material and byte-compared against the `scriptPubKey`. Every surveyed signer does this; so do we.
- **Everything crossing the QR boundary is hostile input.** `ur-rs` adopts an attacker-controlled `seqLen` and allocates on it, so limits are clamped at our call site. The PSBT parser and the UR decoder carry fuzz targets we write ourselves.
- **Secrets are wrapped in zeroizing types** and zeroized at session end. Secret material stays out of logs, error messages, and `Debug` output.
- **Coverage bar**: 95% production code, 98%+ on security-critical components, plus fuzzing, property-based tests, and the BIP test vectors. The spec names which components carry the 98% bar.
- **Verify the shipped artifact, not just the source.** Coldcard shipped a software PRNG for five years because a build-integration defect broke the linkage while the source stayed correct. Tests that only assert against the source tree would have passed.
