"""Signing: what it produces, and what it refuses to produce.

Whether a signature is *valid* is not decided here — a wrong sighash produces a perfectly
well-formed signature. That is `tests/test_regtest_e2e.py`, against a real validator.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from aobs.core.vendor.embit.psbt import PSBT

from aobs.core.review import RefusalReason, review
from aobs.core.signing import SigningRefused, sign
from aobs.core.wallet import Network, Wallet

from conftest import VECTOR_MNEMONIC

CORPUS = Path(__file__).parent.parent / "fixtures" / "psbt"


def _wallet(network: str) -> Wallet:
    return Wallet.from_mnemonic(VECTOR_MNEMONIC, network=Network(network))


def _fixture(name: str) -> tuple[bytes, Wallet]:
    meta = json.loads((CORPUS / f"{name}.json").read_text())
    return (CORPUS / f"{name}.psbt").read_bytes(), _wallet(meta["network"])


def test_every_input_of_a_segwit_spend_is_signed() -> None:
    psbt_bytes, wallet = _fixture("honest_p2wpkh")
    signed = PSBT.parse(sign(psbt_bytes, wallet))
    assert all(len(inp.partial_sigs) == 1 for inp in signed.inputs)
    # SIGHASH_ALL, on every signature, stated in the signature's own trailing byte.
    assert all(
        list(inp.partial_sigs.values())[0][-1] == 0x01 for inp in signed.inputs
    )


def test_a_taproot_key_path_spend_is_signed() -> None:
    psbt_bytes, wallet = _fixture("honest_p2tr")
    signed = PSBT.parse(sign(psbt_bytes, wallet))
    for inp in signed.inputs:
        assert inp.final_scriptwitness is not None
        # One 64-byte Schnorr signature: SIGHASH_DEFAULT, so no trailing flag byte.
        assert len(inp.final_scriptwitness.items[0]) == 64


def test_signing_leaves_the_original_bytes_alone() -> None:
    psbt_bytes, wallet = _fixture("honest_p2wpkh")
    before = bytes(psbt_bytes)
    sign(psbt_bytes, wallet)
    assert psbt_bytes == before


@pytest.mark.parametrize(
    ("fixture", "reason"),
    [
        ("taproot_missing_witness_utxo", RefusalReason.MISSING_UTXO),
        ("sighash_not_all", RefusalReason.SIGHASH_NOT_ALL),
        ("network_mismatch", RefusalReason.NETWORK_MISMATCH),
        ("foreign_input", RefusalReason.UNSIGNABLE_INPUT),
        ("malformed", RefusalReason.MALFORMED),
    ],
)
def test_every_refusal_stops_signing(fixture: str, reason: RefusalReason) -> None:
    psbt_bytes, wallet = _fixture(fixture)
    with pytest.raises(SigningRefused) as raised:
        sign(psbt_bytes, wallet)
    assert raised.value.refusal.reason is reason


def test_a_refusal_never_carries_key_material() -> None:
    psbt_bytes, wallet = _fixture("foreign_input")
    with pytest.raises(SigningRefused) as raised:
        sign(psbt_bytes, wallet)
    message = str(raised.value)
    assert wallet.root.to_base58() not in message
    assert message == "refused: unsignable_input"


def test_a_not_proven_output_does_not_block_signing() -> None:
    """The change-address attack is a warning and a bigger headline number, not a refusal: the
    user must still be able to send money to a stranger."""
    psbt_bytes, wallet = _fixture("change_address_attack")
    assert review(psbt_bytes, wallet).signable
    signed = PSBT.parse(sign(psbt_bytes, wallet))
    assert len(signed.inputs[0].partial_sigs) == 1
