"""Build-time assertions, as pure functions.

Every assertion this build makes lives here, and every one of them is a function of its inputs
with no filesystem and no environment behind it. That is what lets `tests/test_build_verifier.py`
feed each one a deliberately broken input and prove it still bites — an assertion nobody has
watched fail is an assertion nobody has checked.

Three modes, and every one of them is EXPLICIT. A check that runs only when its input happens to
be present passes loudest exactly when it was skipped, so there is no "if the directory exists"
anywhere in this file:

    python3 build/verify.py                      # the two pin files. No inputs, seconds.
    python3 build/verify.py --closure <pool>     # + the resolved appliance pool
    python3 build/verify.py --rootfs <dir> ...   # + the built image, called by build/mkiso.sh
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path, PurePosixPath

sys.path.insert(0, str(Path(__file__).resolve().parent))
import prune_modules  # noqa: E402  the pruner's graph functions, reused rather than restated

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


# =================================================================================================
# The rootfs assertions. Each one is a published claim, checked against a tree that exists.
#
# They take a LISTING and a set of names rather than a directory, for the same reason everything
# above does: `tests/test_build_verifier.py` has to be able to hand each one an image broken in the
# exact way it exists to catch, and constructing a broken rootfs on disk is not something a unit
# test should be doing.
# =================================================================================================

#: Binaries and directories that would each make a published claim false. The value is the claim,
#: and it is in the table so that the failure message says which promise just stopped being true
#: rather than only which file turned up.
FORBIDDEN_IN_ROOTFS = {
    "usr/bin/dpkg": "no package manager is in the image",
    "usr/bin/dpkg-query": "no package manager is in the image",
    "var/lib/dpkg": "no package manager is in the image",
    "usr/bin/apt": "no package manager is in the image",
    "usr/bin/apt-get": "no package manager is in the image",
    "usr/bin/pip": "no package manager is in the image",
    "usr/bin/pip3": "no package manager is in the image",
    "usr/sbin/agetty": "there is no getty",
    "sbin/agetty": "there is no getty",
    "usr/bin/login": "there is no login prompt",
    "bin/login": "there is no login prompt",
    "usr/lib/systemd/systemd": "there is no init system",
    "usr/bin/systemctl": "there is no init system",
    "usr/bin/udevadm": "there is no init system",
    "usr/lib/systemd/systemd-udevd": "there is no init system",
    "etc/inittab": "there is no init system",
}

#: Absent, and the build fails rather than warns. `pip` is never installed into the rootfs at all
#: — `python3-pip` is a harness-group package, so installing it even transiently would put a
#: harness package in the image — but `python3-wheel` and `python3-packaging` are what pip drags in
#: wherever it runs, and this is the check that would notice if that ever changed.
FORBIDDEN_PACKAGE_DIRECTORIES = ("pip", "wheel", "packaging", "setuptools", "pkg_resources")

#: What has to be there. The predecessor's first ISO had neither a shell nor an interpreter, and
#: PID 1 could not have run a single line of itself.
#:
#: **`usr/bin/sh`, not `bin/sh`.** trixie is merged-`/usr`: `/bin` is a symlink to `usr/bin`, so a
#: listing of the tree contains `bin` and `usr/bin/sh` and never the path a person would type. A
#: check written against the typed path fails on a perfectly good image, which is how an assertion
#: gets relaxed instead of fixed.
REQUIRED_IN_ROOTFS = (
    "init",
    "bin",
    "usr/bin/sh",
    "usr/bin/python3",
    "etc/aobs-release",
    "etc/aobs-modules",
    "etc/aobs-ec-backend",
    "opt/aobs/aobs/__main__.py",
)

#: The symbols the vendored embit binds. `secp256k1_ec_privkey_negate` is the deprecated alias
#: embit's loader binds unconditionally, and `secp256k1_schnorrsig_sign32` is the one upstream
#: REMOVED the old name of in 0.8.0 — against such a library embit's `except: pass` binds nothing,
#: the backend still reports as native, and BIP86 signing fails when a user tries to sign a taproot
#: input. This assertion is the only thing between a future Debian and a pure-Python signer.
REQUIRED_SECP256K1_SYMBOLS = frozenset(
    {
        "secp256k1_ec_privkey_negate",
        "secp256k1_ec_pubkey_create",
        "secp256k1_ecdsa_sign",
        "secp256k1_ecdsa_sign_recoverable",
        "secp256k1_ecdh",
        "secp256k1_keypair_create",
        "secp256k1_schnorrsig_sign32",
        "secp256k1_xonly_pubkey_from_pubkey",
    }
)


def rootfs_paths(listing: str) -> set[str]:
    """`find .` output as a set of paths with no `./` prefix and no trailing slash."""
    paths = set()
    for raw in listing.splitlines():
        path = raw.strip()
        if not path or path == ".":
            continue
        if path.startswith("./"):
            path = path[2:]
        paths.add(path.rstrip("/"))
    return paths


def no_forbidden_file_in_rootfs(paths: set[str]) -> None:
    """Nothing in `FORBIDDEN_IN_ROOTFS` survived into the image.

    Every entry here is something Debian installs because it insists, and every one of them is
    removed by the purge stage. The point of checking rather than trusting the `rm` is that a
    package reorganisation moves a binary and the `rm` then silently removes nothing.
    """
    found = sorted(path for path in FORBIDDEN_IN_ROOTFS if path in paths)
    if found:
        claims = sorted({FORBIDDEN_IN_ROOTFS[path] for path in found})
        raise PinFileError(
            f"the rootfs still contains {found}, so these published claims are false: {claims}. "
            "docs/boot-pipeline.md's purge stage is what should have removed them"
        )


def no_packaging_tool_in_the_python_layer(paths: set[str]) -> None:
    """No `pip`, `wheel`, `packaging` or `setuptools` under the wheel layer.

    Removing pip alone would leave `python3-wheel` and `python3-packaging` behind, and a
    `python3-packaging` in the image is a harness package in the rootfs. The wheel layer is
    unpacked from outside the image so none of these should ever arrive; this is what makes that
    a fact rather than an expectation.
    """
    prefix = "opt/aobs-python/"
    found = sorted(
        path
        for path in paths
        if path.startswith(prefix)
        and path[len(prefix) :].split("/", 1)[0].split("-", 1)[0] in FORBIDDEN_PACKAGE_DIRECTORIES
    )
    if found:
        raise PinFileError(
            f"the Python layer contains packaging machinery: {found[:5]}. "
            "The appliance installs nothing and has no resolver in it"
        )


def required_files_present(paths: set[str]) -> None:
    """PID 1, a shell, the interpreter, the identity file and the app.

    The predecessor's first ISO had no `/bin/sh` and no `python3`, so `init` could not have run a
    line of itself. There was no assertion, and nothing said so until the machine hung.
    """
    missing = sorted(path for path in REQUIRED_IN_ROOTFS if path not in paths)
    if missing:
        raise PinFileError(f"the rootfs is missing {missing}; nothing in it could start")


def no_harness_package_in_rootfs(installed: set[str], apt: dict[str, dict[str, str]]) -> None:
    """The group split, checked where it is supposed to bite.

    The split answers one question — "may this survive into the shipped rootfs?" — and an
    unchecked answer is a comment. Read from `var/lib/dpkg/status` BEFORE the purge removes it,
    which is the last moment the image can still say what is in it.
    """
    harness = set(apt.get("harness", {}))
    found = sorted(installed & harness)
    if found:
        raise PinFileError(
            f"the rootfs has harness-group packages installed: {found}. "
            "build/apt-versions.txt puts them in the group that may not reach the image"
        )


def no_network_module_in_tree(paths: set[str]) -> None:
    """No `kernel/net` and no `kernel/drivers/net`, at *absence* strength and stated as such.

    The Alpine predecessor built `CONFIG_NET=n` and the mechanism did not exist. Debian's stock
    kernel has the network stack compiled in and this project does not control that config, so
    what is checkable is that no network DRIVER and no protocol module is in the image. Writing
    this up as structural would be a defect, not a rounding error.
    """
    found = sorted(
        path
        for path in paths
        if ("/kernel/net/" in path or "/kernel/drivers/net/" in path) and ".ko" in path
    )
    if found:
        raise PinFileError(
            f"{len(found)} network modules are still in the image, e.g. {found[:3]}. "
            "The network claim is absence: the module must not be in the image"
        )


def modules_are_reachable_from_the_allowlist(
    dependencies: dict[str, list[str]], allowed: Iterable[str], present: set[str]
) -> None:
    """Every module left in the tree is one the allowlist asked for, or a dependency of one.

    Checked against the REGENERATED `modules.dep`, so it is not the vacuous statement it looks
    like: a module that survived the prune by accident is present in the graph and reachable from
    nothing, and that is exactly what this finds.
    """
    reachable = set()
    pending = list(allowed)
    while pending:
        name = pending.pop()
        if name in reachable:
            continue
        reachable.add(name)
        pending.extend(dependencies.get(name, ()))

    stray = sorted(present - reachable)
    if stray:
        raise PinFileError(
            f"{len(stray)} modules are in the image that the allowlist does not reach, "
            f"e.g. {stray[:5]}. build/modules.allow is the whole list of drivers this appliance "
            "binds, and the prune is what makes that true"
        )


def libsecp256k1_exports_what_embit_binds(symbols: set[str]) -> None:
    """The 0.8.0 alias removal, caught at build time instead of at signing time.

    embit picks its EC implementation inside a bare `except:` and says nothing either way, so a
    library missing one of these produces a pure-Python signer or a taproot failure mid-session,
    with a wallet loaded. Homebrew's 0.7 on a dev host reproduces it; this is what stops a future
    Debian doing the same to a shipped image.
    """
    missing = sorted(REQUIRED_SECP256K1_SYMBOLS - symbols)
    if missing:
        raise PinFileError(
            f"the image's libsecp256k1 does not export {missing}. embit binds these inside a bare "
            "`except:`, so the image would ship a signer that reports as native and is not"
        )


def ram_floor(measured_mib: int, *, argon2_mib: int = 64, headroom_mib: int = 128) -> tuple[int, int]:
    """`(required, published floor)` from the measured tree, by the formula in the document.

    The requirement is `2 x unpacked + 64 + 128` and the published floor is that rounded up to a
    power of two. **They are two numbers on purpose**: `MemTotal` on a machine with 512 MiB
    installed is always somewhat less than 512, so a check against the rounded figure would refuse
    to boot on exactly the machine the figure describes. The rounding is for the user — a floor of
    634 MiB would look measured to a precision nobody has.
    """
    if measured_mib <= 0:
        raise PinFileError(f"a rootfs measured at {measured_mib} MiB is not a rootfs")
    required = 2 * measured_mib + argon2_mib + headroom_mib
    floor = 1
    while floor < required:
        floor *= 2
    return required, floor


def init_is_fully_substituted(text: str) -> None:
    """No `@PLACEHOLDER@` reached the image.

    `build/init` ships with the RAM floor and the default keymap as placeholders because both are
    derived by the build. An unsubstituted one is not a cosmetic defect: `[ "$_total_mib" -lt
    "@RAM_REQUIRED_MIB@" ]` is a shell error at boot, inside PID 1, on a machine with no console
    scrollback.
    """
    left = sorted(set(re.findall(r"@[A-Z0-9_]+@", text)))
    if left:
        raise PinFileError(f"build/init reached the image with {left} unsubstituted")


def release_agrees_with_git(text: str, *, tag: str, commit: str, dirty: bool) -> None:
    """`/etc/aobs-release` says what the tree it was built from says.

    Checked in stage 3d, before `cpio`, while it is still a file a human can open rather than a
    member of an archive. A build that is not at a clean tag must say `development` and never a
    version-shaped string — and that case is **skipped, not faked**: there is no tag to agree
    with, so the only thing to check is that no version was invented.
    """
    fields = {}
    for raw in text.splitlines():
        key, separator, value = raw.partition(":")
        if separator:
            fields[key.strip()] = value.strip()

    if fields.get("git-commit") != commit:
        raise PinFileError(
            f"/etc/aobs-release says git-commit {fields.get('git-commit')!r} and HEAD is {commit!r}"
        )
    if fields.get("dirty") != ("yes" if dirty else "no"):
        raise PinFileError(
            f"/etc/aobs-release says dirty {fields.get('dirty')!r} and the tree says {dirty}"
        )

    release = fields.get("release", "")
    if not tag or dirty:
        if release != "development":
            raise PinFileError(
                f"/etc/aobs-release says release {release!r}, but this build is not at a clean "
                "tag. A development build must never carry a version-shaped string"
            )
        return
    if release != tag:
        raise PinFileError(f"/etc/aobs-release says release {release!r} and the tag is {tag!r}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="build-time assertions")
    parser.add_argument("--closure", type=Path, help="the fetched appliance pool")
    parser.add_argument("--rootfs", type=Path, help="the built rootfs, from build/mkiso.sh")
    parser.add_argument("--files", type=Path, help="a `find .` listing of --rootfs")
    parser.add_argument("--installed", type=Path, help="package names, read before the purge")
    parser.add_argument("--symbols", type=Path, help="the image's libsecp256k1 dynamic symbols")
    parser.add_argument("--allow", type=Path, help="build/modules.allow")
    parser.add_argument("--kver", help="the kernel version directory under usr/lib/modules")
    parser.add_argument("--measured-mib", type=int, help="the measured unpacked rootfs, in MiB")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)

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
    if args.closure is not None:
        pool = args.closure
        if not pool.is_dir():
            raise PinFileError(f"{pool} is not a directory; --closure needs the fetched pool")
        names = closure_from_pool(p.name for p in pool.glob("*.deb"))
        if not names:
            raise PinFileError(f"{pool} holds no .deb; the pool is empty, not clean")
        closure_is_free_of_init_system(names)
        no_python_package_in_closure(names, wheels)
        print(f"appliance closure: {len(names)} packages, no init system, no Debian Python library")

    if args.rootfs is not None:
        _check_rootfs(args, apt)
    return 0


def _check_rootfs(args: argparse.Namespace, apt: dict[str, dict[str, str]]) -> None:
    """The image half. Every input is named on the command line and none of them is optional.

    This function is the only impure thing in the file and it is deliberately thin: it reads, and
    every judgement it makes is made by one of the pure functions above, which is what lets
    `tests/test_build_verifier.py` prove each of those still bites.
    """
    required = {
        "--files": args.files,
        "--installed": args.installed,
        "--symbols": args.symbols,
        "--allow": args.allow,
        "--kver": args.kver,
        "--measured-mib": args.measured_mib,
    }
    absent = sorted(flag for flag, value in required.items() if value in (None, ""))
    if absent:
        raise PinFileError(f"--rootfs needs {absent}; a partial run is not a check")

    paths = rootfs_paths(args.files.read_text(encoding="utf-8"))
    if len(paths) < 1000:
        raise PinFileError(f"{args.files} lists {len(paths)} paths; that is not a Debian rootfs")

    no_forbidden_file_in_rootfs(paths)
    no_packaging_tool_in_the_python_layer(paths)
    required_files_present(paths)
    no_network_module_in_tree(paths)

    # Read from `var/lib/dpkg/status` before the purge removed it, which is the last moment the
    # image can still say what is in it.
    installed = {
        line.split(":", 1)[1].strip()
        for line in args.installed.read_text(encoding="utf-8").splitlines()
        if line.startswith("Package:")
    }
    if not installed:
        raise PinFileError(f"{args.installed} names no packages; it was captured too late")
    no_harness_package_in_rootfs(installed, apt)

    allowed = prune_modules.parse_allowlist(args.allow.read_text(encoding="utf-8"))
    dep_file = args.rootfs / "usr" / "lib" / "modules" / args.kver / "modules.dep"
    dependencies = prune_modules.parse_modules_dep(dep_file.read_text(encoding="utf-8"))
    present = {
        prune_modules.module_name(path) for path in paths if ".ko" in path and "/kernel/" in path
    }
    modules_are_reachable_from_the_allowlist(dependencies, allowed, present)

    libsecp256k1_exports_what_embit_binds(
        set(args.symbols.read_text(encoding="utf-8").split())
    )

    # The receipt `build/signcheck.py` left inside mmdebstrap's chroot. Its absence means the hook
    # did not run, which would leave every other assertion here passing and the only one that can
    # catch a pure-Python signer unchecked.
    backend = (args.rootfs / "etc" / "aobs-ec-backend").read_text(encoding="utf-8").strip()
    if "ctypes" not in backend:
        raise PinFileError(
            f"the image signed with {backend!r}, not the ctypes binding. embit picks its EC "
            "implementation inside a bare `except:` and says nothing either way"
        )

    init_text = (args.rootfs / "init").read_text(encoding="utf-8")
    init_is_fully_substituted(init_text)
    need, floor = ram_floor(args.measured_mib)
    if f"RAM_REQUIRED_MIB={need}" not in init_text or f"RAM_FLOOR_MIB={floor}" not in init_text:
        raise PinFileError(
            f"the measured rootfs is {args.measured_mib} MiB, so PID 1 must carry "
            f"RAM_REQUIRED_MIB={need} and RAM_FLOOR_MIB={floor}. The formula is re-derived here "
            "precisely so the floor and the image cannot drift apart"
        )

    release_agrees_with_git(
        (args.rootfs / "etc" / "aobs-release").read_text(encoding="utf-8"),
        tag=_git("describe", "--exact-match", "--tags"),
        commit=_git("rev-parse", "HEAD"),
        dirty=subprocess.run(
            ["git", "-C", str(ROOT), "diff", "--quiet", "HEAD"], check=False
        ).returncode
        != 0,
    )

    print(
        f"rootfs: {len(paths)} paths, {len(present)} modules, no package manager, no getty, "
        f"no init system, EC backend {backend.rsplit('.', 1)[-1]}, "
        f"floor {floor} MiB from {args.measured_mib} MiB measured"
    )


def _git(*arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(ROOT), *arguments], capture_output=True, text=True, check=False
    )
    return result.stdout.strip() if result.returncode == 0 else ""


if __name__ == "__main__":
    try:
        sys.exit(main())
    except PinFileError as error:
        print(f"verify: {error}", file=sys.stderr)
        sys.exit(1)
