"""The harness half of every port.

Five ports, each with exactly two adapters — this package is one of the two, and
`aobs/adapters/real/` is the other: V4L2 `mmap` capture, the kernel CSPRNG, `loadkeys`, a forced
power-off and the USB bus read out of sysfs. Nothing in `aobs/ui/` knows which of the two it was
handed, which is what keeps the whole application drivable headless with no conditional inside it.

There is no display fake, and that is the point of its absence: the app itself is the display
seam, and tests drive the real `SignerApp` headless through Textual's `run_test()`.
"""

from .entropy import FixedEntropySource
from .frames import ImageFileFrameSource
from .keymap import RecordingKeymap
from .power import RecordingPower
from .usb import FixedUsbBus

__all__ = [
    "FixedEntropySource",
    "FixedUsbBus",
    "ImageFileFrameSource",
    "RecordingKeymap",
    "RecordingPower",
]
