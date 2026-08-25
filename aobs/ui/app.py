"""`SignerApp`: the one Textual application, and the display seam itself.

There is no `Screen` port. It was declared with two adapters — "Textual on the console" and
"Textual `run_test()`" — which are the *same* application under two drivers, not two
implementations of an interface. So the app is the seam: tests drive this object headless through
`run_test()`, pressing real keys against real screens, and the console adapter will run the very
same object. `docs/test-harness.md`'s port table says so.

The four ports it is handed are the things that genuinely do have two implementations. The app
never reaches for a camera, for randomness, for a power-off or for the console's keymap by itself.
"""

from __future__ import annotations

from textual.app import App
from textual.binding import Binding

from aobs.core.failure import describe
from aobs.core.wallet import Network, Wallet
from aobs.ports.entropy_source import EntropySource
from aobs.ports.frame_source import FrameSource
from aobs.ports.keymap import Keymap
from aobs.ports.power import Power
from aobs.ui.geometry import MAX_COLUMNS, fits
from aobs.ui.scanning import ScanTarget
from aobs.ui.screens.camera_lost import CameraLostScreen
from aobs.ui.screens.console_too_small import ConsoleTooSmallScreen
from aobs.ui.screens.home import HomeScreen
from aobs.ui.screens.keymap import KeymapScreen
from aobs.ui.screens.scan import INBOUND_FRAME_RATE, ScanScreen


