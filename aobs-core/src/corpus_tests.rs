//! The adversarial corpus (`05-testing-and-release.md` §5) and the registry bijection
//! (`06-codes.md` §7).
//!
//! **A checked-in regression suite, not fuzz seeds.** Every refusal gets a named case, the name
//! is the code, and each case asserts the `AOBS-R##` its refusal carries. It lives at the crate
//! root rather than beside one module because the registry does: the structural refusals are
//! `psbt`'s and `R10`/`R11` are `ur`'s, both tabled here, and `R12`–`R14` are the backup's and
//! will join them.
//!
//! **Three tables, because the three halves end differently.** [`CASES`] runs hostile bytes
//! through `psbt::validate`, where every case is a refusal. [`TRANSPORT_CASES`] runs scanned
//! symbols through a `ur::Scanner`, where §5's own list includes a bound that **accepts** (the
//! 64 KiB boundary, exactly at the limit) and several that drop with no code at all — so the
//! outcome, not the code, is what a transport case asserts. [`ADDRESS_CASES`] runs §5's
//! address-shaped entries through `Wallet::find_address`, where **nothing carries a code at
//! all**: a receive verification has two outcomes and neither is a refusal (`02-core.md` §10,
//! `04-screens.md` §12), so that table contributes nothing to the bijection and is here because
//! §5 puts those entries in the corpus — which is also
//! [`05-testing-and-release.md` §4's deliberate exception](https://github.com/allisson/aobs/issues/83):
//! the address path gets **no fuzz target**, and these cases are what earn their place instead.
//!
//! **Two readings this file settles, both stated because a later reader would otherwise have to
//! guess.**
//!
//! 1. *In bijection* is between the **set of codes** on each side, not between cases and codes
//!    one-for-one. §5's own list of cases names duplicate keys in *each* map and both halves of
//!    the `non_witness_utxo` rule, which are four cases carrying two codes — so a literal
//!    one-case-per-code reading contradicts the list it appears next to. What the tests below
//!    hold is: every code a `Refusal` variant can produce has at least one case, every case
//!    names a code the registry defines, and no case names a code that is not there.
//! 2. The registry is complete and the implementation is not, so the third direction — every
//!    code in `06-codes.md` §6 has a case — cannot hold until the last refusal ships. It is not
//!    weakened into a comment: [`PENDING`] names each unimplemented code and the ticket that
//!    owes it, and [`the_registry_is_implemented_or_pending`] asserts the two lists together
//!    are exactly the registry. A code appearing in the registry that is neither implemented
//!    nor listed as owed fails; so does a code listed as owed that has quietly been
//!    implemented.

use bitcoin::bip32::{ChildNumber, DerivationPath, Fingerprint, Xpub};
use bitcoin::hashes::Hash as _;
use bitcoin::opcodes::all::{OP_CHECKMULTISIG, OP_CHECKSIG, OP_PUSHNUM_1, OP_RETURN};
use bitcoin::psbt::{Input, Output, Psbt, PsbtSighashType};
use bitcoin::secp256k1::{schnorr, Secp256k1};
use bitcoin::sighash::TapSighashType;
use bitcoin::taproot::{self, TapNodeHash};
use bitcoin::transaction::Version;
use bitcoin::{absolute, Amount, OutPoint, ScriptBuf, Sequence, Transaction, TxIn, TxOut, Witness};

use crate::bip39::Mnemonic;
use crate::derive::{Branch, Family, Network, Wallet};
use crate::psbt::{validate, Refusal, Rejection};
use crate::secret::{Entropy, Passphrase};
use crate::ur::{Class, Outcome, Scanner, PART_BUDGET};

// --- the fixture -------------------------------------------------------------------------

/// The `abandon … about` wallet on mainnet — the one every vector table in the repo is
/// written for.
///
/// Whose keys these are does not matter to a structural check, and using ours anyway costs
/// nothing and leaves the corpus reusable by the derivation check that comes next.
pub(crate) fn wallet() -> Wallet {
    wallet_on(Network::Mainnet)
}

/// The same seed on a chosen network — for the one case whose whole subject is that the two
/// disagree.
///
/// The master fingerprint is byte-identical on both (`02-core.md` §6), so a testnet PSBT built
/// from this seed claims *our* fingerprint and still re-derives to nothing on mainnet. That is
/// exactly the symptomless network mismatch `AOBS-R06`'s fourth copy variant exists for.
pub(crate) fn wallet_on(network: Network) -> Wallet {
    let mnemonic = Mnemonic::from_entropy(&Entropy::new(&[0u8; 16]).expect("16 bytes fit"))
        .expect("16 bytes is an accepted length");
    Wallet::load(
        &mnemonic,
        &Passphrase::new("").expect("empty fits"),
        network,
    )
}

/// The `scriptPubKey` of our first receive address in one family.
pub(crate) fn our_spk(wallet: &Wallet, family: Family) -> ScriptBuf {
    wallet
        .address(family, Branch::Receive, 0)
        .expect("index 0 is a normal child")
        .script_pubkey()
}

/// The P2WPKH redeem script BIP49 wraps, derived independently of [`our_spk`].
fn our_redeem_script(wallet: &Wallet) -> ScriptBuf {
    let secp = Secp256k1::verification_only();
    let key = wallet
        .account_xpub(Family::Bip49)
        .derive_pub(&secp, &[normal(0), normal(0)])
        .expect("normal children of an xpub always derive");
    ScriptBuf::new_p2wpkh(&key.to_pub().wpubkey_hash())
}

pub(crate) fn normal(index: u32) -> ChildNumber {
    ChildNumber::Normal { index }
}

/// The key at `family`/`branch`/`index` under this wallet's accounts, derived independently of
/// [`our_spk`] so a case can name a key without going through an address.
pub(crate) fn our_key(wallet: &Wallet, family: Family, branch: u32, index: u32) -> Xpub {
    let secp = Secp256k1::verification_only();
    wallet
        .account_xpub(family)
        .derive_pub(&secp, &[normal(branch), normal(index)])
        .expect("normal children of an xpub always derive")
}

/// The full path to `family`/`branch`/`index`, which is what an honest coordinator declares.
pub(crate) fn our_path(wallet: &Wallet, family: Family, branch: u32, index: u32) -> DerivationPath {
    wallet
        .account_path(family)
        .extend([normal(branch), normal(index)])
}

/// Declare `(fingerprint, path)` as `key`'s origin on an input, in whichever of the two PSBT
/// maps `family` uses — `tap_key_origins` for BIP86 and `bip32_derivation` for the rest.
pub(crate) fn declare_input(
    input: &mut Input,
    family: Family,
    key: &Xpub,
    fingerprint: Fingerprint,
    path: DerivationPath,
) {
    if family == Family::Bip86 {
        input
            .tap_key_origins
            .insert(key.to_x_only_pub(), (vec![], (fingerprint, path)));
    } else {
        input
            .bip32_derivation
            .insert(key.public_key, (fingerprint, path));
    }
}

/// The same, on an output — where a claim is what makes the output a *candidate* for being our
/// change (`02-core.md` §7).
pub(crate) fn declare_output(
    output: &mut Output,
    family: Family,
    key: &Xpub,
    fingerprint: Fingerprint,
    path: DerivationPath,
) {
    if family == Family::Bip86 {
        output
            .tap_key_origins
            .insert(key.to_x_only_pub(), (vec![], (fingerprint, path)));
    } else {
        output
            .bip32_derivation
            .insert(key.public_key, (fingerprint, path));
    }
}

