//! `05-testing-and-release.md` §4's third target: **the validator, structure-aware and seeded
//! with our own key material.**
//!
//! Where `psbt_parse` fuzzes raw bytes and spends most of its budget being told *these are not a
//! PSBT*, this one generates PSBTs — a plan of inputs and outputs, turned into a well-formed
//! document that gets past the parser every time, so the mutator's budget goes on the checks
//! rather than on the magic bytes. That is what *structure-aware* buys.
//!
//! **The invariant it asserts is §4's own, and it is the one that matters:**
//!
//! > it never accepts a transaction containing an output classified as ours whose
//! > `scriptPubKey` we did not ourselves produce.
//!
//! It is checked **independently of the code under test**. `psbt.rs` reaches its verdict through
//! `Wallet::verify`, which reads the path, decides whether it is scannable and byte-compares;
//! this target re-reads the path with its own arithmetic, derives through `Wallet::address` — the
//! primitive the BIP vectors pin — and compares again. Calling `verify` here would assert that
//! `verify` agrees with itself.
//!
//! The plan can express the attack directly: a claim carrying our fingerprint at a legitimate
//! change path, over an address we never derived. If `AOBS-R08` ever stops firing on it, an
//! accepted `Review` arrives here with a `Change` row this target cannot reproduce, and the
//! assertion is the finding.

#![no_main]

use std::sync::OnceLock;

use arbitrary::Arbitrary;
use libfuzzer_sys::fuzz_target;

use bitcoin::absolute::LockTime;
use bitcoin::bip32::{ChildNumber, DerivationPath, Fingerprint};
use bitcoin::hashes::Hash as _;
use bitcoin::psbt::Psbt;
use bitcoin::secp256k1::{PublicKey, Secp256k1, XOnlyPublicKey};
use bitcoin::transaction::Version;
use bitcoin::{
    Amount, OutPoint, ScriptBuf, Sequence, Transaction, TxIn, TxOut, WPubkeyHash, Witness,
};

use aobs_core::bip39::Mnemonic;
use aobs_core::derive::{Branch, Family, Network, Wallet};
use aobs_core::psbt::{validate, Accepted, OutputKind};
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

/// A valid public key nobody controls — secp256k1's generator point.
///
/// The derivation maps are **keyed** by a public key and our code reads only the values, so a
/// constant is not a shortcut: a target that had to derive the right key per entry would be
/// asserting that we ignore the key, which we can state instead.
fn placeholder_keys() -> &'static (PublicKey, XOnlyPublicKey) {
    static KEYS: OnceLock<(PublicKey, XOnlyPublicKey)> = OnceLock::new();
    KEYS.get_or_init(|| {
        let key: PublicKey = "0279be667ef9dcbbac55a06295ce870b07029bfcdb2dce28d959f2815b16f81798"
            .parse()
            .expect("a valid compressed key");
        (key, XOnlyPublicKey::from(key))
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
    let (key, x_only) = placeholder_keys();

    for (index, (slot, plan)) in psbt.inputs.iter_mut().zip(&plan.inputs).enumerate() {
        let previous = &previous[index];
        slot.witness_utxo = Some(previous.output[0].clone());
        slot.non_witness_utxo = Some(previous.clone());
        if plan.family.family() == Family::Bip49 {
            // BIP49 is indistinguishable from any other P2SH without it, so an honest plan
            // hands it over and `AOBS-R05` is what refuses the plans that do not.
            slot.redeem_script = Some(redeem_script().clone());
        }
        if plan.family.family() == Family::Bip86 {
            // BIP-371's declaration that this is a key-path spend, which `AOBS-R05` also
            // requires ([#82](https://github.com/allisson/aobs/issues/82)). Without it every
            // taproot plan is refused on the script type and never reaches the output checks
            // this target exists for.
            slot.tap_internal_key = Some(*x_only);
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

/// §4's invariant, checked without going through the code that produced the verdict.
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

        // Read the path with this file's own arithmetic. Anything but five children on one of
        // our four accounts, an unhardened branch of 0 or 1 and an unhardened index, is a path
        // no wallet of ours scans — and `AOBS-R09` should have refused before we got here.
        let children: &[ChildNumber] = path.as_ref();
        let [purpose, coin, account, branch, leaf] = children else {
            panic!("accepted change at a path of {} children", children.len());
        };
        let family = Family::ALL
            .into_iter()
            .find(|family| {
                let account_path = wallet.account_path(*family);
                let ours: &[ChildNumber] = account_path.as_ref();
                ours == [*purpose, *coin, *account]
            })
            .expect("accepted change outside our four accounts");
        let branch = match branch {
            ChildNumber::Normal { index: 0 } => Branch::Receive,
            ChildNumber::Normal { index: 1 } => Branch::Change,
            other => panic!("accepted change on branch {other}"),
        };
        let ChildNumber::Normal { index: leaf } = leaf else {
            panic!("accepted change at a hardened index {leaf}");
        };

        // And derive it again. `Wallet::address` is the primitive the BIP vectors pin, so this
        // is a second opinion rather than the same one.
        let ours = wallet
            .address(family, branch, *leaf)
            .expect("a normal index")
            .script_pubkey();
        assert_eq!(
            accepted.psbt.unsigned_tx.output[index].script_pubkey, ours,
            "output {index} was classified as ours and we did not produce its scriptPubKey"
        );
        assert_eq!(row.address.script_pubkey(), ours, "output {index}");
    }
}

fuzz_target!(|plan: Plan| {
    let wallet = wallet();
    let Some(bytes) = build(wallet, &plan) else {
        return;
    };

    if let Ok(accepted) = validate(wallet, &bytes) {
        assert_no_output_is_ours_that_we_did_not_produce(wallet, &accepted);
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
