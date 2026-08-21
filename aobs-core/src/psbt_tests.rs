//! The structural checks from the accepting side, plus the BIP-174 invalid vectors that must
//! *not* become refusals.
//!
//! The refusing side is the corpus (`crate::corpus`), where every case is named and asserts its
//! code. What lives here is everything a corpus case cannot say: the shapes that pass, the
//! boundaries either side of a bound, and the two claims the module's own comments make about
//! itself — that renderability is network-independent, and that the previous transaction beats
//! a `witness_utxo` that disagrees with it.

use bitcoin::bip32::{ChildNumber, Fingerprint};
use bitcoin::hashes::Hash as _;
use bitcoin::psbt::{Error as PsbtError, PsbtSighashType};
use bitcoin::{Amount, ScriptBuf};

use crate::bip39::Mnemonic;

use super::*;
use crate::corpus::declare_input;
use crate::corpus::{
    declare_output, from_hex, normal, one_in_one_out, our_key, our_path, our_spk, psbt, psbt_for,
    taproot_internal_key_orphaned, taproot_key_path_diverted, wallet, wallet_on,
};
use crate::derive::{Branch, Family};
use crate::secret::{Entropy, Passphrase};

/// BIP-174's other four invalid vectors, transcribed from `bitcoin-0.32`'s own tests, which
/// are the BIP's hex. None of them is a refusal: they are bytes that never became a PSBT.
const INVALID_VECTOR_1: &str = "0200000001268171371edff285e937adeea4b37b78000c0566cbb3ad64641713ca42171bf6000000006a473044022070b2245123e6bf474d60c5b50c043d4c691a5d2435f09a34a7662a9dc251790a022001329ca9dacf280bdf30740ec0390422422c81cb45839457aeb76fc12edd95b3012102657d118d3357b8e0f4c2cd46db7b39f6d9c38d9a70abcb9b2de5dc8dbfe4ce31feffffff02d3dff505000000001976a914d0c59903c5bac2868760e90fd521a4665aa7652088ac00e1f5050000000017a9143545e6e33b832c47050f24d3eeb93c9c03948bc787b32e1300";
const INVALID_VECTOR_2: &str = "70736274ff0100750200000001268171371edff285e937adeea4b37b78000c0566cbb3ad64641713ca42171bf60000000000feffffff02d3dff505000000001976a914d0c59903c5bac2868760e90fd521a4665aa7652088ac00e1f5050000000017a9143545e6e33b832c47050f24d3eeb93c9c03948bc787b32e1300000100fda5010100000000010289a3c71eab4d20e0371bbba4cc698fa295c9463afa2e397f8533ccb62f9567e50100000017160014be18d152a9b012039daf3da7de4f53349eecb985ffffffff86f8aa43a71dff1448893a530a7237ef6b4608bbb2dd2d0171e63aec6a4890b40100000017160014fe3e9ef1a745e974d902c4355943abcb34bd5353ffffffff0200c2eb0b000000001976a91485cff1097fd9e008bb34af709c62197b38978a4888ac72fef84e2c00000017a914339725ba21efd62ac753a9bcd067d6c7a6a39d05870247304402202712be22e0270f394f568311dc7ca9a68970b8025fdd3b240229f07f8a5f3a240220018b38d7dcd314e734c9276bd6fb40f673325bc4baa144c800d2f2f02db2765c012103d2e15674941bad4a996372cb87e1856d3652606d98562fe39c5e9e7e413f210502483045022100d12b852d85dcd961d2f5f4ab660654df6eedcc794c0c33ce5cc309ffb5fce58d022067338a8e0e1725c197fb1a88af59f51e44e4255b20167c8684031c05d1f2592a01210223b72beef0965d10be0778efecd61fcac6f79a4ea169393380734464f84f2ab30000000000";
const INVALID_VECTOR_3: &str = "70736274ff0100fd0a010200000002ab0949a08c5af7c49b8212f417e2f15ab3f5c33dcf153821a8139f877a5b7be4000000006a47304402204759661797c01b036b25928948686218347d89864b719e1f7fcf57d1e511658702205309eabf56aa4d8891ffd111fdf1336f3a29da866d7f8486d75546ceedaf93190121035cdc61fc7ba971c0b501a646a2a83b102cb43881217ca682dc86e2d73fa88292feffffffab0949a08c5af7c49b8212f417e2f15ab3f5c33dcf153821a8139f877a5b7be40100000000feffffff02603bea0b000000001976a914768a40bbd740cbe81d988e71de2a4d5c71396b1d88ac8e240000000000001976a9146f4620b553fa095e721b9ee0efe9fa039cca459788ac00000000000001012000e1f5050000000017a9143545e6e33b832c47050f24d3eeb93c9c03948bc787010416001485d13537f2e265405a34dbafa9e3dda01fb82308000000";
const INVALID_VECTOR_4: &str = "70736274ff000100fda5010100000000010289a3c71eab4d20e0371bbba4cc698fa295c9463afa2e397f8533ccb62f9567e50100000017160014be18d152a9b012039daf3da7de4f53349eecb985ffffffff86f8aa43a71dff1448893a530a7237ef6b4608bbb2dd2d0171e63aec6a4890b40100000017160014fe3e9ef1a745e974d902c4355943abcb34bd5353ffffffff0200c2eb0b000000001976a91485cff1097fd9e008bb34af709c62197b38978a4888ac72fef84e2c00000017a914339725ba21efd62ac753a9bcd067d6c7a6a39d05870247304402202712be22e0270f394f568311dc7ca9a68970b8025fdd3b240229f07f8a5f3a240220018b38d7dcd314e734c9276bd6fb40f673325bc4baa144c800d2f2f02db2765c012103d2e15674941bad4a996372cb87e1856d3652606d98562fe39c5e9e7e413f210502483045022100d12b852d85dcd961d2f5f4ab660654df6eedcc794c0c33ce5cc309ffb5fce58d022067338a8e0e1725c197fb1a88af59f51e44e4255b20167c8684031c05d1f2592a01210223b72beef0965d10be0778efecd61fcac6f79a4ea169393380734464f84f2ab30000000000";