/// A funding transaction paying `value` to `spk`, distinct per `nonce` so two inputs of the
/// same family do not share an outpoint.
///
/// It carries one dummy input because a transaction with none is ambiguous with the segwit
/// marker on the way back in — it is only ever hashed, and nothing here spends it.
fn funding(spk: ScriptBuf, value: Amount, nonce: u32) -> Transaction {
    Transaction {
        version: Version::TWO,
        lock_time: absolute::LockTime::from_height(nonce).expect("small heights are valid"),
        input: vec![TxIn {
            previous_output: OutPoint::null(),
            script_sig: ScriptBuf::new(),
            sequence: Sequence::MAX,
            witness: Witness::new(),
        }],
        output: vec![TxOut {
            value,
            script_pubkey: spk,
        }],
    }
}

/// A PSBT spending one input per entry in `inputs` and paying each entry in `outputs`, from the
/// mainnet fixture wallet.
pub(crate) fn psbt(inputs: &[(Family, u64)], outputs: &[(ScriptBuf, u64)]) -> Psbt {
    psbt_for(&wallet(), inputs, outputs)
}

/// The same, for a chosen wallet — which is how the network-mismatch case builds a PSBT one
/// wallet will recognise and another will not.
///
/// Every input is complete and honest: the full previous transaction, the `witness_utxo`
/// beside it, BIP49's redeem script, and the BIP32 origin a coordinator declares. Each case
/// below breaks exactly one of those.
pub(crate) fn psbt_for(
    wallet: &Wallet,
    inputs: &[(Family, u64)],
    outputs: &[(ScriptBuf, u64)],
) -> Psbt {
    let previous: Vec<Transaction> = inputs
        .iter()
        .enumerate()
        .map(|(nonce, &(family, sats))| {
            funding(
                our_spk(wallet, family),
                Amount::from_sat(sats),
                u32::try_from(nonce).expect("the suite has few inputs"),
            )
        })
        .collect();

    let unsigned = Transaction {
        version: Version::TWO,
        lock_time: absolute::LockTime::ZERO,
        input: previous
            .iter()
            .map(|prev| TxIn {
                previous_output: OutPoint {
                    txid: prev.compute_txid(),
                    vout: 0,
                },
                script_sig: ScriptBuf::new(),
                sequence: Sequence::MAX,
                witness: Witness::new(),
            })
            .collect(),
        output: outputs
            .iter()
            .map(|(spk, sats)| TxOut {
                value: Amount::from_sat(*sats),
                script_pubkey: spk.clone(),
            })
            .collect(),
    };

    let mut psbt = Psbt::from_unsigned_tx(unsigned).expect("the transaction is unsigned");
    for (slot, (previous, &(family, _))) in psbt.inputs.iter_mut().zip(previous.iter().zip(inputs))
    {
        slot.witness_utxo = Some(previous.output[0].clone());
        slot.non_witness_utxo = Some(previous.clone());
        if family == Family::Bip49 {
            slot.redeem_script = Some(our_redeem_script(wallet));
        }
        // BIP-371's declaration that this is a key-path spend, which `AOBS-R05` requires and
        // which the taproot signing path reads the internal key out of. The *internal*
        // x-only key, untweaked — the tweak is what the `scriptPubKey` already carries.
        if family == Family::Bip86 {
            slot.tap_internal_key = Some(our_key(wallet, family, 0, 0).to_x_only_pub());
        }
        // The origin an honest coordinator declares. Without it no input re-derives to ours and
        // every case here would refuse on `AOBS-R06` before reaching what it is about.
        declare_input(
            slot,
            family,
            &our_key(wallet, family, 0, 0),
            wallet.fingerprint(),
            our_path(wallet, family, 0, 0),
        );
    }
    psbt
}

/// 64 bytes an attacker can write into `tap_key_sig` or a `tap_script_sigs` entry
/// ([#115](https://github.com/allisson/aobs/issues/115)).
///
/// Nothing verifies it, and that is `AOBS-R17`'s whole point: the refusal is for the input carrying
/// a signature at all, so a fixture that took the trouble to be *valid* would be testing a shape no
/// attacker needs.
pub(crate) fn nonsense_schnorr_signature() -> taproot::Signature {
    taproot::Signature {
        signature: schnorr::Signature::from_slice(&[0x42; 64])
            .expect("64 bytes is a signature's length"),
        sighash_type: TapSighashType::Default,
    }
}

/// The commonest honest shape: one P2WPKH input of 100 000 sat paying 90 000 to a P2WPKH
/// address of ours, 10 000 to the fee.
pub(crate) fn one_in_one_out() -> Psbt {
    let spk = our_spk(&wallet(), Family::Bip84);
    psbt(&[(Family::Bip84, 100_000)], &[(spk, 90_000)])
}

// --- byte surgery, for the three duplicates the type system cannot express -----------------

/// A raw PSBT key-value pair: `<keylen><type><keydata><valuelen><value>`.
fn pair(key_type: u8, key_data: &[u8], value: &[u8]) -> Vec<u8> {
    let mut out = compact_size(1 + key_data.len() as u64);
    out.push(key_type);
    out.extend_from_slice(key_data);
    out.extend(compact_size(value.len() as u64));
    out.extend_from_slice(value);
    out
}

fn compact_size(n: u64) -> Vec<u8> {
    match n {
        0..=0xfc => vec![n as u8],
        0xfd..=0xffff => {
            let mut out = vec![0xfd];
            out.extend_from_slice(&(n as u16).to_le_bytes());
            out
        }
        _ => {
            let mut out = vec![0xfe];
            out.extend_from_slice(&(n as u32).to_le_bytes());
            out
        }
    }
}

/// Insert a second copy of `pair` immediately after the one already in `bytes`.
///
/// Locating it by search rather than by offset arithmetic, and asserting it was found, is what
/// stops a case from silently testing a valid PSBT if the dependency's serialisation moves.
fn duplicate(bytes: &[u8], pair: &[u8]) -> Vec<u8> {
    let at = bytes
        .windows(pair.len())
        .position(|window| window == pair)
        .expect("the pair we built is the pair the dependency serialised");
    let mut out = bytes[..at + pair.len()].to_vec();
    out.extend_from_slice(pair);
    out.extend_from_slice(&bytes[at + pair.len()..]);
    out
}

/// The global map's unsigned-transaction pair, duplicated: `decode_global`'s own arm.
fn duplicated_global_unsigned_tx() -> Vec<u8> {
    let psbt = one_in_one_out();
    let value = bitcoin::consensus::serialize(&psbt.unsigned_tx);
    duplicate(&psbt.serialize(), &pair(0x00, &[], &value))
}

/// Two identical `PSBT_GLOBAL_XPUB` entries: the arm that raises `XPubKey` rather than
/// `DuplicateKey`, which §7 requires we map onto the same refusal.
fn duplicated_global_xpub() -> Vec<u8> {
    let wallet = wallet();
    let xpub: Xpub = *wallet.account_xpub(Family::Bip44);
    let path = wallet.account_path(Family::Bip44);

    let mut value = wallet.fingerprint().to_bytes().to_vec();
    for child in path.into_iter() {
        value.extend_from_slice(&u32::from(*child).to_le_bytes());
    }

    let mut psbt = one_in_one_out();
    psbt.xpub.insert(xpub, (wallet.fingerprint(), path));
    duplicate(&psbt.serialize(), &pair(0x01, &xpub.encode(), &value))
}

/// A duplicated unknown key in the last output map.
///
/// The serialisation is global map, then every input map, then every output map — each ending
/// in its `0x00` separator — so the final byte is the last output map's, and a pair spliced in
/// front of it lands in that map.
fn duplicated_output_key() -> Vec<u8> {
    let bytes = one_in_one_out().serialize();
    let unknown = pair(0x77, &[], &[]);
    let split = bytes.len() - 1;
    let mut out = bytes[..split].to_vec();
    out.extend_from_slice(&unknown);
    out.extend_from_slice(&unknown);
    out.extend_from_slice(&bytes[split..]);
    out
}

// --- the cases ---------------------------------------------------------------------------

