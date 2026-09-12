"""Every assertion in `build/verify.py`, fed a deliberately broken input.

`CLAUDE.md`: the build fails rather than warns at the first stage where a published claim stops
being true — and an assertion nobody has watched fail is an assertion nobody has checked. So each
function here is run twice: once against the committed pin files, which must pass, and once
against an input broken in the exact way that function exists to catch, which must raise.

This module is the M1 half. `docs/roadmap.md` M2 brings back the rest, written against the Debian
build rather than ported from the Alpine `tests/test_build_verifier.py` this file replaces.
"""

from __future__ import annotations

import importlib.util
import io
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# `build/` is source but not a package — it is read by `sh` and by the image build, neither of
# which imports it — so it is loaded by path rather than by name.
_spec = importlib.util.spec_from_file_location("aobs_build_verify", ROOT / "build" / "verify.py")
assert _spec is not None and _spec.loader is not None
verify = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(verify)


APT_TEXT = (ROOT / "build" / "apt-versions.txt").read_text(encoding="utf-8")
WHEEL_TEXT = (ROOT / "build" / "wheel-versions.txt").read_text(encoding="utf-8")

#: A pin file in miniature. Every broken case below is this with one thing wrong, so that what a
#: test proves is the one difference and not the fixture.
GOOD = """\
# a comment
# @group appliance
python3=3.13.5-1
libsecp256k1-2=0.5.0-2+b1

# @group harness
git=1:2.47.3-0+deb13u1
"""


# --- The parser -----------------------------------------------------------------------------------


def test_the_committed_pin_files_parse() -> None:
    """Not a formality: it is what makes every broken-input test below a statement about the
    checker rather than about a fixture nobody ships."""
    apt = verify.parse_pin_file(APT_TEXT, source="apt-versions.txt")
    wheels = verify.parse_pin_file(WHEEL_TEXT, source="wheel-versions.txt")

    assert apt["appliance"]["python3"] == "3.13.5-1"
    assert apt["harness"]["python3-pip"] == "25.1.1+dfsg-1"
    assert wheels["appliance"]["cryptography"] == "50.0.0"
    assert wheels["harness"]["pytest"] == "9.1.1"


def test_a_pin_before_any_group_marker_is_a_parse_error() -> None:
    """The predecessor's exact failure. The split was a prose comment, `py3-pip` sat on the far
    side of it, and a parser that guessed put a package manager in a rootfs that claims to carry
    none."""
    broken = "python3-pip=25.1.1+dfsg-1\n" + GOOD
    with pytest.raises(verify.PinFileError, match="before any"):
        verify.parse_pin_file(broken)


def test_a_group_name_that_is_not_one_of_the_two_is_a_parse_error() -> None:
    """`build/apt-versions.txt` records why a third `@group buildtime` was rejected rather than
    added: it would answer a different question than the one that guards the image."""
    broken = GOOD.replace("# @group harness", "# @group buildtime")
    with pytest.raises(verify.PinFileError, match="unknown group"):
        verify.parse_pin_file(broken)


def test_a_line_that_is_neither_a_pin_nor_a_comment_is_a_parse_error() -> None:
    """An unpinned name is the one thing a pinned list may never contain, and `python3` on its own
    line reads like a pin until something refuses it."""
    with pytest.raises(verify.PinFileError, match="not a pin"):
        verify.parse_pin_file(GOOD + "busybox\n")


def test_a_name_pinned_twice_in_one_group_is_a_parse_error() -> None:
    """Two versions of one fact in a list a human reads top to bottom: the second wins silently,
    and which one that is depends on the parser rather than on a decision."""
    broken = GOOD.replace("libsecp256k1-2=", "python3=3.13.4-1\nlibsecp256k1-2=")
    with pytest.raises(verify.PinFileError, match="twice in the appliance group"):
        verify.parse_pin_file(broken)


def test_a_file_missing_a_group_entirely_is_a_parse_error() -> None:
    """Both groups must be declared even when one is empty, or a deleted marker reads as an empty
    harness group rather than as a file whose split has gone missing."""
    with pytest.raises(verify.PinFileError, match="no `# @group` marker"):
        verify.parse_pin_file("# @group appliance\npython3=3.13.5-1\n")


def test_a_trailing_comment_on_a_pin_is_not_an_error() -> None:
    """`colorama==0.4.6  # marker: sys_platform == 'win32'` is in the committed wheel list, kept
    visible so its absence from `build/inputs.sha256` reads as intentional."""
    parsed = verify.parse_pin_file("# @group appliance\ncolorama==0.4.6  # win32 only\n"
                                   "# @group harness\n")
    assert parsed["appliance"] == {"colorama": "0.4.6"}


# --- Disjointness ---------------------------------------------------------------------------------


def test_the_committed_groups_are_disjoint() -> None:
    verify.groups_are_disjoint(verify.parse_pin_file(APT_TEXT))
    verify.groups_are_disjoint(verify.parse_pin_file(WHEEL_TEXT))


