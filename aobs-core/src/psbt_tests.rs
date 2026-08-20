//! The structural checks from the accepting side, plus the BIP-174 invalid vectors that must
//! *not* become refusals.
//!
//! The refusing side is the corpus (`crate::corpus`), where every case is named and asserts its
//! code. What lives here is everything a corpus case cannot say: the shapes that pass, the
//! boundaries either side of a bound, and the two claims the module's own comments make about
//! itself — that renderability is network-independent, and that the previous transaction beats
//! a `witness_utxo` that disagrees with it.

use bitcoin::psbt::{Error as PsbtError, PsbtSighashType};
use bitcoin::{Amount, ScriptBuf};

use super::*;
use crate::corpus::{from_hex, one_in_one_out, our_spk, psbt, wallet};
use crate::derive::Family;

/// BIP-174's other four invalid vectors, transcribed from `bitcoin-0.32`'s own tests, which
/// are the BIP's hex. None of them is a refusal: they are bytes that never became a PSBT.
const INVALID_VECTOR_1: &str = "0200000001268171371edff285e937adeea4b37b78000c0566cbb3ad64641713ca42171bf6000000006a473044022070b2245123e6bf474d60c5b50c043d4c691a5d2435f09a34a7662a9dc251790a022001329ca9dacf280bdf30740ec0390422422c81cb45839457aeb76fc12edd95b3012102657d118d3357b8e0f4c2cd46db7b39f6d9c38d9a70abcb9b2de5dc8dbfe4ce31feffffff02d3dff505000000001976a914d0c59903c5bac2868760e90fd521a4665aa7652088ac00e1f5050000000017a9143545e6e33b832c47050f24d3eeb93c9c03948bc787b32e1300";
const INVALID_VECTOR_2: &str = "70736274ff0100750200000001268171371edff285e937adeea4b37b78000c0566cbb3ad64641713ca42171bf60000000000feffffff02d3dff505000000001976a914d0c59903c5bac2868760e90fd521a4665aa7652088ac00e1f5050000000017a9143545e6e33b832c47050f24d3eeb93c9c03948bc787b32e1300000100fda5010100000000010289a3c71eab4d20e0371bbba4cc698fa295c9463afa2e397f8533ccb62f9567e50100000017160014be18d152a9b012039daf3da7de4f53349eecb985ffffffff86f8aa43a71dff1448893a530a7237ef6b4608bbb2dd2d0171e63aec6a4890b40100000017160014fe3e9ef1a745e974d902c4355943abcb34bd5353ffffffff0200c2eb0b000000001976a91485cff1097fd9e008bb34af709c62197b38978a4888ac72fef84e2c00000017a914339725ba21efd62ac753a9bcd067d6c7a6a39d05870247304402202712be22e0270f394f568311dc7ca9a68970b8025fdd3b240229f07f8a5f3a240220018b38d7dcd314e734c9276bd6fb40f673325bc4baa144c800d2f2f02db2765c012103d2e15674941bad4a996372cb87e1856d3652606d98562fe39c5e9e7e413f210502483045022100d12b852d85dcd961d2f5f4ab660654df6eedcc794c0c33ce5cc309ffb5fce58d022067338a8e0e1725c197fb1a88af59f51e44e4255b20167c8684031c05d1f2592a01210223b72beef0965d10be0778efecd61fcac6f79a4ea169393380734464f84f2ab30000000000";
const INVALID_VECTOR_3: &str = "70736274ff0100fd0a010200000002ab0949a08c5af7c49b8212f417e2f15ab3f5c33dcf153821a8139f877a5b7be4000000006a47304402204759661797c01b036b25928948686218347d89864b719e1f7fcf57d1e511658702205309eabf56aa4d8891ffd111fdf1336f3a29da866d7f8486d75546ceedaf93190121035cdc61fc7ba971c0b501a646a2a83b102cb43881217ca682dc86e2d73fa88292feffffffab0949a08c5af7c49b8212f417e2f15ab3f5c33dcf153821a8139f877a5b7be40100000000feffffff02603bea0b000000001976a914768a40bbd740cbe81d988e71de2a4d5c71396b1d88ac8e240000000000001976a9146f4620b553fa095e721b9ee0efe9fa039cca459788ac00000000000001012000e1f5050000000017a9143545e6e33b832c47050f24d3eeb93c9c03948bc787010416001485d13537f2e265405a34dbafa9e3dda01fb82308000000";
const INVALID_VECTOR_4: &str = "70736274ff000100fda5010100000000010289a3c71eab4d20e0371bbba4cc698fa295c9463afa2e397f8533ccb62f9567e50100000017160014be18d152a9b012039daf3da7de4f53349eecb985ffffffff86f8aa43a71dff1448893a530a7237ef6b4608bbb2dd2d0171e63aec6a4890b40100000017160014fe3e9ef1a745e974d902c4355943abcb34bd5353ffffffff0200c2eb0b000000001976a91485cff1097fd9e008bb34af709c62197b38978a4888ac72fef84e2c00000017a914339725ba21efd62ac753a9bcd067d6c7a6a39d05870247304402202712be22e0270f394f568311dc7ca9a68970b8025fdd3b240229f07f8a5f3a240220018b38d7dcd314e734c9276bd6fb40f673325bc4baa144c800d2f2f02db2765c012103d2e15674941bad4a996372cb87e1856d3652606d98562fe39c5e9e7e413f210502483045022100d12b852d85dcd961d2f5f4ab660654df6eedcc794c0c33ce5cc309ffb5fce58d022067338a8e0e1725c197fb1a88af59f51e44e4255b20167c8684031c05d1f2592a01210223b72beef0965d10be0778efecd61fcac6f79a4ea169393380734464f84f2ab30000000000";

fn accept(psbt: &Psbt) -> Psbt {
    let bytes = psbt.serialize();
    match validate(&bytes) {
        Ok(accepted) => accepted,
        Err(rejection) => panic!("refused a transaction the policy accepts: {rejection:?}"),
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
    assert_eq!(validate(&bytes).expect("accepted").serialize(), bytes);
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
        validate(&psbt(&[(Family::Bip84, 100_000)], &seven).serialize()),
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
        validate(&psbt.serialize()),
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
        validate(&psbt.serialize()),
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
    let accepted = validate(&bytes).expect("unknown fields never influence a decision");

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
    assert_eq!(validate(&bytes), Err(Rejection::NotAPsbt));
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
        assert_eq!(validate(&bytes), Err(Rejection::NotAPsbt));
    }
}

#[test]
fn a_truncated_psbt_is_not_a_refusal() {
    let bytes = one_in_one_out().serialize();
    for cut in [1, bytes.len() / 2, bytes.len() - 1] {
        assert_eq!(validate(&bytes[..cut]), Err(Rejection::NotAPsbt));
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

    let Err(Rejection::Refused(refusal)) = validate(&psbt.serialize()) else {
        panic!("the second input carries no utxo at all");
    };
    assert_eq!(refusal, Refusal::PreviousTransactionAbsent { input: 1 });
    assert!(refusal.reason().contains("Input 2"), "{}", refusal.reason());
}
