//! `02-core.md` §8 and `05-testing-and-release.md` §2's **BIP-340 / BIP-341** row.
//!
//! **Two suites, and the split is what each one can pin.** The published vectors pin the
//! *arithmetic* — the taproot tweak, the BIP-341 sighash, and the BIP-340 signature over it — and
//! they are the only thing that can, because our own wallet's numbers are numbers we computed.
//! The end-to-end tests pin the *policy*: nothing removed, nothing finalized, at least one
//! signature, and the same bytes twice.
//!
//! **The vector files are committed verbatim rather than transcribed**, from
//! `github.com/bitcoin/bips` at `master`:
//!
//! * `vectors/bip340-test-vectors.csv` — `bip-0340/test-vectors.csv`.
//! * `vectors/bip341-wallet-test-vectors.json` — `bip-0341/wallet-test-vectors.json`.
//!
//! **One fact about the BIP-340 file had to be established rather than read**: only its index-0
//! row has all-zero auxiliary randomness, so it is the only row of that file our signing path can
//! reproduce — every other row was signed with `aux_rand` we do not use. What made the BIP-341
//! file the better suite is that **all seven of its key-path signatures were generated with 32
//! zero bytes of auxiliary randomness**, which is exactly `sign_schnorr_no_aux_rand`. That was
//! checked against an independent BIP-340 implementation before these tests were written, and it
//! is what makes seven cases available where the CSV offers one.

use bitcoin::bip32::Fingerprint;
use bitcoin::hashes::Hash as _;
use bitcoin::key::{Keypair, TapTweak as _};
use bitcoin::script::PushBytesBuf;
use bitcoin::secp256k1::{Message, Secp256k1, SecretKey, XOnlyPublicKey};
use bitcoin::sighash::{Prevouts, SighashCache, TapSighashType};
use bitcoin::taproot::TapNodeHash;
use bitcoin::{Psbt, ScriptBuf, TapSighash, Transaction, TxOut, Witness};

use super::sign;
use crate::corpus::{
    declare_input, from_hex, nonsense_schnorr_signature, our_key, our_path, our_spk, psbt,
    psbt_for, wallet, wallet_on,
};
use crate::derive::{Family, Network, Wallet};
use crate::psbt::{validate, Accepted, InputScript, OurInput};

const BIP340_VECTORS: &str = include_str!("vectors/bip340-test-vectors.csv");
const BIP341_VECTORS: &str = include_str!("vectors/bip341-wallet-test-vectors.json");

/// The whole inbound path, refusing to be refused — the only way to hold an [`Accepted`].
fn accept(wallet: &Wallet, psbt: &Psbt) -> Accepted {
    match validate(wallet, &psbt.serialize()) {
        Ok(accepted) => accepted,
        Err(rejection) => panic!("the fixture must be accepted, not {rejection:?}"),
    }
}

/// One honest single-family spend: one input, one payment to a stranger, the rest to the fee.
fn spend(family: Family) -> Psbt {
    let theirs = ScriptBuf::new_p2wpkh(&bitcoin::WPubkeyHash::from_byte_array([7u8; 20]));
    psbt(&[(family, 100_000)], &[(theirs, 90_000)])
}

// --- BIP-340, the one row we can reproduce -------------------------------------------------

/// BIP-340's index-0 vector: `sign_schnorr_no_aux_rand` **is** BIP-340 with 32 zero bytes of
/// auxiliary randomness, which is the claim `02-core.md` §8's determinism rests on.
#[test]
fn bip340_vector_zero_reproduces_byte_for_byte() {
    let row: Vec<&str> = BIP340_VECTORS
        .lines()
        .nth(1)
        .expect("the file has a header and rows")
        .split(',')
        .collect();
    assert_eq!(row[0], "0", "index 0 is the only all-zero-aux row");
    assert_eq!(
        row[3], "0000000000000000000000000000000000000000000000000000000000000000",
        "and this test is only valid while its aux_rand is zero"
    );

    let secp = Secp256k1::new();
    let secret = SecretKey::from_slice(&from_hex(row[1])).expect("a vector key is in range");
    let keypair = Keypair::from_secret_key(&secp, &secret);
    let message = Message::from_digest(
        from_hex(row[4])
            .try_into()
            .expect("a vector message is 32 bytes"),
    );

    let signature = secp.sign_schnorr_no_aux_rand(&message, &keypair);
    assert_eq!(signature.serialize().to_vec(), from_hex(row[5]));

    // And the public key the vector publishes is the one this key produces.
    let (xonly, _) = keypair.x_only_public_key();
    assert_eq!(xonly.serialize().to_vec(), from_hex(row[2]));
    secp.verify_schnorr(&signature, &message, &xonly)
        .expect("the vector says TRUE");
}

