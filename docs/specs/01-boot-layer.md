# 01 — The boot layer

The image is part of the security model, so it is specified rather than configured by taste.
Sources: [#4](https://github.com/allisson/aobs/issues/4),
[#5](https://github.com/allisson/aobs/issues/5),
[#24](https://github.com/allisson/aobs/issues/24),
[#25](https://github.com/allisson/aobs/issues/25),
[#8](https://github.com/allisson/aobs/issues/8).

Target: Debian 13 (trixie), amd64, kernel 6.12 line.

## 1. Build toolchain: `live-build`

`live-build`, not `mkosi`, not `debos`, not hand-rolled `debootstrap` + `xorriso`.

Two facts decide it. It is the only candidate that emits an ISO, which the deliverable fixes. And it
is *ahead* on reproducibility rather than behind: it already threads `SOURCE_DATE_EPOCH` through
`xorriso --modification-date`, the ESP volume ID, ISO and `.disk` mtime normalisation and every
chroot command, and ships `test/rebuild.sh` as a first-party rebuild-and-compare harness against
`snapshot.debian.org`. The v2 reproducibility goal is therefore a *pinning* exercise, not a
toolchain migration.

**Required in v1, one line each, and they are the difference between "reproducibility is a config
change" and "reproducibility is a rewrite":**

- Pin the live-build version.
- Set `SOURCE_DATE_EPOCH` from the first build.

Customisation surface: `config/package-lists/*.list.chroot`, `config/includes.chroot/`,
`config/hooks/normal/*.hook.chroot`. Accepted downsides, recorded so they are not rediscovered as
defects: it is shell scripts, `config/` is stateful, and `lb build` needs root.

## 2. Kiosk: there is no display server

Slint on `backend-linuxkms` + `renderer-software`, rendering straight to KMS/DRM. **No X server, no
Wayland compositor, no `cage`, no display manager, no GPU driver requirement.** The ISO boots to a
single Rust binary holding DRM master on tty1.

The 22 packages this needs are `libinput`, `libseat`, `libxkbcommon`, `freetype`, `fontconfig`,
`fonts-dejavu` and their closure — 21 MiB. That is the irreducible floor for any KMS GUI, not
Slint's overhead.

- Unprivileged user `signer`, in `video`, `input`, and **whatever group `seatd.service` names**.
  This last one was written as `_seatd`, which is the upstream and Arch convention; **Debian has no
  such group** and runs `ExecStart=seatd -g video`, so on this distribution the seat group and the
  DRM group are the same one. Following the literal text fails the build with `216/GROUP`. The build
  hook therefore reads the group out of the unit rather than hardcoding either name, so a Debian
  that later switches to a dedicated group fails the build instead of shipping an appliance that
  cannot open a seat.
- `seatd` (104 KiB) with `LIBSEAT_BACKEND=seatd`.
- A systemd unit, `ExecStart=/usr/bin/aobs`, `Restart=always`.
- `greetd` is rejected: its `initial_session` runs exactly once per boot by design, which is the
  opposite of what a restarting kiosk needs.

**Crash behaviour is a stated product fact, not an incident.** The app dies → systemd restarts it →
a blank signer with no wallet. That is correct amnesic behaviour: the in-memory wallet is gone and
the user re-enters the seed. Document it; do not engineer around it.

**No shell escape.** Four controls, all cheap, all required:

1. `NAutoVTs=0` and `ReserveVT=0` in `logind.conf` — no gettys at all, not even the default.
2. `kernel.sysrq=0`.
3. No terminal emulator, no SSH server, no login prompt on any tty.
4. `TTYVTDisallocate=yes`, `vt.global_cursor_default=0`.

Nothing on this image is meant to be driven from a shell, so one is only a mistake surface and it
advertises a capability the appliance does not offer.

## 3. No network — enforced, not configured

Ranked by how hard each is to undo accidentally. **Ship 2 and 3 together; 1 is rejected; 4 is
understood but not used as a control.**

1. **`CONFIG_NET=n` — rejected, and it does not work.** `net/unix/Kconfig` is sourced from inside
   `if NET … endif`, so **AF_UNIX disappears with `CONFIG_NET`**. Wayland, D-Bus and systemd all
   need it. It would also mean abandoning Debian's signed kernel.
2. **Ship no network driver modules at all — the primary control.** A chroot hook deletes
   `/lib/modules/*/kernel/drivers/net/`, `/lib/modules/*/kernel/drivers/bluetooth/` and
   `/lib/modules/*/kernel/net/`, then runs `depmod`. Install no `firmware-*` package. Undoing it
   requires rebuilding the ISO: the rootfs is a read-only squashfs with a tmpfs overlay, so there is
   no `.ko` on the medium to `insmod`, and the QR-only channel gives no way to bring one in.
   **The initramfs must be stripped too** — `initramfs-tools` defaults to `MODULES=most`, which
   bundles net drivers independently of the squashfs. Set `MODULES=dep` or prune the same paths.
3. **`install <module> /bin/false` in `/etc/modprobe.d/`.** Blocks `modprobe` and udev autoload but
   not `insmod` on a `.ko` that is still present. A complement to 2, not a substitute.
4. **`blacklist <module>` is not this.** It suppresses *alias-driven* loading only; an explicit
   `modprobe e1000e` still loads. Do not use it where the intent is "never load this".

No `network-manager` (7.6 MiB saved, worthless as a guarantee on its own).

**"No network" here means no link layer to any physical interface, not "no network stack".**
Loopback and AF_UNIX stay intact deliberately.

Build check: `lsinitramfs` shows no `drivers/net` entries.

## 4. No swap, no persistence, no crash dumps

The live-boot defaults are already amnesic — `components/3020-swap` returns immediately unless a
`swap`/`live-boot.swap=` parameter is on the cmdline. So the primary control is simply **never put
`persistence` or `swap` on the kernel command line**, with `nopersistence` added as a
belt-and-braces marker.

Beyond that:

- Neuter `/sbin/swapon` in a hook, and `systemctl mask swap.target`.
- `nohibernate` on the cmdline; `AllowHibernation=no` in `sleep.conf`;
  `HandleLidSwitch=ignore` and `HandleSuspendKey=ignore`, so a closed lid cannot suspend a machine
  holding a seed.
- **There is no `noswap` kernel parameter.** Do not cargo-cult it onto the cmdline.
- Kernel crash dumps: no `kdump-tools` package, no `crashkernel=`.
- Userspace crash dumps: `Storage=none` **and** `ProcessSizeMax=0` in `coredump.conf.d/`. This
  matters more than it looks — the default `Storage=external` writes a **complete copy of the seed
  to a file with a predictable name**, tmpfs or not.
- Auto-mount: no `udisks2`, no `gvfs`, no file manager, no desktop environment. Nothing exists to
  mount anything. Do **not** try to solve this by removing filesystem modules; `squashfs`,
  `overlay`, `isofs` and `vfat` are needed to boot.

## 5. RAM wipe at shutdown, and what it does not survive

**`init_on_free=1` on the cmdline, plus freeing the overlayfs upper dir on shutdown.** There is no
boot-time cost — poisoning is a steady-state allocator overhead, not a startup or shutdown pass.

**Skipped deliberately:** Tails' `memlockd`, `udev-watchdog` and initramfs-shutdown machinery. That
machinery almost entirely buys protection against a *present* adversary, which the threat model
excludes. Tails' pre-3.0 approach of booting a second kernel to wipe free memory was removed
upstream for "severe usability and reliability problems"; do not resurrect it.

**What it does not survive, stated in the user docs rather than buried:**

1. **A hard power cut.** Poisoning fires when memory is *freed*. Cut power and nothing is freed.
   This is a clean-shutdown guarantee only. **It is not a panic button.**
2. **Physical remanence.** Data can remain in RAM for minutes after shutdown. The wipe narrows the
   window; it does not close it.
3. **Kernel memory**, some of which is not erased at all.
4. **Anything the app is still holding.** Freeing is what *triggers* poisoning, so this is no
   substitute for prompt in-app zeroization.

Shutdown covers secrets twice, because the two mechanisms fail differently: `ZeroizeOnDrop` covers a
clean exit and a panic but not a kernel abort; `init_on_free=1` covers the process dying any which
way but survives no hard power cut. **No third mechanism** — a scrubbing ceremony would imply
defending the cold-boot adversary the map declined.

## 6. Kernel command line

```
quiet loglevel=3 panic=0 nopersistence nohibernate init_on_free=1 \
random.trust_cpu=off vt.global_cursor_default=0 toram
```

- `quiet loglevel=3` — boot messages do not compete for the panel.
- `panic=0` — a kernel panic **halts with the message visible** instead of rebooting it away.
- `random.trust_cpu=off` — see §8.
- `toram` — see §7.

## 7. Hardware floor

**UEFI amd64 only. `toram` by default. 2 GiB minimum, 4 GiB recommended (provisional).**

### UEFI is required because it deletes the worst failure rather than handling it

> **Falsified by the walking skeleton. Do not build on this section until
> [#40](https://github.com/allisson/aobs/issues/40) resolves.** Debian 13 sets neither
> `CONFIG_DRM_SIMPLEDRM` nor `CONFIG_SYSFB_SIMPLEFB`, ships no `simpledrm.ko`, and lets `efifb`
> claim the framebuffer. The guaranteed display path below **does not exist on the distribution
> this spec ships**, which inverts the paragraph's conclusion: the native KMS driver is the
> requirement and there is no fallback. §9 below inherits the same error.

The worst case in this area is "no usable display", because reporting it requires the thing that
failed. On UEFI the EFI stub hands the kernel a `simple-framebuffer`, and **`simpledrm` binds it as
a full KMS device with dumb buffers** — `drivers/gpu/drm/tiny/simpledrm.c` declares
`DRM_GEM_SHMEM_DRIVER_OPS` with `DRIVER_ATOMIC | DRIVER_GEM | DRIVER_MODESET`, which is exactly what
`backend-linuxkms` + `renderer-software` needs. **Every UEFI machine therefore has a guaranteed
display path with no GPU driver at all**, and `i915`/`amdgpu`/`nouveau` become an optimisation.

Legacy BIOS has no equivalent: without a native KMS driver you get `vesafb`-class fbdev, which is
not DRM and which Slint cannot render to. The user would see the GRUB menu and then unexplainable
blackness.

**Named cost, accepted:** machines older than roughly 2012 are excluded — real, since repurposed old
laptops are this product's natural hardware.

No CPU feature is required. `random.trust_cpu=off` already made RDRAND/RDSEED a performance question
rather than a correctness one.

### `toram`, and the low-memory escape

`toram` earns its RAM here for two product reasons: the user can **pull the stick once booted**, and
**yanking it cannot kill a session mid-signature**.

The floor rule is *image size + working set (squashfs decompression, the software renderer's
framebuffers, camera frame buffers) + the Argon2id 64 MiB spike*. The number is provisional until
confirmed against the built image.

**Two GRUB entries**, so insufficient RAM degrades instead of bricking:

1. `toram` — the default.
2. *"low memory: keep the USB inserted"* — same cmdline without `toram`.

### Camera

**USB UVC only.** `uvcvideo` is already in Debian's kernel (`CONFIG_USB_VIDEO_CLASS=m`), so a USB
UVC webcam costs **zero extra packages**: the module autoloads, udev creates `/dev/videoN`, and the
app talks V4L2 ioctls directly. The `signer` user needs `video`.

MC-centric devices (modern Intel IPU6/MIPI laptop cameras) need media-controller pipeline
configuration plus proprietary firmware plus libcamera, and are **out of scope for v1**. Probe
`/dev/video*` for `V4L2_CAP_VIDEO_CAPTURE` **without** `V4L2_CAP_IO_MC` and say so clearly rather
than failing obscurely. Cost of that decision: 0 bytes.

Do not install `libv4l-0t64` or `v4l-utils` in the release image. Request `GREY` or `YUYV` from the
camera, **never `MJPG`** — MJPEG would put a JPEG decoder on the hostile-input path for no benefit,
since QR decoding needs luminance only.

### Degraded operation

| Missing | Behaviour |
|---|---|
| Camera | **Degraded but useful.** Create a wallet, see the identity screen, export the watch-only QR, export the encrypted backup QR. Lost: signing and receive-address verification, both of which need a scan. Those actions are shown **visibly unavailable with a stated reason** — not hidden, not an error. |
| Keyboard | **Fatal but reportable.** The GUI is up, so there is a screen to say it on. It names the problem and keeps polling, so hot-plug recovers without a reboot. |
| Display path | Structurally impossible after UEFI-only. |

V4L2 devices are enumerated **at the point of use, not at startup**, so plugging a camera in later
simply works. No udev monitoring, no daemon, no reboot.

## 8. Entropy at boot

`getrandom(2)` is trustworthy immediately after boot on modern amd64 with no seed file:
`random_init_early()` credits 512 bits from RDSEED/RDRAND against a 256-bit `POOL_READY_BITS`
threshold, before the first userspace instruction. A live system with no carried-over seed is not
disadvantaged at all.

**aobs boots with `random.trust_cpu=off` anyway.** That withdraws the credit and makes the pool fill
from timing jitter, while `extract_entropy()` continues to pull RDSEED into **every** extraction
regardless of `trust_cpu`. So the CPU RNG is still mixed in; it just never determines readiness on
its own word. We already decline to trust this machine's firmware, and trusting an opaque
instruction from the same vendor to solely determine the state that generates a wallet seed was the
inconsistency.

Cost: **~1–16 s once at boot** — derived arithmetically from `random.c` with Debian's `CONFIG_HZ=250`,
**not measured**. Two obligations follow:

- The signer blocks on `getrandom(buf, len, 0)` behind a visible **"gathering entropy"** state
  rather than appearing hung (`04-screens.md` §3).
- The real delay is timed on target hardware before release (`05-testing-and-release.md` §6).

**Forbidden, each for a documented reason:**

- `/dev/urandom` — documented upstream as equivalent to `GRND_INSECURE`.
- `GRND_RANDOM` — annotated `/* No effect */` in `uapi/linux/random.h`.
- `GRND_INSECURE` — never.
- A seed file — it is exactly the persistence we forbid, and it buys nothing on amd64.

Verification for the QA checklist: `dmesg | grep -E 'crng init done|RDRAND is not reliable'`.

## 9. Reporting a failure the GUI cannot report itself

Because `simpledrm` is guaranteed, the kernel console always exists — there is always a channel.

> The premise is wrong ([#40](https://github.com/allisson/aobs/issues/40), §7 above), but **the
> conclusion survives**: `efifb` provides a kernel console on exactly the machines `simpledrm` was
> supposed to cover, so this section's channel exists either way. Verified against the built ISO —
> the appliance finds no DRM device, prints the block below, and halts with it visible.

The app is launched by a wrapper that, on any startup failure, prints a **human-written diagnostic
block** and halts:

- one sentence naming what failed;
- one on what it likely means;
- one on what to do;
- the version and build date;
- a short failure code so a bug report is actionable.

Not a stack trace, not systemd's default spew. Halt with the text visible; do not power off.

**The diagnostic prints only fixed strings and typed error-variant names, never formatted program
state** — the same rule that governs logs and `Debug`, extended to the one output path that survives
a crash.

## 10. Build requirements that come from the app side

- **`panic = "unwind"` in the release profile, never `abort`.** The zeroization guarantee lives in
  `ZeroizeOnDrop`, and **drop glue does not run on abort**. An aborting crash with a wallet loaded
  would leave key material in RAM until the shutdown wipe. The top level catches, zeroizes, and
  exits into §9. Enforced by a mechanical CI check.
- The version string and build date are displayed by the appliance and appear in the crash
  diagnostic. They make no security claim and therefore cannot make a false one.
