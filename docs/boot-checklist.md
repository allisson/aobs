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

## USB

5. **`authorized_default` reads `0`** on every root hub once the appliance is up, and it already reads
   `0` **before the mnemonic or passphrase prompt** — not merely before signing. *(#14's sequencing.)*

6. **A mass-storage device inserted mid-session binds nothing.** No block device appears, no driver
   binds, nothing is mounted.

7. **The built-in driver list contains `usbhid` and `uvcvideo` and no other USB class driver**, with
   module loading unavailable. *(Also asserted at build time; this confirms the shipped image.)*

**Stated limit, verified rather than hidden:** between power-on and the `authorized_default` flip there
is a window of seconds in which an inserted device would be authorized. "No device is authorized after
boot" must not be read as "no device is ever authorized".

## Console and input

8. **`fbcon` gives at least 85 columns × 43 rows** — the size #3 fixed for a 77×77-module QR. Check on
   **both** firmware paths: UEFI via `efifb`/`simpledrm`, and legacy BIOS with `vga=791`. A BIOS box
   falling back to 80×25 text cannot display a QR at all. *(#12)*

9. **The keymap picker echoes keys as typed**, before any secret is entered, and a non-US layout
   selected there produces the characters printed on the physical keys. *(#12 — a passphrase typed
   through the wrong map is an unopenable wallet that reports no error.)*

## Camera

10. **Real webcam decode holds 5 fps**, the rate #6 measured as required (Sparrow's
    `ANIMATION_PERIOD_MILLIS = 200`), with 10 fps as the worst case.

11. **A multi-frame PSBT scans end to end from a real screen**, with decode progress advancing — the
    feedback #3 chose over a viewfinder.

## Refusals and failure

12. **The RAM-floor refusal fires.** Boot with less than 512 MiB available and the appliance stops with
    a clear message rather than starting and dying mid-session with a wallet loaded. *(#10, #12)*

13. **There is no path from the running app to a prompt.** No getty, no VT with a login, no VT
    switching; Ctrl+Alt+Del does nothing; SysRq does nothing.

    **Not defended, and confirm it behaves as documented rather than pretending otherwise:**
    `init=/bin/sh` typed at the bootloader does give a shell. That is stated, not defended — a fresh
    boot holds no secrets. *(#12)*

14. **A failure shows a screen naming it**, waits for a keypress, then powers off. The outcome to check
    for is the one that must never happen: a silent power-off with no explanation. *(#12)*

15. **No date or time is displayed anywhere**, and an `nLockTime` is shown raw with no judgement about
    whether it has passed — there is no clock to make that judgement with. *(#12)*

## Interop

16. **A full round trip with each target watch-only wallet**, on mainnet: export the descriptor, have
    the wallet build a PSBT, scan it, sign, scan the result back, broadcast.

    **This is the check with the fewest substitutes.** #5 found that Green cannot receive taproot over
    BC-UR at all, and #4 found that BlueWallet routes `ur:psbt` to a UR v1 decoder where it fails —
    both discovered by reading their source, and both the kind of thing only a real device confirms.
    Note also that **testnet4 interop holds for Sparrow only**; Green has mainnet plus testnet3 and
    Blue Wallet is mainnet-only.
