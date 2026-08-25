"""The scan screen, driven the way the appliance is driven.

Every test presses real keys against a real `SignerApp` and feeds it **real QR images** through the
`FrameSource` fake, decoded by the same `zxing-cpp` the appliance uses. This is the loopback test of
`tests/test_qr_loopback.py` with the application in the middle of it, which is where the three
states, the reset and the give-up actually live.

What is asserted is the status line's text, the slot map's contents, whether the viewfinder is
present, and the bytes that came out of the stream. Never a pixel.

`scan_once()` is called directly rather than waited for. The interval that calls it in the appliance
is 5 fps, so driving it in real time would mean a suite that waits seven seconds to scan
twenty-seven frames — and Textual's clock is not the thing under test. Elapsed time is asserted
where it is an argument, in `tests/test_scan.py`.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from conftest import render_qr, render_qrs
from textual.widgets import Button, Static

from aobs.adapters.fake import (
    FixedEntropySource,
    ImageFileFrameSource,
    RecordingKeymap,
    RecordingPower,
)
from aobs.core.constants import WALLET_QR_MAGIC, WALLET_QR_VERSION
from aobs.core.urcodec import PsbtStream
from aobs.core.wallet import Wallet
from aobs.ports.frame_source import Frame
from aobs.ui.app import SignerApp
from aobs.ui.geometry import MIN_COLUMNS, MIN_ROWS
from aobs.ui.scanning import DIFFERENT_TRANSACTION, MISSING, RECEIVED
from aobs.ui.screens.camera_lost import CAMERA_LOST
from aobs.ui.screens.home import HomeScreen
from aobs.ui.screens.scan import FRAMING_AID_NOTE, INBOUND_FRAME_RATE, ScanScreen

CONSOLE = (128, 48)
CORPUS = Path(__file__).parent.parent / "fixtures" / "psbt"

#: Where each scanning path sits on the home screen, as `docs/failure-states.md`'s inventory
#: orders it. A route rather than a construction: no test here builds a screen to poke at it.
BACKUP = 2
TRANSACTION = 3
ADDRESS = 4


def build(paths: list[Path], *, wallet: Wallet | None = None) -> SignerApp:
    app = SignerApp(
        frames=ImageFileFrameSource(paths),
        entropy=FixedEntropySource(),
        power=RecordingPower(),
        keymap=RecordingKeymap(),
        # No interval: this suite pulls the frames itself, one call per frame, so what a test
        # asserts never depends on how fast the machine running it happens to be.
        scan_frame_interval=None,
    )
    app.wallet = wallet
    return app


def texts(screen) -> str:
    return "\n".join(str(widget.content) for widget in screen.query(Static))


async def open_scan(app: SignerApp, pilot, path: int) -> ScanScreen:
    await pilot.press("f10")
    for _ in range(path):
        await pilot.press("down")
    await pilot.press("f10")
    await pilot.pause()
    assert isinstance(app.screen, ScanScreen)
    return app.screen


def drain(screen: ScanScreen, frames: int) -> None:
    for _ in range(frames):
        screen.scan_once()


def psbt_frames(name: str, directory: Path, *, rung: int = 0) -> tuple[list[Path], bytes, int]:
    directory.mkdir(parents=True, exist_ok=True)
    psbt_bytes = (CORPUS / f"{name}.psbt").read_bytes()
    stream = PsbtStream(psbt_bytes, rung=rung)
    parts = stream.cycle()
    return render_qrs(list(parts), directory), psbt_bytes, len(parts)


def test_the_appliance_itself_pulls_frames_five_times_a_second() -> None:
    """Asserted rather than exercised: this suite runs with no timer, so nothing else would catch
    the appliance's own default going missing."""
    app = SignerApp(
        frames=ImageFileFrameSource([]),
        entropy=FixedEntropySource(),
        power=RecordingPower(),
        keymap=RecordingKeymap(),
    )
    assert INBOUND_FRAME_RATE == 5
    assert app.scan_frame_interval == 1 / INBOUND_FRAME_RATE


# --- The framing aid ------------------------------------------------------------------------------


async def test_the_framing_aid_is_there_until_the_first_decode_and_then_gone(
    tmp_path: Path, mainnet_wallet: Wallet
) -> None:
    """Once bytes are arriving, aiming is solved and the screen's job is progress."""
    blank = tmp_path / "blank.png"
    from PIL import Image

    Image.new("L", (64, 64), 0).save(blank)
    paths, _psbt, _count = psbt_frames("honest_p2wpkh", tmp_path)
    app = build([blank, *paths], wallet=mainnet_wallet)
    async with app.run_test(size=CONSOLE) as pilot:
        screen = await open_scan(app, pilot, TRANSACTION)
        assert screen.query("#viewfinder"), "a framing aid before anything decodes"
        assert FRAMING_AID_NOTE in texts(screen), "and it is called a framing aid, in words"

        drain(screen, 1)  # the blank frame: nothing decodes, so aiming is still the problem
        await pilot.pause()
        assert screen.query("#viewfinder")

        drain(screen, 1)  # the first part
        await pilot.pause()
        assert not screen.query("#viewfinder")
        assert FRAMING_AID_NOTE not in texts(screen)


