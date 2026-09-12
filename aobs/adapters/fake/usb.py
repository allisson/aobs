"""The `UsbBus` harness adapter: a bus whose answer is whatever the test staged.

Two implementations of one interface, which is the test a port has to pass here: this is not the
sysfs walk under a different root, it is a different way of knowing. Staging *a camera enumerated
too late* needs no `/sys` and no device, and the appliance's own half stays the only thing that
ever touches the filesystem.

The answer may change between calls, because the behaviour worth testing is that it is asked more
than once: the home screen re-reads the bus on every composition, and the bug this exists for is a
first reading taken too early.
"""

from __future__ import annotations

from collections.abc import Sequence

from aobs.ports.usb_bus import LateArrival


class FixedUsbBus:
    """Answers with the arrivals it was handed. Empty — nothing arrived late — is the default."""

    def __init__(self, arrivals: Sequence[LateArrival] = ()) -> None:
        self.arrivals = tuple(arrivals)
        #: How many times the bus was asked. The home screen's contract is that it re-reads, and
        #: a test can hold this to it without reaching into Textual's composition.
        self.reads = 0

    def late_arrivals(self) -> tuple[LateArrival, ...]:
        self.reads += 1
        return self.arrivals
