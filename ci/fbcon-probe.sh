#!/bin/sh
# The `fbcon` regression row (05-testing-and-release.md §6.2). Boots the BUILT ISO on
# OVMF + ramfb with no GPU — the fbdev tier — and asserts that the console detach still
# holds.
#
# This is [#52](https://github.com/allisson/aobs/issues/52)'s probe as a standing row.
# What it defends: on the fbdev tier there is one framebuffer and no owner, so Slint and
# `fbcon` write the same memory, and #48 photographed two `pr_emerg` lines sitting
# permanently on top of the UI. The screen they can deface is the transaction review
# screen. `console-detach` unbinds `fbcon` while the app draws; this asserts the unbind is
# still doing that on the image we actually built.
#
# Five captures on one machine:
#
#   panel-0-console-attached   NMI injected during the entropy wait, i.e. before the
#                              detach. The console is attached here, so this capture is
#                              what shows the injection reaching *this* framebuffer. It
#                              needs eyes, not a comparison — it is the control that makes
#                              the three below readable, and #52 read it the same way.
#   panel-1-ready              after the appliance has drawn and the detach has run. If
#                              unbinding `fbcon` cleared the framebuffer, this is where it
#                              shows: Slint will not repaint it (#48).
#   panel-2-after-nmi          NMI with the console detached.
#   panel-3-after-nmi          a second, because #51 asserted on three captures.
#   panel-4-after-stop         during the stop Ctrl-Alt-Del triggers, i.e. around when
#                              `ExecStopPost` runs `console-attach`. Evidence, not an
#                              assertion — see the comment above that step for why the
#                              reattach stays unproven.
#
# The assertion is `panel-1 == panel-2 == panel-3`, byte for byte, on a boot where the
# appliance started **exactly once**. The start count is not a nicety: the first cycle of
# this probe in #52 compared captures of a service that was restarting in a loop, and every
# comparison in it was meaningless. A looping service must not pass for a clean run.
#
#   ci/fbcon-probe.sh bitcoin-signer-amd64.iso [memory-MiB] [timeout-seconds]
set -eu

iso="${1:-bitcoin-signer-amd64.iso}"
memory="${2:-4096}"
deadline="${3:-900}"

[ -f "${iso}" ] || { echo "no such image: ${iso}" >&2; exit 1; }

# Beside the image, like ci/qemu-boot.sh's diagnostic capture: on a failure these are the
# whole of the evidence, and a temporary directory would take them with it.
out="${iso%.iso}-fbcon"
rm -f "${out}"-panel-*.ppm

work="$(mktemp -d)"
log="${work}/serial.log"

# UEFI firmware, from the one list every row shares (ci/ovmf.sh).
. "$(dirname "$0")/ovmf.sh"

command -v nc >/dev/null 2>&1 || { echo "nc is required: it drives the QEMU monitor." >&2; exit 1; }

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

# One monitor command, connection closed after it. Deliberately not `quit` — every capture
# here happens on a machine that has to keep running.
monitor() {
    printf '%s\n' "$1" | nc -w 2 127.0.0.1 "${monitor_port}" >/dev/null 2>&1 || true
}

alive() { kill -0 "${qemu}" 2>/dev/null; }

# Wait for a marker on the serial log. The appliance is the only thing that writes there
# (01-boot-layer.md §6 puts no `console=` on the cmdline), so every line is ours.
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
    monitor "screendump ${out}-$1.ppm"
    sleep 2
    if [ -f "${out}-$1.ppm" ]; then
        echo "  captured $(basename "${out}")-$1.ppm"
    else
        echo "  NO CAPTURE for $1"
    fi
}

# --- the control: an NMI with the console still attached -------------------------------
# Injected during the entropy wait — after the app has started and before it has a window,
# so the console still owns the panel.
await 'AOBS_ENTROPY_WAIT_BEGIN' "${deadline}"
monitor 'nmi'
sleep 2
capture panel-0-console-attached

# --- the assertion: three captures with the console detached ---------------------------
#
# `console-detach` writes nothing to stdout or stderr (§2: a status line from it would land
# on the panel the app has already painted, and Slint does not repaint it away), so there is
# no marker for the unbind and this waits it out instead. The window is bounded and known:
# the readiness datagram is a 3 s timer inside the app, and `ExecStartPost` follows it.
await '^AOBS_READY ' "${deadline}"
sleep 20
capture panel-1-ready
monitor 'nmi'
sleep 4
capture panel-2-after-nmi
monitor 'nmi'
sleep 4
capture panel-3-after-nmi