async def test_at_the_console_floor_the_words_are_on_screen_and_the_aid_is_centred(
    tmp_path: Path, mainnet_wallet: Wallet
) -> None:
    """The framing aid is 24 rows of a 28-row content block, so something has to give.

    What gives is the bottom of the picture, never the status line: the aid is drawn last for
    exactly this reason, and it is what the screen can afford to lose.
    """
    from PIL import Image

    blank = tmp_path / "blank.png"
    Image.new("L", (256, 96), 20).save(blank)
    app = build([blank], wallet=mainnet_wallet)
    async with app.run_test(size=(MIN_COLUMNS, MIN_ROWS)) as pilot:
        screen = await open_scan(app, pilot, TRANSACTION)
        drain(screen, 1)
        await pilot.pause()

        status = screen.query_one("#status")
        assert status.region.y + status.region.height <= MIN_ROWS, "the status line is on screen"
        viewfinder_region = screen.query_one("#viewfinder").region
        assert viewfinder_region.width == 64, "64 cells wide, whatever the console is"
        block = screen.query_one("#frame").region
        left = viewfinder_region.x - block.x
        right = (block.x + block.width) - (viewfinder_region.x + viewfinder_region.width)
        assert abs(left - right) <= 1, "centred in the content block"


# --- A multi-part transaction ---------------------------------------------------------------------


async def test_a_transaction_scanned_through_the_app_arrives_byte_identically(
    tmp_path: Path, mainnet_wallet: Wallet
) -> None:
    paths, psbt_bytes, count = psbt_frames("many_inputs", tmp_path)
    assert count > 1, "the case being tested is the multi-part one"
    app = build(paths, wallet=mainnet_wallet)
    async with app.run_test(size=CONSOLE) as pilot:
        screen = await open_scan(app, pilot, TRANSACTION)
        drain(screen, 1)
        await pilot.pause()
        slots = str(screen.query_one("#slot-map", Static).content)
        assert slots.count(RECEIVED) == 1
        assert slots.count(MISSING) == count - 1
        assert f"1 of {count} parts" in texts(screen)

        drain(screen, count - 1)
        await pilot.pause()
        assert app.scanned == psbt_bytes
        assert screen.payload == psbt_bytes
        assert str(screen.query_one("#slot-map", Static).content) == RECEIVED * count
        assert f"Scan complete — {count} of {count} parts." in texts(screen)


async def test_a_scan_never_times_out(tmp_path: Path, mainnet_wallet: Wallet) -> None:
    """No clock ends a scan. The frames simply run out here, and the screen keeps waiting."""
    paths, _psbt, count = psbt_frames("many_inputs", tmp_path)
    app = build(paths[:1], wallet=mainnet_wallet)
    async with app.run_test(size=CONSOLE) as pilot:
        screen = await open_scan(app, pilot, TRANSACTION)
        drain(screen, 200)
        await pilot.pause()
        assert isinstance(app.screen, ScanScreen), "nothing aborted the scan"
        assert app.scanned is None
        assert f"1 of {count} parts" in texts(screen)


# --- A single static QR ---------------------------------------------------------------------------


async def test_a_single_static_qr_shows_no_slot_map_and_no_part_count(
    tmp_path: Path, mainnet_wallet: Wallet
) -> None:
    """The address scan and the wallet backup use this same screen: `seq_len` is 1, so the map and
    the fraction simply never appear."""
    address = "bcrt1qw508d6qejxtdg4y5r3zarvary0c5xw7kygt080"
    app = build([render_qr(address, tmp_path)], wallet=mainnet_wallet)
    async with app.run_test(size=CONSOLE) as pilot:
        screen = await open_scan(app, pilot, ADDRESS)
        drain(screen, 1)
        await pilot.pause()
        assert app.scanned == address.encode()
        assert not screen.query("#slot-map")
        assert "parts" not in texts(screen)
        assert "Scan complete." in texts(screen)


async def test_a_wallet_backup_is_read_as_bytes_and_not_as_text(tmp_path: Path) -> None:
    """Binary byte mode, no base64. The container arrives exactly as it was written."""
    container = WALLET_QR_MAGIC + bytes([WALLET_QR_VERSION]) + bytes(range(83))
    app = build([render_qr(container, tmp_path)])
    async with app.run_test(size=CONSOLE) as pilot:
        screen = await open_scan(app, pilot, BACKUP)
        drain(screen, 1)
        await pilot.pause()
        assert app.scanned == container
        assert not screen.query("#slot-map")


# --- Giving up ------------------------------------------------------------------------------------


