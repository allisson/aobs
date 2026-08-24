# Research: webcam capture and QR decode stack on Alpine/musl (amd64)

Ticket: [#6](https://github.com/allisson/aobs/issues/6) (items 1–4 original, 5–8 added because the
UI-surface decision [#3](https://github.com/allisson/aobs/issues/3) is blocked on them).
Branch `research/webcam-qr-stack` — findings only, no decision. The map ([#1](https://github.com/allisson/aobs/issues/1))
and the human own the decision.

Convention note: `docs/` previously held only `threat-model.md` (a closed decision). Research notes
go under `docs/research/`.

All package data below comes from the Alpine **v3.24** `APKINDEX` for `x86_64`, fetched from
`https://dl-cdn.alpinelinux.org/alpine/v3.24/{main,community}/x86_64/APKINDEX.tar.gz` on
2026-08-24, and from the `3.24-stable` branch of `aports`. `v3.24/testing/x86_64/APKINDEX.tar.gz`
returns HTTP 404 — **there is no `testing` repository for a stable release**; `testing` exists only
on `edge`. Sizes are apk `I:` (installed size) fields; "closure" means the transitive `D:`
dependency set resolved against v3.24 main+community, summed. Kernel facts are from
`torvalds/linux` at tag `v6.18` (Alpine v3.24 ships `linux-lts 6.18.44-r0`).

## TL;DR

| | winner | weight over a python3-only system |
|---|---|---|
| capture | **direct V4L2 from Python** (kernel uAPI ioctls; no Alpine package) | ~0 (vendored pure-Python, or ~150 lines of `fcntl.ioctl`) |
| decode | **`py3-zxing-cpp` 2.3.0-r3** (community) | **+1.35 MiB** |
| second decoder (optional) | `py3-zbar` 0.23.93-r2 (community) | +4.52 MiB (both decoders: +5.87 MiB) |
| ruled out | `py3-opencv` +516 MiB · GStreamer +297 MiB · `py3-pyzbar` +26.5 MiB · `libcamera` +250 MiB | |

Neither winner needs a display server. Neither constrains the UI surface. Total added ISO weight
for the recommended combination: **~1.4 MiB installed**, or ~5.9 MiB if both decoders ship.

**Cross-cutting flag for the threat model, not for this ticket to settle:** a webcam is a USB
**Video** Class device, not HID. The closed claim in `CONTEXT.md` — "USB is restricted to the HID
class" — is contradicted by any USB webcam. Either the claim becomes "HID and UVC only", or the
camera is not on USB. This needs to go back to the map.

---

## 1. CAPTURE

### What exists in Alpine v3.24 (x86_64)

| package | version | repo | installed | closure over `python3` |
|---|---|---|---|---|
| `v4l-utils-libs` | 1.32.0-r1 | community | 0.57 MiB | +1.25 MiB |
| `v4l-utils` (`v4l2-ctl`) | 1.32.0-r1 | community | 2.35 MiB | +3.65 MiB |
| `gstreamer` | 1.28.3-r0 | **main** | 3.06 MiB | — |
| `gst-plugins-base` | 1.28.3-r0 | **main** | 6.61 MiB | — |
| `gst-plugins-good` | 1.28.3-r0 | community | 6.89 MiB | — |
| gstreamer + base + good + `py3-gobject3` | | | | **+297.69 MiB** (114 pkgs) |
| `opencv` / `py3-opencv` | 4.12.0-r7 | community | 6.33 MiB (py3) | **+516.59 MiB** (189 pkgs) |
| `libcamera` / `py3-libcamera` | 0.7.1-r1 | community | 1.98 MiB | **+250.47 MiB** |

All of these are in **stable v3.24**, none is edge-only. The three heavy options collapse for the
same reason: `so:libGL.so.1` → `mesa-gl` → `mesa` (42.13 MiB) → `llvm22-libs` (**182.13 MiB**).
`mesa`'s own closure is 240.2 MiB.

- `py3-opencv` `D:` includes `libopencv_highgui` (which needs `libQt6Core/Gui/Widgets/OpenGLWidgets/Test`)
  and `libopencv_core` (which needs `openblas` 35.09 MiB + `so:libGL.so.1`). Confirmed in the
  APKBUILD: `-DWITH_QT=ON -DWITH_OPENGL=ON -DWITH_VULKAN=ON -DWITH_OPENCL=ON`. There is no lighter
  packaged subset: even `libopencv_objdetect` alone (the module holding `QRCodeDetector`) resolves
  to a **303.0 MiB** closure, because it needs `libopencv_core` → `libGL`.
- `libopencv_videoio` `D:` pulls ffmpeg + the whole GStreamer stack, so OpenCV's `VideoCapture`
  is strictly worse than either alternative.
- `libcamera` is aimed at ISP/CSI pipelines, not UVC-over-V4L2; it is the wrong tool as well as a
  heavy one.

### The option with no package at all

The V4L2 capture API is a set of kernel ioctls (`VIDIOC_QUERYCAP`, `_ENUM_FMT`, `_S_FMT`,
`_REQBUFS`, `_QUERYBUF`, `_QBUF`, `_DQBUF`, `_STREAMON`) plus `mmap` on `/dev/video0`. All of it is
reachable from CPython with `fcntl.ioctl`, `ctypes`/`struct` and `mmap` — **zero native
dependencies, zero added ISO weight**.

- `linuxpy` 0.25.0 (PyPI) is a pure-Python implementation of exactly this — wheel is
  `linuxpy-0.25.0-py3-none-any.whl`, `requires_dist` is only `typing_extensions; python_version < "3.12"`,
  i.e. **no dependencies at all** on Alpine v3.24's `python3` 3.14.7. `v4l2py` 3.0.0 is the same
  author's thin façade over it. Neither is packaged in Alpine → vendor the source.
- **UNCONFIRMED:** I did not exercise `linuxpy` (or hand-rolled ioctls) against a real UVC camera in
  this session — no camera is reachable from here. What would settle it: boot the ISO candidate on a
  machine with a UVC webcam and stream frames.

### Pixel format matters more than the capture library

For QR decoding only luminance is needed. A UVC camera that offers `YUYV` (`V4L2_PIX_FMT_YUYV`,
4:2:2 packed) gives the Y plane as every even byte: `frame[0::2]` — a single CPython slice, **0.39
ms per 1280×720 frame** (measured; see the caveat in item 6 about the machine). No JPEG decoder, no
`numpy`, no `Pillow` (`py3-pillow` would be +8.00 MiB).

If only `MJPG` is available, a JPEG decoder is required, which reintroduces a dependency
(`py3-pillow` +8.00 MiB, or `libjpeg` via a binding). **UNCONFIRMED:** whether every camera the
appliance should support offers YUYV at a usable resolution and frame rate. Most UVC devices do at
640×480; a required-format check with a clear failure message is the safe design.

### UVC and firmware blobs offline

**No firmware blob is needed for a standard UVC webcam.** Every `.c` file in
`drivers/media/usb/uvc/` at `v6.18` (`uvc_driver.c`, `uvc_video.c`, `uvc_ctrl.c`, `uvc_v4l2.c`,
`uvc_queue.c`, `uvc_status.c`, `uvc_entity.c`, `uvc_metadata.c`, `uvc_debugfs.c`) contains **zero
occurrences of `request_firmware`** — grepped directly against the tagged source. The class driver
configures the device over standard UVC control requests only.

- Alpine's `linux-lts` 6.18.44 config (`aports 3.24-stable/main/linux-lts/lts.x86_64.config`) has
  `CONFIG_USB_VIDEO_CLASS=m` and `CONFIG_MEDIA_USB_SUPPORT=y`, so `uvcvideo` is available as a
  module in the stock kernel.
- `linux-firmware` (main, 20260519-r0) is a meta-package of 0 bytes; the blobs live in subpackages
  (`linux-firmware-other` alone is 5.35 MiB). **None of them is required for UVC.**
- **UNCONFIRMED / caveat:** non-UVC webcams exist (the `gspca` family and some vendor drivers), and
  some of those *do* load firmware. I did not enumerate which. The appliance should require UVC and
  say so, rather than trying to support arbitrary cameras offline.

---

## 2. DECODE

### Packages

| package | version | repo | installed | closure delta over `python3` | X11 in closure? |
|---|---|---|---|---|---|
| `py3-zxing-cpp` | 2.3.0-r3 | community | 0.27 MiB | **+1.35 MiB** (3 pkgs) | **no** |
| `zxing-cpp` (lib) | 2.3.0-r3 | community | 0.97 MiB | | no |
| `py3-zbar` | 0.23.93-r2 | community | 0.05 MiB | **+4.52 MiB** (12 pkgs) | yes (libs only) |
| `libzbar` | 0.23.93-r2 | community | 0.18 MiB | +4.47 MiB | yes (libs only) |
| `py3-pyzbar` | 0.1.9-r5 | community | 0.05 MiB | **+26.48 MiB** (41 pkgs) | yes |
| `py3-opencv` (`QRCodeDetector`) | 4.12.0-r7 | community | 6.33 MiB | **+516.59 MiB** | yes (Qt6+mesa) |

Everything is in **stable v3.24 community**; nothing needed from edge or testing.

### Three findings that change the shape of the decision

**(a) `pyzbar` is the expensive way to reach zbar.** `py3-pyzbar`'s `D:` field is
`python3 zbar python3~3.14` — it depends on the **`zbar` binary package**, whose own `D:` is
`py3-gobject3 so:libMagickWand-7.Q16HDRI.so.10 …`. So choosing pyzbar drags in ImageMagick
(`imagemagick-libs` 4.21 MiB), GLib (5.14 MiB), gobject-introspection, `fftw`, `harfbuzz`, `cairo` —
41 packages, +26.5 MiB. The upstream binding `py3-zbar` (`D: python3~3.14 so:libzbar.so.0`) reaches
the same scanner for **+4.52 MiB**. If zbar is used at all, use `py3-zbar`, not `pyzbar`.
(Seedsigner uses `pyzbar`; that is a Raspberry Pi OS choice, not an Alpine one.)

**(b) `zxing-cpp` is both the smallest and the least entangled.** `py3-zxing-cpp`'s only non-libc
dependencies are `zxing-cpp`, `py3-pybind11` (0.10 MiB) and `libstdc++`. **No X11, no OpenGL, no
BLAS, no numpy.** Its Python API takes a plain 2-D buffer — the docstring reads
`:type image: buffer|numpy.ndarray|PIL.Image.Image`, and `memoryview(y_plane).cast('B', (H, W))`
is accepted, so a raw V4L2 Y plane goes straight in with no intermediate library.
Alpine builds it `-DCMAKE_BUILD_TYPE=MinSizeRel -DBUILD_READERS=ON -DBUILD_PYTHON_MODULE=on`.

**(c) Alpine's zbar is built `--disable-video`.** From `aports 3.24-stable/community/zbar/APKBUILD`:

```
./configure … --disable-video --with-python=python3 --with-gtk=gtk3 --with-gir …
```

So zbar's own V4L2 capture (`zbarcam`, `zbar.Processor`) **is not available** in Alpine. zbar can
only be handed frames the application captured itself. This removes "let zbar own the camera" as an
option and makes item 1 (capture) independent of the decoder either way.

`libzbar` still links X: `D: so:libX11.so.6 so:libXv.so.1 so:libdbus-1.so.3 so:libjpeg.so.8`
(that is zbar's `zbar_window` output backend, compiled in). Those are **link-time library
dependencies, not a runtime display-server requirement** — see item 5.

### No viable pure-Python decoder

`py3-qrcode` 8.2-r2 (community) is an **encoder**. I found no maintained pure-Python QR *decoder* in
Alpine's repositories. **UNCONFIRMED** whether any pure-Python decoder on PyPI could sustain the
needed rate; given that both C options cost ≤4.5 MiB, the question does not need answering.

---

## 3. Pure-Python / pure-C, display-server-free?

- `zxing-cpp` + `py3-zxing-cpp`: C++ library with a pybind11 binding. **No display dependency at
  any level** — not even a linked X library.
- `libzbar` + `py3-zbar`: C library with a C Python binding. X libraries linked, no server needed.
- Capture: pure Python (kernel ioctls). No library at all.

**Neither decoder constrains the UI surface.** Whatever #3 picks — framebuffer TUI, native toolkit,
or direct `/dev/fb0` — the capture/decode half is unaffected.

---

## 4. Total added ISO weight

Baseline for comparison: `python3` closure is **34.79 MiB** (18 packages) and `alpine-base` is
9.6 MiB. The appliance needs CPython regardless, so the honest number is the delta over it.

| combination | added installed size |
|---|---|
| **`py3-zxing-cpp` + pure-Python V4L2 (recommended)** | **+1.35 MiB** |
| `py3-zxing-cpp` + `py3-zbar` (two decoders) | +5.87 MiB |
| … + `v4l-utils` (`v4l2-ctl`, diagnostics only) | +7.55 MiB |
| `py3-zbar` alone | +4.52 MiB |
| `py3-pyzbar` | +26.48 MiB |
| GStreamer capture stack | +297.69 MiB |
| `py3-opencv` (capture **and** decode) | +516.59 MiB |

For scale, since the whole image is copied into RAM: `mesa` alone is 240.2 MiB and
`llvm22-libs` is 182.13 MiB. Choosing OpenCV or GStreamer would multiply the RAM footprint of the
appliance many times over; choosing `py3-zxing-cpp` costs about the size of one of CPython's larger
stdlib extension sets.

---

## 5. Does any capture or decode path need a display server?

**No — confirmed, not assumed.**

- Package-level: `py3-zxing-cpp`'s full closure contains no X, Wayland, GL, or Qt package.
  `py3-zbar`'s closure contains X *libraries* (`libx11`, `libxcb`, `libxext`, `libxv`,
  `libxau`, `libxdmcp`) because `libzbar.so.0` is linked against them, plus `dbus-libs`.
- Runtime: in an Alpine 3.24 container with **no X server, no Wayland compositor, empty `$DISPLAY`
  and no `/tmp/.X11-unix`**, `import zbar; zbar.ImageScanner().scan(zbar.Image(w,h,'Y800',buf))`
  decoded 100/100 frames, and `zxingcpp.read_barcodes(memoryview(...).cast('B',(H,W)))` likewise.
  The X libraries are loaded by the dynamic linker and never used.
- OpenCV's *decoder* (`QRCodeDetector`, in `libopencv_objdetect`) does not itself need a display
  either; it is `libopencv_highgui` (`cv2.imshow`) that needs Qt6. The problem with OpenCV is
  weight, not display. **A decoder that only works under X does not exist among the candidates**, so
  this does not drag the native-toolkit option back into contention.

---

## 6. Frame rate needed, and rate the candidates sustain

### What the encoder side actually emits (primary sources)

- **Sparrow** `QRDisplayDialog.java` (master): `private static final double ANIMATION_PERIOD_MILLIS = 200d;`
  → **5 frames per second by default**. The mouse-scroll handler multiplies the period by 1.1/0.9
  within the bounds `> ANIMATION_PERIOD_MILLIS/2` and `< ANIMATION_PERIOD_MILLIS*10`, i.e. the user
  can push it to **10 fps at the fastest** and 0.5 fps at the slowest.
- **Sparrow** `QRDensity.java`: `NORMAL("Normal", 400, 2000)`, `LOW("Low", 80, 1000)` — max UR
  fragment length **400 characters** (normal) or 80 (low); the second number is BBQR.
  `MIN_FRAGMENT_LENGTH = 10`.
- **Seedsigner** `src/seedsigner/models/encode_qr.py`: UR max fragment length is
  `{LOW: 10, MEDIUM: 30, HIGH: 120}` characters — much smaller fragments than Sparrow.
- **BC-UR** `bcr-2020-005-ur.md`: "for a 10-part UR, the first part will have the `seq` `1-10` and
  the tenth will have `10-10`. However, parts beyond this can be generated by the fountain encoder,
  hence `seq` values of `11-10` and up are normal." The scheme is described as hybrid fixed-rate +
  rateless (MUR, `bcr-2024-001`): the **first `seqLen` parts are the pure fragments in order**, and
  mixed (XOR) parts follow to repair losses. So with no dropped frames a scan completes in exactly
  `seqLen` frames; every dropped frame costs roughly one extra frame later.

**Derived, not measured:** bytewords encode 2 characters per payload byte, so Sparrow's 400-char
fragment carries on the order of 200 bytes. A 1 kB signed PSBT is then ~6 fragments ≈ **1.2 s at
5 fps**; a 3 kB PSBT ~16 fragments ≈ **3.2 s**. The requirement on the appliance is therefore
"decode at the display rate", i.e. **5 fps, 10 fps worst case** — not tens of fps. Dropping every
other frame merely doubles the scan; the fountain code makes that a delay, not a failure.

### What the candidates sustain

**Documented / primary:** Seedsigner ships a working animated-QR scanner on a Raspberry Pi Zero
(single-core 1 GHz ARM11, no GPU use for this path) at `resolution=(512, 384), framerate=12`
(`src/seedsigner/hardware/camera.py`) decoding with zbar (`pyzbar.decode(image, symbols=[ZBarSymbol.QRCODE])`,
`src/seedsigner/models/decode_qr.py`). That is the strongest evidence available that **zbar at
~12 fps on a very slow CPU is enough for a fountain-encoded UR scan**, and any modest amd64 CPU is
far faster than an ARM11. Krux uses the K210's `img.find_qrcodes()` (MaixPy/OpenMV), which is not
transferable to this stack.

**Indicative only — WRONG ARCHITECTURE, read the caveat:** I ran both decoders in an Alpine 3.24
container on this machine. The container is **arm64 (Apple M1), not amd64**, and the frames are
**synthetic** (crisp modules, uniform lighting, no blur, no perspective, no rolling shutter), so
these numbers say "the same order of magnitude, with headroom", not "this is the appliance's rate".
Each figure is 100 frames, single-threaded, whole-frame scan, Y800/greyscale input.

| frame | payload | zbar | zxing-cpp |
|---|---|---|---|
| 640×480, v9 61×61, clean | 320 B | 5.56 ms (180 fps) | 2.31 ms (433 fps) |
| 640×480, v9 61×61, noisy | 320 B | 17.60 ms (57 fps) | 2.81 ms (356 fps) |
| 640×480, v15 85×85, clean | 735 B | 8.54 ms (117 fps) | 2.71 ms (369 fps) |
| 640×480, v15 85×85, noisy | 735 B | 18.16 ms (55 fps) | 3.21 ms (312 fps) |
| 1280×720, v9 61×61, noisy | 320 B | 51.05 ms (20 fps) | 7.57 ms (132 fps) |
| 1280×720, v15 85×85, noisy | 735 B | 62.78 ms (16 fps) | 8.33 ms (120 fps) |

All 100/100 decoded in every case. Two robust observations survive the architecture caveat:
**zxing-cpp is 3–8× faster than zbar** on identical input, and **zbar degrades sharply with frame
area and pixel noise** (5.6 ms → 63 ms across the table) while zxing-cpp barely moves. Capturing at
640×480 rather than 1280×720 is worth more than the choice of decoder.

**NOT CONFIRMED:** decode rate on a real modest **amd64** CPU with real camera frames (blur,
perspective, uneven lighting, rolling shutter). Docker on this machine is arm64, and
`--platform linux/amd64` would run under emulation, producing meaningless timings. What would settle
it: run the same loop on the amd64 target hardware against a live camera, and record decode
*success rate per displayed frame*, which matters more than milliseconds.

---

## 7. Colour depth and image capability of the bare Linux VT / fbcon

Sources: `drivers/tty/vt/vt.c`, `Documentation/fb/fbcon.rst`, `Documentation/fb/{framebuffer,api}.rst`
at `v6.18`.

**Colour: 16 foreground, 8 background, and only 4 true greys.**

- The console palette is 16 entries: `default_red[]`/`default_grn[]`/`default_blu[]` at `vt.c:1372`,
  and the comment at `vt.c:4759` describing the palette ioctl reads
  *"map, 3 bytes per colour, 16 colours, range from 0 to 255"*.
- 256-colour and 24-bit SGR sequences are **parsed but quantised**, not honoured. `vc_t416_color()`
  (`vt.c` ~1652–1683) handles `38;5;n` ("256 colours", via `rgb_from_256()`) and `38;2;r;g;b`
  ("24 bit"), then calls `rgb_foreground()` / `rgb_background()`. `rgb_foreground()` reduces the RGB
  triple to **three hue bits plus a bold/normal intensity flag**; `rgb_background()` keeps only the
  top bit of each channel with the comment *"For backgrounds, err on the dark side"* — i.e. **8
  background colours**. The comment above `vc_t416_color()` states these modes "break the usual
  properties of SGR codes and thus need to be detected and ignored by hand", and subcommands 3/4
  (CMY/CMYK) are explicitly unsupported.
- Of the 16 attribute colours, the neutral greys are black, dark grey, light grey and white — **4
  luminance levels**, not the 16 assumed in the ticket comment. A block-character viewfinder can
  stretch that with glyph density (`░▒▓█`) and with half-blocks (`▀` gives two vertical samples per
  cell using fg+bg), but the underlying grey ramp is 4 levels deep.

**Image protocols: none. Sixel is structurally impossible.**

- Sixel is carried in a DCS (`ESC P`) sequence. `vt.c` parses DCS into state `ESdcs` (`vt.c:2201`,
  entered at `vt.c:2421`) and its handler is literally `case ESdcs: /* ESC P */ return;`
  (`vt.c:2784`) — the payload is discarded, silently. Kitty's protocol (APC) and OSC-based
  protocols meet the same fate (`case ESosc: return;`, `case ESpm: return;`).
- `Documentation/fb/fbcon.rst` describes no image facility at all; its only colour-related option is
  `fbcon=margin:<color>` for the unused screen border.
- Sixel and kitty graphics are terminal-*emulator* features, as the ticket comment assumed. Confirmed
  from source: on the bare VT they cannot exist.

**Cell grid**, for sizing a block viewfinder: Alpine's `linux-lts` config sets
`CONFIG_FONT_TER16x32=y` alongside the default 8×16 font. At 1024×768 that is **128×48 cells with
8×16**, or 64×24 with Terminus 16×32. With half-blocks, 128×96 luminance samples at 8×16 — which
matches the estimate in the ticket comment; it is the *colour depth* estimate that was too
optimistic.

---

## 8. Camera preview written directly to `/dev/fb0`

**Viable in principle, and it is a documented userspace API — but I could not confirm it is fast
enough from Python.**

What the kernel documents:

- `Documentation/fb/framebuffer.rst` §"Programmer's View of `/dev/fb*`": the device can be `read`,
  `written`, `lseek`'d and **`mmap`'d — "(the main usage)"**. Devices are `/dev/fb0`…`/dev/fb31`.
- `Documentation/fb/api.rst` documents the ioctls needed to do it correctly:
  `FBIOGET_VSCREENINFO` / `FBIOPUT_VSCREENINFO` returning `struct fb_var_screeninfo` with
  `bits_per_pixel`, `grayscale`, and the `red`/`green`/`blue`/`transp` bitfields that give the pixel
  packing. Applications "should call the `FBIOGET_VSCREENINFO` ioctl and modify only" the fields they
  need. All of this is reachable from Python with `fcntl.ioctl` + `struct` + `mmap`.
- To stop the framebuffer console drawing over the preview, the tty is put into graphics mode with
  `KDSETMODE`/`KD_GRAPHICS` — `drivers/tty/vt/vt_ioctl.c:376` (`case KDSETMODE:` → `vt_kdsetmode()`).
  Also an `fcntl.ioctl` call. No display server, no toolkit, no library.

What it requires from the kernel config (relevant to the boot-pipeline ticket):

- `CONFIG_FB=y` plus a driver. Alpine's `lts.x86_64.config` has `CONFIG_FB=y`, `CONFIG_FB_EFI=y`,
  `CONFIG_DRM_SIMPLEDRM=y`, `CONFIG_SYSFB_SIMPLEFB=y`, `CONFIG_FRAMEBUFFER_CONSOLE_DEFERRED_TAKEOVER=y`.
- For a real KMS driver, `/dev/fb0` exists only through `CONFIG_DRM_FBDEV_EMULATION`
  (`drivers/gpu/drm/clients/Kconfig`, `default FB`, help text: "this support also provides the linux
  console support on top of your modesetting driver").
- **UNCONFIRMED:** I could not verify `CONFIG_FB_DEVICE`, `CONFIG_VT`, `CONFIG_FRAMEBUFFER_CONSOLE`
  or `CONFIG_DRM_FBDEV_EMULATION` from Alpine's shipped config, because
  `main/linux-lts/lts.x86_64.config` is a **minimised** config (3163 `CONFIG_` lines, only 57
  "is not set" entries) where defaults are omitted. Since the appliance builds its own kernel, the
  Kconfig requirements above are what matters, not Alpine's defaults — but the ISO must assert them
  explicitly.

What is not settled:

- **UNCONFIRMED:** the frame rate a *pure-Python* fb0 preview sustains. Blitting a scaled 640×480
  greyscale frame into a 32-bpp framebuffer means expanding 1 byte to 4 per pixel; done per pixel in
  CPython this will be far too slow, and the viable shapes are slice/stride tricks
  (nearest-neighbour downscale via `frame[y*W:(y+1)*W:step]`, precomputed 256-entry byte tables) or
  a tiny native helper. For reference, the trivially sliceable operation
  (`frame[0::2]`, 1280×720 YUYV → Y) costs 0.39 ms, but expansion to RGBX is not a single slice.
  What would settle it: a 30-line prototype on the target hardware measuring blit ms/frame at the
  panel's resolution.
- **UNCONFIRMED:** I did not find a canonical, maintained pure-Python `/dev/fb0` camera-preview
  example to point at. The kernel docs above are sufficient to write one; treat "there are Python
  examples" as unverified.

If the blit turns out fast enough, this **is** a third UI-surface candidate for #3: text screens
owned by a TUI on the VT, and the viewfinder drawn straight to `/dev/fb0` on another VT switched to
`KD_GRAPHICS` — no display server, no toolkit, and a real greyscale preview instead of a 4-level
block approximation.

---

## Evidence index

- Alpine package data: `https://dl-cdn.alpinelinux.org/alpine/v3.24/{main,community}/x86_64/APKINDEX.tar.gz`
  (fetched 2026-08-24); `v3.24/testing/x86_64/` → HTTP 404.
- APKBUILDs: `https://gitlab.alpinelinux.org/alpine/aports/-/raw/3.24-stable/community/{zbar,zxing-cpp,opencv}/APKBUILD`,
  `…/main/linux-lts/{APKBUILD,lts.x86_64.config}`.
- Kernel `v6.18`: `drivers/tty/vt/vt.c`, `drivers/tty/vt/vt_ioctl.c`, `drivers/media/usb/uvc/*.c`,
  `drivers/gpu/drm/clients/Kconfig`, `drivers/video/fbdev/Kconfig`,
  `Documentation/fb/{framebuffer,api,fbcon}.rst`.
- Sparrow: `src/main/java/com/sparrowwallet/sparrow/control/{QRDisplayDialog,QRDensity}.java` (master).
- Seedsigner (`dev`): `src/seedsigner/hardware/camera.py`, `src/seedsigner/models/{decode_qr,encode_qr}.py`.
- Krux (`main`): `src/krux/{camera,qr}.py`, `src/krux/pages/qr_capture.py`.
- BC-UR: `BlockchainCommons/Research/papers/bcr-2020-005-ur.md` (and MUR, `bcr-2024-001`).
- PyPI JSON API for `linuxpy`, `v4l2py`, `v4l2-python3`, `pyv4l2`.
- Container check (Alpine 3.24.1, **arm64** — indicative only): `py3-zbar`, `py3-zxing-cpp`,
  `py3-qrcode`; `ldd /usr/lib/libzbar.so.0`; decode timings in item 6.