def test_a_package_in_both_groups_fails() -> None:
    """`mkiso.sh` installs the appliance group; M2's verifier refuses to find the harness group in
    the rootfs. A name in both makes those two statements contradict, and the contradiction would
    be settled by whichever check ran last."""
    broken = verify.parse_pin_file(GOOD)
    broken["harness"]["python3"] = "3.13.5-1"
    with pytest.raises(verify.PinFileError, match="BOTH"):
        verify.groups_are_disjoint(broken)


def test_the_wheel_groups_are_disjoint_by_name_and_not_only_by_version() -> None:
    """`gather-wheel-versions.sh` takes the set difference over the whole `name==version` token,
    so a package whose version differs between the two exports lands in both groups. That is the
    intended visibility — and it is still a defect, which is what this proves."""
    both = verify.parse_pin_file(
        "# @group appliance\ncryptography==50.0.0\n"
        "# @group harness\ncryptography==49.0.0\n"
    )
    with pytest.raises(verify.PinFileError, match="cryptography"):
        verify.groups_are_disjoint(both)


# --- The apt/wheel seam ---------------------------------------------------------------------------


def test_the_committed_lists_keep_python_on_one_side_of_the_seam() -> None:
    verify.no_apt_package_shadows_a_wheel(
        verify.parse_pin_file(APT_TEXT), verify.parse_pin_file(WHEEL_TEXT)
    )


def test_a_debian_python_package_that_shadows_a_wheel_fails() -> None:
    """Debian's `python3-cryptography` and the lock's `cryptography` are two unrelated resolutions
    of one import. `docs/adr/0002` calls this two resolvers over one import graph; they agree
    until the first time either moves."""
    apt = verify.parse_pin_file(GOOD)
    apt["appliance"]["python3-cryptography"] = "43.0.0-1"
    with pytest.raises(verify.PinFileError, match="the wheel 'cryptography'"):
        verify.no_apt_package_shadows_a_wheel(apt, verify.parse_pin_file(WHEEL_TEXT))


def test_a_debian_python_package_fails_even_when_no_wheel_has_that_name_yet() -> None:
    """The rule is not "does it collide today". `build/apt-versions.txt` says so in prose —
    adding a `python3-*` line is a mistake even when Debian's version looks fine — because the
    collision arrives later, when the wheel is added, and nothing re-reads the apt list then."""
    apt = verify.parse_pin_file(GOOD)
    apt["harness"]["python3-yaml"] = "6.0.2-1"
    with pytest.raises(verify.PinFileError, match="python3-yaml"):
        verify.no_apt_package_shadows_a_wheel(apt, verify.parse_pin_file(WHEEL_TEXT))


def test_the_normalised_name_is_what_is_compared() -> None:
    """PEP 503: `zxing-cpp`, `zxing_cpp` and `Zxing.CPP` are one distribution, and a checker that
    compared raw strings would pass the one spelling Debian actually uses."""
    apt = verify.parse_pin_file(GOOD)
    apt["appliance"]["python3-zxing-cpp"] = "3.1.1-1"
    with pytest.raises(verify.PinFileError, match="the wheel 'zxing-cpp'"):
        verify.no_apt_package_shadows_a_wheel(apt, verify.parse_pin_file(WHEEL_TEXT))


def test_the_interpreter_and_the_transient_pip_are_the_two_allowed_exceptions() -> None:
    """`python3` is the interpreter the appliance runs; `python3-pip` installs the wheel layer and
    is removed before the initramfs is packed (M2). Neither is a second resolver over one import
    graph, and both are named in `APT_PYTHON_ALLOWED` rather than special-cased in a branch."""
    assert verify.APT_PYTHON_ALLOWED == {"python3", "python3-pip"}
    verify.no_apt_package_shadows_a_wheel(
        verify.parse_pin_file(GOOD + "python3-pip=25.1.1+dfsg-1\n"),
        verify.parse_pin_file(WHEEL_TEXT),
    )


# --- The closure assertions ----------------------------------------------------------------------
#
# These read the RESOLVED POOL rather than a pin file, and that difference is the whole point: not
# one of the names they catch is pinned anywhere. `systemd` arrives through
# `linux-image-amd64` -> `initramfs-tools` -> `udev`, and a Debian Python library would arrive as a
# dependency of something that has nothing to do with Python. The pin-file checks read the eight
# names a human typed and cannot see either.


def test_a_deb_filename_yields_its_package_name() -> None:
    """Debian's `name_version_arch.deb`, and the name never contains an underscore."""
    assert verify.closure_from_pool(
        ["libc6_2.41-12_amd64.deb", "tzdata_2026b-0+deb13u1_all.deb", "Packages.gz"]
    ) == {"libc6", "tzdata"}


def test_something_that_is_not_a_debian_filename_is_an_error_not_a_skip() -> None:
    """A pool member this cannot parse is a pool this has not checked. Silently dropping it would
    make every assertion below vacuous for exactly the file nobody expected to be there."""
    with pytest.raises(verify.PinFileError, match="not a Debian package filename"):
        verify.closure_from_pool(["libc6.deb"])


