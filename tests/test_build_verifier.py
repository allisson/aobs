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


def _load_by_path(path: Path):
    """`build/` is deliberately not a package: the appliance never imports it.

    `tests/test_structure.py` asserts what may import what inside `aobs/`; putting the verifier on
    the normal import path would have forced an exception into those rules for a module the
    appliance never executes.
    """
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[path.stem] = module
    spec.loader.exec_module(module)
    return module


# The verifier is taken off `gather.py` rather than loaded a second time here: `gather.py` already
# owns the by-path import — including registering it in `sys.modules` before its body runs, which
# `@dataclass` requires — and one incantation in the repository is one place for it to be wrong.
gather = _load_by_path(BUILD / "gather.py")
verify = gather.verify


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
    # `docs/boot-pipeline.md`'s *Time*: no clock service, and the appliance never displays a date
    # or time, because that judgement would require trusting a clock deliberately never set.
    ("rtc_driver_on", lambda c: _set(c, "CONFIG_RTC_CLASS", "y"), "CONFIG_RTC_CLASS"),
    ("rtc_sets_system_time", lambda c: _set(c, "CONFIG_RTC_HCTOSYS", "y"), "CONFIG_RTC_HCTOSYS"),
    ("core_dumps_on", lambda c: _set(c, "CONFIG_COREDUMP", "y"), "CONFIG_COREDUMP"),
    ("kcore_on", lambda c: _set(c, "CONFIG_PROC_KCORE", "y"), "CONFIG_PROC_KCORE"),
    ("rdrand_trusted", lambda c: _set(c, "CONFIG_RANDOM_TRUST_CPU", "y"), "CONFIG_RANDOM_TRUST_CPU"),
    ("freed_pages_retained", lambda c: _unset(c, "CONFIG_INIT_ON_FREE_DEFAULT_ON"), "CONFIG_INIT_ON_FREE_DEFAULT_ON"),
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
    ("hwclock", "/sbin/hwclock", "no clock service"),
    ("timezone_database", "/usr/share/zoneinfo/America/Sao_Paulo", "no timezone database"),
    ("localtime", "/etc/localtime", "no timezone database"),
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
    result = subprocess.run(
        [sys.executable, str(BUILD / "assert_in_rootfs.py")],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(ROOT)},
    )
    output = result.stdout + result.stderr
    if os.environ.get("AOBS_AUTHORITATIVE_TIER") == "1":
        assert result.returncode == 0, output
        return
    # Off-container, *which library* performs the EC is not a claim about anything: it is whatever
    # the host provides. `docs/test-harness.md` scopes the tier gate to exactly that half — "the
    # signature-vector check needs no gate and runs in both tiers" — so the rest must still pass
    # here, and only a lone backend-identity violation is tolerated.
    assert result.returncode == 0 or "the live EC backend" in output, output


def test_the_two_copies_of_the_signature_vector_agree() -> None:
    """The vector is pinned twice and the duplication is unavoidable: the rootfs carries no pytest.

    So the two cannot share a module, and nothing but this test stops them from drifting. If they
    ever disagree, one of them is wrong about the appliance and there is no way to tell which from
    either file alone.
    """
    from tests import test_structure

    rootfs = _load_by_path(BUILD / "assert_in_rootfs.py")
    assert rootfs.VECTOR_MESSAGE == test_structure._VECTOR_MESSAGE
    assert rootfs.EXPECTED_ECDSA == test_structure._EXPECTED_ECDSA


def test_the_build_fetches_no_wheel_and_installs_no_package_manager() -> None:
    """"No pip, no virtualenv, no wheel fetched at build time" — `docs/boot-pipeline.md`.

    A build whose entire selling point is that every input is pinned has no dependency resolver in
    it. `build/Dockerfile.test` does install a wheel (`urtypes`, an independent decoder used only by
    the suite) and is exempt for that reason: it builds the harness, not the image.
    """
    for name in ("Dockerfile.iso", "mkiso.sh"):
        text = (BUILD / name).read_text(encoding="utf-8")
        recipe = "\n".join(
            line for line in text.splitlines() if not line.lstrip().startswith("#")
        )
        for resolver in ("pip ", "pip3", "pip install", "virtualenv", "--break-system-packages"):
            assert resolver not in recipe, f"build/{name} reaches for {resolver}"


