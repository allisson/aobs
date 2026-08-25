"""The application shell, driven the way the appliance is driven.

Every test here presses real keys against a real `SignerApp` through Textual's `run_test()` — the
same object the console adapter will run, with no display of any kind. No test constructs a screen
in isolation to poke at it, and nothing asserts on a pixel, a private attribute or the shape of a
compose tree. `docs/test-harness.md`: pixel-diffing a TUI produces tests that fail on a font change
and pass on a wrong address.
"""

from __future__ import annotations

import importlib
import socket
from collections.abc import Iterator
from pathlib import Path

import pytest
from textual.screen import Screen
from textual.widgets import Button, Static

from aobs.adapters.fake import (
    FixedEntropySource,
    ImageFileFrameSource,
    RecordingKeymap,
    RecordingPower,
)
from aobs.core.failure import FAILURE_MESSAGE
from aobs.ports.frame_source import Frame
from aobs.ui.app import SignerApp
from aobs.ui.geometry import MAX_COLUMNS, MIN_COLUMNS, MIN_ROWS
from aobs.ui.screens.console_too_small import ConsoleTooSmallScreen
from aobs.ui.screens.home import NO_CAMERA, PATHS, HomeScreen
from aobs.ui.screens.keymap import KeymapScreen

ROOT = Path(__file__).parent.parent

#: Comfortably above the floor, and the BIOS console `docs/boot-pipeline.md` fixes with `vga=791`.
CONSOLE = (128, 48)


class _OneFrameSource:
    """A camera that is present. One blank frame is all `_camera_present` ever asks for."""

    def __init__(self) -> None:
        self.closed = False

    def frames(self) -> Iterator[Frame]:
        while True:
            yield Frame(width=4, height=4, data=bytes(16))

    def close(self) -> None:
        self.closed = True


def build(*, camera: bool = True, **overrides: object) -> SignerApp:
    ports = {
        "frames": _OneFrameSource() if camera else ImageFileFrameSource([]),
        "entropy": FixedEntropySource(),
        "power": RecordingPower(),
        "keymap": RecordingKeymap(),
    }
    ports.update(overrides)
    return SignerApp(**ports)  # type: ignore[arg-type]


def texts(app: SignerApp) -> str:
    """Everything the screen on top is currently saying, as one string."""
    return "\n".join(str(widget.content) for widget in app.screen.query(Static))


async def reach_home(app: SignerApp, pilot) -> None:
    await pilot.press("f10")
    await pilot.pause()


# --- The keymap picker --------------------------------------------------------------------------


async def test_the_keymap_picker_is_the_first_screen() -> None:
    app = build()
    async with app.run_test(size=CONSOLE):
        assert isinstance(app.screen, KeymapScreen)


async def test_us_is_the_default_and_one_keystroke_accepts_it() -> None:
    keymap = RecordingKeymap()
    app = build(keymap=keymap)
    async with app.run_test(size=CONSOLE) as pilot:
        assert app.screen.selected_layout == "us"
        await reach_home(app, pilot)
        assert keymap.applied == ["us"]


async def test_choosing_a_layout_applies_that_layout_exactly_once() -> None:
    keymap = RecordingKeymap()
    app = build(keymap=keymap)
    async with app.run_test(size=CONSOLE) as pilot:
        await pilot.press("down", "down", "down")  # us -> uk -> de -> fr
        await pilot.pause()
        assert app.screen.selected_layout == "fr"
        await reach_home(app, pilot)
        assert keymap.applied == ["fr"]
        assert isinstance(app.screen, HomeScreen)


async def test_the_picker_echoes_keys_as_typed() -> None:
    app = build()
    async with app.run_test(size=CONSOLE) as pilot:
        await pilot.press("q", "w", "e", "semicolon")
        await pilot.pause()
        assert str(app.screen.query_one("#echo", Static).content) == "qwe;"


