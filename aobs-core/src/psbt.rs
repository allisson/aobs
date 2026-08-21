//! PSBT validation, the derivation check and the review model (`02-core.md` §7 and §9).
//!
//! Everything between attacker-controlled bytes and a review screen being drawn. **A
//! rejection here means no screen is drawn at all**, so this module is the one place in the
//! crate where the answer *no* is the product.
//!
//! **Two outcomes, and the distinction is the whole design.** Bytes that never became a PSBT
//! are overwhelmingly a bad scan: [`Rejection::NotAPsbt`] says so, carries **no code**
//! (`06-codes.md` §4) and the screen returns to scanning. Bytes that decoded and *then* failed
//! a check are hostile until proven otherwise: [`Rejection::Refused`] carries a [`Refusal`],
//! which carries a stable `AOBS-R##` and offers exactly one action — discard.
//!
//! **Two stages, and the order is the design.** The structural refusals — `AOBS-R01`–`R05`,
//! `R07`, `R15`, `R16` and `R17` — need no key material at all, so they run first and a hostile PSBT
//! is thrown out before our own seed is asked anything
//! ([#79](https://github.com/allisson/aobs/issues/79)). Then the derivation check (`R06`, `R08`,
//! `R09`) and the review model ([#80](https://github.com/allisson/aobs/issues/80)), which need
//! the wallet.
//!
//! **There is one entry point, [`validate`], and it returns an [`Accepted`].** Not two calls the
//! shell composes: a caller who ran the structural half and forgot the derivation check would
//! have a transaction that looks reviewable and whose change was never re-derived, which is the
//! whole attack. So the only way to obtain something a screen can draw is to have run every
//! check, and `AOBS-R08` cannot be skipped by forgetting a second call.
//!
//! **The claimed derivation selects a candidate; the byte-compare is the only authority.** That
//! is [`crate::derive::Wallet::verify`]'s job and this module never re-implements it — what
//! lives here is which outputs are candidates (a claim carrying *our* fingerprint, which is a
//! hint and authorises nothing), and what each verdict means: `AOBS-R09` for a path we would
//! never scan, `AOBS-R08` for one whose bytes disagree, and a refusal of the **entire
//! transaction** either way rather than a quiet reclassification to *payment*.
//!
//! **For an input the candidate is narrower, and the reason is what happens next**
//! ([#113](https://github.com/allisson/aobs/issues/113)). An output's claim decides a *display*,
//! so either derivation map may carry it; an input's decides whether we hand back a signature, and
//! the two signing paths read one map each — the ECDSA families' `bip32_derivation`, taproot's
//! `tap_key_origins` entry keyed by the internal key. So an input is ours only when the claim in
//! **that** map byte-verifies, which is what makes *ours* and *signable* one question and lets
//! [`crate::sign`] assert it signed everything this wallet owns.
//!
//! **The duplicate-key refusal is the dependency's invariant, not ours.** `bitcoin` 0.32
//! rejects duplicate keys in all three maps, so §7 forbids us a pre-parse scan and requires we
//! assert it anyway: BIP-174's invalid vector 5 is in the corpus for exactly that. A duplicate
//! global xpub arrives as a *different* variant — `XPubKey("Repeated global xpub key")` — and
//! is mapped onto the same refusal, because a refusal must name its own reason.
//!
//! **Three checks §7 deliberately does not add, recorded here so their absence reads as a
//! decision rather than an oversight.** *No absurd-input-count cap*: the 64 KiB transport bound
//! plus the mandatory previous transaction caps inputs at a couple of hundred transitively, and
//! the asymmetry with the six-output cap is the display model — inputs are aggregated on the
//! panel and cost no rows, outputs cost one each. *No mixed-input-script-type refusal*: mixing
//! families from one seed is legitimate, and that refusal is a proxy for the per-input question
//! [`classify`] asks directly. *No OP_RETURN carve-out*: *every output must be renderable as an
//! address* is the simpler rule, and it refuses an OP_RETURN on its own.
//!
//! **Two refusals arrive free and are recorded rather than re-implemented** (§7):
//! `unsigned_tx_checks()` for BIP-174's empty-scriptSig/empty-witness rule, and
//! `PartialDataConsumption` for a global unsigned-tx value with trailing bytes. Both fire
//! inside `Psbt::deserialize`, so both land as [`Rejection::NotAPsbt`] — those bytes never
//! became a PSBT, and giving them a code would file a bad scan under the same heading as an
//! attack.
//!
//! **Observed and not refused:** `Psbt::deserialize` stops at the last output map and ignores
//! whatever follows it, so trailing bytes are accepted and then dropped — we re-serialise from
//! the parsed structure, so nothing signs them. Recorded here rather than turned into a
//! refusal nobody specified.
//!
//! **Unknown fields** are ignored by every check below, and the returned [`Psbt`] is the parsed
//! one — nothing is stripped, so their bytes are what the outbound PSBT carries.

use core::num::NonZeroU64;
use std::collections::BTreeMap;

use bitcoin::bip32::{DerivationPath, Fingerprint};
use bitcoin::psbt::{Error as PsbtError, Input, Output, Psbt};
use bitcoin::sighash::{EcdsaSighashType, TapSighashType};
use bitcoin::taproot::TapLeafHash;
use bitcoin::{Address, Amount, OutPoint, Script, ScriptBuf, Transaction, TxOut};

use crate::derive::{Family, Network, Verdict, Wallet};

/// What the review panel holds in the 800×600 minimum canvas (`04-screens.md` §11.2), payment
/// and change counted together. A seventh output is `AOBS-R15` and not a scroll.
const MAX_OUTPUTS: usize = 6;

/// The DER signature element an ECDSA input is charged in the vsize prediction, sighash byte
/// included — the **smaller** of the two sizes low-S DER produces (`04-screens.md` §11.2.1).
///
/// Charging the smaller one makes the predicted vsize smaller and therefore the displayed rate
/// higher, so the error runs in one direction only: **the rate shown is never lower than the
/// rate the broadcast transaction pays.** About half of ECDSA inputs produce a 72-byte element
/// instead, which reads high by a fraction of a percent.
const ECDSA_SIGNATURE: usize = 71;

/// A compressed public key, which is what all four families spend to.
const COMPRESSED_PUBKEY: usize = 33;

