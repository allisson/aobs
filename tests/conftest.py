"""Shared fixtures.

The mnemonic every test derives from is the one printed in BIP39 itself, so nothing in this
repository is ever a live wallet (`docs/test-harness.md`). It lives here rather than in eight test
modules so that "the test seeds are published vectors" is one fact in one place.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest
import qrcode
from qrcode.constants import ERROR_CORRECT_L

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


#: Eight screen pixels per QR module, as in `tests/test_qr_loopback.py`: the appliance's console is
#: 1024x768 for a 77x77 code, so this is the same order of magnitude a camera would see.
SCALE = 8


def render_qr(payload: str | bytes, directory: Path, index: int = 0) -> Path:
    """One frame, as an image file — which is what the `FrameSource` fake reads.

    Actual images, decoded by the same `zxing-cpp` the appliance uses. Handing the decoder a string
    instead would skip the component most likely to surprise us, which is the whole reason the
    `FrameSource` port carries frames and not payloads.
    """
    code = qrcode.QRCode(error_correction=ERROR_CORRECT_L, border=4, box_size=SCALE)
    code.add_data(payload)
    code.make(fit=True)
    path = directory / f"frame-{index:03d}.png"
    code.make_image().save(path)
    return path


def render_qrs(payloads: Sequence[str | bytes], directory: Path) -> list[Path]:
    return [render_qr(payload, directory, index) for index, payload in enumerate(payloads)]
