# Boot pipeline

How `bitcoin-signer-amd64.iso` is built, what it contains, and what happens between power-on and the
first screen.

Release engineering — the reproducibility contract, the input archive, signing keys, the release
ritual — is `docs/reproducible-build.md` and `docs/release.md`. This document is how the image is
built and what happens between power-on and the first screen, written precisely enough that building
it is mechanical.

**Where each decision below now lives**, since a decision readable only in a diff is invisible to
the next session:

| | |
|---|---|
| the pinned base, as one timestamp | `build/snapshot.env`, `build/apt-repositories` |
| what the rootfs gets, and what only the harness gets | `build/apt-versions.txt`, `build/wheel-versions.txt` |
| every byte the build consumes | `build/fetch-inputs.sh`, `build/inputs.sha256` |
| PID 1 | `build/init` |
| the stages | `build/mkiso.sh` |
| the fixed cmdline, per firmware path | `build/isolinux.cfg`, `build/grub.cfg` |
| every build-time assertion, as pure functions | `build/verify.py` |
| each assertion fed a deliberately broken input | `tests/test_build_verifier.py` |

**This document was Alpine's and is now Debian's.** `docs/adr/0001-debian-base-and-stock-kernel.md`
records the switch and what it cost. The cost that matters here is that **several claims dropped from
*structural* to *absence*** — the old kernel was configured so that the mechanism did not exist; the
new one is Debian's, and the mechanism exists but is not in the image. `docs/overview.md` tabulates
which claim is which, and `CONTEXT.md` defines the three strengths. Restating one of these as
structural is a defect, not a rounding error.

## Build

`build/mkiso.sh`, running unprivileged. Five stages:

1. **Rootfs.** `mmdebstrap --mode=unshare`, installing the `@group appliance` closure from
   `build/inputs/deb/appliance/` through a `file://` repository. No network, no `--privileged`.
2. **Python layer.** `pip --no-index --target /opt/aobs-python` from `build/inputs/wheels/appliance/`,
   then the transient `pip` and everything it dragged in are purged.
3. **Kernel.** `dpkg-deb -x` of `build/inputs/deb/kernel/` into a staging directory. `vmlinuz` goes
   to the ISO; `/lib/modules` is pruned to the allowlist and copied into the rootfs.
4. **Initramfs.** `find /rootfs | cpio -H newc | zstd`.
5. **Image.** `xorriso` into a hybrid ISO: `isolinux` for legacy BIOS, `grub-efi` for UEFI.

Every input is a pinned version with a checksum and every byte comes from `build/inputs/` over no
network at all. `build/fetch-inputs.sh` is the one networked step and it is not part of any build.

### The build is unprivileged, and that was verified rather than assumed

`mmdebstrap --mode=unshare` needs unprivileged user namespaces, which are a property of the host
kernel and its AppArmor policy — not of mmdebstrap, and not checkable by reading. Ubuntu 24.04 ships
`kernel.apparmor_restrict_unprivileged_userns=1`, which denies exactly the `unshare(CLONE_NEWUSER)`
the mode is named after, so this was not a safe assumption.

**Measured on `ubuntu-24.04`, 2026-09-07: it works.** A bootstrap completed with no `--privileged`.

"Requires root on the host" is a real barrier to the independent rebuilds the trust model depends
on, so `--privileged` is not an escape hatch available to this build. If unshare mode ever stops
working, that is a finding to be written down here, not a licence.

**Two constraints on stage 1 came out of that verification**, and both are about apt rather than
about namespaces:

- The `.deb` pool must be **readable by the `_apt` user**. apt's `file://` method drops privileges
  before reading, so a pool under a `0700` home directory fails with `Permission denied` on every
  `Packages` file and never says why.
- `APT::Sandbox::User "root"` is set, so apt does not drop to a user that cannot read the pool the
  build handed it.

### Why the appliance closure is resolved against an empty root

