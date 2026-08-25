"""The recovery words on screen — after generation, and on demand for the rest of the session.

One screen for both, because they are the same screen: numbered words, and nothing else. What
differs is only what `F10` does next.

**After generation it leads to the read-back, and the reason is not the obvious one.** The BIP39
checksum does not help here: the appliance holds the correct words, and what can be wrong is *the
paper*. The checksum only fires later, on import from that paper — by which time the wallet may
hold funds and the paper may be the only copy. **Read-back is the only check on the paper, and
nothing else performs it** (`docs/seed-entry.md`).

**On demand it leads nowhere**, and that is the rule: *show recovery words* is an explicit action
and never a step on the way to anything else, so 24 words reach the screen only when the user
asked for them. This is the contested half of the document and it is allowed — the words are in
RAM regardless, so refusing protects almost nothing, while a user who cannot check their paper
against the appliance either trusts a backup they never verified or writes down a second guess.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Static

from aobs.ui.widgets.wordgrid import CELL, COLUMNS

WRITE_THEM_DOWN = (
    "Write these down, in this order, on paper. They are the whole wallet: anyone who has them "
    "has the funds, and nobody who loses them gets the funds back."
)

#: The read-back is the price of the only check that will ever be made on the paper, and the
#: screen says the price rather than springing it.
NEXT_IS_READ_BACK = "F10 asks you to type all of them back, from the paper."

CONTINUE_KEYS = "F10 check what you wrote  ·  esc back  ·  F12 power off"
LOOK_KEYS = "esc done  ·  F12 power off"


class RecoveryWordsScreen(Screen):
    """`words`, numbered. Holds them for as long as it is mounted and no longer."""

    BINDINGS = [
        # Never `enter`, never `esc` — `docs/failure-states.md`.
        Binding("f10", "read_back", "Check what you wrote"),
    ]

    DEFAULT_CSS = f"""
    RecoveryWordsScreen .words-row {{ height: auto; }}
    RecoveryWordsScreen .word {{ width: {CELL}; }}
    RecoveryWordsScreen #words {{ margin: 1 0; }}
    RecoveryWordsScreen #recovery-keys {{ margin-top: 1; }}
    """

    def __init__(self, mnemonic: str, *, read_back: bool) -> None:
        super().__init__()
        #: A plain attribute, never a Textual reactive (`docs/secret-hygiene.md`).
        self._words = tuple(mnemonic.split())
        self._read_back = read_back

    @property
    def words(self) -> tuple[str, ...]:
        """What is on screen. Public because a read-back has to be checkable against it — from
        the next screen and from a test — without either reaching into this one."""
        return self._words

    def compose(self) -> ComposeResult:
        with Vertical(id="frame"):
            yield Static("Your recovery words", id="title")
            yield Static(WRITE_THEM_DOWN, id="write-them-down")
            with Vertical(id="words"):
                for start in range(0, len(self._words), COLUMNS):
                    with Horizontal(classes="words-row"):
                        for index in range(start, min(start + COLUMNS, len(self._words))):
                            yield Static(
                                f"{index + 1:>2}  {self._words[index]}",
                                classes="word",
                                id=f"word-{index}",
                            )
            if self._read_back:
                yield Static(NEXT_IS_READ_BACK, id="next-is-read-back")
            yield Static(CONTINUE_KEYS if self._read_back else LOOK_KEYS, id="recovery-keys")

    def on_unmount(self) -> None:
        self._words = ()

    def action_read_back(self) -> None:
        """Only on the generate path. On demand this screen leads nowhere, by construction."""
        if not self._read_back:
            return
        self.app.open_read_back(" ".join(self._words))  # type: ignore[attr-defined]
