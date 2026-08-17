#!/bin/sh
# PROTOTYPE (#52) — does detaching fbcon while the app draws stop the overwrite?
#
# #48's probe, with a control added. Boots the built ISO on OVMF + ramfb with no GPU (the
# fbdev tier), and takes four panel captures on one machine:
#
#   panel-0-console-attached   NMI injected while the app is still waiting on entropy,
#                              i.e. before the detach. The console is attached here, so
#                              kernel text on this capture is what proves the injection
#                              works and that fbcon writes to *this* framebuffer.
#   panel-1-ready              after AOBS_PROTO_DETACH_OK: the appliance, drawn, console
#                              detached. If unbinding fbcon clears the framebuffer, this
#                              is where it shows — Slint will not repaint it (#48).
#   panel-2-after-nmi          NMI with the console detached.
#   panel-3-after-nmi          a second NMI, because #51 asserted on three captures.
#
# The assertion is `panel-1 == panel-2 == panel-3`, byte for byte, which is the form #51
# used on the DRM tier.
#
#   ci/proto-52-probe.sh [iso] [memory-MiB] [timeout-seconds]
set -eu

iso="${1:-bitcoin-signer-amd64.iso}"
memory="${2:-4096}"
deadline="${3:-900}"

[ -f "${iso}" ] || { echo "no such image: ${iso}" >&2; exit 1; }

out="$(cd "$(dirname "$0")/.." && pwd)/docs/prototypes/52"
mkdir -p "${out}"

work="$(mktemp -d)"
log="${work}/serial.log"

# Same firmware discovery as ci/qemu-boot.sh; AOBS_OVMF overrides.
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
            cp "${vars}" "${work}/OVMF_VARS.fd"
            chmod u+w "${work}/OVMF_VARS.fd"
            firmware_args="-drive if=pflash,format=raw,unit=0,readonly=on,file=${code}"
            firmware_args="${firmware_args} -drive if=pflash,format=raw,unit=1,file=${work}/OVMF_VARS.fd"
            break
        fi
    done
fi
[ -n "${firmware_args}" ] || { echo "no UEFI firmware found; set AOBS_OVMF." >&2; exit 1; }

monitor_port="${AOBS_QEMU_MONITOR_PORT:-45456}"

echo "booting ${iso} with ${memory} MiB, ramfb and no GPU"

# shellcheck disable=SC2086
qemu-system-x86_64 \
    -machine q35 \
    -m "${memory}" \
    ${firmware_args} \
    -vga none -device ramfb \
    -cdrom "${iso}" \
    -boot d \
    -display none \
    -serial "file:${log}" \
    -monitor "telnet:127.0.0.1:${monitor_port},server,nowait" \
    -no-reboot \
    -action panic=none &
qemu=$!
# shellcheck disable=SC2064
trap "kill ${qemu} 2>/dev/null || true; rm -rf '${work}'" EXIT

# One monitor command, connection closed after it. Deliberately not `quit` — every
# capture here happens on a machine that has to keep running.
monitor() {
    printf '%s\n' "$1" | nc -w 2 127.0.0.1 "${monitor_port}" >/dev/null 2>&1 || true
}

alive() { kill -0 "${qemu}" 2>/dev/null; }

# Wait for a marker on the serial log. The appliance is the only thing that writes there
# (§6 puts no `console=` on the cmdline), so every line is ours.
await() {
    marker="$1"
    limit="$2"
    waited=0
    while [ "${waited}" -lt "${limit}" ]; do
        if grep -qE "${marker}" "${log}" 2>/dev/null; then
            echo "  ${waited}s  ${marker}"
            return 0
        fi
        alive || { echo "FAIL  the machine stopped while waiting for ${marker}" >&2; return 1; }
        sleep 2
        waited=$((waited + 2))
        [ $((waited % 60)) -eq 0 ] && echo "  ${waited}s, still waiting for ${marker}"
    done
    echo "FAIL  no ${marker} after ${limit}s" >&2
    return 1
}

capture() {
    monitor "screendump ${out}/$1.ppm"
    sleep 2
    [ -f "${out}/$1.ppm" ] && echo "  captured $1.ppm" || echo "  NO CAPTURE for $1"
}

# --- the control: an NMI with the console still attached -------------------------------
# Injected during the entropy wait, which #48 measured at 7.4 s — after the app has
# started and before it has a window, so the console still owns the panel.
await 'AOBS_ENTROPY_WAIT_BEGIN' "${deadline}"
monitor 'nmi'
sleep 2
capture panel-0-console-attached

# --- the assertion: three captures with the console detached ---------------------------
await 'AOBS_PROTO_DETACH_(OK|FAIL|NOFBCON)' "${deadline}"
sleep 2
capture panel-1-ready
monitor 'nmi'
sleep 4
capture panel-2-after-nmi
monitor 'nmi'
sleep 4
capture panel-3-after-nmi

kill "${qemu}" 2>/dev/null || true
wait "${qemu}" 2>/dev/null || true

echo "--- serial console ---"
tr -cd '\11\12\15\40-\176' < "${log}" | sed 's/\[[0-9;]*[A-Za-z]//g' || true
echo "--- end ---"

echo "--- captures ---"
for f in "${out}"/panel-*.ppm; do
    [ -f "${f}" ] || continue
    echo "$(shasum -a 256 "${f}" | cut -c1-16)  $(basename "${f}")"
done

# The first cycle of this probe compared captures taken while the service was restarting
# in a loop, which makes every comparison below meaningless. A looping service must never
# again pass for a clean run: the appliance starts once per boot or this is not a result.
starts="$(grep -c '^AOBS_READY ' "${log}" 2>/dev/null || echo 0)"
if [ "${starts}" != "1" ]; then
    echo "FAIL  the appliance started ${starts} times — it did not survive the detach," >&2
    echo "      so the captures below are of a restarting machine, not of an assertion." >&2
    exit 1
fi

if cmp -s "${out}/panel-1-ready.ppm" "${out}/panel-2-after-nmi.ppm" &&
   cmp -s "${out}/panel-1-ready.ppm" "${out}/panel-3-after-nmi.ppm"; then
    echo "PASS  the three detached captures are byte-identical: the NMI left no mark."
else
    echo "FAIL  the detached captures differ: the overwrite survived the detach." >&2
    exit 1
fi
