"""How many words, asked up front — never detected.

`docs/seed-entry.md` is unambiguous about why this screen exists, and the number is the argument:

> Detection is tempting — accept words and offer *done* whenever the checksum happens to
> validate — and it fails badly at the short end. At 12 words **1 in 16 wrong phrases validates by
> chance**, so a user with a 24-word seed who mistypes early could be handed a perfectly valid
> 12-word wallet that is not theirs, with no error shown anywhere.

The user knows their word count. Asking costs one keystroke and removes a class of silent
wrong-wallet. **Generation does not ask: always 24.**
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Static

from aobs.core.mnemonic import WORD_COUNTS

WHY = "Your seed has one of these lengths. It is asked rather than guessed: a checksum that "
WHY += "happens to pass at twelve words would hand you a valid wallet that is not yours."

KEYS = "up/down choose  ·  F10 type the words  ·  esc back  ·  F12 power off"


class WordCountScreen(Screen):
    BINDINGS = [
        Binding("up", "previous", "Fewer words"),
        Binding("down", "next", "More words"),
        # Never `enter`, never `esc` — `docs/failure-states.md`.
        Binding("f10", "accept", "Type the words"),
    ]

    DEFAULT_CSS = """
    WordCountScreen #counts { height: auto; margin: 1 0; }
    WordCountScreen .count { margin-left: 2; }
    WordCountScreen .count-selected { text-style: bold; }
    WordCountScreen #word-count-keys { margin-top: 1; }
    """

    def __init__(self) -> None:
        super().__init__()
        #: 12 first: it is the shortest and the most common, and no default here can be unsafe —
        #: a wrong choice produces a checksum failure, not a wrong wallet.
        self._selected = 0

    @property
    def selected_count(self) -> int:
        return WORD_COUNTS[self._selected]

    def compose(self) -> ComposeResult:
        with Vertical(id="frame"):
            yield Static("How many words?", id="title")
            yield Static(WHY, id="word-count-why")
            with Vertical(id="counts"):
                for index in range(len(WORD_COUNTS)):
                    yield Static("", classes="count", id=f"count-{index}")
            yield Static(KEYS, id="word-count-keys")

    def on_mount(self) -> None:
        self._repaint()

    def action_previous(self) -> None:
        self._selected = (self._selected - 1) % len(WORD_COUNTS)
        self._repaint()

    def action_next(self) -> None:
        self._selected = (self._selected + 1) % len(WORD_COUNTS)
        self._repaint()

    def action_accept(self) -> None:
        self.app.open_seed_grid(self.selected_count)  # type: ignore[attr-defined]

    def _repaint(self) -> None:
        for index, count in enumerate(WORD_COUNTS):
            widget = self.query_one(f"#count-{index}", Static)
            chosen = index == self._selected
            widget.update(f"{'>' if chosen else ' '} {count} words")
            widget.set_class(chosen, "count-selected")