// --- BIP-341, the key-path suite -----------------------------------------------------------

/// One `keyPathSpending[0].inputSpending[n]` case, as the fields this suite reads out of it.
struct KeyPath {
    input_index: usize,
    internal_privkey: Vec<u8>,
    merkle_root: Option<TapNodeHash>,
    hash_type: u8,
    internal_pubkey: Vec<u8>,
    tweaked_privkey: Vec<u8>,
    sighash: Vec<u8>,
    witness: Vec<u8>,
}

/// BIP-341's `keyPathSpending[0]`: the transaction, its nine spent outputs, and the seven inputs
/// the file gives an expected key-path signature for.
fn bip341_key_path() -> (Transaction, Vec<TxOut>, Vec<KeyPath>) {
    let root: serde_json::Value =
        serde_json::from_str(BIP341_VECTORS).expect("the committed file is the BIP's own JSON");
    let case = &root["keyPathSpending"][0];

    let tx: Transaction = bitcoin::consensus::deserialize(&from_hex(
        case["given"]["rawUnsignedTx"].as_str().unwrap(),
    ))
    .expect("the vector transaction deserialises");

    let utxos: Vec<TxOut> = case["given"]["utxosSpent"]
        .as_array()
        .unwrap()
        .iter()
        .map(|utxo| TxOut {
            value: bitcoin::Amount::from_sat(utxo["amountSats"].as_u64().unwrap()),
            script_pubkey: ScriptBuf::from_bytes(from_hex(utxo["scriptPubKey"].as_str().unwrap())),
        })
        .collect();

    let cases = case["inputSpending"]
        .as_array()
        .unwrap()
        .iter()
        .map(|spending| KeyPath {
            input_index: spending["given"]["txinIndex"].as_u64().unwrap() as usize,
            internal_privkey: from_hex(spending["given"]["internalPrivkey"].as_str().unwrap()),
            merkle_root: spending["given"]["merkleRoot"]
                .as_str()
                .map(|hex| TapNodeHash::from_byte_array(from_hex(hex).try_into().unwrap())),
            hash_type: spending["given"]["hashType"].as_u64().unwrap() as u8,
            internal_pubkey: from_hex(spending["intermediary"]["internalPubkey"].as_str().unwrap()),
            tweaked_privkey: from_hex(spending["intermediary"]["tweakedPrivkey"].as_str().unwrap()),
            sighash: from_hex(spending["intermediary"]["sigHash"].as_str().unwrap()),
            witness: from_hex(spending["expected"]["witness"][0].as_str().unwrap()),
        })
        .collect();

    (tx, utxos, cases)
}

/// BIP-341's key-path sighash, on all seven of its cases and every sighash type they cover —
/// `SIGHASH_DEFAULT`, `ALL`, `NONE`, `SINGLE` and all three `ANYONECANPAY` forms.
///
/// **We refuse everything but the first two** (`AOBS-R03`), and the suite covers all of them
/// anyway: what is being pinned is the dependency's implementation of BIP-341, and a sighash
/// computation that is right on `DEFAULT` and wrong on `SINGLE` is one where the flag handling is
/// wrong rather than the commitment.
#[test]
fn bip341_key_path_sighashes_reproduce_byte_for_byte() {
    let (tx, utxos, cases) = bip341_key_path();
    assert_eq!(cases.len(), 7, "the file's own count");

    let mut cache = SighashCache::new(&tx);
    for case in &cases {
        let sighash = cache
            .taproot_key_spend_signature_hash(
                case.input_index,
                &Prevouts::All(&utxos),
                TapSighashType::from_consensus_u8(case.hash_type)
                    .expect("the vector's own hash type"),
            )
            .expect("the vector's inputs and prevouts agree");
        assert_eq!(
            sighash.to_byte_array().to_vec(),
            case.sighash,
            "input {}",
            case.input_index
        );
    }
}

