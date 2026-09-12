# Boot checklist

The checks only a booted appliance can answer. Published with the ISO.

**This document is the procedure. It is not the evidence.** The evidence is a *boot-checklist run
record*: one operator, one machine, one image, every row answered. `docs/boot-runs/` holds the
records this project has written; the template at the end of this file is what a record is filled in
from. A checklist with no run record beside it says only that somebody thought about these
questions.

Nothing here verifies the appliance to the operator. A modified image can print anything, and a
self-report by a possibly-modified image is not evidence about itself (`docs/overview.md`). Verify
the ISO against the signed manifest **before** writing the stick. These rows check that the image
does what this repository says it does — they cannot check that it is the image you think it is.

## The three row families

A row that does not say which boot answers it is not runnable — a Session offers no prompt, so half
of these questions cannot be asked during one at all.

| Prefix | Where it is answered |
|---|---|
| **`I-n`** | **Inspection boot**: `rdinit=/bin/sh` typed at the bootloader, which replaces the application with a shell |
| **`S-n`** | **Session boot**: the appliance as shipped, PID 1 is `build/init` and the application is the only userspace process |
| **`R-n`** | **Read the repository**: claims an inspection boot cannot answer without producing a number that *looks* like evidence and is not |

**Run the inspection boot first.** It is where the glyph check lives (`I-9`), and a missing glyph
means an image rebuild — cheaper to discover before a Session has been walked than after.

## Verdicts

**`pass`** — the row's stated expectation was met. **`fail`** — it was not. **`deviated`** — the row
was not run as written, or was run against something other than what it names.

`deviated` is the load-bearing verdict: it marks where the evidence stops matching the checklist's
claim, which a missing row or a generous `pass` would hide. **A `deviated` verdict with no written
reason is not a verdict.** Neither is a `pass` on a row that was not actually performed.

---

## Write the medium

**Before the first boot, and not at any other time.** This section has no `pass`/`fail` — no boot
answers it, and it is not a row. What it produces is the run record's `## Image` block, which every
verdict below is evidence *about*: a verdict that cannot name the image it was observed on is a
verdict about nothing.

The digest has to be taken in the same breath as the write. A digest recovered afterwards from a
build directory is a guess about history — the directory may hold a later build of the same commit,
and two builds of one commit are expected to differ until the reproducibility contract exists
(`docs/threat-model.md`, claim (ix)). The 2026-09-11 run is what that costs:
`docs/boot-runs/2026-09-11-cb514-1h.md` could name its image only by the operator's recollection.

**1. Verify the ISO against the signed manifest**, before it touches the stick — the manifest is
what a signature covers and the ISO is not (`CONTEXT.md`, *Manifest*). An unsigned local build says
so in the record instead; it is not a failure, it is a different claim.

**2. Write it, and hash it, without leaving the terminal.** Identify the device node first and read
it back before typing it into `of=`: on a wrong node `dd` destroys the disk it names, without asking
and without a way back. `lsblk` on Linux, `diskutil list` on macOS. The node is the whole disk
(`/dev/sdb`, `/dev/disk4`), never a partition (`/dev/sdb1`, `/dev/disk4s1`).

```
# Linux
sha256sum out/bitcoin-signer-amd64.iso
sudo dd if=out/bitcoin-signer-amd64.iso of=/dev/sdX bs=4M oflag=direct status=progress conv=fsync
sudo head -c "$(stat -c%s out/bitcoin-signer-amd64.iso)" /dev/sdX | sha256sum
```

```
# macOS — /dev/rdiskN is the raw node and is ~20x faster than /dev/diskN
shasum -a 256 out/bitcoin-signer-amd64.iso
diskutil unmountDisk /dev/diskN
sudo dd if=out/bitcoin-signer-amd64.iso of=/dev/rdiskN bs=4m
sudo head -c "$(stat -f%z out/bitcoin-signer-amd64.iso)" /dev/rdiskN | shasum -a 256
```

**3. Record both digests before booting anything**, into the `## Image` block of the run record.