/// One named case: what it is, the code it must refuse with, and the bytes that do it.
pub(crate) struct Case {
    /// What the case is, in the words §5 uses for it.
    pub name: &'static str,
    /// The `AOBS-R##` the refusal must carry.
    pub code: &'static str,
    /// The whole refusal, for a case whose subject is **which copy variant** it earns rather
    /// than only which code.
    ///
    /// `None` for the cases where the code is the whole claim. `Some` where §5 names the
    /// variant — the network mismatch's row says *`AOBS-R06` with the coin-type copy variant*,
    /// and a case asserting the code alone would discharge that row in a weaker form than it
    /// is written in.
    pub refusal: Option<Refusal>,
    /// The hostile bytes.
    pub bytes: fn() -> Vec<u8>,
}

/// BIP-174's **invalid vector 5** — a duplicate `PSBT_IN_NON_WITNESS_UTXO` key in an input map.
///
/// The one case in this suite we did not author. It is here because the duplicate-key refusal
/// rests on the dependency's invariant rather than on our own scan (`02-core.md` §7), and a
/// future relaxation of it has to trip an alarm on the vector the BIP itself publishes.
/// Transcribed from `bitcoin-0.32`'s `invalid_vector_5`, which is BIP-174's own hex.
const BIP174_INVALID_VECTOR_5: &str = "70736274ff0100750200000001268171371edff285e937adeea4b37b78000c0566cbb3ad64641713ca42171bf60000000000feffffff02d3dff505000000001976a914d0c59903c5bac2868760e90fd521a4665aa7652088ac00e1f5050000000017a9143545e6e33b832c47050f24d3eeb93c9c03948bc787b32e1300000100fda5010100000000010289a3c71eab4d20e0371bbba4cc698fa295c9463afa2e397f8533ccb62f9567e50100000017160014be18d152a9b012039daf3da7de4f53349eecb985ffffffff86f8aa43a71dff1448893a530a7237ef6b4608bbb2dd2d0171e63aec6a4890b40100000017160014fe3e9ef1a745e974d902c4355943abcb34bd5353ffffffff0200c2eb0b000000001976a91485cff1097fd9e008bb34af709c62197b38978a4888ac72fef84e2c00000017a914339725ba21efd62ac753a9bcd067d6c7a6a39d05870247304402202712be22e0270f394f568311dc7ca9a68970b8025fdd3b240229f07f8a5f3a240220018b38d7dcd314e734c9276bd6fb40f673325bc4baa144c800d2f2f02db2765c012103d2e15674941bad4a996372cb87e1856d3652606d98562fe39c5e9e7e413f210502483045022100d12b852d85dcd961d2f5f4ab660654df6eedcc794c0c33ce5cc309ffb5fce58d022067338a8e0e1725c197fb1a88af59f51e44e4255b20167c8684031c05d1f2592a01210223b72beef0965d10be0778efecd61fcac6f79a4ea169393380734464f84f2ab30000000001003f0200000001ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff0000000000ffffffff010000000000000000036a010000000000000000";

/// secp256k1's generator point, in compressed form: a valid public key nobody controls, for
/// the cases whose subject is the script's shape rather than whose key it holds.
const GENERATOR: &str = "0279be667ef9dcbbac55a06295ce870b07029bfcdb2dce28d959f2815b16f81798";

/// Hex to bytes, for the one case that arrives as text.
pub(crate) fn from_hex(hex: &str) -> Vec<u8> {
    assert!(hex.len().is_multiple_of(2), "hex comes in pairs");
    (0..hex.len() / 2)
        .map(|i| u8::from_str_radix(&hex[i * 2..i * 2 + 2], 16).expect("hex digits"))
        .collect()
}

