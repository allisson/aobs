"""The keymap picker: the first screen, before any secret exists.

`docs/boot-pipeline.md` is unusually blunt about why this screen is here at all:

> BIP39 words and the EFF export words are `a-z` and survive almost any Latin layout, but **the
> BIP39 passphrase is arbitrary text**. A user on AZERTY or ABNT2 who types a passphrase through a
> US map creates a wallet they can never reopen — no error, no signal, discovered when the funds
> are gone. That is the worst failure mode in the appliance.

Two consequences shape the screen. **US is the default and one keystroke accepts it**, so the
picker costs nothing to the great majority who do not know or care what a keymap is. And **keys are
echoed as typed**, because a list of layout names proves nothing — the user has to be able to press
`q` and `a` and `;` and see what actually arrives, and this is the only moment in the session when
doing that is free of consequence.

It also carries the **release identity footer** (#61), and it carries it for a reason that has
nothing to do with keymaps: this is the screen a user cannot avoid, and *before you type a mnemonic
into it* is the only moment at which knowing what you booted is worth anything. It is not a
dedicated About screen, because a screen you must navigate to is a screen nobody visits.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.events import Key
from textual.screen import Screen
from textual.widgets import Static

from aobs.ports.keymap import DEFAULT_LAYOUT
from aobs.ui.widgets.release import ReleaseFooter

#: How much of what the user typed stays on screen. Long enough to check a handful of keys,
#: short enough never to wrap inside the column budget.
ECHO_WIDTH = 60


class KeymapScreen(Screen):
    """Choose a keyboard layout and prove it is right by typing on it."""

    BINDINGS = [
        Binding("up", "previous", "Previous layout"),
        Binding("down", "next", "Next layout"),
        # Never `enter`, never `esc` — `docs/failure-states.md`. `F10` is the confirm key the
        # review screen already uses, so the appliance teaches one accept key rather than two.
        Binding("f10", "accept", "Use this layout"),
    ]

    DEFAULT_CSS = """
    KeymapScreen #layouts { height: auto; margin: 1 0; }
    KeymapScreen .layout { margin-left: 2; }
    KeymapScreen .layout-selected { text-style: bold; }
    KeymapScreen #echo { margin-top: 1; }
    """

    def __init__(self) -> None:
        super().__init__()
        self._layouts: tuple[str, ...] = ()
        self._selected: int | None = None
        self._typed = ""

    def compose(self) -> ComposeResult:
        self._layouts = tuple(self.app.keymap.layouts())  # type: ignore[attr-defined]
        if self._selected is None:
            # US is the default because it is the layout the kernel already has loaded, so
            # accepting it is a genuine no-op. Only on the first compose: a recompose must not
            # throw away a choice the user has already made.
            self._selected = (
                self._layouts.index(DEFAULT_LAYOUT) if DEFAULT_LAYOUT in self._layouts else 0
            )
        with Vertical(id="frame"):
            yield Static("Keyboard layout", id="title")
            yield Static(
                "Your seed words are unaffected by this choice. A passphrase is not: typed "
                "through the wrong layout it produces a wallet that cannot be reopened.",
                id="why",
            )
            with Vertical(id="layouts"):
                for index, name in enumerate(self._layouts):
                    yield Static(name, classes="layout", id=f"layout-{index}")
            yield Static("Type anything here to check the layout:", id="echo-prompt")
            yield Static("", id="echo")
            # Last, and reserved: `docs/review-screen.md` counts it against the 85×43 floor.
            yield ReleaseFooter(self.app.release)  # type: ignore[attr-defined]

    def on_mount(self) -> None:
        self._repaint()

    # --- selection ---------------------------------------------------------------------------

    @property
    def selected_layout(self) -> str:
        assert self._selected is not None, "the picker has not composed yet"
        return self._layouts[self._selected]

    def action_previous(self) -> None:
        self._selected = (self._layouts.index(self.selected_layout) - 1) % len(self._layouts)
        self._repaint()

    def action_next(self) -> None:
        self._selected = (self._layouts.index(self.selected_layout) + 1) % len(self._layouts)
        self._repaint()

    def action_accept(self) -> None:
        self.app.accept_keymap(self.selected_layout)  # type: ignore[attr-defined]

    # --- the echo ----------------------------------------------------------------------------

    def on_key(self, event: Key) -> None:
        """Echo what actually arrived, not what we think was pressed.

        Only printable characters: the arrows, `F10` and `esc` are doing their own jobs, and
        echoing a control character would put the attacker's-text problem on the one screen that
        exists to be trusted.
        """
        if not event.is_printable or event.character is None:
            return
        self._typed = (self._typed + event.character)[-ECHO_WIDTH:]
        self.query_one("#echo", Static).update(self._typed)
        event.stop()

    def _repaint(self) -> None:
        for index, name in enumerate(self._layouts):
            widget = self.query_one(f"#layout-{index}", Static)
            chosen = index == self._selected
            widget.update(f"{'>' if chosen else ' '} {name}")
            widget.set_class(chosen, "layout-selected")