async def test_esc_mid_stream_discards_the_partials_and_shows_the_count(
    tmp_path: Path, mainnet_wallet: Wallet
) -> None:
    """A user who reached 26 of 27 should know they nearly had it."""
    paths, _psbt, count = psbt_frames("many_inputs", tmp_path)
    app = build(paths[:-1], wallet=mainnet_wallet)
    async with app.run_test(size=CONSOLE) as pilot:
        screen = await open_scan(app, pilot, TRANSACTION)
        drain(screen, count - 1)
        await pilot.pause()
        assert app.scanned is None

        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(app.screen, HomeScreen)
        assert app.scanned is None, "the partials are discarded, not kept"
        assert f"{count - 1} of {count}" in texts(app.screen)
        assert "discarded" in texts(app.screen)


async def test_starting_another_scan_drops_the_notice_about_the_last_one(
    tmp_path: Path, mainnet_wallet: Wallet
) -> None:
    paths, _psbt, count = psbt_frames("many_inputs", tmp_path)
    app = build(paths[:1], wallet=mainnet_wallet)
    async with app.run_test(size=CONSOLE) as pilot:
        screen = await open_scan(app, pilot, TRANSACTION)
        drain(screen, 1)
        await pilot.press("escape")
        await pilot.pause()
        assert "discarded" in texts(app.screen)
        await pilot.press("f10")
        await pilot.pause()
        assert isinstance(app.screen, ScanScreen)
        assert app.notice is None
        assert app.scanned is None, "a new scan does not start holding the last one's bytes"


# --- A different transaction ----------------------------------------------------------------------


async def test_parts_from_another_transaction_are_named_and_the_stream_resets(
    tmp_path: Path, mainnet_wallet: Wallet
) -> None:
    first, _psbt, first_count = psbt_frames("many_inputs", tmp_path / "a")
    second, _other, second_count = psbt_frames("honest_p2wpkh", tmp_path / "b")
    app = build([*first[:2], second[0]], wallet=mainnet_wallet)
    async with app.run_test(size=CONSOLE) as pilot:
        screen = await open_scan(app, pilot, TRANSACTION)
        drain(screen, 2)
        await pilot.pause()
        assert f"2 of {first_count} parts" in texts(screen)

        drain(screen, 1)
        await pilot.pause()
        assert DIFFERENT_TRANSACTION in texts(screen)
        assert f"1 of {second_count} parts" in texts(screen)
        assert app.scanned is None


# --- A QR that decoded and is not ours ------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "payload", "condition"),
    [
        (TRANSACTION, "https://example.com/pay", "not-a-psbt-or-a-wallet-backup"),
        (TRANSACTION, "UR:CRYPTO-ACCOUNT/OEADCY", "wallet-descriptor-not-a-transaction"),
        (BACKUP, "UR:CRYPTO-PSBT/1-3/ABCD", "transaction-not-a-wallet-backup"),
    ],
)
async def test_a_foreign_qr_is_named_in_the_one_failure_shape(
    tmp_path: Path, mainnet_wallet: Wallet, path: int, payload: str, condition: str
) -> None:
    app = build([render_qr(payload, tmp_path)], wallet=mainnet_wallet)
    async with app.run_test(size=CONSOLE) as pilot:
        screen = await open_scan(app, pilot, path)
        drain(screen, 1)
        await pilot.pause()
        rendered = texts(screen)
        assert f"condition: {condition}" in rendered
        assert not screen.query(Button), "no highlighted button, and so no button at all"
        assert screen.focused is None
        assert app.scanned is None


# --- Losing the camera ----------------------------------------------------------------------------


class _UnpluggedMidScan:
    """Answers the presence check, then one frame, then stops existing."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self.closed = False

    def frames(self) -> Iterator[Frame]:
        yield from ImageFileFrameSource([self._path]).frames()
        raise OSError("the camera was unplugged")

    def close(self) -> None:
        self.closed = True


async def test_losing_the_camera_mid_scan_is_a_dead_end_with_no_retry(
    tmp_path: Path, mainnet_wallet: Wallet
) -> None:
    """`authorized_default=0` is set before the first secret, so a replugged camera is not
    re-authorized. It is gone until the next boot, and the screen says so."""
    paths, _psbt, _count = psbt_frames("honest_p2wpkh", tmp_path)
    app = build([], wallet=mainnet_wallet)
    app.frames = _UnpluggedMidScan(paths[0])
    async with app.run_test(size=CONSOLE) as pilot:
        screen = await open_scan(app, pilot, TRANSACTION)
        drain(screen, 3)
        await pilot.pause()
        rendered = texts(app.screen)
        assert CAMERA_LOST.happened in rendered
        assert "condition: camera-lost" in rendered
        assert not app.screen.query(Button), "there is no retry, because retrying cannot work"
        assert app.screen.focused is None
        assert app.camera_available is False
        assert screen is not app.screen

        # And what is left of the session is honest: the paths that scan are unavailable.
        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(app.screen, HomeScreen)
        assert "path-unavailable" in app.screen.query_one("#path-3", Static).classes