/// The corpus. Every refusal this crate can produce is named here, and the tests below hold
/// that claim to the registry.
pub(crate) const CASES: &[Case] = &[
    Case {
        name: "duplicate keys in an input map (BIP-174 invalid vector 5)",
        code: "AOBS-R01",
        refusal: None,
        bytes: || from_hex(BIP174_INVALID_VECTOR_5),
    },
    Case {
        name: "duplicate keys in the global map",
        code: "AOBS-R01",
        refusal: None,
        bytes: duplicated_global_unsigned_tx,
    },
    Case {
        name: "duplicate keys in an output map",
        code: "AOBS-R01",
        refusal: None,
        bytes: duplicated_output_key,
    },
    Case {
        name: "a duplicate global xpub, which arrives as a different error variant",
        code: "AOBS-R01",
        refusal: None,
        bytes: duplicated_global_xpub,
    },
    Case {
        name: "a legacy input with witness_utxo only",
        code: "AOBS-R02",
        refusal: None,
        bytes: || {
            let mut psbt = psbt(
                &[(Family::Bip44, 100_000)],
                &[(our_spk(&wallet(), Family::Bip84), 90_000)],
            );
            psbt.inputs[0].non_witness_utxo = None;
            psbt.serialize()
        },
    },
    Case {
        name: "a segwit input with witness_utxo only — stricter than Krux on purpose",
        code: "AOBS-R02",
        refusal: None,
        bytes: || {
            let mut psbt = one_in_one_out();
            psbt.inputs[0].non_witness_utxo = None;
            psbt.serialize()
        },
    },
    Case {
        name: "an input carrying neither utxo field",
        code: "AOBS-R02",
        refusal: None,
        bytes: || {
            let mut psbt = one_in_one_out();
            psbt.inputs[0].non_witness_utxo = None;
            psbt.inputs[0].witness_utxo = None;
            psbt.serialize()
        },
    },
    Case {
        name: "a non_witness_utxo that does not hash to its outpoint",
        code: "AOBS-R02",
        refusal: None,
        bytes: || {
            let mut psbt = one_in_one_out();
            let previous = psbt.inputs[0]
                .non_witness_utxo
                .as_mut()
                .expect("the fixture carries one");
            // One satoshi more than the outpoint's transaction pays: the BIP-143
            // amount-spoofing class, in its smallest possible form.
            previous.output[0].value += Amount::ONE_SAT;
            psbt.serialize()
        },
    },
    Case {
        name: "a previous transaction with no output at the index spent",
        code: "AOBS-R02",
        refusal: None,
        bytes: || {
            let mut psbt = one_in_one_out();
            let previous = psbt.inputs[0]
                .non_witness_utxo
                .clone()
                .expect("the fixture carries one");
            psbt.unsigned_tx.input[0].previous_output = OutPoint {
                txid: previous.compute_txid(),
                vout: 1,
            };
            psbt.serialize()
        },
    },
    Case {
        name: "SIGHASH_SINGLE",
        code: "AOBS-R03",
        refusal: None,
        bytes: || sighash_case(0x03),
    },
    Case {
        name: "SIGHASH_NONE",
        code: "AOBS-R03",
        refusal: None,
        bytes: || sighash_case(0x02),
    },
    Case {
        name: "SIGHASH_ALL | ANYONECANPAY",
        code: "AOBS-R03",
        refusal: None,
        bytes: || sighash_case(0x81),
    },
    Case {
        name: "a taproot input asking for SIGHASH_ALL | ANYONECANPAY",
        code: "AOBS-R03",
        refusal: None,
        bytes: || {
            let spk = our_spk(&wallet(), Family::Bip84);
            let mut psbt = psbt(&[(Family::Bip86, 100_000)], &[(spk, 90_000)]);
            psbt.inputs[0].sighash_type = Some(PsbtSighashType::from_u32(0x81));
            psbt.serialize()
        },
    },
    Case {
        name: "outputs exceeding inputs",
        code: "AOBS-R04",
        refusal: None,
        bytes: || {
            let spk = our_spk(&wallet(), Family::Bip84);
            psbt(&[(Family::Bip84, 100_000)], &[(spk, 100_001)]).serialize()
        },
    },
    Case {
        name: "a P2WSH input",
        code: "AOBS-R05",
        refusal: None,
        bytes: || {
            foreign_script_case(ScriptBuf::new_p2wsh(
                &our_redeem_script(&wallet()).wscript_hash(),
            ))
        },
    },
    Case {
        name: "a bare multisig input",
        code: "AOBS-R05",
        refusal: None,
        bytes: || {
            foreign_script_case(
                bitcoin::script::Builder::new()
                    .push_opcode(OP_PUSHNUM_1)
                    .push_key(&GENERATOR.parse().expect("a valid compressed key"))
                    .push_opcode(OP_PUSHNUM_1)
                    .push_opcode(OP_CHECKMULTISIG)
                    .into_script(),
            )
        },
    },
    Case {
        name: "a P2SH input with no redeem script",
        code: "AOBS-R05",
        refusal: None,
        bytes: || {
            let spk = our_spk(&wallet(), Family::Bip84);
            let mut psbt = psbt(&[(Family::Bip49, 100_000)], &[(spk, 90_000)]);
            psbt.inputs[0].redeem_script = None;
            psbt.serialize()
        },
    },
    Case {
        name: "a P2SH input whose redeem script is not a P2WPKH",
        code: "AOBS-R05",
        refusal: None,
        bytes: || {
            // A P2SH paying to a redeem script we hand over honestly — it hashes, and it is
            // a multisig, so it is outside the four families rather than a lie.
            let redeem = bitcoin::script::Builder::new()
                .push_opcode(OP_PUSHNUM_1)
                .push_key(&GENERATOR.parse().expect("a valid compressed key"))
                .push_opcode(OP_PUSHNUM_1)
                .push_opcode(OP_CHECKMULTISIG)
                .into_script();
            let spk = our_spk(&wallet(), Family::Bip84);
            let mut psbt = psbt(&[(Family::Bip49, 100_000)], &[(spk, 90_000)]);
            let previous = psbt.inputs[0]
                .non_witness_utxo
                .as_mut()
                .expect("the fixture carries one");
            previous.output[0].script_pubkey = ScriptBuf::new_p2sh(&redeem.script_hash());
            let previous = previous.clone();
            psbt.inputs[0].witness_utxo = Some(previous.output[0].clone());
            psbt.inputs[0].redeem_script = Some(redeem);
            psbt.unsigned_tx.input[0].previous_output = OutPoint {
                txid: previous.compute_txid(),
                vout: 0,
            };
            psbt.serialize()
        },
    },
    Case {
        name: "a P2SH input whose redeem script does not hash to the scriptPubKey",
        code: "AOBS-R05",
        refusal: None,
        bytes: || {
            let spk = our_spk(&wallet(), Family::Bip84);
            let mut psbt = psbt(&[(Family::Bip49, 100_000)], &[(spk, 90_000)]);
            // A P2WPKH redeem script, and a legitimate one — for a different key.
            psbt.inputs[0].redeem_script = Some(ScriptBuf::new_p2wpkh(
                &bitcoin::WPubkeyHash::from_byte_array([0x11; 20]),
            ));
            psbt.serialize()
        },
    },
    Case {
        name: "a taproot input spent through a script path",
        code: "AOBS-R05",
        refusal: None,
        bytes: || {
            let spk = our_spk(&wallet(), Family::Bip84);
            let mut psbt = psbt(&[(Family::Bip86, 100_000)], &[(spk, 90_000)]);
            psbt.inputs[0].tap_merkle_root = Some(TapNodeHash::from_byte_array([0x22; 32]));
            psbt.serialize()
        },
    },
    Case {
        name: "a taproot input whose internal key has no origin entry of its own",
        code: "AOBS-R05",
        refusal: None,
        bytes: || taproot_internal_key_orphaned().serialize(),
    },
    Case {
        name: "a taproot input whose only verifying claim is not the internal key's",
        code: "AOBS-R06",
        refusal: None,
        bytes: || taproot_key_path_diverted().serialize(),
    },
    Case {
        name: "an output we cannot render as an address",
        code: "AOBS-R07",
        refusal: None,
        bytes: || {
            let op_return = bitcoin::script::Builder::new()
                .push_opcode(OP_RETURN)
                .push_slice([0x41u8; 8])
                .into_script();
            psbt(&[(Family::Bip84, 100_000)], &[(op_return, 0)]).serialize()
        },
    },
    Case {
        name: "an output paying a bare public key",
        code: "AOBS-R07",
        refusal: None,
        bytes: || {
            // P2PK: spendable, relayable, and with no address form in any encoding — the
            // second half of why the rule is *renderable* rather than *not an OP_RETURN*.
            let spk = bitcoin::script::Builder::new()
                .push_key(&GENERATOR.parse().expect("a valid compressed key"))
                .push_opcode(OP_CHECKSIG)
                .into_script();
            psbt(&[(Family::Bip84, 100_000)], &[(spk, 90_000)]).serialize()
        },
    },
    Case {
        name: "seven outputs",
        code: "AOBS-R15",
        refusal: None,
        bytes: || {
            let spk = our_spk(&wallet(), Family::Bip84);
            let outputs: Vec<(ScriptBuf, u64)> = (0..7).map(|_| (spk.clone(), 10_000)).collect();
            psbt(&[(Family::Bip84, 1_000_000)], &outputs).serialize()
        },
    },
    Case {
        name: "outputs packed to the transport bound",
        code: "AOBS-R15",
        refusal: None,
        bytes: || {
            // §5's ~2,000-output case: the panel is what bounds this, not the byte count, and
            // the refusal has to be the count rather than whatever the walk would have hit.
            let spk = our_spk(&wallet(), Family::Bip84);
            let outputs: Vec<(ScriptBuf, u64)> = (0..2_000).map(|_| (spk.clone(), 1_000)).collect();
            psbt(&[(Family::Bip84, 21_000_000_000_000_000)], &outputs).serialize()
        },
    },
    Case {
        name: "two taproot inputs each claiming u64::MAX satoshis",
        code: "AOBS-R16",
        refusal: None,
        bytes: || {
            // Taproot needs only its `witness_utxo` and nothing cross-checks the amount, so
            // this is the cheapest way to a sum no `u64` can hold — which is the case the
            // refusal exists for, rather than a single amount one satoshi over the supply.
            let spk = our_spk(&wallet(), Family::Bip84);
            psbt(
                &[(Family::Bip86, u64::MAX), (Family::Bip86, u64::MAX)],
                &[(spk, 90_000)],
            )
            .serialize()
        },
    },
    Case {
        name: "a taproot input arriving with a signature already in it",
        code: "AOBS-R17",
        refusal: None,
        bytes: || {
            // **The shape #115 was opened for.** 64 bytes of nonsense in `tap_key_sig` on an
            // input that re-derives to ours: `bitcoin` 0.32's key path declines an input whose
            // `tap_key_sig` is already set, so before `AOBS-R17` this document was accepted,
            // reviewed, held for three seconds and handed back unchanged under a screen reading
            // *Signed*. Nothing here checks the signature — that it is nonsense is the point.
            let spk = our_spk(&wallet(), Family::Bip84);
            let mut psbt = psbt(&[(Family::Bip86, 100_000)], &[(spk, 90_000)]);
            psbt.inputs[0].tap_key_sig = Some(nonsense_schnorr_signature());
            psbt.serialize()
        },
    },
    Case {
        name: "a testnet PSBT against a mainnet-loaded wallet",
        code: "AOBS-R06",
        refusal: Some(Refusal::NoInputOfOurs {
            network: Network::Mainnet,
            passphrase_in_use: false,
            coin_type_mismatch: true,
        }),
        bytes: || {
            // The same seed, the same fingerprint, and coin type `1h` throughout: a network
            // mismatch has no other symptom, because `scriptPubKey`s are network-agnostic
            // bytes. Validated against the mainnet fixture wallet like every other case.
            let testnet = wallet_on(Network::Testnet);
            let spk = our_spk(&testnet, Family::Bip84);
            psbt_for(&testnet, &[(Family::Bip84, 100_000)], &[(spk, 90_000)]).serialize()
        },
    },
    Case {
        name: "our fingerprint on an output whose scriptPubKey is the attacker's",
        code: "AOBS-R08",
        refusal: None,
        bytes: || {
            let wallet = wallet();
            // A real change path, a real key of ours declared at it, and an address that is
            // not what that path derives. This is the change-substitution class.
            let attacker =
                ScriptBuf::new_p2wpkh(&bitcoin::WPubkeyHash::from_byte_array([0x33; 20]));
            let mut psbt = psbt(&[(Family::Bip84, 100_000)], &[(attacker, 90_000)]);
            declare_output(
                &mut psbt.outputs[0],
                Family::Bip84,
                &our_key(&wallet, Family::Bip84, 1, 0),
                wallet.fingerprint(),
                our_path(&wallet, Family::Bip84, 1, 0),
            );
            psbt.serialize()
        },
    },
    Case {
        name: "change on an unscannable path",
        code: "AOBS-R09",
        refusal: None,
        bytes: || {
            let wallet = wallet();
            // Branch 2. The coins really are ours — the address below is derived from our own
            // account key at that path — and no wallet of ours will ever look there. This is
            // Coldcard's 2019 change-path ransom.
            let key = our_key(&wallet, Family::Bip84, 2, 0);
            let spk = ScriptBuf::new_p2wpkh(&key.to_pub().wpubkey_hash());
            let mut psbt = psbt(&[(Family::Bip84, 100_000)], &[(spk, 90_000)]);
            declare_output(
                &mut psbt.outputs[0],
                Family::Bip84,
                &key,
                wallet.fingerprint(),
                our_path(&wallet, Family::Bip84, 2, 0),
            );
            psbt.serialize()
        },
    },
];

