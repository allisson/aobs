"""Measurements off a `tar -tvf` listing of the appliance rootfs. THROWAWAY, with the probe.

The numbers `docs/roadmap.md` M2 asks for as measurements rather than estimates: the unpacked size
the RAM floor is derived from, and what shipping the full `console-data` keymap set actually costs.

Reads a listing rather than a tree so that nothing in the probe needs privilege — the tar records
ownership as data, which is the whole reason the rootfs is produced as a tarball.
"""

import sys


def main(path: str) -> int:
    rows = []
    for line in open(path, encoding="utf-8", errors="replace"):
        parts = line.split(None, 5)
        if len(parts) < 6 or not parts[2].isdigit():
            continue
        rows.append((int(parts[2]), parts[5].rstrip("\n")))

    total = sum(size for size, _ in rows)
    print(f"MEASURED unpacked      = {total // 1024} KiB ({total / 1048576:.1f} MiB)")

    for label, needle in (
        ("modules", "lib/modules"),
        ("keymaps", "share/keymaps"),
        ("python3", "lib/python3"),
        ("locale", "share/locale"),
        ("doc", "share/doc"),
        ("kernel", "vmlinuz"),
    ):
        n = sum(size for size, name in rows if needle in name)
        print(f"MEASURED {label:<13} = {n // 1024} KiB ({n / 1048576:.1f} MiB)")

    names = [name for _, name in rows]
    print(f"MEASURED keymap_files = {sum(1 for n in names if '.kmap' in n)}")

    # Presence, not size. The last three are what build/verify.py will have to fail the build on.
    for label, needle in (
        ("sh", "bin/sh"),
        ("python3", "usr/bin/python3"),
        ("libsecp256k1", "libsecp256k1.so"),
        ("vmlinuz", "vmlinuz"),
        ("getty", "getty"),
        ("apt", "usr/bin/apt"),
        ("dpkg", "usr/bin/dpkg"),
    ):
        hit = [n for n in names if needle in n]
        print(f"PRESENT  {label:<13} = {hit[0] if hit else 'NO'}  ({len(hit)} matches)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
