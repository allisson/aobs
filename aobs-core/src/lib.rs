//! `aobs-core` — everything that decides something, and nothing that touches hardware.
//!
//! BIP39, derivation, PSBT validation and signing, entropy mixing, backup crypto, UR
//! encode/decode, the review model and the watch-only export model all land here as
//! modules. Seven of them exist: [`secret`], [`entropy`] and [`bip39`]
//! ([#70](https://github.com/allisson/aobs/issues/70)), then [`derive`] and the address half
//! of [`format`] ([#71](https://github.com/allisson/aobs/issues/71)), whose amount half arrived
//! with the writing rules ([#100](https://github.com/allisson/aobs/issues/100)) — and
//! [`entry`], the word-entry component the retype and three later screens drive
//! ([#73](https://github.com/allisson/aobs/issues/73)), and [`psbt`], the whole rejection
//! policy: its structural half first ([#79](https://github.com/allisson/aobs/issues/79)), then
//! the derivation check and the review model those numbers are written from
//! ([#80](https://github.com/allisson/aobs/issues/80)). The rest
//! do not — the walking
//! skeleton ([#39](https://github.com/allisson/aobs/issues/39)) built the boot layer first,
//! because the boot layer is where the unproven claims were.
//!
//! Every seam into this crate is a data boundary — no traits, no mocks (ADR-0004):
//!
//! | Seam | Shape |
//! |---|---|
//! | Camera | The shell hands us decoded strings. We never see a frame. |
//! | CSPRNG | Seed generation takes `csprng_32: [u8; 32]` as a parameter. |
//! | Screen | We produce a review *model*; the shell renders it. |
//! | Clock | We take none. |
//!
//! [`psbt::validate`] is where the screen row is enforced rather than promised: it takes hostile
//! bytes and a [`derive::Wallet`] and returns either a refusal or a [`psbt::Review`], so there
//! is no way to reach something drawable without having run the derivation check.

#![forbid(unsafe_code)]
#![warn(missing_docs)]

pub mod bip39;
pub mod derive;
pub mod entropy;
pub mod entry;
pub mod format;
pub mod psbt;
pub mod secret;

/// The adversarial corpus and the `AOBS-R##` registry bijection
/// (`05-testing-and-release.md` §5, `06-codes.md` §7).
///
/// At the crate root rather than beside one module because the registry spans several: the
/// structural refusals are [`psbt`]'s, and the QR boundary's and the backup's will add their
/// cases to the same table.
#[cfg(test)]
#[path = "corpus_tests.rs"]
mod corpus;