`build/inputs/deb/appliance/` must be **the complete closure for a rootfs that starts from nothing**,
because that is what stage 1 starts from.

This was wrong for the whole of M1 and nothing noticed, because the one consumer at the time —
`build/Dockerfile.test` — starts *from* `debian:trixie-slim` and so never missed what that image
already had. `fetch_debs` resolved inside that same container, and `--reinstall` re-downloads the
packages *named on the command line* and never a transitive dependency apt considers already
satisfied. The pool held **37** packages where the real closure is **57**: no `libc6`, no `dpkg`, no
`tar`, no `debconf`, no `tzdata`, no `libpam-*`. The first `mmdebstrap` run against it failed with
forty unsatisfiable dependencies.

`build/fetch-inputs.sh` now resolves with `Dir::State::status` pointed at an empty file. What is
installed in the container that does the resolving is not a fact about the appliance.

### Why the kernel is extracted and never installed

`linux-image-amd64` is fetched into its own pool, **unresolved**, with `apt-get download`, and
`dpkg-deb -x`'d in stage 3. dpkg is never told a kernel was installed, so no maintainer script runs
and no bootloader is invoked.

Letting apt resolve it drags in the machinery for building the very thing this project builds
itself. Measured: `linux-image-amd64` → `linux-image-6.12.107+deb13-amd64` → `initramfs-tools` →
`udev` → `systemd`. The appliance closure is 78 packages with the kernel in it and contains
`systemd`, `udev`, `initramfs-tools`, `libsystemd-shared` and `dracut-install`; without it the
closure is 57 and contains none of them. **An appliance whose first published claim is that it has
no init system was one `apt-get install` away from shipping one.**

This is also what the design already said: the whole rootfs *is* the initramfs, so the kernel is a
file sitting beside it on the ISO rather than a package inside it.

`libsystemd0` and `libudev1` **do** remain in the closure, pulled by `util-linux`. Those are shared
libraries, not daemons: there is no `systemd` running as PID 1 and no `udevd` in the image. "No
systemd" and "no `libsystemd0`" are different statements and only the first one is true.

`linux-image-amd64` is a 1468-byte metapackage carrying no kernel, so the concrete image package is
derived from it with `apt-cache depends` — a lookup against the index, never a resolution — rather
than pinned a second time. Two lines naming one kernel is two places for one fact.

### The release identity file

Stage 1 also writes **`/etc/aobs-release`** — the version, the commit, the formatted build date and
whether the tree was dirty. It is a stage-1 output specifically so that stage 4, before `cpio`, can
assert it against `git describe --exact-match --tags` while it is still a file a human can open.
What the appliance does with it is the footer row below.

## Boot sequence

Firmware loads kernel + initramfs. **After that the boot medium is never read again and can be
pulled** — that is the amnesia claim's cheapest check, and it stays a claim until someone has done
it on real hardware.

Kernel cmdline, fixed in the bootloader config:

- `random.trust_cpu=off random.trust_bootloader=off` — both default on, and leaving them there would
  rest the entropy floor claim on RDRAND. `docs/entropy-mixing.md` states what that floor promises.
- `vga=791` on the BIOS path — see *Console* below.
- `panic=0` — hang rather than reboot. There is nothing to reboot into, and a reboot loop flashes
  the failure past the user.

**PID 1 is a short POSIX shell script that ends in `exec python3 -m aobs`,** so the app itself is
PID 1 for the session. There is no init system, no `inittab`, no getty, no VT switching. The script
does only what nothing else can, in this order:

1. Mount `proc`, `sys`, `dev`, `devpts`, `shm` — tmpfs and pseudo-filesystems only.
2. Put the console in UTF-8 and **load the default keymap**, so the picker is typeable before it
   draws.
3. **Flip `authorized_default=0` on every root hub** — after our own devices enumerate, before the
   first secret is entered.
