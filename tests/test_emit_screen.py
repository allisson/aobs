"""The emit screen and the QR renderer: the payload, not its prettiness.

What is asserted is the exact string the appliance would put on screen for a wallet to read, the
module arithmetic that string turns into, and what the step-down key does to both. The renderer is
Textual-free, so its half of this file needs no application at all.

`tests/test_qr_loopback.py` already proves that these payloads survive real QR images and the real
decoder. This module asserts that the screen hands the channel the same bytes `PsbtStream` produces
and never a different prefix, a truncated cycle or a rung the user did not ask for.
"""

from __future__ import annotations

import math

from aobs.adapters.fake import (
    FixedEntropySource,
    ImageFileFrameSource,
    RecordingKeymap,
    RecordingPower,
)
from aobs.core.constants import (
    QR_ECC_ANIMATED,
    QR_VERSION_ANIMATED,
    UR_FRAGMENT_LADDER,
    UR_FRAME_RATE_LADDER,
)
from aobs.core.signing import sign
from aobs.core.urcodec import PSBT_UR_TYPE, PsbtStream, decode_psbt_parts
from aobs.core.wallet import Network, Wallet
from aobs.ui import qrcodes
from aobs.ui.app import SignerApp
from aobs.ui.geometry import MAX_COLUMNS
from aobs.ui.screens.emit import KEYS, LAST_RUNG, STEP_DOWN_KEY, EmitScreen

from conftest import CORPUS, VECTOR_MNEMONIC

CONSOLE = (128, 48)
CASE = "many_inputs"


def signed_psbt() -> bytes:
    wallet = Wallet.from_mnemonic(VECTOR_MNEMONIC, network=Network.SIGNET)
    return sign((CORPUS / f"{CASE}.psbt").read_bytes(), wallet)


def build() -> SignerApp:
    return SignerApp(
        frames=ImageFileFrameSource([]),
        entropy=FixedEntropySource(),
        power=RecordingPower(),
        keymap=RecordingKeymap(),
        network=Network.SIGNET,
        scan_frame_interval=None,
        # The suite steps the animation itself: 47 frames at 2 fps would cost 23 seconds to
        # assert something that is not Textual's clock.
        emit_animated=False,
    )


async def open_emit(app: SignerApp, pilot, psbt: bytes) -> EmitScreen:
    app.push_screen(EmitScreen(psbt, app.network.value, animate=app.emit_animated))
    await pilot.pause()
    assert isinstance(app.screen, EmitScreen)
    return app.screen


# --- The renderer ---------------------------------------------------------------------------------


def test_the_module_matrix_is_the_symbol_plus_its_quiet_zone() -> None:
    """`4 × version + 17` modules of symbol, plus four modules of quiet zone on every side."""
    code = qrcodes.render("A" * 700)
    assert code.version == QR_VERSION_ANIMATED
    assert code.modules == 4 * code.version + 17 + 2 * qrcodes.QUIET_ZONE == 85


def test_a_version_15_code_fits_the_console_as_half_blocks() -> None:
    """85 columns and 43 character rows, which is what `docs/qr-emit-parameters.md` budgeted."""
    code = qrcodes.render("A" * 700)
    lines = code.text.split("\n")
    assert len(lines) == code.rows == 43
    assert {len(line) for line in lines} == {85}
    assert code.modules <= MAX_COLUMNS - 4, "inside the column budget"
    assert len(lines) == math.ceil(code.modules / 2)


def test_the_half_block_text_is_a_faithful_encoding_of_the_matrix() -> None:
    """Two module rows per character row, and nothing lost in between — checked by inverting it
    rather than by trusting the glyph table."""
    code = qrcodes.render("UR:CRYPTO-PSBT/1-3/ABCDEF")
    recovered = qrcodes.from_half_blocks(code.text)
    assert recovered[: code.modules] == code.matrix
    assert not any(recovered[code.modules]), "the padding row is dark"


def test_light_modules_are_drawn_as_ink() -> None:
    """The console is white on black, so a filled block is a *light* module. That renders the code
    in its true polarity rather than inverted."""
    code = qrcodes.render("A" * 40)
    # The top-left corner is quiet zone: two light module rows, so a full block.
    assert code.text[0] == "█"
    assert not code.matrix[0][0]


# --- The payload ----------------------------------------------------------------------------------


async def test_the_frames_are_byte_identical_to_the_streams_own() -> None:
    psbt = signed_psbt()
    expected = PsbtStream(psbt).cycle()
    app = build()
    async with app.run_test(size=CONSOLE) as pilot:
        screen = await open_emit(app, pilot, psbt)
        shown = [screen.part]
        for _ in range(len(expected) - 1):
            screen.advance()
            shown.append(screen.part)
    assert tuple(shown) == expected


