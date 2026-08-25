"""Signing.

`sign(psbt_bytes, wallet) -> bytes`. There is exactly one entry point, it reviews first, and it
refuses by raising — there is no parameter, flag or alternate path that proceeds past a refusal
(`docs/psbt-review-model.md`).

Every key used here is derived by this appliance from its own seed at a path it reproduced from
the input's script. A `PSBT_IN_BIP32_DERIVATION` field is never what decides which key signs.
"""

from __future__ import annotations

from embit.psbt import SIGHASH, PSBT

from .review import Refusal, RefusalReason, Review, review
from .wallet import ScriptType, Wallet


class SigningRefused(Exception):
    """Raised instead of signing. Carries the typed reason and nothing else — no bytes, no key
    material, no path (`docs/secret-hygiene.md`: nothing renders a secret, exceptions included).
    """

    def __init__(self, refusal: Refusal) -> None:
        self.refusal = refusal
        super().__init__(f"refused: {refusal.reason.value}")


def sign(psbt_bytes: bytes, wallet: Wallet) -> bytes:
    """Sign every input of a reviewed PSBT, or refuse the whole transaction.

    Returns the serialised PSBT with our signatures added. Never partially signed: an input the
    appliance cannot sign is a refusal, checked before anything is signed.
    """
    reviewed = review(psbt_bytes, wallet)
    if reviewed.refusal is not None:
        raise SigningRefused(reviewed.refusal)
    return sign_reviewed(psbt_bytes, wallet, reviewed)


def sign_reviewed(psbt_bytes: bytes, wallet: Wallet, reviewed: Review) -> bytes:
    """Sign a PSBT the caller has already reviewed — the same act, without reviewing twice.

    The review is re-checked here rather than trusted: a caller cannot hand in a `Review` that
    says yes about different bytes, because every signature still comes from a path this function
    re-derives against this PSBT's own scripts.
    """
    if reviewed.refusal is not None:
        raise SigningRefused(reviewed.refusal)
    psbt = PSBT.parse(psbt_bytes)
    signed = 0
    for i, inp in enumerate(psbt.inputs):
        proven = reviewed.inputs[i].proven
        if proven is None or inp.utxo is None:
            raise SigningRefused(Refusal(RefusalReason.UNSIGNABLE_INPUT, input_index=i))
        key = wallet.derive(proven.script_type, proven.chain, proven.index)
        # The proof, restated at the moment of signing: the key we are about to use reproduces
        # this input's own script.
        if wallet.script_pubkey(
            proven.script_type, proven.chain, proven.index
        ).data != inp.utxo.script_pubkey.data:
            raise SigningRefused(Refusal(RefusalReason.UNSIGNABLE_INPUT, input_index=i))

        if proven.script_type is ScriptType.P2TR:
            signed += psbt.sign_input_with_tapkey(key.key, i, inp, sighash=SIGHASH.DEFAULT)
        else:
            digest = psbt.sighash(i, sighash=SIGHASH.ALL)
            signature = key.key.sign(digest)
            inp.partial_sigs[key.key.get_public_key()] = signature.serialize() + bytes(
                [SIGHASH.ALL]
            )
            signed += 1

    if signed != len(psbt.inputs):
        # Cannot happen after a clean review; it is checked anyway, because "sign nothing rather
        # than partially" is the rule and a count is the only thing that can state it.
        raise SigningRefused(Refusal(RefusalReason.UNSIGNABLE_INPUT))
    return psbt.serialize()
