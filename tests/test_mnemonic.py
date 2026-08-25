"""BIP39 word entry: the four-character prefix, used where it is actually true."""

from __future__ import annotations

import pytest

from aobs.core import export_password
from aobs.core.mnemonic import BIP39_PREFIX, candidates, is_valid, resolve, wordlist

from conftest import VECTOR_MNEMONIC


def test_bip39_is_unique_at_four_characters() -> None:
    """The measurement the asymmetry rests on. If a future wordlist broke this, the prefix
    shortcut would have to go with it."""
    words = wordlist()
    assert len(words) == 2048
    assert len({word[:BIP39_PREFIX] for word in words}) == len(words)


def test_the_eff_list_is_not_unique_at_four_and_the_two_rules_differ() -> None:
    eff = export_password.wordlist()
    assert len({word[:4] for word in eff}) < len(eff)
    # BIP39 entry takes the prefix…
    assert resolve("aban") == "abandon"
    # …and export-password entry does not, on the same four characters.
    assert export_password.resolve("aban") is None


@pytest.mark.parametrize(
    ("typed", "expected"),
    [
        ("aban", "abandon"),
        ("abandon", "abandon"),
        ("ABAN", "abandon"),
        ("  zon  ", None),  # three characters is not yet a word
        ("  zoo  ", "zoo"),  # …and a three-character word is one
        ("zone", "zone"),
        ("abandoned", None),  # a longer string that is not the word
        ("zzzz", None),
        ("", None),
    ],
)
def test_resolve(typed: str, expected: str | None) -> None:
    assert resolve(typed) == expected


def test_candidates_narrow_as_the_user_types() -> None:
    assert candidates("aban") == ("abandon",)
    assert len(candidates("ab")) > 1
    assert candidates("") == ()


def test_the_checksum_is_what_decides_a_mnemonic() -> None:
    assert is_valid(VECTOR_MNEMONIC)
    assert not is_valid("abandon " * 12)  # every word valid, checksum wrong
    assert not is_valid("not even words")
