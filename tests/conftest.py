"""Shared fixtures.

The mnemonic every test derives from is the one printed in BIP39 itself, so nothing in this
repository is ever a live wallet (`docs/test-harness.md`). It lives here rather than in eight test
modules so that "the test seeds are published vectors" is one fact in one place.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path

import pytest

from aobs.core.wallet import Network, Wallet

VECTOR_MNEMONIC = (
    "abandon abandon abandon abandon abandon abandon abandon abandon "
    "abandon abandon abandon about"
)

#: A second published vector mnemonic, for the addresses a fixture needs to be a stranger's.
STRANGER_MNEMONIC = (
    "legal winner thank year wave sausage worth useful legal winner thank yellow"
)

CORPUS = Path(__file__).parent.parent / "fixtures" / "psbt"


@pytest.fixture
def mainnet_wallet() -> Wallet:
    return Wallet.from_mnemonic(VECTOR_MNEMONIC, network=Network.MAINNET)


@pytest.fixture
def signet_wallet() -> Wallet:
    return Wallet.from_mnemonic(VECTOR_MNEMONIC, network=Network.SIGNET)


def fixed_bytes(seed: bytes = b"aobs-test") -> Callable[[int], bytes]:
    """A deterministic stand-in for the `EntropySource` port: a counter through SHA-256.

    Not a constant — a constant would hide a caller that draws the salt and the nonce from the
    same call.
    """
    state = {"n": 0}

    def draw(count: int) -> bytes:
        out = b""
        while len(out) < count:
            out += hashlib.sha256(seed + state["n"].to_bytes(4, "big")).digest()
            state["n"] += 1
        return out[:count]

    return draw
