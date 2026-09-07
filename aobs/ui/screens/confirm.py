"""The confirm screen: the number, restated, and `y`.

`docs/review-screen.md` settled both halves of why this screen is shaped the way it is.

**`F10` opens it and `y` signs**, deliberately different keys, so a user who mashes `F10` twice
lands here and stops. `y` is safe here precisely because the screen is unreachable by momentum —
there is no way to arrive without a deliberate `F10` from an unlocked review.

**No addresses.** They were just read at full width with the eye doing positional work; a second,
necessarily shallower pass at the moment of commitment *substitutes for the first* rather than
adding to it. The confirm's job is the number, and the NOT PROVEN count travels with it because it
explains why the number is what it is.

`esc` is the global back key, so returning to the review costs nothing and re-scrolls nothing: the
review screen holds its own scroll position and its lock stays open.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Static

from aobs.core.review import Review
from aobs.core.signing import SigningRefused, sign
from aobs.ui import reviewtext


class ConfirmScreen(Screen):
    BINDINGS = [
        # Never `enter`, never `esc` (`docs/failure-states.md`), and not `F10` either: the key
        # that opened this screen must not also be the key that acts on it.
        Binding("y", "sign", "Sign"),
    ]

    DEFAULT_CSS = """
    ConfirmScreen .confirm-line { margin-left: 3; }
    ConfirmScreen #confirm-keys { margin-top: 1; }
    """

    def __init__(self, psbt_bytes: bytes, reviewed: Review) -> None:
        super().__init__()
        self.psbt_bytes = psbt_bytes
        self.reviewed = reviewed

    def compose(self) -> ComposeResult:
        with Vertical(id="frame"):
            yield Static(reviewtext.confirm_title(self.reviewed), id="title")
            for index, line in enumerate(reviewtext.confirm_lines(self.reviewed)):
                yield Static(line, classes="confirm-line", id=f"confirm-{index}")
            yield Static(reviewtext.CONFIRM_KEYS, id="confirm-keys")

    def action_sign(self) -> None:
        """Sign the same bytes the review read, and show them going back out.

        `sign()` reviews again before it signs and refuses by raising — there is no parameter or
        alternate path past a refusal. A refusal here cannot happen after a clean review, and it
        is handled rather than trusted not to.
        """
        # Deferred for the same import cycle `screens/review.py` names: the money path's screens
        # each open the next one.
        from aobs.ui.screens.emit import EmitScreen
        from aobs.ui.screens.refusal import RefusalScreen

        try:
            signed = sign(self.psbt_bytes, self.app.wallet)  # type: ignore[attr-defined]
        except SigningRefused as refused:
            self.app.switch_screen(RefusalScreen(refused.refusal))
            return
        self.app.switch_screen(EmitScreen(signed, self.reviewed.network))
