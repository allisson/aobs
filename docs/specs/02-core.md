# 02 — `aobs-core`

Everything that decides anything. No Slint, no `v4l`, no `getrandom`, no filesystem, no clock — and
no trait exists purely to be mocked. Every entry point is a pure function from bytes to a decision.

Sources: [#6](https://github.com/allisson/aobs/issues/6),
[#8](https://github.com/allisson/aobs/issues/8),
[#10](https://github.com/allisson/aobs/issues/10),
[#13](https://github.com/allisson/aobs/issues/13),
[#16](https://github.com/allisson/aobs/issues/16),
[#18](https://github.com/allisson/aobs/issues/18),
[#20](https://github.com/allisson/aobs/issues/20),
[#21](https://github.com/allisson/aobs/issues/21),
[#22](https://github.com/allisson/aobs/issues/22),
[#25](https://github.com/allisson/aobs/issues/25),
[#27](https://github.com/allisson/aobs/issues/27),
[#32](https://github.com/allisson/aobs/issues/32),
[#67](https://github.com/allisson/aobs/issues/67).

## 1. Dependencies

| Crate | Why it, and not us |
|---|---|
| `bitcoin` 0.32.x | PSBT, script, address, BIP32. MIT, GPL-3.0-compatible. |
| `secp256k1` | CC0. Implements **RFC6979 deterministic nonces**, which is the Dark Skippy mitigation for free. Writing our own nonce generation would be volunteering for the attack. |
| `argon2` (RustCrypto) | **No published audit — say so out loud.** It is the unaudited half of the backup crypto and carries the 98% bar with RFC 9106 known-answer vectors and differential testing against the PHC reference. |
| `chacha20poly1305` (RustCrypto) | NCC Group audit, no significant findings. |
| `ur` 0.5.x | UR/BC-UR codec. MIT, GPL-3.0-compatible. **The riskiest parser in the tree**, adopted knowingly; see `03-transport.md`. **The crate is `ur`; `ur-rs` is only the repository name** (`dspicher/ur-rs`) — and it is separately taken on crates.io by an unrelated LLM-agent framework, so `cargo add ur-rs` resolves to a real crate that is not this one. |
| `qrcodegen` 1.8.x | The outbound QR symbol. MIT, GPL-3.0-compatible. Zero dependencies, `#![forbid(unsafe_code)]`, one source file. It is Project Nayuki's reference implementation, the one ported line-for-line across six languages against a shared conformance suite — the same borrowed instinct as `secp256k1`, applied to a 2006 standard with a published test corpus. `encode_segments_advanced` takes a **maximum version** and returns `Err` rather than exceeding it, which is `03-transport.md` §6's two rules — smallest version that fits, hard cap above it — as the library's behaviour instead of ours. |
| `zeroize` | `ZeroizeOnDrop`. |

Rejected and why: `ring` (no Argon2, no XChaCha), `libsodium` bindings (drags a C toolchain into the
ISO against the v2 reproducible-build goal), `age` (see ADR-0007), `nokhwa` (shell-side; pulls
`mozjpeg`, a C library built from source), `qrcode` 0.14.x (kennytm; pure Rust and better maintained
— July 2024 against `qrcodegen`'s April 2022 — but its default features pull `image`, it exposes no
maximum-version parameter, so `03-transport.md` §6's v27 cap becomes a loop we write and a refusal
we define, and it is not the reference implementation), `fast_qr` (MIT, but its `image` feature pulls
`resvg`, and it optimises for throughput and wasm, neither of which is a problem we have at 4 fps),
and **writing the encoder ourselves** — ISO/IEC 18004 is Reed–Solomon over GF(256), eight mask
patterns and a penalty score, none of it hard and all of it silently wrong in ways only a scanner
finds, which is `secp256k1`'s instinct in a second domain: a symbol nobody can read is a signature
nobody can broadcast.

**On `qrcodegen`'s age.** No release since 2022 is the thing that rejected `bardecoder` in
`03-transport.md` §5, so it has to be answered rather than waved past. It reads differently here
because of which side of the QR boundary the code sits on: `bardecoder` would have parsed hostile
input, where an unfixed defect is an attack surface. **The encoder consumes only bytes we
produced** — a PSBT we signed, a descriptor set we built, a ciphertext we sealed — and emits to a
screen. There is no adversary on its input. Against a frozen 2006 standard with a published
conformance corpus, no releases means finished, and `bardecoder`'s staleness never travelled
alone: it came attached to a mandated `image ^0.24` and no raw-buffer entry point.

`secp256k1`'s own contribution policy is *"no crypto should be implemented in Rust"*. That instinct
is correct and worth borrowing rather than contradicting: **do not hand-roll the Bitcoin layer.**

## 2. Secret types

The guarantee lives in what the types **do not** implement.

- No `Clone`, no `Copy`. Every `clone()` makes a copy nothing will ever zeroize.
- No `String`, no growable `Vec`. A realloc leaves the old contents behind in freed memory.
- Fixed-capacity buffers allocated at final size.
- `ZeroizeOnDrop`.
- `Debug` and `Display` hand-written as `[redacted]`.

**Wrapped:** BIP39 entropy, the mnemonic, the derived seed, the master xprv, the passphrase, the
dice buffer, the camera luma plane, the entropy `supplement` hash, decrypted backup plaintext, the
8 EFF backup words.

**Testable, and therefore required:** a compile-time trait-bound assertion that every secret type
implements `ZeroizeOnDrop`; a `Debug`-redaction test asserting the formatted output contains none of
the material.

**Not claimed:** that a test observes a freed page. It is not reliably observable from safe Rust, and
the spec says so rather than shipping a test that appears to prove it.

## 3. Entropy and seed generation

### The mixing construction

```
supplement = SHA-256( "aobs/seed-entropy/v1" ‖ framed(camera_luma) ‖ framed(dice_ascii) )
entropy    = csprng_32 XOR supplement

framed(x)  = u32_le(x.len()) ‖ x
```

When **neither** supplement is present the XOR is skipped entirely and `entropy = csprng_32`
verbatim, byte for byte.

**XOR, not concatenate-and-hash.** Every surveyed device concatenates and hashes, which is only
never-worse under the random-oracle assumption. XOR with any value independent of the CSPRNG output
preserves uniformity **unconditionally**, so "never worse" stops being an assumption and becomes
arithmetic. It cuts the other way too: against a backdoored CPU RNG whose output the attacker knows,
they still face the full entropy of `SHA-256(dice)`.

Independence holds because nothing in this path is attacker-visible — the user rolls the dice, we
capture the frame, and neither can be chosen after seeing `csprng_32`. SHA-256 is already in the
tree for the BIP39 checksum, so this adds no dependency.

`csprng_32` arrives as a **parameter**. Core never calls `getrandom`. That is what makes the
known-answer vectors possible at all, and it leaves the provenance release gate exactly one syscall
site to trace, in the shell.

### Generation length

**24 words only, always. No choice is offered, in either direction.** `entropy` is used whole at 32
bytes; there is no truncation branch in generation. Import accepts 12/15/18/21/24.

### What is deliberately absent

- **No replacement mode.** Dice never *are* the entropy. SeedSigner's `sha256(roll_string)` and
  Coldcard's *"these dice rolls will be the only source of randomness"* are both rejected: they buy
  external verifiability against a web tool and pay for it by breaking the never-worse invariant and
  by putting a screen in front of the user whose photograph is total, silent compromise.
- **No distribution sanity-check.** Coldcard rejects any die face over 30%; Krux computes Shannon
  entropy over the rolls *and* their first differences. Both check because both offer a replacement
  mode. Under the XOR, fifty identical faces is not a weak seed — it is a seed exactly as strong as
  `getrandom` alone. A validator would defend an invariant we do not have and would teach the user
  that the check is what protects them.
- **No minimum roll count, no bit counter, no progress meter.** A "128 bits collected" meter is
  false precision twice over and smuggles the replacement-mode mental model back in through the UI.
- **Never display a running hash of the rolls.** Because we mix rather than replace, the rolls on
  screen are *not* sufficient to reconstruct the wallet — which is why aobs needs none of Coldcard's
  *"anyone who photographs this hash can recreate your wallet"* warning. Displaying a running hash
  would hand that property straight back.

### Lifetime

Dice buffer, camera luma plane, `csprng_32` and `supplement` are all zeroizing types, wiped as soon
as `entropy` exists.

## 4. BIP39

### Wordlist

**English only in v1.** CJK wordlists are excluded by the font argument (roughly 100 MiB of glyph
coverage against a 21 MiB stack); French, Spanish, Italian, Portuguese and Czech need diacritics that
**the keymap cannot produce**. That is now a fact rather than an unknown: the appliance pins a `us`
keymap with no variant and no dead keys (`01-boot-layer.md` §2, `04-screens.md` §5.1), so `é` and `ř`
have no keystroke on any physical keyboard, and offering a layout that did have them was refused on
its own merits.

**Named cost:** a non-English mnemonic cannot be imported at all. The failure is loud and immediate —
the first word simply will not type — but it is a wall rather than a message, so the import screen
**names English before the user starts**.

### The import reducer

Core owns the wordlist, the prefix matching and the checksum, as pure functions over a **fixed
24-slot array**. Shape: `(state, action) -> state`, no clock, no growable secret string, keystrokes
carried in by the shell.

Actions: `char`, `commit`, `back`, `goto`, `finish`, `discard`.

Six settled behaviours, each of which is a rule and not a preference:

1. **Prefix matching against the 2048-word list; space commits.** Every BIP39 word is unique within
   four characters.
2. **No auto-accept on a unique prefix.** Auto-accept fires at an unpredictable letter and the rest
   of the word lands in the *next slot*, silently shifting the phrase — which fails the checksum
   exactly as a wrong word does: globally and unlocalisably. Price of refusing it: one keystroke per
   word.
3. **An off-list keystroke does not land.** `bit` is fine (`bitter`); `bitc` has nowhere to go, so
   the `c` does nothing and the screen names the key that was ignored. **The consequence shapes
   everything after it: an off-list word is unrepresentable, so a checksum failure can only ever
   mean real words in the wrong place.**
4. **The checksum is evaluated only at the end, and the rejection says what it cannot do** — it
   covers the phrase as a whole and cannot name the wrong word. A device that pointed at a word
   would be lying.
5. **The final word is never offered as a checksum candidate.** Measured: the valid final set is
   **8 words at 24, 128 at 12**. At 24, seven of the eight are valid phrases that are *not yours*,
   and choosing wrong produces a working, empty wallet with no error. It is also the only place the
   device would supply key material the user did not, and it cannot coexist with an inferred length.
6. **The length is inferred, not declared.** `Done` is enabled only at 12/15/18/21/24. Named cost:
   twenty-four slots are drawn for a twelve-word phrase, which makes the accepted lengths
   self-evident at a glance.

**A failed checksum keeps the words.** Wiping destroys no secret — the phrase is on the user's paper
— it destroys the **diff between paper and screen**, which is the user's only instrument for finding
their own mistake.

**Nothing is masked, anywhere in this product.**

### Correction

Arrow keys move between words. Leaving a slot settles the buffer into it if it resolves to a word and
drops it if it does not. Backspace deletes a letter and, at an empty buffer, steps back a slot and
returns that word **as editable text**. `⏎` is Done.

### Creation confirmation

The same entry component, with one difference that changes the failure path completely: **here we
know the answer.** A wrong word is rejected **immediately and by position**, the phrase is marked at
that position for repair, and nothing is destroyed.

**The per-word comparison belongs in core** — it is a byte comparison against the generated phrase,
not a checksum, and the shell must not branch on a validation outcome.

## 5. The BIP39 passphrase

**aobs never generates one. It accepts one, and makes no judgement about it.**

Why the backup-password reasoning does not transfer: the backup password protects a ciphertext, so a
wrong one **fails loudly** under Poly1305 — that loud failure is what makes it safe to hand a user
103 unchecksummed bits. A BIP39 passphrase has no checksum, no tag and no ciphertext: a wrong one
derives a **different, valid, empty wallet**, and nothing in the protocol can say otherwise.

**One moment, not two.** In BIP39 the passphrase is not an input to mnemonic generation at all — it
enters at seed derivation. So "creation vs load" is a false split: there is exactly one prompt, at
wallet load, serving created and imported seeds alike. Empty by default; **empty *is* no passphrase.**

- **Core:** full BIP39. Arbitrary UTF-8 in, **NFKD** applied before PBKDF2.
- **Shell:** entry restricted to printable ASCII, `0x20–0x7E`. We render the passphrase so the user
  can verify it, and a font with CJK coverage is ~100 MiB against a 21 MiB stack; drawing tofu boxes
  is worse than refusing. **Named cost: a user whose existing passphrase contains non-ASCII cannot
  enter it, and aobs cannot sign for that wallet.** It is the shell's limitation, so lifting it later
  is a shell change and a font, not a crypto change.
- **Length: a fixed 128-byte buffer** (128 characters under the ASCII restriction), above every
  mainstream wallet's own cap. The cap is structural — growable secret types are forbidden.
- **Never trim.** `"hunter2 "` and `"hunter2"` are different wallets. BIP39 defines no trimming rule,
  and trimming ourselves would silently disagree with every other implementation on the same input.
- **No strength meter, no minimum, no lecture.** A passphrase is strictly additive over a 24-word
  mnemonic and therefore never worse than none — the same unconditional-guarantee shape as the XOR.
  A signer with no rate limiting cannot compensate for a weak one anyway, and a meter would imply it
  could.
- **No double entry.** Retyping is the mitigation for a *masked* field. A user who types a trailing
  space twice has confirmed nothing.
- **The passphrase cannot be changed mid-session.** There is no re-derivation path; see §12.

## 6. Derivation, and what "ours" means

**Four accounts:** BIP44 (P2PKH), BIP49 (P2SH-P2WPKH), BIP84 (P2WPKH) and BIP86 (P2TR key-path), at
**account 0**, on the loaded network. `tpub` and coin type `1h` on testnet/signet, `xpub` and `0h` on
mainnet.

### Which network, and where it is chosen

**Two states, not three.** Testnet and signet share coin type `1h`, the `tb` HRP and the same base58
versions, so nothing in a key, an address or a descriptor distinguishes them. That is why the backup
header spends one bit.

**Nothing infers it.** A generated seed carries no network and neither does a BIP-39 mnemonic; only
the restore path knows, from the header's bit0. So it is asked — and it is the one choice in this
product the user can referee, because *"are you practising, or is this real?"* is a question about
their intent rather than about the system. The refusals elsewhere in this spec to offer a choice
(seed length, passphrase strength, script type, colour scheme) all concern judgements the user is not
equipped to make; this is not one of them.

**The network is a load parameter, exactly like the passphrase (§5).** It is not an input to mnemonic
generation — it enters at derivation — so there is one control, on the load screen, serving created
and typed-in seeds alike. Asking there costs nothing because **the seed is network-independent**: the
words already written on paper are a valid backup on either network, so a user who chooses at load
restarts nothing.

**Placement is forced, not preferred.** The restore path must not be prompted (§10 of
`04-screens.md`), so a control answered before the device knows which path the user is on would take
a value the header then discards. A control whose answer is thrown away is the silent-disagreement
class this spec removes everywhere else. On the load screen, restore *states* the value where the
other two paths *ask* it.

**Mainnet is preselected and the choice is not forced.** A forced pick on a 95/5 split is a
click-through trainer on the screen where that is most expensive. The state this creates — an
inattentive rehearser on mainnet — is self-limiting: signing requires coins, and a rehearser has
none on mainnet, so the default's failure is an empty wallet. A testnet default would instead put the
common path into a `tpub` the coordinator rejects.

**The master fingerprint is identical on every network** — BIP-32 derives the master key with one
constant and the identifier is `HASH160` over a 33-byte pubkey; the network lives only in the base58
version bytes. So the fingerprint cannot catch a network mistake and **the network line is the whole
signal**. It is stated in both directions, never encoded as an absence.

**Those four accounts are the definition of "ours"** — for change re-derivation (§7), for receive
verification (§10), and for the watch-only export (`03-transport.md` §7, `04-screens.md` §8).

No script-type choice and no account-index choice is offered. *"Is your old wallet BIP44 or BIP84?"*
is a question the user cannot referee, asked at the moment of least attention, with no way to check
the answer afterwards.

**Named cost, real:** someone whose existing wallet lives on account 1 or 3 can import their seed,
watch aobs derive a wallet they do not recognise, and then have *every* PSBT refused as not ours — a
hard dead end. Mitigated by copy, not by code: see §7's refusal requirements.

## 7. PSBT validation — the rejection policy

Everything between attacker-controlled bytes arriving through the camera and a review screen being
drawn. **A rejection here means no screen is drawn at all.**

### The governing principle

> **A warning is only legitimate when the user knows something we don't. Everything else is a
> refusal.**

A 12% fee is a warning: the user may well know it is correct. A change output that fails
re-derivation is a refusal: there is no state of the user's knowledge that makes it acceptable, so
asking passes them a decision they cannot make better than we can.

This is stricter than Coldcard, deliberately. A signer that warns about everything trains the user to
click through — after which the one warning that mattered gets clicked through too.

### What a refusal is

The specific reason in plain language, a **stable machine-readable code** alongside it — from the
`AOBS-R##` space in `06-codes.md`, which is what makes *stable* mean something — and exactly
**one action: discard.** No "proceed anyway" — not behind a confirmation, not in an advanced menu.
Hiding the reason buys nothing: the attacker wrote the PSBT and knows which check they tripped.

**Failing to decode is not the same as rejecting.** Bytes that never became a PSBT are overwhelmingly
a bad scan: say so, return to scanning. Bytes that decoded into a well-formed PSBT and *then* failed
a check are hostile until proven otherwise — discard, zeroize, no retry with the same bytes.

### Structural refusals

| Condition | Why |
|---|---|
| Duplicate key in any map | BIP-174 says the PSBT is invalid; there is nothing to evaluate. |
| Any input lacking a **`non_witness_utxo` that hashes to its outpoint's txid** — taproot excepted, where `witness_utxo` suffices | The amount is otherwise an unverified assertion the user cannot check. |
| Sighash other than `SIGHASH_ALL` (or `SIGHASH_DEFAULT` for taproot) | No user can evaluate what signing under `SIGHASH_SINGLE` exposes them to. |
| Sum of outputs exceeds sum of inputs | Structurally impossible; a lie by construction. |
| An input whose script type is outside BIP44/49/84/86 single-sig — **including a taproot input that does not declare its key path in full**: the internal key, *and* a `tap_key_origins` entry keyed by it carrying no leaf hashes (§8a) | We would be signing something we do not model — or, for the taproot half, declaring a key-path spend the document gives no way to sign. |
| An input that does not re-derive to our own key material | Foreign inputs mean the displayed cost is not the user's alone. |
| An output we cannot render as an address | The user would be approving hex. |
| **More than six outputs**, payment and change counted together | The review panel is non-scrolling and holds six rows in the minimum canvas (`04-screens.md` §11.2). A seventh output could only be shown by scrolling, clipping or summarising it, and all three mean approving what was not seen. |

**The six-output cap's two rejected alternatives, both of which the field prefers.** Coldcard caps
*visible* outputs at ten and then prints *"plus N smaller output(s), not shown here, which total: X"* —
under a comment reading *"we do expect all users to verify these outputs completely; do not hide
details"* (`docs/research/03-prior-art-survey.md`). Summarising the remainder is approving the unseen,
which is the compromise our larger screen exists to buy us out of. **Paging** the output list is worse in
a subtler way: it refuses nothing, and a 200-output batch becomes 200 pages nobody walks — a limit that
pretends not to be one, where a refusal is a limit that admits it. **Named cost:** a batched payout above
six outputs cannot be signed here, and the user splits it. That workaround is theirs, it is cheap, and it
costs no security.

**The `non_witness_utxo` rule is stricter than Krux and that is the point.** Krux refuses a *legacy*
input without it; we require the full previous transaction for **every non-taproot input**, deleting
the whole BIP-143 amount-spoofing class rather than its two published instances — Coldcard shipped
it twice, six years apart. Taproot is genuinely exempt: BIP-341 commits to all input amounts and
scriptPubKeys, so a lie invalidates the signature. **Accepted cost: a coordinator sending
`witness_utxo` only is refused.**

**Three checks deliberately not added:**

- **No absurd-input-count cap.** The 64 KiB transport bound plus mandatory `non_witness_utxo`
  already caps inputs at a couple of hundred, transitively. **The asymmetry with the six-output cap is
  the display model, not the byte count:** `04-screens.md` §11.2 shows inputs *aggregated* — count and
  total, never a row each — while every output is enumerated on its own row. Inputs cost no rows.
  Outputs cost one each, and an output is only ~32 bytes (8 value, 1 length, 22 script, 1 map
  separator), so 64 KiB admits on the order of two thousand of them. The bound has to come from the
  panel because nothing else bounds it.
- **No mixed-input-script-type refusal** (Krux hard-refuses this). Mixing P2WPKH and P2TR inputs from
  one seed is legitimate, and the refusal is a *proxy* for per-input re-derivation — which we do
  directly.
- **No OP_RETURN carve-out.** "Every output must be a renderable address" is the simpler rule.

**Unknown fields** are ignored for validation and display, never allowed to influence a decision, and
**preserved byte-for-byte in the returned PSBT**. Emitting a minimal PSBT instead is attractive and
**unverified against real coordinators**; recorded as a possible optimisation, not adopted.

### What the dependency already gives us

`bitcoin` 0.32.x **rejects duplicate keys in every map** — verified at tag `bitcoin-0.32.11` across
`decode_global`, `Input::decode` and `Output::decode`, three mechanisms all erroring, and pinned
upstream by BIP-174's own invalid vector 5. Three consequences:

1. **Do not build a pre-parse duplicate scan.** The condition that would have required it is false.
2. **Assert it anyway.** The refusal now rests on a third party's invariant; carry invalid vector 5
   in the suite so a future relaxation trips an alarm.
3. **Map `Error::XPubKey("Repeated global xpub key")` onto the duplicate-key refusal.** A duplicate
   global xpub is guarded differently and arrives as a *different variant* — and a refusal must name
   its reason, not the wrong one.

Two refusals arrive free and are recorded rather than re-implemented: `unsigned_tx_checks()` for
BIP-174's empty-scriptSig/empty-witness rule, and `PartialDataConsumption` for a global unsigned-tx
value with trailing bytes.

**One refusal the dependency does not give us and §9 needs: the amount bound, `AOBS-R16`.** Settled by
[#80](https://github.com/allisson/aobs/issues/80). A `TxOut` value is a `u64` and nothing bounds it at
parse; a taproot input carries only its `witness_utxo` and nothing cross-checks the amount, because
BIP-341 makes a lie invalidate the *signature* rather than the document. So two taproot inputs claiming
`u64::MAX` each pass every check above, and then every number §9's model is made of overflows the type
that carries it. **The inputs must sum to no more than 21 000 000 BTC** — consensus caps the supply, so
a transaction above it is describing UTXOs that cannot exist. It is checked with the structural
refusals, before any key material is asked anything, and it is what lets the review model carry
`bitcoin::Amount`s at all: once the input total fits, the output total fits by the refusal above it and
so does every difference of the two. **Not a policy about fees or dust** — the one comparison, and
nothing else.

### The derivation check

**The claimed derivation selects a candidate; the byte-compare is the only authority.**

1. The 4-byte master fingerprint is a **hint only** — it is 4 bytes and it collides. It never
   authorises anything.
2. Re-derive the pubkey from our own seed at the claimed path, build the scriptPubKey for the
   *declared script type*, and **byte-compare against the actual scriptPubKey**. Equal → the output
   returns to this wallet. Not equal → **refuse the entire transaction**, rather than reclassifying
   it as a plain spend and showing it.
3. An output returning to the wallet is accepted only on one of our four account paths, with
   `path[-2] ∈ {0, 1}` and `path[-1] < 2³¹`. Change anywhere else is refused outright — that is
   Coldcard's 2019 change-path ransom, where change goes to a path the user's wallet will never scan.
4. **Both branches count**, not just `1`. An output that byte-verifies against our key on the receive
   branch is provably ours and provably scannable.
5. An output with a **foreign** fingerprint is simply a payment — displayed in full, given its own
   confirmation screen, no suspicion attached. Both attack directions are safe: marking real change
   as foreign only causes it to be *shown*, and putting our fingerprint on the attacker's address
   fails the byte-compare and refuses.
6. **For an input, the claim read is the one in the map the input's family is *signed* from**, and
   nothing else counts ([#113](https://github.com/allisson/aobs/issues/113)). For BIP44/49/84 that
   is `bip32_derivation`; for BIP86 it is the single `tap_key_origins` entry keyed by
   `PSBT_IN_TAP_INTERNAL_KEY` with no leaf hashes. An input's claim decides whether we hand back a
   signature, and the two signing paths read one map each — so a claim in the other map, or in
   another taproot entry, is not a claim about *this spend*. The input is then simply **not ours**;
   if none is, that is `AOBS-R06`. This is what makes *ours* and *signable* the same question, and
   §8's *at least one signature* an assertion rather than a hope. An output's claim decides only a
   *display*, so it keeps reading either map: rule 5 is why that costs nothing.

### Three copy requirements on the refusals

All three exist because the failure would otherwise read as a bug in aobs:

- When the refusal is **"no input is ours"** and a passphrase is in use, the copy **names the
  passphrase as the likely cause**.
- The **"no input is ours"** refusal **names account 0 as the assumption**.
- The **"no input is ours"** refusal **names the loaded network**. A network mismatch reaches this
  refusal with no distinguishing symptom, because `scriptPubKey`s are network-agnostic bytes: a
  testnet PSBT loaded as mainnet simply fails re-derivation.

Three causes in a list names nothing, so there is a fourth requirement that makes the common
accidental case precise. **When every input's declared BIP32 coin type disagrees with the loaded
network, the refusal says so outright** — *this transaction is for testnet; the loaded wallet is
mainnet.* This does not breach standing rule 1: the derivation path selects the **copy** and has no
effect on acceptance, which still rests entirely on the byte-compare. It is a typed variant on the
refusal model, computed here — the shell must not branch on it (standing rule 4).

## 8. Signing

- Sign with `secp256k1`'s RFC6979 deterministic nonces. Consequence worth knowing: a re-sign is
  byte-identical, which is what makes the outbound screen's re-display policy free.
- **Add partial signatures and remove nothing. Do not finalize.** BIP-174 separates Signer from
  Combiner and Finalizer; those roles mean editing a document the coordinator authored and expects
  back. Stripping `non_witness_utxo` was the tempting saving and is refused: it is a change that
  fails at *their* end, which is the one end we have no channel to hear from.
- **Named cost:** our output is as large as their input.
- **Owed:** pin whether BIP-174 explicitly forbids a Signer removing fields, rather than resting on
  the role separation alone.

### 8a. What building §8 settled

Three things this section could not have known, recorded here because a later reader would otherwise
take the prose above literally and find something missing
([#82](https://github.com/allisson/aobs/issues/82); the gap the first of them left open is closed
below by [#113](https://github.com/allisson/aobs/issues/113)).

**`sign` is total over everything `validate` accepts, and making that true changed §7.** It takes an
`Accepted` and returns a `Psbt` — no `Result`, and no refusal code, because `06-codes.md` has none
and a signing failure is `AOBS-E04` rather than something a screen states. That is only honest if
nothing the validator accepts can fail to sign, and two gaps had to be closed for it:

- **A taproot input must declare its internal key**, which is now part of `AOBS-R05`. `Psbt::sign`
  reads the key-path spend out of `PSBT_IN_TAP_INTERNAL_KEY`, and BIP-371 makes that field the
  declaration that the spend *is* a key path — so an input without it has not declared the script
  type §7's fifth row is about. Accepting one would mean accepting a transaction we cannot sign, and
  the PSBT would leave the appliance looking signed and carrying nothing. It is the existing code
  because it is the existing question, not a new refusal. (**Half the rule**, as #113 below found:
  the field is one end of BIP-371's declaration and the origin entry naming it is the other.)
- **The signing key source ignores the fingerprint**, which is §7's own input rule one layer down.
  The dependency's `impl GetKey for Xpriv` answers only for a matching fingerprint, so a transaction
  accepted under §7's *"a coordinator that filled the fingerprint in wrongly should not make a
  wallet unsignable"* would have been accepted and then signed nothing. What bounds the key source
  instead is `Wallet`'s own scanning rule — five children, one of our four accounts on the loaded
  network, `path[-2] ∈ {0, 1}`, a normal final index — so the set of paths a private key can be
  derived at is decided by the module that owns what *ours* means and never by a PSBT.

**That gap is now closed, and reading the dependency is what decided how**
([#113](https://github.com/allisson/aobs/issues/113)). §8 could not promise it had signed anything
while an accepted input could still be unsignable. `bitcoin` 0.32's taproot path produces a key-path
signature **iff** `tap_key_origins` holds an entry keyed by exactly `tap_internal_key`, with empty
leaf hashes, whose path our key source answers; the internal key's *value* is never compared against
the key we derive — it is the map lookup and nothing more. Three consequences, and the second is why
the ticket's own recommendation was not taken:

- **The declaration has two halves, so `AOBS-R05` covers both.** An internal key no origin entry
  names, or one whose entry carries leaf hashes (a script-path key, which BIP-371 distinguishes by
  exactly that), is a key path the document gives no way to sign. Structural, no key material, and
  the same argument #82 made for the field itself.
- **Comparing the declared internal key against the key we derive would refuse transactions that
  sign.** An internal key that is *not* the untweaked key of the `scriptPubKey` but whose entry
  declares a path that byte-verifies signs correctly and finalizes correctly, because the dependency
  signs with the key at the declared path and tweaks it. So the widening — and the new `AOBS-R17` it
  would have needed — was rejected: it spends a permanent registry number to refuse a shape that
  works.
- **What decides instead is §7's rule 6**, which is where the real question was: an input's claim is
  read out of the map its family is signed from. That closes the taproot case (the internal key's
  entry is the only claim) and an instance nothing had named — **a BIP44/49/84 input whose only
  byte-verifying claim sits in `tap_key_origins`**, accepted as ours by the old *walk both maps* rule
  and signed by nothing, since the ECDSA path reads `bip32_derivation` alone.

So `sign` now asserts what §8 always meant: **every input the validator found ours comes back
signed**, with the set of those inputs travelling on the `Accepted` rather than recomputed. Two
residual costs, both named rather than glossed:

- **The `AOBS-R06` copy can misname the cause.** A hostile PSBT whose `scriptPubKey` is ours while
  its key-path claim is not lands there, and R06 offers the passphrase, account 0 and the network as
  likely causes. It is the same trade §7 already takes for R06's other variants, on a shape no
  honest coordinator emits.
- **The assertion is about the document going out, not about this call's delta**, and it has to be.
  `Psbt::sign` declines a taproot key path when `tap_key_sig` is *already* set, so a PSBT arriving
  with 64 bytes of nonsense in that field would make an *added a signature* assertion panic —
  `AOBS-E04` on bytes an attacker chooses, which is the trade this section rejected in the first
  place. So a signature that **arrived** satisfies the assertion, and nothing checks that it is
  valid: such a document reaches the coordinator and is refused there, which is the pre-#113 outcome
  for a different shape. **Open, and a ticket rather than a decision taken here** —
  [#115](https://github.com/allisson/aobs/issues/115), where the options are a refusal for an input
  arriving pre-signed (which needs a code `06-codes.md` does not define) or verifying a pre-existing
  signature before counting it.

**`sign_schnorr_no_aux_rand` is the deterministic arm, and which arm gets used is a feature flag
rather than a call site.** `Psbt::sign` reaches `sign_schnorr` with fresh auxiliary randomness when
`secp256k1`'s `rand-std` is enabled anywhere in the graph. Nothing in the workspace enables it, and
the alarm is a test asserting that two signatures over the same transaction are byte-identical — a
non-deterministic signature still verifies, so nothing else would notice.

**BIP-341's key-path vectors are the suite, and BIP-340's are nearly not.** Only the index-0 row of
`bip-0340/test-vectors.csv` has all-zero auxiliary randomness, so it is the only row of that file
this path can reproduce. **All seven of `bip-0341/wallet-test-vectors.json`'s key-path signatures were
generated with 32 zero bytes**, which is exactly what `sign_schnorr_no_aux_rand` computes — checked
against an independent BIP-340 implementation before the tests were written. That is seven cases
covering every sighash type and three non-trivial merkle roots, which is what makes the *tweak*
asserted rather than assumed: a wrong tweak still produces a valid BIP-340 signature, under a key
that does not spend the output.

## 9. The review model

Core emits a typed model; the shell renders it and evaluates nothing.

Contents: amount leaving, amount paying, fee (absolute, rate, and as a percentage of the amount),
input count, input total, amount returning, the classified outputs (payment or change, with the full
derivation path and the re-derivation verdict on each), the network, and the warning variant below.

**The rate divides by a prediction, not a measurement.** The unsigned transaction the PSBT carries is
not the one that pays the fee, so the model computes the vsize the *signed* transaction will have from
our own four script types, in weight units, `vsize = ceil(weight / 4)` — charging each ECDSA input the
smaller 71-byte signature element, so the rate is never displayed lower than what will be paid.
`04-screens.md` §11.2.1 carries that reasoning and the rest of the writing rules; every number in this
model crosses the seam as a `bitcoin::Amount` and is written by `format.rs`, never here.

### The one advisory warning

```
fee ≥ total sent to non-change outputs
```

*You are paying miners more than you are paying your recipient.* True or false regardless of
congestion, fiat price, urgency or size — which is exactly what makes it sayable by a device in a
Faraday cage.

**Why not a percentage.** aobs has no mempool, no clock, no fee estimator and no fiat rate.
**Coldcard's 5% and Krux's 10% encode an assumption about a fee market their devices cannot observe
either**, and percentage-of-spend fails at both ends anyway: 90% on a £3 spend is unremarkable, 2%
on £300,000 is not.

**Carve-out:** with no non-change outputs at all — a consolidation — the ratio is undefined and
nothing fires.

**Accepted miss, recorded:** a coordinator inflating a 1 BTC payment's fee to 0.05 BTC is not caught.
The mitigation is not a second threshold; it is the review panel already showing the fee four ways.

**It is a typed variant in the model, never a formatted string.** The shell renders the variant; it
never evaluates the condition.

### The four candidates that were cut

- **Non-zero locktime** — the trap. Bitcoin Core sets `nLockTime` to the current block height as
  anti-fee-sniping (`DiscourageFeeSniping`, `wallet/spend.cpp`), so it is the norm and a warning
  would fire on nearly every modern transaction. Core has no clock to interpret it with anyway.
- **Consolidation to a single output** — cut on *rarity, not legitimacy*. The harm is privacy; the
  threat model is theft.
- **Unusually large output count** — empty after the "renderable address" refusal.
- **Dust outputs** — a non-relaying transaction fails loudly within seconds of broadcast.

## 10. Receive-address verification

**Scan one address, compare strings, answer. Originate nothing, decode nothing.**

Origination (index in, address and QR out) was cut because **the bypass does not bypass anything**:
an originated address still reaches the payer through the user's online machine, where it is altered
exactly as before. The check has to land on the address that actually leaves, and that is the one the
coordinator is showing.

Typing an index or eyeballing a page of addresses were both rejected for putting a **42-character
human diff** at the centre of a feature whose whole purpose is catching one altered character.

**Normalization is four total, allocation-free steps:**

1. strip an optional `bitcoin:` prefix, case-insensitively (BIP-21: the scheme is case-insensitive);
2. truncate at the first `?`;
3. compare against our derived address — **`eq_ignore_ascii_case` only when our address is
   bech32/bech32m, exact `eq` otherwise**;
4. anything else fails to match.

Step 3 is load-bearing. BIP-173 says encoders MUST output lowercase but that QR presentation SHOULD
use uppercase for alphanumeric mode, so a scanned bech32 address is usually all uppercase and a naive
exact compare would report "not yours" for the user's own address. Base58 is case-sensitive, so
matching *it* loosely would report **"yours"** for an address the user mistyped in case. **We always
know which form ours is, because we derived it — the candidate's form is never consulted, never
inferred, never trusted.**

**Search window: all four accounts, both branches, indices 0–999.** Change is included because it
costs the same loop and excluding it would produce a false negative for a user checking a change
address. 1000 is far past BIP-44's gap limit of 20, which is what makes a negative answer worth
something. 8,000 derivations — **timing owed on target hardware.**

**The negative answer.** It cannot honestly mean "not yours"; it means "not in what I searched". But
the failure the user must not make is treating an unmatched address as safe, and a hedged headline
invites exactly that. So: headline **"This address is not yours."** with the weight of a refusal, and
a subordinate line naming precisely what was searched.

## 11. Backup crypto

### The construction

```
Password    8 words, EFF long wordlist (7776 words), device-generated from the CSPRNG.
            Canonical form: lowercase ASCII, joined by exactly one 0x20, no trailing space.
            Independent selections WITH replacement — the generator must not deduplicate,
            drawn uniformly over 7776 with no modulo bias (the entropy figure below
            assumes uniformity, so a biased draw silently invalidates it).

KDF         Argon2id, m = 65536 KiB (64 MiB), t = 3, p = 4, salt 128 bit, output 256 bit.
            RFC 9106 SECOND RECOMMENDED, verbatim.
            Parameters are NOT stored in the file; they are fixed by the version byte.

AEAD        ChaCha20-Poly1305 (RFC 8439), 12-byte all-zero nonce.

Plaintext   The BIP-39 entropy (16 / 20 / 24 / 28 / 32 raw bytes).
            NOT the mnemonic string, NOT the derived seed, NOT the BIP-39 passphrase.

AAD         Every byte of the file before the ciphertext.
```

```
offset  len  field
     0    1  version      = 0x01
     1    1  flags          bit0: network (0 = mainnet, 1 = testnet/signet)
                            bit1: BIP-39 passphrase was in use
                            bits 2-7: MUST be zero; reject if not
     2    1  entropy_len    16 | 20 | 24 | 28 | 32  (reject anything else)
     3   16  salt           128-bit CSPRNG
    19    N  ciphertext     N = entropy_len
  19+N   16  poly1305_tag

total = 35 + entropy_len  ->  51 | 55 | 59 | 63 | 67
AAD   = bytes [0,19)
```

Generated wallets are always 24 words, so a fresh backup is always the 67-byte case.

### Why the numbers are these numbers

- **8 words is the smallest count that reaches a 128-bit floor once the KDF is counted.**
  `log2(7776) = 12.9248…` bits/word → 8 words = **103.398 bits**. The Argon2id work factor measured
  against a single SHA-256 on the same GPU is **+23.62 bits**, giving **127.02**. Seven words lands
  at 114.10 — a real 16,000× reduction. **There is no room to drop to 7 for usability.**
- **8 words is correct *because of* the KDF, not despite it.** Weaken the KDF to a plain hash and the
  same target needs 10 words. The version byte fixes both, together.
- **Do not raise the memory cost instead.** m = 1 GiB, t = 4 multiplies attacker cost by 21.3×
  (+4.41 bits) for a 16× larger allocation on a RAM-resident system with no swap. One extra EFF word
  buys 12.92 bits for free. RFC 9106's FIRST RECOMMENDED (2 GiB) is rejected outright: on a 4 GiB
  machine it risks an OOM kill mid-operation with no soft failure. Note `m' = 4p·floor(m/4p)` — p=4
  still allocates 64 MiB total, not 256, which is what makes p=4 safe on a small machine.
- **All-zero nonce is correct, not a shortcut.** Every backup gets a fresh 128-bit salt, so the key
  is never reused and nonce-misuse resistance is not a property this design needs to buy. This is
  exactly what `age` does in its scrypt stanza, for the same reason. XChaCha20-Poly1305 costs 24
  bytes to restate a guarantee the salt already gives; AES-256-GCM's nonce-reuse failure is
  catastrophic rather than merely bad, and AES-NI only arrived in 2010 — **for an appliance with no
  update mechanism, prefer the primitive whose worst case is least bad.**

### Two implementation traps

1. The RustCrypto `argon2` crate does **not** expose Argon2's own AD input (`Params::data` is
   retained only for PHC-string compatibility). Context binding goes through the AEAD's AAD.
2. `Params::DEFAULT` is 19 MiB / t=2 / p=1 (OWASP's numbers, not the RFC's). **Never use it.**
   Construct explicitly and assert the parameters in a test.

### What rides in the clear, and why

A wrong password **already** fails loudly — Poly1305 rejects with probability 1 − 2⁻¹²⁸. AAD
contributes nothing to that. What AAD buys is **context binding**: a ciphertext valid in one context
cannot be silently reinterpreted in another. The rule is one line — **AAD is every byte before the
ciphertext** — which costs nothing, since version and salt must be in the clear anyway.

**The passphrase-in-use bit is the most important field in the header.** The passphrase must not be
in the backup, or the backup is single-factor for the whole wallet. But its exclusion creates the
worst failure mode in the feature: a passphrase user who restores gets a **valid, correctly
decrypted, completely wrong wallet** — empty, no error anywhere. Poly1305 cannot catch this. One bit
lets restore say so plainly.

**Derivation-path hints are rejected.** Single-sig paths follow from the seed plus script type; in
the clear they would leak wallet structure to anyone who photographs the QR.

### Versioning, with no update mechanism

1. Version is byte 0 and inside the AAD.
2. **Unknown version ⇒ refuse, loudly and specifically**, displaying the version found and stating
   that a newer ISO is required. **Never** attempt a best-effort parse.
3. Print the version even on failure.
4. **Add-only registry: 0x01 is never desupported.** Old ISOs stay in circulation, so old backups do
   too. The discipline this demands is permanently refusing to remove a version.
5. Old ISOs cannot read newer backups — a stated property in the docs, not something discovered at
   restore time.
6. **Reject** non-zero reserved flag bits and out-of-range `entropy_len` rather than ignoring them.

### Restore-side validation, before Argon2id runs

Exactly one of `{51, 55, 59, 63, 67}` bytes, `version == 0x01`, reserved bits zero, `entropy_len` in
set — **all checked before any key derivation**. See `03-transport.md` §5.

### Wordlist: EFF, not BIP39 — a deliberate rejection of reuse

BIP39 is already on the device and 10 words would give 110 bits. Rejected anyway: **a device that
shows the user two different sets of BIP39 words — one that *is* the wallet, one that is merely the
backup password — will eventually have someone restore the wrong list or write the backup password
on the seed card.** The EFF words are lexically distinct, and that distinctness **is** the safety
feature. Coldcard makes the opposite choice; it is the part of their design most worth not copying.
Cost: one 7776-word list, ~60 KB.

## 12. Session model

**One wallet per boot. No switch, no unload, no idle timeout.**

Core is stateless pure functions, so core has no wallet to replace and exposes no unload. **The whole
property lives in the shell, in a `OnceLock`** — set once, no `take`, no replace. *"There is no
second wallet"* is a type-level fact rather than an assertion, and **the enforcement and the test are
the same mechanism**: a second `set` returns `Err`.

Why: any switch boundary would rest on a correctness property the suite has already conceded it
cannot verify (we do not claim a test observes a freed page). Reboot-to-switch replaces that promise
with a power cycle plus `init_on_free=1`. Independently of cold-boot scope, **with no switch there is
no state in which wallet A's material exists while wallet B is active**, so no later bug can surface
the wrong wallet's keys — the class stops existing rather than being defended.

**Cost, named and accepted:** switching passphrase on the same seed means retyping a 24-word
mnemonic, the most laborious action in the product. This is also what closes the deferred question
from the passphrase ticket: **the passphrase cannot change mid-session.**

**No idle timeout.** The threat is a present adversary mid-session, which is not defended; the
false-trigger cost is now maximal; and a timeout would be the shell holding a policy about when
secrets die.

### Signing more than once

**Unlimited signatures per session, and the re-display slot holds exactly one — the most recent.**

No cap is available to us in any case: rate limiting is structurally unavailable, core has no clock,
and refusing to emit a signature already produced is the worst failure the product can have.

The slot is a **single shell-side value, overwritten on each signature. No list, no history, no
selection UI.** Holding many would create a state in which the user selects which signed transaction
to transmit from a list they cannot verify: with no names, no labels and no clock, the only
distinguishing facts are amount and destination — exactly what `04-screens.md` §11.5 removes from
this path — and a txid is 64 hex characters with nothing to compare against, and is not even stable
across signing for a P2PKH input. Transmitting B while believing it is A is destination substitution
arriving at the user's own hands. With one slot there is nothing to select and the class does not
exist, which is the same move as one-wallet-per-boot above.

**Cost, named and accepted:** a user who signs A, fails to hand it to the host, signs B, and then
needs A again has no recovery but re-scanning, re-reviewing and re-signing. This **narrows** the
safety net that `04-screens.md` §11.5 relies on, and that section is worded accordingly. It is
survivable because the host still holds the PSBT — it is the machine that sent it — so nothing is
destroyed and only a ceremony is repeated, and RFC6979 makes the re-sign byte-identical.

**No warning before the replacement.** It would clear the warning bar (we cannot know whether the
host received A, and the user can), but it would land several screens away from the hold that
actually replaces it, and what is at stake is time rather than money.

**Nothing is zeroized between transactions, and that is a decision rather than an omission.** Every
artifact that turns over is public: the inbound PSBT, the signed transaction, the review model. The
only secret in play is the wallet key material, which this section deliberately grants the whole
session. Adding a scrub step here would reintroduce exactly the lifetime boundary rejected above —
standing rule 9 says we do not claim a test observes a freed page, so any boundary we declare is a
promise we cannot verify, and this one would be bought for material that is not secret.
