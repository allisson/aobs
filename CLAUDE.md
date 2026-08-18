# aobs — Amnesic Offline Bitcoin Signer

A Bitcoin signing appliance shipped as a bootable Debian LiveCD (`bitcoin-signer-amd64.iso`, amd64 only). The user boots it, loads or creates a wallet, signs a PSBT, and shuts down. The wallet lives in RAM and nothing survives the session.

## Status: the spec is closed; the image matches it again; the Rust does not yet

The v1 implementation spec is written and merged — `docs/specs/` (seven files, the last being the code registry added by [#56](https://github.com/allisson/aobs/issues/56)), `docs/adr/` (seventeen ADRs, one of them superseded) and `CONTEXT.md`, assembled from 27 closed decision tickets plus the display-path map ([#42](https://github.com/allisson/aobs/issues/42)).

**A walking skeleton is on `main`** ([#39](https://github.com/allisson/aobs/issues/39)): `aobs/` and `aobs-core/`, `ci/`, and `image/` with the live-build config, hooks and the `aobs.service` unit. It is what falsified ADR-0009 by building an ISO and booting it.

**`image/`, `ci/` and the crate's backend feature were reconciled against ADR-0016 and the panel map by [#57](https://github.com/allisson/aobs/issues/57)** — no seatd, no `libseat1`, `backend-linuxkms-noseat`, `Type=notify`, `console-detach`/`console-attach`, the GPU modules deleted, the keymap pinned, and `TTYVTDisallocate=yes` gone for the reason [#52](https://github.com/allisson/aobs/issues/52) proved.

**That reconciliation has now been built and booted** ([#65](https://github.com/allisson/aobs/issues/65)): the ISO builds from `main` with no manual steps, `ci/check-image.sh` passes, and it draws and prints `AOBS_READY` on both QEMU machine types — `ramfb` with no GPU, which is the fbdev tier ADR-0016 rests on, and virtio-gpu. #52's `fbcon` probe is a standing row (`ci/fbcon-probe.sh`): two NMIs after readiness leave the panel byte-identical on a boot where the appliance started exactly once. Building it found one defect and fixed it — the unit was `Type=notify` and nothing in the crate ever sent `READY=1`, so `aobs/src/notify.rs` now does.

**What still lags, and all of it is Rust:**

- `aobs/src/fail.rs` carries four variants and the pre-split `AOBS-E02`, whose copy blames legacy BIOS — a cause ADR-0016 falsified. `docs/specs/06-codes.md` §5 splits it into `E02`/`E05`/`E06` and adds `E00`, which the wrapper already prints.
- `aobs/src/console.rs`'s doc comment still explains the channel through `simpledrm` and ADR-0009.
- Nothing implements the panel-mode policy, the six-output bound, or the refusal codes — those are an implementation session's, and the spec names them.

**`docs/specs/` is the authority, not the tree.** Reconcile before building on any of it.

**`docs/specs/` is the authority — build from it.** The rule it states about itself governs here too: *if you find yourself deciding something the spec does not answer, that is a ticket, not a gap in the prose to fill in with judgement. Say so and stop.* The exception is the routine mechanics of Rust — module names, error enum shapes, function signatures — which are yours.

**The map is [issue #1](https://github.com/allisson/aobs/issues/1)**, and it is complete. It is no longer a work queue; it is the index of *why*, one line per decision, each linking the ticket whose resolution comment holds the full argument. Read the relevant resolution before reopening a settled question — the map's one-liner is a pointer, not the reasoning. An effort past this destination gets its own map, via `/wayfinder`, rather than reopening this one.

**Research findings** live in `docs/research/`, one file per resolved ticket, every claim carrying a source URL. Read the relevant file before reopening a question it already answers.

**Deliberately unfinished:** eleven owed measurements and eight verification obligations, listed in `docs/specs/00-overview.md` under *What is still owed*. Each is a number that was derived rather than measured, or a claim read from a specification rather than checked against the dependency. None blocks implementation; all block the release gate.

## Settled — do not silently revisit

These came out of grilling and research. Reopening one is a deliberate act with a reason, not a drive-by.

- **Slint, not Tauri.** Tauri was the original premise and lost on measurement: 268 packages / 650 MiB against Slint's 22 / 21 MiB, and `getUserMedia` cannot work in a stock Tauri app on Linux. The UI is Slint on `backend-linuxkms-noseat` + `renderer-software`, with no X server, no compositor and no seat daemon. See `docs/research/05-tauri-viability.md`. (The *22 / 21 MiB* is now stale in our favour and owed as a measurement — `seatd` and `libseat1` left with ADR-0016.) The licence question this raised is settled: **the repo is GPL-3.0-only**, which is what Slint's GPL option requires and what removes an unresolvable ambiguity in its royalty-free licence. See `docs/adr/0001-gpl-3-0-for-the-slint-ui-toolkit.md`.
- **The display path is two tiers**, chosen at runtime by Slint's own `or_else`: a DRM dumb buffer where the machine has a DRM device, `/dev/fb0` via `efifb` where it does not. `simpledrm` — ADR-0009's mechanism — **does not exist on Debian**, which is what falsified it. `amdgpu`, `xe` and `radeon` are deleted from the image because firmware-less they take the framebuffer aperture and then fail. UEFI-only stands, but on build-and-test surface rather than on "no display path exists". See `docs/adr/0016-two-tier-display-path.md`; ADR-0009 is kept as a superseded record because *how* it was wrong is the standing rule's whole point.
- **The appliance answers its own power button, and the app dies before the machine does.** No D-Bus, so no `systemd-logind`: the power button is `KEY_POWER` on its own evdev node, read directly rather than through Slint's key path (Slint delivers it as a bare NUL, which any unnamed key also produces). *End the session* is the app exiting 42 — `SuccessAction=poweroff` takes the machine down **after** the process is dead and `init_on_free` has poisoned its pages, which is what makes the RAM wipe unconditional. Never replace this with `systemctl poweroff` or `reboot(2)`; both leave the seed in RAM while the machine goes down. *Restart* is `exit 0` and a fresh process, not a reboot. See `docs/adr/0017-the-appliance-answers-its-own-power-button.md`.
- **Air-gapped by construction.** The appliance has no network stack, no cloud, no sync, no broadcasting, no telemetry, no update check. Every feature is designed to work with the machine's networking physically absent.
- **QR is the only data channel**, both directions, using BC-UR / UR2 (`ur:crypto-psbt`). The physical keyboard handles seed import and passphrase entry. QR decoding happens in Rust (`v4l` → `rqrr`), never in a webview.
- **Single-sig only** across BIP44/49/84/86, mainnet plus testnet/signet.
- **Amnesic.** State lives in RAM for one session. There is no config file, no wallet database, no transaction history, no cache.
- **Backup crypto**: Argon2id m=64 MiB/t=3/p=4 → ChaCha20-Poly1305 over the BIP-39 entropy. The user cannot choose the password; it is 8 words drawn independently from the EFF long list, ASCII-space separated. It ships, narrowed: offered only after the mnemonic is recorded, and displayed only after the user types the 8 words back correctly. See `docs/adr/0007-encrypted-backup-ships-narrowed.md`.
- **One wallet per boot**, enforced by a `OnceLock` rather than by a test — no switch, no unload, no idle timeout, and restart is the sanctioned way to reach a different wallet. Signing is unlimited within a session, but only the most recently signed transaction is re-displayable. See `docs/adr/0010-one-wallet-per-boot.md`.
- **Six outputs, and a seventh is a refusal.** The review panel is non-scrolling, holds six rows in the 800×600 minimum canvas, and payment and change both count. Do not "fix" this by scrolling, clipping or summarising the remainder — Coldcard's `MAX_VISIBLE_OUTPUTS = 10` plus *"plus N smaller output(s), not shown here"* is the compromise our larger screen exists to avoid, and paging turns the limit into 200 pages nobody walks. Named cost: a batched payout above six outputs is split by the user. See `02-core.md` §7 and `04-screens.md` §11.2.
- **The network is a load parameter**, not a property of a seed: a two-state selector beside the passphrase, mainnet preselected, stated for a restore rather than asked. Testnet/signet sessions look identical to mainnet ones by design. See `docs/adr/0015-network-is-a-load-parameter.md`.

## Threat model

Defended: a compromised online host feeding malicious PSBTs, hostile bytes arriving over the QR channel, theft of the machine or boot media after shutdown.

Out of reach and openly so: malicious firmware, hardware implants, cold-boot and DMA attacks by a present adversary, cameras in the room.

The consequence that shapes the most code: **the transaction review screen is the mitigation.** If the user cannot verify what they are signing, no other property matters.

## Rules that bite while coding

The full list is `docs/specs/00-overview.md` under *Standing rules* — nine of them, and breaking one silently invalidates a chain of tickets. The ones that come up most:

- **Re-derive, never trust.** A PSBT's BIP32 derivation paths are an attacker-supplied assertion. Change outputs are re-derived from our own key material and byte-compared against the `scriptPubKey`. Every surveyed signer does this; so do we.
- **Everything crossing the QR boundary is hostile input.** `ur-rs` adopts an attacker-controlled `seqLen` and allocates on it, so limits are clamped at our call site. The PSBT parser and the UR decoder carry fuzz targets we write ourselves.
- **Secrets are wrapped in zeroizing types** and zeroized at session end. Secret material stays out of logs, error messages, and `Debug` output.
- **Coverage bar**: 95% production code, 98%+ on security-critical components, plus fuzzing, property-based tests, and the BIP test vectors. The spec names which components carry the 98% bar.
- **Verify the shipped artifact, not just the source.** Coldcard shipped a software PRNG for five years because a build-integration defect broke the linkage while the source stayed correct. Tests that only assert against the source tree would have passed.