4. **Set `kernel.modules_disabled=1`.** One-way for the life of the boot; see below.
5. Check available RAM against the floor and refuse to start below it.
6. `exec` the app.

**There is no `set -e`.** Each step checks its own result and a failure is named on the console and
held there. An init that dies is a kernel panic the user cannot read past, so a silent exit is the
one outcome this script may not have.

It is not written in Python, deliberately: PID 1 is the one process that cannot be restarted and is
hardest to test, and everything it does is a `mount` or an `echo` into sysfs.

### Containment, stated so it can be checked

**There is no getty, no VT with a login, and no path from the running app to a prompt.** If the app
exits, the kernel panics on init death rather than dropping to a shell.

**The module claims are *absence*, and this is where Debian's kernel changed the strength.** The
Alpine predecessor built `CONFIG_MODULES=n`, `CONFIG_NET=n`, `CONFIG_MAGIC_SYSRQ=n` and exactly two
built-in USB class drivers, and every one of those was checkable by reading one file in the repo.
Debian's stock kernel has all of them as `y` or `m`, and this project does not control that config.
So:

- **No network interface and no tool to configure one.** `kernel/net` and `kernel/drivers/net` are
  deleted from the modules tree, and no `iproute2` is in the image. The network *stack* is compiled
  into Debian's kernel and is not removable. This is absence, not structure.
- **No block device.** Storage drivers are not in the image; the block layer itself is in Debian's
  kernel.
- **USB binds nothing but HID and UVC.** Only those modules ship, plus `authorized_default=0`.

**`kernel.modules_disabled=1` is a second line, and is never cited as the claim.** `CONFIG_MODULES=y`
reopened a door the old kernel had welded shut: with a loadable-module kernel, a `.ko` that is not in
the image is not the same as a `.ko` that cannot be loaded. The sysctl is irreversible once set and
costs one line in PID 1, so it closes that gap for the life of the session. A `modprobe` blacklist
exists for the same reason and with the same standing. **The claim is that the module is not in the
image**; these two make it expensive to be wrong about, and neither is evidence for it.

**Busybox `sh` is present in the image, and that is not a hole worth closing.** "No shell on the
appliance" would be a claim that protects nobody — Python is in the image and can `os.execv`
anything. The claim above is the true one.

**Not defended: a person at the bootloader typing `init=/bin/sh`.** Stated rather than papered over,
and it costs nothing — a fresh boot holds no secrets, which is the point of the amnesia claim.

## Console

**`fbcon` over firmware framebuffers** — `simpledrm` on UEFI, `vesafb` on BIOS. The module allowlist
carries `i915`, `amdgpu`, `nouveau` and `simpledrm`; it stays generic until a target machine is
characterised, at which point it is narrowed or the reason it stays generic is recorded.

**Legacy BIOS needs `vga=791`, and this is not cosmetic.** `vgacon` gives 80×25 text, and the QR
display is fixed at **85 columns × 43 rows** — so a BIOS boot in text mode could not display a QR
code at all. With `vga=791` (1024×768) `vesafb` provides a graphical framebuffer and `fbcon` gives
128×48. **1024×768 is therefore the resolution floor on both firmware paths.**

#### The release identity footer

The picker carries **one reserved row** at the bottom, and a second line pointing at the advisories:

```
aobs v0.1.0 · 4f1c8a6e2b90 · 2026-09-14
Advisories are published at github.com/allisson/aobs/blob/main/ADVISORIES.txt — this appliance cannot check.
```

Here rather than on an About screen because **a screen you must navigate to is a screen nobody
visits**, and this is meant to reach someone who booted a stick found in a drawer and did not think
to look. The same row is repeated by every failure screen, because a bug report carrying no build
identity is a bug report about nothing.

The **12-hex commit prefix** is what makes the row worth showing: a version alone cannot distinguish
a rebuild from the published build, while the prefix can be matched against a manifest the user has
already verified.

