"""The appliance's own halves of the four ports.

Two kinds of test here, and the split is #48's testing decision rather than convenience.

**Everything decidable without hardware is a pure function, tested directly** — no mocks, no
devices, no injectable syscall dependency. That is the bulk of the risk: pixel-format conversion,
the format preference order, the V4L2 structure layouts, capture-device selection, and layout-name
validation are all functions from data to data, and they are where this kind of code actually
breaks.

**Three behaviours are patched at the standard-library boundary**, because they must be right and
are not otherwise observable: the non-blocking-then-blocking ordering of the randomness call, that
the keymap loader is invoked exactly once with the chosen layout and that a non-zero result becomes
a failure, and that the power-off issues a forced stop. They are patched at the point the adapter
calls the standard library, which keeps the adapter's own signature clean.

What is **not** here: any assertion that a particular `ioctl` was issued in a particular order.
That tests the transcript of an implementation, fails on the first correct refactor, and catches
nothing a boot would not catch better. The camera's behaviour on real hardware is
`docs/boot-checklist.md` items 12 and 13; the keymap's is item 11; the power-off's is item 4.
"""

from __future__ import annotations

import os
import subprocess

import pytest

from aobs.adapters.real import entropy as real_entropy
from aobs.adapters.real import keymap as real_keymap
from aobs.adapters.real import power as real_power
from aobs.adapters.real import v4l2
from aobs.ports.keymap import DEFAULT_LAYOUT

# --- Keymap: what a directory listing offers ----------------------------------------------------


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("us.map.gz", "us"),
        ("br-abnt2.map.gz", "br-abnt2"),
        ("fr.map", "fr"),
        ("dvorak.kmap.gz", "dvorak"),
        ("defkeymap.kmap", "defkeymap"),
        ("README", None),
        ("include", None),
        ("us.map.gz.bak", None),
    ],
)
def test_a_keymap_filename_yields_its_layout_name(filename: str, expected: str | None) -> None:
    assert real_keymap.layout_name(filename) == expected


@pytest.mark.parametrize("filename", ["-rf.map", "US.map", "../us.map", ".map"])
def test_a_name_that_is_not_a_bare_word_is_not_a_layout(filename: str) -> None:
    """`loadkeys` is given `argv`, not a shell, so this is not an injection guard.

    It is a guard against a name beginning with `-` reaching a loader as an option, and against a
    path component reaching one that searches by name.
    """
    assert real_keymap.layout_name(filename) is None


def test_the_picker_is_offered_the_preferred_maps_that_are_installed_in_that_order() -> None:
    installed = ["it", "fr", "us", "cz", "ru", "de"]
    assert real_keymap.offered(installed) == ("us", "de", "fr", "it")


def test_a_preferred_map_the_image_does_not_ship_is_not_offered() -> None:
    """Offering a map that cannot load is the failure this adapter exists to prevent."""
    assert "br" not in real_keymap.offered(["us", "de"])


@pytest.mark.skipif(
    not os.environ.get("AOBS_AUTHORITATIVE_TIER"),
    reason="the keymap tree is the ISO's userland, so it is only asserted where that is reproduced",
)
def test_every_preferred_map_is_one_the_pinned_image_actually_ships() -> None:
    """The check that the picker's non-US entries can be loaded at all.

    Alpine's `kbd-misc` ships the **xkb** naming — `gb`, not `uk`; `br`, not `br-abnt2`;
    `us-dvorak`, not `dvorak` — so a list copied from the fake would have offered a picker whose
    every non-US entry failed. That failure is silent by nature, which is why it is asserted
    against the pinned userland rather than reasoned about.
    """
    offered = real_keymap.LoadkeysKeymap().layouts()
    assert tuple(offered) == real_keymap.PREFERRED


