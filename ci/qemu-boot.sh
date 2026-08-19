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
# Each row asserts the tier on the readiness line, so a green row cannot mean merely that
# *something* drew: ramfb must report `display=fbdev` and virtio-gpu `display=drm`.
#
# Three more knobs, for the panel rows (04-screens.md §0):
#
#   AOBS_QEMU_RES=WxH        the virtio-gpu machine's mode, as the connector's preferred
#                            one. QEMU's own default is 1280x800 — the design canvas, which
#                            is why the plain DRM row runs at scale 1.00. ramfb takes its
#                            mode from OVMF's GOP (800x600 by default) and ignores this.
#
#                            §6.2 names `SLINT_DRM_MODE` for the sub-floor row. It is a
#                            *mode-list index*, so its meaning is QEMU's and the kernel's to
#                            change under us, and nothing in the image can inject an
#                            environment variable into `aobs.service` without a second boot
#                            path that is no longer GRUB-on-the-ISO. This names the geometry
#                            instead and needs no plumbing inside the guest at all.
#
#   AOBS_QEMU_EXPECT=code    wait for that failure code on the console instead of the
#                            readiness line, and fail if a readiness line appears at all —
#                            which is how the below-the-floor row asserts that the appliance
#                            refuses rather than drawing something it cannot draw honestly.
#
#   AOBS_QEMU_EXPECT_PANEL   a fixed string the `AOBS_PANEL` line must contain, e.g.
#                            `mode=1920x1080 scale=1.35 logical=1422x800`.
#
#   AOBS_QEMU_SETTLE=120     on a refusal row, how long to hold the machine after the code
#                            appears before asserting the appliance started exactly once. It
#                            has to outlast the 90-second `Type=notify` start timeout that
#                            `TimeoutStartSec=infinity` removes, because a parked diagnostic
#                            restarted every 90 seconds is the failure parking prevents.
#
#   ci/qemu-boot.sh bitcoin-signer-amd64.iso [memory-MiB] [timeout-seconds]
set -eu

iso="${1:-bitcoin-signer-amd64.iso}"
memory="${2:-4096}"
deadline="${3:-600}"
gpu="${AOBS_QEMU_GPU:-ramfb}"
res="${AOBS_QEMU_RES:-}"
expect="${AOBS_QEMU_EXPECT:-ready}"

case "${gpu}" in
    ramfb)
        display_args="-vga none -device ramfb"
        tier="fbdev"
        [ -z "${res}" ] || { echo "AOBS_QEMU_RES needs virtio-gpu: ramfb's mode is OVMF's" >&2; exit 1; }
        ;;
    virtio-gpu)
        display_args="-vga none -device virtio-gpu-pci"
        tier="drm"
        if [ -n "${res}" ]; then
            case "${res}" in
                [0-9]*x[0-9]*) ;;
                *) echo "AOBS_QEMU_RES must read WxH, not ${res}" >&2; exit 1 ;;
            esac
            display_args="${display_args},xres=${res%x*},yres=${res#*x}"
        fi
        ;;
    *) echo "AOBS_QEMU_GPU must be ramfb or virtio-gpu, not ${gpu}" >&2; exit 1 ;;
esac

# What ends the wait: the readiness line, or — for a row asserting a refusal — the failure
# code in §9's diagnostic block.
case "${expect}" in
    ready) marker='^AOBS_READY ' ;;
    AOBS-E[0-9][0-9]) marker="${expect}" ;;
    *) echo "AOBS_QEMU_EXPECT must be ready or an AOBS-E## code, not ${expect}" >&2; exit 1 ;;
esac

[ -f "${iso}" ] || { echo "no such image: ${iso}" >&2; exit 1; }

work="$(mktemp -d)"
log="${work}/serial.log"
trap 'rm -rf "${work}"' EXIT

# UEFI firmware, from the one list every row shares (ci/ovmf.sh). Sets ${firmware_args}
# and needs ${work}.
. "$(dirname "$0")/ovmf.sh"

echo "booting ${iso} with ${memory} MiB on ${gpu}${res:+ at ${res}}, expecting ${expect}"
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
    if grep -q -- "${marker}" "${log}" 2>/dev/null; then
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

