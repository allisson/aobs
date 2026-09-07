"""Build-time assertions, as pure functions.

Every assertion this build makes lives here, and every one of them is a function of its inputs
with no filesystem and no environment behind it. That is what lets `tests/test_build_verifier.py`
feed each one a deliberately broken input and prove it still bites — an assertion nobody has
watched fail is an assertion nobody has checked.

**This file is the M1 slice**: the two pin files, and nothing else. `docs/roadmap.md` M2 adds the
assertions about the *image* — no harness package in the rootfs, no package manager, `/bin/sh` and
`python3` present, no `kernel/net`, no module outside the allowlist, no getty, the `libsecp256k1`
symbols, the RAM floor. Those need a rootfs to look at; these need two text files, so they come
first and they guard the lists the rest of the build reads.

    python3 build/verify.py            # check the committed pin files, print what passed
"""

from __future__ import annotations

import re
import sys
from collections.abc import Iterable
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent.parent

APT_VERSIONS = ROOT / "build" / "apt-versions.txt"
WHEEL_VERSIONS = ROOT / "build" / "wheel-versions.txt"

#: The only two group names either pin file may declare. A third would be a new answer to the
#: question the groups exist to answer — "may this survive into the shipped rootfs?" — and
#: `build/apt-versions.txt` records why a `buildtime` group was rejected rather than added.
GROUPS = ("appliance", "harness")

#: The two Debian packages whose names begin `python3` and which are nonetheless correct here.
#: `python3` is the interpreter itself; `python3-pip` is the transient installer that
#: `build/mkiso.sh` removes before the initramfs is packed. Everything else matching `python3-*`
#: is the failure `no_apt_package_shadows_a_wheel` exists to catch.
APT_PYTHON_ALLOWED = frozenset({"python3", "python3-pip"})