def test_the_default_layout_is_offered_even_with_no_keymaps_installed() -> None:
    """It is not loaded from a file: it is the map the kernel already has, and accepting it
    applies nothing. An image with no keymap tree still gets one honest entry."""
    assert real_keymap.offered([]) == (DEFAULT_LAYOUT,)


# --- Keymap: the loader ---------------------------------------------------------------------------


class _Loader:
    def __init__(self, returncode: int = 0) -> None:
        self.returncode = returncode
        self.calls: list[list[str]] = []

    def __call__(self, argv, **_kwargs):
        self.calls.append(list(argv))
        return subprocess.CompletedProcess(argv, self.returncode)


def test_accepting_the_default_runs_no_loader_at_all(monkeypatch) -> None:
    """PID 1 already set the console keymap, so accepting US re-applies nothing.

    That is what makes the common case one keypress that cannot fail, rather than one keypress
    that re-runs a program which might.
    """
    loader = _Loader()
    monkeypatch.setattr(subprocess, "run", loader)
    real_keymap.LoadkeysKeymap().apply(DEFAULT_LAYOUT)
    assert loader.calls == []


def test_a_chosen_layout_is_loaded_exactly_once_with_that_name(monkeypatch) -> None:
    loader = _Loader()
    monkeypatch.setattr(subprocess, "run", loader)
    real_keymap.LoadkeysKeymap().apply("br")
    assert loader.calls == [[real_keymap.LOADKEYS, "br"]]


def test_a_loader_that_fails_is_a_named_failure_and_not_a_silent_success(monkeypatch) -> None:
    """The whole reason this port exists. A silently failed application is a passphrase typed
    through the wrong map, which is an unopenable wallet that reports no error."""
    monkeypatch.setattr(subprocess, "run", _Loader(returncode=1))
    with pytest.raises(real_keymap.KeymapError):
        real_keymap.LoadkeysKeymap().apply("fr")


def test_a_missing_loader_is_a_named_failure_too(monkeypatch) -> None:
    def missing(*_args, **_kwargs):
        raise FileNotFoundError(real_keymap.LOADKEYS)

    monkeypatch.setattr(subprocess, "run", missing)
    with pytest.raises(real_keymap.KeymapError):
        real_keymap.LoadkeysKeymap().apply("fr")


def test_a_name_that_is_not_a_layout_never_reaches_the_loader(monkeypatch) -> None:
    loader = _Loader()
    monkeypatch.setattr(subprocess, "run", loader)
    with pytest.raises(real_keymap.KeymapError):
        real_keymap.LoadkeysKeymap().apply("-c")
    assert loader.calls == []


# --- EntropySource: non-blocking first ------------------------------------------------------------


class _Getrandom:
    """`os.getrandom`, refusing the first `blocked` non-blocking calls."""

    def __init__(self, blocked: int) -> None:
        self._blocked = blocked
        #: Every call as `(count, nonblocking)`, which is the ordering under test.
        self.calls: list[tuple[int, bool]] = []

    def __call__(self, count: int, flags: int = 0) -> bytes:
        nonblocking = bool(flags & real_entropy.os.GRND_NONBLOCK)
        self.calls.append((count, nonblocking))
        if nonblocking and self._blocked > 0:
            self._blocked -= 1
            raise BlockingIOError("the pool is not initialised")
        return bytes(count)


def test_the_randomness_call_is_non_blocking_first_and_blocking_only_after(monkeypatch) -> None:
    """The ordering is the point: an uninitialised pool becomes an answerable question rather
    than a syscall the appliance disappears into with nothing on screen."""
    getrandom = _Getrandom(blocked=1)
    monkeypatch.setattr(real_entropy.os, "getrandom", getrandom)
    assert len(real_entropy.KernelEntropySource().random_bytes(32)) == 32
    assert getrandom.calls == [(32, True), (32, False)]