/// A BIP-340 signature under `SIGHASH_DEFAULT`, which is the taproot key path's whole witness
/// item. An explicit `SIGHASH_ALL` would add one byte, so this is the smaller one again.
const SCHNORR_SIGNATURE: usize = 64;

/// BIP49's redeem script: `OP_0 <20-byte key hash>`.
const P2WPKH_REDEEM_SCRIPT: usize = 22;

/// The segwit marker and flag, which cost one weight unit each and are present exactly when
/// some input has a witness (BIP-141).
const SEGWIT_MARKER_AND_FLAG: usize = 2;

/// The two ways inbound bytes fail to become a transaction we will show.
///
/// They are separate arms because they end differently: one returns to scanning and one
/// discards. `02-core.md` §7 — *"failing to decode is not the same as rejecting"*.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Rejection {
    /// The bytes never became a PSBT. No code, no discard, no suspicion: say so and scan
    /// again.
    NotAPsbt,
    /// A well-formed PSBT that failed a check. Discard, and nothing else.
    Refused(Refusal),
}

/// A structural refusal: its reason in plain language and its stable code.
///
/// **Several variants may share one code.** `06-codes.md` §3 — the code names the refusal, not
/// the copy, so the three ways an input's amount can be uncheckable are three sentences and one
/// `AOBS-R02`. A user comparing two machines is comparing which check tripped.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Refusal {
    /// `AOBS-R01` — the same key twice in some map. The dependency's invariant; ours to name.
    DuplicateKey,
    /// `AOBS-R02` — no previous transaction, and no taproot exemption to fall back on.
    PreviousTransactionAbsent {
        /// Zero-based index into the inputs; the copy states it one-based.
        input: usize,
    },
    /// `AOBS-R02` — a previous transaction that does not hash to the outpoint's txid.
    PreviousTransactionMismatch {
        /// Zero-based index into the inputs.
        input: usize,
    },
    /// `AOBS-R02` — the right previous transaction, with no output at the index spent.
    PreviousOutputMissing {
        /// Zero-based index into the inputs.
        input: usize,
    },
    /// `AOBS-R03` — a sighash other than `SIGHASH_ALL`, or `SIGHASH_DEFAULT` for taproot.
    UnsupportedSighash {
        /// Zero-based index into the inputs.
        input: usize,
    },
    /// `AOBS-R04` — the sum of outputs exceeds the sum of inputs.
    OutputsExceedInputs,
    /// `AOBS-R05` — an input whose script type is outside BIP44/49/84/86 single-sig.
    UnsupportedInputScript {
        /// Zero-based index into the inputs.
        input: usize,
    },
    /// `AOBS-R07` — an output we cannot render as an address.
    UnrenderableOutput {
        /// Zero-based index into the outputs; the copy states it one-based.
        output: usize,
    },
    /// `AOBS-R15` — more than six outputs, payment and change counted together.
    TooManyOutputs {
        /// How many the transaction has.
        count: usize,
    },
    /// `AOBS-R16` — the inputs claim to be worth more than the money that will ever exist.
    ///
    /// Consensus caps the supply at 21 000 000 BTC, so a transaction whose inputs sum above it
    /// is describing UTXOs that cannot exist. The check is here rather than left implicit
    /// because a taproot input carries only its `witness_utxo` and nothing cross-checks the
    /// amount (BIP-341 makes a lie invalidate the signature, which is a property of *signing*,
    /// not of reviewing) — so two of them can claim `u64::MAX` each and every number the review
    /// panel is about would overflow the type that carries it.
    AmountOutOfRange,
    /// `AOBS-R17` — an input that already carries a signature
    /// ([#115](https://github.com/allisson/aobs/issues/115), `02-core.md` §7).
    ///
    /// **Five fields, signatures and finalized alike**: `partial_sigs`, `tap_key_sig`,
    /// `tap_script_sigs`, `final_script_sig` and `final_script_witness`. BIP-174 has a Finalizer
    /// *remove* `partial_sigs` when it writes the final script, so the last two are the same
    /// signature in the other encoding and refusing one while accepting the other would draw the
    /// line exactly where an attacker chooses.
    ///
    /// **It is what lets [`crate::sign::sign`] assert the delta.** `Psbt::sign` declines a
    /// taproot key path when `tap_key_sig` is already set, so before this refusal a PSBT arriving
    /// with 64 bytes of nonsense in that field was accepted, reviewed, held for three seconds and
    /// handed back unchanged under a screen reading *Signed*. Nothing here checks whether an
    /// arriving signature is *valid*, and nothing needs to: the document is refused for carrying
    /// one at all.
    ///
    /// **The rule is about the input, not about ownership.** It needs no key material, so it runs
    /// with the structural refusals and therefore before anything knows whose the input is — a
    /// pre-signed input we do not own is refused too. We sign single-sig, so we are the only
    /// Signer there is, and BIP-174 gives one no reason to accept an input somebody already
    /// signed.
    InputAlreadySigned {
        /// Zero-based index into the inputs; the copy states it one-based.
        input: usize,
    },
    /// `AOBS-R06` — no input re-derives to our own key material.
    ///
    /// **Four copy requirements, one code** (`02-core.md` §7), because this refusal would
    /// otherwise read as a bug in aobs. Two are unconditional — the loaded network and account 0,
    /// always named. Two are conditional: the passphrase, named as the likely cause when one is
    /// in use, and the coin-type disagreement, stated outright when every input declares the
    /// other network's. Those two booleans are what makes this one code four sentences.
    ///
    /// **The coin type selects copy and nothing else** (standing rule 1): acceptance rests
    /// entirely on the byte-compare, and the shell must not branch on any of this — it renders
    /// [`Refusal::reason`] (standing rule 4).
    NoInputOfOurs {
        /// The loaded network, named in every variant. A network mismatch reaches this refusal
        /// with no other symptom, because `scriptPubKey`s are network-agnostic bytes.
        network: Network,
        /// Whether a passphrase was in use at load.
        passphrase_in_use: bool,
        /// Whether **every** input declares the other network's BIP-44 coin type, which is what
        /// makes *this transaction was built for the other network* a fact we can state.
        coin_type_mismatch: bool,
    },
    /// `AOBS-R08` — an output claiming to be ours fails the `scriptPubKey` byte-compare.
    ///
    /// The change-substitution class. It refuses the **entire transaction** rather than being
    /// reclassified as a plain spend and shown, because there is no state of the user's
    /// knowledge that makes a transaction lying about where its change goes acceptable.
    ChangeMismatch {
        /// Zero-based index into the outputs; the copy states it one-based.
        output: usize,
    },
    /// `AOBS-R09` — change on a path this wallet would never scan.
    ///
    /// Coldcard's 2019 change-path ransom: coins that are provably yours and that your wallet
    /// will never look for.
    UnscannableChangePath {
        /// Zero-based index into the outputs.
        output: usize,
    },
}

