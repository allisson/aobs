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
| the module allowlist, and why there is no graphics driver in it | `build/modules.allow` |
| the cpio writer, and why it is not `find \| cpio` | `build/mkinitramfs.py` |
| the prune, as a pure function over `modules.dep` | `build/prune_modules.py` |
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
   `build/inputs/deb/appliance/` through a `copy://` repository. No network, no `--privileged`.
2. **Python layer.** The wheels from `build/inputs/wheels/appliance/`, unpacked into
   `/opt/aobs-python` **from outside the image**, plus the app tree copied to `/opt/aobs`.
3. **Kernel.** `dpkg-deb -x` of `build/inputs/deb/kernel/` into a staging directory. `vmlinuz` goes
   to the ISO; `/lib/modules` is pruned to the allowlist and copied into the rootfs. Then the purge,
   then PID 1 with the floor substituted into it, then the assertions.
4. **Initramfs.** `build/mkinitramfs.py | zstd`, and **not** `find | cpio` — see below.
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

**Five constraints on stage 1 came out of that verification.** None is about namespaces; every one
is about apt or mmdebstrap, and each was found by a build failing rather than by reading:

- The `.deb` pool must be **staged outside the checkout**, not merely made readable. apt's `copy:`
  method drops privileges before reading, and in unshare mode that is a subuid the host has never
  heard of — so every *ancestor* of the pool has to be traversable by a stranger, which a
  repository under a home directory is not. Measured twice, the second time with the pool at 755
  and its `Packages` at 644: `Failed to stat - stat (13: Permission denied)`.
- `APT::Sandbox::User "root"` is set, and **is not sufficient on its own** — the first version of
  `mkiso.sh` had it and failed anyway. `$TMPDIR` is no help either: on a GitHub runner it points
  back inside the home directory.
- **`copy://`, not `file://`.** A `file://` URI is resolved by apt running *inside* the chroot,
  where the host's pool path does not exist: `package file ... not accessible from chroot
  directory`. `copy://` reads on the host and copies in. mmdebstrap's alternative is a bind-mount
  hook; `copy://` is the smaller mechanism.
- **`--variant=essential` does not work against a flat local repo.** mmdebstrap reports
  `no essential packages -- skipping` and installs none of them, while apt reads `Essential: yes`
  from that same repo perfectly well — `dpkg-scanpackages` preserves the field for all 22 and apt's
  `?essential` pattern matches there. The selection is therefore done with **`--variant=custom` and
  `--include='?essential'`**, using apt's pattern rather than mmdebstrap's variant machinery.
- **One `--include` per package.** mmdebstrap does not split a comma-joined list that contains a
  pattern; it hands apt the whole string as a single package name.

The last two are the reason a rootfs exists at all, and neither is documented anywhere this project
would have thought to look. They were found by running the build locally with the full log visible,
after several CI rounds spent reading a truncated tail.

**And nothing else in the build needs privilege either, which took two changes of shape to arrive
at.** Both are recorded because both looked like they would need root and neither does:

- **Device nodes cannot be created.** `mknod` for a character device is denied inside a user
  namespace — measured, on the first unprivileged run: `tar: ./dev/console: Cannot mknod: Operation
  not permitted`. An initramfs with no `/dev/console` gives PID 1 no stdio at all, which on this
  appliance means a failure message nobody can read. So `build/mkinitramfs.py` writes the `newc`
  archive itself and **declares** the device nodes in the header, where the major and minor are
  fields. That is why stage 4 is a Python script.
- **Ownership does not have to be real.** Every member of that archive is written `root:root`
  whoever built it, so the tree on disk can stay owned by the build user and `tar --no-same-owner`
  is enough. Entries are emitted sorted, with `SOURCE_DATE_EPOCH` as every mtime, which is most of
  what `docs/reproducible-build.md` will want at M4 arrived at for free.

**One check needs more than that, and where it ended up is a finding.** `build/signcheck.py` makes
the image produce a signature with its own interpreter and its own `libsecp256k1`, and it needs a
chroot with a working `/dev` — see the `find_library` paragraph further down for why. This build
cannot make one on `ubuntu-24.04`: `mknod` is denied unprivileged, and with
`kernel.apparmor_restrict_unprivileged_userns=1` a namespace the build creates has **no
capabilities in it**, so neither writing a uid map nor bind-mounting a device node is available.
Measured in that order: `Operation not permitted` on `uid_map` from `unshare -Ur`, `Permission
denied` on `setgroups` from a hand-rolled equivalent, `Permission denied` on binding `/dev/null`
after `newuidmap` had successfully mapped the process.