fn accept(psbt: &Psbt) -> Review {
    review(&wallet(), psbt)
}

/// The whole inbound path over one PSBT's bytes, refusing to be refused.
fn review(wallet: &Wallet, psbt: &Psbt) -> Review {
    accepted(wallet, &psbt.serialize()).review
}

/// The same, for the three tests whose subject is the document rather than the model.
fn accepted(wallet: &Wallet, bytes: &[u8]) -> Accepted {
    match validate(wallet, bytes) {
        Ok(accepted) => accepted,
        Err(rejection) => panic!("refused a transaction the policy accepts: {rejection:?}"),
    }
}

/// The refusal one PSBT earns, or a panic naming what happened instead.
fn refusal(wallet: &Wallet, psbt: &Psbt) -> Refusal {
    match validate(wallet, &psbt.serialize()) {
        Err(Rejection::Refused(refusal)) => refusal,
        other => panic!("expected a refusal: {other:?}"),
    }
}

// --- the shapes that pass ------------------------------------------------------------------

#[test]
fn all_four_families_are_accepted_together() {
    // §7 adds no mixed-input-script-type refusal: mixing families from one seed is
    // legitimate, and the proxy Krux refuses is a question we ask directly per input.
    let spk = our_spk(&wallet(), Family::Bip84);
    let inputs: Vec<(Family, u64)> = Family::ALL.iter().map(|f| (*f, 100_000)).collect();
    accept(&psbt(&inputs, &[(spk, 390_000)]));
}

#[test]
fn nothing_is_stripped_from_an_accepted_transaction() {
    // §8: add signatures and remove nothing. What comes back is what went in, byte for byte.
    let bytes = one_in_one_out().serialize();
    assert_eq!(accepted(&wallet(), &bytes).psbt.serialize(), bytes);
}

#[test]
fn a_taproot_input_needs_only_its_witness_utxo() {
    // BIP-341 commits to every input's amount and scriptPubKey, so a lie invalidates the
    // signature. This is the one exemption from the previous-transaction rule.
    let spk = our_spk(&wallet(), Family::Bip84);
    let mut psbt = psbt(&[(Family::Bip86, 100_000)], &[(spk, 90_000)]);
    psbt.inputs[0].non_witness_utxo = None;
    accept(&psbt);
}

/// `AOBS-R05`, tightened by [#82](https://github.com/allisson/aobs/issues/82): **a taproot input
/// must declare its internal key.**
///
/// BIP-371 makes `PSBT_IN_TAP_INTERNAL_KEY` the field that says *this is a key-path spend*, so an
/// input without it has not declared the script type §7's fifth row is about. It is also what makes
/// `crate::sign` total over everything this module accepts: the taproot signing path reads the key
/// out of that field, so an accepted input lacking it would be one we cannot sign — and the PSBT
/// would leave the appliance looking signed and carrying nothing.
#[test]
fn a_taproot_input_without_its_internal_key_is_an_unsupported_script_type() {
    let spk = our_spk(&wallet(), Family::Bip84);
    let mut psbt = psbt(&[(Family::Bip86, 100_000)], &[(spk, 90_000)]);
    psbt.inputs[0].tap_internal_key = None;

    assert_eq!(
        refusal(&wallet(), &psbt),
        Refusal::UnsupportedInputScript { input: 0 }
    );
}

/// `AOBS-R05`, tightened again by [#113](https://github.com/allisson/aobs/issues/113): **the
/// declared internal key must have an origin entry of its own.**
///
/// `PSBT_IN_TAP_INTERNAL_KEY` on its own is half a declaration. The taproot signing path reads
/// the key-path spend out of the `tap_key_origins` entry **keyed by that key**, so an internal key
/// no entry names is a key-path spend the document gives no way to sign — which is the same
/// BIP-371 argument [#82](https://github.com/allisson/aobs/issues/82) made for requiring the field
/// at all, carried to the end of the sentence.
#[test]
fn a_taproot_internal_key_with_no_origin_entry_is_an_unsupported_script_type() {
    // The fixture is the corpus's, which asserts the code; this asserts the typed variant.
    assert_eq!(
        refusal(&wallet(), &taproot_internal_key_orphaned()),
        Refusal::UnsupportedInputScript { input: 0 }
    );
}

/// The other half of the same structural rule: **the entry must carry no leaf hashes.**
///
/// BIP-371 uses an empty leaf-hash list as the mark of the internal key, and the dependency reads
/// it that way — an entry carrying leaf hashes is a script-path key, and the key path is not
/// declared. `tap_scripts` and `tap_merkle_root` are both absent here, so the leaf hashes are the
/// only thing the refusal can be about.
#[test]
fn a_taproot_internal_key_carrying_leaf_hashes_is_an_unsupported_script_type() {
    let wallet = wallet();
    let spk = our_spk(&wallet, Family::Bip84);
    let mut psbt = psbt(&[(Family::Bip86, 100_000)], &[(spk, 90_000)]);

    let internal = psbt.inputs[0]
        .tap_internal_key
        .expect("the fixture declares one");
    psbt.inputs[0]
        .tap_key_origins
        .get_mut(&internal)
        .expect("the fixture declares its origin")
        .0
        .push(TapLeafHash::from_byte_array([0x44; 32]));

    assert_eq!(
        refusal(&wallet, &psbt),
        Refusal::UnsupportedInputScript { input: 0 }
    );
}

