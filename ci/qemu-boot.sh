#!/bin/sh
# The QEMU harness (05-testing-and-release.md §6.2). Boots the BUILT ISO.
#
# One machine-readable readiness line printed to the console is the assertion; no
# screenshot diffing. That line doubles as the marker whose absence triggers the
# crash-diagnostic path (01-boot-layer.md §9).
#
# Two display rows, because there are two tiers (01-boot-layer.md §7, ADR-0016), and
# `AOBS_QEMU_GPU` picks which one this run exercises:
#
#   ramfb        OVMF + ramfb with no GPU — the **fbdev tier**, the fallback the display
#                story leans on. It was specified as `simpledrm` and could never pass:
#                Debian builds none, so `efifb` serves this machine, and the assertion is
#                that it *draws*, not that it reports a failure. The default, because it
#                is the row that can fail.
#   virtio-gpu   a native KMS driver, i.e. the DRM tier — the machines already covered.
#
# The rows assert the readiness line only. `display=fbdev|drm` is specified for that line
# (§2) and the appliance does not yet report a tier, so neither row can tell the tiers
# apart yet; the field arrives with the panel work and this harness gets its `display=`
# assertion then.
#
#   ci/qemu-boot.sh bitcoin-signer-amd64.iso [memory-MiB] [timeout-seconds]
set -eu

iso="${1:-bitcoin-signer-amd64.iso}"
memory="${2:-4096}"
deadline="${3:-600}"
gpu="${AOBS_QEMU_GPU:-ramfb}"

case "${gpu}" in
    ramfb) display_args="-vga none -device ramfb" ;;
    virtio-gpu) display_args="-vga none -device virtio-gpu-pci" ;;
    *) echo "AOBS_QEMU_GPU must be ramfb or virtio-gpu, not ${gpu}" >&2; exit 1 ;;
esac

[ -f "${iso}" ] || { echo "no such image: ${iso}" >&2; exit 1; }

work="$(mktemp -d)"
log="${work}/serial.log"
trap 'rm -rf "${work}"' EXIT

# UEFI firmware. Two layouts in the wild: Debian/Ubuntu ship a single OVMF.fd usable with
# -bios, while edk2 upstream (and Homebrew's qemu) split it into a read-only code image
# and a writable variable store that has to go on pflash. AOBS_OVMF overrides both.
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
            # The variable store is written during boot, so it is a per-run copy. A
            # firmware that carried state between runs would not be testing a fresh
            # machine, which is the only kind this appliance ever boots on.
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

echo "booting ${iso} with ${memory} MiB on ${gpu}"
echo "firmware: ${firmware_args}"

# A monitor, for diagnostics only — the assertion is still the readiness line, and this
# harness still does no screenshot diffing (05-testing-and-release.md §6.2).
#
# It earns its place on the failure path. The kernel boots `quiet loglevel=3` with no
# `console=` on the command line (§6), so **nothing but the appliance itself ever writes
# to the serial port**. Without a way to look at the panel, a missing readiness line is
# indistinguishable between a slow boot, a kernel panic and a §9 diagnostic block sitting
# on tty0 — and a CI failure that carries no information is a CI failure nobody can act
# on.
monitor_port="${AOBS_QEMU_MONITOR_PORT:-45455}"
screendump="${iso%.iso}-panel-${gpu}.ppm"

# shellcheck disable=SC2086
qemu-system-x86_64 \
    -machine q35 \
    -m "${memory}" \
    ${firmware_args} \
    ${display_args} \
    -cdrom "${iso}" \
    -boot d \
    -display none \
    -serial "file:${log}" \
    -monitor "telnet:127.0.0.1:${monitor_port},server,nowait" \
    -no-reboot \
    -action panic=none &
qemu=$!

# Ask the monitor for whatever is on the panel right now, into $screendump.
capture_panel() {
    if ! kill -0 "${qemu}" 2>/dev/null; then
        echo "note  the machine is no longer running; no panel to capture"
        return
    fi
    if ! command -v nc >/dev/null 2>&1; then
        echo "note  nc is not installed, so the panel was not captured"
        return
    fi
    printf 'screendump %s\nquit\n' "${screendump}" | nc 127.0.0.1 "${monitor_port}" >/dev/null 2>&1 || true
    sleep 2
    if [ -f "${screendump}" ]; then
        echo "note  panel captured to ${screendump}"
    fi
}
# shellcheck disable=SC2064
trap "kill ${qemu} 2>/dev/null || true; rm -f '${log}'" EXIT

waited=0
found=0
died=0
while [ "${waited}" -lt "${deadline}" ]; do
    if grep -q '^AOBS_READY ' "${log}" 2>/dev/null; then
        found=1
        break
    fi
    if ! kill -0 "${qemu}" 2>/dev/null; then
        died=1
        break
    fi
    sleep 2
    waited=$((waited + 2))
    # Under TCG this boot is minutes long and otherwise completely silent, because
    # nothing routes the kernel to the serial port. Say so rather than looking hung.
    if [ $((waited % 60)) -eq 0 ]; then
        echo "  ${waited}s, still booting"
    fi
done

if [ "${found}" -ne 1 ]; then
    capture_panel
fi

kill "${qemu}" 2>/dev/null || true
wait "${qemu}" 2>/dev/null || true

# GRUB draws its menu on the serial terminal, so the log opens with a screenful of cursor
# positioning. Strip the escapes; what matters here is the appliance's own lines.
echo "--- serial console ---"
tr -cd '\11\12\15\40-\176' < "${log}" | sed 's/\[[0-9;]*[A-Za-z]//g' || true
echo "--- end ---"

if [ "${died}" -eq 1 ]; then
    echo >&2
    echo "FAIL  the machine stopped after ${waited}s without a readiness line." >&2
    exit 1
fi

if [ "${found}" -ne 1 ]; then
    echo >&2
    echo "FAIL  no readiness line after ${waited}s." >&2
    echo "      Its absence is the §9 signal. Nothing but the appliance writes to this" >&2
    echo "      serial port, so read ${screendump} for what the panel was showing." >&2
    exit 1
fi

echo "ok    readiness line: $(grep -m1 '^AOBS_READY ' "${log}")"

# The first of the eight measurements 00-overview.md owes. Derived as 1–16 s under
# `random.trust_cpu=off`; this is the number, from a machine rather than from random.c.
# QEMU is not target hardware, so it does not discharge the obligation — it tracks it.
if grep -q '^AOBS_ENTROPY_MS=' "${log}"; then
    echo "note  entropy readiness under QEMU: $(grep -m1 '^AOBS_ENTROPY_MS=' "${log}")"
else
    echo "FAIL  no entropy measurement on the console" >&2
    exit 1
fi
