"""Typing BIP39 words into numbered slots — an import, or a read-back of words just generated.

One screen, because the typing is identical and only the check at the end differs:

* **An import** is checked by the BIP39 checksum. On failure the message says what is true and no
  more — *checksum failed, one or more words are wrong* — with every slot still editable, no guess
  at which one and no *did you mean*. **A checksum failure names no word**, and pretending
  otherwise sends the user to rewrite a slot that was right.
* **A read-back** is checked against the words the appliance is holding. The checksum is useless
  here: the appliance knows the correct words, and what can be wrong is the paper. A failed
  read-back retries **the same words**, never freshly generated ones — what the user has already
  written down stays valid.

The four-character rule, the explicit commit for the 49 prefix-words and the free navigation all
live in `aobs/ui/widgets/wordgrid.py`, along with the reason the export-password grid must not be
merged with this one.
"""

from __future__ import annotations

from aobs.core import mnemonic
from aobs.ui.wordentry import WordEntryScreen
from aobs.ui.widgets.wordgrid import BIP39

#: Verbatim. `docs/seed-entry.md` fixes both what it says and what it refuses to say.
CHECKSUM_FAILED = "Checksum failed — one or more words are wrong. Every slot is still editable."

#: The read-back's failure, which is a statement about the paper rather than about the words.
READ_BACK_FAILED = (
    "That is not what is written above. Check your paper against the words and try again — "
    "these are the same words, not new ones."
)

TYPE_THEM = (
    "Type each word. Four characters are enough for any BIP39 word; space or enter takes a short "
    "word like `add` as it stands."
)

READ_BACK_INTRO = (
    "Type all of them back, from the paper you just wrote. Nothing else ever checks that paper: "
    "the checksum cannot, because the appliance already holds the right words."
)


class SeedEntryScreen(WordEntryScreen):
    """`slots` BIP39 words. `expected` is a read-back; its absence is an import."""

    def __init__(self, slots: int, *, expected: str | None = None) -> None:
        super().__init__(
            "Read your words back" if expected else "Type your seed",
            BIP39,
            slots,
        )
        #: The generated mnemonic when this is a read-back. Held so a failure retries against it.
        self._expected = expected

    def intro(self) -> tuple[str, ...]:
        return (READ_BACK_INTRO,) if self._expected else (TYPE_THEM,)

    def on_unmount(self) -> None:
        self._expected = None

    def accept(self, words: tuple[str, ...]) -> None:
        typed = " ".join(words)
        if self._expected is not None:
            if typed != self._expected:
                # Every slot stays as the user typed it, for the same reason an import's do: the
                # retype is where a second error gets introduced. `esc` shows the words again, and
                # what is on screen here is the transcription to compare against them.
                self.grid.say(READ_BACK_FAILED)
                return
            self.app.begin_passphrase(self._expected)  # type: ignore[attr-defined]
            return

        if not mnemonic.is_valid(typed):
            self.grid.say(CHECKSUM_FAILED)
            return
        self.app.begin_passphrase(typed)  # type: ignore[attr-defined]
