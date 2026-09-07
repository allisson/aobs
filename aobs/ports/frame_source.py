"""`FrameSource`: where camera frames come from.

Two adapters, which is what makes this a seam rather than a hypothetical one: V4L2 `mmap`
capture on the appliance, and image files in the harness. Frames are *images*, never decoded
payload strings — faking at the payload level would skip `zxing-cpp`, the component most likely
to surprise us, and prove only that our parser can read our own output.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Frame:
    """One captured frame: 8-bit greyscale, row-major, `width * height` bytes."""

    width: int
    height: int
    data: bytes

    def __post_init__(self) -> None:
        if len(self.data) != self.width * self.height:
            raise ValueError("frame data does not match its dimensions")


class FrameSource(Protocol):
    def frames(self) -> Iterator[Frame]:
        """Yield frames until the source is exhausted or the caller stops asking."""
        ...

    def close(self) -> None: ...
