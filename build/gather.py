"""The reading half. Gathers an input, hands it to `build/verify.py`, prints the verdict.

`build/mkiso.sh` cannot call a Python function, so this is the thin shim between them:

    python3 build/gather.py kernel-config build/kernel.config
    python3 build/gather.py rootfs /build/rootfs-listing.txt
    python3 build/gather.py apk-manifest /build/apk-manifest.txt build/apk-versions.txt

Exit 0 means no violations; exit 1 prints each violation — the claim it broke and what was seen —
and the build stops there.

**All the I/O lives here and none of the judgement does.** `verify.py` never opens a file, which is
exactly what lets `tests/test_build_verifier.py` feed it a deliberately broken input in
milliseconds instead of building an image to find out whether an assertion still bites.

Two subcommands are not judgements at all and are here because they read the same files:
`pins-of-group` prints one group of `build/apk-versions.txt` as `apk add` arguments, and
`prune-busybox-applets` deletes the applet symlinks whose names the claims forbid.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

_here = Path(__file__).parent
_spec = importlib.util.spec_from_file_location("aobs_build_verify", _here / "verify.py")
assert _spec is not None and _spec.loader is not None
verify = importlib.util.module_from_spec(_spec)
sys.modules["aobs_build_verify"] = verify
_spec.loader.exec_module(verify)


def _read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def _listing(path: str) -> list[str]:
    return [line for line in _read(path).splitlines() if line.strip()]


def _tree(root: str) -> list[str]:
    base = Path(root)
    return [
        str(path.relative_to(base.parent))
        for path in base.rglob("*")
        if "__pycache__" not in path.parts
    ]


def _report(violations: list) -> int:
    if not violations:
        return 0
    sys.stderr.write(f"\n{len(violations)} violation(s):\n\n")
    for violation in violations:
        sys.stderr.write(f"  {violation}\n\n")
    return 1


def main(argv: list[str]) -> int:
    if not argv:
        sys.stderr.write(__doc__ or "")
        return 2
    command, arguments = argv[0], argv[1:]

    if command == "kernel-config":
        return _report(verify.check_kernel_config(_read(arguments[0])))

    if command == "cmdline":
        firmware, path = arguments
        text = _read(path)
        extract = (
            verify.cmdline_from_isolinux if firmware == verify.BIOS else verify.cmdline_from_grub
        )
        return _report(verify.check_cmdline(extract(text), firmware))

    if command == "rootfs":
        return _report(verify.check_rootfs(_listing(arguments[0])))

    if command == "vendored-tree":
        return _report(verify.check_vendored_tree(_tree(arguments[0])))

    if command == "apk-manifest":
        manifest, pins = arguments
        return _report(verify.check_apk_manifest(_read(manifest), _read(pins)))

    if command == "pins-of-group":
        group, path = arguments
        pins = verify.parse_pins(_read(path))
        print(" ".join(f"{name}={version}" for name, version in pins[group].items()))
        return 0

    if command == "prune-busybox-applets":
        return _prune_busybox_applets(arguments[0])

    sys.stderr.write(f"unknown command: {command}\n")
    return 2


def _prune_busybox_applets(rootfs: str) -> int:
    """Remove the applet symlinks whose names a published claim forbids.

    Alpine's busybox package ships a symlink for a getty, a login, and most of a network toolbox.
    Deleting them is what makes "no getty, no network utility in the rootfs" true of the image.

    **Only symlinks are removed, never a real file.** A regular file with a forbidden name is a
    dependency of something, and quietly deleting it would trade a false claim for a broken
    appliance — so it is left where it is and `check_rootfs` fails the build on it. The verifier is
    an independent judge of the result: an applet nobody thought to list here fails the build
    rather than shipping.

    What this does **not** do is make the applets unreachable. `busybox wget` still exists as code
    inside the one binary, and no file listing can see that. What makes it inert is `CONFIG_NET=n`,
    checked in the kernel config where the claim actually lives — `docs/boot-pipeline.md` says the
    same thing about `sh`: busybox is in the image, Python can `os.execv` anything, and the true
    claim is the one the build checks.
    """
    root = Path(rootfs)
    for directory in ("bin", "sbin", "usr/bin", "usr/sbin"):
        base = root / directory
        if not base.is_dir():
            continue
        for entry in sorted(base.iterdir()):
            if entry.name not in verify.FORBIDDEN_BASENAMES or not entry.is_symlink():
                continue
            target = os.readlink(entry)
            if "busybox" not in target:
                continue
            entry.unlink()
            print(f"/{directory}/{entry.name} -> {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
