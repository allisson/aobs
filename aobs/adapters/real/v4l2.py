"""The half of V4L2 capture that can be decided without a camera.

Structure layouts, the `ioctl` request numbers built from them, which pixel format to ask for,
which node to open, and the conversion from whatever the device produced to the `FrameSource`
port's contract — 8-bit greyscale, row-major, `width * height` bytes. All of it pure functions of
their arguments, which is where #48 put the tests: this is the bulk of the risk, and none of it
needs a device.

`aobs/adapters/real/frames.py` holds the `ioctl` glue that calls into here. Nothing in this module
opens anything.

**The port's contract is unchanged and the conversion is why.** Whatever the device offers becomes
greyscale before it crosses the port, so neither the viewfinder nor `zxing-cpp` ever learns what a
pixel format is.
"""

from __future__ import annotations

import struct
from collections.abc import Sequence

# --- ioctl request numbers -------------------------------------------------------------------
#
# `_IOC(dir, type, nr, size)` from `include/uapi/asm-generic/ioctl.h`, on the one architecture
# this appliance is built for (amd64). They are written as an expression rather than as magic
# hex so that the size in each one is visibly the size of the structure below it — which is the
# thing that would be wrong if a layout here were wrong.

_IOC_WRITE = 1
_IOC_READ = 2


def _ioc(direction: int, kind: str, number: int, size: int) -> int:
    return (direction << 30) | (size << 16) | (ord(kind) << 8) | number


# --- structures ---------------------------------------------------------------------------------
#
# Little-endian and explicitly padded, so the layout is what the kernel's is rather than what this
# machine's compiler would have chosen. Every `struct` here is round-tripped against a known byte
# layout in the suite.

#: `struct v4l2_capability`: driver, card, bus_info, version, capabilities, device_caps, reserved.
CAPABILITY = struct.Struct("<16s32s32sIII12x")

#: `struct v4l2_fmtdesc`: index, type, flags, description, pixelformat, mbus_code, reserved.
FMTDESC = struct.Struct("<III32sII12x")

#: `struct v4l2_pix_format`, the only member of `v4l2_format`'s union this appliance uses. The
#: union is pointer-aligned (`v4l2_window` holds a `v4l2_clip *`), which is why `fmt` starts at
#: offset 8 and the whole thing is 208 bytes rather than 204.
FORMAT = struct.Struct("<I4xIIIIIIIIIIII152x")

#: `struct v4l2_requestbuffers`: count, type, memory, capabilities, flags, reserved.
REQUESTBUFFERS = struct.Struct("<IIIIB3x")

#: `struct v4l2_buffer`. The `timeval` at offset 24 forces four bytes of padding after `field`,
#: and the `m` union is a pointer, so the whole is 88 bytes on amd64.
BUFFER = struct.Struct("<IIIII4xqqIIBBBB4sIIQIIi4x")

#: `struct v4l2_streamparm` with its capture arm: type, capability, capturemode, timeperframe,
#: extendedmode, readbuffers.
STREAMPARM = struct.Struct("<IIIIIII176x")

VIDIOC_QUERYCAP = _ioc(_IOC_READ, "V", 0, CAPABILITY.size)
VIDIOC_ENUM_FMT = _ioc(_IOC_READ | _IOC_WRITE, "V", 2, FMTDESC.size)
VIDIOC_S_FMT = _ioc(_IOC_READ | _IOC_WRITE, "V", 5, FORMAT.size)
VIDIOC_REQBUFS = _ioc(_IOC_READ | _IOC_WRITE, "V", 8, REQUESTBUFFERS.size)
VIDIOC_QUERYBUF = _ioc(_IOC_READ | _IOC_WRITE, "V", 9, BUFFER.size)
VIDIOC_QBUF = _ioc(_IOC_READ | _IOC_WRITE, "V", 15, BUFFER.size)
VIDIOC_DQBUF = _ioc(_IOC_READ | _IOC_WRITE, "V", 17, BUFFER.size)
VIDIOC_STREAMON = _ioc(_IOC_WRITE, "V", 18, 4)
VIDIOC_STREAMOFF = _ioc(_IOC_WRITE, "V", 19, 4)
VIDIOC_S_PARM = _ioc(_IOC_READ | _IOC_WRITE, "V", 22, STREAMPARM.size)

# --- enumerations ----------------------------------------------------------------------------

BUF_TYPE_VIDEO_CAPTURE = 1
MEMORY_MMAP = 1
FIELD_ANY = 0

CAP_VIDEO_CAPTURE = 0x00000001
CAP_STREAMING = 0x04000000
CAP_DEVICE_CAPS = 0x80000000


def fourcc(code: str) -> int:
    return int.from_bytes(code.encode("ascii"), "little")


