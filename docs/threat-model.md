# Threat model

Who this appliance defends against, who it does not, and every claim it makes at the strength it
actually has.

The unit is the **adversary tier**, not the attack. `CONTEXT.md` fixes the three: **Tier 1** is
defended with a testable defence, **Tier 2** is acknowledged with stated limits and explicitly not
defended, **Tier 3** is accepted risk with no defence implied. Naming an adversary without its tier
says nothing — "we considered it" and "we stop it" are different statements — and the tier is what
separates them.

Two rules govern every sentence below, and both are enforced elsewhere in the repository rather than
by good intentions here:

- **A claim without a strength is not yet a claim.** *Structural* means the mechanism does not
  exist, so the claim cannot be violated. *Absence* means the mechanism is not in the image:
  checkable with `ls`, defeatable by an adversary already executing code here. *Best-effort* means
  neither, and is stated as a limit rather than a promise.
- **This project's ancestry was stronger in three places and this document does not inherit that.**
  The Alpine predecessor compiled out networking, modules and the block layer; Debian's stock kernel
  has all three. `docs/adr/0001-debian-base-and-stock-kernel.md` records the trade. Restating one of
  those as structural is a defect, not a wording preference.

**The claim numbers are stable and load-bearing.** Claims (i) through (iii) are the three guarantees
that `CONTEXT.md`'s *Amnesic* entry names, in that entry's order. Code and tests cite them by
number — `aobs/ui/app.py`, `aobs/adapters/real/power.py` and
`tests/test_app_shell.py::test_the_key_material_the_app_holds_is_wiped_before_the_machine_stops` all
name claim (ii); `docs/secret-hygiene.md` names claim (iii). Renumbering breaks those references.
Append; do not reorder.

## The claims

| # | Claim | Strength | How a stranger checks it |
|---|---|---|---|
| (i) | Nothing a Session does is written to a persistent medium | **Structural** for the mounting, **absence** for the drivers | `cat /proc/mounts`, `ls /sys/block` in an inspection boot |
| (ii) | Nothing is recoverable from RAM after power-off | **Best-effort, not promised** | not checkable; stated as a limit |
| (iii) | Nothing is recoverable from RAM during the Session by another process | **Structural** | read `build/init`, which ends in `exec python3 -m aobs` |
| (iv) | No network interface, and no tool to configure one | **Absence** | `ls /lib/modules/*/kernel/net`, `command -v ip` |
| (v) | USB binds nothing but HID and UVC, and nothing is authorized once the appliance is up | **Absence + policy** | `ls /lib/modules/*/kernel/drivers/usb`; the write in `build/init` |
| (vi) | The boot medium is never read after boot | **Structural** | pull the stick out mid-Session and keep signing |
| (vii) | The final 256 bits behind a mnemonic are no weaker than the strongest single contributing source | **Construction, stated and testable** | `docs/entropy-mixing.md`, `tests/test_entropy.py` |
| (viii) | An output is shown as change only when the appliance can prove it | **Construction, stated and testable** | `docs/psbt-review-model.md`, `tests/test_adversarial_corpus.py` |
| (ix) | The published ISO is byte-identical to an independent rebuild | **Checkable by rebuilding** | `sha256sum` against the signed manifest |
| (x) | Nothing verifies the boot medium before the kernel runs | **Not a claim — a stated absence of one** | see *The firmware is not the appliance* |

`docs/overview.md` carries the same table for a reader who has not got this far, phrased for a
stranger. Where the two disagree, this document is wrong until fixed: the overview is a summary and a
summary that has drifted is a defect in the summary.

### (i) Nothing is written to a persistent medium

Two mechanisms at two strengths, and they must not be quoted as one.

**The mounting half is structural.** The entire root filesystem is the initramfs, unpacked into
tmpfs. There is no filesystem to mount from, so no write can be directed at one — `build/init`
mounts `proc`, `sysfs`, `devtmpfs`, `devpts` and three tmpfses and nothing else, and there is no
subsequent `mount` for anything to reach.

**The driver half is absence.** No storage driver is in the image: `build/modules.allow` names none,
and `build/prune_modules.py` deletes every module outside the allowlist's dependency closure, so
`ata`, `nvme` and `scsi` are not on the medium at all. This is weaker, and the difference matters:
Debian's kernel *has* a block layer, so an adversary already executing code on the appliance is not
stopped by this — they are stopped by there being no driver to bind, which is a fact about a
directory listing rather than about the kernel's capabilities.

