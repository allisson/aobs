"""The passphrase entry field, which is deliberately not Textual's `Input`.

`docs/secret-hygiene.md` settled this and is worth quoting, because the reason is stronger than
"an `Input` feels risky":

> A purpose-built entry widget accumulates into **one `bytearray`, zeroed on teardown**, and never
> assigns the secret to a Textual reactive. Reactives are watched, copied and retained **by
> design** — that is what they are for, which makes the general-purpose widget the wrong tool here
> rather than merely a risky one.

**Honest accounting of what that buys.** Per-keystroke `str` objects still come from the event
system and cannot be scrubbed; CPython copies freely and the copies cannot be counted. What this
removes is the one *retained, long-lived, framework-owned* copy — the one that would sit in a
reactive for the rest of the session and could be rendered by an errant refresh. It shortens
dwell. It does not achieve erasure.

**Reveal, and why it is not literally a hold.** The console delivers key presses and no key
releases, so nothing in a terminal can know that a key is still down. The reveal key therefore
shows the passphrase until the *next* keystroke, and the screen says exactly that rather than
promising a hold it cannot implement. `docs/seed-entry.md` accepts putting the passphrase on
screen at all for a reason that is unaffected: someone in the room is an acknowledged, explicitly
undefended tier, whereas a passphrase silently mistyped through the wrong keymap is a total loss.
"""

from __future__ import annotations

from textual.widgets import Static

from aobs.core.secret import SecretBuffer

MASK = "•"

#: Shown while the field is empty, so the row does not silently collapse.
EMPTY = "(no passphrase)"


class SecretInput(Static):
    """One `SecretBuffer`, masked. Holds no reactive and renders nothing unless revealed."""

    DEFAULT_CSS = "SecretInput { height: auto; }"

    def __init__(self, **kwargs: object) -> None:
        super().__init__("", **kwargs)  # type: ignore[arg-type]
        self._buffer = SecretBuffer()
        self._revealed = False

    # --- what the screen drives ----------------------------------------------------------------

    def type_character(self, character: str) -> None:
        self._buffer.append(character)
        # Any keystroke re-masks: the reveal is a look, not a mode to leave the screen in.
        self._revealed = False
        self._repaint()

    def backspace(self) -> None:
        self._buffer.backspace()
        self._revealed = False
        self._repaint()

    def reveal(self) -> None:
        self._revealed = True
        self._repaint()

    @property
    def revealed(self) -> bool:
        return self._revealed

    @property
    def length(self) -> int:
        """The live character count. Always on screen, because a doubled or dropped keystroke is
        the common error and counting is free."""
        return len(self._buffer)

    def take(self) -> str:
        """The passphrase, read once, at the moment it is used to derive."""
        return self._buffer.value()

    # --- lifecycle ------------------------------------------------------------------------------

    def on_mount(self) -> None:
        self._repaint()

    def on_unmount(self) -> None:
        """Zero the buffer, and clear the one thing a reveal put into the widget itself.

        `Static` retains what it was last told to render, so a field torn down while revealed
        would keep the passphrase in `_renderable` for the rest of the session. That is precisely
        the retained copy this widget exists to remove.
        """
        self._revealed = False
        self.update("")
        self._buffer.close()

    def _repaint(self) -> None:
        if self.length == 0:
            self.update(EMPTY)
        elif self._revealed:
            self.update(self._buffer.value())
        else:
            self.update(MASK * self.length)