# --- The release engineering half (#66) ---------------------------------------------------------
#
# Every judgement below is one #54's eight closed tickets settled, and every test below feeds it a
# deliberately broken input. The shape is the same as the kernel-config tests above: name the claim,
# break the input, assert the verdict *and* that the violation names the claim.


def _inputs_list() -> str:
    return (BUILD / "inputs.sha256").read_text(encoding="utf-8")


# --- The input archive, judged on hash and on set equality --------------------------------------


def test_the_real_input_list_accepts_the_directory_it_describes() -> None:
    """The committed list, against a `present` mapping built from the list itself.

    Not a tautology: it asserts the list parses, that it is non-empty, and that `check_inputs`
    accepts the one input the whole archive design produces. A list nothing can satisfy would pass
    every hostile test below and fail every build.
    """
    present = verify.parse_checksum_list(_inputs_list())
    assert len(present) > 100, "the archive is ~200 files: appliance + toolchain closures"
    assert verify.check_inputs(present, _inputs_list()) == []


def test_an_input_with_a_wrong_hash_is_rejected_and_names_the_claim() -> None:
    present = verify.parse_checksum_list(_inputs_list())
    victim = sorted(present)[0]
    present[victim] = "0" * 64
    violations = verify.check_inputs(present, _inputs_list())
    assert [v for v in violations if victim in v.claim and "sha256" in v.claim]


def test_a_missing_input_is_rejected_and_names_the_claim() -> None:
    present = verify.parse_checksum_list(_inputs_list())
    victim = sorted(present)[0]
    del present[victim]
    violations = verify.check_inputs(present, _inputs_list())
    assert [v for v in violations if victim in v.claim and "is present" in v.claim]


def test_an_extra_input_is_a_failure_and_not_an_ignore() -> None:
    """The case a naive implementation ignores, and the reason the check is an equality.

    A rebuilder in 2030 unpacks a release asset into `build/inputs/`. If an unexpected `.apk` there
    were merely unused rather than refused, an attacker who can write to that directory has a place
    to put one — and `apk` resolving a closure against a local repository is exactly the kind of
    thing that would pick it up.
    """
    present = verify.parse_checksum_list(_inputs_list())
    present["apks/main/x86_64/backdoor-1.0-r0.apk"] = "a" * 64
    violations = verify.check_inputs(present, _inputs_list())
    assert [v for v in violations if "backdoor" in v.claim and "unexpected" in v.claim]


def test_an_empty_input_list_is_rejected_rather_than_vacuously_satisfied() -> None:
    """An empty list accepts every directory, which is the failure mode of a set equality."""
    assert verify.check_inputs({}, "") != []
    assert verify.check_inputs({"anything": "0" * 64}, "# only a comment\n") != []


# --- Nothing in the archive is pinned by a hash that moves on its own (#68) ----------------------


def test_no_apkindex_is_pinned_because_alpine_rewrites_it_on_its_own_schedule() -> None:
    """The regression this ticket exists to prevent: re-archiving Alpine's index.

    Alpine regenerates and re-signs both indexes whenever anything lands in the branch, so a pin
    over their bytes dies with no package version, no `.apk` and no closure having changed. That
    cost two claims at once — claim 5 red on pull requests it has nothing to do with, and claim 7
    false at release time, because two fetches of the same package set produced different archives.
    A pin that comes back is caught here rather than a day before a release.
    """
    listed = verify.parse_checksum_list(_inputs_list())
    assert [name for name in listed if name.endswith(".apk")], "the list still pins packages"
    assert not [name for name in listed if "APKINDEX" in name], (
        "build/inputs.sha256 pins an APKINDEX again: its bytes are Alpine's to rewrite, so the "
        "build generates its own from the archived .apk files instead (#68)"
    )