/// A taproot input of ours whose internal key has **no `tap_key_origins` entry of its own**
/// ([#113](https://github.com/allisson/aobs/issues/113)) — half of BIP-371's declaration, which is
/// `AOBS-R05`.
///
/// The internal key is the fixture's real one; what changes is that the only origin entry is keyed
/// under a *different* key of ours, declaring the path that does byte-verify. So the case is about
/// the declaration and never about the compare. Shared with `crate::psbt::tests`, which asserts the
/// typed variant where the corpus asserts the code.
pub(crate) fn taproot_internal_key_orphaned() -> Psbt {
    let wallet = wallet();
    let spk = our_spk(&wallet, Family::Bip84);
    let mut psbt = psbt(&[(Family::Bip86, 100_000)], &[(spk, 90_000)]);
    psbt.inputs[0].tap_key_origins.clear();
    declare_input(
        &mut psbt.inputs[0],
        Family::Bip86,
        &our_key(&wallet, Family::Bip86, 0, 1),
        wallet.fingerprint(),
        our_path(&wallet, Family::Bip86, 0, 0),
    );
    psbt
}

/// A taproot input of ours whose **internal key's own entry points at a branch we never scan**,
/// while a second entry declares the path that really derives it — the shape #113 was opened for,
/// and `AOBS-R06`.
///
/// The `scriptPubKey` is ours and the old *walk both maps* rule called the input ours on the second
/// entry; the entry that decides whether a signature is produced is the first, so the document
/// would have come back carrying nothing.
pub(crate) fn taproot_key_path_diverted() -> Psbt {
    let wallet = wallet();
    let spk = our_spk(&wallet, Family::Bip84);
    let mut psbt = psbt(&[(Family::Bip86, 100_000)], &[(spk, 90_000)]);
    let internal = psbt.inputs[0]
        .tap_internal_key
        .expect("the fixture declares one");
    let unscannable = wallet
        .account_path(Family::Bip86)
        .extend([normal(2), normal(0)]);
    psbt.inputs[0]
        .tap_key_origins
        .insert(internal, (vec![], (wallet.fingerprint(), unscannable)));
    declare_input(
        &mut psbt.inputs[0],
        Family::Bip86,
        &our_key(&wallet, Family::Bip86, 0, 1),
        wallet.fingerprint(),
        our_path(&wallet, Family::Bip86, 0, 0),
    );
    psbt
}

/// A P2WPKH input of ours declaring `raw` as its sighash type.
fn sighash_case(raw: u32) -> Vec<u8> {
    let mut psbt = one_in_one_out();
    psbt.inputs[0].sighash_type = Some(PsbtSighashType::from_u32(raw));
    psbt.serialize()
}

/// One input spending `spk`, honestly: the previous transaction pays it and hashes correctly,
/// so the only thing wrong is the script type.
fn foreign_script_case(spk: ScriptBuf) -> Vec<u8> {
    let ours = our_spk(&wallet(), Family::Bip84);
    let mut psbt = psbt(&[(Family::Bip84, 100_000)], &[(ours, 90_000)]);
    let previous = psbt.inputs[0]
        .non_witness_utxo
        .as_mut()
        .expect("the fixture carries one");
    previous.output[0].script_pubkey = spk;
    let previous = previous.clone();
    psbt.inputs[0].witness_utxo = Some(previous.output[0].clone());
    psbt.unsigned_tx.input[0].previous_output = OutPoint {
        txid: previous.compute_txid(),
        vout: 0,
    };
    psbt.serialize()
}

// --- the QR boundary's fixtures ----------------------------------------------------------
//
// The cases that matter here are the ones no honest encoder emits — a `seqLen` of
// `0xFFFFFFFF`, a part whose `messageLen` disagrees with the stream it joined — so the part
// CBOR is written by hand. `ur::Encoder` cannot be asked for a part that lies.

/// A CBOR unsigned integer at its minimal width, which is what `minicbor`'s `.u32()` writes and
/// therefore what `ur.rs`'s own reader has to agree with.
fn uint(value: u64, out: &mut Vec<u8>) {
    match value {
        0..=0x17 => out.push(u8::try_from(value).expect("under 0x18")),
        0x18..=0xff => out.extend_from_slice(&[0x18, u8::try_from(value).expect("under 0x100")]),
        0x100..=0xffff => {
            out.push(0x19);
            out.extend_from_slice(&u16::try_from(value).expect("under 0x10000").to_be_bytes());
        }
        _ => {
            out.push(0x1a);
            out.extend_from_slice(&u32::try_from(value).expect("under 2^32").to_be_bytes());
        }
    }
}

/// A CBOR definite-length byte-string header.
fn bytes_header(len: usize, out: &mut Vec<u8>) {
    match len {
        0..=0x17 => out.push(0x40 | u8::try_from(len).expect("under 0x18")),
        0x18..=0xff => out.extend_from_slice(&[0x58, u8::try_from(len).expect("under 0x100")]),
        _ => {
            out.push(0x59);
            out.extend_from_slice(&u16::try_from(len).expect("under 0x10000").to_be_bytes());
        }
    }
}

/// One multi-part `ur:crypto-psbt`, with every field of `fountain::Part`'s CBOR array under the
/// caller's control — including the three a stream's identity is pinned on.
pub(crate) fn part(
    seq: usize,
    seq_len: usize,
    message_len: usize,
    checksum: u32,
    data: &[u8],
) -> String {
    let mut cbor = vec![0x85];
    uint(seq as u64, &mut cbor);
    uint(seq_len as u64, &mut cbor);
    uint(message_len as u64, &mut cbor);
    uint(u64::from(checksum), &mut cbor);
    bytes_header(data.len(), &mut cbor);
    cbor.extend_from_slice(data);

    format!(
        "ur:crypto-psbt/{seq}-{seq_len}/{}",
        ur::bytewords::encode(&cbor, ur::bytewords::Style::Minimal)
    )
}

