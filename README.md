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

## Building the ISO

A separate command from the test loop, and a separate container: running the suite must never need
a kernel toolchain. Everything it needs is a container runtime.

```sh
docker build -f build/Dockerfile.iso -t aobs-iso .
mkdir -p out && docker run --rm --privileged -v "$PWD:/src" -v "$PWD/out:/out" aobs-iso
```

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

Writing the stick and booting it:

```sh
sudo dd if=out/bitcoin-signer-amd64.iso of=/dev/sdX bs=4M status=progress conv=fsync
```

**Secure Boot must be disabled in firmware.** The kernel is unsigned and stays unsigned: a shim
chain means Microsoft-signed binaries and a release-signing process, and it would put a third
party's signature in the trust path of an appliance whose pitch is that you can verify it yourself.
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

The claims in `docs/` state what is checkable and how.
