"""BIP39 word entry, where the four-character prefix is true.

`docs/export-password.md` measured the asymmetry and it is the whole reason this module and
`export_password` do not share one: **BIP39 is unique at four characters and the EFF large list is
not.** 5,502 of the EFF list's 7,776 words are still ambiguous at four; every BIP39 word is
settled there. The shortcut is used where it holds and forbidden where it does not — and a user
must never confuse the two lists, which is why the vocabularies stay visibly different.
"""

from __future__ import annotations

from functools import lru_cache

from .vendor.embit import bip39

#: The number of characters BIP39 guarantees to be unique. A property test asserts it.
BIP39_PREFIX = 4

WORD_COUNTS = (12, 15, 18, 21, 24)


@lru_cache(maxsize=1)
def wordlist() -> tuple[str, ...]:
    """The 2,048 English BIP39 words, as embit ships them."""
    return tuple(bip39.WORDLIST)


@lru_cache(maxsize=1)
def _by_prefix() -> dict[str, str]:
    return {word[:BIP39_PREFIX]: word for word in wordlist()}


def resolve(typed: str) -> str | None:
    """The word a user typed, from the full word or from its first four characters.

    Returns None for anything else — a prefix shorter than four characters is not yet a word, and
    the entry screen keeps narrowing rather than guessing.
    """
    text = typed.strip().lower()
    if not text:
        return None
    if text in set(wordlist()):
        return text
    if len(text) >= BIP39_PREFIX:
        word = _by_prefix().get(text[:BIP39_PREFIX])
        # A longer string must still *be* that word: "abandoned" is not "abandon".
        if word is not None and word.startswith(text):
            return word
    return None


def candidates(prefix: str) -> tuple[str, ...]:
    """Words starting with `prefix`, for entry that narrows as the user types."""
    start = prefix.strip().lower()
    if not start:
        return ()
    return tuple(word for word in wordlist() if word.startswith(start))


def is_valid(mnemonic: str) -> bool:
    """Whether a mnemonic's words and its BIP39 checksum both hold."""
    try:
        bip39.mnemonic_to_bytes(mnemonic.strip())
    except Exception:
        return False
    return True


def from_entropy(entropy: bytes) -> str:
    """The mnemonic BIP39 entropy spells.

    Here rather than in the screens so that nothing in `aobs/ui/` imports the vendored library:
    the generate path and the restore path both hold entropy and both need the words.
    """
    return bip39.mnemonic_from_bytes(entropy)
