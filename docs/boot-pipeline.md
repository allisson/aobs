# Boot pipeline

How `bitcoin-signer-amd64.iso` is built, what it contains, and what happens between power-on and the
first screen.

Release engineering — the reproducibility contract, the input archive, signing keys, the release
ritual — is `docs/reproducible-build.md`, `docs/release.md` and `SECURITY.md`. This document is how
the image is built and what happens between power-on and the first screen, written precisely enough
that building it is mechanical.

**Where each decision below now lives**, since a decision readable only in a diff is invisible to
the next session:

| | |
|---|---|
| the kernel, as one reviewable file | `build/kernel.config` |
| PID 1 | `build/init` |
| the four stages | `build/mkiso.sh`, `build/Dockerfile.iso` |
| the fixed cmdline, per firmware path | `build/isolinux.cfg`, `build/grub.cfg` |
| every build-time assertion, as pure functions | `build/verify.py` |
| the assertions that cannot be pure — one signature in each scheme, in the built rootfs | `build/assert_in_rootfs.py` |
| each assertion fed a deliberately broken input | `tests/test_build_verifier.py` |

Two things in this document are implemented differently from the letter of it, both narrowed rather
than widened, and both written down where they happen:

- **PID 1 sets the keymap but not the font.** There is no font file in the image to load: the
  kernel's built-in 8×16 font is already the one #3's exact-1:2 cell requirement asks for, which is
  the same reason `font-terminus` is dropped below.
- **The BIP86 assertion signs and verifies rather than comparing bytes.** A BIP340 signature is not
  required to be byte-stable — any valid nonce yields a valid signature, and implementations
  measurably disagree on the one they pick — so a pinned Schnorr vector would assert something
  BIP340 never promised and fail against a perfectly good library. Verification proves what the
  check is for: that the `schnorrsig`/`xonly`/`keypair` symbols bound at all. The BIP84 ECDSA half
  *is* compared byte for byte, because RFC6979 plus embit's low-R grinding makes it deterministic.
  `PublicKey.schnorr_verify` is not what verifies — see below for why it must never be called.

