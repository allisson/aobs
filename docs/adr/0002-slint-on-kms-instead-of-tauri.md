# ADR-0002 — Slint rendering to KMS/DRM, not Tauri, and QR decoding in Rust

- **Status**: accepted
- **Date**: 2026-08-15
- **Decides**: [#5 — Tauri viability on a minimal image, and where QR decoding lives](https://github.com/allisson/aobs/issues/5)
- **Findings**: `docs/research/05-tauri-viability.md`

## Context

Tauri + Rust was the project's starting premise. The viability ticket was run early precisely
because it could invalidate that premise, and it did.

Tauri on Linux means WebKitGTK. Measured by simulating installs on Debian 13.6 amd64 against a
78-package baseline:

| Stack | Packages | Installed size |
|---|---:|---:|
| Tauri runtime + `cage` kiosk compositor | **268** | **650 MiB** |
| Tauri's documented build deps, in full | 473 | 1205 MiB |
| iced + `tiny-skia` under `cage` | 105 | 242 MiB |
| **Slint `linuxkms` + software renderer + fonts** | **22** | **21 MiB** |

Verified present in the webkit closure on a machine with no network: mDNS service discovery,
Kerberos, LDAP, QUIC/HTTP-3, CUPS printing, raw HID access, the Gamepad API, FireWire DV capture, a
speech synthesiser, and ~20 image/audio/video decoders. None of that is bad packaging — it is what a
browser engine *is*, and it cannot be subset. Debian's tracker records 719 unique CVEs against
`src:webkit2gtk`, and WebKit's bubblewrap sandbox is opt-in via a call **wry never makes**.

The dispositive finding was the camera, not the size. `getUserMedia` clears three of four gates in a
stock Tauri app on Linux and fails the fourth: **`WebKitSettings:enable-media-stream` defaults to
`FALSE`, and neither wry nor tauri ever sets it.** The webview camera path costs a permanent wry
fork.

Two things checked out clean and are recorded so they are not re-litigated. **Offline behaviour was
the guessed risk and Tauri passes it**: a production build serves the frontend over the
`tauri://localhost` custom URI scheme with embedded assets — no loopback, no TCP, no DNS. And
WebKit's multi-process IPC is `socketpair(AF_UNIX)`, a process cost rather than a socket.

## Decision

**Slint on `backend-linuxkms` + `renderer-software`**, rendering straight to KMS/DRM. No X server,
no Wayland compositor, no display manager, no GPU driver requirement.

**QR decoding lives in Rust**: capture with the `v4l` crate (raw V4L2 ioctls, no `libv4l` on the
image), decode with `rqrr` via `PreparedImage::prepare_from_greyscale`, fed directly from the
frame's luma plane.

## Consequences

- The ISO boots to a single Rust binary holding DRM master on tty1. The boot layer gets
  substantially simpler.
- **The app's entire content-parsing surface becomes the PSBT parser and the QR decoder**, both pure
  Rust and both ours to fuzz. Slint's image decoders sit behind an optional cargo feature we do not
  enable, so the GUI parses nothing untrusted.
- The hardware floor becomes a KMS/DRM question plus a V4L2 UVC question, not an X11 driver question
  — which is what later made UEFI-only (ADR-0009) both possible and decisive.
- **The UI must be fully keyboard-navigable by design**: the software renderer draws no mouse cursor.
- Two operational rules ride along: **request `GREY` or `YUYV` from the camera, never `MJPG`**, since
  MJPEG would put a JPEG decoder on the hostile-input path for no benefit; and prefer `v4l` directly
  over `nokhwa`, whose default `decoding` feature can pull `mozjpeg`, a C library built from source.
- It forced the licence question, resolved in ADR-0001.

**Cost, stated plainly:** UI development is slower — no HTML/CSS, no browser devtools, a smaller
ecosystem — and `linuxkms` is a documented but non-default Slint backend, so expect rough edges on
specific hardware.

## Alternatives rejected

- **Tauri** — 12× the packages, 30× the disk, an unsandboxed browser engine, and a camera path that
  needs a permanent wry fork.
- **iced + `tiny-skia`** — +83 packages over Slint and, decisively, `iced_winit` has **no KMS
  backend**, so it puts a Wayland compositor back on the image.
- **egui** — needs a display server *and* a GL implementation.
- **`bardecoder` instead of `rqrr`** — last released 2023, mandates `image ^0.24`, no raw-buffer
  entry point.
