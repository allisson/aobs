# Roadmap

The map. What is settled, what is open, and in what order — in the repo on purpose, so that a
decision is reviewable in the same diff as the change it authorises.

The finish line is **a signed v0.1.0 release**, not parity with the Alpine predecessor. That
predecessor's failure was never finishing: 19 reproducibility-guard runs, zero releases, zero
hardware boots. So **M3 is a gate**. Nothing past it may be started before it passes, and no
milestone after it may be skipped to reach a tag sooner.

No dates. Milestones complete when their exit criteria are met, and every criterion below is
something a command answers rather than something a person judges.

---

## M0 — Repository bootstrap

Get the inherited code and the pinned base into this repo, with nothing built yet.

- [x] Copy `aobs/`, `tests/`, `fixtures/`, `pyproject.toml` from the predecessor. No git history
      import — the old history is 78 issues of decisions about a kernel this project no longer builds.
      Landed on `m0-bootstrap` across six commits rather than one squashed commit, because three of
      them are corrections worth reading separately: the Python-layer seam, the libsecp256k1
      verification, and the embit sdist findings.
- [x] Copy the app-level documents over unchanged: `psbt-review-model`, `review-screen`, `seed-entry`,
      `secret-hygiene`, `address-verification`, `entropy-mixing`, `export-password`,
      `encrypted-wallet-qr`, `network-selection`, `qr-emit-parameters`, `scan-feedback`,
      `failure-states`.
- [x] Seed `CONTEXT.md`, revising the terms the base-OS switch changes: `Offline`, `Amnesic`,
      `No data path`, `Boot medium`, `Input archive`, `Source archive`, `Reproducibility contract`.
- [x] Pick the `snapshot.debian.org` timestamp and record it in one place both the build and the test
      tier read — `build/snapshot.env`.
- [x] `build/apt-repositories`: both `trixie` and `trixie-security` at that instant. The second is not
      optional — at this snapshot `linux-image-amd64` is 6.12.94-1 in main and **6.12.107-1** in
      security, so pinning main alone would ship an appliance kernel thirteen point releases behind,
      silently.
- [x] Generate `build/apt-versions.txt` from that snapshot, with the machine-readable
      `# @group appliance` / `# @group harness` markers. A package outside any group is a parse error,
      never a guess — in the predecessor a prose comment on the wrong side of the split put a package
      manager in the rootfs and nothing noticed.
- [x] Fix `pyproject.toml`'s dependency groups. `textual`, `pillow` and `zxing-cpp` sat under the
      `test` extra while being imported by appliance code — `aobs/ui/screens/scan.py` calls
      `qrdecode.decode_frame`, which needs `zxingcpp` and `PIL` — and the comment there asserted the
      opposite of what the code does. The groups are now load-bearing: `dependencies` is what the
      rootfs gets, `test` is what only the tier gets.
- [x] `build/wheel-versions.txt` + `build/gather-wheel-versions.sh`: **every** Python package, both
      groups, derived from `pyproject.toml` and `uv.lock`. Versions in the list for a human to read;
      hashes only in the lock, so there is one place for one fact. See
      `docs/adr/0002-python-dependencies-from-pinned-wheels.md`, including why the layer is not split
      package by package between apt and PyPI.
- [x] `docs/adr/0001-debian-base-and-stock-kernel.md`,
      `docs/adr/0002-python-dependencies-from-pinned-wheels.md`, `docs/overview.md`, `CLAUDE.md`,
      this file.
- [x] Fix `.gitignore`: the Python-packaging default ignores `build/`, which is source here.
- [x] Drop `tests/test_build_verifier.py` and `tests/test_verify_release.py`. Both test subjects that
      no longer exist — the Alpine `build/gather.py`, `build/verify.py` and `verify-release.sh` — so
      they are rewritten against the Debian build at M2 and M5 respectively, not ported. **This is
      the one place where importing the predecessor loses coverage**, and it is recorded here so it
      cannot be forgotten: until M2 the build has no assertions under test.
- [x] Two assertions in `tests/test_structure.py` are guarded because their subjects are deferred:
      the `docs/test-harness.md` port-table check skips until M2, and the ADVISORIES/README
      cross-check skips until M5. Both guards are listed for removal in those milestones — a
      permanent skip is a deleted test with extra steps.

**Exit**: met. 692 passed, 9 skipped, 2 deselected (the opt-in regtest suite), 0 failed.

