"""The UR codec: emit parameters, the fountain round trip, and the descriptor export.

Property-based testing here is round-trips only, and deliberately so: every real failure across
Krux, SeedSigner and Specter-DIY was plumbing rather than cryptography.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from urtypes.crypto import Output

from aobs.core.constants import (
    QR_ECC_ANIMATED,
    QR_ECC_STATIC,
    UR_FRAGMENT_LADDER,
    UR_FRAME_RATE_LADDER,
)
from aobs.core.descriptor import output_descriptor_ur
from aobs.core.urcodec import (
    ACCEPTED_PSBT_UR_TYPES,
    PSBT_UR_TYPE,
    PsbtCollector,
    PsbtStream,
    URError,
    decode_psbt_parts,
    emit_parameters,
)
from aobs.core.vendor.ur2.ur_decoder import URDecoder
from aobs.core.wallet import Network, ScriptType, Wallet

CORPUS = Path(__file__).parent.parent / "fixtures" / "psbt"
VECTOR_MNEMONIC = (
    "abandon abandon abandon abandon abandon abandon abandon abandon "
    "abandon abandon abandon about"
)


# --- What we emit --------------------------------------------------------------------------------


def test_the_stream_is_crypto_psbt_and_never_ur_psbt() -> None:
    stream = PsbtStream((CORPUS / "honest_p2wpkh.psbt").read_bytes())
    for part in stream.cycle():
        assert part.startswith("UR:CRYPTO-PSBT/")
    assert PSBT_UR_TYPE == "crypto-psbt"


def test_parts_are_uppercased_for_alphanumeric_mode() -> None:
    stream = PsbtStream((CORPUS / "honest_p2tr.psbt").read_bytes())
    part = stream.next_part()
    assert part == part.upper()
    # `-`, `/` and `:` are the only non-alphanumeric characters a UR part contains, and the QR
    # alphanumeric charset has all three.
    assert set(part) <= set("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ $%*+-./:")


def test_the_ladder_and_its_frame_rates_are_the_documented_ones() -> None:
    assert UR_FRAGMENT_LADDER == (340, 200, 120, 50)
    assert UR_FRAME_RATE_LADDER == (2, 2, 1, 1)
    assert emit_parameters(0).fragment_bytes == 340
    assert emit_parameters(0).frame_rate == 2
    assert emit_parameters(3).frame_rate == 1
    assert emit_parameters(3).is_last_rung
    with pytest.raises(ValueError):
        emit_parameters(4)


def test_stepping_down_shrinks_the_fragment_and_stops_at_the_bottom() -> None:
    stream = PsbtStream((CORPUS / "many_inputs.psbt").read_bytes())
    rungs = [stream.parameters.fragment_bytes]
    for _ in range(5):
        stream = stream.stepped_down()
        rungs.append(stream.parameters.fragment_bytes)
    assert rungs == [340, 200, 120, 50, 50, 50]


def test_ecc_is_l_for_the_animation_and_h_for_anything_static() -> None:
    assert QR_ECC_ANIMATED == "L"
    assert QR_ECC_STATIC == "H"


def test_the_frame_count_is_always_available() -> None:
    """*"Frame 2 of 3"* is on screen for every scan, which is why no long-scan warning exists."""
    stream = PsbtStream((CORPUS / "many_inputs.psbt").read_bytes())
    assert stream.seq_len == 10
    assert stream.cycles_completed == 0
    stream.cycle()
    assert stream.cycles_completed == 1


def test_a_bip86_psbt_is_three_frames_not_fifteen() -> None:
    """`docs/qr-emit-parameters.md`'s worked example: a ~700-byte PSBT at 340 payload bytes."""
    psbt_bytes = ((CORPUS / "honest_p2tr.psbt").read_bytes() * 3)[:702]
    assert len(psbt_bytes) == 702
    assert PsbtStream(psbt_bytes).seq_len == 3


# --- Round trips ----------------------------------------------------------------------------------


@settings(max_examples=40, deadline=None)
@given(
    payload=st.binary(min_size=1, max_size=2000),
    rung=st.integers(min_value=0, max_value=3),
)
def test_the_fountain_round_trips(payload: bytes, rung: int) -> None:
    stream = PsbtStream(payload, rung=rung)
    assert decode_psbt_parts(list(stream.cycle())) == payload


