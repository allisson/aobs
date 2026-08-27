"""Tests of the build's assertions rather than of the build.

`docs/boot-pipeline.md`'s *Build-time assertions* section is a list of **published claims**, and
each one is checked here twice: once against the real input in this repository, which must pass,
and once against an input broken on purpose, which must fail *and say which claim it broke*.

The second half is the part that matters. An assertion that has silently stopped checking anything
still passes against a good input; only a hostile input catches it. `tests/test_adversarial_corpus.py`
is the model — one input per attack, each with a declared expected verdict, so a new assertion is
added by adding an input rather than by hunting through test modules.

Nothing here builds an image. Every function under test is pure — text or a listing in, violations
out — which is the entire reason the verifier is a separate module from `build/mkiso.sh`.
"""

from __future__ import annotations

import importlib.util
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
BUILD = ROOT / "build"


def _load_verifier():
    """`build/` is deliberately not a package: the appliance never imports it.

    `tests/test_structure.py` asserts what may import what inside `aobs/`; putting the verifier
    on the normal import path would have forced an exception into those rules for a module the
    appliance never executes.
    """
    name = "aobs_build_verify"
    spec = importlib.util.spec_from_file_location(name, BUILD / "verify.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # `@dataclass` resolves `cls.__module__` through `sys.modules`, so a module loaded by path has
    # to be registered before its body runs or the decorator raises.
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


verify = _load_verifier()


def _config() -> str:
    return (BUILD / "kernel.config").read_text(encoding="utf-8")


def _pins() -> str:
    return (BUILD / "apk-versions.txt").read_text(encoding="utf-8")


def _set(config_text: str, symbol: str, value: str) -> str:
    """Turn one symbol on (or to any value) in a `.config`, however it is currently written.

    A symbol can be absent, disabled as `# CONFIG_X is not set`, or already set; a hostile input
    has to be able to override all three, or the mutation silently does nothing and the test that
    depends on it passes for the wrong reason.
    """
    line = f"{symbol}={value}"
    disabled = re.compile(rf"^# {re.escape(symbol)} is not set$", re.MULTILINE)
    if disabled.search(config_text):
        return disabled.sub(line, config_text)
    assigned = re.compile(rf"^{re.escape(symbol)}=.*$", re.MULTILINE)
    if assigned.search(config_text):
        return assigned.sub(line, config_text)
    return config_text + f"\n{line}\n"


def _unset(config_text: str, symbol: str) -> str:
    return re.sub(
        rf"^{re.escape(symbol)}=.*$",
        f"# {symbol} is not set",
        config_text,
        flags=re.MULTILINE,
    )


# --- The real inputs pass ------------------------------------------------------------------------


def test_the_checked_in_kernel_config_violates_nothing() -> None:
    """The one reviewable file #10 and #14 promise a reader can check by reading."""
    assert verify.check_kernel_config(_config()) == []


def test_the_vendored_tree_as_committed_violates_nothing() -> None:
    paths = [
        str(path.relative_to(ROOT))
        for path in (ROOT / "aobs" / "core" / "vendor").rglob("*")
        if "__pycache__" not in path.parts
    ]
    assert verify.check_vendored_tree(paths) == []


#: A listing with everything PID 1 needs and nothing a claim forbids. The hostile cases below add
#: one intruder to it, so that what they prove is the intruder and not an incidental absence.
MINIMAL_ROOTFS = [
    "/init",
    "/bin/busybox",
    "/bin/sh",
    "/usr/bin/python3",
    "/usr/bin/loadkeys",
    "/usr/lib/libsecp256k1.so.2",
    "/usr/lib/python3.14/site-packages/textual/__init__.py",
    "/etc/passwd",
    "/dev",
    "/proc",
]


def test_a_rootfs_listing_of_only_what_the_appliance_needs_violates_nothing() -> None:
    assert verify.check_rootfs(MINIMAL_ROOTFS) == []


@pytest.mark.parametrize("missing", sorted(verify.REQUIRED_PATHS))
def test_a_rootfs_missing_what_pid_1_needs_is_rejected(missing: str) -> None:
    """An image can fail by absence, and the first ISO build did exactly that.

    It produced a rootfs with no busybox — no `/bin/sh`, no `mount`, no `sleep`, no `poweroff` — in
    which PID 1 could not have run one line. Nothing objected, because every assertion until then
    was about what must *not* be in the image, and `build/Dockerfile.test` inherits busybox from the
    `alpine:3.24` base image, so the test tier had never needed it to be a listed dependency.
    """
    listing = [path for path in MINIMAL_ROOTFS if path != missing]
    violations = verify.check_rootfs(listing)
    assert any(missing in v.claim for v in violations), [v.claim for v in violations]


def test_a_manifest_matching_the_pins_violates_nothing() -> None:
    pins = verify.parse_pins(_pins())
    manifest = "\n".join(
        f"{name}-{version}" for name, version in pins[verify.APPLIANCE].items()
    )
    # A dependency the pins do not name is not a violation: which packages the closure pulls in is
    # decided by the pinned repository index, not by this file. What is pinned must match exactly.
    manifest += "\n" + "\n".join(["musl-1.2.6-r2", "libcrypto3-3.5.8-r0", "py3-pygments-2.20.0-r0"])
    assert verify.check_apk_manifest(manifest, _pins()) == []


# --- `build/apk-versions.txt` parses into two groups, machine-readably ---------------------------


def test_the_pins_split_into_an_appliance_group_and_a_harness_group() -> None:
    """The split used to be a prose comment, and `py3-pip` sits on the harness side of it.

    A naive parser — `grep -v '^#'`, which is what `build/Dockerfile.test` does and is right to do,
    because the test tier wants both halves — would put a package manager in the rootfs and nothing
    would notice. The marker is what lets the ISO build and the verifier read the groups without
    heuristics.
    """
    pins = verify.parse_pins(_pins())
    assert set(pins) == {verify.APPLIANCE, verify.HARNESS}
    assert pins[verify.APPLIANCE] == {
        "busybox": "1.37.0-r31",
        "busybox-binsh": "1.37.0-r31",
        "alpine-baselayout": "3.7.2-r1",
        "python3": "3.14.7-r1",
        "py3-cryptography": "47.0.0-r0",
        "py3-argon2-cffi": "25.1.0-r1",
        "py3-zxing-cpp": "2.3.0-r3",
        "py3-qrcode": "8.2-r2",
        "py3-textual": "8.2.7-r0",
        "py3-rich": "15.0.0-r0",
        "py3-pillow": "12.2.0-r0",
        "libsecp256k1": "0.5.0-r1",
        "kbd": "2.8.0-r0",
        "kbd-misc": "2.8.0-r0",
    }
    assert "py3-pip" not in pins[verify.APPLIANCE]
    assert "py3-pip" in pins[verify.HARNESS]


def test_every_pin_carries_an_exact_version() -> None:
    """`=~` would defeat the purpose, and so would a bare package name."""
    pins = verify.parse_pins(_pins())
    for group in pins.values():
        for name, version in group.items():
            assert re.fullmatch(r"[\w.+]+-r\d+", version), f"{name} is not pinned exactly"


def test_pins_with_no_group_marker_are_a_parse_error() -> None:
    """Fail loudly rather than guessing which half an unmarked package belongs to."""
    with pytest.raises(ValueError):
        verify.parse_pins("python3=3.14.7-r1\n")


# --- The kernel command line, per firmware path -------------------------------------------------


def test_the_bios_bootloader_config_carries_the_fixed_cmdline() -> None:
    cmdline = verify.cmdline_from_isolinux((BUILD / "isolinux.cfg").read_text(encoding="utf-8"))
    assert verify.check_cmdline(cmdline, verify.BIOS) == []


def test_the_uefi_bootloader_config_carries_the_fixed_cmdline() -> None:
    cmdline = verify.cmdline_from_grub((BUILD / "grub.cfg").read_text(encoding="utf-8"))
    assert verify.check_cmdline(cmdline, verify.UEFI) == []


def test_the_bios_path_carries_vga_791_and_the_uefi_path_does_not_need_it() -> None:
    """Without it `vgacon` gives 80×25 and #3's 85×43 QR code cannot be displayed at all."""
    bios = verify.cmdline_from_isolinux((BUILD / "isolinux.cfg").read_text(encoding="utf-8"))
    assert "vga=791" in bios.split()
    uefi = verify.cmdline_from_grub((BUILD / "grub.cfg").read_text(encoding="utf-8"))
    assert verify.check_cmdline(uefi, verify.UEFI) == []


BROKEN_CMDLINES = [
    ("rdrand_trusted", "random.trust_bootloader=off panic=0 init_on_free=1 vga=791", "random.trust_cpu=off"),
    ("bootloader_seed_trusted", "random.trust_cpu=off panic=0 init_on_free=1 vga=791", "random.trust_bootloader=off"),
    ("reboot_on_panic", "random.trust_cpu=off random.trust_bootloader=off init_on_free=1 vga=791", "panic=0"),
    ("panic_timeout_nonzero", "random.trust_cpu=off random.trust_bootloader=off panic=10 init_on_free=1 vga=791", "panic=0"),
    ("freed_pages_retained", "random.trust_cpu=off random.trust_bootloader=off panic=0 vga=791", "init_on_free=1"),
    ("no_framebuffer_on_bios", "random.trust_cpu=off random.trust_bootloader=off panic=0 init_on_free=1", "vga=791"),
    (
        "another_init",
        "random.trust_cpu=off random.trust_bootloader=off panic=0 init_on_free=1 vga=791 init=/bin/sh",
        "no init",
    ),
]


@pytest.mark.parametrize(
    ("cmdline", "expected"),
    [pytest.param(c, e, id=name) for name, c, e in BROKEN_CMDLINES],
)
def test_a_broken_cmdline_is_rejected_and_names_the_claim(cmdline: str, expected: str) -> None:
    violations = verify.check_cmdline(cmdline, verify.BIOS)
    assert violations, f"the verifier accepted a cmdline missing {expected}"
    assert any(expected in v.claim for v in violations), [v.claim for v in violations]


# --- Hostile kernel configs, one per claim ------------------------------------------------------

#: One broken config per published claim: (name, mutation, the text the violation must name).
#: A new assertion is added here as an input, not as a test function.
BROKEN_CONFIGS = [
    ("networking_on", lambda c: _set(c, "CONFIG_NET", "y"), "CONFIG_NET"),
    ("modules_on", lambda c: _set(c, "CONFIG_MODULES", "y"), "CONFIG_MODULES"),
    ("sysrq_on", lambda c: _set(c, "CONFIG_MAGIC_SYSRQ", "y"), "CONFIG_MAGIC_SYSRQ"),
    ("swap_on", lambda c: _set(c, "CONFIG_SWAP", "y"), "CONFIG_SWAP"),
    ("block_layer_on", lambda c: _set(c, "CONFIG_BLOCK", "y"), "CONFIG_BLOCK"),
    ("scsi_driver_on", lambda c: _set(c, "CONFIG_SCSI", "y"), "CONFIG_SCSI"),
    ("nvme_driver_on", lambda c: _set(c, "CONFIG_BLK_DEV_NVME", "y"), "CONFIG_BLK_DEV_NVME"),
    ("usb_storage_on", lambda c: _set(c, "CONFIG_USB_STORAGE", "y"), "CONFIG_USB_STORAGE"),
    ("mmc_driver_on", lambda c: _set(c, "CONFIG_MMC", "y"), "CONFIG_MMC"),
    ("kexec_on", lambda c: _set(c, "CONFIG_KEXEC", "y"), "CONFIG_KEXEC"),
    ("drm_on", lambda c: _set(c, "CONFIG_DRM", "y"), "CONFIG_DRM"),
    # The case a containment check wrongly passes: `usbhid` and `uvcvideo` are both still there.
    ("a_third_usb_class_driver", lambda c: _set(c, "CONFIG_SND_USB_AUDIO", "y"), "CONFIG_SND_USB_AUDIO"),
    ("usb_serial_class_driver", lambda c: _set(c, "CONFIG_USB_SERIAL", "y"), "CONFIG_USB_SERIAL"),
    ("usb_network_class_driver", lambda c: _set(c, "CONFIG_USB_NET_DRIVERS", "y"), "CONFIG_USB_NET_DRIVERS"),
    # The other direction: an equality fails when a required driver goes missing, too.
    ("no_hid_driver", lambda c: _unset(c, "CONFIG_USB_HID"), "CONFIG_USB_HID"),
    ("no_camera_driver", lambda c: _unset(c, "CONFIG_USB_VIDEO_CLASS"), "CONFIG_USB_VIDEO_CLASS"),
    ("no_fb_device", lambda c: _unset(c, "CONFIG_FB_DEVICE"), "CONFIG_FB_DEVICE"),
    ("no_fb_console", lambda c: _unset(c, "CONFIG_FRAMEBUFFER_CONSOLE"), "CONFIG_FRAMEBUFFER_CONSOLE"),
    ("no_efi_framebuffer", lambda c: _unset(c, "CONFIG_FB_EFI"), "CONFIG_FB_EFI"),
    ("no_vesa_framebuffer", lambda c: _unset(c, "CONFIG_FB_VESA"), "CONFIG_FB_VESA"),
    ("no_builtin_font", lambda c: _unset(c, "CONFIG_FONT_8x16"), "CONFIG_FONT_8x16"),
    ("no_initramfs_support", lambda c: _unset(c, "CONFIG_BLK_DEV_INITRD"), "CONFIG_BLK_DEV_INITRD"),
    ("no_zstd_initramfs", lambda c: _unset(c, "CONFIG_RD_ZSTD"), "CONFIG_RD_ZSTD"),
    ("no_tmpfs", lambda c: _unset(c, "CONFIG_TMPFS"), "CONFIG_TMPFS"),
]


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [pytest.param(m, e, id=name) for name, m, e in BROKEN_CONFIGS],
)
def test_a_broken_kernel_config_is_rejected_and_names_the_claim(mutate, expected: str) -> None:
    violations = verify.check_kernel_config(mutate(_config()))
    assert violations, f"the verifier accepted a config with {expected} wrong"
    assert any(expected in violation.claim for violation in violations), (
        f"a violation fired without naming {expected}: {[v.claim for v in violations]}"
    )