**It identifies, it does not attest.** A modified image can print anything, and the README says so in
those words. Nothing derived from the image can be embedded in it — not the ISO hash, not the
manifest hash, and not the initramfs hash either, since the initramfs *is* the whole system — so
version, commit and `SOURCE_DATE_EPOCH` are the complete embeddable set.

A build that is not at a clean tag shows `DEVELOPMENT BUILD` in place of the version, never a
version-shaped string, plus a `-dirty` suffix on the commit when the tree was not clean. The
stage-4 assertion is **skipped for those, not faked.**

### Keyboard layout

**The full `console-data` keymap set ships, with a picker as the first screen, defaulting to US.**

Not US-only. BIP39 words and the EFF export words are `a–z` and survive almost any Latin layout, but
**the BIP39 passphrase is arbitrary text**. A user on AZERTY or ABNT2 who types a passphrase through
a US map creates a wallet they can never reopen — no error, no signal, discovered when the funds are
gone. That is the worst failure mode in the appliance. A curated allowlist would trade a hard promise
for a soft number, and the person outside the list is exactly the person the picker was built for.

The picker is also where the map is proven right: **echo keys as typed, before any secret is
entered.**

**Debian's keymap names are not xkb's, and this bit once already.** `console-data` ships the
traditional console naming — `uk`, `br-abnt2`, `dvorak` — where the Alpine ancestry used `gb`, `br`,
`us-dvorak`. `offered()` filters the preference list to what is actually installed, so wrong names do
not raise: the picker silently offered `us, de, fr, es, it`, having dropped **ABNT2**, which is the
worked example above. Names in `aobs/adapters/real/keymap.py` are checked against the image's own
map tree, not against memory.

## Dependencies

**If Python imports it, it comes from `pyproject.toml`; everything else comes from Debian.** No
package is pinned twice and no dependency has two resolvers.

| source | what |
|---|---|
| `build/apt-versions.txt` | the operating system: `dash`, `busybox`, `util-linux`, `python3`, `libsecp256k1-2`, `kbd`, `console-data`, the kernel |
| `build/wheel-versions.txt` | the Python layer, hash-pinned, derived from `pyproject.toml` and `uv.lock` |
| vendored in the app tree | **`embit`** and **`ur2`**, pinned by git SHA — Debian packages neither |

`docs/adr/0002-python-dependencies-from-pinned-wheels.md` has the numbers and says why the layer is
not split package by package: two resolvers over one import graph reconcile nothing.

**No `python3-*` package may be in the apt list at all**, not merely none that collides with a wheel
today — the collision arrives later, when the wheel is added and nothing re-reads the apt list.
`python3` and `python3-pip` are the two named exceptions, and `pip` is transient.

### The elliptic curve implementation

**Every EC operation on the appliance — key derivation, ECDSA signing, Schnorr signing, address proof
— is performed by Debian's `libsecp256k1`, and never by embit's pure-Python fallback.** This is
recorded because embit does not have one EC implementation: `embit/util/secp256k1.py` picks between a
ctypes binding and `py_secp256k1` inside a bare `except:`, with no message either way.

Debian's `libsecp256k1-2` 0.5.0-2+b1 was pulled from the pinned snapshot and inspected. It exports
`secp256k1_schnorrsig_sign32`, `secp256k1_keypair_create`, `secp256k1_xonly_pubkey_from_pubkey`,
`secp256k1_ecdh` and `secp256k1_ecdsa_sign_recoverable` — BIP86's modules were enabled — and also the
long-deprecated `secp256k1_ec_privkey_negate` alias that the vendored embit's loader binds
unconditionally. No build-from-upstream stage is needed.

**`embit` is vendored from a tagged git commit, not from the PyPI wheel.** That wheel ships a
prebuilt `libsecp256k1_linux_x86_64.so`, and `_find_library()` returns the prebuilt path whenever the
file merely *exists* — it does not fall through when *loading* it fails. Vendoring from source means
`util/prebuilt/` never enters the app tree at all, rather than entering it and being deleted.