/// The tweak and the signature, on the same seven cases.
///
/// **All seven expected signatures were generated with 32 zero bytes of auxiliary randomness**,
/// so they are what pins `sign_schnorr_no_aux_rand` — seven cases rather than the CSV's one, and
/// three of them over a non-trivial merkle root, which is what makes the tweak itself asserted
/// rather than assumed.
#[test]
fn bip341_key_path_signatures_reproduce_byte_for_byte() {
    let secp = Secp256k1::new();
    let (tx, utxos, cases) = bip341_key_path();
    let mut cache = SighashCache::new(&tx);

    for case in &cases {
        let secret =
            SecretKey::from_slice(&case.internal_privkey).expect("a vector key is in range");
        let keypair = Keypair::from_secret_key(&secp, &secret);

        // The internal key the vector publishes, before any tweak.
        let (internal, _) = keypair.x_only_public_key();
        assert_eq!(internal.serialize().to_vec(), case.internal_pubkey);

        // The tweak, against the vector's own tweaked private key. This is the step a signer gets
        // wrong silently: a wrong tweak still produces a valid BIP-340 signature, under a key
        // that does not spend the output.
        let tweaked = keypair.tap_tweak(&secp, case.merkle_root).to_keypair();
        assert_eq!(
            tweaked.secret_bytes().to_vec(),
            case.tweaked_privkey,
            "input {}",
            case.input_index
        );

        let sighash: TapSighash = cache
            .taproot_key_spend_signature_hash(
                case.input_index,
                &Prevouts::All(&utxos),
                TapSighashType::from_consensus_u8(case.hash_type).expect("the vector's hash type"),
            )
            .expect("the vector's inputs and prevouts agree");
        let signature =
            secp.sign_schnorr_no_aux_rand(&Message::from_digest(sighash.to_byte_array()), &tweaked);

        // The witness item is the 64-byte signature, plus the sighash byte for every type but
        // `DEFAULT` — which is BIP-341's own encoding and the reason `SIGHASH_DEFAULT` is one
        // byte cheaper than `ALL`.
        let mut expected = signature.serialize().to_vec();
        if case.hash_type != 0 {
            expected.push(case.hash_type);
        }
        assert_eq!(expected, case.witness, "input {}", case.input_index);
    }
}

// --- What signing does to the document -----------------------------------------------------

/// §8: **add partial signatures and remove nothing.**
///
/// Asserted field by field rather than by a length comparison: the failure this exists for is a
/// helpful `non_witness_utxo` strip, which shrinks the PSBT while every other field still checks
/// out.
#[test]
fn signing_removes_nothing_and_adds_only_signatures() {
    for family in Family::ALL {
        let wallet = wallet();
        let accepted = accept(&wallet, &spend(family));
        let signed = sign(&wallet, &accepted);

        assert_eq!(signed.unsigned_tx, accepted.psbt.unsigned_tx);
        assert_eq!(signed.version, accepted.psbt.version);
        assert_eq!(signed.xpub, accepted.psbt.xpub);
        assert_eq!(signed.proprietary, accepted.psbt.proprietary);
        assert_eq!(signed.unknown, accepted.psbt.unknown);
        assert_eq!(signed.outputs, accepted.psbt.outputs);

        for (after, before) in signed.inputs.iter().zip(&accepted.psbt.inputs) {
            assert_eq!(
                after.non_witness_utxo, before.non_witness_utxo,
                "{family:?}"
            );
            assert_eq!(after.witness_utxo, before.witness_utxo, "{family:?}");
            assert_eq!(after.redeem_script, before.redeem_script);
            assert_eq!(after.bip32_derivation, before.bip32_derivation);
            assert_eq!(after.tap_key_origins, before.tap_key_origins);
            assert_eq!(after.tap_internal_key, before.tap_internal_key);
            assert_eq!(after.sighash_type, before.sighash_type);
            assert_eq!(after.unknown, before.unknown);
        }
    }
}

/// §8: **do not finalize.** The Finalizer is a BIP-174 role we do not take, so neither field is
/// ever written — and `extract_tx` on our output is therefore impossible by construction.
#[test]
fn signing_never_finalizes() {
    for family in Family::ALL {
        let wallet = wallet();
        let accepted = accept(&wallet, &spend(family));
        let signed = sign(&wallet, &accepted);

        for input in &signed.inputs {
            assert!(input.final_script_sig.is_none(), "{family:?}");
            assert!(input.final_script_witness.is_none(), "{family:?}");
        }
    }
}

