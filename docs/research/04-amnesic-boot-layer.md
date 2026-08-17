# Amnesic Debian boot layer: toolchain, kiosk, no-network, RAM wipe, entropy

Research for [issue #4](https://github.com/allisson/aobs/issues/4). Map: [issue #1](https://github.com/allisson/aobs/issues/1).

Target: Debian 13 "trixie", amd64, kernel 6.12, deliverable `bitcoin-signer-amd64.iso`.
All package versions and sizes below were read from the trixie `main/binary-amd64`
`Packages` index (`https://deb.debian.org/debian/dists/trixie/main/binary-amd64/Packages.xz`).

Claims are cited inline. Where a number is *derived* from source rather than measured on
hardware, it is marked **[derived]**.

---

## 1. Build toolchain — recommendation: `live-build`

### The decisive constraint: the deliverable is an ISO

| Tool | Emits a bootable ISO9660 hybrid image? |
|---|---|
| `live-build` | Yes — `scripts/build/binary_iso` drives `xorriso -as mkisofs`. |
| `mkosi` | **No.** `Format=` accepts `directory`, `tar`, `cpio`, `disk`, `uki`, `esp`, `oci`, `sysext`, `confext`, `portable`, `addon`, `none`. There is no ISO output. |
| `debos` | Disk-image oriented (`image-partition`, `filesystem-deploy`, `pack`). No ISO action. |
| `debootstrap` + `xorriso` by hand | Yes, but you write the ISO/EFI/squashfs assembly yourself. |

- mkosi `Format=` list: <https://github.com/systemd/mkosi/blob/main/mkosi/resources/man/mkosi.1.md> (search `Format=`)
- debos actions: <https://github.com/go-debos/debos>
- live-build ISO step: <https://salsa.debian.org/live-team/live-build/-/blob/master/scripts/build/binary_iso>

That alone eliminates mkosi and debos unless we change the deliverable, which the map fixes
as `bitcoin-signer-amd64.iso`.

### Reproducibility (v2 goal) — live-build is already ahead, not behind

This is the point where the intuition "hand-rolled = more control = easier to make
deterministic later" is wrong. live-build *already* threads `SOURCE_DATE_EPOCH` through
every timestamp-bearing step:

- `functions/configuration.sh:57` — `export SOURCE_DATE_EPOCH="${SOURCE_DATE_EPOCH:-$(date '+%s')}"`, and `:49` records `_REPRODUCIBLE` when the caller supplied it.
- `scripts/build/binary_iso:125` — `XORRISO_OPTIONS="${XORRISO_OPTIONS} --modification-date=$(date --utc -d@${SOURCE_DATE_EPOCH} +%Y%m%d%H%M%S00)"`
- `scripts/build/binary_iso:198,230` — normalises `.disk` mtimes and the ISO's own mtime to `SOURCE_DATE_EPOCH`.
- `scripts/build/efi-image:88` — feeds `SOURCE_DATE_EPOCH` (lower 32 bits, hex) to `mkfs.msdos -i` so the ESP volume ID is deterministic.
- `scripts/chroot.sh:32` — exports `SOURCE_DATE_EPOCH` into every chroot command.
- `test/rebuild.sh` — a first-party script that rebuilds an official image for a given `SNAPSHOT_TIMESTAMP` against `snapshot.debian.org` and compares.

Source: <https://salsa.debian.org/live-team/live-build> (checked at `1:20250814`).

Debian's own status page for this work:

> **Bookworm (Stable):** All official images are reproducible at the live-build stage.
> **Trixie:** … "The boot screens and the firmware patterns are slightly different. The core squashfs image is still reproducible though."

<https://wiki.debian.org/ReproducibleInstalls/LiveImages>

So for v2 the work is *pinning* (`SOURCE_DATE_EPOCH` + a `snapshot.debian.org` mirror URL +
a pinned live-build version), not *replacing the toolchain*. A hand-rolled
`debootstrap`+`xorriso` pipeline would put us on the wrong side of that: we would be
reimplementing `binary_iso`, `efi-image`, squashfs file ordering and mtime normalisation —
which is exactly where reproducibility bugs live.

### Maintainability

live-build's customisation surface is a directory tree, and it is the tree Debian's own
live images use:

- `config/package-lists/*.list.chroot` — package selection
- `config/includes.chroot/` — files dropped into the rootfs
- `config/hooks/normal/*.hook.chroot` — arbitrary shell run inside the chroot before squashfs
- `config/hooks/normal/*.hook.binary` — run against the binary (pre-ISO) tree

Hooks are the mechanism for everything in sections 3–5 below. live-build ships worked
examples of exactly this kind of stripping
(`examples/hooks/minimal.hook.chroot`, `examples/hooks/stripped.hook.chroot`), and
`examples/hooks/reproducible/` for the v2 goal.

Honest downsides: live-build is a pile of shell scripts, the `config/` tree is stateful
(`lb clean` matters), and `lb build` needs root. Accepted — the alternative is owning that
complexity ourselves.

**Recommendation: `live-build`.** Pin the live-build version in the build script and set
`SOURCE_DATE_EPOCH` from day one even in v1 — it costs one line and it is the difference
between "reproducibility is a config change" and "reproducibility is a rewrite".

---

## 2. Kiosk launch — `cage` on Wayland, no display manager

### Compositor

`cage` (trixie: `0.2.0-2`, **76 KiB installed**, 21 KB `.deb`) versus
`xserver-xorg-core` (6.2 MiB installed).

> "Cage runs a single, maximized application. Cage can run multiple applications, but only
> a single one is visible at any point in time. **User interaction and activities outside
> the scope of the running application are prevented.**"
> — `cage(1)`, <https://github.com/cage-kiosk/cage/blob/v0.2.0/cage.1.scd>

Critically, **VT switching is off by default**: `-s` is documented as *"Allow VT
switching"* — an opt-in. Without it there is no Ctrl+Alt+F<n> escape from the signer.
X11 has no equivalent single-flag guarantee.

Tauri v2 on Linux is a GTK/WebKitGTK app (`libwebkit2gtk-4.1-dev` per
<https://v2.tauri.app/start/prerequisites/>), so it speaks Wayland natively via GTK.
`xwayland` (2.4 MiB) should be **left out** and kept as a documented fallback knob if the
WebKitGTK build turns out to need it.

Cost note: `libwebkit2gtk-4.1-0` is **96 MiB installed** (23.8 MB `.deb`). The web engine,
not the boot layer, dominates the ISO. Worth knowing before optimising elsewhere.

### Getting to a seat with no login manager

`cage` needs seat access (DRM master + input) without running as root. `libseat` supports
a `seatd` backend and a `logind` backend, selectable at runtime via `LIBSEAT_BACKEND`
(<https://git.sr.ht/~kennylevinsen/seatd/blob/master/README.md>). `seatd` is **104 KiB
installed**.

Recommended shape:

- `seatd.service` enabled; unprivileged user `signer` in group `_seatd` and `video`/`input`.
- A plain systemd unit: `ExecStart=/usr/bin/cage -- /usr/bin/aobs`, `Restart=always`,
  `Environment=LIBSEAT_BACKEND=seatd`, `User=signer`, bound to `graphical.target` (or
  `multi-user.target`, since there is no DM).

`greetd` (1.2 MiB, `initial_session` auto-login) was considered and **rejected**: its
`initial_session` is documented to run *exactly once per boot* —

> "The initial session will only be executed during the first run of greetd since boot in
> order to ensure signing out works properly and to prevent security issues whenever greetd
> or the greeter exit."
> — <https://git.sr.ht/~kennylevinsen/greetd/blob/master/man/greetd-5.scd>

which is the opposite of what a kiosk restart needs. A systemd `Restart=always` unit is
smaller and does the right thing.

### No shell escape

Three controls, all config, all cheap:

1. `cage` without `-s` → no VT switching (above).
2. `logind.conf`: `NAutoVTs=0` and `ReserveVT=0`. Per `logind.conf(5)`, `NAutoVTs=`
   *"controls how many login gettys are available on the VTs … When set to 0, automatic
   spawning of autovt services is disabled"*, and `ReserveVT=` *"Defaults to 6 (in other
   words, there will always be a getty available on Alt-F6.) When set to 0, VT reservation
   is disabled."*
   <https://github.com/systemd/systemd/blob/main/man/logind.conf.xml>
3. `kernel.sysrq=0` — per `Documentation/admin-guide/sysrq.rst`, `/proc/sys/kernel/sysrq`
   value `0` = *"disable sysrq completely"* (note the doc's own caveat: this only governs
   keyboard invocation; `/proc/sysrq-trigger` still works for root, which is fine because
   there is no shell).
   <https://github.com/torvalds/linux/blob/v6.12/Documentation/admin-guide/sysrq.rst>

Also: do not install a terminal emulator, and do not install `openssh-server` (it is not in
a minimal `lb config` anyway).

### If the app crashes

Read from `cage.c`: cage supervises its primary client, and on `SIGCHLD` calls
`server_terminate()` → `wl_display_terminate()`; `cleanup_primary_client()` does
`waitpid()` and returns `WEXITSTATUS(status)` (or `128 + WTERMSIG(status)`) as cage's own
exit status. <https://github.com/cage-kiosk/cage/blob/master/cage.c>

So: **signer dies → cage exits → systemd `Restart=always` brings the whole stack back to a
blank signer.** That is the correct amnesic behaviour and should be stated as a product
fact, not a bug: a crash loses the in-memory wallet and the user must re-enter the seed.
The screen must never show a shell or a console; a `TTYVTDisallocate=yes` on the unit and a
`vt.global_cursor_default=0` / `quiet loglevel=3` cmdline keep kernel logs off the panel.

---

## 3. No network — ranked by how hard each is to undo

Ranked hardest-to-undo first. **Recommended: #2 as the primary control, #3+#5 as cheap
defence in depth. #1 is rejected.**

### 1. Kernel built with `CONFIG_NET=n` — REJECTED

It is the hardest to undo, and it does not work. `net/unix/Kconfig` is sourced from inside
`if NET` … `endif # if NET` in `net/Kconfig` (lines 27, 78, 538 at v6.12), so **AF_UNIX
disappears with CONFIG_NET**. The `CONFIG_UNIX` help text says it plainly:

> "Many commonly used programs such as the X Window system and syslog use these sockets
> **even if your machine is not connected to any network**."
> — <https://github.com/torvalds/linux/blob/v6.12/net/unix/Kconfig>

Wayland, D-Bus, systemd and WebKitGTK's multi-process model all ride AF_UNIX. This would
break the entire kiosk. It would also mean abandoning Debian's signed `linux-image` and
maintaining a custom kernel — a large maintenance and reproducibility cost for a
guarantee we can get another way.

### 2. Ship no network driver modules at all — RECOMMENDED

A `config/hooks/normal/*.hook.chroot` that deletes the driver trees before squashfs, then
runs `depmod`:

```
/lib/modules/*/kernel/drivers/net/       (ethernet, wireless, usb net, ppp, …)
/lib/modules/*/kernel/drivers/bluetooth/
/lib/modules/*/kernel/net/               (protocol modules not built in)
```

and installs **no** `firmware-*` package, so even a driver that reappeared would have
nothing to load onto a Wi-Fi card.

To undo this you must rebuild the ISO. At runtime the rootfs is a read-only squashfs with a
tmpfs overlay (section 4), so there is no `.ko` on the medium to `insmod`, and the QR-only
data channel gives no way to bring one in. This is the strongest control that keeps a stock
Debian kernel.

**Must also strip the initramfs.** `initramfs-tools` defaults to `MODULES=most`, which
bundles network drivers independently of the squashfs. Set `MODULES=dep` (or a hook that
prunes the same paths from the initramfs) or the guarantee has a hole in the boot path.
*(Flagged as a build-time verification item: confirm with `lsinitramfs` that no
`drivers/net` entries remain.)*

Note this leaves loopback and AF_UNIX intact — deliberately. "No network" here means
**no link layer to any physical interface**, not "no network stack".

### 3. `install <module> /bin/false` in `/etc/modprobe.d/`

Blocks `modprobe` and udev-driven autoload. Does **not** stop `insmod` on a `.ko` that is
still present on the image — so this is a complement to #2, not a substitute. Cheap, so do
both.

### 4. `blacklist <module>` in `/etc/modprobe.d/` — weakest module control

Weaker than #3 and commonly misunderstood. `modprobe.d(5)`:

> "the **blacklist** keyword indicates that all of that particular module's internal
> aliases are to be ignored."
> — <https://man7.org/linux/man-pages/man5/modprobe.d.5.html>

It suppresses *alias-driven* loading only. An explicit `modprobe e1000e` still loads the
module. Use `install … /bin/false` instead when the intent is "never load this".

### 5. No NetworkManager / no ifupdown, interfaces down at boot — weakest overall

`network-manager` is 7.6 MiB installed; simply not putting it in the package list saves
space and removes the auto-connect behaviour. But this is pure configuration: one
`ip link set eth0 up` undoes it. Value is only as a visible statement of intent plus the
size saving. Never rely on it as the guarantee.

---

## 4. No swap, no persistence

### The live-boot defaults are already amnesic — verified in source

Both persistence and swap are **opt-in boot parameters**, not defaults:

- `components/3020-swap` parses `swap` / `live-boot.swap=` from the cmdline and
  `return 0`s immediately unless `LIVE_SWAP=true`. Without the parameter, live-boot never
  touches an on-disk swap partition and never writes an fstab swap entry.
- `live-boot(7)`: *"`swap=true` — This parameter enables usage of local swap partitions."*
  and *"`persistence` — live-boot will probe devices for persistence media."* Both are
  listed as parameters you add.

<https://salsa.debian.org/live-team/live-boot> (checked at `1:20250815~deb13u1`)

So the primary control is: **do not put `persistence` or `swap` on the kernel command
line.** `nopersistence` can be added anyway as a belt-and-braces marker (it is documented
as *"disables the persistence feature, useful if the bootloader … has been installed with
persistence enabled"*).

### Belt and braces (what Tails does)

Tails' design requirement, and its implementation:

> "MUST take care not to use any filesystem or swap volume that might exist on the host
> machine hard drives" — implemented by disabling the `/sbin/swapon` binary and not setting
> live-boot's swap option.
> — <https://tails.net/contribute/design/>

Mirror that: a chroot hook that neuters `/sbin/swapon`, plus `systemctl mask swap.target`.

**Note there is no `noswap` kernel parameter.** It does not appear anywhere in
`Documentation/admin-guide/kernel-parameters.txt` at v6.12 — verified by grep. Do not put
it on the cmdline and imagine it does something.

### Hibernation

`nohibernate` is real and documented:

> `nohibernate	[HIBERNATION] Disable hibernation and resume.`
> — <https://github.com/torvalds/linux/blob/v6.12/Documentation/admin-guide/kernel-parameters.txt> (line 3944)

Put it on the cmdline. Belt and braces: with no swap there is no resume device, so
hibernation cannot write anywhere even without the flag; and
`systemd-sleep.conf`'s `AllowHibernation=no` implies `AllowSuspendThenHibernate=no` and
`AllowHybridSleep=no`
(<https://github.com/systemd/systemd/blob/main/man/systemd-sleep.conf.xml>). Also set
`HandleLidSwitch=ignore` / `HandleSuspendKey=ignore` in `logind.conf` so a closed laptop lid
cannot suspend a machine holding a seed in RAM.

### Crash dumps

- **Kernel**: do not install `kdump-tools` and do not put `crashkernel=` on the cmdline.
  Without a reserved crash-kernel region there is no kdump path at all.
- **Userspace**: `/etc/systemd/coredump.conf.d/` with `Storage=none` and `ProcessSizeMax=0`.
  `coredump.conf(5)` is explicit:

  > "Setting `Storage=none` and `ProcessSizeMax=0` disables all coredump handling except for
  > a log entry."
  > — <https://github.com/systemd/systemd/blob/main/man/coredump.conf.xml>

  This matters more than it looks: `Storage=external` is the default and writes to
  `/var/lib/systemd/coredump/`. On a live system that path is tmpfs (RAM, not disk) so it
  is not *persistence*, but a core of the signer process is a full copy of the seed sitting
  in a file with a predictable name. Turn it off.

### Auto-mount

Do not install `udisks2`, `gvfs`, or any file manager, and run no desktop environment —
there is then no agent that mounts anything. This is the correct control given the map's
"no USB or SD storage, no auto-mount, no filesystem parsing of untrusted media". Do **not**
try to solve it by removing filesystem modules: `squashfs`, `overlay`, `isofs` and `vfat`
are all needed to boot.

---

## 5. RAM wipe at shutdown — what it is and what it is not

### What Tails actually does (it is not `sdmem` any more)

> "Tails now relies on the Linux kernel's freed memory poisoning feature." … "we enable
> free poisoning for the buddy allocator, the slub/slab ones, and heap memory"
> — <https://tails.net/contribute/design/memory_erasure/>

The kernel parameter is `init_on_free=1`:

> `init_on_free=	[MM,EARLY] Fill freed pages and heap objects with zeroes.`
> — `kernel-parameters.txt` line 2191, v6.12

Tails' full hardening cmdline, for reference:
`init_on_free=1 slab_nomerge slub_debug=FZ vsyscall=none mce=0 page_alloc.shuffle=1
mds=full,nosmt randomize_kstack_offset=on spec_store_bypass_disable=on`
(<https://gitlab.tails.boum.org/tails/tails/-/raw/master/wiki/src/contribute/design/kernel_hardening.mdwn>).

The rest of the Tails machinery exists because **poisoning only fires when memory is
actually freed**, and a normal shutdown never frees the overlayfs read-write branch. Tails
therefore:

- mounts a tmpfs on `/run/initramfs` and uses `systemd-shutdown`'s ability to switch root
  back into the initramfs, so the root filesystem gets unmounted and its pages freed;
- additionally deletes the overlayfs upper-dir contents from a systemd service late in
  shutdown ("necessary but not sufficient" was their finding for the initramfs jump alone);
- runs `memlockd` to keep every file the shutdown path needs locked in RAM;
- runs a `udev-watchdog` that triggers the same path when the boot medium is yanked.

All from <https://tails.net/contribute/design/memory_erasure/>.

### Is it worth the cost?

**There is no boot-time cost.** `init_on_free=1` is a steady-state allocator overhead, not
a shutdown or startup pass. Tails abandoned the "boot a second kernel and wipe free memory"
approach — shipped 0.7 through 2.12 — because of *"severe usability and reliability
problems"*, and removed it in Tails 3.0 (same page). Do not resurrect it.

Recommendation for v1: **take `init_on_free=1` and the overlayfs-free-on-shutdown idea; do
not port Tails' `memlockd` + `udev-watchdog` + initramfs-shutdown machinery.**

> **Half of this recommendation was reversed by
> [#62](https://github.com/allisson/aobs/issues/62); the finding above is left as written.** The
> overlayfs-free-on-shutdown half cannot stand without the machinery the same sentence declines —
> which is what the paragraph above this one already says, and what nobody noticed when the
> recommendation was folded into the spec. `01-boot-layer.md` §5 now claims `init_on_free=1` alone,
> and rests on nothing secret being written to a filesystem in the first place. The map's
threat model already excludes "DMA and cold-boot attacks by a present adversary", and that
machinery exists almost entirely to shorten the window against a present adversary. Revisit
only if the threat model changes.

### What RAM wipe at shutdown does NOT survive — be blunt about this

1. **A hard power cut.** `init_on_free` zeroes pages *when they are freed*. Cut power and
   nothing is freed: the signer's live heap, the overlayfs upper directory, the page cache
   and the framebuffer are all still holding whatever they held. The RAM wipe is a
   **clean-shutdown guarantee only**. It is not a panic button.
2. **Physical data remanence.** Even after a clean shutdown, Tails' own user documentation
   says data *"can remain in RAM up to several minutes after shutdown"*
   (<https://tails.net/doc/advanced_topics/cold_boot_attacks/>). The wipe reduces the
   window; it does not close it.
3. **Kernel memory.** Tails' own limitations section: *"on shutdown all process memory is
   freed (and thus erased), but some kernel memory is not erased on shutdown, and is
   currently not erased"*, and *"there may be other ways the Linux kernel allocates memory,
   that are not subject to poisoning"*.
4. **Anything the app is still holding.** This is the practical consequence for the signer:
   `init_on_free` is not a substitute for the application zeroizing its own secrets
   (`zeroize` crate, `Zeroizing<T>` wrappers) the moment they are no longer needed. Freeing
   a buffer is what triggers poisoning — so the app must actually free it, promptly, and
   must avoid leaving copies in `String`/`Vec` reallocations, clipboard buffers, or the
   WebKit renderer process's heap.

Item 4 is the one that should carry into the signer's spec.

---

## 6. Camera — essentially free for UVC, not free for anything else

### UVC is already in the kernel we ship

Debian's `linux-image` config has `CONFIG_USB_VIDEO_CLASS=m` (with
`CONFIG_MEDIA_SUPPORT=m`, `CONFIG_MEDIA_USB_SUPPORT=y`,
`CONFIG_USB_VIDEO_CLASS_INPUT_EVDEV=y`) —
<https://salsa.debian.org/kernel-team/linux/-/blob/debian/latest/debian/config/config>.

So `uvcvideo` ships inside `linux-image-6.12.x+deb13-amd64` (108 MiB installed, already in
the image because we need a kernel). A USB UVC webcam costs **zero extra packages**: the
module autoloads on plug, udev creates `/dev/videoN`, and the app talks V4L2 ioctls
directly.

Optional userspace, if wanted:

| Package | Installed | Needed? |
|---|---|---|
| `libv4l-0t64` | 256 KiB | Only if we want libv4lconvert's pixel-format normalisation instead of handling MJPEG/YUYV in Rust. |
| `v4l-utils` | 2.7 MiB | Debugging convenience (`v4l2-ctl`). Leave out of the release image. |

libv4lconvert's purpose, from the kernel docs: *"a library that converts several different
pixelformats found in V4L2 drivers into a few common RGB and YUY formats"* —
<https://github.com/torvalds/linux/blob/v6.12/Documentation/userspace-api/media/v4l/libv4l-introduction.rst>.
A Rust QR decoder wants greyscale, so decoding MJPEG/YUYV in-process is likely simpler than
pulling in libv4l. Decide in the camera/QR ticket.

Also required: the kiosk user must be in the `video` group (or a udev rule granting it),
since `cage` runs unprivileged.

### The caveat that belongs in the hardware compatibility floor

Not every built-in laptop camera is a UVC device. The V4L2 docs distinguish
**MC-centric** from **video-node-centric** hardware:

> "It is required for MC-centric drivers to identify the V4L2 sub-devices and to configure
> the pipelines via the media controller API before using the peripheral."
> — <https://github.com/torvalds/linux/blob/v6.12/Documentation/userspace-api/media/v4l/open.rst>

Modern Intel IPU6 / MIPI laptop cameras are MC-centric and additionally need proprietary
firmware and `libcamera` to produce a frame. Supporting those means firmware blobs, a
libcamera stack, and per-model pipeline configuration — a large, fragile addition to an
offline appliance.

**Recommendation: v1 supports USB UVC cameras only.** State it in the hardware floor
("a USB webcam is required; built-in cameras may not work"), detect at startup by probing
`/dev/video*` for `V4L2_CAP_VIDEO_CAPTURE` without `V4L2_CAP_IO_MC`, and show a clear
message rather than failing obscurely. Image cost of that decision: **0 bytes**.

---

## 7. Entropy at live boot — the answer is "yes, and no seed file is needed"

This is the section that feeds the entropy-policy ticket. Everything here is from
`drivers/char/random.c`, read at both `master` and the `v6.12` tag (Debian 13's kernel).

### 7.1 The kernel seeds the CSPRNG from RDSEED/RDRAND before userspace exists

`random_init_early()` runs *"extremely early, before time keeping functionality is
available, but arch randomness is. Interrupts are not yet enabled."* It pulls
`BLAKE2S_BLOCK_SIZE / sizeof(long)` = **8 longs = 512 bits**, preferring
`arch_get_random_seed_longs()` and falling back to `arch_get_random_longs()`, decrementing
`arch_bits` by 64 for each long it could not get, and then:

```c
	/* Reseed if already seeded by earlier phases. */
	if (crng_ready())
		crng_reseed(NULL);
	else if (trust_cpu)
		_credit_init_bits(arch_bits);
```

On x86 those two helpers are **RDSEED** and **RDRAND** respectively:

```c
static inline size_t __must_check arch_get_random_longs(unsigned long *v, size_t max_longs)
{ return max_longs && static_cpu_has(X86_FEATURE_RDRAND) && rdrand_long(v) ? 1 : 0; }

static inline size_t __must_check arch_get_random_seed_longs(unsigned long *v, size_t max_longs)
{ return max_longs && static_cpu_has(X86_FEATURE_RDSEED) && rdseed_long(v) ? 1 : 0; }
```
<https://github.com/torvalds/linux/blob/master/arch/x86/include/asm/archrandom.h>

The threshold to be "ready" is 256 bits:

```c
enum {
	POOL_BITS = BLAKE2S_HASH_SIZE * 8,          /* = 32 * 8 = 256 */
	POOL_READY_BITS = POOL_BITS,                /* When crng_init->CRNG_READY */
	POOL_EARLY_BITS = POOL_READY_BITS / 2       /* When crng_init->CRNG_EARLY */
};

static enum {
	CRNG_EMPTY = 0, /* Little to no entropy collected */
	CRNG_EARLY = 1, /* At least POOL_EARLY_BITS collected */
	CRNG_READY = 2  /* Fully initialized with POOL_READY_BITS collected */
} crng_init __read_mostly = CRNG_EMPTY;
```

512 credited bits ≥ 256 required, so `credit_init_bits()` transitions straight to
`CRNG_READY` and prints `crng init done`.

**Conclusion: on any amd64 CPU with RDRAND/RDSEED, the kernel CSPRNG is fully initialised
before the first userspace instruction runs. A live system with no carried-over seed file
is not disadvantaged at all. `getrandom(2)` will never block.**

### 7.2 `random.trust_cpu` is ON by default and is no longer a build option

At v6.12 (and master):

```c
static bool trust_cpu __initdata = true;
static bool trust_bootloader __initdata = true;
early_param("random.trust_cpu", parse_trust_cpu);
early_param("random.trust_bootloader", parse_trust_bootloader);
```

`CONFIG_RANDOM_TRUST_CPU` / `CONFIG_RANDOM_TRUST_BOOTLOADER` were removed in commit
`b9b01a5625b5` ("random: use random.trust_{bootloader,cpu} command line option only",
Jason A. Donenfeld, Nov 2022, v6.2):

> "basically everybody enables the compile time option now … So just reduce the number of
> moving pieces and nix the compile time option in favor of the more versatile command line
> option."

<https://github.com/torvalds/linux/commit/b9b01a5625b5>

Consistently, `kernel-parameters.txt` at v6.12 documents only the *off* switches:

> `random.trust_cpu=off  [KNL,EARLY] Disable trusting the use of the CPU's random number
> generator (if available) to initialize the kernel's RNG.`

Debian does not pass `random.trust_cpu=off`, so trixie boots with CPU trust enabled.

### 7.3 The kernel does sanity-check RDRAND (partially)

```c
/*
 * RDRAND has Built-In-Self-Test (BIST) that runs on every invocation.
 * Run the instruction a few times as a sanity check. Also make sure
 * it's not outputting the same value over and over, which has happened
 * as a result of past CPU bugs.
 */
void x86_init_rdrand(struct cpuinfo_x86 *c)
{
	enum { SAMPLES = 8, MIN_CHANGE = 5 };
	…
	if (failure) {
		clear_cpu_cap(c, X86_FEATURE_RDRAND);
		clear_cpu_cap(c, X86_FEATURE_RDSEED);
		pr_emerg("RDRAND is not reliable on this platform; disabling.\n");
	}
}
```
<https://github.com/torvalds/linux/blob/v6.12/arch/x86/kernel/cpu/rdrand.c>

This catches stuck-at outputs (the real AMD errata). It does **not** and cannot catch a
CPU RNG that is biased or backdoored but varying. That residual risk is the whole argument
for §7.6.

### 7.4 How long initialisation takes without a CPU RNG

If RDRAND/RDSEED are absent (pre-2012 Intel, some VMs with the feature masked) or
`random.trust_cpu=off` is set, `arch_bits` is credited as 0 and the pool must fill from
interrupt timing and the jitter loop.

- `add_interrupt_randomness()` *"feeds the input pool roughly once a second or after 64
  interrupts, crediting 1 bit of entropy for whichever comes first"* (random.c comment).
  256 bits at 1 bit/second alone would be ~4 minutes — but that is not the operative path.
- `wait_for_random_bytes()` calls `try_to_generate_entropy()`, which measures the cycle
  counter, computes `samples_per_bit = DIV_ROUND_UP(8192, num_different + 1)`, bails if
  that exceeds `MAX_SAMPLES_PER_BIT = HZ / 15`, and otherwise arms a timer that credits
  1 bit every `samples_per_bit` firings.

**[derived]** With Debian's `CONFIG_HZ=250`, `MAX_SAMPLES_PER_BIT` = 16 and the timer fires
once per tick (4 ms). Reaching 256 bits therefore costs between ~1 s (1 sample/bit, a
machine with a fine-grained TSC) and ~16 s (16 samples/bit, worst accepted case). This is an
arithmetic bound read off the source, **not a measurement** — it should be confirmed on the
actual target hardware by timing the `crng init done` line.

Verification command for the build/QA checklist:
`dmesg | grep -E 'crng init done|RDRAND is not reliable'` — a `crng init done` timestamp at
essentially `[0.000000]` means it came from RDSEED/RDRAND in `random_init_early()`.

### 7.5 Which userspace API to use

From `random.c`'s own comments and `getrandom(2)`:

- **`getrandom(buf, len, 0)`** — blocks until `crng_ready()`, then never blocks again:
  ```c
  if (!crng_ready() && !(flags & GRND_INSECURE)) {
  	if (flags & GRND_NONBLOCK)
  		return -EAGAIN;
  	ret = wait_for_random_bytes();
  ```
  This is the correct call. In Rust it is what the `getrandom` crate and
  `rand::rngs::OsRng` do by default.
- **`GRND_RANDOM`** — `include/uapi/linux/random.h` at v6.12 annotates it
  `/* GRND_RANDOM  No effect */`. Do not use it, do not reason about it.
- **`GRND_INSECURE`** — returns non-cryptographic bytes. Never.
- **Reading `/dev/urandom`** — random.c: *"Reading from /dev/urandom has the same
  functionality as calling getrandom(2) with flags=GRND_INSECURE. Because it does not block
  waiting for the RNG to be ready, it should not be used."* So: **the signer must not read
  `/dev/urandom`.** Use `getrandom(2)`.
- `random(4)` on the seed-file practice (*"If a seed file is saved across reboots as
  recommended below…"*) is **not applicable and must not be implemented** — writing a seed
  file is exactly the persistence we are forbidding, and §7.1 shows it buys nothing on
  amd64. <https://man7.org/linux/man-pages/man4/random.4.html>

### 7.6 The open question to hand to the entropy-policy ticket

There is a precise, cheap posture available that I did not find discussed anywhere and that
follows directly from the source:

`extract_entropy()` pulls RDSEED (falling back to RDRAND, falling back to
`random_get_entropy()`) into `block.rdseed[]` on **every single extraction**, unconditionally
— `trust_cpu` has no bearing on it:

```c
	for (i = 0; i < ARRAY_SIZE(block.rdseed);) {
		longs = arch_get_random_seed_longs(&block.rdseed[i], ARRAY_SIZE(block.rdseed) - i);
		…
	/* next_key = HASHPRF(seed, RDSEED || 0) */
	/* output = HASHPRF(seed, RDSEED || ++counter) */
```

Therefore booting with **`random.trust_cpu=off`** gives us: *RDRAND/RDSEED output is still
mixed into every extraction, but the CSPRNG is not declared ready on its word alone* — the
256 initialisation bits come from timing jitter instead. The cost is the ~1–16 s of §7.4
**[derived]**, once, at boot, before the UI appears; the benefit is that a compromised CPU
RNG cannot by itself determine the state that generates a wallet seed.

For a device whose only job is to generate and protect a Bitcoin seed, that trade looks
right. **Recommendation to the entropy ticket: default to `random.trust_cpu=off` and pay
the seconds** — but confirm the real delay on target hardware first, and make sure the
signer blocks on `getrandom()` behind a visible "gathering entropy" state rather than
appearing hung.

Note also: a physical keyboard and a USB camera are both interrupt sources, so by the time
a user has typed a passphrase the pool has had substantial additional input regardless.

---

## Summary of recommendations

| Area | Recommendation |
|---|---|
| Toolchain | `live-build`, version-pinned, `SOURCE_DATE_EPOCH` set from v1. Only tool of the four that emits an ISO; already reproducibility-aware; Debian's own. |
| Kiosk | `cage` (Wayland) + `seatd` + a systemd `Restart=always` unit as an unprivileged user. No DM, no greeter, no XWayland, no getty (`NAutoVTs=0`, `ReserveVT=0`), `kernel.sysrq=0`. Crash → clean restart with no wallet. |
| No network | Primary: delete `drivers/net`, `drivers/bluetooth` and net protocol modules from both squashfs *and* initramfs; ship no firmware. Secondary: `install … /bin/false`. Never rely on `blacklist` or on `ip link down`. `CONFIG_NET=n` is rejected — it kills AF_UNIX. |
| No swap / persistence | live-boot defaults are already amnesic; just never pass `persistence` or `swap`. Add `nopersistence`, `nohibernate`, neuter `swapon`, mask `swap.target`, `Storage=none` + `ProcessSizeMax=0` for coredumps, no `kdump-tools`, no `crashkernel=`, no udisks2/gvfs. |
| RAM wipe | `init_on_free=1` plus freeing the overlayfs upper dir on shutdown — **the second half reversed by [#62](https://github.com/allisson/aobs/issues/62); see the note above**. Skip Tails' memlockd/udev-watchdog/initramfs-shutdown machinery. It is a clean-shutdown guarantee only — it does nothing after a hard power cut, does not cover all kernel memory, and does not replace in-app zeroization. |
| Camera | USB UVC only, `uvcvideo` already in `linux-image`, 0 extra packages. Skip `v4l-utils` in the release image. MC-centric (IPU6) cameras are out of scope for v1; say so in the hardware floor. |
| Entropy | `getrandom(2)` with flags=0, never `/dev/urandom`, never a seed file. CSPRNG is ready before userspace on any RDRAND-capable amd64. Open recommendation: `random.trust_cpu=off` so the CPU RNG is mixed in but not trusted for initialisation; verify the resulting boot delay on hardware. |