Almost every constraint here arrives from a closed ticket rather than being chosen freshly:
[#2](https://github.com/allisson/aobs/issues/2) (no network stack),
[#3](https://github.com/allisson/aobs/issues/3) (framebuffer TUI, 85×43 characters),
[#6](https://github.com/allisson/aobs/issues/6) (V4L2 + zxing-cpp),
[#8](https://github.com/allisson/aobs/issues/8) (kernel RNG trust),
[#10](https://github.com/allisson/aobs/issues/10) (whole system in the initramfs),
[#14](https://github.com/allisson/aobs/issues/14) (exactly two USB class drivers).

## The shape is already fixed, and it forecloses Alpine's tooling

The appliance runs entirely from an initramfs, on a kernel with no networking, no block or storage
drivers, no loadable modules, and exactly two USB class drivers.

**No stock Alpine kernel satisfies that**, so `linux-lts` cannot be used — and with it go
`mkimage.sh`, the aports ISO profiles and `mkinitfs`, whose whole purpose is producing and mounting a
**modloop** squashfs of the modules an all-built-in kernel does not have.

Alpine's remaining role is what it is genuinely good at: **a pinned, checksummed source of a musl
userland.** It supplies packages, not a boot process.

## Build

A checked-in build script running in an `alpine:3.24` container. Four stages:

1. **Userland.** `apk --root /rootfs --initdb` against a pinned repository file, installing exact
   package versions.
2. **Kernel.** A vanilla kernel.org LTS tarball, pinned by version and SHA-256, built against a
   `.config` checked into this repo.
3. **Initramfs.** `find /rootfs | cpio -H newc | zstd`.
4. **Image.** `xorriso` into a hybrid ISO: `isolinux` for legacy BIOS, `grub-efi` for UEFI.

Every input is a pinned version with a checksum, no step needs Alpine's release machinery, and
every byte comes from `build/inputs/` over no network at all. The output is **byte-identical on any
host**: `docs/reproducible-build.md` states that claim numbered and checkable, lists the six
divergence sources that were fixed, and names the CI guard that fails on any differing byte.

Stage 1 also writes **`/etc/aobs-release`** — the version, the commit, the formatted build date and
whether the tree was dirty. It is a stage-1 output specifically so that stage 3, before `cpio`, can
assert it against `git describe --exact-match --tags` while it is still a file a human can open. What
the appliance does with it is the footer row below.

### Why vanilla kernel source, not Alpine's APKBUILD

The config is replaced wholesale, so Alpine's would be scaffolding around something we discard — and
its APKBUILD exists to emit a `-modules` package this appliance must not have.

The decisive reason is verification. #14 and #10 both promise claims checkable *by reading the kernel
config*: exactly two USB class drivers, no block driver, no networking. That is only checkable if the
config is **one reviewable file in this repo**, not a fragment merged into a distribution's config at
build time.

## Boot sequence

Firmware loads kernel + initramfs. After that the boot medium is never read again and can be pulled
(#10).

Kernel cmdline, fixed in the bootloader config:

- `random.trust_cpu=off random.trust_bootloader=off` — #8; both default on, and leaving them there
  would rest the entropy floor claim on RDRAND.
- `vga=791` on the BIOS path — see *Console* below.
- `panic=0` — hang rather than reboot. There is nothing to reboot into, and a reboot loop flashes the
  failure past the user.

**PID 1 is a short POSIX shell script that ends in `exec python3 -m aobs`,** so the app itself is
PID 1 for the session. There is no init system, no OpenRC, no `inittab`, no getty, no VT switching.
The script does only what nothing else can:

1. Mount `proc`, `sys`, `dev`, `devpts`, `shm` — tmpfs and pseudo-filesystems only.
2. Set the console font and keymap.
3. **Flip `authorized_default=0` on every root hub** (#14) — after our own devices enumerate, before
   the first secret is entered.
4. Check available RAM against the floor and refuse to start below it (#10).
5. `exec` the app.

### Containment, stated so it can be checked

**There is no getty, no VT with a login, and no path from the running app to a prompt.** If the app
exits, the kernel panics on init death rather than dropping to a shell. `CONFIG_MAGIC_SYSRQ=n`;
Ctrl+Alt+Del is disabled.

**Busybox `sh` is present in the image, and that is not a hole worth closing.** "No shell on the
appliance" would be a claim that protects nobody — Python is in the image and can `os.execv`
anything. Writing PID 1 in Python instead would put `ctypes`-wrapped `mount(2)` calls in the one
process that cannot be restarted and is hardest to test. The claim above is the true one.

**Not defended: a person at the bootloader typing `init=/bin/sh`.** Stated rather than papered over,
and it costs nothing — a fresh boot holds no secrets, which is the point of the amnesia claim.

## Console

**`fbcon` over firmware framebuffers only** — `simpledrm`/`efifb` on UEFI, `vesafb` on BIOS. **No DRM
GPU drivers**: they are large and several need firmware blobs, which an all-built-in no-modules kernel
would have to carry and load. Resolution is whatever firmware provides.

**Legacy BIOS needs `vga=791`, and this is not cosmetic.** `vgacon` gives 80×25 text, and #3 fixed
the QR at **85 columns × 43 rows** — so a BIOS boot in text mode could not display a QR code at all.
With `vga=791` (1024×768) `vesafb` provides a graphical framebuffer and `fbcon` gives 128×48.

**1024×768 is therefore the resolution floor on both firmware paths**, which is what #3 left open.

`CONFIG_FB_DEVICE=y` is set: it is independent of fbcon and is what creates `/dev/fb0`, needed only if
#3's framebuffer-viewfinder escape hatch is ever taken.

#### The release identity footer

The picker carries **one reserved row** at the bottom, and a second line pointing at the advisories:

```
aobs v0.1.0 · 4f1c8a6e2b90 · 2026-09-14
Advisories are published at github.com/allisson/aobs/blob/main/ADVISORIES.txt — this appliance cannot check.
```

Here rather than on an About screen because **a screen you must navigate to is a screen nobody
visits**, and this is meant to reach someone who booted a stick found in a drawer and did not think
to look. The same row is repeated by every failure screen, because a bug report carrying no build
identity is a bug report about nothing.

The **12-hex commit prefix** is what makes the row worth showing: a version alone cannot distinguish
a rebuild from the published build, while the prefix can be matched against a manifest the user has
already verified.

**It identifies, it does not attest.** A modified image can print anything, and the README says so in
those words. Nothing derived from the image can be embedded in it — not the ISO hash, not the manifest
hash, and not the initramfs hash either, since the initramfs *is* the whole system — so version,
commit and `SOURCE_DATE_EPOCH` are the complete embeddable set.

A build that is not at a clean tag shows `DEVELOPMENT BUILD` in place of the version, never a
version-shaped string, plus a `-dirty` suffix on the commit when the tree was not clean. The stage-3
assertion is **skipped for those, not faked.**

### Keyboard layout

**A small set of Latin keymaps ships, with a picker as the first screen, defaulting to US.**

Not US-only. BIP39 words and the EFF export words are `a–z` and survive almost any Latin layout, but
**the BIP39 passphrase is arbitrary text**. A user on AZERTY or ABNT2 who types a passphrase through a
US map creates a wallet they can never reopen — no error, no signal, discovered when the funds are
gone. That is the worst failure mode in the appliance, and a few hundred KB of keymaps avoids it.

The picker is also where the map is proven right: **echo keys as typed, before any secret is entered.**

## Dependencies

**apk for everything Alpine packages; vendored source in the app tree for the two it does not. No
pip, no virtualenv, no wheel fetched at build time.**

| source | packages |
|---|---|
| apk | `python3`, `py3-zxing-cpp`, `py3-textual`, `py3-rich`, `py3-cryptography`, `py3-argon2-cffi`, `py3-qrcode`, `libsecp256k1` |
| vendored | **`embit`** (not packaged in Alpine), **`ur2`** (SeedSigner's stdlib-only implementation, #4) |

Vendoring exactly two pure-Python libraries, checked in where they can be read, beats introducing pip
and a dependency resolver into a build whose entire selling point is that every input is pinned.

`py3-segno` does not exist in Alpine, which is why `py3-qrcode` is the encoder.

### The elliptic curve implementation

**Every EC operation on the appliance — key derivation, ECDSA signing, Schnorr signing, address
proof — is performed by Alpine's `libsecp256k1`, and never by embit's pure-Python fallback.** This is
recorded here because it was previously unstated, and because embit does not have one EC
implementation: `embit/util/secp256k1.py` picks between a ctypes binding and `py_secp256k1` inside a
bare `except:`, with no message either way.

Two things make that pick go the right way, and both are load-bearing:

- **The apk, not embit's prebuilt.** embit's wheel ships a `libsecp256k1_linux_x86_64.so` that is
  glibc-linked; on musl it cannot relocate (`__memcpy_chk` is a `_FORTIFY_SOURCE` symbol musl lacks)
  and the bare `except:` silently selects the Python fallback. `gcompat` does not fix this — it does
  not export that symbol either. Alpine's `libsecp256k1` is built from the upstream
  `bitcoin-core/secp256k1` release with `--enable-module-schnorrsig --enable-module-extrakeys`
  (plus `ecdh` and `recovery`), which is what BIP86 needs.
- **`embit` is vendored from a tagged git commit, pinned by full SHA — not from the PyPI wheel.** The
  prebuilt blob exists in no commit of embit's repository: `MANIFEST.in` prunes
  `src/embit/util/prebuilt`, and the `.so` is produced at wheel-build time. Vendoring from source
  means `util/prebuilt/` never enters the app tree at all, rather than entering it and being deleted
  — and it makes this document's "checked in where they can be read" true of embit without
  exception. It matters that the directory stay absent: `_find_library()` returns the prebuilt path
  whenever the file merely *exists*, and does not fall through when *loading* it fails.

**The pin has an upper bound, and it is not cosmetic.** embit binds the schnorr module through the
deprecated alias `secp256k1_schnorrsig_sign`, which upstream renamed to `secp256k1_schnorrsig_sign32`
in 0.5.0's line and **removed outright in 0.8.0**. Against a 0.8.0 or newer library, embit's
`except: pass` binds nothing, the backend still reports as native, and BIP86 signing fails at the
moment a user tries to sign a taproot input. Alpine v3.24's `0.5.0-r1` still carries the alias.
**A routine Alpine bump past 0.8.0 therefore breaks taproot signing silently**, and the signature
assertion below is the only thing that catches it. This was observed, not reasoned about: a
Homebrew `libsecp256k1` 0.8.0 on the dev host reproduces exactly this.

**`PublicKey.schnorr_verify` must never be called.** embit binds `secp256k1_schnorrsig_verify` with
four arguments; since 0.3.0 the C function takes five, the fourth being `msglen`. embit passes the
x-only pubkey pointer where C reads a length, and the library then dereferences whatever follows —
a **segfault**, not an exception, which no `except:` can catch. The appliance only ever signs, so
nothing calls it today; it is written down here because the failure is a crash of the whole
appliance rather than an error anyone can handle. Signing is unaffected and was checked
independently: a signature made through the ctypes path against Alpine's `libsecp256k1` verifies,
it merely picks a different BIP340-legal nonce than embit's own bundled blob picks.

**This is not a constant-time claim.** `py_secp256k1` is not constant-time, but the appliance runs
exactly one userspace process (#15) and has no network, so there is no local observer and no remote
peer to measure. The realistic observer is physical, which is Tier 2/3 territory where this appliance
already promises nothing. The audited library is preferred on supply-chain and correctness grounds;
nothing here should be read as a defence against a timing adversary.

## Size, and the RAM floor

Measured from Alpine v3.24 `APKINDEX` dependency closures, x86_64, installed sizes:

| closure | packages | MiB |
|---|---|---|
| `python3` | 18 | 34.79 |
| + `py3-zxing-cpp` | 21 | 36.13 |
| + `py3-textual` | 32 | 45.26 |
| + `py3-cryptography`, `py3-argon2-cffi` | 38 | 49.51 |
| **full**, with busybox, musl, baselayout, kbd | **45** | **~54** |

Largest: `python3` 22.42, `libcrypto3` 4.97, `py3-pygments` 4.31, `py3-cryptography` 3.42, `kbd-misc`
3.19, `py3-textual` 2.70. For scale, `linux-lts` is **151.76 MiB**, almost entirely the modules this
build does not produce.

**Measured at the first real build, and larger than the table above: 97.1 MiB in 96 packages.**

The table was computed from `APKINDEX` dependency closures before a rootfs existed. What it missed
is Alpine v3.24's `-pyc` companion subpackages — `py3-textual-pyc`, `py3-rich-pyc`,
`py3-pygments-pyc` and so on, pulled in through `install_if` once `python3-pyc` is present — which
roughly doubles every Python payload. The three packages the table counted in prose but no pin
named (`busybox`, `busybox-binsh`, `alpine-baselayout`) account for about 1 MiB of the difference;
the bytecode accounts for the rest.

**This does not move the RAM floor and nothing here is re-derived on its account:** 97 MiB unpacked
against a 512 MiB floor leaves the same real headroom, and the working set is dominated by
Argon2id's transient and the Python heap rather than by the tree on disk. It is recorded because
the build prints both measurements at every run precisely so this number stays a measurement.
Dropping the bytecode would be a size *optimisation* with a first-import cost, and it is not one
this document asks for.

**The initramfs size risk is closed.** ~54 MiB of mostly-text Python zstd-compresses to roughly 20 MiB,
plus a no-net/no-block kernel around 8 MiB: a **~30 MiB image**. No BIOS or UEFI implementation
struggles with that, so #10's fallback architecture (B) is not needed and claim (i) stands as written.

**No pruning of the Python stdlib.** Stripping it buys ~10 MiB against the risk of a missing-module
traceback on an appliance with no recovery path. `font-terminus` (2.17 MiB) *is* dropped — the
built-in kernel 8×16 font already satisfies #3's exact-1:2 cell requirement.

**The floor is 512 MiB**, and it is derived, not asserted: unpacked rootfs ~54 MiB + kernel ~50 MiB +
Argon2id's 64 MiB transient (#9) + the Python heap + camera buffers ≈ 200 MiB working set. 512 MiB
leaves real headroom, sits below anything amd64 hardware that boots UEFI actually has, and is a number
a user can check. The build log emits the measured initramfs and rootfs sizes so the figure stays
derived as the image changes.

## Failure

**The app catches its own top-level exceptions**, wipes the derived key material, shows a plain screen
naming the failure, and waits for a keypress before forcing power-off. A genuine interpreter-level
crash panics the kernel and hangs there (`panic=0`).

The failure the user must never see is a **silent power-off with no explanation** — indistinguishable
from a hardware fault, and it invites exactly the blind retry #11 refused to train.

## Time

**No clock service, no `hwclock`, no NTP, no timezone database.** Nothing the appliance does needs
wall-clock time: signing does not, Argon2id does not, and there is no certificate to validate. The RTC
is read by firmware and ignored.

Consequence, and it belongs on the review screen: **the appliance never displays a date or time**, and
an `nLockTime` is shown as a raw height or timestamp with **no "is this in the past" judgement** —
that judgement would require trusting a clock deliberately never set.

## Build-time assertions

The build **fails**, not warns. This is where "every claim must be testable" is cashed out — each
line below is a published claim, checked before an image exists.

- `CONFIG_NET=n`, `CONFIG_MODULES=n`, `CONFIG_MAGIC_SYSRQ=n`; no block or storage driver; no swap.
- The built-in USB class driver list is **exactly** `usbhid` and `uvcvideo` (#14).
- No `getty`, no `login`, no `inittab` in the rootfs; PID 1 is our script.
- No network utility and no package manager in the rootfs.
- **Import-check every module the app needs against the built kernel.** `CONFIG_NET=n` removes
  `AF_UNIX` as well as `AF_INET`, so `multiprocessing` and anything socket-backed is unavailable —
  that must fail at build time, not mid-session with a wallet loaded.
- **`embit/util/prebuilt/` does not exist in the vendored tree**, and the live EC backend is
  `embit.util.ctypes_secp256k1`.
- **Sign once with each scheme and compare the bytes:** one BIP84 ECDSA signature and one BIP86
  Schnorr signature over a published BIP39 test vector, executed in the built rootfs, matching
  expected output. A name check on the backend module is **not** sufficient and must not be
  substituted for this: embit binds the `schnorrsig`/`xonly`/`keypair` symbols inside their own bare
  `try:`/`except: pass`, so a `libsecp256k1` compiled without those modules imports cleanly, reports
  the native backend, and then fails at taproot signing — mid-session, with a wallet loaded, on
  BIP86 only. A signature that verifies proves the symbols bound, the modules were compiled in, and
  the ABI matches; a symbol check only approximates all three.
- **`build/inputs/` matches `build/inputs.sha256` on hash and on set equality**, before stage 1
  runs. An unexpected extra file is a failure, not an ignore — `docs/reproducible-build.md` claim 5.
- **Nothing in the build derives its parallelism from the host's core count.** `make -j` and
  `zstd -T` are literal constants, and `zstd -T0` is rejected specifically because it is a digit that
  *means* one thread per core.
- **`build/toolchain-versions.txt` carries exactly one group.** `Dockerfile.iso` and
  `fetch-inputs.sh` read it as every non-comment line, which is correct only while that holds.
- **`/etc/aobs-release` agrees with the tag and with `HEAD`**, checked in stage 3 *before* `cpio`,
  while it is still a file a human can open. A build that is not at a clean tag must say
  `development` and never a version-shaped string; the assertion is skipped for those, not faked.
- Emit measured initramfs and rootfs sizes into the build log, and the **hash ladder**: the sha256 of
  the rootfs tree manifest, `bzImage`, `initramfs.zst`, `efi.img` and the ISO, so that a rebuild which
  diverges says where.

Four further assertions run only when a release is being cut, in `build/release-preflight.sh` rather
than in `mkiso.sh`, and `docs/release.md` says why the split falls there: a dirty tree, an unsigned or
absent `vMAJOR.MINOR[.PATCH]` tag, a hand-set `SOURCE_DATE_EPOCH`, and a manifest whose
`git-commit` is not `HEAD`. A development build trips none of them.

## The artifact

`bitcoin-signer-amd64.iso`, ~30 MiB, containing a kernel, an initramfs, and two bootloaders. The user
writes it to a USB stick with `dd` (or burns it) and boots the offline machine from it.

**Secure Boot must be disabled in firmware.** The kernel is unsigned and will stay unsigned: a shim
chain means Microsoft-signed binaries and a release-signing process, squarely inside the *producing
the ISO* out-of-scope ruling — and it would put a third party's signature in the trust path of an
appliance whose pitch is that you can verify it yourself. It changes nothing in the threat model: #2
already declined boot-time self-verification, and firmware attacks are Tier 3.
