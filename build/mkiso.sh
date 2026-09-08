#!/bin/sh
# `out/bitcoin-signer-amd64.iso`, from `build/inputs/` and nothing else.
#
# Five stages, in the order `docs/boot-pipeline.md` fixes them. Run it with no arguments:
#
#     sh build/mkiso.sh
#
# UNPRIVILEGED, START TO FINISH. There is no `sudo` in this file and there is no `--privileged`
# anywhere near it. "Requires root on the host" is a real barrier to the independent rebuilds the
# whole trust model rests on, so if `--mode=unshare` ever stops working that is a finding to write
# down in `docs/boot-pipeline.md`, not a licence to reach for root.
#
# `set -e` IS right here, and it is the exact opposite of the rule in `build/init`. A build that
# stops at the first failure loses nothing; an init that stops is a kernel panic the user cannot
# read past. Two scripts, two rules, and the reason each has the rule it has is the consequence of
# the failure, not a house style.

set -eu

ROOT=$(cd "$(dirname "$0")/.." && pwd)
INPUTS=$ROOT/build/inputs
OUT=$ROOT/out
WORK=$OUT/work
ROOTFS=$WORK/rootfs
KERNEL_STAGE=$WORK/kernel
ISO_TREE=$WORK/iso
ISO=$OUT/bitcoin-signer-amd64.iso

. "$ROOT/build/snapshot.env"

#: Argon2id's transient, fixed by `docs/export-password.md`.
ARGON2_MIB=64
#: The Python heap and the camera buffers. The one estimated term in the floor.
HEADROOM_MIB=128

say() { printf '\n==> %s\n' "$*"; }

# --- Where the privilege isn't ---------------------------------------------------------------------
#
# Nothing in this file runs as root, and nothing in it needs to. Two things looked like they would
# and neither does:
#
#   * **Device nodes.** `mknod` for a character device is denied in a user namespace, so the rootfs
#     on disk cannot contain `/dev/console`. `build/mkinitramfs.py` writes the cpio archive itself
#     and DECLARES the device nodes in the header, which is why stage 4 is a Python script and not
#     `find | cpio`.
#   * **Ownership.** Every member of that archive is written as `root:root` regardless of who built
#     it, so the tree on disk can stay owned by the build user and `tar --no-same-owner` is enough.
#
# What is left needing a namespace is one step: stage 3d chroots into the image to make it produce
# a signature with its own interpreter. `unshare -Ur` covers that — a single-uid map, because
# everything in the tree is already owned by the caller.

# --- Stage 0. Refuse to start on the wrong ground --------------------------------------------------

say "stage 0: preflight"

# The ISO is amd64 and stage 4 runs the appliance's own interpreter to prove it can sign. Both of
# those need the host to be amd64, and neither is worth an escape hatch: a build that skips its own
# signing check on a foreign host is a build that passes loudest exactly where it checked least.
# On an arm64 workstation, run this whole script under `docker run --platform=linux/amd64`.
arch=$(uname -m)
[ "$arch" = "x86_64" ] || {
    echo "mkiso: this build must run on x86_64; this host is $arch." >&2
    echo "       Run it inside \`docker run --platform=linux/amd64\` instead." >&2
    exit 1
}

missing=
for tool in mmdebstrap newuidmap dpkg-deb dpkg-scanpackages depmod zstd xorriso \
            mformat mcopy grub-mkstandalone python3 readelf unshare; do
    command -v "$tool" >/dev/null 2>&1 || missing="$missing $tool"
done
[ -z "$missing" ] || {
    echo "mkiso: the build host is missing:$missing" >&2
    echo "       Debian/Ubuntu: mmdebstrap uidmap dpkg-dev kmod zstd xorriso mtools" >&2
    echo "       grub-efi-amd64-bin isolinux binutils python3 python3-pip" >&2
    exit 1
}

