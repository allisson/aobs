# QR transport format for PSBTs and wallet backups

Research resolving [issue #2](https://github.com/allisson/aobs/issues/2) of the
[v1 map](https://github.com/allisson/aobs/issues/1). All wallet claims below were verified
against cloned source trees at the commits named in §3, not against documentation or
third-party write-ups.

## Recommendation

**PSBT transport, both directions: BC-UR / UR2, emitting and accepting `ur:crypto-psbt`.**

**Encrypted wallet backup: a single-part `ur:bytes` QR at ECC level H — the same codec, not
a second format, and deliberately never the multi-part path.**

**The trade-off accepted:** we take the larger, less-bounded parser. BC-UR's Rust decoder has
an attacker-reachable unbounded allocation (§4.1) and its fountain decoder — the only
component that ever touches hostile data — ships with no fuzz target upstream. BBQr's parser
is smaller, spec-bounded, and already hardened against exactly our threat model. We are
paying for interoperability with a hardening obligation: cap `seqLen` and `messageLen` at our
own call site, and write the fountain-decoder fuzz target ourselves.

**Why that trade is the right way round:** among the five wallets in scope, **every wallet
that speaks BBQr also speaks `ur:crypto-psbt`, and Specter Desktop speaks UR2 only.** BBQr's
supported set is a strict subset. Choosing BBQr would cost us Specter and buy us no wallet at
all — its one exclusive counterparty, Coldcard Q, is a *signer*, and aobs never talks to
another signer. Meanwhile the map's coverage bar already requires fuzzing and adversarial
tests on critical security components, so we owe the transport decoder a fuzz harness
whichever format wins; BBQr's head start on hardening is a schedule saving, not a capability
we cannot reach.

Electrum reaches neither format and is unreachable by any animated QR (§3.4). That is a
property of Electrum, not a consequence of this choice.

---

## 1. The two candidates, from their specs

### BC-UR / UR2

[BCR-2020-005](https://github.com/BlockchainCommons/Research/blob/master/papers/bcr-2020-005-ur.md).
A UR is `ur:<type>/<seqNum>-<seqLen>/<fragment>`; the fragment is CBOR, Bytewords-encoded.

- Payload alphabet is **Bytewords "minimal" style**: "only first and last letters of each
  word", giving **2 characters per byte — the same efficiency as hexadecimal** — plus a
  CRC-32 of the whole message appended as 8 more characters
  ([BCR-2020-012](https://github.com/BlockchainCommons/Research/blob/master/papers/bcr-2020-012-bytewords.md)).
- Stated goals include "Use the alphanumeric QR code mode for efficiency" and "Include a
  CRC-32 checksum of the entire message in each part to tie them together".
- Multi-part URs are a hybrid. Parts with `seqNum <= seqLen` are plain fixed-rate fragments —
  the spec: *"This is all you need to create a basic multi-part UR"* — and parts with
  `seqNum > seqLen` are **fountain-coded**, "a pseudo-random 'mix' of one or more fragments
  … overlaid using XOR".
- The registry ([BCR-2020-006](https://github.com/BlockchainCommons/Research/blob/master/papers/bcr-2020-006-urtypes.md))
  has **renamed** the types: `crypto-psbt` → `psbt` (tag 40310), `crypto-account` →
  `account-descriptor` (40311), `crypto-output` → `output-descriptor` (40308), `crypto-hdkey`
  → `hdkey` (40303). Deprecated names "should only be read, not written". **Deployed wallets
  disagree with the registry**: nothing in scope emits the new names for PSBTs, and Specter's
  scanner cannot parse them at all (§3.3). aobs must therefore *emit the deprecated
  `crypto-psbt`* and *accept both spellings*.
- The CDDL for `psbt` is simply `bytes`; the CBOR layer adds no structure, it wraps the
  BIP-174 blob.

### BBQr

[BBQr.md](https://github.com/coinkite/BBQr/blob/master/BBQr.md), Coinkite, public domain.
An 8-character ASCII header, then Hex or Base32 text.

```
B$   fixed protocol header (2 chars)
H    encoding:  H = Hex, 2 = Base32 (RFC 4648), Z = zlib (wbits=10, no header) then Base32
P    file type: P = PSBT, T = signed txn, J = JSON, C = CBOR, U = UTF-8 text, B = binary, X = executable
05   total number of QR codes, base 36
00   index of this QR code, base 36
```

- "Your QR **MUST** use the 'alphanumeric' character encoding"; charset `0-9A-Z$%*+-./:`.
- "Since we are not printing these codes, and only showing them on a perfect LCD screen, we
  recommend always using level 'L' (lowest) for error correction."
- "All blocks **must** be equal length, except for the last one" — which lets a receiver
  "place received data into the correct place without receiving the entire series" and size
  its buffer from the first non-runt frame.
- "All 'N' QR codes must be scanned, there is no way to 'skip' one, but they do not have to
  be seen in any particular order." **No fountain coding.**
- Hard ceiling: "up to 1295 (`ZZ` in base 36) parts".
- "Since QR codes themselves feature very robust error detection and recovery, there is no
  need for checksums or other such complexity at this level." No message-level checksum,
  where UR has CRC-32.
- Implementation wart: the prose calls it "This seven-character header" while the field list,
  the example `B$te0100` and the sentence "This is 8 characters of overhead" all say eight.
  It is eight.

---

## 2. Capacity, frames and scan time

### Payload sizes

Real PSBTs serialised with [embit](https://github.com/diybitcoinhardware/embit) against
BIP-174/BIP-371; the taproot figure was re-derived by hand field-by-field (§Appendix).

| Transaction | witness_utxo only | + non_witness_utxo | zlib (wbits=10) of the larger |
|---|---|---|---|
| 1-in / 2-out P2TR, BIP86 key-path, 1 change output | **385 B** | 634 B | 414 B (65%) |
| 10-in / 2-out P2WPKH, BIP84, 1 change output | **1 494 B** | 3 744 B | 2 639 B (70%) |

The `non_witness_utxo` column is the one to size against: Bitcoin Core and several desktop
wallets attach the full previous transaction to every input even for segwit, which is what
turns a 1.5 KB ten-input PSBT into a 3.7 KB one. Consistent with Coinkite's own corpus, where
`1in2out.psbt` = 675 B and `1in10out.psbt` = 992 B
([BBQr.md](https://github.com/coinkite/BBQr/blob/master/BBQr.md)).

### Per-frame capacity

QR alphanumeric capacity verified independently with [segno](https://github.com/heuer/segno)
— v40 holds 4296 / 3391 / 2420 / 1852 characters at ECC L / M / Q / H, reproducing the BBQr
spec's own capacity table exactly (and 4297 characters fits no QR version at all).

Bytes of PSBT carried per frame, after each format's overhead:

| QR version, ECC L | BC-UR | BBQr `H` | BBQr `2` | BBQr `Z` |
|---|---|---|---|---|
| v40 (177×177) | 2 112 B | 2 144 B | 2 680 B | ~3 900 B equiv. |
| v27 (125×125) | 1 030 B | 1 062 B | 1 325 B | ~1 900 B equiv. |

UR's figure is `(chars − len("UR:CRYPTO-PSBT/") − len("123-456/") − 8 CRC) / 2 − ~20 B CBOR
fragment header`. **UR is the least dense of the four**, because Bytewords-minimal is
hex-rate while Base32 is 1.6 chars/byte. BBQr's own text makes the point: "Base32 puts 5.0
bits into 5.5 bits of QR data and is closer to optimum".

### Frames needed

| PSBT | v40-L UR | v40-L BBQr `2` | v27-L UR | v27-L BBQr `2` |
|---|---|---|---|---|
| 385 B taproot | 1 | 1 | 1 | 1 |
| 634 B taproot (+prev tx) | 1 | 1 | 1 | 1 |
| 1 494 B segwit | 1 | 1 | 2 | 2 |
| 3 744 B segwit (+prev tx) | 2 | 2 | 4 | 3 |

**Within one frame of each other on every realistic single-sig payload.** Density does not
decide this, and UR's 20% penalty costs at most one extra frame.

### Scan time, and the fountain-code question

BBQr's Coldcard guidance recommends "250ms frame rate" (4 fps) and warns "Avoid very high
versions (too dense). Better to have a more lower-rez QR codes". Take 4 fps and let `p` be
the probability a displayed frame is decoded by the camera. Monte-Carlo, 20 000 trials.
"Cyclic" is BBQr (loop 1..N until all N seen); "fountain" is the ideal `N/p` bound for UR,
which the real LT code approaches but does not quite reach at small N.

| p | N=1 | N=2 | N=3 | N=4 | N=8 | N=16 |
|---|---|---|---|---|---|---|
| 0.7 cyclic | 0.4 s | 0.8 s | 1.4 s | 2.0 s | 4.9 s | 11.8 s |
| 0.7 fountain | 0.4 s | 0.7 s | 1.1 s | 1.4 s | 2.9 s | 5.7 s |
| 0.5 cyclic | 0.5 s | 1.2 s | 2.2 s | 3.2 s | 8.1 s | 19.9 s |
| 0.5 fountain | 0.5 s | 1.0 s | 1.5 s | 2.0 s | 4.0 s | 8.0 s |

Answering the ticket directly: **both formats recover from dropped frames without
restarting.** BBQr frames are order-independent and idempotent — a missed frame simply comes
round again. What BC-UR adds is that the wait is amortised rather than a full cycle. At
N ≤ 4, which covers every payload above, that is **at most 1.2 seconds even at 50% frame
loss**. It becomes material at N ≥ 8, i.e. payloads past ~20 KB, which single-sig taproot and
segwit do not produce.

**So fountain coding is not a reason to choose BC-UR, and its absence is not a reason to
reject BBQr.** This axis is a tie at our sizes, and it should not be cited later as
justification for the decision.

---

## 3. Interoperability — the axis that decides it

Verified against cloned trees: sparrow `b99b880` (2026-08-10), drongo `a47c2b3`, hummingbird
`6f06b2c`, specter-desktop `3bcbae1` (2026-08-12), electrum `a94e460` (2026-08-14),
libnunchuk / BlueWallet / Coldcard firmware at `master` as of 2026-08-15.

### 3.1 PSBT transport

| Wallet | Scans `ur:crypto-psbt` | Displays `crypto-psbt` | Scans BBQr | Displays BBQr |
|---|---|---|---|---|
| **Sparrow** | yes (+ `psbt`/40310, `bytes`, UR1) | **yes, default** | yes (`P`,`T`,`U`) | yes, but **keystore-gated** |
| **Nunchuk** | yes (+ `bytes`, UR1) | yes | yes (`P`,`T`,`U`,`J`) | yes |
| **BlueWallet** | yes (+ `crypto-account`, `crypto-output`, `crypto-hdkey`, `crypto-multi-accounts`, `bytes`) | **yes, default** | yes, since v7.2.6 (2026-02-23) | **conditional only** |
| **Specter Desktop** | yes | yes | **no** | **no** |
| **Electrum** | **no** | **no** | **no** | **no** |
| *(Coldcard Q — a signer, not a counterparty)* | *no BC-UR at all* | *no* | yes | yes |

**The strict-subset fact.** Sparrow, Nunchuk and BlueWallet all do both. Specter does UR2 and
not BBQr. Nothing in scope does BBQr and not UR2. Choosing BBQr subtracts Specter and adds
nobody.

The two BBQr caveats compound this:

- **Sparrow gates BBQr display on the keystore's wallet model** — offered only for
  `COLDCARD`, `SPARROW`, `KRUX`, auto-selected only for `COLDCARD`
  ([`WalletModel.java#L147-L169`](https://github.com/sparrowwallet/drongo/blob/master/src/main/java/com/sparrowwallet/drongo/wallet/WalletModel.java#L147-L169)).
  aobs cannot rely on landing in that set.
- **BlueWallet only animates BBQr for wallets that were themselves imported over BBQr**
  (`setWalletIdMustUseBBQR` in
  [`StorageProvider.tsx`](https://github.com/BlueWallet/BlueWallet/blob/master/components/Context/StorageProvider.tsx)),
  or when the user presses "Force use BBQR" in
  [`DynamicQRCode.tsx`](https://github.com/BlueWallet/BlueWallet/blob/master/components/DynamicQRCode.tsx).
  Its default is URv2.

So BBQr is the **default export path in exactly zero** of the four coordinators, while
`crypto-psbt` is the default in Sparrow, Specter and BlueWallet and a first-class option in
Nunchuk.

### 3.2 Which UR spelling to emit

Sparrow's [hummingbird](https://github.com/sparrowwallet/hummingbird/blob/master/src/main/java/com/sparrowwallet/hummingbird/registry/RegistryType.java)
knows the new `psbt`/40310 tag but **decode-only** — Sparrow's export is always
`CryptoPSBT` → `ur:crypto-psbt`. Specter's scanner regexes match only `UR:CRYPTO-*` and
`UR:BYTES/`, so `ur:psbt/…` **falls through unhandled**
([`qr-scanner.html#L100-L185`](https://github.com/cryptoadvance/specter-desktop/blob/master/src/cryptoadvance/specter/templates/includes/qr-scanner.html#L100-L185));
that code has not been touched since 2021-08 despite active releases.

**Emit `crypto-psbt`. Accept `crypto-psbt`, `psbt` and `bytes`.** Emitting the registry's
preferred `psbt` would silently break Specter.

### 3.3 Account / xpub export — a downstream decision, evidence recorded here

Not this ticket's question, but it determines whether a coordinator can build a PSBT for us
at all, and the evidence is cheap to record now:

| Wallet | accepts `crypto-account` | accepts `crypto-output` | accepts Coldcard-style `bytes` |
|---|---|---|---|
| Sparrow | yes | yes | yes |
| Specter | **yes** | **no** | yes |
| BlueWallet | yes | yes | yes |
| Nunchuk | **no** | **yes** | yes |
| Electrum | no (plain xpub text only) | no | no |

No single UR type covers all four: Specter needs `crypto-account`, Nunchuk needs
`crypto-output`. **Whoever specifies wallet export must emit both**, or make it selectable.
Flagged, not closed here.

### 3.4 Electrum is unreachable by animated QR, whatever we choose

Electrum has **no animated-QR machinery of any kind** — no `ur:`, no BBQr, no chunking, in
either GUI. Its PSBT QR path is a single static code in base43
([`transaction.py#L1219-L1232`](https://github.com/spesmilo/electrum/blob/master/electrum/transaction.py#L1219-L1232)),
with the alphabet `0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ$*+-./:`
([`bitcoin.py#L533`](https://github.com/spesmilo/electrum/blob/master/electrum/bitcoin.py#L533))
— 43 of QR's 45 alphanumeric characters, chosen for exactly that reason, and denser than
Base32 at ~1.475 chars/byte. But:

- `to_qr_data()` returns `(serialized_tx, is_complete)` and **deliberately emits an incomplete
  PSBT**: it calls `convert_all_utxos_to_witness_utxos()` and sets `is_complete = False`,
  documented as "As space in a QR code is limited, some data might have to be omitted." It
  does not split frames; it drops data.
- That shrink "will not apply if all inputs are taproot, due to new sighash" — so the taproot
  case, our BIP86 target, gets no relief.
- One v40-L QR at 1.475 chars/byte tops out near **2.9 KB**, so the 3 744 B ten-input case
  cannot cross at all, and the encoder is quadratic in length (`FIXME` in the source).

Electrum interop over QR is therefore capped and lossy by Electrum's own design. It is not a
reason to prefer either candidate, and it should not be treated as a regression introduced by
this decision.

---

## 4. Parser risk — the cost we are accepting

The map defends against "hostile data arriving over the QR channel (parser attacks)", and
aobs runs on a LiveCD with **no swap**, so an unbounded allocation is not degradation — it is
an OOM kill.

### 4.1 BC-UR — [`ur` crate](https://github.com/dspicher/ur-rs), v0.5.2, MIT

Actively maintained, `no_std`-capable, small dependency set (`bitcoin_hashes`, `crc`,
`minicbor`, `rand_xoshiro`). Three problems, all of which we must handle:

**(a) Unbounded allocation from a single hostile frame.** The decoder adopts
`sequence_count` from the first part it sees, unvalidated
([`fountain.rs`, `Decoder::receive`](https://github.com/dspicher/ur-rs/blob/master/src/fountain.rs)):

```rust
if self.received.is_empty() {
    self.sequence_count = part.sequence_count;   // attacker-controlled u32
    ...
}
let indexes = part.indexes();
```

`Part::indexes()` calls `choose_fragments(sequence, fragment_count, checksum)`, which for any
part with `seqNum > seqLen` executes `let indexes = (0..fragment_count).collect();` and
`xoshiro.choose_degree(fragment_count)`, the latter being
`(1..=length).map(|x| 1.0 / x as f64).collect()`
([`xoshiro.rs`](https://github.com/dspicher/ur-rs/blob/master/src/xoshiro.rs)). **One QR frame
declaring `seqLen = 0xFFFFFFFF` with `seqNum` above it asks for a `Vec<usize>` and a
`Vec<f64>` of 4.29 billion elements — roughly 34 GB each** — before any key material is
touched. `Decoder::validate` compares later parts against the stored values but cannot help,
because the first part sets them.

*Mitigation, mandatory:* clamp `seqLen` and `messageLen` before handing any part to the
decoder. A sane bound falls straight out of §2 — v40-L caps a frame at ~2.1 KB, and no
in-scope PSBT exceeds ~8 KB, so a ceiling in the low tens of frames and a few hundred KB of
message is generous. This belongs in the spec as a hard requirement, not an implementation
detail.

**(b) The decoder is unfuzzed upstream.** The crate's fuzz targets
([`fuzz/fuzz_targets/`](https://github.com/dspicher/ur-rs/tree/master/fuzz/fuzz_targets)) are
`bytewords_decode.rs`, `bytewords_encode.rs`, `ur_encode.rs`. The **fountain decoder** — the
crate's largest file at 45 KB, holding a mixed-parts pool, an XOR reduction queue and a CBOR
parser, and the only component that ever sees attacker-controlled data — **has no fuzz
target**. That is the single highest-value fuzzing surface in the transport layer.

*Mitigation, mandatory:* aobs writes `fuzz_target!(|parts: Vec<&str>| …)` driving
`Decoder::receive` to completion. The map's coverage bar already requires fuzzing on critical
security components, so this is scheduled work, not new scope.

**(c) Two type spellings.** Because `ur-rs` is registry-agnostic, accepting both `crypto-psbt`
and `psbt` is our code, in the security-critical input path. Small, but it is surface BBQr
does not have.

### 4.2 BBQr — [`bbqr` crate](https://github.com/SatoshiPortal/bbqr-rust), v0.6.0 (2026-08-10), MIT

The road not taken, recorded so the comparison is auditable:

- **Bounded by construction.** `MAX_PARTS = 1295`
  ([`consts.rs`](https://github.com/SatoshiPortal/bbqr-rust/blob/master/src/consts.rs)) is a
  spec-level ceiling — the index is two base-36 characters, it *cannot* express more. Equal-
  length blocks mean total size is known from the first non-runt frame and no length field
  can inflate it.
- **The zlib bomb is already capped upstream.**
  [`decode.rs`](https://github.com/SatoshiPortal/bbqr-rust/blob/master/src/decode.rs) sets
  `MAX_DECOMPRESSED_SIZE: usize = 16 * 1024 * 1024`, builds
  `Decompress::new_with_window_bits(false, 10)` per spec, reads through
  `decoder.take(MAX_DECOMPRESSED_SIZE as u64 + 1)` and returns `DecompressedTooLarge`.
- **Adversarial tests name the right cases.**
  [`tests/decode_hardening_test.rs`](https://github.com/SatoshiPortal/bbqr-rust/blob/master/tests/decode_hardening_test.rs)
  covers `a_zlib_bomb_is_rejected_rather_than_inflated`,
  `a_multibyte_header_is_rejected_not_a_panic`,
  `a_part_with_a_non_base36_index_is_rejected_not_a_panic`,
  `a_later_part_with_multibyte_text_is_rejected_not_a_panic`,
  `a_header_only_first_frame_does_not_complete_the_join`,
  `an_over_limit_zlib_input_is_rejected_before_split`.
- **Pure-Rust, few dependencies**: `data-encoding`, `flate2` with `zlib-rs` (no C linkage),
  `radix_fmt`, `log`, `thiserror`, optional `fast_qr`
  ([`Cargo.toml`](https://github.com/SatoshiPortal/bbqr-rust/blob/master/Cargo.toml)).

**Honest summary of the gap.** BBQr's untrusted grammar is an 8-character fixed header, a
base-36 pair, and one of three alphabets, with its only unbounded primitive already capped.
BC-UR's is Bytewords, a CBOR array, a CRC-32, and a stateful fountain decoder sized by an
attacker-supplied count. **BC-UR is genuinely the riskier parser and we are choosing it
anyway**, because interoperability is the thing aobs cannot manufacture for itself and
hardening is.

---

## 5. The backup: same codec, single frame, and never the multi-part path

Three things separate the encrypted wallet backup from PSBT transport:

1. **There is no counterparty.** A backup is written by aobs and read by aobs. No desktop
   wallet ever parses it, so every interop argument in §3 evaporates and the only remaining
   criterion is minimum parser surface.
2. **It is small and it is one frame.** A backup is a version byte, an Argon2id salt (16 B),
   an AEAD nonce (12–24 B), ciphertext over 16–32 B of entropy plus wallet metadata, and a
   16 B tag — comfortably under 256 bytes. As a single-part `ur:bytes` that is
   `9 + 2×256 + 8 = 529` alphanumeric characters, which fits a **version 20 (97×97) QR at
   ECC H**; 128 B fits v14 (73×73). Nothing animates.
3. **It is printed, not displayed.** BBQr justifies ECC L by "we are not printing these codes,
   and only showing them on a perfect LCD screen". A paper backup creases, fades and gets
   photographed badly. **Use ECC H.**

So: **`ur:bytes` single-part**, `UR:BYTES/<bytewords>`, one static QR, ECC H.

- **Zero new transport code.** Same crate, same Bytewords codec as the PSBT path.
- **The fountain decoder is unreachable here, by rule.** A single-part UR has no `seq`
  component at all. The restore prompt must **reject any input containing a sequence
  component** — one string check that puts §4.1's entire risk out of reach on the path that
  runs immediately before a seed enters memory. This is a spec requirement, not a nicety.
- **Type `bytes`, not `crypto-psbt`.** The UR type is self-describing, so a PSBT scanned at
  the restore prompt is rejected on the type string rather than on a crypto failure, and a
  backup scanned at the PSBT prompt likewise. A free confusion-attack guard, and the reason
  to keep a UR wrapper on a payload that needs no splitting.
- **No compression, ever.** Ciphertext is incompressible. UR has no compression layer at all,
  which is exactly what we want here — the backup path never touches an inflater.
- **Integrity is cryptographic, not CRC.** UR's CRC-32 comes along for free, but the AEAD tag
  is the real check and it is strictly stronger.

The alternative — BBQr type `B`, encoding `2` — is denser (418 chars vs 529 at 256 B, v18 vs
v20) but would mean carrying a second codec and its `flate2`/`data-encoding`/`radix_fmt`
dependencies solely for a 250-byte blob. Not worth it for two QR versions.

---

## 6. What would reopen this

- **`ur-rs` gains a `seqLen` bound and a fountain-decoder fuzz target.** Then §4 largely
  dissolves and this decision gets cheaper, not different.
- **BBQr becomes the default export in Specter, or Specter adds it.** Only then does BBQr stop
  being a strict subset. Watch
  [`qr-scanner.html`](https://github.com/cryptoadvance/specter-desktop/blob/master/src/cryptoadvance/specter/templates/includes/qr-scanner.html)
  — untouched since 2021-08.
- **Multisig, descriptors or PSBTs above ~20 KB enter scope.** Out of scope per the map, but
  at N ≥ 8 frames the fountain advantage stops being noise (§2), which would *strengthen* this
  choice rather than reverse it.
- **The registry rename reaches deployed wallets.** If Sparrow and Specter start emitting
  `ur:psbt`, the accept-both rule in §3.2 can eventually shed the deprecated spelling.

---

## Appendix: reproducing the numbers

PSBT sizes from `embit` (BIP-174/BIP-371 serialisation), compressed with
`zlib.compressobj(9, zlib.DEFLATED, -10)` to match BBQr's mandated `wbits=10`, no header. QR
versions and capacities from `segno`, which independently reproduces the BBQr spec's capacity
table. Scan times are a 20 000-trial Monte-Carlo over a cyclic display with i.i.d. per-frame
capture probability `p`, at 4 fps.

The taproot figure was cross-checked by hand against BIP-174: 5 B magic + 141 B global
(unsigned tx 137 B) + 142 B input map (witness_utxo 46, tap_bip32_derivation 60,
tap_internal_key 35, separator 1) + 97 B output maps = **385 B**.

## Sources

Specs:
- BIP-174, PSBT — https://github.com/bitcoin/bips/blob/master/bip-0174.mediawiki
- BIP-371, taproot PSBT fields — https://github.com/bitcoin/bips/blob/master/bip-0371.mediawiki
- BCR-2020-005, Uniform Resources — https://github.com/BlockchainCommons/Research/blob/master/papers/bcr-2020-005-ur.md
- BCR-2020-006, UR type registry — https://github.com/BlockchainCommons/Research/blob/master/papers/bcr-2020-006-urtypes.md
- BCR-2020-012, Bytewords — https://github.com/BlockchainCommons/Research/blob/master/papers/bcr-2020-012-bytewords.md
- BBQr specification — https://github.com/coinkite/BBQr/blob/master/BBQr.md

Rust implementations:
- `ur` — https://github.com/dspicher/ur-rs · https://crates.io/crates/ur
- `bbqr` — https://github.com/SatoshiPortal/bbqr-rust · https://crates.io/crates/bbqr

Wallet source (all verified in cloned trees, August 2026):
- Sparrow `QRScanDialog.java` — https://github.com/sparrowwallet/sparrow/blob/master/src/main/java/com/sparrowwallet/sparrow/control/QRScanDialog.java#L231
- Sparrow `QRDisplayDialog.java` — https://github.com/sparrowwallet/sparrow/blob/master/src/main/java/com/sparrowwallet/sparrow/control/QRDisplayDialog.java#L51
- Sparrow PSBT export — https://github.com/sparrowwallet/sparrow/blob/master/src/main/java/com/sparrowwallet/sparrow/transaction/HeadersController.java#L1012-L1022
- Sparrow descriptor export — https://github.com/sparrowwallet/sparrow/blob/master/src/main/java/com/sparrowwallet/sparrow/wallet/SettingsController.java#L386-L441
- drongo `WalletModel.showBbqr()` — https://github.com/sparrowwallet/drongo/blob/master/src/main/java/com/sparrowwallet/drongo/wallet/WalletModel.java#L147-L169
- hummingbird `RegistryType.java` — https://github.com/sparrowwallet/hummingbird/blob/master/src/main/java/com/sparrowwallet/hummingbird/registry/RegistryType.java
- Sparrow BBQr commit `7f388561`, release 1.8.3 — https://github.com/sparrowwallet/sparrow/releases/tag/1.8.3
- Specter scanner — https://github.com/cryptoadvance/specter-desktop/blob/master/src/cryptoadvance/specter/templates/includes/qr-scanner.html#L100-L185
- Specter display — https://github.com/cryptoadvance/specter-desktop/blob/master/src/cryptoadvance/specter/templates/includes/qr-code.html#L278-L395
- Specter `crypto-account` xpub import — https://github.com/cryptoadvance/specter-desktop/blob/master/src/cryptoadvance/specter/templates/device/new_device/new_device_keys.jinja#L414-L425
- Specter base43 acceptance — https://github.com/cryptoadvance/specter-desktop/blob/master/src/cryptoadvance/specter/server_endpoints/wallets/wallets_api.py#L130-L138
- Electrum `to_qr_data()` — https://github.com/spesmilo/electrum/blob/master/electrum/transaction.py#L1219-L1232
- Electrum base43 alphabet — https://github.com/spesmilo/electrum/blob/master/electrum/bitcoin.py#L533
- Electrum QR import decoding — https://github.com/spesmilo/electrum/blob/master/electrum/transaction.py#L1493-L1526
- libnunchuk `.gitmodules` (bc-ur-2, bbqr-cpp) — https://github.com/nunchuk-io/libnunchuk/blob/master/.gitmodules
- libnunchuk `nunchukutils.cpp` — https://github.com/nunchuk-io/libnunchuk/blob/master/src/nunchukutils.cpp
- BlueWallet `blue_modules/ur/index.js` — https://github.com/BlueWallet/BlueWallet/blob/master/blue_modules/ur/index.js
- BlueWallet `screen/send/ScanQRCode.tsx` — https://github.com/BlueWallet/BlueWallet/blob/master/screen/send/ScanQRCode.tsx
- BlueWallet vendored BBQr — https://github.com/BlueWallet/BlueWallet/tree/master/blue_modules/bbqr
- Coldcard `shared/bbqr.py` — https://github.com/Coldcard/firmware/blob/master/shared/bbqr.py
- Coldcard `shared/auth.py` (920-byte single-QR threshold) — https://github.com/Coldcard/firmware/blob/master/shared/auth.py
- BBQr support matrix (Coinkite, first-party vendor claim, not code-verified) — https://bbqr.org/

## Not confirmed

- **Nunchuk iOS.** `github.com/nunchuk-io/nunchuk-ios` is not public; iOS behaviour is
  inferred from the shared `libnunchuk` core only.
- **Which Specter release tag first shipped the 2021-06-19 UR2 commit** (`1d34c1cd`).
- **Which `WalletModel` Sparrow assigns to an aobs keystore imported by QR**, and therefore
  whether Sparrow would even offer BBQr for it. Moot given the recommendation, but it is the
  fact that would have to be established before BBQr could be reconsidered.
- **"Coldcard has no BC-UR" is a negative**, established by exhaustive grep of the QR-related
  `shared/*.py`, repo-wide code search and release notes. Strong, but a negative.
