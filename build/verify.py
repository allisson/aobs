"""The build's judgement, as pure functions. Text or a listing in, violations out.

`docs/boot-pipeline.md`'s *Build-time assertions* section is a list of **published claims** about
an image. This module is where each one is decided. `build/mkiso.sh` gathers the inputs and calls
these functions; it contains no judgement of its own, and what it decides it decides by asking
here.

The split is the point. Every function below is pure — no I/O, no subprocess, no filesystem, no
image — so every published claim gets a test that runs in the ordinary `aobs-test` container in
milliseconds, **including a test that feeds the check a deliberately broken input and asserts it
objects.** An assertion that has silently stopped checking anything is caught by
`tests/test_build_verifier.py`, which is a thing no amount of green build logs can do.

A violation is a **return value**, never an exception. Reading is the caller's job.

This module is not part of the appliance. `aobs/` never imports it, `build/` is deliberately not a
package, and it uses nothing outside the standard library so it can run in the build container
before anything is installed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

APPLIANCE = "appliance"
HARNESS = "harness"

#: The marker that makes `build/apk-versions.txt` machine-readable. Before it, the two halves of
#: that file were separated by a prose comment and `py3-pip` sat in the second half — so a parser
#: that read the file naively would have put a package manager in the rootfs, defeating a published
#: claim, and nothing would have noticed.
_GROUP_MARKER = re.compile(r"^#\s*@group\s+(\w+)\s*$")


@dataclass(frozen=True)
class Violation:
    """One broken claim, and what was seen instead.

    Both halves are required. A violation that fires without saying why is a failing build nobody
    can act on, and the maintainer reading the log is the person this dataclass exists for.
    """

    claim: str
    saw: str

    def __str__(self) -> str:
        return f"{self.claim}\n    saw: {self.saw}"


# --- `build/apk-versions.txt` -------------------------------------------------------------------


def parse_pins(pins_text: str) -> dict[str, dict[str, str]]:
    """The single pinned list, split into its two groups by the marker rather than by a comment.

    Three consumers read this file: `build/Dockerfile.test` (both groups — the harness runs on the
    appliance's own libraries, which is the whole point of the tier), `build/mkiso.sh` (the
    appliance group only), and this module. The marker is the contract between them.

    A package outside any group is a `ValueError`, not a guess: putting it in the wrong half is
    either a package manager in the rootfs or a missing dependency on the appliance.
    """
    groups: dict[str, dict[str, str]] = {}
    current: str | None = None
    for number, raw in enumerate(pins_text.splitlines(), start=1):
        line = raw.strip()
        marker = _GROUP_MARKER.match(line)
        if marker:
            current = marker.group(1)
            groups.setdefault(marker.group(1), {})
            continue
        if not line or line.startswith("#"):
            continue
        if current is None:
            raise ValueError(
                f"{number}: {line!r} belongs to no group — every package must follow a "
                f"`# @group <name>` marker"
            )
        if "=" not in line:
            raise ValueError(f"{number}: {line!r} is not pinned (`name=version`)")
        name, version = line.split("=", 1)
        groups[current][name] = version
    return groups


def check_apk_manifest(manifest_text: str, pins_text: str) -> list[Violation]:
    """What the rootfs actually got, against what `build/apk-versions.txt` pins.

    `manifest_text` is one `name-version` per line, as `apk info -v` prints it.

    Two claims, and only two. **Every pinned appliance package is installed at exactly its pinned
    version** — a `zxing-cpp`, `cryptography` or `libsecp256k1` skew fails the build rather than
    the session, and the `libsecp256k1` upper bound is enforced here because a routine Alpine bump
    past 0.8.0 breaks taproot signing silently. **No harness package is installed** — the ISO
    carries no test runner and no package manager.

    A package the pins do not name is not a violation: which packages the dependency closure pulls
    in is decided by the pinned repository index, not by this file. Pinning the closure would mean
    pinning 45 names to constrain 11.
    """
    pins = parse_pins(pins_text)
    appliance = pins.get(APPLIANCE, {})
    harness = pins.get(HARNESS, {})
    installed = _parse_manifest(manifest_text)
    violations: list[Violation] = []

    for name, pinned in appliance.items():
        if name not in installed:
            violations.append(
                Violation(
                    f"every package pinned in the appliance group is installed: {name} is not",
                    "absent from the rootfs manifest",
                )
            )
        elif installed[name] != pinned:
            violations.append(
                Violation(
                    f"{name} is installed at exactly the pinned {pinned}",
                    f"{name}-{installed[name]}",
                )
            )

    for name in harness:
        if name in installed:
            violations.append(
                Violation(
                    "no package from the harness group is in the rootfs: the appliance carries no "
                    "test runner and no package manager",
                    f"{name}-{installed[name]}",
                )
            )
    return violations


def _parse_manifest(manifest_text: str) -> dict[str, str]:
    """`py3-zxing-cpp-2.3.0-r3` → `("py3-zxing-cpp", "2.3.0-r3")`.

    apk's own format: the version is the last two dash-separated fields, and the name is whatever
    precedes them — which is why splitting from the right is the only correct way to do it.
    """
    installed: dict[str, str] = {}
    for raw in manifest_text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.rsplit("-", 2)
        if len(parts) != 3:
            continue
        name, version, release = parts
        installed[name] = f"{version}-{release}"
    return installed


# --- The kernel configuration -------------------------------------------------------------------

#: Every symbol that must be off, and the published claim it would break. `=y` and `=m` are both
#: violations: `CONFIG_MODULES=n` makes `=m` impossible in a real kernel, but this function reads
#: text and a hostile text can say anything.
_MUST_BE_OFF: dict[str, str] = {
    "CONFIG_NET": "no network interface is ever brought up: the kernel has no network stack (#2)",
    "CONFIG_MODULES": "all built-in, no modloop: nothing can be loaded into the running kernel (#10)",
    "CONFIG_MAGIC_SYSRQ": "the containment claim holds against a keyboard",
    "CONFIG_SWAP": "no secret is ever written to a block device",
    "CONFIG_BLOCK": "no block device is ever mounted: the block layer is not compiled in",
    # Belt and braces. `CONFIG_BLOCK=n` makes every one of these unreachable in a real kernel, but
    # a config edit that turns the block layer back on must fail on the driver too, so that the
    # claim is enforced at each place a reader would look for it.
    "CONFIG_BLK_DEV": "no block device is ever mounted",
    "CONFIG_BLK_DEV_LOOP": "no block device is ever mounted",
    "CONFIG_BLK_DEV_NBD": "no block device is ever mounted",
    "CONFIG_BLK_DEV_RAM": "no block device is ever mounted",
    "CONFIG_BLK_DEV_NVME": "no storage driver is compiled in",
    "CONFIG_NVME_CORE": "no storage driver is compiled in",
    "CONFIG_SCSI": "no storage driver is compiled in",
    "CONFIG_ATA": "no storage driver is compiled in",
    "CONFIG_MMC": "no storage driver is compiled in",
    "CONFIG_MD": "no storage driver is compiled in",
    "CONFIG_VIRTIO_BLK": "no storage driver is compiled in",
    "CONFIG_XEN_BLKDEV_FRONTEND": "no storage driver is compiled in",
    "CONFIG_ZRAM": "no block device is ever mounted",
    "CONFIG_EXT4_FS": "no filesystem is ever mounted: only tmpfs and pseudo-filesystems",
    "CONFIG_VFAT_FS": "no filesystem is ever mounted: only tmpfs and pseudo-filesystems",
    "CONFIG_ISO9660_FS": "the boot medium is never read again after the kernel and initramfs load",
    "CONFIG_SQUASHFS": "there is no modloop and nothing to mount one from (#10)",
    # A GPU driver is large and several need firmware blobs, which a no-modules kernel would have
    # to carry and load. `fbcon` over the firmware framebuffer needs none of it.
    "CONFIG_DRM": "fbcon over firmware framebuffers only, and no DRM GPU drivers at all",
    "CONFIG_KEXEC": "there is no path from the running app to another kernel",
    "CONFIG_KEXEC_FILE": "there is no path from the running app to another kernel",
    "CONFIG_DEVMEM": "one userspace process, and no window onto physical memory",
    "CONFIG_PROC_KCORE": "one userspace process, and no window onto its own memory as a file",
    "CONFIG_HIBERNATION": "no secret is ever written to a block device",
    # `docs/secret-hygiene.md`: with `CONFIG_COREDUMP=n` there is no dumper in the kernel at all.
    # `resource.setrlimit(RLIMIT_CORE, (0, 0))` in `aobs/adapters/failure_handler.py` is
    # belt-and-braces and must never be the claim — it is a userspace call made by the same code
    # that would be failing.
    "CONFIG_COREDUMP": "no core dumper exists in the kernel to write derived key material out",
    "CONFIG_PROC_PAGE_MONITOR": "nothing enumerates the one process's pages for it",
    # #8: both default to *on*, and left there the entropy floor claim would quietly rest on
    # RDRAND. The cmdline says so too; this is the same claim in the file a reviewer reads.
    "CONFIG_RANDOM_TRUST_CPU": "RDRAND is never a sole or direct source of the entropy floor (#8)",
    "CONFIG_RANDOM_TRUST_BOOTLOADER": "no bootloader-supplied seed alone initialises the RNG (#8)",
    # `docs/boot-pipeline.md`'s *Time*: no clock service, no `hwclock`, no NTP, no timezone
    # database. The RTC is read by firmware and ignored, so the kernel needs no driver for it —
    # and the appliance never displays a date or time, because that judgement would require
    # trusting a clock deliberately never set.
    "CONFIG_RTC_CLASS": "the appliance never reads a clock: nothing sets system time from an RTC",
    "CONFIG_RTC_HCTOSYS": "the appliance never reads a clock: nothing sets system time from an RTC",
}

#: Every symbol that must be on, and why. A symbol that is merely *absent* counts as off: the build
#: generates the `.config` with `allnoconfig` as its base, where anything not asked for is `n`.
_MUST_BE_ON: dict[str, str] = {
    "CONFIG_BLK_DEV_INITRD": "the whole system runs from the initramfs (#10)",
    "CONFIG_RD_ZSTD": "the initramfs is `cpio | zstd`",
    "CONFIG_TMPFS": "PID 1 mounts tmpfs and pseudo-filesystems, and nothing else",
    "CONFIG_DEVTMPFS": "PID 1 mounts tmpfs and pseudo-filesystems, and nothing else",
    "CONFIG_PROC_FS": "PID 1 mounts tmpfs and pseudo-filesystems, and nothing else",
    "CONFIG_SYSFS": "PID 1 flips `authorized_default=0` on every root hub through sysfs (#14)",
    "CONFIG_UNIX98_PTYS": "PID 1 mounts devpts",
    "CONFIG_VT": "the appliance is a framebuffer TUI on the console (#3)",
    "CONFIG_VT_CONSOLE": "the appliance is a framebuffer TUI on the console (#3)",
    "CONFIG_FB": "the appliance is a framebuffer TUI on the console (#3)",
    "CONFIG_FB_DEVICE": "creates `/dev/fb0`, needed if #3's viewfinder escape hatch is taken",
    "CONFIG_FRAMEBUFFER_CONSOLE": "fbcon is what gives 128×48 instead of vgacon's 80×25 (#3)",
    "CONFIG_FB_EFI": "the UEFI firmware framebuffer path",
    "CONFIG_FB_VESA": "the BIOS firmware framebuffer path, which `vga=791` selects",
    "CONFIG_FONT_SUPPORT": "the built-in 8×16 font, so `font-terminus` need not ship",
    "CONFIG_FONT_8x16": "#3's exact-1:2 cell requirement, met without a package",
    "CONFIG_INPUT": "the keyboard",
    "CONFIG_INPUT_KEYBOARD": "the keyboard",
    "CONFIG_INPUT_EVDEV": "the keyboard",
    "CONFIG_HID": "the keyboard",
    "CONFIG_HID_GENERIC": "the keyboard",
    "CONFIG_USB_SUPPORT": "the two USB class drivers #14 allows",
    "CONFIG_USB": "the two USB class drivers #14 allows",
    "CONFIG_USB_HID": "one of exactly two USB class drivers (#14)",
    "CONFIG_USB_VIDEO_CLASS": "one of exactly two USB class drivers (#14)",
    "CONFIG_MEDIA_SUPPORT": "the V4L2 camera path (#6)",
    "CONFIG_VIDEO_DEV": "the V4L2 camera path (#6)",
    "CONFIG_TTY": "the console",
    "CONFIG_BINFMT_ELF": "`exec python3 -m aobs`",
    "CONFIG_MULTIUSER": "PID 1 and the app run as root, and there is no second user",
    # `CONFIG_COREDUMP` is `bool "Enable core dump support" if EXPERT`, `default y` — compile-outable
    # but only *visible* under `EXPERT`. Confirmed against kernel sources rather than assumed.
    "CONFIG_EXPERT": "what makes CONFIG_COREDUMP=n possible at all (`docs/secret-hygiene.md`)",
    "CONFIG_INIT_ON_FREE_DEFAULT_ON": "a page CPython returns to the kernel does not retain a key",
    # An offline machine kept for exactly this purpose is often old enough that its keyboard is
    # PS/2, which reaches the console through `atkbd` and not through `usbhid`.
    "CONFIG_SERIO": "a PS/2 keyboard on the kind of old offline machine this appliance is for",
    "CONFIG_SERIO_I8042": "a PS/2 keyboard on the kind of old offline machine this appliance is for",
    "CONFIG_KEYBOARD_ATKBD": "a PS/2 keyboard on the kind of old offline machine this appliance is for",
}

#: The two USB class drivers #14 allows, checked as an **equality** and not as a containment.
_USB_CLASS_DRIVERS = frozenset({"CONFIG_USB_HID", "CONFIG_USB_VIDEO_CLASS"})

#: Every other USB symbol the image is allowed to enable: the stack itself and the host
#: controllers, which are not class drivers and carry no claim.
#:
#: The rule below is deliberately written the other way round from a whitelist of *forbidden*
#: drivers. Any enabled symbol whose name mentions USB and is not named here is a violation, so a
#: class driver nobody thought to forbid — `CONFIG_SND_USB_AUDIO`, `CONFIG_BT_HCIBTUSB`,
#: `CONFIG_USB_SERIAL`, a driver that does not exist yet — fails without this file being updated.
#: A pair of `grep`s for `usbhid` and `uvcvideo` would pass with a third driver present, which is
#: exactly what #14 asks not to happen.
_USB_ALLOWED = frozenset(
    {
        "CONFIG_USB_SUPPORT",
        "CONFIG_USB",
        "CONFIG_USB_PCI",
        "CONFIG_USB_COMMON",
        "CONFIG_USB_ARCH_HAS_HCD",
        "CONFIG_USB_DEFAULT_PERSIST",
        "CONFIG_USB_AUTOSUSPEND_DELAY",
        "CONFIG_USB_XHCI_HCD",
        "CONFIG_USB_XHCI_PCI",
        "CONFIG_USB_EHCI_HCD",
        "CONFIG_USB_EHCI_PCI",
        "CONFIG_USB_EHCI_HCD_PLATFORM",
        "CONFIG_USB_OHCI_HCD",
        "CONFIG_USB_OHCI_HCD_PCI",
        "CONFIG_USB_UHCI_HCD",
        "CONFIG_USB_HIDDEV",
        "CONFIG_USB_ANNOUNCE_NEW_DEVICES",
        # The V4L2 menu `uvcvideo` lives under, and `uvcvideo`'s own sub-option. Neither is a
        # second class driver; without the first, `CONFIG_USB_VIDEO_CLASS` is not selectable.
        "CONFIG_MEDIA_USB_SUPPORT",
        "CONFIG_USB_VIDEO_CLASS_INPUT_EVDEV",
    }
    | _USB_CLASS_DRIVERS
)


def check_kernel_config(config_text: str) -> list[Violation]:
    """The claims #10 and #14 promise a reviewer can check *by reading the config*.

    Which is only true because the config is one file in this repository rather than a fragment
    merged into a distribution's config at build time — the decisive reason for vanilla kernel.org
    source over Alpine's `APKBUILD`.

    The build runs this twice: on the checked-in `build/kernel.config`, and on the `.config`
    Kbuild actually generated, because a symbol can arrive through a dependency nobody wrote down.
    """
    symbols = _symbols(config_text)
    violations: list[Violation] = []

    for symbol, claim in _MUST_BE_OFF.items():
        value = symbols.get(symbol, "n")
        if value in {"y", "m"}:
            violations.append(Violation(f"{symbol}=n — {claim}", f"{symbol}={value}"))

    for symbol, claim in _MUST_BE_ON.items():
        value = symbols.get(symbol, "n")
        if value != "y":
            violations.append(
                Violation(
                    f"{symbol}=y — {claim}",
                    f"{symbol}={value}" if symbol in symbols else f"{symbol} is not set",
                )
            )

    violations.extend(_check_usb_class_drivers(symbols))
    return violations


def _check_usb_class_drivers(symbols: dict[str, str]) -> list[Violation]:
    """#14 as an equality: the built-in USB class driver set is *exactly* usbhid and uvcvideo.

    **Stated precisely, because "exactly" invites more than this can deliver.** The equality is over
    *every enabled symbol whose name mentions USB*, against an explicit allow-list — which is why a
    driver nobody thought to forbid fails without this module being edited, and why a pair of greps
    for `usbhid` and `uvcvideo` would not. What it does not reach is a USB class driver whose Kconfig
    symbol does not contain the string `USB`. Upstream names them all so today, and there is no list
    of "all USB class drivers" to check against instead. `docs/boot-checklist.md` item 9 is the other
    half: on a booted appliance the driver list is read off the running kernel, which is a fact about
    the shipped image rather than about the config text.
    """
    violations: list[Violation] = []
    enabled_usb = {
        symbol
        for symbol, value in symbols.items()
        if "USB" in symbol and value in {"y", "m"}
    }
    for symbol in sorted(enabled_usb - _USB_ALLOWED):
        violations.append(
            Violation(
                f"the built-in USB class driver list is exactly usbhid and uvcvideo (#14): "
                f"{symbol} is a third one",
                f"{symbol}={symbols[symbol]}",
            )
        )
    missing = sorted(_USB_CLASS_DRIVERS - enabled_usb)
    for symbol in missing:
        violations.append(
            Violation(
                f"the built-in USB class driver list is exactly usbhid and uvcvideo (#14): "
                f"{symbol} is missing",
                f"{symbol} is not set",
            )
        )
    return violations


def _symbols(config_text: str) -> dict[str, str]:
    """A `.config` as a mapping. `# CONFIG_X is not set` reads as `n`; absent also reads as `n`.

    Absence is the correct reading because the build generates the `.config` from `allnoconfig`
    with this file as the preset, so nothing is on that this file did not ask for.
    """
    symbols: dict[str, str] = {}
    for raw in config_text.splitlines():
        line = raw.strip()
        disabled = re.fullmatch(r"# (CONFIG_\w+) is not set", line)
        if disabled:
            symbols[disabled.group(1)] = "n"
            continue
        if line.startswith("#") or "=" not in line:
            continue
        symbol, value = line.split("=", 1)
        if symbol.startswith("CONFIG_"):
            symbols[symbol.strip()] = value.strip().strip('"')
    return symbols


# --- The kernel command line --------------------------------------------------------------------

#: Every cmdline parameter that must be present, and the published claim it carries. These are
#: fixed in the bootloader config precisely so that they are not a thing anyone has to remember.
_REQUIRED_CMDLINE: dict[str, str] = {
    "random.trust_cpu=off": "the entropy floor does not silently rest on RDRAND (#8)",
    "random.trust_bootloader=off": "no bootloader-supplied seed alone initialises the RNG (#8)",
    "panic=0": "a failure hangs on a visible message rather than rebooting in a loop that flashes "
    "the explanation past the user",
    "init_on_free=1": "a page CPython returns to the kernel does not retain a key "
    "(`docs/secret-hygiene.md`, bounded there: it does not cover reuse inside musl's allocator)",
}

BIOS = "bios"
UEFI = "uefi"


def cmdline_from_isolinux(config_text: str) -> str:
    """The `APPEND` line of `build/isolinux.cfg`, as the kernel would receive it.

    Extraction is pure and lives here rather than in `build/mkiso.sh` for the same reason every
    other judgement does: it is the only way `tests/test_build_verifier.py` can assert the claim
    against the file this repository actually ships.
    """
    return _first_directive(config_text, "APPEND")


def cmdline_from_grub(config_text: str) -> str:
    """The parameters on the `linux` line of `build/grub.cfg`, minus the kernel path itself."""
    line = _first_directive(config_text, "linux")
    _, _, parameters = line.partition(" ")
    return parameters.strip()


#: Which extractor reads which firmware path's bootloader config. Here rather than in
#: `build/gather.py` so that a firmware path is one entry in one table — the extractor and the
#: parameters that path requires — instead of the same two-valued `if` written in two modules.
FIRMWARE_EXTRACTORS = {BIOS: cmdline_from_isolinux, UEFI: cmdline_from_grub}


def _first_directive(config_text: str, keyword: str) -> str:
    for raw in config_text.splitlines():
        line = raw.strip()
        if line.startswith("#"):
            continue
        head, _, rest = line.partition(" ")
        if head == keyword:
            return rest.strip()
    return ""


def check_cmdline(cmdline: str, firmware: str) -> list[Violation]:
    """The cmdline as the bootloader config spells it, per firmware path.

    `vga=791` is on the BIOS path only and it is **not cosmetic**: `vgacon` gives 80×25 text, #3
    fixed the QR at 85 columns × 43 rows, so a BIOS boot without it cannot display a QR code at
    all. With `vga=791` (1024×768) `vesafb` provides a graphical framebuffer and `fbcon` gives
    128×48. On UEFI the firmware framebuffer is already graphical and `vga=` is meaningless.

    `init=` is refused rather than required: for an initramfs the kernel runs `/init`, which is our
    script. A bootloader config that names an init has moved PID 1 somewhere the claims do not
    cover. A *person at the bootloader* typing `init=/bin/sh` is undefended and stated as such — a
    fresh boot holds no secrets, which is the point of the amnesia claim.
    """
    tokens = cmdline.split()
    violations: list[Violation] = []
    for required, claim in _REQUIRED_CMDLINE.items():
        if required not in tokens:
            violations.append(
                Violation(f"the {firmware} cmdline carries {required} — {claim}", cmdline.strip())
            )
    if firmware == BIOS and "vga=791" not in tokens:
        violations.append(
            Violation(
                "the bios cmdline carries vga=791 — without it vgacon gives 80×25 and the 85×43 QR "
                "code cannot be displayed at all (#3)",
                cmdline.strip(),
            )
        )
    for token in tokens:
        if token.startswith("init="):
            violations.append(
                Violation(
                    f"the {firmware} cmdline names no init: PID 1 is `/init`, our script",
                    token,
                )
            )
    return violations


# --- The root filesystem ------------------------------------------------------------------------

#: Basenames the rootfs must not contain, and the published claim each one would break.
#:
#: **This is a claim about paths, and that is the claim `docs/boot-pipeline.md` makes.** Busybox is
#: in the image and its applets are reachable as `busybox wget`, which no file listing can see.
#: That is not the hole it looks like: what makes `wget` inert is `CONFIG_NET=n` above, checked in
#: the kernel where the claim actually lives. The listing check is here for the things that *are*
#: files — a getty, an inittab, apk, pip, a test runner — because those are what a rootfs build
#: step accidentally leaves behind.
FORBIDDEN_BASENAMES: dict[str, str] = {
    "getty": "no getty, no VT with a login, and no path from the running app to a prompt",
    "agetty": "no getty, no VT with a login, and no path from the running app to a prompt",
    "getty.sh": "no getty, no VT with a login, and no path from the running app to a prompt",
    "login": "no login: there is no getty and no path from the running app to a prompt",
    "sulogin": "no login: there is no getty and no path from the running app to a prompt",
    "inittab": "PID 1 is our script: there is no init system and no inittab",
    "openrc": "PID 1 is our script: there is no init system, no OpenRC, no supervisor",
    "openrc-init": "PID 1 is our script: there is no init system, no OpenRC, no supervisor",
    "rc-service": "PID 1 is our script: there is no init system, no OpenRC, no supervisor",
    "rc-status": "PID 1 is our script: there is no init system, no OpenRC, no supervisor",
    "apk": "no package manager in the rootfs",
    "pip": "no package manager in the rootfs",
    "pip3": "no package manager in the rootfs",
    "easy_install": "no package manager in the rootfs",
    "wget": "no network utility in the rootfs",
    "curl": "no network utility in the rootfs",
    "ip": "no network utility in the rootfs",
    "ifconfig": "no network utility in the rootfs",
    "route": "no network utility in the rootfs",
    "arping": "no network utility in the rootfs",
    "ping": "no network utility in the rootfs",
    "ping6": "no network utility in the rootfs",
    "nc": "no network utility in the rootfs",
    "netcat": "no network utility in the rootfs",
    "telnet": "no network utility in the rootfs",
    "ssh": "no network utility in the rootfs",
    "scp": "no network utility in the rootfs",
    "sshd": "no network utility in the rootfs",
    "dropbear": "no network utility in the rootfs",
    "udhcpc": "no network utility in the rootfs",
    "udhcpd": "no network utility in the rootfs",
    "ntpd": "no network utility in the rootfs",
    "chronyd": "no network utility in the rootfs",
    "hwclock": "no clock service, no hwclock, no NTP, no timezone database",
    "pytest": "no test runner in the rootfs",
    "py.test": "no test runner in the rootfs",
}


#: What PID 1 needs in order to run at all, and what the boot sequence needs to reach the app.
#:
#: This half of the check exists because the first ISO build produced a rootfs with **no busybox**:
#: no `/bin/sh`, no `mount`, no `sleep`, no `poweroff`. Nothing objected, because busybox was never
#: a *listed* dependency — `build/Dockerfile.test` inherits it from the `alpine:3.24` base image, so
#: the test tier had never noticed it was missing from `build/apk-versions.txt`. Every assertion
#: above was about what must **not** be in the image; an image can fail by absence too.
REQUIRED_PATHS: dict[str, str] = {
    "/init": "PID 1 is our script, and the kernel runs `/init` for an initramfs",
    "/bin/sh": "PID 1 is a POSIX shell script, so the image needs a shell to run it",
    "/bin/busybox": "`mount`, `sleep`, `poweroff` and `awk` in PID 1 are busybox applets",
    "/usr/bin/python3": "PID 1 ends in `exec python3 -m aobs`",
    "/usr/bin/loadkeys": "PID 1 loads the default keymap, and the picker changes it (#12)",
}


def _components(path: object) -> list[str]:
    """`/usr/lib/python3.14/site-packages/pip/__init__.py` → its path components, leading `/` gone.

    Both listing checks below match on components rather than on substrings: a directory counts as
    much as a binary, and `pip` must not match `pipes.py`.
    """
    return str(path).strip("/").split("/")


#: Paths forbidden as whole paths rather than by name, because the name alone is innocent.
#:
#: Python's stdlib ships a `zoneinfo` *module*; what `docs/boot-pipeline.md` rules out is the
#: timezone *database* — the data files — so the check has to be about the path and not the word.
FORBIDDEN_PATH_PREFIXES: dict[str, str] = {
    "/usr/share/zoneinfo": "no timezone database: the appliance never displays a date or time",
    "/etc/localtime": "no timezone database: the appliance never displays a date or time",
    "/etc/timezone": "no timezone database: the appliance never displays a date or time",
}


def check_rootfs(paths: Iterable[str]) -> list[Violation]:
    """The image's own claims, read off a path listing — what must not be there, and what must.

    A directory counts as much as a binary: `site-packages/pip/` is a package manager whether or
    not the `pip3` wrapper survived.
    """
    violations: list[Violation] = []
    present = {"/" + str(path).strip("/") for path in paths}
    for required, claim in REQUIRED_PATHS.items():
        if required not in present:
            violations.append(Violation(f"the rootfs carries {required} — {claim}", "absent"))
    for path in paths:
        text = "/" + str(path).strip("/")
        forbidden = next(
            (
                claim
                for prefix, claim in FORBIDDEN_PATH_PREFIXES.items()
                if text == prefix or text.startswith(prefix + "/")
            ),
            None,
        )
        if forbidden is not None:
            violations.append(Violation(forbidden, text))
            continue
        for part in _components(path):
            claim = FORBIDDEN_BASENAMES.get(part)
            if claim is not None:
                violations.append(Violation(claim, str(path)))
                break
    return violations


# --- The vendored tree --------------------------------------------------------------------------


def check_vendored_tree(paths: Iterable[str]) -> list[Violation]:
    """`embit/util/prebuilt/` must not exist, and a `.so` must not reach the tree by another name.

    `_find_library()` returns the prebuilt path whenever the file merely *exists* and does not fall
    through when *loading* it fails. On musl the glibc-linked blob cannot relocate, the bare
    `except:` selects the pure-Python fallback, and every EC operation on the appliance silently
    stops being the audited implementation — with no message either way.
    """
    violations: list[Violation] = []
    for path in paths:
        text = str(path)
        parts = _components(path)
        if "prebuilt" in parts:
            violations.append(
                Violation(
                    "`embit/util/prebuilt/` does not exist in the vendored tree: `_find_library()` "
                    "returns that path whenever the file merely exists",
                    text,
                )
            )
        elif parts[-1].endswith((".so", ".dylib", ".dll")) or ".so." in parts[-1]:
            violations.append(
                Violation(
                    "the vendored libraries are pure Python, checked in where they can be read: "
                    "no binary artifact belongs in the tree",
                    text,
                )
            )
    return violations