**The pin has an upper bound, and it is not cosmetic.** embit binds the schnorr module through the
deprecated alias `secp256k1_schnorrsig_sign`, which upstream renamed to `secp256k1_schnorrsig_sign32`
and **removed outright in 0.8.0**. Against a 0.8.0 or newer library, embit's `except: pass` binds
nothing, the backend still reports as native, and BIP86 signing fails at the moment a user tries to
sign a taproot input. **A future Debian shipping 0.8.0 would break taproot signing silently**, and
`build/verify.py`'s symbol assertion is the only thing standing between that and a pure-Python
signer. This was observed, not reasoned about: Homebrew's 0.7 on a dev host reproduces it.

**`PublicKey.schnorr_verify` must never be called.** embit binds `secp256k1_schnorrsig_verify` with
four arguments; since 0.3.0 the C function takes five, the fourth being `msglen`. embit passes the
x-only pubkey pointer where C reads a length, and the library then dereferences whatever follows — a
**segfault**, not an exception, which no `except:` can catch. The appliance only ever signs, so
nothing calls it today; it is written down because the failure is a crash of the whole appliance
rather than an error anyone can handle.

**This is not a constant-time claim.** `py_secp256k1` is not constant-time, but the appliance runs
exactly one userspace process and has no network, so there is no local observer and no remote peer to
measure. The realistic observer is physical, which is territory where this appliance already promises
nothing.

## Size, and the RAM floor

**The floor is derived by the build from the measured tree, by the formula below, so that the floor
and the image cannot drift apart.**

```
floor = next_power_of_two( 2 × unpacked_rootfs + 64 MiB + 128 MiB )
```

Each term, and which are mechanism and which are headroom:

- **`2 × unpacked_rootfs` is mechanism, not margin.** The whole rootfs is the initramfs, so at boot
  the compressed image and the unpacked tmpfs are resident at the same time.
- **`64 MiB` is Argon2id's transient**, fixed by `docs/export-password.md`.
- **`128 MiB` is headroom** for the Python heap and camera buffers. This is the one estimated term.
- **Rounding to a power of two** is deliberate: the floor is a number a user checks against their
  machine, and a figure like 634 MiB would look measured to a precision nobody has.

**The measured inputs are published against the run they came from** — unpacked rootfs, initramfs,
kernel, ISO — because a floor derived from an unpublished number is an assertion wearing a formula.

> **Not yet measured.** The appliance closure is 57 packages and 26 MiB of compressed `.deb`, and the
> kernel package is a further 107.9 MiB compressed. The *unpacked* rootfs, the packed initramfs and
> the ISO have not been measured, so no floor is stated here yet. The first `mkiso.sh` run fills this
> in with numbers and the run that produced them.

**No pruning of the Python stdlib.** Stripping it buys little against the risk of a missing-module
traceback on an appliance with no recovery path.

**The full `console-data` set costs real resident RAM**, and the number goes here once measured. It
is paid deliberately; see *Keyboard layout*.

## Failure

**The app catches its own top-level exceptions**, wipes the derived key material, shows a plain
screen naming the failure, and waits for a keypress before forcing power-off. A genuine
interpreter-level crash panics the kernel and hangs there (`panic=0`).

The failure the user must never see is a **silent power-off with no explanation** — indistinguishable
from a hardware fault, and it invites exactly the blind retry the failure shape exists to refuse.
`docs/failure-states.md` fixes that shape.

## Time

**No clock service, no `hwclock`, no NTP, no timezone database in use.** Nothing the appliance does
needs wall-clock time: signing does not, Argon2id does not, and there is no certificate to validate.
The RTC is read by firmware and ignored.

Consequence, and it belongs on the review screen: **the appliance never displays a date or time**,
and an `nLockTime` is shown as a raw height or timestamp with **no "is this in the past" judgement** —
that judgement would require trusting a clock deliberately never set.

