"""The scan controller: decoded payloads in, what the screen should say out.

Pure, and time is an argument. It reads no clock, holds no widget and touches no camera — the
screen counts frames and hands the elapsed seconds in, which is what makes the delayed density hint
testable without a `sleep` anywhere in the suite (`docs/test-harness.md`).

It owns three decisions from `docs/scan-feedback.md` and `docs/failure-states.md`:

* **Which of the three states the stream is in**, and therefore which status line is on screen.
  Three states rather than one spinner, because they have three different fixes and the appliance
  knows which one it has.
* **The slot map**, one cell per part index — `▮` received, `▯` missing. Never a bar: the first
  `seq_len` parts are the pure fragments in order and mixed XOR parts follow to repair losses, so a
  bar that fills, stalls and jumps reads as broken at exactly the moment the fountain is working.
* **What a decoded-but-foreign QR is called.** Not *unrecognised QR* — that discards information
  the appliance already holds.

Nothing here times out. `esc` is the give-up, and `give_up_notice()` is what it says on the way out.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from aobs.core.constants import WALLET_QR_MAGIC, WALLET_QR_VERSION
from aobs.core.urcodec import ACCEPTED_PSBT_UR_TYPES, DifferentMessage, PsbtCollector, URError
from aobs.core.wallet import Network
from aobs.core.wallet_qr import NETWORK_FOR_BYTE
from aobs.ui.geometry import MAX_COLUMNS
from aobs.ui.qrdecode import Decoded
from aobs.ui.widgets.failure import Failure

#: How long the appliance waits before offering advice about density and aiming. Shown instantly
#: it is advice handed to someone who is merely still aiming (`docs/scan-feedback.md`).
HINT_AFTER_SECONDS = 4.0

#: Above this the map no longer fits one row, and the fraction stands alone. Compressing several
#: parts into one cell would show a filled cell for an incomplete range, which is the one thing the
#: map must never do. The number is the column budget itself, less the two columns of padding on
#: each side of the content block — `docs/scan-feedback.md` says "above ~96 parts" and this is what
#: that comes to once the block is drawn.
MAX_SLOTS = MAX_COLUMNS - 4

RECEIVED = "▮"
MISSING = "▯"

#: UR types that carry a wallet rather than a transaction. A user who scanned one on the
#: transaction screen learns exactly that.
DESCRIPTOR_UR_TYPES = (
    "crypto-account",
    "crypto-hdkey",
    "crypto-output",
    "account",
    "hdkey",
    "output",
)


class ScanTarget(Enum):
    """What this scan is looking for.

    One screen for one QR or forty-five (`docs/scan-feedback.md`): two screens would mean two
    aiming implementations, which drift, and the user is doing the same physical thing in both
    cases. What differs is only which payloads belong here — and therefore what a QR that does not
    belong is *called*.
    """

    TRANSACTION = "transaction"
    WALLET_BACKUP = "wallet-backup"
    ADDRESS = "address"


class ScanState(Enum):
    AIMING = "aiming"
    SCANNING = "scanning"
    STILL_FRAME = "still-frame"
    NOT_DECODING = "not-decoding"


#: The wording is `docs/scan-feedback.md`'s, and each line names where the fix is.
AIMING_LINE = "Point the camera at the QR code."
STILL_FRAME_LINE = (
    "Frames are decoding but no new parts are arriving — your wallet may be showing a still frame."
)
NOT_DECODING_LINE = (
    "Nothing is decoding — move closer, or ask your wallet for a lower QR density."
)

DIFFERENT_TRANSACTION = "These frames are from a different transaction. Starting again."

NOT_OURS = Failure(
    condition="not-a-psbt-or-a-wallet-backup",
    happened="This is not a PSBT or a wallet backup.",
    next_steps=(
        "Check that your wallet is showing the transaction, not a payment request or an address.",
    ),
)
DESCRIPTOR_NOT_A_TRANSACTION = Failure(
    condition="wallet-descriptor-not-a-transaction",
    happened="This is a wallet descriptor, not a transaction.",
    next_steps=(
        "Ask your wallet to show the transaction it wants signed.",
        "A descriptor is what the appliance exports, not what it signs.",
    ),
)
BACKUP_NOT_A_TRANSACTION = Failure(
    condition="wallet-backup-not-a-transaction",
    happened="This is an encrypted wallet backup, not a transaction.",
    next_steps=("Restore from an encrypted wallet QR is a separate path on the home screen.",),
)
TRANSACTION_NOT_A_BACKUP = Failure(
    condition="transaction-not-a-wallet-backup",
    happened="This is a transaction, not an encrypted wallet backup.",
    next_steps=("Sign a transaction is a separate path on the home screen.",),
)
def backup_wrong_network(backup: Network) -> Failure:
    """A backup for another chain, named — the appliance knows which side is wrong here.

    Unlike `RefusalReason.NETWORK_MISMATCH`, where a PSBT and the session disagree and neither is
    authoritative, the container *is* authoritative about the chain it was written for, and the
    session's network is still changeable at this moment. So the *where* is singular and directed,
    and this is a scan failure rather than a fourth `RefusalKind`.
    """
    return Failure(
        condition="wallet-backup-wrong-network",
        happened=(
            f"This is one of our wallet backups, and it was exported on {backup.value}. "
            "This session is on a different network."
        ),
        next_steps=(
            f"Choose {backup.value} from the home screen, then scan the code again.",
            "The master fingerprint cannot catch this: it comes from the seed and is identical "
            "on all four networks.",
        ),
    )


BACKUP_UNKNOWN_NETWORK = Failure(
    condition="wallet-backup-unknown-network",
    happened=(
        "This is one of our wallet backups, but it names a network this version of the appliance "
        "does not know."
    ),
    next_steps=(
        "Use the version of the appliance that wrote it, or restore from the recovery words.",
    ),
)
BACKUP_WRONG_VERSION = Failure(
    condition="wallet-backup-version",
    happened=(
        "This is one of our wallet backups, written by a different version of the appliance. "
        "This version cannot read it."
    ),
    next_steps=(
        "Use the version of the appliance that wrote it, or restore from the recovery words.",
    ),
)


@dataclass(frozen=True)
class Completed:
    """The bytes, byte-identical to what was sent. What happens to them is another ticket."""

    payload: bytes


@dataclass(frozen=True)
class Foreign:
    """A QR that decoded and is not ours, named for what it actually is."""

    failure: Failure


@dataclass(frozen=True)
class Restarted:
    """Parts of a different message arrived, so the stream was discarded and started again."""

    message: str = DIFFERENT_TRANSACTION


ScanEvent = Completed | Foreign | Restarted


@dataclass(frozen=True)
class ScanProgress:
    """Everything the screen draws, and the whole of what a test asserts on."""

    state: ScanState
    status: str
    #: `None` for a single static QR and above `MAX_SLOTS` parts — the two cases where a map
    #: would be a lie rather than a picture.
    slot_map: str | None
    received: int
    expected: int | None
    #: The framing aid disappears on the first successful decode: once bytes are arriving, aiming
    #: is solved and the screen's job is progress.
    framing_aid: bool
    complete: bool


class ScanController:
    def __init__(
        self,
        target: ScanTarget,
        *,
        network: Network,
        hint_after: float = HINT_AFTER_SECONDS,
    ) -> None:
        self.target = target
        #: The session's network, for the wallet-backup gate. Required rather than defaulted: a
        #: default here is the silent mainnet the gate exists to catch.
        self.network = network
        self._hint_after = hint_after
        self._collector = PsbtCollector()
        self._elapsed = 0.0
        self._decoded_at: float | None = None
        self._new_part_at: float | None = None
        self._complete = False

    # --- what the screen feeds in ---------------------------------------------------------------

    def frame(self, decoded: Decoded | None, elapsed: float) -> ScanEvent | None:
        """One frame's worth of progress. `elapsed` is seconds since the scan started.

        `None` for `decoded` is the ordinary case — most frames of a scan are the user still
        aiming — and it is what moves the state towards the density hint.
        """
        self._elapsed = elapsed
        if decoded is None or self._complete:
            return None
        if self._decoded_at is None:
            # The clock for *no new parts* starts at the first decode, not at the first frame:
            # before anything decodes, the problem is aiming and the other line says so.
            self._new_part_at = elapsed
        self._decoded_at = elapsed
        return self._accept(decoded)

    # --- what the screen draws ------------------------------------------------------------------

    @property
    def state(self) -> ScanState:
        if self._decoded_at is None:
            return (
                ScanState.AIMING if self._elapsed < self._hint_after else ScanState.NOT_DECODING
            )
        if self._elapsed - self._decoded_at >= self._hint_after:
            return ScanState.NOT_DECODING
        if self._new_part_at is not None and self._elapsed - self._new_part_at >= self._hint_after:
            return ScanState.STILL_FRAME
        return ScanState.SCANNING

    @property
    def progress(self) -> ScanProgress:
        expected = self._collector.expected_part_count
        received = self._collector.received_part_count
        state = self.state
        return ScanProgress(
            state=state,
            status=self._status(state, received, expected),
            slot_map=self._slot_map(expected),
            received=received,
            expected=expected,
            framing_aid=self._decoded_at is None,
            complete=self._complete,
        )

    def give_up_notice(self) -> str:
        """What `esc` says on the way out. The count is the point of it.

        A user who reached 26 of 27 should know they nearly had it, rather than concluding the
        appliance cannot scan (`docs/scan-feedback.md`).
        """
        expected = self._collector.expected_part_count
        if expected is None or expected <= 1:
            return "The scan was cancelled. Nothing was kept."
        return (
            f"The scan was cancelled at {self._collector.received_part_count} of {expected} "
            "parts, and the partial transaction was discarded."
        )

    # --- internals -------------------------------------------------------------------------------

    def _accept(self, decoded: Decoded) -> ScanEvent | None:
        if self.target is ScanTarget.ADDRESS:
            # Any decoded text is a candidate address. Whether it *is* one, and whether it is
            # ours, is the address screen's question and needs no camera to answer.
            self._complete = True
            return Completed(decoded.text.encode())

        if decoded.raw.startswith(WALLET_QR_MAGIC):
            if self.target is not ScanTarget.WALLET_BACKUP:
                return Foreign(BACKUP_NOT_A_TRANSACTION)
            if decoded.raw[4:5] != bytes([WALLET_QR_VERSION]):
                # Framing, before any decryption: #9's magic-and-version separates this from a
                # wrong password, which an AEAD tag never could.
                return Foreign(BACKUP_WRONG_VERSION)
            # The network, from the same cleartext header and for the same reason: the user learns
            # the backup belongs to another chain *before* typing eight words in full. This is the
            # courtesy and never the boundary — anyone who can substitute the QR can flip this
            # byte, and the tag covers it, so the load-bearing check is the one after the password
            # verifies. Both exist; deleting either leaves the wrong one.
            network_byte = decoded.raw[5:6]
            backup_network = NETWORK_FOR_BYTE.get(network_byte[0]) if network_byte else None
            if backup_network is None:
                return Foreign(BACKUP_UNKNOWN_NETWORK)
            if backup_network is not self.network:
                return Foreign(backup_wrong_network(backup_network))
            self._complete = True
            return Completed(decoded.raw)

        text = decoded.text.strip()
        if not text.lower().startswith("ur:"):
            return Foreign(NOT_OURS)
        ur_type = text[3:].split("/", 1)[0].lower()
        if ur_type in DESCRIPTOR_UR_TYPES:
            return Foreign(DESCRIPTOR_NOT_A_TRANSACTION)
        if ur_type not in ACCEPTED_PSBT_UR_TYPES:
            return Foreign(NOT_OURS)
        if self.target is not ScanTarget.TRANSACTION:
            return Foreign(TRANSACTION_NOT_A_BACKUP)
        return self._receive(text)

    def _receive(self, text: str) -> ScanEvent | None:
        before = self._collector.received_part_count
        try:
            complete = self._collector.receive(text)
        except DifferentMessage:
            # A named message and a reset, not a stream that silently never completes. The part
            # that caused it starts the new stream: it is a perfectly good part of transaction B.
            self._collector = PsbtCollector()
            self._collector.receive(text)
            self._new_part_at = self._elapsed
            return Restarted()
        except URError:
            # A corrupt fragment. Not a foreign QR — a frame that did not count, which is what
            # the fountain parts that follow are for.
            return None
        if self._collector.received_part_count > before:
            self._new_part_at = self._elapsed
        if complete:
            self._complete = True
            return Completed(self._collector.result())
        return None

    def _status(self, state: ScanState, received: int, expected: int | None) -> str:
        if self._complete:
            if expected is not None and expected > 1:
                return f"Scan complete — {expected} of {expected} parts."
            return "Scan complete."
        if state is ScanState.AIMING:
            return AIMING_LINE
        if state is ScanState.NOT_DECODING:
            return NOT_DECODING_LINE
        if state is ScanState.STILL_FRAME:
            return STILL_FRAME_LINE
        if expected is not None and expected > 1:
            return f"Scanning — {received} of {expected} parts."
        return "Scanning."

    def _slot_map(self, expected: int | None) -> str | None:
        if expected is None or expected <= 1 or expected > MAX_SLOTS:
            return None
        arrived = self._collector.received_part_indexes
        return "".join(RECEIVED if index in arrived else MISSING for index in range(expected))