**Nothing else is claimed, and one thing specifically is not.** That run took 22 m 31 s because this
dev machine has no loadable `libsecp256k1`, so every EC operation went through embit's
`py_secp256k1` — the code path `docs/boot-pipeline.md` forbids on the appliance. It is evidence that
the suite runs. It is not evidence about the code that ships; see `CLAUDE.md` and M1.

---

## M1 — The application, green in the authoritative tier

Needs no image at all, which is why it is first: the harness drives the app headless in seconds and an
ISO build is minutes.

The original plan here was a Textual port, on the belief that Debian shipped a *newer* Textual than the
app was written for. It ships an older one — six majors older — and two crypto floors besides, so
`docs/adr/0002` moved the Python layer to hash-pinned wheels and **there is no port**. What is left is
proving that the app runs unchanged on Debian's interpreter, against Debian's `libsecp256k1`, with the
wheel layer installed the way the image will install it.

- [ ] `build/Dockerfile.test` on `debian:trixie-slim` at the pinned snapshot, installing both apt
      groups and both wheel groups — the authoritative tier.
- [ ] Wheels install from pre-fetched files with `--no-index`, the same way `mkiso.sh` will do it. A
      tier that reaches PyPI at test time is not testing what ships.
- [ ] Full suite green on Debian's `python3` 3.13.5. `pyproject.toml` says `>=3.12`; the predecessor
      ran Alpine's 3.14 and this machine runs 3.13.12, so Debian's 3.13.5 is close to but not the same
      as anything the suite has passed on.
- [ ] Confirm every appliance wheel has a `manylinux` build compatible with trixie's glibc 2.41 for
      CPython 3.13 — `cryptography` ships `cp311-abi3`, but `pillow`, `zxing-cpp`, `cffi` and
      `argon2-cffi-bindings` are per-version and must be checked rather than assumed. A missing wheel
      means a compiler in the build, which `docs/adr/0001` spent the Alpine kernel config to avoid.
- [ ] Confirm the vendored `embit` and `ur2` build and pass there — Debian packages neither.
- [x] **Done, ahead of the milestone.** Debian's `libsecp256k1-2` 0.5.0-2+b1, pulled from the pinned
      snapshot and inspected, exports `secp256k1_schnorrsig_sign32`, `secp256k1_keypair_create`,
      `secp256k1_xonly_pubkey_from_pubkey`, `secp256k1_ecdh` and `secp256k1_ecdsa_sign_recoverable`
      — BIP86's modules were enabled — and also the long-deprecated `secp256k1_ec_privkey_negate`
      alias that the vendored embit's loader binds unconditionally. No build-from-upstream stage is
      needed and `docs/adr/0001` stands.
- [ ] Assert every EC operation goes through that `.so` and never embit's pure-Python fallback.
      **Measured, and worse than a performance note**: with no `libsecp256k1` to `ctypes`-load, the
      vendored embit silently resolves to `py_secp256k1` — 1.73 ms per `ec_pubkey_create` against
      tens of microseconds for the C library, which is why the suite takes 22 minutes on a machine
      without it. The cost is the visible half. The other half is that such a run exercises the exact
      code path `docs/boot-pipeline.md` forbids on the appliance, and passes. So the assertion is not
      only a build-time check: the suite itself must refuse to run against the fallback, or say so on
      every line of output.
- [ ] `build/verify.py` parses **both** pin files and asserts the two groups stay disjoint — two lists
      is a thing the build checks, not a thing that can drift.
- [ ] **No test may be skipped in this tier.** Three entropy tests carry
      `@linux_getrandom_only` because `os.GRND_NONBLOCK` does not exist off Linux, so they skip on a
      dev Mac and the ordering guarantee in `docs/entropy-mixing.md` is guarded only here. A tier
      that reports skips is not authoritative; make a non-zero skip count fail it.

**Exit**: the full suite passes inside the authoritative tier, at the exact versions the ISO will
install, from both lists. One ECDSA and one Schnorr signature verified against a known-answer fixture.

**Risk**: the `manylinux` question below is now the live one — `libsecp256k1` is settled.

**And a standing condition, not a task**: on a machine without a loadable libsecp256k1 the vendored
embit resolves to `py_secp256k1` and the suite still passes, 50-80x slower. Homebrew's 0.7 counts as
"without": it dropped the deprecated alias embit binds, so the library loads and embit rejects it.
The decision was to leave embit's vendored loader alone and make **this container the place the suite
is actually run** — so a green run on a dev machine is not evidence about the code that ships, and no
milestone may cite one. The same silent fallback is what a future Debian shipping 0.7+ would cause on
the appliance itself; `build/verify.py`'s symbol assertion is the only thing standing between that and
a pure-Python signer.