#: The formats this appliance accepts, **in preference order**, and the order is the statement:
#: `GREY` needs no conversion at all, then the two packed 4:2:2 formats every USB webcam offers,
#: then the planar ones whose luma plane is already what the port wants.
#:
#: Compressed formats are deliberately absent. `MJPG` would put a JPEG decoder on the appliance —
#: a dependency `docs/boot-pipeline.md`'s package table does not carry, inside the path that also
#: feeds the entropy mixer. A camera offering only formats on no list here is a camera problem,
#: and the user is told so rather than shown a black viewfinder.
PREFERRED_FORMATS: tuple[int, ...] = (
    fourcc("GREY"),
    fourcc("YUYV"),
    fourcc("UYVY"),
    fourcc("NV12"),
    fourcc("YU12"),  # I420
    fourcc("YV12"),
)

#: What the appliance asks the device for. #3 fixed the QR at 77 modules across a 1024x768
#: console; 640x480 leaves several sensor pixels per module at a normal working distance, and is
#: the one size every UVC camera supports. The driver is free to answer with something else and
#: `S_FMT` reports what it actually chose, which is what the adapter then uses.
PREFERRED_WIDTH = 640
PREFERRED_HEIGHT = 480

#: The rate the adapter asks the device to produce at. It is **the rate the scan screen already
#: assumes** — `aobs.ui.screens.scan.INBOUND_FRAME_RATE`, measured by #6 against Sparrow's
#: `ANIMATION_PERIOD_MILLIS = 200` — and the suite asserts the two are the same number. The
#: adapter invents no pacing of its own: the scan screen owns the timer, this owns producing a
#: frame when asked. Matching the two is what keeps queued buffers from going stale.
TARGET_FRAME_RATE = 5


class CameraError(OSError):
    """The camera cannot produce frames the appliance can use.

    An `OSError` on purpose: `SignerApp._camera_present` and `ScanScreen.scan_once` both already
    read that as "no camera" and "the camera is gone", and this adapter is written to those two
    contracts rather than asking them to learn a third exception.
    """


def choose_format(offered: Sequence[int]) -> int | None:
    """The format to ask for, from what the device enumerated. `None` if none is usable."""
    for candidate in PREFERRED_FORMATS:
        if candidate in offered:
            return candidate
    return None


def choose_capture_device(candidates: Sequence[tuple[str, int]]) -> str | None:
    """Which video node to open, from `(path, capabilities)` pairs.

    Discovery is *find a capture device*, not *open a fixed path*: a machine with two video nodes
    for one physical camera is ordinary — UVC registers a metadata node alongside the capture
    one — and only one of them captures. The first candidate that reports both capture and
    streaming wins, in the order given, so `/dev/video0` beats `/dev/video1` when both qualify.
    """
    for path, capabilities in candidates:
        if capabilities & CAP_VIDEO_CAPTURE and capabilities & CAP_STREAMING:
            return path
    return None


def effective_capabilities(capabilities: int, device_caps: int) -> int:
    """What *this node* can do, which is not always what the driver can do.

    `capabilities` is the union across every node the driver registers; `device_caps` is the one
    that was opened, and is only meaningful when the driver says so. Reading the union is exactly
    how a metadata node gets mistaken for a capture node.
    """
    return device_caps if capabilities & CAP_DEVICE_CAPS else capabilities


#: The formats whose first plane is already 8-bit luma at the given stride. `GREY` is that by
#: definition; the planar YUV ones carry Y whole before any chroma.
_LUMA_PLANE_FIRST = frozenset(
    {fourcc("GREY"), fourcc("NV12"), fourcc("YU12"), fourcc("YV12")}
)


def to_greyscale(
    pixelformat: int, data: bytes, width: int, height: int, bytes_per_line: int
) -> bytes:
    """One captured buffer to the port's contract: `width * height` luma bytes, row-major.

    `bytes_per_line` is the device's stride and is **not** assumed to equal the image width — a
    driver may pad rows, and odd dimensions are exactly where this kind of code breaks.
    """
    if pixelformat in _LUMA_PLANE_FIRST:
        step = 1
        start = 0
    elif pixelformat == fourcc("YUYV"):
        step, start = 2, 0
    elif pixelformat == fourcc("UYVY"):
        step, start = 2, 1
    else:
        raise CameraError("the camera produced a format the appliance cannot read")

    needed = (height - 1) * bytes_per_line + start + (width - 1) * step + 1
    if bytes_per_line < width * step or len(data) < needed:
        raise CameraError("the camera produced a short frame")

    out = bytearray(width * height)
    for row in range(height):
        begin = row * bytes_per_line + start
        line = data[begin : begin + width * step]
        out[row * width : (row + 1) * width] = line[::step] if step != 1 else line
    return bytes(out)

