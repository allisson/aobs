"""The adversarial corpus: the Tier 1 defence, executable.

One file per attack in `fixtures/psbt/`, each with the verdict declared beside it by
`fixtures/generate.py`. This module reads whatever is there — a new refusal rule is added by
adding a fixture, not by editing a test.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from aobs.core.review import OutputCategory, Review, review
from aobs.core.text import is_inert
from aobs.core.wallet import Network, Wallet

CORPUS = Path(__file__).parent.parent / "fixtures" / "psbt"

VECTOR_MNEMONIC = (
    "abandon abandon abandon abandon abandon abandon abandon abandon "
    "abandon abandon abandon about"
)


def _cases() -> list[Path]:
    cases = sorted(CORPUS.glob("*.json"))
    assert cases, "the corpus is empty: run `uv run python fixtures/generate.py`"
    return cases


def _review_of(meta: dict) -> Review:
    psbt_bytes = (CORPUS / f"{meta['name']}.psbt").read_bytes()
    wallet = Wallet.from_mnemonic(VECTOR_MNEMONIC, network=Network(meta["network"]))
    return review(psbt_bytes, wallet)


@pytest.fixture(params=_cases(), ids=lambda p: p.stem)
def case(request) -> dict:
    return json.loads(request.param.read_text())


def test_case_meets_its_declared_verdict(case: dict) -> None:
    expected = case["expected"]
    result = _review_of(case)

    declared_refusal = expected["refusal"]
    if declared_refusal is None:
        assert result.refusal is None, f"{case['name']} was refused: {result.refusal}"
        assert result.signable
    else:
        assert result.refusal is not None, f"{case['name']} was not refused"
        assert result.refusal.reason.value == declared_refusal["reason"]
        assert result.refusal.input_index == declared_refusal.get("input_index")
        assert not result.signable
        # A refusal carries no override and no alternate entry point: `signable` is the whole
        # interface, and there is nothing else to call.
        return

    for declared in expected.get("outputs", []):
        out = result.outputs[declared["index"]]
        assert out.category.value == declared["category"]
        assert out.amount_sats == declared["sats"]
        if "proven_path" in declared:
            assert out.proven is not None
            assert out.proven.path == declared["proven_path"]
        else:
            assert out.proven is None
        if "claimed_path" in declared:
            assert out.claimed_path == declared["claimed_path"]

    if "headline" in expected:
        declared = expected["headline"]
        assert result.headline is not None
        assert result.headline.payments_sats == declared["payments_sats"]
        assert result.headline.fee_sats == declared["fee_sats"]
        assert result.headline.total_leaving_sats == declared["total_leaving_sats"]

    for index, codes in expected.get("output_warnings", {}).items():
        actual = {w.code.value for w in result.warnings_for_output(int(index))}
        assert actual == set(codes)

    if "transaction_warnings" in expected:
        actual = {w.code.value for w in result.transaction_warnings}
        assert actual == set(expected["transaction_warnings"])

    if expected.get("no_control_characters"):
        assert is_inert(_all_text(result))


def _all_text(result: Review) -> str:
    parts = [result.network, result.fingerprint_hex]
    for out in result.outputs:
        parts += [out.address or "", out.script_pubkey_hex, out.claimed_path or ""]
    for inp in result.inputs:
        parts += [inp.txid, inp.proven.path if inp.proven else ""]
    return " ".join(parts)


# --- The two properties the corpus exists to hold ------------------------------------------------


def test_not_proven_never_rounds_to_change() -> None:
    """Collapsing three categories into two is the change-address attack. Structurally
    impossible: NOT PROVEN is leaving, everywhere."""
    for path in _cases():
        meta = json.loads(path.read_text())
        result = _review_of(meta)
        for out in result.outputs:
            if out.category is OutputCategory.NOT_PROVEN:
                assert out.is_leaving
                assert out.proven is None


def test_the_change_address_attack_raises_the_headline_number() -> None:
    """The figure the user is most likely to read is the one the attack moves."""
    attack = json.loads((CORPUS / "change_address_attack.json").read_text())
    result = _review_of(attack)
    fake_change = result.outputs[1]

    assert fake_change.category is OutputCategory.NOT_PROVEN
    assert fake_change.claimed_path == "m/84h/1h/0h/1/0"
    assert result.headline is not None
    # Had the claim been believed, the headline would have been the 200 000 sat payment plus the
    # fee. It is not: the fake change is in it.
    assert result.headline.payments_sats == 1_195_000
    assert result.headline.total_leaving_sats > 205_000
