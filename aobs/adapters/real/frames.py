"""The `FrameSource` real adapter: V4L2 `mmap` capture.

Direct V4L2 from Python through `ioctl` and memory-mapped buffers — no display server, no capture
library. That is #6's finding carried into code; the decode library is `zxing-cpp`, already pinned
in `build/apk-versions.txt` and already exercised by the test tier.

Everything decidable without a camera lives in `aobs/adapters/real/v4l2.py` and is tested there.
What is left here is the glue, kept short because it is the part no test in this repository
covers — `docs/boot-checklist.md` items 12 and 13 are its verification procedure.

**What the two callers already expect of this, unchanged:**

* `SignerApp._camera_present` pulls exactly one frame before any secret exists and treats *nothing
  yielded* and `OSError` alike as "no camera". A machine with no webcam therefore reaches the home
  screen with the outbound paths offered and the scan paths disabled.
* `ScanScreen` turns an `OSError` mid-scan into the camera-lost screen, and its own `on_unmount`
  closes the iterator. **A leaked descriptor is a camera that works once per session**, so opening
  and releasing are both tied to the generator: the probe's `close()` releases the buffers and the
  file descriptor before the scan screen opens a stream of its own.
"""

from __future__ import annotations

import fcntl
import mmap
import os
import select
from collections.abc import Iterator
from pathlib import Path

from . import v4l2
from aobs.ports.frame_source import Frame

DEVICE_ROOT = Path("/dev")

#: Buffers in the driver's queue. Three is enough that the device is never left with nothing to
#: fill while a frame is being converted, and few enough that the oldest queued frame is never far
#: behind — which, with `S_PARM` set to the scan screen's own rate, is what keeps the viewfinder
#: showing where the camera is pointed *now*.
BUFFER_COUNT = 3

#: How long a single `DQBUF` may wait before the device is called gone. Generous against the
#: 5 fps the device was asked for, and short enough that an unplugged camera reaches the
#: camera-lost screen rather than hanging the session.
FRAME_TIMEOUT_SECONDS = 2.0


