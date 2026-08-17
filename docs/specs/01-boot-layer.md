# 01 — The boot layer

The image is part of the security model, so it is specified rather than configured by taste.
Sources: [#4](https://github.com/allisson/aobs/issues/4),
[#5](https://github.com/allisson/aobs/issues/5),
[#24](https://github.com/allisson/aobs/issues/24),
[#25](https://github.com/allisson/aobs/issues/25),
[#8](https://github.com/allisson/aobs/issues/8).

Target: Debian 13 (trixie), amd64, kernel 6.12 line.

**The base distribution was re-examined and kept.** Alpine was priced as a candidate when Debian's
missing `simpledrm` falsified the display story
([#45](https://github.com/allisson/aobs/issues/45), ADR-0016) and **not taken** — 18 of this file's
controls port, 16 need rework, 4 are lost. §1–§3 therefore stand as written, corrected in place rather
than handed to a migration. Debian's own MR !1453 sets both `simpledrm` symbols for forky, which will
shrink the fbdev tier of §7 with no change on our side.

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

Slint on **`backend-linuxkms-noseat`** + `renderer-software`, rendering straight to the display with
**no seat daemon**. **No X server, no Wayland compositor, no `cage`, no display manager, no GPU driver
requirement.** The ISO boots to a single Rust binary that owns the panel — as DRM master where the
machine has a DRM device, and as the only writer of `/dev/fb0` where it does not (§7, ADR-0016).

The package floor is `libinput`, `libxkbcommon`, `freetype`, `fontconfig`, `fonts-dejavu` and their
closure. That is the irreducible floor for any GUI on bare KMS, not Slint's overhead. **The count and
size are an owed measurement** (`00-overview.md`): the *22 packages / 21 MiB* measured for ADR-0002
included `libseat1` and `seatd`, which this image no longer ships.

- Unprivileged user `signer`, in **`video`, `input` and `dialout`, and no fourth group.** The first two
  are what the appliance needs, read from systemd's own udev rules rather than from convention:
  `/dev/fb0` is `SUBSYSTEM=="graphics"` → `root:video`, `/dev/dri/card0` → `root:video`, `/dev/video0` →
  `root:video`, `/dev/input/event*` → `root:input`.
- **`dialout` is for the serial mirror, and it is stated here rather than discovered later.** The app
  writes its markers to `/dev/ttyS0` as well as to stdout (§9), which is how the QEMU harness asserts
  anything at all (`05-testing-and-release.md` §6.2). This spec said *no third group* until
  [#57](https://github.com/allisson/aobs/issues/57) found the tree already had one and the reason was
  sound. The rejected alternative was `console=ttyS0` on the kernel command line, which would change
  what **every user's** machine does in order to serve CI, against a cmdline §6 fixes verbatim.
  Dropping the mirror entirely was rejected too: it costs §6.2 its assertion and pushes CI onto
  screenshot diffing, and a gate that is painful is a gate that gets skipped.
- **No `seatd`, no `libseat1`, and `LIBSEAT_BACKEND` is not set.** `libseat` was what stopped
  `/dev/fb0` from being opened at all: under the `seatd` backend the open is delegated to a daemon
  that hands back DRM and evdev nodes only. `-noseat` makes it a plain `open(2)`. Slint's own note
  that `-noseat` requires running "as a user privileged to access all input and DRM/KMS device files"
  is a statement about file permissions, which group membership satisfies.
- A systemd unit:

  ```
  User=signer
  Environment=XKB_DEFAULT_RULES=evdev
  Environment=XKB_DEFAULT_MODEL=pc105
  Environment=XKB_DEFAULT_LAYOUT=us
  Type=notify
  NotifyAccess=all
  ExecStart=/usr/lib/aobs/launch
  ExecStartPost=+/usr/lib/aobs/console-detach
  ExecStopPost=+/usr/lib/aobs/console-attach
  Restart=always
  StandardOutput=journal+console
  ```

  - **The keymap is pinned to `evdev`/`pc105`/`us`, and no layout choice is offered.** Slint's
    linuxkms backend compiles its keymap with every RMLVO field defaulted —
    `Keymap::new_from_names(&ctx, "", "", "", "", None, 0)` in `calloop_backend/input.rs`, under a
    context created with `CONTEXT_NO_FLAGS` — and libxkbcommon fills defaulted fields from
    `XKB_DEFAULT_*`, falling back to its build-time defaults, upstream `evdev`/`pc105`/`us`. The three
    lines therefore change nothing about today's behaviour; they make it a **decision** rather than an
    inherited default that a distribution build flag or a stray environment could move under us.
    `pc105` is that upstream default and the superset geometry: the extra ISO key it carries is
    unmapped in `us` and reaches nothing that is not reachable elsewhere.
  - **`XKB_DEFAULT_VARIANT` and `XKB_DEFAULT_OPTIONS` stay unset.** No dead keys, and no
    group-switch toggle — a second group would be an invisible mode with nothing on screen to name
    it, in a field where a wrong character is the whole risk.
  - **No package is owed for any of this.** `libxkbcommon0` **depends on** `xkb-data`, so the entire
    layout database is already inside the floor above. Which layout, and why no picker, is
    `04-screens.md` §5.1, where the cost is named.
  - **`Type=notify` is load-bearing.** The app sends `READY=1` once its window is up. With
    `Type=simple` the console detach would fire before the app is drawing, and a startup failure
    would print §9's diagnostic to a console that is already gone.
  - **`NotifyAccess=all`, never `main`.** `launch` deliberately does not `exec` the binary — the §9
    fallback text after it is the whole reason the wrapper exists — so the notifying process is never
    the main PID, and `main` drops the datagram silently until the unit times out.
  - **The `+` prefix is what keeps the app unprivileged.** systemd runs the two console scripts as
    root inside a `User=signer` unit; the app never gains a capability. Verified in
    [#52](https://github.com/allisson/aobs/issues/52).
  - **`console-detach` unbinds `fbcon`, found by name** in `/sys/class/vtconsole/vtcon*/name`, never
    by a hardcoded index. `console-attach` rebinds it, so §9 has a channel again after the app stops.
    Why this exists is §7; that it works is [#52](https://github.com/allisson/aobs/issues/52).
- **The unit must not be coupled to VT1.** No `TTYPath`, no `StandardInput=tty`, no `TTYReset`, no
  `TTYVHangup`, and no `TTYVTDisallocate` — see the shell-escape controls below, where the last of
  those used to live. The app reads no stdin: input is libinput on `/dev/input/*`.
- **Nothing may be written to the console after the first frame.** `console-detach` writes nothing to
  the unit's stdout or stderr — both inherit `journal+console`, so a status line from it would land on
  the panel; anything it needs to say goes to the journal directly. Anything printed in the
  window between the first paint and the unbind completing **stays on the panel** — Slint does not
  repaint it away. The readiness line is safe because it is emitted before the first paint and the
  first frame covers it.
- **The readiness line is `AOBS_READY version=… build=… display=fbdev|drm`.** It names the tier that
  won, which is what lets CI's two display rows fail honestly (`05-testing-and-release.md` §6.2), and
  its absence is what triggers the crash-diagnostic path.
- `greetd` is rejected: its `initial_session` runs exactly once per boot by design, which is the
  opposite of what a restarting kiosk needs.

**Crash behaviour is a stated product fact, not an incident.** The app dies → systemd restarts it →
a blank signer with no wallet. That is correct amnesic behaviour: the in-memory wallet is gone and
the user re-enters the seed. Document it; do not engineer around it.

**No shell escape.** Three controls, all cheap, all required, plus one that had to be dropped:

1. `NAutoVTs=0` and `ReserveVT=0` in `logind.conf` — no gettys at all, not even the default.
2. `kernel.sysrq=0`.
3. No terminal emulator, no SSH server, no login prompt on any tty.
4. `vt.global_cursor_default=0` on the cmdline.

**`TTYVTDisallocate=yes` is gone, deliberately.** It was listed here as a control, and on this unit it
**kills the appliance the moment `fbcon` unbinds** — [#52](https://github.com/allisson/aobs/issues/52)
watched the service die five times in a row behind a black panel because of it. Nothing is lost:
control 1 leaves no getty to allocate a VT in the first place, so there is no VT holding readable text
for it to clear. Do not add it back without re-running #52's probe.

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

   **The same hook deletes `amdgpu.ko`, `xe.ko` and `radeon.ko`, for a different reason** (§7,
   ADR-0016): with no `firmware-*` package installed none of the three can ever initialise on this
   image, and each removes the framebuffer aperture *before* failing, destroying a working `efifb`
   with no way to put it back. Same paths, same `depmod`, same initramfs pruning. `efifb` itself is
   built in (`CONFIG_FB_EFI=y`) and cannot be pruned this way.
3. **`install <module> /bin/false` in `/etc/modprobe.d/`.** Blocks `modprobe` and udev autoload but
   not `insmod` on a `.ko` that is still present. A complement to 2, not a substitute.
4. **`blacklist <module>` is not this.** It suppresses *alias-driven* loading only; an explicit
   `modprobe e1000e` still loads. Do not use it where the intent is "never load this".

No `network-manager` (7.6 MiB saved, worthless as a guarantee on its own).

**"No network" here means no link layer to any physical interface, not "no network stack".**
Loopback and AF_UNIX stay intact deliberately.

Build check: `lsinitramfs` shows no `drivers/net` entries, and neither the module tree nor the
initramfs contains `amdgpu.ko`, `xe.ko` or `radeon.ko` (`05-testing-and-release.md` §6.1).

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

**`init_on_free=1` on the cmdline, and nothing else.** There is no boot-time cost — poisoning is a
steady-state allocator overhead, not a startup or shutdown pass.

**What actually protects the wallet is the process dying.** The wallet lives in the app's anonymous
memory, never on a filesystem. `04-screens.md` §13's *end the session* is a shutdown: systemd stops the
unit, the process dies, and **process death frees its pages** — which is what `init_on_free=1` poisons.
That path holds however the process dies, and it does not involve the overlay at all.

**The overlayfs upper dir is deliberately not claimed**, and this is a correction
([#62](https://github.com/allisson/aobs/issues/62)) rather than an omission. This section used to read
*"plus freeing the overlayfs upper dir on shutdown"*, which was half of Tails' two-part mechanism:
`docs/research/04-amnesic-boot-layer.md` records that a normal shutdown **never frees that branch**, so
Tails both switches root back into an initramfs to get the rootfs unmounted *and* deletes the upper dir
from a late service, having found the initramfs jump alone *"necessary but not sufficient"*. This spec
refuses the switch-root machinery below, so what was kept was the half that cannot stand alone — and
nothing ever implemented it.

Deleting it is the honest correction on three grounds, in order of weight:

1. **Nothing secret is written to a filesystem here.** No wallet file, no config, no cache, no
   transaction history — all settled absences — no coredumps (§4), and no swap. The claim the appliance
   actually makes is stronger than the one the clause made, and it is checkable: `docs/qa-checklist.md`
   carries a row that a full session leaves the upper dir holding nothing the app wrote.
2. **The dangerous step would have been ours to make safe.** Deleting the running root's upper dir late
   in shutdown reverts or removes files the rest of the shutdown path still needs; Tails runs `memlockd`
   precisely to survive that, and it is machinery this section declines by name.
3. **It would be a third mechanism**, bought against the cold-boot adversary the threat model excludes,
   which is exactly what the rule at the end of this section forbids.

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
5. **The overlayfs upper dir and the page cache**, which a normal shutdown does not free at all. Stated
   because it is the thing this section used to claim: those pages keep whatever the running system
   wrote until power is cut and the DRAM decays. What makes that acceptable is not a mechanism but an
   absence — nothing secret is written there.

Shutdown covers secrets twice, because the two mechanisms fail differently: `ZeroizeOnDrop` covers a
clean exit and a panic but not a kernel abort; `init_on_free=1` covers the process dying any which
way but survives no hard power cut. **No third mechanism** — a scrubbing ceremony would imply
defending the cold-boot adversary the map declined.

## 6. Kernel command line

```
quiet loglevel=3 panic=0 nopersistence nohibernate init_on_free=1 \
random.trust_cpu=off vt.global_cursor_default=0 toram
```

- `quiet loglevel=3` — boot messages do not compete for the panel. On the fbdev tier this is also a
  narrowing, not just tidiness: everything below CRIT is gone, so only an oops, a panic, an NMI or an
  MCE can reach the panel at all. **No `loglevel` value can suppress those** — the NMI lines are
  `pr_emerg`, and suppressing EMERG would suppress the panic text §9 depends on. Hence §2's console
  detach.
- `panic=0` — a kernel panic **halts with the message visible** instead of rebooting it away.
- `random.trust_cpu=off` — see §8.
- `toram` — see §7.

## 7. Hardware floor

**UEFI amd64 only. `toram` by default. 2 GiB minimum, 4 GiB recommended (provisional). A framebuffer
of at least 800×600.**

### Two display tiers, and that is what deletes the worst failure

The worst case in this area is "no usable display", because reporting it requires the thing that
failed. **`simpledrm` is not what deletes it** — Debian 13 sets neither `CONFIG_DRM_SIMPLEDRM` nor
`CONFIG_SYSFB_SIMPLEFB` and ships no `simpledrm.ko`, so on this image `sysfb` registers an
`efi-framebuffer` for `efifb` and no `/dev/dri` node is ever created on a machine with no native KMS
driver ([#40](https://github.com/allisson/aobs/issues/40), which falsified the original reasoning).
**Two tiers delete it instead** (ADR-0016):

| The machine has | The appliance draws through | Protection from console text |
|---|---|---|
| A DRM device (`i915`, `nouveau`, `virtio-gpu`, `ast`, …) | a DRM dumb buffer | the kernel's own — a DRM master is never displaced by `fbcon`, and the console is restored on `lastclose` |
| No DRM device | `/dev/fb0`, provided by `efifb` from the EFI stub's framebuffer | `fbcon` detached for exactly the interval the app is drawing (§2) |

Slint chooses between them at runtime, per machine, in `display/swdisplay.rs`: `DumbBufferDisplay`
first, `.or_else` into `LinuxFBDisplay`. **So the second tier reaches only the machines that would
otherwise be black**, and nothing already covered changes.

Four consequences, each a named cost rather than a hope:

- **`amdgpu`, `xe` and `radeon` are deleted from the image** (§3). Firmware-less they can never
  initialise here, and each takes the framebuffer aperture before failing. Deleting them turns modern
  AMD, Radeon HD 2000+, Lunar Lake and Battlemage from *unreportable blackness* into *draws*.
- **No vsync on the fbdev tier**, by construction in both Slint and `efifb`. It shows on moving
  content, which is the camera preview only; QR decode runs on the V4L2 frame, not the presented
  buffer, so it costs appearance and never correctness.
- **A framebuffer format outside `LinuxFBDisplay`'s five accepted arms** reaches `AOBS-E05` on a live
  console. `efifb` under OVMF reports 32 bpp with r/g/b at 16/8/0 and alpha at 24, which negotiates to
  `Argb8888`; real firmware is covered by the per-release tested-hardware list
  (`05-testing-and-release.md` §6.3), not by an assumption here.
- **Accepted and unquantified:** a driver we *keep* — `i915`, `nouveau`, `ast`, `mgag200`, `gma500`,
  `udl`, `hyperv` — that removes the aperture and then fails for a reason unrelated to firmware.
  `gma500`'s legacy modesetting is the most likely instance. No cheap control covers it.

**UEFI amd64 only still, but for a smaller reason.** `vesafb` is a framebuffer too, so legacy BIOS
would now have a display path; what it would also have is a second GRUB configuration, a second CI
matrix, and a pixel format nobody has checked against those five arms. **UEFI-only stands on
build-and-test surface, not on "no display path exists".**

**Named cost, accepted:** machines older than roughly 2012 are excluded. Still real, and now
unnecessary rather than structural — which is the honest way to state it.

**The compatibility statement is a floor, not a hardware list:** *UEFI amd64, any machine whose
firmware hands over a framebuffer **of at least 800×600**.* The empirical claim belongs to the
tested-hardware list published with each release.

**The resolution qualifier, and why the floor owes one.** A mode below 800×600 reaches the startup
diagnostic of §9 on a live console rather than a drawn UI, in the same class as a pixel format outside
`LinuxFBDisplay`'s five arms: the panel is there and the review screen cannot be drawn honestly on it,
so booting into it would sell the one property the appliance exists for. 800×600 is edk2's default GOP
mode (`MdeModulePkg.dec`: `PcdVideoHorizontalResolution|800`, `PcdVideoVerticalResolution|600` — `0`
there would mean *highest available*), which is what OVMF hands the CI rows in
`05-testing-and-release.md` §6.2 and what a BMC or older firmware hands a user, so the floor sits
exactly on the common case rather than above it. The layout policy that makes 800×600 sufficient — one
design canvas, a scale factor above it, reflow below it — is `04-screens.md` §0. **Named cost:**
640×480-class firmware is excluded, on machines at or below the ~2012 line already excluded above.

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
| Display path | **Reportable, not impossible.** No framebuffer at all halts on `AOBS-E02`; one in a format the renderer cannot negotiate on `AOBS-E05`; one below the 800×600 floor on `AOBS-E06` — each with §9's diagnostic on a live console, and each with a different third sentence, which is why they are three codes (`06-codes.md` §5). The population that used to fail *silently* — a UEFI machine with no usable KMS driver — now draws through the fbdev tier. |

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

**The kernel console always exists, so there is always a channel** — provided by `efifb` on a machine
with no DRM driver and by the native driver's `fbcon` where there is one. Neither is `simpledrm`, which
this image does not have (§7). Verified against the built ISO: with no DRM device the appliance prints
the block below and halts with it visible on the panel.

Two things keep that true under the two-tier path:

- `ExecStartPost` runs only after a **successful** start, so a startup failure never detaches the
  console — the diagnostic always has somewhere to go. `ExecStopPost` rebinds it for the *app ran, then
  died* case, where systemd restarts the app anyway.
- `panic=0` and `StandardOutput=journal+console` are what put the text on the panel; `/dev/console`
  needs no `TTYPath`, which is why §2 can drop the unit's VT1 coupling without losing this channel.

The app is launched by a wrapper that, on any startup failure, prints a **human-written diagnostic
block** and halts:

- one sentence naming what failed;
- one on what it likely means;
- one on what to do;
- the version and build date;
- a short failure code so a bug report is actionable — from the `AOBS-E##` space in `06-codes.md`,
  which also states why the code is worth printing when the variant name is already there.

Not a stack trace, not systemd's default spew. Halt with the text visible; do not power off.

**The diagnostic prints only fixed strings and typed error-variant names, never formatted program
state** — the same rule that governs logs and `Debug`, extended to the one output path that survives
a crash.

**The serial mirror, stated because an undocumented output channel is worse than a documented one.**
Every line the app writes to the console it also writes to `/dev/ttyS0` when one exists — the readiness
line, the entropy markers, and this diagnostic. It is what the QEMU harness reads
(`05-testing-and-release.md` §6.2), and it is a **mirror, not a second behaviour**: the same bytes, on a
machine that has a serial port, and a silent no-op on one that does not. Three rules bound it, and they
are the whole of the concession:

1. **Fixed strings and typed variant names only** — the §9 rule above, unchanged. No secret material
   ever reaches it, because none reaches the console either.
2. **Nothing is written there that is not also written to the console the user is looking at.** There is
   no serial-only output, so nothing can be reported to a machine that is hidden from the person.
3. **It is not a network and does not become one.** No reading, no protocol, no acknowledgement — the
   file is opened write-only and the failure to open it is ignored.

This is the appliance's only output channel besides the panel and the QR codes it draws, and it is
listed here so that it is a decision rather than a discovery.

## 10. Build requirements that come from the app side

- **`panic = "unwind"` in the release profile, never `abort`.** The zeroization guarantee lives in
  `ZeroizeOnDrop`, and **drop glue does not run on abort**. An aborting crash with a wallet loaded
  would leave key material in RAM until the shutdown wipe. The top level catches, zeroizes, and
  exits into §9. Enforced by a mechanical CI check.
- The version string and build date are displayed by the appliance and appear in the crash
  diagnostic. They make no security claim and therefore cannot make a false one.