impl Refusal {
    /// Every variant, for the tests that hold the codes to `06-codes.md` §6.
    ///
    /// The indices are samples: nothing about a code or the shape of its copy depends on
    /// which input tripped it.
    /// One entry per variant, not per copy: [`Refusal::NoInputOfOurs`] has four sentences and
    /// appears once, and the four are asserted in `psbt_tests.rs` instead.
    pub const ALL: [Self; 14] = [
        Self::DuplicateKey,
        Self::PreviousTransactionAbsent { input: 0 },
        Self::PreviousTransactionMismatch { input: 0 },
        Self::PreviousOutputMissing { input: 0 },
        Self::UnsupportedSighash { input: 0 },
        Self::OutputsExceedInputs,
        Self::UnsupportedInputScript { input: 0 },
        Self::UnrenderableOutput { output: 0 },
        Self::TooManyOutputs { count: 7 },
        Self::AmountOutOfRange,
        Self::InputAlreadySigned { input: 0 },
        Self::NoInputOfOurs {
            network: Network::Mainnet,
            passphrase_in_use: false,
            coin_type_mismatch: false,
        },
        Self::ChangeMismatch { output: 0 },
        Self::UnscannableChangePath { output: 0 },
    ];

    /// The stable machine-readable code, from `06-codes.md` §6's `AOBS-R##` space.
    ///
    /// It is the half a user can read off a panel and type into a bug report, and the half a
    /// refactor may not rename.
    #[must_use]
    pub fn code(self) -> &'static str {
        match self {
            Self::DuplicateKey => "AOBS-R01",
            Self::PreviousTransactionAbsent { .. }
            | Self::PreviousTransactionMismatch { .. }
            | Self::PreviousOutputMissing { .. } => "AOBS-R02",
            Self::UnsupportedSighash { .. } => "AOBS-R03",
            Self::OutputsExceedInputs => "AOBS-R04",
            Self::UnsupportedInputScript { .. } => "AOBS-R05",
            Self::UnrenderableOutput { .. } => "AOBS-R07",
            Self::TooManyOutputs { .. } => "AOBS-R15",
            Self::AmountOutOfRange => "AOBS-R16",
            Self::InputAlreadySigned { .. } => "AOBS-R17",
            Self::NoInputOfOurs { .. } => "AOBS-R06",
            Self::ChangeMismatch { .. } => "AOBS-R08",
            Self::UnscannableChangePath { .. } => "AOBS-R09",
        }
    }

    /// The specific reason, in plain language, for the screen to state verbatim.
    ///
    /// Computed here and never assembled by the shell, which marshals and evaluates nothing
    /// (standing rule 4). Positions are stated one-based, because the panel counts that way
    /// and nobody reads a transaction from input zero.
    #[must_use]
    pub fn reason(self) -> String {
        match self {
            Self::DuplicateKey => "This transaction file carries the same field twice. \
                 BIP-174 says a file like that is invalid, so there is nothing here to \
                 review."
                .to_owned(),
            Self::PreviousTransactionAbsent { input } => format!(
                "Input {} does not carry the transaction it spends from, so the amount it \
                 says it is worth cannot be checked. aobs needs that transaction for every \
                 input except a taproot one.",
                input + 1
            ),
            Self::PreviousTransactionMismatch { input } => format!(
                "Input {} carries a previous transaction that is not the one it says it \
                 spends, so the amount it says it is worth cannot be checked.",
                input + 1
            ),
            Self::PreviousOutputMissing { input } => format!(
                "Input {}'s previous transaction has no output in the position the input \
                 spends, so the amount it says it is worth cannot be checked.",
                input + 1
            ),
            Self::UnsupportedSighash { input } => format!(
                "Input {} asks to be signed under a rule other than signing all of this \
                 transaction. There is no honest way to show you what that would commit you \
                 to.",
                input + 1
            ),
            Self::OutputsExceedInputs => "This transaction pays out more than its inputs \
                 provide, which no valid transaction can do."
                .to_owned(),
            Self::UnsupportedInputScript { input } => format!(
                "Input {} spends a kind of output aobs does not model. It signs \
                 single-signature inputs only, in the four standard forms.",
                input + 1
            ),
            Self::UnrenderableOutput { output } => format!(
                "Output {} is not an address aobs can write down. Approving it would mean \
                 approving raw script you cannot read.",
                output + 1
            ),
            Self::TooManyOutputs { count } => format!(
                "This transaction has {count} outputs and the review panel holds \
                 {MAX_OUTPUTS}. aobs will not ask you to approve an output it has not shown \
                 you. Split the payment and sign it in parts."
            ),
            Self::AmountOutOfRange => "This transaction says its inputs are worth more than \
                 the 21 million bitcoin that will ever exist, so at least one of the amounts \
                 in it is false."
                .to_owned(),
            Self::InputAlreadySigned { input } => format!(
                "Input {} already carries a signature. aobs signs single-signature inputs, so \
                 it is the only signer there is, and a transaction that already holds a \
                 signature for an input is not asking aobs for one.",
                input + 1
            ),
            Self::NoInputOfOurs {
                network,
                passphrase_in_use,
                coin_type_mismatch,
            } => {
                // Four sentences for four requirements, assembled rather than written out as
                // four `format!` arms: the requirements compose — a passphrase and a coin-type
                // disagreement can both be true — and four arms would be four places to forget
                // one of the two that are unconditional. Assembled *here* rather than in a
                // helper, because a helper taking these three would be a signature with two
                // same-typed booleans side by side, and nothing would catch them swapped.
                let mut reason = String::from(
                    "None of this transaction's inputs belongs to the wallet you loaded: aobs \
                     re-derived every one of them from your own seed and none of them matched.",
                );

                if coin_type_mismatch {
                    // The one variant that names a cause instead of listing three. Three causes
                    // in a list names nothing, and this is the common accidental case.
                    reason.push_str(&format!(
                        " Every input in it was built for {}, and the wallet you loaded is for \
                         {}.",
                        network.other().name(),
                        network.name()
                    ));
                } else {
                    reason.push_str(&format!(
                        " The wallet you loaded is for {}.",
                        network.name()
                    ));
                }

                reason.push_str(
                    " aobs derives account 0 of each of the four standard address types, so a \
                     wallet kept on a different account arrives here too.",
                );

                if passphrase_in_use {
                    reason.push_str(
                        " You loaded this wallet with a passphrase, and a passphrase that \
                         differs by one character derives an entirely different wallet — that is \
                         the likeliest cause.",
                    );
                }

                reason
            }
            Self::ChangeMismatch { output } => format!(
                "Output {} says it comes back to this wallet, and the address it actually pays \
                 is not the one aobs derives at the path it claims. aobs will not sign a \
                 transaction that misdescribes where its change goes.",
                output + 1
            ),
            Self::UnscannableChangePath { output } => format!(
                "Output {} says it comes back to this wallet at a path aobs would never look \
                 at, so those coins would be yours and unfindable. aobs derives account 0 of \
                 each of the four standard address types, on the receiving and change branches \
                 only.",
                output + 1
            ),
        }
    }
}