#: Every file that installs `.apk` files out of `build/inputs/`. There are **two**, they are easy to
#: change apart, and the second one is the one that got missed: `Dockerfile.iso` installs the
#: toolchain closure into the builder before `mkiso.sh` exists to run, so it needs its own index and
#: its own flags. CI caught it as `opening .../APKINDEX.tar.gz: No such file or directory` followed
#: by `unable to select packages` — after a green test suite, because nothing here was looking.
INSTALLS_FROM_INPUTS = ("mkiso.sh", "Dockerfile.iso")


def _installer(name: str) -> str:
    return (BUILD / name).read_text(encoding="utf-8")


@pytest.mark.parametrize("name", INSTALLS_FROM_INPUTS)
def test_every_place_that_installs_from_the_archive_generates_its_own_index(name: str) -> None:
    """`apk` cannot resolve a local repository without an index, and none is archived (#68)."""
    text = _installer(name)
    assert "apk add" in text or "add $PACKAGES" in text, (
        f"{name} is in INSTALLS_FROM_INPUTS but installs nothing — fix the list, not the test"
    )
    assert [line for line in text.splitlines() if line.strip().startswith("apk index")], (
        f"{name} installs from build/inputs/ without generating an index first: no Alpine index is "
        "archived, so `apk` has nothing to resolve against"
    )


@pytest.mark.parametrize("name", INSTALLS_FROM_INPUTS)
def test_every_generated_index_rewrites_the_arch_of_noarch_packages(name: str) -> None:
    """`--rewrite-arch` is load-bearing, and without it the error names the wrong cause.

    Alpine's published index for an arch directory rewrites `A:noarch` to that arch. A plain
    `apk index` leaves it, and `apk` then looks for those packages under `<repo>/noarch/`. Measured,
    not supposed: 46 of 96 packages fail — `busybox-binsh`, `alpine-baselayout` and every `-pyc`
    subpackage — each reported as `package mentioned in index not found (try 'apk update')`, on a
    directory where the file is present and the index was generated a second earlier.
    """
    calls = [line for line in _installer(name).splitlines() if line.strip().startswith("apk index")]
    assert calls, "the `apk index` call is code, not only prose"
    assert all("--rewrite-arch x86_64" in line for line in calls), (
        f"{name} runs apk index without --rewrite-arch, which leaves every noarch package "
        "unfindable under the arch directory it is actually in"
    )


@pytest.mark.parametrize("name", INSTALLS_FROM_INPUTS)
def test_every_install_states_that_it_allows_an_untrusted_index(name: str) -> None:
    """A locally generated index carries no Alpine signature, and the build says so out loud.

    The alternative considered and rejected was a self-signed index: it would satisfy `apk` with a
    key this build minted and read like a signature check to anyone who did not look. What replaces
    Alpine's install-time check is stage 0's, over every byte that index describes.
    """
    text = _installer(name)
    assert "--allow-untrusted" in text
    assert "abuild-sign" not in text, "a self-signed index is signature theatre, not a check"


# --- The toolchain list has exactly one group ---------------------------------------------------


def test_the_real_toolchain_list_carries_exactly_the_toolchain_group() -> None:
    assert verify.check_toolchain_list(_toolchain()) == []


def test_a_second_group_in_the_toolchain_list_is_rejected() -> None:
    """`Dockerfile.iso` and `fetch-inputs.sh` read that file as every non-comment line, which is
    correct only while it has one group — the same hazard the `@group` markers closed once."""
    violations = verify.check_toolchain_list(_toolchain() + "\n# @group harness\npy3-pip=1.0-r0\n")
    assert [v for v in violations if "exactly one group" in v.claim]


def test_an_unpinned_toolchain_package_is_rejected() -> None:
    violations = verify.check_toolchain_list(_toolchain() + "\ngcc\n")
    assert [v for v in violations if "name=version" in v.claim]


def _toolchain() -> str:
    return (BUILD / "toolchain-versions.txt").read_text(encoding="utf-8")


# --- The embedded release line ------------------------------------------------------------------

_COMMIT = "4f1c8a6e2b90d7c35a18ef04b6d2917c0ae53b81"
_EPOCH = "1773446400"