# A refusal has to be a refusal that *stays*. §9 parks the process forever and
# `TimeoutStartSec=infinity` is what stops systemd from killing the parked process and
# starting it over (01-boot-layer.md §2), so this outlasts the 90-second default that key
# removes and then counts starts: one `AOBS_PANEL` line per start of the appliance.
settle="${AOBS_QEMU_SETTLE:-120}"
if [ "${found}" -eq 1 ] && [ "${expect}" != "ready" ] && [ "${settle}" -gt 0 ]; then
    echo "  holding ${settle}s to see whether the parked diagnostic survives"
    sleep "${settle}"
    # `|| true`, not `|| echo 0`: grep -c already prints 0 when it matches nothing and only
    # then exits non-zero, so the echo would append a second line and the comparison below
    # would fail on "0\n0" instead of reporting zero starts.
    starts="$(grep -c '^AOBS_PANEL ' "${log}" 2>/dev/null || true)"
    if [ "${starts:-0}" -ne 1 ]; then
        echo >&2
        echo "FAIL  the appliance started ${starts} times. A parked diagnostic must not be" >&2
        echo "      restarted out from under the user (01-boot-layer.md §2, §9)." >&2
        capture_panel
        exit 1
    fi
    echo "ok    still parked after ${settle}s, having started exactly once"
fi

# On a refusal row the panel is the point — §9's block has to be sitting on a live console
# rather than behind a UI or a black screen. Asserting pixels would be the screenshot
# diffing §6.2 rules out, so the capture is evidence for a human, not a gate.
if [ "${found}" -ne 1 ] || [ "${expect}" != "ready" ]; then
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
    echo "FAIL  the machine stopped after ${waited}s without ${expect}." >&2
    exit 1
fi

if [ "${found}" -ne 1 ]; then
    echo >&2
    echo "FAIL  no ${expect} after ${waited}s." >&2
    echo "      Nothing but the appliance writes to this serial port, so read" >&2
    echo "      ${screendump} for what the panel was showing." >&2
    exit 1
fi

if [ "${expect}" = "ready" ]; then
    ready="$(grep -m1 '^AOBS_READY ' "${log}")"
    echo "ok    readiness line: ${ready}"

    # The tier the line names has to be the tier this machine has. Without it a green row
    # would prove only that *something* drew (§6.2, ADR-0016).
    if ! echo "${ready}" | grep -q "display=${tier}"; then
        echo "FAIL  ${gpu} must report display=${tier}" >&2
        exit 1
    fi
    echo "ok    tier: display=${tier}"
else
    echo "ok    refusal: $(grep -m1 -- "${expect}" "${log}" | sed 's/^ *//')"

    # A refusal that also drew is not a refusal. 04-screens.md §0: below the floor the
    # appliance refuses at startup, on a live console, and shows no UI at all.
    if grep -q '^AOBS_READY ' "${log}"; then
        echo "FAIL  ${expect} was reported and the appliance came up anyway" >&2
        exit 1
    fi
    echo "ok    no readiness line, so no UI was drawn"
fi

# The mode the appliance learned, and what it decided to do with it (04-screens.md §0).
if grep -q '^AOBS_PANEL ' "${log}"; then
    echo "ok    panel: $(grep -m1 '^AOBS_PANEL ' "${log}")"
else
    echo "FAIL  no AOBS_PANEL line, so the appliance never reported the mode it learned" >&2
    exit 1
fi

if [ -n "${AOBS_QEMU_EXPECT_PANEL:-}" ]; then
    if grep -qF -- "AOBS_PANEL ${AOBS_QEMU_EXPECT_PANEL}" "${log}"; then
        echo "ok    panel matches ${AOBS_QEMU_EXPECT_PANEL}"
    else
        echo "FAIL  panel is not ${AOBS_QEMU_EXPECT_PANEL}" >&2
        exit 1
    fi
fi

# The first of the eight measurements 00-overview.md owes. Derived as 1–16 s under
# `random.trust_cpu=off`; this is the number, from a machine rather than from random.c.
# QEMU is not target hardware, so it does not discharge the obligation — it tracks it.
if grep -q '^AOBS_ENTROPY_MS=' "${log}"; then
    echo "note  entropy readiness under QEMU: $(grep -m1 '^AOBS_ENTROPY_MS=' "${log}")"
else
    echo "FAIL  no entropy measurement on the console" >&2
    exit 1
fi