def test_an_init_system_in_the_closure_fails_the_build() -> None:
    """The appliance's first published claim is that it has no init system. Measured 2026-09-07:
    the closure is 78 packages with the kernel resolved and 57 without, and `systemd`, `udev`,
    `initramfs-tools`, `libsystemd-shared` and `dracut-install` are all in the difference."""
    for offender in ("systemd", "udev", "initramfs-tools", "libsystemd-shared", "dracut-install"):
        with pytest.raises(verify.PinFileError, match=offender):
            verify.closure_is_free_of_init_system({"dash", "python3", offender})


def test_libsystemd0_and_libudev1_are_deliberately_allowed() -> None:
    """They are shared libraries pulled by `util-linux`, not daemons. "No systemd" and "no
    libsystemd0" are different statements; `docs/boot-pipeline.md` claims only the first, so
    failing on the second would be the build asserting something the project does not say."""
    verify.closure_is_free_of_init_system({"util-linux", "libsystemd0", "libudev1"})


def test_a_debian_python_library_reaching_the_closure_fails_the_build() -> None:
    """`no_apt_package_shadows_a_wheel` reads `build/apt-versions.txt`, where a transitive
    dependency never appears. This is the same `docs/adr/0002` collision arriving by the route
    nobody is watching."""
    wheels = verify.parse_pin_file(WHEEL_TEXT)
    with pytest.raises(verify.PinFileError, match="python3-zxing-cpp"):
        verify.no_python_package_in_closure({"python3", "python3-zxing-cpp"}, wheels)


def test_the_closure_check_names_the_wheel_it_collides_with() -> None:
    """Which of the two lists is wrong is the thing the reader needs, and normalisation is what
    makes `python3-zxing-cpp` and the wheel `zxing-cpp` one name."""
    wheels = verify.parse_pin_file(WHEEL_TEXT)
    with pytest.raises(verify.PinFileError, match="the wheel 'zxing-cpp'"):
        verify.no_python_package_in_closure({"python3-zxing-cpp"}, wheels)


def test_debians_decomposition_of_cpython_is_not_a_shadowed_wheel() -> None:
    """`python3-minimal`, `python3.13`, `python3.13-minimal` and the `libpython3*` pair are how
    Debian ships the interpreter `build/apt-versions.txt` pins as `python3`. They are not a second
    resolution of anything in `uv.lock` and there is no wheel they could shadow.

    The pin-file check never had to draw this line, because a human writes `python3` and the
    decomposition never appears there. Getting it wrong in either direction matters: too broad and
    `python3-cryptography` walks through as interpreter packaging, too narrow and the build fails
    on its own interpreter."""
    wheels = verify.parse_pin_file(WHEEL_TEXT)
    verify.no_python_package_in_closure(
        {
            "python3",
            "python3-minimal",
            "python3.13",
            "python3.13-minimal",
            "libpython3-stdlib",
            "libpython3.13-stdlib",
            "libpython3.13-minimal",
        },
        wheels,
    )
    # ...and the line is drawn at the right place: a library is still caught.
    with pytest.raises(verify.PinFileError, match="python3-cryptography"):
        verify.no_python_package_in_closure({"python3-minimal", "python3-cryptography"}, wheels)


# =================================================================================================
# The rootfs assertions. `docs/roadmap.md` M2: each one fed an image broken in the exact way it
# exists to catch. A listing rather than a directory, because building a broken Debian rootfs on
# disk is not something a unit test should be doing — and because a function that takes a listing
# is a function the build can call before the image is packed.
# =================================================================================================

_prune_spec = importlib.util.spec_from_file_location(
    "aobs_build_prune", ROOT / "build" / "prune_modules.py"
)
assert _prune_spec is not None and _prune_spec.loader is not None
prune = importlib.util.module_from_spec(_prune_spec)
_prune_spec.loader.exec_module(prune)

_initramfs_spec = importlib.util.spec_from_file_location(
    "aobs_build_mkinitramfs", ROOT / "build" / "mkinitramfs.py"
)
assert _initramfs_spec is not None and _initramfs_spec.loader is not None
initramfs = importlib.util.module_from_spec(_initramfs_spec)
_initramfs_spec.loader.exec_module(initramfs)


#: A listing shaped like the real one — merged-`/usr`, so `bin` is a symlink and the shell is at
#: `usr/bin/sh`. Getting that wrong is how an assertion fails on a good image and gets relaxed.
GOOD_ROOTFS = {
    "init",
    "bin",
    "usr/bin/sh",
    "usr/bin/python3",
    "etc/aobs-release",
    "etc/aobs-modules",
    "etc/aobs-ec-backend",
    "opt/aobs/aobs/__main__.py",
    "opt/aobs-python/textual/__init__.py",
    "usr/lib/modules/6.12.0/kernel/drivers/hid/usbhid/usbhid.ko.xz",
}


def test_find_output_becomes_paths_without_the_dot_slash() -> None:
    assert verify.rootfs_paths("./usr/bin/sh\n.\n./etc/\n\n") == {"usr/bin/sh", "etc"}


def test_a_clean_rootfs_passes_every_file_level_assertion() -> None:
    verify.no_forbidden_file_in_rootfs(GOOD_ROOTFS)
    verify.no_packaging_tool_in_the_python_layer(GOOD_ROOTFS)
    verify.required_files_present(GOOD_ROOTFS)
    verify.no_network_module_in_tree(GOOD_ROOTFS)


