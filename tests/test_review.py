"""Review-model behaviour the corpus does not state as a per-fixture verdict.

The corpus asserts what each attack must produce. This module asserts the rules that hold across
all of them: what proves an input, what the window is for, what the core hands a screen.
"""

from __future__ import annotations

import json

import pytest
from aobs.core.vendor.embit.psbt import PSBT

from aobs.core.constants import CHANGE_WINDOW_CEILING, CHANGE_WINDOW_LOOKAHEAD
from aobs.core.review import OutputCategory, RefusalReason, review
from aobs.core.signing import sign
from aobs.core.text import is_inert
from aobs.core.wallet import Network, ScriptType, Wallet

from conftest import CORPUS, VECTOR_MNEMONIC


def _review(name: str, network: Network = Network.SIGNET):
    wallet = Wallet.from_mnemonic(VECTOR_MNEMONIC, network=network)
    return review((CORPUS / f"{name}.psbt").read_bytes(), wallet), wallet


# --- What proves an input ----------------------------------------------------------------------


def test_an_input_past_the_windows_ceiling_is_still_ours() -> None:
    """The window bounds what may be believed to be *change*. An input whose script we reproduce
    is one we can spend, and refusing it would be a hard refusal on an honest transaction."""
    result, wallet = _review("input_past_the_ceiling")
    assert result.signable
    proven = result.inputs[0].proven
    assert proven is not None and proven.index == 500 > CHANGE_WINDOW_CEILING
    assert proven.path == "m/84h/1h/0h/0/500"
    # And it signs, which is the point of recognising it.
    assert sign((CORPUS / "input_past_the_ceiling.psbt").read_bytes(), wallet)


def test_a_claimed_input_path_is_still_only_input_to_a_check() -> None:
    """The claim on that input names index 500. Change the script it points at and the claim
    stops proving anything — which is the same rule outputs are held to."""
    psbt = PSBT.parse((CORPUS / "input_past_the_ceiling.psbt").read_bytes())
    stranger = Wallet.from_mnemonic(
        "legal winner thank year wave sausage worth useful legal winner thank yellow",
        network=Network.SIGNET,
    )
    psbt.inputs[0].witness_utxo.script_pubkey = stranger.script_pubkey(
        ScriptType.P2WPKH, 0, 500
    )
    wallet = Wallet.from_mnemonic(VECTOR_MNEMONIC, network=Network.SIGNET)

    result = review(psbt.serialize(), wallet)
    assert result.refusal is not None
    assert result.refusal.reason is RefusalReason.UNSIGNABLE_INPUT


# --- The window --------------------------------------------------------------------------------


def test_the_window_is_stated_and_bounded_by_the_ceiling() -> None:
    result, _ = _review("honest_p2wpkh")
    # Highest proven input index is 2, so the window is 0..22 — and it is stated, so a NOT PROVEN
    # verdict can say what was searched.
    assert result.change_window == (0, 2 + CHANGE_WINDOW_LOOKAHEAD)

    far, _ = _review("input_past_the_ceiling")
    assert far.change_window == (0, CHANGE_WINDOW_CEILING)


def test_the_network_refusal_does_not_depend_on_the_attackers_fingerprint() -> None:
    result, _ = _review("network_mismatch_foreign_fingerprint")
    assert result.refusal is not None
    assert result.refusal.reason is RefusalReason.NETWORK_MISMATCH


# --- What the core hands a screen ---------------------------------------------------------------


def test_proven_change_is_marked_as_needing_no_eye_check() -> None:
    result, _ = _review("honest_p2wpkh")
    payment, change = result.outputs
    assert change.category is OutputCategory.CHANGE_PROVEN
    assert not change.address_needs_checking
    assert payment.address_needs_checking


def test_a_not_proven_output_still_needs_checking() -> None:
    result, _ = _review("change_address_attack")
    not_proven = result.outputs[1]
    assert not_proven.category is OutputCategory.NOT_PROVEN
    assert not_proven.address_needs_checking


def test_address_not_seen_before_is_not_repeated_on_a_not_proven_output() -> None:
    """It is true of every payment. Beside the warning that matters it adds nothing."""
    result, _ = _review("change_address_attack")
    codes = {w.code.value for w in result.warnings_for_output(1)}
    assert codes == {"output_not_proven"}
    assert {w.code.value for w in result.warnings_for_output(0)} == {
        "address_not_seen_before"
    }


@pytest.mark.parametrize("name", sorted(p.stem for p in CORPUS.glob("*.psbt")))
def test_every_string_the_core_hands_out_is_inert(name: str) -> None:
    """Not incidentally inert — every one of them has been through `inert()`."""
    meta_network = Network(json.loads((CORPUS / f"{name}.json").read_text())["network"])
    result, _ = _review(name, meta_network)
    for out in result.outputs:
        assert is_inert(out.address or "")
        assert is_inert(out.script_pubkey_hex)
        assert is_inert(out.claimed_path or "")


def test_the_fee_is_available_three_ways() -> None:
    result, _ = _review("fee_absurd")
    assert result.fee is not None
    assert result.fee.sats == 400_000
    assert result.fee.share_of_sent == pytest.approx(0.8)
    assert result.fee.sat_per_vbyte > 0
    # And the headline states its own composition rather than asserting a total.
    assert result.headline is not None
    assert (
        result.headline.payments_sats + result.headline.fee_sats
        == result.headline.total_leaving_sats
    )


def test_hostile_bytes_never_raise() -> None:
    wallet = Wallet.from_mnemonic(VECTOR_MNEMONIC, network=Network.SIGNET)
    good = (CORPUS / "honest_p2wpkh.psbt").read_bytes()
    for truncated in range(0, len(good), 17):
        assert review(good[:truncated], wallet) is not None
    for flip in range(0, len(good), 23):
        mutated = bytearray(good)
        mutated[flip] ^= 0xFF
        assert review(bytes(mutated), wallet) is not None
    assert review(b"", wallet).refusal.reason is RefusalReason.MALFORMED
