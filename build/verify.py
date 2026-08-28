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

import datetime
import re
from dataclasses import dataclass
from typing import Iterable, Mapping

APPLIANCE = "appliance"
HARNESS = "harness"
TOOLCHAIN = "toolchain"

#: The maintainer's own key, used as it is: Ed25519, personal UID, no invented org identity (#58).
#: Custody is **stated rather than engineered away** — it lives on an ordinary networked computer,
#: and `SECURITY.md` and the README both say so.
BUILDER_FINGERPRINT = "C8532ED68A596CFBB7F92D04360718E309BEAA9F"

#: CI's witness key. **Empty, because no such key exists yet**, and a placeholder fingerprint in a
#: file strangers read to learn whom to trust would be the worst possible kind of invention. The
#: witness signature is already non-fatal to verification and the `signer:` lines make its absence
#: visible rather than silent, so adding it later is a one-line change here and in
#: `verify-release.sh` — with no format change and no re-verification of anything already published.
WITNESS_FINGERPRINT = ""

#: Who a manifest declares was expected to sign it. **A verifier must never trust this to decide who
#: may sign** — trusting the manifest to say who may sign it is circular, so `verify-release.sh`
#: hardcodes its own copy. This list exists for one narrow purpose: telling *"one of two"* from
#: *"one, and no idea whether more were coming"*.
SIGNERS: tuple[tuple[str, str], ...] = tuple(
    entry
    for entry in (
        (BUILDER_FINGERPRINT, "builder"),
        (WITNESS_FINGERPRINT, "witness-ci"),
    )
    if entry[0]
)

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


def check_toolchain_list(pins_text: str) -> list[Violation]:
    """`build/toolchain-versions.txt` carries exactly one group, named `toolchain`.

    Not a style rule. `build/Dockerfile.iso` and `build/fetch-inputs.sh` read that file as *every
    non-comment line*, which is correct only while it has one group — and a naive reader of a
    two-group file is precisely the hazard the `# @group` markers were introduced to close, when
    `py3-pip` sat on the far side of a prose comment and a parser would have put a package manager in
    the rootfs. The check is here so that adding a second group fails the build instead of quietly
    installing it.
    """
    try:
        groups = parse_pins(pins_text)
    except ValueError as error:
        return [
            Violation(
                "every package in build/toolchain-versions.txt follows a `# @group` marker and is "
                "pinned `name=version`",
                str(error),
            )
        ]
    if sorted(groups) != [TOOLCHAIN]:
        return [
            Violation(
                "build/toolchain-versions.txt carries exactly one group, named toolchain: "
                "Dockerfile.iso and fetch-inputs.sh read it as every non-comment line, which is "
                "correct only while that is true",
                f"groups: {', '.join(sorted(groups)) or 'none'}",
            )
        ]
    return []


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
    "CONFIG_HID_SUPPORT": "the menu `CONFIG_HID` lives under: without it HID drops silently",
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
        # Not a driver: an endianness constant kconfig `select`s alongside the OHCI controller.
        # It appears in the generated `.config` without anyone asking for it.
        "CONFIG_USB_OHCI_LITTLE_ENDIAN",
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
    # In the harness group since the release work needed it there, and named here for the same
    # reason `wget` is: `git fetch` is a network utility, and the harness landing in the rootfs must
    # fail on the path as well as on the package name.
    "git": "no network utility in the rootfs",
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


# --- The shared `key: value` reading ------------------------------------------------------------
#
# Two files use it here: `/etc/aobs-release` and the release manifest. One reader for both, so the
# manifest cannot mean by `git-commit:` something other than what the embedded release file means by
# it.
#
# **There is a second reader of `/etc/aobs-release`, and it is not this one.** `aobs/core/release.py`
# parses the same file for display, because this module cannot import the appliance and the appliance
# cannot import `build/`. That duplication is real and deliberate; what keeps the two from drifting is
# `tests/test_build_verifier.py::test_the_appliance_and_the_build_parse_the_release_file_the_same_way`,
# which feeds both the same text and asserts they agree. The risk was never that either parser is
# hard — it is that one gets changed and the other does not.