@pytest.mark.parametrize(
    ("path", "claim"),
    [
        ("usr/bin/dpkg", "package manager"),
        ("var/lib/dpkg", "package manager"),
        ("usr/bin/apt-get", "package manager"),
        ("usr/sbin/agetty", "getty"),
        ("usr/bin/login", "login"),
        ("usr/lib/systemd/systemd", "init system"),
        ("etc/inittab", "init system"),
    ],
)
def test_each_thing_the_purge_removes_fails_the_build_if_it_survives(path: str, claim: str) -> None:
    with pytest.raises(verify.PinFileError) as raised:
        verify.no_forbidden_file_in_rootfs(GOOD_ROOTFS | {path})
    assert path in str(raised.value)
    assert claim in str(raised.value)


def test_removing_pip_alone_is_not_enough() -> None:
    """`python3-packaging` in the image is a harness package in the rootfs.

    The wheel layer is unpacked from outside so none of these ever arrives, which is a stronger
    position than the purge M2 originally specified — and exactly the reason to keep checking.
    """
    for name in ("pip", "wheel", "packaging", "setuptools"):
        with pytest.raises(verify.PinFileError):
            verify.no_packaging_tool_in_the_python_layer(
                GOOD_ROOTFS | {f"opt/aobs-python/{name}/__init__.py"}
            )


def test_a_wheel_whose_name_merely_starts_with_a_forbidden_one_is_not_a_false_positive() -> None:
    verify.no_packaging_tool_in_the_python_layer(
        GOOD_ROOTFS | {"opt/aobs-python/packaging_of_nothing/__init__.py"}
    )


@pytest.mark.parametrize(
    "missing",
    ["init", "usr/bin/sh", "usr/bin/python3", "etc/aobs-release", "etc/aobs-ec-backend"],
)
def test_an_image_that_could_not_start_fails_the_build(missing: str) -> None:
    with pytest.raises(verify.PinFileError) as raised:
        verify.required_files_present(GOOD_ROOTFS - {missing})
    assert missing in str(raised.value)


# --- The commands PID 1 invokes ---------------------------------------------------------------------
#
# The first hardware boot stopped at `/init: 55: mount: not found`. `/usr/bin/mount` is in a package
# named `mount`, not in `util-linux`, and nothing pinned it or looked for it; `modprobe` and `sysctl`
# were missing behind it. Every assertion above passed on that image, which is what these are for.

#: PID 1 as committed, read rather than imitated: a fixture would let the parser and the script
#: drift apart, which is the whole failure this check exists to prevent.
INIT_TEXT = (ROOT / "build" / "init").read_text(encoding="utf-8")


def _rootfs_carrying(commands: tuple[str, ...], *, at: str = "usr/bin") -> set[str]:
    return GOOD_ROOTFS | {f"{at}/{command}" for command in commands}


def test_the_commands_are_read_out_of_the_committed_pid_1() -> None:
    """Every `step` in the real script, not a list someone remembered to update."""
    commands = verify.commands_pid1_invokes(INIT_TEXT)
    assert "mount" in commands
    assert "kbd_mode" in commands
    assert "loadkeys" in commands
    # The non-`step` invocations, which the explicit tuple contributes.
    assert "modprobe" in commands
    assert "awk" in commands
    # Builtins are not commands: an image needs nothing on disk for them.
    assert "echo" not in commands
    assert "printf" not in commands


def test_pid_1s_own_path_is_what_the_check_searches() -> None:
    assert verify.init_search_path(INIT_TEXT) == ("/usr/sbin", "/usr/bin", "/sbin", "/bin")


def test_an_init_that_sets_no_path_is_refused() -> None:
    with pytest.raises(verify.PinFileError):
        verify.init_search_path('step "could not mount /proc" mount -t proc proc /proc\n')


def test_an_image_carrying_every_command_passes() -> None:
    commands = (*verify.commands_pid1_invokes(INIT_TEXT), *verify.REAL_ADAPTER_COMMANDS)
    verify.required_commands_present(
        _rootfs_carrying(commands), commands, verify.init_search_path(INIT_TEXT)
    )


def test_the_missing_mount_that_stopped_the_first_hardware_boot_fails_the_build() -> None:
    """The regression, stated as the boot stated it."""
    commands = (*verify.commands_pid1_invokes(INIT_TEXT), *verify.REAL_ADAPTER_COMMANDS)
    with pytest.raises(verify.PinFileError) as raised:
        verify.required_commands_present(
            _rootfs_carrying(commands) - {"usr/bin/mount"},
            commands,
            verify.init_search_path(INIT_TEXT),
        )
    assert "mount" in str(raised.value)


@pytest.mark.parametrize("missing", ["mount", "modprobe", "kbd_mode", "cat", "awk", "loadkeys"])
def test_any_command_absent_from_the_image_fails_the_build(missing: str) -> None:
    commands = (*verify.commands_pid1_invokes(INIT_TEXT), *verify.REAL_ADAPTER_COMMANDS)
    with pytest.raises(verify.PinFileError) as raised:
        verify.required_commands_present(
            _rootfs_carrying(commands) - {f"usr/bin/{missing}"},
            commands,
            verify.init_search_path(INIT_TEXT),
        )
    assert missing in str(raised.value)