def _release_file(**overrides: str) -> str:
    fields = {
        "release": "v1.0",
        "released": "2026-03-14",
        "git-commit": _COMMIT,
        "source-date-epoch": _EPOCH,
        "dirty": "no",
    }
    fields.update(overrides)
    return "".join(f"{key}: {value}\n" for key, value in fields.items())


def _judge_release(text: str, *, tag: str = "v1.0", dirty: bool = False) -> list:
    return verify.check_embedded_release(
        text, tag=tag, head_commit=_COMMIT, dirty=dirty, source_date_epoch=_EPOCH
    )


def test_a_matching_release_line_is_accepted() -> None:
    assert verify.utc_date(_EPOCH) == "2026-03-14"
    assert _judge_release(_release_file()) == []


def test_a_release_line_naming_another_version_than_the_tag_is_rejected() -> None:
    violations = _judge_release(_release_file(release="v0.9"))
    assert [v for v in violations if "the signed tag" in v.claim]


def test_a_release_line_naming_another_commit_than_head_is_rejected() -> None:
    violations = _judge_release(_release_file(**{"git-commit": "b" * 40}))
    assert [v for v in violations if "git-commit is HEAD" in v.claim]


def test_a_dirty_tree_may_not_claim_a_version() -> None:
    """The `-dirty` build is a development build by every definition this project uses."""
    violations = _judge_release(_release_file(dirty="yes"), dirty=True)
    assert [v for v in violations if "version-shaped string" in v.claim]


def test_a_development_build_is_skipped_rather_than_faked() -> None:
    """No tag at HEAD: the tag assertion does not apply, and nothing is invented in its place."""
    development = _release_file(release=verify.DEVELOPMENT)
    assert _judge_release(development, tag="") == []


def test_a_development_build_that_claims_a_version_is_rejected() -> None:
    violations = _judge_release(_release_file(release="v1.0"), tag="")
    assert [v for v in violations if verify.DEVELOPMENT in v.claim]


def test_a_release_line_missing_a_field_says_which_one() -> None:
    for field in ("release", "released", "git-commit", "source-date-epoch", "dirty"):
        text = "".join(
            line + "\n"
            for line in _release_file().splitlines()
            if not line.startswith(f"{field}:")
        )
        violations = _judge_release(text)
        assert [v for v in violations if field in v.claim], field


def test_a_released_date_that_is_not_the_epoch_is_rejected() -> None:
    """The appliance may not import `datetime`, so the build is the only place the epoch becomes a
    date — and this is the only thing keeping the two halves of that arrangement consistent."""
    violations = _judge_release(_release_file(released="2020-01-01"))
    assert [v for v in violations if "released date" in v.claim]


def test_a_release_line_carrying_a_truncated_commit_is_rejected() -> None:
    violations = _judge_release(_release_file(**{"git-commit": _COMMIT[:12]}))
    assert [v for v in violations if "40-hex" in v.claim]


def test_an_epoch_the_build_did_not_run_under_is_rejected() -> None:
    violations = _judge_release(_release_file(**{"source-date-epoch": "1", "released": "1970-01-01"}))
    assert [v for v in violations if "source-date-epoch" in v.claim]


def test_the_appliance_and_the_build_parse_the_release_file_the_same_way() -> None:
    """Two parsers for one format, and this is what stops them drifting.

    `build/verify.py` cannot import the appliance and the appliance cannot import `build/`, so
    `/etc/aobs-release` is read twice. The format is four `key: value` lines; the risk is not that
    either parser is hard, it is that one of them is changed and the other is not.
    """
    from aobs.core.release import parse

    text = _release_file()
    appliance = parse(text)
    build = verify.parse_fields(text)
    assert appliance.release == build["release"]
    assert appliance.released == build["released"]
    assert appliance.commit == build["git-commit"]
    assert appliance.dirty is (build["dirty"] == "yes")


# --- The four release-mode refusals ------------------------------------------------------------


def _facts(**overrides) -> object:
    fields = {
        "head_commit": _COMMIT,
        "dirty": False,
        "tag": "v1.0",
        "tag_signed": True,
        "tag_commit_date": _EPOCH,
    }
    fields.update(overrides)
    return verify.GitFacts(**fields)