#: `<sha256>  <name>`, exactly as `sha256sum` writes it and as `sha256sum -c` reads it back. Two
#: spaces, not one: one space is the `--text`/`--binary` marker position and busybox is strict
#: about it.
_CHECKSUM_LINE = re.compile(r"^([0-9a-f]{64})  (\S.*)$")


def parse_fields(text: str) -> dict[str, str]:
    """Every `key: value` line, last one winning. Comments and blank lines ignored.

    Repeated keys are the manifest's `signer:` and `input-*:` lines; those are read by
    `parse_repeated_field` instead, which is why this one may collapse them without losing
    anything a caller here needs.
    """
    fields: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition(":")
        if separator and " " not in key:
            fields[key.strip()] = value.strip()
    return fields


def parse_repeated_field(text: str, key: str) -> list[str]:
    """Every value of a key that may legitimately appear more than once — `signer:`, `input-*:`."""
    prefix = f"{key}:"
    return [
        line.strip()[len(prefix) :].strip()
        for line in text.splitlines()
        if line.strip().startswith(prefix)
    ]


def parse_checksum_list(text: str) -> dict[str, str]:
    """The contiguous `<sha256>  <name>` block of a checksum list, as `{name: sha256}`.

    Every other line is skipped rather than rejected: `build/inputs.sha256` is a bare list, but the
    manifest carries this same block among comments and metadata, and the whole point of the
    documented `grep` one-liner is that the block is extractable from the noise around it.
    """
    listed: dict[str, str] = {}
    for raw in text.splitlines():
        match = _CHECKSUM_LINE.match(raw.rstrip("\n"))
        if match:
            listed[match.group(2).strip()] = match.group(1)
    return listed


# --- The input archive --------------------------------------------------------------------------


def check_inputs(present: Mapping[str, str], committed_text: str) -> list[Violation]:
    """`build/inputs/` against `build/inputs.sha256`, on hash **and on set equality**.

    `present` is `{relative path: sha256}` for every file actually in the directory;
    `build/gather.py` walks and hashes, this decides. `docs/reproducible-build.md` claim 7.

    **The extra file is the case that matters**, and it is the one a naive implementation ignores.
    A rebuilder in 2030 unpacks a release asset into `build/inputs/`; if an unexpected `.apk` in
    that directory were merely unused rather than refused, an attacker who can write there has a
    place to put one — and `apk` resolving a closure against a local repository is exactly the kind
    of thing that would pick it up. So the check is an equality, not a containment.

    This runs in `build/mkiso.sh` and **not** in `build/fetch-inputs.sh`, which is the other half
    of the same decision: verification only in the fetcher is verification a hand-populated
    directory walks straight past.
    """
    committed = parse_checksum_list(committed_text)
    violations: list[Violation] = []
    if not committed:
        return [
            Violation(
                "build/inputs.sha256 lists the sha256 of every file the build consumes",
                "the list is empty or has no `<sha256>  <name>` lines at all",
            )
        ]
    for name in sorted(committed):
        if name not in present:
            violations.append(
                Violation(
                    f"every file build/inputs.sha256 lists is present in build/inputs/: "
                    f"{name} is not",
                    "absent — run build/fetch-inputs.sh, or unpack the release's input archive",
                )
            )
        elif present[name] != committed[name]:
            violations.append(
                Violation(
                    f"{name} matches the sha256 committed in build/inputs.sha256",
                    f"{present[name]}, expected {committed[name]}",
                )
            )
    for name in sorted(set(present) - set(committed)):
        violations.append(
            Violation(
                "build/inputs/ contains nothing build/inputs.sha256 does not list: the input set "
                "is an equality, so a file smuggled into the directory is a failure and not an "
                f"ignore — {name} is unexpected",
                f"{present[name]}  {name}",
            )
        )
    return violations


# --- The embedded release line ------------------------------------------------------------------

#: What `/etc/aobs-release` says instead of a version when the build is not a release build. It is
#: deliberately not version-shaped: a developer must not be able to sign with a build months later
#: believing it was a release, and `DEVELOPMENT BUILD` on screen is what makes that impossible to
#: misread. #61.
DEVELOPMENT = "development"

#: The only version shape a release may carry. `vMAJOR.MINOR` and nothing else — the release ritual
#: (#65) matches the tag against this, and `docs/release.md` names no other form.
RELEASE_TAG = re.compile(r"^v(0|[1-9]\d*)\.(0|[1-9]\d*)$")

