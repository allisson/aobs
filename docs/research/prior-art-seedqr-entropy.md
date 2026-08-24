# Prior art: Seedsigner, Krux, SpecterDIY — encrypted seed QRs and entropy

Research note for [issue #7](https://github.com/allisson/aobs/issues/7). Aimed at unblocking
[#8](https://github.com/allisson/aobs/issues/8) (entropy mixing) and
[#9](https://github.com/allisson/aobs/issues/9) (encrypted-wallet-QR format).

Status: **complete for the two decisions it was aimed at.** Claims read from source or from a
project's own normative doc are marked CONFIRMED and carry a file path. Everything I could not
confirm is listed in "Unresolved / not confirmed" at the end, each with the specific check that
would settle it. No cipher parameter, size, or advisory identifier in this note is from memory —
parameters come from the code, QR capacities were computed, and the advisory registries were
queried directly.

## Method

Primary sources only: each project's own source tree and its own docs, plus the specs they cite
(BIP39, BIP32, RFC 9106 for Argon2, RFC 8439 for ChaCha20-Poly1305, ISO/IEC 18004 for QR). No blog
posts, no third-party summaries. CVE/advisory claims come from GitHub Security Advisories or the
projects' own release notes, or they are reported as "not found".

Repos under investigation:

- SeedSigner — `github.com/SeedSigner/seedsigner`
- Krux — `github.com/selfcustody/krux`
- Specter-DIY — `github.com/cryptoadvance/specter-diy`

Commits read (shallow clones, 2026-08-24):

| Project | Commit | `git describe` |
|---|---|---|
| Krux | `8afa9ee` (2026-08-06) | `v26.04.0-56-g8afa9ee` |
| SeedSigner | `d70b322` (2026-08-22) | `0.8.7-107-gd70b322` |
| Specter-DIY | `3f3c831` (2026-08-16) | `v1.10.3-2-g3f3c831` |

File paths below are relative to each project's repo root at those commits.

---

# 1. Encrypted seed QR

## Krux — KEF ("Krux Encryption Format"). CONFIRMED, fully specified.

Krux is the only one of the three with an encrypted-seed container, and it is genuinely
specified rather than merely implemented. Primary sources:

- `docs/getting-started/features/encryption/kef-specifications.en.md` — 468-line normative spec
- `src/krux/kef.py` (570 lines) — reference implementation (`VERSIONS`, `MODE_IVS`, `Cipher`,
  `wrap`/`unwrap`, `_pad`/`_unpad`, `_deflate`)
- `src/krux/encryption.py` — storage layer, `MnemonicStorage`
- `src/krux/pages/encryption_ui.py` — the UI that chooses parameters and gathers the IV
- `src/krux/krux_settings.py` — defaults (`EncryptionSettings`, line ~416)
- `tests/test_kef.py`, `tests/test_encryption.py` — test vectors

### Container layout (CONFIRMED, spec "Common Structure of a KEF Envelope")

```
len_id + id + v + i + cpl
```

| Field | Size | Meaning |
|---|---|---|
| `len_id` | 1 byte | length of `id`, 0–252 |
| `id` | `len_id` bytes | **doubles as the PBKDF2 salt** and as the user-visible label |
| `v` | 1 byte | version code, selects mode/padding/auth/compression |
| `i` | 3 bytes big-endian | iteration count |
| `cpl` | variable | cipher payload: `IV` + ciphertext + `auth`, layout per version |

Self-describing and version-dispatched: 12 assigned version codes (0, 1, 5, 6, 7, 10, 11, 12,
15, 16, 20, 21) across four AES modes (ECB, CBC, CTR, GCM), each with/without raw-deflate
compression, and with either a truncated SHA256 tag or the GCM tag.

### KDF (CONFIRMED)

```
k = pbkdf2_hmac_sha256(K, id, i)          # 256-bit AES key
```

- `K` = user password, encoded UTF-8 **without normalization** (spec is explicit about this).
- salt = `id`, the same field the user sees as a label. There is **no dedicated random salt**.
- effective iterations = `i` if `i > 10_000`, else `i * 10_000`. Stored `i` MUST be >= 1.
- Default in `krux_settings.py:430`:
  `pbkdf2_iterations = NumberSetting(int, "pbkdf2_iterations", 100000, [10000, 500000])`
  — default 100 000, user-settable 10 000–500 000.
- Default mode, `krux_settings.py:429`: `CategorySetting("version", "AES-GCM", ...)`.
- **No Argon2 anywhere.** KEF is PBKDF2-HMAC-SHA256 only. On the K210 it is hardware-accelerated
  (`uhashlib_hw`, changelog 25.x "SHA-256 and PBKDF2-HMAC now use hardware-accelerated hashing").

### Nonce/IV handling (CONFIRMED)

`kef.py` `MODE_IVS`: CBC 16 bytes, CTR 12 bytes, GCM 12 bytes, ECB none.

The IV is **not** from a CSPRNG. `src/krux/pages/encryption_ui.py:287-307`
(`input_iv_ui`) makes the user point the camera at something:

```python
def input_iv_ui(self):
    """implements ui to allow user to gather entropy from camera for iv"""
    if self.iv_len > 0:
        ...  t("Additional entropy from camera required for %s") % self.mode_name
        from .capture_entropy import CameraEntropy
        camera_entropy = CameraEntropy(self.ctx)
        entropy = camera_entropy.capture(show_entropy_details=False)
        ...
        self.__iv = entropy[: self.iv_len]
```

That is a deliberate choice forced by the hardware (see item 7) and it is exactly where their
one real crypto vulnerability landed (item 6).

### Authentication (CONFIRMED) — deliberately truncated

Three forms, per version:
- GCM: `auth = authtag[:4]` — **4 bytes**, exposed.
- non-AEAD, exposed: `auth = sha256(v || iv || P || k)[:3 or :4]`.
- non-AEAD, hidden: `auth = sha256(P)[:4 or :16]`, appended to plaintext before padding.

The spec defends the truncation explicitly, and its reasoning is worth reading before we copy it:

> "KEF's use-case for authentication is to validate that the user has correctly entered their
> decryption `key`. In the worse case, "false-authenticated" success will occur at a rate of
> 1:16M (or 1:4B for others) if using an incorrect decryption `key`; similar if an attacker has
> modified the KEF envelope."

So KEF's `auth` is a **password-typo check, not integrity protection**. A 4-byte tag gives an
attacker a 1-in-2^32 forgery per attempt; with an oracle that is not a meaningful barrier. For
our threat model (issue #9's "is wrong password distinguishable from corrupt QR") this is the
central design fork: KEF chose "small envelope" over "authenticated container".

### What is encrypted (CONFIRMED)

The **BIP39 entropy bytes**, 16 or 32 bytes — not the word string. `encryption.py:113`:
`return bip39.mnemonic_from_bytes(decrypted)`. So a 24-word mnemonic is a 32-byte plaintext.

The spec's version notes say v0/v1 are for "encryption of 16 or 32 BIP39 entropy bytes";
`encryption.py` retains `_deprecated_decrypt` for in-the-wild `seeds.json` files that hold
encrypted mnemonic **words** instead.

The **passphrase is not part of the envelope** in the mnemonic-storage path — CONFIRMED by
`encryption.py` decrypting straight to `mnemonic_from_bytes`. KEF as a *format* can hold a
passphrase as arbitrary plaintext (that was the point of the 23.09 → later extension), but the
stored-mnemonic feature stores entropy only. Consequence for #9: a KEF-style envelope restores
a mnemonic, not a wallet.

### Size budget (CONFIRMED by arithmetic over the spec)

Minimum envelope for a 32-byte 24-word entropy, version 5 (AES-ECB, 3-byte exposed auth,
zero-length `id`): `1 + 0 + 1 + 3 + 32 + 3` = **40 bytes**.
Version 20 (AES-GCM, the default): `1 + len_id + 1 + 3 + 12 + 32 + 4` = **53 + len_id bytes**.
Both fit a single small QR comfortably (see item 2 for the version/capacity table). Krux
base64-encodes the envelope for its JSON storage (`base_encode(kef_envelope, 64)`), which costs
~33%; the spec explicitly leaves QR encoding to the implementation.

### Password delivery (CONFIRMED)

`src/krux/pages/encryption_ui.py` class `EncryptionKey` (line 416): the key comes from a
keypad, or from a scanned QR ("Scan Key QR Code", line 481), and a scanned key may itself be a
KEF envelope that gets decrypted first (lines 488-496). `ENCRYPTION_KEY_MAX_LEN = 200`.
There is **no generated password and no wordlist** — the user invents the password. The spec
compensates with a blunt warning:

> "**KEF offers no expectation of security for a weak user-supplied `key`** ... If a KEF envelope
> has been created with a "weak" `key` and stored accessible to others, user should assume that
> their secret has been leaked."

This is the single biggest divergence from our #9 brief, which fixes the password at 8 EFF
large-wordlist words (~103 bits) generated by the appliance. **Our choice is better and we
should not copy theirs.** With ~103 bits of real password entropy, PBKDF2 vs Argon2id barely
matters; with a human-invented password, the KDF is all you have and PBKDF2-100k is thin.

### Two further KEF details worth flagging

- **Iteration jitter is timer-derived, not random.** `encryption_ui.py:186-188`:
  ```python
  self.iterations = Settings().encryption.pbkdf2_iterations
  max_delta = self.iterations // 10
  self.iterations += int(time.ticks_ms()) % max_delta
  ```
  The spec asks for "a small `delta` as extra bits of entropy to derive different AES-256 keys
  that would otherwise be the same in the event the user re-uses the same `key`, `id` and
  `iterations`". The implementation sources that delta from a millisecond tick counter. It is a
  band-aid for the missing random salt. **A real random salt is the correct fix; do not copy
  the jitter.**
- **ECB is still an offered mode**, guarded only by a duplicate-block check
  (`kef.py:190-195`). The spec's own security note admits ECB "would leak patterns within
  ciphertext". Offering it at all is a backwards-compatibility cost we do not have.

## SeedSigner — no encrypted seed QR at all. CONFIRMED.

There is no encryption anywhere in SeedSigner's source. A repo-wide grep for
`AES|pbkdf2|Cipher|Argon|ChaCha|encrypt(` over `src/` returns exactly one hit, and it is not
encryption — it is Electrum's seed derivation, `src/seedsigner/models/seed.py:186`:

```python
self.seed_bytes = hashlib.pbkdf2_hmac('sha512', self.mnemonic_str.encode('utf-8'),
    b'electrum' + self._passphrase.encode('utf-8'),
    iterations=SettingsConstants.ELECTRUM_PBKDF2_ROUNDS)
```

SeedQR and CompactSeedQR are **plaintext**, deliberately. Their spec is explicit that the
threat model is a hand-transcribed metal backup you keep physically, not a document you can
safely leave lying around. This is a coherent position, and it is *not* the position issue #9
takes — but it means SeedSigner offers us no encrypted-container prior art, only a size budget
(item 2) and a warning about binary QR payloads.

## Specter-DIY — encrypted storage, but no password-based export QR. CONFIRMED.

Specter encrypts its on-device storage, not an exportable backup. `src/helpers.py`:

- `encrypt`/`decrypt`: AES-256-CBC, IV 16 bytes from `rng.get_random_bytes(IV_SIZE)`,
  **bit-padding** (`0x80` then NUL fill) rather than PKCS7.
- `aead_encrypt`/`aead_decrypt`: encrypt-then-MAC, output
  `<compact-len:adata><iv><ct><hmac>`, with a **full 32-byte HMAC-SHA256** and proper key
  separation via `tagged_hash`:
  ```python
  aes_key  = tagged_hash("aes", key)
  hmac_key = tagged_hash("hmac", key)
  ```
  `tagged_hash` is the BIP340-style construction `sha256(sha256(tag) || sha256(tag) || data)`.

Crucially, **the key is a device secret, not a user password** — `src/keystore/flash.py:148,183`
and `src/keystore/ram.py:158` all derive it from `get_random_bytes(32)`. There is **no
password-based KDF in Specter at all**: no PBKDF2, no Argon2. So Specter has no analogue of our
encrypted wallet QR, and nothing to copy for #9's KDF question.

What *is* worth copying from Specter for #9 is the **container discipline**: full-length
HMAC-SHA256, encrypt-then-MAC, and distinct sub-keys per purpose derived by tagged hashing.
Compare that with KEF's 3-or-4-byte truncated tag. If #9 wants "wrong password" to be reliably
distinguishable from "corrupt QR", Specter's shape is the right one and KEF's is not.

---

# 2. SeedQR and CompactSeedQR — the plaintext size budget

Primary source: `docs/seed_qr/README.md` (SeedSigner), 550 lines, normative, with nine test
vectors. Encoder/decoder: `src/seedsigner/models/encode_qr.py`, `models/decode_qr.py`.

### Standard SeedQR (CONFIRMED)

BIP39 English wordlist index of each word, **zero-padded to exactly 4 decimal digits**,
concatenated, encoded in QR **Numeric** mode.

- 12 words → 48 digits → **25x25 (QR version 2)**
- 24 words → 96 digits → **29x29 (QR version 3)**

The spec is emphatic that the English wordlist is assumed and there is no language tag:
"there is no mechanism to specify or detect which language wordlist was used". A same-index
word in another wordlist silently yields a different seed.

### CompactSeedQR (CONFIRMED)

The raw BIP39 entropy — 11 bits per word, **checksum bits dropped** (4 bits for 12 words, 8 for
24) — encoded in QR **Byte** mode.

- 12 words → 132 - 4 = 128 bits = **16 bytes** → **21x21 (QR version 1)**
- 24 words → 264 - 8 = 256 bits = **32 bytes** → **25x25 (QR version 2)**

I verified those capacities independently rather than trusting the doc's screenshot, computing
byte-mode capacity at ECC level L with `segno` (which implements the ISO/IEC 18004 tables):

| QR version | modules | byte capacity at ECC L |
|---|---|---|
| 1 | 21x21 | 17 |
| 2 | 25x25 | 32 |
| 3 | 29x29 | 53 |
| 4 | 33x33 | 78 |
| 5 | 37x37 | 106 |
| 6 | 41x41 | 134 |
| 7 | 45x45 | 154 |
| 8 | 49x49 | 192 |

32 bytes lands exactly on the version-2 boundary — CompactSeedQR is sized to the millimetre.

### Why this matters for #9's size budget

Our encrypted container adds a header, a salt, a nonce and a tag on top of the same 32-byte
payload. Sketching a sane one:

```
version(1) + salt(16) + argon2 params(3) + nonce(12) + ciphertext(32) + tag(16) = 80 bytes
```

80 bytes is **QR version 4, 33x33**, at ECC L. That is one size up from a 24-word
CompactSeedQR and comfortably readable by a webcam. Even a generous 106-byte container stays at
version 5 (37x37). **Conclusion for #9: there is no size pressure. A full 16-byte AEAD tag and
a real 16-byte random salt cost us one QR version step, and we should simply pay it.** KEF's
truncation to 3-4 bytes buys 12 bytes, which here buys nothing.

Note this budget assumes **binary QR mode**. If #9 armours the payload as base64 (+33%) or
bech32, 80 bytes becomes ~108 characters, which in alphanumeric mode is around version 5-6.
Still fine, but binary mode is strictly better if the reader supports it.

### The binary-QR trap SeedSigner documents — copy this test suite idea

CompactSeedQR's spec devotes test vectors 2 and 7-9 to bytes that break QR readers:

> "Note that this vector and a few others below include a null byte character (`\x00`) in its
> CompactSeedQR bytestream. This is a particularly troublesome character for most QR readers;
> most will read this character as an instruction to stop reading any further data.
> Take extra care to confirm that your implementation correctly reads these characters and all
> remaining data after it!"

Vectors 7, 8 and 9 exist specifically to cover payloads containing `\n`, `\r` and `\r\n`.
The spec also warns that zxing returns framing bytes and padding around the payload (a 12-word
compact QR "will start with `41 0` ... and end with `0 ec`") while ZBar returns just the data.

**This is directly actionable for us.** Our encrypted container is high-entropy ciphertext, so
roughly 1 payload in 3 will contain a NUL byte somewhere, and embedded newlines are near
certain across many exports. Our QR-channel tests must include fixtures whose ciphertext
contains `\x00`, `\n`, `\r`, and `\r\n`, and must assert full-length round-trip. This is a
class of bug that only shows up for some users, on some seeds, which is the worst kind.

---

# 3. Entropy: what each project actually does, and who meets our floor

This is the heart of the ticket, so the combining code is quoted rather than described.

## SeedSigner — iterated SHA256 chain, camera-dominated, no CSPRNG. CONFIRMED.

`src/seedsigner/views/tools_views.py:170-203` is the entire mixing construction:

```python
# Build in some hardware-level uniqueness via CPU unique Serial num
try:
    serial_num = b''
    with open("/proc/cpuinfo", "r") as f:
        for line in f:
            if "Serial" in line:
                serial_num = line.split(":")[-1].strip().encode('utf-8')
                break
    serial_hash = hashlib.sha256(serial_num)
    hash_bytes = serial_hash.digest()
except Exception as e:
    logger.info(repr(e), exc_info=True)
    hash_bytes = b'0'

# Build in modest entropy via millis since power on
millis_hash = hashlib.sha256(hash_bytes + str(time.time()).encode('utf-8'))
hash_bytes = millis_hash.digest()

# Build in better entropy by chaining the preview frames
for frame in preview_images:
    img_hash = hashlib.sha256(hash_bytes + frame.tobytes())
    hash_bytes = img_hash.digest()

# Finally build in our headline entropy via the new full-res image
final_hash = hashlib.sha256(hash_bytes + seed_entropy_image.tobytes()).digest()
```

Construction: **chained concatenate-then-hash**, `h_{i+1} = SHA256(h_i || source_i)`.
Sources, in order: Raspberry Pi CPU serial, `time.time()`, 50 camera preview frames, one
full-resolution camera frame. Then `generate_mnemonic_from_bytes(final_hash)` (truncated to 16
bytes for 12 words).

The chaining itself is sound — it is additive, and no source can *cancel* another. **But
`os.urandom` is never called.** A repo-wide grep for `urandom|SystemRandom|secrets\.` over
`src/` returns only `views/screensaver.py` and `views/seed_views.py`, neither in the seed path.

So the *floor* SeedSigner achieves is only as high as its best source, and its best source is
the camera. Under a camera that is fully adversary-controlled, the remaining sources are the
CPU serial (a fixed public-ish device identifier, and note the fallback is the literal
`b'0'`) and `time.time()` (wall clock, guessable to within a window). **SeedSigner would not
satisfy our threat model's strong-entropy claim**, because it has no mandatory source that an
attacker who owns the camera cannot also predict. Two side notes: the comment says "millis
since power on" but the code uses wall-clock `time.time()`; and `hash_bytes = b'0'` on
`/proc/cpuinfo` failure is a silent degradation with no user-visible signal.

## Specter-DIY — SHA-512 pool plus mandatory TRNG. CONFIRMED, and it does meet the floor.

`src/rng.py` in full is 43 lines and is the best construction of the three:

```python
entropy_pool = b"7" * 64

try:
    from os import urandom as get_trng_bytes
except:
    def get_trng_bytes(nbytes):
        with open("/dev/urandom", "rb") as f:
            return f.read(nbytes)

def get_random_bytes(nbytes):
    global entropy_pool
    d = get_trng_bytes(nbytes)
    feed(d)  # why not?
    # if more than 64 - just do trng
    if nbytes > 64:
        return d
    else:
        h = hashlib.sha512(entropy_pool)
        h.update(d)
        return h.digest()[:nbytes]

def feed(data):
    global entropy_pool
    h = hashlib.sha512(entropy_pool)
    h.update(data)
    entropy_pool = h.digest()
```

The pool is fed continuously from the UI. `src/gui/decorators.py`:

```python
def feed_touch():
    point = lv.point_t()
    indev = lv.indev_get_act()
    lv.indev_get_point(indev, point)
    t = time.ticks_cpu()
    random_data = t.to_bytes(4, "big") + bytes([point.x % 256, point.y % 256])
    rng.feed(random_data)
```

Mnemonic generation, `src/helpers.py:21-25`:

```python
def gen_mnemonic(num_words: int) -> str:
    """Generates a mnemonic with num_words"""
    if num_words < 12 or num_words > 24 or num_words % 3 != 0:
        raise RuntimeError("Invalid word count")
    return bip39.mnemonic_from_bytes(rng.get_random_bytes(num_words * 4 // 3))
```

24 words → 32 bytes → takes the `nbytes <= 64` branch → `SHA512(pool || trng)[:32]`. This is
exactly the property our threat model demands: **hardware TRNG is mandatory and unconditional,
the touch pool is additive, and neither can lower the other.** They document the claim in
almost our words, `docs/security-model.md:263-273`:

> "We use multiple sources of entropy: **TRNG of the microcontroller.** Proprietary, certified
> and probably good, but we don't trust it alone. **Touchscreen.** Every touch contributes the
> position and the moment of the touch (in microcontroller ticks at 180 MHz).
> All entropy is hashed together (SHA-512 based entropy pool) and converted to your recovery
> phrase. **The resulting entropy is always at least as good as the best individual source.**"

That last sentence is our #8 requirement, already shipped by someone else. Good news for the
map: the claim is achievable and this is the construction that achieves it.

**Three flaws in it we must not inherit:**

1. **The `nbytes > 64` branch bypasses the pool entirely** and returns raw TRNG. For any
   request over 64 bytes the "at least as good as the best source" property silently drops to
   "exactly as good as the TRNG". `gen_mnemonic` never hits it (32 bytes), so seeds are safe
   today, but it is a trap one refactor away from mattering. Our mixer must have **one** path.
2. **The pool's initial value is the constant `b"7" * 64`.** Before any touch, the pool
   contributes nothing. Harmless given the mandatory TRNG — which is precisely the argument for
   making the CSPRNG mandatory — but it means the pool is not a floor of its own.
3. **The code comments admit the design is unfinished**: "probably not the best way at the
   moment, but anything is better than nothing", and `feed(d)  # why not?`. Feeding the TRNG
   output back into the pool is harmless but pointless, and "why not?" is not a rationale. Our
   equivalent needs a stated argument, because #8's whole point is that the construction be
   defensible.

## Krux — pick-one, no mixing, no CSPRNG. CONFIRMED, and it fails the floor.

Krux offers **alternative** entropy sources, never combined:
`src/krux/pages/login.py` — "Via Words", "Via D6", "Via D20" (line 95-97), plus
`new_key_from_snapshot` (camera). Each path independently produces the full entropy:

- dice → `hashlib.sha256(entropy_bytes).digest()[:num_bytes]`
  (`pages/new_mnemonic/dice_rolls.py`, last line of `new_key`)
- camera → `hasher.digest()` of the image buffer (`pages/capture_entropy.py`, last line of
  `capture`)

There is **no kernel CSPRNG contribution to either**, and this is deliberate and documented.
Their changelog for 26.08.0 states:

> "Remove the unused `os.urandom()` from the MaixPy firmware. It was never called by Krux and
> played no part in generating keys or mnemonics, which draw entropy from the camera or dice.
> **It was backed by a deterministic PRNG**, so it has been removed to keep it from being
> mistaken for a secure source later."

So on Krux's hardware there was no trustworthy CSPRNG to mix in, and they removed the fake one
rather than let it look real. That is the honest call *on that hardware* — and it is precisely
the constraint we do not share (item 7).

The consequence is stark: **on Krux, a single compromised or observed source is a total
compromise.** Dice observed through a window, or a camera pointed at a controlled scene, yields
the whole seed. Krux mitigates with quality gates and warnings (items 4 and 5), never with a
second independent source.

One further weak-randomness spot, `src/krux/key.py:266-275`:

```python
@staticmethod
def pick_final_word(entropy, words):
    ...
    random.seed(int(time.ticks_ms() + entropy))
    return random.choice(Key.get_final_word_candidates(words))
```

`random` here is `urandom` (MicroPython's deterministic PRNG, `key.py:25`
`import urandom as random`), seeded from a millisecond tick counter. This only picks the final
checksum word when the user entered the other words themselves, so the exposure is bounded (3
free bits for a 24-word mnemonic, 7 for a 12-word one) — but it is a timer-seeded PRNG choosing
key material, and it is the pattern to watch for in our own code.

## Summary: who meets our threat model's floor

| | mandatory strong source | sources combined | meets our "floor" claim |
|---|---|---|---|
| Specter-DIY | yes — TRNG / `os.urandom`, unconditional | SHA-512 pool, `SHA512(pool \|\| trng)` | **Yes** (for `nbytes <= 64`) |
| SeedSigner | no | chained `SHA256(h \|\| source)` | No — best source is the camera |
| Krux | no (removed the fake one) | not combined; user picks one | No — single source is the whole seed |

**Recommendation for #8:** adopt Specter's shape, not Krux's or SeedSigner's. Concretely:
one code path, `H(domain_tag || csprng_32 || conditioned_webcam || conditioned_dice)`, with the
CSPRNG read unconditionally and the optional sources contributing empty-but-present byte strings
when skipped. Prefer a hash with explicit length-framing per source (or HKDF-Extract with the
concatenation as IKM) over bare concatenation, so a long webcam contribution cannot be
reinterpreted as dice bytes. Never XOR — an XOR of user-supplied dice against system entropy is
exactly the construction where an adversary who learns the system value can force any output.

---

# 4. Dice

## SeedSigner (CONFIRMED)

`src/seedsigner/helpers/mnemonic_generation.py`:

```python
DICE__NUM_ROLLS__12WORD = 50
DICE__NUM_ROLLS__24WORD = 99

def generate_mnemonic_from_dice(roll_data: str, ...) -> list[str]:
    """
        Uses the iancoleman.io/bip39 and bitcoiner.guide/seed "Base 10" or "Hex" mode approach:
        * dice rolls are treated as string data.
        * hashed via SHA256.

        Important note: This method is NOT compatible with iancoleman's "Dice" mode.
    """
    entropy_bytes = hashlib.sha256(roll_data.encode()).digest()
    if len(roll_data) == DICE__NUM_ROLLS__12WORD:
        entropy_bytes = entropy_bytes[:16]
    return bip39.mnemonic_from_bytes(entropy_bytes, ...).split()
```

**D6 only, no D20.** 50 rolls for 12 words, 99 for 24. The roll string is hashed as ASCII —
never bit-packed — so the non-power-of-two bias problem is sidestepped entirely rather than
solved. Nothing is mixed in: dice alone determine the seed.

99 D6 rolls carry 99 x log2(6) = **255.9 bits**, so 99 is the honest minimum for 256 bits and
they chose correctly. (50 rolls = 129.2 bits for a 128-bit seed, likewise correct.)

SeedSigner also offers **coin flips** (`generate_mnemonic_from_coin_flips`, 128 or 256 flips,
same SHA256-the-ASCII-string treatment) and, per the 0.5.1 release notes, options to supply the
final word's entropy by coin flips, direct BIP39 word selection, or "finalize with zeros".

The one thing SeedSigner does here that neither other project does, and that we should copy the
*spirit* of: **external verifiability.** `docs/dice_verification.md` (273 lines) walks the user
through reproducing the exact same mnemonic from the same 99 rolls on iancoleman.io/bip39 and
bitcoiner.guide/seed, and `mnemonic_generation.py` is runnable as a standalone CLI for the same
purpose ("It can also be run as an independently-executable CLI to facilitate external
verification of SeedSigner's results for a given input entropy"). That directly answers #8's
"Verification" bullet — a user who cannot audit the running binary *can* audit a
deterministic-from-dice path against a third-party tool.

**The catch, and it is a big one for us:** that verifiability only exists *because* the dice
path is a pure function of the rolls, with no system entropy mixed in. **Verifiability and our
floor requirement are in direct tension.** You cannot both mix in a secret CSPRNG value and let
the user reproduce the result elsewhere. #8 must pick one, and the threat model already picks:
the floor wins. So our verification story cannot be "reproduce the seed offline"; it has to be
something weaker, e.g. displaying the SHA256 of the dice contribution alone so the user can
confirm their rolls were ingested verbatim, while the final seed remains unreproducible. That
distinction should be stated explicitly in #8, because "Krux/SeedSigner let me verify and you
don't" is a question users will ask.

## Krux (CONFIRMED)

`src/krux/pages/new_mnemonic/dice_rolls.py`:

```python
D6_12W_MIN_ROLLS = 50
D6_24W_MIN_ROLLS = 99
D20_12W_MIN_ROLLS = 30
D20_24W_MIN_ROLLS = 60
MIN_ENTROPY_12W = 128
MIN_ENTROPY_24W = 256
ENTROPY_TOLERANCE = 2  # bits
PATTERN_DETECT_TOLERANCE = 30  # %
```

Final step, identical in substance to SeedSigner:

```python
entropy = "".join(self.rolls) if self.num_sides < 10 else "-".join(self.rolls)
...
num_bytes = 32 if len_mnemonic == 24 else 16
return hashlib.sha256(entropy_bytes).digest()[:num_bytes]
```

D6 counts match SeedSigner's. D20: 60 rolls x log2(20) = 259.3 bits for 24 words, 30 rolls =
129.7 bits for 12 — again correct. Note the delimiter matters: D20 rolls are joined with `-`
because "1" then "2" would otherwise be ambiguous with "12". A subtle encoding lesson: the
string fed to the hash must be unambiguously parseable, or two different roll sequences can
collide onto the same seed.

Krux goes considerably further than SeedSigner on **fabricated-roll detection**, and this part
is worth copying:

- `calculate_entropy()` — Shannon entropy of the roll distribution x roll count, compared
  against `MIN_ENTROPY_12W/24W` with a 2-bit tolerance.
- `pattern_detection()` — Shannon entropy of the **first derivative** of the roll sequence
  (`rolls[i] - rolls[i-1]`), normalized against `log2(range)`, flagged if the deviation exceeds
  30%. This catches arithmetic progressions ("1,2,3,4,5,6,1,2,3..."), which a plain
  distribution test passes cleanly. That is a genuinely good idea: a user faking rolls
  overwhelmingly produces sequences that are flat in distribution but structured in
  derivative.
- `stats_for_nerds()` — draws the roll histogram and the Shannon figure.

**Both warnings are advisory only.** The code shows "Poor entropy!" / "Pattern detected!" and
then asks `self.prompt(t("Proceed anyway?"))`, and a user who says yes gets the seed. Given
Krux mixes in nothing else, a user who clicks through gets a weak seed with no floor beneath
it. In our design the same warning is safe to make advisory precisely because the CSPRNG is
underneath it — which is a good argument to reuse in #8.

Krux also displays `SHA256 of rolls` in full before generating. For 24 words that displayed
hex string **is** the entropy, so the screen shows the seed material — a deliberate
verifiability-vs-shoulder-surfing trade they made in favour of verifiability.

## Specter-DIY

**No dice support.** Confirmed by grep for `dice|d6|d20|roll` across `src/` and `docs/` —
zero hits in any entropy context. Specter relies solely on TRNG plus the touch pool.

---

# 5. Camera entropy

## Krux — gate, then hash the whole frame. CONFIRMED.

`src/krux/pages/capture_entropy.py`. Thresholds:

```python
POOR_VARIANCE_TH = 10               # RMS of L, A, B channel stdevs
INSUFFICIENT_VARIANCE_TH = 5
INSUFFICIENT_SHANNONS_ENTROPY_TH = 3   # bits per pixel
```

The conditioning is: no conditioning, but a **hard refusal gate** on two independent measures,
then SHA256 over the raw frame:

```python
shannon_16b = shannon.entropy_img16b(img_bytes)
...
if (shannon_16b < INSUFFICIENT_SHANNONS_ENTROPY_TH
        or self.stdev_index < INSUFFICIENT_VARIANCE_TH):
    error_msg = t("Insufficient entropy!")
    ...
    return None                      # refuses outright — no "proceed anyway"
...
hasher = hashlib.sha256()
while hasher_index < image_len:
    hasher.update(img_bytes[hasher_index : hasher_index + 128])
    hasher_index += 128
return hasher.digest()
```

Two things to note. First, unlike the dice path there is **no "Proceed anyway?" override** —
insufficient camera entropy is a hard stop. Second, the guard is real but shallow: it measures
*variation within one frame*. A hostile but visually busy scene — a printed photograph of
static, a screen showing a fixed noisy image — passes both gates while being entirely
predictable to the attacker who chose it. **A per-frame statistic cannot distinguish "noisy" from
"unpredictable".** That is the fundamental limit of camera entropy and it applies to us too.

Krux reports its yield to the user as Shannon's entropy in bits and bits/px (a full-frame
figure in the tens of thousands of bits) but takes only 256 bits out via SHA256, so no yield
*claim* is being made beyond "enough". The camera path is also labelled
**"(Experimental)"** in `login.py:127`, years after shipping.

## SeedSigner — frame pool with NIST-flavoured health tests. CONFIRMED.

`src/seedsigner/gui/screens/tools_screens.py`, `PREVIEW_POOL_SIZE = 50`, plus the docstring on
`ToolsImageEntropyLivePreviewView` which is the clearest statement of intent in any of the three
codebases:

> "A fixed number of live preview frames are collected into a frame pool to provide an
> additional source of entropy. These frames provide VOLUME for the final seed but are not
> themselves individually assessed for entropy QUALITY. ...
> 1.) A frame that is a single flat color is rejected (e.g. completely black, completely white,
> all just one shade of green).
> 2.) A frame identical to any previously admitted frame is rejected (de-duplicated via
> sha256).
> ...
> This mirrors the role that **NIST SP 800-90B (sec. 4.2)** assigns to continuous health tests:
> detect gross noise-source failure -- a sensor stuck on one value, a stalled or repeating
> camera -- **without attempting to measure entropy.**"

Rule 1 is implemented with `PIL.Image.getextrema()`:

```python
frame_has_variation = False
for lowest_value, highest_value in frame.getextrema():
    if lowest_value != highest_value:
        frame_has_variation = True
```

Rule 2 keeps a never-pruned set of frame SHA256 digests, so a stalled camera repeating one
frame can never fill the pool. The pool must be **full (50 distinct, non-flat frames)** before
the final full-resolution capture is allowed, and a short pool raises rather than degrades:

```python
if ret is None or len(ret) != ToolsImageEntropyLivePreviewScreen.PREVIEW_POOL_SIZE:
    raise Exception(_("Entropy collection failed. Expected {expected} preview frames, got {actual}")...)
```

The final image is taken at `resolution=(2*max_dim, 2*max_dim)` — "at least 4x the number of
pixels the screen can actually display" — and the display copy is `autocontrast`-boosted while
"the original pixels" are preserved for hashing. Afterwards the code explicitly drops the image
references (`self.controller.image_entropy_final_image = None`) with the comment "Image should
never get saved nor stick around in memory".

**SeedSigner's guard is better than Krux's** on the failure modes it targets: it catches a
stalled or repeating camera, which Krux's per-frame statistic does not. Krux's is better at
catching a *low-variance* frame, which SeedSigner's flat-colour test only catches in the
degenerate all-identical-pixels case. They are complementary, and the honest reading is that
**we should implement both**, and be clear in the docs that neither detects a hostile-but-busy
scene.

The framing to steal outright is SeedSigner's: **health test, not entropy estimate.** Citing
NIST SP 800-90B sec. 4.2 gives the check a defensible purpose ("detect gross noise-source
failure") instead of an indefensible one ("prove there are N bits here"). Our threat model
already says the webcam is additive either way, which means a failed health check must be
allowed to *warn without blocking* — exactly what 800-90B-style continuous tests are for.

## Specter-DIY

No camera-frame entropy. Its camera module (`src/hosts/qr.py`) is a QR scanner only. Its
non-TRNG source is the touchscreen (item 3).

---

# 6. Mistakes, CVEs and post-mortems — the highest-value item

## The formal record is empty. CONFIRMED, and stated precisely.

- GitHub Security Advisories, `GET /repos/{owner}/{repo}/security-advisories`:
  `SeedSigner/seedsigner` → `[]`, `selfcustody/krux` → `[]`,
  `cryptoadvance/specter-diy` → `[]`.
- NVD 2.0 keyword search (`services.nvd.nist.gov/rest/json/cves/2.0?keywordSearch=`) for
  `seedsigner`, `krux+bitcoin`, `specter-diy`: `totalResults: 0` for all three.

**There are no CVEs and no published advisories for any of these projects.** I am stating that
as a negative result from those two registries on 2026-08-24, not as proof that nothing was ever
wrong — an unindexed advisory, a forum post-mortem, or a quietly-fixed bug would not appear in
either. What follows is drawn from the maintainers' own changelogs, which is where all three
actually disclose.

## Krux 24.11.1 — the IV was not being used. The most relevant failure to us.

`CHANGELOG.md`, section "Changelog 24.11.1 - November 2024", headed **"Security Fix"**:

> "This release addresses a vulnerability affecting AES-CBC encrypted mnemonics stored on flash
> storage, SD cards, and QR codes. Due to an implementation error, the Initialization Vector
> (IV) in our CBC encryption, **which used camera-generated entropy, was not being correctly
> utilized, which meant it did not provide the intended additional entropy.**"

This is the single most instructive item in the whole ticket. Read it against KEF's design:
the IV is gathered through a multi-screen camera-entropy UI, the spec has a paragraph telling
implementers to "take precautions to ensure that this value is random and not reused", and the
salt is a user-chosen label rather than a random value — so the IV was carrying real
uniqueness duty. And it silently was not plumbed through. It shipped, in a release, affecting
QR codes.

**Lessons for #9, stated as requirements:**
1. **A nonce that is not verifiably random is a nonce you cannot rely on.** Take the nonce and
   the salt from the kernel CSPRNG, one call, no UI, no user gesture. An elaborate ceremony to
   produce the IV is more code, more screens, and more places for it to fail to arrive.
2. **Test that the nonce is actually used.** The property is cheap to assert: encrypt the same
   plaintext under the same password twice and require the ciphertexts to differ. That single
   test would have caught Krux's bug. It belongs in our test harness for #9, named and
   deliberate.
3. **Do not let a random salt be optional or user-supplied.** KEF's `id`-as-salt means two
   users with the same label and the same password derive the same key. A dedicated 16-byte
   random salt removes the whole class.

## Krux 26.08.0 — heap buffer overflow in the camera entropy path.

`CHANGELOG.md`, current release, **"Security Fixes"**:

> "Camera entropy: fix a heap buffer overflow in the Shannon entropy module. Only the Maix Bit
> could trigger it ... The module copied the whole frame into a fixed 320x240 RGB565 (153,600
> byte) scratch buffer, so the Maix Bit's larger CIF frames (352x288 RGB565, 202,752 bytes)
> wrote **49,152 bytes past the end.** The scratch copy has been removed entirely, the read
> length is now capped and rounded to whole pixels..."

Lesson: the *entropy quality estimator* was the memory-safety bug, not the crypto. A frame
whose dimensions the analysis code did not expect overflowed a fixed buffer. Our webcam
conditioning will also be handed frames whose resolution we did not choose (generic amd64,
arbitrary UVC device, driver-negotiated format). **Our frame handling must derive every length
from the frame it was actually given, never from an assumed resolution** — and it should be
fuzzed with odd, large and truncated frame buffers. Writing this in Python removes the overflow
specifically, but the same mismatch becomes a silent wrong-length read or an exception in the
seed path.

## Krux 26.08.0 — the removed fake CSPRNG.

> "Remove the unused `os.urandom()` from the MaixPy firmware. It was never called by Krux and
> played no part in generating keys or mnemonics ... **It was backed by a deterministic PRNG**,
> so it has been removed to keep it from being mistaken for a secure source later."

Lesson: a randomness API that is not actually random is a landmine for the next contributor.
The counterpart obligation for us is the reverse of theirs: we *do* have a real CSPRNG, so #8
must name exactly which interface it reads (`getrandom(2)` / `/dev/urandom`) and assert the
kernel's entropy is initialised before use, rather than trusting whatever a library labels
"random".

## Krux — other changelog items touching this ground

- **PBKDF2 iteration multiples**: "Encrypted Mnemonic QR codes would fail to decrypt if PBKDF2
  iterations settings was changed to non multiple of 10,000." A format that stores iterations in
  a lossy encoding (3 bytes, x10,000 unless > 10,000) produced undecryptable backups. **Lesson
  for #9: encode KDF parameters exactly and losslessly, or fix them by version byte.** Our
  Argon2id parameters should be either literal in the header or implied by a version byte —
  never a compressed approximation.
- **"Krux encrypted mnemonic as a passphrase is invalid, but no error was raised"** — a silent
  wrong-input acceptance in the encryption UI.
- **SD-card `.pyc` precedence** (24.11.0 era, "Vulnerability Fix: Block Import of Python Modules
  from SD Card"): MicroPython preferred frozen modules from removable media over internal flash,
  so code could be run from an SD card. Not entropy or crypto, but directly analogous to a
  LiveCD's module search path — worth carrying to the boot-pipeline ticket rather than #8/#9.

## SeedSigner — no security advisories; one relevant strengthening.

No `SECURITY.md`-published advisories and nothing labelled a vulnerability in the release notes.
The one item on this ground is release **0.4.4** ("The Smart Scanning, Live Preview & Moar
Entropy Release", 2021-08-28):

> "More entropy introduced to seed-from-photo module (CPU serial, milliseconds, frames)"

Read plainly: before 0.4.4 the seed-from-photo path rested on a **single camera image**, and the
CPU serial, timestamp and 50-frame pool were added afterwards. Two later commits continue the
same hardening (`9377f0d` "Collect a minimum pool of preview frames for image entropy",
`45bc864` "Fix held button skipping image entropy preview and review" — the latter a UI bug
that let a user skip the entropy-review step by holding a button). I am **not** calling 0.4.4 a
vulnerability fix; the maintainers did not, and I found no disclosure framing it that way. It is
reported here as the direction of travel: every project on this list has moved *toward* more and
better-guarded sources over time. Nobody has moved the other way.

## Specter-DIY — a disclosure policy, no disclosures.

`SECURITY.md` (added 2026, commit `4139dbd`) defines a private-report-then-90-day process with
named GPG keys, and scopes out "lab-grade physical attacks on the main MCU without the
smartcard" and upstream dependency bugs. No advisories have been published under it. Their
`docs/security-model.md` is candid in the same way the entropy section is — worth reading as a
model for how to write our own claims so they stay checkable.

## The meta-lesson

Every real failure found here is an **implementation or plumbing failure, not a cryptographic
design failure**: an IV that never reached the cipher, a buffer sized for the wrong camera, a
parameter encoding that lost information, a UI that could be skipped. The primitives were
fine. So the leverage for #8 and #9 is not in picking a cleverer construction — it is in
choosing constructions whose correct operation is *cheap to assert in a test*, and then writing
those tests. Concretely, three tests that would each have caught a real shipped bug:
same-plaintext-twice-differs (Krux's IV), round-trip at every KDF parameter value (Krux's
iterations), and adversarial frame dimensions (Krux's overflow).

---

# 7. What does not transfer — their hardware constraints vs ours

The single most important thing to carry out of this research is which of their choices are
*forced* and therefore not evidence for anything in our design.

| Their choice | Why they made it | Transfers to us? |
|---|---|---|
| Krux: no CSPRNG in the seed path | The K210/MaixPy had no trustworthy CSPRNG; the available `os.urandom` was a deterministic PRNG, and they removed it | **No.** We have `getrandom(2)` on a mainline Linux kernel. Their strongest argument for camera-or-dice-only evaporates on our platform. Our threat model already makes the CSPRNG mandatory, and nothing in Krux's design argues against that. |
| SeedSigner: camera as the headline source, no CSPRNG | Same shape of constraint plus a design preference for a user-witnessed physical source; the Pi does have `/dev/urandom`, so this one is a **choice**, not a hardware limit | **No, and note the difference.** SeedSigner *could* have mixed in `os.urandom` and did not. That is a deliberate "only trust what the user can see" stance. It is defensible on its own terms but it is incompatible with our stated floor, and we should say so rather than quietly diverge. |
| Krux: camera-derived AES IV | No CSPRNG to draw an IV from | **No.** Draw nonce and salt from the CSPRNG. This is also where their one real vulnerability lived. |
| Krux: PBKDF2-HMAC-SHA256, no Argon2 | 8 MB SRAM on the K210 cannot host a memory-hard KDF; PBKDF2 is hardware-accelerated there | **Partially.** We *can* run Argon2id, but #9's "hard memory budget" concern is real for a boot-to-RAM appliance and is our own constraint, not an inherited one. It needs its own number against our own RAM budget. |
| KEF: 3-4 byte truncated auth tags | Envelope size mattered for tiny QR codes and thermal printers on a 320x240 screen | **No.** Item 2's capacity table shows a full 16-byte AEAD tag costs us at most one QR version step. Pay it. |
| KEF: `id` (a user label) doubles as the PBKDF2 salt, with timer-derived iteration jitter | No CSPRNG for a real salt; the label was already in the envelope, so reusing it was free | **No.** Use a 16-byte CSPRNG salt as its own field. |
| Krux/SeedSigner: dice ASCII string hashed, fully reproducible externally | Verifiability for users who cannot audit the firmware | **Only in spirit.** Full reproducibility is incompatible with mixing in a secret CSPRNG value. See item 4 — #8 needs a weaker, honest verification story. |
| SeedSigner: 50-frame pool, flat-frame and duplicate-frame health tests | Fixed, known camera module; frames arrive at a known resolution | **Yes, the tests; no, the assumptions.** The health tests are platform-independent and we should implement them (plus Krux's variance gate). The *fixed resolution* assumption does not hold for us: generic amd64 with an arbitrary UVC webcam means driver-negotiated formats, and that is exactly the mismatch that produced Krux's buffer overflow. |
| SeedSigner: CPU serial from `/proc/cpuinfo` as a source | A Raspberry Pi has a stable per-board serial there | **No, and it is a bad idea for us anyway.** On generic amd64 that field is absent (their fallback is the literal `b'0'`), and a device identifier is not secret — it adds no entropy against an attacker who knows which machine you used. Our threat model gets nothing from it. |
| Specter: touchscreen coordinates + CPU ticks feeding the pool | It has a touchscreen and no other cheap continuous source | **The construction, not the source.** We have no touchscreen; our optional sources are the webcam and dice. The `SHA512(pool \|\| trng)` shape is what transfers. |
| Specter: `nbytes > 64` returns raw TRNG | An optimisation for large requests on a constrained MCU | **No.** One path only. |
| All three: entropy source doubles as a physical ceremony the user watches | Dedicated device, no OS, the user's trust has nowhere else to go | **Partially.** We inherit the same trust problem — a stranger booting our ISO cannot audit the running binary either. But we can be more honest about it, because our CSPRNG guarantees a floor that does not depend on the ceremony being meaningful. |

Two further asymmetries in **our** favour, and one against.

In our favour: we have a real kernel CSPRNG, and we have `hashlib`/`hmac`/`argon2` and the whole
CPython ecosystem instead of MicroPython's `ucryptolib` (which is why KEF is AES-only with no
AEAD beyond GCM-with-truncated-tag). Neither of those constraints binds us, so KEF's shape
should be treated as a *catalogue of forced compromises*, not a design to reuse.

Against us: the appliance runs on hardware we have never seen. Krux and SeedSigner know their
camera, their resolution, their RAM. We know none of those. That argues for (a) deriving every
buffer length from the data actually received, (b) an Argon2id memory parameter chosen against a
worst-case RAM budget we state explicitly, and (c) treating "no usable webcam" as an ordinary,
tested path rather than an error — which the threat model's "webcam optional and additive"
already implies.

---

# What to copy, avoid, and improve on — condensed

**Copy:**
- Specter's mixing shape: `H(pool || mandatory_csprng)`, one path, CSPRNG unconditional
  (`src/rng.py`). It already implements our floor claim and documents it in our words.
- Specter's container discipline for #9: encrypt-then-MAC, full-length HMAC-SHA256 (or a full
  AEAD tag), sub-keys separated by tagged hashing (`src/helpers.py` `aead_encrypt`).
- SeedSigner's health-test framing for the webcam, NIST SP 800-90B sec. 4.2: detect gross
  source failure, do not claim to measure entropy. Implement both its rules (flat-frame,
  duplicate-frame) *and* Krux's variance/Shannon gate.
- Krux's dice `pattern_detection()` — Shannon entropy of the roll *derivatives*, which catches
  arithmetic progressions that a distribution test passes.
- Krux's roll counts: 99 D6 or 60 D20 for 256 bits (both genuinely exceed it); unambiguous
  delimiter for multi-digit dice.
- SeedSigner's binary-QR test vectors containing `\x00`, `\n`, `\r`, `\r\n` — our ciphertext
  will hit all of these.
- KEF's self-describing envelope *idea*: length-prefixed header, explicit version byte
  dispatching the whole rule set, and "be strict when encrypting, tolerant and vague when
  decrypting" (never leak *why* a decryption failed).

**Avoid:**
- Krux's "pick one source" model, and any construction where dice or camera *replace* system
  entropy.
- Deriving a nonce or IV from anything but the CSPRNG (Krux 24.11.1).
- Truncated authentication tags (KEF's 3-4 bytes) — we have the QR budget for a full one.
- A user-chosen label as the KDF salt, and timer-derived "jitter" standing in for a random salt.
- Lossy KDF-parameter encoding (KEF's x10,000 iteration field).
- ECB in any form.
- Specter's `nbytes > 64` bypass, and its constant `b"7" * 64` pool seed as any kind of floor.
- A CPU serial or wall-clock timestamp presented as an entropy source.
- Any "randomness" API not confirmed to be a CSPRNG (Krux's removed `os.urandom`).

**Improve on:**
- Argon2id where all three use PBKDF2 or nothing — but justify the memory parameter against a
  stated RAM budget (#9), since a boot-to-RAM appliance pays for it directly.
- A generated 8-word EFF password (~103 bits) instead of KEF's user-invented key. This is our
  biggest single improvement over Krux: with ~103 bits the KDF stops being load-bearing, which
  is the honest answer to #9's "verify Argon2id is actually buying anything".
- Make the floor property a **test**, not a claim: adversarial constant/hostile inputs to the
  mixer, asserting the output still varies with the CSPRNG alone. The threat model already
  demands this and none of the three appears to test it.
- Encrypt-and-restore a *wallet*, not just a mnemonic. Krux's stored envelope holds BIP39
  entropy only, so a restore silently loses the passphrase — #9 should decide this explicitly.

---

# Unresolved / not confirmed

Stated plainly so nothing here is quoted as settled:

1. **Whether an unindexed advisory or forum post-mortem exists** for any of the three. I checked
   GitHub Security Advisories and NVD only, both empty. Confirmed by: searching the projects'
   own issue trackers with the security label, their Telegram/Nostr announcements, and
   `osv.dev` — none of which I queried.
2. **Whether Krux's `id`-as-salt has been formally analysed.** The spec invites scrutiny
   ("Corrections and refinement to, and scrutiny of this specification are appreciated") but I
   found no cryptanalysis of KEF, published or otherwise. Absence of found analysis is not
   absence of analysis.
3. **SeedSigner's exact `encode_qr.py`/`decode_qr.py` behaviour for SeedQR.** I confirmed the
   format from the normative spec and its test vectors, and located the encoder/decoder files,
   but did not read their implementations line by line to confirm they match the spec. The nine
   test vectors in `docs/seed_qr/README.md` are the authority I relied on. Confirmed by: running
   the vectors through those modules.
4. **Whether Specter's `get_random_bytes` >64-byte branch is reachable with attacker influence
   over `nbytes`.** I confirmed `gen_mnemonic` requests 32 bytes and so never takes it; I did
   not audit every other caller. Confirmed by: enumerating all `get_random_bytes` call sites and
   their size arguments.
5. **Krux's `shannon.entropy_img16b`** is a C module I did not read; I took its behaviour from
   the changelog's own description of the overflow and its fix. Confirmed by: reading the C
   source in the MaixPy firmware tree (not in this repo).
6. **Exact QR module sizes at other ECC levels.** My capacity table is ECC level **L** only,
   computed with `segno`. If #9 chooses a higher ECC level for webcam-read reliability — which
   is a real consideration and arguably the right call — the byte budget shrinks and the table
   must be recomputed. Confirmed by: recomputing at M/Q/H before fixing the container size.
7. **Whether `getrandom(2)` is guaranteed initialised** at the point our appliance generates a
   seed, on a machine that has just booted from read-only media with little I/O to draw on. This
   is the one genuinely new risk our platform introduces that none of these projects faced, and
   it belongs in #8. Confirmed by: reading `random.c` semantics for the blocking behaviour of
   `getrandom(2)` without `GRND_NONBLOCK`, and testing on a cold-booted VM.
