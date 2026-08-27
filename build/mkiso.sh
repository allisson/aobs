#!/bin/sh
#
# `bitcoin-signer-amd64.iso`, in four stages, from a container.
#
#     docker build -f build/Dockerfile.iso -t aobs-iso .
#     docker run --rm --privileged -v "$PWD:/src" -v "$PWD/out:/out" aobs-iso
#
# `docs/boot-pipeline.md` fixes the stages: a pinned apk userland into `/rootfs`, a vanilla
# kernel.org LTS tarball built against `build/kernel.config`, `cpio | zstd` into an initramfs, and
# `xorriso` into a hybrid ISO with `isolinux` for legacy BIOS and `grub-efi` for UEFI.
#
# **This script is thin, and that is the design.** It gathers inputs and calls `build/verify.py`,
# which holds every judgement. The script decides nothing by itself, so each published claim is a
# pure function that `tests/test_build_verifier.py` can feed a deliberately broken input in
# milliseconds — instead of a shell condition that can only be exercised by building an image.
#
# It **fails, it does not warn**, and it stops at the first stage that violates: nobody should ever
# read a passing log for stage 4 above a broken stage 1.
#
# Out of scope, deliberately and stated in `docs/boot-pipeline.md`: reproducible builds (nothing
# here forecloses them — every input is a pinned version with a checksum), release engineering, and
# Secure Boot. The image is unsigned and stays unsigned.

set -eu

SRC=${SRC:-/src}
OUT=${OUT:-/out}
WORK=${WORK:-/build}
ROOTFS=$WORK/rootfs
ISOROOT=$WORK/isoroot
ARTIFACT=$OUT/bitcoin-signer-amd64.iso

#: The one input that does not come from Alpine, pinned as tightly as the ones that do: by version
#: and by SHA-256 against the tarball kernel.org publishes. 6.12 is a longterm line.
#:
#: The checksum was taken from kernel.org's own published `sha256sums.asc` for `v6.x`. That file is
#: PGP-signed and **this build does not verify the signature** — it verifies the tarball against
#: the checksum committed here, which moves the trust to this repository's git history where a
#: reviewer can see it change.
KERNEL_VERSION=6.12.106
KERNEL_SHA256=0392555761d99c7604503f6178951e2df77e978b92cc96d11e248423e48ed785
KERNEL_TARBALL=linux-$KERNEL_VERSION.tar.xz
KERNEL_URL=https://cdn.kernel.org/pub/linux/kernel/v6.x/$KERNEL_TARBALL

stage() { printf '\n=== %s\n' "$1"; }
note() { printf '    %s\n' "$1"; }

# Every violation the verifier returns, printed, and then a non-zero exit. `verify.py` never
# raises on a violation and never reads a file: reading is this script's job, judging is its own,
# and that split is what makes the assertions testable without an image.
judge() {
	if ! python3 "$SRC/build/gather.py" "$@"; then
		printf '\nbuild refused: the claim above is no longer true of this image.\n' >&2
		exit 1
	fi
}

# --- Stage 0. The checked-in inputs, before any work happens -------------------------------------
#
# The kernel config, both bootloader command lines, and the vendored tree are all readable right
# now. Judging them first means a config edit that breaks a published claim costs seconds rather
# than a full kernel compile.

stage "Stage 0 — the checked-in inputs"
judge kernel-config "$SRC/build/kernel.config"
judge cmdline bios "$SRC/build/isolinux.cfg"
judge cmdline uefi "$SRC/build/grub.cfg"
judge vendored-tree "$SRC/aobs/core/vendor"
note "kernel.config, isolinux.cfg, grub.cfg, vendored tree: no violations"

rm -rf "$WORK"
mkdir -p "$ROOTFS" "$ISOROOT/boot/isolinux" "$OUT"

# --- Stage 1. Userland ---------------------------------------------------------------------------
#
# Alpine's role is the one it is genuinely good at: a pinned, checksummed source of a musl
# userland. It supplies packages, not a boot process — `mkimage.sh`, the aports ISO profiles and
# `mkinitfs` are all foreclosed by #10, since their purpose is producing and mounting a modloop
# squashfs of modules an all-built-in kernel does not have.
#
# The **appliance group only** of `build/apk-versions.txt`. The harness group — pytest, hypothesis,
# and `py3-pip` — is what the test container installs and what must never reach the image.

stage "Stage 1 — userland"
PACKAGES=$(python3 "$SRC/build/gather.py" pins-of-group appliance "$SRC/build/apk-versions.txt")
note "installing $(echo "$PACKAGES" | wc -w) pinned packages"