def test_a_ready_pool_is_never_asked_to_block(monkeypatch) -> None:
    getrandom = _Getrandom(blocked=0)
    monkeypatch.setattr(real_entropy.os, "getrandom", getrandom)
    real_entropy.KernelEntropySource().random_bytes(32)
    assert getrandom.calls == [(32, True)]


def test_readiness_is_answered_rather_than_waited_on(monkeypatch) -> None:
    getrandom = _Getrandom(blocked=1)
    monkeypatch.setattr(real_entropy.os, "getrandom", getrandom)
    source = real_entropy.KernelEntropySource()
    assert source.ready() is False
    assert source.ready() is True
    assert all(nonblocking for _count, nonblocking in getrandom.calls)


# --- Power: a forced stop ---------------------------------------------------------------------


def test_the_power_off_forces_a_stop_rather_than_asking_for_a_shutdown(monkeypatch) -> None:
    """There is no init to ask, no filesystem to unmount and no service to stop. The amnesia
    guarantee rests on the machine stopping, not on the application's tidiness."""
    issued: list[int] = []

    class _Libc:
        def reboot(self, command: int) -> int:
            issued.append(command)
            return 0

    monkeypatch.setattr(real_power.ctypes, "CDLL", lambda *_a, **_k: _Libc())
    monkeypatch.setattr(real_power.os, "_exit", lambda code: issued.append(-code))
    real_power.ForcedPowerOff().power_off()
    assert issued[0] == real_power.RB_POWER_OFF


# --- V4L2: the structure layouts ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("layout", "size"),
    [
        (v4l2.CAPABILITY, 104),
        (v4l2.FMTDESC, 64),
        (v4l2.FORMAT, 208),
        (v4l2.REQUESTBUFFERS, 20),
        (v4l2.BUFFER, 88),
        (v4l2.STREAMPARM, 204),
    ],
)
def test_each_structure_is_the_size_the_kernel_uapi_defines(layout, size: int) -> None:
    assert layout.size == size


@pytest.mark.parametrize(
    ("request_number", "known"),
    [
        (v4l2.VIDIOC_QUERYCAP, 0x80685600),
        (v4l2.VIDIOC_ENUM_FMT, 0xC0405602),
        (v4l2.VIDIOC_S_FMT, 0xC0D05605),
        (v4l2.VIDIOC_REQBUFS, 0xC0145608),
        (v4l2.VIDIOC_QUERYBUF, 0xC0585609),
        (v4l2.VIDIOC_QBUF, 0xC058560F),
        (v4l2.VIDIOC_DQBUF, 0xC0585611),
        (v4l2.VIDIOC_STREAMON, 0x40045612),
        (v4l2.VIDIOC_STREAMOFF, 0x40045613),
        (v4l2.VIDIOC_S_PARM, 0xC0CC5616),
    ],
)
def test_each_ioctl_request_matches_the_published_number(request_number: int, known: int) -> None:
    """The request number encodes the structure's size, so these are the layouts above checked
    against a value published independently of this repository."""
    assert request_number == known


def test_a_capture_buffer_round_trips_through_its_layout() -> None:
    """Field order is what a wrong layout gets wrong, and the fields that matter are the index
    and the byte count — a shifted `bytesused` is a frame silently truncated."""
    packed = v4l2.BUFFER.pack(
        2, v4l2.BUF_TYPE_VIDEO_CAPTURE, 4096, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, b"",
        7, v4l2.MEMORY_MMAP, 8192, 4096, 0, 0,
    )
    fields = v4l2.BUFFER.unpack(packed)
    assert (fields[0], fields[2], fields[15], fields[16], fields[17]) == (
        2,
        4096,
        v4l2.MEMORY_MMAP,
        8192,
        4096,
    )


def test_a_pixel_format_round_trips_through_its_layout() -> None:
    packed = v4l2.FORMAT.pack(
        v4l2.BUF_TYPE_VIDEO_CAPTURE,
        640,
        480,
        v4l2.fourcc("YUYV"),
        v4l2.FIELD_ANY,
        1280,
        *(0,) * 7,
    )
    fields = v4l2.FORMAT.unpack(packed)
    assert (fields[1], fields[2], fields[3], fields[5]) == (
        640,
        480,
        v4l2.fourcc("YUYV"),
        1280,
    )