/// A multi-part `ur:crypto-psbt` whose body is exactly these CBOR bytes — for the cases whose
/// subject is the part CBOR itself rather than the values in it.
pub(crate) fn raw_part(indices: &str, cbor: &[u8]) -> String {
    format!(
        "ur:crypto-psbt/{indices}/{}",
        ur::bytewords::encode(cbor, ur::bytewords::Style::Minimal)
    )
}

/// A real animation carrying `payload`, which is the only way to get parts whose checksum and
/// padding the fountain decoder will actually accept.
///
/// **Takes the payload, not the message.** §1's message is the payload in a CBOR byte string, so
/// a coordinator's animation is built the way [`crate::outbound`] builds ours — and every test
/// below that asserts what comes out asserts the payload it put in. Where the *message* length is
/// the subject, [`message_len`] is how a test names it.
pub(crate) fn stream(
    ur_type: &str,
    payload: &[u8],
    max_fragment_length: usize,
    count: usize,
) -> Vec<String> {
    let message = crate::ur::wrap(payload);
    let mut encoder = ur::Encoder::new(&message, max_fragment_length, ur_type).expect("a message");
    (0..count)
        .map(|_| encoder.next_part().expect("a part"))
        .collect()
}

/// The single-part form carrying `payload` — `03-transport.md` §6's *"an animation of length one
/// that happens not to move"*, which arrives with no `seq` component at all.
pub(crate) fn single(ur_type: &str, payload: &[u8]) -> String {
    ur::ur::encode(&crate::ur::wrap(payload), &ur::Type::Custom(ur_type))
}

/// A payload whose bytes are not all the same, so a fragment that lands in the wrong slot
/// cannot pass unnoticed.
pub(crate) fn transport_message(len: usize) -> Vec<u8> {
    (0..len)
        .map(|i| u8::try_from(i % 251).expect("under 251"))
        .collect()
}

/// A payload whose **message** is exactly `len` bytes once §1's wrapper is on it.
///
/// `03-transport.md` §3's bounds and §9's arithmetic are both stated over the message, and so is
/// every fragment count a transport test asserts — so this, and not [`transport_message`], is
/// what a case names when the number it cares about is a `messageLen` or a `seqLen`. The wrapper
/// is 1, 2, 3 or 5 bytes depending on the width, so the payload is solved for rather than
/// subtracted.
///
/// # Panics
///
/// If `len` is too small to hold a wrapper and at least one byte.
pub(crate) fn transport_payload(len: usize) -> Vec<u8> {
    let payload = (1..len)
        .map(|candidate| len - candidate)
        .find(|&candidate| crate::ur::wrap(&vec![0u8; candidate]).len() == len)
        .expect("every length above 1 is one byte of header plus a payload");
    transport_message(payload)
}

/// The checksum a real animation put in its parts, so a hand-built part can disagree with a
/// stream on exactly one field.
pub(crate) fn checksum_of(symbol: &str) -> u32 {
    let (_, body) = symbol
        .strip_prefix("ur:")
        .and_then(|rest| rest.split_once('/'))
        .expect("a UR");
    let (_, payload) = body.rsplit_once('/').expect("a multi-part UR");
    let cbor = ur::bytewords::decode(payload, ur::bytewords::Style::Minimal).expect("bytewords");

    // `[0x85, seq, seqLen, messageLen, checksum, data]`, every integer minimal.
    let mut at = 1usize;
    for _ in 0..3 {
        at += 1 + uint_width(cbor[at]);
    }
    let head = cbor[at];
    at += 1;
    match head {
        0..=0x17 => u32::from(head),
        0x18 => u32::from(cbor[at]),
        0x19 => u32::from(u16::from_be_bytes([cbor[at], cbor[at + 1]])),
        _ => u32::from_be_bytes([cbor[at], cbor[at + 1], cbor[at + 2], cbor[at + 3]]),
    }
}

fn uint_width(head: u8) -> usize {
    match head {
        0..=0x17 => 0,
        0x18 => 1,
        0x19 => 2,
        0x1a => 4,
        _ => 8,
    }
}

// --- the QR boundary's cases -------------------------------------------------------------