class SignerApp(App[None]):
    """The appliance.

    Holds the session: the wallet or the absence of one, the network, whether a camera was found.
    Nothing here ends the session but `F12` and an unrecoverable fault — a refused PSBT returns to
    the scan screen with the wallet still loaded, because dropping it buys nothing (it is in RAM
    regardless, and a refusal means the attack failed) and costs a great deal.
    """

    #: Three reserved keys, identical on every screen, and nothing else reserved
    #: (`docs/failure-states.md`). They are `priority` so that no screen can shadow them: a user
    #: who has learned `esc` means *back* must never meet a screen where it means *proceed*, and
    #: the way to guarantee that is to make the screen unable to claim the key at all.
    #:
    #: The third reserved key is the confirm key, and it is deliberately absent here: it is
    #: per-screen, and only the rule about it is global — never `enter`, never `esc`.
    BINDINGS = [
        Binding("escape", "back", "Back", priority=True),
        Binding("f12", "power_off", "Power off", priority=True),
    ]

    CSS = f"""
    Screen {{ align-horizontal: center; }}
    #frame {{ width: {MAX_COLUMNS}; max-width: 100%; height: 1fr; padding: 1 2; }}
    #title {{ text-style: bold; margin-bottom: 1; }}
    """

    def __init__(
        self,
        *,
        frames: FrameSource,
        entropy: EntropySource,
        power: Power,
        keymap: Keymap,
        network: Network = Network.MAINNET,
        scan_frame_interval: float | None = 1 / INBOUND_FRAME_RATE,
    ) -> None:
        super().__init__()
        self.frames = frames
        self.entropy = entropy
        self.power = power
        self.keymap = keymap
        #: How often the scan screen pulls a frame. `None` means no timer at all, which is how the
        #: suite drives frames itself: pacing twenty-seven frames in real time would cost the suite
        #: seven seconds to assert something that is not Textual's clock.
        self.scan_frame_interval = scan_frame_interval

        # --- session state ---
        self.wallet: Wallet | None = None
        #: Not settled by any document in `docs/`. This spec proceeds on the parent's stated
        #: assumption — chosen on the wallet screen before the wallet is constructed, defaulting
        #: to mainnet, shown in the header of every screen that shows money. If the assumption is
        #: wrong the correction is one screen and this one argument, and it belongs on the map
        #: rather than in a diff.
        self.network = network
        self.camera_available = False
        #: What an unrecoverable fault said, for a test to read. Never a traceback.
        self.fatal_message: str | None = None
        #: The bytes the last completed scan produced. This is where the inbound spec ends: what
        #: happens to them is the review, restore and address-verification specs.
        self.scanned: bytes | None = None
        #: One sentence for the screen the user lands on next — how far an abandoned scan got.
        #: Nothing here is attacker-controlled: the appliance writes it about its own state.
        self.notice: str | None = None

    # --- startup -----------------------------------------------------------------------------

    def on_mount(self) -> None:
        columns, rows = self.size.width, self.size.height
        if not fits(columns, rows):
            # Refuse rather than degrade: a layout that has quietly reflowed is exactly where a
            # truncated address goes unnoticed. Nothing else in the session starts.
            self.push_screen(ConsoleTooSmallScreen(columns, rows))
            return
        self.camera_available = self._camera_present()
        self.push_screen(KeymapScreen())

    def _camera_present(self) -> bool:
        """Ask the `FrameSource` for one frame, once, before any secret exists.

        A source that yields nothing is a machine with no webcam, and that disables the scan paths
        and nothing else — generating a wallet and exporting its descriptor are both outbound and
        need no camera at all.
        """
        stream = self.frames.frames()
        try:
            next(stream)
        except (StopIteration, OSError):
            return False
        finally:
            # The port promises an `Iterator`, not a generator, so `close()` is not guaranteed —
            # the real V4L2 adapter is free to hand back something else.
            close = getattr(stream, "close", None)
            if close is not None:
                close()
        return True

    # --- the global keys ---------------------------------------------------------------------

    def action_back(self) -> None:
        """Back out of this screen without acting. Never proceeds, and never leaves nothing.

        The stack holds Textual's own default screen underneath ours, so backing off the first
        real screen would leave the user staring at a blank one. There is nothing behind the first
        screen, so `esc` there does nothing.
        """
        if len(self.screen_stack) > 2:
            # The screen being left says what leaving costs — how far an abandoned scan got —
            # before the screen underneath is asked to redraw. Set after the pop, the notice
            # would be one refresh too late to appear, which is a silence rather than a bug the
            # next reader would notice.
            leaving = getattr(self.screen, "leave_notice", None)
            self.notice = leaving() if leaving is not None else None
            self.pop_screen()

    # --- what the screens call ----------------------------------------------------------------

    def open_scan(self, target: ScanTarget) -> None:
        """Every inbound path goes through the one scan screen.

        The notice and the bytes of the last scan are both dropped here rather than when they are
        read: they describe a scan the user has walked away from, and a stale wallet backup sitting
        in a session attribute is exactly the kind of thing `docs/secret-hygiene.md` is about.
        """
        self.notice = None
        self.scanned = None
        self.push_screen(ScanScreen(target))

    def camera_lost(self) -> None:
        """The camera stopped answering. It cannot come back this session, and the screen says so.

        `authorized_default=0` is set before the first secret exists, so an unplugged and
        replugged camera is not re-authorized. Backing out of the message lands on a home screen
        with the scan paths disabled, which is the honest remainder of the session.
        """
        self.camera_available = False
        self.switch_screen(CameraLostScreen())

    def action_power_off(self) -> None:
        """End the session, from anywhere, always.

        `F12` specifically: hard to hit by accident, impossible to hit while touch-typing a
        mnemonic — and a power-off that needs a menu is one people avoid, which leaves wallets
        loaded on unattended machines.
        """
        self.power.power_off()
        self.exit()

    # --- what the keymap picker calls ---------------------------------------------------------

    def accept_keymap(self, name: str) -> None:
        self.keymap.apply(name)
        self.switch_screen(HomeScreen())

    # --- unrecoverable faults -----------------------------------------------------------------

    def fatal(self, error: BaseException) -> str:
        """The whole of what an unrecoverable fault may say: the exception type, and one sentence.

        Not `str(error)`, and above all not a traceback. An exception raised from inside a frame
        holding a mnemonic must not be trusted to be free of it, and a crash renderer drawing that
        frame would defeat every measure in `docs/secret-hygiene.md` in one screenful — at the
        exact moment the user is staring at the display.
        """
        self.fatal_message = describe(error)
        return self.fatal_message

    def _handle_exception(self, error: Exception) -> None:
        """Replace Textual's crash renderer, which is `Traceback(show_locals=True)`.

        Overriding a private method is not something to do lightly, and it is the right call here:
        the default is not a style choice we dislike, it is a renderer that prints local variables
        of every frame on the stack. There is no public hook for this, and leaving the default in
        place would make the appliance's central promise false.
        """
        self._return_code = 1
        if self._exception is None:
            self._exception = error
            self._exception_event.set()
        self._exit_renderables.append(self.fatal(error))
        self._close_messages_no_wait()
