"""`Frame` in, decoded payload or `None` out. The whole of the appliance's inbound decode.

It lives in `aobs/ui/` rather than in `aobs/core/`, and the reason is the seam rather than taste:
`Frame` is defined in `aobs/ports/`, and `tests/test_structure.py` forbids the core from importing
a port. So the one module that turns camera bytes into a payload sits on the app side of the line,
and stays free of Textual so it can be tested against rendered images with no application at all.

**Both views of the payload are returned, because the appliance has two kinds of inbound QR.** UR
parts are text (`docs/qr-emit-parameters.md`: uppercased, alphanumeric mode); the encrypted wallet
QR is *binary byte mode, no base64* (`docs/encrypted-wallet-qr.md`), so its magic and version bytes
can only be checked against the raw bytes. Guessing at the raw bytes by re-encoding the text is how
a container gets misread as a foreign QR.

**The frame is handed over as a buffer, never as a decoded image (#24).** `zxing-cpp` reads a
`zxingcpp.ImageView` — a pointer, dimensions and a pixel format — and `Frame` already promises
exactly that: 8-bit greyscale, row-major, `width * height` bytes. Wrapping it in a `PIL.Image`
first was one line, and the price was an image library in the image: an AVIF decoder and a
bundled `libavif`, fed by camera frames, which are the only bytes on this appliance that come
from outside it. `ImageFormat.Lum` names the format the port already guarantees rather than
inferring it from the shape of a `memoryview` cast, which is the other way the buffer could be
passed and the way that hides the assumption.
"""

from __future__ import annotations

from dataclasses import dataclass

import zxingcpp

from aobs.ports.frame_source import Frame


@dataclass(frozen=True)
class Decoded:
    """One QR read out of one frame, in the two forms the callers need."""

    text: str
    raw: bytes


def decode_frame(frame: Frame) -> Decoded | None:
    """The first QR in `frame`, or `None` when the frame carries none.

    `None` is the ordinary case, not an error: at 5 fps most frames of a scan are the user still
    aiming, and a frame that fails to decode fails *to* decode — QR's own checksum and UR's
    per-part CRC32 mean it never decodes wrongly.
    """
    view = zxingcpp.ImageView(
        frame.data, frame.width, frame.height, zxingcpp.ImageFormat.Lum
    )
    results = zxingcpp.read_barcodes(view)
    if not results:
        return None
    result = results[0]
    return Decoded(text=result.text, raw=bytes(result.bytes))
