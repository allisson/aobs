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

- [x] `build/Dockerfile.test` on `debian:trixie-slim`, installing both apt groups and both wheel
      groups from `build/inputs/` — the authoritative tier. `.github/workflows/tests.yml` runs it on
      every push to main and every pull request.
- [x] Wheels install from pre-fetched files with `--no-index`, the same way `mkiso.sh` will.
- [x] **`build/fetch-inputs.sh` moved here from M2**, because the tier needs it too and not only the
      image build. snapshot.debian.org rate-limits — measured 2026-09-07, five consecutive
      `InRelease` fetches returned 503 and the same URL returned 200 once retries were added — so a
      tier that apt-ed from it on every push would be flaky and abusive. It also cannot use HTTPS
      from `debian:trixie-slim`, which ships no `ca-certificates`; installing those first would mean
      pulling an unpinned package from an unpinned mirror *before* the step that does the pinning.
      Both problems disappear when the tier installs from a hash-gated local pool: 189 files,
      313 MiB, two `.deb` pools and two wheel pools, gated on hash **and** set equality.
- [x] The Python layer installs with `pip --target /opt/aobs-python`, not into `dist-packages`.
      Pinning `python3-pip` in apt drags Debian's `python3-wheel` and `python3-packaging` in, and
      dpkg's `packaging` 25.0 then blocks the lock's 26.3 — pip will not uninstall a package with no
      RECORD file. `--ignore-installed` would leave two copies with `sys.path` deciding the winner,
      which is `docs/adr/0002`'s "two resolvers over one import graph" arriving through pip's own
      dependencies. One directory, declared first on `PYTHONPATH`, is the answer.