def test_a_command_in_any_directory_on_the_path_counts() -> None:
    """`sbin` and `bin` are symlinks under merged-`/usr`, so the search is any-of and not `usr/bin`."""
    verify.required_commands_present(
        GOOD_ROOTFS | {"usr/sbin/mount"}, ("mount",), ("/usr/sbin", "/usr/bin")
    )


def test_an_empty_path_resolves_nothing_and_is_refused() -> None:
    with pytest.raises(verify.PinFileError):
        verify.required_commands_present(GOOD_ROOTFS, ("mount",), ())


def test_a_step_with_no_command_in_it_is_an_error_not_a_skip() -> None:
    with pytest.raises(verify.PinFileError):
        verify.commands_pid1_invokes('PATH=/usr/bin\nstep "could not do the thing"\n')


def test_a_step_that_runs_a_variable_cannot_be_checked_and_is_refused() -> None:
    """A command this build cannot name is a command it cannot look for, and passing would be a
    check that reports success for having understood nothing."""
    with pytest.raises(verify.PinFileError):
        verify.commands_pid1_invokes('PATH=/usr/bin\nstep "could not run it" "$TOOL" -x\n')


def test_an_init_that_stopped_using_step_is_refused() -> None:
    """Either PID 1 stopped checking its own steps or this parser stopped matching them. Both are
    the same size of problem and neither may pass quietly."""
    with pytest.raises(verify.PinFileError):
        verify.commands_pid1_invokes("PATH=/usr/bin\nmount -t proc proc /proc\n")


def test_the_step_helpers_own_definition_is_not_read_as_a_step() -> None:
    commands = verify.commands_pid1_invokes(INIT_TEXT)
    assert '"$@"' not in commands
    assert "fail" not in commands


# --- The libraries the image links ------------------------------------------------------------------
#
# The second hardware boot got through PID 1 and died at `exec python3 -m aobs`: `import zxingcpp`
# raised `libstdc++.so.6: cannot open shared object file`. The wheels are unpacked from outside the
# chroot, so no installed .deb declares what they link and apt resolved a closure that was correct
# for the packages and blind to the application.

#: A listing with the library directory populated the way the image's is.
LIBRARY_ROOTFS = GOOD_ROOTFS | {
    "usr/lib/x86_64-linux-gnu/libc.so.6",
    "usr/lib/x86_64-linux-gnu/libstdc++.so.6",
    "opt/aobs-python/pillow.libs/libavif-8a7f9d56.so.16.4.2",
}


def test_the_sweep_parses_into_one_record_per_object() -> None:
    records = verify.parse_dynamic_report(
        "OBJECT /opt/aobs-python/zxingcpp/zxingcpp.abi3.so\n"
        "NEEDED libstdc++.so.6\n"
        "NEEDED libc.so.6\n"
        "OBJECT /opt/aobs-python/PIL/_avif.cpython-313-x86_64-linux-gnu.so\n"
        "RUNPATH $ORIGIN/../pillow.libs\n"
        "NEEDED libavif-8a7f9d56.so.16.4.2\n"
    )
    assert records == [
        ("/opt/aobs-python/zxingcpp/zxingcpp.abi3.so", ("libstdc++.so.6", "libc.so.6"), ()),
        (
            "/opt/aobs-python/PIL/_avif.cpython-313-x86_64-linux-gnu.so",
            ("libavif-8a7f9d56.so.16.4.2",),
            ("$ORIGIN/../pillow.libs",),
        ),
    ]


def test_a_needed_before_any_object_is_an_error_not_an_attribution() -> None:
    with pytest.raises(verify.PinFileError):
        verify.parse_dynamic_report("NEEDED libstdc++.so.6\nOBJECT /usr/lib/x.so\n")


def test_a_line_the_parser_does_not_know_is_an_error() -> None:
    with pytest.raises(verify.PinFileError):
        verify.parse_dynamic_report("OBJECT /usr/lib/x.so\nSONAME x.so\n")


def test_an_image_that_carries_every_library_it_links_passes() -> None:
    verify.no_unresolved_shared_library(
        verify.parse_dynamic_report(
            "OBJECT /opt/aobs-python/zxingcpp/zxingcpp.abi3.so\n"
            "NEEDED libstdc++.so.6\n"
            "NEEDED libc.so.6\n"
        ),
        LIBRARY_ROOTFS,
    )


def test_the_missing_c_plus_plus_runtime_that_stopped_the_second_boot_fails_the_build() -> None:
    with pytest.raises(verify.PinFileError) as raised:
        verify.no_unresolved_shared_library(
            verify.parse_dynamic_report(
                "OBJECT /opt/aobs-python/zxingcpp/zxingcpp.abi3.so\nNEEDED libstdc++.so.6\n"
            ),
            LIBRARY_ROOTFS - {"usr/lib/x86_64-linux-gnu/libstdc++.so.6"},
        )
    assert "libstdc++.so.6" in str(raised.value)
    assert "zxingcpp" in str(raised.value)


