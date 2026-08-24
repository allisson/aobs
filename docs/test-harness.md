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
| `Screen` | Textual on the console (#3) | Textual `run_test()` |
| `EntropySource` | `getrandom`, camera, dice (#8) | fixed bytes |
| `Power` | forced power-off (#10) | records the call |

The deletion test passes: delete the core and the review logic reappears in every caller; delete a port
and nothing vanishes, which is correct — ports are meant to be thin.

**The consequence that matters: the PSBT review model is testable with no fixtures beyond bytes.** The
proof rule, the three output categories and the headline number are pure functions of PSBT bytes plus a
wallet. That is the part where a bug loses money, and it needs no camera, no screen and no node.

### Layout

`aobs/core/`, `aobs/ports/`, `aobs/adapters/`, `aobs/ui/`, `tests/`, `fixtures/`, `build/`.

One rule carries weight and is enforced by a test: **`core/` may not import any adapter.** Left
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

**Two tiers.**

*Fast local*: `uv` on the host Python — the loop a developer lives in. The prototype already
established `uv run --with` works for this.

*Authoritative*: an `alpine:3.24` container installing **the exact apk versions the ISO installs**
(#12), so a version skew in `zxing-cpp` or `cryptography` fails there rather than on the appliance.

One local-tier test catches an ISO-only failure without an ISO: **an import-graph assertion that the
app's module closure never pulls in `socket`, `ssl`, `multiprocessing` or `urllib`.** #12 noted that
`CONFIG_NET=n` removes `AF_UNIX` as well as `AF_INET`; this is that check, runnable on a laptop.

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