/// And the derivation half ([#113](https://github.com/allisson/aobs/issues/113)): **for a taproot
/// input the internal key's entry is the only claim the byte-compare reads.**
///
/// The input's `scriptPubKey` really is ours, and a second entry declares the path that derives
/// it — but the internal key's own entry points at a branch we never scan, which is the entry the
/// signing path would use. A claim in any other entry is not a claim about *this* spend, so the
/// input is not ours and the transaction is `AOBS-R06` rather than a document that comes back
/// carrying nothing.
#[test]
fn a_taproot_claim_that_is_not_the_internal_keys_does_not_make_the_input_ours() {
    assert!(matches!(
        refusal(&wallet(), &taproot_key_path_diverted()),
        Refusal::NoInputOfOurs { .. }
    ));
}

/// The same rule facing the other way, which is the instance #113 did not name: **a BIP44/49/84
/// input claims in `bip32_derivation`, and a claim in the taproot map is not one.**
///
/// `Psbt::sign`'s ECDSA path iterates `bip32_derivation` and nothing else, so an input whose only
/// byte-verifying claim sits in `tap_key_origins` would have been accepted as ours and signed
/// nothing — the taproot defect with no taproot in it.
#[test]
fn a_non_taproot_claim_in_the_taproot_map_does_not_make_the_input_ours() {
    let wallet = wallet();
    let spk = our_spk(&wallet, Family::Bip84);
    let mut psbt = psbt(&[(Family::Bip84, 100_000)], &[(spk, 90_000)]);

    // The same key, the same path, the same fingerprint — moved to the map its family does not
    // declare in. `Family::Bip86` here selects the *map*, not the script type.
    psbt.inputs[0].bip32_derivation.clear();
    declare_input(
        &mut psbt.inputs[0],
        Family::Bip86,
        &our_key(&wallet, Family::Bip84, 0, 0),
        wallet.fingerprint(),
        our_path(&wallet, Family::Bip84, 0, 0),
    );

    assert!(matches!(
        refusal(&wallet, &psbt),
        Refusal::NoInputOfOurs { .. }
    ));
}

#[test]
fn a_non_taproot_input_needs_only_its_previous_transaction() {
    let mut psbt = one_in_one_out();
    psbt.inputs[0].witness_utxo = None;
    accept(&psbt);
}

#[test]
fn six_outputs_are_accepted_and_the_seventh_is_the_refusal() {
    let spk = our_spk(&wallet(), Family::Bip84);
    let outputs: Vec<(ScriptBuf, u64)> = (0..MAX_OUTPUTS).map(|_| (spk.clone(), 10_000)).collect();
    accept(&psbt(&[(Family::Bip84, 100_000)], &outputs));

    let seven: Vec<(ScriptBuf, u64)> = (0..=MAX_OUTPUTS).map(|_| (spk.clone(), 10_000)).collect();
    assert_eq!(
        validate(
            &wallet(),
            &psbt(&[(Family::Bip84, 100_000)], &seven).serialize()
        ),
        Err(Rejection::Refused(Refusal::TooManyOutputs { count: 7 }))
    );
}

#[test]
fn a_zero_fee_transaction_is_not_a_refusal() {
    // §7's rule is *exceeds*, not *equals*. A transaction that pays no fee is a bad idea and
    // not a lie, and the review panel is where the user sees it.
    let spk = our_spk(&wallet(), Family::Bip84);
    accept(&psbt(&[(Family::Bip84, 100_000)], &[(spk, 100_000)]));
}

#[test]
fn an_absent_sighash_type_is_accepted() {
    let psbt = one_in_one_out();
    assert!(psbt.inputs[0].sighash_type.is_none());
    accept(&psbt);
}

#[test]
fn sighash_all_may_be_declared_explicitly() {
    let mut psbt = one_in_one_out();
    psbt.inputs[0].sighash_type = Some(PsbtSighashType::from_u32(0x01));
    accept(&psbt);
}

#[test]
fn a_taproot_input_may_declare_default_or_all() {
    let spk = our_spk(&wallet(), Family::Bip84);
    for declared in [0x00, 0x01] {
        let mut psbt = psbt(&[(Family::Bip86, 100_000)], &[(spk.clone(), 90_000)]);
        psbt.inputs[0].sighash_type = Some(PsbtSighashType::from_u32(declared));
        accept(&psbt);
    }
}

#[test]
fn a_non_taproot_input_may_not_declare_sighash_default() {
    // 0x00 is not an ECDSA sighash type at all; the dependency's own parse refuses it, and
    // here that lands as `AOBS-R03` rather than as an accept.
    let mut psbt = one_in_one_out();
    psbt.inputs[0].sighash_type = Some(PsbtSighashType::from_u32(0x00));
    assert_eq!(
        validate(&wallet(), &psbt.serialize()),
        Err(Rejection::Refused(Refusal::UnsupportedSighash { input: 0 }))
    );
}

// --- the two claims the module makes about itself -----------------------------------------

#[test]
fn the_previous_transaction_beats_a_witness_utxo_that_disagrees() {
    // The whole point of the `non_witness_utxo` rule: an inflated `witness_utxo` cannot buy
    // the attacker a larger input total, because the amount comes from the transaction that
    // hashes. Paying 200 000 out of a 100 000 input is refused even though `witness_utxo`
    // claims it is affordable.
    let spk = our_spk(&wallet(), Family::Bip84);
    let mut psbt = psbt(&[(Family::Bip84, 100_000)], &[(spk, 200_000)]);
    psbt.inputs[0].witness_utxo = Some(TxOut {
        value: Amount::from_sat(21_000_000_000_000_000),
        script_pubkey: psbt.inputs[0]
            .witness_utxo
            .as_ref()
            .expect("the fixture carries one")
            .script_pubkey
            .clone(),
    });
    assert_eq!(
        validate(&wallet(), &psbt.serialize()),
        Err(Rejection::Refused(Refusal::OutputsExceedInputs))
    );
}