mmdebstrap already has all of it — it maps through setuid `newuidmap` and sets up the chroot for
maintainer scripts. **So the signing check runs as one of its customize hooks in stage 1**, which
is also why the Python layer and the app tree are staged before the rootfs rather than after it.
That deleted a helper instead of adding one.

The hook leaves a receipt at `/etc/aobs-ec-backend`, and `build/verify.py` refuses an image without
it. A customize hook that silently did not run would leave every other assertion passing and the
only one that can catch a pure-Python signer unchecked.

### The local build is privileged, and the claim above is CI's alone

**Every ISO ever built on a developer machine in this project was built in a `--privileged`
container.** That is the finding the rule above asks for, and it went unwritten for a year:
the recipe lived in a local Docker image and a shell history, never in the repository, so the
escalation to `--privileged` was rediscovered from scratch each time rather than known.

`build/mkiso.sh` needs an amd64 Linux host with unprivileged user namespaces, and a developer
machine is generally neither. `build/mkiso-docker.sh` supplies the host — `build/Dockerfile.isohost`
is the `ubuntu-24.04` the runner is, with CI's tool list and a uid-1001 `builder` — and then hands
the container `--privileged`, because on the Docker measured here there is no other way to reach
stage 1. The build, the inputs and the assertions inside are unchanged; what the script replaces is
the host, and what it gives up is the property the section above measures.

**So an ISO built locally is not evidence that the build needs no privilege.** The claim is measured
on `ubuntu-24.04` in CI's `image` job and nowhere else. Anything published about it cites that job,
never a local build.

The escalation, measured 2026-09-09 on OrbStack's Docker, each step failing with what the next one
answers:

| `docker run` | stage 1 |
|---|---|
| plain | `unshare syscall failed: Operation not permitted` — the default seccomp profile denies `unshare(CLONE_NEWUSER)` |
| `--security-opt seccomp=unconfined` | `newuidmap: write to uid_map failed: Operation not permitted` — the namespace opens, the range mapping does not |
| `--privileged` | builds |

**The middle failure is not the obvious causes, and each was excluded rather than assumed.**
`newuidmap` is setuid-root and does elevate in that container (measured: euid 0, ruid 1001);
`CAP_SETUID` and `CAP_SETGID` are in the bounding set; the container is in no user namespace of its
own (`uid_map` is `0 0 4294967295`); the rootfs is not `nosuid`; `NoNewPrivs` is 0; and container
root writes the same mapping successfully. A native `linux/arm64` container fails identically, so
the amd64 emulation is not it either. What is left is the host kernel's own policy, which is a
property of this Docker and not of the build.

**A local host where the unprivileged path can actually run** is a full Linux VM rather than a
container — an OrbStack machine, `orb create -a amd64 ubuntu:24.04`, or any amd64 Linux box. That is
the thing to reach for if the property itself is what needs testing; `--privileged` is for getting an
ISO, not for measuring anything.

One more thing this cost, recorded because it cost a whole build: **never pipe the build's output.**
`sh build/mkiso.sh | tail` reported success for a build whose stage 1 had already failed, because a
pipeline exits with its last command's status. `build/mkiso-docker.sh` pipes nothing — and the same
truncated-tail reading is what the constraints below were found in spite of.

### Why the appliance closure is resolved against an empty root

`build/inputs/deb/appliance/` must be **the complete closure for a rootfs that starts from nothing**,
because that is what stage 1 starts from.

**The closure is 88 packages**, and getting to that number took two separate fixes because the base
image hid the answer twice, by two different mechanisms.

**First: what the container already had installed.** This was wrong for the whole of M1 and nothing
noticed, because the one consumer at the time — `build/Dockerfile.test` — starts *from*
`debian:trixie-slim` and so never missed what that image already had. `fetch_debs` resolved inside
that same container, and `--reinstall` re-downloads the packages *named on the command line* and
never a transitive dependency apt considers already satisfied. The pool held **37** packages: no
`libc6`, no `dpkg`, no `tar`, no `debconf`, no `tzdata`, no `libpam-*`. The first `mmdebstrap` run
against it failed with forty unsatisfiable dependencies. Fixed by resolving with
`Dir::State::status` pointed at an empty file.

**Second: what apt refuses to mention.** **apt never lists an `Essential: yes` package as a
dependency**, with or without an empty status file — it assumes they are present. trixie/main has 22
such packages and the empty-root resolution picked up 5 of them, silently omitting `base-files`,
`base-passwd`, `bash`, `coreutils`, `grep`, `sed`, `gzip`, `libc-bin`, `ncurses-base`, `perl-base`,
`sysvinit-utils`, `hostname`, `bsdutils`, `diffutils`, `findutils`, `init-system-helpers` and
`ncurses-bin`.

