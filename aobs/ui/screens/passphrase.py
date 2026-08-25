"""The passphrase, entered once.

Three decisions from `docs/secret-hygiene.md` and `docs/seed-entry.md`, none of them the reflex:

**Masked, with a reveal key.** Putting a passphrase on screen is a real cost and it is the right
trade: someone in the room is an acknowledged, explicitly undefended tier, whereas a passphrase
silently mistyped through the wrong keymap is a total loss — the appliance's worst failure mode,
with no error anywhere and the funds gone. `aobs/ui/widgets/secretinput.py` explains why the
reveal is until the next keystroke rather than literally a hold: the console delivers no key
releases, and the screen says what it does rather than promising a hold it cannot implement.

**A live character count, always.** A doubled or dropped keystroke is the common error, and
counting is free.

**Confirmed by master fingerprint, never by typing it twice.** Typing it twice is the reflex and
it is both weaker and worse: it doubles the copies by construction, and it cannot catch the
failure that actually matters — a passphrase typed *consistently* through the wrong keymap. The
fingerprint catches that; a second entry does not. So there is exactly one field on this screen,
and the check is the next one.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.events import Key
from textual.screen import Screen
from textual.widgets import Static

from aobs.ui.widgets.secretinput import SecretInput

REVEAL_KEY = "f2"

WHAT_IT_IS = (
    "A passphrase makes a different wallet from the same words. Leave it empty if you do not use "
    "one; there is no wrong answer here, only a different wallet."
)

#: The keymap picker's warning, restated where it bites. Nothing else in the session depends on
#: the layout being right.
KEYMAP = (
    "Type it exactly as you did before. Through the wrong keyboard layout it makes a wallet that "
    "cannot be reopened, with no error shown anywhere."
)

KEYS = "F2 show it until the next key  ·  F10 done  ·  esc back  ·  F12 power off"


class PassphraseScreen(Screen):
    """One `SecretInput`, a count, and `F10`."""

    BINDINGS = [
        Binding(REVEAL_KEY, "reveal", "Show it"),
        # Never `enter`, never `esc` — `docs/failure-states.md`.
        Binding("f10", "accept", "Done"),
    ]

    DEFAULT_CSS = """
    PassphraseScreen #passphrase-keymap { margin-top: 1; }
    PassphraseScreen #passphrase-field { margin-top: 1; }
    PassphraseScreen #passphrase-count { margin-top: 1; }
    PassphraseScreen #passphrase-keys { margin-top: 1; }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="frame"):
            yield Static("Passphrase", id="title")
            yield Static(WHAT_IT_IS, id="passphrase-what")
            yield Static(KEYMAP, id="passphrase-keymap")
            yield SecretInput(id="passphrase-field")
            yield Static("", id="passphrase-count")
            yield Static(KEYS, id="passphrase-keys")

    def on_mount(self) -> None:
        self._repaint()

    @property
    def field(self) -> SecretInput:
        return self.query_one("#passphrase-field", SecretInput)

    # --- keys ------------------------------------------------------------------------------------

    def on_key(self, event: Key) -> None:
        """Every printable character, including the ones a wordlist would reject: a passphrase is
        arbitrary text, which is exactly why the keymap matters here and nowhere else."""
        if event.key == "backspace":
            self.field.backspace()
        elif event.key == "space":
            self.field.type_character(" ")
        elif event.is_printable and event.character is not None:
            self.field.type_character(event.character)
        else:
            return
        self._repaint()
        event.stop()

    def action_reveal(self) -> None:
        self.field.reveal()
        self._repaint()

    def action_accept(self) -> None:
        self.app.finish_wallet(self.field.take())  # type: ignore[attr-defined]

    def _repaint(self) -> None:
        self.query_one("#passphrase-count", Static).update(
            f"{self.field.length} characters"
        )
