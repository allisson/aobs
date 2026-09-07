"""The randomness wait: what an uninitialised pool looks like instead of a frozen screen.

`docs/entropy-mixing.md` wrote the sentence this screen exists to show, and it wrote it as a
consequence of a boot decision rather than as a courtesy:

> Boot with `random.trust_cpu=off` and `random.trust_bootloader=off`. […] The cost is that
> `getrandom()` may block, and this appliance has no disk I/O to generate interrupt entropy. What
> it does have is the two device classes #14 permits: a keyboard someone is typing a mnemonic on,
> and a camera producing frames — both generate interrupts, the camera generously.
>
> So entropy-consuming work is sequenced **after** user interaction has begun. If the pool is not
> ready, the appliance says so plainly — *keep typing, point the camera at something* — rather
> than freezing.

Three shapes follow from that, and all three are load-bearing:

**It names those two things and no others**, because they are the only interrupt sources the
permitted device set allows. Advice to "move the mouse" would be advice about a device this
appliance refuses to bind.

**It proceeds by itself.** The user is not asked to press a key when they judge the wait is over —
they have no way to judge it, and the appliance does.

**`esc` leaves it.** A machine whose pool will never initialise must not be a trap: backing out
lands on the dice screen with the rolls still there, and the rest of the session — the outbound
paths — is untouched.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.events import Key
from textual.screen import Screen
from textual.widgets import Static

#: Verbatim, and asserted verbatim. Changing these sentences is changing the decision.
WHY = (
    "The machine has just started and the kernel's pool of randomness is not ready yet. "
    "Nothing is generated until it is."
)

#: The two interrupt sources #14's permitted device set allows, and the only two.
HOW = "Keep typing, and point the camera at something."

PROCEEDS = "Generation continues on its own the moment the pool is ready."

KEYS = "esc back  ·  F12 power off"


class EntropyWaitScreen(Screen):
    """Poll the `EntropySource` until it says the pool is up, then generate."""

    DEFAULT_CSS = """
    EntropyWaitScreen #wait-how { margin-top: 1; text-style: bold; }
    EntropyWaitScreen #wait-proceeds { margin-top: 1; }
    EntropyWaitScreen #wait-keys { margin-top: 1; }
    """

    def __init__(self, dice_rolls: str) -> None:
        super().__init__()
        #: Carried across the wait rather than re-collected. The user rolled these already, and
        #: losing them to a wait they did not ask for would be the appliance's fault, not theirs.
        self.dice_rolls = dice_rolls
        self._timer = None
        self._handed_off = False

    def compose(self) -> ComposeResult:
        with Vertical(id="frame"):
            yield Static("Waiting for randomness", id="title")
            yield Static(WHY, id="wait-why")
            yield Static(HOW, id="wait-how")
            yield Static(PROCEEDS, id="wait-proceeds")
            yield Static(KEYS, id="wait-keys")

    def on_mount(self) -> None:
        interval = self.app.entropy_poll_interval  # type: ignore[attr-defined]
        if interval is not None:
            self._timer = self.set_interval(interval, self.poll_once)

    def on_unmount(self) -> None:
        self._stop()

    def on_key(self, event: Key) -> None:
        """Typing is half of what makes the pool ready, so typing is also when to look again.

        It is not the mechanism — the timer is, and the suite drives `poll_once` directly with no
        timer at all. This only makes the screen answer the moment the thing it asked for works.
        The event is not stopped: `esc` and `F12` are the app's, and this screen wants neither.
        """
        del event
        self.poll_once()

    def poll_once(self) -> None:
        """Ask the port whether the pool is up. Called by the interval, and by the suite."""
        if self._handed_off:
            return  # a late tick, or a keypress arriving behind the one that succeeded
        if self.app.entropy.ready():  # type: ignore[attr-defined]
            self._handed_off = True
            self._stop()
            self.app.entropy_ready(self.dice_rolls)  # type: ignore[attr-defined]

    def _stop(self) -> None:
        if self._timer is not None:
            self._timer.stop()
            self._timer = None
