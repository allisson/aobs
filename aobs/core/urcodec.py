"""UR: what the appliance emits on screen, and what it accepts from a camera.

`docs/qr-emit-parameters.md` and the format research settle every parameter here:

* **`ur:crypto-psbt`, UR v2, multi-part outbound.** `ur:psbt` is accepted inbound and never
  emitted — Blue Wallet routes anything it does not recognise to a UR v1 decoder, where it fails.
* **Uppercased**, so the whole string fits QR alphanumeric mode: 1.55× the payload for free.
* **One named fragment size**, ~340 payload bytes at version 15 / ECC L, with a step-down ladder
  of 340 → 200 → 120 → 50 and the frame rate stepping 2 → 1 fps alongside it. The figure is
  computed from the field layouts rather than measured, which is exactly why the ladder exists.
* **The animation does not stop.** It cycles the deterministic first `seq_len` parts and then
  keeps emitting fountain parts until the user says the wallet is done. A receiver arriving late
  still converges, and starting over is never the only recovery.

The codec is in the core because it is pure: bytes in, strings out. Rendering those strings as
QR images, and pacing them, belong to the screens.
"""

from __future__ import annotations

from dataclasses import dataclass

from .constants import (
    QR_ECC_ANIMATED,
    QR_VERSION_ANIMATED,
    UR_FRAGMENT_LADDER,
    UR_FRAME_RATE_LADDER,
)
from .vendor.ur2.bytewords import Bytewords, Bytewords_Style_minimal
from .vendor.ur2.cbor_lite import CBORDecoder, CBOREncoder
from .vendor.ur2.fountain_encoder import Part as FountainPart
from .vendor.ur2.ur import UR
from .vendor.ur2.ur_decoder import URDecoder
from .vendor.ur2.ur_encoder import UREncoder

#: What we emit. Never `ur:psbt`.
PSBT_UR_TYPE = "crypto-psbt"

#: What we accept. `ur:psbt` is the post-2023 rename; refusing it would turn our own output rule
#: into an interop refusal.
ACCEPTED_PSBT_UR_TYPES = ("crypto-psbt", "psbt")


class URError(Exception):
    """A UR that did not decode. Carries no payload — the bytes may be a wallet's."""


class DifferentMessage(URError):
    """A well-formed part of a *different* message than the one being assembled.

    Detected for free, and that is the whole reason it is a named condition rather than a silent
    rejection: every UR part carries the message length and a CRC32 of the whole message, so a
    user who starts scanning transaction B midway through A can be told so
    (`docs/failure-states.md`) instead of watching a stream that can never complete.

    The vendored decoder's own answer to this part is `False`, indistinguishable from a duplicate.
    So the comparison is made here, before the part is handed over.
    """


@dataclass(frozen=True)
class EmitParameters:
    """Everything the QR screen needs to render one rung of the ladder."""

    rung: int
    fragment_bytes: int
    frame_rate: int
    ecc: str = QR_ECC_ANIMATED
    qr_version: int = QR_VERSION_ANIMATED

    @property
    def is_last_rung(self) -> bool:
        return self.rung == len(UR_FRAGMENT_LADDER) - 1


def emit_parameters(rung: int = 0) -> EmitParameters:
    if not 0 <= rung < len(UR_FRAGMENT_LADDER):
        raise ValueError("no such rung on the ladder")
    return EmitParameters(
        rung=rung,
        fragment_bytes=UR_FRAGMENT_LADDER[rung],
        frame_rate=UR_FRAME_RATE_LADDER[rung],
    )


def _cbor_bytes(payload: bytes) -> bytearray:
    encoder = CBOREncoder()
    encoder.encodeBytes(payload)
    # A bytearray, not bytes: the vendored fountain encoder pads the message in place.
    return bytearray(encoder.get_bytes())


def _cbor_to_bytes(cbor: bytes) -> bytes:
    decoder = CBORDecoder(cbor)
    payload, _length = decoder.decodeBytes()
    return bytes(payload)


