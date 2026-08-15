# Tauri viability on a minimal image, and where QR decoding lives

Resolves [#5](https://github.com/allisson/aobs/issues/5). Map: [#1](https://github.com/allisson/aobs/issues/1).

## Verdict

**Tauri goes.** Replace it with **Slint** (`backend-linuxkms` + `renderer-software`), rendering
straight to KMS/DRM with no display server and no GPU driver.

**QR decoding lives in Rust**, not in the webview. Capture with the `v4l` crate (raw V4L2 ioctls),
decode with `rqrr` from the camera's luma plane.

Two findings carry the decision, and either one alone is close to sufficient:

1. **The webview costs 268 packages / 650 MiB where the replacement costs 22 packages / 21 MiB.**
   Measured, not estimated — method below. That closure includes Kerberos, LDAP, HTTP/3, RTMP,
   mDNS service discovery, CUPS printing, FireWire DV capture, a speech synthesiser and eleven
   audio/video codecs, on an appliance whose stated selling point is minimal attack surface and
   whose only data channel is a QR code.
2. **`getUserMedia` does not work in a stock Tauri app on Linux and cannot be made to work without
   forking wry.** WebKitGTK's `enable-media-stream` setting defaults to `FALSE` and neither wry nor
   Tauri ever sets it. So the "webview camera" option — the thing a webview was supposed to buy us —
   is not actually on the table.

Tauri is *not* rejected for the reason the ticket guessed. Offline behaviour is genuinely fine:
a production Tauri v2 app needs no loopback, no TCP, no DNS. That premise checked out. It fails on
footprint and on the camera.

---

## Method

All package numbers were produced by simulating installs against Debian 13.6 (trixie), amd64,
inside a `debian:trixie` container whose baseline is **78 packages** — close to what a debootstrap
minbase LiveCD starts from.

```sh
apt-get install -s --no-install-recommends <pkg>   # count "^Inst " lines
# installed size summed from Installed-Size in `apt-cache dumpavail`
```

Scripts used: `measure.sh`, `sizes.sh`, `probe.sh`, `probe2.sh` (run in-container; not committed —
the commands above reproduce them in three lines). Library-level facts were read out of the actual
Debian binaries with `objdump -p` and `strings`, not inferred from documentation.

---

## 1. Footprint, measured

Packages and installed size **added on top of the 78-package base**, Debian 13.6 amd64,
`--no-install-recommends` throughout.

| Stack | Packages | Installed size |
|---|---:|---:|
| `libwebkit2gtk-4.1-0` (runtime only) | **235** | **637 MiB** |
| `libwebkit2gtk-4.1-dev` (build) | 399 | 864 MiB |
| Tauri's documented build deps, in full ([prerequisites][tauri-prereq]) | 473 | 1205 MiB |
| **Tauri runtime + `cage` Wayland kiosk** | **268** | **650 MiB** |
| Tauri runtime + minimal Xorg | 257 | 662 MiB |
| iced/egui-style X11+GL client libs (no server) | 54 | 217 MiB |
| iced + `tiny-skia` under `cage` | 105 | 242 MiB |
| **Slint `linuxkms` + software renderer + fonts** | **22** | **21 MiB** |
| Slint `linuxkms` + software renderer, no fonts | 14 | 14 MiB |

Sub-totals, for where the weight sits:

| Component | Packages | Installed size |
|---|---:|---:|
| GTK 3 alone | 102 | 134 MiB |
| Mesa (`libgl1-mesa-dri`) | 31 | 200 MiB |
| GStreamer base + good | 131 | 136 MiB |
| minimal Xorg server | 77 | 256 MiB |
| `libsoup-3.0-0` (HTTP client) | 53 | 48 MiB |
| PipeWire | 57 | 49 MiB |
| xdg-desktop-portal + GTK backend | 191 | 227 MiB |

Two single shared objects account for 123 MiB of the webview total:

```
92M  /usr/lib/x86_64-linux-gnu/libwebkit2gtk-4.1.so.0.21.9
31M  /usr/lib/x86_64-linux-gnu/libjavascriptcoregtk-4.1.so.0.10.13
```

(`libwebkit2gtk-4.1-0` version 2.52.5-1~deb13u1.)

**Ratio: 12x the packages, 30x the disk.** Squashfs will compress the ISO, but it compresses both
sides; the package-count ratio is the honest measure of how much third-party C/C++ is inside the
trusted boundary.

Note also that `libwebkit2gtk-4.0-37` (the Tauri v1 ABI) **does not exist in trixie**. Tauri v1 is
not buildable on Debian 13 at all; 4.1/libsoup3 is the only option, which is the v1→v2 split
([Tauri v1 prerequisites][tauri-v1-prereq] list `libwebkit2gtk-4.0-dev`, [v2][tauri-prereq] list
`-4.1-dev`; [`libwebkit2gtk-4.1-dev`][deb-webkit-dev] depends on `libsoup-3.0-dev`).

## 2. What is actually inside that closure

The ticket asked how much of the webview footprint exists to talk to a network we are removing.
Verified present in the `libwebkit2gtk-4.1-0` dependency closure on trixie:

**Network and remote-auth code, on a machine with no network:**

| Package | Version | What it is |
|---|---|---|
| `libsoup-3.0-0` | 3.6.5-3 | HTTP client library |
| `libcurl3t64-gnutls` | 8.14.1-2+deb13u4 | HTTP/FTP/etc. client |
| `libnghttp2-14` | 1.64.0-1.1 | HTTP/2 |
| `libngtcp2-16` | 1.11.0-1 | QUIC / HTTP/3 |
| `librtmp1` | 2.4+…-2+b5 | RTMP streaming |
| `libssh2-1t64` | 1.11.1-1 | SSH |
| `libgssapi-krb5-2` | 1.21.3-5 | Kerberos |
| `libldap2` | 2.6.10 | LDAP |
| `libavahi-client3` | 0.8-16 | **mDNS/DNS-SD service discovery** |
| `libproxy1v5` | 0.5.9-1 | proxy autoconfiguration |
| `glib-networking` | 2.80.1-1 | TLS backend + proxy modules |
| `libcups2t64` | 2.4.10-3 | printing |

**Parsers reachable from content, i.e. from anything a hostile QR payload can influence:**

`libjxl0.11` (JPEG XL), `libavif16` + `libdav1d7` + `libaom3` + `librav1e0.7` + `libsvtav1enc2` +
`libgav1-1` (AV1), `libwebp7`/`libwebpdemux2`/`libwebpmux3`, `libvpx9`, `libtiff6`, `libjpeg62-turbo`,
`libpng16-16t64`, `libopus0`, `libvorbis0a`, `libtheora0`, `libmp3lame0`, `libmpg123-0t64`,
`libflac14`, `libwavpack1`, `libtwolame0`, `libspeex1`, `libopencore-amrnb0`/`-amrwb0`, `libtag2`,
`libsndfile1`, `libxml2`, `libxslt1.1`, plus WebKit's own built-in SVG engine (12 `SVGSVGElement`
string hits in the `.so`) and its own font shaping stack.

