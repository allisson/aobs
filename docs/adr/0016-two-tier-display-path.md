# ADR-0016 — Two display tiers: DRM where the machine has it, `efifb` where it does not

- **Status**: accepted
- **Date**: 2026-08-17
- **Supersedes**: [ADR-0009](./0009-uefi-only.md)
- **Decides**: [#49 — Decide the display path](https://github.com/allisson/aobs/issues/49), on the
  map [#42](https://github.com/allisson/aobs/issues/42)

## Context

ADR-0009 earned UEFI-only by *deleting* the worst failure in the product — no usable display, which
cannot be reported because reporting it needs the thing that failed. Its mechanism was `simpledrm`
binding the EFI stub's `simple-framebuffer` as a full KMS device, so every UEFI machine would have a
display path with no GPU driver at all.

**That premise was read from upstream kernel source and never checked against Debian's kernel
configuration.** The walking skeleton falsified it
([#40](https://github.com/allisson/aobs/issues/40)): `/boot/config-6.12.101+deb13-amd64` inside the
built ISO sets neither `CONFIG_SYSFB_SIMPLEFB` nor `CONFIG_DRM_SIMPLEDRM`, there is no `simpledrm.ko`
anywhere in the image, and under OVMF with `ramfb` and no GPU the kernel brings up `efifb`, creates no
`/dev/dri` node, and the appliance halts on `AOBS-E02`. `CONFIG_SYSFB` alone registers an
`efi-framebuffer` platform device for `efifb`, not the `simple-framebuffer` device `simpledrm` binds.

ADR-0009 is left otherwise intact. It was a correct decision on the information available, and *how*
it was wrong — a property of upstream source assumed to be a property of the shipped kernel — is the
reason this project's standing rule says to verify the shipped artifact rather than the source.

Five candidates were priced before this decision, four of them by research:

| # | Candidate | Outcome |
|---|---|---|
| 1 | A Debian kernel package that already carries both symbols | **dead** — no suite, no flavour, never `=m` ([#43](https://github.com/allisson/aobs/issues/43)) |
| 2 | A custom kernel with the two options flipped | **deferred to Debian, not rejected** — its MR !1453 sets both for forky ([#43](https://github.com/allisson/aobs/issues/43)) |
| 3 | Switch the base distribution to Alpine | **not taken** — the premise holds ([#44](https://github.com/allisson/aobs/issues/44)) but the bill is 18 controls ported, 16 reworked, 4 lost ([#45](https://github.com/allisson/aobs/issues/45)) |
| 4 | Render without DRM, through Slint's fbdev display | **chosen** ([#46](https://github.com/allisson/aobs/issues/46)) |
| 5 | Accept native-KMS-only and publish a hardware list — the null option | **dead** — the module deletion below empties its exclusion list ([#47](https://github.com/allisson/aobs/issues/47)) |

## Decision

**The display path has two tiers, chosen at runtime, per machine: a DRM dumb buffer where a DRM
device exists, and `/dev/fb0` where none does.**

They are tiers rather than alternatives because Slint already chains them, in
[`display/swdisplay.rs` @ `v1.17.1`](https://github.com/slint-ui/slint/blob/v1.17.1/internal/backends/linuxkms/display/swdisplay.rs):

```rust
dumbbuffer::DumbBufferDisplay::new(device_opener, renderer_formats)
    .or_else(|_| linuxfb::LinuxFBDisplay::new(device_opener, renderer_formats))
```

So no machine loses anything it has today, and the fallback reaches exactly the machines that
currently get blackness. Four parts make this a guaranteed display path again:

1. **`backend-linuxkms-noseat`, not `backend-linuxkms`.** `libseat` — not the absence of
   `simpledrm` — is what stopped `/dev/fb0` from being opened at all: under the `seatd` backend the
   open is delegated to a seat daemon that hands back only DRM and evdev nodes. With `-noseat` it is
   a plain `open(2)`, and `signer` in `video` + `input` covers `/dev/fb0`, `/dev/dri/card0`,
   `/dev/input/event*` and `/dev/video0` by systemd's own udev rules. `seatd` and `libseat1` leave
   the image.
2. **`amdgpu`, `xe` and `radeon` are deleted from the module tree and the initramfs.** The image
   installs no `firmware-*` package, so none of the three can ever initialise here — and each calls
   `drm_aperture_remove_conflicting_pci_framebuffers()` *before* failing on the absent blob, with no
   way to put the aperture back. Kept, they would destroy a working `efifb` on their way out.
3. **`fbcon` is detached while the app draws**, and reattached when it stops, reproducing on the
   fbdev tier the protection the DRM tier gets from the kernel for free.
4. **UEFI amd64 only still**, but for a different reason — see *The hardware floor* below.

The compatibility statement stops being a hardware list and becomes a floor: **UEFI amd64, any
machine whose firmware hands over a framebuffer.** The empirical claim lives in the per-release
tested-hardware list (`05-testing-and-release.md` §6.3), not here.

> **Qualifier added by [#55](https://github.com/allisson/aobs/issues/55), not a change to this
> decision:** *…a framebuffer **of at least 800×600***. This ADR widened the population of panel
> geometries — the fbdev tier draws at whatever mode the firmware handed over — and the layout policy
> that followed (`04-screens.md` §0) set a minimum canvas. Below it, the startup diagnostic reports
> rather than the UI drawing. The display-path choice itself is untouched.

### Why not the candidates that would have restored `simpledrm` itself

**Candidate 3 is dominated by candidate 2**: Alpine buys exactly the property a custom Debian kernel
buys, for a much larger bill. **Candidate 2 is dominated by time**: when forky absorbs MR !1453,
`simpledrm` appears, `DumbBufferDisplay` wins the chain unaided, and the fbdev tier shrinks **with no
code change on our side**. Choosing 4 buys the DRM path for free later; choosing 2 or 3 pays for it
now, in a kernel we then own forever — every CVE a rebuild — and in the loss of Debian's signed
kernel.

### The hardware floor: UEFI-only stands, on a weaker but honest reason

`vesafb` is a framebuffer too, so ADR-0009's exclusion of pre-2012 machines is **no longer
necessary**. It is kept anyway, and the difference matters: legacy BIOS would mean a second GRUB
configuration and a second CI matrix, and `vesafb`'s reported pixel format has never been checked
against the five format arms `LinuxFBDisplay` accepts.

**UEFI-only now stands on build-and-test surface, not on "no display path exists".** That is a
smaller claim than ADR-0009's, and stating the smaller one is the point.

## Consequences

### What the worst failure looks like now

- **Deleted:** the entire firmware-hungry class, which was the whole known population of unreportable
  blackness. Reading [#47](https://github.com/allisson/aobs/issues/47) §7–§8, its *"not satisfied
  by"* list empties: every AMD graphics device in eighteen years, Radeon HD 2000+, Intel Lunar Lake
  and Battlemage, and RTX 40/50 all **draw** — the first two by no longer being sabotaged, the others
  by `efifb` surviving. `CONFIG_FB_EFI=y` in Debian, so `efifb` cannot be pruned away by module
  deletion.
- **Handled:** a machine whose EFI framebuffer format falls outside `LinuxFBDisplay`'s five accepted
  arms reaches `AOBS-E02` on a live console — a reported failure, not blackness.
- **Accepted, and named:** a driver we *keep* — `i915`, `nouveau`, `ast`, `mgag200`, `gma500`, `udl`,
  `hyperv` — that removes the aperture and then fails for a reason unrelated to firmware. #47 traced
  the firmware failures only; **this class is unquantified**, no cheap control covers it, and
  `gma500`'s legacy-modeset caveat is its most likely instance. It is stated rather than implied
  away.

### The `fbcon` overwrite, mitigated

On the fbdev tier the kernel console and the app share one framebuffer with no arbitration, so
console text lands on the panel and stays — Slint does not repaint it away. No `loglevel` value fixes
this: the NMI lines observed in [#48](https://github.com/allisson/aobs/issues/48) are `pr_emerg`, and
suppressing EMERG would suppress the panic text §9 depends on. What `quiet loglevel=3` does buy is
real — everything below CRIT is gone, so the defacement class is *"the machine is already in serious
trouble"*.

The control is to detach `fbcon` for exactly the interval the app is drawing, by `ExecStartPost=+`
and `ExecStopPost=+` on the unit, so the app itself never gains a privilege.
[#52](https://github.com/allisson/aobs/issues/52) verified it: two NMI injections left the panel
**byte-identical** with the console detached, on a boot whose control shows the same injection
printing to the panel four seconds earlier, and the unbind does not clear the framebuffer. Hence
*mitigated*, not *accepted*. It was verified under QEMU + `ramfb` only; real hardware is an owed
verification.

Two properties of the unit follow from that probe and are not implementation detail:

- **The unit cannot be coupled to VT1.** `TTYVTDisallocate=yes` — which ADR-0009's spec text lists
  among the four no-shell-escape controls — kills the appliance the moment `fbcon` unbinds. It is
  dropped, along with `TTYPath`, `StandardInput=tty`, `TTYReset` and `TTYVHangup`. Nothing is lost:
  the app reads no stdin, `StandardOutput=journal+console` keeps §9's channel, and `NAutoVTs=0` /
  `ReserveVT=0` already leave no getty to allocate a VT.
- **Nothing may be written to the console after the first frame.** Two of our own lines, printed in
  the ~120 ms between the first paint and the unbind completing, persisted on the panel.

### Tearing: accepted, scoped to the fallback tier

No page flip and no vsync on the fbdev tier, by construction in both Slint (a `NoopPresenter`) and
`efifb`. It lands only on moving content — the camera preview — and QR decode runs on the V4L2 frame
rather than the presented buffer, so it costs appearance and not correctness. The review screen is
static.

### Everything else this moves

- `01-boot-layer.md` §2 (`-noseat`, the unit, the shell-escape controls), §3 (three more modules
  deleted), §7 (this ADR's floor), §9 (the console's real provider).
- `05-testing-and-release.md` §6.1 and §6.2: the readiness line carries the tier —
  `AOBS_READY version=… build=… display=fbdev|drm` — because otherwise neither display row can fail
  honestly.
- ADR-0002's `backend-linuxkms` becomes `backend-linuxkms-noseat`; its *22 packages / 21 MiB* goes
  stale with `seatd` and `libseat1` removed, and becomes an owed measurement rather than a guess.
- §2's build hook that read the seat group out of `seatd.service` is deleted; with no `seatd` there
  is nothing left for it to guard.

## Alternatives rejected

- **A custom kernel with `CONFIG_DRM_SIMPLEDRM` + `CONFIG_SYSFB_SIMPLEFB`** — deferred to Debian's
  own MR !1453 rather than rejected. Taking it now buys a permanent maintenance obligation for a
  property that arrives free.
- **Alpine as the base distribution** — dominated by the above.
- **Native-KMS-only, with a published hardware list** (the null option) — the module deletion leaves
  it nothing to exclude, so it is strictly worse than candidate 4 for the same effort.
- **Bringing legacy BIOS back.** `vesafb` makes the pre-2012 exclusion unnecessary but not unwanted;
  a second boot path and CI matrix is a cost with no product reason behind it.
- **`xe.force_execlist`** — an escape hatch that would buy native KMS for Lunar Lake, which already
  draws once `xe` is deleted. #47 flags it unverified; it is a lead not taken.
- **Suppressing the NMI text with `loglevel`** — impossible without suppressing the panic text that
  is §9's whole channel.
