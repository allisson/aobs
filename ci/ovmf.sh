# UEFI firmware discovery, shared by every row that boots the ISO.
#
# Sourced, not run: it sets `firmware_args` for the caller's qemu invocation and needs
# `${work}` to already be a writable scratch directory. Extracted when the third harness
# (ci/power-button-probe.sh) would have been the third verbatim copy of the same five paths —
# a list that has to be identical everywhere or one row silently boots different firmware
# than the others.
#
# Two layouts in the wild: Debian/Ubuntu ship a single OVMF.fd usable with -bios, while edk2
# upstream (and Homebrew's qemu) split it into a read-only code image and a writable variable
# store that has to go on pflash. AOBS_OVMF overrides both.

firmware_args=""
if [ -n "${AOBS_OVMF:-}" ]; then
    firmware_args="-bios ${AOBS_OVMF}"
else
    for pair in \
        "/usr/share/OVMF/OVMF_CODE_4M.fd:/usr/share/OVMF/OVMF_VARS_4M.fd" \
        "/usr/share/OVMF/OVMF_CODE.fd:/usr/share/OVMF/OVMF_VARS.fd" \
        "/usr/share/edk2/ovmf/OVMF_CODE.fd:/usr/share/edk2/ovmf/OVMF_VARS.fd" \
        "/opt/homebrew/share/qemu/edk2-x86_64-code.fd:/opt/homebrew/share/qemu/edk2-i386-vars.fd" \
        "/usr/local/share/qemu/edk2-x86_64-code.fd:/usr/local/share/qemu/edk2-i386-vars.fd"
    do
        code="${pair%%:*}"
        vars="${pair##*:}"
        if [ -f "${code}" ] && [ -f "${vars}" ]; then
            # The variable store is written during boot, so it is a per-run copy. A firmware
            # that carried state between runs would not be testing a fresh machine, which is
            # the only kind this appliance ever boots on.
            cp "${vars}" "${work}/OVMF_VARS.fd"
            chmod u+w "${work}/OVMF_VARS.fd"
            firmware_args="-drive if=pflash,format=raw,unit=0,readonly=on,file=${code}"
            firmware_args="${firmware_args} -drive if=pflash,format=raw,unit=1,file=${work}/OVMF_VARS.fd"
            break
        fi
    done
fi

if [ -z "${firmware_args}" ]; then
    for candidate in /usr/share/ovmf/OVMF.fd /usr/share/qemu/OVMF.fd; do
        [ -f "${candidate}" ] && { firmware_args="-bios ${candidate}"; break; }
    done
fi

if [ -z "${firmware_args}" ]; then
    echo "no UEFI firmware found. Install the ovmf package, or set AOBS_OVMF." >&2
    exit 1
fi