# Every byte the build consumes, checked before any of it is used. `fetch-inputs.sh` is the one
# networked step in this project and it is not part of any build; this is where its output is
# trusted or not.
[ -d "$INPUTS/deb/appliance" ] || {
    echo "mkiso: no build/inputs. Run \`sh build/fetch-inputs.sh\` first." >&2
    exit 1
}
( cd "$ROOT" && sha256sum -c --quiet build/inputs.sha256 )
named=$(wc -l < "$ROOT/build/inputs.sha256")
present=$(find "$INPUTS" -type f | wc -l)
[ "$named" -eq "$present" ] || {
    echo "mkiso: build/inputs has $present files and build/inputs.sha256 names $named." >&2
    echo "       An unexpected extra file is a failure, not something to ignore." >&2
    exit 1
}

# The pin-file and closure assertions, before a single package is unpacked. Both are cheap and
# both fail for reasons that would otherwise only show up as a strange rootfs.
python3 "$ROOT/build/verify.py" --closure "$INPUTS/deb/appliance"

rm -rf "$WORK"
mkdir -p "$WORK" "$OUT"

# --- Stage 1. The rootfs ----------------------------------------------------------------------------

say "stage 1: rootfs (mmdebstrap --mode=unshare, no network, no privilege)"

# THE POOL IS STAGED OUTSIDE THE CHECKOUT, and this is the constraint that bit twice.
#
# apt's `copy:` method drops privileges to `_apt` before reading, and in unshare mode that is a
# subuid that is nobody the host has heard of. It therefore needs every ANCESTOR of the pool to be
# traversable by a stranger, not merely the pool and its files to be readable — and a repository
# checkout under a home directory is not. Measured on `ubuntu-24.04`:
# `Failed to stat - stat (13: Permission denied)`, seven times, against a pool whose own
# permissions were 755 and whose `Packages` was 644.
#
# `APT::Sandbox::User "root"` is set below and is NOT sufficient on its own; the first version of
# this script had it and failed anyway. `$TMPDIR` is avoided for the same reason — on a GitHub
# runner it points back inside the home directory.
POOL=$(mktemp -d /tmp/aobs-pool.XXXXXX)
trap 'rm -rf "$POOL"' EXIT INT TERM
chmod 755 "$POOL"
cp "$INPUTS"/deb/appliance/*.deb "$POOL/"
chmod 644 "$POOL"/*.deb
( cd "$POOL" && dpkg-scanpackages -m . > Packages 2>/dev/null && gzip -kf Packages )

# `--variant=custom` with `--include='?essential'`, and NOT `--variant=essential`. Against a flat
# local repo mmdebstrap reports `no essential packages -- skipping` and installs none of them,
# while apt reads `Essential: yes` from that same repo perfectly well: `dpkg-scanpackages -m`
# preserves the field and apt's `?essential` pattern matches on it. So the Essential set is
# selected with apt's pattern rather than with mmdebstrap's variant machinery.
#
# ONE `--include` PER PACKAGE. mmdebstrap does not split a comma-joined list that contains a
# pattern; it hands apt the whole string as a single package name and apt reports
# `Unable to locate package ?essential,dash,busybox,...`.
#
# `copy://`, NOT `file://`. A `file://` URI is resolved by apt running INSIDE the chroot, where the
# host's pool path does not exist. `copy://` reads on the host and copies in.
includes="--include=?essential"
for pin in $(awk '
    /^# @group / { g = $3; next }
    /^[[:space:]]*#/ { next }
    /^[[:space:]]*$/ { next }
    { if (g == "appliance") { split($0, f, "="); print f[1] } }
' "$ROOT/build/apt-versions.txt" | grep -v '^linux-image'); do
    includes="$includes --include=$pin"
done

mmdebstrap \
    --mode=unshare \
    --variant=custom \
    $includes \
    --aptopt='APT::Sandbox::User "root"' \
    --aptopt='Acquire::AllowInsecureRepositories "true"' \
    --customize-hook='rm -f "$1"/etc/resolv.conf "$1"/etc/hostname' \
    "$DEBIAN_SUITE" "$WORK/rootfs.tar" "deb [trusted=yes] copy://$POOL ./"

say "stage 1: $(stat -c %s "$WORK/rootfs.tar" | awk '{printf "%.1f MiB", $1/1048576}') of tarball"

say "stage 1b: unpacking the rootfs"
mkdir -p "$ROOTFS"
# `--no-same-owner` because the build is unprivileged and the ownership in the tarball is not what
# ships anyway: `build/mkinitramfs.py` writes every archive member as root:root. `./dev/*` is
# excluded because those members are device nodes, which cannot be created without privilege and
# are declared in the cpio header instead.
tar -C "$ROOTFS" --no-same-owner --exclude='./dev/*' -xf "$WORK/rootfs.tar"
rm -f "$WORK/rootfs.tar"

# --- The release identity file -------------------------------------------------------------------
#
# A stage-1 output on purpose, so that stage 4 can check it against the tag while it is still a
# file a human can open rather than a member of an archive.
say "stage 1c: /etc/aobs-release"
commit=$(cd "$ROOT" && git rev-parse HEAD 2>/dev/null || echo "")
if (cd "$ROOT" && git diff --quiet HEAD 2>/dev/null); then dirty=no; else dirty=yes; fi
tag=$(cd "$ROOT" && git describe --exact-match --tags 2>/dev/null || echo "")
# A build that is not at a clean tag says `development` and NEVER a version-shaped string, so that
# nobody signs with one months later believing it was a release.
if [ -n "$tag" ] && [ "$dirty" = "no" ]; then release=$tag; else release=development; fi
: "${SOURCE_DATE_EPOCH:=$(cd "$ROOT" && git log -1 --pretty=%ct 2>/dev/null || date +%s)}"
released=$(date -u -d "@$SOURCE_DATE_EPOCH" +%Y-%m-%d 2>/dev/null || echo unknown)
cat > "$ROOTFS/etc/aobs-release" <<EOF
release: $release
released: $released
git-commit: $commit
dirty: $dirty
EOF

# --- Stage 2. The Python layer -------------------------------------------------------------------
#
# **`pip` is never installed into the rootfs, and this is a correction to what M2 originally
# specified.** The plan was to install it, use it and purge it with `--auto-remove`. It cannot be
# done: `python3-pip` is a HARNESS-group package, the appliance pool does not contain it, and
# putting it in the rootfs even transiently means installing a harness package into the image —
# which is the one thing the group split exists to forbid.
#
# So the wheels are unpacked from outside by the build host's pip, with the target platform named
# explicitly. `pip`, `python3-wheel` and `python3-packaging` are therefore absent from the image by
# construction rather than by removal, which is a stronger position than the purge would have
# reached. `build/verify.py` still asserts all three are gone: the assertion is what makes the
# claim checkable, and it does not care how it came to be true.

say "stage 2: the Python layer (wheels, no pip in the image)"
python3 -m pip install \
    --quiet \
    --no-index \
    --no-cache-dir \
    --find-links "$INPUTS/wheels/appliance" \
    --require-hashes \
    --only-binary :all: \
    --implementation cp \
    --python-version 3.13 \
    --platform manylinux_2_28_x86_64 \
    --platform manylinux2014_x86_64 \
    --target "$ROOTFS/opt/aobs-python" \
    -r "$ROOT/build/requirements.appliance.txt"
find "$ROOTFS/opt/aobs-python" -name '*.dist-info' -prune -o -name '__pycache__' -type d -exec rm -rf {} +

# The app tree, copied and never `pip install`ed. It is not a distribution and there is nothing for
# a resolver to do: `build/init` puts `/opt/aobs` on `PYTHONPATH` and `python3 -m aobs` finds it.
say "stage 2b: the app tree"
mkdir -p "$ROOTFS/opt/aobs"
tar -C "$ROOT" -cf - aobs | tar -C "$ROOTFS/opt/aobs" -xf -
find "$ROOTFS/opt/aobs" -name '__pycache__' -type d -exec rm -rf {} +

# --- Stage 3. The kernel ---------------------------------------------------------------------------

say "stage 3: kernel, extracted and never installed"
mkdir -p "$KERNEL_STAGE"
for deb in "$INPUTS"/deb/kernel/linux-image-6*.deb; do
    dpkg-deb -x "$deb" "$KERNEL_STAGE"
done
KVER=$(ls "$KERNEL_STAGE/usr/lib/modules")
[ -n "$KVER" ] || { echo "mkiso: no module tree in the kernel package" >&2; exit 1; }
say "stage 3: kernel $KVER"

# `modules.dep` is NOT shipped in the .deb — Debian generates it from the maintainer script, and
# this build runs no maintainer scripts. So the first depmod is not a nicety; without it there is
# no dependency graph to prune against.
depmod -b "$KERNEL_STAGE/usr" "$KVER"

python3 "$ROOT/build/prune_modules.py" \
    --tree "$KERNEL_STAGE/usr/lib/modules/$KVER" \
    --allow "$ROOT/build/modules.allow" \
    --write-loadlist "$ROOTFS/etc/aobs-modules"

# Regenerate against what survived, so `modprobe` on the appliance reads a graph that describes
# the tree it actually has rather than the one Debian shipped.
mkdir -p "$ROOTFS/usr/lib/modules"
cp -a "$KERNEL_STAGE/usr/lib/modules/$KVER" "$ROOTFS/usr/lib/modules/"
depmod -b "$ROOTFS/usr" "$KVER"

install -D -m 644 "$ROOT/build/modprobe-blacklist.conf" "$ROOTFS/etc/modprobe.d/aobs.conf"

# --- Stage 3b. The purge ---------------------------------------------------------------------------
#
# Three things Debian insists on, used and then removed before the initramfs is packed.
# `docs/boot-pipeline.md` has the table and `build/verify.py` fails the build if any survives.

say "stage 3b: purge"
# What the image contains, captured while it can still say so. The group split's whole question is
# "may this survive into the shipped rootfs?", and `var/lib/dpkg/status` is the only thing that
# answers it — and the next command deletes it.
grep '^Package:' "$ROOTFS/var/lib/dpkg/status" > "$WORK/installed.txt"
# dpkg and its database. It is a package manager, and the published claim says none is in the
# image. Nothing on the appliance installs anything, so nothing needs to read the database either.
rm -rf "$ROOTFS/var/lib/dpkg" "$ROOTFS/var/cache/apt" "$ROOTFS/var/lib/apt" "$ROOTFS/etc/dpkg" \
       "$ROOTFS/usr/bin/dpkg" "$ROOTFS/usr/bin/dpkg-deb" "$ROOTFS/usr/bin/dpkg-divert" \
       "$ROOTFS/usr/bin/dpkg-maintscript-helper" "$ROOTFS/usr/bin/dpkg-query" \
       "$ROOTFS/usr/bin/dpkg-split" "$ROOTFS/usr/bin/dpkg-statoverride" \
       "$ROOTFS/usr/bin/dpkg-trigger" "$ROOTFS/usr/sbin/dpkg-preconfigure" \
       "$ROOTFS/usr/sbin/dpkg-reconfigure" "$ROOTFS/usr/share/dpkg"
# apt, if the closure put it there. It is in the appliance POOL — `debian-archive-keyring`,
# `libapt-pkg7.0` and `sqv` sit beside it — so whether it reaches the rootfs depends on what
# mmdebstrap chose to install, and "depends on" is not a thing a published claim may rest on.
rm -rf "$ROOTFS/usr/bin/apt" "$ROOTFS/usr/bin/apt-get" "$ROOTFS/usr/bin/apt-cache" \
       "$ROOTFS/usr/bin/apt-config" "$ROOTFS/usr/bin/apt-key" "$ROOTFS/usr/bin/apt-mark" \
       "$ROOTFS/usr/lib/apt" "$ROOTFS/etc/apt" "$ROOTFS/usr/share/doc/apt"
# agetty. `util-linux` ships it and PID 1 needs `util-linux` for `mount`, so it arrives whether or
# not it is wanted. Nothing spawns it — there is no init system — but "there is no getty" was false
# of the tree as built, and narrowing the claim to "no getty RUNS" was the alternative and was
# rejected: `ls` can check the first and only an argument can check the second.
rm -f "$ROOTFS/usr/sbin/agetty" "$ROOTFS/sbin/agetty"
# Not a claim, just the largest prunable thing in the tree at 27.3 MiB. Nothing in this appliance
# reads a locale: the console is fixed to UTF-8 and every string it shows is its own.
rm -rf "$ROOTFS/usr/share/locale" "$ROOTFS/usr/share/doc" "$ROOTFS/usr/share/man" \
       "$ROOTFS/usr/share/info" "$ROOTFS/usr/share/lintian"

# --- Stage 3c. PID 1 ---------------------------------------------------------------------------------
#
# Last, because the RAM floor it carries is derived from the finished tree. `build/init` ships with
# placeholders and `build/verify.py` fails the build if an unsubstituted one reaches the image.

say "stage 3c: PID 1 and the derived RAM floor"
unpacked_kib=$(du -sk "$ROOTFS" | awk '{print $1}')
unpacked_mib=$(( unpacked_kib / 1024 ))
required_mib=$(( 2 * unpacked_mib + ARGON2_MIB + HEADROOM_MIB ))
floor_mib=1
while [ "$floor_mib" -lt "$required_mib" ]; do floor_mib=$(( floor_mib * 2 )); done

sed -e "s/@RAM_REQUIRED_MIB@/$required_mib/" \
    -e "s/@RAM_FLOOR_MIB@/$floor_mib/" \
    -e "s/@DEFAULT_KEYMAP@/us/" \
    "$ROOT/build/init" > "$ROOTFS/init"
chmod 755 "$ROOTFS/init"

say "measured: unpacked rootfs ${unpacked_mib} MiB -> requires ${required_mib} MiB -> floor ${floor_mib} MiB"

# --- Stage 3d. The assertions, against a tree that exists ------------------------------------------

say "stage 3d: build-time assertions"
( cd "$ROOTFS" && find . -type f -o -type l -o -type d ) > "$WORK/rootfs.files"
paths_count=$(wc -l < "$WORK/rootfs.files" | tr -d ' ')
readelf --dyn-syms --wide "$ROOTFS"/usr/lib/x86_64-linux-gnu/libsecp256k1.so.* \
    | awk '{ print $8 }' | sed 's/@.*//' | sort -u > "$WORK/libsecp256k1.syms"

