"""Entropy mixing: system bytes, camera frames and dice rolls into 256 bits.

`mix(system, camera_frames=..., dice_rolls=...) -> Entropy`.

The claim being met is `docs/threat-model.md`'s: the final 256 bits are no weaker than the
strongest single contributing source, and no single source can drag them down. Three shapes
carry it, and all three are structural rather than promised:

* The kernel CSPRNG is a **required argument**. There is no reachable path in which dice
  substitute for it — that is the whole trap this construction closes.
* Sources are framed as `label ‖ length ‖ bytes`, so no source can impersonate another's framing
  or shift a boundary. XOR is disqualified: an adversary controlling one input cancels the rest.
* There is **no entropy estimator anywhere**. Krux's one memory-safety failure was a heap
  overflow inside one, so this design does not have one to harden.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import Enum

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from .constants import (
    DICE_BITS_PER_ROLL,
    ENTROPY_HKDF_INFO,
    ENTROPY_HKDF_SALT,
    ENTROPY_OUTPUT_BYTES,
)


class SourceLabel(str, Enum):
    """Domain separation labels. Their bytes are part of the construction, so changing one
    changes every seed this appliance would derive from the same inputs."""

    SYSTEM = "system"
    CAMERA = "camera"
    DICE = "dice"


@dataclass(frozen=True)
class Contribution:
    """What a source contributed, as a fact. Never a score, never an estimate, never a tick."""

    label: SourceLabel
    #: Bytes for the system source, frames for the camera, rolls for the dice.
    quantity: int
    unit: str

    @property
    def dice_bits(self) -> float | None:
        """log2(6) per roll — stated so the user can read it, never as a quota to fill."""
        if self.label is not SourceLabel.DICE:
            return None
        return self.quantity * DICE_BITS_PER_ROLL


@dataclass(frozen=True)
class Entropy:
    """256 bits and an honest account of where they came from."""

    value: bytes
    contributions: tuple[Contribution, ...]
    #: True when every camera frame handed in was constant. A sanity check on the *hardware*:
    #: it cannot move the floor, because the contribution stays additive either way.
    camera_constant: bool = False

    def __repr__(self) -> str:  # pragma: no cover - trivial, but load-bearing
        sources = ", ".join(f"{c.label.value}:{c.quantity}" for c in self.contributions)
        return f"<Entropy {len(self.value) * 8} bits from {sources}>"

    __str__ = __repr__


def _framed(label: SourceLabel, payload: bytes) -> bytes:
    """`label ‖ length ‖ bytes`, with the label's own length prefixed too, so no concatenation of
    parts can be read as a different one."""
    raw = label.value.encode("ascii")
    return (
        len(raw).to_bytes(1, "big") + raw + len(payload).to_bytes(4, "big") + payload
    )


def mix(
    system: bytes,
    *,
    camera_frames: tuple[bytes, ...] = (),
    dice_rolls: str = "",
) -> Entropy:
    """Mix the sources into 256 bits of BIP39 entropy.

    `system` is the kernel CSPRNG's output and is not optional: an empty value is a programming
    error, not a mode of operation.
    """
    if not system:
        raise ValueError("the kernel CSPRNG is not an optional source")

    ikm = _framed(SourceLabel.SYSTEM, system)
    contributions = [Contribution(SourceLabel.SYSTEM, len(system), "bytes")]

    if camera_frames:
        # Whole frames, hashed. No pixel statistics, no min-entropy calculation, no buffer
        # arithmetic — see the module docstring.
        digests = b"".join(hashlib.sha256(frame).digest() for frame in camera_frames)
        ikm += _framed(SourceLabel.CAMERA, digests)
        contributions.append(Contribution(SourceLabel.CAMERA, len(camera_frames), "frames"))

    rolls = _rolls(dice_rolls)
    if rolls:
        # The ASCII roll string, never bit-packed: that sidesteps mod-6 bias rather than
        # correcting for it.
        ikm += _framed(SourceLabel.DICE, rolls.encode("ascii"))
        contributions.append(Contribution(SourceLabel.DICE, len(rolls), "rolls"))

    value = HKDF(
        algorithm=hashes.SHA256(),
        length=ENTROPY_OUTPUT_BYTES,
        salt=ENTROPY_HKDF_SALT,
        info=ENTROPY_HKDF_INFO,
    ).derive(ikm)

    return Entropy(
        value=value,
        contributions=tuple(contributions),
        camera_constant=bool(camera_frames) and all(_constant(f) for f in camera_frames),
    )


def _rolls(dice_rolls: str) -> str:
    """The roll string, with anything that is not a D6 face dropped.

    Any count is accepted — the appliance states the bits contributed rather than demanding a
    quota.
    """
    return "".join(ch for ch in dice_rolls if ch in "123456")


def _constant(frame: bytes) -> bool:
    return len(set(frame)) <= 1