### (ii) Nothing is recoverable from RAM after power-off

**Best-effort. This is a limit, not a promise, and it is the weakest claim in the document.**

There is no byte-zeroing. What exists is a wipe of **the derived key material the app itself holds**
— `SignerApp` drops the retained references to the wallet, mnemonic, mixing state, export state and
scanned payload — and it runs *before* the power-off, because `aobs/adapters/real/power.py` issues
`reboot(2)` with `RB_POWER_OFF` and does not return. The ordering is the whole of what can be
asserted, and it is asserted, by the test named above, against a recording fake.

**What "best-effort" is conceding.** CPython copies `bytes` and `str` freely; the copies cannot be
counted, let alone overwritten. So dropping references reduces what a cold-boot attacker finds by an
amount nobody can quantify, and a full RAM overwrite was rejected as theatre rather than deferred as
work — `docs/secret-hygiene.md` records both rejections and the facts behind them. A reader who takes
this row as erasure has been misled; the word in every citation of it is *best-effort*, deliberately.

The mitigation that actually applies is procedural and belongs to the operator: power the machine
off, and do not hand it to somebody within seconds of doing so.

### (iii) Nothing is recoverable from RAM during the Session by another process

**Structural, and it has two halves.**

**No other process exists.** The appliance runs exactly one userspace process: PID 1, which is the
application. `build/init` ends in `exec python3 -m aobs`; there is no init system, no getty, no
daemon and no shell. The claim needs no defence because the thing it defends against cannot be
instantiated — there is nothing to open `/proc/self/mem` with. A stranger checks this by reading
`build/init` against the assertions in `build/verify.py` that every command in it resolves on PID 1's
own `PATH`. **Not** by counting `/proc/[0-9]*`: see *Inspection boot* in `CONTEXT.md` for why that
number describes the stranger's own shell.

**And the process is never dumped.** A core dump writes the address space out, which would defeat the
first half from inside. That is answered in the pinned kernel's configuration and in `build/init`
rather than by trusting the process to behave well; `docs/secret-hygiene.md` owns the detail.

### (iv) Offline

**Absence.** `kernel/net` and `drivers/net` are deleted from the modules tree, and no `iproute2`,
`ifupdown`, `wpasupplicant`, `curl`, `wget` or `ssh` is installed. `build/verify.py`'s
`no_network_module_in_tree` fails the build if one survives.

Not *disabled*. Nothing is turned off, because there is nothing there to turn off, and "disabled"
promises a switch someone could flip back. The `modprobe` blacklist beside the allowlist is a second
line and is never what the claim rests on. The stronger reading — no network stack in the kernel —
was true of the Alpine ancestry and is **no longer true**.

### (v) USB binds nothing but HID and UVC

**Absence for the drivers, policy for the authorization.** `build/modules.allow` ships the four USB
host controllers, `usbhid`, `hid_generic` and `uvcvideo`; storage, networking, audio, printer and
serial class drivers are not in the image. Then `build/init` writes `authorized_default=0` to every
root hub **after** the appliance's own devices have enumerated, so a device plugged in during a
Session gets no driver bound.

Three things this claim does not say, each of which has been stated wrongly before:

- **Not "no USB".** The camera is a USB device and so is an external keyboard, and the kernel
  enumerates and binds a driver to both. Two classes, not one.
- **Not "USB is restricted to HID".** A webcam is USB *Video* Class. That wording was false and must
  not come back.
- **Not "all input is USB".** On a laptop the keyboard is typically behind a built-in i8042
  controller, which `CONFIG_SERIO_I8042=y` and `CONFIG_KEYBOARD_ATKBD=y` put in the kernel image
  itself — outside the allowlist's reach and outside `authorized_default=0`. That is how the machine
  in `docs/boot-runs/` was driven: keystrokes never touched USB. The claim does not weaken, because
  an i8042 controller has two fixed ports on an embedded controller and no arbitrary-class hotplug,
  but it is a claim about **what USB binds** and never about where keystrokes come from.

The `authorized_default=0` half is checked at source level — the write in `build/init` — and not by
reading the value in an inspection boot, where `build/init` never ran.

### (vi) The boot medium is never read after boot

**Structural.** Firmware reads the medium before Linux starts; the kernel and the initramfs are in
RAM by the time PID 1 exists, and nothing on the appliance opens the medium again. `build/grub.cfg`
is embedded into a standalone `bootx64.efi` rather than read from the ISO, so not even the
bootloader's configuration is fetched after that point.

