# ADR-0004 — Two crates, every seam a data boundary, zero traits and zero mocks

- **Status**: accepted
- **Date**: 2026-08-15
- **Decides**: [#10 — Module boundaries and test strategy for the coverage bar](https://github.com/allisson/aobs/issues/10)

## Context

The project asserts 95% production-code coverage and 98%+ on security-critical components.
Requirements of that kind are met by architecture or not at all — a test strategy bolted onto a
shape that resists testing produces a number, not a guarantee.

The prior-art survey supplied the sharpest constraint: Coldcard disclosed that a build-integration
defect resolved seed generation to a software PRNG for five years. **The source was correct; the
linkage was wrong.** No amount of code review catches that. Only a test that runs against the
shipped artifact does.

## Decision

**Two crates, and no more.**

- **`aobs-core`** — BIP39, derivation, PSBT validation and signing, entropy mixing, backup crypto,
  UR encode/decode, the review model. No Slint, no `v4l`, no `getrandom`, no filesystem, no clock.
- **`aobs`** — the binary: Slint UI, camera loop, the raw `getrandom` syscall, seat and input.

The boundary is a single question — *does this touch hardware* — and everything else is a module
inside core. **The dependency direction is the enforcement**: `aobs-core/Cargo.toml` naming neither
`slint` nor `v4l` is mechanically checkable in CI, which is worth more than architectural intent in a
document.

**Every seam is a data boundary. No traits, no mocks, no test doubles.**

| Seam | Shape |
|---|---|
| Camera | The shell runs `v4l` → `rqrr` and hands core *decoded strings*. The seam is `&str`, so the whole ingestion path tests from a text fixture. |
| CSPRNG | Core takes `csprng_32: [u8; 32]` as a parameter. |
| Screen | Core produces a review *model*; tests assert on the model, never on pixels. |
| Clock | Core takes none. Nothing in it is time-dependent — no network, no expiry, no rate limiting. |

**This is not a stylistic preference. It is the mechanism by which 98% is reachable**, and it is the
difference between meeting the requirement and asserting a number at it.

## Consequences

- **Nine components carry the 98% bar**, and the ninth is deliberate: **address and amount
  formatting**. Formatting looks like presentation, but Coldcard's 2019 receive-path display
  manipulation was a vulnerability *in the display layer* — a chunking routine that drops a character
  defeats every check above it.
- **Region coverage, not line coverage.** Line coverage marks a partially-taken branch as covered,
  which would let the rejection policy report green with half its arms untested.
- **The shell is excluded from the coverage gate**, which is only honest under the rule that keeps it
  thin: *the shell contains no decision about money and no branch on a validation outcome; it
  marshals.* Later decisions repeatedly enforced this — the per-word comparison during the mnemonic
  retype, the fee-warning variant, and the payload-class check all moved into core for this reason.
- **Legitimate exclusions are exactly three:** derive-generated code, `unreachable!()` arms, and the
  shell. **Per-line coverage opt-outs in source are forbidden** — that meets a number by editing the
  denominator.
- **Zeroization is enforced by what the types don't implement:** no `Clone`, no `Copy`, no `String`,
  no growable `Vec`. A realloc leaves the old contents behind and no clone is ever zeroized. Tests
  cover only what is observable — a `ZeroizeOnDrop` trait-bound assertion and `Debug` redaction.
  **We do not claim a test observes a freed page**, and saying so is what later made
  one-wallet-per-boot (ADR-0010) the right call.
- **Coverage is necessary, not sufficient.** Fuzzing, BIP vectors, property tests and the QEMU
  provenance gate are separate gates. A repository can sit at 98% and still ship Coldcard's defect.

## Alternatives rejected

- **A six-crate workspace** (`aobs-psbt`, `aobs-bip39`, `aobs-qr`, …) — nothing external consumes
  them, Rust's module system already enforces the internal boundaries, and it buys a dependency graph
  to maintain in exchange for nothing.
- **Traits with one implementation, plus mocks** — buys testability we get for free from data seams,
  and costs an indirection a build change can silently re-resolve, which is exactly the Coldcard
  failure shape.
- **Hand-rolling the Bitcoin layer** — `bitcoin` 0.32.x and `secp256k1` are MIT/CC0 and
  GPL-3.0-compatible, and `secp256k1`'s RFC6979 deterministic nonces are the Dark Skippy mitigation
  for free. Writing our own nonce generation would be volunteering for the attack.