# --- the other half: `console-attach` gives the console back ---------------------------
#
# `ExecStopPost=+/usr/lib/aobs/console-attach` rebinds `fbcon` when the appliance stops, so
# §9 has a channel again. This is the one stop the harness can ask for, and it exercises
# that whole path.
#
# Ctrl-Alt-Del and not the ACPI power button, and it stays that way now that #69 has built
# the confirm-then-exit path. Two different stops are worth having: the button ends in
# `SuccessAction=poweroff`, which is a machine that is *gone* — there is no window in which to
# ask for a capture — whereas Ctrl-Alt-Del goes to PID 1 from the kernel with nothing in
# between and `-no-reboot` turns the reboot into an exit, so `ExecStopPost` runs on a machine
# that is still there to be photographed. The button's own row is ci/power-button-probe.sh.
#
# **What this asserts is that the stop path completes, not that the console came back.**
# The panel does not change during the stop, and it cannot: `quiet` on the cmdline
# (01-boot-layer.md §6) makes systemd print no status, so nothing is written to the
# console for a rebound `fbcon` to draw, and an unchanged panel is equally consistent with
# a reattach that worked. #52 recorded the reattach as *not established* for the same
# reason and covered §9's case structurally instead — `ExecStartPost` runs only after a
# successful start, so a startup failure never detaches at all. It is still not
# established. What is asserted here is that nothing in the stop path hangs, and
# `console-attach` runs in that path.
monitor 'sendkey ctrl-alt-delete'
capture panel-4-after-stop

waited=0
while [ "${waited}" -lt 120 ] && alive; do
    sleep 2
    waited=$((waited + 2))
done
if alive; then
    stopped=0
    echo "note  the machine was still running ${waited}s after Ctrl-Alt-Del"
else
    stopped=1
    echo "  ${waited}s  stopped"
fi

kill "${qemu}" 2>/dev/null || true
wait "${qemu}" 2>/dev/null || true

echo "--- serial console ---"
tr -cd '\11\12\15\40-\176' < "${log}" | sed 's/\[[0-9;]*[A-Za-z]//g' || true
echo "--- end ---"

echo "--- captures ---"
for f in "${out}"-panel-*.ppm; do
    [ -f "${f}" ] || continue
    if command -v sha256sum >/dev/null 2>&1; then
        echo "$(sha256sum "${f}" | cut -c1-16)  $(basename "${f}")"
    else
        echo "$(shasum -a 256 "${f}" | cut -c1-16)  $(basename "${f}")"
    fi
done

# The appliance starts once per boot, or this is not a result. `Type=notify` and the two
# `+`-prefixed console scripts are also asserted here and nowhere else: a unit that never
# received READY=1, or an ExecStartPost that failed, restarts — and restarting is what this
# count refuses.
# `|| true`: grep -c prints its 0 and *then* exits non-zero, so `|| echo 0` appended a
# second line and reported "0 0" starts.
starts="$(grep -c '^AOBS_READY ' "${log}" 2>/dev/null || true)"
if [ "${starts}" != "1" ]; then
    echo "FAIL  the appliance started ${starts} times — it did not come up and stay up," >&2
    echo "      so the captures above are of a restarting machine, not of an assertion." >&2
    exit 1
fi

for f in panel-1-ready panel-2-after-nmi panel-3-after-nmi; do
    [ -f "${out}-${f}.ppm" ] || { echo "FAIL  ${f} was never captured." >&2; exit 1; }
done

if cmp -s "${out}-panel-1-ready.ppm" "${out}-panel-2-after-nmi.ppm" &&
   cmp -s "${out}-panel-1-ready.ppm" "${out}-panel-3-after-nmi.ppm"; then
    echo "PASS  the three detached captures are byte-identical: the NMI left no mark."
else
    echo "FAIL  the detached captures differ: the overwrite survived the detach." >&2
    exit 1
fi

if [ "${stopped}" != "1" ]; then
    echo "FAIL  the machine did not stop after Ctrl-Alt-Del: something in the stop path" >&2
    echo "      hung, and console-attach runs in that path." >&2
    exit 1
fi

echo "PASS  the stop path completed and the machine went down; console-attach ran in it."
echo "note  whether fbcon came back is still unproven — see the comment above the stop."
