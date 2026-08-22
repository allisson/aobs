//! `05-testing-and-release.md` §4's third target: **the validator, structure-aware and seeded
//! with our own key material.**
//!
//! Where `psbt_parse` fuzzes raw bytes and spends most of its budget being told *these are not a
//! PSBT*, this one generates PSBTs — a plan of inputs and outputs, turned into a well-formed
//! document that gets past the parser every time, so the mutator's budget goes on the checks
//! rather than on the magic bytes. That is what *structure-aware* buys.
//!
//! **The invariants it asserts are §4's own, and they are the two that matter:**
//!
//! > it never accepts a transaction containing an output classified as ours whose
//! > `scriptPubKey` we did not ourselves produce, and every input it accepts as ours is one
//! > `sign` produces a signature for.
//!
//! Both are checked **independently of the code under test**. `psbt.rs` reaches its verdicts
//! through `Wallet::verify`, which reads the path, decides whether it is scannable and
//! byte-compares; this target re-reads the path with its own arithmetic, derives through
//! `Wallet::address` — the primitive the BIP vectors pin — and compares again. Calling `verify`
//! here would assert that `verify` agrees with itself.
//!
//! The plan can express both attacks directly. For the first: a claim carrying our fingerprint at
//! a legitimate change path, over an address we never derived — if `AOBS-R08` ever stops firing on
//! it, an accepted `Review` arrives here with a `Change` row this target cannot reproduce. For the
//! second ([#113](https://github.com/allisson/aobs/issues/113)): a taproot input whose key-path
//! claim the signing path would never reach, which is [`KeyPath`]'s axis — if §7's rule 6 ever
//! widens back to *walk both maps*, such an input is accepted as ours and comes back unsigned.
//!
//! **A third invariant rides on the same plan** ([#115](https://github.com/allisson/aobs/issues/115)):
//! an input arriving with a signature already in it is never accepted, which is [`Arriving`]'s axis.
//! It is what makes the second invariant a claim about this call's *delta* rather than about the
//! document going out — `Psbt::sign` declines a taproot key path whose `tap_key_sig` is already
//! set, so without the refusal a signature that merely arrived would have satisfied it.
//!
//! **The second invariant is why this target signs**, which costs one signature per input of every
//! accepted plan. It is the only way the assertion reaches a mutator: the set of inputs `sign`
//! checks is `crate::psbt`'s own, so a target that did not re-derive independently would be
//! watching two functions agree.

#![no_main]

use std::sync::OnceLock;

use arbitrary::Arbitrary;
use libfuzzer_sys::fuzz_target;

use bitcoin::absolute::LockTime;
use bitcoin::bip32::{ChildNumber, DerivationPath, Fingerprint};
use bitcoin::hashes::Hash as _;
use bitcoin::psbt::{Input, Psbt};
use bitcoin::secp256k1::{schnorr, PublicKey, Secp256k1, XOnlyPublicKey};
use bitcoin::sighash::{EcdsaSighashType, TapSighashType};
use bitcoin::taproot::TapLeafHash;
use bitcoin::transaction::Version;
use bitcoin::{
    ecdsa, taproot, Amount, OutPoint, ScriptBuf, Sequence, Transaction, TxIn, TxOut, WPubkeyHash,
    Witness,
};

use aobs_core::bip39::Mnemonic;
use aobs_core::derive::{Branch, Family, Network, Wallet};
use aobs_core::psbt::{validate, Accepted, OutputKind};
use aobs_core::sign::sign;
use aobs_core::secret::{Entropy, Passphrase};

/// Our own key material, derived once. `Wallet::load` is PBKDF2 over 2 048 HMAC rounds plus four
/// hardened derivations, which would otherwise dominate every iteration.
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