/// An accepted transaction: the document, and the model of it a screen renders.
///
/// **Two public fields rather than two return values.** §8 signs the PSBT the review was computed
/// from, so both have to cross the seam — and handing them back separately would let a caller pair
/// a review with a different transaction, which is the same class of mistake as skipping the
/// derivation check. Pairing them here keeps [`Review`] to exactly the contents `02-core.md` §9
/// lists, none of which is the document.
///
/// The third field is crate-private and is what makes [`crate::sign`]'s assertion sayable
/// ([#113](https://github.com/allisson/aobs/issues/113)). **What it buys is exactly one thing and
/// no more:** nothing outside this crate can construct an `Accepted`, so *the only way to obtain
/// one is to have run every check* is now a property of the type rather than an argument about the
/// call graph. It is **not** a claim that a held one cannot be edited — `psbt` and `review` are
/// public and the type is `Clone`, so a caller could still clone one and swap the document. That
/// would trip `crate::sign`'s assertion as `AOBS-E04`, which is a crate bug rather than a hostile
/// input, and closing it means accessors rather than fields.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Accepted {
    /// The parsed PSBT, unmodified: unknown fields included, nothing stripped (§8).
    pub psbt: Psbt,
    /// What the review panel draws.
    pub review: Review,
    /// The indices of the inputs the byte-compare found ours, in the transaction's own order —
    /// **exactly the inputs `crate::sign` must come back having signed** (§8a).
    pub(crate) ours: Vec<usize>,
}

/// The typed model the review panel renders (`02-core.md` §9).
///
/// **The shell renders this and evaluates nothing** (standing rule 4). Every number crosses the
/// seam as a [`Amount`] and is written by [`crate::format`]; the warning is a variant and never
/// a formatted string, so no arm of the shell re-tests the condition that produced it.
///
/// The fields are §9's list and nothing else — the PSBT it is about is [`Accepted::psbt`].
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Review {
    /// The loaded network. Stated on the panel because a `scriptPubKey` cannot state it.
    pub network: Network,
    /// How many inputs the transaction spends. Inputs are aggregated on the panel and cost no
    /// rows, which is why there is no bound on them the way there is on outputs.
    pub input_count: usize,
    /// What those inputs are worth together.
    pub input_total: Amount,
    /// What leaves the wallet: the input total less what comes back. Equal to
    /// [`Review::paying`] plus [`Review::fee`].
    pub leaving: Amount,
    /// What the recipients receive: the total to outputs that are not our change. It is the
    /// denominator of both the fee percentage and the one warning, so the two cannot disagree
    /// about what they are about.
    pub paying: Amount,
    /// What comes back to this wallet: the total to outputs that re-derived to ours.
    pub returning: Amount,
    /// The fee, absolute. The panel also states it as a rate over [`Review::vsize`] and as a
    /// percentage of [`Review::paying`] — same number, three readings.
    pub fee: Amount,
    /// The **predicted vsize of the signed** transaction, in vbytes, which is what the fee rate
    /// divides by (`04-screens.md` §11.2.1).
    ///
    /// The PSBT carries an unsigned transaction, so this is a prediction rather than a
    /// measurement — sound because the wallet is single-sig across exactly four known script
    /// types, and charged the smaller signature element in every family so the rate it produces
    /// is never lower than the rate that will be paid.
    pub vsize: NonZeroU64,
    /// One row per output, in the transaction's own order. At most six of them: a seventh is
    /// `AOBS-R15` and the panel is never asked to draw what it cannot hold.
    pub outputs: Vec<OutputRow>,
    /// The one advisory warning, or nothing.
    pub warning: Option<Warning>,
}

/// One output row on the panel: the address at full width, the amount, and what it is.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct OutputRow {
    /// The address, rendered for the loaded network. It exists because `AOBS-R07` refused every
    /// output that has no address form.
    pub address: Address,
    /// What this output pays.
    pub amount: Amount,
    /// Payment or change — and change only after the byte-compare said so.
    pub kind: OutputKind,
}

/// What an output is, after the derivation check (`02-core.md` §7).
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum OutputKind {
    /// A payment: no derivation claim at all, or one bearing a fingerprint that is not ours.
    ///
    /// **No suspicion attaches to it** — it is displayed in full and given its own confirmation
    /// screen. Both attack directions are safe here: marking real change as foreign only causes
    /// it to be *shown*, and putting our fingerprint on the attacker's address fails the
    /// byte-compare and refuses the transaction.
    Payment,
    /// Change: an output that claimed our fingerprint and then proved it.
    ///
    /// §11.2 presents change as **settled rather than as a thing to check**, which is only
    /// honest if the re-derivation actually ran — so the verdict travels with the row rather
    /// than being assumed by the screen.
    Change {
        /// The full claimed path, which is also the path we derived at. The panel states it.
        path: DerivationPath,
        /// The verdict.
        verdict: Rederivation,
    },
}

/// The re-derivation verdict on a change output.
///
/// **One arm, deliberately.** The other two verdicts do not reach a panel: a path we would never
/// scan is `AOBS-R09` and bytes that disagree are `AOBS-R08`, and both refuse the entire
/// transaction. The variant exists rather than being implied because §11.2 makes the panel
/// *state* that the compare ran, and a screen may not state something the model does not carry.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Rederivation {
    /// The `scriptPubKey` derived at this path was byte-identical to the one the transaction
    /// carries.
    MatchedByteForByte,
}