---

## M2 — The image builds

- [ ] `mmdebstrap --mode=unshare` builds the rootfs from the pinned snapshot. **No `--privileged`.**
      Verify unshare mode works in the CI runner early; if it does not, that is a finding, not a
      licence to reach for `--privileged`.
- [ ] `build/fetch-inputs.sh`: the one networked step, and not part of the build. It resolves both
      pin files' closures — `.deb`s from the snapshot, wheels from PyPI — into `build/inputs/`, and
      the build refuses to start unless every byte matches `build/inputs.sha256`
      — on hash **and** on set equality. There is no second, offline-only path to go stale.
- [ ] Install Debian's `linux-image-amd64` (6.12 LTS, the same series the predecessor compiled by
      hand). No kernel compile, no `kernel.config`, no toolchain.
- [ ] Prune the modules tree to the generic allowlist — `i915`, `amdgpu`, `nouveau`, `simpledrm`,
      `uvcvideo`, `usbhid`, plus dependencies — and delete everything else, including all of
      `kernel/net` and `kernel/drivers/net` and every storage driver. Regenerate `modules.dep`.
- [ ] A `modprobe` blacklist as a cheap second line. It is never cited as the claim.
- [ ] Install the wheel layer into the rootfs with `pip --no-index` from `build/inputs/`, then remove
      `pip` before the initramfs is packed. `build/verify.py` fails the build if any package manager
      survives into the image.
- [ ] Copy the app tree into the rootfs. Never `pip install` for the app itself.
- [ ] Ship the full `console-data` keymap set. Measure what it costs.
- [ ] `build/init` as PID 1: five mounts, UTF-8 console, default keymap, `authorized_default=0` after
      our devices enumerate and before the first secret, the RAM floor, `exec python3 -m aobs`. No
      `set -e`; each step checks its own result and a failure is named on the console and held there.
- [ ] `cpio | zstd` the whole rootfs into the initramfs.
- [ ] `xorriso` into a hybrid ISO: `isolinux` for BIOS, `grub-efi` for UEFI. Secure Boot is **not**
      supported in v0.1.
- [ ] Write `docs/test-harness.md` and remove the skip guard in
      `tests/test_structure.py::test_there_is_no_screen_port`.
- [ ] `build/verify.py`: every build-time assertion as a pure function, each fed a deliberately broken
      input by the suite to prove it still bites — this is where `tests/test_build_verifier.py` comes
      back, written against the Debian build rather than ported from the Alpine one. Minimum set — no harness package in the rootfs, no
      package manager, `/bin/sh` and `python3` present (the predecessor's first ISO had neither, and
      `build/init` could not have run a line), no `kernel/net`, no module outside the allowlist, no
      getty, the `libsecp256k1` symbols, the RAM floor matching the measured size.
- [ ] Derive the RAM floor from the measured unpacked size by a stated formula, re-derived by the
      build so the floor and the image cannot drift apart. **Publish the measured numbers** — unpacked
      rootfs, initramfs, kernel, ISO — against the run they came from.

**Exit**: `out/bitcoin-signer-amd64.iso` exists, every assertion passes, and the size and RAM figures
are recorded as measurements rather than estimates.

---

## M3 — It boots on real hardware and signs a PSBT — **GATE**

The thing the predecessor never did. No test in this repository can tell you whether the kernel boots,
finds a framebuffer and enumerates a camera on a real machine.

- [ ] **Choose and characterise the target machine**: make, age, BIOS or UEFI, whether Secure Boot can
      be disabled in its firmware, built-in webcam or USB. Nothing below can be judged without this.
- [ ] Narrow the generic module allowlist to what that machine actually needs, or record why it stays
      generic.
- [ ] `docs/boot-checklist.md`: the checks only a booted appliance can answer, published with the ISO.
- [ ] Run it. Boot the stick, walk the keymap picker, generate a wallet, export the xpub by QR, build
      an unsigned PSBT in a watch-only wallet, scan it, review it, sign it, scan the signature back,
      broadcast on signet.
- [ ] Pull the boot medium out mid-session and keep signing. That is the cheapest check of the
      amnesia claim, and it is only a claim until someone has done it.
- [ ] Check each structural claim on the running appliance: `ls -d /proc/[0-9]*`, `cat /proc/mounts`,
      `ls /sys/block`, `command -v ip`, `cat /sys/bus/usb/devices/usb*/authorized_default`.
- [ ] Record the answers as a **boot-checklist run record** — the checklist is the procedure, the run
      record is the evidence, and only the second is something a stranger can check. Verdicts are
      *pass*, *fail* and *deviated*; the third is load-bearing.