def test_a_capability_round_trips_through_its_layout() -> None:
    packed = v4l2.CAPABILITY.pack(
        b"uvcvideo", b"Integrated Camera", b"usb-0000:00:14.0-4", 0x00060601,
        v4l2.CAP_VIDEO_CAPTURE | v4l2.CAP_DEVICE_CAPS, v4l2.CAP_VIDEO_CAPTURE,
    )
    fields = v4l2.CAPABILITY.unpack(packed)
    assert fields[0].rstrip(b"\0") == b"uvcvideo"
    assert fields[5] == v4l2.CAP_VIDEO_CAPTURE


# --- V4L2: what to ask the device for ------------------------------------------------------------


def test_the_format_asked_for_is_the_first_preferred_one_the_device_offers() -> None:
    offered = [v4l2.fourcc("MJPG"), v4l2.fourcc("YUYV"), v4l2.fourcc("GREY")]
    assert v4l2.choose_format(offered) == v4l2.fourcc("GREY")


def test_the_preference_order_is_stated_and_followed() -> None:
    """`GREY` needs no conversion; the packed 4:2:2 pair is what every USB webcam offers."""
    assert v4l2.choose_format([v4l2.fourcc("UYVY"), v4l2.fourcc("YUYV")]) == v4l2.fourcc(
        "YUYV"
    )


def test_a_camera_offering_nothing_usable_is_a_camera_problem_and_says_so() -> None:
    """Named as a camera problem rather than shown as a black viewfinder: a user who cannot use
    this webcam should swap it, not keep adjusting their aim."""
    assert v4l2.choose_format([v4l2.fourcc("MJPG"), v4l2.fourcc("H264")]) is None


def test_no_compressed_format_is_accepted() -> None:
    """`MJPG` would put a JPEG decoder on the appliance — a dependency the package table does not
    carry — inside the path that also feeds the entropy mixer."""
    assert v4l2.fourcc("MJPG") not in v4l2.PREFERRED_FORMATS


def test_the_adapter_targets_the_rate_the_scan_screen_already_assumes() -> None:
    """The adapter invents no pacing of its own: the scan screen owns the timer."""
    from aobs.ui.screens.scan import INBOUND_FRAME_RATE

    assert v4l2.TARGET_FRAME_RATE == INBOUND_FRAME_RATE


# --- V4L2: which node to open ---------------------------------------------------------------------


def test_the_capture_node_is_chosen_rather_than_a_fixed_path() -> None:
    """One physical camera commonly registers two nodes and only one of them captures."""
    candidates = [
        ("/dev/video0", 0),
        ("/dev/video1", v4l2.CAP_VIDEO_CAPTURE | v4l2.CAP_STREAMING),
    ]
    assert v4l2.choose_capture_device(candidates) == "/dev/video1"


def test_a_capture_node_that_cannot_stream_is_not_chosen() -> None:
    candidates = [("/dev/video0", v4l2.CAP_VIDEO_CAPTURE)]
    assert v4l2.choose_capture_device(candidates) is None


def test_the_first_qualifying_node_wins() -> None:
    both = v4l2.CAP_VIDEO_CAPTURE | v4l2.CAP_STREAMING
    assert (
        v4l2.choose_capture_device([("/dev/video0", both), ("/dev/video1", both)])
        == "/dev/video0"
    )


def test_a_machine_with_no_video_node_at_all_chooses_nothing() -> None:
    assert v4l2.choose_capture_device([]) is None


