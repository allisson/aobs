"""Interop: frames captured from Sparrow, Green and Blue Wallet.

The loopback proves self-consistency; this proves we read *their* output. It reads whatever is in
`fixtures/wallet_frames/` — adding a capture is adding files, per that directory's README.

The corpus is empty today. That is recorded as a gap in the README rather than papered over, and
this module skips rather than passing quietly, so an empty corpus never reads as a clean interop
result.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import zxingcpp
from PIL import Image

from aobs.adapters.fake import ImageFileFrameSource
from aobs.core.urcodec import PsbtCollector
from aobs.ports.frame_source import Frame

CAPTURES = Path(__file__).parent.parent / "fixtures" / "wallet_frames"

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp"}


def _captures() -> list[Path]:
    return sorted(path.parent for path in CAPTURES.glob("*/capture.json"))


def _decode(frame: Frame) -> str | None:
    image = Image.frombytes("L", (frame.width, frame.height), frame.data)
    results = zxingcpp.read_barcodes(image)
    return results[0].text if results else None


@pytest.mark.parametrize("capture", _captures(), ids=lambda path: path.name)
def test_a_captured_stream_reassembles_to_the_wallets_own_psbt(capture: Path) -> None:
    meta = json.loads((capture / "capture.json").read_text())
    frames = sorted(
        path for path in capture.iterdir() if path.suffix.lower() in IMAGE_SUFFIXES
    )
    assert frames, f"{capture.name} has a capture.json and no frames"

    collector = PsbtCollector()
    source = ImageFileFrameSource(frames)
    for frame in source.frames():
        text = _decode(frame)
        if text is None:
            continue  # a frame the decoder could not read costs a cycle, not the scan
        if collector.receive(text):
            break
    source.close()

    psbt_bytes = collector.result()
    assert hashlib.sha256(psbt_bytes).hexdigest() == meta["expected_psbt_sha256"]


def test_the_corpus_is_present() -> None:
    if not _captures():
        pytest.skip(
            "no captured wallet frames yet — see fixtures/wallet_frames/README.md. "
            "The loopback test proves self-consistency; this is the interop half and it is a "
            "known gap."
        )