#: The fields `/etc/aobs-release` must carry. Version, commit and `SOURCE_DATE_EPOCH` are the
#: **complete embeddable set** — #61's finding is that nothing derived from the image can be
#: embedded in it, the initramfs hash included, since the initramfs is the whole system.
#:
#: `released` is the **formatted** date and not a second source of truth: the appliance may not
#: import `datetime` (`tests/test_structure.py::test_core_reads_no_ambient_state`), so the one place
#: an epoch can become a date is the build, and the appliance displays the string it was handed.
#: The check below is what keeps the two halves of that arrangement honest.
_RELEASE_FIELDS = ("release", "released", "git-commit", "source-date-epoch", "dirty")

_COMMIT = re.compile(r"^[0-9a-f]{40}$")


def utc_date(epoch: str) -> str:
    """`1773446400` → `2026-09-14`, in UTC and nowhere else. Empty for anything that is not one.

    Pure: a conversion, not a clock reading. Nothing in this module or in the appliance ever asks
    what time it is now.
    """
    try:
        seconds = int(epoch)
    except ValueError:
        return ""
    return (
        datetime.datetime.fromtimestamp(seconds, tz=datetime.timezone.utc)
        .date()
        .isoformat()
    )


def check_embedded_release(
    release_text: str,
    *,
    tag: str,
    head_commit: str,
    dirty: bool,
    source_date_epoch: str,
) -> list[Violation]:
    """`/etc/aobs-release`, as stage 1 wrote it, against what git says about the tree.

    Run in **stage 3, before `cpio`** — #61: after `cpio` the value is inside an archive and the
    failure message stops being about a file a human can open.

    `tag` is `git describe --exact-match --tags`, empty when HEAD carries no tag. A build that is
    not at a clean tag is a development build, and the assertion is then **skipped rather than
    faked**: the only thing checked is that it does not claim to be a release.
    """
    fields = parse_fields(release_text)
    violations: list[Violation] = []
    for field in _RELEASE_FIELDS:
        if field not in fields:
            violations.append(
                Violation(
                    f"/etc/aobs-release carries {field}: the appliance names itself on the first "
                    f"screen, and the manifest's own fields are generated from this file",
                    "absent",
                )
            )
    if violations:
        return violations

    release, released, commit, epoch, dirty_field = (fields[field] for field in _RELEASE_FIELDS)

    if not _COMMIT.match(commit):
        violations.append(
            Violation(
                "/etc/aobs-release names the full 40-hex commit: the 12-hex prefix on screen is "
                "what makes the line checkable against the manifest",
                commit or "empty",
            )
        )
    elif commit != head_commit:
        violations.append(
            Violation(
                "the embedded git-commit is HEAD: the image and the manifest are generated from "
                "this one file so that they cannot disagree",
                f"{commit}, HEAD is {head_commit}",
            )
        )

    if epoch != source_date_epoch:
        violations.append(
            Violation(
                "the embedded source-date-epoch is the one the build ran under: the ISO's internal "
                "timestamps are an assertion about which commit built it "
                "(`docs/reproducible-build.md` claim 2)",
                f"{epoch or 'empty'}, the build ran under {source_date_epoch or 'nothing'}",
            )
        )

    if dirty_field != ("yes" if dirty else "no"):
        violations.append(
            Violation(
                "the embedded dirty flag is what git says about the tree: it is the `-dirty` "
                "suffix the first screen shows, and a wrong one is the appliance lying about "
                "itself",
                f"dirty: {dirty_field or 'empty'}, git says {'yes' if dirty else 'no'}",
            )
        )

    if released != utc_date(epoch):
        violations.append(
            Violation(
                "the embedded released date is source-date-epoch formatted as UTC `YYYY-MM-DD`: "
                "the appliance may not import `datetime`, so the build is the only place that "
                "conversion can happen and this is the only thing keeping the two consistent",
                f"released: {released or 'empty'}, source-date-epoch {epoch} is "
                f"{utc_date(epoch) or 'not an integer'}",
            )
        )

    if is_release_build(tag, dirty):
        if release != tag:
            violations.append(
                Violation(
                    "a release image's embedded version is the signed tag it was built at: the "
                    "image and the manifest cannot be allowed to disagree (#61)",
                    f"release: {release or 'empty'}, git describe says {tag}",
                )
            )
    elif release != DEVELOPMENT:
        violations.append(
            Violation(
                f"a build that is not at a clean tag says {DEVELOPMENT!r} and never a "
                f"version-shaped string: a developer must not sign months later with a build they "
                f"took for a release (#61)",
                f"release: {release or 'empty'}"
                + (" on a dirty tree" if dirty else " with no tag at HEAD"),
            )
        )
    return violations


