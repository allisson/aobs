"""Run a command inside the built image, unprivileged, without the `unshare` binary.

`build/mkiso.sh` stage 3d chroots into the rootfs to make it produce a signature with its own
interpreter and its own `libsecp256k1`. That needs a user namespace, and on `ubuntu-24.04` the
obvious way to get one does not work:

    unshare: write failed /proc/self/uid_map: Operation not permitted

**The namespace was created; the mapping was refused.** Ubuntu 24.04 ships an AppArmor profile for
`/usr/bin/unshare` — it is one of the binaries the distribution treats as a user-namespace gadget —
and a process confined by it cannot write its own `uid_map`. `mmdebstrap` is unaffected in stage 1
because it is not a profiled binary and because it shells out to setuid `newuidmap` over the whole
`/etc/subuid` range.

So the namespace is created here instead, from a process AppArmor has no opinion about. It is the
same three writes `unshare -Ur` performs — `setgroups deny`, then a single-uid `uid_map` and
`gid_map` — and nothing here needs any capability the caller did not already have.

The device nodes are bound one at a time over empty regular files. `mount --bind /dev` is refused
inside a user namespace with `wrong fs type`, because the whole directory is a mount with locked
flags; a bind over a plain file is not. Five nodes is all this check needs, and `/dev/null` is the
one that matters: `ctypes.util.find_library` shells out to `ldconfig` with `stdin=DEVNULL`, and
without it the image reports a pure-Python EC backend with no error anywhere.

    python3 build/unshare_exec.py <rootfs> <command> [args...]
"""

from __future__ import annotations

import ctypes
import os
import sys

CLONE_NEWNS = 0x00020000
CLONE_NEWUSER = 0x10000000
MS_BIND = 4096

#: What the image needs to behave like a booted machine for the length of one check. On the
#: appliance these are declared in the cpio header and then covered by devtmpfs; here they are
#: borrowed from the build host.
BOUND_DEVICES = ("null", "zero", "urandom", "random", "tty")


def _libc() -> ctypes.CDLL:
    return ctypes.CDLL(None, use_errno=True)


def enter_namespace() -> None:
    # `libc.unshare` rather than `os.unshare`, which is Linux-only and 3.12+. This file already
    # calls `mount(2)` through ctypes and there is no reason for two mechanisms.
    uid, gid = os.getuid(), os.getgid()
    if _libc().unshare(CLONE_NEWUSER | CLONE_NEWNS) != 0:
        error = ctypes.get_errno()
        raise OSError(error, f"could not create a user namespace: {os.strerror(error)}")
    # `setgroups deny` first, and it is not optional: without it the kernel refuses the `gid_map`
    # write, because a process that kept its supplementary groups could otherwise drop a group by
    # entering a namespace.
    with open("/proc/self/setgroups", "w") as handle:
        handle.write("deny")
    with open("/proc/self/uid_map", "w") as handle:
        handle.write(f"0 {uid} 1")
    with open("/proc/self/gid_map", "w") as handle:
        handle.write(f"0 {gid} 1")


def bind_devices(rootfs: str) -> None:
    libc = _libc()
    for node in BOUND_DEVICES:
        target = os.path.join(rootfs, "dev", node)
        # The empty file is the mount point. It outlives the namespace, so the caller deletes it —
        # a regular file called `dev/null` in an initramfs is worse than no `dev/null` at all, and
        # `build/mkinitramfs.py` refuses to pack a tree that still has one.
        with open(target, "wb"):
            pass
        if libc.mount(f"/dev/{node}".encode(), target.encode(), None, MS_BIND, None) != 0:
            error = ctypes.get_errno()
            raise OSError(error, f"could not bind /dev/{node}: {os.strerror(error)}")


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    rootfs, command = argv[0], argv[1:]

    enter_namespace()
    bind_devices(rootfs)
    os.chroot(rootfs)
    os.chdir("/")
    os.execv(command[0], command)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
