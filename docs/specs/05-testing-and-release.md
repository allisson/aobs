# 05 — Testing, gates and release

Sources: [#3](https://github.com/allisson/aobs/issues/3),
[#8](https://github.com/allisson/aobs/issues/8),
[#10](https://github.com/allisson/aobs/issues/10),
[#13](https://github.com/allisson/aobs/issues/13),
[#20](https://github.com/allisson/aobs/issues/20),
[#21](https://github.com/allisson/aobs/issues/21),
[#23](https://github.com/allisson/aobs/issues/23),
[#24](https://github.com/allisson/aobs/issues/24),
[#25](https://github.com/allisson/aobs/issues/25),
[#27](https://github.com/allisson/aobs/issues/27),
[#32](https://github.com/allisson/aobs/issues/32).

## 1. Coverage

**`cargo llvm-cov` on region coverage, not line coverage.** Line coverage marks a partially-taken
branch as covered, which would let the rejection policy report green with half its arms untested.

Two gates:

- `aobs-core` ≥ **95%** overall.
- The nine components below ≥ **98%**.

**The nine at 98%:**

1. PSBT validation and the whole rejection policy
2. Derivation and the change re-derivation byte-compare
3. Sighash computation and the signing call into `secp256k1`
4. The entropy mixing function
5. BIP39 mnemonic ↔ entropy conversion and checksum (including passphrase handling and NFKD)
6. Backup crypto — Argon2id parameters, ChaCha20-Poly1305, header and AAD framing
7. The UR decode clamping wrapper and the payload-class check
8. The zeroizing secret types
9. **Address and amount formatting**

Nine is the non-obvious one and it is deliberate. Formatting looks like presentation, but the review
screen *is* the mitigation, and Coldcard's 2019 receive-path display manipulation was a vulnerability
**in the display layer** — the review screen itself was the bug. A chunking routine that drops a
character or renders an address ambiguously defeats every check above it.

**The shell crate is excluded from the gate**, which is only honest if the shell stays thin — hence
the rule that keeps it so: *the shell contains no decision about money and no branch on a validation
outcome; it marshals.* Backed by a mechanical dependency check, not by review.

**Legitimate exclusions are exactly three:** derive-generated code, `unreachable!()` arms guarding
invariants, and the shell crate.

**Forbidden: per-function or per-line coverage opt-out attributes in source.** That is how a number
gets met by editing the denominator instead of writing tests. Code that cannot be covered moves to
the shell or is deleted.

> **Coverage is necessary, not sufficient.** The fuzz targets, BIP vectors, property tests and the
> QEMU provenance gate are *separate* CI gates, not a subset of the coverage run. A repository can
> sit at 98% and still ship Coldcard's linkage defect.

## 2. Vectors

| Suite | What it pins |
|---|---|
| **BIP-32** | Derivation across all four families — the tables BIP-49, BIP-84 and BIP-86 publish for the `abandon … about` mnemonic, plus the master `xprv`/`xpub` BIP-86 publishes for it, which pins seed and master derivation too. **BIP-44 publishes no vectors at all**, read from the document rather than assumed, so that family is cross-checked against the same path derived from BIP-86's published root through the dependency's own API, and the test file says so. |
| **BIP-39 English, all five lengths, passphrase `"TREZOR"`** | Mnemonic ↔ entropy, checksum, seed derivation. |
| **BIP-39 Japanese, passphrase `㍍ガバヴァぱばぐゞちぢ十人十色`** ([bip32JP](https://github.com/bip32JP/bip32JP.github.io/blob/master/test_JP_BIP39.json)) | **Mandatory, not optional.** `㍍` (U+334D) is a *compatibility* character that decomposes under NFKD and is left untouched by NFD. These are the only vectors in the suite that distinguish NFKD from NFD — an implementation reaching for the wrong form passes everything else. |
| **BIP-174**, including **invalid vector 5** | The PSBT parser, and the duplicate-key refusal we now inherit from the dependency. |
| **BIP-340 / BIP-341** | Taproot key-path signing and sighash. The files are committed verbatim rather than transcribed, and **the suite is BIP-341's seven key-path cases rather than BIP-340's rows**: only index 0 of `bip-0340/test-vectors.csv` has all-zero auxiliary randomness, where **all seven of BIP-341's key-path signatures do** — which is exactly `sign_schnorr_no_aux_rand`, established against an independent implementation rather than read ([#82](https://github.com/allisson/aobs/issues/82), `02-core.md` §8a). Three of the seven carry a non-trivial merkle root, which is what makes the *tweak* asserted: a wrong tweak still produces a valid BIP-340 signature, under a key that does not spend the output. |
| **BIP-380** | The four exported descriptors' checksums. |
| **BCR-2020-015** | The `crypto-account` CBOR, against the spec's own example encodings. |
| **RFC 9106** | Argon2id known-answer vectors, plus differential testing against the PHC reference — this is the unaudited half of the crypto. |
| **Entropy mixing, authored by us** | No supplements (asserting `entropy == csprng` byte for byte), dice only, camera only, both, and an empty dice string treated as *absent* rather than as a zero-length field. |
| **Backup format** | Round-trip at each of the five lengths; AAD tamper on every header field; reserved bits non-zero; out-of-range `entropy_len`; unknown version. |
| **Address verification** | Derived addresses across all four families matched in both lowercase and uppercase QR forms. |
| **The fee warning** | Fee exactly equal to the payment total (the boundary — the rule is `≥`), a consolidation with no non-change outputs (undefined, silent), change plus a one-satoshi payment, and a legitimate high-congestion transaction well under the ratio that **must stay silent**. |
| **Amount and fee writing, authored by us** | The rules `04-screens.md` §11.2.1 settles, at their boundaries: zero, one satoshi and `Amount::MAX` in the eight-decimal BTC form; the satoshi grouping at each group-boundary length; a fee equal to the amount paying (`100.000%` — the same `≥` boundary the fee-warning row walks); a consolidation with no non-change outputs (no percentage at all, rather than a zero or a dash); and the two round-to-zero bounds, a non-zero fee that would print `0.0 sat/vB` and a non-zero ratio that would print `0.000%`. The extremes are where a formatter turns into an evaluator (`02-core.md` §9). |
| **Word entry, authored by us** | `02-core.md` §4's six behaviours *through* the reducer rather than by inspection: four characters of **every one of the 2048 words** resolving to that word, a word that is also a prefix (`add` against `address`) committing as itself, a unique prefix committing **nothing** without a space, the three off-list keystroke classes — a capital, a digit, a letter with a diacritic — and both correction keys. Plus the type-back's own half: a wrong word refused **by position** with every other slot intact, the last word refused the same way, and the same code driving a wordlist that is not BIP-39's. |
| **Passphrase** | Idempotence `nfkd(nfkd(x)) == nfkd(x)`; no-trim — `"a"`, `" a"` and `"a "` derive three distinct seeds; 128 bytes accepted and 129 refused at the shell. |
| **Network, authored by us** | **The master fingerprint of one seed is byte-identical on mainnet and testnet** — the identity screen's only network signal rests on this and it is read from the BIP-32 text rather than measured, so the assertion is the alarm if it ever stops holding. Plus: the same seed derives different account xpubs and different addresses across the two; a testnet PSBT against a mainnet-loaded wallet lands on the "no input is ours" refusal carrying the coin-type-disagreement variant. |

## 3. Property tests

- **The safety proof for entropy mixing:** the mixing function is **injective in the `csprng_32`
  argument for every fixed supplement**. Uniform in, uniform out — verified rather than argued.
- BIP39 round-trip: `entropy → mnemonic → entropy` at every accepted length.
- Address formatting: chunking is lossless, and the concatenation of the rendered groups equals the
  address.
- **The retype places nothing we did not generate.** For any sequence of keystrokes, every
  filled slot holds the word the generated phrase has at that position, and the state stays
  inside its fixed arrays. The first half is the type-back's whole safety claim, asserted
  against sequences nobody wrote a case for; the second is because an out-of-bounds index in a
  reducer is a session ending mid-transcription.
- **No sequence of scanned symbols escapes the transport bounds.** For any sequence of QR
  symbols — parts from an honest animation, parts forged field by field, and text that is not a UR
  at all — every outcome a `ur::Scanner` produces is inside `03-transport.md` §3's bounds: a
  clamped `seqLen` at most 64, fragments resolved never above it, parts taken in never past the
  budget, and an accepted payload inside its class's length rule. It is `05` §4's first fuzz
  target's assertion, running on every commit rather than in the nightly job.
- **The outbound animation never refuses.** For every message length, at the fragment length
  `03-transport.md` §9 settles, no emitted part exceeds v27-L's 2 132-character budget — charging the
  sequence number its full `u32` width rather than the one it happens to be emitted at. This is the
  assertion that catches a fragment length raised without redoing §9.1's arithmetic, and it is why the
  length is a parameter rather than a constant the test cannot vary. **It stands as of
  [#82](https://github.com/allisson/aobs/issues/82)**, in two halves: §9.1's closed form is asserted
  character for character against what `ur` 0.5.2 emits — which is what earns the right to charge
  every field its `u32` maximum instead of sweeping what the encoder happens to produce — and the
  ceiling is then swept over every message length inside the 64 KiB transport bound and over
  fragment lengths either side of 960, where the sweep's own boundary is that **1 019 is the largest
  value that clears the budget at all.**

## 4. Fuzz targets

Three we write, one we skip, one deliberate exception.

1. **The fountain decoder through our clamping wrapper** — `fuzz_target!(|parts: Vec<&str>|)` driving
   `Decoder::receive` to completion. Asserts no panic, termination, and **no allocation above the
   transport bounds**. Highest-value surface in the transport layer, and upstream ships no target for
   it.
2. **The PSBT parser** on raw bytes — no panic, bounded allocation.
3. **The validator**, structure-aware and seeded with our own test key material, asserting the three
   invariants that matter: *it never accepts a transaction containing an output classified as ours
   whose scriptPubKey we did not ourselves produce*; — added by
   [#113](https://github.com/allisson/aobs/issues/113) — *every input it accepts as ours is one
   `sign` produces a signature for, in the field that input's family is signed from*; and — added by
   [#115](https://github.com/allisson/aobs/issues/115) — *an input arriving with a signature already
   in it is never accepted at all.* The first two are re-derived in the target with its own path
   arithmetic through `Wallet::address`, never by asking the code under test whether it agrees with
   itself. **The second is why this target signs**, at one signature per input of every accepted
   plan: the set of inputs `sign` asserts over is `psbt.rs`'s own, so an independent re-derivation is
   the only thing that turns a widened map read back into a finding. It is also the only target that
   calls a *second* module of the crate, which is deliberate — the defect it exists for lives in the
   seam between the two (`02-core.md` §8a). **The third is what makes the second a claim about the
   delta**: `Psbt::sign` declines a taproot key path whose `tap_key_sig` is already set, so without
   `AOBS-R17` a signature that merely *arrived* would satisfy it — and the third invariant names no
   code, because which one a refusal earns is the corpus's assertion and never a target's. **The
   second's per-family form is restated here rather than shared**
   ([#117](https://github.com/allisson/aobs/issues/117)): `sign` reads the family off the `Accepted`
   the check built, where the target decides it from the `scriptPubKey` it already read to
   re-derive — so this is the one place where saying the rule twice is the point.
4. **Skipped: Bytewords and CBOR encode/decode** — `ur` fuzzes those three targets upstream.
   Recorded so a later reviewer does not read the gap as an oversight.
5. **Deliberate exception: the address-verification path gets no fuzz target.** Its "parser" is a
   prefix strip, a truncate and two comparisons — all total, allocation-free and non-indexing. A fuzz
   target would be exercising `str::eq`. What earns its place instead is corpus entries (§5).

**All three targets exist** as of [#77](https://github.com/allisson/aobs/issues/77), which brought
the transport layer the first one wraps; the other two arrived with
[#79](https://github.com/allisson/aobs/issues/79) and
[#80](https://github.com/allisson/aobs/issues/80). `ci/check-fuzz.sh` runs every target
`cargo fuzz list` reports rather than a list written in the script, so target four is a file and
not an edit here.

**The fountain target's `no allocation above the transport bounds` is two halves, and the split is
deliberate.** `-malloc_limit_mb` aborts on a single allocation above the limit, which is what
catches `03-transport.md` §1's 34 GB claim on the spot. The assertions in the target are the other
half and they hold the *outcomes* to the bounds — a clamped `seqLen` above 64, more parts taken in
than the budget, a message past 64 KiB — so a clamp that stopped clamping fails even when the
allocation it admitted was small enough to slip under the limit. The same claim also runs on every
commit as a property test in `aobs-core`, because the fuzz gate is a nightly job and a regression
should not wait for it.

## 5. The adversarial corpus

**A checked-in regression suite, not merely fuzz seeds.** Every refusal gets a named case, plus these
drawn from the published attacks.

**The name is the code** (`06-codes.md`). Each case asserts the `AOBS-R##` its refusal carries, and the
suite asserts that the registry and the corpus are **in bijection** — every code in `06-codes.md` §6 has
exactly one case, and every case names a code that exists there. That is what keeps the *stable* in
"stable machine-readable code" from being an accident: a refusal added in code with an invented code
fails the suite instead of shipping, and a code changed by accident fails it too.

The cases:

- a frame declaring `seqLen = 0xFFFFFFFF`;
- parts with inconsistent `seqLen`/`messageLen`, and parts disagreeing with an established stream's
  identity;
- a stream that feeds valid parts past the 1 024-part budget without completing;
- duplicate keys in each map; a duplicate global xpub (which arrives as a *different* error variant);
- a legacy input with `witness_utxo` only;
- a `non_witness_utxo` that does not hash to its outpoint;
- **our fingerprint on an output whose scriptPubKey is the attacker's**;
- change on an unscannable path;
- `SIGHASH_SINGLE` / `NONE` / `ANYONECANPAY`;
- outputs exceeding inputs;
- whitespace and unicode in parsed address-adjacent fields (Coldcard 2019, where the review screen
  itself was the vulnerability);
- the 64 KiB boundary at exactly the limit and one byte over;
- **six outputs, and seven** — the second refusing on `AOBS-R15` — plus a PSBT packing outputs to the
  transport bound, which is where the ~2,000-output case lives;
- **two taproot inputs each claiming `u64::MAX` satoshis** — `AOBS-R16`, the amount bound, and the
  shape it exists for rather than a single amount one satoshi over the supply;
- **a testnet PSBT against a mainnet-loaded wallet** — `AOBS-R06` with the coin-type copy variant,
  the network mismatch that has no other symptom;
- **a taproot input whose internal key has no origin entry of its own** — `AOBS-R05`, half of
  BIP-371's declaration ([#113](https://github.com/allisson/aobs/issues/113));
- **a taproot input whose only verifying claim is not the internal key's** — `AOBS-R06`, the shape
  that would otherwise be accepted and come back with no signature in it (#113);
- **a taproot input arriving with a signature already in `tap_key_sig`** — `AOBS-R17`, the shape the
  dependency's key path silently declines, which was accepted and handed back unchanged under a
  screen reading *Signed* ([#115](https://github.com/allisson/aobs/issues/115));
- address-shaped entries: mixed-case bech32, truncated bech32, a valid address differing by one
  character, a valid address differing only in case, `bitcoin:` with a query string, an uppercase
  BIP-21 URI, and a correctly-formed address from the *wrong* account;
- wrong-class payloads at each of the three prompts.

## 6. Gates that run against the artifact, not the source

This section exists because of one finding: **Coldcard's seed generation resolved to MicroPython's
software PRNG for five years. The source was correct; the linkage was wrong.** A test that only reads
the repository is exactly the test that passed for five years. Note also that the substitute PRNG
passes every cheap statistical check, so an on-device randomness self-test would be theatre — what
catches this is **provenance**, not statistics.

### 6.1 Mechanical CI checks

- `aobs-core/Cargo.toml` names neither `slint` nor `v4l`.
- The release profile sets **`panic = "unwind"`**.
- `lsinitramfs` on the built image shows no `drivers/net` entries.
- **No `amdgpu.ko`, `xe.ko` or `radeon.ko` anywhere** — neither in the squashfs module tree nor in the
  initramfs. Each of them removes the framebuffer aperture before failing firmware-less, so on this
  image their presence is what turns a working `efifb` into blackness (`01-boot-layer.md` §3, §7).
- **No D-Bus in the package manifest** — ADR-0017 makes that absence load-bearing, so it is checked
  against the artifact that ships and not only by the build hook that refuses to install one.
- **The shutdown contract is in the unit on the squashfs**: `SuccessExitStatus=42`,
  `RestartPreventExitStatus=42`, and `SuccessAction=poweroff` **in `[Unit]`**. §5's RAM wipe rests on
  the app dying before the machine goes down, and these three directives are the whole mechanism — a
  unit that lost them still boots, still draws, and passes every other row. The section is checked
  too, because systemd discards `SuccessAction=` from `[Service]` as an unknown key and starts the
  unit anyway (ADR-0017).

### 6.2 The QEMU harness

Boots the **built ISO**. One machine-readable readiness line printed to the console is the assertion;
no screenshot diffing. That line doubles as the marker whose absence triggers the crash-diagnostic
path.

**The readiness line carries the display tier**: `AOBS_READY version=… build=… display=fbdev|drm`
(`01-boot-layer.md` §2). Without the tier neither display row below can fail honestly — a green row
would prove only that *something* drew.

**The mode the appliance learned is a second line**, printed before the first paint and beside the
entropy markers: `AOBS_PANEL mode=…x… scale=… logical=…x…`. The three panel rows below assert
against it, because the alternative is reading a scale factor off a screenshot.

**A third line carries the words screen's own arithmetic**, on every boot that draws:
`AOBS_WORDS required=… available=… fits=yes|no`, read off the layout properties the screen is built
from rather than computed a second time beside them. `ci/qemu-boot.sh` fails a boot reporting
`fits=no`, which turns `04-screens.md` §3's owed measurement into a standing assertion — and the
default `ramfb` row runs at the 800×600 floor, the only geometry where it can fail
([#72](https://github.com/allisson/aobs/issues/72)).

**A fourth line carries the review panel's two**, on the same terms:
`AOBS_REVIEW rows-required=… rows-available=… rows-fit=yes|no address-required=… address-available=…
address-one-line=yes|no|unknown` ([#81](https://github.com/allisson/aobs/issues/81),
`04-screens.md` §11.2). The row half is arithmetic over the panel's own heights, exactly as
`AOBS_WORDS` is. **The address half is a font measurement**, and that is why this one line is printed
from inside the event loop rather than before the first paint: a `Text`'s preferred width is not a
number this backend has before the font is loaded, and a line printed earlier would print a zero and
call it a pass. `address-one-line=unknown` is what the appliance says when the measurement came back at
or below zero, and `ci/qemu-boot.sh` fails that too — a green on a measurement that never happened is
worse than a red (standing rule 8).

**And it is the one line the harness *waits* for** ([#82](https://github.com/allisson/aobs/issues/82)).
Every other marker is printed before the first paint, so readiness implies it is already in the log.
This one is printed after `AOBS_READY` by design, and the wait loop breaks the instant it sees
readiness — so checking it in the same breath gave the measurement **zero** time. The face it needs is
`DejaVu Sans Mono`, which nothing earlier in the boot has drawn in, so it is a cold font load every
time. It raced and lost on CI while passing locally, which is the worst way for a gate to behave: **a
gate that depends on winning a race is not a gate.** The fix is a bounded wait rather than moving the
readiness line, because the two lines assert different things and are ready at different moments —
`AOBS_READY` says the loop came up, and delaying it behind a font load would change what it means.

| Row | Proves |
|---|---|
| **Entropy provenance** — trace the `getrandom` syscall during a seed generation and assert the wallet's entropy bytes are **byte-identical** to what the traced syscall returned; assert `crng init done` in `dmesg`; assert **zero opens of `/dev/urandom`**. | The linkage, not the intention. |
| OVMF + virtio-gpu | The DRM tier. Asserts `display=drm`. |
| OVMF + `ramfb`, no GPU | **The fbdev tier** — the fallback the display story now leans on (`01-boot-layer.md` §7, ADR-0016). Asserts `display=fbdev` and a drawn frame. This is the configuration that used to be specified as `simpledrm` and could never pass: Debian builds no `simpledrm`, so `efifb` is what serves this machine, and the assertion is that it **draws**, not that it reports `AOBS-E02` or `AOBS-E05`. |
| **`fbcon` regression** — inject two NMIs on the `ramfb` machine after `AOBS_READY` and assert the panel is **byte-identical** across them. | That the console detach still holds. This is [#52](https://github.com/allisson/aobs/issues/52)'s probe as a standing row, and it must count `AOBS_READY` lines and refuse to compare anything unless the appliance started exactly once — a looping service must not pass for a clean run. |
| **The power button** — `system_powerdown` on the `ramfb` machine after `AOBS_READY`, asserting the confirm appears and that confirming it powers the machine off. | That the button reaches the app at all, and that the exit-status contract fires. [#89](https://github.com/allisson/aobs/issues/89) measured the first half with a throwaway build — `Power Button` / `KEY_POWER` reached an unprivileged app — and a control press first, without which a silent run cannot be told from a broken probe. **The row stands as of [#69](https://github.com/allisson/aobs/issues/69)** (`ci/power-button-probe.sh`), which gave it a shutdown to assert on: it presses Enter with no button press first as the control, asserts the machine survives the button, compares two captures of the same panel to establish that the confirm was drawn, and asserts that confirming it powers the machine off. That last observation is the only one that covers the whole contract — the wrapper passing the app's status through, `SuccessExitStatus`, `RestartPreventExitStatus` and `SuccessAction` — because none of the four is observable on its own. It cannot also assert *started exactly once*: the point of the last step is that the process ends. |
| RAM at and below the floor | The low-memory GRUB entry degrades rather than bricks. |
| No camera | The degraded-but-useful path. |
| No keyboard | The "no input" screen appears. |
| **The minimum canvas** — the `ramfb` machine at OVMF's default 800×600 GOP, asserting the review panel draws **stacked** with every character of a 62-character P2TR address present and no scroll region anywhere. | That the floor in `04-screens.md` §0 is a floor we actually meet, in the geometry CI already boots by default. **The row stands as of [#81](https://github.com/allisson/aobs/issues/81)**, as `AOBS_REVIEW … rows-fit=yes address-one-line=yes` beside `AOBS_WORDS … fits=yes` — asserted as the panel's own numbers rather than as a screenshot, because §6.2 diffs no screenshots. *Every character present* and *no scroll region anywhere* are structural rather than asserted here: the panel holds no `Flickable`, no `ScrollView` and no clip or elide on an address, so an address that did not fit would overflow and the line would report it. |
| **Below the floor** — the virtio-gpu machine at `xres=640,yres=480`, asserting `AOBS-E06` on a live console, **no readiness line at all**, and — after holding the machine past the old 90-second start timeout — that the appliance **started exactly once**, which is what keeps `TimeoutStartSec=infinity` (`01-boot-layer.md` §2) honest. | That the floor refuses rather than degrades. `SLINT_DRM_MODE` was specified here and is not what runs: it is a mode-*list index*, so QEMU and the kernel are free to change what it selects, and injecting an environment variable into `aobs.service` needs a boot path that is no longer GRUB-on-the-ISO. QEMU's own `xres`/`yres` name the geometry and set the connector's preferred mode, which is what Slint picks ([#68](https://github.com/allisson/aobs/issues/68)). **Asserted on the DRM tier only** — nothing in CI can hand `efifb` a sub-floor mode, since that tier's mode is OVMF's GOP. |
| **A large mode** — the virtio-gpu machine at `xres=1920,yres=1080`, asserting `scale=1.35` and a `logical=1422x800` canvas on the panel line. | That the scale-factor policy runs, rather than the layout growing and the type staying put. Its sibling is the plain virtio-gpu row above: QEMU's default is 1280×800, the design canvas itself, so that row pins `scale=1.00` where no scaling is meant to happen. |

The seed path calls `getrandom` as a **raw syscall**, with no crate-level indirection a build change
can silently re-resolve. That is what leaves the harness exactly one site to trace.

### 6.3 By hand, because QEMU cannot

- A real UVC camera (QEMU has no synthetic UVC device).
- Real drivers on real silicon: one Intel iGPU, one AMD, one NVIDIA-on-nouveau.
- **The fbdev tier on real firmware**, on at least one machine with no native KMS driver: that
  `efifb`'s reported format negotiates, and that the console detach behaves as it did under QEMU. Both
  were verified against `ramfb` only, where the vtcon index and the pixel format came from that
  kernel and that firmware (`01-boot-layer.md` §7).
- **The power button on real firmware.** #89 measured it under QEMU's ACPI implementation only, and
  the device name and key code came from that kernel and that firmware — the same limit
  `01-boot-layer.md` §7 records for the fbdev tier.
- **A real coordinator finalizing and broadcasting what we emit**, on signet: Sparrow and Specter
  Desktop at least, since §7's `crypto-account` decision already rests on Specter's scanner and §1's
  type-string decision rests on both. Nothing in CI can do this — our own decoder reads our own
  encoder, which asserts symmetry and not interoperability — and it is the only row that would catch
  §6a's open question about whether `crypto-psbt`'s payload is the PSBT's bytes or a CBOR byte string
  wrapping them ([#112](https://github.com/allisson/aobs/issues/112)). **A signature nobody can
  broadcast is the failure the whole outbound path exists to avoid**, so this is a release-gate row
  and not a nice-to-have.
- **A phone or coordinator camera reading the symbol at the 800×600 floor**, where the square is
  258 px against the ~700 the v27 cap was priced on (`04-screens.md` §11.5). It is §6.4's owed
  measurement, sharpened: the floor is the hard case, not the design canvas.
- Physical keyboards through libinput — including **one non-US board**, to confirm that the pinned
  `us` keymap (`01-boot-layer.md` §2) still reaches all 95 printable ASCII characters on it, since
  that reachability is the whole argument for offering no layout choice (`04-screens.md` §5.1).

The camera being untestable in CI costs less than it appears, because of where the seam sits: core
receives *decoded strings*, so camera→frame is entirely shell, and the decode path is covered by a
**recorded-frame corpus replayed from files**. Only the capture itself needs hands.

**That corpus is `aobs/frames/` and the table in `aobs/src/qr.rs`** as of
[#78](https://github.com/allisson/aobs/issues/78): eight frames as raw V4L2 buffers, with their
format, width, height and stride in the table rather than in the file — a buffer is bytes and nothing
else, so a fixture carrying a header would be testing a shape the appliance never sees. It covers
`GREY`, `YUYV`, a padded stride, eleven degrees of rotation, a plain-text address, two symbols in one
frame, and a frame with nothing in it; two of them replay as one animation through core's four bounds
into the bytes the encoder started with.

**They are synthesised rather than photographed, and that is a gap rather than a technicality.** They
carry no lens blur, no rolling-shutter shear, no uneven illumination and no sensor noise, so they
exercise every way this crate can hand `rqrr` the wrong bytes — which is the failure mode that belongs
to us — and say nothing about the detector's tolerance, which is what the real UVC camera on the list
above is for. It is that same obligation rather than a new one.

**A tested-hardware list is published with each release**, naming exactly what was verified rather
than implying broader support.

### 6.4 The measurement obligations

Each of these is a number the spec currently carries as *derived*. The release gate is where they
become measured. None of them blocks implementation.

| Measure | Fallback if it fails |
|---|---|
| Entropy readiness delay under `random.trust_cpu=off` (derived: 1–16 s) | None needed; it changes copy, not design. |
| Package count and installed size of the GUI floor, with `seatd` and `libseat1` gone (stale: 22 packages / 21 MiB, measured when both were present) | None; it is a claim in ADR-0002 and `01-boot-layer.md` §2, not a design input. |
| RAM floor against the built image (provisional 2 GiB / 4 GiB) | Publish the real number. |
| Argon2id wall clock on low-end amd64 (derived ~1.2–2.5 s) | None; the wait screen is already indeterminate. |
| 8,000-derivation address search | Narrow the index window, and say what was searched. |
| The four-descriptor `crypto-account` payload fits one QR at ECC H | **Narrow what we export. Never animate it.** |
| ~~Two columns of 12 words in the 800×600 **minimum canvas**~~ — **measured** ([#72](https://github.com/allisson/aobs/issues/72)): 440 px required against 458, as `AOBS_WORDS`. | Type size, not layout. |
| ~~A 62-character P2TR payment address, 4-character grouped with §0's sub-cell gaps, on **one line** in the minimum canvas~~ — **measured** ([#81](https://github.com/allisson/aobs/issues/81)): 699 px required against 752, from the shipped font rather than from §0's arithmetic, as `AOBS_REVIEW`. | Wrap it, and drop the output bound to what still fits. Never truncate. |
| ~~**Six output rows fit the minimum canvas**, non-scrolling, with the stacked money facts above them~~ — **measured** ([#81](https://github.com/allisson/aobs/issues/81)): 447 px required against 458, as `AOBS_REVIEW`. The bound stands at six and is now fixed. | Lower the bound before the first ISO ships — after that it is fixed. |
| ~~The predicted signed-transaction vsize against a real signed transaction, in all four script types~~ — **measured** ([#82](https://github.com/allisson/aobs/issues/82)): predicted never above real, and never more than one vbyte per ECDSA input below it. P2WPKH 141/141, P2TR 154/154, P2PKH 225/226 — the published 226 charging the 72-byte DER element we do not. | None needed; the error runs in the safe direction by construction. |
| A phone camera reads our v27 output at arm's length. **04-screens.md §11.5 sharpens what it is being asked**: the outbound square is 258 px at the 800×600 floor, against the ~700 px §6's cap was priced on. | **v40 is the documented fallback** — and the maximum UR fragment length is re-derived from the new cap, never kept (`03-transport.md` §9). |
| The inbound capture-resolution floor | The resolution fallback chain already handles it. |

## 7. Release

**CI builds the ISO; the maintainer signs `SHA256SUMS` with minisign on an offline machine; GitHub
Releases is the only distribution point.**

### 7.1 What a signature can honestly claim

> **Until reproducible builds land, the signature attests "the maintainer intends this artifact to be
> the release", not "this artifact matches the source."**

A maintainer signing a CI output cannot themselves verify it corresponds to the tree. That is
precisely the gap that resolved Coldcard's seed generation to a software PRNG while the source stayed
correct. What partially closes it in v1 is §6.2's entropy provenance gate, **promoted from a build
step to a published artifact, run against the *published* ISO with its report published alongside.**

### 7.2 Key custody

**The release key never touches a networked machine.** The principle is nearly free here because the
signature covers a few-hundred-byte `SHA256SUMS`, not the gigabyte ISO — the air-gap crossing is a
hash file on a USB stick, small enough to type if it came to that. This rules out CI holding the key
under any scheme.

**An offline machine beats a hardware token.** A YubiKey makes the key non-extractable but performs
every signature on a networked host, so an attacker owning that host can sign arbitrary bytes on any
touch. At this payload size the physical gap costs nothing and is worth more.

The secret key is passphrase-encrypted with a **printed backup**. Key *continuity* is the whole
defence in §7.3, so a lost key destroys it permanently.

### 7.3 minisign, and the honesty about first use

minisign over GPG, decided on the fact that **verification instructions are part of the product**:
the public key is one short line that fits in a README, a release page, a QR and the ISO itself;
verification is `minisign -Vm SHA256SUMS -P <key>` with the key inline; there is no keyring, no trust
database, and none of `gpg: WARNING: This key is not certified…`, the most-ignored warning in
computing.

**No GPG signature alongside** — two signing paths means two custody problems, and a user taking the
weaker path gets the weaker guarantee while believing otherwise.

minisign's **`-t` trusted comment is covered by the signature and printed on successful
verification**, so version, build date and the attestation reference ride inside it rather than
living in a separate unsigned file.

**Key continuity is where the honesty is owed. No signature scheme solves it.** If the publication
surface is compromised at the moment of first download, the attacker supplies the ISO, the key and
the instructions together.

> **Signature verification defends against a compromised mirror or CDN. It does not defend against a
> compromised project.**

That sentence goes in the docs **verbatim**, not paraphrased into comfort. What genuinely narrows the
window:

- **The key lives in-tree**, so it is in every clone and every fork, and it carries a commit history.
  git is an append-only log we would otherwise have to build.
- **The key ships inside the ISO**, so a returning user verifies release N+1 with the key from N.
  **Trust-on-first-use is exposure once per user, not once per release.**
- **A rotation policy published in advance: a new key is only ever announced signed by the old one.**
  Stating the rule up front converts an unsigned key change from a surprise into an alarm.
- **GitHub build attestation** from CI. Not a second signature over the same claim — minisign says
  *the maintainer released this*, attestation says *this came out of this repo's workflow*. The pair
  forces an attacker to compromise the download host **and** the repo identity.

OpenTimestamps was considered and cut: it duplicates the transparency-log role at the cost of a
second tool the user must install.

### 7.4 What ships alongside the ISO

- `SHA256SUMS` and `SHA256SUMS.minisig`
- the minisign public key (also in-tree, also inside the ISO)
- **the package manifest live-build emits** — the stripped-network claim is otherwise uncheckable
  without building the image, and one upload makes a security claim auditable
- **the entropy release-gate report**, run against the published ISO
- the tested-hardware list
- version, build date and attestation reference in the **signed trusted comment**

### 7.5 Hosting and verification instructions

**GitHub Releases only. No self-hosted mirror, no separate website in v1.** A mirror nobody watches
is a liability rather than resilience. Host compromise is bounded by the offline key: **a compromised
host cannot produce a valid signature**, so the attack degrades to serving an unsigned or
wrongly-signed ISO — plus the TOFU residual above, which is already stated as unfixable.

Most users will not verify, and an instruction block below a download button is decoration. What
changes behaviour is **making verification the shortest path rather than an extra chore**:

- the download page **leads with one copy-paste block that downloads and verifies in a single
  command**, key inline via `-P`;
- **expected success output shown verbatim**, so a failure looks visibly different rather than merely
  absent;
- per-OS variants, and **no "skip verification" alternative** — no torrent or mirror link that
  arrives without the same block;
- a plain statement of what to do on failure: do not boot it, report it.

### 7.6 Self-reported provenance

A tampered ISO computes and displays whatever its tampered code says. **Self-verification is
structurally theatre against an attacker, at every level of effort**, and it is labelled as such. It
does catch a corrupt USB write and bit-rot, which are real and more common than tampering.

- Display version and build date: **yes** — it makes no security claim and therefore cannot make a
  false one.
- Display the image's own hash: **only** labelled as a corruption check, never as a tamper check.
- **Never render a green tick or anything reading "verified".**
