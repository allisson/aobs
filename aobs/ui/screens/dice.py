"""The dice screen: one optional screen, offered before generation.

`docs/seed-entry.md` settles the wording rather than the placement, and the wording is the whole
decision:

> **"roll dice if you don't trust this machine's random number generator."** Never "add more
> entropy", never a bar filling toward "secure".

Two consequences follow, and both are load-bearing:

**A user who skips is shown no degraded state.** No warning, no amber anything, no bar short of
full — because `docs/entropy-mixing.md` settled that the 256 bits are no weaker than the strongest
single contributing source, and the kernel CSPRNG is a required argument to `mix()`. Skipping does
not degrade the guarantee, so nothing on the way out may imply that it does.

**There is no quota and no minimum.** Dice are additive: the roll count and the bits they carry
are shown as they accumulate, and the user stops when they like. `DICE_BITS_PER_ROLL` is log2(6),
stated as a fact and never as a target to fill.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.events import Key
from textual.screen import Screen
from textual.widgets import Static

from aobs.core.constants import DICE_BITS_PER_ROLL

#: Verbatim, and asserted verbatim. Changing this sentence is changing the decision.
OFFER = "Roll dice if you don't trust this machine's random number generator."

HOW = "Press 1 to 6 for each roll. Backspace undoes one. There is no number you have to reach."

#: What `F10` does with no rolls at all, said plainly and with nothing attached to it. A user who
#: skips is not warned, because there is nothing to warn about.
SKIP = "Press F10 to go on. With no rolls, the wallet comes from the kernel's own randomness."

KEYS = "F10 generate the wallet  ·  esc back  ·  F12 power off"

FACES = "123456"


class DiceScreen(Screen):
    """Rolls in, a roll string out. It computes no entropy and estimates nothing."""

    BINDINGS = [
        # Never `enter`, never `esc` — `docs/failure-states.md`.
        Binding("f10", "generate", "Generate the wallet"),
    ]

    DEFAULT_CSS = """
    DiceScreen #dice-how { margin-top: 1; }
    DiceScreen #dice-count { margin-top: 1; text-style: bold; }
    DiceScreen #dice-keys { margin-top: 1; }
    """

    def __init__(self) -> None:
        super().__init__()
        #: The ASCII roll string, exactly as `mix()` wants it. Never bit-packed: that would
        #: sidestep mod-6 bias rather than correcting for it (`docs/entropy-mixing.md`).
        self._rolls = ""

    def compose(self) -> ComposeResult:
        with Vertical(id="frame"):
            yield Static("Dice", id="title")
            yield Static(OFFER, id="dice-offer")
            yield Static(HOW, id="dice-how")
            yield Static(SKIP, id="dice-skip")
            yield Static("", id="dice-count")
            yield Static(KEYS, id="dice-keys")

    def on_mount(self) -> None:
        self._repaint()

    def on_unmount(self) -> None:
        self._rolls = ""

    # --- rolling -------------------------------------------------------------------------------

    @property
    def rolls(self) -> str:
        return self._rolls

    def on_key(self, event: Key) -> None:
        if event.character in tuple(FACES):
            self._rolls += event.character
        elif event.key == "backspace":
            self._rolls = self._rolls[:-1]
        else:
            return
        self._repaint()
        event.stop()

    def _repaint(self) -> None:
        """A count and the bits it carries. Not a bar, not a score, not a tick."""
        bits = len(self._rolls) * DICE_BITS_PER_ROLL
        self.query_one("#dice-count", Static).update(
            f"rolls: {len(self._rolls)}  ·  bits contributed: {bits:.1f}"
        )

    # --- generation -----------------------------------------------------------------------------

    def action_generate(self) -> None:
        self.app.generate_wallet(self._rolls)  # type: ignore[attr-defined]