/// Two valid public keys nobody controls — secp256k1's generator point and its double.
///
/// The `bip32_derivation` map is **keyed** by a public key and our code reads only the values, so
/// a constant is not a shortcut there: a target that had to derive the right key per entry would
/// be asserting that we ignore the key, which we can state instead.
///
/// **`tap_key_origins` is the exception, and it is why there is a second x-only key**
/// ([#113](https://github.com/allisson/aobs/issues/113)). For a taproot input the entry *keyed by
/// `tap_internal_key`* is the key-path declaration, so which key an entry is under is a fact the
/// policy reads — and a second key is what lets [`KeyPath`] put the honest origin somewhere the
/// internal key does not name.
fn placeholder_keys() -> &'static (PublicKey, XOnlyPublicKey, XOnlyPublicKey) {
    static KEYS: OnceLock<(PublicKey, XOnlyPublicKey, XOnlyPublicKey)> = OnceLock::new();
    KEYS.get_or_init(|| {
        let key: PublicKey = "0279be667ef9dcbbac55a06295ce870b07029bfcdb2dce28d959f2815b16f81798"
            .parse()
            .expect("a valid compressed key");
        let other: PublicKey = "02c6047f9441ed7d6d3045406e95c07cd85c778e4b8cef3ca7abac09b95c709ee5"
            .parse()
            .expect("a valid compressed key");
        (key, XOnlyPublicKey::from(key), XOnlyPublicKey::from(other))
    })
}

/// What to build. Every field the fuzzer can move is a decision the rejection policy has an
/// answer for.
#[derive(Arbitrary, Debug)]
struct Plan {
    inputs: Vec<InputPlan>,
    outputs: Vec<OutputPlan>,
    /// Drop the previous transaction on the first input, which is `AOBS-R02` unless taproot.
    starve_first_input: bool,
}

#[derive(Arbitrary, Debug)]
struct InputPlan {
    family: Slot,
    /// Capped at `u32::MAX` satoshis so the fuzzer spends its budget on the checks rather than
    /// on `AOBS-R16`, which `psbt_tests.rs` pins at its boundary anyway.
    value: u32,
    claim: InputClaim,
    /// How a taproot input declares its key path. Ignored by the other three families.
    key_path: KeyPath,
    /// Whether the input turns up with a signature already in it.
    arriving: Arriving,
}

/// Whether the input arrives already carrying a signature
/// ([#115](https://github.com/allisson/aobs/issues/115)).
///
/// **Two variants rather than six, for [`KeyPath`]'s own reason.** Every signed form is refused, so
/// a flat six-way enum would refuse five plans in six and starve the checks this target exists for.
/// Nesting them puts [`Arriving::Unsigned`] back at half.
///
/// **What this axis reaches is the invariant `AOBS-R17` was spent on.** Before it, a taproot input
/// arriving with `tap_key_sig` set was accepted and then silently declined by the dependency's key
/// path, so the document went back out unchanged under a screen reading *Signed*. A plan that
/// declares one must not be accepted at all — [`assert_no_accepted_input_arrived_signed`] — and if
/// one ever is, `sign`'s delta assertion is the second finding on the same bytes.
#[derive(Arbitrary, Debug)]
enum Arriving {
    /// All five fields empty, which is the only form the policy accepts.
    Unsigned,
    /// One of them filled with bytes that are not a signature this wallet would produce.
    Signed(ArrivingSignature),
}

/// The five fields an input can arrive signed in — the three signature maps, and the two a
/// Finalizer writes while removing `partial_sigs`.
#[derive(Arbitrary, Debug)]
enum ArrivingSignature {
    PartialSig,
    TapKeySig,
    TapScriptSig,
    FinalScriptSig,
    FinalScriptWitness,
}

/// What an input says about itself.
///
/// [`InputClaim::Honest`] exists because everything this target asserts sits behind
/// `AOBS-R06`: an input is ours only when a claimed path resolves to the address the funding
/// transaction actually paid, which is `(its own family, branch 0, index 0)` unhardened and
/// full-length. Left to a [`Claim`]'s five independent fields that is a coincidence the mutator
/// has to find, and until it does, the accepting arm of the policy is never entered. One variant
/// makes it a third of all plans.
#[derive(Arbitrary, Debug)]
enum InputClaim {
    /// The origin the funding transaction's address really has.
    Honest,
    /// No origin declared at all, which is `AOBS-R06` and the coin-type variant silent.
    Absent,
    /// Whatever the fuzzer says.
    Declared(Claim),
}

