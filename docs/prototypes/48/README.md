# Prototype for #48 — the appliance draws with no GPU driver

A throwaway branch, not a proposed change. [#49](https://github.com/allisson/aobs/issues/49) decides
whether any of this ships.

## What was changed

One feature name in `aobs/Cargo.toml`:

```diff
-features = ["compat-1-2", "std", "backend-linuxkms", "renderer-software"]
+features = ["compat-1-2", "std", "backend-linuxkms-noseat", "renderer-software"]
```

Plus the `Cargo.lock` fallout — **21 lines, all deletions**: `libseat 0.2.4` and `libseat-sys 0.2.0`
leave the dependency graph. Nothing was added.

Plus one instrumentation line in `main.rs`, which emits Slint's real `PlatformError` text before
mapping it to `Failure::DisplayUnavailable`. `01-boot-layer.md` §9 forbids formatted program state in
the diagnostic, which is why [#40](https://github.com/allisson/aobs/issues/40) could observe
`AOBS-E02` without being able to name the cause. Whether a library's own error string counts as
program state is #49's call, so it is instrumentation here and nothing more.

**Nothing else.** No package-list change, no hook change, no cmdline change. `seatd` and `libseat1`
are still installed in this image and the package count is still 180 — the binary simply no longer
asks them for anything.

## How it was run

```sh
docker run --rm --platform linux/amd64 -v "$PWD:/src" -w /src aobs-build ci/build-binary.sh
docker run --rm --privileged --platform linux/amd64 -v "$PWD:/src" -v aobs-work:/build -w /src \
    aobs-build ci/local-inner.sh
ci/qemu-boot.sh bitcoin-signer-amd64.iso 4096 900
```

`ci/qemu-boot.sh` is unmodified: OVMF, `-vga none -device ramfb`, no GPU — the row
`05-testing-and-release.md` §6.2 describes, and the configuration that produced #40's failure.

## What happened

```
AOBS_ENTROPY_WAIT_BEGIN
AOBS_ENTROPY_MS=7461
AOBS_READY version=0.1.0 build=2026-08-15
```

`ok    readiness line: AOBS_READY version=0.1.0 build=2026-08-15`, in 55 s under TCG. No
`AOBS_PROTO_DISPLAY_ERROR` line, so `AppWindow::new()` succeeded rather than being rescued.

`panel-ready.png` is the panel itself, captured through the QEMU monitor: the walking-skeleton screen
at 800×600, drawn with no GPU driver, no `simpledrm` and no DRM device of any kind.

## The failure this prototype found

`panel-after-kernel-message.png` is the same boot after an NMI was injected from the monitor:

```
[   48.642282] Uhhuh. NMI received for unknown reason 21 on CPU 0.
[   48.646972] Dazed and confused, but trying to continue
```

Those two lines are printed **onto the appliance's own screen**, in `fbcon`'s font, over the UI — and
they **persist**, because Slint has no reason to redraw pixels it believes are unchanged. A third
capture after ejecting the CD-ROM shows them still there.

This is exactly what [#46](https://github.com/allisson/aobs/issues/46) predicted from source:
`KD_GRAPHICS` requires `/dev/console`, which is `0600 root:root`, so the unprivileged `signer` user
cannot take the console out of text mode, and `fbcon` keeps writing to the same framebuffer Slint is
rendering into. Predicted, then observed.

It matters more than an NMI does, because the screen it can overwrite is the transaction review
screen — the one mitigation the whole threat model rests on.

## Not established here

- **Whether the DRM path is immune to the same thing.** A `simpledrm` or native-KMS boot might
  suppress `fbcon` while a DRM master holds the device, which would be a real advantage for the
  kernel-side candidates over this one. Plausible, **not verified** — it needs the same probe run
  against a DRM boot, and it is now a question on #49.
- Real hardware. This is QEMU with `ramfb`.
- Any input path: no keyboard was pressed, no camera attached.
- What the image would look like with `seatd` and `libseat1` actually removed.
- Tearing, which cannot show up in a single static screenshot.
