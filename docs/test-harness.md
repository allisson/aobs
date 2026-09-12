# Test harness

The four tiers, and what each one is authoritative for.

Written fresh for Debian rather than adapted from the Alpine predecessor's, because the subject
changed out from under that document: the authoritative tier is now a `debian:trixie-slim` container
installing the exact pinned versions the ISO installs, with a gate that refuses to start against the
wrong EC backend and a skip policy keyed by node id. None of that existed before M1.

## The four tiers, and the one rule that orders them

| tier | what it is | authoritative for |
|---|---|---|
| **dev loop** | `pytest` on a contributor's machine, usually one file | nothing. It is a fast signal, not evidence |
| **the authoritative tier** | `build/Dockerfile.test`, run in CI on every push and pull request | the application: every claim about what the code does |
| **build-time assertions** | `build/verify.py`, run by `build/mkiso.sh` | the image: every published claim about what is and is not in it |
| **the boot checklist** | a human, a stick and a real machine | everything a running appliance answers and nothing else can |

**A green suite on a dev machine is not evidence, and this is not a style preference.** Without a
loadable `libsecp256k1` the vendored embit silently resolves to `py_secp256k1` and every EC operation
runs 50-80x slower through the code path `docs/boot-pipeline.md` forbids on the appliance — while
passing. Measured: 1.73 ms per `ec_pubkey_create` against tens of microseconds, and a 22-minute suite
against roughly seven. The cost is the visible half; the other half is that such a run exercises the
forbidden path and reports green.

Homebrew's `libsecp256k1` 0.7 counts as "without". It dropped the deprecated alias embit's loader
binds, so the library loads and embit rejects it — and `secp256k1.py` binds inside a bare `except:`,
so a present-but-unloadable library produces a pure-Python signer and no error at all.

So the rule is: **a claim about the suite comes from the authoritative tier**. Locally, run the files
you are working on.

### The tier cannot report green from the wrong backend

Two halves, both in `tests/conftest.py`, and the first one runs everywhere:

- `pytest_report_header` names the interpreter and the **live** backend on every run in both tiers,
  and adds a line saying the run is not evidence about the appliance whenever the backend is the
  fallback. That is what stops a milestone being checked off from a green `py_secp256k1` run.
- `pytest_sessionstart` is the tier half. With `AOBS_AUTHORITATIVE_TIER=1` and any backend other
  than `ctypes_secp256k1`, **the session does not start** — because a green report from 700 tests
  through the fallback looks exactly like a good one.

There is no `AOBS_ALLOW_PURE_PYTHON_EC` escape hatch. An escape hatch on this one *is* the failure
mode.

The backend is read from `ec_pubkey_create.__module__`, never from whether a `.so` is on disk.

### No test may be skipped in this tier, and the mechanism is a list of names

`SKIPS_ALLOWED` in `tests/conftest.py` names each permitted skip **by node id**, with the milestone
that deletes it. **Two** things fail the session: a skip nobody named, and an entry that no longer
skips.

The second matters as much as the first. A stale entry is a standing exemption nobody notices has
stopped applying, so the next skip of that test passes unremarked.

A count cannot do this job. It cannot tell a fifth skip from one of the four *moving*, and it cannot
notice an entry that has stopped skipping. Staleness is judged only on a whole-suite run, because the
dev loop runs one file in the same container.

`skip_policy_violations()` is a pure function and `tests/test_tier_gates.py` feeds it its own broken
inputs, the same way `tests/test_build_verifier.py` does for `build/verify.py`.

## The seam

The core is pure and the world is behind five ports. `aobs/core/` may not import any adapter,
`aobs.ui`, or `aobs.ports` — a test enforces it.

| port | the appliance's adapter | the harness's adapter |
|---|---|---|
| `FrameSource` | V4L2 capture from the camera | image files and recorded frame sequences |
| `Keymap` | `loadkeys`, against the image's own `console-data` tree | a recorder that reports what was asked for |
| `EntropySource` | `getrandom(2)` | fixed bytes, so a derivation is reproducible |
| `Power` | `reboot(2)` with `RB_POWER_OFF` | a recorder that captures the call instead of making it |
| `UsbBus` | every device's `authorized` under `/sys/bus/usb/devices` | a fixed set of readings, so a Late arrival can be staged |

**There is no `Screen` port, and its absence is deliberate.** Its two adapters would have been
"Textual on the console" and "Textual `run_test()`" — the same application under two drivers, not two
implementations of an interface. The application *is* the display seam.

**`UsbBus` is the fifth, and it had to argue past two precedents to get here.** `Screen` was refused
for having one implementation under two drivers; `release` was refused a port in `aobs/ui/app.py`
because *reading one file has one implementation, and the seam the tests need is this value being
passed in*. Neither applies. A sysfs walk and a canned set of readings are two implementations, the
way `getrandom(2)` and fixed bytes are. And unlike `release`, the bus is asked **again on every
home-screen composition** — a value passed in once cannot answer differently the second time, and
answering the second time is the entire point (`docs/failure-states.md`, *A late arrival is reported
and never interpreted*).

A fake must never be reachable from the appliance. `aobs/__main__.py` imports no
`aobs.adapters.fake` module and reads neither `os.environ` nor `sys.argv`, so there is no flag and no
fallback that could select one. A fake `Power` does not power off and a fake `EntropySource` returns
a deterministic counter: an appliance started with either would look correct on screen and be
worthless in every claim it makes.

## What the harness fakes, and how