def test_a_node_reports_its_own_capabilities_and_not_the_drivers_union() -> None:
    """Reading the union is exactly how a metadata node gets mistaken for a capture node."""
    union = v4l2.CAP_VIDEO_CAPTURE | v4l2.CAP_STREAMING | v4l2.CAP_DEVICE_CAPS
    assert v4l2.effective_capabilities(union, 0) == 0


def test_a_driver_that_does_not_report_device_caps_is_read_from_the_union() -> None:
    union = v4l2.CAP_VIDEO_CAPTURE | v4l2.CAP_STREAMING
    assert v4l2.effective_capabilities(union, 0) == union


# --- V4L2: conversion to the port's contract ------------------------------------------------------
#
# The port promises 8-bit greyscale, row-major, `width * height` bytes. Every case below uses a
# stride wider than the image, because a driver padding its rows is ordinary and assuming
# otherwise is where this kind of code breaks.


def test_a_greyscale_frame_is_taken_row_by_row_at_the_devices_stride() -> None:
    data = bytes(range(10))
    assert v4l2.to_greyscale(v4l2.fourcc("GREY"), data, 3, 2, 5) == bytes([0, 1, 2, 5, 6, 7])


def test_yuyv_keeps_the_luma_byte_of_each_pair() -> None:
    data = bytes(range(16))
    assert v4l2.to_greyscale(v4l2.fourcc("YUYV"), data, 3, 2, 8) == bytes(
        [0, 2, 4, 8, 10, 12]
    )


def test_uyvy_keeps_the_other_one() -> None:
    data = bytes(range(16))
    assert v4l2.to_greyscale(v4l2.fourcc("UYVY"), data, 3, 2, 8) == bytes(
        [1, 3, 5, 9, 11, 13]
    )


@pytest.mark.parametrize("code", ["NV12", "YU12", "YV12"])
def test_a_planar_format_is_its_luma_plane_and_the_chroma_is_ignored(code: str) -> None:
    """The Y plane comes whole and first, so the chroma that follows is never read."""
    data = bytes(range(10)) + b"\xff" * 32
    assert v4l2.to_greyscale(v4l2.fourcc(code), data, 3, 2, 5) == bytes([0, 1, 2, 5, 6, 7])


def test_an_odd_width_is_converted_without_running_into_the_next_row() -> None:
    """Odd dimensions with a padded stride are the case that catches an off-by-one."""
    data = bytes(range(2, 2 + 21))
    converted = v4l2.to_greyscale(v4l2.fourcc("YUYV"), data, 3, 3, 7)
    assert converted == bytes([2, 4, 6, 9, 11, 13, 16, 18, 20])
    assert len(converted) == 9


def test_the_converted_frame_always_matches_the_ports_dimensions() -> None:
    from aobs.ports.frame_source import Frame

    data = bytes(range(256)) * 40
    converted = v4l2.to_greyscale(v4l2.fourcc("YUYV"), data, 40, 30, 96)
    Frame(width=40, height=30, data=converted)  # raises if the length is wrong


def test_a_format_the_appliance_cannot_read_is_refused_rather_than_guessed_at() -> None:
    with pytest.raises(v4l2.CameraError):
        v4l2.to_greyscale(v4l2.fourcc("MJPG"), b"\xff" * 100, 3, 2, 5)


def test_a_short_buffer_is_refused_rather_than_padded() -> None:
    with pytest.raises(v4l2.CameraError):
        v4l2.to_greyscale(v4l2.fourcc("GREY"), bytes(6), 3, 2, 5)


def test_a_stride_narrower_than_the_image_is_refused() -> None:
    with pytest.raises(v4l2.CameraError):
        v4l2.to_greyscale(v4l2.fourcc("YUYV"), bytes(100), 8, 2, 8)


def test_the_camera_error_is_an_oserror() -> None:
    """Both callers already read `OSError` — the probe as "no camera", the scan screen as "the
    camera is gone". This adapter is written to those two contracts rather than asking them to
    learn a third exception."""
    assert issubclass(v4l2.CameraError, OSError)
