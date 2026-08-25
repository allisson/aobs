"""The PSBT review model: the proof rule, the three output categories, the headline number.

`review(psbt_bytes, wallet) -> Review`. Bytes in, value objects out — no I/O, no clock, no
ambient state. This is the part of the appliance where a bug loses money, and it is a pure
function of the PSBT's bytes plus the wallet's own keys.

Everything here derives from `docs/psbt-review-model.md`. Nothing here trusts a field the PSBT
asserts: a `PSBT_OUT_BIP32_DERIVATION` is input to a check and never the answer.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum

from embit.psbt import SIGHASH, PSBT

from .constants import (
    CHANGE_WINDOW_CEILING,
    CHANGE_WINDOW_LOOKAHEAD,
    FEE_WARN_SAT_PER_VBYTE,
    FEE_WARN_SHARE_OF_SENT,
)
from .wallet import CHANGE_CHAIN, RECEIVE_CHAIN, ScriptType, Wallet


class OutputCategory(str, Enum):
    """Three, never two. Collapsing them is the change-address attack."""

    PAYMENT = "payment"
    CHANGE_PROVEN = "change_proven"
    #: Claims to be ours, but we could not reproduce it. Counted as a payment for every purpose
    #: including the headline number, and never rounded to change.
    NOT_PROVEN = "not_proven"


class RefusalReason(str, Enum):
    """Refusals are typed and total: no override, no confirmation button."""

    MALFORMED = "malformed"
    NETWORK_MISMATCH = "network_mismatch"
    MISSING_UTXO = "missing_utxo"
    SIGHASH_NOT_ALL = "sighash_not_all"
    UNSIGNABLE_INPUT = "unsignable_input"


class WarningCode(str, Enum):
    """Advisory and enumerated. The user may proceed."""

    FEE_ABOVE_THRESHOLD = "fee_above_threshold"
    ADDRESS_NOT_SEEN_BEFORE = "address_not_seen_before"
    WHOLE_BALANCE_SPEND = "whole_balance_spend"
    OUTPUT_NOT_PROVEN = "output_not_proven"


class WarningScope(str, Enum):
    """Where a warning belongs on the screen: beside one output, or with the totals."""

    OUTPUT = "output"
    TRANSACTION = "transaction"


@dataclass(frozen=True)
class Refusal:
    reason: RefusalReason
    #: Which input provoked it, where one did. Never a message: wording belongs to the screens.
    input_index: int | None = None


@dataclass(frozen=True)
class Warning:
    code: WarningCode
    scope: WarningScope
    output_index: int | None = None


@dataclass(frozen=True)
class DerivedPath:
    """A path this appliance derived itself, and the proof that it matches."""

    script_type: ScriptType
    chain: int
    index: int
    path: str

    @property
    def is_change_chain(self) -> bool:
        return self.chain == CHANGE_CHAIN


@dataclass(frozen=True)
class ReviewedInput:
    index: int
    txid: str
    vout: int
    #: None when the PSBT carries no UTXO data for this input — which is a refusal.
    amount_sats: int | None
    #: The path we reproduced ourselves; None means we cannot sign it.
    proven: DerivedPath | None
    is_taproot: bool


@dataclass(frozen=True)
class ReviewedOutput:
    index: int
    amount_sats: int
    category: OutputCategory
    #: Full string, never truncated. None for a script with no address form (e.g. OP_RETURN).
    address: str | None
    script_pubkey_hex: str
    #: Set only on CHANGE_PROVEN — the appliance's own derivation, not the PSBT's claim.
    proven: DerivedPath | None = None
    #: What the PSBT claimed for this output, if anything, purely so a screen can say the claim
    #: was checked. It is never evidence.
    claimed_path: str | None = None

    @property
    def is_leaving(self) -> bool:
        return self.category is not OutputCategory.CHANGE_PROVEN


@dataclass(frozen=True)
class Headline:
    """Total leaving = outputs not proven ours, plus the fee. Composition kept visible so the
    figure is checkable rather than asserted."""

    payments_sats: int
    fee_sats: int

    @property
    def total_leaving_sats(self) -> int:
        return self.payments_sats + self.fee_sats


@dataclass(frozen=True)
class Fee:
    """The fee three ways. `docs/psbt-review-model.md`: the percentage is the form in which an
    absurd fee is obvious to a non-expert."""

    sats: int
    #: Estimated from the inputs' script types — the signed transaction does not exist yet.
    estimated_vsize: int
    #: Share of what is actually leaving, excluding the fee itself. None on a spend with no
    #: payment at all (everything proven change), where the percentage has no meaning.
    share_of_sent: float | None

    @property
    def sat_per_vbyte(self) -> float:
        return self.sats / self.estimated_vsize


@dataclass(frozen=True)
class Review:
    network: str
    fingerprint_hex: str
    refusal: Refusal | None
    inputs: tuple[ReviewedInput, ...] = ()
    outputs: tuple[ReviewedOutput, ...] = ()
    warnings: tuple[Warning, ...] = ()
    fee: Fee | None = None
    headline: Headline | None = None
    #: The window actually searched for change, as (0, last) inclusive — stated, so a NOT PROVEN
    #: verdict can say what was searched.
    change_window: tuple[int, int] = (0, 0)
    #: Total value of the inputs the appliance proved its own.
    input_total_sats: int | None = None

    @property
    def signable(self) -> bool:
        return self.refusal is None

    def warnings_for_output(self, index: int) -> tuple[Warning, ...]:
        return tuple(w for w in self.warnings if w.output_index == index)

    @property
    def transaction_warnings(self) -> tuple[Warning, ...]:
        return tuple(w for w in self.warnings if w.scope is WarningScope.TRANSACTION)


# --- Deriving our own scripts ------------------------------------------------------------------


class _OwnScripts:
    """Our own scriptPubKeys, derived on demand and cached for one review.

    The only source of truth about what is ours. Derivation is cheap — 200 P2WPKH keys in 47 ms
    (`docs/address-verification.md`) — so this is deliberately eager within its window rather
    than clever.
    """

    def __init__(self, wallet: Wallet, script_types: tuple[ScriptType, ...]) -> None:
        self._wallet = wallet
        self._script_types = script_types
        self._by_script: dict[bytes, DerivedPath] = {}
        self._filled: dict[tuple[ScriptType, int], int] = {}

    def _fill(self, upto: int) -> None:
        for script_type in self._script_types:
            for chain in (RECEIVE_CHAIN, CHANGE_CHAIN):
                done = self._filled.get((script_type, chain), -1)
                for index in range(done + 1, upto + 1):
                    data = self._wallet.script_pubkey(script_type, chain, index).data
                    self._by_script[data] = DerivedPath(
                        script_type=script_type,
                        chain=chain,
                        index=index,
                        path=self._wallet.path(script_type, chain, index),
                    )
                if upto > done:
                    self._filled[(script_type, chain)] = upto

    def find(self, script_data: bytes, upto: int) -> DerivedPath | None:
        self._fill(upto)
        hit = self._by_script.get(script_data)
        if hit is None or hit.index > upto:
            return None
        return hit


def _script_types_in(psbt: PSBT) -> tuple[ScriptType, ...]:
    """Which of our two script types the PSBT could involve, from the witness versions its own
    scripts carry. Narrowing this halves the derivation work and can never widen what proves."""
    versions: set[int] = set()
    for scope in list(psbt.inputs) + list(psbt.outputs):
        script = scope.utxo.script_pubkey if hasattr(scope, "utxo") and scope.utxo else None
        if script is None:
            script = getattr(scope, "script_pubkey", None)
        if script is None or len(script.data) < 2:
            continue
        opcode = script.data[0]
        if opcode == 0x00:
            versions.add(0)
        elif 0x51 <= opcode <= 0x60:
            versions.add(opcode - 0x50)
    found = tuple(st for st in ScriptType if st.witness_version in versions)
    return found or tuple(ScriptType)


# --- Refusal checks ------------------------------------------------------------------------------


def _claimed_derivations(psbt: PSBT, fingerprint: bytes):
    """Every derivation the PSBT claims under our master fingerprint, inputs and outputs.

    These are claims. They are read for two purposes only: to notice a network mismatch, and to
    tell a screen that a claim was checked. Neither makes them evidence.
    """
    for scope in list(psbt.inputs) + list(psbt.outputs):
        for derivation in scope.bip32_derivations.values():
            if derivation.fingerprint == fingerprint:
                yield derivation.derivation
        for _leaves, derivation in scope.taproot_bip32_derivations.values():
            if derivation.fingerprint == fingerprint:
                yield derivation.derivation


_HARDENED = 0x80000000


def _network_mismatch(psbt: PSBT, wallet: Wallet) -> bool:
    """A PSBT asking this wallet to sign under another network's coin type.

    Scripts are network-agnostic, so this is the one place the PSBT itself says which network it
    was built for: BIP84/BIP86 coin type. A testnet wallet cannot be talked into a mainnet
    signature.
    """
    ours = wallet.network.coin_type | _HARDENED
    purposes = {st.purpose | _HARDENED for st in ScriptType}
    for path in _claimed_derivations(psbt, wallet.fingerprint):
        if len(path) >= 2 and path[0] in purposes and path[1] != ours:
            return True
    return False


def _sighash_is_all(scope, is_taproot: bool) -> bool:
    """`SIGHASH_ALL` only, on every input.

    Taproot's DEFAULT (0x00) commits to exactly what ALL commits to and is the normal encoding
    for a key-path spend, so it is the same rule and not an exception to it.
    """
    declared = scope.sighash_type
    if declared is None:
        return True
    if declared == SIGHASH.ALL:
        return True
    return is_taproot and declared == SIGHASH.DEFAULT


# --- Fee and size --------------------------------------------------------------------------------

#: Witness weight units for one input, spent by this appliance. P2WPKH: items count, a 72-byte
#: signature (DER, high-S never produced, worst case), a 33-byte pubkey. P2TR key path: one
#: 64-byte Schnorr signature.
_WITNESS_WEIGHT = {ScriptType.P2WPKH: 1 + 1 + 72 + 1 + 33, ScriptType.P2TR: 1 + 1 + 64}


def _estimated_vsize(psbt: PSBT, input_types: list[ScriptType | None]) -> int:
    """Virtual size of the transaction this PSBT will become once we have signed it.

    An estimate, and named one: the signed transaction does not exist while it is being reviewed.
    """
    base = len(psbt.tx.serialize())
    witness = sum(
        _WITNESS_WEIGHT.get(script_type or ScriptType.P2WPKH, 0) for script_type in input_types
    )
    total_weight = base * 4 + witness + 2  # marker and flag
    return math.ceil(total_weight / 4)


# --- The review ----------------------------------------------------------------------------------


@dataclass
class _Draft:
    """Scratch state while a review is being built. Never leaves this module."""

    inputs: list[ReviewedInput] = field(default_factory=list)
    outputs: list[ReviewedOutput] = field(default_factory=list)
    warnings: list[Warning] = field(default_factory=list)


def review(psbt_bytes: bytes, wallet: Wallet) -> Review:
    """Review a PSBT against a wallet. Never raises on hostile bytes: a PSBT that fails to parse
    or is internally inconsistent comes back as a refusal, which is what the screens show."""
    empty = Review(
        network=wallet.network.value,
        fingerprint_hex=wallet.fingerprint_hex,
        refusal=Refusal(RefusalReason.MALFORMED),
    )
    try:
        psbt = PSBT.parse(psbt_bytes)
    except Exception:
        return empty
    if not psbt.inputs or not psbt.outputs:
        return empty
    if len(psbt.inputs) != len(psbt.tx.vin) or len(psbt.outputs) != len(psbt.tx.vout):
        return empty

    if _network_mismatch(psbt, wallet):
        return Review(
            network=wallet.network.value,
            fingerprint_hex=wallet.fingerprint_hex,
            refusal=Refusal(RefusalReason.NETWORK_MISMATCH),
        )

    own = _OwnScripts(wallet, _script_types_in(psbt))
    draft = _Draft()
    refusal: Refusal | None = None

    # --- inputs. Ours is decided by reproducing the script, exactly as it is for outputs.
    any_taproot = any(inp.utxo is not None and inp.is_taproot for inp in psbt.inputs)
    input_types: list[ScriptType | None] = []
    input_total = 0
    utxo_known = True
    for i, inp in enumerate(psbt.inputs):
        utxo = inp.utxo
        # Taproot needs every input's witness_utxo, not only the one being signed: the sighash
        # commits to all input amounts and scripts. One rule, two reasons.
        missing = utxo is None or (any_taproot and inp.witness_utxo is None)
        proven = None if missing else own.find(utxo.script_pubkey.data, CHANGE_WINDOW_CEILING)
        script_type = proven.script_type if proven else None
        input_types.append(script_type)
        if missing:
            utxo_known = False
            if refusal is None:
                refusal = Refusal(RefusalReason.MISSING_UTXO, input_index=i)
        else:
            input_total += utxo.value
            if not _sighash_is_all(inp, inp.is_taproot) and refusal is None:
                refusal = Refusal(RefusalReason.SIGHASH_NOT_ALL, input_index=i)
            elif proven is None and refusal is None:
                refusal = Refusal(RefusalReason.UNSIGNABLE_INPUT, input_index=i)
        draft.inputs.append(
            ReviewedInput(
                index=i,
                txid=bytes(reversed(inp.txid)).hex() if inp.txid else "",
                vout=inp.vout if inp.vout is not None else 0,
                amount_sats=None if missing else utxo.value,
                proven=proven,
                is_taproot=bool(utxo is not None and inp.is_taproot),
            )
        )

    # --- the derivation window, from what we proved rather than from what was claimed.
    highest = max((i.proven.index for i in draft.inputs if i.proven), default=-1)
    window_last = min(CHANGE_WINDOW_CEILING, highest + CHANGE_WINDOW_LOOKAHEAD)

    # --- outputs. Change only where the script reproduces from our own key inside the window.
    payments_sats = 0
    change_sats = 0
    for i, out in enumerate(psbt.outputs):
        script = out.script_pubkey
        proven = own.find(script.data, window_last)
        claimed = _claimed_path(out, wallet)
        if proven is not None:
            category = OutputCategory.CHANGE_PROVEN
        elif claimed is not None:
            # It claims to be ours and we could not reproduce it — the change-address attack, or
            # an index past the window. Either way: a payment, warned about, never change.
            category = OutputCategory.NOT_PROVEN
        else:
            category = OutputCategory.PAYMENT
        try:
            address = script.address(wallet.network.embit)
        except Exception:
            address = None
        draft.outputs.append(
            ReviewedOutput(
                index=i,
                amount_sats=out.value,
                category=category,
                address=address,
                script_pubkey_hex=script.data.hex(),
                proven=proven,
                claimed_path=claimed,
            )
        )
        if category is OutputCategory.CHANGE_PROVEN:
            change_sats += out.value
        else:
            payments_sats += out.value
        if category is OutputCategory.NOT_PROVEN:
            draft.warnings.append(
                Warning(WarningCode.OUTPUT_NOT_PROVEN, WarningScope.OUTPUT, output_index=i)
            )
        if category is not OutputCategory.CHANGE_PROVEN:
            draft.warnings.append(
                Warning(
                    WarningCode.ADDRESS_NOT_SEEN_BEFORE, WarningScope.OUTPUT, output_index=i
                )
            )

    fee: Fee | None = None
    headline: Headline | None = None
    if utxo_known:
        fee_sats = input_total - (payments_sats + change_sats)
        if fee_sats < 0:
            # Outputs exceed inputs: internally inconsistent, and a dead end rather than a guess.
            return empty
        share = (fee_sats / payments_sats) if payments_sats else None
        fee = Fee(
            sats=fee_sats,
            estimated_vsize=_estimated_vsize(psbt, input_types),
            share_of_sent=share,
        )
        headline = Headline(payments_sats=payments_sats, fee_sats=fee_sats)
        if (share is not None and share > FEE_WARN_SHARE_OF_SENT) or (
            fee.sat_per_vbyte > FEE_WARN_SAT_PER_VBYTE
        ):
            draft.warnings.append(
                Warning(WarningCode.FEE_ABOVE_THRESHOLD, WarningScope.TRANSACTION)
            )
        if change_sats == 0:
            draft.warnings.append(
                Warning(WarningCode.WHOLE_BALANCE_SPEND, WarningScope.TRANSACTION)
            )

    return Review(
        network=wallet.network.value,
        fingerprint_hex=wallet.fingerprint_hex,
        refusal=refusal,
        inputs=tuple(draft.inputs),
        outputs=tuple(draft.outputs),
        warnings=tuple(draft.warnings),
        fee=fee,
        headline=headline,
        change_window=(0, window_last),
        input_total_sats=input_total if utxo_known else None,
    )


def _claimed_path(out, wallet: Wallet) -> str | None:
    """The path this output claims under our fingerprint, as text, or None.

    Read so a screen can say *the claim was checked and did not hold*. It is never the answer to
    whether the output is ours.
    """
    for derivation in out.bip32_derivations.values():
        if derivation.fingerprint == wallet.fingerprint:
            return _path_text(derivation.derivation)
    for _leaves, derivation in out.taproot_bip32_derivations.values():
        if derivation.fingerprint == wallet.fingerprint:
            return _path_text(derivation.derivation)
    return None


def _path_text(path) -> str:
    parts = ["m"]
    for element in path:
        if element >= _HARDENED:
            parts.append(f"{element - _HARDENED}h")
        else:
            parts.append(str(element))
    return "/".join(parts)