class V4L2FrameSource:
    """Capture device in, `Frame`s out. One stream at a time."""

    def __init__(self) -> None:
        self._stream: Iterator[Frame] | None = None

    def frames(self) -> Iterator[Frame]:
        self.close()
        self._stream = self._capture()
        return self._stream

    def close(self) -> None:
        """Release whatever the last `frames()` opened. Idempotent."""
        stream = self._stream
        self._stream = None
        if stream is not None:
            close = getattr(stream, "close", None)
            if close is not None:
                close()

    # --- the glue -----------------------------------------------------------------------------

    def _capture(self) -> Iterator[Frame]:
        """Open, negotiate, stream, and release on the way out however this generator ends.

        Raises `CameraError` — an `OSError` — when there is no usable camera, when the device
        offers no format the appliance can read, and when the device stops answering mid-stream.
        Both callers already read `OSError`, and the distinction between the three is not one
        either of them can act on differently: a camera that cannot be used is a session with no
        camera.
        """
        path = self._find_device()
        if path is None:
            raise v4l2.CameraError("no capture device")

        fd = os.open(path, os.O_RDWR)
        buffers: list[mmap.mmap] = []
        streaming = False
        try:
            pixelformat, width, height, bytes_per_line = self._negotiate(fd)
            self._set_rate(fd)
            buffers = self._map_buffers(fd)
            for index in range(len(buffers)):
                fcntl.ioctl(fd, v4l2.VIDIOC_QBUF, _buffer(index))
            fcntl.ioctl(fd, v4l2.VIDIOC_STREAMON, _buf_type())
            streaming = True
            while True:
                index, used = self._dequeue_latest(fd)
                raw = buffers[index][:used]
                fcntl.ioctl(fd, v4l2.VIDIOC_QBUF, _buffer(index))
                yield Frame(
                    width=width,
                    height=height,
                    data=v4l2.to_greyscale(
                        pixelformat, raw, width, height, bytes_per_line
                    ),
                )
        finally:
            if streaming:
                try:
                    fcntl.ioctl(fd, v4l2.VIDIOC_STREAMOFF, _buf_type())
                except OSError:  # pragma: no cover - the device is already gone
                    pass
            for buffer in buffers:
                buffer.close()
            os.close(fd)

    def _find_device(self) -> str | None:
        """*Find a capture device*, not *open a fixed path*.

        One physical camera commonly registers two nodes — UVC adds a metadata node — and only one
        of them captures, so every candidate is asked what it is.
        """
        candidates: list[tuple[str, int]] = []
        for node in sorted(DEVICE_ROOT.glob("video*"), key=lambda p: _index(p.name)):
            try:
                fd = os.open(node, os.O_RDWR)
            except OSError:
                continue
            try:
                raw = fcntl.ioctl(fd, v4l2.VIDIOC_QUERYCAP, bytes(v4l2.CAPABILITY.size))
                _, _, _, _, capabilities, device_caps = v4l2.CAPABILITY.unpack(raw)
            except OSError:
                continue
            finally:
                os.close(fd)
            candidates.append(
                (str(node), v4l2.effective_capabilities(capabilities, device_caps))
            )
        return v4l2.choose_capture_device(candidates)

    def _negotiate(self, fd: int) -> tuple[int, int, int, int]:
        """Ask for a format the appliance can convert, and read back what was actually set."""
        chosen = v4l2.choose_format(self._offered_formats(fd))
        if chosen is None:
            raise v4l2.CameraError("the camera offers no format the appliance can read")
        request = v4l2.FORMAT.pack(
            v4l2.BUF_TYPE_VIDEO_CAPTURE,
            v4l2.PREFERRED_WIDTH,
            v4l2.PREFERRED_HEIGHT,
            chosen,
            v4l2.FIELD_ANY,
            *(0,) * 8,
        )
        raw = fcntl.ioctl(fd, v4l2.VIDIOC_S_FMT, request)
        (
            _type,
            width,
            height,
            pixelformat,
            _field,
            bytes_per_line,
            *_rest,
        ) = v4l2.FORMAT.unpack(raw)
        if pixelformat not in v4l2.PREFERRED_FORMATS:
            # `S_FMT` is allowed to answer with something other than what was asked for.
            raise v4l2.CameraError("the camera offers no format the appliance can read")
        return pixelformat, width, height, bytes_per_line

    def _offered_formats(self, fd: int) -> list[int]:
        formats: list[int] = []
        for index in range(64):  # a bound, not an expectation: no camera enumerates this many
            request = v4l2.FMTDESC.pack(
                index, v4l2.BUF_TYPE_VIDEO_CAPTURE, 0, b"", 0, 0
            )
            try:
                raw = fcntl.ioctl(fd, v4l2.VIDIOC_ENUM_FMT, request)
            except OSError:
                break  # EINVAL is how the enumeration ends
            formats.append(v4l2.FMTDESC.unpack(raw)[4])
        return formats

    def _set_rate(self, fd: int) -> None:
        """Ask the device for the scan screen's own rate. Advisory: not every driver honours it."""
        request = v4l2.STREAMPARM.pack(
            v4l2.BUF_TYPE_VIDEO_CAPTURE, 0, 0, 1, v4l2.TARGET_FRAME_RATE, 0, 0
        )
        try:
            fcntl.ioctl(fd, v4l2.VIDIOC_S_PARM, request)
        except OSError:  # pragma: no cover - a device that will not be paced still captures
            pass

    def _map_buffers(self, fd: int) -> list[mmap.mmap]:
        request = v4l2.REQUESTBUFFERS.pack(
            BUFFER_COUNT, v4l2.BUF_TYPE_VIDEO_CAPTURE, v4l2.MEMORY_MMAP, 0, 0
        )
        raw = fcntl.ioctl(fd, v4l2.VIDIOC_REQBUFS, request)
        count = v4l2.REQUESTBUFFERS.unpack(raw)[0]
        if count == 0:
            raise v4l2.CameraError("the camera granted no capture buffers")
        buffers = []
        for index in range(count):
            queried = v4l2.BUFFER.unpack(
                fcntl.ioctl(fd, v4l2.VIDIOC_QUERYBUF, _buffer(index))
            )
            offset, length = queried[16], queried[17]
            buffers.append(
                mmap.mmap(fd, length, mmap.MAP_SHARED, mmap.PROT_READ, offset=offset)
            )
        return buffers

    def _dequeue_latest(self, fd: int) -> tuple[int, int]:
        """The newest frame the driver has, not the oldest.

        The device free-runs; if converting a frame took longer than the device's period, the
        queue holds a frame that is already stale. Dropping to the newest is what keeps the
        viewfinder showing where the camera is pointed now, and costs the scan nothing — the same
        UR fragment is re-emitted every cycle (`docs/qr-emit-parameters.md`).
        """
        index, used = self._dequeue(fd, FRAME_TIMEOUT_SECONDS)
        while select.select([fd], [], [], 0)[0]:
            fcntl.ioctl(fd, v4l2.VIDIOC_QBUF, _buffer(index))
            index, used = self._dequeue(fd, 0)
        return index, used

    def _dequeue(self, fd: int, timeout: float) -> tuple[int, int]:
        if not select.select([fd], [], [], timeout)[0]:
            raise v4l2.CameraError("the camera stopped producing frames")
        dequeued = v4l2.BUFFER.unpack(fcntl.ioctl(fd, v4l2.VIDIOC_DQBUF, _buffer(0)))
        return dequeued[0], dequeued[2]


def _buf_type() -> bytes:
    return v4l2.BUF_TYPE_VIDEO_CAPTURE.to_bytes(4, "little")


def _buffer(index: int) -> bytes:
    """A zeroed `v4l2_buffer` naming an index, which is all three of the queue calls need."""
    return v4l2.BUFFER.pack(
        index,
        v4l2.BUF_TYPE_VIDEO_CAPTURE,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        b"",
        0,
        v4l2.MEMORY_MMAP,
        0,
        0,
        0,
        0,
    )


def _index(name: str) -> int:
    """`video10` sorts after `video2`, which lexicographic order gets wrong."""
    digits = name[len("video") :]
    return int(digits) if digits.isdigit() else 1 << 30