def test_a_symbol_set_to_m_is_as_bad_as_y() -> None:
    """`CONFIG_MODULES=n` makes `=m` impossible, but the verifier reads text, not a kernel."""
    violations = verify.check_kernel_config(_set(_config(), "CONFIG_SCSI", "m"))
    assert any("CONFIG_SCSI" in violation.claim for violation in violations)


def test_a_symbol_that_is_merely_absent_counts_as_missing() -> None:
    """Deleting a required line must fail exactly as setting it to `n` does."""
    config = "\n".join(
        line for line in _config().splitlines() if not line.startswith("CONFIG_TMPFS=")
    )
    assert any("CONFIG_TMPFS" in v.claim for v in verify.check_kernel_config(config))


# --- Hostile rootfs listings --------------------------------------------------------------------

BROKEN_ROOTFS = [
    ("getty", "/sbin/getty", "getty"),
    ("agetty", "/sbin/agetty", "getty"),
    ("login", "/bin/login", "login"),
    ("inittab", "/etc/inittab", "inittab"),
    ("apk", "/sbin/apk", "package manager"),
    ("pip", "/usr/bin/pip3", "package manager"),
    ("pip_package", "/usr/lib/python3.14/site-packages/pip/__init__.py", "package manager"),
    ("wget", "/usr/bin/wget", "network utility"),
    ("ip", "/sbin/ip", "network utility"),
    ("ssh", "/usr/bin/ssh", "network utility"),
    ("udhcpc", "/sbin/udhcpc", "network utility"),
    ("pytest", "/usr/bin/pytest", "test runner"),
    ("openrc", "/sbin/openrc", "init system"),
]


