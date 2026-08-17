# Prototype for #51 — a DRM master is immune to the `fbcon` overwrite

[#48](https://github.com/allisson/aobs/issues/48) found that on the fbdev path an injected NMI prints
kernel lines onto the appliance's screen, over the UI, permanently. This asks whether the DRM path
shares that defect. **It does not**, and the kernel does it on purpose.

## What was run

No code change at all. The **unmodified walking-skeleton ISO** — `backend-linuxkms`, `libseat`,
`seatd`, exactly as `main` builds it — with one QEMU argument changed:

```diff
- -vga none -device ramfb
+ -vga none -device virtio-gpu-pci
```

Then #48's probe verbatim: wait for `AOBS_READY`, `screendump`, inject `nmi` from the monitor,
`screendump`, eject the CD-ROM, `screendump`.

`virtio_gpu` is a real KMS driver with dumb buffers and needs no firmware
([#47](https://github.com/allisson/aobs/issues/47)).

## What happened

```
AOBS_ENTROPY_WAIT_BEGIN
AOBS_ENTROPY_MS=6774
AOBS_READY version=0.1.0 build=2026-08-15
```

Ready in 55 s, at 1280×800 — `virtio-gpu`'s mode, against `ramfb`'s 800×600.

**All three captures are byte-identical**, `md5 = 69d814bd4326b284fddfea107720cb62`. The NMI left no
mark on the panel. `panel-after-kernel-message.png` is the capture taken *after* the NMI: a clean
appliance screen.

For contrast, #48's two fbdev captures differ from each other
(`d2a908c1…` → `d61d1ee2…`), which is the kernel text arriving.

**That the appliance drew at all is itself the proof it was on DRM**: this build routes every device
open through `libseat`, and `seatd` answers `ENOENT` for `/dev/fb0`
([#46](https://github.com/allisson/aobs/issues/46)). It cannot have reached the fbdev fallback.

## Why — from source, not from the screenshot

The ticket asked for the mechanism rather than an inference from one image, because a QEMU-only
result nobody can explain will not survive contact with real hardware. There are two, and the second
is the load-bearing one.

**1. The console owns a different framebuffer.** `virtio_gpu` sets up fbdev emulation through
`drm_fbdev_shmem_setup` (`drivers/gpu/drm/virtio/virtgpu_drv.c:106`), and
`drm_fbdev_shmem_helper_fb_probe` allocates its own buffer with `drm_client_framebuffer_create`
(`drivers/gpu/drm/drm_fbdev_shmem.c:126`). `fbcon` writes there and the damage worker flushes it —
into a buffer that is not on the CRTC, because the DRM master put its own there. On the fbdev path
there is only **one** framebuffer, the physical aperture, so Slint and `fbcon` write to the same
memory. The difference is structural, not incidental.

**2. The kernel refuses to take the display from an active master, and says so.** In
`drm_fb_helper_set_par` (`drivers/gpu/drm/drm_fb_helper.c:1339`):

```c
	/*
	 * ... Everything else uses the normal
	 * commit function, which ensures that we never steal the display from
	 * an active drm master.
	 */
	force = var->activate & FB_ACTIVATE_KD_TEXT;

	__drm_fb_helper_restore_fbdev_mode_unlocked(fb_helper, force);
```

Several fbdev entry points are gated the same way, returning `-EBUSY` while a master is held —
`drm_fb_helper_setcmap` (:1021), `drm_fb_helper_ioctl` (:1061), `drm_fb_helper_pan_display` (:1425),
`drm_fb_helper_hotplug_event` (:1974).

**And the console comes back when the master goes away.** `drm_fb_helper_lastclose` →
`drm_fb_helper_restore_fbdev_mode_unlocked` (:2001). So the suppression lasts exactly as long as the
app holds the device — which is the behaviour `01-boot-layer.md` §9 wants, since the diagnostic
console is needed precisely when the app has died.

## What this means for the decision

The DRM candidates buy a property candidate 4 **structurally cannot have**: while the appliance is
running, no kernel message can deface the screen the user is reading a transaction from, and the
console still returns when the appliance dies. That is not a preference — on the fbdev path there is
one framebuffer and no owner.

This is [#49](https://github.com/allisson/aobs/issues/49)'s to weigh against candidate 4 costing one
word and candidates 2 and 3 costing a kernel patch or a distribution.

## Not established here

- **Real hardware.** QEMU + `virtio-gpu`, which the appliance will never ship on.
- **That `simpledrm` behaves like `virtio_gpu` here** — *narrowed to a boot, not a mechanism.*
  `simpledrm` was not the driver under test, and nothing with `simpledrm` has been booted at any
  point on this map. But the mechanism is now source-identical rather than analogous:
  `simpledrm.c:1045` calls **`drm_fbdev_shmem_setup`**, exactly as `virtgpu_drv.c:106` does, so the
  console client allocates its own buffer through the same `drm_client_framebuffer_create` path. That
  `simpledrm` *scans out* the sysfb aperture does not change where `fbcon` writes. Both mechanisms
  therefore apply unchanged; what is missing is an observation, not an argument.
- Whether a kernel **panic** (`oops_in_progress`, which several of these paths check explicitly and
  which bypasses the gate on purpose) reaches the panel. A panic *should* reach the screen; that is
  §9's whole intent. Untested.
