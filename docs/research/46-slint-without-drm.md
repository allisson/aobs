# Can Slint render without DRM, straight to `/dev/fb0`?

Research findings for [aobs#46](https://github.com/allisson/aobs/issues/46). Map:
[aobs#42](https://github.com/allisson/aobs/issues/42).

Pinned at Slint tag **`v1.17.1`** (commit `cf62c97`, released 2026-07-07 — the highest release, and
the line `aobs/Cargo.toml` already asks for). Kernel claims are read at tag **`v6.12`**, the line
`01-boot-layer.md` targets. Every claim below is read from source at those tags, not from docs prose,
except where the source *is* documentation and is cited as such.

---

## Answer

**Yes — and the candidate is not "a custom `Platform` + `SoftwareRenderer`". Slint's own
`backend-linuxkms` already contains a complete `/dev/fb0` renderer, has since 1.7.0, and falls back
to it automatically when DRM dumb buffers are unavailable.** `internal/backends/linuxkms/display/
swdisplay/linuxfb.rs` opens `/dev/fb0`…`/dev/fb9`, reads `FBIOGET_VSCREENINFO` and
`FBIOGET_FSCREENINFO`, negotiates a pixel format, `mmap`s the aperture, renders into a packed cached
back buffer and copies rows into the framebuffer honouring `line_length`. No DRM device is opened on
that path. No custom `Platform` is needed, no fork, no upstream patch.

**The reason the built ISO nevertheless printed `AOBS-E02` is `libseat`.** With the `libseat`
feature — which is exactly what the `slint` feature `backend-linuxkms` selects — every device open
goes through `libseat::Seat::open_device`, and `seatd` refuses any path that is not evdev, DRM,
wscons or hidraw:

```c
} else {
        log_errorf("%s is not a supported device type ", sanitized_path);
        errno = ENOENT;
        return NULL;
}
```

`/dev/fb0` is none of those. The fallback ran and could not open the file.

**The change is one feature name.** `backend-linuxkms` → `backend-linuxkms-noseat`, which compiles
the same backend with `device_accessor` as a plain `OpenOptions::open`. `libseat1` and `seatd` leave
the image; the `signer` user's `video` and `input` groups are sufficient and no third group is
needed. See [§8](#8-what-this-means-for-the-spec).

**The cost that is real and must be stated:** there is no page flip and no vsync on this path — by
construction in Slint (a `NoopPresenter`) and by construction in `efifb` (no `fb_pan_display`,
`ypanstep = 0`, `yres_virtual = yres`). Tearing is possible and unmitigable. See
[§5](#5-vsync-and-tearing-there-is-no-mechanism-at-all).

---

## 1. Is the `Platform` / `SoftwareRenderer` API gated behind `no_std` or MCU flags?

**No. Both are ordinary public API on a `std` Linux target.** This bullet is answered for the record;
[§2](#2-the-path-that-already-exists) is why it does not need to be used.

- `slint::platform` is declared unconditionally — no `cfg` on the module at all
  ([`api/rs/slint/lib.rs:422`](https://github.com/slint-ui/slint/blob/v1.17.1/api/rs/slint/lib.rs#L422)),
  re-exporting `i_slint_core::platform::*`, which is where `Platform`, `WindowAdapter` and
  `set_platform` live.
- `slint::platform::software_renderer` carries exactly one gate, `#[cfg(feature =
  "renderer-software")]`
  ([`api/rs/slint/lib.rs`](https://github.com/slint-ui/slint/blob/v1.17.1/api/rs/slint/lib.rs#L414-L456)).
  Nothing about `no_std`, nothing MCU-specific. `renderer-software` is in Slint's *default* feature
  set ([docs.rs features, 1.17.1](https://docs.rs/crate/slint/1.17.1/features)).
- Minimum version for the pieces this ticket asks about: `Platform` + `SoftwareRenderer` have been
  public API since the 1.0 line; **the version that matters here is 1.13.0**, for the reason in
  [§4](#4-stride-is-handled-and-only-since-1130).
- Prior art that it works off-MCU: `examples/uefi-demo` is a custom `Platform` +
  `MinimalSoftwareWindow` + a hand-written `TargetPixel` (`SlintBltPixel`) drawing into a UEFI GOP
  framebuffer
  ([`examples/uefi-demo/main.rs:173,218,236,415`](https://github.com/slint-ui/slint/blob/v1.17.1/examples/uefi-demo/main.rs#L173)).
  A linear framebuffer with a stride is exactly the fbdev case.

## 2. The path that already exists

`SoftwareRendererAdapter::new` asks `display::swdisplay::new` for a `SoftwareBufferDisplay`, and that
function is a two-line fallback chain
([`display/swdisplay.rs`](https://github.com/slint-ui/slint/blob/v1.17.1/internal/backends/linuxkms/display/swdisplay.rs)):

```rust
if std::env::var_os("SLINT_BACKEND_LINUXFB").is_some() {
    return linuxfb::LinuxFBDisplay::new(device_opener, renderer_formats);
}
dumbbuffer::DumbBufferDisplay::new(device_opener, renderer_formats)
    .or_else(|_| linuxfb::LinuxFBDisplay::new(device_opener, renderer_formats))
```

The DRM attempt fails cleanly rather than fatally when there is no DRM node: `DrmOutput::new` wraps
`read_dir("/dev/dri/")` in `if let Ok(...)` and returns `Err` when the directory is absent or yields
nothing
([`drmoutput.rs:49-61`](https://github.com/slint-ui/slint/blob/v1.17.1/internal/backends/linuxkms/drmoutput.rs#L49)).
So on an `efifb`-only machine the chain reaches `LinuxFBDisplay` on its own.

`LinuxFBDisplay::new` probes `/dev/fb0` through `/dev/fb9` and concatenates the per-device errors
into one message
([`linuxfb.rs`](https://github.com/slint-ui/slint/blob/v1.17.1/internal/backends/linuxkms/display/swdisplay/linuxfb.rs)).
Note for whoever debugs this next: **`aobs/src/main.rs` throws that message away** —
`AppWindow::new().map_err(|_| Failure::DisplayUnavailable)` discards Slint's text, which is why
[#40](https://github.com/allisson/aobs/issues/40) recorded `AOBS-E02` and not the reason. The
mechanism in [§3](#3-why-the-built-iso-still-failed-libseat-refuses-devfb0) is read from source, not
from that boot log.

**Upstream provenance, so "would we be first?" is answered: no, and not by a small margin.**

| Version | Date | Entry |
| --- | --- | --- |
| **1.7.0** | 2024-07-18 | "LinuxKMS backend: Added support for software rendering and legacy framebuffers." |
| **1.13.0** | 2025-09-03 | "LinuxKMS: Added support for a padded legacy linux framebuffers." |
| **1.13.0** | 2025-09-03 | "LinuxKMS: Added support for overriding the default framebuffer interface selection" (`SLINT_BACKEND_LINUXFB`) |

([`CHANGELOG.md`](https://github.com/slint-ui/slint/blob/v1.17.1/CHANGELOG.md), lines 1085 and
460-461.) It is also documented for users, in the *Legacy LinuxFB Interface* section of the
[LinuxKMS backend page](https://docs.slint.dev/latest/docs/slint/guide/backends-and-renderers/backend_linuxkms/):

> For software rendering, DRM dumb buffers are the preferred default way of posting frame buffers to
> the display. If DRM dumb buffers are not supported, the LinuxKMS backend falls back to using the
> Linux legacy framebuffer interface (`/dev/fbX`). To override this default and use only the legacy
> framebuffer interface, set the `SLINT_BACKEND_LINUXFB=1` environment variable.

And it is in third-party use: [slint-ui/slint#9862](https://github.com/slint-ui/slint/issues/9862)
(2025-10-27) is a user running `features = ["backend-linuxkms-noseat", "renderer-software",
"compat-1-2"]` against `/dev/fb0` on a `riscv64-musl` LicheeRV Nano, reporting a format their panel
needed. `Bgra8888` was added in response and is in 1.17.1's list. That is the shape of the risk here:
not "does it work", but "does it know your framebuffer's format" — see
[§4](#4-stride-is-handled-and-only-since-1130).

**One doc sentence on that page is stale and should not be trusted:** *"All renderers use Linux's
direct rendering manager (DRM) subsystem to configure display outputs."* `LinuxFBDisplay` opens no
DRM device and sets no mode; it inherits whatever mode the firmware left. The source is the
authority, not that sentence.

## 3. Why the built ISO still failed: `libseat` refuses `/dev/fb0`

Two `device_accessor` closures exist in `calloop_backend.rs`, selected by the `libseat` cargo feature
([`calloop_backend.rs:155-192`](https://github.com/slint-ui/slint/blob/v1.17.1/internal/backends/linuxkms/calloop_backend.rs#L155)):

```rust
#[cfg(feature = "libseat")]
let device_accessor = |device: &std::path::Path| { self.seat.borrow_mut().open_device(&device) … };

#[cfg(not(feature = "libseat"))]
let device_accessor = |device: &std::path::Path| {
    OpenOptions::new()
        .custom_flags((nix::fcntl::OFlag::O_NOCTTY | nix::fcntl::OFlag::O_CLOEXEC).bits())
        .read(true).write(true).open(device) …
};
```

`LinuxFBDisplay::new` calls that closure for `/dev/fb0`. Under `libseat` the request reaches
`seatd`'s `seat_open_device()`, which classifies the path and rejects anything it does not recognise
([`seatd/seat.c:329-358`](https://git.sr.ht/~kennylevinsen/seatd/tree/master/item/seatd/seat.c)):
`path_is_evdev`, `path_is_drm`, `path_is_wscons`, `path_is_hidraw`, else `errno = ENOENT`. And
`path_is_drm` is a literal prefix test for `/dev/dri/`
([`common/drm.c:25-29`](https://git.sr.ht/~kennylevinsen/seatd/tree/master/item/common/drm.c)).
There is no fbdev device type in `seatd` at all.

**So the fbdev fallback is structurally unreachable under `backend-linuxkms`, and reachable under
`backend-linuxkms-noseat`.** The feature mapping, so this is not folklore:

| `slint` feature | selects | effect |
| --- | --- | --- |
| `backend-linuxkms` | `i-slint-backend-linuxkms/libseat` | seat-mediated opens; `/dev/fb0` → `ENOENT` |
| `backend-linuxkms-noseat` | `i-slint-backend-linuxkms` (no `libseat`) | plain `open(2)`; `/dev/fb0` works with `video` |

([`internal/backends/selector/Cargo.toml:23-24`](https://github.com/slint-ui/slint/blob/v1.17.1/internal/backends/selector/Cargo.toml#L23),
[`api/rs/slint/Cargo.toml:211,215`](https://github.com/slint-ui/slint/blob/v1.17.1/api/rs/slint/Cargo.toml#L211).)
`libseat = ["dep:libseat"]` is optional and `default = []` in the backend crate
([`internal/backends/linuxkms/Cargo.toml`](https://github.com/slint-ui/slint/blob/v1.17.1/internal/backends/linuxkms/Cargo.toml)),
so nothing else drags it in.

Slint's own note on `-noseat` overstates the price, and the overstatement is worth naming because it
would otherwise read as a blocker:

> This variant … eliminates the need to have libseat installed, but in exchange **requires running
> the application as a user that's privileged to access all input and DRM/KMS device files; typically
> that's the root user.**
> — [LinuxKMS backend page](https://docs.slint.dev/latest/docs/slint/guide/backends-and-renderers/backend_linuxkms/)

That is a statement about *file permissions*, and group membership satisfies it. From systemd 257's
[`rules.d/50-udev-default.rules.in`](https://github.com/systemd/systemd/blob/v257/rules.d/50-udev-default.rules.in):

```
SUBSYSTEM=="input",  GROUP="input"
SUBSYSTEM=="graphics", GROUP="video"
SUBSYSTEM=="drm", KERNEL!="renderD*", GROUP="video"
SUBSYSTEM=="video4linux", GROUP="video"
```

`/dev/fb0` is `SUBSYSTEM=="graphics"` → `root:video`; `/dev/dri/card0` → `root:video`;
`/dev/input/event*` → `root:input`; `/dev/video0` → `root:video`. **`signer` in `video` + `input`
covers every device this appliance touches, on both display paths and the camera.** No root, and no
third group — `01-boot-layer.md` §2's "whatever group `seatd.service` names" problem disappears with
`seatd`.

The linuxkms backend contains no `drmSetMaster` call
(`grep -rn "set_master\|acquire_master\|drop_master" internal/backends/linuxkms/` → no hits at
v1.17.1), so on a machine that *does* have a GPU the DRM path still relies on implicit master-on-
first-open rather than on a capability. That is unchanged by this switch.

## 4. Buffer format, stride, and partial redraw

### What the renderer requires

`TargetPixel` is a plain public trait, `Sized + Copy`, **not sealed**
([`internal/renderers/software/draw_functions.rs:839`](https://github.com/slint-ui/slint/blob/v1.17.1/internal/renderers/software/draw_functions.rs#L839)),
with three built-in implementations: `Rgb8Pixel` (24 bpp packed, `:861`), `PremultipliedRgbaColor`
(`:874`) and `Rgb565Pixel` (`:923`). Backends and applications add their own — `linuxkms`'s own
`renderer/sw.rs` defines `DumbBufferPixelXrgb888` and `DumbBufferPixelBgra8888`, and `uefi-demo`
defines `SlintBltPixel`. So no format is out of reach in principle.

The entry point is
([`software/lib.rs:532`](https://github.com/slint-ui/slint/blob/v1.17.1/internal/renderers/software/lib.rs#L532)):

```rust
pub fn render(&self, buffer: &mut [impl TargetPixel], pixel_stride: usize) -> PhysicalRegion
```

with the doc comment: *"The pixel_stride is the size (in pixels) between two lines in the buffer …
its size must be at least `pixel_stride * height`"*. **Stride is a first-class parameter, in pixels,
not bytes.**

What the *linuxkms software renderer* offers for negotiation is a fixed list
([`renderer/sw.rs:22`](https://github.com/slint-ui/slint/blob/v1.17.1/internal/backends/linuxkms/renderer/sw.rs#L22)):
`Xrgb8888`, `Argb8888`, `Bgra8888`, `Rgb565`. `Rgba8888` and `Bgr565` are present but commented out.
`negotiate_format` walks the *renderer's* list and takes the first one the display also offers.

### What `LinuxFBDisplay` accepts

From `FBIOGET_VSCREENINFO`, `bits_per_pixel` must be 32 or 16, and the `(red.offset, green.offset,
blue.offset)` triple must match one of five `match` arms — three at 32 bpp, two at 16 — with
`transp.length`/`transp.offset` splitting X-vs-A to give seven fourccs in total:

| bpp | r/g/b offsets | `transp` | fourcc chosen |
| --- | --- | --- | --- |
| 32 | 16 / 8 / 0 | len > 0, off 24 | `Argb8888` |
| 32 | 16 / 8 / 0 | otherwise | `Xrgb8888` |
| 32 | 0 / 8 / 16 | len > 0, off 24 | `Bgra8888` |
| 32 | 0 / 8 / 16 | otherwise | `Bgrx8888` |
| 32 | 24 / 16 / 8, alpha at 0 | len > 0 | `Rgba8888` |
| 16 | 11(5) / 5(6) / 0(5) | — | `Rgb565` |
| 16 | 0(5) / 5(6) / 11(5) | — | `Bgr565` |

Anything else is `"Unsupported framebuffer format: …"`. Note that three of the seven are a dead end:
`Bgrx8888` is absent from the renderer's list entirely, and `Rgba8888` and `Bgr565` are present but
commented out — a framebuffer reporting any of them is detected and then negotiates to nothing. None
of the three is what `efifb` produces.

### Does `efifb` under OVMF satisfy it? Yes, and here are the numbers

`efifb` fills `fb_var_screeninfo` straight out of `screen_info`, which the EFI stub fills from the
GOP mode
([`drivers/firmware/efi/libstub/gop.c:446-461`](https://github.com/torvalds/linux/blob/v6.12/drivers/firmware/efi/libstub/gop.c#L446)).
For `PIXEL_BGR_RESERVED_8BIT_PER_COLOR`:

```c
si->blue_pos  = 0;
si->red_pos   = 16;
si->green_pos = 8;
si->rsvd_pos  = 24;
si->red_size = si->green_size = si->blue_size = si->rsvd_size = 8;
si->lfb_depth = 32;
si->lfb_linelength = pixels_per_scan_line * 4;
```

and `efifb` copies those through verbatim
([`drivers/video/fbdev/efifb.c:520-527`](https://github.com/torvalds/linux/blob/v6.12/drivers/video/fbdev/efifb.c#L520)),
with the identical layout as its own fallback when the firmware left the fields zero (`:398-408`).
So `FBIOGET_VSCREENINFO` reports **`bits_per_pixel = 32`, `red.offset = 16`, `green.offset = 8`,
`blue.offset = 0`, `transp.offset = 24`, `transp.length = 8`** — which is row 1 of the table above,
`Argb8888`, and `Argb8888` is second in the renderer's preference list. It negotiates.
`FBIOGET_FSCREENINFO` reports `type = FB_TYPE_PACKED_PIXELS`, `visual = FB_VISUAL_TRUECOLOR`
(`efifb.c:66-71`) and `line_length = si->lfb_linelength`.

OVMF is where that pixel format comes from, and for the CI configuration
`05-testing-and-release.md` §6.2 uses it is nailed down: `QemuRamfbDxe` sets
`PixelFormat = PixelBlueGreenRedReserved8BitPerColor` and `PixelsPerScanLine =
HorizontalResolution`, i.e. **stride exactly `width * 4`, no padding**
([`OvmfPkg/QemuRamfbDxe/QemuRamfb.c:277-280`](https://github.com/tianocore/edk2/blob/master/OvmfPkg/QemuRamfbDxe/QemuRamfb.c#L277),
`RAMFB_FORMAT 0x34325258 /* DRM_FORMAT_XRGB8888 */` at `:24`).

`mmap` is available: `efifb_ops` is built from `FB_DEFAULT_IOMEM_OPS` (`efifb.c:271-275`), which
expands to `.fb_read/.fb_write/.fb_fillrect/.fb_copyarea/.fb_imageblit` **and `.fb_mmap =
fb_io_mmap`** ([`include/linux/fb.h:551-566`](https://github.com/torvalds/linux/blob/v6.12/include/linux/fb.h#L551)).
Slint maps `line_length * height` bytes with `memmap2::MmapOptions::map_mut`, and `smem_len` is
`size_vmode * 2` page-rounded (`efifb.c:429-438`), so the mapping always fits.

The mapping is write-combining when the UEFI memory map says the region is WC, plain uncached
`ioremap` when it says UC, `memremap(MEMREMAP_WT|WB)` otherwise (`efifb.c:479-491`). That ordering is
why the design in the next paragraph matters.

### Stride is handled — and only since 1.13.0

`LinuxFBDisplay` does **not** render into the `mmap`. It allocates a packed heap back buffer of
`width * height * bpp`, renders into that with `pixel_stride = width`, and then copies:

```rust
if line_length == pixel_row_size {
    fb.as_mut().copy_from_slice(&back_buffer);
} else {
    for y in 0..self.height as usize { /* row-by-row, honouring line_length */ }
}
```

It also refuses a framebuffer whose `line_length` is *less* than `width * bpp` rather than
corrupting memory. **That row-loop is the 1.13.0 change** ("support for a padded legacy linux
framebuffers", upstream [#9000](https://github.com/slint-ui/slint/pull/9000), 2025-07-28). Before it,
a framebuffer with `pixels_per_scan_line > width` — which real firmware GOPs do produce, and which
`gop.c`'s `PIXEL_BIT_MASK` branch computes as `(pixels_per_scan_line * depth) / 8` — rendered
sheared. aobs is on 1.17, so this is a floor to record, not a risk to carry.

The cached-heap-buffer design is deliberate and upstream measured it. From the July 2026 commit that
gave the *Skia* software path the same treatment (`008b793`, in 1.17.1): *"Dumb buffer mappings are
typically write-combined (uncached), so every operation that blends … reads destination pixels at
uncached speed. Measured on an AM62L3 EVM: 141 MB/s reads vs 10.4 GB/s writes … The copy is a pure
sequential write, which write-combined memory absorbs at full speed."* Its commit message says
plainly: *"LinuxFB already renders into a cached heap buffer internally and doesn't need another
one."*

### Partial redraw bookkeeping

`map_back_buffer` reports buffer **age 0 on the first frame and 1 forever after**, which
`SoftwareRendererAdapter` maps to `RepaintBufferType::NewBuffer` then
`RepaintBufferType::ReusedBuffer`. That is correct: the heap back buffer always holds the complete
previous frame, so Slint redraws only the dirty region into it.

**But `copy_to_framebuffer()` takes no dirty region and copies the whole screen every time.** So
partial rendering saves the *drawing*, not the *copy*: every rendered frame is a full
`line_length * height` sequential write. It is at least gated — `render_if_needed` only renders when
`redraw_requested` was set
([`fullscreenwindowadapter.rs:101-106`](https://github.com/slint-ui/slint/blob/v1.17.1/internal/backends/linuxkms/fullscreenwindowadapter.rs#L101)) —
which for a mostly-static signing screen means the copy happens on interaction, not at 60 Hz. The
DRM dumb-buffer path *does* copy only damaged rows; the fbdev path does not.

## 5. Vsync and tearing: there is no mechanism at all

`LinuxFBDisplay` hands out a `NoopPresenter`, whose `present()` is `Ok(())`
([`display.rs`, `mod noop_presenter`](https://github.com/slint-ui/slint/blob/v1.17.1/internal/backends/linuxkms/display.rs)),
with the comment *"Used when the underlying renderer/display takes care of the presentation to the
display and (hopefully) implements vsync."* On the fbdev path nothing does. The DRM path by contrast
runs three dumb buffers and `wait_for_page_flip()`
([`dumbbuffer.rs:94-102`](https://github.com/slint-ui/slint/blob/v1.17.1/internal/backends/linuxkms/display/swdisplay/dumbbuffer.rs#L94)).

**And the kernel would refuse anyway.** Both candidate mechanisms are dead on `efifb`:

- **`FBIOPAN_DISPLAY`** — `fb_pan_display()` bails with `-EINVAL` when
  `!info->fbops->fb_pan_display`
  ([`fbmem.c:186-189`](https://github.com/torvalds/linux/blob/v6.12/drivers/video/fbdev/core/fbmem.c#L186)),
  and `efifb_ops` has no `fb_pan_display`. Independently, `efifb` sets `ypanstep = 0` and
  `ywrapstep = 0` (`efifb.c:541-542`), and sets **`yres_virtual = yres`** (`:512`) despite having
  remapped `size_vmode * 2` — so there is no second page to pan to even if the op existed.
- **`FBIO_WAITFORVSYNC`** — defined generically as `_IOW('F', 0x20, __u32)`
  ([`include/uapi/linux/fb.h:38`](https://github.com/torvalds/linux/blob/v6.12/include/uapi/linux/fb.h#L38))
  but implemented per driver. `do_fb_ioctl`'s default arm returns **`-ENOTTY`** when
  `fb->fb_ioctl` is NULL
  ([`fb_chrdev.c:151-158`](https://github.com/torvalds/linux/blob/v6.12/drivers/video/fbdev/core/fb_chrdev.c#L151)),
  and `efifb` provides none.

**So: tearing is possible and there is no fix available at any layer.** What it looks like in
practice: the scanout reads the same memory the app is sequentially memcpying into, so a redraw that
straddles the vertical blank shows the top of the new frame and the bottom of the old one for one
refresh. `01-boot-layer.md` §7's screens are static text; redraws happen on keypress and on the
camera preview. **The camera preview is the one place this is not obviously acceptable** and is the
thing to look at in a prototype, not the review screen. The cost of the copy itself —
8,294,400 bytes to WC memory at 1920×1080 — is **not measured**, and belongs on the owed-measurements
list rather than being asserted here.

Two adjacent scares, both checked and both false alarms:

- **Console blanking does not exist by default.** `blankinterval` is a plain uninitialised `static
  int` — zero — in
  [`drivers/tty/vt/vt.c:180-181`](https://github.com/torvalds/linux/blob/v6.12/drivers/tty/vt/vt.c#L180),
  and `Documentation/admin-guide/kernel-parameters.txt` says of `consoleblank=`: *"A value of 0
  disables the blank timer. Defaults to 0."* A static screen will not blank. Do **not** cargo-cult
  `consoleblank=0` onto the cmdline; it is already the default.
- **Cursor.** `vt.global_cursor_default=0` is already on the cmdline (§6), which is the visible
  artefact `KD_GRAPHICS` would otherwise suppress. See [§6](#6-kd_graphics-cannot-be-set-by-signer) for
  what remains.

## 6. `KD_GRAPHICS` cannot be set by `signer`

`LinuxFBDisplay::new` calls `setup_graphics_mode()`, which **opens `/dev/console` first**, uses
`VT_GETSTATE` to find the active VT, then `KDSETMODE`/`KD_GRAPHICS` on `/dev/tty<N>`. On failure it
prints `"Warning: Could not set graphics mode: …"` and continues — it is not fatal.

It will fail for an unprivileged user, and the reason is `/dev/console`'s mode:

- `devtmpfs_create_node` uses **`0600` root:root** when the device supplies no mode
  ([`drivers/base/devtmpfs.c:122-135`](https://github.com/torvalds/linux/blob/v6.12/drivers/base/devtmpfs.c#L122)).
- `tty_devnode` only relaxes to `0666` for `MKDEV(TTYAUX_MAJOR, 0)` and `MKDEV(TTYAUX_MAJOR, 2)`
  — `/dev/tty` and `/dev/ptmx`. `/dev/console` is minor **1**, so it keeps `0600`
  ([`drivers/tty/tty_io.c:3526-3539`](https://github.com/torvalds/linux/blob/v6.12/drivers/tty/tty_io.c#L3526)).
- No udev rule widens it: `50-udev-default.rules.in`'s `SUBSYSTEM=="tty"` rules match `ptmx`, the
  literal `tty`, and `tty[0-9]*` — never `console`.

Even past that, `/dev/tty1` is `GROUP="tty", MODE="0620"` — group has **write but not read** — and
Slint opens it `.read(true).write(true)`. So group `tty` would not help either; `logind` normally
chowns the VT to the session user, and this appliance has no logind session.

**Consequence, stated as a cost rather than solved here:** the VT stays in `KD_TEXT` and `fbcon`
remains live on the same framebuffer. With `quiet loglevel=3` and no gettys nothing routinely writes
there, but a `KERN_ERR`-or-worse printk would land on top of the UI, and because partial rendering
believes the back buffer matches the screen, that text would **persist until something dirties those
pixels**. This is the one genuinely new failure mode the fbdev path introduces, and it is the
opposite face of `01-boot-layer.md` §9, which *wants* that console to exist. Deciding between
`TTYPath=/dev/tty1` on the unit, a tmpfiles/udev relaxation of `/dev/console`, an upstream patch that
skips `/dev/console` and uses `/dev/tty0`, and simply accepting it is
[#49](https://github.com/allisson/aobs/issues/49)'s business, not this ticket's. **I did not verify
empirically whether `fbcon` repaints in practice on the built image**, nor whether Debian sets
`CONFIG_FRAMEBUFFER_CONSOLE_DEFERRED_TAKEOVER`.

## 7. Input: no `libseat`, no `seatd`, and the path interface is not needed

The ticket asks whether `libinput` can be driven with its *path* interface. It can — but **Slint
already solves this without it**, and the answer to the packaging question does not depend on the
path interface at all.

With `libseat` off, Slint uses `DirectDeviceAccess`, whose `open_restricted` is a plain
`OpenOptions::open`, and constructs the context as
([`calloop_backend/input.rs:81-115`](https://github.com/slint-ui/slint/blob/v1.17.1/internal/backends/linuxkms/calloop_backend/input.rs#L81)):

```rust
let mut libinput = input::Libinput::new_with_udev(Self {});
libinput.udev_assign_seat("seat0").unwrap();
```

That is `libinput`'s **udev** interface with a hardcoded `"seat0"`, not the path interface — and it
works with no seat manager, because `seat0` is what every unassigned device already belongs to.
libinput's `udev-seat.c`:

```c
static const char default_seat[] = "seat0";
…
device_seat = udev_device_get_property_value(udev_device, "ID_SEAT");
if (!device_seat)
        device_seat = default_seat;
```

([`src/udev-seat.c:34,82-84`](https://gitlab.freedesktop.org/libinput/libinput/-/blob/main/src/udev-seat.c#L34)).
`ID_SEAT` is only set for genuinely multi-seat hardware, so on this appliance every keyboard is
`seat0`. What that costs: **`libudev1` at runtime, which is already in the base system** (it is
`systemd`'s library), and group `input` for the `open()`.

For completeness, the path interface is real and documented — `libinput_path_create_context`
*"Create a new libinput context that requires the caller to manually add or remove devices with
libinput_path_add_device() and libinput_path_remove_device()"*, with no mention of udev or seats,
against `libinput_udev_create_context` which *"is inactive until assigned a seat ID with
libinput_udev_assign_seat()"*
([libinput API, base group](https://wayland.freedesktop.org/libinput/doc/latest/api/group__base.html)).
`Libinput::new_from_path` exists in the `input` crate 0.10.0 that Slint depends on. **It buys nothing
here**: it would remove no package (`libudev1` is base), and it would cost us device enumeration and
hotplug — which `01-boot-layer.md` §7 requires ("keeps polling, so hot-plug recovers without a
reboot"). Recommendation: do not build it.

One fragility to record: that `udev_assign_seat("seat0").unwrap()` is an upstream `unwrap`. With
`panic = "unwind"` (§10) it lands in `main.rs`'s `catch_unwind` as `Failure::Panicked`, so it is
reported rather than silent — but it is a panic in a dependency on the input path, and worth a line
in whatever test asserts §9.

## 8. What this means for the spec

**Package closure: 22 → 20.** `libseat1` and `seatd` come out of
`image/config/package-lists/aobs.list.chroot`. Nothing else in the measured 22
(`docs/research/05-tauri-viability.md` §6) depends on either. `libseat-dev` also leaves the *build*
dependency list, since the `libseat` crate is never compiled.
**Not re-measured with `apt` — that simulation is owed**, and the published package manifest
(ADR-0012) is what makes it auditable.

**Cargo change, in full:**

```toml
features = ["compat-1-2", "std", "backend-linuxkms-noseat", "renderer-software"]
```

`renderer-software` continues to pull the `drm` crate as a hard dependency of the backend's
`renderer-software` feature — but `drm`/`drm-ffi`/`drm-sys` are pure-Rust ioctl wrappers with
pregenerated bindings, and `pkg_config::probe("libdrm")` sits behind `drm-sys`'s non-default
`use_bindgen` feature ([`drm-sys/build.rs`](https://github.com/Smithay/drm-rs/blob/master/drm-sys/build.rs)).
So there is **no `libdrm` at build time and none at runtime**, and no change from today.

**`signer`'s groups become `video` and `input`, full stop.** `01-boot-layer.md` §2's build hook that
reads the seat group out of `seatd.service` is deleted along with `seatd`.

**RAM, since §7's provisional 2 GiB floor counts the renderer's framebuffers.** `SoftwareRenderer`
itself allocates **no pixel-sized buffer** — its fields are a repaint-buffer-type cell, two dirty
regions, a per-item partial-rendering cache, a rotation, and (with `systemfonts`) a text layout cache
([`software/lib.rs:438-450`](https://github.com/slint-ui/slint/blob/v1.17.1/internal/renderers/software/lib.rs#L438)).
Everything pixel-scaled is what the *display* allocates:

| Path | Pixel buffers at 1920×1080 | Heap |
| --- | --- | ---: |
| `LinuxFBDisplay` | one packed 32-bpp back buffer | **7.91 MiB** |
| `DumbBufferDisplay` | front + back + in-flight dumb buffers | 23.73 MiB |
| `LinuxFBDisplay`, `Rgb565` | one packed 16-bpp back buffer | 3.96 MiB |

(`1920 × 1080 × 4 = 8,294,400 B`; the dumb buffers are three separate `create_dumb_buffer` calls at
[`dumbbuffer.rs:40-58`](https://github.com/slint-ui/slint/blob/v1.17.1/internal/backends/linuxkms/display/swdisplay/dumbbuffer.rs#L40).)
**The fbdev path costs about 16 MiB *less* than the DRM path**, and the `mmap` of `/dev/fb0` is not
an additional allocation — it maps firmware-reserved memory that exists whether or not we use it.
Either way this is single-digit MiB against a 2 GiB floor: the floor is `toram` plus squashfs plus
Argon2id's 64 MiB, and the renderer is noise in it. `render_by_line` exists as the low-memory escape
and is not needed.

**What CI can assert.** `05-testing-and-release.md` §6.2's `ramfb` row becomes assertable rather than
impossible: OVMF + `ramfb` gives `efifb` at `PixelBlueGreenRedReserved8BitPerColor`, `stride =
width * 4` (§4), which negotiates to `Argb8888`. The `AOBS_READY` line already printed from inside
the running event loop is the assertion — no screenshot diff needed. And per the standing rule, it
asserts the shipped ISO, not the source tree.

**What this does *not* settle.** Whether candidate 4 *wins* is [#49](https://github.com/allisson/aobs/issues/49)'s
call. This ticket says only that it is available, cheap, upstream, and unblocks legacy BIOS via
`vesafb` in principle — `vesafb` is `CONFIG_FB_VESA=y` in Debian's kernel per
[#40](https://github.com/allisson/aobs/issues/40), and `01-boot-layer.md` §7's "which Slint cannot
render to" is now false for both `efifb` and `vesafb`. **I did not verify `vesafb`'s reported pixel
layout**, and ADR-0009's pre-2012 exclusion is a decision, not a consequence.

## 9. What I could not verify

Stated plainly, because the mechanism above is read from source and none of it was run:

1. **No boot.** I did not build an ISO with `backend-linuxkms-noseat` and watch it draw on `efifb`.
   Everything in §2–§4 is source and kernel reading. The empirical proof is a prototype ticket, and
   its minimal form is one boot under OVMF + `ramfb` looking for `AOBS_READY`.
2. **The ISO's actual Slint error text was destroyed** by `main.rs`'s `.map_err(|_|
   Failure::DisplayUnavailable)`, so §3's `libseat`/`ENOENT` mechanism — though certain from
   `seatd`'s source — was never *observed* as the cause on this image. A boot with the message
   preserved would confirm it in one line.
3. **The full-frame copy is unmeasured** (8,294,400 B to write-combining memory per rendered frame),
   and so is whether tearing is perceptible on the camera preview.
4. **The package closure is not re-measured.** 22 → 20 is arithmetic on
   `05-tauri-viability.md` §6's list, not an `apt` simulation.
5. **`fbcon` interference is theoretical.** I did not check whether Debian 13 sets
   `CONFIG_FRAMEBUFFER_CONSOLE_DEFERRED_TAKEOVER`, nor observe a printk landing on the UI.
6. **Only `QemuRamfbDxe` was checked** among OVMF's display paths. `QemuVideoDxe`, `BochsDisplay` and
   `VirtioGpuDxe` were not, and neither was any real firmware GOP — real firmware may use
   `PIXEL_BIT_MASK` and a padded `pixels_per_scan_line`, which Slint handles since 1.13.0 but which I
   did not exercise.
7. **`vesafb`'s `fb_var_screeninfo`** under legacy BIOS was not read. The legacy-BIOS claim is
   plausible and unverified, in exactly the way this ticket's own premise was.

---

## Sources

| Claim | Source |
| --- | --- |
| `/dev/fb0` display implementation, format table, stride copy, VT graphics mode | [`internal/backends/linuxkms/display/swdisplay/linuxfb.rs`](https://github.com/slint-ui/slint/blob/v1.17.1/internal/backends/linuxkms/display/swdisplay/linuxfb.rs) |
| DRM-then-fbdev fallback chain, `SLINT_BACKEND_LINUXFB`, `negotiate_format` | [`display/swdisplay.rs`](https://github.com/slint-ui/slint/blob/v1.17.1/internal/backends/linuxkms/display/swdisplay.rs) |
| `NoopPresenter` and its comment | [`display.rs`](https://github.com/slint-ui/slint/blob/v1.17.1/internal/backends/linuxkms/display.rs) |
| Renderer format list, buffer-age → `RepaintBufferType`, `render(buffer, width)` | [`renderer/sw.rs`](https://github.com/slint-ui/slint/blob/v1.17.1/internal/backends/linuxkms/renderer/sw.rs) |
| Triple dumb buffers, `wait_for_page_flip` | [`display/swdisplay/dumbbuffer.rs`](https://github.com/slint-ui/slint/blob/v1.17.1/internal/backends/linuxkms/display/swdisplay/dumbbuffer.rs) |
| Two `device_accessor` closures, `libseat` gate | [`calloop_backend.rs`](https://github.com/slint-ui/slint/blob/v1.17.1/internal/backends/linuxkms/calloop_backend.rs) |
| `DirectDeviceAccess`, `new_with_udev` + `udev_assign_seat("seat0")` | [`calloop_backend/input.rs`](https://github.com/slint-ui/slint/blob/v1.17.1/internal/backends/linuxkms/calloop_backend/input.rs) |
| `/dev/dri` probe fails to `Err`, no `set_master` | [`drmoutput.rs`](https://github.com/slint-ui/slint/blob/v1.17.1/internal/backends/linuxkms/drmoutput.rs) |
| `render_if_needed` gate | [`fullscreenwindowadapter.rs`](https://github.com/slint-ui/slint/blob/v1.17.1/internal/backends/linuxkms/fullscreenwindowadapter.rs) |
| `libseat` optional, `default = []`; `renderer-software` → `drm` | [`internal/backends/linuxkms/Cargo.toml`](https://github.com/slint-ui/slint/blob/v1.17.1/internal/backends/linuxkms/Cargo.toml) |
| `backend-linuxkms` = `libseat`; `-noseat` = without | [`internal/backends/selector/Cargo.toml`](https://github.com/slint-ui/slint/blob/v1.17.1/internal/backends/selector/Cargo.toml), [`api/rs/slint/Cargo.toml`](https://github.com/slint-ui/slint/blob/v1.17.1/api/rs/slint/Cargo.toml) |
| `platform` unconditional, `software_renderer` gated on `renderer-software` | [`api/rs/slint/lib.rs`](https://github.com/slint-ui/slint/blob/v1.17.1/api/rs/slint/lib.rs#L414) |
| `TargetPixel` unsealed; `Rgb8Pixel`/`PremultipliedRgbaColor`/`Rgb565Pixel` impls | [`internal/renderers/software/draw_functions.rs`](https://github.com/slint-ui/slint/blob/v1.17.1/internal/renderers/software/draw_functions.rs#L839) |
| `render(buffer, pixel_stride)`; `SoftwareRenderer` fields hold no framebuffer | [`internal/renderers/software/lib.rs`](https://github.com/slint-ui/slint/blob/v1.17.1/internal/renderers/software/lib.rs#L438) |
| Custom `Platform` + `TargetPixel` off-MCU | [`examples/uefi-demo/main.rs`](https://github.com/slint-ui/slint/blob/v1.17.1/examples/uefi-demo/main.rs) |
| 1.7.0 / 1.13.0 changelog entries | [`CHANGELOG.md`](https://github.com/slint-ui/slint/blob/v1.17.1/CHANGELOG.md) |
| WC-read measurement quoted from upstream | commit [`008b793`](https://github.com/slint-ui/slint/commit/008b793a90bf7d789c5c87b2251b77e80ee9e40e) |
| Padded-framebuffer support | PR [#9000](https://github.com/slint-ui/slint/pull/9000) |
| Third-party fbdev use, `Bgra8888` request | [issue #9862](https://github.com/slint-ui/slint/issues/9862) |
| *Legacy LinuxFB Interface*, `-noseat` note, no software mouse cursor | [docs.slint.dev — LinuxKMS Backend](https://docs.slint.dev/latest/docs/slint/guide/backends-and-renderers/backend_linuxkms/) |
| Feature list for 1.17.1 | [docs.rs/crate/slint/1.17.1/features](https://docs.rs/crate/slint/1.17.1/features) |
| `seat_open_device` device-type allowlist, `errno = ENOENT` | [`seatd/seat.c`](https://git.sr.ht/~kennylevinsen/seatd/tree/master/item/seatd/seat.c) |
| `path_is_drm` = `/dev/dri/` prefix | [`common/drm.c`](https://git.sr.ht/~kennylevinsen/seatd/tree/master/item/common/drm.c) |
| `libinput` path vs udev interface | [libinput API, base group](https://wayland.freedesktop.org/libinput/doc/latest/api/group__base.html) |
| `ID_SEAT` unset ⇒ `seat0` | [`src/udev-seat.c`](https://gitlab.freedesktop.org/libinput/libinput/-/blob/main/src/udev-seat.c) |
| `efifb` var/fix screeninfo, `ioremap_wc`, `yres_virtual = yres`, `ypanstep = 0`, `FB_DEFAULT_IOMEM_OPS` | [`drivers/video/fbdev/efifb.c`](https://github.com/torvalds/linux/blob/v6.12/drivers/video/fbdev/efifb.c) |
| `FB_DEFAULT_IOMEM_OPS` includes `fb_mmap = fb_io_mmap` | [`include/linux/fb.h`](https://github.com/torvalds/linux/blob/v6.12/include/linux/fb.h#L551) |
| `fb_pan_display` → `-EINVAL` without the op | [`drivers/video/fbdev/core/fbmem.c`](https://github.com/torvalds/linux/blob/v6.12/drivers/video/fbdev/core/fbmem.c#L186) |
| `do_fb_ioctl` default arm → `-ENOTTY` | [`drivers/video/fbdev/core/fb_chrdev.c`](https://github.com/torvalds/linux/blob/v6.12/drivers/video/fbdev/core/fb_chrdev.c#L151) |
| `FBIO_WAITFORVSYNC` definition | [`include/uapi/linux/fb.h`](https://github.com/torvalds/linux/blob/v6.12/include/uapi/linux/fb.h#L38) |
| EFI stub GOP → `screen_info` pixel layout | [`drivers/firmware/efi/libstub/gop.c`](https://github.com/torvalds/linux/blob/v6.12/drivers/firmware/efi/libstub/gop.c#L429) |
| `consoleblank` defaults to 0 | [`drivers/tty/vt/vt.c`](https://github.com/torvalds/linux/blob/v6.12/drivers/tty/vt/vt.c#L180), [`kernel-parameters.txt`](https://github.com/torvalds/linux/blob/v6.12/Documentation/admin-guide/kernel-parameters.txt) |
| devtmpfs default `0600`; `tty_devnode` only relaxes minors 0 and 2 | [`drivers/base/devtmpfs.c`](https://github.com/torvalds/linux/blob/v6.12/drivers/base/devtmpfs.c#L122), [`drivers/tty/tty_io.c`](https://github.com/torvalds/linux/blob/v6.12/drivers/tty/tty_io.c#L3526) |
| `graphics`/`drm`/`input`/`video4linux` device groups | [systemd `rules.d/50-udev-default.rules.in`](https://github.com/systemd/systemd/blob/v257/rules.d/50-udev-default.rules.in) |
| OVMF `ramfb` pixel format and stride | [`OvmfPkg/QemuRamfbDxe/QemuRamfb.c`](https://github.com/tianocore/edk2/blob/master/OvmfPkg/QemuRamfbDxe/QemuRamfb.c) |
| `drm-sys` bindgen behind a non-default feature | [`drm-sys/build.rs`](https://github.com/Smithay/drm-rs/blob/master/drm-sys/build.rs) |

---