def test_a_runpath_with_origin_is_resolved_relative_to_the_object() -> None:
    """Pillow's bundled libraries are found this way and nowhere on the default path, so an
    `$ORIGIN` this check could not expand would fail a build that works."""
    verify.no_unresolved_shared_library(
        verify.parse_dynamic_report(
            "OBJECT /opt/aobs-python/PIL/_avif.cpython-313-x86_64-linux-gnu.so\n"
            "RUNPATH $ORIGIN/../pillow.libs\n"
            "NEEDED libavif-8a7f9d56.so.16.4.2\n"
        ),
        LIBRARY_ROOTFS,
    )


def test_a_bundled_library_reachable_only_by_runpath_is_not_found_without_it() -> None:
    """The other half of the test above: it is the RUNPATH doing the work, not a lucky default."""
    with pytest.raises(verify.PinFileError):
        verify.no_unresolved_shared_library(
            verify.parse_dynamic_report(
                "OBJECT /opt/aobs-python/PIL/_avif.cpython-313-x86_64-linux-gnu.so\n"
                "NEEDED libavif-8a7f9d56.so.16.4.2\n"
            ),
            LIBRARY_ROOTFS,
        )


def test_an_empty_sweep_is_a_collector_that_did_not_run_and_not_a_clean_image() -> None:
    with pytest.raises(verify.PinFileError) as raised:
        verify.no_unresolved_shared_library([], LIBRARY_ROOTFS)
    assert "did not run" in str(raised.value)


def test_a_network_module_left_in_the_tree_fails_the_build() -> None:
    with pytest.raises(verify.PinFileError):
        verify.no_network_module_in_tree(
            GOOD_ROOTFS | {"usr/lib/modules/6.12.0/kernel/drivers/net/ethernet/intel/e1000e.ko.xz"}
        )
    with pytest.raises(verify.PinFileError):
        verify.no_network_module_in_tree(
            GOOD_ROOTFS | {"usr/lib/modules/6.12.0/kernel/net/ipv6/ipv6.ko.xz"}
        )


def test_a_harness_package_in_the_rootfs_fails_the_build() -> None:
    apt = verify.parse_pin_file(APT_TEXT)
    verify.no_harness_package_in_rootfs({"dash", "busybox", "python3"}, apt)
    with pytest.raises(verify.PinFileError) as raised:
        verify.no_harness_package_in_rootfs({"dash", "git"}, apt)
    assert "git" in str(raised.value)


def test_a_stray_module_the_allowlist_does_not_reach_fails_the_build() -> None:
    graph = {"usbhid": ["usbcore"], "usbcore": [], "e1000e": []}
    verify.modules_are_reachable_from_the_allowlist(graph, ["usbhid"], {"usbhid", "usbcore"})
    with pytest.raises(verify.PinFileError) as raised:
        verify.modules_are_reachable_from_the_allowlist(
            graph, ["usbhid"], {"usbhid", "usbcore", "e1000e"}
        )
    assert "e1000e" in str(raised.value)


def test_the_symbol_assertion_catches_the_0_8_0_alias_removal() -> None:
    """upstream removed `secp256k1_schnorrsig_sign` in 0.8.0, and embit binds the old name.

    Against such a library embit's `except: pass` binds nothing, the backend still reports as
    native, and BIP86 signing fails when a user tries to sign a taproot input.
    """
    verify.libsecp256k1_exports_what_embit_binds(set(verify.REQUIRED_SECP256K1_SYMBOLS))
    with pytest.raises(verify.PinFileError) as raised:
        verify.libsecp256k1_exports_what_embit_binds(
            set(verify.REQUIRED_SECP256K1_SYMBOLS) - {"secp256k1_schnorrsig_sign32"}
        )
    assert "schnorrsig_sign32" in str(raised.value)


def test_the_floor_is_a_power_of_two_above_the_unrounded_requirement() -> None:
    need, floor = verify.ram_floor(152)
    assert need == 2 * 152 + 64 + 128
    assert floor == 512
    assert need <= floor
    # Two numbers on purpose: `MemTotal` on a 512 MiB machine is under 512, so a check against the
    # rounded figure would refuse to boot on exactly the machine the figure names.
    assert need != floor


def test_a_rootfs_that_measured_as_nothing_is_not_a_rootfs() -> None:
    with pytest.raises(verify.PinFileError):
        verify.ram_floor(0)


def test_an_unsubstituted_placeholder_in_pid_1_fails_the_build() -> None:
    verify.init_is_fully_substituted("RAM_REQUIRED_MIB=496\nloadkeys us\n")
    with pytest.raises(verify.PinFileError) as raised:
        verify.init_is_fully_substituted("RAM_REQUIRED_MIB=@RAM_REQUIRED_MIB@\n")
    assert "@RAM_REQUIRED_MIB@" in str(raised.value)


RELEASE = "release: v0.1.0\nreleased: 2026-09-14\ngit-commit: {commit}\ndirty: no\n"


