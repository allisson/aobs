//! `aobs-core` — everything that decides something, and nothing that touches hardware.
//!
//! BIP39, derivation, PSBT validation and signing, entropy mixing, backup crypto, UR
//! encode/decode, the review model and the watch-only export model all land here as
//! modules. None of them exists yet: the walking skeleton
//! ([#39](https://github.com/allisson/aobs/issues/39)) builds the boot layer first,
//! because the boot layer is where the unproven claims are.
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
