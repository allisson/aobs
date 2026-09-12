"""Rendering a running screen to plain text, for the blocks `README.md` carries.

`docs/console-appearance.md`, *The blocks in the README*, fixes what these are for and why they are
text rather than an image: the appliance is colourless monospace, so a fenced block renders at the
reader's own metrics and diffs as text, while Textual's SVG export embeds an `@font-face` fetching
Fira Code from a CDN and places every glyph at that font's aspect ratio.

Textual 8.2.8 has no plain-text export. This is `App.export_screenshot()`
(`textual/app.py:1855`) with its last call changed from `export_svg()` to `export_text()`, which
means it reaches `Screen._compositor` — **a private attribute, and the one thing here that a
Textual upgrade can break.** It is confined to this module for that reason. Nothing in this file is
an assertion; `tests/test_structure.py` is what asserts, and it asserts against `README.md`.
"""

from __future__ import annotations

import io
import json
import tempfile
from pathlib import Path

from rich.console import Console

from conftest import VECTOR_MNEMONIC, render_qrs

from aobs.adapters.fake import (
    FixedEntropySource,
    FixedUsbBus,
    ImageFileFrameSource,
    RecordingKeymap,
    RecordingPower,
)
from aobs.core.constants import UR_FRAGMENT_LADDER
from aobs.core.urcodec import PsbtStream
from aobs.core.wallet import Network, Wallet
from aobs.ports.frame_source import Frame
from aobs.ui.app import SignerApp
from aobs.ui.screens.emit import EmitScreen
from aobs.ui.screens.home import HomeScreen
from aobs.ui.screens.review import ReviewScreen
from aobs.ui.screens.scan import ScanScreen

#: The console the appliance was measured on — 128×48, which is what a 1024×768 firmware
#: framebuffer gives fbcon — and the size every screen suite here already drives. It is a real
#: geometry rather than the floor, so the blocks picture a roomy screen and not a minimal one.
#:
#: This comment used to say `docs/boot-pipeline.md` fixes the size with `vga=791`, and to note that
#: the floor was avoided because at `MIN_ROWS` the emit screen's QR is clipped. Both are gone:
#: `vga=791` never set a mode on the machine this was measured on, and a floor that clips the QR
#: was a defect rather than a reason to drive a different size — `MIN_ROWS` is now 43.
CONSOLE = (128, 48)


def render(app: SignerApp) -> str:
    """The screen on top, as the characters a console would show, trailing blanks removed."""
    columns, rows = app.size
    console = Console(
        width=columns,
        height=rows,
        file=io.StringIO(),
        force_terminal=True,
        record=True,
        legacy_windows=False,
        safe_box=False,
    )
    console.print(
        app.screen._compositor.render_update(
            full=True, screen_stack=app._background_screens, simplify=True
        )
    )
    lines = [line.rstrip() for line in console.export_text().splitlines()]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    # The content block is capped at 96 columns and centred, so on a 128-column console every
    # line carries the same left gutter. Removing it keeps every character and every relative
    # position and costs the README 16 columns it would otherwise scroll sideways to show.
    gutter = min(len(line) - len(line.lstrip()) for line in lines if line)
    return "\n".join(line[gutter:] for line in lines)


# --- The four screens the README's session narrates -----------------------------------------------

#: One corpus case behind all four blocks, so the README's session shows one transaction arriving,
#: being reviewed and leaving again rather than three unrelated ones. `many_outputs` because its
#: output list fills the review screen, which is the screen worth the rows.
#:
#: The attack cases stay in `tests/test_review_screen.py`. A README is not where an attack is
#: demonstrated, and a reader cannot tell a pictured refusal from a pictured signing at a glance.
CASE = "many_outputs"

#: The rung the *sending* wallet's frames are rendered at for the scan block. The appliance does
#: not choose this — it reads whatever fragment size the wallet emits — and the smallest rung
#: (`aobs/core/constants.py`, `UR_FRAGMENT_LADDER`) turns this transaction into a stream with
#: slots worth picturing instead of the two a 340-byte fragmentation would give it.
SCAN_RUNG = len(UR_FRAGMENT_LADDER) - 1

