"""The `FrameSource` fake: frames read from image files.

Actual images, decoded by the same `zxing-cpp` the appliance uses. That is the whole point of
this fake — the loopback test would prove nothing if it handed the decoder a string.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from pathlib import Path

from PIL import Image

from aobs.ports.frame_source import Frame


class ImageFileFrameSource:
    """Yields each image file in order, converted to 8-bit greyscale."""

    def __init__(self, paths: Sequence[Path | str]) -> None:
        self._paths = [Path(path) for path in paths]
        self.closed = False

    def frames(self) -> Iterator[Frame]:
        for path in self._paths:
            with Image.open(path) as image:
                grey = image.convert("L")
                yield Frame(width=grey.width, height=grey.height, data=grey.tobytes())

    def close(self) -> None:
        self.closed = True
