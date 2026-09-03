"""The application shell, driven the way the appliance is driven.

Every test here presses real keys against a real `SignerApp` through Textual's `run_test()` — the
same object the console adapter will run, with no display of any kind. No test constructs a screen
in isolation to poke at it, and nothing asserts on a pixel, a private attribute or the shape of a
compose tree. `docs/test-harness.md`: pixel-diffing a TUI produces tests that fail on a font change
and pass on a wrong address.
"""

from __future__ import annotations

import importlib
import re
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
from aobs.core.release import ADVISORIES_URL, Release
from aobs.core.wallet import Network, Wallet
from aobs.core.wallet_qr import export_wallet
from aobs.ports.frame_source import Frame
from aobs.ui.app import SignerApp
from aobs.ui.geometry import MAX_COLUMNS, MIN_COLUMNS, MIN_ROWS
from aobs.ui.screens.address_list import AddressListScreen
from aobs.ui.screens.address_verify import AddressVerifyScreen
from aobs.ui.screens.confirm import ConfirmScreen
from aobs.ui.screens.descriptor import DescriptorScreen
from aobs.ui.screens.console_too_small import ConsoleTooSmallScreen
from aobs.ui.screens.camera_lost import CameraLostScreen
from aobs.ui.screens.dice import DiceScreen
from aobs.ui.screens.entropy_wait import EntropyWaitScreen
from aobs.ui.screens.emit import EmitScreen
from aobs.ui.screens.export_password import ExportPasswordScreen
from aobs.ui.screens.fingerprint import FingerprintScreen
from aobs.ui.screens.passphrase import PassphraseScreen
from aobs.ui.screens.recovery_words import RecoveryWordsScreen
from aobs.ui.screens.seed_entry import SeedEntryScreen
from aobs.ui.screens.word_count import WordCountScreen
from aobs.ui.screens.refusal import RefusalScreen
from aobs.ui.screens.review import ReviewScreen
from aobs.ui.screens.home import NO_CAMERA, PATHS, HomeScreen
from aobs.ui.screens.keymap import KeymapScreen
from aobs.ui.screens.network import NetworkScreen
from aobs.ui.screens.scan import ScanScreen
from aobs.ui.screens.wallet_export import (
    ExportDoneScreen,
    ExportPasswordShowScreen,
    ReadBackScreen,
    WalletQrScreen,
)

from conftest import CORPUS, VECTOR_MNEMONIC, fixed_bytes

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


class _UnpluggedMidSession:
    """A camera that answers once and then stops existing.

    Once, because `_camera_present` asks for one frame before the first secret: a source that
    raised immediately would be a session with no camera, which is a different screen.
    """

    def __init__(self) -> None:
        self.closed = False

    def frames(self) -> Iterator[Frame]:
        yield Frame(width=4, height=4, data=bytes(16))
        raise OSError("the camera was unplugged")

    def close(self) -> None:
        self.closed = True


