#!/bin/sh
#
# `bitcoin-signer-amd64.iso`, in four stages, from a container.
#
#     docker run --rm --platform=linux/amd64 -v "$PWD:/src" -w /src \
#         alpine:3.24 sh build/fetch-inputs.sh          # once, or when a pin changes
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
# **Every byte comes from `build/inputs/`, and nothing here touches a network.** There is no second
# build path: `build/fetch-inputs.sh` populates that directory — from Alpine's CDN today, from the
# unpacked release asset in 2030 — and the divergence between the two is confined to *fetching*.
#
# **The output is byte-identical on any host.** `docs/reproducible-build.md` states the claim
# numbered and checkable, lists the six divergence sources that were fixed, and names the CI guard
# that builds twice under hostile variation and fails on any differing byte. Release engineering is
# `docs/release.md`. Secure Boot remains out of scope: the image is unsigned and stays unsigned.

set -eu

# What a deterministic build needs from its environment, forced **here** and not only in
# `Dockerfile.iso`. The guard runs the second build with `-e TZ=`, `-e LC_ALL=` and a different
# umask precisely to prove the build ignores them, and `docker run -e` overrides an `ENV` — so the
# Dockerfile holds the defaults and this holds the enforcement.
export LC_ALL=C
export LANG=C
export TZ=UTC
umask 022

SRC=${SRC:-/src}
OUT=${OUT:-/out}
WORK=${WORK:-/build}
INPUTS=$SRC/build/inputs
ROOTFS=$WORK/rootfs
ISOROOT=$WORK/isoroot
ARTIFACT=$OUT/bitcoin-signer-amd64.iso

#: Fixed constants, never `nproc`. `docs/reproducible-build.md` claim 1 puts CPU count and host
#: architecture inside the contract, and this is the price: `zstd`'s output genuinely varies with the
#: thread count, `make`'s does not, and both are pinned anyway — because "nothing in the build reads
#: the machine" is checkable and "only the one that matters" is a judgement made afresh every time.
#: `build/verify.py`'s `check_pinned_parallelism` is what keeps it true.
MAKE_JOBS=4
ZSTD_THREADS=1

stage() { printf '\n=== %s\n' "$1"; }
note() { printf '    %s\n' "$1"; }
rung() { printf '    sha256 %-18s %s\n' "$1" "$(sha256sum "$2" | cut -d' ' -f1)"; }

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
# The kernel config, both bootloader command lines, the vendored tree and the input set are all
# readable right now. Judging them first means a config edit that breaks a published claim costs
# seconds rather than a full kernel compile.

stage "Stage 0 — the checked-in inputs"
judge kernel-config "$SRC/build/kernel.config"
judge cmdline bios "$SRC/build/isolinux.cfg"
judge cmdline uefi "$SRC/build/grub.cfg"
judge vendored-tree "$SRC/aobs/core/vendor"
judge toolchain-list "$SRC/build/toolchain-versions.txt"
judge pinned-parallelism "$SRC/build/mkiso.sh" "$SRC/build/Dockerfile.iso" \
	"$SRC/build/fetch-inputs.sh"
note "kernel.config, cmdlines, vendored tree, toolchain list, pinned parallelism: no violations"

# `build/inputs/` against `build/inputs.sha256`, on hash **and on set equality**. The enforcement is
# here rather than in the fetcher because a hand-populated directory — which is exactly what the
# 2030 rebuild path is — would walk straight past a check that lived only there.
judge inputs "$INPUTS" "$SRC/build/inputs.sha256"
note "$(grep -c . "$SRC/build/inputs.sha256") archived inputs: every hash matches, no extra file"

#: The commit date of HEAD, and **derived here rather than passed in**. Not the tag date — an
#: untagged working build has none, and a fallback is a second contract nobody tests. Not a constant
#: — a commit date makes the ISO's internal timestamps an assertion about *which commit built it*.
#:
#: **Consequence, written down because it will surprise someone: a rebase that rewrites commit dates
#: changes the ISO hash.** That is correct. The hash is a claim about a commit, and a rewritten
#: commit is a different commit.
SOURCE_DATE_EPOCH=$(git -C "$SRC" -c safe.directory="$SRC" log -1 --format=%ct)
export SOURCE_DATE_EPOCH
note "SOURCE_DATE_EPOCH=$SOURCE_DATE_EPOCH (the commit date of HEAD)"

rm -rf "$WORK"
mkdir -p "$ROOTFS" "$ISOROOT/boot/isolinux" "$OUT"

# The local repository, written here rather than committed: it is the absolute path of the bind
# mount, so it is a fact about this container and not about the repository.
printf '%s\n' "$INPUTS/apks/main" "$INPUTS/apks/community" >"$WORK/repositories"

