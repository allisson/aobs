# Test harness

How the application is run and tested without the LiveCD, and what is left that only a boot can check.

The appliance's real environment is a kiosk with a webcam, no filesystem and no network. A dev host is
none of those things — so this document is mostly about **where the seam sits**, because that is what
decides how much of the appliance is reachable from a laptop.

[#3](https://github.com/allisson/aobs/issues/3) already discharged the ticket's stated dependency, and
generously: Textual's `run_test()` drove the prototype headless with no display of any kind, pressing
keys and asserting widget state. The display side of this harness needs no framebuffer, no VM and no X.

## The seam

**One deep core module with a pure interface — bytes in, value objects out — and four narrow ports
around it.**

The core owns wallet derivation, PSBT parse, the proof rule and output categorisation, signing,
entropy mixing, the encrypted-wallet container, and UR fragment encode/decode. It performs **no I/O**
and takes its inputs as arguments: `review(psbt_bytes, wallet) -> Review`, `mix(sources) -> Entropy`.

Four ports, each with exactly two adapters — which is what makes them real seams rather than
hypothetical ones:

| port | real adapter | fake adapter |
|---|---|---|
| `FrameSource` | V4L2 `mmap` capture (#6) | frames from image files |
| `Keymap` | `loadkeys` (#12) | records what was applied |
| `EntropySource` | `getrandom`, camera, dice (#8) | fixed bytes |
| `Power` | forced power-off (#10) | records the call |

**The display is not one of them, and that is a correction.** A `Screen` port was declared here
with two adapters — "Textual on the console" and "Textual `run_test()`" — and those are the *same*
application under two drivers, not two implementations of an interface. The port sat between two
halves of one thing, and its fake could only render `str(view)` through a throwaway one-widget app
because there is no honest `next_key()` inside a running Textual event loop.

So **`SignerApp` is the display seam**. Tests drive the real application headless through
`run_test()`, pressing real keys against real screens; the console adapter runs the very same
object. `Keymap` took the vacated fourth slot, and it is a port for the reason `Screen` was not:
applying a keyboard layout genuinely has two implementations, and a test has to be able to watch
which layout was applied — `docs/boot-pipeline.md` calls a passphrase typed through the wrong map
the worst failure mode in the appliance.

The deletion test passes: delete the core and the review logic reappears in every caller; delete a port
and nothing vanishes, which is correct — ports are meant to be thin.

**The consequence that matters: the PSBT review model is testable with no fixtures beyond bytes.** The
proof rule, the three output categories and the headline number are pure functions of PSBT bytes plus a
wallet. That is the part where a bug loses money, and it needs no camera, no screen and no node.

### Layout

`aobs/core/`, `aobs/ports/`, `aobs/adapters/`, `aobs/ui/`, `tests/`, `fixtures/`, `build/`.

One rule carries weight and is enforced by a test: **`core/` may not import any adapter,
`aobs.ui` or `aobs.ports`.** `aobs/ui/` is on the list the core is guarded *from*, not on the list
that guards it. Left
implicit, the first implementation session puts I/O inside the core and the seam is gone before anyone
notices. Structure *inside* `core/` is an implementation-plan question and is deliberately not fixed
here.

## Faking the camera

**Actual image frames, never decoded payload strings.**

Faking at the payload level skips `zxing-cpp` — the exact component #6 chose, and the one most likely
to surprise us — and would prove only that our parser can read our own output.

**The loopback test is the highest-value test in the harness.** Take a PSBT, encode it to UR fragments,
render each to a QR image, feed the images through the real decoder, reassemble, assert the result is
**byte-identical** to the input. Encode, fountain assembly, decode and reassembly in one pass, with no
hardware.

It proves self-consistency, not interop. So alongside it: **a checked-in corpus of frames captured from
Sparrow, Green and Blue Wallet.** #4's format decisions came from documentation; that corpus is what
turns them into a regression test, and it is the difference between *we read the spec correctly* and
*we read their output correctly*.

## Asserting the display

**Two levels, and pixels are not one of them.**

Assert on the **emitted payload** — the UR strings the app would render — which is what actually has to
be correct. Use `run_test()` for interaction and widget state, with screenshot export as a
human-reviewed artifact, **never as a passing/failing assertion**. Pixel-diffing a TUI produces tests
that fail on a font change and pass on a wrong address.

One assertion here is not about layout at all. **#3's escape-injection rule**: all attacker-controlled
text must be escaped before it reaches the terminal, and #3 said explicitly that this must be a tested
rule rather than an assumed Rich behaviour. Feed a PSBT carrying ANSI escapes, assert they render
inert. It is a security test and it lives at this seam.

## Fixtures and test seeds

**One generator script, checked in, deriving everything from the published BIP39 test-vector
mnemonic** — the same one the #3 prototype uses at `m/84h/1h/0h`. Fixtures are generated artifacts
committed next to the script, so a reviewer regenerates and diffs rather than trusting a blob.

Mainnet fixtures are allowed and necessary — mainnet review behaviour is exactly what needs testing —
but only from that published vector mnemonic, which is public and so is not a live wallet. To stop that
decaying, **a test asserts every fixture's master fingerprint is in a short allow-list**, so a
contributor pasting in a PSBT from their own wallet fails CI instead of quietly committing a real xpub.

### The adversarial corpus

**A named corpus, one file per attack, each with its declared expected verdict.** #11 established that
the watch-only wallet is Tier 1 and sends hostile bytes every session; this is where that stops being
prose. It is the Tier 1 defence, executable.

Minimum contents, each tracing to a closed decision:

- An output whose `PSBT_OUT_BIP32_DERIVATION` claims a path that does not reproduce the script — **the
  change-address attack**. Expected: NOT PROVEN, counted as leaving, raising the headline number.
- A change index outside the derivation window.
- Missing `witness_utxo` on one input of a taproot spend.
- A non-`SIGHASH_ALL` flag on one input among many.
- A network mismatch.
- An output label carrying ANSI escapes.
- A many-input PSBT, for frame-count behaviour.
- A structurally malformed PSBT.

Keeping them in one place with declared verdicts means **a new refusal rule is added by adding a
file**, not by hunting through test modules for where its siblings live.

## Property-based testing

**Round-trips only.** Hypothesis over the UR fountain encode→decode cycle, and over the
encrypted-wallet container encode→decode including **every Argon2id parameter value the format
admits**.

The reason is #7's finding, and it is specific: every real failure across Krux, SeedSigner and
Specter-DIY was **plumbing, not cryptography** — a misused CBC IV, a heap overflow, a lossy iteration
encoding. #9 already committed to round-trip fixtures on exactly that basis; a generator is the honest
way to keep that promise, where a hand-written table drifts the moment the format gains a field.

**Do not property-test the review model.** Generating valid-but-interesting PSBTs is a research
project, and the adversarial corpus is the better instrument — its cases are chosen because an attacker
would choose them, which no generator discovers.

## Running it

**One tier.** An `alpine:3.24` container installing **the exact apk versions the ISO installs**
(#12), so a version skew in `zxing-cpp`, `cryptography` or `libsecp256k1` fails here rather than on
the appliance.

    docker build -f build/Dockerfile.test -t aobs-test .     # only when the pins change
    docker run --rm -v "$PWD:/src" -w /src aobs-test         # the dev loop, ~20 s

The bind mount is what makes this the loop a developer lives in: the image carries the pinned
userland, the working tree comes from the host, and **no rebuild is needed to run an edit** — only a
change to `build/apk-versions.txt` requires one. CI uses the `COPY` baked into the image instead, so
what it judges is the tree as pushed.

**This used to be two tiers, and the second one was `uv` on the host Python — "the loop a developer
lives in".** It was retired in #35 when it stopped being the fast one. `embit` is vendored from git
and carries no prebuilt binary (#34), so a host with no system `libsecp256k1` falls back to
`py_secp256k1`: measured at **5 m 45 s against the container's 20 s**, a tier 17x slower than the one
it existed to be faster than. It also tested PyPI-resolved libraries on a non-Alpine Python — a
configuration the appliance is never in.

`uv run --extra test pytest` still works and is still useful for a debugger or an IDE test runner.
It is **not a tier**: nothing in CI runs it, and no claim about the appliance rests on it. The one
assertion that would be wrong there — which library performs the EC — is guarded by
`AOBS_AUTHORITATIVE_TIER=1`, which only `build/Dockerfile.test` sets, so the suite passes on a host
without the library instead of failing for the wrong reason.

Recovering the host speed is **harder than it sounds, and on macOS does not currently work at all**
— recorded so nobody re-derives it:

- `ctypes.util.find_library` on macOS searches `/usr/local/lib` and `/usr/lib`, **not**
  `/opt/homebrew/lib`, so a `brew install secp256k1` is invisible to embit on Apple Silicon.
  `DYLD_LIBRARY_PATH` does not rescue it either: SIP strips the variable before Python sees it.
- Homebrew currently ships **0.8.0, which embit cannot use for taproot at all** — upstream removed
  `secp256k1_schnorrsig_sign` there, and embit binds that name. A developer who did force it onto
  the path would get a native backend with BIP86 signing broken.
- On a Linux dev host a distro `libsecp256k1` in the **0.4–0.7** range works and is found normally.

The reason that one assertion is guarded rather than simply always-on: which library performs the EC
is a claim about the *appliance*, so it is checked where the appliance's environment is reproduced.
Run off-container it would only ever have been testing whether a PyPI wheel shipped a prebuilt blob
for that platform — the very blob #34 decided the appliance must not use.

One test catches an ISO-only failure without an ISO. #12 noted that `CONFIG_NET=n`
removes `AF_UNIX` as well as `AF_INET`; this is that check, runnable on a laptop — but it is **not**
an import-graph assertion over the running app's module closure, which is what this document used to
call for. That form cannot pass and never could: `asyncio`, which Textual *is*, imports `socket` and
`ssl`, and `pathlib` on Python 3.12 imports `urllib.parse`. Asserting their absence would fail on
every kernel while proving nothing about the one the appliance boots.

Two assertions replace it, and between them they say the thing that was meant:

- **The core's closure stays clean** — the core is pure and reaches for none of it, so the original
  assertion still holds where it is true.
- **No module in the app tree imports the network stack**, and **a whole session constructs no
  socket**: the app is driven from the picker to the home screen and out through `F12` with
  `socket.socket` patched to raise. That is the honest form of the claim, because `import socket`
  succeeds on a `CONFIG_NET=n` kernel and only calling `socket()` fails.

## Regtest end-to-end

**An opt-in suite, outside the default loop.**

Fixture round-tripping cannot tell you a signature is *valid*. A wrong sighash produces a perfectly
well-formed signature that only a validator rejects — and **BIP86 taproot is exactly where that
happens**, because the sighash commits to all input amounts and scripts (#11). Every appliance-side
check would pass while the transaction is unspendable.

So: build a real PSBT with `walletcreatefundedpsbt`, sign it with the core, then `finalizepsbt` +
**`testmempoolaccept`**. Not broadcast-and-confirm — mempool acceptance asserts the same thing without
generating blocks. Opt-in, so a contributor with no node still gets the full default suite.

## What only a boot can check

Everything above runs without an ISO. The rest is [`boot-checklist.md`](boot-checklist.md), **published
with the ISO rather than kept internal** — the items there are precisely the ones #10 and #14 promised
as *verifiable*, and a claim whose verification procedure is unwritten is not really verifiable.

#10 committed to the first of them going in the published README. That checklist is what keeps the
promise, and running it is what a release means, given release engineering itself is out of scope.
