"""Entropy mixing: the floor claim as a property, plus fixed adversarial vectors.

`docs/entropy-mixing.md` puts the real verification here rather than on screen: anything the
appliance displays about its own mixing is a claim by the same code that would be lying.
"""

from __future__ import annotations

import hashlib
import hmac

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from aobs.core.constants import ENTROPY_HKDF_INFO, ENTROPY_HKDF_SALT
from aobs.core.entropy import SourceLabel, mix

STUB_SYSTEM = bytes(range(32))
ZERO_FRAME = bytes(64)
CONSTANT_DICE = "1" * 99


# --- An independent implementation of the construction, from the document ----------------------
#
# Written from `docs/entropy-mixing.md` with hashlib and hmac only, so the vectors below are
# checked against the construction rather than against the same code that produced them.


def _hkdf(ikm: bytes, length: int = 32) -> bytes:
    prk = hmac.new(ENTROPY_HKDF_SALT, ikm, hashlib.sha256).digest()
    out, block, counter = b"", b"", 1
    while len(out) < length:
        block = hmac.new(
            prk, block + ENTROPY_HKDF_INFO + bytes([counter]), hashlib.sha256
        ).digest()
        out += block
        counter += 1
    return out[:length]


def _framed(label: str, payload: bytes) -> bytes:
    raw = label.encode("ascii")
    return bytes([len(raw)]) + raw + len(payload).to_bytes(4, "big") + payload


def _expected(system: bytes, frames: tuple[bytes, ...] = (), dice: str = "") -> bytes:
    ikm = _framed("system", system)
    if frames:
        ikm += _framed("camera", b"".join(hashlib.sha256(f).digest() for f in frames))
    if dice:
        ikm += _framed("dice", dice.encode("ascii"))
    return _hkdf(ikm)


# --- Fixed adversarial vectors -----------------------------------------------------------------


def test_system_only_vector() -> None:
    assert mix(STUB_SYSTEM).value == _expected(STUB_SYSTEM)


def test_all_zero_camera_and_constant_dice_vector() -> None:
    result = mix(STUB_SYSTEM, camera_frames=(ZERO_FRAME,) * 8, dice_rolls=CONSTANT_DICE)
    assert result.value == _expected(STUB_SYSTEM, (ZERO_FRAME,) * 8, CONSTANT_DICE)
    assert result.camera_constant is True


def test_the_vectors_are_pinned() -> None:
    """The same two vectors as literals, so a change to the construction is visible in the diff
    and not only in a helper that changed alongside it."""
    assert mix(STUB_SYSTEM).value.hex() == (
        "8eb75f6902f6f32d926c099484eb5c6012502f8a00766225cc341df5bdcd0ba9"
    )
    assert mix(
        STUB_SYSTEM, camera_frames=(ZERO_FRAME,) * 8, dice_rolls=CONSTANT_DICE
    ).value.hex() == (
        "6b80eb701855a26a4630e77115f652ca56b6fce6c9e398f64cd53653e1d75521"
    )


# --- The floor claim, as a property ------------------------------------------------------------


@settings(max_examples=50, deadline=None)
@given(
    system=st.binary(min_size=32, max_size=32),
    other=st.binary(min_size=32, max_size=32),
)
def test_an_adversarial_constant_camera_cannot_pin_the_output(
    system: bytes, other: bytes
) -> None:
    """Feed an adversarial constant for one source; the output still varies with the others."""
    frames = (ZERO_FRAME,) * 4
    a = mix(system, camera_frames=frames).value
    b = mix(other, camera_frames=frames).value
    assert (a == b) == (system == other)


@settings(max_examples=50, deadline=None)
@given(dice=st.text(alphabet="123456", min_size=1, max_size=120))
def test_an_adversarial_constant_system_source_cannot_pin_the_output(dice: str) -> None:
    constant = b"\x00" * 32
    assert mix(constant, dice_rolls=dice).value != mix(constant, dice_rolls=dice + "6").value


@settings(max_examples=50, deadline=None)
@given(
    frames=st.lists(st.binary(min_size=1, max_size=64), min_size=1, max_size=4),
    dice=st.text(alphabet="123456", max_size=30),
)
def test_mixing_is_deterministic(frames: list[bytes], dice: str) -> None:
    first = mix(STUB_SYSTEM, camera_frames=tuple(frames), dice_rolls=dice)
    second = mix(STUB_SYSTEM, camera_frames=tuple(frames), dice_rolls=dice)
    assert first.value == second.value
    assert len(first.value) == 32


# --- The kernel CSPRNG is unconditional --------------------------------------------------------


def test_dice_cannot_substitute_for_the_kernel_csprng() -> None:
    with pytest.raises(ValueError):
        mix(b"", dice_rolls=CONSTANT_DICE)


def test_the_system_source_is_a_required_positional_argument() -> None:
    import inspect

    parameters = inspect.signature(mix).parameters
    assert parameters["system"].default is inspect.Parameter.empty
    assert parameters["system"].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    # Everything else is keyword-only and optional: no call shape omits the kernel.
    assert all(
        p.kind is inspect.Parameter.KEYWORD_ONLY
        for name, p in parameters.items()
        if name != "system"
    )


# --- Facts, not assurances ---------------------------------------------------------------------


def test_contributions_are_quantities_and_never_a_score() -> None:
    result = mix(STUB_SYSTEM, camera_frames=(b"\x01\x02",) * 8, dice_rolls="123456" * 3)
    quantities = {c.label: c.quantity for c in result.contributions}
    assert quantities == {
        SourceLabel.SYSTEM: 32,
        SourceLabel.CAMERA: 8,
        SourceLabel.DICE: 18,
    }
    assert result.camera_constant is False
    dice = next(c for c in result.contributions if c.label is SourceLabel.DICE)
    assert dice.dice_bits == pytest.approx(46.529, abs=1e-3)


def test_any_number_of_rolls_is_accepted() -> None:
    assert mix(STUB_SYSTEM, dice_rolls="1").value != mix(STUB_SYSTEM).value
    # Non-D6 characters are dropped rather than raising: the appliance has no quota to enforce.
    assert mix(STUB_SYSTEM, dice_rolls="1 2 3").value == mix(STUB_SYSTEM, dice_rolls="123").value


def test_entropy_never_renders_its_value() -> None:
    result = mix(STUB_SYSTEM, dice_rolls="123")
    rendered = f"{result!r} {result!s}"
    assert result.value.hex() not in rendered
    assert "256 bits" in rendered


def test_the_report_states_sources_and_the_resulting_fingerprint() -> None:
    """`docs/entropy-mixing.md`: which sources contributed and in what quantity, plus the wallet
    fingerprint. No score, no estimate, no reassuring tick."""
    from aobs.core.entropy import report
    from aobs.core.wallet import Network, Wallet

    entropy = mix(STUB_SYSTEM, camera_frames=(b"\x01\x02",) * 8, dice_rolls="123456" * 3)
    wallet = Wallet.from_entropy(entropy.value, network=Network.SIGNET)
    stated = report(entropy, wallet)

    assert stated.fingerprint_hex == wallet.fingerprint_hex
    assert [(c.label.value, c.quantity, c.unit) for c in stated.contributions] == [
        ("system", 32, "bytes"),
        ("camera", 8, "frames"),
        ("dice", 18, "rolls"),
    ]
    assert stated.camera_constant is False
    # Nothing in the report is a judgement about strength.
    fields = set(vars(stated))
    assert not fields & {"score", "strength", "bits", "estimate", "secure"}