**Things whose presence on a signing appliance is simply hard to justify:**

`libraw1394-11` + `libavc1394-0` + `libiec61883-0` (FireWire DV camera capture),
`libcaca0` + `libaa1` (ASCII-art video output), `libflite1` (speech synthesis — 12 separate
`libflite_*` `NEEDED` entries in `libwebkit2gtk-4.1.so`), `libmanette-0.2-0` (**Gamepad API**),
`libhidapi-hidraw0` (**raw HID device access**), `libhunspell-1.7-0` + `libaspell15` + `libhyphen0`
(spellchecking and hyphenation), `libsecret-1-0` (keyring), `libcdparanoia0` (audio CD ripping).

The Gamepad and raw-HID entries deserve a sentence of their own: they are `NEEDED` entries of the
webview binary itself, meaning a browser engine on this appliance links code for enumerating and
reading arbitrary HID devices. Nothing in the product needs that.

None of this is WebKit being badly packaged. It is what a browser engine *is*. You cannot subset it.

## 3. Offline behaviour — Tauri passes this test

This is the part of the ticket where Tauri comes out clean, and it should be recorded as settled so
nobody re-litigates it.

**Production assets load over a custom URI scheme, not HTTP.** `crates/tauri/src/manager/mod.rs`:

```rust
pub(crate) fn tauri_protocol_url(&self, https: bool) -> Cow<'_, Url> {
  if cfg!(windows) || cfg!(target_os = "android") {
    let scheme = if https { "https" } else { "http" };
    Cow::Owned(Url::parse(&format!("{scheme}://tauri.localhost")).unwrap())
  } else {
    Cow::Owned(Url::parse("tauri://localhost").unwrap())
  }
}
```

