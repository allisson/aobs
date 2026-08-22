//! Signing (`02-core.md` §8).
//!
//! **Add partial signatures and remove nothing. Do not finalize.** BIP-174 separates Signer from
//! Combiner and Finalizer, and those roles mean editing a document the coordinator authored and
//! expects back. Stripping `non_witness_utxo` was the tempting saving and is refused here as it
//! is in the spec: it is a change that fails at *their* end, which is the one end we have no
//! channel to hear from. **Named cost: our output is as large as their input.**
//!
//! **The nonce is RFC6979's and nothing here chooses it.** `secp256k1`'s ECDSA path is
//! deterministic by construction, and the taproot path reaches
//! `Secp256k1::sign_schnorr_no_aux_rand`, which is BIP-340 with 32 zero bytes of auxiliary
//! randomness — the form BIP-341's own key-path vectors were generated in, which is why they
//! reproduce here byte for byte. Two consequences follow and both are load-bearing elsewhere:
//! the Dark Skippy class is closed, and **a re-sign is byte-identical**, which is what makes
//! `04-screens.md` §11.5's one re-display slot a safety net rather than a promise.
//!
//! **Which arm of `secp256k1` gets used is a feature flag, not a call site.** `Psbt::sign`
//! reaches `sign_schnorr` with fresh auxiliary randomness when `rand-std` is enabled anywhere in
//! the graph, and `sign_schnorr_no_aux_rand` when it is not. Nothing in this workspace enables
//! it, and [`tests::signing_twice_produces_the_same_bytes`] is the alarm if a feature
//! unification ever does — a non-deterministic signature would still verify, so no other test
//! would notice.
//!
//! **[`sign`] cannot fail, and that is a designed property rather than a hope.** It takes an
//! [`Accepted`] — the only way to hold one is to have run every check — and every precondition
//! `Psbt::sign` has was established there: an input's spent output exists and its `vout` is in
//! range (`AOBS-R02`), its script type is one of four we model and a taproot input declares its
//! key path in full (`AOBS-R05`), and its sighash commits to everything (`AOBS-R03`). So there is
//! no failure arm for a caller to handle and no refusal code for one to carry.
//!
//! **And it promises that it signed what the wallet owns**
//! ([#113](https://github.com/allisson/aobs/issues/113), `02-core.md` §8a). *At least one
//! signature* was the claim §8 could not make while an accepted input could still be unsignable —
//! the shape being a taproot input whose key-path claim the signing path would never reach. That is
//! now `crate::psbt`'s business: an input's claim is read out of the map its family is signed from,
//! so *ours* and *signable* are one question, and the set of inputs the byte-compare found ours
//! travels on the [`Accepted`] for this function to assert against. A document that came back with
//! nothing in it under a screen reading *Signed* is the failure this closes.
//!
//! **The promise is the delta, and one refusal is what made it sayable**
//! ([#115](https://github.com/allisson/aobs/issues/115)). #113 could only assert it of the document
//! going out, because `Psbt::sign` declines a taproot key path whose `tap_key_sig` is already set:
//! a signature that *arrived* satisfied the assertion, and a hostile PSBT could therefore be
//! reviewed, held and handed back unchanged under a screen reading *Signed*. `AOBS-R17` removes
//! that shape from the accepted set — an input arriving with a signature in any of five fields is
//! refused before any key material — so this function can assert both halves: every input the
//! wallet owns **arrived unsigned and comes back signed.**
//!
//! **And *signed* names one field per family, not either of two**
//! ([#117](https://github.com/allisson/aobs/issues/117)). `partial_sigs` for BIP44/49/84,
//! `tap_key_sig` for BIP86 — `02-core.md` §7 rule 6 one layer down, and the same asymmetry
//! `crate::psbt` already respects when it reads an input's *claim*. The disjunction that stood here
//! before held only because `Psbt::sign` dispatches on the `scriptPubKey` and `AOBS-R17` refuses a
//! `partial_sigs` entry that arrived, neither of which it said; the family the check computed now
//! travels on the [`Accepted`] so the assertion can state the rule instead of resting on them.

use core::convert::Infallible;