**The camera** is an image file or a directory of frames fed through `FrameSource`. Decoding is the
real `zxing-cpp` against real pixels — the fake is the *source*, never the decoder, because a fake
decoder would test the harness's idea of a QR code rather than a QR code.

**The USB bus** is a list of late arrivals fed through `UsbBus`, and the fake counts how many times
it was asked. That count is the point: the home screen's contract is that it re-reads on every
composition, and a test that recomposed by hand would pass even if `on_screen_resume` had stopped
firing.

**A camera that is absent** is staged the way the appliance fails, not the way the harness finds
convenient. An empty `FrameSource` is a device that answered and produced nothing — `NO_FRAMES` —
while a machine with no video node raises `NO_CAPTURE_DEVICE` before anything is opened. The two
reach different sentences, so staging one while meaning the other tests a screen the appliance
never shows.

**The display** is asserted through Textual's `run_test()`, against the geometry the appliance
actually has: 85 columns × 43 rows, which is the QR display and the floor `aobs/ui/geometry.py`
enforces. Nothing in the boot path fixes a console size — see
`docs/adr/0003-the-console-is-enforced-not-requested.md` — so the floor is the appliance's own.

**Fixtures** live in `fixtures/` and are produced by the one script that generates them all,
`fixtures/generate.py`, so a fixture is never a file somebody once made and nobody can remake.

**The adversarial corpus** is the set of PSBTs built to make the review screen lie — outputs that
look like change and are not, addresses that differ only in a way a glance misses. `docs/psbt-review-model.md`
fixes the proof rule those tests hold the code to.

**`fixtures/wallet_frames/` is empty**, and the tests that read it skip for that reason and are named
in `SKIPS_ALLOWED`. They exist ahead of their corpus deliberately: the parametrised test collects one
item that cannot run, and its node id changes to real capture ids the moment frames are added —
which is precisely when that entry should stop matching.

## Property-based testing

Used where a round trip has an inverse — UR encode/decode, PSBT parse/serialise, mnemonic
encode/decode. Hypothesis generates the input; the assertion is that the inverse returns what went
in. These are the tests that find the case nobody thought of, which is why they are pointed at the
codecs rather than at the screens.

## The regtest suite

`tests/test_regtest_e2e.py` needs a `bitcoind` and is **deselected by default**, so a contributor
with no node still gets the full default suite. It is opt-in and no runner runs it: the two
deselected items in every CI report are these.

## Running it

```sh
# The authoritative tier: what a claim about the suite comes from.
sh build/fetch-inputs.sh                       # once, and only when the pins change
docker build -f build/Dockerfile.test -t aobs-test .
docker run --rm aobs-test python3 -m pytest -rs

# The dev loop: the files you are working on. Not evidence.
pytest tests/test_review.py
```

`-rs` stays in CI so the same run prints why each permitted skip skipped.

**The commands above are the whole procedure on any host, including an arm64 Mac.** They were not,
until #19 ran them there: `build/Dockerfile.test` resolved `debian:trixie-slim` to the host's
architecture while `build/fetch-inputs.sh` had fetched an amd64 closure, and the build died on
`dpkg:arm64 Conflicts dpkg:amd64`. The `FROM` line now pins `--platform=linux/amd64`, which is the
pin `fetch-inputs.sh` already applies to its own two `docker run` calls and to the wheels. Nothing
here is a recommendation about which machine to use — an arm64 tier would be judging this code
against a different libc and a different `libsecp256k1`, and the pin is what makes that
unreachable rather than merely unlikely.

**Measured, in the authoritative tier on CI's native x86_64:** 876 passed, 3 skipped, 2 deselected,
0 failed, in 416.23 s, the run reporting `python 3.13.5, EC backend ctypes_secp256k1, authoritative
tier yes` — run [34706000285](https://github.com/allisson/aobs/actions/runs/34706000285) on
`fbf563f`, from [#37](https://github.com/allisson/aobs/pull/37).

**Every figure here names its run, and that is the format rather than a courtesy.** The previous
entry — 720 passed, 4 skipped in 427 s, run
[34166600257](https://github.com/allisson/aobs/actions/runs/34166600257) on
[#3](https://github.com/allisson/aobs/pull/3) — was written as *what the tier reports* and went
quietly wrong 156 tests later, which is how #19 found it. A measurement is only ever evidence that
this tier ran green on that commit, so the commit is part of the measurement.

The same image under qemu on an arm64 Mac gave the same 876/3/2 in 509.17 s. That is corroboration
and is **not** what a claim cites.

## What only a boot can check

No test in this repository can tell you whether the kernel boots, finds a framebuffer, or enumerates
a camera on a real machine. Neither can any of the build-time assertions: they check what is in the
image, never what happens when it runs.

`docs/boot-checklist.md` holds those checks and is published with the ISO. The checklist is the
procedure; the **run record** is the evidence, and only the second is something a stranger can check.
Verdicts are *pass*, *fail* and *deviated*, and the third is load-bearing.

> Neither exists yet. They arrive at M3, which `docs/roadmap.md` makes a gate: the predecessor of
> this repo never cut a release and was never booted on real hardware, and that is the failure the
> ordering exists to prevent.

## The verifier a stranger runs

`verify-release.sh` is what somebody who trusts nobody runs against a published release:
`sha256sum` and `gpg`, nothing else, by construction and by test.

> It does not exist yet either. It arrives at M5, driven in CI against a fixture release signed with
> scratch keys in a throwaway `GNUPGHOME` — the one artifact aimed at people who trust nobody is the
> last one to be tested against a stand-in.