The `http`/`https` scheme is Windows/Android only. `devUrl` is `#[cfg(dev)]`-gated. Registration is
`register_uri_scheme_protocol()` in `crates/tauri/src/manager/webview.rs`; the handler in
`crates/tauri/src/protocol/tauri.rs` reads from the in-binary asset store. wry does
`web_context.register_uri_scheme(&name, handler)` then `load_uri` — no listener anywhere
([wry `src/webkitgtk/mod.rs`][wry-webkitgtk]).

`tauri://localhost` is a **scheme name, not a hostname**; nothing resolves it. WebKit short-circuits
custom-scheme loads before the NetworkProcess is involved
(`Source/WebKit/WebProcess/Network/WebLoaderStrategy.cpp` hands off to
`urlSchemeHandlerForScheme(...)->startNewTask(...)` and returns).

Confirmed by contrapositive: [`tauri-plugin-localhost`][tauri-localhost] exists precisely to
"expose your apps assets through a localhost server **instead of** the default custom protocol",
and warns it "brings considerable security risks". Opt-in, not default. Don't add it.

**WebKit still forks a NetworkProcess** once storage/cookies/localStorage are touched
(`NetworkStorageManager` lives there), but all WebKit IPC on Unix is
`socketpair(AF_UNIX, SOCK_SEQPACKET, ...)` — a process cost, not a socket cost. No `AF_INET` in the
IPC path. The multi-process model is not optional: since 2.26 the only allowed process model is
`WEBKIT_PROCESS_MODEL_MULTIPLE_SECONDARY_PROCESSES` ([WebKitWebContext docs][webkit-context]).
The Debian package ships `WebKitNetworkProcess`, `WebKitWebProcess`, `WebKitGPUProcess`.