#: Where *sign a transaction* sits on the home screen's inventory (`docs/failure-states.md`).
TRANSACTION = 3

CORPUS = Path(__file__).parent.parent / "fixtures" / "psbt"

#: `VECTOR_MNEMONIC` is the published BIP39 vector every test derives from (`tests/conftest.py`),
#: so nothing pictured in the README is a live wallet and the seed is one fact in one place.

def _network() -> Network:
    """The corpus declares each case's network beside it, and a wallet on the wrong one refuses."""
    return Network(json.loads((CORPUS / f"{CASE}.json").read_text())["network"])


class _OneFrame:
    """A camera that is present. One blank frame is all the home screen's probe asks for."""

    def __init__(self) -> None:
        self.closed = False

    def frames(self):
        while True:
            yield Frame(width=4, height=4, data=bytes(16))

    def close(self) -> None:
        self.closed = True


def _app(
    paths: list[Path] | None = None, *, wallet: bool = True, camera: bool = False
) -> SignerApp:
    network = _network()
    app = SignerApp(
        frames=_OneFrame() if camera else ImageFileFrameSource(paths or []),
        entropy=FixedEntropySource(),
        power=RecordingPower(),
        keymap=RecordingKeymap(),
        usb=FixedUsbBus(),
        network=network,
        scan_frame_interval=None,
        emit_animated=False,
    )
    if wallet:
        app.wallet = Wallet.from_mnemonic(VECTOR_MNEMONIC, network=network)
    return app


async def _home() -> str:
    """The first screen of a Session: no wallet yet, and a camera attached.

    No wallet because that is what a reader meets, and `_app()`'s injected one would have the
    screen announce a wallet the session has not made. A camera because without one the screen
    correctly greys out the two scanning paths, which pictures a setup the docs tell you not to
    run rather than the appliance as intended.
    """
    app = _app(wallet=False, camera=True)
    async with app.run_test(size=CONSOLE) as pilot:
        await pilot.press("f10")  # accept the keymap
        await pilot.pause()
        assert isinstance(app.screen, HomeScreen)
        return render(app)


async def _scan() -> str:
    """Mid-stream: the framing aid has done its job and the slot map is filling."""
    with tempfile.TemporaryDirectory() as directory:
        parts = list(PsbtStream((CORPUS / f"{CASE}.psbt").read_bytes(), rung=SCAN_RUNG).cycle())
        paths = render_qrs(parts, Path(directory))
        app = _app(paths)
        async with app.run_test(size=CONSOLE) as pilot:
            await pilot.press("f10")
            for _ in range(TRANSACTION):
                await pilot.press("down")
            await pilot.press("f10")
            await pilot.pause()
            assert isinstance(app.screen, ScanScreen)
            for _ in range(max(1, len(parts) // 2)):
                app.screen.scan_once()
            await pilot.pause()
            return render(app)


async def _review() -> str:
    app = _app()
    async with app.run_test(size=CONSOLE) as pilot:
        await pilot.press("f10")
        app.open_review((CORPUS / f"{CASE}.psbt").read_bytes())
        await pilot.pause()
        assert isinstance(app.screen, ReviewScreen)
        return render(app)


async def _emit() -> str:
    app = _app()
    async with app.run_test(size=CONSOLE) as pilot:
        await pilot.press("f10")
        app.open_review((CORPUS / f"{CASE}.psbt").read_bytes())
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ReviewScreen)
        while not screen.unlocked:
            await pilot.press("pagedown")
            await pilot.pause()
        await pilot.press("f10")
        await pilot.pause()
        await pilot.press("y")
        await pilot.pause()
        assert isinstance(app.screen, EmitScreen)
        return render(app)


#: Name → renderer, in the order the README's session walks them.
SCREENS = {
    "home": _home,
    "scan": _scan,
    "review": _review,
    "emit": _emit,
}


async def blocks() -> dict[str, str]:
    return {name: await renderer() for name, renderer in SCREENS.items()}
