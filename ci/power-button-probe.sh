#!/bin/sh
# The power-button row (05-testing-and-release.md §6.2). Boots the BUILT ISO on OVMF + ramfb
# with no GPU and asserts that the button reaches the app, that it lands on §13's confirm
# rather than on a shutdown, and that the exit-status contract fires end to end.
#
# The row existed in the spec with a caveat — *this row waits for a shutdown to assert on* —
# because nothing in the crate exited 42. [#89](https://github.com/allisson/aobs/issues/89)
# had measured the first half with a throwaway build (`Power Button` / `KEY_POWER` reaching an
# unprivileged app) and ADR-0017 recorded the second half as **not established**. This is that
# half, and #69 is what made it assertable.
#
# What it drives, in order, and what each step is for:
#
#   1  the machine is up and drawing            AOBS_READY on the serial log
#   2  `sendkey ret`, then still running        **the control.** Enter is the key that
#                                              confirms on §13's screen, so a run where Enter
#                                              alone ends the session proves nothing about the
#                                              button. This is also what a silent step 4 would
#                                              otherwise be indistinguishable from.
#   3  `sendkey esc`                            back to the start menu, so step 5 confirms
#                                              from a known cursor (a screen change resets it
#                                              to the first row, which is *shut down*).
#   4  `system_powerdown`, then still running    the ACPI press reaches the app and lands on
#                                              the confirm. **Still running is the assertion**:
#                                              §13 rules the button is not a second, faster
#                                              path to shutdown.
#   5  the panel changed across step 4          that the app *reacted* — the confirm is a
#                                              screen, and a screen is a repaint. Two captures
#                                              from the same machine compared to each other,
#                                              which is the technique the fbcon row already
#                                              uses; §6.2's ban is on diffing against a golden
#                                              image, and there is none here.
#   6  `sendkey ret`, then the machine is down   `exit 42` → `SuccessExitStatus=42` →
#                                              `RestartPreventExitStatus=42` → the unit reaches
#                                              inactive → `SuccessAction=poweroff`. Every one of
#                                              those four has to hold for the machine to go
#                                              down, and none of them is observable on its own.
#
# One thing is deliberately *not* asserted: that the appliance started exactly once. It cannot
# be, because step 6's whole point is that the process ends — and it ends having asked to stay
# dead, so a restart would show up as the machine still running, which step 6 already fails on.
#
#   ci/power-button-probe.sh bitcoin-signer-amd64.iso [memory-MiB] [timeout-seconds]
set -eu

iso="${1:-bitcoin-signer-amd64.iso}"
memory="${2:-4096}"
deadline="${3:-900}"

[ -f "${iso}" ] || { echo "no such image: ${iso}" >&2; exit 1; }

# Beside the image, like the fbcon row's captures: on a failure these are the whole of the
# evidence, and a temporary directory would take them with it.
out="${iso%.iso}-power"
rm -f "${out}"-panel-*.ppm

work="$(mktemp -d)"
log="${work}/serial.log"

# UEFI firmware, from the one list every row shares (ci/ovmf.sh).
. "$(dirname "$0")/ovmf.sh"

command -v nc >/dev/null 2>&1 || { echo "nc is required: it drives the QEMU monitor." >&2; exit 1; }

# A third port, so this row can run beside the others without them fighting over a monitor.
monitor_port="${AOBS_QEMU_MONITOR_PORT:-45457}"

echo "booting ${iso} with ${memory} MiB, ramfb and no GPU"

# `-no-shutdown` is deliberately absent: the machine going down is the assertion, so QEMU has
# to be allowed to exit when the guest powers off.
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

monitor() {
    printf '%s\n' "$1" | nc -w 2 127.0.0.1 "${monitor_port}" >/dev/null 2>&1 || true
}

alive() { kill -0 "${qemu}" 2>/dev/null; }

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

# Whether the machine went down within the window. Used twice with opposite expectations,
# which is the whole shape of this probe.
settled() {
    waited=0
    while [ "${waited}" -lt "$1" ] && alive; do
        sleep 2
        waited=$((waited + 2))
    done
    ! alive
}

# --- 1. up and drawing -----------------------------------------------------------------
#
# The 20 s is the readiness datagram's own timer plus `ExecStartPost`, the same wait the fbcon
# row makes for the same reason: nothing marks the console detach on the console.
await '^AOBS_READY ' "${deadline}"
sleep 20

# --- 2. the control: Enter, with no button press ----------------------------------------
#
# Enter on the start menu chooses its first row, which in this build is a screen that says it
# is not built yet. What matters is that the machine is still here afterwards.
monitor 'sendkey ret'
if settled 20; then
    echo "FAIL  Enter alone took the machine down. Nothing after this proves anything about" >&2
    echo "      the power button (04-screens.md §13: one press confirms, on a confirm screen)." >&2
    exit 1
fi
echo "ok    Enter alone did not end the session"

# --- 3. back to a known cursor ----------------------------------------------------------
monitor 'sendkey esc'
sleep 4
capture panel-0-start

# --- 4. the button ----------------------------------------------------------------------
#
# `system_powerdown` is an ACPI power button press. On this image nothing but the app can
# answer it: no D-Bus, so no `systemd-logind` (ADR-0017), which is what made this same command
# sit for 120 s with no reaction in #65.
monitor 'system_powerdown'
if settled 30; then
    echo "FAIL  the button took the machine down on its own. It must land on §13's confirm —" >&2
    echo "      it is not a second, faster path to shutdown, and an accidental knock has to" >&2
    echo "      cost a press to undo rather than a session." >&2
    exit 1
fi
echo "ok    the button did not shut the machine down by itself"
capture panel-1-confirm

# --- 5. the app reacted -----------------------------------------------------------------
for f in panel-0-start panel-1-confirm; do
    [ -f "${out}-${f}.ppm" ] || { echo "FAIL  ${f} was never captured." >&2; exit 1; }
done
if cmp -s "${out}-panel-0-start.ppm" "${out}-panel-1-confirm.ppm"; then
    echo "FAIL  the panel is byte-identical across the press, so nothing was drawn in" >&2
    echo "      response: the button did not reach the app." >&2
    exit 1
fi
echo "ok    the panel changed across the press, so the app drew the confirm"

# --- 6. confirming it takes the machine down --------------------------------------------
#
# One press, never a hold (§13). Everything downstream of it is the exit-status contract, and
# the machine going down is the only observation that covers all of it.
monitor 'sendkey ret'
if settled 120; then
    echo "PASS  the confirm powered the machine off: exit 42 reached systemd, the unit"
    echo "      declared it a success, prevented the restart, and SuccessAction ran."
else
    echo "FAIL  the machine is still running ${waited}s after confirming the shutdown." >&2
    echo "      Something in the chain did not fire: /usr/lib/aobs/launch swallowing the" >&2
    echo "      app's status, SuccessExitStatus, RestartPreventExitStatus, or SuccessAction." >&2
    capture panel-2-still-running
    echo "--- serial console ---" >&2
    tr -cd '\11\12\15\40-\176' < "${log}" | sed 's/\[[0-9;]*[A-Za-z]//g' >&2 || true
    echo "--- end ---" >&2
    exit 1
fi

echo "--- serial console ---"
tr -cd '\11\12\15\40-\176' < "${log}" | sed 's/\[[0-9;]*[A-Za-z]//g' || true
echo "--- end ---"