def test_a_clean_signed_tagged_tree_passes_the_preflight() -> None:
    assert (
        verify.check_release_preflight(
            _facts(), source_date_epoch=_EPOCH, manifest_commit=_COMMIT
        )
        == []
    )


@pytest.mark.parametrize(
    "overrides, epoch, manifest_commit, expected",
    [
        ({"dirty": True}, _EPOCH, _COMMIT, "clean working tree"),
        ({"tag": "", "tag_commit_date": ""}, _EPOCH, _COMMIT, "annotated tag"),
        ({"tag_signed": False}, _EPOCH, _COMMIT, "signed by the maintainer"),
        ({}, "1773446401", _COMMIT, "SOURCE_DATE_EPOCH"),
        ({}, _EPOCH, "c" * 40, "manifest's git-commit is HEAD"),
    ],
    ids=["dirty", "untagged", "unsigned-tag", "hand-set-epoch", "manifest-not-head"],
)
def test_each_release_mode_refusal_fires_on_its_own_hostile_input(
    overrides: dict, epoch: str, manifest_commit: str, expected: str
) -> None:
    violations = verify.check_release_preflight(
        _facts(**overrides), source_date_epoch=epoch, manifest_commit=manifest_commit
    )
    assert [v for v in violations if expected in v.claim], violations


@pytest.mark.parametrize(
    "overrides, epoch, manifest_commit",
    [
        ({"dirty": True}, _EPOCH, _COMMIT),
        ({"tag": "", "tag_commit_date": ""}, _EPOCH, _COMMIT),
        ({"tag_signed": False}, _EPOCH, _COMMIT),
        ({}, "1773446401", _COMMIT),
        ({}, _EPOCH, "c" * 40),
    ],
    ids=["dirty", "untagged", "unsigned-tag", "hand-set-epoch", "manifest-not-head"],
)
def test_no_release_mode_refusal_fires_in_development_mode(
    overrides: dict, epoch: str, manifest_commit: str
) -> None:
    """A guard that fires during ordinary work gets disabled, and then it guards nothing on the day
    it mattered. Every one of the four is silent for a build that is not cutting a release."""
    assert (
        verify.check_release_preflight(
            _facts(**overrides),
            source_date_epoch=epoch,
            manifest_commit=manifest_commit,
            release_mode=False,
        )
        == []
    )


def test_a_tag_that_is_not_vmajor_minor_is_rejected() -> None:
    violations = verify.check_release_preflight(
        _facts(tag="release-1.0"), source_date_epoch=_EPOCH, manifest_commit=_COMMIT
    )
    assert [v for v in violations if "vMAJOR.MINOR" in v.claim]


def test_a_preflight_with_no_manifest_yet_judges_the_other_three() -> None:
    """The preflight runs before the manifest is written as well as after it."""
    assert (
        verify.check_release_preflight(_facts(), source_date_epoch=_EPOCH, manifest_commit=None)
        == []
    )


# --- The manifest ------------------------------------------------------------------------------

_ISO_SHA = "a" * 64
_ARCHIVE_SHA = "b" * 64
_LIST_SHA = "c" * 64


def _manifest(**overrides: str) -> str:
    fields = {
        "format": verify.MANIFEST_FORMAT,
        "release": "v1.0",
        "released": "2026-03-14",
        "git-tag": "v1.0",
        "git-commit": _COMMIT,
        "source-date-epoch": _EPOCH,
        "iso-name": "bitcoin-signer-amd64.iso",
        "alpine-branch": "v3.24",
        "aports-commit": "0934530484bbcde7498e2c694c710a49616a450e",
        "inputs-list-sha256": _LIST_SHA,
    }
    fields.update(overrides)
    return (
        "# a comment sha256sum -c would choke on\n"
        + "".join(f"{key}: {value}\n" for key, value in fields.items())
        + f"signer: {verify.BUILDER_FINGERPRINT} builder\n"
        + "input-kernel: linux-6.12.106.tar.xz sha256=" + "d" * 64 + "\n"
        + f"{_ISO_SHA}  bitcoin-signer-amd64.iso\n"
        + f"{_ARCHIVE_SHA}  aobs-inputs-v1.0.tar\n"
    )