#[test]
fn renderability_does_not_depend_on_the_network() {
    // `AOBS-R07` is asked with one network hardcoded, on the grounds that a network only
    // selects an HRP or a version byte. This is that grounds, asserted.
    let wallet = wallet();
    let mut scripts: Vec<ScriptBuf> = Family::ALL.iter().map(|f| our_spk(&wallet, *f)).collect();
    scripts.push(
        bitcoin::script::Builder::new()
            .push_opcode(bitcoin::opcodes::all::OP_RETURN)
            .into_script(),
    );
    scripts.push(ScriptBuf::new());
    scripts.push(ScriptBuf::from_bytes(
        [&[0x51u8, 0x1e][..], &[0x33u8; 30][..]].concat(),
    ));

    for script in scripts {
        assert_eq!(
            Address::from_script(&script, bitcoin::Network::Bitcoin).is_ok(),
            Address::from_script(&script, bitcoin::Network::Testnet).is_ok(),
            "{script:?}"
        );
    }
}

// --- unknown fields ------------------------------------------------------------------------

#[test]
fn unknown_fields_are_ignored_and_preserved() {
    let mut psbt = one_in_one_out();
    let key = bitcoin::psbt::raw::Key {
        type_value: 0x77,
        key: vec![0x01, 0x02],
    };
    let value = vec![0xde, 0xad, 0xbe, 0xef];
    psbt.unknown.insert(key.clone(), value.clone());
    psbt.inputs[0].unknown.insert(key.clone(), value.clone());
    psbt.outputs[0].unknown.insert(key.clone(), value.clone());

    let bytes = psbt.serialize();
    let accepted = accepted(&wallet(), &bytes).psbt;

    assert_eq!(accepted.unknown.get(&key), Some(&value));
    assert_eq!(accepted.inputs[0].unknown.get(&key), Some(&value));
    assert_eq!(accepted.outputs[0].unknown.get(&key), Some(&value));
    assert_eq!(accepted.serialize(), bytes);
}

// --- bytes that never became a PSBT --------------------------------------------------------

/// The dependency's own verdict on a vector, plus ours: `NotAPsbt`, with no code.
///
/// Pinning the error variant as well as our answer is what makes a transcription slip in the
/// hex above fail — a mistyped vector would otherwise still land on `NotAPsbt` and pass.
fn decode_failure(hex: &str) -> PsbtError {
    let bytes = from_hex(hex);
    let error = Psbt::deserialize(&bytes).expect_err("the vector is invalid");
    assert_eq!(validate(&wallet(), &bytes), Err(Rejection::NotAPsbt));
    error
}

#[test]
fn the_other_bip174_invalid_vectors_are_not_refusals() {
    assert!(matches!(
        decode_failure(INVALID_VECTOR_1),
        PsbtError::InvalidMagic
    ));
    assert!(matches!(
        decode_failure(INVALID_VECTOR_2),
        PsbtError::ConsensusEncoding(_)
    ));
    // Vectors 3 and 4 are §7's *two refusals that arrive free* — `unsigned_tx_checks` and the
    // missing unsigned transaction. Both fire inside the decode, so neither carries a code.
    assert!(matches!(
        decode_failure(INVALID_VECTOR_3),
        PsbtError::UnsignedTxHasScriptSigs
    ));
    assert!(matches!(
        decode_failure(INVALID_VECTOR_4),
        PsbtError::MustHaveUnsignedTx
    ));
}

#[test]
fn empty_and_arbitrary_bytes_are_not_refusals() {
    for bytes in [vec![], b"psbt".to_vec(), b"not a psbt at all".to_vec()] {
        assert_eq!(validate(&wallet(), &bytes), Err(Rejection::NotAPsbt));
    }
}

#[test]
fn a_truncated_psbt_is_not_a_refusal() {
    let bytes = one_in_one_out().serialize();
    for cut in [1, bytes.len() / 2, bytes.len() - 1] {
        assert_eq!(validate(&wallet(), &bytes[..cut]), Err(Rejection::NotAPsbt));
    }
}

// --- the copy ------------------------------------------------------------------------------

#[test]
fn every_refusal_carries_a_code_from_the_refusal_space() {
    for refusal in Refusal::ALL {
        let code = refusal.code();
        assert_eq!(code.len(), 8, "{code}");
        assert!(code.starts_with("AOBS-R"), "{code}");
        assert!(code[6..].chars().all(char::is_numeric), "{code}");
    }
}

#[test]
fn all_holds_every_variant() {
    // `code()` and `reason()` are exhaustive matches, so a variant added later cannot compile
    // without an arm in each. `ALL` is the one place it *can* be forgotten, and forgetting it
    // would silently exempt the new refusal from the registry tests — so this maps every
    // variant to a distinct index through a third exhaustive match and asserts `ALL` covers
    // the whole range.
    fn index(refusal: Refusal) -> usize {
        match refusal {
            Refusal::DuplicateKey => 0,
            Refusal::PreviousTransactionAbsent { .. } => 1,
            Refusal::PreviousTransactionMismatch { .. } => 2,
            Refusal::PreviousOutputMissing { .. } => 3,
            Refusal::UnsupportedSighash { .. } => 4,
            Refusal::OutputsExceedInputs => 5,
            Refusal::UnsupportedInputScript { .. } => 6,
            Refusal::UnrenderableOutput { .. } => 7,
            Refusal::TooManyOutputs { .. } => 8,
            Refusal::AmountOutOfRange => 9,
            Refusal::NoInputOfOurs { .. } => 10,
            Refusal::ChangeMismatch { .. } => 11,
            Refusal::UnscannableChangePath { .. } => 12,
        }
    }

    let mut seen: Vec<usize> = Refusal::ALL.iter().map(|r| index(*r)).collect();
    seen.sort_unstable();
    assert_eq!(seen, (0..Refusal::ALL.len()).collect::<Vec<usize>>());
}