use bitcoin::bip32::{DerivationPath, Xpriv};
use bitcoin::psbt::{GetKey, KeyRequest, Psbt};
use bitcoin::secp256k1::{Secp256k1, Signing};
use bitcoin::PrivateKey;

use crate::derive::Wallet;
use crate::psbt::{Accepted, InputScript, OurInput};

/// Sign every input of the accepted transaction that is ours, and change nothing else.
///
/// The returned PSBT is `accepted.psbt` plus `partial_sigs` and `tap_key_sig` entries: no field
/// is removed, no field is rewritten, and `final_script_sig` and `final_script_witness` are left
/// absent, because finalizing is the coordinator's role and not ours.
///
/// # Panics
///
/// If `Psbt::sign` reports an error, or if any input `crate::psbt::validate` found ours arrived
/// already signed or comes back with no signature in the field its family is signed from. All
/// three mean a precondition that function is supposed to have established did not hold —
/// `06-codes.md` §5's `AOBS-E04` and not a refusal, because there is no refusal code for it and
/// there is nothing here that can fail without the crate being internally inconsistent. The
/// arrived-signed half is `AOBS-R17`'s job, which is why a hostile PSBT reaches that refusal rather
/// than this panic.
#[must_use]
pub fn sign(wallet: &Wallet, accepted: &Accepted) -> Psbt {
    let mut psbt = accepted.psbt.clone();

    let signed = wallet.with_master(|master| {
        let keys = OurPaths { master, wallet };
        psbt.sign(&keys, wallet.secp())
    });

    // `expect` rather than a match with a `panic!` of our own, which is this crate's house style
    // for an invariant established upstream (`derive.rs` does the same on every `derive_priv`).
    // The per-input `SignError` map it would format is program state, which 01-boot-layer.md §9
    // forbids *printing* — and nothing prints it: `main` silences the panic hook for exactly this
    // reason and `fail::halt` writes the diagnostic instead.
    let _ = signed.expect("a validated transaction has every precondition signing needs");

    // **And the claim §8a could not make** ([#113](https://github.com/allisson/aobs/issues/113)):
    // *every input this wallet owns comes back signed.* `Psbt::sign` reports an error only for a
    // precondition it could not evaluate; an input it silently declined is an `Ok` with nothing in
    // it, which is the shape that would put a document with no signature in it under a screen
    // reading *Signed*. What makes this sayable is that `crate::psbt` reads an input's claim out of
    // the map its family is signed from, so *ours* and *signable* are the same question asked once.
    //
    // **It is now the delta, which is what the screen actually claims**
    // ([#115](https://github.com/allisson/aobs/issues/115)). #113 could only assert it of the
    // document going out: `Psbt::sign` declines a taproot key path when `tap_key_sig` is *already*
    // set, so an added-a-signature assertion would have panicked on a PSBT arriving with 64 bytes
    // of nonsense in that field — `AOBS-E04`, a crash and a 24-word retype, on bytes an attacker
    // chooses. `AOBS-R17` removed that shape from the accepted set instead, so both halves can be
    // said, and asserting the first is what pins the refusal this one rests on.
    //
    // **The two halves are deliberately different predicates.** *Arrived unsigned* is `AOBS-R17`'s
    // own five-field test, shared with the check that refuses it rather than restated. *Comes back
    // signed* is **one** field — the one this input's family is signed from — so none of the other
    // four can stand in for it: not a `tap_script_sigs` entry, and not (which is what
    // [#117](https://github.com/allisson/aobs/issues/117) found) a `partial_sigs` entry on a
    // taproot input.
    //
    // **That asymmetry is §7 rule 6 one layer down, and it has to be said here.** The disjunction
    // this replaced — a signature in *either* field, for every input — was not wrong, and it was
    // only not wrong because of two facts stated nowhere near it: `Psbt::sign` dispatches on the
    // `scriptPubKey`, so it never reaches `bip32_sign_ecdsa` for a taproot input, and `AOBS-R17`
    // refuses one that arrives already carrying `partial_sigs`. Remove either and a taproot input
    // of ours comes back with an ECDSA signature, no key-path signature, and a passing assertion.
    // The family is not recomputed here for the reason it is not recomputed anywhere else in this
    // crate: `crate::psbt`'s structural walk classified it and it travels on the [`Accepted`].
    //
    // **And both are scoped to the inputs this call signs, where `AOBS-R17` is about every input.**
    // That is not the assertion falling short of the refusal: what this function promises is its own
    // delta, and for a foreign input it adds nothing and claims nothing, so a signature arriving
    // there is not a fact about anything said here. The wider rule is the validator's, asserted
    // where it lives — `psbt_tests.rs` on the input that is not ours, and §4's third fuzz invariant
    // on every plan.
    for &OurInput { index, script } in &accepted.ours {
        assert!(
            !crate::psbt::arrived_signed(&accepted.psbt.inputs[index]),
            "an input the validator accepted arrived already signed: {index}"
        );
        let input = &psbt.inputs[index];
        let signature_is_where_it_belongs = match script {
            InputScript::P2tr => input.tap_key_sig.is_some(),
            InputScript::P2pkh | InputScript::P2shP2wpkh | InputScript::P2wpkh => {
                !input.partial_sigs.is_empty()
            }
        };
        assert!(
            signature_is_where_it_belongs,
            "an input the validator found ours came back with no signature in the field its \
             family is signed from: {index}"
        );
    }

    psbt
}