That 57-package pool got every one of its members into the chroot and then died with
`chroot: failed to run command 'dpkg': No such file or directory` while installing the essential
packages — a complete dependency closure that is not a working userland. Fixed by asking for
`?essential` alongside the pins, which keeps the set derived from the archive; listing the 22 names
in `build/apt-versions.txt` would be a closure maintained by hand, and drift there is the exact
failure mode of the 37-package pool.

> **The figure 57 was published in this document and in the commit that fixed the first mechanism,
> before the second was known.** It was a complete closure by apt's reckoning and still could not
> boot a chroot. Recorded rather than quietly overwritten, because "the pool is now the complete
> closure" was a claim made at a strength it had not earned.

`sysvinit-utils` arrives with the Essential set and is not an init system: it provides `pidof` and
`fstab-decode`. `build/verify.py`'s init-system assertion names daemons, not this.

The count is **88 against both suites and 87 against `main` alone** — `trixie-security`'s versions
pull `libstdc++6`. `build/apt-repositories` carries both suites for the kernel's sake, so 88 is the
number, and the difference is recorded because a figure that moves by one with no explanation is
how a measurement turns back into an estimate.

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
- **No `vga=`, on either path.** It was on the BIOS line until M3 and never once set a mode on the
  machine this project booted; see *The console floor* below.
- `panic=0` — hang rather than reboot. There is nothing to reboot into, and a reboot loop flashes
  the failure past the user.

**PID 1 is a short POSIX shell script that ends in `exec python3 -m aobs`,** so the app itself is
PID 1 for the session. There is no init system, no `inittab`, no getty, no VT switching. The script
does only what nothing else can, in this order:

1. Mount `proc`, `sys`, `dev`, `devpts`, `shm`, `run`, `tmp` — tmpfs and pseudo-filesystems only.
2. Put the console in UTF-8 and **load the default keymap**, so the picker is typeable before it
   draws.
3. **`modprobe` the allowlist**, from `/etc/aobs-modules`, and settle.
4. **Flip `authorized_default=0` on every root hub** — after our own devices enumerate, before the
   first secret is entered.
5. **Set `kernel.modules_disabled=1`**, by writing `/proc/sys` directly. One-way for the life of
   the boot; see below.
6. Check available RAM against the floor and refuse to start below it.
7. `exec` the app.

**Step 3 was not in this list and had to be added.** There is no udev and no init system, so the
only alternative to loading the drivers here is the kernel's own usermode helper firing on a device
match — at an unpredictable moment, *including after step 5 has closed the door*. Loading them here
is what makes "our own devices have enumerated" a point in time the script can name, which is what
step 4 is placed relative to. A module the machine does not have is reported and skipped: a machine
with no `i915` is a machine with an AMD card, and refusing to boot over it would be absurd.

**There is no `set -e`.** Each step checks its own result and a failure is named on the console and
held there. An init that dies is a kernel panic the user cannot read past, so a silent exit is the
one outcome this script may not have.

It is not written in Python, deliberately: PID 1 is the one process that cannot be restarted and is
hardest to test, and everything it does is a `mount` or an `echo` into sysfs.

### What the first hardware boot found: PID 1's commands were never checked for

The first boot on real hardware stopped at step 1 with `/init: 55: mount: not found`, and the fault
was not in PID 1. **`/usr/bin/mount` is not in `util-linux`. It is in a package named `mount`,**
which nothing pinned — while this document said the opposite in three places, and the appliance pin
list, the purge table and the containment claim below were all written on top of that sentence.

Three of the seven steps were broken, not one, and the other two are why this is written down here
rather than fixed quietly:

| step | command | package | what it did on the machine |
|---|---|---|---|
| 1 | `mount` | `mount`, unpinned | the photographed failure: PID 1's first line of work |
| 3 | `modprobe` | `kmod`, unpinned | **no failure at all.** Every module in the allowlist reported `no <module> on this machine`, exactly as a machine with none of that hardware would, and the session continued with no camera and no USB HID driver |
| 5 | `sysctl` | `procps`, unpinned | would have hard-failed after step 3 had already gone quietly wrong |

