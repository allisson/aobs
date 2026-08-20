//! `05-testing-and-release.md` §4's first target: **the fountain decoder through our clamping
//! wrapper**.
//!
//! It is the highest-value surface in the transport layer and **upstream ships no target for
//! it**: `ur`'s own fuzzing covers `bytewords_decode`, `bytewords_encode` and `ur_encode` only,
//! so the fountain decoder — the parser that adopts an attacker's `sequence_count` and allocates
//! on it — has never been fuzzed by anybody. That is the whole reason this file is a requirement
//! rather than a nicety (`03-transport.md` §1).
//!
//! **What §4 asks for, and where each half lives.**
//!
//! - *No panic* — libFuzzer, on an unwinding panic (`fuzz/Cargo.toml` pins
//!   `panic = "unwind"` for exactly this).
//! - *Termination* — libFuzzer's own timeout. There is no loop here but the one over the input,
//!   and [`Scanner::receive`] is straight-line code with no recursion, so a hang would be the
//!   dependency's.
//! - *No allocation above the transport bounds* — two halves, and neither is an assertion after
//!   the fact. `ci/check-fuzz.sh`'s `-malloc_limit_mb` aborts on a single allocation above the
//!   limit, which is the half that catches the 34 GB claim. The assertions below are the other
//!   half: they hold the *outcomes* to the bounds, so a clamp that stopped clamping fails here
//!   even when the resulting allocation is small enough to slip under the limit.
//!
//! **The signature is §4's: `Vec<&str>` — a sequence of decoded QR symbols**, which is exactly
//! what the shell hands core (ADR-0004: we never see a frame). One [`Scanner`] takes the whole
//! sequence, because the state the bounds protect is per-scan: the pinned stream identity and
//! the parts budget only exist across symbols.
//!
//! **Only [`Class::Psbt`] reaches the fountain decoder**, which is what this target is for. The
//! other two classes are single-part by rule and never touch it, so they are driven one symbol
//! at a time on a fresh scanner — the class check and the address bounds for free, with no
//! pretence that it is the same surface.

#![no_main]

use libfuzzer_sys::fuzz_target;

use aobs_core::ur::{
    Class, Outcome, Payload, Scanner, MAX_ADDRESS_LEN, MAX_MESSAGE_LEN, MAX_SEQUENCE_COUNT,
    PART_BUDGET,
};

/// Every accepted payload is inside the bound its class states, whatever path produced it.
fn check(payload: &Payload) {
    match payload {
        Payload::Transaction(bytes) | Payload::Backup(bytes) => {
            assert!(!bytes.is_empty(), "an empty message was accepted");
            assert!(
                bytes.len() <= MAX_MESSAGE_LEN,
                "a message of {} bytes passed the 64 KiB bound",
                bytes.len()
            );
        }
        Payload::Address(text) => {
            assert!(!text.is_empty(), "empty text was accepted as an address");
            assert!(
                text.len() <= MAX_ADDRESS_LEN,
                "{} bytes passed the address bound",
                text.len()
            );
            assert!(
                text.bytes().all(|byte| (0x20..=0x7e).contains(&byte)),
                "non-printable bytes passed the address filter"
            );
        }
    }
}

fuzz_target!(|parts: Vec<&str>| {
    let mut scanner = Scanner::new(Class::Psbt);
    let mut accepted = 0usize;

    for symbol in &parts {
        match scanner.receive(symbol) {
            Outcome::Received { parts, of } => {
                accepted += 1;
                // `of` is the attacker's `seqLen` after the clamp, and it is the denominator the
                // scanning screen draws — a value above the bound is both an unbounded
                // allocation in the dependency and a lie on the panel.
                assert!(of <= MAX_SEQUENCE_COUNT, "seqLen {of} passed the clamp");
                assert!(
                    parts <= of,
                    "{parts} fragments resolved out of a stream of {of}"
                );
                // The bound on *work*: a `Received` means a part reached the dependency.
                assert!(
                    accepted <= PART_BUDGET,
                    "{accepted} parts were taken in past the budget"
                );
            }
            Outcome::Complete(payload) => check(&payload),
            Outcome::Discarded(_) | Outcome::Refused(_) => {}
        }
    }

    for symbol in &parts {
        for class in [Class::Address, Class::Backup] {
            if let Outcome::Complete(payload) = Scanner::new(class).receive(symbol) {
                check(&payload);
            }
        }
    }
});