python3 "$ROOT/build/verify.py" \
    --rootfs "$ROOTFS" \
    --files "$WORK/rootfs.files" \
    --installed "$WORK/installed.txt" \
    --symbols "$WORK/libsecp256k1.syms" \
    --allow "$ROOT/build/modules.allow" \
    --kver "$KVER" \
    --measured-mib "$unpacked_mib"

# The one assertion that cannot be a pure function over a listing: does the interpreter in this
# rootfs actually produce a signature in each scheme? A name check on the backend module is not
# enough — embit binds `schnorrsig`, `xonly` and `keypair` inside their own bare `except: pass`, so
# a library compiled without those modules imports cleanly, reports the native backend, and fails
# at taproot signing, mid-session, with a wallet loaded.
say "stage 3d: one signature in each scheme, from inside the image"

# `unshare -Urm` and a bind-mounted `/dev`, and the reason is a finding worth the two extra lines.
#
# On the first run of this check the image reported `py_secp256k1` — a pure-Python signer in an
# appliance whose whole EC story is that it never uses one. The library was present and exported
# every symbol. What failed was `ctypes.util.find_library`, which shells out to `ldconfig -p` with
# `stdin=subprocess.DEVNULL`: with no `/dev/null` in the tree that raises `FileNotFoundError`,
# CPython catches it under `except OSError: pass`, and embit's own bare `except:` turns the
# resulting `None` into the fallback backend WITHOUT ONE WORD OF OUTPUT.
#
# The image itself is fine — `/dev/null` is declared in the cpio header and devtmpfs is mounted by
# PID 1's first step. The tree on disk is what lacked it, because device nodes cannot be created
# unprivileged. So the check has to run against something shaped like the booted machine, and this
# is the cheapest thing that is: a mount namespace with the host's `/dev` bound in.
#
# It is also the clearest demonstration this project has of why the backend is asserted rather than
# assumed. Two silent excepts, one missing character device, and a signer that reports as native.
cat > "$WORK/signcheck.py" <<'PYCHECK'
import sys