Step 3's behaviour is the finding worth keeping. A missing module is deliberately not a reason to
refuse to boot, so the loop reports and continues — which means a missing *`modprobe`* was
indistinguishable from unremarkable hardware. **Step 5 now writes `/proc/sys` directly** rather than
pin `procps` for one write: `sysctl` arrives with `ps`, `top`, `free`, `kill` and `pgrep`, and step 4
already closes the USB hubs with the same `echo`. The write is read back, because a one-way control
that silently did nothing is a claim in this document that stopped being true with nothing to say so.

`mount` and `kmod` are now pinned, and `busybox` is not: it was pinned for a `poweroff` PID 1 never
called — power off is `reboot(2)` with `RB_POWER_OFF` in `aobs/adapters/real/power.py` — and Debian's
`busybox` ships no applet symlinks, so that `poweroff` did not exist either. Nothing in the
repository invoked it.

**The assertion that was missing is the deliverable.** Every check in `build/verify.py` passed on
that image: `required_files_present` names `sh`, `python3`, the identity files and the app, and
stops. `commands_pid1_invokes` now reads every `step` in `build/init` itself — the grammar is
already fixed, so that file is also the machine-readable record of what it needs — and
`required_commands_present` resolves each one against PID 1's own `PATH` in the built rootfs, plus
the commands the real adapters shell out to. It is derived from the script rather than a list beside
it, because a hand-kept copy is what drifts.

### What the second hardware boot found: the image could sign and could not start

With PID 1 fixed, the appliance got through all seven steps — two root hubs closed, the UVC camera
enumerated, `crng init done` — reached `exec python3 -m aobs`, and died there:

```
ImportError. The session cannot continue. Power off and start again.
Kernel panic - not syncing: Attempted to kill init!  PID: 1  Comm: python3
```

The panic is this document's containment claim working: the app exited, and the kernel panicked on
init death rather than dropping anyone to a prompt.

**The fault was `libstdc++.so.6`, and it could not have been found from that screen.** `zxingcpp`,
`PIL/_avif` and pillow's bundled `libavif` all link the C++ runtime; the image did not carry it.
The `.deb` was *already in the appliance pool*, fetched as a dependency of `apt` — which is not
installed — and being in the pool is not being in the image.

**Why apt could not have known.** `pip --target` unpacks the wheels from OUTSIDE the chroot, by
design (`docs/adr/0002`, and the purge section below on why `pip` may not be in the image). So no
installed package declares a dependency on anything a wheel links, and apt resolves a closure that
is correct for the packages and blind to the application. `libstdc++6` is therefore pinned
explicitly, exactly as `libsecp256k1-2` is: both are libraries the Python layer needs and no `.deb`
asks for.

**Two assertions, because they catch disjoint failures.** `build/signcheck.py` now imports
`aobs.ui.app` inside mmdebstrap's chroot — the build proved the image could *sign* long before it
proved the image could *start* — and `no_unresolved_shared_library` reads a `readelf -d` sweep of
every shared object in the tree and resolves each `DT_NEEDED` against the image's own libraries,
honouring `DT_RUNPATH` so pillow's bundled directory is found the way the loader finds it. The
import check alone would have shipped this image: importing `aobs.ui.app` does not import
`PIL/_avif`, because Pillow loads its format plugins lazily, so two of the three broken objects
would have survived to fail on some later frame. `readelf` and not `ldd` because running the loader
needs a chroot and this build has no privilege to make one; reading the tables is a file read, and
the resolution is then a pure function.

**And the fault screen now names an `ImportError`.** It showed the type and nothing else, which is
why this took an unpacked initramfs and a chroot to identify. `docs/secret-hygiene.md` carries the
carve-out and its bounds: one exception type, chosen because the import machinery writes that
message and it names a module or a library rather than anything the application was holding.

### Containment, stated so it can be checked

**There is no getty, no VT with a login, and no path from the running app to a prompt.** If the app
exits, the kernel panics on init death rather than dropping to a shell.

**That claim is about the binary, and the binary arrives whether or not it is wanted.** `util-linux`
ships `/usr/sbin/agetty`, and `util-linux` is in every Debian rootfs because it is `Essential: yes` —
pinned or not, wanted or not. (This paragraph used to say it was pinned *because PID 1 needs
`mount`*; that was the false sentence the section above is about, and the claim here never depended
on it.) Measured in the built rootfs: `agetty` present, five matching paths. Nothing spawns it — there is no
init system — so the *behaviour* was already as described, but "there is no getty" was false of the
tree as built.

So the purge stage deletes it, and `build/verify.py` asserts it is gone. Narrowing the claim to
"no getty *runs*" was the alternative and was rejected: "the binary is not in the image" is something
a stranger can check with `ls`, and "nothing can spawn one" is an argument they have to follow.

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
- **USB binds nothing but HID and UVC.** Only those modules ship, plus `authorized_default=0`. The
  claim is about what USB binds and **not** about where keystrokes come from — see *Where input comes
  from* below, because on a laptop they usually do not come from USB at all.