/// Every family gets a signature, in whichever of the three fields its family uses.
#[test]
fn each_family_signs_into_the_field_its_family_uses() {
    for family in Family::ALL {
        let wallet = wallet();
        let accepted = accept(&wallet, &spend(family));
        let signed = sign(&wallet, &accepted);
        let input = &signed.inputs[0];

        if family == Family::Bip86 {
            assert!(input.tap_key_sig.is_some(), "{family:?}");
            assert!(input.partial_sigs.is_empty(), "{family:?}");
            // A key-path spend and nothing else: no script-path signature is produced.
            assert!(input.tap_script_sigs.is_empty(), "{family:?}");
        } else {
            assert_eq!(input.partial_sigs.len(), 1, "{family:?}");
            assert!(input.tap_key_sig.is_none(), "{family:?}");
        }
    }
}

/// The signature is over the sighash the transaction commits to, verified against the key the
/// `scriptPubKey` pays — which is the one assertion that would catch signing the wrong input.
#[test]
fn the_ecdsa_signature_verifies_against_the_key_the_output_pays() {
    let secp = Secp256k1::new();
    for family in [Family::Bip44, Family::Bip49, Family::Bip84] {
        let wallet = wallet();
        let accepted = accept(&wallet, &spend(family));
        let signed = sign(&wallet, &accepted);

        let (pubkey, signature) = signed.inputs[0]
            .partial_sigs
            .iter()
            .next()
            .expect("one signature");
        let mut cache = SighashCache::new(&signed.unsigned_tx);
        let (message, _) = signed
            .sighash_ecdsa(0, &mut cache)
            .expect("the utxo and script are present");

        secp.verify_ecdsa(&message, &signature.signature, &pubkey.inner)
            .unwrap_or_else(|_| panic!("{family:?}"));
        assert_eq!(*pubkey, our_key(&wallet, family, 0, 0).to_pub().into());
    }
}

/// The same for taproot, against the **tweaked output key** the `scriptPubKey` carries.
#[test]
fn the_schnorr_signature_verifies_against_the_tweaked_output_key() {
    let secp = Secp256k1::new();
    let wallet = wallet();
    let accepted = accept(&wallet, &spend(Family::Bip86));
    let signed = sign(&wallet, &accepted);

    let signature = signed.inputs[0].tap_key_sig.expect("a key-path signature");
    let mut cache = SighashCache::new(&signed.unsigned_tx);
    let utxos: Vec<TxOut> = signed
        .inputs
        .iter()
        .map(|input| input.witness_utxo.clone().expect("R02 required one"))
        .collect();
    let sighash = cache
        .taproot_key_spend_signature_hash(0, &Prevouts::All(&utxos), TapSighashType::Default)
        .expect("the prevouts are all present");

    // The output key is the last 32 bytes of the `scriptPubKey` — `OP_1 <32 bytes>` — so this
    // reads the key out of the bytes being spent rather than deriving it a second time.
    let spk = our_spk(&wallet, Family::Bip86);
    let output_key = XOnlyPublicKey::from_slice(&spk.as_bytes()[2..]).expect("a p2tr output key");
    secp.verify_schnorr(
        &signature.signature,
        &Message::from_digest(sighash.to_byte_array()),
        &output_key,
    )
    .expect("the key path signature must verify");
}