/// How a taproot input declares its key-path spend
/// ([#113](https://github.com/allisson/aobs/issues/113)).
///
/// BIP-371 puts the declaration in two places at once — `PSBT_IN_TAP_INTERNAL_KEY`, and the
/// `tap_key_origins` entry keyed by that key with no leaf hashes — and the dependency's signing
/// path reads the second. So a declaration can be broken in ways [`InputClaim`] cannot express,
/// and every one of them is a shape that used to be accepted and then come back with no signature
/// in it.
///
/// **Two variants rather than five, for [`InputClaim`]'s own reason.** Every broken form refuses
/// the taproot input, so a flat five-way enum would refuse four taproot plans in five and starve
/// the output checks this target exists for. Nesting them puts [`KeyPath::Declared`] back at half.
///
/// **What these variants reach is the second invariant**, and the module header says how: a plan
/// whose taproot declaration is broken must not be accepted as ours, and if one is, it comes back
/// unsigned and [`assert_every_input_of_ours_came_back_signed`] is the finding. Which *code* each
/// broken form earns is the corpus's assertion rather than this target's — a fuzz target names no
/// `AOBS-R##`.
#[derive(Arbitrary, Debug)]
enum KeyPath {
    /// The internal key names its own origin entry: what `AOBS-R05` asks for, and the only form
    /// that can be ours.
    Declared,
    /// One of the ways the declaration can be incomplete.
    Broken(BrokenKeyPath),
}

/// The four incomplete taproot declarations, all of which the policy must refuse.
#[derive(Arbitrary, Debug)]
enum BrokenKeyPath {
    /// No internal key at all, which is `AOBS-R05` — the field #82 made mandatory.
    Absent,
    /// An internal key no entry names, which is `AOBS-R05` for the same reason.
    Orphaned,
    /// The entry naming it carries a leaf hash, so it is a script-path key and the key path is
    /// undeclared — also `AOBS-R05`.
    LeafHashed,
    /// The internal key's entry declares a path of the fuzzer's choosing while the honest origin
    /// moves to an entry the internal key does not name. **The shape #113 was opened for**: the
    /// `scriptPubKey` can be ours and the signing path still reach nothing, so the input must not
    /// be ours either — `AOBS-R06` when it is the only input.
    Diverted(Claim),
}

#[derive(Arbitrary, Debug)]
struct OutputPlan {
    value: u32,
    /// Where the money actually goes — which is the only thing that decides whose it is.
    script: Destination,
    /// What the transaction *says* about it.
    claim: Option<Claim>,
}

/// Whose address an output pays.
#[derive(Arbitrary, Debug)]
enum Destination {
    /// One of ours, at a path of the fuzzer's choosing.
    Ours {
        family: Slot,
        branch: u8,
        index: u32,
    },
    /// A P2WPKH nobody in this process can derive.
    Foreign([u8; 20]),
}

/// A BIP32 origin, as declared rather than as true.
#[derive(Arbitrary, Debug)]
struct Claim {
    /// Whether the declared fingerprint is ours. A foreign one makes an output a payment.
    ours: bool,
    family: Slot,
    branch: u32,
    index: u32,
    hardened_branch: bool,
    hardened_index: bool,
    /// Truncate the path, so a claim can be the wrong length as well as the wrong place.
    short: bool,
}

/// One of the four families, without the fuzzer having to guess a discriminant.
#[derive(Arbitrary, Debug, Clone, Copy)]
enum Slot {
    Bip44,
    Bip49,
    Bip84,
    Bip86,
}

impl Slot {
    fn family(self) -> Family {
        match self {
            Self::Bip44 => Family::Bip44,
            Self::Bip49 => Family::Bip49,
            Self::Bip84 => Family::Bip84,
            Self::Bip86 => Family::Bip86,
        }
    }
}

fn child(index: u32, hardened: bool) -> ChildNumber {
    // `Hardened { index }` is the dependency's own sub-2^31 half, so the mask is what lets the
    // fuzzer reach a hardened child at all rather than a construction error.
    let index = index & 0x7fff_ffff;
    if hardened {
        ChildNumber::Hardened { index }
    } else {
        ChildNumber::Normal { index }
    }
}

impl Claim {
    fn path(&self, wallet: &Wallet) -> DerivationPath {
        let account = wallet.account_path(self.family.family());
        if self.short {
            return account;
        }
        account.extend([
            child(self.branch, self.hardened_branch),
            child(self.index, self.hardened_index),
        ])
    }

    fn fingerprint(&self, wallet: &Wallet) -> Fingerprint {
        if self.ours {
            wallet.fingerprint()
        } else {
            Fingerprint::from([0xde, 0xad, 0xbe, 0xef])
        }
    }
}