/// The one advisory warning (`02-core.md` §9).
///
/// A warning is only legitimate when the user knows something we don't; everything else is a
/// refusal. This is the only condition that qualifies, and it is a variant rather than a string
/// so the shell renders it and never evaluates it.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Warning {
    /// `fee ≥ total sent to non-change outputs` — *you are paying miners more than you are
    /// paying your recipient*.
    ///
    /// True or false regardless of congestion, fiat price, urgency or size, which is exactly
    /// what makes it sayable by a device in a Faraday cage. **Silent for a consolidation**: with
    /// no non-change outputs the ratio is undefined and nothing fires.
    FeeAbovePayment,
}

/// One input's spent output, as the structural walk established it.
///
/// It exists so the derivation check and the vsize prediction do not re-derive facts the walk
/// already had. Recomputing them would mean a second pass with error arms that cannot be
/// reached, which is worse than carrying three fields.
struct Spend {
    /// Which of the four script types, for the vsize prediction.
    script: InputScript,
    /// What the input is worth, from the previous transaction rather than asserted.
    value: Amount,
    /// The `scriptPubKey` being spent — the right-hand side of the input byte-compare.
    script_pubkey: ScriptBuf,
}

/// One of the four script types we model, identified from the output being spent.
///
/// Not *ours* — that is the derivation check's word (`R06`, `R08`). This says only that the
/// input is a shape BIP44/49/84/86 single-sig describes, which is what `AOBS-R05` asks.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum InputScript {
    /// BIP44.
    P2pkh,
    /// BIP49, whose redeem script has been checked to hash to the `scriptPubKey`.
    P2shP2wpkh,
    /// BIP84.
    P2wpkh,
    /// BIP86, key path.
    P2tr,
}

impl InputScript {
    /// Bytes this input's `scriptSig` gains when it is signed (`04-screens.md` §11.2.1).
    ///
    /// The unsigned transaction already spends one byte on each empty `scriptSig`'s length
    /// prefix, and every signed form here stays under 253 bytes, so the prefix does not grow
    /// and this is the script's own length.
    fn script_sig_growth(self) -> usize {
        match self {
            // `<signature> <pubkey>`, each behind its own one-byte push opcode.
            Self::P2pkh => 1 + ECDSA_SIGNATURE + 1 + COMPRESSED_PUBKEY,
            // One push of the 22-byte P2WPKH redeem script; the witness carries the rest.
            Self::P2shP2wpkh => 1 + P2WPKH_REDEEM_SCRIPT,
            Self::P2wpkh | Self::P2tr => 0,
        }
    }

    /// Bytes this input contributes to the witness of a signed **segwit** transaction.
    ///
    /// A legacy input inside a segwit transaction still costs its item count of zero, which is
    /// why `P2pkh` is 1 here and not 0. When no input has a witness the transaction is not
    /// segwit at all and none of this is counted — see [`predicted_vsize`].
    fn witness_size(self) -> usize {
        match self {
            Self::P2pkh => 1,
            Self::P2shP2wpkh | Self::P2wpkh => 1 + (1 + ECDSA_SIGNATURE) + (1 + COMPRESSED_PUBKEY),
            Self::P2tr => 1 + (1 + SCHNORR_SIGNATURE),
        }
    }

    /// Whether the signed form of this input carries a witness at all.
    fn is_segwit(self) -> bool {
        !matches!(self, Self::P2pkh)
    }
}

/// Parse hostile bytes, run every check, and return the transaction with the model of it.
///
/// The whole inbound path in one call: decode, the structural refusals that need no key
/// material, then the derivation check and the review model, which need the wallet. There is no
/// way to obtain an [`Accepted`] without having run all of it, which is the point — see the
/// module documentation.
///
/// # Errors
///
/// [`Rejection::NotAPsbt`] when the bytes never decoded, [`Rejection::Refused`] when they
/// decoded and failed a check.
pub fn validate(wallet: &Wallet, bytes: &[u8]) -> Result<Accepted, Rejection> {
    let psbt = parse(bytes)?;
    let spends = check(&psbt).map_err(Rejection::Refused)?;
    build(wallet, psbt, &spends).map_err(Rejection::Refused)
}

/// Decode, mapping the dependency's two duplicate-key mechanisms onto `AOBS-R01` and
/// everything else onto *these bytes are not a PSBT*.
fn parse(bytes: &[u8]) -> Result<Psbt, Rejection> {
    Psbt::deserialize(bytes).map_err(|error| match error {
        // Three sites in the dependency raise this one variant — `decode_global`,
        // `Input::decode` and `Output::decode` — which is why there is no pre-parse scan here.
        PsbtError::DuplicateKey(_) => Rejection::Refused(Refusal::DuplicateKey),
        // §7: a duplicate global xpub is guarded differently and arrives as a different
        // variant. The string is matched exactly, because `XPubKey` also carries four
        // malformed-xpub messages that are decode failures and not duplicates.
        PsbtError::XPubKey("Repeated global xpub key") => Rejection::Refused(Refusal::DuplicateKey),
        _ => Rejection::NotAPsbt,
    })
}

