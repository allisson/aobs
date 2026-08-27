# Boot checklist

The checks that only a booted appliance can answer. Everything else is automated — see
[`test-harness.md`](test-harness.md).

**This is published with the ISO, not kept internal.** Each item below is the verification procedure
for a claim this project makes in public, and a claim whose procedure is unwritten is not really
verifiable. Running this list is what a release means.

The list is ordered by how much trust each check requires, least first. **Item 1 requires none** — it
is the one check a stranger can perform in three seconds without trusting us or any tooling.

## Amnesia

1. **Pull the boot medium, then sign anyway.** Boot the appliance, wait for the first screen, physically
   remove the USB stick or disc, then complete a full session: enter a mnemonic, scan a PSBT, review,
   sign, display the signed result. It completes. *(#10 claim (i); goes in the published README.)*

2. **Image the medium and diff it.** `dd` the medium to a file, run a full session, power off, `dd`
   again. The two images are byte-identical. The direct proof nothing was written, run on the
   reviewer's own machine.

3. **On the running appliance:**
   - `/proc/mounts` lists only tmpfs, proc, sys, dev, devpts, shm.
   - `/proc/swaps` is empty.
   - No `/dev/sd*`, `/dev/sr*`, `/dev/loop*` node exists — because no driver exists to create one.

4. **Shutdown is a forced power-off**, not a reboot. The machine ends powered down. *(#10)*

5. **Exactly one userspace process exists.** `ls -d /proc/[0-9]*` shows a single PID — the app. This is
   what makes claim (iii) structural rather than a promise. *(#15)*

6. **No core file can be produced.** `ulimit -c` reads `0`, and killing the app with `SIGSEGV` leaves no
   core file anywhere in the tmpfs — which it cannot, because `CONFIG_COREDUMP=n` means no dumper
   exists. *(#15)*

## USB

7. **`authorized_default` reads `0`** on every root hub once the appliance is up, and it already reads
   `0` **before the mnemonic or passphrase prompt** — not merely before signing. *(#14's sequencing.)*

8. **A mass-storage device inserted mid-session binds nothing.** No block device appears, no driver
   binds, nothing is mounted.

9. **The built-in driver list contains `usbhid` and `uvcvideo` and no other USB class driver**, with
   module loading unavailable. *(Also asserted at build time; this confirms the shipped image.)*

**Stated limit, verified rather than hidden:** between power-on and the `authorized_default` flip there
is a window of seconds in which an inserted device would be authorized. "No device is authorized after
boot" must not be read as "no device is ever authorized".

## Console and input

10. **`fbcon` gives at least 85 columns × 43 rows** — the size #3 fixed for a 77×77-module QR. Check on
    **both** firmware paths: UEFI via `efifb`/`simpledrm`, and legacy BIOS with `vga=791`. A BIOS box
    falling back to 80×25 text cannot display a QR at all. *(#12)*

11. **The keymap picker echoes keys as typed**, before any secret is entered, and a non-US layout
    selected there produces the characters printed on the physical keys. *(#12 — a passphrase typed
    through the wrong map is an unopenable wallet that reports no error.)*

## Camera

12. **Real webcam decode holds 5 fps**, the rate #6 measured as required (Sparrow's
    `ANIMATION_PERIOD_MILLIS = 200`), with 10 fps as the worst case.

13. **A multi-frame PSBT scans end to end from a real screen**, with decode progress advancing — the
    feedback #3 chose over a viewfinder.

14. **A webcam offering only compressed formats is a named camera problem, not a black picture.**
    With an MJPEG-only camera attached, the appliance reaches the home screen with the scan paths
    marked unavailable — the same session a machine with no webcam gets — rather than showing an
    empty framing aid the user would keep re-aiming at. *(#48. The accepted formats are `GREY`,
    `YUYV`, `UYVY`, `NV12`, `YU12` and `YV12`; a JPEG decoder is not on the appliance.)*

15. **The camera is released between uses.** Probe at startup, then scan, then leave and scan
    again: each works. A leaked descriptor is a camera that works exactly once per session, which
    looks like flaky hardware rather than like a bug. *(#48)*

## Refusals and failure

16. **The RAM-floor refusal fires.** Boot with less than 512 MiB available and the appliance stops with
    a clear message rather than starting and dying mid-session with a wallet loaded. *(#10, #12)*

17. **There is no path from the running app to a prompt.** No getty, no VT with a login, no VT
    switching; Ctrl+Alt+Del does nothing; SysRq does nothing.

    **Not defended, and confirm it behaves as documented rather than pretending otherwise:**
    `init=/bin/sh` typed at the bootloader does give a shell. That is stated, not defended — a fresh
    boot holds no secrets. *(#12)*

18. **A failure shows a screen naming it**, waits for a keypress, then powers off. The outcome to check
    for is the one that must never happen: a silent power-off with no explanation. *(#12)*

19. **A cold boot reaches the randomness wait screen, and leaves it on its own.** On a machine
    whose pool is slow to initialise — which is what `random.trust_cpu=off
    random.trust_bootloader=off` is for — go straight to *generate a wallet* and skip the dice.
    The wait screen appears, names typing and pointing the camera at something, and **clears
    itself** the moment the pool comes up, with no key pressed. `esc` leaves it, and the rolls are
    still there on the dice screen behind. *(#8, #48. The outcome to check for is the one this
    screen exists to prevent: the appliance freezing inside a syscall with nothing on screen.)*

20. **A keymap that will not load is named before any secret exists.** Select a layout whose map
    the image does not ship — or run with the loader removed — and the appliance names the failure
    on the fault screen while the picker is still the first screen. A silently failed application
    is a passphrase typed through the wrong map, which is an unopenable wallet that reports no
    error. *(#12, #48)*

21. **No date or time is displayed anywhere**, and an `nLockTime` is shown raw with no judgement about
    whether it has passed — there is no clock to make that judgement with. *(#12)*

## Interop

22. **A full round trip with each target watch-only wallet**, on mainnet: export the descriptor, have
    the wallet build a PSBT, scan it, sign, scan the result back, broadcast.

    **This is the check with the fewest substitutes.** #5 found that Green cannot receive taproot over
    BC-UR at all, and #4 found that BlueWallet routes `ur:psbt` to a UR v1 decoder where it fails —
    both discovered by reading their source, and both the kind of thing only a real device confirms.
    Note also that **testnet4 interop holds for Sparrow only**; Green has mainnet plus testnet3 and
    Blue Wallet is mainnet-only.