/// How a transport case must end.
///
/// Unlike the PSBT cases, not every one of `05-testing-and-release.md` §5's transport cases is a
/// refusal: the bounds in `03-transport.md` §3 that carry no code drop the symbol and leave the
/// screen live (`06-codes.md` §4), and the 64 KiB boundary's *exactly at the limit* half is an
/// **acceptance**. A table that could only express refusals would have to leave those out.
pub(crate) enum Expect {
    /// The stream completes and the payload arrives.
    Accepted,
    /// The symbol is dropped with no code and the scan stays live.
    Discarded,
    /// A refusal carrying this `AOBS-R##`.
    Refused(&'static str),
}

/// One named transport case: the class the screen asked for, the symbols in the order they are
/// scanned, and how the last one must end.
pub(crate) struct TransportCase {
    /// What the case is, in the words §5 uses for it.
    pub name: &'static str,
    /// The class the screen asked for — which for the wrong-class cases is the whole subject.
    pub expected: Class,
    /// The symbols, scanned in order into one [`Scanner`].
    pub symbols: fn() -> Vec<String>,
    /// How the last symbol must end.
    pub last: Expect,
}

/// The transport corpus, from `05-testing-and-release.md` §5's own list.
pub(crate) const TRANSPORT_CASES: &[TransportCase] = &[
    TransportCase {
        name: "a frame declaring seqLen = 0xFFFFFFFF",
        expected: Class::Psbt,
        // The body need not even be bytewords: the claim is refused on the decimal in the URI
        // path, which is what *before any part reaches `ur`* means for this bound.
        symbols: || vec!["ur:crypto-psbt/1-4294967295/aeaeaeae".to_owned()],
        last: Expect::Discarded,
    },
    TransportCase {
        name: "a part with an inconsistent seqLen",
        expected: Class::Psbt,
        symbols: inconsistent_sequence_count,
        last: Expect::Discarded,
    },
    TransportCase {
        name: "a part with an inconsistent messageLen",
        expected: Class::Psbt,
        symbols: inconsistent_message_length,
        last: Expect::Discarded,
    },
    TransportCase {
        name: "a part disagreeing with an established stream's identity",
        expected: Class::Psbt,
        symbols: foreign_checksum,
        last: Expect::Discarded,
    },
    TransportCase {
        name: "a stream feeding valid parts past the 1,024-part budget without completing",
        expected: Class::Psbt,
        symbols: budget_exhausted,
        last: Expect::Refused("AOBS-R11"),
    },
    TransportCase {
        name: "the 64 KiB boundary, exactly at the limit",
        expected: Class::Psbt,
        symbols: || stream("crypto-psbt", &transport_payload(64 * 1024), 2_048, 32),
        last: Expect::Accepted,
    },
    TransportCase {
        name: "the 64 KiB boundary, one byte over",
        expected: Class::Psbt,
        // Same fragment length as the row above, so `messageLen` is the only field that
        // differs — at a smaller fragment the `seqLen` bound would trip first and the case
        // would be asserting the wrong thing.
        symbols: || stream("crypto-psbt", &transport_payload(64 * 1024 + 1), 2_048, 33),
        last: Expect::Discarded,
    },
    TransportCase {
        name: "a crypto-psbt whose message is a bare PSBT rather than the registry's byte string",
        expected: Class::Psbt,
        // The convention this crate emitted and accepted before
        // [#112](https://github.com/allisson/aobs/issues/112). It is in the corpus because it is
        // the shape a regression would take: nothing else here would notice the wrapper coming
        // back off, since every other case builds its stream with `single`/`stream`.
        symbols: || {
            vec![ur::ur::encode(
                b"psbt\xff\x01\x00\x00",
                &ur::Type::Custom("crypto-psbt"),
            )]
        },
        last: Expect::Discarded,
    },
    TransportCase {
        name: "a wrong-class payload at the signing prompt",
        expected: Class::Psbt,
        symbols: || vec!["bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4".to_owned()],
        last: Expect::Refused("AOBS-R10"),
    },
    TransportCase {
        name: "a wrong-class payload at the address prompt",
        expected: Class::Address,
        symbols: || vec![single("crypto-psbt", b"a transaction")],
        last: Expect::Refused("AOBS-R10"),
    },
    TransportCase {
        name: "a wrong-class payload at the restore prompt",
        expected: Class::Backup,
        symbols: || vec![single("crypto-psbt", b"a transaction")],
        last: Expect::Refused("AOBS-R10"),
    },
];

/// A real first part, then a hand-built second one differing only in `seqLen`.
fn inconsistent_sequence_count() -> Vec<String> {
    let parts = stream("crypto-psbt", &transport_payload(4_000), 1_000, 1);
    let checksum = checksum_of(&parts[0]);
    vec![parts[0].clone(), part(2, 8, 4_000, checksum, &[0u8; 1_000])]
}

/// The same, differing only in `messageLen`.
fn inconsistent_message_length() -> Vec<String> {
    let parts = stream("crypto-psbt", &transport_payload(4_000), 1_000, 1);
    let checksum = checksum_of(&parts[0]);
    vec![parts[0].clone(), part(2, 4, 4_001, checksum, &[0u8; 1_000])]
}

/// The same, differing only in the message checksum — the field a stream's identity rests on
/// that neither decimal in the URI path can carry.
fn foreign_checksum() -> Vec<String> {
    let parts = stream("crypto-psbt", &transport_payload(4_000), 1_000, 1);
    let checksum = checksum_of(&parts[0]).wrapping_add(1);
    vec![parts[0].clone(), part(2, 4, 4_000, checksum, &[0u8; 1_000])]
}

/// Sequence 1 of a four-part stream, over and over: well-formed, consistent with the stream's
/// identity, and never completing it. This is the shape fountain coding makes free.
fn budget_exhausted() -> Vec<String> {
    let parts = stream("crypto-psbt", &transport_payload(4_000), 1_000, 1);
    vec![parts[0].clone(); PART_BUDGET + 1]
}

// --- the receive-verification cases ------------------------------------------------------

/// How an address case must end. **Two outcomes and no code**: a receive verification either
/// finds the address in our own key material or does not, and the negative is not a refusal
/// (`02-core.md` §10, `06-codes.md` §4 — nothing was refused and nothing was discarded).
pub(crate) enum Answer {
    /// Found, at exactly this place — asserted rather than merely *some* place, because a case
    /// that matched the wrong index would still be a pass otherwise.
    Found(Family, Branch, u32),
    /// Not in what was searched. `04-screens.md` §12 is where that becomes a headline with the
    /// weight of a refusal and a subordinate line naming the window.
    NotFound,
}

/// One named address case: the candidate as it would arrive off the camera, and the answer.
pub(crate) struct AddressCase {
    /// What the case is, in the words §5 uses for it.
    pub name: &'static str,
    /// The candidate, built from the fixture wallet — so a case names *our* address and then
    /// damages it, which is the only way the damage is the subject.
    pub candidate: fn(&Wallet) -> String,
    pub answer: Answer,
}

/// The wallet a substituted address comes from: a different seed, same network, real addresses.
fn another_wallet() -> Wallet {
    let mnemonic = Mnemonic::from_entropy(&Entropy::new(&[7u8; 16]).expect("16 bytes fit"))
        .expect("16 bytes is an accepted length");
    Wallet::load(
        &mnemonic,
        &Passphrase::new("").expect("empty fits"),
        Network::Mainnet,
    )
}

fn ours_at(wallet: &Wallet, family: Family, branch: Branch, index: u32) -> String {
    wallet
        .address(family, branch, index)
        .expect("a normal index derives")
        .to_string()
}

/// `05-testing-and-release.md` §5's address-shaped entries, verbatim from its own list.
pub(crate) const ADDRESS_CASES: &[AddressCase] = &[
    AddressCase {
        name: "mixed-case bech32",
        // BIP-173 forbids mixed case in a *valid* bech32 string, and this case records that we
        // do not care: step 3 is `eq_ignore_ascii_case` for a bech32 address of ours, and the
        // candidate's form is never consulted. So a mixed-case rendering of our own address
        // **matches**, and no substitution is bought by it — case is the only thing the compare
        // is blind to, so no *different* address can be made to match this way.
        candidate: |wallet| {
            let ours = ours_at(wallet, Family::Bip84, Branch::Receive, 4);
            ours.char_indices()
                .map(|(at, character)| {
                    if at % 2 == 0 {
                        character.to_ascii_uppercase()
                    } else {
                        character
                    }
                })
                .collect()
        },
        answer: Answer::Found(Family::Bip84, Branch::Receive, 4),
    },
    AddressCase {
        name: "truncated bech32",
        // A prefix of ours is not ours, and there is no partial credit: the compare is total.
        candidate: |wallet| {
            let ours = ours_at(wallet, Family::Bip84, Branch::Receive, 0);
            ours[..ours.len() - 6].to_owned()
        },
        answer: Answer::NotFound,
    },
    AddressCase {
        name: "a valid address differing by one character",
        // The attack, one character wide — and the one the 4-character grouping on the verdict
        // screen exists to make readable.
        candidate: |wallet| {
            let mut ours = ours_at(wallet, Family::Bip86, Branch::Receive, 0);
            let last = ours.pop().expect("an address has characters");
            ours.push(if last == 'q' { 'p' } else { 'q' });
            ours
        },
        answer: Answer::NotFound,
    },
    AddressCase {
        name: "a valid address differing only in case",
        // **The base58 half of step 3, and the direction that would report *yours*.** Base58 is
        // case-sensitive, so this is a different string and must not match — which is why the
        // looseness is selected by the family we derived and never by the candidate.
        candidate: |wallet| ours_at(wallet, Family::Bip44, Branch::Receive, 0).to_uppercase(),
        answer: Answer::NotFound,
    },
    AddressCase {
        name: "`bitcoin:` with a query string",
        candidate: |wallet| {
            format!(
                "bitcoin:{}?amount=0.0123&label=Coffee",
                ours_at(wallet, Family::Bip49, Branch::Receive, 1)
            )
        },
        answer: Answer::Found(Family::Bip49, Branch::Receive, 1),
    },
    AddressCase {
        name: "an uppercase BIP-21 URI",
        // Scheme and address both shouted, which is what a bech32 QR carrying a URI looks like:
        // BIP-21 makes the scheme case-insensitive and BIP-173 SHOULD use uppercase for
        // alphanumeric mode, so both halves of step 1 and step 3 fire on one symbol.
        candidate: |wallet| {
            format!(
                "bitcoin:{}",
                ours_at(wallet, Family::Bip84, Branch::Change, 2)
            )
            .to_uppercase()
        },
        answer: Answer::Found(Family::Bip84, Branch::Change, 2),
    },
    AddressCase {
        name: "a correctly-formed address from the wrong account",
        // Not damaged in any way — a real BIP84 receive address, of a different seed. This is
        // what a substitution actually looks like on the wire, and the only thing that catches
        // it is that we derived our own.
        candidate: |_| ours_at(&another_wallet(), Family::Bip84, Branch::Receive, 0),
        answer: Answer::NotFound,
    },
];

// --- the registry ------------------------------------------------------------------------

/// `06-codes.md` §6's refusal space, read from the file itself rather than copied into a
/// constant here. A copy is a second place to forget.
const REGISTRY: &str = include_str!("../../docs/specs/06-codes.md");

/// Codes the registry defines but nothing implements yet, each with the ticket that owes it.
///
/// This list only ever shrinks. Everything in it is a refusal whose *mechanism* does not exist
/// — the derivation check, the QR boundary, the backup — rather than a case somebody forgot to
/// write.
const PENDING: &[(&str, &str)] = &[
    ("AOBS-R12", "#85 — an unknown backup version byte"),
    ("AOBS-R13", "#85 — a malformed backup header"),
    ("AOBS-R14", "#85 — the Poly1305 tag"),
];

/// Every `AOBS-R##` the registry's tables define, in the order they appear there.
///
/// A table row and nothing else: §6's prose mentions codes too, and a mention is not a
/// definition. §2's table row for the space itself reads `AOBS-R##`, so a code is only a code
/// when its two trailing characters are digits.
fn registry_codes() -> Vec<&'static str> {
    REGISTRY
        .lines()
        .filter(|line| line.starts_with("| `AOBS-R"))
        .map(|line| {
            let start = line.find('`').expect("the prefix carries one") + 1;
            let end = start
                + line[start..]
                    .find('`')
                    .expect("a table cell closes its backtick");
            &line[start..end]
        })
        .filter(|code| code.len() == 8 && code[6..].chars().all(|c| c.is_ascii_digit()))
        .collect()
}

