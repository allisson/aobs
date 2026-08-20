//! PSBT validation — the structural half of the rejection policy (`02-core.md` §7).
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
//! **What is here and what is not.** The seven structural refusals — `AOBS-R01`–`R05`, `R07`
//! and `R15` — need no key material, which is why they land before anything re-derives a
//! `scriptPubKey` ([#79](https://github.com/allisson/aobs/issues/79)). The derivation check
//! (`R06`, `R08`, `R09`) and the review model are
//! [#80](https://github.com/allisson/aobs/issues/80)'s, and until they land a PSBT with no
//! input of ours passes this module — including one with no inputs at all, which `R06` is what
//! refuses.
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

use bitcoin::psbt::{Error as PsbtError, Input, Psbt};
use bitcoin::sighash::{EcdsaSighashType, TapSighashType};
use bitcoin::{Address, OutPoint, Script, ScriptBuf, TxOut};

/// What the review panel holds in the 800×600 minimum canvas (`04-screens.md` §11.2), payment
/// and change counted together. A seventh output is `AOBS-R15` and not a scroll.
const MAX_OUTPUTS: usize = 6;

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
}

impl Refusal {
    /// Every variant, for the tests that hold the codes to `06-codes.md` §6.
    ///
    /// The indices are samples: nothing about a code or the shape of its copy depends on
    /// which input tripped it.
    pub const ALL: [Self; 9] = [
        Self::DuplicateKey,
        Self::PreviousTransactionAbsent { input: 0 },
        Self::PreviousTransactionMismatch { input: 0 },
        Self::PreviousOutputMissing { input: 0 },
        Self::UnsupportedSighash { input: 0 },
        Self::OutputsExceedInputs,
        Self::UnsupportedInputScript { input: 0 },
        Self::UnrenderableOutput { output: 0 },
        Self::TooManyOutputs { count: 7 },
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
        }
    }
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

/// Parse hostile bytes and run every structural check, in the registry's own order.
///
/// The returned PSBT is the parsed one, unmodified: unknown fields included, nothing
/// stripped. What it does **not** carry is any claim about whose keys the inputs are — that is
/// [#80](https://github.com/allisson/aobs/issues/80)'s.
///
/// # Errors
///
/// [`Rejection::NotAPsbt`] when the bytes never decoded, [`Rejection::Refused`] when they
/// decoded and failed a check.
pub fn validate(bytes: &[u8]) -> Result<Psbt, Rejection> {
    let psbt = parse(bytes)?;
    check(&psbt).map_err(Rejection::Refused)?;
    Ok(psbt)
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
fn check(psbt: &Psbt) -> Result<(), Refusal> {
    let outputs = &psbt.unsigned_tx.output;
    if outputs.len() > MAX_OUTPUTS {
        return Err(Refusal::TooManyOutputs {
            count: outputs.len(),
        });
    }

    // Zipped rather than indexed: `Psbt::deserialize` decodes exactly as many input maps as
    // the unsigned transaction has inputs, and zipping means no arm of this loop can panic
    // if that ever stops being true.
    let mut input_total: u128 = 0;
    for (index, (txin, input)) in psbt.unsigned_tx.input.iter().zip(&psbt.inputs).enumerate() {
        let spent = spent_output(input, txin.previous_output, index)?;
        let script = classify(&spent.script_pubkey, input)
            .ok_or(Refusal::UnsupportedInputScript { input: index })?;
        if !sighash_commits_to_everything(input, script) {
            return Err(Refusal::UnsupportedSighash { input: index });
        }
        input_total += u128::from(spent.value.to_sat());
    }

    // `u128` because both sums are attacker-supplied `u64`s and a wrapping add would turn
    // "pays out more than it holds" into "pays out nothing". No policy about `MAX_MONEY`
    // here: the comparison is the refusal §7 names, and nothing else.
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

    Ok(())
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
        return (input.tap_merkle_root.is_none() && input.tap_scripts.is_empty())
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