# --- The four release-mode refusals -------------------------------------------------------------


@dataclass(frozen=True)
class GitFacts:
    """What git says about the tree the release is being cut from. Gathered, never decided here.

    `build/gather.py` runs the four commands. Keeping the *facts* in a value object is what lets
    `tests/test_build_verifier.py` feed each refusal a hostile one in milliseconds — the whole
    reason the four refusals are not shell conditions in `build/release-preflight.sh`.
    """

    #: `git rev-parse HEAD`.
    head_commit: str
    #: `git status --porcelain` produced output.
    dirty: bool
    #: `git describe --exact-match --tags HEAD`, empty when HEAD carries no tag.
    tag: str
    #: `git tag -v <tag>` exited zero, i.e. the tag is annotated **and** its signature verified.
    tag_signed: bool
    #: `git log -1 --format=%ct <tag>^{commit}`, as text. Empty when there is no tag.
    tag_commit_date: str


def is_release_build(tag: str, dirty: bool) -> bool:
    """Whether a build may call itself a version. The one definition, used by both sides.

    `build/gather.py` asks it to decide what to write into `/etc/aobs-release`, and
    `check_embedded_release` asks it to decide what that file was allowed to say. Those two are
    deliberately a generator and an independent judge — but they must not be allowed to disagree
    about *what a release build is*, which is what this being one function prevents.
    """
    return bool(tag) and not dirty


def check_release_preflight(
    git: GitFacts,
    *,
    source_date_epoch: str,
    manifest_commit: str | None,
    release_mode: bool = True,
) -> list[Violation]:
    """The four things a human passes without noticing, made things a human cannot skip. #65.

    **A development build trips none of them**, which is not a loophole but the design: a guard that
    fires during ordinary work gets disabled, and then it guards nothing on the day it mattered.

    `release_mode` is that decision, made a parameter rather than left implicit in who calls this.
    Today the only caller is the release ritual and it passes `True` explicitly; the reason the
    parameter exists at all is that *"in release mode only"* is a claim the suite has to be able to
    check, and `tests/test_build_verifier.py` checks it by driving each of the four hostile inputs
    through `release_mode=False` and asserting silence. A guard nobody has confirmed is quiet during
    ordinary work is a guard nobody will keep.

    `manifest_commit` is the manifest's `git-commit:` field, or `None` when no manifest exists yet —
    the preflight runs before the manifest is written as well as after it.
    """
    if not release_mode:
        return []

    violations: list[Violation] = []

    if git.dirty:
        violations.append(
            Violation(
                "a release is cut from a clean working tree: an uncommitted edit is in the image "
                "and in nothing a stranger can check out",
                "git status --porcelain is not empty",
            )
        )

    if not git.tag:
        violations.append(
            Violation(
                "HEAD is at an annotated tag matching vMAJOR.MINOR — the stage-3 assertion binds "
                "the embedded version to it, so the tag exists before the build",
                "git describe --exact-match --tags found no tag at HEAD",
            )
        )
    elif not RELEASE_TAG.match(git.tag):
        violations.append(
            Violation(
                "the release tag is vMAJOR.MINOR and nothing else: `docs/release.md` names no "
                "other form and the manifest's file names are built from it",
                git.tag,
            )
        )
    if git.tag and not git.tag_signed:
        violations.append(
            Violation(
                "the tag is signed by the maintainer's own key and tagged locally, never through "
                "the GitHub UI — main's HEAD is otherwise signed by GitHub's key",
                f"git tag -v {git.tag} did not verify",
            )
        )

    # No tag means no date to compare against, and the missing tag is already reported above.
    if git.tag_commit_date and source_date_epoch != git.tag_commit_date:
        violations.append(
            Violation(
                "SOURCE_DATE_EPOCH is the commit date of HEAD, derived and never passed in: a "
                "mismatch means it was set by hand, and the ISO's timestamps would then assert "
                "something about no commit at all",
                f"SOURCE_DATE_EPOCH={source_date_epoch or 'unset'}, the tagged commit is dated "
                f"{git.tag_commit_date}",
            )
        )

    if manifest_commit is not None and manifest_commit != git.head_commit:
        violations.append(
            Violation(
                "the manifest's git-commit is HEAD: the signature covers the manifest because the "
                "manifest names the inputs, so a manifest describing another commit signs nothing",
                f"{manifest_commit or 'empty'}, HEAD is {git.head_commit}",
            )
        )
    return violations