from aobs.core.vendor.embit import ec
from aobs.core.vendor.embit.util import secp256k1

backend = secp256k1.ec_pubkey_create.__module__
if "ctypes" not in backend:
    sys.exit(f"the image's embit resolved to {backend}, not the ctypes binding")

key = ec.PrivateKey(b"\x01" * 32)
digest = b"\x02" * 32

ecdsa = key.sign(digest)
if not key.get_public_key().verify(ecdsa, digest):
    sys.exit("BIP84: the image could not verify its own ECDSA signature")

schnorr = key.schnorr_sign(digest)
if len(schnorr.serialize()) != 64:
    sys.exit("BIP86: schnorr_sign did not return 64 bytes")

print(f"signing: ok, backend {backend}")
PYCHECK
cp "$WORK/signcheck.py" "$ROOTFS/signcheck.py"
# Bind-mounted one device at a time, not `mount --bind /dev`: the whole directory is a mount with
# locked flags and a bind of it is refused inside a user namespace with `wrong fs type`. A bind
# over an empty regular file is not, and five nodes is the whole of what this check needs.
unshare -Urm sh -euc '
    for node in null zero urandom random tty; do
        : > "$1/dev/$node"
        mount --bind "/dev/$node" "$1/dev/$node"
    done
    PYTHONPATH=/opt/aobs:/opt/aobs-python chroot "$1" /usr/bin/python3 /signcheck.py