# --- Stage 1. Userland ---------------------------------------------------------------------------
#
# Alpine's role is the one it is genuinely good at: a pinned, checksummed source of a musl
# userland. It supplies packages, not a boot process — `mkimage.sh`, the aports ISO profiles and
# `mkinitfs` are all foreclosed by #10, since their purpose is producing and mounting a modloop
# squashfs of modules an all-built-in kernel does not have.
#
# The **appliance group only** of `build/apk-versions.txt`. The harness group — pytest, hypothesis,
# gnupg, git and `py3-pip` — is what the test container installs and what must never reach the image.

stage "Stage 1 — userland"
PACKAGES=$(python3 "$SRC/build/gather.py" pins-of-group appliance "$SRC/build/apk-versions.txt")
note "installing $(echo "$PACKAGES" | wc -w) pinned packages from build/inputs/"

mkdir -p "$ROOTFS/etc/apk"
cp "$WORK/repositories" "$ROOTFS/etc/apk/repositories"
# shellcheck disable=SC2086
apk --root "$ROOTFS" --initdb --no-cache \
	--repositories-file "$WORK/repositories" \
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

# `/etc/aobs-release`: what the appliance says about itself on the first screen (#61). A stage-1
# output and a file a human can open, so that the stage-3 assertion below has something to be about.
# The manifest's `release` and `git-commit` are generated from this same file, which is what leaves
# the image and the manifest nothing to disagree over.
note "embedded release line: $(python3 "$SRC/build/gather.py" write-release "$SRC" "$ROOTFS/etc/aobs-release")"

find "$ROOTFS" | sed "s|^$ROOTFS||" | sort >"$WORK/rootfs-listing.txt"
judge rootfs "$WORK/rootfs-listing.txt"
note "no getty, no login, no inittab, no network utility, no package manager, no test runner"

# The assertions that cannot be pure functions: the app's imports, the live EC backend, and one
# signature in each scheme. See `build/assert_in_rootfs.py` for what this does and does not prove.
chroot "$ROOTFS" /usr/bin/python3 /assert_in_rootfs.py
rm -f "$ROOTFS/assert_in_rootfs.py"

# --- Stage 2. Kernel -----------------------------------------------------------------------------
#
# Vanilla kernel source, not Alpine's `linux-lts`: no stock Alpine kernel satisfies the shape,
# its APKBUILD exists to emit a `-modules` package this appliance must not have, and — decisively —
# #10 and #14 promise claims checkable *by reading the config*, which is only true if the config is
# one file in this repository.
#
# The tarball comes from `build/inputs/`, whose every hash was checked in stage 0 against the list in
# git. Its version is read off the filename rather than pinned a second time here: two pins for one
# fact is one pin that can be wrong.