#[test]
fn the_output_bound_refusal_states_both_numbers() {
    // The copy names what the transaction has and what the panel holds, and both come out of
    // the same constant the check uses. A formatting slip here is a refusal that explains
    // nothing.
    let reason = Refusal::TooManyOutputs { count: 41 }.reason();
    assert!(reason.contains("41 outputs"), "{reason}");
    assert!(reason.contains(&MAX_OUTPUTS.to_string()), "{reason}");
}

#[test]
fn every_refusal_states_its_reason_in_plain_language() {
    for refusal in Refusal::ALL {
        let reason = refusal.reason();
        assert!(reason.ends_with('.'), "{reason}");
        assert!(reason.len() > 40, "{reason}");
        // The reason is the copy and the code is beside it, never inside it (`06-codes.md`
        // §1: the code is not how anyone learns what happened).
        assert!(!reason.contains("AOBS-"), "{reason}");
    }
}

#[test]
fn a_refusal_names_the_position_that_tripped_it_one_based() {
    let spk = our_spk(&wallet(), Family::Bip84);
    let mut psbt = psbt(
        &[(Family::Bip84, 100_000), (Family::Bip84, 100_000)],
        &[(spk, 150_000)],
    );
    psbt.inputs[1].non_witness_utxo = None;
    psbt.inputs[1].witness_utxo = None;

    let refusal = refusal(&wallet(), &psbt);
    assert_eq!(refusal, Refusal::PreviousTransactionAbsent { input: 1 });
    assert!(refusal.reason().contains("Input 2"), "{}", refusal.reason());
}

// --- the derivation check ------------------------------------------------------------------

/// A wallet that is not ours, from a seed nothing else in the suite uses.
fn stranger() -> Wallet {
    let mnemonic = Mnemonic::from_entropy(&Entropy::new(&[0xAB; 16]).expect("16 bytes fit"))
        .expect("16 bytes is an accepted length");
    Wallet::load(
        &mnemonic,
        &Passphrase::new("").expect("empty fits"),
        Network::Mainnet,
    )
}

/// The mainnet fixture wallet loaded with a passphrase — a different wallet, same seed.
fn with_passphrase() -> Wallet {
    let mnemonic = Mnemonic::from_entropy(&Entropy::new(&[0u8; 16]).expect("16 bytes fit"))
        .expect("16 bytes is an accepted length");
    Wallet::load(
        &mnemonic,
        &Passphrase::new("correct horse").expect("13 bytes fit"),
        Network::Mainnet,
    )
}

/// A stranger's P2WPKH address, for the outputs that are genuinely payments.
fn theirs() -> ScriptBuf {
    our_spk(&stranger(), Family::Bip84)
}

/// One BIP84 input of `input` satoshis, paying `payment` to a stranger and `change` back to
/// `84h/0h/0h/1/0` — declared the way a coordinator declares it. The remainder is the fee.
fn spend(input: u64, payment: u64, change: u64) -> Psbt {
    let wallet = wallet();
    let back = wallet
        .address(Family::Bip84, Branch::Change, 0)
        .expect("a normal index")
        .script_pubkey();
    let mut psbt = psbt(
        &[(Family::Bip84, input)],
        &[(theirs(), payment), (back, change)],
    );
    declare_output(
        &mut psbt.outputs[1],
        Family::Bip84,
        &our_key(&wallet, Family::Bip84, 1, 0),
        wallet.fingerprint(),
        our_path(&wallet, Family::Bip84, 1, 0),
    );
    psbt
}

#[test]
fn the_review_model_carries_every_number_the_panel_states() {
    let model = accept(&spend(100_000, 60_000, 30_000));

    assert_eq!(model.network, Network::Mainnet);
    assert_eq!(model.input_count, 1);
    assert_eq!(model.input_total, Amount::from_sat(100_000));
    assert_eq!(model.paying, Amount::from_sat(60_000));
    assert_eq!(model.returning, Amount::from_sat(30_000));
    assert_eq!(model.fee, Amount::from_sat(10_000));
    // What leaves the wallet is what the recipient gets plus what the miners get. The two
    // numbers are computed from different sides — the inputs less the change, against the
    // outputs — so this is a real cross-check and not a restatement.
    assert_eq!(model.leaving, Amount::from_sat(70_000));
    assert_eq!(model.leaving, model.paying + model.fee);
    assert_eq!(model.outputs.len(), 2);
    assert_eq!(model.warning, None);
}

/// Change is classified only after the byte-compare, and the verdict travels with the row —
/// §11.2 makes the panel *state* that the compare ran.
#[test]
fn change_carries_its_full_path_and_its_verdict() {
    let wallet = wallet();
    let model = accept(&spend(100_000, 60_000, 30_000));

    assert_eq!(model.outputs[0].kind, OutputKind::Payment);
    assert_eq!(
        model.outputs[1].kind,
        OutputKind::Change {
            path: our_path(&wallet, Family::Bip84, 1, 0),
            verdict: Rederivation::MatchedByteForByte,
        }
    );
    // The rendered address is the loaded network's, not a network-free stand-in.
    assert!(model.outputs[1].address.to_string().starts_with("bc1"));
    assert_eq!(model.outputs[1].amount, Amount::from_sat(30_000));
}

