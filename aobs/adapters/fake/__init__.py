"""The harness half of every port.

Four ports, each with exactly two adapters — this package is one of the two. The real adapters
(V4L2 `mmap` capture, `getrandom`/camera/dice, forced power-off, `loadkeys`) are a later spec;
declaring the ports and shipping these fakes is what keeps the core honest in the meantime.

There is no display fake, and that is the point of its absence: the app itself is the display
seam, and tests drive the real `SignerApp` headless through Textual's `run_test()`.
"""

from .entropy import FixedEntropySource
from .frames import ImageFileFrameSource
from .keymap import RecordingKeymap
from .power import RecordingPower

__all__ = [
    "FixedEntropySource",
    "ImageFileFrameSource",
    "RecordingKeymap",
    "RecordingPower",
]