**Measured: 20 modules ship and 4209 are deleted.** `build/modules.allow` is the whole list and
`build/prune_modules.py` computes the dependency closure from the regenerated `modules.dep`.
`build/verify.py` then checks the inverse — that every module still in the tree is reachable from
the allowlist — which is what catches one that survived the prune by accident.

`modules.dep` is **not shipped in the `.deb`**: Debian generates it from the maintainer script, and
this build runs none. So the first `depmod` is not a tidying step, it is what creates the graph the
prune runs against.

**`kernel.modules_disabled=1` is a second line, and is never cited as the claim.** `CONFIG_MODULES=y`
reopened a door the old kernel had welded shut: with a loadable-module kernel, a `.ko` that is not in
the image is not the same as a `.ko` that cannot be loaded. The write is irreversible once made and
costs two lines in PID 1 — the `echo` and the read-back — so it closes that gap for the life of the
session. It is an `echo` into `/proc/sys` and not `sysctl` for the reason given above: `sysctl` is in
`procps`, and one write is not worth a process-inspection toolkit in the image. A `modprobe` blacklist
exists for the same reason and with the same standing. **The claim is that the module is not in the
image**; these two make it expensive to be wrong about, and neither is evidence for it.

### The purge stage

Three things are installed because Debian insists, used, and then removed before the initramfs is
packed. `build/verify.py` fails the build if any of them survives:

| removed | why it was there | why it goes |
|---|---|---|
| `dpkg` and its database | `Essential: yes`; a Debian rootfs built the normal way always has one | it is a package manager, and the published claim says none is in the image |
| `apt` | in the appliance pool; whether it reaches the rootfs depends on what mmdebstrap installs | same claim, and "depends on" is not something a claim may rest on |
| `agetty` | shipped by `util-linux`, which is `Essential: yes` and so is in every Debian rootfs | the containment claim above |
| `usr/share/locale`, `doc`, `man`, `info` | Debian ships them | not a claim, just the largest prunable thing in the tree. Nothing here reads a locale |

**`pip` is not in this table any more, and its absence is the interesting entry.** M2 specified
installing it, using it and purging it with `--auto-remove`. That cannot be done: `python3-pip` is a
**harness-group** package, the appliance pool does not contain it, and putting it into the rootfs
even for one stage means installing a harness package into the image — the one thing the group
split exists to forbid. So the wheels are unpacked from outside by the build host's pip, with the
target platform named explicitly, and `pip`, `python3-wheel` and `python3-packaging` are absent by
construction rather than by removal. `build/verify.py` still asserts all three are gone: the
assertion is what makes the claim checkable, and it does not care how it came to be true.

**`apt` was previously written up here as "not in the appliance closure at all". That was wrong.**
`apt` is in the pool, and so are `libapt-pkg7.0`, `debian-archive-keyring` and `sqv` — the packages
that are only there to support it. What is true is the weaker statement that was measured: apt did
not end up in the *built rootfs*, because mmdebstrap installs the Essential set plus what is named
and apt is `Priority: important` rather than essential. That is a fact about what mmdebstrap chose,
and "what a tool chose" is not a thing a published claim may rest on. So the purge removes apt too,
and `build/verify.py` asserts it is gone, exactly as for `dpkg`.

The shape is the same in all three cases and it is the one M2 already specified for `pip`: install,
use, remove, assert absence. The alternative each time was to narrow a published claim to fit a
build detail, and that is the trade this project does not make.

**Busybox `sh` is present in the image, and that is not a hole worth closing.** "No shell on the
appliance" would be a claim that protects nobody — Python is in the image and can `os.execv`
anything. The claim above is the true one.

**Not defended: a person at the bootloader typing `rdinit=/bin/sh`.** Stated rather than papered over,
and it costs nothing — a fresh boot holds no secrets, which is the point of the amnesia claim.

## Console

**`fbcon` over a firmware framebuffer, and which driver provides it is the firmware's decision, not
the boot path's.** Three are built into Debian's kernel — `CONFIG_FB_EFI=y`, `CONFIG_FB_VESA=y`,
`CONFIG_FB_SIMPLE=y` — so the console needs no module on any of them.

**First registrar takes the aperture.** The firmware decides which framebuffer *devices* exist, and
whichever device probes first acquires the memory: `devm_aperture_acquire` refuses an overlapping
range with `-EBUSY` (`drivers/video/aperture.c:175`), so a second driver simply never comes up.
There is no fixed mapping from firmware path to driver:

- **UEFI** — `sysfb` registers `efi-framebuffer` from the GOP's mode, and `efifb` binds it.
  Unobserved; this project has never booted a UEFI machine.
- **coreboot** — `framebuffer-coreboot` reads the framebuffer entry out of the coreboot table and
  registers a `simple-framebuffer` device (`drivers/firmware/google/framebuffer-coreboot.c:64`),
  which `simplefb` binds. This is independent of `CONFIG_SYSFB_SIMPLEFB`, which governs the `sysfb`
  path only. **This is what the one machine this project has booted does**, at `1.765199`.
- **generic BIOS with a VESA mode set** — `sysfb` registers `vesa-framebuffer` and `vesafb` binds
  it. Unobserved.
- **BIOS with no linear framebuffer** — `sysfb` registers `vga-framebuffer`, nothing in this image
  binds it, and the console falls back to `vgacon` at 80×25. The appliance refuses to start; see
  *The console floor* below.

**"BIOS means `vesafb`" was this document's claim until M3 and it is wrong.** The target machine is
a BIOS boot and it runs `simplefb`. See
`docs/adr/0003-the-console-is-enforced-not-requested.md`.

**There is no graphics driver in the allowlist, and this document used to say there was.** It named
`i915`, `amdgpu`, `nouveau` and `simpledrm`. Three facts, all read off the pinned kernel's own
config, closed that:

- `CONFIG_DRM_SIMPLEDRM is not set`. **The module does not exist in Debian's kernel**, so a quarter
  of the old allowlist named a file that was never going to be found. `CONFIG_SYSFB_SIMPLEFB` is
  unset too, which stops `sysfb` from registering a `simple-framebuffer` — it does **not** stop
  `simplefb` itself, which is `CONFIG_FB_SIMPLE=y` and binds whatever registers such a device.
- The three firmware framebuffers above are built in, so the mechanism this section names is
  already satisfied without loading anything.
- The three DRM drivers need firmware blobs this image does not ship. Loading one takes the
  framebuffer away from a driver that is working and hands it to one that may not come up — trading
  a console that is guaranteed for a console that is faster, on an appliance that draws QR codes
  and text.

They also cost about 70 MiB of the 98 MiB module tree, which is the least interesting of the three
reasons and the only one that would have been reversible.

#### The console floor

**The appliance enforces its console size; it does not request it.** The QR display is fixed at
**85 columns × 43 rows**, and the QR channel is the only path out, so a console that cannot draw it
is a console the appliance must refuse rather than start on. `aobs/ui/geometry.py` sets the floor at
**100 × 43** and `aobs/ui/app.py` pushes `ConsoleTooSmallScreen` below it, before the keymap picker
and before anything else in the session. 1024×768 at the kernel's 8×16 font is 128×48, which clears
it.

**`vga=791` used to be named here as the mechanism, and it was never one.** The argument was that
`vgacon`'s 80×25 cannot draw the QR display, so a BIOS boot needs a VESA mode set. The premise is
right and the conclusion was not: on the only machine this project has booted, `vga=791` printed
`Undefined video mode number: 317` and stalled 30 seconds on every boot, and the 1024×768 console
came from coreboot's own framebuffer. A `vga=` value is one firmware's mode number — that machine's
SeaVGABIOS offers `0x141`–`0x144`, an OEM range that includes neither `0x117` (`vga=791`) nor the
standard `0x118` — and the kernel's portable `0xRRCC` form reaches text modes only, because
`video-mode.c:88` matches on pixel counts that overflow the `u16` it compares
(`(768 << 8) + 1024`). There is no parameter that portably guarantees a framebuffer.

So `build/isolinux.cfg` and `build/grub.cfg` now carry **identical** cmdlines with no `vga=`, and
the guarantee moved to the one place that can make it: a check inside the appliance that says on
screen what it needs and what it got. `docs/adr/0003-the-console-is-enforced-not-requested.md`.

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

### Where input comes from

**The module allowlist is not where a laptop's own keyboard comes from, and this document used to
imply that it was.**

`build/modules.allow` names `usbhid` and `hid_generic`, and every description of input in this
repository was written around them. Then the appliance was driven end to end on a Chromebook using
the machine's own keyboard, and neither module carried a single keystroke. The keyboard sits behind a
built-in i8042 controller, and the pinned kernel has that path compiled in:

| Symbol | State in `linux-image-amd64=6.12.107-1` | Consequence |
|---|---|---|
| `CONFIG_SERIO_I8042`, `CONFIG_SERIO_LIBPS2` | `=y` | The controller is in the kernel image, not the modules tree |
| `CONFIG_KEYBOARD_ATKBD` | `=y` | So is the driver that binds the keyboard on it |
| `CONFIG_INPUT_EVDEV` | `=m`, and not in the allowlist | Deleted. Input reaches the app through the **vt keyboard handler**, never `/dev/input/event*` |
| `CONFIG_KEYBOARD_CROS_EC` | `=m`, and not in the allowlist | Deleted. A Chromebook routing its keyboard through the embedded controller would boot and have **no keys** |
| `CONFIG_MOUSE_PS2`, `CONFIG_I2C_HID` | `=m`, and not in the allowlist | Deleted. The touchpad binds nothing, which is wanted — the appliance has no pointer |

Two things follow. **The allowlist cannot be read as the complete list of what binds hardware**: it
governs the modules tree and says nothing about drivers the kernel image carries, which is where the
console framebuffers (`CONFIG_FB_EFI=y`, `CONFIG_FB_VESA=y`) also live. And **`authorized_default=0`
does not cover the keyboard on such a machine** — an i8042 controller has two fixed ports on an
embedded controller and no arbitrary-class hotplug, so nothing is lost, but the claim must not be
stated as though USB authorization were what protects input.

`build/verify.py` asserts the four `=y` symbols above stay `=y` in whatever kernel is pinned. Without
that assertion, a future Debian flipping `KEYBOARD_ATKBD` or `FB_VESA` to `m` would delete the
keyboard or the console from the image and every other build-time check would still pass — the same
shape as the `mount` and `libstdc++6` faults below.

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
| `build/apt-versions.txt` | the operating system: `dash`, `mount`, `util-linux`, `kmod`, `python3`, `libsecp256k1-2`, `kbd`, `console-data`, the kernel |
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

**`ctypes.util.find_library` fails silently when `/dev/null` is missing, and this build found out
the hard way.** The first run of the stage-3d signing check reported `py_secp256k1` from an image
whose `libsecp256k1.so.2` was present and exported every symbol on the list. The chain: CPython's
`find_library` shells out to `ldconfig -p` with `stdin=subprocess.DEVNULL`; with no `/dev/null` in
the tree that raises `FileNotFoundError`; CPython catches it under `except OSError: pass` and
returns `None`; embit's own bare `except:` turns the `None` into the fallback backend. Two swallowed
exceptions, one absent character device, and a signer that reports as native.

The image is fine — `/dev/null` is declared in the cpio header and devtmpfs is mounted by PID 1's
first step. **The tree on disk was what lacked it**, because device nodes cannot be created
unprivileged, so the check now runs in a mount namespace with five device nodes bound in. It is
recorded at length because it is the clearest demonstration this project has of why the backend is
asserted rather than assumed: nothing anywhere printed a warning.

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

**PID 1 compares against the unrounded requirement, not against the published floor, and the two
numbers are in the script separately.** `MemTotal` on a machine with 512 MiB installed is always
somewhat under 512 — firmware reserves some and never gives it back — so a check against the
rounded figure would refuse to boot on exactly the machine the figure describes. The requirement is
what the machine has to satisfy; the floor is what the user is told to look for. `build/verify.py`
re-derives both from the measured tree and fails the build if the script carries either wrongly.

**The measured inputs are published against the run they came from** — unpacked rootfs, initramfs,
kernel, ISO — because a floor derived from an unpublished number is an assertion wearing a formula.