# --- The manifest -------------------------------------------------------------------------------

#: The manifest's own format marker. Bumped only if the *shape* changes, never for a new field: a
#: verifier that hard-fails on an added field is a verifier that breaks the next release.
MANIFEST_FORMAT = "aobs-manifest-1"

_MANIFEST_REQUIRED = (
    "format",
    "release",
    "released",
    "git-tag",
    "git-commit",
    "source-date-epoch",
    "iso-name",
    "alpine-branch",
    "aports-commit",
    "inputs-list-sha256",
)


def check_manifest(
    manifest_text: str,
    *,
    release_text: str,
    inputs_list_sha256: str,
    published: Mapping[str, str],
) -> list[Violation]:
    """The manifest against the three things it must not be allowed to disagree with.

    `/etc/aobs-release` — because #61 settled that the manifest's `release` and `git-commit` are
    *generated from that file* rather than assembled independently, so there is nothing for the
    image and the manifest to disagree about. The sha256 of `build/inputs.sha256` as committed at
    the tag — `inputs-list-sha256` is the field doing the real work, pinning the archive to a list a
    reader can regenerate from a `git checkout`, so an asset replaced in place is still caught. And
    the files published beside it, whose block must be `sha256sum -c` format exactly, because the
    documented one-liner is `grep … | sha256sum -c -` and a hash the manifest gets wrong is a
    verification failure for every reader.
    """
    fields = parse_fields(manifest_text)
    embedded = parse_fields(release_text)
    violations: list[Violation] = []

    for field in _MANIFEST_REQUIRED:
        if field not in fields:
            violations.append(
                Violation(
                    f"the manifest carries {field}: a reader learns which inputs produced this "
                    f"file, not merely that somebody signed it",
                    "absent",
                )
            )
    if fields.get("format") not in (None, MANIFEST_FORMAT):
        violations.append(
            Violation(
                f"the manifest declares format: {MANIFEST_FORMAT}",
                fields.get("format", ""),
            )
        )

    for field in ("release", "git-commit", "source-date-epoch"):
        if field in fields and field in embedded and fields[field] != embedded[field]:
            violations.append(
                Violation(
                    f"the manifest's {field} is generated from /etc/aobs-release, so the image and "
                    f"the manifest cannot disagree (#61)",
                    f"manifest says {fields[field]}, the image says {embedded[field]}",
                )
            )

    if fields.get("git-tag") is not None and fields.get("release") != fields.get("git-tag"):
        violations.append(
            Violation(
                "the manifest's release and git-tag are the same string: the appliance displays "
                "one of them and the advisories name the other",
                f"release: {fields.get('release')}, git-tag: {fields.get('git-tag')}",
            )
        )

    if "inputs-list-sha256" in fields and fields["inputs-list-sha256"] != inputs_list_sha256:
        violations.append(
            Violation(
                "inputs-list-sha256 is the sha256 of build/inputs.sha256 as committed at the tag: "
                "it is what pins the archive to the source, so an archive replaced in place on "
                "GitHub Releases is still caught",
                f"{fields['inputs-list-sha256']}, the committed list hashes to {inputs_list_sha256}",
            )
        )

    if not parse_repeated_field(manifest_text, "signer"):
        violations.append(
            Violation(
                "the manifest names who was expected to sign it: the verifier can then tell "
                "`one of two signers` from `one, and no idea whether more were coming`",
                "no signer: line",
            )
        )

    listed = parse_checksum_list(manifest_text)
    if not listed:
        violations.append(
            Violation(
                "the manifest carries a contiguous block of `<sha256>  <name>` lines in "
                "`sha256sum -c` format: the documented command is "
                "`grep -E '^[0-9a-f]{64}  ' manifest.txt | sha256sum -c -`",
                "no checksum lines at all",
            )
        )
    for name in sorted(published):
        if name not in listed:
            violations.append(
                Violation(
                    f"every file published beside the manifest is named in it: {name} is not",
                    "absent from the checksum block",
                )
            )
        elif listed[name] != published[name]:
            violations.append(
                Violation(
                    f"the manifest's hash for {name} is the hash of the file being published",
                    f"{listed[name]}, the file hashes to {published[name]}",
                )
            )
    for name in sorted(set(listed) - set(published)):
        violations.append(
            Violation(
                f"the manifest names only files that are actually published: {name} is not one of "
                f"them, and a reader's `sha256sum -c` would fail on it",
                "named in the manifest, absent from the release",
            )
        )
    return violations