@settings(max_examples=20, deadline=None)
@given(payload=st.binary(min_size=400, max_size=1500), skip=st.integers(0, 5))
def test_the_fountain_round_trips_from_a_late_start(payload: bytes, skip: int) -> None:
    stream = PsbtStream(payload)
    for _ in range(skip):
        stream.next_part()
    collector = PsbtCollector()
    for _ in range(stream.seq_len * 6):
        if collector.receive(stream.next_part()):
            break
    assert collector.result() == payload


def test_ur_psbt_is_accepted_inbound_even_though_it_is_never_emitted() -> None:
    """Our output rule must not become an interop refusal."""
    assert ACCEPTED_PSBT_UR_TYPES == ("crypto-psbt", "psbt")
    payload = (CORPUS / "honest_p2wpkh.psbt").read_bytes()
    parts = [
        part.replace("UR:CRYPTO-PSBT/", "UR:PSBT/") for part in PsbtStream(payload).cycle()
    ]
    assert decode_psbt_parts(parts) == payload


def test_a_foreign_ur_is_rejected_rather_than_absorbed() -> None:
    collector = PsbtCollector()
    with pytest.raises(URError):
        collector.receive("UR:CRYPTO-SEED/OEADGDSTASLPLABGINAEAEAEAEAEAEAEAEAEAEAEAEAEAEAEAEAEAEAEAE")
    with pytest.raises(URError):
        collector.receive("not a ur at all")


# --- The descriptor export ---------------------------------------------------------------------------


@pytest.fixture
def wallet() -> Wallet:
    return Wallet.from_mnemonic(VECTOR_MNEMONIC, network=Network.MAINNET)


@pytest.mark.parametrize("script_type", list(ScriptType))
def test_the_descriptor_ur_decodes_to_our_own_descriptor(
    wallet: Wallet, script_type: ScriptType
) -> None:
    """Decoded by `urtypes`, which is not our code: the CBOR is checked against an independent
    implementation of the registry rather than against our own encoder."""
    ur = output_descriptor_ur(wallet, script_type)
    assert ur.startswith("UR:CRYPTO-OUTPUT/")
    decoded = Output.from_cbor(URDecoder.decode(ur.lower()).cbor)
    # BIP380 admits both hardened markers; the two strings are the same descriptor.
    assert decoded.descriptor(include_checksum=False).replace("'", "h") == (
        wallet.descriptor(script_type).split("#")[0]
    )


def test_bip84_and_bip86_are_separate_urs(wallet: Wallet) -> None:
    """Green rejects a `crypto-account` containing taproot *whole*, BIP84 descriptor included."""
    wpkh = output_descriptor_ur(wallet, ScriptType.P2WPKH)
    tr = output_descriptor_ur(wallet, ScriptType.P2TR)
    assert wpkh != tr
    for ur in (wpkh, tr):
        # Single-part: a static descriptor is one QR, and a part header would say `1-2`.
        assert ur.count("/") == 1


def test_the_descriptor_ur_carries_origin_and_fingerprint_and_no_name(wallet: Wallet) -> None:
    decoded = Output.from_cbor(
        URDecoder.decode(output_descriptor_ur(wallet, ScriptType.P2WPKH).lower()).cbor
    )
    hd_key = decoded.hd_key()
    assert hd_key.origin.source_fingerprint == wallet.fingerprint
    assert hd_key.origin.path() == "84'/0'/0'"
    assert hd_key.name is None


def test_the_descriptor_ur_states_the_network(wallet: Wallet) -> None:
    signet = Wallet.from_mnemonic(VECTOR_MNEMONIC, network=Network.SIGNET)
    mainnet_key = Output.from_cbor(
        URDecoder.decode(output_descriptor_ur(wallet, ScriptType.P2WPKH).lower()).cbor
    ).hd_key()
    signet_key = Output.from_cbor(
        URDecoder.decode(output_descriptor_ur(signet, ScriptType.P2WPKH).lower()).cbor
    ).hd_key()
    assert mainnet_key.use_info.network == 0
    # The registry has one "testnet", and nothing in any export distinguishes testnet4, signet
    # and regtest anyway: the network is receiver-side configuration.
    assert signet_key.use_info.network == 1