The two digests carry different weight and the record must not merge them. The **ISO digest** is
what ties this run to a build and, for a release, to a manifest. The **medium read-back digest** is
**best-effort**: it is evidence that the host which wrote the stick read those same bytes back off
it, nothing more. It is not evidence about what the firmware reads at boot — a medium can be
rewritten after the read-back, and the appliance cannot check its own medium
(`docs/overview.md`). Write it up as the first and never as the second.

A read-back that cannot be taken — a host that will not read the raw node — is recorded as `not
taken`. That is an honest run. A digest invented afterwards is not.

---

## Inspection boot

You get a shell as PID 1. `build/init` has **not** run: no filesystems beyond what the kernel
mounted, no module loaded, no USB hub locked down.

**Type `inspect` at the `boot:` prompt.** The bootloader shows a prompt for three seconds, cancelled
by the first keystroke, and offers two entries — `aobs` and `inspect`. On a UEFI host it is GRUB's
menu with the same two, and the same three seconds.

That is a change made *because of* this checklist, and the reason is worth keeping. The bootloader
used to set `PROMPT 0` and `TIMEOUT 0`, on the argument that a person standing there could type a
parameter and that this cost nothing. Under `PROMPT 0`, SYSLINUX shows the prompt only while
**Shift** or **Alt** is held or with **Caps Lock**/**Scroll Lock** set, reading the BIOS
keyboard-flags byte — which the firmware has to populate. On the machine in `docs/boot-runs/`
(coreboot `RW_LEGACY` SeaBIOS, Chromebook) **Shift and Alt on the built-in keyboard produced no
prompt at all**; an external USB keyboard with Caps Lock set produced it immediately, and that
machine has no Caps Lock or Scroll Lock key of its own. A door that opens only on firmware that
populates one BIOS byte is not a door the absence claims can rest on.

**Then the external keyboard stops working the moment the kernel starts, and that is correct
behaviour.** In an inspection boot `build/init` never runs, so nothing loads `xhci_pci`, `usbhid` or
`hid_generic` — a USB keyboard has no driver. The built-in keyboard keeps working because
`CONFIG_SERIO_I8042=y` and `CONFIG_KEYBOARD_ATKBD=y` are in the kernel image. So: **external
keyboard for the bootloader, built-in keyboard for the shell.** If the machine has no built-in
keyboard, load the modules by hand before anything else — but note that doing so makes `I-5` and
`I-6` observations about a tree you have already touched, and the run record must say so.

**Spelling it out instead of trusting the entry** is supported and encouraged — a stranger checking
absence claims has every reason to distrust an entry someone else named `inspect`. Type the label
first, because at a SYSLINUX prompt the first word is the entry to boot, so a bare `rdinit=/bin/sh`
is read as a kernel image name and fails:

```
boot: aobs rdinit=/bin/sh
```

Both routes produce the identical command line; `build/isolinux.cfg` and `build/grub.cfg` are
written so the two entries differ by that one parameter and nothing else. On UEFI the equivalent is
GRUB's `e` on the `aobs` entry.

**`rdinit=`, not `init=`, and this is the parameter that matters.** The whole root filesystem is the
initramfs, so the kernel never mounts a root and never reaches the `init=` path: `init/main.c` runs
`ramdisk_execute_command` — default `/init`, overridden by **`rdinit=`** — and only falls through to
`execute_command` from `init=` if that *fails*. `/init` is `build/init` and it succeeds, so an
`init=` on the command line is accepted by the bootloader, ignored by the kernel, and boots the
appliance normally. It does not error. It looks exactly like a working command line, which is why this
repository documented it in six places for as long as it did.

Options typed after the label are appended to that entry's `APPEND` line, so both
`random.trust_*=off` survive — which matters, because an inspection boot that differed from the
Session boot in any option would be inspecting a different image from the one that signs.

**The UEFI path is unexercised** — see the note under `I-7`. It ships the same two entries.

**The shell will greet you with `/bin/sh: 0: can't access tty; job control turned off`. That is not
a fault.** It is dash noting that it is PID 1 with no controlling terminal, so `Ctrl+Z`, `fg` and
`bg` do not work. Every command below is non-interactive and unaffected.

### `I-0` — Mount the pseudo-filesystems the rows below read

```
mount -t proc  proc  /proc
mount -t sysfs sysfs /sys
```

**This is preparation, not a check** — but it is not optional and it is not obvious. `build/init`
mounts these at steps 1 and 2 and `build/init` did not run; the pinned kernel has no
`CONFIG_DEVTMPFS_MOUNT`, so it auto-mounts nothing either. Without this, `I-1`, `I-2`, `I-7` and
`I-8` fail for the wrong reason.

Mounting them yourself does not weaken `I-1`. The claim is that no *filesystem on a medium* is
mounted; `proc` and `sysfs` are pseudo-filesystems with no backing store, they are two of the five
`build/init` mounts anyway, and `I-1`'s pass condition names them explicitly.

### `I-1` — Nothing is mounted but tmpfs and pseudo-filesystems

```
cat /proc/mounts
```

**Pass**: every line is `rootfs`/`tmpfs`, `proc`, `sysfs`, `devtmpfs` or `devpts`. No `ext4`, no
`vfat`, no `iso9660`, nothing naming a block device. Records the mounting half of threat-model claim
(i), which is **structural** — the whole rootfs is the initramfs and there is nothing to mount from.

### `I-2` — No block device enumerates

```
ls /sys/block
```

**Pass**: empty, or `loop*`/`ram*` only. Anything named `sd*`, `nvme*`, `mmcblk*` or `sr*` is a
**fail** — it means a storage driver reached the image. The driver half of claim (i), at **absence**
strength.

### `I-3` — No storage driver is in the modules tree

```
ls /lib/modules/*/kernel/drivers/ata /lib/modules/*/kernel/drivers/nvme \
   /lib/modules/*/kernel/drivers/scsi
