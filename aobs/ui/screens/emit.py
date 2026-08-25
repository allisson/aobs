"""The signed PSBT going back out: an animated `ur:crypto-psbt` that never stops cycling.

Every parameter is `PsbtStream`'s, from `emit_parameters(rung)` — version 15, ECC L, alphanumeric
mode, 340 payload bytes at 2 fps on the first rung. This screen holds a stream and a rung index and
nothing else (`docs/qr-emit-parameters.md`).

**The animation does not stop.** It cycles the deterministic first `seq_len` parts and then keeps
emitting fountain parts, indefinitely, until the user says the wallet is done. Not a fixed
multiple: the appliance is a kiosk whose entire purpose in that moment is being scanned, and
stopping at any multiple creates a failure whose only recovery is starting over — precisely what
fountain encoding exists to avoid.

**The cycle count is on screen** and doubles as the honest diagnostic. A user on cycle five knows
the wallet is not reading, and that is the moment `F9` earns its place.

**No warning about a long scan.** *Frame 2 of 47* is on screen for every scan anyway, and it tells
the user everything a warning would, at the moment it is actionable, with no click-through reflex
to build.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Center, Vertical
from textual.screen import Screen
from textual.widgets import Static

from aobs.core.urcodec import PsbtStream
from aobs.ui import qrcodes

#: The step-down key. A function key rather than a letter, for the same reason the appliance's
#: three reserved keys are: the keymap is whatever the user chose on the first screen, and `F9`
#: is in the same place on every Latin layout. It sits beside `F10`, and a slip in that direction
#: does something harmless — the code gets less dense.
STEP_DOWN_KEY = "f9"

INSTRUCTION = "Show this to your wallet until it has read the whole code."
KEYS = "F9 smaller code  ·  esc done  ·  F12 power off"
#: What the last rung says instead of offering a step that does not exist.
LAST_RUNG = "This is the least dense code the appliance can show."


class EmitScreen(Screen):
    BINDINGS = [Binding(STEP_DOWN_KEY, "step_down", "Smaller code")]

    DEFAULT_CSS = """
    EmitScreen #qr-row { height: auto; }
    EmitScreen #qr { width: auto; height: auto; }
    EmitScreen #emit-status { margin-top: 1; }
    EmitScreen #emit-keys { margin-top: 1; }
    """

    def __init__(self, signed_psbt: bytes, network: str, *, animate: bool = True) -> None:
        super().__init__()
        self.signed_psbt = signed_psbt
        self.network = network
        self.stream = PsbtStream(signed_psbt)
        #: The suite drives `advance()` itself. Pacing 47 frames at 2 fps would cost it
        #: 23 seconds to assert something that is not Textual's clock.
        self._animate = animate
        self._timer = None
        #: The part currently on screen, so a test can assert the payload rather than its
        #: rendering.
        self.part: str = ""

    def compose(self) -> ComposeResult:
        with Vertical(id="frame"):
            yield Static(f"Signed transaction  ·  {self.network}", id="title")
            with Center(id="qr-row"):
                yield Static("", id="qr")
            yield Static("", id="emit-status")
            yield Static(INSTRUCTION, id="emit-instruction")
            yield Static(KEYS, id="emit-keys")

    def on_mount(self) -> None:
        self.advance()
        self._start()

    def on_unmount(self) -> None:
        self._stop()

    # --- the animation ------------------------------------------------------------------------

    def advance(self) -> None:
        """Draw the next frame. Called by the interval on the appliance, and by the suite
        directly, which runs with no interval at all."""
        self.part = self.stream.next_part()
        self.query_one("#qr", Static).update(qrcodes.render(self.part).text)
        self.query_one("#emit-status", Static).update(self._status())

    def _status(self) -> str:
        parameters = self.stream.parameters
        line = (
            f"Frame {self.stream.frame_in_cycle} of {self.stream.seq_len}"
            f"  ·  cycle {self.stream.cycles_completed + 1}"
            f"  ·  {parameters.fragment_bytes} bytes per frame"
        )
        return line + (f"  ·  {LAST_RUNG}" if parameters.is_last_rung else "")

    def _start(self) -> None:
        if self._animate:
            self._timer = self.set_interval(1 / self.stream.parameters.frame_rate, self.advance)

    def _stop(self) -> None:
        if self._timer is not None:
            self._timer.stop()
            self._timer = None

    # --- the ladder ---------------------------------------------------------------------------

    def action_step_down(self) -> None:
        """One rung down: fewer payload bytes per frame, and a slower frame rate with it.

        A recovery path the user reaches for when a wallet will not read the code — not a
        configuration menu they must understand in advance. On the last rung it does nothing, and
        the status line has already said so.
        """
        if self.stream.parameters.is_last_rung:
            return
        self._stop()
        self.stream = self.stream.stepped_down()
        self.advance()
        self._start()
