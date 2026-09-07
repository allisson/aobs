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
