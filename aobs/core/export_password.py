"""The export password: eight EFF large-wordlist words, ~103.4 bits.

`docs/export-password.md` settled three things that shape this module, and each is enforced by
its shape rather than by a rule someone must remember:

* **No user-chosen password.** `generate()` is the only source of one, and nothing in this module
  or in `wallet_qr` accepts a password to encrypt under. The enforcement is the absence of the
  feature.
* **Full-word entry only.** The EFF large list is *not* prefix-unique — 5,502 of its 7,776 words
  are still ambiguous at four characters — so `resolve()` accepts an exact word and nothing else.
  BIP39's four-character shortcut is true of BIP39 and is not true here.
* **The list is the published list.** Hyphens kept, nothing pruned, so anyone can fetch it from
  EFF and check us.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache

from .constants import EXPORT_PASSWORD_WORDS

#: Built by string surgery on `__file__` rather than with `pathlib`, which on Python 3.12 imports
#: `urllib.parse` — and `docs/test-harness.md` asserts the core's module closure pulls in no
#: `urllib`. The appliance is Linux and the harness runs on POSIX, so the separator is `/`.
_WORDLIST_PATH = __file__.rsplit("/", 1)[0] + "/data/eff_large_wordlist.txt"


@lru_cache(maxsize=1)
def wordlist() -> tuple[str, ...]:
    """The 7,776 words, in the file's own order.

    The file is EFF's, dice-roll column and all; only the second column is read.
    """
    words = []
    with open(_WORDLIST_PATH, encoding="utf-8") as handle:
        lines = handle.read().splitlines()
    for line in lines:
        if not line.strip():
            continue
        _roll, word = line.split("\t", 1)
        words.append(word.strip())
    if len(words) != 7776:
        raise ValueError("the EFF large wordlist must have exactly 7776 words")
    return tuple(words)


@dataclass(frozen=True)
class ExportPassword:
    """Eight words, in order.

    Held as words rather than as a string so the read-back can be checked slot by slot, which is
    where a mistranscription is cheap to catch.
    """

    words: tuple[str, ...]

    def __post_init__(self) -> None:
        if len(self.words) != EXPORT_PASSWORD_WORDS:
            raise ValueError(f"an export password is {EXPORT_PASSWORD_WORDS} words")
        for word in self.words:
            if word not in set(wordlist()):
                raise ValueError("word is not in the EFF large wordlist")

    @property
    def text(self) -> str:
        """The form the KDF sees. Space-separated, exactly as the words are shown."""
        return " ".join(self.words)

    def numbered(self) -> tuple[tuple[int, str], ...]:
        """The words as the display needs them: numbered 1–8, one per line."""
        return tuple((i + 1, word) for i, word in enumerate(self.words))

    def read_back_matches(self, typed: list[str] | tuple[str, ...]) -> bool:
        """All eight words, and not a subset: sampling three of eight misses the single
        mistranscribed word 62% of the time."""
        return tuple(typed) == self.words

    def __repr__(self) -> str:  # pragma: no cover - trivial, but load-bearing
        return f"<ExportPassword {EXPORT_PASSWORD_WORDS} words>"

    __str__ = __repr__


def generate(random_bytes: Callable[[int], bytes]) -> ExportPassword:
    """Eight words drawn uniformly from the list.

    `random_bytes` is the caller's randomness — the `EntropySource` port in the appliance, fixed
    bytes in a test. There is no parameter by which a caller supplies words of its own.
    """
    words = tuple(wordlist()[_uniform_index(random_bytes, len(wordlist()))]
                  for _ in range(EXPORT_PASSWORD_WORDS))
    return ExportPassword(words)


def _uniform_index(random_bytes: Callable[[int], bytes], modulus: int) -> int:
    """An index with no modulo bias, by rejection sampling over whole 16-bit draws."""
    limit = (1 << 16) - ((1 << 16) % modulus)
    while True:
        value = int.from_bytes(random_bytes(2), "big")
        if value < limit:
            return value % modulus


# --- Entry ---------------------------------------------------------------------------------------


def resolve(typed: str) -> str | None:
    """The word a user typed, or None.

    Exact matches only. A prefix — however long — is not a word here, and the table in
    `docs/export-password.md` is why: uniqueness arrives only at the full word.
    """
    word = typed.strip().lower()
    return word if word in set(wordlist()) else None


def candidates(prefix: str) -> tuple[str, ...]:
    """Words starting with `prefix`, for autocomplete that narrows as the user types.

    Narrowing the display is not accepting the prefix: `resolve` still requires the full word.
    """
    start = prefix.strip().lower()
    if not start:
        return ()
    return tuple(word for word in wordlist() if word.startswith(start))
