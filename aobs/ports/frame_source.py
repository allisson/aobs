"""`FrameSource`: where camera frames come from, and the named ways it can fail.

Two adapters, which is what makes this a seam rather than a hypothetical one: V4L2 `mmap`
capture on the appliance, and image files in the harness. Frames are *images*, never decoded
payload strings — faking at the payload level would skip `zxing-cpp`, the component most likely
to surprise us, and prove only that our parser can read our own output.

`CameraError` and `CameraReason` are declared **here** rather than beside the V4L2 code that
raises them, and #19 is why. A failure both adapters can produce and the user interface must put
a sentence to is part of this contract: `aobs/ui/` may not import `aobs.adapters.real`, so a
reason living there could only reach a screen as prose to be matched on, and the harness could
only stage a failure by raising something the appliance never raises. Two ways to spell one
failure is the one thing a harness may not have.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from enum import Enum
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


class CameraReason(str, Enum):
    """Why a frame source could not produce frames — one name per condition.

    The names exist so a screen can say what happened without matching on an exception message
    written for a different audience. `docs/failure-states.md` holds the sentence each one gets;
    this declares only that the four are distinct, which is the part the adapters must honour.

    `NO_CAPTURE_DEVICE` is the one that is ambiguous in the world and not in this enum: no video
    node is what a machine with no webcam looks like *and* what a **late arrival** looks like.
    Separating those two is `UsbBus`'s job, never this one's.
    """

    NO_CAPTURE_DEVICE = "no-capture-device"
    NO_USABLE_FORMAT = "no-usable-format"
    NO_BUFFERS = "no-buffers"
    NO_FRAMES = "no-frames"


class CameraError(OSError):
    """The camera cannot produce frames the appliance can use.

    An `OSError` on purpose: `SignerApp._camera_present` and `ScanScreen.scan_once` both already
    read that as "no camera" and "the camera is gone", and the adapters are written to those two
    contracts rather than asking them to learn a third exception.
    """

    def __init__(self, reason: CameraReason, message: str) -> None:
        super().__init__(message)
        #: Which condition this was. The message stays for a human reading a traceback that this
        #: appliance will never print; the screen reads this.
        self.reason = reason


class FrameSource(Protocol):
    def frames(self) -> Iterator[Frame]:
        """Yield frames until the source is exhausted or the caller stops asking."""
        ...

    def close(self) -> None: ...