```

**Pass**: all three report *No such file or directory*. All three exist in Debian's unpruned tree, so
this row is checking that `build/prune_modules.py` did its work on this image and not that Debian
happened to omit them.

### `I-4` — No network module, and no tool to configure one

```
ls /lib/modules/*/kernel/net /lib/modules/*/kernel/drivers/net
command -v ip ifconfig wpa_supplicant curl wget ssh
```

**Pass**: both listings report *No such file or directory*, and `command -v` prints nothing and exits
non-zero for every name. Threat-model claim (iv), at **absence** strength. Both directories exist in
the unpruned tree.

### `I-5` — USB carries only the classes the allowlist names

```
ls /lib/modules/*/kernel/drivers/usb
```

**Pass**: `common`, `core` and `host`, and nothing else. Debian's unpruned tree has fifteen
directories here; the ones whose absence this row is really checking are **`storage`** and
**`serial`**. If either is present, stop — claim (v) is false on this image.

### `I-6` — The camera and HID drivers are present, and are all that is

```
ls /lib/modules/*/kernel/drivers/hid /lib/modules/*/kernel/drivers/media
ls /lib/modules/*/kernel/drivers/gpu 2>&1
```

**Pass**: `drivers/hid` holds `hid.ko.xz`, `hid-generic.ko.xz` and `usbhid/`; `drivers/media` holds
`v4l2-core` and `usb/` (the `uvc` driver), plus whatever `depmod` pulled in as a dependency;
`drivers/gpu` reports *No such file or directory*. The last one is not an oversight —
`build/modules.allow` ships **no graphics driver** deliberately, and `I-7` is what proves the console
does not need one.

### `I-7` — Which framebuffer is actually driving the console

```
cat /proc/fb
cat /sys/class/graphics/fb0/name
stty size
```

**Record all three verbatim.** The name is one of three, and **it does not follow from the firmware
path**: `efifb` is the GOP on a UEFI boot, `simplefb` is a `simple-framebuffer` device — a coreboot
machine registers one from the coreboot table — and `vesafb` is a VESA linear mode on a BIOS boot.
`docs/boot-pipeline.md` has the ordering; first registrar takes the aperture.

**Pass** requires a framebuffer to exist *and* `stty size` to report at least **43 rows and 100
columns**, which is the floor `aobs/ui/geometry.py` enforces. Below it the appliance refuses to
start, by design — so a `deviated` verdict here is a machine that cannot run the appliance, not a
checklist that needs adjusting.

This is one half of the graphics decision in `build/modules.allow`, and the half it answers is the
firmware path you booted. **The other paths stay unobserved and the run record must say so** rather
than let a reader infer them from one — `I-7c` is where the UEFI path says it.

### `I-7b` — Which framebuffer devices were offered, and which driver lost

```
ls /sys/devices/platform/ | grep -i framebuffer
dmesg | grep -iE 'simple-?fb|vesafb|efifb|aperture|coreboot'
```

**Record both verbatim.** `I-7` names the driver that won; this names the field it won on, and the
two are not the same question. The kernel can register more than one framebuffer device and only
one of them gets the memory: `devm_aperture_acquire` refuses an overlapping range with `-EBUSY`,
first come, so the second driver to probe fails and never appears in `/proc/fb`. Which driver that
was, and whether it was offered a device at all, is visible only here.

Expect one or two entries, and **the name of the `sysfb` one is a readout of whether the firmware
gave the kernel a linear framebuffer**: `vesa-framebuffer` means it did (`sysfb.c:157`),
`efi-framebuffer` means a UEFI GOP, and `vga-framebuffer` means plain text mode — the firmware
offered nothing, and whatever is drawing the console came from somewhere else. A coreboot machine
also has `framebuffer-coreboot` registering a `simple-framebuffer` as a child of the coreboot
device, so it does not appear directly in this listing; look for it in the `dmesg` line instead.

**There is no pass or fail here.** The run record carries what was seen. On the 2026-09-12 run this
check is what showed `vga=791` had never set a mode — `vga-framebuffer.0`, no `vesafb`, no aperture
conflict — and `vga=` was removed from the image as a result.

### `I-7c` — The UEFI framebuffer path

```
cat /sys/class/graphics/fb0/name
ls /sys/devices/platform/ | grep -i framebuffer
stty size
```

**This row exists to be `deviated` on a machine that has no UEFI path**, and that is every machine
this project has recorded. It is the second half of the graphics decision in `build/modules.allow`:
that decision covers two firmware paths, `I-7` answers whichever one you booted, and without this
row the other one has no place to be recorded and is read as a path nobody considered.

**Pass** requires all three: `fb0/name` reads `efifb`, the platform listing shows
`efi-framebuffer`, and `stty size` reports at least **43 rows and 100 columns**. The middle readout
is the one that discriminates — per `I-7b`, `efi-framebuffer` is `sysfb` reporting a GOP
framebuffer from the firmware, so a UEFI boot whose console came from somewhere else does not pass
by having drawn something.

**`fail`** is a UEFI boot that draws nothing, comes up under the floor, or reaches the console
through a driver this image does not ship. **`deviated`** is a machine with no UEFI path at all —
the target machine's `RW_LEGACY` SeaBIOS is a BIOS path and reaching `efifb` would mean flashing a
full ROM. **The reason is written in the row, and a `pass` is never inferred from `I-7` passing on
the other path.** Closing this needs a UEFI boot; `docs/roadmap.md`'s Secure Boot row is where that
is planned.

### `I-8` — Which controller the keyboard is on

```
cat /proc/bus/input/devices
```

**Record verbatim.** On a laptop expect an `i8042`/`AT Translated Set 2 keyboard` entry: the keyboard
is behind a built-in controller that `CONFIG_SERIO_I8042=y` puts in the kernel image, which the module
allowlist cannot remove and `authorized_default=0` never touches. On a machine driven by an external
keyboard expect a USB entry instead.

Neither is a failure. The row exists because claim (v) is about **what USB binds** and not about where
keystrokes come from, and because a Chromebook that routed its keyboard through the embedded
controller would have *no keys at all* — `cros_ec_keyb` is a module and is not in the image.

### `I-9` — Whether the console has a glyph for the four characters that need one

```
python3 -c 'print("U+2588 [\u2588]  U+2591 [\u2591]  U+0021 [!]  U+002D [-]")'
```

Or, staying in the shell:

```
printf 'U+2588 [\342\226\210]  U+2591 [\342\226\221]  U+0021 [!]  U+002D [-]\n'
```

**Octal, not `\xHH`, and do not "fix" this back.** `/bin/sh` is dash and its builtin `printf` is
POSIX: it prints `\xHH` literally, so a `\x` form produces a line of backslashes that looks like a
failed glyph and is actually a failed command. That is exactly what this row's first attempt did.

**And the octal is `\ddd`, not `\0ddd`.** The three-digit `\0ddd` spelling is the form for a `%b`
*argument*; in a format string dash consumes `\0` plus **two** further digits and prints the
leftover one, so `\0342\0226\0210` draws `260` and tests no glyph while looking like a row that
ran. That is what this row's second attempt did, on 2026-09-11 — `docs/boot-runs/2026-09-11-cb514-1h.md`.
The `\u2588` escape in the `python3` form is there for the same reason: neither `█` nor `░` can be
typed on the console under test.

**Both forms have been observed on a panel.** The `\ddd` form drew both blocks on 2026-09-12 —
`docs/boot-runs/2026-09-11-cb514-1h.md`, Addendum. It is the third spelling this row has published:
`\xHH` and `\0ddd` each printed something that was not a glyph, and each looked like a row that ran.

`python3` is the appliance's own interpreter, is in the image by construction, and draws to the
same console through the same font — either form is representative.

**Record each of the four separately**: rendered, or not. A blank, a `?`, a solid box or a wrong
glyph are all *not rendered*.

**This row now confirms a derivation rather than discovering one.** The five characters below were
`⚠ ▮ ▯ – —` and none of them is in the console's repertoire — the default map is generated from
`drivers/tty/vt/cp437.uni`, 303 codepoints — so they were replaced with `!`, `█`, `░` and `-`, and
`tests/test_structure.py` fails the build for the next character outside the set. What this row
adds is observation on a real panel, which no amount of reading the kernel gives you. **Run it
against the characters the appliance actually draws now**, and expect all four of *these* to
render; a `fail` here means the derivation was wrong and the repertoire list is not what the
console is using.

The console font is `CONFIG_FONT_8x16` — the kernel's built-in 8x16 font, since `build/init` never
calls `setfont` — so this boot is representative of what a Session will draw. The stakes per
character:

| Character | Used by | If it has no glyph |
|---|---|---|
| `⚠` U+26A0 | `aobs/ui/reviewtext.py` — the NOT PROVEN marker | The strongest warning on the review screen is invisible |
| `▮` U+25AE, `▯` U+25AF | `aobs/ui/scanning.py` — the slot map | The scan screen's **entire** progress feedback is unreadable |
| `–` U+2013, `—` U+2014 | Row templates | Cosmetic |

**A missing glyph on the first three is a `fail`, not a `deviated`.** The substitute is chosen from
what this row showed does render, `docs/review-screen.md` and `docs/scan-feedback.md` are amended
character by character, the image is rebuilt, and the session boot happens against the rebuilt image.
Substitutes are deliberately not chosen in advance: the check is cheaper than the guess.

---

## Read the repository

Two claims do not survive the `rdinit=/bin/sh` substitution, and neither may be written up as if it
does. These rows are answered by reading source, and the run record says so rather than printing a
number that looks like evidence.

### `R-1` — Exactly one userspace process exists for the whole Session

**Not** `ls -d /proc/[0-9]*`. In an inspection boot the stranger's own shell is PID 1, so that count
describes the shell.

**Pass**: `build/init` ends in `exec python3 -m aobs`; there is no init system, no getty and no
second `exec`; and `build/verify.py` asserts every command `build/init` invokes resolves on PID 1's
own `PATH` in the built rootfs. Threat-model claim (iii), **structural**.

### `R-2` — No USB device is authorized once the appliance is up

**Not** `cat /sys/bus/usb/devices/usb*/authorized_default`. PID 1 writes it, and this boot replaced
PID 1, so the value read here is whatever the kernel left.

**Pass**: `build/init` writes `0` to every root hub's `authorized_default`, **after** the appliance's
own devices have enumerated, and fails the boot if a write does not take. The policy half of claim
(v).

---

## Session boot

Boot the medium with no arguments. From here the appliance is the only userspace process and there is
no prompt: everything below is observed on the screen, in order, in one Session.

### `S-1` — The keymap picker is usable and prints its own keys

**Pass**: the picker draws, its key line is visible on the screen, and pressing the key it names
moves off it. The screen where `esc` has nowhere to go is the one screen whose keys must be printed,
and it once was not — a boot reached it and could go no further.

### `S-1b` — What the home screen says about the camera, recorded verbatim

The one row whose answer is most often *nothing*, and *nothing* is an answer. This is the only
reading a Session boot can give about USB authorization — `R-2` is read from source precisely
because an inspection boot has replaced the PID 1 that would have written it.

**Copy the camera note off the screen exactly**, or write *no camera note shown* if there is none.
There are six things it can be, and they are not interchangeable:

| what is on screen | what it means |
|---|---|
| no note at all | a camera was found and every scan path is available |
| *No camera was found …* alone | no capture node, and nothing arrived late — consistent with a machine that has no webcam |
| *No camera was found …* **plus** *One USB device arrived after the bus was closed …* | a Late arrival exists. **This is the row `docs/roadmap.md` is waiting on.** Record the `idVendor:idProduct` and the device name |
| *The camera offers no image format …* | a node existed and negotiation failed — not a timing fault |
| *The camera granted no capture buffers …* | as above |
| *The camera was found but produced no frames …* | as above |

**Pass**: whatever is on screen is written down, including its absence. This row cannot fail; it can
only be unanswered, and an unanswered row is an incomplete record. A run that shows the third line
is the first observation that separates the two causes `docs/failure-states.md` says V4L2 cannot,
and it is what a diagnosis of the intermittent camera would be built from — it is still not, by
itself, that diagnosis.

### `S-2` — Half-bright renders on this panel

**Pass**: on the home screen, the rows that need a wallet are visibly greyer than the rows that do
not. `docs/console-appearance.md` fixes what a screen may rest on; if half-bright does not render on
this panel, every dimmed row is indistinguishable from an available one and the worded reason beside
each is all the user has.

### `S-3` — A wallet can be generated, and entropy does not deadlock

**Pass**: the mixing screens accept their sources, the appliance reports bits contributed rather than
demanding a quota, and if the kernel pool is not ready it says so plainly — *keep typing, point the
camera at something* — instead of freezing. Record the master fingerprint.

### `S-4` — The xpub leaves by QR and a watch-only wallet reads it

**Pass**: the export QR renders inside the console's 85×43 display and a watch-only wallet on another
machine scans it and derives the same master fingerprint as `S-3`. Record the wallet software and
version.

### `S-5` — With a wallet loaded, the three ways in read as unavailable

**Pass**: all three rows are dimmed, each carries its own right-aligned reason (*one wallet per
session*), the note under the list is present, and pressing `F10` on one of them **does nothing** —
no screen change, no failure screen. A Session holds at most one wallet and there is no unloading;
this row is the check that walking a way in cannot replace a loaded wallet.

### `S-6` — An unsigned PSBT scans in, and the slot map tracks it

**Pass**: the PSBT is built in the watch-only wallet, the framing aid shows the code, and the slot map
fills as parts arrive — including a re-scan of a part already held, which must not regress the map.
Depends on `I-9` for `▮`/`▯`.

### `S-7` — The review screen shows what the PSBT is, not what it claims

**Pass**: every output is categorised as payment, proven change, or NOT PROVEN; the NOT PROVEN marker
is legible; and the amounts and fee are shown. Record the categories the appliance reached, and
whether they match what the watch-only wallet believed it built — a disagreement here is the finding,
not the error.

### `S-8` — It signs, and the signature leaves by QR

**Pass**: the appliance signs, the signature QR renders, and the watch-only wallet scans it back and
finalises the transaction.

### `S-9` — The transaction broadcasts

**Pass**: the finalised transaction is accepted by the network. **Record the network and the txid.**
Any non-mainnet network is acceptable — `docs/network-selection.md` treats testnet4 and signet as
peers, and pinning one into this procedure would produce a `deviated` verdict for something the row
never cared about. testnet4 is what this project has used.

### `S-10` — The boot medium comes out, and signing continues

**Pull the stick out of the running machine, mid-Session, and keep going** — scan another PSBT, review
it, sign it.

**Pass**: nothing changes. This is the cheapest check of claim (vi), it is **structural** — firmware
read the medium before Linux started and nothing opens it again — and until somebody has physically
done it, it is a claim and not a fact. Do it after `S-9` so a failure does not cost the run.

### `S-11` — The machine stops

**Pass**: the power-off key ends the Session and the machine powers down. There is no shutdown
sequence to observe: no init system to ask, no filesystem to unmount. The wipe that precedes it is
**best-effort** and is not observable from here — `tests/test_app_shell.py` is where that ordering is
asserted, and this row must not be written up as evidence of it.

## Not covered by this revision

Named rather than quietly omitted, so that a reader does not mistake this list for the whole of what
a booted appliance can answer:

- **Address verification** (`docs/address-verification.md`) — scan a receive address and have the
  appliance prove it. It has screens and a Tier 1 rationale, and no row here.
- **Mnemonic entry and passphrase entry** (`docs/seed-entry.md`) — `S-3` generates a wallet rather
  than restoring one, so the twelve/twenty-four-word entry path and hold-to-reveal are unexercised.
- **The encrypted wallet QR** (`docs/encrypted-wallet-qr.md`) and its export password.

---

## Run-record template

Copy this into `docs/boot-runs/<date>-<machine>.md` and fill every row. An unanswered row is not an
omission, it is an incomplete record — and this template is the last section of the checklist on
purpose: a template that lives away from its procedure drifts from it.

```markdown
# Boot-checklist run record — <date>