' -- "$ROOTFS"
# The bind mounts went with the namespace; the empty files they were mounted over did not, and a
# regular file called `dev/null` in an initramfs is worse than none. `build/mkinitramfs.py` refuses
# to pack a tree that still has one, so this is belt and braces on a mistake that would be quiet.
rm -f "$ROOTFS/signcheck.py" "$ROOTFS/dev/null" "$ROOTFS/dev/zero" "$ROOTFS/dev/urandom" \
      "$ROOTFS/dev/random" "$ROOTFS/dev/tty"

# --- Stage 4. The initramfs -------------------------------------------------------------------------

say "stage 4: newc | zstd"
mkdir -p "$ISO_TREE/boot"
SOURCE_DATE_EPOCH=$SOURCE_DATE_EPOCH \
    python3 "$ROOT/build/mkinitramfs.py" --rootfs "$ROOTFS" --output "$WORK/initramfs.cpio"
zstd -19 -T0 -q -f -o "$ISO_TREE/boot/initramfs.zst" "$WORK/initramfs.cpio"
rm -f "$WORK/initramfs.cpio"
cp "$KERNEL_STAGE/boot/vmlinuz-$KVER" "$ISO_TREE/boot/vmlinuz"

mib() { stat -c %s "$1" | awk '{ printf "%.1f", $1 / 1048576 }'; }
initramfs_mib=$(mib "$ISO_TREE/boot/initramfs.zst")
kernel_mib=$(mib "$ISO_TREE/boot/vmlinuz")