_PUBLISHED = {
    "bitcoin-signer-amd64.iso": _ISO_SHA,
    "aobs-inputs-v1.0.tar": _ARCHIVE_SHA,
}


def _judge_manifest(text: str, **overrides) -> list:
    arguments = {
        "release_text": _release_file(),
        "inputs_list_sha256": _LIST_SHA,
        "published": _PUBLISHED,
    }
    arguments.update(overrides)
    return verify.check_manifest(text, **arguments)


def test_a_consistent_manifest_is_accepted() -> None:
    assert _judge_manifest(_manifest()) == []


def test_the_documented_one_liner_extracts_exactly_the_published_files() -> None:
    """The format was decided by measurement: `sha256sum -c` cannot read a file with comments in it,
    so the documented command is a `grep` nobody would guess unaided. This asserts the `grep` the
    README prints selects the block and nothing else."""
    selected = [
        line
        for line in _manifest().splitlines()
        if re.match(r"^[0-9a-f]{64}  ", line)
    ]
    assert len(selected) == len(_PUBLISHED)
    assert "input-kernel" not in "\n".join(selected)


@pytest.mark.parametrize(
    "field", ["format", "release", "git-tag", "git-commit", "iso-name", "inputs-list-sha256"]
)
def test_a_manifest_missing_a_field_says_which_one(field: str) -> None:
    text = "\n".join(
        line for line in _manifest().splitlines() if not line.startswith(f"{field}:")
    )
    violations = _judge_manifest(text)
    assert [v for v in violations if field in v.claim], field


def test_a_manifest_disagreeing_with_the_image_is_rejected() -> None:
    """#61: `release` and `git-commit` are *generated from* `/etc/aobs-release`, so there is nothing
    for the image and the manifest to disagree about — and this is what proves it."""
    for field, value in (("release", "v9.9"), ("git-commit", "e" * 40)):
        violations = _judge_manifest(_manifest(**{field: value}))
        assert [v for v in violations if "cannot disagree" in v.claim], field


def test_a_manifest_naming_the_wrong_input_list_is_rejected() -> None:
    """`inputs-list-sha256` is the field doing the real work: it pins the archive to a list a reader
    can regenerate from a `git checkout`, so an asset replaced in place is still caught."""
    violations = _judge_manifest(_manifest(**{"inputs-list-sha256": "f" * 64}))
    assert [v for v in violations if "inputs-list-sha256" in v.claim]


def test_a_manifest_with_a_wrong_published_hash_is_rejected() -> None:
    violations = _judge_manifest(_manifest(), published={**_PUBLISHED, "bitcoin-signer-amd64.iso": "9" * 64})
    assert [v for v in violations if "bitcoin-signer-amd64.iso" in v.claim]


def test_a_manifest_naming_a_file_that_is_not_published_is_rejected() -> None:
    """A reader's `sha256sum -c` would fail on it, so the manifest may not name it."""
    published = {name: value for name, value in _PUBLISHED.items() if name.endswith(".iso")}
    violations = _judge_manifest(_manifest(), published=published)
    assert [v for v in violations if "aobs-inputs-v1.0.tar" in v.claim]


def test_a_manifest_with_no_signer_line_is_rejected() -> None:
    text = "\n".join(
        line for line in _manifest().splitlines() if not line.startswith("signer:")
    )
    violations = _judge_manifest(text)
    assert [v for v in violations if "expected to sign" in v.claim]


def test_a_manifest_with_no_checksum_block_is_rejected() -> None:
    text = "\n".join(
        line for line in _manifest().splitlines() if not re.match(r"^[0-9a-f]{64}  ", line)
    )
    violations = _judge_manifest(text)
    assert [v for v in violations if "sha256sum -c" in v.claim]


