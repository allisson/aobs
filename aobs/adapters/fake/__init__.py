"""The harness half of every port.

Four ports, each with exactly two adapters — this package is one of the two, and
`aobs/adapters/real/` is the other: V4L2 `mmap` capture, the kernel CSPRNG, `loadkeys` and a
forced power-off. Nothing in `aobs/ui/` knows which of the two it was handed, which is what keeps
the whole application drivable headless with no conditional inside it.

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
