//! `05-testing-and-release.md` §4's second target: **the PSBT parser on raw bytes**.
//!
//! It drives the whole inbound path — `Psbt::deserialize`, every structural check behind it, and
//! since [#80](https://github.com/allisson/aobs/issues/80) the derivation check and the review
//! model too — on arbitrary bytes, which is what the QR boundary hands us after the fountain
//! decoder is done (standing rule 2: everything crossing that boundary is hostile input).
//!
//! **Raw bytes is what distinguishes it from the `validator` target**, which generates PSBTs.
//! Almost everything the mutator produces here dies at the magic bytes, and that is the surface
//! being fuzzed: the parser, on input nobody shaped.
//!
//! **What it asserts.** No panic and no unbounded allocation, the two §4 names — the allocation
//! half is `ci/check-fuzz.sh`'s `-malloc_limit_mb`, because a limit libFuzzer enforces is worth
//! more than one we assert after the fact. Plus two invariants that cost nothing here and would
//! otherwise want a test each per shape the fuzzer finds: an accepted transaction never carries
//! more outputs than the panel holds, and re-serialising it reproduces the bytes it was parsed
//! from — §7's *preserved byte-for-byte*, asserted against inputs nobody authored.

#![no_main]

use std::sync::OnceLock;

use libfuzzer_sys::fuzz_target;

use aobs_core::bip39::Mnemonic;
use aobs_core::derive::{Network, Wallet};
use aobs_core::psbt::validate;
use aobs_core::secret::{Entropy, Passphrase};

/// Our own key material, derived once: `validate` needs a wallet for the derivation check, and
/// `Wallet::load` is PBKDF2 over 2 048 HMAC rounds plus four hardened derivations.
///
/// Which wallet it is does not matter to this target — bytes that reach the derivation check at
/// all are already far past what it is fuzzing.
fn wallet() -> &'static Wallet {
    static WALLET: OnceLock<Wallet> = OnceLock::new();
    WALLET.get_or_init(|| {
        let mnemonic = Mnemonic::from_entropy(&Entropy::new(&[0u8; 16]).expect("16 bytes fit"))
            .expect("16 bytes is an accepted length");
        Wallet::load(
            &mnemonic,
            &Passphrase::new("").expect("empty fits"),
            Network::Mainnet,
        )
    })
}

fuzz_target!(|data: &[u8]| {
    let wallet = wallet();

    if let Ok(accepted) = validate(wallet, data) {
        assert!(
            accepted.psbt.unsigned_tx.output.len() <= 6,
            "accepted a transaction the review panel cannot hold"
        );
        // The bytes we were handed may carry trailing garbage the dependency ignores, so the
        // fixed point is the accepted PSBT's own serialisation rather than `data`.
        let round_trip = accepted.psbt.serialize();
        assert_eq!(
            validate(wallet, &round_trip).map(|again| again.psbt.serialize()),
            Ok(round_trip.clone()),
            "an accepted transaction did not survive its own serialisation"
        );
    }
});
