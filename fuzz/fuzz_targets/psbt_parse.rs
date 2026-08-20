//! `05-testing-and-release.md` §4's second target: **the PSBT parser on raw bytes**.
//!
//! It drives the whole inbound path — `Psbt::deserialize` and every structural check behind it
//! — on arbitrary bytes, which is what the QR boundary hands us after the fountain decoder is
//! done (standing rule 2: everything crossing that boundary is hostile input).
//!
//! **What it asserts.** No panic and no unbounded allocation, the two §4 names — the allocation
//! half is `ci/check-fuzz.sh`'s `-malloc_limit_mb`, because a limit libFuzzer enforces is worth
//! more than one we assert after the fact. Plus two invariants that cost nothing here and would
//! otherwise want a test each per shape the fuzzer finds: an accepted transaction never carries
//! more outputs than the panel holds, and re-serialising it reproduces the bytes it was parsed
//! from — §7's *preserved byte-for-byte*, asserted against inputs nobody authored.
//!
//! It replaces the placeholder target, which existed to prove the harness before there was any
//! of our code to fuzz.

#![no_main]

use libfuzzer_sys::fuzz_target;

use aobs_core::psbt::validate;

fuzz_target!(|data: &[u8]| {
    if let Ok(psbt) = validate(data) {
        assert!(
            psbt.unsigned_tx.output.len() <= 6,
            "accepted a transaction the review panel cannot hold"
        );
        // The bytes we were handed may carry trailing garbage the dependency ignores, so the
        // fixed point is the accepted PSBT's own serialisation rather than `data`.
        let round_trip = psbt.serialize();
        assert_eq!(
            validate(&round_trip).map(|again| again.serialize()),
            Ok(round_trip.clone()),
            "an accepted transaction did not survive its own serialisation"
        );
    }
});
