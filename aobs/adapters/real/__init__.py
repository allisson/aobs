"""The appliance's half of every port.

Four ports, each with exactly two adapters — this package is the other one. Nothing here is
imported by `aobs/ui/`, which knows only the ports; `aobs/__main__.py` is the single module that
names these classes, which is what keeps the whole application drivable with the fakes and free of
any conditional asking what it is running on.

Each adapter is split the same way, and the split is the testing decision from #48 rather than a
style: **everything decidable without hardware is a pure function**, tested directly in the
container with no mocks and no devices, and the syscall glue around it is kept short enough to
read in one sitting because it is the part no test in this repository covers.
"""

from .entropy import KernelEntropySource
from .frames import V4L2FrameSource
from .keymap import LoadkeysKeymap
from .power import ForcedPowerOff

__all__ = [
    "ForcedPowerOff",
    "KernelEntropySource",
    "LoadkeysKeymap",
    "V4L2FrameSource",
]
