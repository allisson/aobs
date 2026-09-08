"""The rootfs as a `newc` cpio archive, written directly rather than through `cpio(1)`.

**This is not a preference, and the reason is worth the file.** `find | cpio` reads a tree that
already exists, and a tree that already exists cannot contain `/dev/console`: `mknod` for a
character device is denied inside a user namespace, so an unprivileged build cannot create one.
Measured — `tar: ./dev/console: Cannot mknod: Operation not permitted`, on the very first
unprivileged run. An initramfs with no `/dev/console` gives PID 1 no stdio at all, which on this
appliance means a failure message nobody can read.

The `newc` header carries the device's major and minor as *fields*. Writing the archive here means
those entries are declared rather than created, so the whole build stays unprivileged and the
alternative — `sudo`, or `fakeroot`, or the kernel's `gen_init_cpio` as a build dependency — is not
needed.

Three things fall out of doing it here, and all three are wanted:

* **Every entry is `root:root`.** The build user's uid never reaches the image, so the archive does
  not depend on who built it.
* **Every mtime is `SOURCE_DATE_EPOCH`**, and entries are emitted in sorted order. That is most of
  what `docs/reproducible-build.md` will need at M4, arrived at for free.
* **The device nodes are a table in this file**, which is a list a reviewer can read, rather than
  the residue of whatever happened to be in `/dev` on the build host.

    python3 build/mkinitramfs.py --rootfs <dir> --output <file.cpio>
"""

from __future__ import annotations

import argparse
import os
import stat
import sys
from pathlib import Path

#: `newc`, the format the kernel's initramfs unpacker reads. Not `odc` and not GNU `bin`: those
#: cannot express a 32-bit device number and the kernel does not accept them here.
MAGIC = b"070701"

#: The device nodes the image needs before it has mounted anything. `/dev/console` is the one that
#: matters — the kernel wires PID 1's stdin, stdout and stderr to it, and `build/init` mounts
#: devtmpfs over the top a few lines later. The rest are the conventional minimum, cheap to declare
#: and awkward to be missing.
#:
#: `(path, mode, major, minor)`, and every one is a character device.
DEVICE_NODES = (
    ("dev/console", 0o600, 5, 1),
    ("dev/null", 0o666, 1, 3),
    ("dev/zero", 0o666, 1, 5),
    ("dev/full", 0o666, 1, 7),
    ("dev/random", 0o444, 1, 8),
    ("dev/urandom", 0o444, 1, 9),
    ("dev/tty", 0o666, 5, 0),
    ("dev/ptmx", 0o666, 5, 2),
)


class InitramfsError(Exception):
    """The tree cannot be packed into something that would boot."""


def _field(value: int) -> bytes:
    if not 0 <= value <= 0xFFFFFFFF:
        raise InitramfsError(f"{value} does not fit in a newc header field")
    return b"%08X" % value


def _pad(stream, length: int) -> int:
    padding = (-length) % 4
    if padding:
        stream.write(b"\0" * padding)
    return padding


def write_entry(
    stream,
    *,
    name: str,
    mode: int,
    mtime: int,
    data: bytes = b"",
    nlink: int = 1,
    rdev: tuple[int, int] = (0, 0),
    ino: int = 0,
) -> None:
    """One `newc` member. `uid` and `gid` are always zero, and that is the point.

    The header is a fixed 110 bytes of ASCII hex followed by the NUL-terminated name, both padded
    to a four-byte boundary. `check` is zero for `newc` — the format defines the field and the
    kernel ignores it.
    """
    encoded = name.encode("utf-8") + b"\0"
    header = (
        MAGIC
        + _field(ino)
        + _field(mode)
        + _field(0)  # uid: root, never the build user's
        + _field(0)  # gid
        + _field(nlink)
        + _field(mtime)
        + _field(len(data))
        + _field(0)  # devmajor of the filesystem the entry came from; meaningless here
        + _field(0)  # devminor
        + _field(rdev[0])
        + _field(rdev[1])
        + _field(len(encoded))
        + _field(0)  # check, unused by newc
    )
    stream.write(header)
    stream.write(encoded)
    _pad(stream, len(header) + len(encoded))
    if data:
        stream.write(data)
        _pad(stream, len(data))


def pack(rootfs: Path, stream, *, mtime: int) -> int:
    """Every member of `rootfs`, then the device nodes, then the trailer. Returns the count.

    Sorted, so the archive is a function of the tree and not of readdir order. Hardlinks are
    written as separate copies rather than as shared inodes: the saving in a rootfs this size is
    under a megabyte before compression, and a shared-inode `newc` entry that the kernel's unpacker
    disagrees with about ordering produces a zero-length binary, silently.
    """
    written = 0
    for path in sorted(rootfs.rglob("*"), key=lambda p: str(p)):
        info = path.lstat()
        name = str(path.relative_to(rootfs))
        if stat.S_ISLNK(info.st_mode):
            write_entry(
                stream,
                name=name,
                mode=info.st_mode,
                mtime=mtime,
                data=os.readlink(path).encode("utf-8"),
            )
        elif stat.S_ISDIR(info.st_mode):
            write_entry(stream, name=name, mode=info.st_mode, mtime=mtime, nlink=2)
        elif stat.S_ISREG(info.st_mode):
            write_entry(stream, name=name, mode=info.st_mode, mtime=mtime, data=path.read_bytes())
        else:
            # A socket or a fifo left behind by something. Neither belongs in an image that starts
            # from nothing every boot, and silently packing one would be the wrong kind of quiet.
            raise InitramfsError(f"{name} is neither a file, a directory nor a symlink")
        written += 1

    for name, mode, major, minor in DEVICE_NODES:
        write_entry(
            stream,
            name=name,
            mode=stat.S_IFCHR | mode,
            mtime=mtime,
            rdev=(major, minor),
        )
        written += 1

    write_entry(stream, name="TRAILER!!!", mode=0, mtime=0)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rootfs", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)

    if not (args.rootfs / "init").is_file():
        raise InitramfsError(f"{args.rootfs}/init does not exist; the kernel would panic on boot")
    if (args.rootfs / "dev" / "console").exists():
        raise InitramfsError(
            f"{args.rootfs}/dev/console exists on disk. The device nodes are declared in this "
            "file's table, and a real one in the tree means the build ran with privileges it is "
            "not supposed to need"
        )

    mtime = int(os.environ.get("SOURCE_DATE_EPOCH", "0"))
    with args.output.open("wb") as stream:
        count = pack(args.rootfs, stream, mtime=mtime)
    print(f"initramfs: {count} members, {args.output.stat().st_size // 1048576} MiB uncompressed")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except InitramfsError as error:
        print(f"mkinitramfs: {error}", file=sys.stderr)
        sys.exit(1)