# --- Stage 5. The image ------------------------------------------------------------------------------

say "stage 5: xorriso, hybrid BIOS + UEFI"

# BIOS: isolinux, from the host's own syslinux files. These are loader bytes and not image content
# — nothing here ends up in the running system, which is the whole reason the boot medium can be
# pulled once the kernel and initramfs are in memory.
mkdir -p "$ISO_TREE/isolinux"
for f in isolinux.bin ldlinux.c32; do
    src=$(find /usr/lib/ISOLINUX /usr/lib/syslinux -name "$f" 2>/dev/null | head -1)
    [ -n "$src" ] || { echo "mkiso: cannot find $f (install isolinux and syslinux-common)" >&2; exit 1; }
    cp "$src" "$ISO_TREE/isolinux/"
done
cp "$ROOT/build/isolinux.cfg" "$ISO_TREE/isolinux/"

# UEFI: one standalone binary with the config baked in, so GRUB reads nothing from the medium.
mkdir -p "$WORK/efi/EFI/boot"
grub-mkstandalone -O x86_64-efi \
    -o "$WORK/efi/EFI/boot/bootx64.efi" \
    "boot/grub/grub.cfg=$ROOT/build/grub.cfg"

# The EFI System Partition, as a FAT image El Torito can point at.
efi_kib=$(( ( $(du -sk "$WORK/efi" | awk '{print $1}') + 1024 ) / 32 * 32 + 1024 ))
rm -f "$ISO_TREE/efiboot.img"
mformat -i "$WORK/efiboot.img" -C -f "$efi_kib" -v AOBSEFI :: 2>/dev/null \
    || { dd if=/dev/zero of="$WORK/efiboot.img" bs=1024 count="$efi_kib" status=none
         mformat -i "$WORK/efiboot.img" -v AOBSEFI :: ; }