/// **A foreign fingerprint is simply a payment** (§7): displayed in full, no suspicion
/// attached. The path and the key are ours; only the fingerprint is not.
///
/// This is the safe direction of both attacks — marking real change as foreign only causes it
/// to be *shown*.
#[test]
fn an_output_with_a_foreign_fingerprint_is_a_payment() {
    let wallet = wallet();
    let mut psbt = spend(100_000, 60_000, 30_000);
    psbt.outputs[1].bip32_derivation.clear();
    declare_output(
        &mut psbt.outputs[1],
        Family::Bip84,
        &our_key(&wallet, Family::Bip84, 1, 0),
        Fingerprint::from([0xde, 0xad, 0xbe, 0xef]),
        our_path(&wallet, Family::Bip84, 1, 0),
    );

    let model = accept(&psbt);
    assert_eq!(model.outputs[1].kind, OutputKind::Payment);
    assert_eq!(model.paying, Amount::from_sat(90_000));
    assert_eq!(model.returning, Amount::ZERO);
}

/// An output with no claim at all is a payment, even when it pays an address of ours.
#[test]
fn an_output_with_no_claim_is_a_payment() {
    let model = accept(&one_in_one_out());

    assert_eq!(model.outputs[0].kind, OutputKind::Payment);
    assert_eq!(model.returning, Amount::ZERO);
    assert_eq!(model.paying, Amount::from_sat(90_000));
}

/// `AOBS-R08`: our fingerprint on an output whose `scriptPubKey` is the attacker's refuses the
/// **entire transaction** rather than being reclassified as a plain spend and shown.
#[test]
fn a_change_output_that_fails_the_compare_refuses_the_whole_transaction() {
    let wallet = wallet();
    let mut psbt = spend(100_000, 60_000, 30_000);
    // Same declaration, one byte of the address changed: the output no longer derives from the
    // path it claims.
    psbt.unsigned_tx.output[1].script_pubkey =
        ScriptBuf::new_p2wpkh(&bitcoin::WPubkeyHash::from_byte_array([0x55; 20]));

    assert_eq!(
        refusal(&wallet, &psbt),
        Refusal::ChangeMismatch { output: 1 }
    );
}

/// `AOBS-R09`: change on a path we would never scan, in its two shapes — a third branch and a
/// hardened final index. **Both refuse**, and neither derives anything.
#[test]
fn change_on_a_path_we_would_never_scan_refuses() {
    let wallet = wallet();
    let unscannable = [
        wallet
            .account_path(Family::Bip84)
            .extend([normal(2), normal(0)]),
        wallet
            .account_path(Family::Bip84)
            .extend([normal(1), ChildNumber::Hardened { index: 0 }]),
    ];

    for path in unscannable {
        let mut psbt = spend(100_000, 60_000, 30_000);
        psbt.outputs[1].bip32_derivation.clear();
        declare_output(
            &mut psbt.outputs[1],
            Family::Bip84,
            &our_key(&wallet, Family::Bip84, 1, 0),
            wallet.fingerprint(),
            path.clone(),
        );
        assert_eq!(
            refusal(&wallet, &psbt),
            Refusal::UnscannableChangePath { output: 1 },
            "{path}"
        );
    }
}

/// `AOBS-R06`: a PSBT for somebody else's wallet. The fingerprints differ, and that is not what
/// refuses it — the byte-compare is.
#[test]
fn a_transaction_with_no_input_of_ours_is_refused() {
    let stranger = stranger();
    let theirs = psbt_for(
        &stranger,
        &[(Family::Bip84, 100_000)],
        &[(our_spk(&stranger, Family::Bip84), 90_000)],
    );

    assert_eq!(
        refusal(&wallet(), &theirs),
        Refusal::NoInputOfOurs {
            network: Network::Mainnet,
            passphrase_in_use: false,
            coin_type_mismatch: false,
        }
    );
}

/// A PSBT with no inputs at all reaches `AOBS-R06`, and the coin-type variant does **not**
/// fire — there is no declared path to assert anything about.
#[test]
fn a_transaction_with_no_inputs_is_refused_without_naming_a_network_for_it() {
    let refused = refusal(&wallet(), &psbt(&[], &[(theirs(), 0)]));

    assert_eq!(
        refused,
        Refusal::NoInputOfOurs {
            network: Network::Mainnet,
            passphrase_in_use: false,
            coin_type_mismatch: false,
        }
    );
}

/// The four copy variants of `AOBS-R06`, one code (`02-core.md` §7).
///
/// Two requirements are unconditional and hold in all four — the loaded network and account 0.
/// Two are conditional: the passphrase, and the coin-type disagreement stated outright. The
/// last of those **selects copy only**: acceptance rested on the byte-compare in every one of
/// these four, which is standing rule 1.
#[test]
fn the_no_input_refusal_carries_four_copy_variants() {
    let stranger = stranger();
    let mainnet_psbt = psbt_for(
        &stranger,
        &[(Family::Bip84, 100_000)],
        &[(our_spk(&stranger, Family::Bip84), 90_000)],
    );
    let testnet = wallet_on(Network::Testnet);
    let testnet_psbt = psbt_for(
        &testnet,
        &[(Family::Bip84, 100_000)],
        &[(our_spk(&testnet, Family::Bip84), 90_000)],
    );

    let mut seen = Vec::new();
    for (wallet, passphrase) in [(wallet(), false), (with_passphrase(), true)] {
        for (psbt, mismatch) in [(&mainnet_psbt, false), (&testnet_psbt, true)] {
            let refused = refusal(&wallet, psbt);
            assert_eq!(
                refused,
                Refusal::NoInputOfOurs {
                    network: Network::Mainnet,
                    passphrase_in_use: passphrase,
                    coin_type_mismatch: mismatch,
                }
            );

            let reason = refused.reason();
            // Unconditional, in all four.
            assert!(reason.contains("mainnet"), "{reason}");
            assert!(reason.contains("account 0"), "{reason}");
            // Conditional, and named only when true.
            assert_eq!(reason.contains("passphrase"), passphrase, "{reason}");
            assert_eq!(reason.contains("testnet or signet"), mismatch, "{reason}");
            seen.push(reason);
        }
    }

    seen.sort();
    seen.dedup();
    assert_eq!(seen.len(), 4, "the four variants are four sentences");
}