/// [#113](https://github.com/allisson/aobs/issues/113)'s resolution, from the accepting side:
/// **what signs a taproot input is the internal key's own origin entry, not the internal key's
/// value.**
///
/// The declared internal key here is a real key of ours at the wrong index — *not* the key this
/// `scriptPubKey` is the tweak of — and the entry it is keyed under declares the path that does
/// derive the output. The dependency uses the internal key only to select that entry, so the
/// signature it produces is over the tweak of the key at the declared path, which is the output
/// key. Refusing this shape (the ticket's option 1) would have refused a transaction that signs
/// and finalizes; what §7 refuses instead is a key-path claim we cannot sign at all.
#[test]
fn a_taproot_input_signs_from_the_internal_keys_own_origin_entry() {
    let secp = Secp256k1::new();
    let wallet = wallet();
    let mut psbt = spend(Family::Bip86);

    let bogus = our_key(&wallet, Family::Bip86, 0, 1).to_x_only_pub();
    psbt.inputs[0].tap_internal_key = Some(bogus);
    psbt.inputs[0].tap_key_origins.clear();
    psbt.inputs[0].tap_key_origins.insert(
        bogus,
        (
            vec![],
            (wallet.fingerprint(), our_path(&wallet, Family::Bip86, 0, 0)),
        ),
    );

    let accepted = accept(&wallet, &psbt);
    let signed = sign(&wallet, &accepted);
    let signature = signed.inputs[0].tap_key_sig.expect("a key-path signature");

    let mut cache = SighashCache::new(&signed.unsigned_tx);
    let utxos: Vec<TxOut> = signed
        .inputs
        .iter()
        .map(|input| input.witness_utxo.clone().expect("R02 required one"))
        .collect();
    let sighash = cache
        .taproot_key_spend_signature_hash(0, &Prevouts::All(&utxos), TapSighashType::Default)
        .expect("the prevouts are all present");
    let spk = our_spk(&wallet, Family::Bip86);
    let output_key = XOnlyPublicKey::from_slice(&spk.as_bytes()[2..]).expect("a p2tr output key");

    secp.verify_schnorr(
        &signature.signature,
        &Message::from_digest(sighash.to_byte_array()),
        &output_key,
    )
    .expect("the signature must verify against the key the output pays");
}

/// §8: **a re-sign is byte-identical**, which is what makes `04-screens.md` §11.5's one
/// re-display slot a safety net rather than a promise.
///
/// It is also the alarm for a feature unification switching `secp256k1`'s `rand-std` on, which
/// would make the taproot path draw fresh auxiliary randomness. A non-deterministic signature
/// still verifies, so no other test in this file would notice.
#[test]
fn signing_twice_produces_the_same_bytes() {
    for family in Family::ALL {
        let wallet = wallet();
        let accepted = accept(&wallet, &spend(family));
        assert_eq!(
            sign(&wallet, &accepted).serialize(),
            sign(&wallet, &accepted).serialize(),
            "{family:?}"
        );
        // And a second wallet from the same seed signs the same bytes, which is the property a
        // re-scan after a restart depends on.
        let reloaded = crate::corpus::wallet();
        assert_eq!(
            sign(&wallet, &accepted).serialize(),
            sign(&reloaded, &accepted).serialize(),
            "{family:?}"
        );
    }
}

/// A transaction with one input of ours and one that is not: **ours is signed and theirs is left
/// alone.**
///
/// `AOBS-R06` asks only that *some* input re-derives, so this shape is accepted — and a signer
/// that produced a signature for the stranger's input would be signing something it does not own.
#[test]
fn a_foreign_input_beside_ours_is_left_unsigned() {
    let ours = wallet();
    let stranger = wallet_on(Network::Testnet);

    // Build the PSBT from our wallet, then replace input 1's declared origin and spent output
    // with the stranger's. The stranger's coin type differs, so `verify` finds nothing there.
    let mut psbt = psbt_for(
        &ours,
        &[(Family::Bip84, 100_000), (Family::Bip84, 50_000)],
        &[(our_spk(&ours, Family::Bip84), 140_000)],
    );
    let theirs = psbt_for(
        &stranger,
        &[(Family::Bip84, 50_000)],
        &[(our_spk(&stranger, Family::Bip84), 40_000)],
    );
    psbt.unsigned_tx.input[1] = theirs.unsigned_tx.input[0].clone();
    psbt.inputs[1] = theirs.inputs[0].clone();

    let accepted = accept(&ours, &psbt);
    let signed = sign(&ours, &accepted);

    assert_eq!(signed.inputs[0].partial_sigs.len(), 1);
    assert!(
        signed.inputs[1].partial_sigs.is_empty(),
        "a foreign input must stay unsigned"
    );
}

/// **The fingerprint authorises nothing here either** (standing rule 1).
///
/// `crate::psbt` accepts an input whose declared origin carries a fingerprint that is not ours,
/// because the byte-compare is what decides — *"a coordinator that filled the fingerprint in
/// wrongly should not make a wallet unsignable."* The dependency's own `impl GetKey for Xpriv`
/// answers only for a matching fingerprint, so this is the test that says `OurPaths` exists.
#[test]
fn an_input_declared_under_a_foreign_fingerprint_is_still_signed() {
    let wallet = wallet();
    let mut psbt = spend(Family::Bip84);
    psbt.inputs[0].bip32_derivation.clear();
    declare_input(
        &mut psbt.inputs[0],
        Family::Bip84,
        &our_key(&wallet, Family::Bip84, 0, 0),
        Fingerprint::from([0xde, 0xad, 0xbe, 0xef]),
        our_path(&wallet, Family::Bip84, 0, 0),
    );

    let accepted = accept(&wallet, &psbt);
    assert_eq!(sign(&wallet, &accepted).inputs[0].partial_sigs.len(), 1);
}