Checklist: `docs/boot-checklist.md` at commit <sha>.

## Image

- ISO: <filename>, <size>
- sha256 (ISO): <digest> — captured <at the moment the medium was written | after the fact, and how>
- sha256 (medium read-back): <digest, or "not taken">
- Verified against: <signed manifest, or "unsigned local build">
- Built from: <commit sha>, `<clean|dirty>`

## Operator

- <name>
- Signing key: <fingerprint, or "unsigned in-repo record">

## Machine

Identified by class, never by serial number — the class is what somebody reproducing this run has
to match.

- Make and model: <e.g. Acer Chromebook 514, CB514-1H-C0FF>
- Platform: <e.g. Intel Apollo Lake>
- Manufactured: <year-month>
- Firmware: <e.g. coreboot + RW_LEGACY SeaBIOS payload; developer mode enabled>
- Firmware path booted: <BIOS | UEFI>
- Secure Boot / verified boot: <state, and whether it can be disabled>
- Camera: <built-in lid webcam | external USB>
- Keyboard: <built-in | external USB>
- Watch-only wallet: <software and version, on what machine>

## Boots

| Boot | Kernel command line | Notes |
|---|---|---|
| Inspection | `rdinit=/bin/sh` <plus the image's own arguments> | |
| Session | <the image's own arguments> | |