mkdir -p "$ROOTFS/etc/apk"
cp "$SRC/build/apk-repositories" "$ROOTFS/etc/apk/repositories"
# shellcheck disable=SC2086
apk --root "$ROOTFS" --initdb --no-cache \
	--repositories-file "$SRC/build/apk-repositories" \
	--keys-dir /etc/apk/keys \
	add $PACKAGES

# The manifest is captured *before* the apk database is removed, because it is the only record of
# what was installed and the image must not carry a package database.
apk --root "$ROOTFS" info -v | sort >"$WORK/apk-manifest.txt"
judge apk-manifest "$WORK/apk-manifest.txt" "$SRC/build/apk-versions.txt"
note "every pinned package present at its pinned version; no harness package installed"

# The applet symlinks, created explicitly rather than left to an apk trigger. `apk --root` does run
# triggers, but PID 1 is a shell script whose every line is an applet — `mount`, `sleep`, `awk`,
# `poweroff` — and "the boot works if the trigger fired" is not a thing to leave implicit in the one
# process that cannot be restarted.
chroot "$ROOTFS" /bin/busybox --install -s

# Busybox ships an applet symlink for a getty, a login and most of a network toolbox. Removing them
# is what makes "no getty, no network utility in the rootfs" true of the image; the verifier below
# is an independent judge of the result, so an applet nobody thought of fails the build rather than
# shipping. Only symlinks are removed here — never a real file, which would be a dependency.
python3 "$SRC/build/gather.py" prune-busybox-applets "$ROOTFS" | while read -r removed; do
	note "removed busybox applet: $removed"
done

# Busybox also ships *regular files* for applets this appliance does not use: an `/etc/inittab` for
# its own init, and the config and lease script for `udhcpc`. The prune above deliberately touches
# only symlinks — a regular file with a forbidden name is a dependency of something until proven
# otherwise — so these are named here, one line each, and the verifier below is what proved they
# were there in the first place.
rm -f "$ROOTFS/etc/inittab"
rm -rf "$ROOTFS/etc/udhcpc" "$ROOTFS/usr/share/udhcpc"

# apk's own database and keys. A database with no package manager to read it is inert, but the
# claim is "no package manager in the rootfs" and residue invites the argument.
rm -rf "$ROOTFS/etc/apk" "$ROOTFS/lib/apk" "$ROOTFS/var/cache/apk"