async def test_nothing_emitted_ever_carries_the_ur_psbt_prefix() -> None:
    """`ur:psbt` is accepted inbound and never emitted: Blue Wallet routes it to its UR v1
    decoder, where it fails. Liberal inbound, strict outbound."""
    psbt = signed_psbt()
    app = build()
    async with app.run_test(size=CONSOLE) as pilot:
        screen = await open_emit(app, pilot, psbt)
        for _ in range(screen.stream.seq_len * 3):
            assert screen.part.startswith(f"UR:{PSBT_UR_TYPE.upper()}/")
            screen.advance()


async def test_the_animation_does_not_stop_at_any_multiple_of_the_cycle() -> None:
    """Stopping at any multiple creates a failure whose only recovery is starting over, which is
    precisely what fountain encoding exists to avoid."""
    psbt = signed_psbt()
    app = build()
    async with app.run_test(size=CONSOLE) as pilot:
        screen = await open_emit(app, pilot, psbt)
        seq_len = screen.stream.seq_len
        assert seq_len > 1, "the case being tested is the multi-part one"

        parts = [screen.part]
        for _ in range(seq_len * 5):
            screen.advance()
            parts.append(screen.part)
        assert len(parts) == seq_len * 5 + 1
        assert all(parts), "a frame is emitted past every multiple of seq_len"
        assert screen.stream.cycles_completed == 5

        # And a receiver that only ever saw the tail still converges.
        assert decode_psbt_parts(parts[-seq_len * 2 :]) == psbt


async def test_the_frame_and_the_cycle_are_on_screen() -> None:
    """*Frame 2 of 47* tells the user everything a warning would, at the moment it is actionable,
    with no click-through reflex to build — so there is no warning."""
    psbt = signed_psbt()
    app = build()
    async with app.run_test(size=CONSOLE) as pilot:
        screen = await open_emit(app, pilot, psbt)
        seq_len = screen.stream.seq_len
        status = str(screen.query_one("#emit-status").content)
        assert f"Frame 1 of {seq_len}" in status
        assert "cycle 1" in status
        assert f"{UR_FRAGMENT_LADDER[0]} bytes per frame" in status

        screen.advance()
        assert f"Frame 2 of {seq_len}" in str(screen.query_one("#emit-status").content)

        for _ in range(seq_len - 1):
            screen.advance()
        status = str(screen.query_one("#emit-status").content)
        assert f"Frame 1 of {seq_len}" in status
        assert "cycle 2" in status


# --- The ladder -----------------------------------------------------------------------------------


async def test_the_step_down_key_walks_the_whole_ladder_and_stops() -> None:
    """A recovery path, not a configuration menu. The frame rate follows the fragment size down."""
    psbt = signed_psbt()
    app = build()
    async with app.run_test(size=CONSOLE) as pilot:
        screen = await open_emit(app, pilot, psbt)
        seen = []
        for _ in range(len(UR_FRAGMENT_LADDER) + 2):
            parameters = screen.stream.parameters
            seen.append((parameters.fragment_bytes, parameters.frame_rate))
            await pilot.press(STEP_DOWN_KEY)
            await pilot.pause()

        ladder = list(zip(UR_FRAGMENT_LADDER, UR_FRAME_RATE_LADDER, strict=True))
        assert seen[: len(ladder)] == ladder
        # Past the bottom it does nothing rather than wrapping or erroring.
        assert seen[len(ladder) :] == [ladder[-1]] * 2
        assert LAST_RUNG in str(screen.query_one("#emit-status").content)


async def test_stepping_down_trades_frames_for_density() -> None:
    psbt = signed_psbt()
    app = build()
    async with app.run_test(size=CONSOLE) as pilot:
        screen = await open_emit(app, pilot, psbt)
        first = screen.stream.seq_len
        await pilot.press(STEP_DOWN_KEY)
        await pilot.pause()
        assert screen.stream.seq_len > first
        # And what it emits is still the same PSBT, at the new rung.
        parts = [screen.part]
        for _ in range(screen.stream.seq_len):
            screen.advance()
            parts.append(screen.part)
        assert decode_psbt_parts(parts) == psbt


async def test_every_rung_stays_inside_version_15() -> None:
    """The fragment size is what keeps the code inside the console, at every rung of the ladder."""
    psbt = signed_psbt()
    app = build()
    async with app.run_test(size=CONSOLE) as pilot:
        screen = await open_emit(app, pilot, psbt)
        for rung in range(len(UR_FRAGMENT_LADDER)):
            assert screen.stream.parameters.rung == rung
            assert screen.stream.parameters.ecc == QR_ECC_ANIMATED
            for _ in range(screen.stream.seq_len):
                assert qrcodes.render(screen.part).version <= QR_VERSION_ANIMATED
                screen.advance()
            await pilot.press(STEP_DOWN_KEY)
            await pilot.pause()


