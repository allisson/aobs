"""The three modules the scan screen is made of, tested without an application.

`docs/test-harness.md`'s reason for the split is the one being exercised here: the parts most
likely to be wrong — the decode, the cell arithmetic, and which of three status lines is due —
need no camera, no console and no Textual to test.

**Time is an argument everywhere in this file.** The delayed density hint is asserted by handing
the controller an elapsed number, which is why there is no `sleep` in the suite.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import render_qr

from aobs.adapters.fake import ImageFileFrameSource
from aobs.core.constants import (
    WALLET_QR_MAGIC,
    WALLET_QR_NETWORK_BYTE,
    WALLET_QR_TOTAL_BYTES,
    WALLET_QR_VERSION,
)
from aobs.core.urcodec import PSBT_UR_TYPE, PsbtStream, decode_psbt_parts
from aobs.core.wallet import Network
from aobs.ports.frame_source import Frame
from aobs.ui import viewfinder
from aobs.ui.qrdecode import Decoded, decode_frame
from aobs.ui.scanning import (
    AIMING_LINE,
    BACKUP_NOT_A_TRANSACTION,
    BACKUP_UNKNOWN_NETWORK,
    BACKUP_WRONG_VERSION,
    DESCRIPTOR_NOT_A_TRANSACTION,
    HINT_AFTER_SECONDS,
    MAX_SLOTS,
    NOT_DECODING_LINE,
    NOT_OURS,
    STILL_FRAME_LINE,
    TRANSACTION_NOT_A_BACKUP,
    Completed,
    Foreign,
    Restarted,
    ScanController,
    ScanState,
    ScanTarget,
    backup_wrong_network,
)

CORPUS = Path(__file__).parent.parent / "fixtures" / "psbt"


def frame_of(path: Path) -> Frame:
    source = ImageFileFrameSource([path])
    return next(iter(source.frames()))


def parts_of(name: str = "many_inputs", *, rung: int = 0) -> tuple[str, ...]:
    return PsbtStream((CORPUS / f"{name}.psbt").read_bytes(), rung=rung).cycle()


def seen(part: str) -> Decoded:
    """A part as the decoder would have handed it over."""
    return Decoded(text=part, raw=part.encode())


# --- The frame decoder ----------------------------------------------------------------------------


def test_a_rendered_part_decodes_back_to_itself(tmp_path: Path) -> None:
    part = parts_of()[0]
    decoded = decode_frame(frame_of(render_qr(part, tmp_path)))
    assert decoded is not None
    assert decoded.text == part


def test_a_frame_with_no_code_in_it_decodes_to_none() -> None:
    assert decode_frame(Frame(width=64, height=64, data=bytes(64 * 64))) is None


def test_a_binary_container_survives_as_bytes_and_not_as_text(tmp_path: Path) -> None:
    """The encrypted wallet QR is binary byte mode, no base64 (`docs/encrypted-wallet-qr.md`).

    So the decoder hands back the raw bytes as well as the text. Recovering the bytes by
    re-encoding the text is how a container gets misread as a foreign QR: the text here is
    mojibake, and the bytes are exact.
    """
    container = _container(WALLET_QR_VERSION).raw
    assert len(container) == WALLET_QR_TOTAL_BYTES
    decoded = decode_frame(frame_of(render_qr(container, tmp_path)))
    assert decoded is not None
    assert decoded.raw == container
    assert decoded.text.encode() != container


# --- The viewfinder -------------------------------------------------------------------------------


def grey(level: int, width: int = 128, height: int = 48) -> Frame:
    return Frame(width=width, height=height, data=bytes([level]) * (width * height))


def test_the_viewfinder_is_64_by_24_cells_carrying_128_by_48_samples() -> None:
    cells = viewfinder.cells(grey(0))
    assert len(cells) == viewfinder.CELL_ROWS == 24
    assert {len(row) for row in cells} == {viewfinder.CELL_COLUMNS} == {64}
    # Two vertical luma samples per cell is what makes 64x24 cells a 128x48 sample image.
    assert viewfinder.CELL_ROWS * 2 == 48


@pytest.mark.parametrize(
    ("sample", "level"), [(0, 0), (63, 0), (64, 1), (127, 1), (128, 2), (191, 2), (192, 3), (255, 3)]
)
def test_the_foreground_is_one_of_the_console_s_four_true_greys(sample: int, level: int) -> None:
    assert viewfinder.foreground_level(sample) == level
    assert viewfinder.GREYS[level] in ("#000000", "#555555", "#aaaaaa", "#ffffff")


@pytest.mark.parametrize(("sample", "level"), [(0, 0), (127, 0), (128, 2), (255, 2)])
def test_the_background_half_has_only_the_two_greys_the_bare_vt_admits(
    sample: int, level: int
) -> None:
    """16 foreground colours and 8 backgrounds: there is no bold bit for a background.

    A cell whose background asked for dark grey would render as something else on the appliance's
    own console, which is the one console that matters.
    """
    assert viewfinder.background_level(sample) == level
    assert set(viewfinder.BACKGROUND_LEVELS) == {0, 2}


def test_every_cell_of_every_frame_stays_inside_the_palette() -> None:
    for level in (0, 40, 90, 130, 200, 255):
        for row in viewfinder.cells(grey(level)):
            for foreground, background in row:
                assert 0 <= foreground < len(viewfinder.GREYS)
                assert background in viewfinder.BACKGROUND_LEVELS


def test_the_viewfinder_shows_where_the_bright_rectangle_is() -> None:
    """The whole of what a framing aid claims to do: left, right, or centred."""
    width, height = 128, 48
    data = bytearray(width * height)
    for y in range(height):
        for x in range(width // 2):  # the bright half is on the left
            data[y * width + x] = 255
    cells = viewfinder.cells(Frame(width=width, height=height, data=bytes(data)))
    left = [cell for row in cells for cell in row[: viewfinder.CELL_COLUMNS // 2]]
    right = [cell for row in cells for cell in row[viewfinder.CELL_COLUMNS // 2 :]]
    assert {cell[0] for cell in left} == {3}
    assert {cell[0] for cell in right} == {0}


def test_the_rendered_markup_is_one_line_per_cell_row_of_half_blocks() -> None:
    lines = viewfinder.render(grey(200)).splitlines()
    assert len(lines) == viewfinder.CELL_ROWS
    for line in lines:
        assert line.count(viewfinder.HALF_BLOCK) == viewfinder.CELL_COLUMNS


# --- The controller: three states -----------------------------------------------------------------


def test_before_anything_decodes_the_line_is_about_aiming() -> None:
    controller = ScanController(ScanTarget.TRANSACTION, network=Network.MAINNET)
    controller.frame(None, 0.2)
    progress = controller.progress
    assert progress.state is ScanState.AIMING
    assert progress.status == AIMING_LINE
    assert progress.framing_aid is True


def test_the_density_hint_waits_a_few_seconds_and_then_arrives() -> None:
    """Shown instantly it is advice handed to someone who is merely still aiming.

    Asserted by handing the controller an elapsed number, which is the whole reason the
    controller reads no clock.
    """
    controller = ScanController(ScanTarget.TRANSACTION, network=Network.MAINNET)
    controller.frame(None, HINT_AFTER_SECONDS - 0.2)
    assert controller.progress.status == AIMING_LINE
    controller.frame(None, HINT_AFTER_SECONDS)
    assert controller.state is ScanState.NOT_DECODING
    assert controller.progress.status == NOT_DECODING_LINE


def test_parts_arriving_says_the_count_and_nothing_about_density() -> None:
    controller = ScanController(ScanTarget.TRANSACTION, network=Network.MAINNET)
    parts = parts_of()
    controller.frame(seen(parts[0]), 0.2)
    progress = controller.progress
    assert progress.state is ScanState.SCANNING
    assert progress.status == f"Scanning — 1 of {len(parts)} parts."
    assert progress.framing_aid is False, "aiming is solved the moment bytes arrive"


def test_frames_decoding_with_no_new_parts_names_the_still_frame() -> None:
    """A stall the appliance can diagnose: the wallet is showing one frame, so say so."""
    controller = ScanController(ScanTarget.TRANSACTION, network=Network.MAINNET)
    parts = parts_of()
    controller.frame(seen(parts[0]), 0.2)
    for tick in range(1, 40):
        elapsed = 0.2 + tick * 0.2
        controller.frame(seen(parts[0]), elapsed)  # the same frame, over and over
        if elapsed - 0.2 >= HINT_AFTER_SECONDS:
            break
    assert controller.state is ScanState.STILL_FRAME
    assert controller.progress.status == STILL_FRAME_LINE
    assert controller.progress.received == 1


def test_a_scan_that_stops_decoding_altogether_falls_back_to_the_density_hint() -> None:
    controller = ScanController(ScanTarget.TRANSACTION, network=Network.MAINNET)
    controller.frame(seen(parts_of()[0]), 0.2)
    controller.frame(None, 0.2 + HINT_AFTER_SECONDS)
    assert controller.progress.status == NOT_DECODING_LINE


# --- The controller: the slot map -----------------------------------------------------------------


def test_out_of_order_arrival_looks_like_holes_filling_in() -> None:
    """Never a bar. A bar that fills, stalls and jumps reads as broken exactly when the fountain
    is doing its job (`docs/scan-feedback.md`)."""
    parts = parts_of()
    assert len(parts) >= 4
    controller = ScanController(ScanTarget.TRANSACTION, network=Network.MAINNET)

    controller.frame(seen(parts[2]), 0.2)
    assert controller.progress.slot_map == "▯▯▮" + "▯" * (len(parts) - 3)

    controller.frame(seen(parts[0]), 0.4)
    assert controller.progress.slot_map == "▮▯▮" + "▯" * (len(parts) - 3)

    controller.frame(seen(parts[1]), 0.6)
    assert controller.progress.slot_map.startswith("▮▮▮")
    assert controller.progress.received == 3


def test_the_widest_map_drawn_fits_the_column_budget() -> None:
    """A map that wrapped would still be honest, and it would stop being one row of holes."""
    from aobs.ui.geometry import MAX_COLUMNS

    assert MAX_SLOTS <= MAX_COLUMNS - 4


def test_above_ninety_six_parts_the_fraction_stands_alone() -> None:
    """Compressing several parts into one cell would show a filled cell for an incomplete range."""
    # `seq_len` is the sender's choice and varies by an order of magnitude. The map's only input
    # is the part count, so what makes this case is a message long enough at the smallest rung —
    # 5 kB of payload in 50-byte fragments, which is the shape Green's encoder produces.
    parts = PsbtStream(bytes(5000), rung=3).cycle()
    assert len(parts) > MAX_SLOTS
    controller = ScanController(ScanTarget.TRANSACTION, network=Network.MAINNET)
    controller.frame(seen(parts[0]), 0.2)
    progress = controller.progress
    assert progress.slot_map is None
    assert progress.status == f"Scanning — 1 of {len(parts)} parts."


def test_a_completed_stream_hands_back_exactly_what_was_sent() -> None:
    psbt_bytes = (CORPUS / "many_inputs.psbt").read_bytes()
    stream = PsbtStream(psbt_bytes)
    controller = ScanController(ScanTarget.TRANSACTION, network=Network.MAINNET)
    event = None
    for index in range(stream.seq_len * 2):
        event = controller.frame(seen(stream.next_part()), 0.2 * (index + 1))
        if event is not None:
            break
    assert isinstance(event, Completed)
    assert event.payload == psbt_bytes
    assert controller.progress.complete is True
    seq_len = stream.seq_len
    assert controller.progress.status == f"Scan complete — {seq_len} of {seq_len} parts."


# --- The controller: a different message, and giving up -------------------------------------------


def test_parts_from_a_different_transaction_are_named_and_the_stream_restarts() -> None:
    """Detectable for free: every part carries the message length and a CRC32 of the message."""
    first = parts_of("many_inputs")
    second = parts_of("honest_p2wpkh")
    controller = ScanController(ScanTarget.TRANSACTION, network=Network.MAINNET)
    controller.frame(seen(first[0]), 0.2)
    controller.frame(seen(first[1]), 0.4)
    assert controller.progress.received == 2

    event = controller.frame(seen(second[0]), 0.6)
    assert isinstance(event, Restarted)
    assert "different transaction" in event.message
    # Reset, not a stream that silently never completes — and the part that caused it counts.
    assert controller.progress.expected == len(second)
    assert controller.progress.received == 1


def test_giving_up_says_how_far_it_got() -> None:
    parts = parts_of()
    controller = ScanController(ScanTarget.TRANSACTION, network=Network.MAINNET)
    controller.frame(seen(parts[0]), 0.2)
    notice = controller.give_up_notice()
    assert f"1 of {len(parts)}" in notice
    assert "discarded" in notice


def test_giving_up_before_anything_arrived_claims_no_count() -> None:
    controller = ScanController(ScanTarget.TRANSACTION, network=Network.MAINNET)
    controller.frame(None, 0.2)
    assert "Nothing was kept." in controller.give_up_notice()


# --- The controller: a single static QR -----------------------------------------------------------


def test_an_address_completes_on_the_first_decode_with_no_parts_to_count() -> None:
    controller = ScanController(ScanTarget.ADDRESS, network=Network.MAINNET)
    address = "bcrt1qw508d6qejxtdg4y5r3zarvary0c5xw7kygt080"
    event = controller.frame(Decoded(text=address, raw=address.encode()), 0.2)
    assert isinstance(event, Completed)
    assert event.payload == address.encode()
    progress = controller.progress
    assert progress.slot_map is None
    assert progress.expected is None
    assert progress.status == "Scan complete."


def test_a_wallet_backup_completes_on_the_first_decode() -> None:
    container = _container(WALLET_QR_VERSION).raw
    controller = ScanController(ScanTarget.WALLET_BACKUP, network=Network.MAINNET)
    event = controller.frame(Decoded(text="mojibake", raw=container), 0.2)
    assert isinstance(event, Completed)
    assert event.payload == container
    assert controller.progress.slot_map is None


# --- The controller: liberal inbound, strict outbound ---------------------------------------------


def test_ur_psbt_is_accepted_inbound_and_never_emitted() -> None:
    """`docs/failure-states.md`: refusing it inbound would reject a PSBT the user's wallet
    legitimately produced. #4's rule is about our *output*, and both halves are pinned here so the
    asymmetry lives in one place."""
    psbt_bytes = (CORPUS / "honest_p2wpkh.psbt").read_bytes()
    emitted = PsbtStream(psbt_bytes).cycle()
    assert PSBT_UR_TYPE == "crypto-psbt"
    for part in emitted:
        assert part.startswith("UR:CRYPTO-PSBT/")
        assert not part.startswith("UR:PSBT/")

    # The same parts under the prefix a wallet may legitimately send: the UR type is outside the
    # fragment's own CRC, so this is a part a wallet could have emitted.
    renamed = [part.replace("UR:CRYPTO-PSBT/", "UR:PSBT/") for part in emitted]
    assert decode_psbt_parts(renamed) == psbt_bytes

    controller = ScanController(ScanTarget.TRANSACTION, network=Network.MAINNET)
    event = None
    for index, part in enumerate(renamed):
        event = controller.frame(seen(part), 0.2 * (index + 1))
    assert isinstance(event, Completed)
    assert event.payload == psbt_bytes


# --- The controller: a QR that decoded and is not ours -------------------------------------------


def _container(version: int, network: Network = Network.MAINNET, *, network_byte: int | None = None) -> Decoded:
    byte = WALLET_QR_NETWORK_BYTE[network.value] if network_byte is None else network_byte
    return Decoded(
        text="mojibake", raw=WALLET_QR_MAGIC + bytes([version, byte]) + bytes(range(83))
    )


@pytest.mark.parametrize(
    ("target", "network", "decoded", "expected"),
    [
        (
            ScanTarget.TRANSACTION,
            Network.MAINNET,
            Decoded(text="https://example.com/pay", raw=b"https://example.com/pay"),
            NOT_OURS,
        ),
        (
            ScanTarget.TRANSACTION,
            Network.MAINNET,
            Decoded(text="UR:CRYPTO-ACCOUNT/OEADCY", raw=b"UR:CRYPTO-ACCOUNT/OEADCY"),
            DESCRIPTOR_NOT_A_TRANSACTION,
        ),
        (
            ScanTarget.TRANSACTION,
            Network.MAINNET,
            Decoded(text="UR:CRYPTO-HDKEY/ONAXHD", raw=b"UR:CRYPTO-HDKEY/ONAXHD"),
            DESCRIPTOR_NOT_A_TRANSACTION,
        ),
        (
            ScanTarget.TRANSACTION,
            Network.MAINNET,
            _container(WALLET_QR_VERSION),
            BACKUP_NOT_A_TRANSACTION,
        ),
        (
            ScanTarget.WALLET_BACKUP,
            Network.MAINNET,
            _container(WALLET_QR_VERSION + 1),
            BACKUP_WRONG_VERSION,
        ),
        # A version 1 container: the free case, asserted so it stays free.
        (
            ScanTarget.WALLET_BACKUP,
            Network.MAINNET,
            _container(1),
            BACKUP_WRONG_VERSION,
        ),
        # A backup for another network, and the session's own network is what makes it foreign.
        (
            ScanTarget.WALLET_BACKUP,
            Network.MAINNET,
            _container(WALLET_QR_VERSION, Network.SIGNET),
            backup_wrong_network(Network.SIGNET),
        ),
        (
            ScanTarget.WALLET_BACKUP,
            Network.SIGNET,
            _container(WALLET_QR_VERSION, Network.MAINNET),
            backup_wrong_network(Network.MAINNET),
        ),
        (
            ScanTarget.WALLET_BACKUP,
            Network.REGTEST,
            _container(WALLET_QR_VERSION, Network.TESTNET4),
            backup_wrong_network(Network.TESTNET4),
        ),
        # A network byte no version of the appliance assigns.
        (
            ScanTarget.WALLET_BACKUP,
            Network.MAINNET,
            _container(WALLET_QR_VERSION, network_byte=0x7F),
            BACKUP_UNKNOWN_NETWORK,
        ),
        (
            ScanTarget.WALLET_BACKUP,
            Network.MAINNET,
            Decoded(text="UR:CRYPTO-PSBT/1-3/ABCD", raw=b"UR:CRYPTO-PSBT/1-3/ABCD"),
            TRANSACTION_NOT_A_BACKUP,
        ),
        (
            ScanTarget.WALLET_BACKUP,
            Network.MAINNET,
            Decoded(text="just some text", raw=b"just some text"),
            NOT_OURS,
        ),
    ],
    ids=lambda value: getattr(value, "condition", None) or getattr(value, "value", None) or "",
)
def test_a_foreign_qr_is_named_for_what_it_actually_is(target, network, decoded, expected) -> None:
    """One row per case, so a new case is added by adding a row.

    *Unrecognised QR* would discard information the appliance already holds
    (`docs/failure-states.md`).
    """
    event = ScanController(target, network=network).frame(decoded, 0.2)
    assert isinstance(event, Foreign)
    assert event.failure == expected
    assert event.failure.condition != ""


def test_every_foreign_condition_has_its_own_name_and_its_own_words() -> None:
    failures = (
        NOT_OURS,
        DESCRIPTOR_NOT_A_TRANSACTION,
        BACKUP_NOT_A_TRANSACTION,
        TRANSACTION_NOT_A_BACKUP,
        BACKUP_WRONG_VERSION,
        BACKUP_UNKNOWN_NETWORK,
        backup_wrong_network(Network.SIGNET),
    )
    assert len({failure.condition for failure in failures}) == len(failures)
    assert len({failure.happened for failure in failures}) == len(failures)