impl Destination {
    fn script_pubkey(&self, wallet: &Wallet) -> ScriptBuf {
        match self {
            Self::Ours {
                family,
                branch,
                index,
            } => {
                let branch = if branch % 2 == 0 {
                    Branch::Receive
                } else {
                    Branch::Change
                };
                wallet
                    .address(family.family(), branch, index & 0x7fff_ffff)
                    .expect("a masked index is a normal child")
                    .script_pubkey()
            }
            Self::Foreign(hash) => ScriptBuf::new_p2wpkh(&WPubkeyHash::from_byte_array(*hash)),
        }
    }
}

/// The transaction an input spends from: one output, paying our own address in that family.
fn funding(wallet: &Wallet, family: Family, value: Amount, nonce: u32) -> Transaction {
    Transaction {
        version: Version::TWO,
        lock_time: LockTime::from_height(nonce).expect("small heights are valid"),
        input: vec![TxIn {
            previous_output: OutPoint::null(),
            script_sig: ScriptBuf::new(),
            sequence: Sequence::MAX,
            witness: Witness::new(),
        }],
        output: vec![TxOut {
            value,
            script_pubkey: wallet
                .address(family, Branch::Receive, 0)
                .expect("index 0 is a normal child")
                .script_pubkey(),
        }],
    }
}

/// Turn a plan into serialised PSBT bytes, or `None` when it describes nothing buildable.
fn build(wallet: &Wallet, plan: &Plan) -> Option<Vec<u8>> {
    // Bounds on the plan itself, not on the policy: 8 inputs and 8 outputs reach past the
    // six-output refusal while keeping each iteration cheap.
    if plan.inputs.is_empty() || plan.inputs.len() > 8 || plan.outputs.len() > 8 {
        return None;
    }

    let previous: Vec<Transaction> = plan
        .inputs
        .iter()
        .enumerate()
        .map(|(nonce, input)| {
            funding(
                wallet,
                input.family.family(),
                Amount::from_sat(u64::from(input.value)),
                u32::try_from(nonce).expect("at most eight"),
            )
        })
        .collect();

    let unsigned = Transaction {
        version: Version::TWO,
        lock_time: LockTime::ZERO,
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
        output: plan
            .outputs
            .iter()
            .map(|out| TxOut {
                value: Amount::from_sat(u64::from(out.value)),
                script_pubkey: out.script.script_pubkey(wallet),
            })
            .collect(),
    };

    let mut psbt = Psbt::from_unsigned_tx(unsigned).ok()?;
    let (key, x_only, other) = placeholder_keys();

    for (index, (slot, plan)) in psbt.inputs.iter_mut().zip(&plan.inputs).enumerate() {
        let previous = &previous[index];
        slot.witness_utxo = Some(previous.output[0].clone());
        slot.non_witness_utxo = Some(previous.clone());
        if plan.family.family() == Family::Bip49 {
            // BIP49 is indistinguishable from any other P2SH without it, so an honest plan
            // hands it over and `AOBS-R05` is what refuses the plans that do not.
            slot.redeem_script = Some(redeem_script().clone());
        }
        let declared = match &plan.claim {
            InputClaim::Honest => Some((
                wallet.fingerprint(),
                honest_path(wallet, plan.family.family()),
            )),
            InputClaim::Absent => None,
            InputClaim::Declared(claim) => Some((claim.fingerprint(wallet), claim.path(wallet))),
        };
        if let Some(source) = declared {
            slot.bip32_derivation.insert(*key, source.clone());
            slot.tap_key_origins.insert(*x_only, (vec![], source));
        }
        if plan.family.family() == Family::Bip86 {
            // BIP-371's declaration that this is a key-path spend, which `AOBS-R05` requires
            // ([#82](https://github.com/allisson/aobs/issues/82),
            // [#113](https://github.com/allisson/aobs/issues/113)). `Declared` is what keeps a
            // taproot plan reaching the output checks this target exists for; the other four
            // variants are the ways the declaration can be broken.
            slot.tap_internal_key = Some(*x_only);
            match &plan.key_path {
                KeyPath::Declared => {}
                KeyPath::Broken(BrokenKeyPath::Absent) => slot.tap_internal_key = None,
                KeyPath::Broken(BrokenKeyPath::Orphaned) => {
                    slot.tap_internal_key = Some(*other);
                }
                KeyPath::Broken(BrokenKeyPath::LeafHashed) => {
                    if let Some((leaves, _)) = slot.tap_key_origins.get_mut(x_only) {
                        leaves.push(TapLeafHash::from_byte_array([0x44; 32]));
                    }
                }
                KeyPath::Broken(BrokenKeyPath::Diverted(claim)) => {
                    if let Some(entry) = slot.tap_key_origins.remove(x_only) {
                        slot.tap_key_origins.insert(*other, entry);
                    }
                    slot.tap_key_origins.insert(
                        *x_only,
                        (vec![], (claim.fingerprint(wallet), claim.path(wallet))),
                    );
                }
            }
        }
        plant_arriving_signature(slot, &plan.arriving, key, x_only);
    }

    if plan.starve_first_input {
        psbt.inputs[0].non_witness_utxo = None;
    }

    for (slot, plan) in psbt.outputs.iter_mut().zip(&plan.outputs) {
        if let Some(claim) = &plan.claim {
            let source = (claim.fingerprint(wallet), claim.path(wallet));
            slot.bip32_derivation.insert(*key, source.clone());
            slot.tap_key_origins.insert(*x_only, (vec![], source));
        }
    }

    Some(psbt.serialize())
}