- [x] Full suite green on Debian's `python3` 3.13.5. `pyproject.toml` says `>=3.12`; the predecessor
      ran Alpine's 3.14 and this machine runs 3.13.12, so Debian's 3.13.5 is close to but not the same
      as anything the suite has passed on.

      **Measured**, in `build/Dockerfile.test` on CI's native x86_64, run
      [34166600257](https://github.com/allisson/aobs/actions/runs/34166600257) on
      [#3](https://github.com/allisson/aobs/pull/3): **720 passed, 4 skipped, 2 deselected,
      0 failed** in 427 s, the run reporting `python 3.13.5, EC backend ctypes_secp256k1,
      authoritative tier yes`. The skip policy passed by staying silent — the four skips were
      exactly `SKIPS_ALLOWED` and none was stale.

      The same image under qemu on an arm64 Mac gave the same 720/4/2 in 496 s. That is recorded
      as corroboration and is **not** what closes this box: the rule is that a claim about the
      suite comes from the tier, and a dev machine is not where this project cites one.
- [x] **Confirmed.** Every appliance wheel has a `manylinux` build for CPython 3.13:
      `fetch-inputs.sh` runs `pip download --only-binary :all: --platform manylinux_2_28_x86_64
      --platform manylinux2014_x86_64 --python-version 3.13`, which fails if any package would need
      a source distribution, and it succeeds for all 18 appliance and 26 harness wheels.
      `cryptography` is `cp311-abi3`, `zxing-cpp` is `cp312-abi3`, `argon2-cffi-bindings` is
      `cp310-abi3`, and `pillow` and `cffi` are `cp313`. No compiler in the build.
- [x] The vendored `embit` and `ur2` pass there.
- [x] **First defect this tier caught, and the reason it exists.**
      `aobs/adapters/real/keymap.py`'s `PREFERRED` carried Alpine's xkb keymap naming — `gb`, `br`,
      `us-dvorak`. Debian's `console-data` ships the traditional console naming — `uk`,
      `br-abnt2`, `dvorak` — the exact inverse. `offered()` filters the list to what is installed,
      so wrong names do not raise: the picker silently offered `us, de, fr, es, it`, having dropped
      **ABNT2**, which is the layout `CONTEXT.md` names as the worked example of a user creating a
      wallet they can never reopen. Corrected against the image's own 216-map tree.
- [x] **Done, ahead of the milestone.** Debian's `libsecp256k1-2` 0.5.0-2+b1, pulled from the pinned
      snapshot and inspected, exports `secp256k1_schnorrsig_sign32`, `secp256k1_keypair_create`,
      `secp256k1_xonly_pubkey_from_pubkey`, `secp256k1_ecdh` and `secp256k1_ecdsa_sign_recoverable`
      — BIP86's modules were enabled — and also the long-deprecated `secp256k1_ec_privkey_negate`
      alias that the vendored embit's loader binds unconditionally. No build-from-upstream stage is
      needed and `docs/adr/0001` stands.
- [x] Assert every EC operation goes through that `.so` and never embit's pure-Python fallback.
      **Measured, and worse than a performance note**: with no `libsecp256k1` to `ctypes`-load, the
      vendored embit silently resolves to `py_secp256k1` — 1.73 ms per `ec_pubkey_create` against
      tens of microseconds for the C library, which is why the suite takes 22 minutes on a machine
      without it. The cost is the visible half. The other half is that such a run exercises the exact
      code path `docs/boot-pipeline.md` forbids on the appliance, and passes. So the assertion is not
      only a build-time check: the suite itself must refuse to run against the fallback, or say so on
      every line of output.

      **Landed as both halves, in `tests/conftest.py`.** `pytest_report_header` names the
      interpreter and the live backend on *every* run in *both* tiers, and adds a line saying the
      run is not evidence about the appliance whenever the backend is the fallback — that is the
      dev-machine half, and it is what stops a milestone being checked off from a green
      `py_secp256k1` run. `pytest_sessionstart` is the tier half: with `AOBS_AUTHORITATIVE_TIER=1`
      and a backend other than `ctypes_secp256k1` the session **does not start**, because a green
      report from 697 tests through the fallback looks exactly like a good one. No
      `AOBS_ALLOW_PURE_PYTHON_EC` escape hatch — an escape hatch on this one *is* the failure mode.
      The backend is read from `ec_pubkey_create.__module__`, never from whether a `.so` is on
      disk: `secp256k1.py` binds inside a bare `except:`, so a present-but-unloadable library
      produces a pure-Python signer and no error at all.
- [x] `build/verify.py` parses **both** pin files and asserts the two groups stay disjoint — two lists
      is a thing the build checks, not a thing that can drift.

      Three pure functions, and the M1 slice only — every assertion that needs a rootfs to look at
      is M2's. `parse_pin_file` makes the `# @group` markers load-bearing: a pin before any marker,
      an unknown group, an unpinned name, a name pinned twice in one group, or a missing group is
      an error and never a guess. `groups_are_disjoint` owns the cross-group case separately, so
      the message names the rootfs rather than a duplicate line. `no_apt_package_shadows_a_wheel`
      is the `docs/adr/0002` seam and is the one that will actually bite: **no `python3-*` package
      may be in the apt list at all**, not merely none that collides with a wheel today, because
      the collision arrives later when the wheel is added and nothing re-reads the apt list then.
      `python3` and `python3-pip` are the two named exceptions. `tests/test_build_verifier.py`
      returns here — written against the Debian build, not ported from the Alpine one M0 dropped —
      and feeds each function an input broken in the exact way it exists to catch.
- [x] **No test may be skipped in this tier**, and the mechanism is an **allowlist keyed by node
      id**, not a count. Three entropy tests carry `@linux_getrandom_only` because
      `os.GRND_NONBLOCK` does not exist off Linux, so they skip on a dev Mac and the ordering
      guarantee in `docs/entropy-mixing.md` is guarded only here. A tier that reports skips is not
      authoritative.

      **This box previously said "make a non-zero skip count fail it", and that was unimplementable
      at M1** — two of the four skips have subjects that arrive at M2 and M5, so zero is not
      reachable from here. `.github/workflows/tests.yml` had already settled for `<= 4` parsed out
      of `-q` output with `sed`, which is weaker than it looks: a count cannot tell a fifth skip
      from one of the four *moving*, and it cannot notice an entry that has stopped skipping. The
      gate is now `SKIPS_ALLOWED` in `tests/conftest.py`, naming each of the four by node id with
      the milestone that deletes it, and **two** things fail the session — a skip nobody named, and
      an entry that no longer skips. The second matters as much as the first: a stale entry is a
      standing exemption nobody notices has stopped applying, so the next skip of that test passes
      unremarked. Staleness is judged only on a whole-suite run, because the dev loop runs one file
      in the same container. `skip_policy_violations()` is a pure function and is fed its own
      broken inputs in `tests/test_tier_gates.py`, the same way `build/verify.py` is.

**Exit**: met. The full suite passes inside the authoritative tier, at the exact versions the ISO
will install, from both lists — 720 passed, 4 skipped, 2 deselected, 0 failed. The two signatures
are `tests/test_structure.py::test_both_signature_schemes_produce_the_expected_bytes`: the BIP84
ECDSA against a pinned known-answer vector, and the BIP86 Schnorr signed by the live backend and
verified by the pure-Python one — no Schnorr vector is pinned, because BIP340 does not promise a
byte-stable signature and pinning one would assert something the spec never said.

**Nothing else is claimed.** The four remaining skips are named in `SKIPS_ALLOWED` and their
subjects arrive at M2 and M5. Nothing here has been booted: M1 needs no image, and every claim in
`docs/threat-model.md` that a running appliance answers is still unanswered until M3.

**Risk**: none of M1's is now live — `libsecp256k1` is settled and `manylinux` is confirmed for all
44 wheels. The next one belongs to M2: whether `mmdebstrap --mode=unshare` works in the CI runner
without `--privileged`.

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

- [x] `mmdebstrap --mode=unshare` builds the rootfs from the pinned snapshot. **No `--privileged`.**
      Verified on `ubuntu-24.04` before anything was built on top of it. Five constraints came out
      of that verification, all of them about apt or mmdebstrap and none about namespaces;
      `docs/boot-pipeline.md` lists them.
- [x] `build/fetch-inputs.sh` — done at M1, see above. `mkiso.sh` consumes the same pool: the
      `deb/appliance` closure is downloaded separately from `deb/harness` precisely so the appliance
      group is complete on its own.
- [x] ~~**Purge the transient `pip` with `--auto-remove`.**~~ **Closed differently, and the reason
      is the group split.** `python3-pip` is a harness-group package, so installing it into the
      rootfs even for one stage is the one thing the split exists to forbid. The wheels are
      unpacked from outside by the build host's pip instead, and `pip`, `python3-wheel` and
      `python3-packaging` are absent by construction rather than by removal. `build/verify.py`
      asserts all three are gone regardless of how it came to be true.
- [x] Install Debian's `linux-image-amd64` (6.12 LTS, the same series the predecessor compiled by
      hand). No kernel compile, no `kernel.config`, no toolchain. **Extracted with `dpkg-deb -x`
      and never installed** — resolving it drags `initramfs-tools` -> `udev` -> `systemd` into the
      pool of an appliance whose first published claim is that it has none.
- [x] Prune the modules tree to the allowlist and regenerate `modules.dep`. **Measured: 20 modules
      ship, 4209 are deleted.** The allowlist this box named is not the allowlist that shipped:
      `simpledrm` does not exist in Debian's kernel, `efifb` and `vesafb` are both built in, and the
      three DRM drivers need firmware this image does not ship — so there is no graphics driver in
      it at all. `build/modules.allow` says why. `modules.dep` is not in the `.deb`, so the first
      `depmod` is what creates the graph the prune runs against.
- [x] A `modprobe` blacklist as a cheap second line. It is never cited as the claim, and
      `build/modprobe-blacklist.conf` says what it is actually for: the window between PID 1
      loading the allowlist and PID 1 setting `kernel.modules_disabled=1`.
- [x] Install the wheel layer with `pip --no-index` from `build/inputs/` — from **outside** the
      image, per the box above. `build/verify.py` fails the build if any package manager is in it.
- [x] Copy the app tree into the rootfs at `/opt/aobs`. Never `pip install` for the app itself.
- [x] Ship the full `console-data` keymap set. **Measured: 0.4 MiB, 216 maps** — they are gzipped,
      and the concern this box existed to test was unfounded. `docs/boot-pipeline.md` has the table.
- [x] `build/init` as PID 1. **Seven steps, not six**: the list this box wrote had nothing that
      loads a module, and with no udev the kernel's usermode helper would have fired at an
      unpredictable moment — including after `kernel.modules_disabled=1`. Loading the allowlist
      explicitly is also what makes "after our devices enumerate" a point in time the script can
      name. No `set -e`; every failure is named on the console and held there forever.
- [x] ~~`cpio | zstd`~~ **`build/mkinitramfs.py | zstd`.** `find | cpio` reads a tree that already
      exists, and a tree that already exists cannot contain `/dev/console`: `mknod` is denied in a
      user namespace, and an initramfs without it gives PID 1 no stdio. The `newc` header carries
      the device numbers as fields, so the writer declares them. Every member is `root:root` with
      `SOURCE_DATE_EPOCH` as its mtime, which is most of what M4 will want, for free.
- [x] `xorriso` into a hybrid ISO: `isolinux` for BIOS, `grub-efi` for UEFI, and the build asserts
      both El Torito records are there. Secure Boot is **not** supported in v0.1.
- [x] Write `docs/test-harness.md` and remove the skip guard in
      `tests/test_structure.py::test_there_is_no_screen_port`.
- [x] `build/verify.py`: every build-time assertion as a pure function, each fed a deliberately broken
      input by the suite to prove it still bites — this is where `tests/test_build_verifier.py` comes
      back, written against the Debian build rather than ported from the Alpine one. Minimum set — no harness package in the rootfs, no
      package manager, `/bin/sh` and `python3` present (the predecessor's first ISO had neither, and
      `build/init` could not have run a line), no `kernel/net`, no module outside the allowlist, no
      getty, the `libsecp256k1` symbols, the RAM floor matching the measured size.
- [x] Derive the RAM floor from the measured unpacked size by a stated formula, re-derived by the
      build so the floor and the image cannot drift apart. **Published against run 34228074569**:
      155 MiB unpacked, 38.2 MiB initramfs, 11.6 MiB kernel, 58.0 MiB ISO, floor **512 MiB**. PID 1
      compares against the unrounded 502, not the rounded 512, because `MemTotal` on a 512 MiB
      machine is under 512 — `docs/boot-pipeline.md` says why both numbers are in the script.

**Exit**: ~~`out/bitcoin-signer-amd64.iso` exists, every assertion passes, and the size and RAM
figures are recorded as measurements rather than estimates.~~ **Met**, run
[34228074569](https://github.com/allisson/aobs/actions/runs/34228074569): the ISO builds on
`ubuntu-24.04` with no `--privileged`, every assertion passes, both El Torito records are present,
and the image produced a signature in each scheme with `ctypes_secp256k1`.

**Nothing in M2 proves it boots.** That is M3, and it is a gate for exactly this reason: an ISO that
builds and asserts cleanly is what the predecessor also had.

---

## M3 — It boots on real hardware and signs a PSBT — **GATE**

The thing the predecessor never did. No test in this repository can tell you whether the kernel boots,
finds a framebuffer and enumerates a camera on a real machine.

**First attempt, and what it cost to learn: the ISO booted and PID 1 could not run its own first
line.** Debian's kernel came up on the target machine, the initramfs unpacked, `/init` started, and
step 1 died with `mount: not found` — because `/usr/bin/mount` is in a package named `mount`, which
was never pinned, while `docs/boot-pipeline.md` said in three places that `util-linux` provided it.
`modprobe` (`kmod`) and `sysctl` (`procps`) were missing behind it, and the `modprobe` one is the
one to remember: it would not have failed anything, it would have reported every allowlisted module
as absent hardware and run the session with no camera and no USB HID driver.

Nothing caught it because nothing was looking: `build/verify.py` asserted `/bin/sh`, `python3` and
the identity files were present and stopped there. It now reads every `step` out of `build/init`
itself and asserts each command resolves on PID 1's own `PATH` in the built rootfs, along with what
the real adapters shell out to. `mount` and `kmod` are pinned, step 5 writes `/proc/sys` directly
instead of pinning `procps` for one write, and `busybox` is gone — it was pinned for a `poweroff`
that PID 1 never called and that Debian's applet-symlink-free build never provided.

The lesson is the M2 exit criteria's, not this milestone's: "the image builds" was measured by
assertions that between them never asked whether the image could execute a single line of PID 1.

**Second attempt: all seven steps ran, and the app could not import itself.** Two root hubs closed,
the UVC camera enumerated, `crng init done`, `exec python3 -m aobs` — and then `ImportError`, with
the kernel panicking on init death exactly as the containment claim says it should. The fault was
`libstdc++.so.6`, which `zxingcpp`, `PIL/_avif` and pillow's bundled `libavif` all link and the
image did not carry. The `.deb` was already in the appliance pool as a dependency of `apt`, which is
not installed: being in the pool is not being in the image.

Apt could not have known. The wheels are unpacked from outside the chroot, so nothing an installed
package declares mentions what they link — the same reason `libsecp256k1-2` is pinned by hand.
`libstdc++6` is now pinned the same way, `build/signcheck.py` imports `aobs.ui.app` inside the
chroot so the build proves the image can start and not only that it can sign, and
`no_unresolved_shared_library` resolves every `DT_NEEDED` in the tree against the image's own
libraries — needed as well as the import check, because Pillow loads its format plugins lazily and
`_avif` is not on the startup import path.

**And it took an unpacked initramfs and a chroot to identify a one-line fault**, because the fault
screen showed `ImportError.` and nothing else. `docs/secret-hygiene.md` now carves out that one
exception type: the import machinery writes the message, and it names a library, not a secret.

**Third attempt: it booted to the keymap picker, and the user could not get off it. Fixed, and the
fourth boot got through.** The appliance drew its first screen — the whole boot chain works — and
then stopped being usable, because the picker never printed its own keys. With the key line added,
the picker was confirmed working on the machine and the session went on past it; the gate itself is
still open, because a boot that reaches the home screen is not a PSBT signed and broadcast. `F10` was bound, `docs/failure-states.md` fixed it, and every
other screen printed a line; this one did not, and it is the one screen where `esc` has nowhere to
go. `HomeScreen` turned out to have the identical defect. Both print their keys now, and a
source-level rule in `tests/test_structure.py` fails the build for the next screen that binds a
function key without rendering it.

**A later boot signed a real transaction, and the transaction half of the exit is met.** Booted from
a live USB stick on a Chromebook, the appliance carried a session end to end: wallet loaded, an
unsigned PSBT built in Sparrow scanned in over the QR channel, reviewed, signed, the signature
scanned back out, and the transaction broadcast on **testnet4** —
[`dcdfc90e38d7299caa00c5c7fb4c01ab73e9d093adee823745d9dbc6466b3a07`](https://mempool.space/testnet4/tx/dcdfc90e38d7299caa00c5c7fb4c01ab73e9d093adee823745d9dbc6466b3a07).
Signet was the network written into the script below; testnet4 is a peer of it in
`docs/network-selection.md` and the substitution changes nothing the run was checking.

**The gate stays open.** The exit is two things joined by an *and*, and only the first is met: there
is no run record, because `docs/boot-checklist.md` has not been written, and none of the boxes below
has been answered as evidence a stranger can read. One machine that boots is also not a
hardware-compatibility claim, and the README does not make one.

Worth recording as a pattern, because all three findings share it: **each fault was a claim the
repository stated correctly in prose and never checked.** `mount` was documented as coming from
`util-linux`; the C++ runtime was assumed to arrive with the closure; the reserved keys were fixed
in a document that assumed screens printed them. The assertions added in this milestone are all of
the same shape — read what the repository already says, and check the artefact against it.

- [ ] **Follow-up, after the gate: drop `pillow` from the appliance.** It is in the image for one
      line — `aobs/ui/qrdecode.py:20` wraps a captured frame as a `PIL.Image` for zxingcpp — and its
      only other use is the *fake* frame source, which is harness-only. In exchange the image
      carries an AVIF decoder and a bundled `libavif`. zxing-cpp's Python API also takes a raw
      buffer with dimensions, which would remove an untrusted-input image decoder from an offline
      signer. Deliberately **not** done alongside the boot fixes: it changes a working decode path,
      and M3 is a gate precisely to stop that.

- [x] **Choose and characterise the target machine**: make, age, BIOS or UEFI, whether Secure Boot can
      be disabled in its firmware, built-in webcam or USB. Nothing below can be judged without this.
      *Answered above and in `docs/threat-model.md`'s* The firmware is not the appliance *section. The
      Secure Boot question does not have its usual answer on this machine: stock coreboot will not
      boot a foreign USB at all, so the firmware was not configured but bypassed, and v0.1 does not
      support Secure Boot on any host. The camera is the machine's **built-in lid webcam**, and
      unlike the keyboard it is genuinely a USB device — it bound through `uvcvideo`, the one UVC
      driver the image ships, which is what the earlier signing run's enumeration recorded.*
- [x] Narrow the generic module allowlist to what that machine actually needs, or record why it stays
      generic. *Recorded in `build/modules.allow`: all four USB host controllers stay. The target is
      xHCI-only, so narrowing would trade "boots on a machine with USB" for "boots on a machine with
      xHCI" and retire every laptop older than about 2010 — the hardware most likely to be free for
      this job — to save a few hundred KiB of a tree already cut from 98 MiB.*
- [x] `docs/boot-checklist.md`: the checks only a booted appliance can answer, published with the ISO.
      *Written. Three row families, because two claims cannot be answered by a boot at all: `I-n`
      inspection boot, `S-n` session boot, `R-n` read the repository. The run-record template is its
      last section rather than a separate file — a template that lives away from its procedure
      drifts from it, which is this milestone's recurring fault in miniature.*
- [ ] Run it. Boot the stick, walk the keymap picker, generate a wallet, export the xpub by QR, build
      an unsigned PSBT in a watch-only wallet, scan it, review it, sign it, scan the signature back,
      broadcast on signet. *Done on testnet4 — see the signing run above. The row stays open because
      it is the run **record** that closes it, not the run: no verdict per step has been written
      down, and the checklist it would be written against does not exist yet.*
- [ ] With the wallet loaded, confirm the three ways in read as unavailable — *one wallet per
      session* beside each row and the note under the list — and that `F10` on one does nothing.
      Photographed with the console check below, which is the boot that can answer whether the
      right-aligned reason and the dimmed row survive on the panel.
- [ ] Pull the boot medium out mid-session and keep signing. That is the cheapest check of the
      amnesia claim, and it is only a claim until someone has done it.
- [ ] **Check what the console can actually draw**, on one screen showing all of it. Both halves
      are fixed by `docs/console-appearance.md`. **Half-bright is already answered — it renders**,
      seen on the home screen on the target machine's BIOS path, where the six rows that need a
      wallet are visibly greyer than the four that do not. One panel and one framebuffer driver, so
      the worded reason on those rows stays. What is left is whether the console has a **glyph** for
      the five characters outside the built-in font's repertoire: `⚠` (`aobs/ui/reviewtext.py:48`, the NOT PROVEN
      marker), `▮` and `▯` (`aobs/ui/scanning.py:45`, the slot map — the whole of the scan screen's
      feedback), and the two dashes. Same pattern as the three faults above: *a claim the repository
      stated correctly in prose and never checked.* Replacing the glyphs is deliberately **not**
      done in advance — two of them sit inside row templates that `docs/review-screen.md` and
      `docs/scan-feedback.md` fix character by character, and the check is cheaper than the guess.
- [ ] Check each claim in the image, **and say which boot each check belongs to** — the row as
      written was not runnable, because a session has no prompt and the checks were listed as if it
      did. `docs/overview.md` now carries the split; the checklist has to repeat it per row.
      - In an `init=/bin/sh` boot: `cat /proc/mounts`, `ls /sys/block`, `command -v ip`,
        `ls /lib/modules/*/kernel/net`, `ls /lib/modules/*/kernel/drivers/usb`.
      - **Not** `ls -d /proc/[0-9]*` and **not** `cat /sys/bus/usb/devices/usb*/authorized_default`:
        that boot replaces PID 1, so the count is the stranger's own shell and `build/init` never
        ran to set the hubs. Both are source-level checks against `build/init` and
        `build/verify.py`, and the run record says so rather than printing a number that looks like
        evidence and is not.
      - In an ordinary session: pull the boot medium out and keep signing.
- [ ] Record the answers as a **boot-checklist run record** — the checklist is the procedure, the run
      record is the evidence, and only the second is something a stranger can check. Verdicts are
      *pass*, *fail* and *deviated*; the third is load-bearing.
- [ ] Write `docs/threat-model.md`. **Deferred here from M2 and scheduled nowhere until now**, which
      in this repository means it was not going to happen. M3 is where it belongs: it is the first
      milestone with a real machine to be specific about, and the claims it has to state at their
      true strength are the ones a boot either supports or does not.
- [ ] Check the two claims a build cannot: that the modules tree really does leave the machine with
      no network interface, and that the graphics decision holds. `build/modules.allow` ships no
      DRM driver on the argument that `efifb` and `vesafb` are built in and sufficient. That
      argument has never met a screen.

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
- ~~**Revisit the keymap set** if the measured RAM cost of full `console-data` turns out to be
  absurd~~ — **closed, with the number in hand: 0.4 MiB, 216 maps, gzipped**, against a 512 MiB
  floor. Measured in the built rootfs at M2, run 34173912095. There is nothing to revisit and the
  picker keeps every map.
- **Narrow the module allowlist** per additional machines as boot-checklist run records accumulate.
- Multisig is **out of scope** and is not a deferral. A multisig keychain is not a Wallet in this
  project's vocabulary.
