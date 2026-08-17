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

- [ ] **It boots on at least one real UEFI machine and draws the screen.** The claim moved
      with ADR-0016: the fbdev tier — `efifb`, not `simpledrm` — is what serves a machine
      with no native KMS driver, and it has only ever been watched under QEMU + `ramfb`.
      Record the machine: make, model, year, **panel resolution**, GPU, and which tier won
      (the readiness line says `display=fbdev` or `display=drm`).
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
      `grub-efi` only, so a legacy-BIOS machine is refused by its own firmware and never
      reaches any diagnostic of ours. UEFI-only now stands on build-and-test surface rather
      than on "no display path exists" (ADR-0016), which makes this a *product* question
      rather than a technical one. Boot one and record what the user actually sees; if it is
      worse than blackness with no explanation, that is a ticket, not a fix to improvise.
- [ ] The code printed matches `docs/specs/06-codes.md` — `AOBS-E02` for no framebuffer at
      all, `AOBS-E05` for a format outside the renderer's five arms, `AOBS-E06` for a mode
      below 800×600, and `AOBS-E00` only when the wrapper prints it because the binary never
      spoke.
- [ ] The block is a human-written paragraph and a failure code — not a stack trace, and
      **no formatted program state**.

## Reconciled against ADR-0016 and the panel map — [#57](https://github.com/allisson/aobs/issues/57)

Rows that only exist because `image/` was brought back in line with `docs/specs/`. Each one
guards a claim the tree used to contradict.

### The RAM wipe rests on an absence (§5, [#62](https://github.com/allisson/aobs/issues/62))

§5 claims `init_on_free=1` and nothing else, because nothing secret is written to a
filesystem. That is a checkable claim and these rows are the check — a development build is
the practical way to run them, since the shipped image offers no shell.

- [ ] After a **full session** — create a wallet, load it with a passphrase, sign a
      transaction, reach the shutdown screen — the overlayfs upper dir holds **nothing the
      app wrote**. List it and read the list; do not sample it.
- [ ] Nothing in `/run/log/journal` carries secret material: no mnemonic, no passphrase, no
      key, no backup password, no PSBT contents.
- [ ] No file anywhere on the writable layer is owned by `signer` other than an empty home.
- [ ] `swapon --show` is empty and `/proc/swaps` lists nothing (§4, and the wipe assumes it).

### No seat daemon (§2, ADR-0016)

- [ ] `ps` shows no `seatd`, and the published package manifest lists neither `seatd` nor
      `libseat1`. If either is back, the image and the crate's `backend-linuxkms-noseat`
      have drifted apart and the fbdev tier is dead again.
- [ ] On a machine with **no** DRM device, the readiness line says `display=fbdev`. That is
      the whole point of `-noseat`: under the seatd backend the `/dev/fb0` open was
      delegated to a daemon that hands back DRM and evdev nodes only.

### The serial mirror (§2, §9)

- [ ] On a machine **with** a serial port, capture everything that reaches it across a full
      session — boot, wallet load, a signature, shutdown — and confirm it is **only** the
      lines that were also on the panel. Anything serial-only is a channel nobody decided on.
- [ ] No secret material appears there: no mnemonic, no passphrase, no key, no backup
      password, and no PSBT contents.
- [ ] On a machine with **no** serial port, nothing changes and nothing fails — the open is
      allowed to fail silently.

### The console detach (§2, §7, [#52](https://github.com/allisson/aobs/issues/52))

- [ ] On the fbdev tier, provoke kernel output while the app is drawing (an NMI, or a
      `pr_emerg` from a development build) and confirm **the panel is unchanged**.
- [ ] Nothing from `console-detach` or `console-attach` ever appears on the panel. They log
      to the journal; anything written to the unit's stdout after the first frame *stays*
      on screen, because Slint does not repaint it away.
- [ ] Stop the service and confirm the console comes back — that is the channel §9 needs
      exactly when the GUI is gone.
- [ ] `TTYVTDisallocate=yes` is **not** in the unit. #52 watched the service die five times
      behind a black panel with it present. Do not add it back without re-running that probe.

### The keymap ([#54](https://github.com/allisson/aobs/issues/54))

- [ ] On a **non-US** physical keyboard, every printable ASCII character can still be typed
      into the passphrase field — the legends lie, nothing is unreachable, and that
      reachability is the entire argument for offering no layout picker.
- [ ] The passphrase and seed-import screens **name the layout** before the user starts.
- [ ] Dead keys do nothing anywhere: `XKB_DEFAULT_VARIANT` and `XKB_DEFAULT_OPTIONS` are
      unset, not set to an empty string.

### Panel modes ([#55](https://github.com/allisson/aobs/issues/55))

- [ ] On a panel larger than the design size, type is **larger**, not the layout roomier —
      1920×1080 and 3840×2160 should both look like a 1422×800 canvas scaled up.
- [ ] At 800×600 the review panel draws **stacked**, non-scrolling, with a 62-character P2TR
      address complete on screen.
- [ ] A mode below 800×600 halts on `AOBS-E06` with the diagnostic on a live console, rather
      than drawing something cramped.

### The output bound ([#58](https://github.com/allisson/aobs/issues/58))

- [ ] Six outputs fit the review panel at 800×600 with nothing clipped and no scroll region.
      **This is the measurement the bound rests on** — if it comes back tighter, the number
      drops before the first ISO ships, and never after.
- [ ] A seven-output PSBT is refused with `AOBS-R15` before any review screen is drawn.