def test_the_release_file_has_to_agree_with_the_tree_it_was_built_from() -> None:
    commit = "a" * 40
    verify.release_agrees_with_git(
        RELEASE.format(commit=commit), tag="v0.1.0", commit=commit, dirty=False
    )
    with pytest.raises(verify.PinFileError):
        verify.release_agrees_with_git(
            RELEASE.format(commit=commit), tag="v0.2.0", commit=commit, dirty=False
        )
    with pytest.raises(verify.PinFileError):
        verify.release_agrees_with_git(
            RELEASE.format(commit=commit), tag="v0.1.0", commit="b" * 40, dirty=False
        )


def test_a_development_build_may_not_carry_a_version_shaped_string() -> None:
    """The failure this prevents is somebody signing with a snapshot months later.

    A build that is not at a clean tag is skipped, not faked — but "skipped" means there is no tag
    to agree with, never that any string is acceptable.
    """
    commit = "c" * 40
    verify.release_agrees_with_git(
        f"release: development\ngit-commit: {commit}\ndirty: yes\n",
        tag="",
        commit=commit,
        dirty=True,
    )
    with pytest.raises(verify.PinFileError) as raised:
        verify.release_agrees_with_git(
            RELEASE.format(commit=commit), tag="", commit=commit, dirty=False
        )
    assert "version-shaped" in str(raised.value)


# --- The pruner ------------------------------------------------------------------------------------


def test_a_module_filename_becomes_its_module_name() -> None:
    """Hyphens and the compression suffix, and both bite.

    `hid-generic.ko.xz` is the module `hid_generic`. An allowlist written against filenames would
    match nothing for exactly the driver that binds the keyboard.
    """
    assert prune.module_name("kernel/drivers/hid/hid-generic.ko.xz") == "hid_generic"
    assert prune.module_name("kernel/drivers/usb/core/usbcore.ko") == "usbcore"
    assert prune.module_name("kernel/x.ko.zst") == "x"


def test_the_dependency_closure_includes_what_it_was_not_asked_for() -> None:
    graph = prune.parse_modules_dep(
        "kernel/a.ko: kernel/b.ko kernel/c.ko\nkernel/b.ko: kernel/c.ko\nkernel/c.ko:\n"
        "kernel/unrelated.ko:\n"
    )
    assert prune.closure(graph, ["a"]) == {"a", "b", "c"}


def test_a_cycle_in_the_dependency_graph_terminates() -> None:
    graph = {"a": ["b"], "b": ["a"]}
    assert prune.closure(graph, ["a"]) == {"a", "b"}


def test_a_module_the_kernel_builds_in_is_not_an_error_here() -> None:
    """`build/modules.allow` names host controllers a given kernel may have as `=y`.

    A machine whose `xhci_pci` is built in has nothing to load and nothing missing. The error case
    is an allowlist that resolves to NOTHING, and that is checked where the message can say so.
    """
    assert prune.closure({"usbhid": []}, ["usbhid", "xhci_pci"]) == {"usbhid", "xhci_pci"}


def test_an_empty_allowlist_would_delete_every_module_and_is_refused() -> None:
    with pytest.raises(prune.PruneError):
        prune.parse_allowlist("# nothing but comments\n\n")


def test_a_modules_dep_line_with_no_colon_is_an_error_not_a_guess() -> None:
    with pytest.raises(prune.PruneError):
        prune.parse_modules_dep("kernel/a.ko kernel/b.ko\n")


# --- The initramfs writer --------------------------------------------------------------------------


def test_the_device_nodes_are_declared_rather_than_created(tmp_path: Path) -> None:
    """`mknod` is denied in a user namespace, so `/dev/console` cannot exist in the tree on disk.

    An initramfs without it gives PID 1 no stdio, which on this appliance means a failure message
    nobody can read. The header carries the major and minor as fields, so the entry is written
    without the build ever having privilege.
    """
    (tmp_path / "init").write_text("#!/bin/sh\n")
    stream = io.BytesIO()
    initramfs.pack(tmp_path, stream, mtime=0)
    archive = stream.getvalue()
    assert b"dev/console\0" in archive
    # 070701, then 13 hex fields; rdevmajor is the tenth and rdevminor the eleventh.
    header = archive[archive.index(b"dev/console\0") - 110 :][:110]
    assert header[6 + 9 * 8 : 6 + 10 * 8] == b"00000005"
    assert header[6 + 10 * 8 : 6 + 11 * 8] == b"00000001"


def test_every_member_is_written_as_root_whoever_built_it(tmp_path: Path) -> None:
    (tmp_path / "init").write_text("#!/bin/sh\n")
    stream = io.BytesIO()
    initramfs.pack(tmp_path, stream, mtime=0)
    archive = stream.getvalue()
    header = archive[archive.index(b"init\0") - 110 :][:110]
    assert header[6 + 2 * 8 : 6 + 3 * 8] == b"00000000"  # uid
    assert header[6 + 3 * 8 : 6 + 4 * 8] == b"00000000"  # gid