/// Fill one of the five fields `AOBS-R17` refuses, or leave the input clean
/// ([#115](https://github.com/allisson/aobs/issues/115)).
///
/// **Every value is non-empty on purpose.** These have to survive a serialise/deserialise round
/// trip to reach the policy at all, and an empty `final_script_sig` is a plan that plants nothing
/// while [`assert_no_accepted_input_arrived_signed`] would still demand a refusal.
///
/// Nothing here is a signature the wallet would produce. That is the point: the refusal is for
/// carrying one at all, so a target that planted a *valid* signature would be testing a shape no
/// attacker needs.
fn plant_arriving_signature(
    input: &mut Input,
    arriving: &Arriving,
    key: &PublicKey,
    x_only: &XOnlyPublicKey,
) {
    let Arriving::Signed(field) = arriving else {
        return;
    };
    let schnorr = taproot::Signature {
        signature: schnorr::Signature::from_slice(&[0x42; 64]).expect("64 bytes is a signature"),
        sighash_type: TapSighashType::Default,
    };
    match field {
        ArrivingSignature::PartialSig => {
            input.partial_sigs.insert(
                bitcoin::PublicKey::new(*key),
                ecdsa::Signature {
                    // The low-`s` DER encoding of `(1, 1)`: well-formed, and a signature over
                    // nothing.
                    signature: bitcoin::secp256k1::ecdsa::Signature::from_der(&[
                        0x30, 0x06, 0x02, 0x01, 0x01, 0x02, 0x01, 0x01,
                    ])
                    .expect("well-formed DER"),
                    sighash_type: EcdsaSighashType::All,
                },
            );
        }
        ArrivingSignature::TapKeySig => input.tap_key_sig = Some(schnorr),
        ArrivingSignature::TapScriptSig => {
            input
                .tap_script_sigs
                .insert((*x_only, TapLeafHash::from_byte_array([0x44; 32])), schnorr);
        }
        ArrivingSignature::FinalScriptSig => {
            input.final_script_sig = Some(ScriptBuf::from_bytes(vec![0x51]));
        }
        ArrivingSignature::FinalScriptWitness => {
            input.final_script_witness = Some(Witness::from_slice(&[[0x42; 64].as_slice()]));
        }
    }
}

/// The P2WPKH redeem script BIP49 wraps, for the first receive address.
///
/// A P2SH `scriptPubKey` carries only the hash, so the preimage has to be derived: this is the
/// BIP49 account key's own child, not the BIP84 sibling, and handing over the wrong one would
/// make every BIP49 plan an `AOBS-R05` that never reaches what it is about.
///
/// It takes no wallet because it is cached for the process, and the wallet is the same one for
/// the process: an argument read only on the first call would be a lie on every later one.
fn redeem_script() -> &'static ScriptBuf {
    static SCRIPT: OnceLock<ScriptBuf> = OnceLock::new();
    SCRIPT.get_or_init(|| {
        let secp = Secp256k1::verification_only();
        let key = wallet()
            .account_xpub(Family::Bip49)
            .derive_pub(
                &secp,
                &[
                    ChildNumber::Normal { index: 0 },
                    ChildNumber::Normal { index: 0 },
                ],
            )
            .expect("normal children of an xpub always derive");
        ScriptBuf::new_p2wpkh(&key.to_pub().wpubkey_hash())
    })
}