/// One input built for the other network among several of ours is **not** a network mistake, so
/// the coin-type variant is *every* and not *any*.
#[test]
fn one_foreign_coin_type_among_ours_does_not_claim_a_network() {
    let wallet = wallet();
    let testnet = wallet_on(Network::Testnet);
    let mut psbt = psbt_for(
        &testnet,
        &[(Family::Bip84, 100_000), (Family::Bip49, 100_000)],
        &[(our_spk(&testnet, Family::Bip84), 190_000)],
    );
    // The second input now declares a mainnet path — still not ours, but the transaction can no
    // longer be described as built for one network.
    psbt.inputs[1].bip32_derivation.clear();
    declare_input(
        &mut psbt.inputs[1],
        Family::Bip49,
        &our_key(&wallet, Family::Bip49, 0, 0),
        wallet.fingerprint(),
        our_path(&wallet, Family::Bip49, 0, 0),
    );

    assert_eq!(
        refusal(&wallet, &psbt),
        Refusal::NoInputOfOurs {
            network: Network::Mainnet,
            passphrase_in_use: false,
            coin_type_mismatch: false,
        }
    );
}

/// An input whose origin was declared under a fingerprint that is not ours is still ours if we
/// derive its `scriptPubKey` — the byte-compare answers the question the hint only asks.
#[test]
fn an_input_verifies_under_a_fingerprint_that_is_not_ours() {
    let wallet = wallet();
    let mut psbt = one_in_one_out();
    psbt.inputs[0].bip32_derivation.clear();
    declare_input(
        &mut psbt.inputs[0],
        Family::Bip84,
        &our_key(&wallet, Family::Bip84, 0, 0),
        Fingerprint::from([0x00, 0x00, 0x00, 0x00]),
        our_path(&wallet, Family::Bip84, 0, 0),
    );

    accept(&psbt);
}

// --- the amount bound ----------------------------------------------------------------------

/// `AOBS-R16` is the money supply exactly: the cap is accepted and one satoshi over is not.
#[test]
fn the_amount_bound_is_the_money_supply() {
    let spk = our_spk(&wallet(), Family::Bip84);
    let supply = Amount::MAX_MONEY.to_sat();

    accept(&psbt(&[(Family::Bip84, supply)], &[(spk.clone(), 1_000)]));
    assert_eq!(
        refusal(
            &wallet(),
            &psbt(&[(Family::Bip84, supply + 1)], &[(spk, 1_000)])
        ),
        Refusal::AmountOutOfRange
    );
}

/// The shape the bound exists for: two taproot inputs whose sum no `u64` can hold. `AOBS-R04`
/// cannot catch it — the outputs are modest — and every number the panel states would wrap.
#[test]
fn two_inputs_summing_past_u64_are_refused_rather_than_wrapped() {
    let spk = our_spk(&wallet(), Family::Bip84);
    let psbt = psbt(
        &[(Family::Bip86, u64::MAX), (Family::Bip86, u64::MAX)],
        &[(spk, 90_000)],
    );

    assert_eq!(refusal(&wallet(), &psbt), Refusal::AmountOutOfRange);
}

// --- the one advisory warning (`02-core.md` §9) --------------------------------------------

/// The rule is `fee ≥ total sent to non-change outputs`, and equality is the boundary the `≥`
/// exists for.
#[test]
fn the_warning_fires_when_the_fee_equals_the_payment() {
    let model = accept(&spend(100_000, 40_000, 20_000));

    assert_eq!(model.fee, model.paying);
    assert_eq!(model.warning, Some(Warning::FeeAbovePayment));
}

/// One satoshi under, and it is silent.
#[test]
fn the_warning_is_silent_one_satoshi_under_the_boundary() {
    let model = accept(&spend(100_000, 40_001, 20_000));

    assert_eq!(model.fee, Amount::from_sat(39_999));
    assert_eq!(model.warning, None);
}

/// **A consolidation fires nothing** (§9's carve-out): with no non-change outputs the ratio is
/// undefined, and `fee >= 0` would otherwise be true of every transaction ever built.
#[test]
fn a_consolidation_with_no_payment_fires_nothing() {
    let wallet = wallet();
    let back = wallet
        .address(Family::Bip84, Branch::Change, 0)
        .expect("a normal index")
        .script_pubkey();
    let mut psbt = psbt(&[(Family::Bip84, 100_000)], &[(back, 90_000)]);
    declare_output(
        &mut psbt.outputs[0],
        Family::Bip84,
        &our_key(&wallet, Family::Bip84, 1, 0),
        wallet.fingerprint(),
        our_path(&wallet, Family::Bip84, 1, 0),
    );

    let model = accept(&psbt);
    assert_eq!(model.paying, Amount::ZERO);
    assert_eq!(model.returning, Amount::from_sat(90_000));
    assert_eq!(model.warning, None);
}

/// A legitimate high-congestion transaction well under the ratio **stays silent**. A signer
/// that warns about everything trains the user to click through.
#[test]
fn a_high_fee_well_under_the_ratio_stays_silent() {
    let model = accept(&spend(1_000_000, 900_000, 50_000));

    assert_eq!(model.fee, Amount::from_sat(50_000));
    assert_eq!(model.warning, None);
}