`tzdata` is in the closure because Debian's `python3` depends on it. It is present and unused; that
is a fact about a dependency graph, not a clock.

## Build-time assertions

The build **fails**, not warns, at the first stage where a published claim stops being true.

**Every assertion is a pure function in `build/verify.py`, and that file is the only authority on
what each one checks.** This section says *why* each exists and names the function; it deliberately
does not restate the checks, because two places for one fact drift the first time an assertion is
tightened. `tests/test_build_verifier.py` feeds each function an input broken in the exact way it
exists to catch.

| function | why it exists |
|---|---|
| `parse_pin_file` | the `# @group` markers are machine-readable and load-bearing. A pin before any marker, an unknown group, an unpinned name or a name pinned twice is an error and never a guess |
| `groups_are_disjoint` | two lists is a thing the build checks, not a thing that can drift |
| `no_apt_package_shadows_a_wheel` | the `docs/adr/0002` seam. It must run over the resolved **closure**, not only the eight names a human typed — a `python3-*` arriving as a transitive dependency would otherwise pass silently |

The rootfs assertions, each one a published claim checked before an image exists:

| assertion | why it exists |
|---|---|
| no harness package in the rootfs | the group split answers "may this survive into the shipped rootfs?" and is worthless unchecked |
| no package manager | `pip` is installed transiently; removing it alone leaves `python3-wheel` and `python3-packaging` behind, and a `python3-packaging` in the image is a harness package in the rootfs |
| no init system: no `systemd` binary, no `udevd`, no getty, no `login` | the appliance's first published claim. The closure reaches it through `linux-image-amd64` if the kernel is ever resolved rather than extracted |
| `/bin/sh` and `python3` present | the predecessor's first ISO had neither, and PID 1 could not have run a line |
| no `kernel/net`, no `kernel/drivers/net` | the network claim, at *absence* strength |
| no module outside the allowlist | same, for storage and everything else |
| the `libsecp256k1` symbols | the 0.8.0 alias removal above. Without this, a future base silently produces a pure-Python signer |
| **one signature in each scheme, in the built rootfs** | a name check on the backend module is **not** sufficient. embit binds `schnorrsig`/`xonly`/`keypair` inside their own bare `except: pass`, so a library compiled without those modules imports cleanly, reports the native backend, and fails at taproot signing — mid-session, with a wallet loaded, on BIP86 only |
| the RAM floor matches the measured size | the formula above is only worth stating if the build re-derives it |
| `build/inputs/` matches `build/inputs.sha256` on hash **and on set equality** | an unexpected extra file is a failure, not an ignore |
| `/etc/aobs-release` agrees with the tag and `HEAD` | checked in stage 4 *before* `cpio`, while it is still a file a human can open |

**The BIP84 half compares bytes; the BIP86 half signs and verifies.** RFC6979 plus embit's low-R
grinding makes ECDSA deterministic, so a pinned vector is meaningful. BIP340 does not promise a
byte-stable signature — any valid nonce yields a valid signature — so a pinned Schnorr vector would
assert something the spec never said and fail against a perfectly good library. Verification proves
what the check is for: that the symbols bound at all.

Further assertions run only when a release is being cut, in `build/release-preflight.sh` rather than
in `mkiso.sh`, and `docs/release.md` says why the split falls there. A development build trips none
of them.

## The artifact

`bitcoin-signer-amd64.iso`, containing a kernel, an initramfs, and two bootloaders. The user writes
it to a USB stick with `dd` and boots the offline machine from it.

**Secure Boot must be disabled in firmware, and is not supported in v0.1.** Debian's signed
`shim` + `grub` + signed kernel make it genuinely achievable now that the kernel is Debian's —
pruning the modules tree does not break the kernel image's signature — but it adds a second boot path
to test and raises reproducibility questions about signed blobs. `docs/roadmap.md` records it as the
best candidate for the first post-v0.1 milestone.