**Exit**: one PSBT signed on real hardware and broadcast, and a run record with every row answered.

Everything below this line waits.

---

## M4 — The reproducibility guard

- [ ] `docs/reproducible-build.md`: the contract as a numbered list of environment facts that must not
      reach the bytes of the ISO — build path, hostname, user, uid, clock, locale, timezone, umask, CPU
      count, host kernel, host architecture — and an explicit list of what is *not* claimed.
- [ ] CI builds twice under deliberately hostile variation and fails on any differing byte.
- [ ] Fix every divergence source found. `SOURCE_DATE_EPOCH` throughout; deterministic `cpio` ordering,
      ownership and timestamps; deterministic `mmdebstrap` output; no build-host paths in the image.
- [ ] Runs on `build/**` pull requests. Record the measured wall-clock against the timeout, as the
      predecessor did (14 m 42 s against a 40-minute threshold — and it no longer carries a 249 s
      kernel compile).
- [ ] The **input archive**: every byte the build consumes that the build did not write, fetched,
      verified and published as one thing, so a release stays rebuildable after upstream stops serving
      those bytes. Every member must be a function of the package set, or two fetches of the same set
      produce two different archives.
- [ ] The **source archive**: corresponding source for every copyleft-touched package the input archive
      redistributes. An accompaniment, not an input — no build reads a byte of it. Debian's source
      packages and `snapshot.debian.org` make the pinning exact; this is easier here than it was on
      Alpine.

**Exit**: two builds from a clean tree, on deliberately different hosts, produce the same sha256.

---

## M5 — Signed v0.1.0

- [ ] The **manifest**: plain text, line-oriented, naming the release, the commit, the inputs,
      `SOURCE_DATE_EPOCH`, and the sha256 of every published file. The manifest is what is signed; the
      ISO is not. A signature over a file that names the inputs also says which inputs produced them,
      which is what an independent reproduction needs.
- [ ] `verify-release.sh`: what a stranger runs, and `tests/test_verify_release.py` with it — `sha256sum` and `gpg`, nothing else, by construction
      and by test — driven in CI against a fixture release signed with scratch keys in a throwaway
      `GNUPGHOME`. The one artifact aimed at people who trust nobody is the last one to be tested
      against a stand-in.
- [ ] `build/release-preflight.sh`: the release-mode refusals — clean tree, tag present, tag matches
      the version, inputs match. A build from a dirty tree must not be able to claim a release; the
      predecessor's only ISO read `release: development` for exactly that reason.
- [ ] `docs/release.md`: the ritual.
- [ ] The **pre-trust warning**, in the README and on the release: what has been *observed*, never what
      has been *found*, and carrying the conditions that retract it. Plus the honest admissions the
      predecessor's README made and should keep making — GitHub serves the ISO, the manifest, the
      signature and the README together, so the fingerprint must come from somewhere else; and the
      maintainer's key lives on an ordinary networked computer.
- [ ] `ADVISORIES.txt` and its policy. An empty list is not an attestation. Removing the `skipif` on
      `tests/test_structure.py::test_the_readme_carries_the_advisory_list_verbatim` is part of this,
      and `build/release-preflight.sh` must refuse a release whose `ADVISORIES.txt` is missing —
      otherwise the skip silently protects the very drift the test exists to catch.
- [ ] Cut and sign v0.1.0 from a clean tagged tree, with the boot-checklist run record published
      beside the ISO.

**Exit**: a stranger can download, verify, rebuild, get the same hash, boot it, and sign.

---

## After v0.1.0

Not in scope for the release, recorded so nobody has to rediscover that they were considered.

- **Secure Boot**, via Debian's signed `shim` + `grub` + signed kernel. Genuinely achievable now that
  the kernel is Debian's — pruning the modules tree does not break the kernel image's signature — but
  it adds a second boot path to test and raises reproducibility questions about signed blobs. Best
  candidate for the first post-v0.1 milestone.
- **Witness build**: an independent rebuild published so a third party can see two hashes agree. It
  never ran in the predecessor and cannot run before a tag exists. Worth doing once there is a tag to
  test it against, with the limit stated: a key in GitHub's secret store corroborates the build, not
  the platform.
- **Revisit the keymap set** if the measured RAM cost of full `console-data` turns out to be absurd —
  with a number in hand, not a guess.
- **Narrow the module allowlist** per additional machines as boot-checklist run records accumulate.
- Multisig is **out of scope** and is not a deferral. A multisig keychain is not a Wallet in this
  project's vocabulary.