@pytest.mark.parametrize(
    ("intruder", "expected"),
    [pytest.param(p, e, id=name) for name, p, e in BROKEN_ROOTFS],
)
def test_a_rootfs_carrying_something_the_claims_forbid_is_rejected(
    intruder: str, expected: str
) -> None:
    violations = verify.check_rootfs(MINIMAL_ROOTFS + [intruder])
    assert violations, f"the verifier accepted a rootfs containing {intruder}"
    text = " ".join(v.claim + " " + v.saw for v in violations)
    assert expected in text, f"the violation does not name the claim: {text}"
    assert intruder in text, f"the violation does not say what it saw: {text}"


# --- Hostile vendored tree ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "intruder",
    [
        "aobs/core/vendor/embit/util/prebuilt",
        "aobs/core/vendor/embit/util/prebuilt/libsecp256k1_linux_x86_64.so",
    ],
)
def test_a_vendored_tree_carrying_the_prebuilt_blob_is_rejected(intruder: str) -> None:
    """`_find_library()` returns the prebuilt path whenever the file merely *exists*.

    It does not fall through when *loading* it fails, so on musl the bare `except:` silently
    selects the pure-Python fallback — which is exactly how the authoritative tier signed in pure
    Python for its whole life before #34.
    """
    violations = verify.check_vendored_tree(["aobs/core/vendor/embit/ec.py", intruder])
    assert violations
    assert any("prebuilt" in v.claim for v in violations)