/// The structural checks, in `06-codes.md` §6's numeric order with one exception: the output
/// count runs first.
///
/// `AOBS-R15` is a property of the transaction as a whole and needs no walk, so a
/// two-thousand-output PSBT is refused for what it is rather than for whichever of its
/// outputs happens to fail something else first.
fn check(psbt: &Psbt) -> Result<Vec<Spend>, Refusal> {
    let outputs = &psbt.unsigned_tx.output;
    if outputs.len() > MAX_OUTPUTS {
        return Err(Refusal::TooManyOutputs {
            count: outputs.len(),
        });
    }

    // Zipped rather than indexed: `Psbt::deserialize` decodes exactly as many input maps as
    // the unsigned transaction has inputs, and zipping means no arm of this loop can panic
    // if that ever stops being true.
    let mut spends = Vec::with_capacity(psbt.inputs.len());
    let mut input_total: u128 = 0;
    for (index, (txin, input)) in psbt.unsigned_tx.input.iter().zip(&psbt.inputs).enumerate() {
        // `AOBS-R17` first in the loop, because it is the one question here that needs nothing
        // at all — not the spent output, not the script type, not our key material. An input
        // that is both pre-signed and starved is refused for the signature, which is the more
        // specific fact about it (`02-core.md` §7,
        // [#115](https://github.com/allisson/aobs/issues/115)).
        if arrived_signed(input) {
            return Err(Refusal::InputAlreadySigned { input: index });
        }
        let spent = spent_output(input, txin.previous_output, index)?;
        let script = classify(&spent.script_pubkey, input)
            .ok_or(Refusal::UnsupportedInputScript { input: index })?;
        if !sighash_commits_to_everything(input, script) {
            return Err(Refusal::UnsupportedSighash { input: index });
        }
        input_total += u128::from(spent.value.to_sat());
        spends.push(Spend {
            script,
            value: spent.value,
            script_pubkey: spent.script_pubkey.clone(),
        });
    }

    // `u128` because the amounts are attacker-supplied `u64`s and a wrapping add would turn
    // "pays out more than it holds" into "pays out nothing".
    //
    // `AOBS-R16` runs here, before the comparison below and before any number reaches the
    // review model: consensus caps the supply, so a sum above it is describing UTXOs that
    // cannot exist — and once the sum fits, so does every number derived from it, which is
    // what lets the model carry `Amount`s at all.
    if input_total > u128::from(Amount::MAX_MONEY.to_sat()) {
        return Err(Refusal::AmountOutOfRange);
    }

    let output_total: u128 = outputs
        .iter()
        .map(|out| u128::from(out.value.to_sat()))
        .sum();
    if output_total > input_total {
        return Err(Refusal::OutputsExceedInputs);
    }

    for (index, out) in outputs.iter().enumerate() {
        if !renderable(&out.script_pubkey) {
            return Err(Refusal::UnrenderableOutput { output: index });
        }
    }

    Ok(spends)
}

/// The derivation check and the review model — everything that needs our own key material
/// (`02-core.md` §7's derivation check and §9).
///
/// The inputs are asked first. `AOBS-R06` is a property of the transaction as a whole, and a
/// PSBT for somebody else's wallet should be refused for being somebody else's rather than for
/// whichever of its outputs failed a compare — which is also what makes a testnet PSBT loaded
/// as mainnet land here, with the coin-type sentence, instead of on `AOBS-R09`.
fn build(wallet: &Wallet, psbt: Psbt, spends: &[Spend]) -> Result<Accepted, Refusal> {
    let ours = inputs_of_ours(wallet, &psbt, spends);
    if ours.is_empty() {
        return Err(Refusal::NoInputOfOurs {
            network: wallet.network(),
            passphrase_in_use: wallet.passphrase_in_use(),
            coin_type_mismatch: every_input_declares_the_other_network(wallet, &psbt),
        });
    }

    let mut rows = Vec::with_capacity(psbt.unsigned_tx.output.len());
    let mut returning = Amount::ZERO;
    let mut paying = Amount::ZERO;
    let mut payments = 0usize;

    for (index, txout) in psbt.unsigned_tx.output.iter().enumerate() {
        // Rendered for the **loaded** network, where `renderable` above asked the
        // network-free question. Reusing `AOBS-R07` rather than unwrapping is what keeps the
        // two from disagreeing silently if that claim ever stops holding.
        let address = Address::from_script(&txout.script_pubkey, wallet.network().params())
            .map_err(|_| Refusal::UnrenderableOutput { output: index })?;

        let kind = match change_path(wallet, psbt.outputs.get(index), &txout.script_pubkey, index)?
        {
            Some(path) => {
                returning += txout.value;
                OutputKind::Change {
                    path,
                    verdict: Rederivation::MatchedByteForByte,
                }
            }
            None => {
                payments += 1;
                paying += txout.value;
                OutputKind::Payment
            }
        };

        rows.push(OutputRow {
            address,
            amount: txout.value,
            kind,
        });
    }

    // Every sum below fits a `u64` because `AOBS-R16` bounded the input total by the money
    // supply and `AOBS-R04` bounded the output total by the input total.
    let input_total = Amount::from_sat(spends.iter().map(|spend| spend.value.to_sat()).sum());
    let output_total = Amount::from_sat(
        psbt.unsigned_tx
            .output
            .iter()
            .map(|out| out.value.to_sat())
            .sum(),
    );

    Ok(Accepted {
        review: Review {
            network: wallet.network(),
            input_count: spends.len(),
            input_total,
            leaving: input_total - returning,
            paying,
            returning,
            fee: input_total - output_total,
            vsize: predicted_vsize(&psbt.unsigned_tx, spends),
            outputs: rows,
            // §9's carve-out is the `payments > 0`: with no non-change outputs the ratio is
            // undefined, so a consolidation fires nothing rather than firing on `fee >= 0`.
            warning: (payments > 0 && input_total - output_total >= paying)
                .then_some(Warning::FeeAbovePayment),
        },
        psbt,
        ours,
    })
}

/// Which inputs re-derive to our own key material — the `AOBS-R06` question, and the set
/// [`crate::sign`] is asserted to sign.
///
/// **The fingerprint is not read at all here.** The asymmetry with [`change_path`] is deliberate:
/// for an output the fingerprint decides between two *displays* and §7 fixes that a foreign one
/// is a payment, but for an input it would only decide whether to ask a question the byte-compare
/// answers outright. It cannot accept anything wrong — what makes an input ours is that we derive
/// its `scriptPubKey`, and a coordinator that filled the fingerprint in wrongly should not make a
/// wallet unsignable. Which *paths* are candidates is [`input_is_ours`]'s narrower question.
fn inputs_of_ours(wallet: &Wallet, psbt: &Psbt, spends: &[Spend]) -> Vec<usize> {
    spends
        .iter()
        .zip(&psbt.inputs)
        .enumerate()
        .filter(|(_, (spend, input))| input_is_ours(wallet, spend, input))
        .map(|(index, _)| index)
        .collect()
}