fn sorted_unique(codes: impl IntoIterator<Item = &'static str>) -> Vec<&'static str> {
    let mut codes: Vec<&str> = codes.into_iter().collect();
    codes.sort_unstable();
    codes.dedup();
    codes
}

/// Every code a refusal in this crate can carry, from both spaces that produce one: the
/// rejection policy's and the QR boundary's.
fn implemented_codes() -> Vec<&'static str> {
    sorted_unique(
        Refusal::ALL
            .iter()
            .map(|refusal| refusal.code())
            .chain(crate::ur::Refusal::ALL.iter().map(|refusal| refusal.code())),
    )
}

fn corpus_codes() -> Vec<&'static str> {
    sorted_unique(
        CASES
            .iter()
            .map(|case| case.code)
            .chain(TRANSPORT_CASES.iter().filter_map(|case| match case.last {
                Expect::Refused(code) => Some(code),
                // The bounds that drop rather than refuse are cases with no code to contribute
                // (`06-codes.md` §4), and so is the acceptance half of the 64 KiB boundary.
                Expect::Accepted | Expect::Discarded => None,
            })),
    )
}

// --- the tests ---------------------------------------------------------------------------

#[test]
fn every_case_refuses_with_its_code() {
    // Every case runs against the same mainnet fixture wallet, including the one whose subject
    // is that the PSBT was built for the other network.
    let wallet = wallet();
    for case in CASES {
        match validate(&wallet, &(case.bytes)()) {
            Err(Rejection::Refused(refusal)) => {
                assert_eq!(refusal.code(), case.code, "{}: {refusal:?}", case.name);
                if let Some(expected) = case.refusal {
                    assert_eq!(refusal, expected, "{}", case.name);
                }
            }
            other => panic!("{} was not refused: {other:?}", case.name),
        }
    }
}

#[test]
fn every_transport_case_ends_as_it_says() {
    // One scanner per case, fed the case's symbols in order — which is the point of several of
    // them: a part disagreeing with an established stream is only a case if a stream was
    // established first.
    for case in TRANSPORT_CASES {
        let mut scanner = Scanner::new(case.expected);
        let symbols = (case.symbols)();
        assert!(!symbols.is_empty(), "{}: no symbols", case.name);

        let outcome = symbols
            .iter()
            .map(|symbol| scanner.receive(symbol))
            .last()
            .expect("a symbol");

        match (&case.last, &outcome) {
            (Expect::Accepted, Outcome::Complete(_))
            | (Expect::Discarded, Outcome::Discarded(_)) => {}
            (Expect::Refused(code), Outcome::Refused(refusal)) => {
                assert_eq!(refusal.code(), *code, "{}: {refusal:?}", case.name);
            }
            _ => panic!("{} ended as {outcome:?}", case.name),
        }
    }
}

#[test]
fn every_address_case_answers_as_it_says() {
    // One wallet for the whole table: a search is 8,000 derivations and the fixture is the same
    // one every other table here is written against.
    let wallet = wallet();

    for case in ADDRESS_CASES {
        let candidate = (case.candidate)(&wallet);
        assert!(!candidate.is_empty(), "{}: no candidate", case.name);

        match (&case.answer, wallet.find_address(&candidate)) {
            (Answer::Found(family, branch, index), Some(found)) => {
                assert_eq!(
                    (found.family, found.branch, found.index),
                    (*family, *branch, *index),
                    "{}",
                    case.name
                );
                // What the screen shows is our own material, never the candidate — which for
                // the two shouted cases is the whole difference between the two strings.
                assert_eq!(
                    found.address.to_string(),
                    ours_at(&wallet, *family, *branch, *index),
                    "{}",
                    case.name
                );
            }
            (Answer::NotFound, None) => {}
            (Answer::Found(..), None) => panic!("{} was not found", case.name),
            (Answer::NotFound, Some(found)) => {
                panic!("{} was found at {}", case.name, found.path)
            }
        }
    }
}

#[test]
fn case_names_are_distinct() {
    let names = sorted_unique(
        CASES
            .iter()
            .map(|case| case.name)
            .chain(TRANSPORT_CASES.iter().map(|case| case.name))
            .chain(ADDRESS_CASES.iter().map(|case| case.name)),
    );
    assert_eq!(
        names.len(),
        CASES.len() + TRANSPORT_CASES.len() + ADDRESS_CASES.len(),
        "two cases share a name"
    );
}

/// §5's own list of address-shaped entries is seven, and the table is those seven. A case
/// quietly dropped would leave the suite green — which is what this asserts against, the same
/// way [`the_registry_parses_to_the_codes_it_states`] does for the codes.
#[test]
fn the_address_table_is_the_seven_entries_section_five_names() {
    assert_eq!(
        ADDRESS_CASES
            .iter()
            .map(|case| case.name)
            .collect::<Vec<_>>(),
        [
            "mixed-case bech32",
            "truncated bech32",
            "a valid address differing by one character",
            "a valid address differing only in case",
            "`bitcoin:` with a query string",
            "an uppercase BIP-21 URI",
            "a correctly-formed address from the wrong account",
        ]
    );
}

#[test]
fn the_corpus_covers_every_implemented_refusal() {
    // The bijection, in the direction that can hold today: every code a `Refusal` can carry
    // has a case, and no case names a code nothing produces.
    assert_eq!(corpus_codes(), implemented_codes());
}

#[test]
fn every_implemented_code_is_in_the_registry() {
    let registry = sorted_unique(registry_codes());
    for code in implemented_codes() {
        assert!(
            registry.contains(&code),
            "{code} is produced in code and is not in 06-codes.md §6"
        );
    }
}

#[test]
fn the_registry_is_implemented_or_pending() {
    let pending: Vec<&str> = sorted_unique(PENDING.iter().map(|(code, _)| *code));
    assert_eq!(
        pending.len(),
        PENDING.len(),
        "a code is listed as pending twice"
    );

    let implemented = implemented_codes();
    for code in &pending {
        assert!(
            !implemented.contains(code),
            "{code} is implemented and still listed as pending"
        );
    }

    let mut both: Vec<&str> = implemented.iter().chain(pending.iter()).copied().collect();
    both.sort_unstable();
    assert_eq!(
        both,
        sorted_unique(registry_codes()),
        "the registry, the implementation and the pending list disagree"
    );
}

#[test]
fn the_registry_parses_to_the_codes_it_states() {
    // The parser above reads a markdown table, so it gets its own assertion: a change to the
    // file's shape must not quietly reduce the registry to nothing.
    assert_eq!(
        registry_codes(),
        [
            "AOBS-R01", "AOBS-R02", "AOBS-R03", "AOBS-R04", "AOBS-R05", "AOBS-R06", "AOBS-R07",
            "AOBS-R15", "AOBS-R16", "AOBS-R17", "AOBS-R08", "AOBS-R09", "AOBS-R10", "AOBS-R11",
            "AOBS-R12", "AOBS-R13", "AOBS-R14",
        ]
    );
}