# --- Hostile apk manifests ----------------------------------------------------------------------


def test_a_manifest_carrying_a_harness_package_is_rejected() -> None:
    """`py3-pip` reaching the rootfs through the file that pins the harness is the whole reason
    the section marker exists."""
    pins = verify.parse_pins(_pins())
    manifest = "\n".join(f"{n}-{v}" for n, v in pins[verify.APPLIANCE].items())
    manifest += "\npy3-pip-26.1.2-r0\n"
    violations = verify.check_apk_manifest(manifest, _pins())
    assert any("py3-pip" in v.saw for v in violations)
    assert any("harness" in v.claim for v in violations)


def test_a_manifest_at_the_wrong_version_is_rejected() -> None:
    """A `zxing-cpp`, `cryptography` or `libsecp256k1` skew must fail the build, not the session."""
    pins = verify.parse_pins(_pins())
    manifest = "\n".join(
        f"{n}-{'0.8.0-r0' if n == 'libsecp256k1' else v}"
        for n, v in pins[verify.APPLIANCE].items()
    )
    violations = verify.check_apk_manifest(manifest, _pins())
    assert any("libsecp256k1" in v.claim for v in violations)
    assert any("0.8.0-r0" in v.saw for v in violations)


def test_a_manifest_missing_a_pinned_package_is_rejected() -> None:
    pins = verify.parse_pins(_pins())
    manifest = "\n".join(
        f"{n}-{v}" for n, v in pins[verify.APPLIANCE].items() if n != "kbd-misc"
    )
    violations = verify.check_apk_manifest(manifest, _pins())
    assert any("kbd-misc" in v.claim for v in violations)