## Verdicts

`pass` | `fail` | `deviated`. A `deviated` verdict states its reason in the same row.

| Row | Verdict | Observed |
|---|---|---|
| `I-0` proc and sysfs mounted | | |
| `I-1` mounts | | |
| `I-2` no block device | | |
| `I-3` no storage driver | | |
| `I-4` no network | | |
| `I-5` USB classes | | |
| `I-6` HID and camera only | | |
| `I-7` framebuffer and console size | | |
| `I-7b` framebuffer devices offered | | |
| `I-7c` UEFI framebuffer path | | |
| `I-8` keyboard controller | | |
| `I-9` glyph — `█` received | | |
| `I-9` glyph — `░` missing | | |
| `I-9` glyph — `!` NOT PROVEN marker | | |
| `I-9` glyph — `-` dash | | |
| `R-1` one userspace process | | |
| `R-2` authorized_default | | |
| `S-1` keymap picker | | |
| `S-1b` camera note, verbatim | | |
| `S-2` half-bright | | |
| `S-3` wallet generated | | |
| `S-4` xpub out by QR | | |
| `S-5` three ways in unavailable | | |
| `S-6` PSBT in, slot map | | |
| `S-7` review screen | | |
| `S-8` signed, signature out | | |
| `S-9` broadcast | | |
| `S-10` medium pulled mid-Session | | |
| `S-11` machine stops | | |

## Transaction

- Network: <e.g. testnet4>
- txid: <hex>
- Master fingerprint: <hex>

## Findings

Anything this run learned that the repository did not already state, and where it was written down.
A run that finds nothing says so.
```