/// **The delta assertion has teeth** ([#115](https://github.com/allisson/aobs/issues/115)).
///
/// `AOBS-R17` is what keeps this shape out of the accepted set, so the only way to reach the
/// assertion is from inside the crate: an `Accepted` obtained honestly, with a `tap_key_sig`
/// planted afterwards. That is the shape `Psbt::sign` silently declines to sign — the whole
/// reason #113 could not assert the delta — and a test that only checked the outgoing document
/// would pass on it, which is what makes this the assertion's own case rather than a repeat of
/// `each_family_signs_into_the_field_its_family_uses`.
#[test]
#[should_panic(expected = "arrived already signed")]
fn an_accepted_input_that_arrived_signed_is_a_crate_bug() {
    let wallet = wallet();
    let mut accepted = accept(&wallet, &spend(Family::Bip86));
    accepted.psbt.inputs[0].tap_key_sig = Some(nonsense_schnorr_signature());

    let _ = sign(&wallet, &accepted);
}

/// **And the comes-back-signed half has teeth too**
/// ([#117](https://github.com/allisson/aobs/issues/117)): a taproot input of ours whose only
/// signature is a `partial_sigs` entry.
///
/// **That shape is unreachable from outside this crate, and the unreachability is the point.**
/// `Psbt::sign` dispatches on the `scriptPubKey`, so it never reaches `bip32_sign_ecdsa` for a
/// P2TR input; `AOBS-R17` refuses one that arrives already carrying `partial_sigs`. Those two
/// facts are what the disjunctive assertion this replaced rested on without stating either, so a
/// test cannot pretend to reach it honestly — it constructs the `Accepted` from inside, the way
/// [`an_accepted_input_that_arrived_signed_is_a_crate_bug`] does, and plants the family rather
/// than the signature: an honest BIP84 spend signs into `partial_sigs`, the family travelling
/// beside it says taproot, and the per-family assertion is the one thing that notices.
#[test]
#[should_panic(expected = "the field its family is signed from")]
fn a_signature_in_another_familys_field_is_a_crate_bug() {
    let wallet = wallet();
    let mut accepted = accept(&wallet, &spend(Family::Bip84));
    accepted.ours = vec![OurInput {
        index: 0,
        script: InputScript::P2tr,
    }];

    let _ = sign(&wallet, &accepted);
}

/// And the other half of the same bound: **a path this wallet would never scan derives nothing.**
///
/// The input's `scriptPubKey` is ours at `84h/0h/0h/0/0` and one claim declares that, so the
/// transaction is accepted; a second claim points at `84h/0h/0h/2/0`, a branch we do not scan. The
/// signature count is what says the second claim was refused a key.
#[test]
fn a_claim_on_a_path_we_would_never_scan_derives_nothing() {
    let wallet = wallet();
    let mut psbt = spend(Family::Bip84);
    let unscannable = wallet
        .account_path(Family::Bip84)
        .extend([crate::corpus::normal(2), crate::corpus::normal(0)]);
    declare_input(
        &mut psbt.inputs[0],
        Family::Bip84,
        &our_key(&wallet, Family::Bip84, 2, 0),
        wallet.fingerprint(),
        unscannable,
    );

    let accepted = accept(&wallet, &psbt);
    let signed = sign(&wallet, &accepted);
    assert_eq!(
        signed.inputs[0].partial_sigs.len(),
        1,
        "only the scannable claim may produce a key"
    );
}

// --- The owed measurement (`00-overview.md`) ------------------------------------------------

