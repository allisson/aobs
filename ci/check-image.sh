#!/bin/sh
# The mechanical CI check that can only be answered by the artifact
# (05-testing-and-release.md §6.1), plus the manifest that makes §3's claim auditable
# without building (ADR-0012).
#
# This section exists because of one finding: Coldcard's seed generation resolved to
# MicroPython's software PRNG for five years. The source was correct; the linkage was
# wrong. A test that only reads the repository is exactly the test that passed for five
# years.
#
#   ci/check-image.sh bitcoin-signer-amd64.iso
set -eu

iso="${1:-bitcoin-signer-amd64.iso}"
[ -f "${iso}" ] || { echo "no such image: ${iso}" >&2; exit 1; }

work="$(mktemp -d)"
trap 'rm -rf "${work}"' EXIT

fail=0
bad() { echo "FAIL  $1" >&2; fail=1; }
good() { echo "ok    $1"; }

# --- 01-boot-layer.md §3: the stated build check ------------------------------
xorriso -osirrox on -indev "${iso}" -extract /live "${work}/live" >/dev/null 2>&1

initrd="$(ls "${work}"/live/initrd.img-* 2>/dev/null | head -n 1 || true)"
if [ -z "${initrd}" ]; then
    bad "no initrd found in /live on the image"
else
    lsinitramfs "${initrd}" > "${work}/initramfs.txt"

    if grep -qE 'kernel/drivers/net/' "${work}/initramfs.txt"; then
        bad "the initramfs contains drivers/net entries"
        grep -E 'kernel/drivers/net/' "${work}/initramfs.txt" | head -20 >&2
    else
        good "the initramfs contains no drivers/net entries"
    fi

    if grep -qE 'kernel/drivers/bluetooth/|kernel/net/' "${work}/initramfs.txt"; then
        bad "the initramfs contains drivers/bluetooth or net entries"
        grep -E 'kernel/drivers/bluetooth/|kernel/net/' "${work}/initramfs.txt" | head -20 >&2
    else
        good "the initramfs contains no drivers/bluetooth or net entries"
    fi

    # §3 and ADR-0016: amdgpu, xe and radeon are deleted for the same reason the network
    # modules are — firmware-less they take the framebuffer aperture and then fail, and
    # each one kept is a machine that boots to unreportable blackness instead of drawing.
    if grep -qE '/(amdgpu|xe|radeon)\.ko' "${work}/initramfs.txt"; then
        bad "the initramfs contains amdgpu, xe or radeon"
        grep -E '/(amdgpu|xe|radeon)\.ko' "${work}/initramfs.txt" | head -20 >&2
    else
        good "the initramfs contains no amdgpu, xe or radeon"
    fi

    # The initramfs is only half of §3. The squashfs is the other half, and it is the one
    # that persists after boot. It came out of the same extraction above.
    unsquashfs -l "${work}/live/filesystem.squashfs" > "${work}/squashfs.txt" 2>/dev/null

    if grep -qE '/(amdgpu|xe|radeon)\.ko' "${work}/squashfs.txt"; then
        bad "the squashfs still carries amdgpu, xe or radeon"
        grep -E '/(amdgpu|xe|radeon)\.ko' "${work}/squashfs.txt" | head -20 >&2
    else
        good "the squashfs carries no amdgpu, xe or radeon"
    fi

    # ADR-0016 again, from the other direction: no seat daemon anywhere. libseat is what
    # stopped /dev/fb0 from being opened at all, so its presence would mean the image and
    # the crate's `backend-linuxkms-noseat` had drifted apart.
    if grep -qE '/(usr/)?s?bin/seatd$|/libseat\.so' "${work}/squashfs.txt"; then
        bad "the squashfs carries seatd or libseat"
        grep -E '/(usr/)?s?bin/seatd$|/libseat\.so' "${work}/squashfs.txt" | head -20 >&2
    else
        good "the squashfs carries no seatd or libseat"
    fi

    if grep -qE 'lib/modules/[^/]+/kernel/(drivers/net|drivers/bluetooth|net)/' "${work}/squashfs.txt"; then
        bad "the squashfs still carries network driver modules"
        grep -E 'lib/modules/[^/]+/kernel/(drivers/net|drivers/bluetooth|net)/' \
            "${work}/squashfs.txt" | head -20 >&2
    else
        good "the squashfs carries no network driver modules"
    fi

    # §2 control 3, checked against the artifact rather than the package list.
    #
    # Anchored at the executable directories on purpose. A looser match hits
    # /usr/share/terminfo/x/xterm — a terminfo *entry*, which is a description of a
    # terminal and not one — and an empty /run/sshd, which is a tmpfs mount point at boot.
    # Neither is a way in, and a check that fails on them is a check nobody will keep.
    #
    # getty and login are not on this list: util-linux is essential and cannot be removed,
    # so the control there is masking the units (0400-aobs-no-shell-escape.hook.chroot), not
    # deleting the binaries.
    if grep -qE '^[^ ]*/(usr/)?s?bin/(sshd|dropbear|telnetd|xterm|urxvt|st|foot|alacritty)$' \
        "${work}/squashfs.txt"; then
        bad "the squashfs carries an SSH server or a terminal emulator"
        grep -E '^[^ ]*/(usr/)?s?bin/(sshd|dropbear|telnetd|xterm|urxvt|st|foot|alacritty)$' \
            "${work}/squashfs.txt" >&2
    else
        good "the squashfs carries no SSH server and no terminal emulator"
    fi
fi

# --- ADR-0012 / §7.4: the package manifest ships alongside --------------------
manifest="${iso%.iso}.packages"
if [ -f "${manifest}" ]; then
    good "package manifest present: $(wc -l < "${manifest}" | tr -d ' ') packages"
    if grep -qE '^(firmware-|network-manager|udisks2|gvfs|kdump-tools|v4l-utils|libv4l)' "${manifest}"; then
        bad "the package manifest lists a package §3/§4/§7 rules out"
        grep -E '^(firmware-|network-manager|udisks2|gvfs|kdump-tools|v4l-utils|libv4l)' "${manifest}" >&2
    else
        good "the package manifest lists nothing §3/§4/§7 rules out"
    fi
else
    bad "no package manifest beside the image (${manifest})"
fi

exit "${fail}"