# --- The pinned parallelism ----------------------------------------------------------------------

#: `make -j` and `zstd -T`, the two places a core count could reach the build. `zstd`'s output
#: genuinely varies with the thread count; `make`'s does not, and it is pinned anyway, because a
#: contract that says "host architecture must not matter" cannot have one of its two parallelism
#: knobs read the machine and the other not — and the rule "nothing in the build calls `nproc`" is
#: checkable, while "only the one that matters" is a judgement call made afresh every time.
_PARALLELISM_FLAG = re.compile(r"(?:^|\s)(-j|-T)\s*(\S*)")

#: `MAKE_JOBS=4` at the top of a script, so the flag below may say `-j"$MAKE_JOBS"` and still be a
#: literal constant. Only a bare integer counts: `MAKE_JOBS=$(nproc)` is caught by the `nproc` rule
#: and `MAKE_JOBS=$OTHER` does not resolve, so neither can launder a core count through a name.
_LITERAL_ASSIGNMENT = re.compile(r"^(\w+)=(\d+)$")

_VARIABLE = re.compile(r'^"?\$\{?(\w+)\}?"?$')


def _constants(text: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for line in text.splitlines():
        match = _LITERAL_ASSIGNMENT.match(line.strip())
        if match:
            found[match.group(1)] = match.group(2)
    return found


def check_pinned_parallelism(sources: Mapping[str, str]) -> list[Violation]:
    """No build step derives its parallelism from the machine it runs on.

    `docs/reproducible-build.md` claim 1 puts **CPU count** and **host architecture** inside the
    reproducibility contract, and this is the cost of including them: `-j` and `zstd -T` are fixed
    constants. The guard that actually catches a regression here is CI building twice with
    `--cpus=2` against the runner's full count; this function is what catches it in 3 ms while
    somebody is editing the build.
    """
    violations: list[Violation] = []
    for name, text in sorted(sources.items()):
        constants = _constants(text)
        for number, raw in enumerate(text.splitlines(), start=1):
            line = raw.strip()
            if line.startswith("#"):
                continue
            if "nproc" in line:
                violations.append(
                    Violation(
                        "no build step derives its parallelism from the host's core count: "
                        "`make -j` and `zstd -T` are pinned constants "
                        "(`docs/reproducible-build.md` claim 1)",
                        f"{name}:{number}: {line}",
                    )
                )
                continue
            for flag, value in _PARALLELISM_FLAG.findall(line):
                variable = _VARIABLE.match(value)
                if variable:
                    value = constants.get(variable.group(1), "")
                if not value.isdigit():
                    violations.append(
                        Violation(
                            f"every {flag} in the build names a literal integer, directly or "
                            f"through a constant assigned in the same file: an empty or computed "
                            f"one is the host's core count by another route",
                            f"{name}:{number}: {line}",
                        )
                    )
                elif flag == "-T" and value == "0":
                    # The one literal that is not a constant: `zstd -T0` *means* "as many threads as
                    # there are cores", so it is the core-count dependence spelled as a digit — and
                    # it is the specific divergence source `docs/reproducible-build.md` lists sixth.
                    violations.append(
                        Violation(
                            "zstd -T names a thread count and never 0: `-T0` means one thread per "
                            "core, so the compressed output varies with the machine "
                            "(`docs/reproducible-build.md` divergence source 6)",
                            f"{name}:{number}: {line}",
                        )
                    )
    return violations