/// Whether this one input re-derives to ours — the byte-compare over **the claims that describe
/// this spend** ([#113](https://github.com/allisson/aobs/issues/113)).
///
/// **A claim only counts in the map its family is signed from**, and the asymmetry with
/// [`change_path`] is the reason: an output's claim decides a *display*, so reading one from
/// either map costs nothing, while an input's decides whether we will hand back a signature. The
/// two signing paths read one map each — the ECDSA families' from `bip32_derivation`, taproot's
/// from the `tap_key_origins` entry keyed by the internal key — so a claim in the other map is
/// not a claim about this spend at all, and counting it would mean calling an input ours and then
/// returning it unsigned under a screen that says *Signed*.
///
/// Standing rule 1 is untouched: this narrows *which* attacker-supplied path is read, and the
/// byte-compare is still the only thing that accepts.
fn input_is_ours(wallet: &Wallet, spend: &Spend, input: &Input) -> bool {
    let ours = |path: &DerivationPath| {
        matches!(
            wallet.verify(path, &spend.script_pubkey),
            Verdict::Ours { .. }
        )
    };
    match spend.script {
        // `AOBS-R05` established that the entry exists; this reads the path out of it.
        InputScript::P2tr => taproot_key_path_claim(input).is_some_and(|(_, path)| ours(path)),
        InputScript::P2pkh | InputScript::P2shP2wpkh | InputScript::P2wpkh => {
            input.bip32_derivation.values().any(|(_, path)| ours(path))
        }
    }
}

/// The `tap_key_origins` entry that declares this input's key-path spend, or `None`.
///
/// BIP-371's two halves of one declaration: the key is `PSBT_IN_TAP_INTERNAL_KEY`, and the entry
/// naming it carries **no leaf hashes** — an entry with leaf hashes is a script-path key, and the
/// dependency's taproot signing path skips it for exactly that reason. Absence is `AOBS-R05`.
fn taproot_key_path_claim(input: &Input) -> Option<&(Fingerprint, DerivationPath)> {
    let internal = input.tap_internal_key?;
    let (leaf_hashes, source) = input.tap_key_origins.get(&internal)?;
    leaf_hashes.is_empty().then_some(source)
}

/// The path an output comes back to us at, or `None` when it is a payment.
///
/// **The fingerprint is a hint and authorises nothing** (§7): it selects which claims are
/// candidates, and a foreign one makes the output a payment with no suspicion attached. What
/// decides is [`crate::derive::Wallet::verify`].
///
/// # Errors
///
/// `AOBS-R09` when a candidate points somewhere we would never scan, `AOBS-R08` when it points
/// at one of our paths and the bytes disagree. Both refuse the entire transaction.
fn change_path(
    wallet: &Wallet,
    output: Option<&Output>,
    script_pubkey: &Script,
    index: usize,
) -> Result<Option<DerivationPath>, Refusal> {
    // A missing output map is no claim, which is a payment. `Psbt::deserialize` gives one map
    // per output, so this is the same defence as the zip in `check`.
    let Some(output) = output else {
        return Ok(None);
    };

    let mut refusal = None;
    for (fingerprint, path) in claims(&output.bip32_derivation, &output.tap_key_origins) {
        if fingerprint != wallet.fingerprint() {
            continue;
        }
        match wallet.verify(path, script_pubkey) {
            Verdict::Ours { .. } => return Ok(Some(path.clone())),
            Verdict::Unscannable => {
                refusal.get_or_insert(Refusal::UnscannableChangePath { output: index });
            }
            Verdict::Mismatch => {
                refusal.get_or_insert(Refusal::ChangeMismatch { output: index });
            }
        }
    }

    // A claim that verifies wins over one that does not, whatever order the maps hold them in:
    // an output is ours if *some* claimed path derives it. Only when none does is the first
    // failing verdict the refusal.
    match refusal {
        Some(refusal) => Err(refusal),
        None => Ok(None),
    }
}

/// Every `(fingerprint, path)` a derivation map pair claims, taproot origins included.
///
/// Both PSBT maps are walked because the four families straddle them: BIP44/49/84 declare their
/// origins in `bip32_derivation` and BIP86 in `tap_key_origins`, and an output is entitled to
/// carry either.
///
/// **Outputs and copy only.** An input's own claim is [`input_is_ours`]'s narrower question, which
/// reads the map the input's family is *signed* from and no other
/// ([#113](https://github.com/allisson/aobs/issues/113)); what this is still asked about an input
/// is [`every_input_declares_the_other_network`], where a declaration in either map is evidence
/// about which network the coordinator built for and decides nothing but a sentence.
fn claims<'a, K1, K2>(
    bip32: &'a BTreeMap<K1, (Fingerprint, DerivationPath)>,
    taproot: &'a BTreeMap<K2, (Vec<TapLeafHash>, (Fingerprint, DerivationPath))>,
) -> impl Iterator<Item = (Fingerprint, &'a DerivationPath)> {
    bip32
        .values()
        .chain(taproot.values().map(|(_, source)| source))
        .map(|(fingerprint, path)| (*fingerprint, path))
}

/// Whether **every** input declares the other network's BIP-44 coin type — `AOBS-R06`'s fourth
/// copy requirement (§7).
///
/// It selects copy and nothing else. *Every* rather than *any*, because one input built for the
/// other network among several of ours is not a network mistake; and *the other network's* coin
/// type rather than merely a disagreeing one, because the sentence names which network the
/// transaction was built for, and a coin type belonging to some third chain would not license
/// that claim. An input declaring nothing disqualifies the variant: the copy would be asserting
/// something about a path that is not there.
fn every_input_declares_the_other_network(wallet: &Wallet, psbt: &Psbt) -> bool {
    let purposes = Family::ALL.map(Family::purpose);
    let theirs = wallet.network().other().coin_type();

    !psbt.inputs.is_empty()
        && psbt.inputs.iter().all(|input| {
            let mut declared = claims(&input.bip32_derivation, &input.tap_key_origins)
                .filter_map(|(_, path)| {
                    let [purpose, coin, ..] = path.as_ref() else {
                        return None;
                    };
                    purposes.contains(purpose).then_some(*coin)
                })
                .peekable();
            declared.peek().is_some() && declared.all(|coin| coin == theirs)
        })
}