KERNEL_TARBALL=$(cd "$INPUTS" && ls linux-*.tar.xz)
KERNEL_VERSION=${KERNEL_TARBALL#linux-}
KERNEL_VERSION=${KERNEL_VERSION%.tar.xz}

stage "Stage 2 — kernel $KERNEL_VERSION"
cd "$WORK"
tar -xf "$INPUTS/$KERNEL_TARBALL"
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

make ARCH=x86_64 -j"$MAKE_JOBS" bzImage >/dev/null
cp arch/x86/boot/bzImage "$ISOROOT/boot/vmlinuz"
note "vmlinuz: $(du -h "$ISOROOT/boot/vmlinuz" | cut -f1)"

# --- Stage 3. Initramfs --------------------------------------------------------------------------
#
# The whole system is the initramfs (#10). After the kernel and this file load, the boot medium is
# never read again and the user can pull the stick out — which is claim (i), and the thing
# `docs/boot-checklist.md` asks a reviewer to confirm by doing exactly that.

stage "Stage 3 — initramfs"

# **Before `cpio`, and stage 3 rather than stage 4** (#61): after `cpio` the value is inside an
# archive and the failure message stops being about a file a human can open. The assertion binds the
# embedded version to `git describe --exact-match --tags` and refuses a dirty tree claiming a
# version — and it is *skipped, not faked,* for a development build.
judge embedded-release "$SRC" "$ROOTFS/etc/aobs-release"
note "the embedded release line agrees with the tag and the commit"

# Two of `docs/reproducible-build.md`'s six divergence sources, both here. `find | cpio` with no sort
# leaks directory order into the archive; cpio member mtimes come from the filesystem. So every
# member's mtime is set to `SOURCE_DATE_EPOCH` — GNU `touch`, because busybox's does not accept the
# `@` form and a `touch` that silently does nothing is a defect that passes every test until two
# builders compare hashes — and the listing is sorted under `LC_ALL=C`.
#
# `--reproducible` zeroes the device and inode numbers cpio would otherwise copy off the filesystem.
find "$ROOTFS" -exec touch -h -d "@$SOURCE_DATE_EPOCH" {} +
(cd "$ROOTFS" && find . -print0 | LC_ALL=C sort -z |
	cpio --null --quiet --reproducible -o -H newc) |
	zstd -q -19 -T"$ZSTD_THREADS" -o "$ISOROOT/boot/initramfs.zst"

# The first rung of the failure ladder, and it is a *tree manifest* rather than a hash of the
# archive: when two builds diverge, the question is which file differs, and a manifest of mode, owner
# and content hash per path answers it where a single number cannot.
python3 "$SRC/build/gather.py" tree-manifest "$ROOTFS" >"$WORK/rootfs-manifest.txt"

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
#
# Divergence source three: `grub-mkstandalone` builds the embedded memdisk as a tar whose member
# mtimes come from the source file. So the config is staged and touched rather than passed from the
# repository, where its mtime is whatever `git checkout` happened to set.
mkdir -p "$WORK/efi/EFI/BOOT" "$WORK/grub/boot/grub"
cp "$SRC/build/grub.cfg" "$WORK/grub/boot/grub/grub.cfg"
touch -d "@$SOURCE_DATE_EPOCH" "$WORK/grub/boot/grub/grub.cfg"
grub-mkstandalone -O x86_64-efi -o "$WORK/efi/EFI/BOOT/BOOTX64.EFI" \
	"boot/grub/grub.cfg=$WORK/grub/boot/grub/grub.cfg"

# El Torito needs the UEFI bootloader inside a FAT image, not loose on the ISO9660 tree.
#
# Divergence source four: `mkfs.vfat` takes the volume ID from the clock unless `-i` names one, and
# mtools writes each file's mtime into the FAT directory entry — in *local* time, which is why `TZ`
# is forced to UTC at the top of this script rather than left to the environment.
EFI_VOLUME_ID=$(printf '%08X' $((SOURCE_DATE_EPOCH % 4294967296)))
dd if=/dev/zero of="$ISOROOT/boot/efi.img" bs=1M count=8 status=none
mkfs.vfat -n AOBSEFI -i "$EFI_VOLUME_ID" "$ISOROOT/boot/efi.img" >/dev/null
touch -d "@$SOURCE_DATE_EPOCH" "$WORK/efi/EFI/BOOT/BOOTX64.EFI"
mmd -i "$ISOROOT/boot/efi.img" ::/EFI ::/EFI/BOOT
mcopy -i "$ISOROOT/boot/efi.img" "$WORK/efi/EFI/BOOT/BOOTX64.EFI" ::/EFI/BOOT/BOOTX64.EFI

# Divergence source five: `xorriso` writes ISO9660 creation, modification, expiration and effective
# timestamps from the clock, and derives the volume UUID from them. `--modification-date` sets all of
# them at once, which is the documented reproducible-builds form. Every file's own date comes from
# its mtime, and every mtime in the tree was set above.
find "$ISOROOT" -exec touch -h -d "@$SOURCE_DATE_EPOCH" {} +
ISO_DATE=$(date -u -d "@$SOURCE_DATE_EPOCH" +%Y%m%d%H%M%S00)

xorriso -as mkisofs \
	-o "$ARTIFACT" \
	-V AOBS \
	--modification-date="$ISO_DATE" \
	-isohybrid-mbr /usr/share/syslinux/isohdpfx.bin \
	-c boot/isolinux/boot.cat \
	-b boot/isolinux/isolinux.bin \
	-no-emul-boot -boot-load-size 4 -boot-info-table \
	-eltorito-alt-boot \
	-e boot/efi.img \
	-no-emul-boot -isohybrid-gpt-basdat \
	-quiet \
	"$ISOROOT"

# --- The failure ladder --------------------------------------------------------------------------
#
# `docs/reproducible-build.md` claim 8: a rebuild that diverges says *where*. The hashes are printed
# here, from the build that already produced every intermediate, rather than re-derived by a CI
# script — a ladder that lives in the CI job is a ladder that goes stale the day the build changes.

stage "Done"
rung "rootfs tree" "$WORK/rootfs-manifest.txt"
rung bzImage "$ISOROOT/boot/vmlinuz"
rung initramfs.zst "$ISOROOT/boot/initramfs.zst"
rung efi.img "$ISOROOT/boot/efi.img"
rung iso "$ARTIFACT"
note "$ARTIFACT — $(du -h "$ARTIFACT" | cut -f1)"
note "Write it with dd, disable Secure Boot in firmware, and boot the offline machine."
