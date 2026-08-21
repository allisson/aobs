# aobs v1 — implementation spec: overview

**Status:** closed for v1. Every decision here came out of a map ticket
([issue #1](https://github.com/allisson/aobs/issues/1) and its children); the ticket holds the full
argument, this spec holds what to build. Where the two disagree, the ticket is right and the spec is
a bug.

**Rule for an implementation session:** if you find yourself deciding something this spec does not
answer, that is a ticket on the map, not a gap in the prose to fill in with judgement. Say so and
stop. The one exception is the routine mechanics of Rust — module names, error enum shapes, function
signatures — which are yours.

## What is being built

`bitcoin-signer-amd64.iso`: a bootable Debian LiveCD that turns a commodity amd64 machine into an
offline Bitcoin signing appliance for one session. The user boots it, creates or loads a single-sig
wallet, exports watch-only key material, verifies receive addresses, signs PSBTs, and shuts down.
Nothing survives the session.

The product exists for one reason, and it decides every trade in this spec:

> aobs trades away every hardware guarantee the dedicated signers have — secure element, rate
> limiting, physical air gap, hardware entropy, attestation — for the one thing none of them can buy
> at any price: a screen and a CPU big enough to show the user the entire transaction, in full,
> without truncation or paging.
> — [#3](https://github.com/allisson/aobs/issues/3)

## The spec set

| File | Covers |
|---|---|
| `00-overview.md` | This file: scope, architecture, the standing rules, what is still owed. |
| `01-boot-layer.md` | live-build, kiosk, no network, no swap, RAM wipe, kernel cmdline, hardware floor, crash reporting. |
| `02-core.md` | `aobs-core`: entropy, BIP39, derivation, PSBT validation and signing, review model, backup crypto, watch-only export, secret types. |
| `03-transport.md` | The QR boundary in both directions: bounds, scanner, decoder discipline, outbound animation. |
| `04-screens.md` | Every screen and the flow between them, in the shell. |
| `05-testing-and-release.md` | Coverage bar, vectors, fuzz targets, adversarial corpus, CI gates, release gates, signing and distribution. |
| `06-codes.md` | The code registry: the two code spaces, what makes a code stable with no update mechanism, and every startup-failure and refusal code. |

ADRs in `docs/adr/` carry the *why* for the decisions a newcomer would otherwise read as arbitrary —
including one, ADR-0009, kept as a superseded record because *how* it was wrong is worth reading. `CONTEXT.md` is the glossary.

## Architecture

Two crates, and no more ([#10](https://github.com/allisson/aobs/issues/10), ADR-0004).

```
aobs-core   BIP39, derivation, PSBT validation and signing, entropy mixing,
            backup crypto, UR encode/decode, payload class checking,
            the review model, the watch-only export model.
            No Slint. No v4l. No getrandom. No filesystem. No clock.

aobs        The binary. Slint UI, camera loop, the raw getrandom syscall,
            seat and input handling, the OnceLock holding the session wallet.
```

The boundary is a single question — *does this touch hardware* — and everything else is a module
inside core. The dependency direction is the enforcement: `aobs-core/Cargo.toml` names neither
`slint` nor `v4l`, checked mechanically in CI.

**Every seam is a data boundary, not an interface. Zero traits, zero mocks.**

| Seam | Shape |
|---|---|
| Camera | Core never sees a camera or a frame. The shell runs `v4l` → `rqrr` and hands core decoded strings. |
| CSPRNG | Core never calls `getrandom`. Seed generation takes `csprng_32: [u8; 32]` as a parameter. |
| Screen | Core produces a review *model*; the shell renders it. Tests assert on the model, never on pixels. |
| Clock | Core takes no clock. Elapsed seconds on a screen are the shell's business. |

## Standing rules

These are not advice. They are the rules the decisions were taken under, and breaking one silently
invalidates a chain of tickets.

1. **Re-derive, never trust.** A PSBT's BIP32 derivation paths are an attacker-supplied assertion.
   The byte-compare of a re-derived `scriptPubKey` is the sole authority. The 4-byte fingerprint is a
   hint and never authorises anything.
2. **A warning is only legitimate when the user knows something we don't.** Everything else is a
   refusal, and a refusal happens before a review screen is drawn. Exactly one advisory warning
   exists in v1.
3. **A refusal offers only discard.** No "proceed anyway", not behind a confirmation, not in an
   advanced menu.
4. **The shell contains no decision about money and no branch on a validation outcome.** It
   marshals. This is what keeps the shell honestly outside the coverage gate.
5. **Secret material lives in types that implement neither `Clone` nor `Copy`, and use no `String`
   and no growable `Vec`.** Fixed-capacity buffers allocated at final size, `ZeroizeOnDrop`, `Debug`
   hand-written as `[redacted]`.
6. **Everything crossing the QR boundary is hostile input**, bounded at our call site before any
   third-party parser sees it.
7. **Verify the shipped artifact, not the source tree.** Coldcard shipped a software PRNG for five
   years with correct source and a broken linkage; a test that only reads the repo is the test that
   passed for five years.
8. **State the fact, invent nothing.** No fabricated progress bars, no green ticks, no
   "are you sure?", no self-reported provenance dressed as a security claim.
9. **We do not claim a test observes a freed page.** Carried forward verbatim so nobody later adds
   a comforting fake.

## Threat model

**Defended:** a compromised online host feeding malicious PSBTs (change substitution, fee inflation,
amount spoofing), hostile bytes arriving over the QR channel, theft of the machine or boot media
after shutdown, casual physical access between sessions.

**Out of reach, and openly so:** malicious firmware or BIOS, hardware implants, DMA and cold-boot
attacks by a present adversary, cameras in the room, shoulder surfing. Several decisions in this
spec — nothing is masked, no idle timeout, no lock screen — follow from that exclusion, and
reversing the exclusion reopens them.

**Structurally unavailable:** rate limiting, PIN counters, wipe-on-failure, duress wallets. Amnesia
forecloses them; Jade buys rate limiting only by requiring network connectivity, which is the
property aobs exists to have. All security reduces to seed entropy plus the user's physical backup
discipline.

## Scope

**In v1:** single-sig across BIP44 / BIP49 / BIP84 / BIP86 (key-path), mainnet and testnet/signet,
account 0 only. Create a wallet, import a mnemonic, restore an encrypted backup, load a passphrase,
export watch-only descriptors, verify a receive address, review and sign a PSBT, hand the signed
PSBT back.

**Out of scope, ruled rather than deferred:** multisig, descriptor and wallet-policy registration,
taproot script-path, miniscript, USB and SD data transfer, broadcasting, transaction history, an
address book, any network stack, non-amd64, bit-for-bit reproducible builds (v2 goal), and defence
against firmware implants or cold-boot extraction.

## What is still owed

None of these blocks implementation. All of them block the release gate
(`05-testing-and-release.md` §6), and each is a number that was *derived* rather than measured.

| Owed | Source |
|---|---|
| Entropy readiness delay under `random.trust_cpu=off` on real hardware (derived: 1–16 s). | [#8](https://github.com/allisson/aobs/issues/8), [#24](https://github.com/allisson/aobs/issues/24) |
| RAM floor confirmed against the built image (provisional: 2 GiB min, 4 GiB recommended). | [#24](https://github.com/allisson/aobs/issues/24) |
| Package count and installed size of the GUI floor now that `seatd` and `libseat1` are gone (stale: 22 packages / 21 MiB, measured with both present). | [#49](https://github.com/allisson/aobs/issues/49) |
| Argon2id wall clock on low-end amd64 (derived: ~1.2–2.5 s at 64 MiB). | [#6](https://github.com/allisson/aobs/issues/6) |
| Address-search time across 4 accounts × 2 branches × 1000 indices (8,000 derivations). | [#21](https://github.com/allisson/aobs/issues/21), [#27](https://github.com/allisson/aobs/issues/27) |
| That the four-descriptor `crypto-account` payload fits one QR at ECC H (estimated ~460 B CBOR → ~1,000 UR chars). | [#27](https://github.com/allisson/aobs/issues/27) |
| That a phone camera reads our v27 output at arm's length (v40 is the documented fallback — and the maximum UR fragment length is re-derived from the new cap, `03-transport.md` §9). | [#30](https://github.com/allisson/aobs/issues/30) |
| The capture-resolution floor for reading an inbound v40 symbol. | [#31](https://github.com/allisson/aobs/issues/31) |
| That the predicted signed-transaction vsize the fee rate divides by matches a real signed transaction across all four script types (derived: a weight-unit sum charging each ECDSA input a 71-byte signature element, so it errs high by a fraction of a percent — `04-screens.md` §11.2.1). | [#100](https://github.com/allisson/aobs/issues/100) |

**Discharged.** Three rows have left this table, and all three left it as *standing* assertions rather
than one-off readings — printed by the appliance and checked by `ci/qemu-boot.sh` on every boot that
draws, in the geometry CI already boots by default. They are the only ones that could: the appliance is
the thing that knows the answer, and every other row on this table asks about hardware or a person.

- *That two columns of 12 words fit the 800×600 minimum canvas at the settled type size*: **440
  logical px required against 458 available**, as `AOBS_WORDS`
  ([#72](https://github.com/allisson/aobs/issues/72), `04-screens.md` §3).
- *That six output rows fit the minimum canvas non-scrolling, below the stacked money facts*: **447
  against 458**, as the first half of `AOBS_REVIEW`
  ([#81](https://github.com/allisson/aobs/issues/81), `04-screens.md` §11.2). **The six-output cap
  therefore stands, and is now fixed rather than provisional.**
- *That a 62-character P2TR payment address, 4-character grouped with §0's sub-cell gaps, holds one
  line in the minimum canvas*: **699 px required against 752 available**, as the second half of the
  same line ([#81](https://github.com/allisson/aobs/issues/81)). §0's derived 698 was right to within a pixel — and the
  width of a 4-character group is now **measured from the font on the shipped image** rather than
  computed from a font table, which is what makes this an assertion about the ISO instead of a
  re-run of our own arithmetic. The prototype's *nothing in-tree has been measured against the widest
  address class we ship* no longer holds: the panel renders 62 characters at the floor on every boot
  CI takes.

Eight verification obligations, distinct from measurements:

- **The fbdev display tier on real firmware**, verified only under QEMU + `ramfb` so far: that
  `efifb`'s reported pixel format negotiates against the renderer's five accepted arms, and that
  detaching `fbcon` while the app draws behaves as it did in QEMU — the vtcon name and the format both
  came from that kernel and that firmware ([#49](https://github.com/allisson/aobs/issues/49),
  [#52](https://github.com/allisson/aobs/issues/52), ADR-0016).
- **The residual aperture-removal class is unquantified, and accepted by name**: a driver the image
  *keeps* — `i915`, `nouveau`, `ast`, `mgag200`, `gma500`, `udl`, `hyperv` — that removes the
  framebuffer aperture and then fails for a reason unrelated to firmware would leave no display and no
  channel. Only the firmware failures were traced ([#47](https://github.com/allisson/aobs/issues/47));
  `gma500` is the most likely instance. The tested-hardware list is the only instrument against it.

- **That nothing secret is written to a filesystem.** `01-boot-layer.md` §5's RAM-wipe story is
  `init_on_free=1` and nothing else, and it rests on this absence rather than on a mechanism — the
  overlayfs upper dir is explicitly not claimed, because a normal shutdown never frees it
  ([#62](https://github.com/allisson/aobs/issues/62)). The check is `docs/qa-checklist.md`'s row: after
  a full session, the writable layer holds nothing the app wrote. Until it is run, the strongest claim
  in that section is an assumption.

- **The power button on real firmware.** [#89](https://github.com/allisson/aobs/issues/89) measured
  it under QEMU's ACPI implementation only — `Power Button` / `KEY_POWER` reaching an unprivileged
  app — and the device name and key code came from that kernel and that firmware, the same limit the
  fbdev tier carries above (ADR-0017).
- **That the exit-status contract fires end to end.** `SuccessExitStatus=42`,
  `RestartPreventExitStatus=42` and `SuccessAction=poweroff` are accepted by the image's own systemd
  (`systemd-analyze verify`, `257.13-1~deb13u1`), but nothing in the crate exits 42 yet, so no boot
  has ever powered off through them. It is what `04-screens.md` §13's *end the session* rests on
  ([#69](https://github.com/allisson/aobs/issues/69), ADR-0017).

- **Pin whether BIP-174 explicitly forbids a Signer removing fields**, rather than resting on the
  role separation alone ([#30](https://github.com/allisson/aobs/issues/30)).
- **Nunchuk's `crypto-account` support is unverified**, not assumed
  ([#27](https://github.com/allisson/aobs/issues/27)).
- **That the master fingerprint is identical on every network** is read from the BIP-32 text, not
  measured against `bitcoin` 0.32.x. The identity screen's only network signal rests on it, so it
  carries an assertion in the suite ([#34](https://github.com/allisson/aobs/issues/34)).

Two recorded revisit triggers, which are not v1 work:

- If Specter Desktop accepts `account-descriptor` (40311), the watch-only encoding flips to it.
- If Specter Desktop ever accepts BBQr, the PSBT transport decision is worth re-running — but
  establish first which `WalletModel` Sparrow assigns to an aobs keystore imported by QR.