# --- The keys -------------------------------------------------------------------------------------


def test_the_step_down_key_is_f9_and_the_screen_teaches_it() -> None:
    """`docs/qr-emit-parameters.md` names the key. Asserted here so the document and the binding
    cannot drift apart silently, and so a rename lands in both."""
    assert STEP_DOWN_KEY == "f9"
    assert KEYS.startswith("F9 ")
    # Never `F11`: a slip from there lands on `F12` and ends the session.
    assert "F11" not in KEYS


async def test_f10_is_inert_on_this_screen_which_is_why_f9_sits_beside_it() -> None:
    """The load-bearing half of the key choice: a slip from `F10` to `F9` is harmless because
    `F10` does nothing here. A later ticket that binds it on this screen fails here."""
    psbt = signed_psbt()
    app = build()
    async with app.run_test(size=CONSOLE) as pilot:
        screen = await open_emit(app, pilot, psbt)
        before = (screen.stream.parameters.rung, screen.part)
        await pilot.press("f10")
        await pilot.pause()
        assert app.screen is screen, "F10 left the emit screen"
        assert (screen.stream.parameters.rung, screen.part) == before


async def test_esc_leaves_the_emit_screen_reversibly() -> None:
    """What makes `esc done` honest rather than a commit.

    The confirm reaches emit with `switch_screen`, so emit replaces the confirm and sits on the
    review — which kept its scroll and its open lock. A user who presses `esc` before the wallet
    has finished reading lands back there and can re-sign the same bytes and emit again.
    """
    from aobs.ui.screens.review import ReviewScreen

    app = build()
    app.wallet = Wallet.from_mnemonic(VECTOR_MNEMONIC, network=Network.SIGNET)
    async with app.run_test(size=CONSOLE) as pilot:
        await pilot.press("f10")  # accept the keymap
        await pilot.pause()
        app.open_review((CORPUS / "honest_p2wpkh.psbt").read_bytes())
        await pilot.pause()
        await pilot.press("f10", "y")
        await pilot.pause()
        assert isinstance(app.screen, EmitScreen)
        emitted = app.screen.signed_psbt

        await pilot.press("escape")
        await pilot.pause()
        review = app.screen
        assert isinstance(review, ReviewScreen), "esc landed somewhere other than the review"
        assert review.unlocked, "the review's lock closed behind the user"

        # And the way back out is the same two keys, emitting the same bytes.
        await pilot.press("f10", "y")
        await pilot.pause()
        assert isinstance(app.screen, EmitScreen)
        assert app.screen.signed_psbt == emitted


# --- What is not on the screen --------------------------------------------------------------------


async def test_there_is_no_warning_dialog_about_a_long_animation() -> None:
    """The appliance never trains the user to click through things."""
    from textual.widgets import Button

    psbt = signed_psbt()
    app = build()
    async with app.run_test(size=CONSOLE) as pilot:
        screen = await open_emit(app, pilot, psbt)
        assert screen.stream.seq_len > 1
        assert not screen.query(Button)
        assert screen.focused is None
        rendered = "\n".join(str(w.content) for w in screen.query("Static"))
        assert "warning" not in rendered.lower()
        assert "continue" not in rendered.lower()


def test_the_appliance_itself_paces_the_animation_from_the_ladder() -> None:
    """Asserted rather than exercised: this suite runs with no timer, so nothing else would catch
    the appliance's own default going missing."""
    app = SignerApp(
        frames=ImageFileFrameSource([]),
        entropy=FixedEntropySource(),
        power=RecordingPower(),
        keymap=RecordingKeymap(),
    )
    assert app.emit_animated is True
    assert UR_FRAME_RATE_LADDER[0] == 2


def test_the_renderer_imports_no_textual() -> None:
    """The module arithmetic is where a code no wallet can read comes from, so it is testable with
    no application at all — and a stray import of the framework would quietly end that.

    Asserted on the module's own imports rather than on `sys.modules`, and the distinction is the
    same one `tests/test_structure.py` draws about the network stack: `aobs/ui/__init__.py` exports
    `SignerApp`, so *reaching* this module through the package imports Textual whatever this module
    does. The rule that is both true and enforceable is that this module does not.
    """
    import ast
    from pathlib import Path

    tree = ast.parse(Path(qrcodes.__file__).read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    assert not {name for name in imported if name.split(".")[0] == "textual"}
    assert "qrcode" in imported, "the renderer is the one place the QR library is reached for"


def test_the_module_arithmetic_needs_no_application() -> None:
    """A version 1 code: 21 modules of symbol, 29 with the quiet zone, 15 character rows."""
    code = qrcodes.render("UR:CRYPTO-PSBT/1-2/ABCD")
    assert code.version == 1
    assert code.modules == 29
    assert code.rows == 15