**Measured**, run [34228074569](https://github.com/allisson/aobs/actions/runs/34228074569) on
`ubuntu-24.04`, unprivileged, from `build/mkiso.sh` end to end:

| | |
|---|---|
| **unpacked rootfs** | **155 MiB** (6264 paths) |
| **`initramfs.zst`** | **38.2 MiB** |
| **`vmlinuz`** | **11.6 MiB** |
| **`bitcoin-signer-amd64.iso`** | **58.0 MiB** |
| modules shipped | 20, of Debian's 4229 |
| appliance closure on disk | 88 packages, 41 MiB of compressed `.deb` |
| kernel package | 107.9 MiB compressed, unpacked separately |

`requirement = 2 × 155 + 64 + 128 = 502 MiB`, so `floor = next_power_of_two(502)` = **512 MiB**.

The Alpine predecessor asserted 512 MiB from a prose estimate and happened to be right. This is the
same number arrived at from a tree somebody built, which is the difference the roadmap asks for.

**155 MiB is not the same 132.6 MiB this document published at the last milestone, and the
difference is not drift.** That figure was a rootfs and nothing else, measured before anything was
added to it or removed from it. This one is the tree that ships: `usr/share/locale`, `doc`, `man`
and `info` are gone (27.3 MiB of locale alone), and the Python wheel layer, the app tree and the
pruned module tree are in. The old paragraph of caveats saying the figure could only move down is
therefore retired — it has moved, in both directions, and this is the number after both.

**What is not published here is a per-directory breakdown of the final tree.** The build does not
emit one and this document is not going to estimate it.

**No pruning of the Python stdlib.** Stripping it buys little against the risk of a missing-module
traceback on an appliance with no recovery path.

**`usr/share/locale` is the largest prunable item in the tree at 27.3 MiB** — larger than the whole
Python stdlib's share — and nothing in this appliance reads a locale: the console is fixed to UTF-8
and every string it displays is its own. Dropping it is the one size lever worth taking, and unlike
the stdlib it carries no risk of a missing-import traceback.

**The full `console-data` set costs 0.4 MiB, and the worry was unfounded.** 216 keymaps, gzipped.
This document previously hedged about "a real cost in resident RAM" and `docs/roadmap.md` reserved
the right to revisit the decision "if the measured RAM cost turns out to be absurd". It is 0.4 MiB
against a 512 MiB floor. The question is closed and the keymap picker keeps every map.

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
| no package manager: no `pip`, no `dpkg`, no `apt`, and no dpkg database | all three are installed or arrive because Debian insists, and all are removed by the purge stage. Removing `pip` alone leaves `python3-wheel` and `python3-packaging` behind, and a `python3-packaging` in the image is a harness package in the rootfs |
| no `agetty` | `util-linux` ships it and is `Essential: yes`, so it is in the rootfs whether pinned or not. Measured present in the built rootfs, so this assertion is the only thing that makes the containment claim true |
| **every library the image links is in the image** | the assertion the second hardware boot needed. `pip --target` unpacks the wheels from outside the chroot, so no installed package declares what they link and apt's closure is blind to the application. A `readelf -d` sweep, resolved against the image's own libraries and honouring `DT_RUNPATH`; `readelf` and not `ldd` because running the loader needs a chroot this build has no privilege to make |
| **the image imports what PID 1 runs** | `build/signcheck.py`, in mmdebstrap's chroot, alongside the signing check that was already there. The build proved the image could sign long before it proved the image could start. Needed *as well as* the sweep, not instead of it: lazily imported objects like Pillow's `_avif` are invisible to an import of `aobs.ui.app`, and pure-Python import failures are invisible to `readelf` |
| **every command PID 1 and the real adapters invoke, resolvable on PID 1's own `PATH`** | the assertion the first hardware boot needed and did not have. `mount` was in no pinned package, PID 1 died on its first line of work, and every other check on this page passed on that image. The list is read out of `build/init`'s own `step` grammar, so it cannot drift from the script |
| no init system: no `systemd` binary, no `udevd`, no getty, no `login` | the appliance's first published claim. The closure reaches it through `linux-image-amd64` if the kernel is ever resolved rather than extracted |
| `/bin/sh` and `python3` present | the predecessor's first ISO had neither, and PID 1 could not have run a line |
| no `kernel/net`, no `kernel/drivers/net` | the network claim, at *absence* strength |
| no module outside the allowlist | same, for storage and everything else |
| the `libsecp256k1` symbols | the 0.8.0 alias removal above. Without this, a future base silently produces a pure-Python signer |
| **one signature in each scheme, in the built rootfs** | a name check on the backend module is **not** sufficient. embit binds `schnorrsig`/`xonly`/`keypair` inside their own bare `except: pass`, so a library compiled without those modules imports cleanly, reports the native backend, and fails at taproot signing — mid-session, with a wallet loaded, on BIP86 only |
| the RAM floor matches the measured size | the formula above is only worth stating if the build re-derives it |
| `build/inputs/` matches `build/inputs.sha256` on hash **and on set equality** | an unexpected extra file is a failure, not an ignore |
| `/etc/aobs-release` agrees with the tag and `HEAD` | checked in stage 3d *before* the archive is written, while it is still a file a human can open |
| no `@PLACEHOLDER@` survived into `build/init` | the floor and the default keymap are substituted by the build. An unsubstituted one is a shell error inside PID 1, on a machine with no scrollback |
| the ISO carries two El Torito boot images | a hybrid ISO that lost one still builds, still mounts and still boots on whichever firmware the person who built it happens to have. That failure reaches a user, not a build log |

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
