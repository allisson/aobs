"""Numbered slots a user types words into. Two vocabularies, **two different rules**.

Read this before touching either entry screen, because the merge is the obvious refactor and it
is wrong:

* **BIP39 resolves at four characters.** The list is genuinely unique there — 2048 distinct
  4-prefixes — so `mnemonic.resolve()` completes a word the user has not finished typing, and
  four characters is all anyone ever has to spell.
* **The EFF large wordlist does not.** `docs/export-password.md` measured it: **5,502 of its
  7,776 words are still ambiguous at four characters**, and uniqueness arrives only at the full
  word. So `export_password.resolve()` accepts an exact word and nothing else.

Same widget, different wordlist, different rule. `Vocabulary` is the seam that keeps both true at
once, and it is the only place the difference is written down as code rather than as prose. The
grid itself never counts characters: it asks the vocabulary to resolve what was typed, and the
vocabulary's own rule is the answer.

Beyond the rule, the shape is settled by `docs/seed-entry.md`:

**An editable grid, not a wizard**, because a checksum failure names no word. The user has to be
able to go to slot 17, change it and retry without retyping the sixteen they got right — a wizard
forces that retype, and the retype is where a *second* error is introduced.

**Space or enter commits the word.** Every word, not only the short ones, and the reason is a
measured collision rather than a preference. Committing automatically the moment four characters
resolve would have to guess where the next word begins, and it guesses wrong: after `crue` has
resolved to `cruel`, the `l` that starts `lounge` is indistinguishable from the `l` that finishes
`cruel`. One generated 24-word seed drawn at random held **three** such adjacencies — `cruel
lounge`, `merit twelve`, `gospel exchange` — so auto-committing silently eats the first letters of
the next word for exactly the user who is taking the shortcut. The separator costs one keystroke a
word and removes the whole class.

It is also what makes the 49 BIP39 words that are prefixes of other words enterable at all (`add`
/ `addict` / `address`): a three-letter word can never reach four characters, and without an
explicit commit auto-resolution would have to guess or stall.

**The resolution is shown as it happens.** A slot being typed into displays the word its buffer
resolves to, so `crue` reads as `cruel` before it is committed — the user sees what the appliance
has understood rather than trusting it.

**Numeric index entry is rejected.** It exists for devices with four buttons; this appliance has
a keyboard.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Static

from aobs.core import export_password, mnemonic

#: Slots per row. Four columns fit 24 words in six rows inside the 96-column block, which is what
#: keeps the whole grid on the smallest console the appliance will start on.
COLUMNS = 4

#: Width of one cell: `"12  "` plus the longest word in either list, plus the typing cursor.
CELL = 20


@dataclass(frozen=True)
class Vocabulary:
    """A wordlist and the rule for resolving a word in it.

    The rule lives inside `resolve`, which is the point: the grid asks *is this a word yet* and
    never *how many characters is enough*, so the four-character asymmetry between the two lists
    cannot leak into shared code and be "unified" away.
    """

    #: How the list is named to the user. A rejection says which list it read from, because a
    #: user with two pieces of paper in front of them has to know which one is being checked.
    name: str
    resolve: Callable[[str], str | None]

    @property
    def rejected(self) -> str:
        return f"That is not a word in the {self.name}."


BIP39 = Vocabulary(
    name="BIP39 list",
    # Resolves a four-character prefix, because BIP39 is genuinely unique there.
    resolve=mnemonic.resolve,
)

EFF = Vocabulary(
    name="EFF large wordlist",
    # Exact words only. 5,502 of 7,776 are still ambiguous at four characters — see the module
    # docstring, and do not "unify" this with BIP39's rule.
    resolve=export_password.resolve,
)

#: The characters a word may contain. `-` is in the EFF list and is kept, because the list is
#: published with its hyphens and pruning it would make us un-checkable against EFF's own file.
WORD_CHARACTERS = set("abcdefghijklmnopqrstuvwxyz-")

CURSOR = "_"


class WordGrid(Vertical):
    """`slots` numbered cells, freely navigable, one of them being typed into."""

    DEFAULT_CSS = f"""
    WordGrid {{ height: auto; margin: 1 0; }}
    WordGrid .grid-row {{ height: auto; }}
    WordGrid .slot {{ width: {CELL}; }}
    WordGrid .slot-current {{ text-style: bold; }}
    WordGrid #grid-message {{ margin-top: 1; }}
    """

    def __init__(self, vocabulary: Vocabulary, slots: int, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self.vocabulary = vocabulary
        #: Plain attributes, never Textual reactives: `docs/secret-hygiene.md` rules the
        #: general-purpose widgets out for exactly this, and seed words are the secret it is about.
        self._words: list[str] = [""] * slots
        self._cursor = 0
        #: What has been typed into the current slot and not yet committed.
        self._typed = ""
        self._message = ""
        #: Which cell the cursor was on when the grid was last drawn. A keystroke changes at most
        #: two cells, and redrawing all twenty-four of them per keystroke is work for nothing.
        self._painted = 0

    # --- what the screens read ----------------------------------------------------------------

    @property
    def slots(self) -> int:
        return len(self._words)

    @property
    def cursor(self) -> int:
        return self._cursor

    @property
    def words(self) -> tuple[str, ...]:
        return tuple(self._words)

    @property
    def filled(self) -> bool:
        return all(self._words)

    @property
    def message(self) -> str:
        return self._message

    def say(self, message: str) -> None:
        """What the screen wants said under the grid — a checksum failure, a wrong password."""
        self._message = message
        self.query_one("#grid-message", Static).update(self._message)

    def on_unmount(self) -> None:
        """Let go of the words. They are in RAM regardless, and holding them in a torn-down
        widget for the rest of the session is the dwell `docs/secret-hygiene.md` shortens."""
        self._words = [""] * len(self._words)
        self._typed = ""

    # --- typing --------------------------------------------------------------------------------

    def type_character(self, character: str) -> None:
        character = character.lower()
        if character not in WORD_CHARACTERS:
            return
        self._message = ""
        self._typed += character
        self._repaint()

    def commit(self) -> None:
        """Space or enter: take what the buffer resolves to, and move to the next slot.

        Whatever the vocabulary resolves — a four-character BIP39 prefix, a whole EFF word, a
        three-letter word that is a prefix of two others. Anything it does not resolve is rejected
        here, in this slot, before anything downstream is attempted.
        """
        if not self._typed:
            self._advance()
            return
        word = self.vocabulary.resolve(self._typed)
        if word is None:
            self._message = self.vocabulary.rejected
            self._repaint()
            return
        self._words[self._cursor] = word
        self._advance()

    def backspace(self) -> None:
        self._message = ""
        if self._typed:
            self._typed = self._typed[:-1]
        elif self._words[self._cursor]:
            self._words[self._cursor] = ""
        elif self._cursor > 0:
            self._cursor -= 1
            self._words[self._cursor] = ""
        self._repaint()

    # --- navigation ------------------------------------------------------------------------------

    def move(self, delta: int) -> None:
        """Go to another slot. A resolvable buffer is kept; anything else is dropped and said so.

        Free navigation is the point of the grid: a checksum failure names no word, so the user
        must be able to reach slot 17 alone.
        """
        if self._typed:
            word = self.vocabulary.resolve(self._typed)
            if word is not None:
                self._words[self._cursor] = word
            else:
                self._message = self.vocabulary.rejected
        self._cursor = max(0, min(len(self._words) - 1, self._cursor + delta))
        self._typed = ""
        self._repaint()

    def _advance(self) -> None:
        self._typed = ""
        if self._cursor < len(self._words) - 1:
            self._cursor += 1
        self._repaint()

    # --- drawing -----------------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        for start in range(0, len(self._words), COLUMNS):
            with Horizontal(classes="grid-row"):
                for index in range(start, min(start + COLUMNS, len(self._words))):
                    yield Static("", classes="slot", id=f"slot-{index}")
        yield Static("", id="grid-message")

    def on_mount(self) -> None:
        for index in range(len(self._words)):
            self._paint(index)
        self.query_one("#grid-message", Static).update(self._message)

    def _cell(self, index: int) -> str:
        """A slot shows its word, or what is being typed into it — resolved as far as it goes.

        Showing the resolution live is what makes the four-character rule visible rather than
        magic: `crue` reads as `cruel` before the space that commits it, so the user checks the
        appliance's understanding instead of trusting it.
        """
        number = f"{index + 1:>2}"
        if index != self._cursor:
            return f"{number}  {self._words[index]}"
        if self._typed:
            return f"{number}  {self.vocabulary.resolve(self._typed) or self._typed}{CURSOR}"
        if self._words[index]:
            return f"{number}  {self._words[index]}"
        return f"{number}  {CURSOR}"

    def _paint(self, index: int) -> None:
        cell = self.query_one(f"#slot-{index}", Static)
        cell.update(self._cell(index))
        cell.set_class(index == self._cursor, "slot-current")

    def _repaint(self) -> None:
        """The cell that changed and the one the cursor left, and nothing else."""
        for index in {self._painted, self._cursor}:
            self._paint(index)
        self._painted = self._cursor
        self.query_one("#grid-message", Static).update(self._message)