/// A change output does not count towards the denominator, which is what makes the warning
/// about the recipient rather than about the transaction.
#[test]
fn change_is_not_part_of_the_warnings_denominator() {
    // 10 000 to the recipient, 80 000 back to us, 10 000 to the miners: the fee equals the
    // payment even though it is an eighth of what comes home.
    let model = accept(&spend(100_000, 10_000, 80_000));

    assert_eq!(model.paying, Amount::from_sat(10_000));
    assert_eq!(model.warning, Some(Warning::FeeAbovePayment));
}

// --- the predicted vsize (`04-screens.md` §11.2.1) -----------------------------------------

/// Two outputs of `spk`, so the rows cost the same in every family.
fn two_out(family: Family, spk: &ScriptBuf) -> Psbt {
    psbt(
        &[(family, 100_000)],
        &[(spk.clone(), 60_000), (spk.clone(), 30_000)],
    )
}

/// The three single-family shapes, against the figures the ecosystem publishes for them.
///
/// These are hand-derived from BIP-141's weight rule and the element sizes above, and they
/// agree with the widely-quoted sizes for a 1-in 2-out spend: 141 vB for P2WPKH, 225 for P2PKH
/// (the 226 figure charges a 72-byte signature element, which we deliberately do not), and 154
/// for P2TR. *The prediction against a real signed transaction is owed* — `00-overview.md`.
#[test]
fn the_predicted_vsize_matches_the_published_figures() {
    let wallet = wallet();
    for (family, expected) in [
        (Family::Bip44, 225u64),
        (Family::Bip84, 141),
        (Family::Bip86, 154),
    ] {
        let spk = our_spk(&wallet, family);
        assert_eq!(
            accept(&two_out(family, &spk)).vsize.get(),
            expected,
            "{family:?}"
        );
    }
}

/// A legacy-only transaction has no marker, no flag and no witness section, so it weighs
/// exactly four units per byte and its vsize *is* its size.
#[test]
fn a_legacy_transaction_weighs_four_units_per_byte() {
    let wallet = wallet();
    let spk = our_spk(&wallet, Family::Bip44);
    let psbt = two_out(Family::Bip44, &spk);
    let signed_base = psbt.unsigned_tx.base_size() + 1 + 71 + 1 + 33;

    assert_eq!(accept(&psbt).vsize.get(), signed_base as u64);
}

/// A legacy input inside a segwit transaction still costs its empty witness item, so mixing
/// families is not the same as adding the two predictions.
#[test]
fn a_segwit_transaction_discounts_its_witness() {
    let wallet = wallet();
    let spk = our_spk(&wallet, Family::Bip84);
    let mixed = psbt(
        &[(Family::Bip44, 100_000), (Family::Bip84, 100_000)],
        &[(spk.clone(), 90_000), (spk, 90_000)],
    );

    let model = accept(&mixed);
    // Base: the unsigned size plus the P2PKH scriptSig. Witness: marker and flag, the legacy
    // input's empty item, and the P2WPKH witness.
    let base = mixed.unsigned_tx.base_size() + 1 + 71 + 1 + 33;
    let witness = 2 + 1 + (1 + (1 + 71) + (1 + 33));
    assert_eq!(model.vsize.get(), ((4 * base + witness) as u64).div_ceil(4));
    // And it is a discount: the witness bytes cost a quarter each.
    assert!(model.vsize.get() < (base + witness) as u64);
}

/// BIP49 pays for both halves — a `scriptSig` push of the redeem script *and* a witness.
#[test]
fn bip49_pays_for_the_redeem_script_and_the_witness() {
    let wallet = wallet();
    let spk = our_spk(&wallet, Family::Bip49);
    let psbt = two_out(Family::Bip49, &spk);

    let base = psbt.unsigned_tx.base_size() + 1 + 22;
    let witness = 2 + (1 + (1 + 71) + (1 + 33));
    assert_eq!(
        accept(&psbt).vsize.get(),
        ((4 * base + witness) as u64).div_ceil(4)
    );
}

/// The addresses on the panel are the **loaded network's**, not a network-free stand-in — which
/// is the one thing rendering needs the whole network for.
#[test]
fn the_addresses_on_the_panel_are_the_loaded_networks() {
    let testnet = wallet_on(Network::Testnet);
    let spk = our_spk(&testnet, Family::Bip84);
    let model = review(
        &testnet,
        &psbt_for(&testnet, &[(Family::Bip84, 100_000)], &[(spk, 90_000)]),
    );

    assert_eq!(model.network, Network::Testnet);
    assert!(
        model.outputs[0].address.to_string().starts_with("tb1"),
        "{}",
        model.outputs[0].address
    );
}

/// A declared path too short to read a coin type out of claims no network, so `AOBS-R06`'s
/// fourth variant stays silent rather than asserting something about a path that is not there.
#[test]
fn an_input_declaring_a_path_too_short_to_read_claims_no_network() {
    let wallet = wallet();
    let stranger = stranger();
    let mut psbt = psbt_for(
        &stranger,
        &[(Family::Bip84, 100_000)],
        &[(our_spk(&stranger, Family::Bip84), 90_000)],
    );
    psbt.inputs[0].bip32_derivation.clear();
    declare_input(
        &mut psbt.inputs[0],
        Family::Bip84,
        &our_key(&wallet, Family::Bip84, 0, 0),
        wallet.fingerprint(),
        DerivationPath::from(vec![ChildNumber::Hardened { index: 84 }]),
    );

    assert_eq!(
        refusal(&wallet, &psbt),
        Refusal::NoInputOfOurs {
            network: Network::Mainnet,
            passphrase_in_use: false,
            coin_type_mismatch: false,
        }
    );
}
