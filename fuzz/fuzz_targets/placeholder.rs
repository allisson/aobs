//! The placeholder target: it proves the harness, and it is deleted by the first real one.
//!
//! `05-testing-and-release.md` §4 names three targets we write ourselves — the fountain
//! decoder through our clamping wrapper, the PSBT parser on raw bytes, and the validator
//! — and none of the code they fuzz exists yet. This target exists so that when the first
//! of them lands, the only new thing is the target: the nightly toolchain, the sanitizer,
//! libFuzzer's link step and `ci/check-fuzz.sh` are already known to work end to end.
//!
//! It asserts nothing about aobs. A gate wired after the code is a gate negotiated with
//! the code it is supposed to judge, which is the whole reason this file is here early.

#![no_main]

use libfuzzer_sys::fuzz_target;

fuzz_target!(|data: &[u8]| {
    // Two total operations on attacker-shaped bytes. The assertion is deliberately one
    // that cannot fail: what is under test is the harness reaching this line at all, and
    // `cargo fuzz run` exiting non-zero when it panics is proved by the harness itself,
    // not by leaving a real defect in the tree.
    assert_eq!(data.len(), data.iter().count());
    let _ = core::str::from_utf8(data);
});
