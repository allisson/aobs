"""The loopback: PSBT → UR fragments → QR images → the real decoder → reassembly.

`docs/test-harness.md` calls this the highest-value test in the harness, and the reason is the
shape of it: encode, fountain assembly, decode and reassembly are proven in one pass, with no
hardware, against `zxing-cpp` itself. Frames are always actual images — faking at the payload
level would skip the exact component most likely to surprise us.

It proves self-consistency, not interop. The checked-in corpus of frames captured from Sparrow,
Green and Blue Wallet is the other half, and it is a separate module.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import qrcode
import zxingcpp
from PIL import Image
from qrcode.constants import ERROR_CORRECT_H, ERROR_CORRECT_L
from qrcode.util import MODE_ALPHA_NUM, optimal_mode

from aobs.adapters.fake import ImageFileFrameSource
from aobs.core.constants import (
    QR_ECC_ANIMATED,
    QR_ECC_STATIC,
    QR_VERSION_ANIMATED,
    UR_FRAGMENT_LADDER,
    WALLET_QR_TOTAL_BYTES,
)
from aobs.core.wallet import Network
from aobs.core.wallet_qr import Argon2Params, export_wallet
from aobs.core.urcodec import PsbtStream, decode_psbt_parts
from aobs.ports.frame_source import Frame
from aobs.ui import qrcodes

from conftest import fixed_bytes

CORPUS = Path(__file__).parent.parent / "fixtures" / "psbt"

#: Eight screen pixels per QR module. The appliance's console is 1024×768 for a 77×77 code, so
#: this is the same order of magnitude a camera would see.
SCALE = 8


def encode(part: str) -> qrcode.QRCode:
    """`qrcode` rather than `segno`, because `py3-qrcode` is what Alpine packages and the
    authoritative tier installs no wheels from PyPI (`docs/boot-pipeline.md`)."""
    code = qrcode.QRCode(error_correction=ERROR_CORRECT_L, border=4, box_size=SCALE)
    code.add_data(part)
    code.make(fit=True)
    return code


def render(part: str, directory: Path, index: int) -> Path:
    """One frame, as an image file — which is what the `FrameSource` fake reads."""
    path = directory / f"frame-{index:03d}.png"
    encode(part).make_image().save(path)
    return path


def decode(frame: Frame) -> str:
    image = Image.frombytes("L", (frame.width, frame.height), frame.data)
    results = zxingcpp.read_barcodes(image)
    assert results, "zxing-cpp read nothing from the frame"
    return results[0].text


def loopback(psbt_bytes: bytes, tmp_path: Path, *, rung: int = 0) -> tuple[bytes, int]:
    stream = PsbtStream(psbt_bytes, rung=rung)
    parts = stream.cycle()
    paths = [render(part, tmp_path, i) for i, part in enumerate(parts)]

    source = ImageFileFrameSource(paths)
    scanned = [decode(frame) for frame in source.frames()]
    source.close()
    assert source.closed

    return decode_psbt_parts(scanned), stream.seq_len


@pytest.mark.parametrize("name", ["honest_p2wpkh", "honest_p2tr", "many_inputs"])
def test_a_psbt_survives_the_whole_channel_byte_identically(name: str, tmp_path: Path) -> None:
    psbt_bytes = (CORPUS / f"{name}.psbt").read_bytes()
    decoded, _seq_len = loopback(psbt_bytes, tmp_path)
    assert decoded == psbt_bytes


def test_every_rung_of_the_ladder_still_round_trips(tmp_path: Path) -> None:
    """The ladder is a recovery path, so each rung has to work — the tests pin the ladder's
    behaviour, not the belief that 340 bytes works."""
    psbt_bytes = (CORPUS / "honest_p2wpkh.psbt").read_bytes()
    frames_per_rung = []
    for rung in range(len(UR_FRAGMENT_LADDER)):
        directory = tmp_path / f"rung{rung}"
        directory.mkdir()
        decoded, seq_len = loopback(psbt_bytes, directory, rung=rung)
        assert decoded == psbt_bytes
        frames_per_rung.append(seq_len)
    # Stepping down trades frames for density, which is the whole trade being offered.
    assert frames_per_rung == sorted(frames_per_rung)
    assert frames_per_rung[0] < frames_per_rung[-1]


def test_the_frames_fit_the_console_at_version_15(tmp_path: Path) -> None:
    """`docs/qr-emit-parameters.md`: 77×77 modules is what fits, and there is no headroom."""
    psbt_bytes = (CORPUS / "many_inputs.psbt").read_bytes()
    stream = PsbtStream(psbt_bytes)
    assert QR_ECC_ANIMATED == "L"
    for part in stream.cycle():
        assert encode(part).version <= QR_VERSION_ANIMATED
        # Uppercased, so the whole part fits alphanumeric mode: 1.55x the payload for free.
        assert optimal_mode(part.encode()) == MODE_ALPHA_NUM


def test_a_late_receiver_still_converges(tmp_path: Path) -> None:
    """The animation does not stop, and fountain parts past the first cycle are what let a
    receiver that arrived late finish without starting over."""
    psbt_bytes = (CORPUS / "many_inputs.psbt").read_bytes()
    stream = PsbtStream(psbt_bytes)
    seq_len = stream.seq_len
    assert seq_len > 1

    # Miss the whole first cycle, then scan from wherever the animation happens to be.
    for _ in range(seq_len):
        stream.next_part()
    assert stream.cycles_completed == 1

    late = [stream.next_part() for _ in range(seq_len * 3)]
    assert decode_psbt_parts(late) == psbt_bytes


def test_a_dropped_frame_costs_a_cycle_and_not_the_scan(tmp_path: Path) -> None:
    """A frame that fails to decode fails *to decode* — QR's checksum and UR's per-part CRC32
    mean it never decodes wrongly — so ECC L risks latency and not silent corruption."""
    psbt_bytes = (CORPUS / "many_inputs.psbt").read_bytes()
    stream = PsbtStream(psbt_bytes)
    parts = list(stream.cycle())
    dropped = parts[:-1]  # the receiver missed the last deterministic frame

    from aobs.core.urcodec import PsbtCollector

    collector = PsbtCollector()
    for part in dropped:
        assert not collector.receive(part)
    # It converges on the fountain parts that follow, with no restart.
    for _ in range(stream.seq_len * 2):
        if collector.receive(stream.next_part()):
            break
    assert collector.result() == psbt_bytes


#: The pinned version of the static wallet-backup code. 89 bytes of binary at ECC H is a version 9
#: code — 53x53 modules, well inside the console's 77x77 budget. The network byte cost nothing:
#: 88 bytes was version 9 too. Pinned here rather than asserted about in prose.
WALLET_QR_VERSION_PINNED = 9
WALLET_QR_MODULES_PINNED = 53


def test_the_wallet_container_still_fits_ecc_h_and_reads_back(tmp_path: Path) -> None:
    """The container is binary byte mode and is read back through the real decoder.

    The size claim in `docs/encrypted-wallet-qr.md` is the thing under test: a network byte added
    to the header must not push the code past the version the document promises.
    """
    exported = export_wallet(
        bytes(range(32)),
        fixed_bytes(),
        network=Network.SIGNET,
        params=Argon2Params(memory_kib=64, time_cost=1, parallelism=1),
    )
    assert len(exported.container) == WALLET_QR_TOTAL_BYTES == 89
    assert QR_ECC_STATIC == "H"

    # What the export screen itself draws, and the version it comes out at.
    rendered = qrcodes.render(exported.container, ecc=QR_ECC_STATIC)
    assert rendered.version == WALLET_QR_VERSION_PINNED
    assert rendered.modules == WALLET_QR_MODULES_PINNED + 2 * qrcodes.QUIET_ZONE
    assert rendered.version < QR_VERSION_ANIMATED, "and well inside the console's own budget"

    code = qrcode.QRCode(error_correction=ERROR_CORRECT_H, border=4, box_size=SCALE)
    code.add_data(exported.container)
    code.make(fit=True)
    assert code.version == WALLET_QR_VERSION_PINNED

    path = tmp_path / "wallet.png"
    code.make_image().save(path)
    source = ImageFileFrameSource([path])
    frames = list(source.frames())
    source.close()
    image = Image.frombytes("L", (frames[0].width, frames[0].height), frames[0].data)
    results = zxingcpp.read_barcodes(image)
    assert results, "zxing-cpp read nothing from the container's code"
    assert bytes(results[0].bytes) == exported.container