async def test_the_echo_ignores_the_keys_that_are_doing_something_else() -> None:
    """`esc` carries `\\x1b` as its character. Echoing it would put the appliance's one
    attacker-text problem on the one screen that exists to be trusted."""
    app = build()
    async with app.run_test(size=CONSOLE) as pilot:
        await pilot.press("a", "escape", "down", "up", "b")
        await pilot.pause()
        assert str(app.screen.query_one("#echo", Static).content) == "ab"


# --- The global keys ------------------------------------------------------------------------------


async def test_f12_powers_off_from_every_screen_the_app_can_reach() -> None:
    """A sweep rather than a single case: a screen added later that shadows `F12` fails here."""
    reached: list[type[Screen]] = []
    for walk in ([], ["f10"]):
        power = RecordingPower()
        app = build(power=power)
        async with app.run_test(size=CONSOLE) as pilot:
            for key in walk:
                await pilot.press(key)
            await pilot.pause()
            reached.append(type(app.screen))
            await pilot.press("f12")
            await pilot.pause()
            assert power.powered_off, f"F12 did not power off {type(app.screen).__name__}"

    small = build()
    async with small.run_test(size=(MIN_COLUMNS - 1, MIN_ROWS)) as pilot:
        reached.append(type(small.screen))
        await pilot.press("f12")
        await pilot.pause()
        assert small.power.powered_off

    # Every screen in the tree, not just the ones this walk happened to visit: a later ticket
    # that adds a screen and no route to it fails here.
    assert set(reached) == set(_screen_classes())


async def test_esc_never_commits_and_never_powers_off() -> None:
    keymap = RecordingKeymap()
    power = RecordingPower()
    app = build(keymap=keymap, power=power)
    async with app.run_test(size=CONSOLE) as pilot:
        await pilot.press("escape", "escape")
        await pilot.pause()
        # Still on the first screen: nothing was applied, nothing was ended, nothing proceeded.
        assert isinstance(app.screen, KeymapScreen)
        assert keymap.applied == []
        assert power.powered_off is False


async def test_esc_on_the_first_screen_of_a_session_backs_out_to_nothing() -> None:
    """`esc` never leaves the user staring at a blank screen, and never re-runs the gate it
    already passed: the picker is a one-time gate and home is the base of the session."""
    keymap = RecordingKeymap()
    app = build(keymap=keymap)
    async with app.run_test(size=CONSOLE) as pilot:
        await reach_home(app, pilot)
        assert isinstance(app.screen, HomeScreen)
        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(app.screen, HomeScreen)
        assert keymap.applied == ["us"], "backing out is not a second apply"


def _screen_classes() -> list[type[Screen]]:
    """Every screen in the tree, found rather than listed.

    A later ticket adds a screen by adding a module, so it is swept by the rules below without
    anyone remembering to add it here — which is the point: these are the rules that decay when
    enforcement depends on memory.
    """
    found: list[type[Screen]] = []
    for path in sorted((ROOT / "aobs" / "ui" / "screens").glob("*.py")):
        if path.stem == "__init__":
            continue
        module = importlib.import_module(f"aobs.ui.screens.{path.stem}")
        found += [
            member
            for member in vars(module).values()
            if isinstance(member, type)
            and issubclass(member, Screen)
            and member.__module__ == module.__name__
        ]
    assert found, "the sweep found no screens, so it proves nothing"
    return found


@pytest.mark.parametrize("screen", _screen_classes(), ids=lambda cls: cls.__name__)
def test_no_screen_binds_enter_or_esc_as_its_confirm(screen: type[Screen]) -> None:
    """`docs/failure-states.md`: the confirm key is per-screen and never `enter`, never `esc`.

    A sweep, so a later ticket adding a screen fails here rather than in review.
    """
    bound = set()
    for binding in getattr(screen, "BINDINGS", []):
        if isinstance(binding, str):
            bound.add(binding.split(",")[0])
        elif isinstance(binding, tuple):
            bound.add(binding[0])
        else:
            bound.update(key.strip() for key in binding.key.split(","))
    assert not (bound & {"enter", "escape", "esc"}), screen.__name__