def test_the_declared_signers_are_the_fingerprints_the_verifier_hardcodes() -> None:
    """The declared list and the accepted list are different things by design, and they must agree.

    `verify-release.sh` hardcodes the fingerprints it accepts, because trusting the manifest to say
    who may sign it is circular. The `signer:` lines exist to tell *one of two* from *one, and no
    idea whether more were coming* — and that only works while the two lists name the same people.
    """
    script = (ROOT / "verify-release.sh").read_text(encoding="utf-8")
    assert f"KNOWN_BUILDER={verify.BUILDER_FINGERPRINT}" in script
    assert f"KNOWN_WITNESS={verify.WITNESS_FINGERPRINT}" in script
    declared = {fingerprint for fingerprint, _ in verify.SIGNERS}
    assert declared == {verify.BUILDER_FINGERPRINT}, (
        "no witness key exists yet; when one does, both this list and verify-release.sh gain it"
    )


# --- The pinned parallelism ---------------------------------------------------------------------


def test_the_real_build_derives_no_parallelism_from_the_core_count() -> None:
    sources = {
        name: (ROOT / name).read_text(encoding="utf-8")
        for name in ("build/mkiso.sh", "build/Dockerfile.iso", "build/fetch-inputs.sh")
    }
    assert verify.check_pinned_parallelism(sources) == []


@pytest.mark.parametrize(
    "line",
    [
        'make ARCH=x86_64 -j"$(nproc)" bzImage',
        "zstd -q -19 -T0 -o out.zst",
        "JOBS=$(nproc)",
        'make -j"$JOBS" all',
    ],
    ids=["nproc-in-j", "zstd-T0", "nproc-in-a-variable", "unresolvable-variable"],
)
def test_a_build_step_that_reads_the_machine_is_rejected(line: str) -> None:
    """`docs/reproducible-build.md` claim 1 puts CPU count and host architecture inside the
    contract; `zstd`'s output genuinely varies with the thread count. The CI guard catches a
    regression here by building twice with `--cpus=2`; this catches it in 3 ms."""
    assert verify.check_pinned_parallelism({"script.sh": line}) != []


def test_a_pinned_constant_is_accepted_directly_or_through_a_name() -> None:
    assert verify.check_pinned_parallelism({"s": "make -j4 all\nzstd -T1 -o x"}) == []
    assert (
        verify.check_pinned_parallelism({"s": "MAKE_JOBS=4\nmake -j\"$MAKE_JOBS\" all"}) == []
    )


def test_a_comment_mentioning_nproc_is_not_a_violation() -> None:
    """The rule is about what the build *does*, and `mkiso.sh` explains at length why it does not
    call `nproc` — a check that could not survive its own documentation is a check nobody keeps."""
    assert verify.check_pinned_parallelism({"s": "# never nproc, see the contract"}) == []


def test_the_verifier_never_raises_on_a_violation() -> None:
    """Reading is the caller's job and judging is the verifier's; a violation is a return value.

    This is what makes the hostile-input tests above possible at all, and it is why the build
    script contains no judgement of its own.
    """
    assert verify.check_kernel_config("") != []
    assert verify.check_rootfs(["/sbin/getty"]) != []
    assert verify.check_inputs({}, "") != []
    assert verify.check_toolchain_list("gcc") != []
    assert _judge_release("") != []
    assert verify.check_release_preflight(_facts(dirty=True), source_date_epoch="", manifest_commit=None) != []
    assert _judge_manifest("") != []
    assert verify.check_pinned_parallelism({"s": "make -j$(nproc)"}) != []


# --- The two metadata sources, and which question each answers (#68) ----------------------------
#
# `build/apkindex.py` reads an `APKINDEX` for the one question only an index can answer — which
# repository a package came from, and the recipe commit of a package the archive does not carry —
# and each `.apk`'s own `.PKGINFO` for everything about the bytes the archive does carry. The two
# agree field for field, because `apk index` generates the index from exactly that file.

apkindex = _load_by_path(BUILD / "apkindex.py")


def _fake_apk(path: Path, fields: dict[str, str]) -> Path:
    """An `.apk`-shaped file: concatenated gzip streams, `.PKGINFO` in the second.

    The shape is the point. A reader that opens only the first stream finds the signature segment
    and no `.PKGINFO` at all, which is the bug this fixture exists to keep caught.
    """
    import gzip
    import io
    import tarfile

    def segment(members: dict[str, bytes]) -> bytes:
        raw = io.BytesIO()
        with tarfile.open(fileobj=raw, mode="w") as archive:
            for name, body in members.items():
                info = tarfile.TarInfo(name)
                info.size = len(body)
                archive.addfile(info, io.BytesIO(body))
        return gzip.compress(raw.getvalue())

    pkginfo = "".join(f"{key} = {value}\n" for key, value in fields.items()).encode()
    path.write_bytes(
        segment({".SIGN.RSA.alpine-devel@example-0000.rsa.pub": b"signature"})
        + segment({".PKGINFO": pkginfo})
    )
    return path