# --- A violation is actionable ------------------------------------------------------------------


def test_a_violation_says_which_claim_broke_and_what_it_saw() -> None:
    """A failing build must tell the maintainer the fact, not an exit code."""
    (violation,) = [
        v
        for v in verify.check_kernel_config(_set(_config(), "CONFIG_NET", "y"))
        if "CONFIG_NET" in v.claim
    ]
    assert violation.claim and violation.saw
    assert "CONFIG_NET=y" in str(violation)


def test_the_build_installs_the_appliance_group_and_nothing_from_the_harness() -> None:
    """What `build/mkiso.sh` passes to `apk add`, read the way the script reads it."""
    printed = subprocess.run(
        [sys.executable, str(BUILD / "gather.py"), "pins-of-group", "appliance",
         str(BUILD / "apk-versions.txt")],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    assert "python3=3.14.7-r1" in printed
    assert not [pin for pin in printed if pin.startswith(("py3-pytest", "py3-pip", "py3-hypothesis"))]


def test_pruning_removes_a_forbidden_busybox_applet_and_spares_a_real_file(tmp_path) -> None:
    """The prune step must never trade a false claim for a broken appliance.

    A symlink into busybox is an applet and removing it is what makes the claim true. A *regular*
    file with a forbidden name is a dependency of something, and deleting it silently would break
    the image — so it is left alone and `check_rootfs` fails the build on it instead.
    """
    (tmp_path / "bin").mkdir()
    (tmp_path / "sbin").mkdir()
    (tmp_path / "bin" / "busybox").write_text("#!/not/really\n")
    (tmp_path / "sbin" / "getty").symlink_to("/bin/busybox")
    (tmp_path / "bin" / "wget").symlink_to("/bin/busybox")
    (tmp_path / "bin" / "sh").symlink_to("/bin/busybox")
    (tmp_path / "sbin" / "login").write_text("a real binary, not an applet\n")

    subprocess.run(
        [sys.executable, str(BUILD / "gather.py"), "prune-busybox-applets", str(tmp_path)],
        capture_output=True,
        text=True,
        check=True,
    )

    assert not (tmp_path / "sbin" / "getty").exists()
    assert not (tmp_path / "bin" / "wget").exists()
    assert (tmp_path / "bin" / "sh").is_symlink(), "busybox `sh` stays, and that is deliberate"
    assert (tmp_path / "sbin" / "login").exists(), "a regular file is never silently deleted"
    assert verify.check_rootfs(["/sbin/login"]) != [], "and the build fails on it instead"


@pytest.mark.parametrize("script", ["init", "mkiso.sh"])
def test_the_shell_halves_of_the_build_parse(script: str) -> None:
    """PID 1 and the build script are the two things here that are not Python.

    A syntax error in PID 1 is a kernel panic on a machine with no recovery path, and it would be
    found by booting rather than by anything else in this suite. `sh -n` costs nothing.
    """
    result = subprocess.run(["sh", "-n", str(BUILD / script)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("script", ["init", "mkiso.sh"])
def test_the_shell_halves_of_the_build_are_executable(script: str) -> None:
    assert os.access(BUILD / script, os.X_OK), f"build/{script} is not executable"


def test_the_in_rootfs_assertions_pass_in_this_container_too() -> None:
    """`build/assert_in_rootfs.py` runs inside the built rootfs, where nothing here can reach it.

    What this test buys is narrow and worth having: a typo, a renamed embit symbol or a bad import
    in that script would otherwise surface minutes into an ISO build rather than in the dev loop.
    The container installs the same pinned apk versions the image installs, so the assertions are
    meaningful here as well — but the authoritative statement about the *image* is the build stage,
    not this test, and the backend-identity half of the script is only true where the appliance's
    environment is reproduced.
    """
    if os.environ.get("AOBS_AUTHORITATIVE_TIER") != "1":
        pytest.skip("the backend-identity assertion is a claim about the appliance's environment")
    result = subprocess.run(
        [sys.executable, str(BUILD / "assert_in_rootfs.py")],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(ROOT)},
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_the_verifier_never_raises_on_a_violation() -> None:
    """Reading is the caller's job and judging is the verifier's; a violation is a return value.

    This is what makes the hostile-input tests above possible at all, and it is why the build
    script contains no judgement of its own.
    """
    assert verify.check_kernel_config("") != []
    assert verify.check_rootfs(["/sbin/getty"]) != []