mmd   -i "$WORK/efiboot.img" ::/EFI ::/EFI/boot
mcopy -i "$WORK/efiboot.img" "$WORK/efi/EFI/boot/bootx64.efi" ::/EFI/boot/
cp "$WORK/efiboot.img" "$ISO_TREE/efiboot.img"

isohdpfx=$(find /usr/lib/ISOLINUX /usr/lib/syslinux -name 'isohdpfx.bin' 2>/dev/null | head -1)
[ -n "$isohdpfx" ] || { echo "mkiso: cannot find isohdpfx.bin" >&2; exit 1; }

rm -f "$ISO"
xorriso -as mkisofs \
    -iso-level 3 \
    -volid AOBS \
    -isohybrid-mbr "$isohdpfx" \
    -eltorito-boot isolinux/isolinux.bin \
    -eltorito-catalog isolinux/boot.cat \
    -no-emul-boot -boot-load-size 4 -boot-info-table \
    -eltorito-alt-boot \
    -e efiboot.img \
    -no-emul-boot \
    -isohybrid-gpt-basdat \
    -quiet \
    -o "$ISO" "$ISO_TREE"

iso_mib=$(mib "$ISO")

# Both boot paths, checked rather than assumed. A hybrid ISO that lost one of its El Torito entries
# still builds, still mounts and still boots on whichever firmware the person who built it happens
# to have — which is exactly the failure that reaches a user and not a build log.
records=$(xorriso -indev "$ISO" -report_el_torito plain 2>/dev/null | grep -c '^El Torito boot img')
[ "$records" -ge 2 ] || {
    echo "mkiso: the ISO has $records El Torito boot images; BIOS and UEFI need one each." >&2
    exit 1
}

say "done"
cat <<EOF

  $ISO

  | unpacked rootfs | ${unpacked_mib} MiB (${paths_count} paths) |
  | initramfs.zst   | ${initramfs_mib} MiB |
  | vmlinuz         | ${kernel_mib} MiB |
  | ISO             | ${iso_mib} MiB |

  RAM: requires ${required_mib} MiB, published floor ${floor_mib} MiB
EOF
