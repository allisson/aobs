# Overview

Orientation for whoever is about to change this code. What the appliance is, what it claims, at what
strength, and where the claims are enforced. `README.md` is the other document: its reader is a
stranger deciding whether to trust a download, and its job is to help them distrust it correctly.
This one's job is to stop the next session from silently weakening a claim.

Read the document that fixes a behaviour before changing that behaviour. A design decision made only
inside a code diff is invisible to the next session. `docs/roadmap.md` is the map of what is settled
and what is open; `CONTEXT.md` is the vocabulary, and its terms are load-bearing.

## What it is

The Amnesic Offline Bitcoin Signer is a Bitcoin signing appliance: a bootable Debian image, run on an
offline machine, used to review and sign a PSBT, then powered off. QR codes are the only data path in
or out. Single-sig, BIP84 and BIP86, Python, [`embit`](https://github.com/diybitcoinhardware/embit).

The counterparty is an untrusted watch-only wallet — Sparrow, Blockstream, Blue Wallet — holding the
exported xpub, building unsigned PSBTs and broadcasting signed ones. *Untrusted* is load-bearing:
everything the appliance shows the user is derived from the PSBT and the appliance's own keys, never
from what the watch-only wallet asserts.

## The claims, and their exact strength

This project's credibility is the difference between what it promises and what it can show. Three of
the claims below are **structural** — they cannot be violated because the mechanism does not exist.
The rest are **absence** claims: the mechanism is not in the image. An absence claim is weaker. It is
checkable by a stranger with `find` and `ls`, and it can be defeated by an adversary who already has
code execution on the appliance.

Say which kind you mean. A sentence that does not is not yet a claim.

| Claim | Strength | How a stranger checks it |
|---|---|---|
| Exactly one userspace process exists for the whole session | **Structural** — the app is PID 1, there is no init system to start a second | `ls -d /proc/[0-9]*` |
| No filesystem is mounted beyond tmpfs and pseudo-filesystems | **Structural** — the whole rootfs is the initramfs; there is nothing to mount from | `cat /proc/mounts` |
| The boot medium is never read after boot | **Structural** — firmware reads it before Linux starts; pull the stick out and keep signing | pull the stick out |
| No network interface, and no tool to configure one | **Absence** — no `kernel/net`, no `drivers/net`, no `iproute2` | `ls /lib/modules/*/kernel/net`, `command -v ip` |
| No block device, so nothing can be written to a persistent medium | **Absence** — storage drivers are not in the image; the block layer itself is in Debian's kernel | `ls /sys/block`, `ls /lib/modules/*/kernel/drivers/{ata,nvme,scsi}` |
| USB binds nothing but HID and UVC | **Absence + policy** — only those modules ship, and `authorized_default=0` after our own devices enumerate | `ls /lib/modules/*/kernel/drivers/usb`, `cat /sys/bus/usb/devices/usb*/authorized_default` |
| Nothing recoverable from RAM after power-off | **Best-effort, not promised** — no byte-zeroing | not checkable; stated as a limit |
| The published ISO is byte-identical to an independent rebuild | **Checkable by rebuilding** | `sha256sum`, against the signed manifest |

Three of these are weaker than they were in this project's Alpine ancestry, where a hand-written
kernel config compiled out networking, modules and the block layer entirely. `docs/adr/0001-debian-base-and-stock-kernel.md`
records why that was traded away and what was bought with it. Do not restate either as structural.

The strongest claim is the last one, and it is the one the project actually rests on: the signature
tells you who to blame, the rebuild tells you whether to. `docs/reproducible-build.md` states the
contract numbered and checkable.

## The appliance is not self-verifying

The version row on the first screen identifies; it does not attest. A modified image can print
anything, and a self-report by a possibly-modified image is not evidence about itself. Nothing on the
appliance verifies the appliance. Verification happens off it, before boot, against a signed manifest
from a key you got somewhere else.

## Architecture

One rule carries weight and a test enforces it: **`aobs/core/` may not import any adapter,
`aobs.ui`, or `aobs.ports`.**

| | |
|---|---|
| `aobs/core/` | The pure core. Bytes in, value objects out. No I/O, no clock, no ambient state |
| `aobs/core/vendor/` | `embit` and `ur2`, pinned by git SHA. Debian packages neither; vendoring is deliberate |
| `aobs/ports/` | Four ports: `FrameSource`, `Keymap`, `EntropySource`, `Power` |
| `aobs/adapters/fake/` | The harness half of each port: image files, fixed bytes, recorders |
| `aobs/adapters/real/` | The appliance's half: V4L2 capture, `getrandom`, `loadkeys`, power-off |
| `aobs/ui/` | The Textual application: global keys, the failure shape, every screen |
| `aobs/__main__.py` | What PID 1 `exec`s, and the one place the real adapters are named |
| `build/` | The image, the pinned package list, PID 1, and the assertions that fail the build |
| `fixtures/` | Every fixture, and the one script that generates them all |

**The display is not a port.** `SignerApp` *is* the display seam: tests drive the real application
headless through Textual's `run_test()`, and the console adapter runs the very same object.

`embit`'s prebuilt `libsecp256k1` blob exists only in the PyPI wheel, which is why the wheel is not
what gets vendored. Every EC operation on the appliance — derivation, ECDSA, Schnorr, address proof —
runs through Debian's `libsecp256k1-2` via `ctypes`, never embit's pure-Python fallback. The build
asserts the Schnorr and extrakeys symbols resolve in the shipped `.so`, and fails if they do not.

## The image

Debian 13 (trixie), pinned to a `snapshot.debian.org` timestamp — both `trixie` and `trixie-security`,
because the kernel security update lives in the second one — so `apt` resolves to fixed versions
forever. `build/snapshot.env` holds the pin.

Two pinned lists, and `build/verify.py` parses both. `build/apt-versions.txt` is everything Debian can
serve at an acceptable version: the base layout, `python3`, `busybox`, `kbd`/`console-data`,
`libsecp256k1-2`, `python3-qrcode`, `python3-zxing-cpp`, `python3-pil`, and the kernel.
`build/wheel-versions.txt` is the rest of the Python layer — `textual`, `rich`, `cryptography`,
`argon2-cffi` — pinned by version and sha256, because Debian stable ships all four **below** what this
application declares; `docs/adr/0002-python-dependencies-from-pinned-wheels.md` has the numbers and the
trade. Wheels are fetched in the one networked step and installed with `--no-index`, so the build still
touches no network, and `pip` is removed before the initramfs is packed.

In both lists the appliance group is installed into the rootfs, the harness group never is, the
`# @group` markers are machine-readable, and the build fails if a harness package or a package manager
reaches the image.

Four things about the shape, each of them a decision rather than an accident:

**No init system.** `build/init` is PID 1: a short POSIX shell script that mounts the tmpfs and
pseudo-filesystems, puts the console in UTF-8, loads the default keymap so the picker is typeable,
flips `authorized_default=0` on every root hub after our own devices have enumerated and before the
first secret is entered, checks available RAM against the floor, and `exec`s `python3 -m aobs`. No
systemd, no getty, no VT switching, no supervisor. There is no `set -e`: a failure here must be named
on the console and held there, never a silent exit, because an init that dies is a kernel panic the
user cannot read past.

It is not written in Python, deliberately: PID 1 is the one process that cannot be restarted and is
hardest to test, and everything it does is a `mount` or an `echo` into sysfs.

**The whole rootfs is the initramfs**, `cpio | zstd`. No block layer is needed at runtime, which is
what makes "no filesystem is ever mounted" literally true rather than argued. The cost is that every
byte is resident, so the RAM floor is derived from the measured unpacked size by a formula the build
re-derives — the floor and the image cannot drift apart.

**Debian's `linux-image-amd64`, unmodified**, at the same 6.12 LTS series this project used to compile
by hand. The modules tree is then pruned to an explicit allowlist and everything else is deleted,
including all of `kernel/net` and `drivers/net`. The allowlist is generic until a target machine is
characterised: `i915`, `amdgpu`, `nouveau`, `simpledrm`, `uvcvideo`, `usbhid`, plus dependencies. A
`modprobe` blacklist exists as a cheap second line and is **never** cited as the claim; the claim is
that the module is not in the image.

**The build is unprivileged.** `mmdebstrap --mode=unshare` builds the rootfs; nothing needs
`--privileged`. "Requires root on the host" is a real barrier to the independent rebuilds the trust
model depends on.

Busybox is in the image and that is stated rather than hidden. "No shell on the appliance" would
protect nobody: Python is in the image and can `os.execv` anything. The true claim is the one the
build checks — no getty, no VT with a login, no path from the running app to a prompt.

The full `console-data` keymap set ships, at a real cost in resident RAM. The keymap picker exists
because a user on AZERTY or ABNT2 typing a BIP39 passphrase through a US map creates a wallet they can
never reopen, with no error and no signal. That failure is silent and unrecoverable; a curated
allowlist would trade a hard promise for a soft number, and the person outside the list is exactly the
person the picker was built for.

## Testing

Four tiers, and the split is what keeps skew failing in CI rather than on the appliance:

1. **Fast suite** — runs anywhere, on any Python. The core, the ports against fakes, the app headless.
2. **Authoritative tier** — `debian:trixie-slim` at the same pinned snapshot, installing *the exact
   versions the ISO installs*, from both pin files and with wheels resolved `--no-index` the way the
   image resolves them. Whatever `pip` gives a dev machine is precisely the drift this tier catches.
3. **Reproducibility guard** — builds twice under deliberately hostile variation and fails on any
   differing byte. Runs on `build/**` changes.
4. **Regtest suite** — needs a `bitcoind`. Opt-in, outside the default loop.

Every build-time assertion lives in `build/verify.py` as pure functions, each one fed a deliberately
broken input by the suite to prove it still bites. The build **fails rather than warns** at the first
stage where a published claim stops being true.

## Where things are settled

`docs/roadmap.md` is the map: what is settled, what is open, what order. In the repo on purpose, so a
design decision is reviewable in the same diff as the change it authorises — which a tracker issue
cannot be.

| Document | Fixes |
|---|---|
| `docs/adr/0001-debian-base-and-stock-kernel.md` | The base OS and the kernel, and what the switch cost |
| `docs/adr/0002-python-dependencies-from-pinned-wheels.md` | Where the Python layer comes from, and where a prebuilt blob may live |
| `docs/boot-pipeline.md` | The build's stages, PID 1, the module allowlist, the RAM floor |
| `docs/threat-model.md` | Adversary tiers, and every claim above at its stated strength |
| `docs/reproducible-build.md` | The reproducibility contract and the divergence sources it fixes |
| `docs/test-harness.md` | The four tiers and what each one is authoritative for |
| `docs/release.md` | The release ritual, the manifest, the release-mode refusals |
| `docs/boot-checklist.md` | The checks only a booted appliance can answer |
| `docs/psbt-review-model.md`, `docs/review-screen.md` | The proof rule, the three output categories, the screen |
| `docs/seed-entry.md`, `docs/secret-hygiene.md` | Mnemonic and passphrase entry, and how secrets are handled |
| `docs/address-verification.md` | Address display and the proof behind it |
| `docs/entropy-mixing.md` | What "strong entropy" promises |
| `docs/export-password.md`, `docs/encrypted-wallet-qr.md` | The eight-word export password and what it protects |
| `docs/qr-emit-parameters.md`, `docs/scan-feedback.md` | The QR channel in both directions |
| `docs/network-selection.md` | Mainnet, testnet, signet |
| `docs/failure-states.md` | The one shape every refusal is drawn in |

## Ancestry

This is a restart of an Alpine-based project that compiled its own kernel. The Python application,
its tests and its app-level documents carry over essentially unchanged; the build and the operating
system were rewritten. What the switch bought and what it cost is in
`docs/adr/0001-debian-base-and-stock-kernel.md`, and the three weakened claims are marked as such in
the table above and in `docs/threat-model.md`. The predecessor never cut a release and was never
booted on real hardware — which is why `docs/roadmap.md` puts a hardware boot ahead of everything
that is not needed to reach one.