/// The vsize the **signed** transaction will have, in vbytes (`04-screens.md` §11.2.1).
///
/// The sum is in weight units — the base size at ×4 plus each input's own signing data at its
/// own weight — and divides **once**, `vsize = ceil(weight / 4)` as BIP-141 defines it, never
/// rounding per input. Every signature element charged is the smaller of the two its family
/// produces, so the rate this feeds is never lower than what will be paid.
fn predicted_vsize(unsigned: &Transaction, spends: &[Spend]) -> NonZeroU64 {
    let base: usize = unsigned.base_size()
        + spends
            .iter()
            .map(|spend| spend.script.script_sig_growth())
            .sum::<usize>();

    // No input with a witness means no marker, no flag and no witness section at all: the
    // signed transaction is a legacy one and weighs four units per byte.
    let witness: usize = if spends.iter().any(|spend| spend.script.is_segwit()) {
        SEGWIT_MARKER_AND_FLAG
            + spends
                .iter()
                .map(|spend| spend.script.witness_size())
                .sum::<usize>()
    } else {
        0
    };

    let weight = 4 * base as u64 + witness as u64;
    NonZeroU64::new(weight.div_ceil(4)).expect("a transaction has a size")
}

/// The output an input spends, established from the previous transaction rather than asserted.
///
/// **Stricter than Krux on purpose** (§7): every non-taproot input must carry the full previous
/// transaction, which deletes the whole BIP-143 amount-spoofing class rather than its two
/// published instances. Taproot is exempt because BIP-341 commits to all input amounts and
/// `scriptPubKey`s, so a lie there invalidates the signature.
///
/// When both fields are present the previous transaction wins — it is the one that hashes.
fn spent_output(input: &Input, outpoint: OutPoint, index: usize) -> Result<&TxOut, Refusal> {
    if let Some(previous) = &input.non_witness_utxo {
        if previous.compute_txid() != outpoint.txid {
            return Err(Refusal::PreviousTransactionMismatch { input: index });
        }
        return previous
            .output
            .get(outpoint.vout as usize)
            .ok_or(Refusal::PreviousOutputMissing { input: index });
    }

    match &input.witness_utxo {
        Some(utxo) if utxo.script_pubkey.is_p2tr() => Ok(utxo),
        _ => Err(Refusal::PreviousTransactionAbsent { input: index }),
    }
}

/// Which of the four script types this input spends, or `None` — which is `AOBS-R05`.
///
/// P2SH is the only arm that needs a second field: `P2SH-P2WPKH` is indistinguishable from
/// any other P2SH by its `scriptPubKey`, so the redeem script must be present, must hash to
/// that `scriptPubKey`, and must itself be a P2WPKH. A P2SH-wrapped multisig fails the last
/// of those, which is where Krux's mixed-type refusal is unnecessary: we ask the question
/// directly.
fn classify(spk: &Script, input: &Input) -> Option<InputScript> {
    if spk.is_p2pkh() {
        return Some(InputScript::P2pkh);
    }
    if spk.is_p2wpkh() {
        return Some(InputScript::P2wpkh);
    }
    if spk.is_p2tr() {
        // BIP86 is the key path and nothing else. A merkle root or a control block means the
        // spend goes through a script we do not model, whatever the internal key says.
        //
        // **And the key path has to be declared in full**
        // ([#82](https://github.com/allisson/aobs/issues/82),
        // [#113](https://github.com/allisson/aobs/issues/113)). BIP-371 makes
        // `PSBT_IN_TAP_INTERNAL_KEY` the field that says *this is a key-path spend* and an empty
        // leaf-hash list the mark of the internal key in `tap_key_origins`, so a declaration is
        // complete only when both are there: the field, and an origin entry keyed by it carrying
        // no leaf hashes. An input missing either has not declared the script type this arm is
        // about — which is what `AOBS-R05` asks, and why this is that refusal rather than a new
        // one. It is also what makes `crate::sign` total over everything this function accepts:
        // the dependency signs a taproot key path out of exactly that entry, so accepting an
        // input without one would mean accepting one we cannot sign, and a PSBT would leave the
        // appliance looking signed and carrying nothing.
        return (input.tap_merkle_root.is_none()
            && input.tap_scripts.is_empty()
            && taproot_key_path_claim(input).is_some())
        .then_some(InputScript::P2tr);
    }
    if spk.is_p2sh() {
        let redeem = input.redeem_script.as_ref()?;
        if ScriptBuf::new_p2sh(&redeem.script_hash()).as_script() != spk {
            return None;
        }
        return redeem.is_p2wpkh().then_some(InputScript::P2shP2wpkh);
    }
    None
}

/// Whether this input arrived carrying a signature — the whole of what
/// [`Refusal::InputAlreadySigned`] asks, where the five fields and the reason they are five are
/// argued.
///
/// It is a function rather than a line because [`crate::sign`] reads it as well, as the *arrived
/// unsigned* half of its delta assertion: the negation of this refusal is what makes that
/// assertion sayable, so the two must be the same predicate and not two lists to keep in step.
pub(crate) fn arrived_signed(input: &Input) -> bool {
    !input.partial_sigs.is_empty()
        || input.tap_key_sig.is_some()
        || !input.tap_script_sigs.is_empty()
        || input.final_script_sig.is_some()
        || input.final_script_witness.is_some()
}

/// Whether this input's sighash commits to the whole transaction.
///
/// Absent is accepted: BIP-174 leaves the field optional and its absence means the signer
/// chooses, which for us is always `SIGHASH_ALL`. Present, it must be `SIGHASH_ALL` — or, on
/// taproot, `SIGHASH_DEFAULT`, which commits to the same thing in fewer bytes. `ANYONECANPAY`
/// and the non-standard values fail the dependency's own parse and land here as `false`.
fn sighash_commits_to_everything(input: &Input, script: InputScript) -> bool {
    let Some(declared) = input.sighash_type else {
        return true;
    };
    if script == InputScript::P2tr {
        matches!(
            declared.taproot_hash_ty(),
            Ok(TapSighashType::Default | TapSighashType::All)
        )
    } else {
        matches!(declared.ecdsa_hash_ty(), Ok(EcdsaSighashType::All))
    }
}

/// Whether this `scriptPubKey` has an address form at all — `AOBS-R07` is the *no*.
///
/// **The answer does not depend on the network**: the only thing a network selects is the HRP
/// or the version byte of an address that exists either way, and a test asserts the two agree
/// on every script the suite carries. That is also why there is no OP_RETURN carve-out — §7
/// keeps the simpler rule, and an OP_RETURN is refused by this one.
fn renderable(spk: &Script) -> bool {
    Address::from_script(spk, bitcoin::Network::Bitcoin).is_ok()
}

#[cfg(test)]
#[path = "psbt_tests.rs"]
mod tests;
