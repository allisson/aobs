"""The screen shape both word grids share: keys in, slots out.

The *rules* differ — see `aobs/ui/widgets/wordgrid.py`, which is where the four-character
asymmetry between BIP39 and the EFF large wordlist is written down. What is genuinely common is
this: the arrows move, printable characters type, space or enter commits, backspace undoes, and
`F10` submits whatever the slots hold to a check the subclass owns.

`enter` is handled here rather than bound, and that is deliberate. `docs/failure-states.md` fixes
the confirm key as per-screen and **never `enter`** — so `enter` must not appear in a screen's
`BINDINGS`. Here it is not a confirm at all: it commits one word into one slot, exactly as space
does, and the screen's confirm stays `F10`.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.events import Key
from textual.screen import Screen
from textual.widgets import Static

from aobs.ui.widgets.wordgrid import COLUMNS, WORD_CHARACTERS, Vocabulary, WordGrid

KEYS = "space or enter commits a word  ·  arrows move  ·  F10 done  ·  esc back  ·  F12 power off"


class WordEntryScreen(Screen):
    """A titled grid of numbered slots. Subclasses decide what a full grid means."""

    BINDINGS = [
        Binding("left", "move_left", "Previous slot"),
        Binding("right", "move_right", "Next slot"),
        Binding("up", "move_up", "A row up"),
        Binding("down", "move_down", "A row down"),
        # Never `enter`, never `esc` — `docs/failure-states.md`.
        Binding("f10", "accept", "Done"),
    ]

    DEFAULT_CSS = """
    WordEntryScreen #word-entry-keys { margin-top: 1; }
    """

    def __init__(self, title: str, vocabulary: Vocabulary, slots: int) -> None:
        super().__init__()
        self._title = title
        self._vocabulary = vocabulary
        self._slots = slots

    # --- what a subclass fills in ---------------------------------------------------------------

    def intro(self) -> tuple[str, ...]:
        """Lines above the grid. What this grid is for, and anything the user must know before
        typing into it."""
        return ()

    def accept(self, words: tuple[str, ...]) -> None:
        """`F10` on a full grid. The subclass checks the words and moves the session on."""
        raise NotImplementedError

    # --- the screen -------------------------------------------------------------------------------

    @property
    def grid(self) -> WordGrid:
        return self.query_one(WordGrid)

    def compose(self) -> ComposeResult:
        with Vertical(id="frame"):
            yield Static(self._title, id="title")
            for index, line in enumerate(self.intro()):
                yield Static(line, id=f"intro-{index}")
            yield WordGrid(self._vocabulary, self._slots)
            yield Static(KEYS, id="word-entry-keys")

    # --- keys ------------------------------------------------------------------------------------

    def on_key(self, event: Key) -> None:
        grid = self.grid
        if event.key in ("space", "enter"):
            grid.commit()
        elif event.key == "backspace":
            grid.backspace()
        elif event.character is not None and event.character.lower() in WORD_CHARACTERS:
            grid.type_character(event.character)
        else:
            # Everything else — the arrows, `F10`, the two global keys — belongs to a binding.
            return
        event.stop()

    def action_move_left(self) -> None:
        self.grid.move(-1)

    def action_move_right(self) -> None:
        self.grid.move(1)

    def action_move_up(self) -> None:
        self.grid.move(-COLUMNS)

    def action_move_down(self) -> None:
        self.grid.move(COLUMNS)

    def action_accept(self) -> None:
        grid = self.grid
        if not grid.filled:
            empty = self._slots - sum(1 for word in grid.words if word)
            grid.say(f"{empty} slot{'' if empty == 1 else 's'} still to fill.")
            return
        self.accept(grid.words)