**DBus is a soft dependency**, needed only for theme detection (Tauri's `dbus` cargo feature is
default-on and disableable — [docs.rs/tauri feature list][tauri-features]: "Enables dbus dependency
for theme support on Linux"), tray, notifications, single-instance and a11y. Session bus, Unix
socket, not TCP.

**Verdict on offline: no blocker.** A production Tauri app runs with the network stack absent.

## 4. Attack surface

The ticket asks whether a browser engine matters when there is no network and no untrusted URL.
It matters, for three reasons that survive the "but it's offline" objection:

**Volume.** [Debian's security tracker for src:webkit2gtk][deb-sec-webkit] lists **719 unique CVEs,
48 of them currently open**. That is the historical rate of memory-safety bugs in the engine we
would be putting between hostile QR data and the seed.

**Debian "supports" it by rebasing, not backporting.** The [trixie release notes][deb-relnotes]
§5.2.3.1 say the "high rate of vulnerabilities and partial lack of upstream support in the form of
long term branches make it very difficult to support these browsers and engines with backported
security fixes", while confirming `webkit2gtk` *is* covered. The mechanism is visible in the
tracker's own version list: bookworm carries 2.50.6, trixie 2.52.x — far past what those releases
shipped with. For a signed, hash-published appliance ISO, that means every security update is an
**engine version bump** with the behavioural-change risk that implies. It is the opposite of the
stable, auditable base a signing appliance wants, and it directly antagonises the v2 reproducible-
build goal.

**The parsers are reachable.** Yes, there is no network and no untrusted URL. But QR payloads are
untrusted input by definition (see the map's threat model: "hostile data arriving over the QR
channel (parser attacks)"), and once a PSBT-derived string reaches the DOM, everything WebKit
parses is in scope — the SVG engine, the font stack, the image decoders, `libxml2`, `libxslt`,
JavaScriptCore's JIT. On the Slint path, the app's total content-parsing surface is: the PSBT
parser and the QR decoder, both pure Rust, both ours to fuzz to the map's 98% bar. Slint's image
decoders are behind an **optional** `image-decoders` cargo feature we simply do not enable
([Image docs][slint-image]) — the GUI parses nothing.

The honest counter-argument is that a webview's sandbox (bubblewrap + seccomp) is stronger than a
single-process Rust binary's. It does not hold here: WebKit's sandbox is opt-in via
`webkit_web_context_set_sandbox_enabled` and **wry never calls it**. We would ship an unsandboxed
browser engine.

## 5. Camera path — the webview option does not exist

Four gates sit between a Tauri app and a camera frame. Three are fine. The fourth is fatal.

| Gate | Status |
|---|---|
| Compile-time `ENABLE_MEDIA_STREAM` | **OK.** `Source/cmake/OptionsGTK.cmake` sets `WEBKIT_OPTION_DEFAULT_PORT_VALUE(ENABLE_MEDIA_STREAM PRIVATE ON)`, and [Debian's `debian/rules`][deb-webkit-src] overrides nothing. Confirmed empirically: `getUserMedia` (4), `getDisplayMedia` (5), `MediaStreamTrack` (45) string hits in the shipped `.so`. |
| Secure context (`MediaDevices.idl` is `SecureContext`) | **OK.** wry calls `security_manager().register_uri_scheme_as_secure(name)`, so `tauri://localhost` is a secure origin. |
| PipeWire / portals | **Not needed for a camera.** PipeWire is required for `getDisplayMedia` screen capture only. Camera enumeration goes through a generic `GstDeviceMonitor` on `"Video/Source"` (`GStreamerCaptureDeviceManager.cpp`); `Video/Source` and `pipewiresrc` are both present as strings in the `.so`, and `libgstvideo4linux2.so` ships in `gstreamer1.0-plugins-good`, which is already a hard dependency of `libwebkit2gtk-4.1-0`. So the v4l2 path exists — saving us the 191-package portals stack and the 57-package PipeWire stack. |
| **Runtime `WebKitSettings:enable-media-stream`** | **FATAL. Defaults to `FALSE`** ([property docs][webkit-mediastream], since 2.4), and **neither wry nor Tauri ever sets it.** wry's settings block touches only `set_enable_webgl`, `set_enable_webaudio`, `set_enable_back_forward_navigation_gestures`, `set_javascript_can_access_clipboard`, `set_enable_page_cache`, `set_user_agent`, `set_enable_developer_extras`, `set_enable_javascript`. A code search for `enable_media_stream` across `org:tauri-apps` returns hits only in the generated `webkit2gtk-rs` bindings — zero in wry, zero in tauri. See [tauri#8346][tauri-8346], [wry#85][wry-85], [tauri discussion 8426][tauri-8426]. |

So "just use `getUserMedia`" means: fork wry, patch in `settings.set_enable_media_stream(true)`,
and carry that fork for the life of the project — in exchange for pushing camera frames through
GStreamer and a JS `MediaStream` before decoding them in JavaScript or shuttling them back over IPC
to Rust.

**Recommendation: capture and decode in Rust. Do not use `getUserMedia`.**

Even if wry set the flag tomorrow, Rust-side capture is the right answer, because it puts the trust
boundary where the threat model wants it. Hostile QR data hits a small pure-Rust decoder we own and
can fuzz, instead of a browser media pipeline we cannot subset.

### The Rust path, concretely

**Capture: the `v4l` crate**, not `nokhwa`.

- `v4l` 0.14.0, MIT ([crates.io][crates-v4l]). Its **default features are `v4l2` + `v4l2-sys`** —
  raw kernel `videodev2.h` ioctls on `/dev/video*`. The `libv4l` backend is opt-in
  ([README][v4l-readme]: "`v4l2-sys`: Use only the Linux kernel provided v4l2 API provided by
  videodev2.h"). **Runtime cost on the image: zero packages.** No `libv4l-0`, no `libv4lconvert0`.
  Build-time it needs libclang + kernel headers for bindgen (`v4l2-sys/build.rs` emits no
  `cargo:rustc-link-lib`), which is a build-container concern, not an ISO concern.
- `nokhwa` 0.10.11 goes through the same `v4l` + `v4l2-sys-mit` crates underneath
  ([deps][crates-nokhwa-bindings]) but wraps them in `image ^0.25`, `flume`, `paste`, and a default
  `decoding` feature whose mjpeg path can pull **`mozjpeg`, a C library built from source**. For
  one fixed camera on one fixed platform, `nokhwa`'s cross-platform abstraction is pure cost.
- **Request `GREY` or `YUYV`, never `MJPG`.** Most USB webcams default to MJPEG; accepting that
  default puts a JPEG decoder directly on the hostile-input path for no benefit. QR decoding wants
  luminance only, and `rqrr` takes luminance directly. This is a security requirement, not a
  preference.

**Decode: `rqrr`**, not `bardecoder`.

| | `rqrr` | `bardecoder` |
|---|---|---|
| Version / date | 0.10.1, 2026-01-27 ([crates.io][crates-rqrr]) | 0.5.0, **2023-07-29** ([crates.io][crates-bardecoder]) |
| Last commit | 2026-05-18 | 2024-02-13, message: *"Updated dependencies in 'How to use' section, current ones are not working."* |
| Licence | `(MIT OR Apache-2.0) AND ISC` | MIT |
| Dependencies | 3: `g2p`, `lru`, **`image` optional** | 5: `anyhow`, **`image ^0.24` mandatory**, `log`, `newtype_derive`, `thiserror` |
| Raw buffer input | **Yes** | No — public API is the `image` crate's types |
| C code | None (reimplementation of quirc, not an FFI binding) | None |

`rqrr`'s [`PreparedImage::prepare_from_greyscale(w, h, fill)`][rqrr-prepared] takes a closure —
"The values returned by the function are interpreted as luminance" — so a V4L2 YUYV or GREY frame
is fed by indexing the luma plane, with no intermediate allocation and no `image` dependency at all.
`bardecoder` is stale, pins `image ^0.24` (two majors behind), and would fight anything else in the
tree over that version.

Neither crate says anything about structured-append, BBQr, or UR/BC-UR. Multi-frame reassembly is
ours to write regardless of which decoder we pick — which is another argument for the one with the
smaller surface underneath it.

**Not researched here:** the QR *encoder* for the outbound direction. `qrcode` and `fast_qr` are the
obvious candidates; that belongs with the QR transport format ticket, not this one.

## 6. The replacement: Slint

Compared on the criterion that actually matters for this appliance — what has to be on the image.

| | Runs with no X11/Wayland? | Runs with no GPU? | Licence | Added packages |
|---|---|---|---|---:|
| **Slint** `backend-linuxkms` + `renderer-software` | **Yes** | **Yes** | GPL-3.0-only OR Slint Royalty-free 2.0 OR commercial | **22** |
| iced 0.14 + `tiny-skia` | No — X11 or Wayland only | Yes | MIT | 105 |
| egui/eframe 0.36 | No | **No** — glow (GL) or wgpu only | MIT OR Apache-2.0 | 54 + display server |
| Tauri / webkit2gtk | No | No | — | 268 |

Slint is the only one of the three that documents running on bare KMS/DRM. From the
[backends table][slint-backends]: the `linuxkms` backend uses "Linux's KMS/DRI infrastructure … **No
windowing system or compositor is required**". The [renderers table][slint-backends] lists the
Software renderer's GPU requirement as "No GPU", described as "Runs anywhere, highly portable, and
lightweight". The [LinuxKMS page][slint-linuxkms] confirms "DRM dumb buffers are used for software
rendering", with input via libinput/libudev and device access via libseat.

egui is the worst fit: it needs a display server *and* a GL implementation, meaning Xorg or a
compositor plus Mesa's 200 MiB llvmpipe just to fake a GL context. iced with
`default-features = false, features = ["tiny-skia"]` drops the GPU requirement but not the display
server — `iced_winit` has X11 and Wayland backends and no KMS one.

The measured 22 packages for the Slint path are exactly:

```
libinput10 libinput-bin libevdev2 libmtdev1t64 libudev1(base) libwacom9 libwacom-common
libgudev-1.0-0 libglib2.0-0t64 libffi8 libatomic1 libxkbcommon0 xkb-data libseat1 seatd
libfreetype6 libfontconfig1 fontconfig-config libpng16-16t64 libbrotli1 libexpat1
fonts-dejavu-core fonts-dejavu-mono
```

Input handling, keymaps, seat management, and font rendering. That is the whole GUI stack. No HTTP
client, no TLS, no Kerberos, no codecs, no JIT, no SVG, no Mesa, no X server.

### Slint's cost, stated plainly

**The licence is the real trade-off, and it needs a decision.** Slint is
`GPL-3.0-only OR LicenseRef-Slint-Royalty-free-2.0 OR LicenseRef-Slint-Software-3.0`
([crates.io][crates-slint]). This repo is currently MIT.

- The **royalty-free licence** is free of charge for "Desktop, Mobile, or Web" applications but
  requires displaying the `AboutSlint` widget (or a download-page badge), and **excludes embedded
  systems**. Whether a bootable amd64 appliance ISO is a "Desktop Application" or an "embedded
  system" is genuinely ambiguous, and ambiguity in a licence is not a thing to ship on.
- The **GPL-3.0 option** is unambiguous and free, at the price of the whole appliance being
  GPL-3.0.

**Recommendation: take GPL-3.0 and relicense the repo.** Reasoning: the appliance is distributed as
a signed ISO whose entire value proposition is that users can audit what they are booting, so
copyleft is aligned rather than costly; it is the licence comparable open signing devices ship
under; and it removes an ambiguity that would otherwise sit unresolved under a security product.
The alternative — keeping MIT — costs 83 extra packages and 221 extra MiB for iced + `tiny-skia`
under `cage`, and still leaves a Wayland compositor and Mesa on the image.

**Also given up, honestly:**

- **UI development is slower.** No HTML/CSS, no browser devtools, no hot reload against a familiar
  stack. Slint has its own `.slint` markup and a live preview, but the ecosystem is smaller.
- **`linuxkms` is a non-default backend.** It is documented and supported, but it is a less-trodden
  path than winit, so expect to hit rough edges on specific hardware. This bears directly on the
  map's open "hardware compatibility floor" question, which now needs a KMS/DRM answer rather than
  an X11 one.
- **No mouse cursor with the software renderer** ([LinuxKMS page][slint-linuxkms] caveat). Irrelevant
  here — the map already fixes input as "the physical keyboard … for seed import and passphrase
  entry only", plus the camera. But it does mean the UI must be fully keyboard-navigable by design,
  not as a retrofit.
- **A rendering bug is now in our process.** Without WebKit we lose its (unused, since wry never
  enables it) sandbox. The mitigation is that the total parsing surface shrinks from a browser
  engine to two small pure-Rust parsers we can fuzz — which is the trade the map's 98% coverage bar
  for critical components was written to make possible.

---

## Consequences for the map

- **Stack constraint changes.** The map's settled constraint reads "Tauri + Rust on a minimal Debian
  LiveCD". It becomes **"Slint + Rust"**. This is the premise-invalidation the ticket was run early
  to catch.
- **Boot layer gets simpler.** No X server, no Wayland compositor, no display manager. The ISO boots
  to a single Rust binary holding the DRM master on tty1. This should feed the LiveCD ticket.
- **Licence decision is open** and blocks nothing immediately, but should be closed before code
  lands: GPL-3.0 (recommended) vs. staying MIT with iced.
- **Hardware compatibility floor** is now a KMS/DRM question (`i915`/`amdgpu`/`nouveau`/`simpledrm`
  availability in the kernel we ship) plus a V4L2 UVC question, not an X11 driver question.
- **Fuzzing targets are now concrete**: the `rqrr` frame decoder wrapper, the multi-frame QR
  reassembler, and the PSBT parser. Those three are the entire untrusted-input surface.

---

## Sources

[tauri-prereq]: https://v2.tauri.app/start/prerequisites/
[tauri-v1-prereq]: https://v1.tauri.app/v1/guides/getting-started/prerequisites/
[tauri-localhost]: https://github.com/tauri-apps/plugins-workspace/blob/v2/plugins/localhost/README.md
[tauri-features]: https://docs.rs/tauri/latest/tauri/
[tauri-8346]: https://github.com/tauri-apps/tauri/issues/8346
[tauri-8426]: https://github.com/orgs/tauri-apps/discussions/8426
[wry-webkitgtk]: https://github.com/tauri-apps/wry/blob/dev/src/webkitgtk/mod.rs
[wry-85]: https://github.com/tauri-apps/wry/issues/85
[deb-webkit-dev]: https://packages.debian.org/trixie/libwebkit2gtk-4.1-dev
[deb-webkit-src]: https://sources.debian.org/src/webkit2gtk/latest/debian/rules/
[deb-sec-webkit]: https://security-tracker.debian.org/tracker/source-package/webkit2gtk
[deb-relnotes]: https://www.debian.org/releases/trixie/release-notes/issues.en.html
[webkit-context]: https://webkitgtk.org/reference/webkit2gtk/stable/class.WebContext.html
[webkit-mediastream]: https://webkitgtk.org/reference/webkit2gtk/stable/property.Settings.enable-media-stream.html
[slint-backends]: https://docs.slint.dev/latest/docs/slint/guide/backends-and-renderers/backends_and_renderers/
[slint-linuxkms]: https://docs.slint.dev/latest/docs/slint/guide/backends-and-renderers/backend_linuxkms/
[slint-image]: https://docs.rs/slint/latest/slint/struct.Image.html
[crates-slint]: https://crates.io/crates/slint
[crates-v4l]: https://crates.io/crates/v4l
[v4l-readme]: https://github.com/raymanfx/libv4l-rs/blob/master/README.md
[crates-nokhwa-bindings]: https://crates.io/crates/nokhwa-bindings-linux
[crates-rqrr]: https://crates.io/crates/rqrr
[crates-bardecoder]: https://crates.io/crates/bardecoder
[rqrr-prepared]: https://docs.rs/rqrr/latest/rqrr/struct.PreparedImage.html

- Tauri v2 Linux prerequisites — <https://v2.tauri.app/start/prerequisites/>
- Tauri v1 prerequisites (4.0 vs 4.1 split) — <https://v1.tauri.app/v1/guides/getting-started/prerequisites/>
- Tauri Debian distribution notes — <https://v2.tauri.app/distribute/debian/>
- Tauri source, `crates/tauri/src/manager/mod.rs`, `manager/webview.rs`, `protocol/tauri.rs` — <https://github.com/tauri-apps/tauri>
- Tauri cargo features (`dbus`) — <https://docs.rs/tauri/latest/tauri/>
- `tauri-plugin-localhost` README — <https://github.com/tauri-apps/plugins-workspace/blob/v2/plugins/localhost/README.md>
- wry `src/webkitgtk/mod.rs`, `src/webkitgtk/web_context.rs` — <https://github.com/tauri-apps/wry>
- tauri#8346, wry#85, tauri-apps discussion 8426 (getUserMedia on Linux)
- WebKitGTK `WebKitWebContext` process model — <https://webkitgtk.org/reference/webkit2gtk/stable/class.WebContext.html>
- WebKitGTK `enable-media-stream` property (default FALSE) — <https://webkitgtk.org/reference/webkit2gtk/stable/property.Settings.enable-media-stream.html>
- WebKit source: `Source/cmake/OptionsGTK.cmake`, `Source/cmake/WebKitFeatures.cmake`, `Source/WebKit/WebProcess/Network/WebLoaderStrategy.cpp`, `Source/WebCore/Modules/mediastream/MediaDevices.idl`, `Source/WebCore/platform/mediastream/gstreamer/GStreamerCaptureDeviceManager.cpp`
- Debian `libwebkit2gtk-4.1-dev` package page — <https://packages.debian.org/trixie/libwebkit2gtk-4.1-dev>
- Debian `webkit2gtk` source `debian/control`, `debian/rules` — <https://sources.debian.org/src/webkit2gtk/latest/>
- Debian security tracker, src:webkit2gtk (719 CVEs, 48 open) — <https://security-tracker.debian.org/tracker/source-package/webkit2gtk>
- Debian 13 release notes, limitations in security support — <https://www.debian.org/releases/trixie/release-notes/issues.en.html>
- Slint backends and renderers — <https://docs.slint.dev/latest/docs/slint/guide/backends-and-renderers/backends_and_renderers/>
- Slint LinuxKMS backend — <https://docs.slint.dev/latest/docs/slint/guide/backends-and-renderers/backend_linuxkms/>
- Slint `Image` API — <https://docs.rs/slint/latest/slint/struct.Image.html>
- Slint royalty-free licence — <https://github.com/slint-ui/slint/blob/master/LICENSES/LicenseRef-Slint-Royalty-free-2.0.md>
- eframe README (Linux deps, wgpu/glow) — <https://github.com/emilk/egui/blob/master/crates/eframe/README.md>
- iced README and `Cargo.toml` (tiny-skia, x11/wayland features) — <https://github.com/iced-rs/iced>
- `v4l` crate and README (v4l2-sys vs libv4l-sys) — <https://crates.io/crates/v4l>, <https://github.com/raymanfx/libv4l-rs>
- `nokhwa` and `nokhwa-bindings-linux` — <https://crates.io/crates/nokhwa>, <https://docs.rs/nokhwa>
- `rqrr` — <https://crates.io/crates/rqrr>, <https://docs.rs/rqrr/latest/rqrr/struct.PreparedImage.html>
- `bardecoder` — <https://crates.io/crates/bardecoder>, <https://github.com/piderman314/bardecoder>
</content>