_GROUP_MARKER = re.compile(r"^#\s*@group\s+(\S+)\s*$")
#: `name=version` in the apt list, `name==version` in the wheel list, either optionally followed
#: by a trailing `#` comment — `colorama==0.4.6  # marker: sys_platform == 'win32'` is one.
_PIN = re.compile(r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._+-]*)={1,2}(?P<version>[^\s#]+)\s*(?:#.*)?$")


class PinFileError(Exception):
    """A pin file says something the build refuses to interpret.

    Never a warning and never a default. In the Alpine predecessor the appliance/harness split was
    a prose comment, `py3-pip` sat on the wrong side of it, and a parser that guessed put a package
    manager in the rootfs with nothing noticing.
    """


def parse_pin_file(text: str, *, source: str = "<pins>") -> dict[str, dict[str, str]]:
    """`{group: {name: version}}` from a pin file, or `PinFileError`.

    Three things are errors rather than guesses: a pin before any `# @group` marker, a group name
    that is not one of `GROUPS`, and a name pinned twice *within one group*. The first is the
    predecessor's exact failure; the third is how two versions of one fact enter a list a human
    reads top to bottom.

    A name in *both* groups is deliberately not this function's error. It is a different defect
    with a different consequence — it makes "installed into the rootfs" and "must never reach the
    rootfs" both true of one package — and `groups_are_disjoint` is where it is named, so the
    message a reader gets is about the rootfs rather than about a duplicate line.
    """
    groups: dict[str, dict[str, str]] = {}
    current: str | None = None
    seen: dict[str, dict[str, int]] = {}

    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        marker = _GROUP_MARKER.match(stripped)
        if marker:
            name = marker.group(1)
            if name not in GROUPS:
                raise PinFileError(
                    f"{source}:{number}: unknown group {name!r}; the groups are {GROUPS}"
                )
            current = name
            groups.setdefault(name, {})
            seen.setdefault(name, {})
            continue
        if not stripped or stripped.startswith("#"):
            continue

        pin = _PIN.match(stripped)
        if pin is None:
            raise PinFileError(f"{source}:{number}: not a pin and not a comment: {stripped!r}")
        if current is None:
            raise PinFileError(
                f"{source}:{number}: {pin.group('name')!r} is pinned before any "
                f"`# @group` marker, so nothing says whether it may reach the rootfs"
            )
        name = pin.group("name")
        if name in seen[current]:
            raise PinFileError(
                f"{source}:{number}: {name!r} is pinned twice in the {current} group, "
                f"first at line {seen[current][name]}"
            )
        seen[current][name] = number
        groups[current][name] = pin.group("version")

    missing = [group for group in GROUPS if group not in groups]
    if missing:
        raise PinFileError(f"{source}: no `# @group` marker for {missing}")
    return groups


def groups_are_disjoint(groups: dict[str, dict[str, str]], *, source: str = "<pins>") -> None:
    """No package may be in both groups.

    The appliance group is what `build/mkiso.sh` installs into the rootfs and the harness group is
    what `build/verify.py` will refuse to find there at M2. A name in both makes those two
    statements contradict each other, and the contradiction would be resolved by whichever check
    ran last rather than by a decision.
    """
    both = sorted(set(groups.get("appliance", {})) & set(groups.get("harness", {})))
    if both:
        raise PinFileError(
            f"{source}: {both} are in BOTH the appliance and the harness group; "
            "a package may only be in the group that decides whether it reaches the rootfs"
        )


def no_apt_package_shadows_a_wheel(
    apt: dict[str, dict[str, str]], wheels: dict[str, dict[str, str]]
) -> None:
    """The seam `docs/adr/0002` draws: if Python imports it, it comes from a wheel.

    Debian's `python3-cryptography` and the lock's `cryptography` are two unrelated resolutions of
    one import, and they disagree the first time either moves. So no `python3-*` package may be
    pinned in the apt list at all — not even one whose Debian version looks fine, and not only the
    ones that collide with a name in the wheel list today, because the collision arrives later
    when a wheel is added. `APT_PYTHON_ALLOWED` names the two exceptions and why.

    When the offender *is* already in the wheel list, the error says so: that is the same defect
    caught one step further along, and naming the wheel is what tells the reader which of the two
    lists is wrong.
    """
    pinned = {name for names in wheels.values() for name in names}
    normalised = {_normalise(name): name for name in pinned}

    for group, names in apt.items():
        for name in sorted(names):
            if not (name == "python3" or name.startswith("python3-")):
                continue
            if name in APT_PYTHON_ALLOWED:
                continue
            wheel = normalised.get(_normalise(name[len("python3-") :]))
            shadowed = f", which is the wheel {wheel!r}" if wheel else ""
            raise PinFileError(
                f"build/apt-versions.txt: {name!r} is pinned in the {group} group{shadowed}. "
                "Every Python package comes from a wheel (docs/adr/0002); the only apt "
                f"exceptions are {sorted(APT_PYTHON_ALLOWED)}"
            )


#: Names that must never appear in the appliance closure. `linux-image-amd64` resolves to
#: `initramfs-tools` -> `udev` -> `systemd`, which would put an init system in the pool of an
#: appliance whose first published claim is that it has none. `docs/boot-pipeline.md` says why the
#: kernel is extracted rather than installed; this is what fails the build if that ever changes.
#:
#: `libsystemd0` and `libudev1` are deliberately NOT here. They are shared libraries pulled by
#: `util-linux`, not daemons, and "no systemd" and "no libsystemd0" are different statements. Only
#: the first is claimed, so only the first is checked.
FORBIDDEN_IN_APPLIANCE_CLOSURE = frozenset(
    {"systemd", "systemd-sysv", "udev", "initramfs-tools", "libsystemd-shared", "dracut-install"}
)


def closure_is_free_of_init_system(names: set[str]) -> None:
    """No init system reached the appliance pool.

    Checked over the RESOLVED CLOSURE rather than the pin list, because none of these is pinned:
    every one arrives as a transitive dependency of the kernel metapackage. Measured 2026-09-07,
    the closure is 78 packages with the kernel resolved and 57 without, and all six names below are
    in the difference.
    """
    found = sorted(names & FORBIDDEN_IN_APPLIANCE_CLOSURE)
    if found:
        raise PinFileError(
            f"the appliance closure contains {found}. The kernel is fetched unresolved and "
            "unpacked with dpkg-deb -x precisely so that it does not drag an init system in "
            "(docs/boot-pipeline.md); something is resolving it instead"
        )


def no_python_package_in_closure(names: set[str], wheels: dict[str, dict[str, str]]) -> None:
    """`docs/adr/0002`'s seam, applied where it actually bites.

    `no_apt_package_shadows_a_wheel` reads the eight names a human typed into
    `build/apt-versions.txt`. A `python3-*` package arriving as a TRANSITIVE dependency never
    appears there and would pass it silently, which is the same two-resolvers-over-one-import-graph
    collision arriving by a route nobody is watching.
    """
    pinned = {name for names_ in wheels.values() for name in names_}
    normalised = {_normalise(name): name for name in pinned}

    for name in sorted(names):
        if not name.startswith("python3-"):
            continue
        if name in APT_PYTHON_ALLOWED or _is_interpreter_packaging(name):
            continue
        wheel = normalised.get(_normalise(name[len("python3-") :]))
        shadowed = f", which is the wheel {wheel!r}" if wheel else ""
        raise PinFileError(
            f"the appliance closure contains the Debian Python package {name!r}{shadowed}. "
            "Every Python package comes from a wheel (docs/adr/0002). It is not in "
            "build/apt-versions.txt, so it arrived as a transitive dependency — the pin that "
            "pulled it in is what has to change"
        )


#: How Debian decomposes CPython itself, as opposed to how it packages a library written in Python.
#: `python3-minimal`, `python3.13`, `python3.13-minimal`, `libpython3-stdlib` and
#: `libpython3.13-*` are the interpreter `build/apt-versions.txt` pins as `python3`; they are not a
#: second resolution of anything in `uv.lock`, and there is no wheel they could shadow.
#:
#: The pin-list check never had to draw this line, because a human writes `python3` there and the
#: decomposition never appears. The closure check does, and getting it wrong in either direction
#: matters: too broad and `python3-cryptography` walks through as "interpreter packaging"; too
#: narrow and the build fails on its own interpreter.
_INTERPRETER_PACKAGING = re.compile(r"^(python3-minimal|python3\.\d+(-minimal)?|libpython3(\.\d+)?-\w+)$")


def _is_interpreter_packaging(name: str) -> bool:
    """Is this Debian shipping CPython, rather than Debian shipping a Python library?"""
    return bool(_INTERPRETER_PACKAGING.match(name))


def closure_from_pool(paths: Iterable[str]) -> set[str]:
    """Package names from a pool of `.deb` filenames.

    Debian's filename is `name_version_arch.deb`, and the name never contains an underscore, so
    the first field is the package. Reading the pool rather than asking apt keeps this a pure
    function the suite can feed a broken input.
    """
    names = set()
    for path in paths:
        stem = PurePosixPath(path).name
        if not stem.endswith(".deb"):
            continue
        name, _, rest = stem.partition("_")
        if not name or not rest:
            raise PinFileError(f"{stem!r} is not a Debian package filename")
        names.add(name)
    return names


def _normalise(distribution: str) -> str:
    """PEP 503 normalisation, so `zxing-cpp`, `zxing_cpp` and `Zxing.CPP` are one name."""
    return re.sub(r"[-_.]+", "-", distribution).lower()


def main() -> int:
    apt = parse_pin_file(APT_VERSIONS.read_text(encoding="utf-8"), source=str(APT_VERSIONS))
    wheels = parse_pin_file(WHEEL_VERSIONS.read_text(encoding="utf-8"), source=str(WHEEL_VERSIONS))

    groups_are_disjoint(apt, source=str(APT_VERSIONS))
    groups_are_disjoint(wheels, source=str(WHEEL_VERSIONS))
    no_apt_package_shadows_a_wheel(apt, wheels)

    for label, parsed in (("apt", apt), ("wheels", wheels)):
        counts = ", ".join(f"{group} {len(parsed[group])}" for group in GROUPS)
        print(f"{label}: {counts}")
    print("pin files: groups disjoint, no Debian Python package")

    # The closure checks need a pool to read, and the CI job that checks the pin files does not
    # fetch one. They are therefore an EXPLICIT MODE rather than something that runs when a
    # directory happens to exist: "assert only if the input is present" is a check that passes
    # loudest exactly when it has been skipped.
    if "--closure" in sys.argv:
        pool = Path(sys.argv[sys.argv.index("--closure") + 1])
        if not pool.is_dir():
            raise PinFileError(f"{pool} is not a directory; --closure needs the fetched pool")
        names = closure_from_pool(p.name for p in pool.glob("*.deb"))
        if not names:
            raise PinFileError(f"{pool} holds no .deb; the pool is empty, not clean")
        closure_is_free_of_init_system(names)
        no_python_package_in_closure(names, wheels)
        print(f"appliance closure: {len(names)} packages, no init system, no Debian Python library")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except PinFileError as error:
        print(f"verify: {error}", file=sys.stderr)
        sys.exit(1)
