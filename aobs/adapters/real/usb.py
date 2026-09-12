"""The `UsbBus` real adapter: every device's `authorized`, read out of sysfs.

Split the way #48 fixed for every adapter here: `late_arrivals` is a pure function of readings
already taken and is where the tests are; `SysfsUsbBus.late_arrivals` is the short walk that takes
them, and is the part no test in this repository covers.

**Why `authorized == 0` is the whole rule, and no class matching happens.** `build/init` flips
`authorized_default=0` *after* the appliance's own devices have enumerated, so every device that
was present in time reads `1`. A `0` is therefore not a judgement about the device; it is the
arithmetic of when it arrived, which is exactly what a **late arrival** is (`CONTEXT.md`).

Matching on `bInterfaceClass` for the video class was the obvious first design and it cannot work.
Linux adds an unauthorised device to sysfs and reads its device descriptor — `usb_new_device()`
calls `usb_enumerate_device()` and `device_add()` with no authorization check — but
`usb_generic_driver_probe()` skips `usb_set_configuration()` for it, and setting a configuration is
what registers interfaces with the driver core. No interface, no `bInterfaceClass`. The class of a
UVC camera lives only there; `bDeviceClass` on the device itself is typically `ef` or `00` and says
nothing. So the reading is *something arrived late*, never *the camera arrived late*.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path

from aobs.ports.usb_bus import LateArrival

DEVICE_ROOT = Path("/sys/bus/usb/devices")

#: The device-level attributes read for each candidate. All three are in `dev_attrs[]` in the
#: kernel's `drivers/usb/core/sysfs.c` and are created unconditionally by `device_add()`, so they
#: are present for an unauthorised device — which is the only reason this adapter can say anything
#: at all. `product` is the exception: it is a string descriptor and plenty of devices have none.
AUTHORIZED = "authorized"
VENDOR_ID = "idVendor"
PRODUCT_ID = "idProduct"
NAME = "product"


def late_arrivals(readings: Sequence[dict[str, str | None]]) -> tuple[LateArrival, ...]:
    """The late arrivals among `readings`, in the order given.

    A reading is one device's attributes, with `None` for anything that could not be read. Three
    rules, and each one is a decision rather than defensive coding:

    * `authorized` must read exactly `0`. Anything else — `1`, absent, unreadable, a value this
      code does not recognise — is **not** a late arrival. A device we cannot classify is not
      evidence, and counting it would put a claim on the home screen built from less than nothing.
    * A missing `idVendor` or `idProduct` drops the device. The identifiers are the entire value of
      reporting it: *one USB device arrived late* with nothing to look up tells an operator only
      that they cannot act.
    * A missing `product` is kept, as `None`. The screen omits the name rather than inventing one.
    """
    found = []
    for reading in readings:
        if (reading.get(AUTHORIZED) or "").strip() != "0":
            continue
        vendor_id = (reading.get(VENDOR_ID) or "").strip()
        product_id = (reading.get(PRODUCT_ID) or "").strip()
        if not vendor_id or not product_id:
            continue
        name = (reading.get(NAME) or "").strip()
        found.append(LateArrival(vendor_id, product_id, name or None))
    return tuple(found)


class SysfsUsbBus:
    """The appliance's half: read `/sys/bus/usb/devices`, decide with `late_arrivals`."""

    def late_arrivals(self) -> tuple[LateArrival, ...]:
        return late_arrivals(list(self._readings()))

    def _readings(self) -> Iterable[dict[str, str | None]]:
        """One dict per device directory, sorted by name so the screen is stable across draws.

        Every failure here is swallowed and the device is simply not reported. This runs on every
        home-screen composition, on a machine whose USB tree can change under it mid-walk, and
        there is nothing a user could do about a sysfs read that failed — `docs/failure-states.md`
        settles that the honest response to not knowing is to say nothing new.
        """
        try:
            directories = sorted(DEVICE_ROOT.iterdir())
        except OSError:
            return
        for directory in directories:
            authorized = _read(directory / AUTHORIZED)
            if authorized is None:
                # Not a device directory, or an attribute this kernel does not have. Either way
                # there is no reading to take, and interfaces (`1-1:1.0`) land here too.
                continue
            yield {
                AUTHORIZED: authorized,
                VENDOR_ID: _read(directory / VENDOR_ID),
                PRODUCT_ID: _read(directory / PRODUCT_ID),
                NAME: _read(directory / NAME),
            }


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