The check is physical and it is the cheapest one in the repository: pull the stick out mid-Session
and keep signing. The boot medium is **not** storage — nothing is ever written to it — and calling it
storage is what makes people think this claim needs defending.

### (vii) Strong entropy

**The final 256 bits are no weaker than the strongest single contributing source, and no single
source can drag them down.** HKDF-Extract-then-Expand over a length-prefixed, domain-separated
concatenation of the conditioned sources; `docs/entropy-mixing.md` owns the construction and
`tests/test_entropy.py` owns the evidence.

**RDRAND is never a sole or direct source**, which is why the appliance boots with
`random.trust_cpu=off` and `random.trust_bootloader=off`. Left at their defaults — both are *on* —
the kernel would initialise its RNG from RDRAND or a bootloader-supplied seed alone, and this
document's floor would quietly rest on a CPU instruction nobody can audit.

### (viii) The proof rule

**The appliance shows an output as change only when it can prove it, and treats everything else as
money leaving.** This is the Tier 1 defence and it is stated as a claim because it is the one thing
the appliance does that a compromised counterparty cannot talk it out of. `docs/psbt-review-model.md`
owns the model, `docs/review-screen.md` the screen, `tests/test_adversarial_corpus.py` the evidence.

### (ix) Reproducibility

**Checkable by rebuilding**, and it is the claim the project actually rests on: the signature tells
you who to blame, the rebuild tells you whether to. Due in M4; `docs/reproducible-build.md` will own
it. Until an independent rebuild exists, see Tier 2's *pre-trust* entry — the mechanism being
checkable is not the same as its having been checked.

### (x) Nothing verifies the boot medium before the kernel runs

**This row is in the table so that its absence is on the record, not to make a claim.** See below.

## Tier 1 — defended, with a testable defence

**The watch-only wallet, and everything that arrives over the QR channel.**

This is the adversary the appliance was built for, and it is not hypothetical: the watch-only wallet
sends attacker-controlled bytes into the appliance every single Session. The QR channel is the only
inbound data path, and every byte on it is treated as hostile.

| Attack | Defence | Evidence |
|---|---|---|
| **Change-address attack** — a PSBT output that claims one of our change paths so the user waves through money leaving | The proof rule: the appliance reproduces the output's script from its own seed at a path it recognises. A `PSBT_OUT_BIP32_DERIVATION` field is *input to that check, never the answer* | `tests/test_adversarial_corpus.py`, `fixtures/generate.py` |
| **Collapsing three output categories into two** | **NOT PROVEN degrades to payment, never to change** — the failure mode is a user scrutinising an output that turned out to be their own, never a user waving through an attacker's | `tests/test_review.py`, `tests/test_review_text.py` |
| **A lied-about receive address** — the mirror of the change-address attack, on the receive side | Scan and prove: the user scans the address and the appliance answers *this is yours, at `m/84h/0h/0h/0/7`*, or it is not. The human is removed from the comparison rather than given a prettier one | `docs/address-verification.md`, `tests/test_address.py` |
| **Escape and control-character injection** in any attacker-supplied string | `aobs/core/text.py` strips C0, DEL and C1 in the core — removed, not escaped, and never left to what a renderer happens to do | `tests/test_address_screens.py`, `docs/test-harness.md` |
| **Malformed, oversized or adversarial QR payloads** | Decoded in the core against a corpus built to break it; a refusal is drawn in the one shape `docs/failure-states.md` fixes | `tests/test_adversarial_corpus.py`, `tests/test_urcodec.py` |

**What makes this Tier 1 rather than Tier 2 is the last column.** Each row names a test that fails if
the defence stops working. A defence with no executable evidence behind it belongs one tier down, and
moving it up because it feels solid is the failure this ranking exists to prevent.

## Tier 2 — acknowledged, limits stated, explicitly not defended

Everything here is real, none of it is defended, and saying so is the point. A Tier 2 entry that
quietly acquires a half-defence must move tier or lose the half-defence; it may not stay here with a
reassuring sentence attached.

**Someone in the room.** The passphrase is masked by default with a hold-to-reveal key, which puts it
on screen deliberately: a passphrase silently mistyped through the wrong keymap is a total loss, and
that is the worse failure. Shoulder-surfing is not defended. Nor is a camera pointed at the screen
while a mnemonic is displayed, or while the encrypted wallet QR is on it.