def build(*, camera: bool = True, **overrides: object) -> SignerApp:
    ports = {
        "frames": _OneFrameSource() if camera else ImageFileFrameSource([]),
        "entropy": FixedEntropySource(),
        "power": RecordingPower(),
        "keymap": RecordingKeymap(),
        # The scan screen's frames are pulled by the tests, never by a timer: see
        # `tests/test_scan_screen.py`.
        "scan_frame_interval": None,
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
    #: The keymap picker, home, and the scan screen two paths down from it.
    for walk in ([], ["f10"], ["f10", "down", "down", "f10"]):
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

    # The camera-lost screen is reached by losing the camera, which no keystroke can do.
    lost = build(frames=_UnpluggedMidSession(), power=RecordingPower())
    async with lost.run_test(size=CONSOLE) as pilot:
        await pilot.press("f10", "down", "down", "f10")
        await pilot.pause()
        assert isinstance(lost.screen, ScanScreen)
        lost.screen.scan_once()  # the one frame
        lost.screen.scan_once()  # and then the cable
        await pilot.pause()
        reached.append(type(lost.screen))
        await pilot.press("f12")
        await pilot.pause()
        assert lost.power.powered_off

    # The money path. Each screen gets its own session, because `F12` ends the one it is pressed
    # in — which is the whole thing being asserted.
    for name, walk, expected in (
        ("network_mismatch", (), RefusalScreen),
        ("honest_p2wpkh", (), ReviewScreen),
        ("honest_p2wpkh", ("f10",), ConfirmScreen),
        ("honest_p2wpkh", ("f10", "y"), EmitScreen),
    ):
        money = build(power=RecordingPower(), network=Network.SIGNET, emit_animated=False)
        money.wallet = Wallet.from_mnemonic(VECTOR_MNEMONIC, network=Network.SIGNET)
        async with money.run_test(size=CONSOLE) as pilot:
            await reach_home(money, pilot)
            money.open_review((CORPUS / f"{name}.psbt").read_bytes())
            await pilot.pause()
            for key in walk:
                await pilot.press(key)
            await pilot.pause()
            assert isinstance(money.screen, expected), type(money.screen).__name__
            reached.append(type(money.screen))
            await pilot.press("f12")
            await pilot.pause()
            assert money.power.powered_off, f"F12 did not power off {expected.__name__}"

    # The wallet paths. Home starts on *generate*, so the walk down the three peer choices is the
    # walk through the screens that get a wallet in. *Choose the network* sits last, so `up` from
    # the top wraps straight onto it.
    for walk, expected in (
        (("f10",), DiceScreen),
        (("f10", "f10"), RecoveryWordsScreen),
        (("f10", "f10", "f10"), SeedEntryScreen),
        (("down", "f10"), WordCountScreen),
        (("up", "f10"), NetworkScreen),
    ):
        entry = build(power=RecordingPower())
        async with entry.run_test(size=CONSOLE) as pilot:
            await reach_home(entry, pilot)
            for key in walk:
                await pilot.press(key)
            await pilot.pause()
            assert isinstance(entry.screen, expected), type(entry.screen).__name__
            reached.append(type(entry.screen))
            await pilot.press("f12")
            await pilot.pause()
            assert entry.power.powered_off, f"F12 did not power off {expected.__name__}"

    # The randomness wait, which is reached by a pool that is not up rather than by a keystroke.
    cold = FixedEntropySource()
    cold.not_ready_for = 1000
    waiting = build(power=RecordingPower(), entropy=cold, entropy_poll_interval=None)
    async with waiting.run_test(size=CONSOLE) as pilot:
        await reach_home(waiting, pilot)
        await pilot.press("f10", "f10")  # generate, then skip the dice
        await pilot.pause()
        assert isinstance(waiting.screen, EntropyWaitScreen)
        reached.append(type(waiting.screen))
        await pilot.press("f12")
        await pilot.pause()
        assert waiting.power.powered_off

    # The tail every path shares, and the one screen a scanned backup opens. Driven through the
    # app the way the money path above is: the keystrokes that reach them are their own tests.
    exported = export_wallet(bytes(16), fixed_bytes(), network=Network.MAINNET)
    for reach, expected in (
        (lambda app: app.begin_passphrase(VECTOR_MNEMONIC), PassphraseScreen),
        (lambda app: app.open_export_password(exported.container), ExportPasswordScreen),
    ):
        entry = build(power=RecordingPower())
        async with entry.run_test(size=CONSOLE) as pilot:
            await reach_home(entry, pilot)
            reach(entry)
            await pilot.pause()
            assert isinstance(entry.screen, expected), type(entry.screen).__name__
            reached.append(type(entry.screen))
            await pilot.press("f12")
            await pilot.pause()
            assert entry.power.powered_off, f"F12 did not power off {expected.__name__}"

    # The receive and export side. Every one of these needs a wallet in the session, so the
    # wallet is put there directly rather than walked to — the keystrokes that reach them are
    # their own tests, and what is asserted here is only that `F12` still ends the session.
    for reach, expected in (
        (lambda app: app.open_address_verify("bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4"),
         AddressVerifyScreen),
        (lambda app: app.open_address_list(), AddressListScreen),
        (lambda app: app.open_descriptor(), DescriptorScreen),
        (lambda app: app.open_wallet_export(), WalletQrScreen),
        (lambda app: app.push_screen(ExportPasswordShowScreen(exported)),
         ExportPasswordShowScreen),
        (lambda app: app.push_screen(ReadBackScreen(exported)), ReadBackScreen),
        (lambda app: app.push_screen(ExportDoneScreen(exported)), ExportDoneScreen),
    ):
        outbound = build(power=RecordingPower())
        outbound.wallet = Wallet.from_mnemonic(VECTOR_MNEMONIC, network=Network.MAINNET)
        outbound.mnemonic = VECTOR_MNEMONIC
        async with outbound.run_test(size=CONSOLE) as pilot:
            await reach_home(outbound, pilot)
            reach(outbound)
            await pilot.pause()
            assert isinstance(outbound.screen, expected), type(outbound.screen).__name__
            reached.append(type(outbound.screen))
            await pilot.press("f12")
            await pilot.pause()
            assert outbound.power.powered_off, f"F12 did not power off {expected.__name__}"

    loaded = build(power=RecordingPower())
    async with loaded.run_test(size=CONSOLE) as pilot:
        await reach_home(loaded, pilot)
        loaded.begin_passphrase(VECTOR_MNEMONIC)
        await pilot.pause()
        await pilot.press("f10")
        await pilot.pause()
        assert isinstance(loaded.screen, FingerprintScreen)
        reached.append(type(loaded.screen))
        await pilot.press("f12")
        await pilot.pause()
        assert loaded.power.powered_off

    # Every screen in the tree, not just the ones this walk happened to visit: a later ticket
    # that adds a screen and no route to it fails here.
    assert set(reached) == set(_screen_classes())


async def test_the_key_material_the_app_holds_is_wiped_before_the_machine_stops() -> None:
    """`docs/threat-model.md` claim (ii): a **best-effort** wipe of the derived key material the
    app itself holds, and the ordering is the whole of what can be asserted.

    The real `Power` does not return, so a wipe after it would never run. The recording fake is
    the only place that sequence is observable at all, which is why it is watched here rather than
    in the adapter — and none of it is byte-zeroing: CPython's copies are uncounted, and this
    drops the retained references, nothing more.
    """

    class _WatchingPower:
        def __init__(self, app_getter) -> None:
            self._app = app_getter
            self.held_at_stop: list[object] = []
            self.powered_off = False

        def power_off(self) -> None:
            app = self._app()
            self.held_at_stop = [
                app.wallet, app.mnemonic, app.mixing, app.export, app.scanned
            ]
            self.powered_off = True

    app = build()
    power = _WatchingPower(lambda: app)
    app.power = power
    async with app.run_test(size=CONSOLE) as pilot:
        await reach_home(app, pilot)
        app.wallet = Wallet.from_mnemonic(VECTOR_MNEMONIC, network=Network.MAINNET)
        app.mnemonic = VECTOR_MNEMONIC
        app.scanned = b"a scanned payload"
        await pilot.press("f12")
        await pilot.pause()
        assert power.powered_off
        assert power.held_at_stop == [None, None, None, None, None]


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


# --- Choosing a path -----------------------------------------------------------------------------


async def test_the_selection_moves_with_the_arrows_and_wraps() -> None:
    app = build()
    async with app.run_test(size=CONSOLE) as pilot:
        await reach_home(app, pilot)
        assert app.screen.selected_path is PATHS[0]
        await pilot.press("down", "down")
        await pilot.pause()
        assert app.screen.selected_path is PATHS[2]
        await pilot.press("up", "up", "up")
        await pilot.pause()
        assert app.screen.selected_path is PATHS[-1], "the list wraps rather than stopping"


async def test_the_accept_key_on_an_unavailable_path_does_nothing_at_all() -> None:
    """Shown rather than hidden, and inert rather than explaining itself twice: the sentence
    saying why is already on the screen."""
    app = build(camera=False)
    async with app.run_test(size=CONSOLE) as pilot:
        await reach_home(app, pilot)
        for _ in range(2):  # to "Restore from an encrypted wallet QR", which needs a camera
            await pilot.press("down")
        await pilot.press("f10")
        await pilot.pause()
        assert isinstance(app.screen, HomeScreen)
        assert app.screen.selected_path.needs_camera is True


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


def test_the_entry_point_wires_the_real_adapters_and_only_those() -> None:
    """A fake `Power` does not power off and a fake `EntropySource` returns a deterministic
    counter, so an appliance started with either would look correct on screen and be worthless in
    every claim it makes. `real_adapters()` is the one place the halves are chosen, and every one
    of them is real — the dangerous configuration is unreachable rather than merely discouraged.

    Constructing them is free of hardware on purpose: none of the four touches a device until it
    is used, which is what lets this run in a container with no camera and no keymap tree.
    """
    import aobs.__main__ as entry
    from aobs.adapters.real import (
        ForcedPowerOff,
        KernelEntropySource,
        LoadkeysKeymap,
        V4L2FrameSource,
    )

    adapters = entry.real_adapters()
    assert {name: type(port) for name, port in adapters.items()} == {
        "frames": V4L2FrameSource,
        "entropy": KernelEntropySource,
        "power": ForcedPowerOff,
        "keymap": LoadkeysKeymap,
    }


def test_a_missing_camera_is_not_a_reason_to_refuse_to_start() -> None:
    """It is a normal session with fewer paths, which the application already models: the probe
    answers honestly and the home screen disables the paths that scan. Generating a wallet and
    exporting a descriptor are both outbound and need no camera at all."""
    import aobs.__main__ as entry

    frames = entry.real_adapters()["frames"]
    stream = frames.frames()
    with pytest.raises(OSError):  # no capture device in a container
        next(stream)
    frames.close()


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


# --- The release identity footer (#61) ----------------------------------------------------------
#
# The claim is narrow and worth stating: this row **identifies, it does not attest**. A modified
# image can print anything. What is tested here is that a user who did not think to look is shown
# the version and the commit anyway, before they type a mnemonic — and that a development build
# cannot be mistaken for a release.

RELEASED = Release(
    release="v0.1.0",
    released="2026-09-14",
    commit="4f1c8a6e2b90d7c35a18ef04b6d2917c0ae53b81",
    dirty=False,
)


def footer(app: SignerApp) -> str:
    return str(app.screen.query_one("#release-identity", Static).content)


async def test_the_first_screen_names_the_version_the_commit_and_the_date() -> None:
    """All three parts, on the screen the user cannot avoid, before any secret exists."""
    app = build(release=RELEASED)
    async with app.run_test(size=CONSOLE):
        assert isinstance(app.screen, KeymapScreen)
        assert footer(app) == "aobs v0.1.0 · 4f1c8a6e2b90 · 2026-09-14"


async def test_the_footer_carries_a_commit_prefix_and_not_only_a_version() -> None:
    """The prefix is what makes the line checkable against a manifest the user has verified.

    A version alone cannot distinguish a rebuild from the published build, which is the whole
    reason #61 put twelve hex characters on the screen.
    """
    app = build(release=RELEASED)
    async with app.run_test(size=CONSOLE):
        assert "4f1c8a6e2b90" in footer(app)
        assert RELEASED.commit not in footer(app), "the full 40 hex would not fit the column cap"


async def test_both_footer_rows_fit_the_column_cap() -> None:
    """The advisory line is the longer of the two and is what fixes the wording's length budget: a
    line that wraps on the first screen reads as a layout defect rather than as a pointer."""
    app = build(release=RELEASED)
    async with app.run_test(size=CONSOLE):
        assert len(footer(app)) <= MAX_COLUMNS
        advisories = str(app.screen.query_one("#release-advisories", Static).content)
        assert len(advisories) <= MAX_COLUMNS, len(advisories)


async def test_a_development_build_says_so_and_never_a_version_shaped_string() -> None:
    """The one that matters: a developer must not sign months later with a build they took for a
    release, so `DEVELOPMENT BUILD` replaces the version rather than annotating it."""
    development = Release(
        release="development",
        released="2026-08-28",
        commit="0123456789abcdef0123456789abcdef01234567",
        dirty=False,
    )
    app = build(release=development)
    async with app.run_test(size=CONSOLE):
        row = footer(app)
        assert "DEVELOPMENT BUILD" in row
        assert not re.search(r"\bv\d+\.\d+\b", row), row


async def test_a_dirty_tree_carries_a_dirty_suffix() -> None:
    dirty = Release(
        release="development", released="2026-08-28", commit="0123456789ab" + "0" * 28, dirty=True
    )
    app = build(release=dirty)
    async with app.run_test(size=CONSOLE):
        assert "0123456789ab-dirty" in footer(app)


async def test_the_footer_says_where_advisories_live_and_does_not_claim_to_have_checked() -> None:
    """#62: the appliance attempts no detection of its own, and the row must not look like it did.

    There is no trustworthy clock offline, a wrong *this build is old* is worse than silence, and a
    modified image would lie about it anyway.
    """
    app = build(release=RELEASED)
    async with app.run_test(size=CONSOLE):
        line = str(app.screen.query_one("#release-advisories", Static).content)
        assert ADVISORIES_URL in line
        assert "cannot check" in line


async def test_the_same_line_appears_on_the_failure_screen() -> None:
    """A bug report carrying no build identity is a bug report about nothing.

    The console-too-small screen is the failure screen reachable without a session, and it uses the
    one `FailurePanel` shape every other failure screen uses.
    """
    app = build(release=RELEASED)
    async with app.run_test(size=(MIN_COLUMNS - 1, MIN_ROWS)):
        assert isinstance(app.screen, ConsoleTooSmallScreen)
        assert footer(app) == "aobs v0.1.0 · 4f1c8a6e2b90 · 2026-09-14"
