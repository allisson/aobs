# ADR-0009 — UEFI only, because `simpledrm` deletes the unreportable failure

- **Status**: **superseded by [ADR-0016](./0016-two-tier-display-path.md)**
- **Date**: 2026-08-15
- **Decides**: [#24 — Hardware compatibility floor, and what happens when hardware is unsupported](https://github.com/allisson/aobs/issues/24)

> **Superseded, and left otherwise intact.** Its central mechanism is false on the distribution this
> spec ships: Debian 13 sets neither `CONFIG_DRM_SIMPLEDRM` nor `CONFIG_SYSFB_SIMPLEFB`, so
> `simpledrm` never binds and there is no guaranteed display path with no GPU driver
> ([#40](https://github.com/allisson/aobs/issues/40)). The premise was read from upstream kernel
> source and never checked against the shipped kernel — which is why the standing rule says to verify
> the artifact. [ADR-0016](./0016-two-tier-display-path.md) states the mechanism that actually exists
> and keeps UEFI-only on a different, weaker reason. Everything below is the record of the original
> decision; do not build on it.
>
> Still current, and unaffected by the falsification: `toram` and its low-memory second GRUB entry,
> the RAM floor, the camera and keyboard degradation behaviour, `random.trust_cpu=off`, and
> `panic = "unwind"`.

## Context

The worst failure available to this appliance is *no usable display*, because reporting it requires
the thing that failed. Slint's `backend-linuxkms` + `renderer-software` needs a KMS/DRM device with
dumb buffers; without one the user sees the GRUB menu and then unexplainable blackness, with no
channel left to explain it.

On UEFI, the EFI stub hands the kernel a `simple-framebuffer` and **`simpledrm` binds it as a full
KMS device with dumb buffer support** — verified in `drivers/gpu/drm/tiny/simpledrm.c`, which
declares `DRM_GEM_SHMEM_DRIVER_OPS` (supplying `dumb_create`) with
`DRIVER_ATOMIC | DRIVER_GEM | DRIVER_MODESET`. That is exactly what the renderer requires.

On legacy BIOS there is no equivalent: a native KMS driver gives DRM, and its absence gives
`vesafb`-class fbdev, which is not DRM.

## Decision

**UEFI amd64 only. `toram` by default. 2 GiB minimum / 4 GiB recommended, provisional until confirmed
against the built image.**

On any UEFI machine there is a **guaranteed display path with no GPU driver at all**, so `i915`,
`amdgpu` and `nouveau` become an optimisation rather than a requirement.

No CPU feature is required: `random.trust_cpu=off` (ADR-0008) already made RDRAND/RDSEED a
performance question rather than a correctness one.

## Consequences

- **Named cost, accepted: machines older than roughly 2012 are excluded.** This is real, since
  repurposed old laptops are exactly this product's natural hardware. Taken anyway, because it
  converts the worst failure in the product from *possible and unreportable* to **structurally
  impossible**, and halves the boot paths to build and test.
- **The kernel console always exists**, which is what makes a human-written diagnostic block a viable
  last channel. The cmdline carries `quiet loglevel=3` so boot messages do not compete for the panel,
  and **`panic=0`** so a kernel panic halts with the message visible rather than rebooting it away.
- **`toram` by default**, for two product reasons rather than performance: the user can pull the
  stick once booted, and yanking it cannot kill a session mid-signature. **A second GRUB entry —
  *"low memory: keep the USB inserted"* — converts insufficient RAM from a brick into a degraded
  boot.**
- **No camera is degraded but useful** (create, identity, watch-only QR, backup QR; loses signing and
  address verification), with those actions **visibly unavailable and their reason stated**. **No
  keyboard is fatal but reportable**, because the GUI is up to say it on, and it keeps polling so
  hot-plug recovers. V4L2 is enumerated at the point of use, so plugging a camera in later just
  works.
- **No getty, no login prompt, no shell on any tty.**
- **A zeroization finding this surfaced, now a build requirement: `panic = "unwind"`, never
  `abort`.** The zeroization guarantee lives in `ZeroizeOnDrop`, and **drop glue does not run on
  abort** — an aborting crash with a wallet loaded would leave key material in RAM until the shutdown
  wipe. Enforced by a mechanical CI check.
- The unpredictable-panel population this creates is one of the arguments that later chose the light
  colour scheme (ADR-0011).
- **CI gains QEMU rows**, including OVMF with `ramfb` and no GPU, which exercises `simpledrm`
  specifically — the fallback the entire display story leans on.
- The ticket's *"measure before this closes"* was **declined as a precondition**: there is no ISO and
  the map forbids building one, so making the measurement a gate would block the map on an artifact
  it prohibits. It became a named release-gate obligation instead.

## Alternatives rejected

- **Support legacy BIOS** — keeps pre-2012 machines but reintroduces a failure mode that cannot be
  reported to the user at all.
- **Require a native KMS driver** — no better on old hardware and worse on new, since it makes the
  guaranteed path conditional on driver coverage.
- **Support MC-centric (IPU6/MIPI) cameras** — needs media-controller pipeline configuration,
  proprietary firmware and libcamera. USB UVC only, probed by capability, stated clearly rather than
  failing obscurely.