**The firmware under the appliance.** See the section below — this is the entry the hardware run made
concrete, and it is the largest one in this tier.

**The boot medium between builds.** Nothing on the appliance verifies the appliance
(`docs/overview.md`). The version row on the first screen identifies; it does not attest, and a
modified image can print anything. Verification happens off the appliance, before boot, against a
signed manifest and a key obtained somewhere else. An attacker who can rewrite your USB stick between
two of your Sessions is not defended against by anything in the image, by construction — a
self-report by a possibly-modified image is not evidence about itself.

**RAM remanence after power-off.** Claim (ii)'s concession, restated here so it appears in the tier
list and not only in the claim list. Cold-boot attacks are not defended against.

**A tampered published ISO, before an independent rebuild exists.** The reproducibility contract is a
*testable* defence, which would make it Tier 1 — but a defence nobody has exercised is not evidence,
and at v0.1.0 nobody outside this project has rebuilt the image. That is a **pre-trust** claim in
`CONTEXT.md`'s sense: a statement about what has been observed, carrying the condition that retracts
it. This entry moves to Tier 1 when a witness build exists, and not before.

## Tier 3 — accepted risk, no defence implied

**The build host and the maintainer.** If the machine that builds the ISO is compromised, or the
person holding the signing key is dishonest, nothing in this design helps you. Reproducibility lets a
third party detect a divergence between the published artefact and the published source; it says
nothing about the source. There is one maintainer and one key.

**Debian's archive and the pinned wheels.** The appliance is built from pinned Debian packages and
pinned wheels, and their contents are trusted as given. `docs/adr/0002-python-dependencies-from-pinned-wheels.md`
records where a prebuilt blob may live and why. A backdoor inside `libsecp256k1` or inside the kernel
is not something this project can detect.

**Coercion, and the operator.** A wrench, a subpoena, or an operator who chooses to exfiltrate the
mnemonic by reading it aloud. The appliance's amnesia is about what the machine keeps, never about
what a person does with what they saw.

**Hardware implants and physical side channels.** A hardware keylogger between the keyboard and the
controller, an implant on the mainboard, electromagnetic or acoustic emanation. Not detected, not
defended, no claim.

## The firmware is not the appliance

The machine in `docs/boot-runs/` is an Acer Chromebook 514 (`CB514-1H-C0FF`), booted from a USB stick
through **coreboot's `RW_LEGACY` SeaBIOS payload, with the machine in developer mode**. Three things
follow, and they are Tier 2 items rather than defects:

**There is no boot-integrity check on the medium — claim (x).** SeaBIOS boots what it is pointed at.
Secure Boot is not supported in v0.1 on any machine: `build/grub.cfg` says so, and the firmware
setting has to be off even on the UEFI path. So on every host, the integrity of what boots is
established *before* the stick is written, by verifying the ISO against the signed manifest, and
never by the machine. This is not a weakened claim; it is the absence of one, and the absence is
stated so that nobody infers a claim from the appliance's other structural properties.

**Unlocking a Chromebook lowers that host's boot integrity permanently.** Developer mode is a
persistent, visible modification: it survives power cycles, it announces itself at every boot, and it
opens the machine to an evil maid far more cheaply than a stock ChromeOS device. Booting this
appliance on that host is a trade the operator makes, and it is a cost of the hardware path rather
than a property of the image. An appliance whose pitch is that you can verify what it is should say
plainly what it asks of the machine underneath.

**Firmware is outside every claim in this document.** The appliance's claims begin when the kernel
starts. Nothing above defends against a modified `RW_LEGACY` payload, a reflashed full ROM, or an
implant in the embedded controller — and on a machine whose write protect has already been defeated
to make room for this appliance, that adversary got cheaper, not more expensive.

## Out of scope for this document

- **Screen layout and wording.** `docs/review-screen.md`, `docs/failure-states.md`,
  `docs/console-appearance.md` and `docs/scan-feedback.md` own what is drawn. This document owns what
  must be *true*, never what it looks like.
- **The build's stages and PID 1.** `docs/boot-pipeline.md`.
- **The reproducibility contract.** `docs/reproducible-build.md`, due in M4. Claim (ix) states the
  promise; that document states the mechanism and the divergence sources it fixes.
- **The checks only a booted appliance can answer.** `docs/boot-checklist.md` is the procedure and
  `docs/boot-runs/` holds the evidence. This document says which claims a boot can settle; it does
  not settle them.