class PsbtStream:
    """The animated stream for one signed PSBT.

    Stateful, but only in the way an animation is: `next_part()` walks the deterministic parts
    and then the fountain, and nothing here reads a clock or a screen.
    """

    def __init__(self, psbt_bytes: bytes, *, rung: int = 0) -> None:
        self.parameters = emit_parameters(rung)
        self._psbt_bytes = bytes(psbt_bytes)
        self._ur = UR(PSBT_UR_TYPE, _cbor_bytes(self._psbt_bytes))
        # The floor is 10 bytes or the whole message, whichever is smaller: the vendored
        # encoder asserts rather than returning when a message is shorter than its minimum.
        self._encoder = UREncoder(
            self._ur,
            self.parameters.fragment_bytes,
            min_fragment_len=min(10, max(1, len(self._ur.cbor))),
        )
        self._emitted = 0

    @property
    def seq_len(self) -> int:
        """How many deterministic parts make up one cycle — *"frame 2 of 3"*, which is on screen
        for every scan and is why no long-scan warning exists."""
        return self._encoder.fountain_encoder.seq_len()

    @property
    def cycles_completed(self) -> int:
        """The honest diagnostic: a user on cycle five knows the wallet is not reading, and that
        is the moment the step-down key earns its place."""
        return self._emitted // self.seq_len if self.seq_len else 0

    @property
    def frame_in_cycle(self) -> int:
        """*frame 2 of 3* — 1-based, and 0 before the first part has been asked for.

        The screen holds a rung index and nothing else, so the position in the cycle is the
        stream's to state rather than a counter a screen keeps beside it.
        """
        if not self._emitted or not self.seq_len:
            return 0
        return (self._emitted - 1) % self.seq_len + 1

    def next_part(self) -> str:
        """The next frame, uppercased for QR alphanumeric mode. Never stops."""
        part = self._encoder.next_part()
        self._emitted += 1
        return part.upper()

    def cycle(self) -> tuple[str, ...]:
        """One full pass of the deterministic parts, which is what a test asserts on."""
        return tuple(self.next_part() for _ in range(self.seq_len))

    def stepped_down(self) -> PsbtStream:
        """The next rung down: fewer payload bytes per frame, and a slower frame rate with it.

        A recovery path the user reaches for when a wallet will not read the code — not a
        configuration menu they must understand in advance.
        """
        if self.parameters.is_last_rung:
            return self
        return PsbtStream(self._psbt_bytes, rung=self.parameters.rung + 1)


class PsbtCollector:
    """Reassembly of an inbound PSBT from scanned parts."""

    def __init__(self) -> None:
        self._decoder = URDecoder()

    def receive(self, part: str) -> bool:
        """Take one scanned string. Returns True once the PSBT is complete.

        A part that does not belong — a foreign UR type, a corrupt string — is rejected rather
        than absorbed, and a part of a different message raises `DifferentMessage`.
        """
        text = part.strip().lower()
        if not text.startswith("ur:"):
            raise URError("not a UR")
        ur_type = text[3:].split("/", 1)[0]
        if ur_type not in ACCEPTED_PSBT_UR_TYPES:
            raise URError("not a PSBT UR")
        self._reject_different_message(text)
        self._decoder.receive_part(text)
        return self._decoder.is_complete()

    @property
    def expected_part_count(self) -> int | None:
        """How many parts the sender says there are, or `None` before the first one arrives.

        The vendored decoder raises on the empty case rather than answering it, so the `None` in
        the signature is produced here.
        """
        if self._decoder.fountain_decoder.expected_part_indexes is None:
            return None
        return self._decoder.expected_part_count()

    @property
    def received_part_indexes(self) -> frozenset[int]:
        """Which part indexes have arrived — the slot map's whole input.

        A count cannot draw the map: the parts do not arrive in order, and *which* holes are
        still open is the thing the user is being shown (`docs/scan-feedback.md`).
        """
        return frozenset(self._decoder.received_part_indexes())

    @property
    def received_part_count(self) -> int:
        return len(self._decoder.received_part_indexes())

    def _reject_different_message(self, text: str) -> None:
        """Compare this part against what the parts so far agreed on.

        The three fields are the sender's own: sequence length, message length and the CRC32 of
        the whole message. Two different transactions agreeing on all three is a CRC32 collision
        between messages of identical length, which is not a case worth a fourth field.
        """
        fountain = self._decoder.fountain_decoder
        if fountain.expected_part_indexes is None:
            return
        part = _fountain_part(text)
        if part is None:
            return
        if (
            len(fountain.expected_part_indexes) != part.seq_len
            or fountain.expected_message_len != part.message_len
            or fountain.expected_checksum != part.checksum
        ):
            raise DifferentMessage("this part belongs to a different message")

    def result(self) -> bytes:
        if not self._decoder.is_success():
            raise URError("the UR did not decode")
        return _cbor_to_bytes(self._decoder.result_message().cbor)


def _fountain_part(text: str) -> FountainPart | None:
    """The sender's own header for one multi-part UR part, or `None` for anything else.

    `None` covers a single-part UR (no sequence component, so nothing to disagree about) and a
    fragment that does not parse — which is the decoder's business to reject, not this rule's.
    """
    try:
        _ur_type, components = URDecoder.parse(text)
        if len(components) != 2:
            return None
        cbor = Bytewords.decode(Bytewords_Style_minimal, components[1])
        return FountainPart.from_cbor(cbor)
    except Exception:
        return None


def decode_psbt_parts(parts: list[str] | tuple[str, ...]) -> bytes:
    """Reassemble a PSBT from a list of scanned parts, in any order."""
    collector = PsbtCollector()
    for part in parts:
        if collector.receive(part):
            break
    return collector.result()


def encode_single_part(ur_type: str, cbor: bytes) -> str:
    """A static, single-frame UR — the descriptor export, read once at setup.

    Static QRs are ECC H (`docs/qr-emit-parameters.md`), which is a rendering parameter and so is
    stated by `QR_ECC_STATIC` rather than applied here.
    """
    return UREncoder.encode(UR(ur_type, cbor)).upper()
