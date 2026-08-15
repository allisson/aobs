# Prior-art survey: what the existing offline signers settled

Resolves [issue #3](https://github.com/allisson/aobs/issues/3). Map: [issue #1](https://github.com/allisson/aobs/issues/1).

All code citations are permalinks pinned to the commit that was HEAD when this survey was written, so
line numbers stay valid:

| Project | Repo | Pinned commit |
|---|---|---|
| SeedSigner | `SeedSigner/seedsigner` | `5088588dd4f913a489329d2422b0f925ed281856` |
| Krux | `selfcustody/krux` | `8afa9eed34d1b19a04fb72d22f297da18a7068e6` |
| Coldcard | `Coldcard/firmware` | `627ca44f714b478e95e91a699eaf8d6cba8423e5` |
| Passport | `Foundation-Devices/passport2` | `2e96f0af1789f4f86fa35e177b557ebb17442363` |
| Jade | `Blockstream/Jade` | `5ad85661d8c9451547bc382b6bf59c0fdc28864b` |

Scope note: the map fixes aobs at **single-sig only** (BIP44/49/84/86), **QR-only both directions**, and a
threat model that defends against a hostile coordinator and hostile QR data but explicitly *not* against
firmware implants, DMA or cold-boot. The survey is filtered through that: multisig and descriptor
registration are described only where they change how a device handles single-sig change.

---

## 1. Verification UX — what the review screen actually shows

This is the finding that matters most, so it goes first. The question is not "does it show the address"
— they all do — but **which fields, in what order, how change is proven, and what happens when the proof
fails**.

### 1.1 The one thing all five agree on

Every device derives the change address **from its own key material** and compares it byte-for-byte
against the `scriptPubKey` in the transaction. Nobody trusts the PSBT's claim that an output is change.
The BIP32 derivation path in the PSBT output map is treated as an *assertion by the coordinator that
must be proven*, never as a fact.

- SeedSigner: rebuilds the address from the seed's xpub and the claimed path, then string-compares —
  [`psbt_views.py#L382-L411`](https://github.com/SeedSigner/seedsigner/blob/5088588dd4f913a489329d2422b0f925ed281856/src/seedsigner/views/psbt_views.py#L382-L411).
- Krux: `_classify_output` requires `descriptor.owns(psbt_output)` before an output may be labelled
  change or self-transfer —
  [`psbt.py#L268-L299`](https://github.com/selfcustody/krux/blob/8afa9eed34d1b19a04fb72d22f297da18a7068e6/src/krux/psbt.py#L268-L299).
- Coldcard: reconstructs the script and raises `FraudulentChangeOutput` on mismatch —
  [`psbt.py#L406-L449`](https://github.com/Coldcard/firmware/blob/627ca44f714b478e95e91a699eaf8d6cba8423e5/shared/psbt.py#L406-L449).
- Passport: derives the private key, recomputes the pubkey, and compares —
  [`double_check_psbt_change_task.py#L30-L60`](https://github.com/Foundation-Devices/passport2/blob/2e96f0af1789f4f86fa35e177b557ebb17442363/ports/stm32/boards/Passport/modules/tasks/double_check_psbt_change_task.py#L30-L60).
- Jade: rebuilds the singlesig script from the claimed path and `sodium_memcmp`s it against the output —
  [`sign_psbt.c#L569-L615`](https://github.com/Blockstream/Jade/blob/5ad85661d8c9451547bc382b6bf59c0fdc28864b/main/process/sign_psbt.c#L569-L615).

The change/receive distinction itself is universally `path[-2] == 1`. Nobody has invented anything
cleverer, and nobody needs to.

**Settled for aobs: derive-and-compare is the only acceptable change proof. Do not design an alternative.**

### 1.2 Where they diverge — the field lists

**SeedSigner** — a forced linear walk, one concern per screen, no way to skip in single-sig
([`psbt_views.py`](https://github.com/SeedSigner/seedsigner/blob/5088588dd4f913a489329d2422b0f925ed281856/src/seedsigner/views/psbt_views.py)):

1. **Overview** (`#L109-L163`): spend amount, change amount, fee amount, number of inputs, number of
   change outputs, number of self-transfer outputs, destination addresses, whether an OP_RETURN exists.
   Rendered as a pictogram.
2. **Warning interstitials**: "Unsupported Script Type!" if input policy could not be parsed (`#L167-L184`),
   "Full Spend!" if `change_amount == 0` (`#L188-L205`). These are their own screens, not banners.
3. **Math** (`#L209-L242`): total input value, number of inputs, spend amount, number of recipients, fee,
   change — laid out as an arithmetic proof the user can check.
4. **Per-recipient** (`#L246-L299`): one screen per destination, titled "Will Send (#n)", showing amount
   and the **full address**.
5. **Per-change** (`#L303-L452`): one screen per change output, titled "Your Change" or "Self-Transfer",
   showing amount, the literal string `change address #<index>` or `receive address #<index>` derived from
   the path, the address, and a green "Address verified!" tick — but only if verification actually passed
   ([`psbt_screens.py#L648-L709`](https://github.com/SeedSigner/seedsigner/blob/5088588dd4f913a489329d2422b0f925ed281856/src/seedsigner/gui/screens/psbt_screens.py#L648-L709)).
6. **OP_RETURN** (`#L486-L511`) if present.
7. **Finalize** (`#L515-L554`).

**Coldcard** — a single scrolling "story" the user pages through
([`auth.py#L455-L520`](https://github.com/Coldcard/firmware/blob/627ca44f714b478e95e91a699eaf8d6cba8423e5/shared/auth.py#L455-L520),
[`#L686-L770`](https://github.com/Coldcard/firmware/blob/627ca44f714b478e95e91a699eaf8d6cba8423e5/shared/auth.py#L686-L770)):
warning count at the top, then either "Consolidating X BTC within wallet." or "Sending X BTC", then
"Network fee X BTC", then `n inputs / m outputs`, then each foreign output as
`<amount>\n - to address -\n<address>`, then `Change back:\n<total>` with the change addresses, then
locktime notes, then a `---WARNING---` block.

Two limits worth copying deliberately or rejecting deliberately:
`MAX_VISIBLE_OUTPUTS = 10` and `MAX_VISIBLE_CHANGE = 20`
([`auth.py#L695-L696`](https://github.com/Coldcard/firmware/blob/627ca44f714b478e95e91a699eaf8d6cba8423e5/shared/auth.py#L695-L696)).
Beyond that the device prints
`.. plus N smaller output(s), not shown here, which total: X`
([`#L746-L754`](https://github.com/Coldcard/firmware/blob/627ca44f714b478e95e91a699eaf8d6cba8423e5/shared/auth.py#L746-L754)).
The comment above the function is candid about the tension: *"we do expect all users to verify these
outputs completely; do not hide details"* — and then it hides details, because the screen is 320×240.

**Passport** — three screens, then a sign prompt
([`sign_psbt_common_flow.py`](https://github.com/Foundation-Devices/passport2/blob/2e96f0af1789f4f86fa35e177b557ebb17442363/ports/stm32/boards/Passport/modules/flows/sign_psbt_common_flow.py)):
outputs (`#L59-L111`, each as `Amount` / `Destination`, **change omitted entirely unless the whole tx is a
self-send**), then change (`#L216-L250`: total change amount and the change addresses), then warnings
(`#L252-L280`: network fee plus the warning list). Note what is *absent* from the destination screen: no
input count, no total input value, no fee. The fee appears only on the third screen, filed under
"warnings".

Passport is also the only one of the five that runs its fraud check **after** the user has already pressed
Sign (`#L154-L188`), rather than before showing the review. Functionally equivalent, but it means the
error message arrives at the moment of highest user commitment.

**Krux** — a summary page then a paged sequence
([`psbt.py#L349-L458`](https://github.com/selfcustody/krux/blob/8afa9eed34d1b19a04fb72d22f297da18a7068e6/src/krux/psbt.py#L349-L458)):
`Inputs (n): ₿ x`, `Spend (n): ₿ x`, `Self-transfer or Change (n): ₿ x`, then
`Fee: ₿ x (p%) ~s sat/vB`. Then one page per spend output, one per self-transfer, one per change, each
`n. <label>\n\n<address>\n\n<amount>`.

Krux shows **fee as an absolute amount, as a percentage of the spend, and as a sat/vB estimate** on the
same line ([`#L306-L336`](https://github.com/selfcustody/krux/blob/8afa9eed34d1b19a04fb72d22f297da18a7068e6/src/krux/psbt.py#L306-L336)).
That triple is the best fee presentation in the survey and is close to free to implement.

**Jade** — per-output paging then a fee screen
([`ui/sign_tx.c`](https://github.com/Blockstream/Jade/blob/5ad85661d8c9451547bc382b6bf59c0fdc28864b/main/ui/sign_tx.c)):
`Output n/m` with `To: <address>` and `Amount`, then a final `Send Transaction` screen whose **only field
is `Fee:`** (`#L648-L682`, `#L754-L762`). No total-sent, no input count anywhere in the flow.

Jade is also alone in **hiding validated change outputs from the user completely** —
[`sign_tx.c#L43-L60`](https://github.com/Blockstream/Jade/blob/5ad85661d8c9451547bc382b6bf59c0fdc28864b/main/ui/sign_tx.c#L43-L60):
*"Don't display pre-validated (eg. change) outputs (if provided) unless they have an associated warning
message."* The denominator changes with it: the screen says `Output 1/2` where the transaction has three
outputs. The failure direction is safe (a coordinator that omits or lies about the change entry gets the
output *shown*, not hidden), but the user is never given the chance to check that the change address is
the one they expect, and never learns how many outputs the transaction really has.

### 1.3 How the address is rendered so a human can compare it

Four distinct answers, and this is where dedicated hardware is visibly straining:

- **SeedSigner** — fixed-width font, the whole address wrapped across lines, with the **first 7 and last 7
  characters in an accent colour and an emphasis font weight**
  ([`components.py#L911-L1010`](https://github.com/SeedSigner/seedsigner/blob/5088588dd4f913a489329d2422b0f925ed281856/src/seedsigner/gui/components.py#L911-L1010)).
  Line widths are recomputed so every line is the same length, which makes a transposed character visible
  as a ragged column. Best-in-class. But on the change screen it is called with `max_lines=1`
  ([`psbt_screens.py#L691-L695`](https://github.com/SeedSigner/seedsigner/blob/5088588dd4f913a489329d2422b0f925ed281856/src/seedsigner/gui/screens/psbt_screens.py#L691-L695)),
  which collapses it to `bc1q567...1234567` — the exact truncation that address-substitution attacks are
  built to survive. It is only tolerable there because verification already succeeded programmatically.
- **Krux** — space-separated 4-character groups
  ([`format.py#L76-L78`](https://github.com/selfcustody/krux/blob/8afa9eed34d1b19a04fb72d22f297da18a7068e6/src/krux/format.py#L76-L78)).
- **Coldcard** — 4-character chunks
  ([`utils.py#L728-L730`](https://github.com/Coldcard/firmware/blob/627ca44f714b478e95e91a699eaf8d6cba8423e5/shared/utils.py#L728-L730)),
  with a control byte prefixed so the display layer can render addresses specially per hardware model
  ([`#L723-L726`](https://github.com/Coldcard/firmware/blob/627ca44f714b478e95e91a699eaf8d6cba8423e5/shared/utils.py#L723-L726)).
- **Passport** — chunks in **alternating black and grey**, 3 or 4 blocks per line depending on whether the
  unit has a colour screen, with wider spacing when the address contains more than five `m`/`n` glyphs
  (the characters most easily confused at small sizes)
  ([`utils.py#L1479-L1501`](https://github.com/Foundation-Devices/passport2/blob/2e96f0af1789f4f86fa35e177b557ebb17442363/ports/stm32/boards/Passport/modules/utils.py#L1479-L1501)).
  The most thoughtful rendering of the five.
- **Jade** — plain string, scrolled.

**Settled for aobs:** chunk the address, use a fixed-width font, alternate emphasis per chunk, and never
truncate an address the user is being asked to verify. Passport's `m`/`n` spacing tweak and SeedSigner's
equal-line-width wrapping are both cheap and both worth taking.

### 1.4 What each device refuses versus merely warns about

This is the part of the review screen that does the real work, and the five disagree sharply.

| Condition | SeedSigner | Krux | Coldcard | Passport | Jade |
|---|---|---|---|---|---|
| Change address fails re-derivation | **Hard refuse** — "Suspicious Transaction", only button is "Discard transaction", back button suppressed ([`psbt_views.py#L456-L482`](https://github.com/SeedSigner/seedsigner/blob/5088588dd4f913a489329d2422b0f925ed281856/src/seedsigner/views/psbt_views.py#L456-L482)) | Reclassified as a plain spend and shown | **Hard refuse** — `FraudulentChangeOutput` | **Hard refuse** — `PSBT_FRAUDULENT_CHANGE_ERROR` | Refuses: *"Receive script cannot be validated"* ([`sign_tx.c#L296-L301`](https://github.com/Blockstream/Jade/blob/5ad85661d8c9451547bc382b6bf59c0fdc28864b/main/process/sign_tx.c#L296-L301)) |
| Change path shape is unusual but address checks out | — | Warn + Proceed? | Warn `Troublesome Change Outs` with the offending path printed ([`psbt.py#L1786-L1841`](https://github.com/Coldcard/firmware/blob/627ca44f714b478e95e91a699eaf8d6cba8423e5/shared/psbt.py#L1786-L1841)) | inherits Coldcard warnings | Warn `Unusual change path suffix` |
| Fee too high | — | Warn at **≥10%** of spend ([`home.py#L431-L447`](https://github.com/selfcustody/krux/blob/8afa9eed34d1b19a04fb72d22f297da18a7068e6/src/krux/pages/home_pages/home.py#L431-L447)) | Warn at **≥5%**, **hard refuse at ≥10%** (configurable, `-1` disables) ([`psbt.py#L1686-L1693`](https://github.com/Coldcard/firmware/blob/627ca44f714b478e95e91a699eaf8d6cba8423e5/shared/psbt.py#L1686-L1693)) | inherits | Warn only when **fee ≥ 100% of spend** ([`sign_utils.c#L739`](https://github.com/Blockstream/Jade/blob/5ad85661d8c9451547bc382b6bf59c0fdc28864b/main/process/sign_utils.c#L739)) |
| Non-`SIGHASH_ALL` input | — | **Hard refuse** ([`psbt.py#L460-L475`](https://github.com/selfcustody/krux/blob/8afa9eed34d1b19a04fb72d22f297da18a7068e6/src/krux/psbt.py#L460-L475)) | Refused for pure consolidations, warned otherwise | inherits | — |
| Legacy input with no `non_witness_utxo` | — | **Hard refuse** ([`psbt.py#L160-L164`](https://github.com/selfcustody/krux/blob/8afa9eed34d1b19a04fb72d22f297da18a7068e6/src/krux/psbt.py#L160-L164)) | Fixed 2026-07-01, see §5 | — | — |
| Understated input amounts (BIP143) | — | Warn: *"The fee shown may be lower than the real fee"* ([`psbt.py#L203-L214`](https://github.com/selfcustody/krux/blob/8afa9eed34d1b19a04fb72d22f297da18a7068e6/src/krux/psbt.py#L203-L214)) | Warn | — | — |
| Mixed input script types | — | **Hard refuse** — `"mixed inputs in the tx"` | — | — | Warn |
| Outputs exceed inputs | — | **Hard refuse** | **Hard refuse** — "Outputs worth more than inputs!" | inherits | — |
| Derivation path ≠ loaded wallet's | — | Warn, showing both paths side by side ([`home.py#L369-L388`](https://github.com/selfcustody/krux/blob/8afa9eed34d1b19a04fb72d22f297da18a7068e6/src/krux/pages/home_pages/home.py#L369-L388)) | — | — | Warn `Unusual %s path` |

Krux's `validate()` and its sibling checks are the most complete rejection policy in the survey and the
best single reference for aobs's own
([`psbt.py#L148-L214`](https://github.com/selfcustody/krux/blob/8afa9eed34d1b19a04fb72d22f297da18a7068e6/src/krux/psbt.py#L148-L214)).
Its docstring on BIP143 is worth reading in full: it explains precisely why more than one unverified
input is dangerous and why taproot and single-input transactions are immune.

Also note: **mainline Coldcard firmware refuses to spend taproot at all** —
`"Install EDGE firmware to spend taproot."`
([`psbt.py#L815-L816`](https://github.com/Coldcard/firmware/blob/627ca44f714b478e95e91a699eaf8d6cba8423e5/shared/psbt.py#L815-L816))
— and its output validator explicitly skips the change check for `AF_P2TR`
([`#L422-L432`](https://github.com/Coldcard/firmware/blob/627ca44f714b478e95e91a699eaf8d6cba8423e5/shared/psbt.py#L422-L432)).
aobs's BIP86 scope means Krux, Jade and Passport are the only useful references for taproot change
verification; Coldcard mainline is not one.

---

## 2. Encrypted seed export — who does it, and what the criticism is

The second finding the ticket asked to weight. Short answer: **three of the five export an encrypted
seed, and no two of them agree on what the key should be.** The design space splits cleanly on one
question — *who chooses the encryption key* — and that split predicts every criticism.

### 2.1 Who exports an encrypted seed

**Krux — yes, and it is the most permissive implementation.** Krux offers "Encrypted QR Code" and
storage of encrypted mnemonics in internal flash or on SD, alongside plaintext options (Plaintext QR,
SeedQR, Compact SeedQR, Words, Numbers, Stackbit 1248, Tiny Seed)
([`mnemonic_backup.py#L33-L95`](https://github.com/selfcustody/krux/blob/8afa9eed34d1b19a04fb72d22f297da18a7068e6/src/krux/pages/home_pages/mnemonic_backup.py#L33-L95),
[`encryption_ui.py#L596-L676`](https://github.com/selfcustody/krux/blob/8afa9eed34d1b19a04fb72d22f297da18a7068e6/src/krux/pages/encryption_ui.py#L596-L676)).

The format is "KEF" — PBKDF2-HMAC-SHA256 stretching to 256 bits, then AES in ECB, CBC, CTR or GCM
(GCM default), packaged as `ID length | ID | version | iterations | IV | ciphertext | auth`
([`kef.py#L138-L215`](https://github.com/selfcustody/krux/blob/8afa9eed34d1b19a04fb72d22f297da18a7068e6/src/krux/kef.py#L138-L215),
[format spec](https://github.com/selfcustody/krux/blob/8afa9eed34d1b19a04fb72d22f297da18a7068e6/docs/getting-started/features/encryption/encryption.en.md)).
Default iteration count is **100,000**, user-adjustable between 10,000 and 500,000
([`krux_settings.py#L430`](https://github.com/selfcustody/krux/blob/8afa9eed34d1b19a04fb72d22f297da18a7068e6/src/krux/krux_settings.py#L430)).

Three properties of this design are the criticism, and all three are visible in the source:

1. **The key is chosen by the human.** The only guard is `key_strength()`, a character-class scoring
   heuristic — counts of upper/lower/digit/special, plus length bonuses at 12/16/20/40 characters
   ([`encryption_ui.py#L423-L473`](https://github.com/selfcustody/krux/blob/8afa9eed34d1b19a04fb72d22f297da18a7068e6/src/krux/pages/encryption_ui.py#L423-L473)).
   This is the password-meter design that has been discredited for a decade: `Password1!` scores
   "Strong". A key that scores Strong here may carry 30 bits of real entropy, and 100,000 PBKDF2
   iterations buys roughly 17 bits of work factor against it.
2. **The salt is the label, and the label defaults to the wallet fingerprint.** The KDF salt is the
   envelope ID (`Cipher(key, id_, iterations)`,
   [`encryption.py#L107-L113`](https://github.com/selfcustody/krux/blob/8afa9eed34d1b19a04fb72d22f297da18a7068e6/src/krux/encryption.py#L107-L113)),
   and the docs state *"For mnemonics, the default ID is the wallet fingerprint without a passphrase."*
   That ID travels in the envelope **in the clear** — it is field (2) of the published format. So a
   photographed Encrypted QR tells the finder which wallet it is, and therefore what the balance is,
   before they spend a single cycle attacking it. It also means the salt is neither random nor unique
   across a user's backups.
3. **Krux itself says it is not a backup.** From the project's own documentation: *"Storage of encrypted
   secrets on the device or SD cards are meant for convenience only and should not be considered a
   long-term form of backup"*, and *"If a KEF envelope is created with a weak key and shared or exposed,
   it should be assumed to offer **NO protection**, and the secret will be leaked."*

**Coldcard — yes, and it is the safest of the three, for one reason.** `make_complete_backup` writes an
AES-256-CBC 7-Zip archive whose plaintext is a text file containing the mnemonic, `bip32_master_key`,
`xprv`, `xpub`, `raw_secret` and all settings
([`backups.py#L25-L60`](https://github.com/Coldcard/firmware/blob/627ca44f714b478e95e91a699eaf8d6cba8423e5/shared/backups.py#L25-L60)).
The password is **machine-generated, not chosen**: 32 bytes from the hardware RNG rendered as 12 BIP39
words (checksum deliberately dropped, so it is a wordlist password rather than a valid mnemonic)
([`backups.py#L310-L340`](https://github.com/Coldcard/firmware/blob/627ca44f714b478e95e91a699eaf8d6cba8423e5/shared/backups.py#L310-L340)).
That is ~132 bits.

The KDF is weak on purpose: `rounds_pow=13`, i.e. 2^13 = 8,192 rounds of the 7-Zip SHA-256 construction,
against a 7-Zip standard of 2^19
([`compat7z.py#L213-L215`](https://github.com/Coldcard/firmware/blob/627ca44f714b478e95e91a699eaf8d6cba8423e5/shared/compat7z.py#L213-L215),
[`#L325-L342`](https://github.com/Coldcard/firmware/blob/627ca44f714b478e95e91a699eaf8d6cba8423e5/shared/compat7z.py#L325-L342)).
Coinkite's docs are explicit that this is fine *because the key is long*: the backup password gives
*"effectively 132 bits of security without any key stretching"* and they are *"not relying on"* the
stretching ([backup-files.md](https://github.com/Coldcard/firmware/blob/master/docs/backup-files.md)).
That reasoning is sound. It is only sound because the machine picked the password.

Coldcard also ships a deliberate **cleartext backup** escape hatch behind a hidden key press, guarded by
a confirmation that reads *"The file will **NOT** be encrypted and anyone who finds the file will get all
of your money for free!"*, and a source comment describing it as *"only safe for people living in faraday
cages inside locked vaults"*
([`backups.py#L329-L336`](https://github.com/Coldcard/firmware/blob/627ca44f714b478e95e91a699eaf8d6cba8423e5/shared/backups.py#L329-L336)).

**Passport — yes, and its key derivation is the weakest link in the survey.** Passport writes the same
7-Zip AES-256 format with the same `rounds_pow=13`
([`compat7z.py#L232-L234`](https://github.com/Foundation-Devices/passport2/blob/2e96f0af1789f4f86fa35e177b557ebb17442363/ports/stm32/boards/Passport/modules/compat7z.py#L232-L234)),
but the password is a **20-decimal-digit Backup Code**
(`5 sections × 4 digits`,
[`constants.py#L102-L104`](https://github.com/Foundation-Devices/passport2/blob/2e96f0af1789f4f86fa35e177b557ebb17442363/ports/stm32/boards/Passport/modules/constants.py#L102-L104))
that is **not random** — it is derived deterministically as
`SHA256(device_hash || secret)`, with 4 decimal digits extracted from each of the first five 32-bit words
of the digest
([`get_backup_code_task.py#L19-L46`](https://github.com/Foundation-Devices/passport2/blob/2e96f0af1789f4f86fa35e177b557ebb17442363/ports/stm32/boards/Passport/modules/tasks/get_backup_code_task.py#L19-L46)).

Consequences, all of them structural:

- **~66 bits, not 132.** 10^20 ≈ 2^66.4, against a KDF costing 8,192 SHA-256 rounds. That is a factor of
  2^66 less margin than Coldcard's design at identical KDF cost. Still out of reach today; not a margin
  you would choose.
- **The code cannot be rotated.** It is a pure function of the device and the seed. If it leaks, the only
  remedy is moving to a new seed.
- **The backup code is derived from the secret it protects.** Not exploitable as written — SHA-256 is not
  invertible and `device_hash` is unknown to a finder — but it is a construction that gets worse under
  any future weakness, and it removes the option of per-backup keys.
- **The filename leaks the wallet identity.** Backups are written as `{xfp}-backup.7z` where `xfp` is the
  master key fingerprint in hex
  ([`backup_common_flow.py#L11-L18`](https://github.com/Foundation-Devices/passport2/blob/2e96f0af1789f4f86fa35e177b557ebb17442363/ports/stm32/boards/Passport/modules/flows/backup_common_flow.py#L11-L18)).
  Same targeting leak as Krux's envelope ID, by a different route.
- The published risk acceptance is in the UI text itself: *"We consider this safe since physical access to
  the microSD card is required to access the backup."*
  ([`backup_flow.py#L34-L38`](https://github.com/Foundation-Devices/passport2/blob/2e96f0af1789f4f86fa35e177b557ebb17442363/ports/stm32/boards/Passport/modules/flows/backup_flow.py#L34-L38)).
  That sentence is doing a lot of work. The threat the encryption exists to stop *is* someone getting
  physical access to the microSD card.

**SeedSigner — no.** Its only seed exports are **SeedQR** and **CompactSeedQR**, both plaintext
([`encode_qr.py#L87-L139`](https://github.com/SeedSigner/seedsigner/blob/5088588dd4f913a489329d2422b0f925ed281856/src/seedsigner/models/encode_qr.py#L87-L139)).
There is no encrypted-seed export path in the codebase. The published criticism of SeedSigner's backup
story runs the other way — that putting a seed into a QR code at all widens exposure to cameras — but
that is a criticism of QR seed transport, not of encryption.

**Jade — no export, but it does persist an encrypted seed on-device.** See §4.

### 2.2 What the criticism amounts to, and the rule it implies

There is no single canonical paper attacking the practice; the criticism is distributed across the
projects' own documentation, and it converges on one point. Encrypting a seed backup does not remove a
single point of failure — it **moves** it from the physical medium to the key, and in doing so it
converts a loud failure into a silent one:

- **Unencrypted backup**: to steal it you must take the physical object. The owner notices.
- **Encrypted backup**: to steal it you photograph it or copy the file and walk away. The owner notices
  nothing, and the attacker gets an offline, unlimited, un-rate-limited brute force against whatever the
  key actually was. Every guard the device has — PIN counters, wipe-on-failure, tamper detection — is
  outside the attacker's path.

Krux states this outcome in the plainest terms of any of the three, in its own docs: a weak key means
**no protection**, and the secret is leaked. Coldcard survives the criticism only because it never lets
the user pick, and Passport survives it with a 66-bit margin and a code it cannot rotate.

**The rule this settles for aobs:** if aobs writes an encrypted seed anywhere, the key must be
**generated by aobs, never typed by the user**, the envelope must carry **nothing that identifies the
wallet** (no fingerprint, no descriptor, no filename hint), and the KDF must be sized to the machine aobs
actually runs on — Argon2id with real memory cost, not PBKDF2 at whatever an MCU can afford. This
directly constrains the open "BIP39 passphrase generation policy" item on the map: the wordlist and
length are not a UI question, they are the entire security margin.

---

## 3. Entropy

| Device | Hardware sources | User entropy | Mixing |
|---|---|---|---|
| **Coldcard** | MCU TRNG + **two independent secure-element RNGs** (SE1, SE2) | D6 dice (≥50), coin flips (≥128), keyboard-mash timing (≥65 presses) | `sha256d(mcu ‖ se1 ‖ se2)` ([`seed.py#L658-L671`](https://github.com/Coldcard/firmware/blob/627ca44f714b478e95e91a699eaf8d6cba8423e5/shared/seed.py#L658-L671)) |
| **Passport** | **Avalanche noise diode via ADC** + STM32 MCU RNG + secure-element RNG | random final word | XOR of all three sources, then SHA-256 ([`noise.h`](https://github.com/Foundation-Devices/passport2/blob/2e96f0af1789f4f86fa35e177b557ebb17442363/ports/stm32/boards/Passport/noise.h), [`new_seed_task.py`](https://github.com/Foundation-Devices/passport2/blob/2e96f0af1789f4f86fa35e177b557ebb17442363/ports/stm32/boards/Passport/modules/tasks/new_seed_task.py)) |
| **Jade** | ESP32 `esp_fill_random` + `bootloader_random_enable`, plus AXP192 sensor reads and CPU cycle counts continuously re-fed into a SHA-256 entropy pool | — | rolling `entropy_state` re-hashed on every draw ([`random.c#L49-L145`](https://github.com/Blockstream/Jade/blob/5ad85661d8c9451547bc382b6bf59c0fdc28864b/main/random.c#L49-L145)) |
| **Krux** | **Camera snapshot**, hashed; Shannon-entropy estimate and per-channel RMS variance shown to the user before acceptance ([`capture_entropy.py`](https://github.com/selfcustody/krux/blob/8afa9eed34d1b19a04fb72d22f297da18a7068e6/src/krux/pages/capture_entropy.py)) | D6 and D20 dice, with Shannon entropy **and derivative-pattern detection** ([`dice_rolls.py#L72-L119`](https://github.com/selfcustody/krux/blob/8afa9eed34d1b19a04fb72d22f297da18a7068e6/src/krux/pages/new_mnemonic/dice_rolls.py#L72-L119)) | SHA-256 |
| **SeedSigner** | **Camera**: a pool of live-preview frames plus one full-resolution capture, chained through SHA-256 together with the Pi's serial number and millis-since-boot ([`tools_views.py#L165-L214`](https://github.com/SeedSigner/seedsigner/blob/5088588dd4f913a489329d2422b0f925ed281856/src/seedsigner/views/tools_views.py#L165-L214)) | D6 dice (50 or 99 rolls), coin flips (128 or 256) | SHA-256 of the roll/flip **string** ([`mnemonic_generation.py#L64-L100`](https://github.com/SeedSigner/seedsigner/blob/5088588dd4f913a489329d2422b0f925ed281856/src/seedsigner/helpers/mnemonic_generation.py#L64-L100)) |

Three points that bear directly on aobs:

**Manual entropy usually replaces the hardware RNG rather than mixing with it.** SeedSigner's dice path is
`sha256(roll_string)` and nothing else — no hardware randomness is combined in. That is deliberate: it
makes the result **externally reproducible**, so a user can verify SeedSigner's output against
`iancoleman.io/bip39` or a command-line tool (the module ships as a standalone CLI for exactly this,
and the project documents the procedure in `docs/dice_verification.md`). Coldcard offers the same
replacement mode and puts a full-screen warning on it: *"These dice rolls will be the only source of
randomness for your seed. No hardware-generated randomness is mixed in."*, plus *"The hash shown while
rolling is SECRET. Anyone who sees or photographs the final hash can recreate your wallet"*
([`seed.py#L84-L89`](https://github.com/Coldcard/firmware/blob/627ca44f714b478e95e91a699eaf8d6cba8423e5/shared/seed.py#L84-L89)).
This is a genuine trade-off — verifiability against defence-in-depth — and aobs has to pick one
consciously rather than inherit it.

**Everyone who accepts human entropy sanity-checks the distribution.** Coldcard rejects dice where any
face exceeds 30% or a coin exceeds 65%, and credits mash timing at a conservative 2 bits per gap
([`seed.py#L40-L61`](https://github.com/Coldcard/firmware/blob/627ca44f714b478e95e91a699eaf8d6cba8423e5/shared/seed.py#L40-L61)).
Krux computes Shannon entropy over the rolls *and* over the first differences, catching a user who
alternates or cycles. Krux likewise scores camera frames and will say "Insufficient entropy!" for a
snapshot of a blank wall. None of this is expensive and all of it is worth copying.

**Coldcard shipped a five-year RNG failure, and it is the single most important cautionary tale here.**
Per Coinkite's own disclosure history, on 2026-07-30 they disclosed that during the 2021 libNgU
migration *"the seed-generation path resolved `rng_get()` to MicroPython's Yasmarang software PRNG
implementation instead of COLDCARD's intended board-specific hardware TRNG path"*, described as *"a
build-integration and symbol-resolution defect, not an intentional runtime fallback"*, affecting Mk2/Mk3
firmware 4.0.1–4.1.9 and later branches, with an associated theft incident
([coinkite.com/historical-disclosures](https://coinkite.com/historical-disclosures)).

The lesson is not "use a good RNG". Every one of these projects intended to. The lesson is that the
failure was **invisible at runtime and undetectable by inspection of the source**, because the source was
correct — the *linkage* was wrong. Any design where "we call the good RNG" is asserted rather than
tested at the artifact level is one build system change away from the same outcome. This belongs in
aobs's test plan as a named requirement, and it argues for a statistical and provenance self-test on the
entropy path in the shipped ISO, not merely in CI.

---

## 4. Persistence

| Device | Persists between sessions | Where |
|---|---|---|
| **SeedSigner** | **Nothing but settings, and only opt-in.** Seeds live in a plain in-RAM Python list ([`seed_storage.py#L7-L33`](https://github.com/SeedSigner/seedsigner/blob/5088588dd4f913a489329d2422b0f925ed281856/src/seedsigner/models/seed_storage.py#L7-L33)). Settings write to `/mnt/microsd/settings.json` only when "Persistent Settings" is enabled and a card is present; disabling the setting deletes the file ([`settings.py#L130-L136`, `#L190-L195`](https://github.com/SeedSigner/seedsigner/blob/5088588dd4f913a489329d2422b0f925ed281856/src/seedsigner/models/settings.py#L130-L136)) | microSD (settings only) |
| **Krux** | **Encrypted mnemonics, if the user asks.** `seeds.json` in internal flash or on SD, keyed by envelope ID ([`encryption.py#L122-L178`](https://github.com/selfcustody/krux/blob/8afa9eed34d1b19a04fb72d22f297da18a7068e6/src/krux/encryption.py#L122-L178)) | K210 flash / SD |
| **Coldcard** | The seed, in the secure elements; plus settings, multisig registrations, address-explorer notes, trick PINs | SE1/SE2 + LFS |
| **Passport** | The seed, in the secure element; settings in EEPROM | SE + EEPROM |
| **Jade** | The seed, AES-256-CBC encrypted with HMAC-SHA256 appended (encrypt-then-MAC) in off-chip flash ([`keychain.c#L411-L520`](https://github.com/Blockstream/Jade/blob/5ad85661d8c9451547bc382b6bf59c0fdc28864b/main/keychain.c#L411-L520)) | Off-chip flash |
| **Tails** | Nothing, unless Persistent Storage is explicitly enabled | — |

**How the stateless ones handle repeated use** is the question aobs actually needs answered, and there is
only one real answer in the field: **SeedSigner makes the user re-enter the seed every session** — scan a
SeedQR, or type 12/24 words on the button interface
([`psbt_views.py#L11-L81`](https://github.com/SeedSigner/seedsigner/blob/5088588dd4f913a489329d2422b0f925ed281856/src/seedsigner/views/psbt_views.py#L11-L81)).
Within a single power-on the seed stays in RAM and is reused for further PSBTs; the seed selection screen
is skipped automatically when the loaded seed's fingerprint already matches the PSBT's inputs (`#L27-L30`).
Everything is dropped on power-off. This is the closest prior art to aobs, and the design it implies is
that **session ergonomics matter more than they look**: if re-entry is painful, users reach for a stored
seed, which is exactly how Krux ended up with `seeds.json`.

**Jade's persistence deserves a specific warning for aobs.** Jade's seed is encrypted with an AES-256 key
assembled from three parts — the user's PIN, a device secret, and a secret held by a **remote blind
oracle** — combined over ECDH
([`pinclient.c`](https://github.com/Blockstream/Jade/blob/5ad85661d8c9451547bc382b6bf59c0fdc28864b/main/process/pinclient.c),
[Blockstream Help Center](https://help.blockstream.com/hc/en-us/articles/9639949755673-How-does-Blockstream-Jade-s-oracle-enforced-PIN-protection-work)).
Three wrong PINs and both the device and the oracle delete their halves. This buys Jade something no
purely offline device has: **rate limiting without a secure element**. It costs Jade the property aobs
exists to have — **unlocking requires network connectivity** (via the companion app), so Jade in its
default configuration is not an air-gapped device at the moment it matters most. A self-hosted oracle is
supported, which moves the trust but not the connectivity requirement.

This is the honest trade aobs is making: **amnesia buys you "no secret to steal" and forfeits "limited
guesses". You cannot rate-limit what you do not remember.** No PIN counter, no wipe-on-failure, no trick
PINs, no duress wallet with state. Every guard aobs has must live in the seed's own entropy and the
user's physical backup discipline.

**Tails** is the reference for the boot layer and confirms the map's cheap mitigations are the right ones:
`/sbin/swapon` replaced with a no-op so nothing reaches host swap; system files on a read-only medium;
config and temp files in tmpfs only; RAM overwritten at shutdown using the kernel's freed-memory
poisoning (`init_on_free=1`), with a jump back to the initramfs so the overlayfs read-write branch is
freed and erased; and a `udev-watchdog` that triggers emergency shutdown the moment the boot medium is
removed ([tails.net/contribute/design/memory_erasure](https://tails.net/contribute/design/memory_erasure/),
[tails.net/contribute/design](https://tails.net/contribute/design/)).

Tails is also honest about the ceiling, and aobs should quote it rather than overclaim: *"we enable free
poisoning for the buddy allocator, the slub/slab ones, and heap memory, but there may be other ways the
Linux kernel allocates memory, that are not subject to poisoning"*, and *"on shutdown all process memory
is freed (and thus erased), but some kernel memory is not erased on shutdown, and is currently not
erased"*. The map already places cold-boot out of scope; this is the primary source that justifies that
line rather than merely asserting it.

The `udev-watchdog` behaviour is worth stealing outright: **yanking the disc/USB triggers immediate
shutdown and wipe.** That is a real defence against "theft of the machine while running", which sits just
outside the map's stated "theft after shutdown" and costs almost nothing.

---

## 5. Known weaknesses, published attacks and criticisms

**Coldcard** has the longest and most useful public record — 23 disclosures from 2019 to 2026
([coinkite.com/historical-disclosures](https://coinkite.com/historical-disclosures)). The ones that are
directly about the problems aobs must solve:

- *Change-path ransom: unrestricted derivation paths* (2019-11-01) — the attack that `consider_dangerous_change`
  exists to stop: a coordinator sends change to a path the user's wallet will never scan, so the funds are
  provably theirs but unreachable without the attacker's help.
- *Receive-path display manipulation via whitespace parsing* (2019-11-01) — **the review screen itself was
  the vulnerability**. Whitespace in a parsed field changed what the user saw.
- *BIP-143 input-amount and replay vulnerability* (2020-06) and *Legacy input-amount spoofing via
  witness-UTXO-only PSBT* (2026-07-01, before 5.5.1) — the same class twice, six years apart. This is why
  Krux hard-refuses a legacy input without `non_witness_utxo`.
- *Multisig change-script parser confusion* (2019-12-19), *"Trust PSBT" setting ignored in multisig*
  (2020-02-27), *Multisig xpub substitution by malicious coordinator* (2021-02-09) — out of aobs's scope,
  and a decent argument that the map was right to rule multisig out.
- *Delta PIN private-key recovery from two signatures* (2025-09-29).
- *Seed-generation RNG weakness and theft incident* (2026-07-30) — see §3.
- Physical: laser fault injection on the ATECC508A recovering PINs on Mk1/Mk2 (2020-05-18); a double-laser
  plus MCU extraction chain on Mk3 (2021, practical against complete units by 2023); double-laser readout
  bypassing EEPROM read protection on the Mk4's DS28C36 SE2 (2023-09), which did **not** achieve full seed
  compromise because Mk4 requires material from SE1, SE2 *and* the MCU.

**Dark Skippy** (disclosed to ~15 vendors 2024-03-08 by Lloyd Fournier, Nick Farrow and Robin Linus;
published at [darkskippy.com](https://darkskippy.com/)) is the attack that applies to aobs as much as to
any of them. A malicious signer chooses ECDSA nonces as chunks of the seed rather than randomly; an
observer scans the mempool, solves the low-entropy nonces with Pollard's Kangaroo, and reconstructs the
master secret from **as few as two signatures**. A BIP39 passphrase does not help — the attack targets the
master private key, not the mnemonic. The mitigation named in the disclosure is anti-exfil signing
protocols: *"There are a number of existing mitigations including 'anti-exfil' signing protocols which are
offered by some signing devices."* For aobs this is an argument for deterministic nonces
(RFC 6979 / BIP340 aux) plus the reproducible-build goal already on the map as v2 — because the whole
attack presupposes firmware you did not verify.

**SeedSigner's** published criticisms, which land on aobs with more force than on SeedSigner:

- No secure element; the security model is air-gapping plus statelessness and nothing else.
- No firmware verification mechanism on the device — the user is entirely responsible for verifying what
  they flashed.
- **A full Linux installation has a large attack surface** compared to bare-metal firmware. This is the
  criticism aobs inherits and amplifies.
- Putting seeds into QR codes (SeedQR) widens exposure to cameras, which are everywhere.
- On the other side: no supply chain to compromise, because the user assembles commodity parts.

**Krux's** self-documented weaknesses are the encryption issues in §2.1, plus its docs' own note that
flash storage degrades and stored secrets are not a backup. The K210 has no secure element.

**Jade's** criticisms are the connectivity requirement and the oracle's metadata visibility: even a blind
oracle learns **how often and when** a given device unlocks. Blockstream's answer is that you may run your
own. *(Unverified: secondary reviews reference a vulnerability affecting firmware 1.0.24–1.0.36, patched
November 2025 and disclosed in December, 1.0.38+ recommended, no known exploitation. The tracker site
`jade.fail` / `esp32.fail` was unreachable at the time of writing and Blockstream publishes no equivalent
of Coinkite's disclosure history, so this was not confirmed against a primary source. Re-check before
relying on it.)*

**Passport's** issues in this survey are the 66-bit non-rotatable Backup Code and the XFP-in-filename leak
(§2.1), both read directly from source.

---

## 6. The differentiator

### 6.1 What aobs plausibly does better

**Verification UX, by a margin that is not close.** This is the whole case. Every finding in §1 where a
dedicated device compromises is a compromise forced by a 240×240 or 320×240 screen and a few hundred
kilobytes of RAM:

- Coldcard hides outputs past the 10th and change past the 20th, in a function whose own comment says
  users are expected to verify everything.
- Passport omits change from the destination screen entirely, moves the fee to a screen titled
  "warnings", and its source comment concedes *"we don't really expect all users to verify these outputs"*.
- Jade hides validated change completely, and its final confirm screen shows exactly one number.
- SeedSigner — which tries hardest — still truncates the change address to `first7...last7`.

aobs has a 1366×768 minimum-class display and gigabytes of RAM. It can show **every output, every full
address chunked in a fixed-width font, the full derivation path for every change output, the fee in BTC
and sats and sat/vB and as a percentage, and the input total — simultaneously, without paging, with
nothing hidden and nothing truncated.** No dedicated signer can do that at any price, and the review
screen is the exact place where the map's primary threat (a compromised coordinator substituting change
or inflating fees) is either caught or not.

**Cryptographic work factor.** Krux is capped at PBKDF2-100k because the K210 is slow; Coldcard and
Passport ship 2^13 SHA-256 rounds because their MCUs are slower still. aobs can run **Argon2id with
hundreds of megabytes and seconds of work** without the user noticing, which is roughly the difference
between a backup passphrase that must carry 132 bits and one that can survive with far less.

**Amnesia stronger than any device here.** SeedSigner still writes `settings.json` to microSD; Krux writes
encrypted mnemonics to flash; the other three persist the seed permanently. aobs persists **nothing**,
with no persistence partition, no swap and RAM wipe at shutdown — which means the map's "theft of the
machine or boot media after shutdown" is defended by the absence of a secret, not by the strength of one.

**No hardware supply chain.** There is no device to intercept in shipping, no vendor to coerce, no
tamper-evident bag to inspect. The single artifact to verify is the ISO, and it can be verified by hash
from a *different* computer before it ever boots. SeedSigner gets a weaker version of this; the other four
do not get it at all.

**Testability that embedded projects cannot match.** The map's 95%/98% coverage bar plus fuzzing,
property-based tests and adversarial vectors is genuinely reachable on amd64 with ordinary CI, running
against the same code that ships. Coldcard's July 2026 RNG catastrophe was a **build-integration defect**
— precisely the failure class that artifact-level testing on the host catches and source review does not.

**Zero marginal cost**, so rehearsal on testnet/signet is free and users who would never buy a signer can
still have one.

### 6.2 What aobs inherently does worse — bluntly

**Attack surface is the worst in the survey, and it is not close either.** SeedSigner is already criticised
for running a full Linux install. aobs runs a full Linux install **plus a WebKit-class HTML renderer**,
because Tauri's Linux backend is WebKitGTK. The transaction review screen — the security-critical surface
— is drawn by a browser engine with a decade of CVEs, sitting on top of a kernel, a graphics stack, a
compositor and a V4L2 camera pipeline. Coldcard renders that same screen with `snprintf` into a framebuffer.
Measured in lines of code that must not be malicious or buggy, aobs is several orders of magnitude worse
than every device surveyed, and no amount of application-level test coverage changes that number.

**"Offline-only" is a policy, not a physical fact.** A Coldcard has no radio and no network hardware; the
air gap is a property of the silicon. A laptop has Wi-Fi, Bluetooth, Ethernet, sometimes a cellular modem,
and always USB. aobs's air gap is a configuration choice inside an image running on hardware that is fully
capable of transmitting, and it is enforced by exactly the software stack an attacker would target first.

**No secure element, no PIN, no rate limiting, no wipe-on-failure — and amnesia is why.** Coldcard has
three chips that must all be defeated. Passport has an SE. Jade gets rate limiting from the oracle and
destroys its key half after three wrong PINs. aobs has none of this and structurally cannot: a device that
remembers nothing cannot remember how many times you have guessed. The entire security of a wallet reduces
to the entropy of the seed and the physical security of the user's paper backup.

**The firmware and BIOS are trusted on faith, every single boot.** The map concedes this, but the
consequence deserves stating: aobs is booted on whatever commodity machine is to hand, with an unknown
service history, an unauditable UEFI, unauditable Management Engine or PSP firmware, Thunderbolt DMA, and
possibly a hardware keylogger. A dedicated signer at least has secure boot the vendor controls and a
tamper-evident enclosure. A signed ISO proves the image was not altered in transit; it proves nothing
about the machine executing it.

**Entropy quality on commodity amd64 is the weakest of the six, in principle.** Passport has an avalanche
noise diode. Coldcard has three independent hardware RNGs it hashes together. Jade continuously refeeds a
pool from sensors and cycle counters. aobs gets RDRAND — an opaque instruction from the same vendor whose
firmware it already does not trust — and the kernel CSPRNG, which on a LiveCD boots with **no persistent
seed file and no accumulated entropy history**, in the first seconds of uptime, on a machine that may have
no disk I/O and no user input yet. This is the one place where aobs is genuinely behind on the merits, and
Coldcard's 2026 incident shows what the failure looks like when it happens. Mixing camera and user entropy
is not a nice-to-have here; it is compensating for a real deficit.

**Physically worse in every respect that matters after the fact.** More RAM to cold-boot, a larger and
more conspicuous device, a bright screen visible from further away, an attached camera and microphone the
user did not choose, and a fan that keeps DRAM cool enough to matter. A SeedSigner fits in a pocket and can
be disassembled in ten seconds.

**Nothing to attest.** No genuine-check, no vendor signature verified by a chip on boot, no anti-tamper
mesh. Release integrity in v1 is "signed ISO plus published hashes" — which the user must check, on
another computer, correctly, every time. In practice most will not.

### 6.3 The one-line version

**aobs trades away every hardware guarantee the dedicated signers have — secure element, rate limiting,
physical air gap, hardware entropy, attestation — in exchange for the one thing none of them can buy at any
price: a screen and a CPU big enough to show the user the entire transaction, in full, without truncation
or paging, and to do real cryptographic work while doing it. If the transaction review screen is not
demonstrably better than Coldcard's, aobs has no reason to exist.**