# The app tree, as committed, where PID 1's `python3 -m aobs` will find it. No pip, no virtualenv,
# no wheel: `docs/boot-pipeline.md` is explicit that a build whose selling point is that every
# input is pinned has no dependency resolver in it.
SITE=$(chroot "$ROOTFS" /usr/bin/python3 -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')
mkdir -p "$ROOTFS$SITE"
tar -C "$SRC" --exclude='__pycache__' -cf - aobs | tar -C "$ROOTFS$SITE" -xf -
note "app tree installed at $SITE/aobs"

install -m 0755 "$SRC/build/init" "$ROOTFS/init"
install -m 0644 "$SRC/build/assert_in_rootfs.py" "$ROOTFS/assert_in_rootfs.py"

find "$ROOTFS" | sed "s|^$ROOTFS||" | sort >"$WORK/rootfs-listing.txt"
judge rootfs "$WORK/rootfs-listing.txt"
note "no getty, no login, no inittab, no network utility, no package manager, no test runner"

# The assertions that cannot be pure functions: the app's imports, the live EC backend, and one
# signature in each scheme. See `build/assert_in_rootfs.py` for what this does and does not prove.
chroot "$ROOTFS" /usr/bin/python3 /assert_in_rootfs.py
rm -f "$ROOTFS/assert_in_rootfs.py"

# --- Stage 2. Kernel -----------------------------------------------------------------------------
#
# Vanilla kernel.org source, not Alpine's `linux-lts`: no stock Alpine kernel satisfies the shape,
# its APKBUILD exists to emit a `-modules` package this appliance must not have, and — decisively —
# #10 and #14 promise claims checkable *by reading the config*, which is only true if the config is
# one file in this repository.

stage "Stage 2 — kernel $KERNEL_VERSION"
cd "$WORK"
if [ ! -f "$KERNEL_TARBALL" ]; then
	wget -q -O "$KERNEL_TARBALL" "$KERNEL_URL"
fi
echo "$KERNEL_SHA256  $KERNEL_TARBALL" | sha256sum -c -
note "tarball matches the pinned SHA-256"

tar -xf "$KERNEL_TARBALL"
cd "linux-$KERNEL_VERSION"

# `allnoconfig` with this repository's file as the preset: the base is "everything off", so nothing
# is enabled that `build/kernel.config` did not ask for. That is a stronger statement than a 10,000
# line config a reviewer will not read, and it is not a fragment merged into a *distribution's*
# config, which is the thing `docs/boot-pipeline.md` rules out.
KCONFIG_ALLCONFIG="$SRC/build/kernel.config" make ARCH=x86_64 allnoconfig >/dev/null

# The generated `.config`, not only the checked-in one: a symbol can arrive through a `select` that
# nobody wrote down, so the claims are judged against what Kbuild actually decided.
judge kernel-config .config
note "the generated .config violates nothing either"

make ARCH=x86_64 -j"$(nproc)" bzImage >/dev/null
cp arch/x86/boot/bzImage "$ISOROOT/boot/vmlinuz"
note "vmlinuz: $(du -h "$ISOROOT/boot/vmlinuz" | cut -f1)"

# --- Stage 3. Initramfs --------------------------------------------------------------------------
#
# The whole system is the initramfs (#10). After the kernel and this file load, the boot medium is
# never read again and the user can pull the stick out — which is claim (i), and the thing
# `docs/boot-checklist.md` asks a reviewer to confirm by doing exactly that.

stage "Stage 3 — initramfs"
(cd "$ROOTFS" && find . | cpio --quiet -o -H newc) | zstd -q -19 -T0 -o "$ISOROOT/boot/initramfs.zst"

# The RAM floor is **derived, not asserted** — `docs/boot-pipeline.md` puts the numbers on the
# record and PID 1 refuses below 512 MiB. These two measurements are what keep the figure derived
# as the image changes, which is why they are printed at every build.
ROOTFS_KIB=$(du -sk "$ROOTFS" | cut -f1)
INITRAMFS_KIB=$(du -sk "$ISOROOT/boot/initramfs.zst" | cut -f1)
note "measured rootfs:    $((ROOTFS_KIB / 1024)) MiB unpacked"
note "measured initramfs: $((INITRAMFS_KIB / 1024)) MiB compressed"
note "RAM floor: 512 MiB — rootfs + kernel + Argon2id's 64 MiB transient + heap + camera buffers"

# --- Stage 4. Image ------------------------------------------------------------------------------
#
# A hybrid ISO: `isolinux` for legacy BIOS, `grub-efi` for UEFI, both carrying the fixed cmdline
# already judged in stage 0. `-isohybrid-gpt-basdat` is what makes `dd` to a USB stick work.

stage "Stage 4 — image"
cp "$SRC/build/isolinux.cfg" "$ISOROOT/boot/isolinux/isolinux.cfg"
for module in isolinux.bin ldlinux.c32 libcom32.c32 libutil.c32 mboot.c32; do
	[ -f "/usr/share/syslinux/$module" ] && cp "/usr/share/syslinux/$module" "$ISOROOT/boot/isolinux/"
done

# A standalone GRUB with the config embedded, so the UEFI path needs nothing on the ESP but one
# binary. `grub.cfg`'s `search --file` is what points GRUB at the ISO rather than at the ESP.
mkdir -p "$WORK/efi/EFI/BOOT"
grub-mkstandalone -O x86_64-efi -o "$WORK/efi/EFI/BOOT/BOOTX64.EFI" \
	"boot/grub/grub.cfg=$SRC/build/grub.cfg"

# El Torito needs the UEFI bootloader inside a FAT image, not loose on the ISO9660 tree.
dd if=/dev/zero of="$ISOROOT/boot/efi.img" bs=1M count=8 status=none
mkfs.vfat -n AOBSEFI "$ISOROOT/boot/efi.img" >/dev/null
mmd -i "$ISOROOT/boot/efi.img" ::/EFI ::/EFI/BOOT
mcopy -i "$ISOROOT/boot/efi.img" "$WORK/efi/EFI/BOOT/BOOTX64.EFI" ::/EFI/BOOT/BOOTX64.EFI

xorriso -as mkisofs \
	-o "$ARTIFACT" \
	-V AOBS \
	-isohybrid-mbr /usr/share/syslinux/isohdpfx.bin \
	-c boot/isolinux/boot.cat \
	-b boot/isolinux/isolinux.bin \
	-no-emul-boot -boot-load-size 4 -boot-info-table \
	-eltorito-alt-boot \
	-e boot/efi.img \
	-no-emul-boot -isohybrid-gpt-basdat \
	-quiet \
	"$ISOROOT"

stage "Done"
note "$ARTIFACT — $(du -h "$ARTIFACT" | cut -f1)"
note "sha256: $(sha256sum "$ARTIFACT" | cut -d' ' -f1)"
note "Write it with dd, disable Secure Boot in firmware, and boot the offline machine."
