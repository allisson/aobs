# Argon2id parameters and AEAD for the encrypted wallet backup

Research findings for [aobs#6](https://github.com/allisson/aobs/issues/6). Map: [aobs#1](https://github.com/allisson/aobs/issues/1).

Scope note: this document assumes the encrypted backup feature exists. Whether it *should* exist is
[aobs#7](https://github.com/allisson/aobs/issues/7). Evidence bearing on that question is collected in
[§9](#9-evidence-bearing-on-7-does-the-feature-earn-its-place) rather than acted on here.

---

## Recommendation in one block

```
Password    8 words, EFF long wordlist (7776 words), device-generated from the CSPRNG.
KDF         Argon2id, m = 65536 KiB (64 MiB), t = 3, p = 4, salt 128 bit, output 256 bit.
            RFC 9106 SECOND RECOMMENDED option, verbatim. Parameters are NOT stored in the
            file; they are fixed by the format version byte.
AEAD        ChaCha20-Poly1305 (RFC 8439), 12-byte all-zero nonce.
            The key is unique per backup because the salt is fresh, so the nonce carries
            no entropy burden. Same argument age makes for its scrypt stanza.
Plaintext   The BIP-39 entropy (16 / 24 / 32 raw bytes). Not the mnemonic string,
            not the derived 512-bit seed, and NOT the BIP-39 passphrase.
AAD         Every byte of the file before the ciphertext: version || flags || entropy_len || salt.
Size        67 bytes total for a 24-word seed. 51 bytes for a 12-word seed.
```

---

## 1. Password entropy — the exact number, with working

The EFF long wordlist has 7776 words and is designed for selection with five dice
([EFF, *Deep Dive: EFF's New Wordlists for Random Passphrases*, 2016](https://www.eff.org/deeplinks/2016/07/new-wordlists-random-passphrases)).
EFF states 12.9 bits per word and recommends six words for 77 bits "for most uses" — a general-purpose
recommendation, not one calibrated to key material.

7776 = 6<sup>5</sup>, so the per-word entropy is exact:

```
log2(7776) = 5 · log2(6) = 5 · (1 + log2 3) = 5 · 2.5849625007211562
           = 12.924812503605781 bits/word
```

Eight independent, uniform selections **with replacement** (each word drawn fresh from all 7776 — this
matters; drawing without replacement would give a different and slightly smaller number, and the
generator must not deduplicate):

```
H = 8 · 12.924812503605781 = 103.39850002884624 bits

search space = 7776^8
             = 13,367,494,538,843,734,067,838,845,976,576
             ≈ 1.336749 × 10^31          (cross-check: 2^103.3985 = 1.336749 × 10^31 ✓)

expected guesses to find (uniform search, average case) = 7776^8 / 2
             ≈ 6.683747 × 10^30
```

**103.398 bits.** Every figure below follows from this number.

---

## 2. Argon2id parameters

### 2.1 What RFC 9106 actually says

[RFC 9106 §4](https://www.rfc-editor.org/rfc/rfc9106.html) gives two named options:

- **FIRST RECOMMENDED** — "Argon2id with t=1 iteration, p=4 lanes, m=2^(21) (2 GiB of RAM), 128-bit salt, and 256-bit tag size."
- **SECOND RECOMMENDED** — "Argon2id with t=3 iterations, p=4 lanes, m=2^(16) (64 MiB of RAM), 128-bit salt, and 256-bit tag size."

On variant choice: "If you do not know the difference between the types or you consider side-channel
attacks to be a viable threat, choose Argon2id." aobs is a physically-held device with a hostile-media
threat model, so Argon2id is not a judgement call.

Salt: "A length of 128 bits is sufficient for all applications but can be reduced to 64 bits in the case
of space constraints." We are not space constrained at 67 bytes; use 128 bits.

Memory is total, not per-lane. RFC 9106 §3 defines the block count as `m' = 4 * p * floor(m / 4p)`, so
`p=4` with `m=65536` still allocates 64 MiB overall, not 256 MiB. This is the fact that makes `p=4`
safe on a small machine.

### 2.2 Why not FIRST RECOMMENDED

The 2 GiB option is disqualified by the platform, not by taste. aobs is a Debian LiveCD with the root
filesystem in RAM, no swap (a standing constraint on the map), and a Tauri/WebKit process already
resident. A 2 GiB transient allocation on a 4 GiB machine risks the OOM killer during a backup or
restore, and with no swap there is no soft failure — the process dies mid-operation. The hardware
compatibility floor is still unsettled on the map, which is itself a reason not to bet on 2 GiB.

64 MiB is safe on any machine that can boot the ISO at all.

### 2.3 Measured cost — attacker side

hashcat 7.0.0 added Argon2 as hash-mode 34000 using "the official Argon2 implementation from the
Password Hashing Competition (PHC)" and published benchmarks at **exactly the RFC 9106 SECOND
RECOMMENDED memory and time cost**
([hashcat 7.0.0 release notes](https://github.com/hashcat/hashcat/blob/master/docs/releases_notes_v7.0.0.md)):

| Device | Argon2id m=65536, t=3, p=1 |
| --- | --- |
| NVIDIA GeForce RTX 4090 | **1703 H/s** |
| AMD Radeon RX 7900 XTX | 1367 H/s |
| Intel i7-14700K | 96 H/s |
| AMD Ryzen 9 9900X | 92 H/s |

Caveat, stated rather than buried: hashcat benchmarks `p=1` and we specify `p=4`. Lane count changes how
the work is scheduled, not how much memory is filled or how many times it is passed over, so `1703 H/s`
is the right order of magnitude for per-GPU throughput at our parameters. The number is a measurement of
someone else's hardware, not ours.

**Assumed attacker hardware: NVIDIA RTX 4090, 450 W Total Graphics Power
([NVIDIA RTX 4090 specifications](https://www.nvidia.com/en-us/geforce/graphics-cards/40-series/rtx-4090/)),
running hashcat 7.0.0 mode 34000.** This is a consumer card, deliberately: it is the cheapest
credible unit of attack and the one an adversary can buy a thousand of without attracting attention.

### 2.4 Measured cost — defender side

The same table gives the honest defender number: an i7-14700K reaches 96 H/s **across all cores under a
cracking workload**. Per-core that is roughly 96/28 ≈ 3.4 H/s, i.e. **~0.29 s per hash on one modern
core**.

A single Argon2id at these parameters does the same total work regardless of `p`, so on genuinely
low-end amd64 — a 2008-era Core 2 Duo or a Bay Trail Celeron, roughly 4–6× slower per core than a
14700K P-core, with 2 cores to spread 4 lanes over — the derived estimate is **~1.2–2.5 s wall clock and
a flat 64 MiB peak allocation**.

> This is a *derived* figure, not a measured one. It is the one number in this document that has not been
> observed on real hardware. The spec should carry a requirement to measure Argon2id(64 MiB, t=3, p=4) on
> whatever machine the hardware compatibility floor ticket settles on, and a progress indicator on the
> backup/restore screens regardless — 2.5 s of a frozen UI on a security operation reads as a crash.

### 2.5 Raising the memory cost is a bad trade — this is the decisive calculation

The tempting move is m = 1 GiB, t = 4. It multiplies attacker cost by 16 × 4/3 ≈ 21.3×, which is:

```
log2(21.3) = 4.41 bits
```

**4.41 bits, bought with a 16× larger allocation on a RAM-resident live system.** One additional EFF word
costs the user four seconds of transcription and buys **12.92 bits** — nearly three times as much, with
no memory footprint at all and no risk to the boot.

The rule this settles for the whole feature: **on a memory-constrained live system, buy security in words,
not in megabytes.** Take RFC 9106's SECOND RECOMMENDED unmodified and spend any remaining security budget
on password length.

---

## 3. Total attack cost, and whether 8 is the right number

### 3.1 Wall-clock and energy

```
guesses per GPU-year = 1703 H/s × 31,556,952 s/yr = 5.374 × 10^10

expected effort       = 6.683747 × 10^30 / 5.374 × 10^10
                      = 1.2437 × 10^20 GPU-years
```

| Adversary | Expected time to recover the password |
| --- | --- |
| 1 RTX 4090 | 1.24 × 10<sup>20</sup> years |
| 1,000 GPUs (~$1.6 M of cards, ~450 kW) | 1.24 × 10<sup>17</sup> years |
| 1,000,000 GPUs (larger than any known cluster) | 1.24 × 10<sup>14</sup> years |
| 1,000,000,000 GPUs | 1.24 × 10<sup>11</sup> years |

The age of the universe is ~1.38 × 10<sup>10</sup> years. A billion-GPU adversary needs about nine times it.

Energy is the more honest bound, since it does not depend on how many cards you imagine:

```
energy per guess = 450 W / 1703 H/s      = 0.2642 J
total energy     = 6.683747e30 × 0.2642  = 1.766 × 10^30 J
```

World primary energy consumption is on the order of 6.2 × 10<sup>20</sup> J/year (~620 EJ), so brute-forcing
the password costs roughly **2.8 × 10<sup>9</sup> years of total global energy production**. No parameter
tuning changes that conclusion; it is a statement about 103 bits, not about Argon2.

### 3.2 The comparison that actually decides the word count

Raw bit counts are not comparable across KDFs. Convert the Argon2id work factor into bits by measuring it
against a single SHA-256 on the same GPU:

- SHA2-256 (hashcat mode 1400), RTX 4090: **21,975.5 MH/s**
  ([Chick3nman, *Hashcat v6.2.6 benchmark on the Nvidia RTX 4090*](https://gist.github.com/Chick3nman/32e662a5bb63bc4f51b847bb422222fd))
- Argon2id m=64 MiB t=3, RTX 4090: **1703 H/s** (hashcat 7.0.0 notes, above)

```
ratio = 2.19755 × 10^10 / 1703 = 1.29040 × 10^7
log2(ratio) = 23.62 bits
```

*(Cross-version comparison — SHA-256 from hashcat 6.2.6, Argon2 from 7.0.0 — same GPU. Flagged, not hidden.)*

So Argon2id at RFC 9106 SECOND RECOMMENDED contributes **+23.62 bits** over an unsalted single-hash
baseline. Total strength, expressed on a common scale:

| Words | Raw entropy | + Argon2id (23.62) | vs. 128-bit floor |
| --- | --- | --- | --- |
| 6 (EFF's own recommendation) | 77.55 | 101.17 | ✗ short by 27 |
| 7 | 90.47 | 114.10 | ✗ short by 14 |
| **8** | **103.40** | **127.02** | **✓ lands on it** |
| 9 | 116.32 | 139.94 | over |
| 10 | 129.25 | 152.87 | over |

### 3.3 Verdict: 8 words is correct

**8 is the smallest word count that reaches the 128-bit security floor once the KDF is counted, and it
reaches it almost exactly (127.0).** It is not a round number someone picked; it is the answer.

Two consequences worth writing into the spec:

1. **8 words is correct *because of* the KDF, not despite it.** Strip Argon2id down to a plain hash and
   the same target needs **10 words**. If anyone ever proposes weakening the KDF "for speed on old
   hardware", the word count must rise with it. Bind the two: the format version fixes both, together.
2. The margin is thin by design. There is no room to drop to 7 words for usability. 7 words is 14 bits
   short and that is a real 16,000× reduction in attack cost, not a rounding difference.

### 3.4 Why the EFF long list rather than BIP-39

BIP-39 English is already on the device — it must be, for seed import — so reusing it would ship one
fewer wordlist, and BIP-39's own design criteria are attractive for transcription: "it's enough to type
the first four letters to unambiguously identify the word", and word pairs like "build"/"built" and
"woman"/"women" are excluded
([BIP-39](https://github.com/bitcoin/bips/blob/master/bip-0039.mediawiki)). At 11 bits/word exactly,
10 BIP-39 words would give 110 bits.

**Reject anyway.** A device that shows the user two different sets of BIP-39 words — one that is the
wallet and one that is merely the backup password — is a device that will eventually have someone
restore the wrong list, or write the backup password onto the seed card. The EFF words are visually and
lexically distinct from BIP-39 (longer, ordinary English), and that distinctness *is* the safety
feature. Coldcard makes the opposite choice (§8) and it is the part of their design most worth not
copying.

Cost of the decision: one 7776-word list, ~60 KB, shipped in the ISO. Cheap.

---

## 4. AEAD selection

### 4.1 The nonce question is already answered by the salt

Every backup gets a fresh 128-bit CSPRNG salt, so every backup gets a distinct Argon2id output, so the
AEAD key is never reused. Nonce-reuse resistance is therefore not a property this design needs to buy.

This is not a novel argument — it is exactly what the age specification does. In the scrypt recipient
stanza, "the body is ChaCha20-Poly1305 encrypted with this key and a **12-byte all-zeros nonce**"
([age v1 specification](https://github.com/C2SP/C2SP/blob/main/age.md)), because the wrap key is already
unique to the file via a fresh 16-byte salt.

A random nonce drawn from the same CSPRNG that produced the salt adds nothing: if that CSPRNG repeats,
the salt repeats too and the key collides regardless. Spending 12 or 24 bytes to restate a guarantee the
salt already provides is not defence in depth, it is a second thing to get wrong.

### 4.2 The three candidates

| | Verdict | Reasoning |
| --- | --- | --- |
| **ChaCha20-Poly1305** (RFC 8439) | **Chosen** | NCC-audited RustCrypto implementation; constant-time by construction with no data-dependent table lookups; fast in pure software on pre-AES-NI amd64; the primitive age already uses for this exact job. |
| **XChaCha20-Poly1305** | Reject | Its entire value is a 24-byte random nonce safe under key reuse. Our key is never reused. Costs 24 bytes and an HChaCha20 step to buy a property we already have. Available in the same crate if a future design ever holds a long-lived key. |
| **AES-256-GCM** | Reject | Not on safety grounds — see below. On age-of-hardware and failure-mode grounds. |
| **AES-256-GCM-SIV** | Reject | Nonce-misuse-resistant, which we do not need; two-pass; least widely deployed of the three. It *is* the right answer if the design later acquires a fixed key with counter nonces. |

**On AES specifically, an argument worth not overstating.** The intuitive objection — "table-driven AES
leaks via cache timing on machines without AES-NI" — does **not** apply to the RustCrypto crate. Its
README states: "All implementations contained in the crate are designed to execute in constant time,
either by relying on hardware intrinsics (i.e. AES-NI on x86/x86_64), or using a portable implementation
based on bitslicing"
([RustCrypto/block-ciphers `aes`](https://github.com/RustCrypto/block-ciphers/blob/master/aes/README.md)).
The crate is safe on old amd64.

The two real reasons to skip it:

1. **Speed on the target.** AES-NI arrived with the 32 nm Westmere family in January 2010
   ([Intel, *Advanced Encryption Standard (AES) Instructions Set*](https://www.intel.com/content/www/us/en/developer/articles/tool/intel-advanced-encryption-standard-aes-instructions-set.html)).
   Machines older than that — precisely the class of hardware people repurpose as an air-gapped
   signer — run the bitsliced fallback plus a software GHASH. ChaCha20 has no such cliff.
2. **Worst-case behaviour.** The `aes-gcm` crate's own note flags that the portable GHASH "maintains
   constant-time properties only on processors supporting constant-time multiplication"
   ([RustCrypto/AEADs `aes-gcm`](https://github.com/RustCrypto/AEADs/blob/master/aes-gcm/README.md)), and
   GCM's failure under nonce reuse is catastrophic (authentication-key recovery, arbitrary forgery)
   rather than merely bad. For an appliance **with no update mechanism**, prefer the primitive whose
   worst case is least bad. That constraint should drive every close call in this document.

### 4.3 Crates

| Crate | Audit status | Notes |
| --- | --- | --- |
| `chacha20poly1305` (RustCrypto/AEADs) | **Audited.** "This crate has received one security audit by NCC Group, with no significant findings", funded by MobileCoin. [Report (archived)](https://web.archive.org/web/20240108154854/https://research.nccgroup.com/wp-content/uploads/2020/02/NCC_Group_MobileCoin_RustCrypto_AESGCM_ChaCha20Poly1305_Implementation_Review_2020-02-12_v1.0.pdf) | Includes XChaCha20-Poly1305 in the same crate if ever needed. MSRV 1.85. |
| `argon2` (RustCrypto/password-hashes) | **No published audit.** | Pure Rust, all three variants, `no_std` capable. See the mitigation below. |
| `ring` | — | Has no Argon2 and no XChaCha; would force a second crate anyway, so it buys nothing. |
| libsodium bindings | — | Pulls a C toolchain into an otherwise pure-Rust ISO build. Cuts directly against the v2 reproducible-build goal on the map. Reject. |

**The unaudited half is the KDF, and that should be said out loud.** Mitigation, which the map's
"98%+ for critical security components" bar should be pointed at explicitly: RFC 9106 ships known-answer
test vectors, and the PHC reference implementation is available for differential testing. The Argon2id
implementation is the single component in this feature most deserving of vector-based and differential
testing rather than coverage-by-line-count.

**One implementation trap.** The RustCrypto `argon2` crate does **not** expose Argon2's own associated-data
(AD) input. Its `Params::data` field is documented as "This field is not longer part of the argon2
standard ... and should not be used for any non-legacy work", retained only for PHC-string compatibility
([`argon2/src/params.rs`](https://github.com/RustCrypto/password-hashes/blob/master/argon2/src/params.rs)).
Context binding must therefore go through the **AEAD's** AAD, not through Argon2. §6 does exactly that.

Also note the crate's defaults are **not** RFC 9106's: `DEFAULT_M_COST = 19 * 1024`, `DEFAULT_T_COST = 2`,
`DEFAULT_P_COST = 1` (OWASP's recommendation, not the RFC's). `Params::DEFAULT` must never be used here;
construct the parameters explicitly and assert them in a test.

---

## 5. What is encrypted

**Encrypt the BIP-39 entropy: the raw 16, 24 or 32 bytes.** Not the mnemonic string, not the derived seed.

- **Not the mnemonic string.** It is 2–3× larger and drags in language selection and Unicode
  normalisation as a compatibility hazard — BIP-39 requires UTF-8 NFKD. A restore path that has to
  normalise a string correctly to reproduce a wallet is a restore path with a silent-failure mode.
- **Not the derived 512-bit seed.** BIP-39's mnemonic→seed step is PBKDF2-HMAC-SHA512 with 2048
  iterations ([BIP-39](https://github.com/bitcoin/bips/blob/master/bip-0039.mediawiki)) and is one-way.
  A seed-only backup can never re-display the words to the user and can never be carried to a wallet
  that wants a mnemonic. Worse, the seed already bakes in whatever BIP-39 passphrase was active, so
  restoring it silently locks in a passphrase decision the user cannot see, inspect, or change.
- **Entropy is self-describing and self-checking.** 16/24/32 bytes maps to 12/18/24 words, and
  regenerating the mnemonic re-derives the BIP-39 checksum — a free integrity check on restore that is
  independent of Poly1305.

### The BIP-39 passphrase must NOT be in the backup

If the passphrase rides in the backup, the backup is single-factor for the entire wallet and the
passphrase stops being a factor at all. Excluding it is what keeps the two factors independent.

But exclusion creates a loud-failure obligation: a user who used a passphrase and restores from the
backup gets a **valid, correctly-decrypted, completely wrong wallet** — empty, with no error anywhere.
That is exactly the silent-wrong-wallet outcome issue #6 asks to prevent, and no amount of AEAD prevents
it. The fix is a **passphrase-in-use flag in the associated data**, so restore can state plainly: *this
backup was made with a BIP-39 passphrase; the words alone will not reproduce your wallet.* One bit,
and it closes the worst failure mode in the feature.

---

## 6. What rides in the clear as associated data

### 6.1 A distinction the ticket conflates, stated precisely

**A wrong password already fails loudly.** Poly1305 rejects a wrong key with probability
1 − 2<sup>−128</sup>. AAD contributes nothing to wrong-password detection.

What AAD actually buys is **context binding**: a ciphertext that is valid in one context cannot be
silently reinterpreted in another. That is a different and narrower guarantee, and it is the one that
should decide which fields go in.

### 6.2 The rule

**AAD = every byte of the file before the ciphertext.** One rule, no per-field argument, no ambiguity
about coverage, and tampering with any header byte is fatal. The version byte and the salt must be in
the clear anyway (you need them to derive the key at all), so the rule costs nothing.

Fields:

| Field | In the clear | Why |
| --- | --- | --- |
| Format version | yes, AAD | Needed before parsing. Binding it prevents reinterpreting a v1 file as v2. |
| Network (mainnet / test-signet) | yes, AAD | Restoring a testnet rehearsal seed as mainnet, or the reverse, is a silent wrong-wallet outcome. Cheap to bind, and it leaks nothing an adversary holding the QR does not already infer. |
| BIP-39 passphrase in use | yes, AAD | The loud-failure flag from §5. |
| Entropy length (16/24/32) | yes, AAD | Determines the word count on restore. |
| Argon2id salt | yes, AAD | Required for key derivation. |
| KDF parameters | **no** | Fixed by the version byte. See §7.2. |
| Derivation paths / script type | **no** | Reject. |

### 6.3 Why derivation-path hints are rejected

The map fixes v1 to single-sig across BIP44/49/84/86. Those paths are fully determined by the seed plus
the script type; they are not needed to restore. Putting them in the clear leaks wallet structure —
account count, script types in use — to anyone who photographs the QR, in exchange for convenience the
restore flow can supply itself by scanning all four standard paths.

If a script-type hint is later judged worth having, it belongs **inside the ciphertext**, not in the AAD.
Nothing that is merely convenient should be readable by someone holding the QR without the password.

---

## 7. Format

### 7.1 Layout

```
offset  len  field
------  ---  -----------------------------------------------------------
     0    1  version           = 0x01
     1    1  flags             bit0: network  (0 = mainnet, 1 = testnet/signet)
                               bit1: BIP-39 passphrase was in use
                               bits 2-7: MUST be zero; reject if not
     2    1  entropy_len       16 | 24 | 32   (reject any other value)
     3   16  argon2id_salt     128-bit CSPRNG
    19    N  ciphertext        N = entropy_len
  19+N   16  poly1305_tag
------  ---  -----------------------------------------------------------
total = 35 + entropy_len   ->  67 bytes (24 words) | 59 (18 words) | 51 (12 words)

AAD   = bytes [0, 19)  =  version || flags || entropy_len || salt
key   = Argon2id(password, salt = argon2id_salt, m = 65536, t = 3, p = 4, out = 32)
nonce = 12 zero bytes
```

Password canonicalisation, which must be pinned or restore breaks: the 8 words **lowercase, ASCII,
joined by exactly one space (0x20), no trailing space**. Input handling should normalise whitespace and
case before hashing so a user who types with capitals or double spaces still restores.

### 7.2 KDF parameters are not in the file — and that is deliberate

age puts its scrypt work factor in the file, and pays for it: `rage` ships a `--max-work-factor <WF>`
flag whose stated purpose is "Maximum work factor to allow for passphrase decryption"
([rage README](https://github.com/str4d/rage)) — a mitigation that exists only because an attacker can
hand you a file demanding an unbounded amount of work. Krux does the same thing, encoding PBKDF2
iterations in three bytes of its KEF envelope.

aobs writes and reads both ends of this format. Fixing the parameters to the version byte removes the
work-factor field entirely: no downgrade surface (nobody can hand you a file claiming t=1), no
resource-exhaustion surface, one fewer field to validate. A future parameter change gets a new version
byte, which is the versioning mechanism regardless.

### 7.3 Size, and one benefit worth naming

67 bytes is small enough that the QR can run at **error-correction level H (~30% recoverable)** and still
be an unremarkable low-density symbol. Damage tolerance on the physical artifact is free here — see
[§9](#9-evidence-bearing-on-7-does-the-feature-earn-its-place), because it bears directly on issue #7's
"QR faded or partially damaged" loss mode. Exact QR version sizing belongs to the QR transport ticket,
not this one.

---

## 8. Reuse before inventing

### 8.1 age — evaluated seriously, rejected

The [age v1 specification](https://github.com/C2SP/C2SP/blob/main/age.md) is the strongest candidate:
a reviewed spec under C2SP, a maintained Rust implementation, ChaCha20-Poly1305, HMAC-SHA-256 over the
header. Six findings against it, each from the spec or the implementation:

1. **Wrong KDF.** The scrypt stanza specifies
   `scrypt(N = work factor, r = 8, p = 1, dkLen = 32, S = "age-encryption.org/v1/scrypt" || salt, P = passphrase)`.
   RFC 9106 and this ticket both call for Argon2id, whose data-independent first half is the reason
   §2.1's variant guidance points at it.
2. **Attacker-controlled work factor.** The work factor is a header argument. `--max-work-factor` exists
   to bound it. §7.2 has no such surface.
3. **No slot for our associated data.** The specification "does not describe support for arbitrary
   metadata in the header." Network, passphrase flag and entropy length could not be bound as AAD, so
   §6's context binding is simply unavailable.
4. **~3× the bytes for a 32-byte secret.** Version line, base64 stanza, base64 HMAC line, chunked payload
   framing: roughly 200+ bytes of header against 67 bytes total for the fixed layout. On a QR read by a
   cheap camera, that is error-correction headroom spent on framing we do not use.
5. **No published audit** for the `age` Rust crate, where `chacha20poly1305` has one.
6. **Solves problems we do not have.** Multiple recipients, streaming 64 KiB chunked payloads with a
   final-chunk flag, header extensibility. Our plaintext is 32 bytes, once, for one recipient.

**What we reuse from age is its judgement, not its bytes**: ChaCha20-Poly1305, and the all-zero-nonce
argument in §4.1, which is age's own reasoning applied to the same situation.

### 8.2 The general point about bespoke containers

"Don't invent a container for key material" is sound advice aimed at a specific set of mistakes: choosing
a cipher mode, handling padding, managing IVs, ordering MAC and encryption. **A single-shot AEAD over a
fixed-length plaintext with a per-file key has none of those decisions left in it.** There is no mode to
pick, no padding, no IV schedule, no MAC-then-encrypt question. The "format" is four fixed-offset fields
and a constant.

The failure that reuse guards against does not exist here; the costs of reuse (§8.1) do. That is the
whole argument, and it should be recorded as such rather than restated as a preference.

### 8.3 What other signers do

| Signer | Construction | Password | Strength |
| --- | --- | --- | --- |
| **Coldcard** | `backup.7z`, "AES-256 encryption, in CBC mode", key is "a SHA256 hash of a passphrase, hashed in a particular way to support 7z compatibility", with 7z key stretching. Contents: "a simple text file with everything you could need to access your funds ... including seed words and settings". ([Coldcard docs](https://coldcard.com/docs/backups/)) | Device-generated **12 BIP-39 words** — "COLDCARD will pick 12 words as a password ... chosen randomly", TRNG-sourced, "effectively 132 bits of security" | 132 bits raw, but a **non-memory-hard** KDF. Higher raw entropy than our 103.4; far lower cost per guess. |
| **Foundation Passport** | 7z, AES-256, "a form of SHA-256 to hash the 20-digit passcode into a 256-bit key" ([Foundation blog](https://foundation.xyz/blog/why-we-love-encrypted-microsd-backups)) | Device-generated **20 decimal digits** | 10<sup>20</sup> = **66.4 bits**, non-memory-hard. The weakest of the surveyed designs by a wide margin — 37 bits below ours before the KDF is even counted. |
| **Krux** | KEF envelope: PBKDF2-HMAC-SHA256 (iterations in the envelope), AES in ECB/CBC/CTR/GCM across ~12 version numbers. Encrypts the mnemonic bytes. ([`kef.py`](https://github.com/selfcustody/krux/blob/main/src/krux/kef.py)) | User-chosen | Weak KDF, user-chosen password, and see §9.6 on what the format became. |
| **SeedSigner** | SeedQR / CompactSeedQR — **plaintext**, deliberately. "A SeedQR does not encrypt the child or reduce the consequences of theft." ([SeedSigner docs](https://github.com/SeedSigner/seedsigner/blob/main/docs/seed_qr/README.md)) | — | The explicit decision *not* to build this feature, from the closest comparable project. |
| **SLIP-39** (SatoshiLabs / Trezor) | Four-round Feistel with PBKDF2-HMAC-SHA256 as the round function, `iterations = 2500 << e`; Shamir split across shares. Identifier and iteration exponent ride in the clear. ([SLIP-39](https://github.com/satoshilabs/slips/blob/master/slip-0039.md)) | Optional passphrase; **no authentication** — "there is no way to verify that the correct passphrase was used" | Different problem: m-of-n split with no password to lose. Named alternative for #7. |

Two things the table makes obvious. **First: our construction is the strongest of the surveyed encrypted
backups, and not marginally.** Everyone else uses 7z-style or PBKDF2 key stretching; none is memory-hard;
Passport's 66.4-bit password is genuinely low. Second: **7z is not a candidate.** AES-256-CBC with a
CRC and no AEAD is a downgrade on every axis that matters, and it exists in those designs for
desktop-tool compatibility — a benefit aobs cannot use, since a QR is not a file anyone opens with 7-Zip.

PKCS#5 / PBKDF2 is likewise superseded for this purpose by RFC 9106; there is no argument for it.
BIP-38 (scrypt + AES-256-**ECB** for single private keys) is prior art in the "do not copy this" sense.

---

## 9. Evidence bearing on #7 — does the feature earn its place?

Turned up while researching the construction. Recorded here because #7 is blocked on this ticket; not
acted on, because settling it is #7's job.

**9.1 — The strongest fact against the feature comes from the prior art itself.** Coldcard's backup
contains "seed words **and settings**"; Passport's backs up a configured device. What makes those
backups valuable is the non-seed state: multisig registrations, derivation configuration, account
labels, PIN and device settings — state that is expensive or impossible to reconstruct.
**aobs is amnesic and single-sig. It has no such state.** The backup can contain nothing but the seed,
which means it is strictly a re-encoding of the mnemonic, not a superset of it. The feature aobs is
copying is not the feature those devices have.

**9.2 — The two-artifact objection is quantifiable.** Losing *either* the words or the QR loses the
wallet. If each artifact independently survives a year with probability (1−p), the pair survives with
(1−p)² — **strictly worse than a single mnemonic on steel.** The encrypted backup can only win if it
enables storage locations a plaintext mnemonic could not use: a cloud drive, a bank box you do not fully
trust, a photo on a phone. That scenario is the entire case for the feature, and #7 should either name
it concretely or kill the feature.

**9.3 — For passphrase users it is a *third* artifact, not a second.** §5 establishes that the BIP-39
passphrase must not be in the backup. So a passphrase user must keep: the QR, the 8 backup words, and
the passphrase. Three artifacts, all required, none reconstructible from the others. Against one steel
plate plus a passphrase. This makes 9.2 substantially worse for exactly the users most likely to want
the feature.

**9.4 — One point in the feature's favour, worth stating fairly.** At 67 bytes the QR fits comfortably at
error-correction level H (~30% damage recoverable) as an ordinary low-density symbol. The "faded or
partially damaged QR" loss mode in #7 is largely answerable, and cheaply. A plaintext mnemonic on paper
has no comparable error correction.

**9.5 — SLIP-39 is the named alternative if the feature is cut.** It solves the neighbouring and arguably
more valuable problem — m-of-n split, geographic distribution, **no password to lose** — with a reviewed
SatoshiLabs specification and existing implementations. One caveat #7 must weigh: SLIP-39 is
unauthenticated by design ("there is no way to verify that the correct passphrase was used"), so it
trades away exactly the loud-failure property §6 is built around.

**9.6 — Price in the maintenance tail; Krux is the case study.** Krux's KEF envelope now spans four cipher
modes (ECB, CBC, CTR, GCM) across roughly twelve version numbers, with padded, unpadded and compressed
variants, on a device that — like aobs — has no update mechanism. Every one of those versions must be
decryptable forever. This feature accretes, and §10's add-only version registry is the shape of that
commitment: **v1 must be readable by every aobs that ever ships.**

---

## 10. Format versioning under "no update mechanism, old ISOs in circulation"

1. **Version is byte 0 and it is inside the AAD.** It cannot be altered without breaking the Poly1305 tag.
2. **Unknown version ⇒ refuse, loudly and specifically.** An aobs that reads a version byte it does not
   recognise must display the version number it found and state that a newer ISO is required. It must
   never attempt a best-effort parse. Best-effort parsing of key material is how a wrong wallet gets
   restored silently.
3. **Print the version even on failure.** The restore screen should show the format version it read even
   when it cannot decrypt, so a user holding the wrong ISO gets an actionable message rather than
   "invalid backup".
4. **Add-only registry: version 0x01 is never desupported.** Because old ISOs stay in circulation, so do
   old backups. Every future aobs must keep reading 0x01. This is the entire versioning policy and it is
   one line; the discipline it requires is refusing, permanently, to remove a version.
5. Old ISOs cannot read newer backups. That is unavoidable and belongs in the user-facing documentation
   as a stated property, not discovered at restore time.
6. Reject non-zero reserved flag bits and out-of-range `entropy_len` rather than ignoring them, so a
   future version that assigns them cannot be silently misread by a v1 reader.

---

## Sources

| Claim | Source |
| --- | --- |
| Argon2id, both recommended parameter sets, variant guidance, salt/tag lengths, `m' = 4p·floor(m/4p)` | [RFC 9106](https://www.rfc-editor.org/rfc/rfc9106.html) |
| EFF long list: 7776 words, 12.9 bits/word, six-word recommendation, dice selection | [EFF, *Deep Dive: EFF's New Wordlists for Random Passphrases*](https://www.eff.org/deeplinks/2016/07/new-wordlists-random-passphrases) |
| Argon2id GPU/CPU throughput at m=65536, t=3; hash-mode 34000 uses the PHC implementation | [hashcat 7.0.0 release notes](https://github.com/hashcat/hashcat/blob/master/docs/releases_notes_v7.0.0.md) |
| SHA2-256 rate on RTX 4090 (21,975.5 MH/s) | [Chick3nman, hashcat v6.2.6 RTX 4090 benchmark](https://gist.github.com/Chick3nman/32e662a5bb63bc4f51b847bb422222fd) |
| RTX 4090: 450 W TGP, 24 GB GDDR6X | [NVIDIA RTX 4090 specifications](https://www.nvidia.com/en-us/geforce/graphics-cards/40-series/rtx-4090/) |
| age v1: scrypt stanza, all-zero nonce, HKDF labels, header HMAC, 64 KiB chunks, no metadata slot | [age specification (C2SP)](https://github.com/C2SP/C2SP/blob/main/age.md) |
| `rage --max-work-factor`; use the `age` crate as a library | [rage README](https://github.com/str4d/rage) |
| `chacha20poly1305` NCC Group audit, XChaCha 192-bit nonce | [RustCrypto/AEADs `chacha20poly1305`](https://github.com/RustCrypto/AEADs/blob/master/chacha20poly1305/README.md) |
| `aes-gcm` audit and variable-time-multiplication caveat | [RustCrypto/AEADs `aes-gcm`](https://github.com/RustCrypto/AEADs/blob/master/aes-gcm/README.md) |
| RustCrypto `aes` is constant-time via AES-NI or bitslicing | [RustCrypto/block-ciphers `aes`](https://github.com/RustCrypto/block-ciphers/blob/master/aes/README.md) |
| `argon2` crate: variants, no audit statement | [RustCrypto/password-hashes `argon2`](https://github.com/RustCrypto/password-hashes/blob/master/argon2/README.md) |
| `argon2` defaults (19 MiB / t=2 / p=1); AD field deprecated and unused | [`argon2/src/params.rs`](https://github.com/RustCrypto/password-hashes/blob/master/argon2/src/params.rs) |
| AES-NI introduced with 32 nm Westmere, January 2010 | [Intel, AES Instructions Set](https://www.intel.com/content/www/us/en/developer/articles/tool/intel-advanced-encryption-standard-aes-instructions-set.html) |
| BIP-39: 2048 words, four-letter prefix uniqueness, ENT/CS/MS table, PBKDF2-HMAC-SHA512 2048 rounds | [BIP-39](https://github.com/bitcoin/bips/blob/master/bip-0039.mediawiki) |
| SLIP-39: Feistel/PBKDF2 construction, share fields, no passphrase verification | [SLIP-39](https://github.com/satoshilabs/slips/blob/master/slip-0039.md) |
| Coldcard: 7z AES-256-CBC, 12 BIP-39 words, 132 bits, contents include settings | [Coldcard backup docs](https://coldcard.com/docs/backups/), [`shared/backups.py`](https://github.com/Coldcard/firmware/blob/master/shared/backups.py) |
| Passport: 7z AES-256, 20-digit device-generated code | [Foundation, *Why we love encrypted microSD backups*](https://foundation.xyz/blog/why-we-love-encrypted-microsd-backups) |
| Krux: KEF envelope layout, PBKDF2, cipher-mode version table | [`src/krux/kef.py`](https://github.com/selfcustody/krux/blob/main/src/krux/kef.py), [`src/krux/encryption.py`](https://github.com/selfcustody/krux/blob/main/src/krux/encryption.py) |
| SeedQR is plaintext by design | [SeedSigner SeedQR docs](https://github.com/SeedSigner/seedsigner/blob/main/docs/seed_qr/README.md) |