/// The path the funding transaction's own address sits at: branch 0, index 0, in that family.
fn honest_path(wallet: &Wallet, family: Family) -> DerivationPath {
    wallet.account_path(family).extend([
        ChildNumber::Normal { index: 0 },
        ChildNumber::Normal { index: 0 },
    ])
}

/// Read a claimed path with this file's own arithmetic and derive what it points at, or `None`
/// for a path no wallet of ours would ever scan.
///
/// **`Wallet::verify`'s scanning rule restated here rather than called**: five children on one of
/// our four accounts, an unhardened branch of 0 or 1, an unhardened index. Calling `verify` would
/// assert that `verify` agrees with itself, and `Wallet::address` — the primitive the BIP vectors
/// pin — is the second opinion both assertions below rest on.
fn ours_at(wallet: &Wallet, path: &DerivationPath) -> Option<ScriptBuf> {
    let children: &[ChildNumber] = path.as_ref();
    let [purpose, coin, account, branch, leaf] = children else {
        return None;
    };
    let family = Family::ALL.into_iter().find(|family| {
        let account_path = wallet.account_path(*family);
        let ours: &[ChildNumber] = account_path.as_ref();
        ours == [*purpose, *coin, *account]
    })?;
    let branch = match branch {
        ChildNumber::Normal { index: 0 } => Branch::Receive,
        ChildNumber::Normal { index: 1 } => Branch::Change,
        _ => return None,
    };
    let ChildNumber::Normal { index: leaf } = leaf else {
        return None;
    };
    Some(
        wallet
            .address(family, branch, *leaf)
            .expect("a normal index")
            .script_pubkey(),
    )
}

/// The `scriptPubKey` an input spends, the way `crate::psbt` establishes it: **the previous
/// transaction wins** where both utxo fields are present (`AOBS-R02`), so an inflated
/// `witness_utxo` buys nothing here either.
fn spent_script_pubkey(psbt: &Psbt, index: usize) -> Option<ScriptBuf> {
    let input = &psbt.inputs[index];
    let vout = usize::try_from(psbt.unsigned_tx.input[index].previous_output.vout).ok()?;
    if let Some(previous) = &input.non_witness_utxo {
        return previous.output.get(vout).map(|out| out.script_pubkey.clone());
    }
    input
        .witness_utxo
        .as_ref()
        .map(|out| out.script_pubkey.clone())
}

/// The one path a taproot input claims for its key-path spend — §7 rule 6's taproot half, restated
/// here for the same reason [`ours_at`] is.
fn key_path_claim(input: &Input) -> Option<&DerivationPath> {
    let internal = input.tap_internal_key?;
    let (leaf_hashes, (_, path)) = input.tap_key_origins.get(&internal)?;
    leaf_hashes.is_empty().then_some(path)
}

/// §4's first invariant, checked without going through the code that produced the verdict.
fn assert_no_output_is_ours_that_we_did_not_produce(wallet: &Wallet, accepted: &Accepted) {
    // One row per output, in the transaction's own order — the premise everything below indexes
    // on.
    assert_eq!(
        accepted.review.outputs.len(),
        accepted.psbt.unsigned_tx.output.len(),
        "the model dropped or invented a row"
    );

    for (index, row) in accepted.review.outputs.iter().enumerate() {
        let OutputKind::Change { path, .. } = &row.kind else {
            continue;
        };

        // A path this file cannot re-derive is one `AOBS-R09` should have refused before we got
        // here, so failing to read it is the finding rather than a case to skip.
        let ours = ours_at(wallet, path)
            .unwrap_or_else(|| panic!("accepted change at a path no wallet of ours scans: {path}"));
        assert_eq!(
            accepted.psbt.unsigned_tx.output[index].script_pubkey, ours,
            "output {index} was classified as ours and we did not produce its scriptPubKey"
        );
        assert_eq!(row.address.script_pubkey(), ours, "output {index}");
    }
}

