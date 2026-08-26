"""Twenty addresses at a time — the check that the descriptor export landed intact.

A distinct second purpose to the scan flow, and worth naming on the screen rather than leaving to
be inferred: after exporting the descriptor, the user confirms the watch-only wallet derives the
same addresses. A mismatch means a corrupted or substituted descriptor, and it is catchable
exactly once, at setup, before any funds move (`docs/address-verification.md`).

**This path does need a script-type toggle**, where the scan path does not: here the user is
choosing what to look at, rather than presenting something for the appliance to check. On the
scan path the `bc1q`/`bc1p` prefix has already answered the question.

**Full addresses, grouped in fours, never a middle ellipsis** — the same rule as the review
screen, for the opposite reason. There it exists because the user should *not* be eye-verifying
proven change; here they genuinely are comparing, and this is the formatting built for it.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.events import Key
from textual.screen import Screen
from textual.widgets import Static

from aobs.core.address import page
from aobs.core.constants import ADDRESS_PAGE_SIZE
from aobs.core.wallet import RECEIVE_CHAIN, ScriptType
from aobs.ui import addresstext

#: Same key, same meaning as everywhere else it appears: a state change that confirms nothing.
SCRIPT_TYPE_KEY = "f9"


class AddressListScreen(Screen):
    BINDINGS = [
        Binding("up", "previous_page", "Previous twenty"),
        Binding("down", "next_page", "Next twenty"),
        Binding(SCRIPT_TYPE_KEY, "toggle_script_type", "Script type"),
        # Never `enter`, never `esc` — `docs/failure-states.md`.
        Binding("f10", "jump", "Jump to index"),
    ]

    DEFAULT_CSS = """
    AddressListScreen #address-purpose { margin-bottom: 1; }
    AddressListScreen #address-header { text-style: bold; }
    AddressListScreen #addresses { height: 1fr; margin: 1 0; }
    AddressListScreen #address-jump { margin-top: 1; }
    AddressListScreen #address-keys { margin-top: 1; }
    """

    def __init__(self, script_type: ScriptType = ScriptType.P2WPKH) -> None:
        super().__init__()
        self.script_type = script_type
        self.start = 0
        #: What the user has typed towards a jump. Digits only, and it commits on `F10`.
        self._digits = ""

    @property
    def addresses(self):
        """The twenty on screen. Public so a test asserts the rows rather than their rendering."""
        return page(
            self.app.wallet,  # type: ignore[attr-defined]
            self.script_type,
            chain=RECEIVE_CHAIN,
            start=self.start,
            count=ADDRESS_PAGE_SIZE,
        )

    def compose(self) -> ComposeResult:
        listed = self.addresses
        with Vertical(id="frame"):
            yield Static(addresstext.LIST_TITLE, id="title")
            yield Static(addresstext.LIST_PURPOSE, id="address-purpose")
            yield Static(
                addresstext.list_header(
                    self.app.wallet,  # type: ignore[attr-defined]
                    self.script_type,
                    chain=RECEIVE_CHAIN,
                ),
                id="address-header",
            )
            with VerticalScroll(id="addresses"):
                for row, entry in enumerate(listed):
                    yield Static(addresstext.list_row(entry), id=f"address-{row}")
            yield Static(addresstext.list_position(self.start, len(listed)), id="address-position")
            yield Static(addresstext.jump_prompt(self._digits), id="address-jump")
            yield Static(addresstext.LIST_KEYS, id="address-keys")

    # --- paging ------------------------------------------------------------------------------

    def action_next_page(self) -> None:
        self.start += ADDRESS_PAGE_SIZE
        self._redraw()

    def action_previous_page(self) -> None:
        """Stops at zero. There is no index below it and wrapping to the end of an unbounded
        chain would be inventing a last page."""
        self.start = max(0, self.start - ADDRESS_PAGE_SIZE)
        self._redraw()

    def action_toggle_script_type(self) -> None:
        self.script_type = (
            ScriptType.P2TR if self.script_type is ScriptType.P2WPKH else ScriptType.P2WPKH
        )
        self._redraw()

    # --- jump to an index ----------------------------------------------------------------------

    def on_key(self, event: Key) -> None:
        """Digits accumulate; backspace edits. `F10` is what commits them, and it is a binding.

        Typed inline rather than in a modal: a modal would need its own confirm key, and the
        appliance teaches exactly one.
        """
        if event.character is not None and event.character.isdigit():
            self._digits += event.character
        elif event.key == "backspace":
            self._digits = self._digits[:-1]
        else:
            return
        event.stop()
        self._redraw()

    def action_jump(self) -> None:
        if not self._digits:
            return
        self.start = int(self._digits)
        self._digits = ""
        self._redraw()

    def _redraw(self) -> None:
        self.refresh(recompose=True)