/// Finalize a copy of a signed PSBT, by hand, for the one purpose the measurement below needs.
///
/// **This is a test, not a code path.** §8 forbids the appliance the Finalizer role; what is
/// forbidden is *emitting* a finalized document, and measuring one we built here is how the
/// prediction gets checked against a real signed transaction rather than against our own
/// arithmetic a second time.
fn finalized(psbt: &Psbt) -> Transaction {
    let mut tx = psbt.unsigned_tx.clone();
    for (txin, input) in tx.input.iter_mut().zip(&psbt.inputs) {
        if let Some(signature) = &input.tap_key_sig {
            txin.witness = Witness::from_slice(&[signature.to_vec()]);
            continue;
        }
        let (pubkey, signature) = input
            .partial_sigs
            .iter()
            .next()
            .expect("every input of these fixtures is ours");
        let spk = &input
            .witness_utxo
            .as_ref()
            .expect("the fixtures carry both utxo fields")
            .script_pubkey;

        if spk.is_p2sh() {
            let redeem = input.redeem_script.clone().expect("R05 required one");
            txin.script_sig = ScriptBuf::builder()
                .push_slice(PushBytesBuf::try_from(redeem.to_bytes()).expect("22 bytes"))
                .into_script();
            txin.witness = Witness::p2wpkh(signature, &pubkey.inner);
        } else if spk.is_p2wpkh() {
            txin.witness = Witness::p2wpkh(signature, &pubkey.inner);
        } else {
            txin.script_sig = ScriptBuf::builder()
                .push_slice(
                    PushBytesBuf::try_from(signature.serialize().to_vec()).expect("a DER sig"),
                )
                .push_key(pubkey)
                .into_script();
        }
    }
    tx
}

/// `00-overview.md`'s owed measurement, discharged: **the predicted signed vsize the fee rate
/// divides by, against a real signed transaction, in all four script types.**
///
/// The prediction charges every family the *smaller* of its two signature elements — 71 bytes of
/// DER for ECDSA, 64 for a `SIGHASH_DEFAULT` Schnorr — so the direction is the one
/// `04-screens.md` §11.2.1 promises: **the prediction is never above the real vsize, so the
/// displayed rate is never lower than the rate that will be paid.** The gap is at most one byte of
/// DER per ECDSA input, which the assertion below bounds rather than merely observes.
#[test]
fn the_predicted_vsize_is_never_above_a_real_signed_transaction() {
    for family in Family::ALL {
        let wallet = wallet();
        let accepted = accept(&wallet, &spend(family));
        let predicted = accepted.review.vsize.get();
        let real = finalized(&sign(&wallet, &accepted)).vsize() as u64;

        assert!(
            predicted <= real,
            "{family:?}: predicted {predicted} above real {real}"
        );
        // One 72-byte DER element instead of 71 costs one byte, which is one weight unit in a
        // witness and four in a `scriptSig` — so one vbyte either way, per input.
        assert!(
            real - predicted <= 1,
            "{family:?}: predicted {predicted}, real {real}"
        );
    }
}

/// The same measurement on the shapes the published figures are quoted for, so the numbers
/// `psbt_tests.rs` asserts against the ecosystem's tables are the numbers a signed transaction
/// actually weighs.
///
/// Two outputs of the family's **own** script type, which is the shape those tables are quoted
/// for — a mixed pair would be a different transaction with a coincidentally similar name.
#[test]
fn the_published_figures_hold_against_signed_transactions() {
    let wallet = wallet();

    for (family, published) in [
        (Family::Bip44, 225u64),
        (Family::Bip84, 141),
        (Family::Bip86, 154),
    ] {
        let spk = our_spk(&wallet, family);
        let accepted = accept(
            &wallet,
            &psbt(
                &[(family, 100_000)],
                &[(spk.clone(), 60_000), (spk.clone(), 30_000)],
            ),
        );
        assert_eq!(accepted.review.vsize.get(), published, "{family:?}");

        let real = finalized(&sign(&wallet, &accepted)).vsize() as u64;
        assert!(
            (published..=published + 1).contains(&real),
            "{family:?}: published {published}, real {real}"
        );
    }
}

/// A ten-input consolidation, which is where a per-input rounding error would show up as ten of
/// them rather than one.
#[test]
fn the_prediction_holds_across_ten_inputs() {
    let wallet = wallet();
    let inputs: Vec<(Family, u64)> = (0..10).map(|_| (Family::Bip84, 20_000)).collect();
    let accepted = accept(
        &wallet,
        &psbt(&inputs, &[(our_spk(&wallet, Family::Bip84), 190_000)]),
    );

    let predicted = accepted.review.vsize.get();
    let real = finalized(&sign(&wallet, &accepted)).vsize() as u64;
    assert!(predicted <= real, "predicted {predicted}, real {real}");
    assert!(real - predicted <= 10, "predicted {predicted}, real {real}");
}