/// §4's second invariant ([#113](https://github.com/allisson/aobs/issues/113)): **every input this
/// wallet owns comes back signed.**
///
/// `crate::sign` asserts this itself, and this is not that assertion twice over: the set of inputs
/// it checks is the one `crate::psbt` computed, where this reads the claim out of the map the
/// input's family is signed from and re-derives with [`ours_at`]. So a rule 6 that drifted — a map
/// read that widened again, a taproot entry counted that the signing path never reaches — arrives
/// here as a signature that is missing rather than as two functions agreeing with each other.
///
/// **And *signed* is one field per family, not either of two**
/// ([#117](https://github.com/allisson/aobs/issues/117)). This is the one place where restating the
/// rule independently is the point: `crate::sign` reads the family off the `Accepted` the check
/// built, where this file decides it from the `scriptPubKey` it already had to read to re-derive.
fn assert_every_input_of_ours_came_back_signed(
    wallet: &Wallet,
    accepted: &Accepted,
    signed: &Psbt,
) {
    for (index, input) in accepted.psbt.inputs.iter().enumerate() {
        let Some(spk) = spent_script_pubkey(&accepted.psbt, index) else {
            continue;
        };
        let taproot = spk.is_p2tr();

        // §7 rule 6: the map the family is *signed* from, and no other. For taproot that is the
        // single entry keyed by the internal key; for the other three, `bip32_derivation`.
        let ours = if taproot {
            key_path_claim(input).is_some_and(|path| ours_at(wallet, path).as_ref() == Some(&spk))
        } else {
            input
                .bip32_derivation
                .values()
                .any(|(_, path)| ours_at(wallet, path).as_ref() == Some(&spk))
        };
        if !ours {
            continue;
        }

        // The same asymmetry one layer down: a taproot key-path signature is `tap_key_sig`, and
        // every other family's is a `partial_sigs` entry. An input carrying only the other
        // family's field is the finding, where the disjunction this replaced called it a pass.
        let signed = &signed.inputs[index];
        let where_it_belongs = if taproot {
            signed.tap_key_sig.is_some()
        } else {
            !signed.partial_sigs.is_empty()
        };
        assert!(
            where_it_belongs,
            "input {index} re-derives to ours and came back with no signature in the field its \
             family is signed from"
        );
    }
}

/// §4's third invariant ([#115](https://github.com/allisson/aobs/issues/115)): **no input of an
/// accepted transaction arrived carrying a signature.**
///
/// It reads the plan rather than the document, which is the point — the plan is what *declared* the
/// signature, so this cannot be fooled by a field that failed to survive the round trip. Reaching it
/// at all means the transaction was accepted, so the plan having declared one is the finding.
///
/// The rule is wider than the shape the ticket found, and deliberately: the check needs no key
/// material, so it runs before anything knows whose the input is, and a pre-signed input the wallet
/// does not own is refused too. Which code that earns is the corpus's assertion — a fuzz target
/// names no `AOBS-R##`.
fn assert_no_accepted_input_arrived_signed(plan: &Plan) {
    let pre_signed = plan
        .inputs
        .iter()
        .any(|input| matches!(input.arriving, Arriving::Signed(_)));
    assert!(
        !pre_signed,
        "a transaction with a pre-signed input was accepted"
    );
}

fuzz_target!(|plan: Plan| {
    let wallet = wallet();
    let Some(bytes) = build(wallet, &plan) else {
        return;
    };

    if let Ok(accepted) = validate(wallet, &bytes) {
        assert_no_accepted_input_arrived_signed(&plan);
        assert_no_output_is_ours_that_we_did_not_produce(wallet, &accepted);
        assert_every_input_of_ours_came_back_signed(wallet, &accepted, &sign(wallet, &accepted));
        let review = &accepted.review;

        // The money adds up, in both directions the model computes it from.
        assert_eq!(
            review.paying + review.returning + review.fee,
            review.input_total
        );
        assert_eq!(review.leaving, review.paying + review.fee);
        assert!(review.outputs.len() <= 6, "the panel cannot hold that many");

        // The warning is a variant and the condition is not re-evaluated anywhere else, so this
        // is the one place the two can be held to each other.
        let fires = review
            .outputs
            .iter()
            .any(|row| row.kind == OutputKind::Payment)
            && review.fee >= review.paying;
        assert_eq!(review.warning.is_some(), fires);
    }
});