def test_the_app_reserves_exactly_esc_and_f12_and_binds_them_with_priority() -> None:
    bindings = {binding.key: binding for binding in SignerApp.BINDINGS}
    assert set(bindings) == {"escape", "f12"}
    assert all(binding.priority for binding in bindings.values()), (
        "a screen that can shadow a global key is a screen where `esc` might mean proceed"
    )


# --- Geometry ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "size", [(MIN_COLUMNS - 1, MIN_ROWS), (MIN_COLUMNS, MIN_ROWS - 1), (80, 25)]
)
async def test_a_console_below_the_floor_refuses_to_start_and_says_so(size) -> None:
    keymap = RecordingKeymap()
    app = build(keymap=keymap)
    async with app.run_test(size=size):
        assert isinstance(app.screen, ConsoleTooSmallScreen)
        rendered = texts(app)
        assert f"{MIN_COLUMNS}" in rendered and f"{MIN_ROWS}" in rendered
        assert "console-too-small" in rendered
        assert keymap.applied == [], "nothing else in the session started"


async def test_the_floor_itself_starts() -> None:
    app = build()
    async with app.run_test(size=(MIN_COLUMNS, MIN_ROWS)):
        assert isinstance(app.screen, KeymapScreen)


@pytest.mark.parametrize("width", [MIN_COLUMNS, 128, 240])
async def test_the_content_block_is_capped_at_96_columns_and_centred(width: int) -> None:
    app = build()
    async with app.run_test(size=(width, 48)):
        frame = app.screen.query_one("#frame")
        assert frame.outer_size.width == min(MAX_COLUMNS, width)
        left = frame.region.x
        right = width - (left + frame.outer_size.width)
        assert abs(left - right) <= 1, "the block is centred"


# --- No camera ------------------------------------------------------------------------------------


async def test_a_frame_source_that_yields_nothing_starts_with_the_scan_paths_disabled() -> None:
    app = build(camera=False)
    async with app.run_test(size=CONSOLE) as pilot:
        await reach_home(app, pilot)
        assert app.camera_available is False
        rendered = texts(app)
        assert NO_CAMERA in rendered
        # One sentence saying why, and not a dead screen: the outbound paths are still here.
        assert "Generate a new wallet" in rendered
        assert "Export the descriptor" in rendered

        for index, path in enumerate(PATHS):
            widget = app.screen.query_one(f"#path-{index}", Static)
            unavailable = "path-unavailable" in widget.classes
            assert unavailable == (path.needs_camera or path.needs_wallet), path.name


async def test_a_camera_that_is_present_leaves_every_scan_path_available() -> None:
    app = build(camera=True)
    async with app.run_test(size=CONSOLE) as pilot:
        await reach_home(app, pilot)
        assert app.camera_available is True
        assert NO_CAMERA not in texts(app)
        for index, path in enumerate(PATHS):
            widget = app.screen.query_one(f"#path-{index}", Static)
            assert ("path-unavailable" in widget.classes) == path.needs_wallet, path.name


# --- The failure shape ------------------------------------------------------------------------


async def test_a_failure_screen_offers_next_steps_with_no_default_and_no_button() -> None:
    app = build()
    async with app.run_test(size=(80, 25)):
        assert isinstance(app.screen, ConsoleTooSmallScreen)
        assert not app.screen.query(Button), "no highlighted button, and so no button at all"
        assert app.screen.focused is None, "nothing on a failure screen is pre-selected"
        steps = app.screen.query(".failure-next-step")
        assert len(steps) >= 2
        assert not any(step.has_focus for step in steps)


