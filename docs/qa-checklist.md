# QA checklist — by hand, because CI cannot

`05-testing-and-release.md` §6.3 names what QEMU cannot answer. This file is the running
list, extended as each slice lands. Nothing here is a substitute for a CI gate; these are
the claims that need a person and a machine.

A tested-hardware list is published with each release, naming exactly what was verified
rather than implying broader support (§6.3).

## Walking skeleton — [#39](https://github.com/allisson/aobs/issues/39)

### Found by building it: `simpledrm` is not in Debian's kernel

**ADR-0009's guaranteed display path does not exist on the distribution we ship.** Debian 13's
`linux-image-6.12.101+deb13-amd64` config carries:

```
# CONFIG_SYSFB_SIMPLEFB is not set
# CONFIG_DRM_SIMPLEDRM is not set
```

There is no `simpledrm.ko` anywhere in the built image, and a UEFI boot of the built ISO logs
`fb0: EFI VGA frame buffer device` — **`efifb` claims the framebuffer**. `efifb` is fbdev, not DRM,
which is exactly the "vesafb-class fbdev … which Slint cannot render to" that ADR-0009 attributes to
legacy BIOS. It applies to UEFI on Debian too.

The consequence inverts the ADR: **the native KMS driver (`i915`, `amdgpu`, `radeon`, `nouveau`) is
the requirement, not the optimisation, and there is no fallback.** A UEFI machine with no supported
GPU gets `AOBS-E02` and no screen.

Observed end to end against the built ISO under OVMF + `ramfb`: the appliance starts, measures
entropy, finds no DRM device, prints the §9 diagnostic and halts with it visible — the failure path
works, on the artifact. What does not work is the assumption underneath it.

**This is a ticket, not something to improvise** — [#40](https://github.com/allisson/aobs/issues/40),
which carries the evidence and the options. Each way out reverses a settled decision.

### The claim the whole slice exists to retire

- [ ] **It boots on at least one real UEFI machine and draws the screen.** ADR-0009 rests
      on reading `drivers/gpu/drm/tiny/simpledrm.c`. Nobody has watched it draw a pixel.
      Record the machine: make, model, year, panel resolution, GPU.
- [ ] The version string and build date on screen match the ISO that was written to the
      stick (01-boot-layer.md §10).

### Boot menu and RAM

- [ ] Both GRUB entries appear, and only those two (§7).
- [ ] The default entry boots with `toram`, and **the USB stick can be pulled once the
      screen is up** without the session dying.
- [ ] The *low memory: keep the USB inserted* entry boots on a machine below the floor and
      degrades rather than bricking.
- [ ] **Measure the RAM floor against the built image.** Provisional at 2 GiB minimum /
      4 GiB recommended; the real number is owed (`00-overview.md`).

### Entropy

- [ ] Read `AOBS_ENTROPY_MS` off the console on real hardware, on at least one low-end
      machine. Derived as 1–16 s under `random.trust_cpu=off`; **derived, not measured**,
      and this is the measurement (§8).
      *First data point, and it does not discharge the obligation:* **11 695 ms** in QEMU
      under TCG with no `virtio-rng`, inside the derived band. A VM with an idle CPU and no
      devices is close to the worst case for timing jitter, so treat this as an upper
      bound to beat, not as the number.
- [ ] `dmesg | grep -E 'crng init done|RDRAND is not reliable'` — the verification §8
      names.

### No shell escape (§2)

- [ ] Ctrl+Alt+F1 … F6 reach no login prompt.
- [ ] Alt+SysRq+B does nothing.
- [ ] The app restarting leaves a blank signer, not a broken screen. There is no way to
      kill it from the appliance itself, which is the point — provoke it from a
      development build. Crash behaviour is a stated product fact, not an incident.

### No network (§3)

- [ ] With an Ethernet cable plugged in at boot, no interface appears and no link is
      brought up. There is nothing on the image to check this with, so check it from the
      switch or the other end of the cable.
- [ ] The published package manifest lists no `firmware-*` package.

### The failure path (§9)

- [ ] Provoke a startup failure (a development build is the practical way) and confirm the
      block appears and the machine **halts with it visible** rather than rebooting or
      powering off. `Restart=always` must not scroll it away.
- [ ] **Open question, worth answering here rather than guessing.** The image carries
      `grub-efi` only, which follows from UEFI-only (ADR-0009) but means a legacy-BIOS
      machine is refused by its own firmware and never reaches our `DisplayUnavailable`
      diagnostic. Boot one and record what the user actually sees. If it is worse than
      ADR-0009's "unexplainable blackness", that is a ticket, not a fix to improvise.
- [ ] The block is a human-written paragraph and a failure code — not a stack trace, and
      **no formatted program state**.
