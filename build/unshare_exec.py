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

**The cause is not the `unshare` binary**, which was this file's first theory and was wrong. With
`kernel.apparmor_restrict_unprivileged_userns=1` the namespace is created and then has no
capabilities in it, so the map write is refused whoever makes it — writing `/proc/self/uid_map`
from Python fails the same way, one step earlier and with `Permission denied` on `setgroups`.

So the maps are written by `newuidmap` and `newgidmap`, which are setuid-root and can write a map
for a process that cannot write its own. That is exactly what mmdebstrap does in stage 1, and it is
why stage 1 works on a runner where `unshare -Ur` does not.

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
import subprocess
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


def _check(result: int, what: str) -> None:
    if result != 0:
        error = ctypes.get_errno()
        raise OSError(error, f"{what}: {os.strerror(error)}")


def fork_into_namespace() -> int:
    """Fork a child in a new user namespace, map it with `newuidmap`, and return its pid.

    **The maps are written by `newuidmap`, not by this process, and that is the whole point.**
    Writing `/proc/self/uid_map` straight after `unshare(2)` is the documented way and it does not
    work here: with `kernel.apparmor_restrict_unprivileged_userns=1` the namespace is created and
    then has no capabilities in it, so the write is refused whoever makes it. Measured on
    `ubuntu-24.04`, twice and with two different errors — `Operation not permitted` on `uid_map`
    from `unshare -Ur`, and `Permission denied` on `setgroups` from this file's first version,
    which is what finally identified the cause.

    `newuidmap` and `newgidmap` are setuid-root with `CAP_SETUID` and `CAP_SETGID`, so they can
    write a map for a process that cannot write its own. Mapping namespace uid 0 to the caller's
    own uid needs no `/etc/subuid` entry, and one uid is all this needs — nothing in the check
    reads a file owned by anybody else. This is the same mechanism mmdebstrap uses in stage 1,
    which is why that stage works on a runner where `unshare -Ur` does not.

    Two pipes rather than one: the child cannot proceed until the maps exist, and the parent cannot
    write them until the namespace does.
    """
    created_read, created_write = os.pipe()
    mapped_read, mapped_write = os.pipe()

    pid = os.fork()
    if pid == 0:
        os.close(created_read)
        os.close(mapped_write)
        _check(_libc().unshare(CLONE_NEWUSER | CLONE_NEWNS), "could not create a user namespace")
        os.write(created_write, b"1")
        if os.read(mapped_read, 1) != b"1":
            os._exit(70)
        return 0

    os.close(created_write)
    os.close(mapped_read)
    if os.read(created_read, 1) != b"1":
        raise OSError("the child never entered a user namespace")
    uid, gid = os.getuid(), os.getgid()
    for tool, own in (("newuidmap", uid), ("newgidmap", gid)):
        if subprocess.run([tool, str(pid), "0", str(own), "1"], check=False).returncode != 0:
            raise OSError(f"{tool} could not map namespace id 0 to {own}")
    os.write(mapped_write, b"1")
    return pid


def bind_devices(rootfs: str) -> None:
    libc = _libc()
    for node in BOUND_DEVICES:
        target = os.path.join(rootfs, "dev", node)
        # The empty file is the mount point. It outlives the namespace, so the caller deletes it —
        # a regular file called `dev/null` in an initramfs is worse than no `dev/null` at all, and
        # `build/mkinitramfs.py` refuses to pack a tree that still has one.
        with open(target, "wb"):
            pass
        _check(
            libc.mount(f"/dev/{node}".encode(), target.encode(), None, MS_BIND, None),
            f"could not bind /dev/{node}",
        )


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    rootfs, command = argv[0], argv[1:]

    pid = fork_into_namespace()
    if pid != 0:
        # The parent's only remaining job is to be the exit status. A signalled child is reported
        # as a non-zero status rather than as a clean run, because the whole reason this exists is
        # that a quiet pass here would be a pure-Python signer shipping unremarked.
        _, status = os.waitpid(pid, 0)
        return os.waitstatus_to_exitcode(status) if os.WIFEXITED(status) else 128 + os.WTERMSIG(status)

    bind_devices(rootfs)
    os.chroot(rootfs)
    os.chdir("/")
    os.execv(command[0], command)
    return 127


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