async def test_a_failure_screen_carries_a_condition_name_and_never_a_traceback() -> None:
    app = build()
    async with app.run_test(size=(80, 25)):
        rendered = texts(app)
        assert "condition: console-too-small" in rendered
        assert "Traceback" not in rendered
        assert 'File "' not in rendered


# --- Unrecoverable faults --------------------------------------------------------------------


class _MnemonicShaped(Exception):
    """Stands in for an exception raised inside a frame holding a secret."""


async def test_an_unrecoverable_fault_says_the_type_and_one_sentence_and_nothing_else() -> None:
    secret = "abandon abandon abandon abandon abandon about"
    app = build()
    with pytest.raises(_MnemonicShaped):
        async with app.run_test(size=CONSOLE) as pilot:

            def boom() -> None:
                raise _MnemonicShaped(secret)

            app.call_next(boom)
            await pilot.pause()

    assert app.fatal_message == f"_MnemonicShaped. {FAILURE_MESSAGE}"
    assert secret not in app.fatal_message
    assert "Traceback" not in app.fatal_message


# --- The no-network claim, as behaviour --------------------------------------------------------


async def test_the_running_app_opens_no_socket(monkeypatch: pytest.MonkeyPatch) -> None:
    """`socket` is importable on any kernel — `CONFIG_NET=n` breaks `socket()`, not `import`.

    So the checkable claim is the one made here: a whole session, from the picker to the home
    screen and out through `F12`, constructs no socket of any kind.
    """

    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("the appliance opened a socket")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "socketpair", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)

    power = RecordingPower()
    app = build(power=power)
    async with app.run_test(size=CONSOLE) as pilot:
        await reach_home(app, pilot)
        assert isinstance(app.screen, HomeScreen)
        await pilot.press("f12")
        await pilot.pause()
    assert power.powered_off


# --- The entry point ----------------------------------------------------------------------------


def test_the_entry_point_installs_the_failure_handler_before_constructing_anything(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Order, not existence. There must be no window in which an exception could reach Python's
    default traceback printer, so the handler goes in before the first object is built."""
    import aobs.__main__ as entry
    from aobs.adapters import failure_handler

    order: list[str] = []
    monkeypatch.setattr(failure_handler, "install", lambda: order.append("install"))
    monkeypatch.setattr(
        entry, "real_adapters", lambda: order.append("adapters") or {}  # type: ignore[func-returns-value]
    )

    with pytest.raises(TypeError):  # SignerApp() with no ports
        entry.main()
    assert order == ["install", "adapters"]


def test_the_entry_point_refuses_to_run_the_appliance_on_fakes() -> None:
    """A fake `Power` does not power off and a fake `EntropySource` returns a constant. Until the
    real adapters exist, `python3 -m aobs` says so rather than starting something that looks like
    an appliance."""
    import aobs.__main__ as entry

    with pytest.raises(NotImplementedError, match="real adapters"):
        entry.real_adapters()


async def test_the_running_app_installs_no_logging_handler_that_writes_anywhere() -> None:
    """`docs/failure-states.md`: no log file, no diagnostic QR, no *copy error details*.

    A dump written while a wallet is loaded is the artifact most likely to contain key material,
    and it would leave by the QR channel — the one channel this project spent four tickets
    constraining. The core's closure is checked in `tests/test_structure.py`; this is the same
    assertion against an application that has actually started and drawn.
    """
    import logging

    def handlers() -> set[int]:
        loggers = [logging.getLogger()] + [
            logging.getLogger(name) for name in list(logging.root.manager.loggerDict)
        ]
        return {
            id(handler)
            for logger in loggers
            if isinstance(logger, logging.Logger)
            for handler in logger.handlers
        }

    # Before and after, by identity: the test runner installs handlers of its own, and what is
    # asserted here is that *the appliance* installs none — not that the process has none.
    before = handlers()
    app = build()
    async with app.run_test(size=CONSOLE) as pilot:
        await reach_home(app, pilot)
        assert handlers() - before == set()
