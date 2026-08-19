//! `aobs-core` — everything that decides something, and nothing that touches hardware.
//!
//! BIP39, derivation, PSBT validation and signing, entropy mixing, backup crypto, UR
//! encode/decode, the review model and the watch-only export model all land here as
//! modules. Five of them exist: [`secret`], [`entropy`] and [`bip39`]
//! ([#70](https://github.com/allisson/aobs/issues/70)), then [`derive`] and the address half
//! of [`format`] ([#71](https://github.com/allisson/aobs/issues/71)), whose amount half arrived
//! with the writing rules ([#100](https://github.com/allisson/aobs/issues/100)) — but not the
//! review model those numbers come from. The rest do not — the walking
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

#![forbid(unsafe_code)]
#![warn(missing_docs)]

pub mod bip39;
pub mod derive;
pub mod entropy;
pub mod format;
pub mod secret;
