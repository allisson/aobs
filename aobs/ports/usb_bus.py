"""`UsbBus`: what the USB bus looks like after PID 1 closed it.

The appliance asks this exactly one question — *did anything arrive too late to be authorised* —
and it asks it because `FrameSource` cannot tell two situations apart that are not the same thing.
No video node is what a machine with no webcam looks like, and it is also what a camera that
enumerated after `authorized_default=0` looks like. The first is a normal session with fewer
paths; the second silently costs an operator every scan path while the appliance says the same
sentence. `docs/failure-states.md` fixes what is said about each.

**This port answers with observations and never with conclusions.** A `LateArrival` says a device
arrived late and what its device descriptor called it. It does not say the device was a camera,
because that is unknowable: an unauthorised device is never given a configuration, so no interface
descriptor is ever read, and the video class lives in the interface. `CONTEXT.md` holds the term
and that limit together, because they are the same fact.

Why this is a port rather than a value passed in, which `aobs/ui/app.py` argues for `release`: the
bus is asked again on every home-screen composition, and a value read once before the app starts
cannot answer differently the second time. Answering the second time is the point — the failure
being chased is one where the first reading was taken too early.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class LateArrival:
    """One USB device that enumerated after the bus was closed to new devices.

    `name` is the device's own product string and is `None` when it has none — plenty of devices
    ship without one, and inventing a placeholder would put a word on screen that no sticker on
    the machine will match.
    """

    vendor_id: str
    product_id: str
    name: str | None


class UsbBus(Protocol):
    def late_arrivals(self) -> tuple[LateArrival, ...]:
        """Every device the kernel has that was not authorised, in a stable order.

        Empty is the ordinary answer and means nothing arrived late — never that the bus could not
        be read. A device whose authorization cannot be determined is left out rather than
        guessed at: a device we cannot classify is not evidence, and counting it would manufacture
        exactly the inference `docs/failure-states.md` refuses to let the appliance make.
        """
        ...