def test_pkginfo_is_read_past_the_signature_segment() -> None:
    """The control segment is the *second* gzip stream, behind end-of-archive padding.

    Without `ignore_zeros` `tarfile` stops at the first segment's padding and the licence, origin
    and aports commit silently become the NOTICE's fallback strings — a written offer pointing
    nowhere, on a file that still looks well-formed.
    """
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        apk = _fake_apk(
            Path(directory) / "busybox-1.37.0-r31.apk",
            {
                "pkgname": "busybox",
                "pkgver": "1.37.0-r31",
                "license": "GPL-2.0-only",
                "origin": "busybox",
                "commit": "c3ef5d10e6ef6528852c51f0564963e2f8c1be19",
            },
        )
        assert apkindex.pkginfo(apk) == {
            "name": "busybox",
            "version": "1.37.0-r31",
            "licence": "GPL-2.0-only",
            "origin": "busybox",
            "aports-commit": "c3ef5d10e6ef6528852c51f0564963e2f8c1be19",
        }


def test_the_notice_records_every_archived_package_from_its_own_bytes() -> None:
    """One row per `.apk` present, licence and aports commit included, both repositories walked."""
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        inputs = Path(directory)
        for repository, name in (("main", "busybox"), ("community", "cpio")):
            (inputs / "apks" / repository / "x86_64").mkdir(parents=True)
            _fake_apk(
                inputs / "apks" / repository / "x86_64" / f"{name}-1.0-r0.apk",
                {"pkgname": name, "pkgver": "1.0-r0", "license": "GPL-2.0-only",
                 "origin": name, "commit": "0" * 40},
            )
        text = apkindex.notice(inputs)

    rows = [line for line in text.splitlines() if line.startswith("  ") and ".apk |" in line]
    assert len(rows) == 2, "both repositories are walked, not only main"
    assert all("GPL-2.0-only" in row and "0" * 40 in row for row in rows)
    assert "declared by no metadata" not in text and "not recorded in .PKGINFO" not in text, (
        "every row carries a real licence and a real commit: the fallbacks are what a written "
        "offer pointing nowhere looks like"
    )


# --- The aports pointer survives having no index (#68) ------------------------------------------


def test_the_aports_pointer_is_read_from_the_archive_and_not_from_an_index() -> None:
    """`alpine-release` is the branch's release marker and this build neither installs nor archives
    it, so its recipe commit is answerable only while an index is in hand. The fetcher records it
    above the first `@closure` marker; the manifest reads it from there, offline."""
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        inputs = Path(directory)
        (inputs / "CLOSURES.txt").write_text(
            "# @aports-commit alpine-release 0934530484bbcde7498e2c694c710a49616a450e\n"
            "# @closure appliance\nbusybox-1.37.0-r31.apk\n"
            "# @closure toolchain\ngcc-15.2.0-r5.apk\n",
            encoding="utf-8",
        )
        assert gather._aports_commit(inputs) == "0934530484bbcde7498e2c694c710a49616a450e"
        assert gather._closures(inputs) == {
            "appliance": ["busybox-1.37.0-r31.apk"],
            "toolchain": ["gcc-15.2.0-r5.apk"],
        }, "the marker sits where the closure reader ignores it"


def test_a_missing_aports_marker_is_a_hard_failure_and_not_an_empty_field() -> None:
    """A manifest that silently names no commit is a written offer pointing nowhere."""
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        inputs = Path(directory)
        (inputs / "CLOSURES.txt").write_text("# @closure appliance\nbusybox-1.37.0-r31.apk\n",
                                             encoding="utf-8")
        with pytest.raises(SystemExit):
            gather._aports_commit(inputs)
