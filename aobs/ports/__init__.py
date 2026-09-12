"""The five ports.

`docs/test-harness.md` fixes them, and each has exactly two adapters. This package declares the
interfaces; `aobs/adapters/fake/` holds the harness half and `aobs/adapters/real/` the
appliance's.

There was another name here once, `Screen`, and it was wrong. Its two adapters were "Textual on
the console" and "Textual `run_test()`" — the *same* application under two drivers, not two
implementations of an interface — so the port sat between two halves of one thing. The app is the
display seam now, driven headless by `run_test()`, and `Keymap` took the vacated slot: applying a
keyboard layout really does have two implementations, `loadkeys` and a recorder.

`UsbBus` was added fifth by #19 and had to pass that same test plus a second one. `aobs/ui/app.py`
refuses `release` a port because *reading one file has one implementation, and the seam the tests
need is this value being passed in* — which is true of a value read once before the app starts and
false here: the bus is read again on every home-screen composition, and the whole failure being
chased is a first reading taken too early. A sysfs walk and a fixed set of readings are two
implementations, the way `getrandom(2)` and fixed bytes are.
"""

from .entropy_source import EntropySource
from .frame_source import CameraError, CameraReason, Frame, FrameSource
from .keymap import DEFAULT_LAYOUT, Keymap
from .power import Power
from .usb_bus import LateArrival, UsbBus

__all__ = [
    "DEFAULT_LAYOUT",
    "CameraError",
    "CameraReason",
    "EntropySource",
    "Frame",
    "FrameSource",
    "Keymap",
    "LateArrival",
    "Power",
    "UsbBus",
]
