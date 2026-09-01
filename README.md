# aobs

Amnesic Offline Bitcoin Signer — a Bitcoin signing appliance: a bootable Alpine LiveCD run on an
offline machine to review and sign a PSBT, then powered off. QR codes are the only data path in or
out. Single-sig, BIP84 and BIP86, Python, [embit](https://github.com/diybitcoinhardware/embit).

The design is closed one decision at a time on the wayfinder map,
[issue #1](https://github.com/allisson/aobs/issues/1); `docs/` holds the settled decisions and
`CONTEXT.md` the vocabulary. **Read the document before changing behaviour it fixes** — a design
decision made only inside a code diff is invisible to the next session.

## What exists today

`aobs/core/` — the pure core — the harness around it, the application, and both halves of every
port. `python3 -m aobs` starts a signer whose camera is a webcam, whose randomness is the kernel,
whose keymap picker changes the keyboard and whose `F12` stops the machine. `build/` turns the
repository into `bitcoin-signer-amd64.iso`, and PID 1 is what `exec`s the above.

| | |
|---|---|
| `aobs/core/` | Bytes in, value objects out. No I/O, no clock, no ambient state. |
| `aobs/ports/` | The four ports: `FrameSource`, `Keymap`, `EntropySource`, `Power`. |
| `aobs/adapters/fake/` | The harness half of each port: image files, fixed bytes, recorders. |
| `aobs/adapters/real/` | The appliance's half: V4L2 capture, `getrandom`, `loadkeys`, power-off. |
| `aobs/ui/` | The Textual application: global keys, the failure shape, every screen. |
| `aobs/__main__.py` | What PID 1 `exec`s, and the one place the real adapters are named. |
| `fixtures/` | Every fixture, and the one script that generates them all. |
| `build/` | Both tiers, the kernel config, PID 1, and the assertions that fail the build. |

The display is not a port. `SignerApp` **is** the display seam: tests drive the real application
headless through Textual's `run_test()`, and the console adapter will run the very same object.

One rule carries weight and a test enforces it: **`core/` may not import any adapter,
`aobs.ui` or `aobs.ports`.**

## Verifying what you downloaded

You are about to boot an image and type a seed phrase into it. Verify it first. This takes two
commands and needs nothing you do not already have: `sha256sum` and `gpg`.

### 1. Get the maintainer's key, from somewhere that is not this page

```sh
gpg --locate-key allisson@gmail.com     # from keys.openpgp.org
```

Then confirm the fingerprint you got matches:

```
C853 2ED6 8A59 6CFB B7F9  2D04 3607 18E3 09BE AA9F
```

**Confirm it against a second source before you rely on it.** The same fingerprint is published on
[x.com/allisson](https://x.com/allisson), an account that predates this project by years. Two
sources with different operators, neither of them GitHub, is the whole point of this step.
`SECURITY.md` holds the anchors and the revocation procedure.

### 2. Verify the release

```sh
gpg --verify manifest-v1.0.txt.asc manifest-v1.0.txt
grep -E '^[0-9a-f]{64}  ' manifest-v1.0.txt | sha256sum -c -
```

That is the entire verification. The `grep` is required, not decoration: `sha256sum -c` treats the
manifest's comments as malformed checksum lines and fails on them — measured against busybox
coreutils, not assumed.

`verify-release.sh` in the release does the same thing and, more usefully, prints what it could
*not* check. It is a **convenience, not an authority**: it is under 120 lines, it shells out only to
the two commands above, and you should read it before you run it. `--iso-only` exists so that
declining the 360 MB input archive is not reported as a failure.

### What this proves, and what it does not

**It proves** that the person holding that key vouches for these exact bytes, and that the bytes you
have are the bytes they vouched for.

**It does not prove the image is honest.** For that, rebuild it and compare — the manifest names the
commit, the inputs and `SOURCE_DATE_EPOCH` precisely so that you can:

```sh
git checkout v1.0
docker run --rm --platform=linux/amd64 -v "$PWD:/src" -w /src \
    alpine:3.24 sh build/fetch-inputs.sh
docker build -f build/Dockerfile.iso -t aobs-iso .
mkdir -p out && docker run --rm --privileged -v "$PWD:/src" -v "$PWD/out:/out" aobs-iso
```

A matching sha256 means a stranger's build and the published build are the same file. That is the
claim this project actually rests on; the signature only tells you who to blame if it fails.
`docs/reproducible-build.md` states the contract numbered and checkable.

**The version row on the appliance's first screen identifies, it does not attest.**
`aobs v1.0 · 4f1c8a6e2b90 · 2026-09-14` is checkable against the manifest you verified, which is what
the commit prefix is for — but a modified image can print anything, and a self-report by a
possibly-modified image is not evidence about itself.

### What GitHub could forge

Said plainly, because most projects do not:

**GitHub serves you the ISO, the manifest, the signature, and this README.** If GitHub is compromised
or coerced, all four change together and nothing on this page detects it — including the fingerprint
printed above, and including the key listed on the maintainer's GitHub profile, which is the same
origin as everything else here.

What GitHub cannot forge is a signature by a key it does not hold. So the one step that has to come
from elsewhere is step 1: **get the fingerprint from keys.openpgp.org or from the account linked
above, not from this file.** Everything after that is arithmetic you run yourself.

Two smaller admissions, in the same spirit:

- **The maintainer's key lives on an ordinary networked computer**, not a hardware token and not an
  air-gapped machine. Whoever compromises that computer can sign releases. This is a one-person
  project and that is the honest limit of it.
- **A `witness-ci` signature is worth less than the builder's.** It would say a GitHub Actions runner
  independently rebuilt the image and got the same hash — valuable, and exactly what independent
  reproduction is for — but the key it signs with lives in GitHub's secret store, so it is not
  independent *of GitHub*. It corroborates the build, not the platform.

## Security advisories

None. No release has been cut yet.

`ADVISORIES.txt` in this repository is the source of truth, signed by the key above and re-attached
to every release; `SECURITY.md` holds the threshold for publishing one and the six fields an entry
carries. Every release's README carries the full list, so that a user who came back to fetch a newer
ISO meets the advisories on the way rather than by searching for them.

**The appliance does not check this list and cannot.** There is no trustworthy clock on an offline
machine, and a modified image would lie about it anyway. The static line under the version row points
here; it never claims to have looked.

## Building the ISO

A separate command from the test loop, and a separate container: running the suite must never need
a kernel toolchain. Everything it needs is a container runtime.

```sh
docker run --rm --platform=linux/amd64 -v "$PWD:/src" -w /src \
    alpine:3.24 sh build/fetch-inputs.sh          # once, or when a pin changes
docker build -f build/Dockerfile.iso -t aobs-iso .
mkdir -p out && docker run --rm --privileged -v "$PWD:/src" -v "$PWD/out:/out" aobs-iso
```

**The build touches no network.** `build/fetch-inputs.sh` is the only step that does, and it is not
part of the build: it populates `build/inputs/` — 96 appliance packages, 112 toolchain packages, the
minirootfs tarball and the kernel tarball — and `build/mkiso.sh`
refuses to start unless every byte of that directory matches `build/inputs.sha256`, on hash **and on
set equality**. There is no second, offline-only build path to go stale: this is the only path, and
CI walks it on every commit.

**The output is byte-identical on any host** — build path, hostname, user, uid, clock, locale,
timezone, umask, CPU count, host kernel version and host architecture do not affect it, and CI builds
twice under deliberately hostile variation and fails on any differing byte.
`docs/reproducible-build.md` states the claims, the ten divergence sources that were fixed, and what
is deliberately *not* claimed.

Four stages — a pinned apk userland into `/rootfs`, a vanilla kernel.org LTS tarball pinned by
version and SHA-256 built against `build/kernel.config`, `cpio | zstd` into an initramfs, `xorriso`
into a hybrid ISO — and the build **fails rather than warns** at the first stage where a published
claim stops being true. `--privileged` is for one thing: the `chroot` that signs one BIP84 ECDSA and
one BIP86 Schnorr signature inside the rootfs the image will actually carry.

| | |
|---|---|
| `build/kernel.config` | The kernel, as one reviewable file. No networking, no modules, no block layer, exactly two USB class drivers. |
| `build/init` | PID 1: five tmpfs and pseudo-filesystem mounts, the console, `authorized_default=0`, the RAM floor, `exec python3 -m aobs`. |
| `build/verify.py` | Every build-time assertion, as pure functions. Text or a listing in, violations out. |
| `build/mkiso.sh` | The four stages. Gathers inputs, asks the verifier, exits non-zero on the first violation. |
| `build/apk-versions.txt` | The single pinned list both tiers read, split into two machine-readable groups. |
| `build/toolchain-versions.txt` | The builder's own pins, in one group, so `Dockerfile.iso` can read it naively and be right. |
| `build/fetch-inputs.sh` | The one networked step. Populates `build/inputs/`; `--refresh` rewrites `build/inputs.sha256`. |
| `build/release-preflight.sh` | The four release-mode refusals, and nothing else. `docs/release.md` holds the ritual. |
| `verify-release.sh` | What a stranger runs. `sha256sum` and `gpg` and nothing else, by construction and by test. |

Writing the stick and booting it:

```sh
sudo dd if=out/bitcoin-signer-amd64.iso of=/dev/sdX bs=4M status=progress conv=fsync
```

**Secure Boot must be disabled in firmware.** The kernel is unsigned and stays unsigned: a shim
chain means Microsoft-signed binaries, and it would put a third party's signature in the trust path
of an appliance whose pitch is that you can verify it yourself. Release signing is an unrelated
mechanism — a detached signature over a manifest, verified before you boot — and it leaves the image
itself unsigned.
A boot that stops before the keymap picker on a machine with Secure Boot on is that, and not a fault.

What the build proves is one half; `docs/boot-checklist.md` is the other, and the boundary is
deliberate. No runner can check amnesia, USB behaviour, the console, or the camera — you boot it and
look.

## Running the tests

One tier, and `.github/workflows/tests.yml` runs it on every pull request: `alpine:3.24` with the
exact apk versions pinned in `build/apk-versions.txt`, so a `zxing-cpp`, `cryptography` or
`libsecp256k1` skew fails here rather than on the appliance.

```sh
docker build -f build/Dockerfile.test -t aobs-test .     # only when the pins change
docker run --rm -v "$PWD:/src" -w /src aobs-test         # the dev loop, ~20 s
```

The bind mount is what makes this the everyday loop: the image carries the pinned userland, the
working tree comes from the host, and no rebuild is needed to run an edit.

`uv run --extra test pytest` still works, for a debugger or an IDE test runner. It is not a tier —
nothing in CI runs it, and it is roughly 17x slower, because `embit` is vendored without its
prebuilt binary and most hosts have no system `libsecp256k1`. `docs/test-harness.md` explains why
that trade is the right way round.

**Regtest, opt-in** — the only instrument that catches a wrong taproot sighash, because a wrong
sighash produces a well-formed signature every appliance-side check accepts. Needs a `bitcoind`
in regtest mode:

```sh
uv run pytest -m regtest
```

`BITCOIN_CLI` and `BITCOIN_CLI_ARGS` say how to reach the node, so a container counts as one and
nothing needs installing on the host — the invocation is in that module's docstring.

Fixtures are generated artifacts, committed next to their generator so a reviewer regenerates and
diffs rather than trusting a blob:

```sh
uv run python fixtures/generate.py
```

Every key in this repository descends from the BIP39 test-vector mnemonic printed in BIP39
itself. A test asserts every fixture's master fingerprint is on a short allow-list, so a PSBT
from a real wallet fails CI rather than quietly committing an xpub.

## Status

The build exists and **nothing here has been run on real hardware.**

What is verified: `build/kernel.config` is checked against every claim it carries by
`tests/test_build_verifier.py`, which also feeds each assertion a deliberately broken input to prove
it still bites, and the config has been through `kconfig`'s own dependency resolution — 613 symbols
against 6.12.106, no violations. Stages 0 and 1 of the build run end to end: 96 pinned packages,
97.1 MiB, and both signature schemes signing inside the rootfs the image will carry.

What is not: no ISO has been produced. The kernel compile, the initramfs and `xorriso` are written
and unexecuted. And no test in this repository can tell you whether the resulting kernel boots,
finds a framebuffer and enumerates a camera on your machine — that is `docs/boot-checklist.md`, and
it is published with the ISO.

No release has been cut. The reproducibility guard and the witness build are written and have never
run, so two numbers this design depends on are still estimates: the guard's CI runtime against the
40-minute fallback threshold, and whether a native amd64 kernel build fits a free runner's 6-hour
ceiling. `docs/reproducible-build.md` flags both as measured-on-first-run rather than designed around.

The claims in `docs/` state what is checkable and how.