/// The key source `Psbt::sign` asks: **our master key, at any path this wallet would scan.**
///
/// Two differences from the dependency's own `impl GetKey for Xpriv`, and both are decisions.
///
/// **The fingerprint is ignored**, which is `crate::psbt`'s rule for inputs applied one layer
/// down: *what makes an input ours is that we derive its `scriptPubKey`, and a coordinator that
/// filled the fingerprint in wrongly should not make a wallet unsignable.* `Xpriv::get_key`
/// answers only for a matching fingerprint, so a transaction accepted on that rule would come back
/// out with no signature in it at all. The fingerprint authorises nothing anywhere else in this
/// crate (standing rule 1) and it authorises nothing here.
///
/// **The path is bounded by [`Wallet`]'s own scanning rule**, not by the PSBT. The path in a
/// `KeyRequest` is attacker-supplied, and what this function returns is a private key, so the set
/// of paths it will derive at is decided by the module that owns what *ours* means — five
/// children, one of our four accounts on the loaded network, `path[-2] ∈ {0, 1}`, a normal final
/// index. Nothing outside that set can hold this wallet's money, so nothing outside it needs a
/// signature.
///
/// **The `PrivateKey` this hands back has no drop that clears it**, which is the dependency's
/// type and the same cost `Wallet::with_master` already records for `Xpriv`. Standing rule 9
/// applies: nothing here claims a freed page is observably clean.
struct OurPaths<'a> {
    master: &'a Xpriv,
    wallet: &'a Wallet,
}

impl GetKey for OurPaths<'_> {
    /// Nothing can go wrong: a request we do not answer is `None`, and a derivation that fails
    /// is a path outside the set above, which is also `None`.
    type Error = Infallible;

    fn get_key<C: Signing>(
        &self,
        request: KeyRequest,
        secp: &Secp256k1<C>,
    ) -> Result<Option<PrivateKey>, Self::Error> {
        // `KeyRequest` is `#[non_exhaustive]`, so the catch-all is required rather than lazy —
        // and *not answering* is the right default for a request whose shape we have not read.
        let KeyRequest::Bip32((_, path)) = request else {
            return Ok(None);
        };
        Ok(self.derive(&path, secp))
    }
}

impl OurPaths<'_> {
    /// The private key at `path`, or `None` if this wallet would never look there.
    fn derive<C: Signing>(&self, path: &DerivationPath, secp: &Secp256k1<C>) -> Option<PrivateKey> {
        if !self.wallet.scannable_path(path) {
            return None;
        }
        Some(
            self.master
                .derive_priv(secp, path)
                .expect("a scannable path is five normal-or-hardened children")
                .to_priv(),
        )
    }
}

#[cfg(test)]
#[path = "sign_tests.rs"]
mod tests;
