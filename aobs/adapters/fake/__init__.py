"""The harness half of every port.

Four ports, each with exactly two adapters — this package is one of the two. The real adapters
(V4L2 `mmap` capture, Textual on the console, `getrandom`/camera/dice, forced power-off) are a
later spec; declaring the ports and shipping these fakes is what keeps the core honest in the
meantime.
"""

from .entropy import FixedEntropySource
from .frames import ImageFileFrameSource
from .power import RecordingPower
from .screen import TextualScreen

__all__ = [
    "FixedEntropySource",
    "ImageFileFrameSource",
    "RecordingPower",
    "TextualScreen",
]
