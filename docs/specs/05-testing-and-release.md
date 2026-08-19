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
| **BIP-32** | Derivation across all four families. |
| **BIP-39 English, all five lengths, passphrase `"TREZOR"`** | Mnemonic ↔ entropy, checksum, seed derivation. |
| **BIP-39 Japanese, passphrase `㍍ガバヴァぱばぐゞちぢ十人十色`** ([bip32JP](https://github.com/bip32JP/bip32JP.github.io/blob/master/test_JP_BIP39.json)) | **Mandatory, not optional.** `㍍` (U+334D) is a *compatibility* character that decomposes under NFKD and is left untouched by NFD. These are the only vectors in the suite that distinguish NFKD from NFD — an implementation reaching for the wrong form passes everything else. |
| **BIP-174**, including **invalid vector 5** | The PSBT parser, and the duplicate-key refusal we now inherit from the dependency. |
| **BIP-340 / BIP-341** | Taproot key-path signing and sighash. |
| **BIP-380** | The four exported descriptors' checksums. |
| **BCR-2020-015** | The `crypto-account` CBOR, against the spec's own example encodings. |
| **RFC 9106** | Argon2id known-answer vectors, plus differential testing against the PHC reference — this is the unaudited half of the crypto. |
| **Entropy mixing, authored by us** | No supplements (asserting `entropy == csprng` byte for byte), dice only, camera only, both, and an empty dice string treated as *absent* rather than as a zero-length field. |
| **Backup format** | Round-trip at each of the five lengths; AAD tamper on every header field; reserved bits non-zero; out-of-range `entropy_len`; unknown version. |
| **Address verification** | Derived addresses across all four families matched in both lowercase and uppercase QR forms. |
| **The fee warning** | Fee exactly equal to the payment total (the boundary — the rule is `≥`), a consolidation with no non-change outputs (undefined, silent), change plus a one-satoshi payment, and a legitimate high-congestion transaction well under the ratio that **must stay silent**. |
| **Passphrase** | Idempotence `nfkd(nfkd(x)) == nfkd(x)`; no-trim — `"a"`, `" a"` and `"a "` derive three distinct seeds; 128 bytes accepted and 129 refused at the shell. |
| **Network, authored by us** | **The master fingerprint of one seed is byte-identical on mainnet and testnet** — the identity screen's only network signal rests on this and it is read from the BIP-32 text rather than measured, so the assertion is the alarm if it ever stops holding. Plus: the same seed derives different account xpubs and different addresses across the two; a testnet PSBT against a mainnet-loaded wallet lands on the "no input is ours" refusal carrying the coin-type-disagreement variant. |

## 3. Property tests

- **The safety proof for entropy mixing:** the mixing function is **injective in the `csprng_32`
  argument for every fixed supplement**. Uniform in, uniform out — verified rather than argued.
- BIP39 round-trip: `entropy → mnemonic → entropy` at every accepted length.
- Address formatting: chunking is lossless, and the concatenation of the rendered groups equals the
  address.
- **The outbound animation never refuses.** For every message length, at the fragment length
  `03-transport.md` §9 settles, no emitted part exceeds v27-L's 2 132-character budget — charging the
  sequence number its full `u32` width rather than the one it happens to be emitted at. This is the
  assertion that catches a fragment length raised without redoing §9.1's arithmetic, and it is why the
  length is a parameter rather than a constant the test cannot vary.

## 4. Fuzz targets

Three we write, one we skip, one deliberate exception.

1. **The fountain decoder through our clamping wrapper** — `fuzz_target!(|parts: Vec<&str>|)` driving
   `Decoder::receive` to completion. Asserts no panic, termination, and **no allocation above the
   transport bounds**. Highest-value surface in the transport layer, and upstream ships no target for
   it.
2. **The PSBT parser** on raw bytes — no panic, bounded allocation.
3. **The validator**, structure-aware and seeded with our own test key material, asserting the one
   invariant that matters: *it never accepts a transaction containing an output classified as ours
   whose scriptPubKey we did not ourselves produce.*
4. **Skipped: Bytewords and CBOR encode/decode** — `ur` fuzzes those three targets upstream.
   Recorded so a later reviewer does not read the gap as an oversight.
5. **Deliberate exception: the address-verification path gets no fuzz target.** Its "parser" is a
   prefix strip, a truncate and two comparisons — all total, allocation-free and non-indexing. A fuzz
   target would be exercising `str::eq`. What earns its place instead is corpus entries (§5).

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

| Row | Proves |
|---|---|
| **Entropy provenance** — trace the `getrandom` syscall during a seed generation and assert the wallet's entropy bytes are **byte-identical** to what the traced syscall returned; assert `crng init done` in `dmesg`; assert **zero opens of `/dev/urandom`**. | The linkage, not the intention. |
| OVMF + virtio-gpu | The DRM tier. Asserts `display=drm`. |
| OVMF + `ramfb`, no GPU | **The fbdev tier** — the fallback the display story now leans on (`01-boot-layer.md` §7, ADR-0016). Asserts `display=fbdev` and a drawn frame. This is the configuration that used to be specified as `simpledrm` and could never pass: Debian builds no `simpledrm`, so `efifb` is what serves this machine, and the assertion is that it **draws**, not that it reports `AOBS-E02` or `AOBS-E05`. |
| **`fbcon` regression** — inject two NMIs on the `ramfb` machine after `AOBS_READY` and assert the panel is **byte-identical** across them. | That the console detach still holds. This is [#52](https://github.com/allisson/aobs/issues/52)'s probe as a standing row, and it must count `AOBS_READY` lines and refuse to compare anything unless the appliance started exactly once — a looping service must not pass for a clean run. |
| **The power button** — `system_powerdown` on the `ramfb` machine after `AOBS_READY`, asserting the confirm appears and that confirming it powers the machine off. | That the button reaches the app at all, and that the exit-status contract fires. [#89](https://github.com/allisson/aobs/issues/89) measured the first half with a throwaway build — `Power Button` / `KEY_POWER` reached an unprivileged app — and a control press first, without which a silent run cannot be told from a broken probe. **This row waits for a shutdown to assert on**; until then the measurement stands and the row does not. |
| RAM at and below the floor | The low-memory GRUB entry degrades rather than bricks. |
| No camera | The degraded-but-useful path. |
| No keyboard | The "no input" screen appears. |
| **The minimum canvas** — the `ramfb` machine at OVMF's default 800×600 GOP, asserting the review panel draws **stacked** with every character of a 62-character P2TR address present and no scroll region anywhere. | That the floor in `04-screens.md` §0 is a floor we actually meet, in the geometry CI already boots by default. **This row waits for the review panel**; until it exists, the default `ramfb` row asserts only that 800×600 draws and reports `scale=1.00`. |
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
- Physical keyboards through libinput — including **one non-US board**, to confirm that the pinned
  `us` keymap (`01-boot-layer.md` §2) still reaches all 95 printable ASCII characters on it, since
  that reachability is the whole argument for offering no layout choice (`04-screens.md` §5.1).

The camera being untestable in CI costs less than it appears, because of where the seam sits: core
receives *decoded strings*, so camera→frame is entirely shell, and the decode path is covered by a
**recorded-frame corpus replayed from files**. Only the capture itself needs hands.

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
| Two columns of 12 words in the 800×600 **minimum canvas** (the binding geometry since `04-screens.md` §0 fixed the floor; 1280×800 is no longer the tight case) | Type size, not layout. |
| A 62-character P2TR payment address, 4-character grouped with §0's sub-cell gaps, on **one line** in the minimum canvas (derived: 62 cells + 15 gaps ≈ 698 px against ~768 px usable) | Wrap it, and drop the output bound to what still fits. Never truncate. |
| **Six output rows fit the minimum canvas**, non-scrolling, with the stacked money facts above them (derived: ~320 px of rows at ~57 px each) | Lower the bound before the first ISO ships — after that it is fixed. |
| A phone camera reads our v27 output at arm's length | **v40 is the documented fallback** — and the maximum UR fragment length is re-derived from the new cap, never kept (`03-transport.md` §9). |
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