def test_a_fifo_left_in_the_tree_is_refused_rather_than_quietly_dropped(tmp_path: Path) -> None:
    """A fifo or a socket in a tree that starts from nothing every boot is somebody's leftover.

    Packing one silently is the wrong kind of quiet: `newc` has no way to say what it is, so the
    entry would arrive as a zero-length regular file with a plausible name.
    """
    (tmp_path / "init").write_text("#!/bin/sh\n")
    os.mkfifo(tmp_path / "stray.fifo")
    with pytest.raises(initramfs.InitramfsError):
        initramfs.pack(tmp_path, io.BytesIO(), mtime=0)


def test_an_archive_with_no_init_would_panic_the_kernel_and_is_refused(tmp_path: Path) -> None:
    with pytest.raises(initramfs.InitramfsError):
        initramfs.main(["--rootfs", str(tmp_path), "--output", str(tmp_path / "out.cpio")])


# --- The kernel's own config -----------------------------------------------------------------
#
# The console and the keyboard are compiled in, so they never reach the modules tree and no
# assertion against the built image can see them. `docs/boot-pipeline.md` states what each symbol
# carries; these tests are what stop that statement drifting from the pinned kernel.

#: A `/boot/config-*` in miniature: every required symbol built in, plus the two shapes the parser
#: has to tell apart — an explicitly unset symbol and a symbol that is a module.
GOOD_KERNEL_CONFIG = """\
#
# Automatically generated file; DO NOT EDIT.
#
CONFIG_FB_EFI=y
CONFIG_FB_VESA=y
CONFIG_FB_SIMPLE=y
CONFIG_FRAMEBUFFER_CONSOLE=y
CONFIG_SERIO_I8042=y
CONFIG_KEYBOARD_ATKBD=y
CONFIG_VT=y
CONFIG_KEYBOARD_CROS_EC=m
# CONFIG_DRM_SIMPLEDRM is not set
CONFIG_LOCALVERSION=""
"""


#: **The pinned kernel is checked by `build/mkiso.sh`, not here.** It runs
#: `verify.py --kernel-config` against the real `/boot/config-*` from the kernel `.deb`, inside the
#: authoritative tier, where the package is present by construction. A second copy of that check
#: in this file would either skip on a dev host — the loudest possible pass — or duplicate a `.deb`
#: extractor to reach a conclusion the build already reaches. What belongs here is what belongs
#: here for every other assertion: the broken inputs, proving the function still bites.


def test_a_good_config_parses_and_passes() -> None:
    symbols = verify.kernel_config_symbols(GOOD_KERNEL_CONFIG)
    verify.kernel_provides_console_and_input(symbols)
    assert symbols["FB_VESA"] == "y"
    #: `# CONFIG_X is not set` is a statement, not a comment. A parser that dropped it could not
    #: tell "this kernel does not have it" from "this file does not mention it".
    assert symbols["DRM_SIMPLEDRM"] == "n"
    assert symbols["KEYBOARD_CROS_EC"] == "m"


@pytest.mark.parametrize("symbol", sorted(verify.REQUIRED_BUILT_IN))
def test_a_symbol_demoted_to_a_module_fails_the_build(symbol: str) -> None:
    """The real failure: a future Debian shipping one of these as `m`.

    A module the allowlist does not name is deleted by `build/prune_modules.py`, so the image
    would lose its console or its keyboard while every other assertion in the file still passed.
    """
    broken = GOOD_KERNEL_CONFIG.replace(f"CONFIG_{symbol}=y", f"CONFIG_{symbol}=m")
    with pytest.raises(verify.PinFileError) as raised:
        verify.kernel_provides_console_and_input(verify.kernel_config_symbols(broken))
    assert f"CONFIG_{symbol} is m" in str(raised.value)
    assert verify.REQUIRED_BUILT_IN[symbol] in str(raised.value)


@pytest.mark.parametrize("symbol", sorted(verify.REQUIRED_BUILT_IN))
def test_a_symbol_missing_from_the_config_fails_the_build(symbol: str) -> None:
    """Absent is not the same as `m`, and neither one may pass.

    A config that does not mention the symbol at all is the shape a different architecture's or a
    hand-rolled kernel's config has, and it must not read as satisfied.
    """
    broken = GOOD_KERNEL_CONFIG.replace(f"CONFIG_{symbol}=y\n", "")
    with pytest.raises(verify.PinFileError) as raised:
        verify.kernel_provides_console_and_input(verify.kernel_config_symbols(broken))
    assert "absent from the config" in str(raised.value)


def test_an_explicitly_unset_symbol_fails_the_build() -> None:
    broken = GOOD_KERNEL_CONFIG.replace(
        "CONFIG_FB_VESA=y", "# CONFIG_FB_VESA is not set"
    )
    with pytest.raises(verify.PinFileError) as raised:
        verify.kernel_provides_console_and_input(verify.kernel_config_symbols(broken))
    assert "CONFIG_FB_VESA is n" in str(raised.value)


def test_a_file_that_is_not_a_kernel_config_is_refused_rather_than_passed(tmp_path: Path) -> None:
    """Zero symbols must not read as zero problems — the mode is explicit for the same reason."""
    empty = tmp_path / "config-none"
    empty.write_text("# nothing here\n")
    with pytest.raises(verify.PinFileError) as raised:
        verify.main(["--kernel-config", str(empty)])
    assert "not a kernel config" in str(raised.value)
