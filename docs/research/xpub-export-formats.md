# Research: xpub export formats accepted by the target watch-only wallets

Ticket: [#5](https://github.com/allisson/aobs/issues/5). Branch `research/xpub-export-formats` —
findings only, no decision. The map ([#1](https://github.com/allisson/aobs/issues/1)) and the
human own the decision.

Scope fixed by the map: single-sig, **BIP84** (native segwit) and **BIP86** (taproot), on
**mainnet, testnet4, signet, regtest**. Target watch-only wallets: **Sparrow**, **Blockstream
App / Green**, **Blue Wallet**.

Direction of travel here is the *opposite* of [#4](https://github.com/allisson/aobs/issues/4):
this document is about the appliance → wallet **key/account export** at wallet-creation time, not
about PSBT transport.

All source-code claims below are pinned to a commit or tag of the wallet's own repository, cloned
on 2026-08-24. Spec claims are pinned to the BIP / SLIP / BCR text itself. Anything not read
directly is marked **UNCONFIRMED** with the check that would settle it.

## Status of this document

**COMPLETE**, with the residual unknowns listed under *What this does not settle*. Every claim below
is pinned to a file and revision in the evidence index; nothing here is a decision — the map
([#1](https://github.com/allisson/aobs/issues/1)) and the human own that.

- [x] 1. Which import encodings each wallet ACCEPTS
- [x] 2. Fingerprint + derivation path: required, optional, or ignored
- [x] 3. SLIP-132 (`zpub`/`vpub`) vs plain `xpub`/`tpub` + descriptor; taproot specifically
- [x] 4. The intersection, and the minimum set the appliance must emit
- [x] 5. Size and QR frames, with byte counts
- [x] 6. testnet4

## Candidate formats (the vocabulary this document uses)

| name | what it is | owner |
|---|---|---|
| **bare extended key** | A BIP32 serialized extended public key, base58check, `xpub…`/`tpub…`. Carries depth, parent fingerprint, child number, chain code, key — but **not** the full derivation path and **not** the master key fingerprint. | BIP32 |
| **SLIP-132** | Alternative version bytes on the same BIP32 payload to signal script type: `ypub`/`zpub` (mainnet P2WPKH-in-P2SH / P2WPKH), `upub`/`vpub` (testnet). No taproot variant is registered. | SLIP-0132 |
| **output descriptor** | `wpkh([73c5da0a/84h/0h/0h]xpub…/0/*)` — script type, key origin (master fingerprint + full path), key, and child range, plus a checksum. | BIP380 (general), BIP381 (`pk`/`pkh`/`wpkh`/`sh`), BIP386 (`tr`) |
| **UR `crypto-hdkey`** | CBOR-encoded HD key with optional `use-info` (network + asset) and `origin`/`children` key-path structures. Carries fingerprint and path. | Blockchain Commons BCR-2020-007 |
| **UR `crypto-account`** | A master-key-fingerprint plus a list of `crypto-output` descriptors, one per script type — the multi-account-descriptor export a device shows once and a wallet imports whole. | Blockchain Commons BCR-2020-015 |
| **ColdCard-style JSON** | `{"chain":"BTC","xfp":"0F056943","bip84":{"name":"p2wpkh","xfp":"…","deriv":"m/84'/0'/0'","xpub":"…","_pub":"zpub…","first":"bc1q…"}, …}` — the `generic JSON` / `wallet export file` several wallets learned to read. | Coinkite |

## 1. Which import encodings each wallet ACCEPTS

### Sparrow — SETTLED

Repo `sparrowwallet/sparrow` @ `70f9c844b78bb07a3bbaa2307ead4a07508f4b21` (master, 2026-08-24).
Supporting library `sparrowwallet/drongo` (cloned same day) supplies `ExtendedKey`,
`OutputDescriptor`, `Network`, `KeyDerivation`.

**The QR scan path.** `src/main/java/com/sparrowwallet/sparrow/control/QRScanDialog.java` is the
single funnel for every QR Sparrow reads (keystore import, wallet import, PSBT). Two branches:

*UR branch* — `qrtext` starting with the `ur:` prefix (line 233) is fed to `URDecoder` /
`LegacyURDecoder`, then `extractResultFromUR(UR)` (line 431) dispatches on
`RegistryType`. The types accepted, verbatim from the `else if` chain (lines 435–535):

| `RegistryType` | UR type string | mapped to |
|---|---|---|
| `BYTES` | `ur:bytes` | PSBT, tx, or UTF-8 text (tried in that order) |
| `CRYPTO_PSBT` | `ur:crypto-psbt` | PSBT |
| `CRYPTO_ADDRESS` | `ur:crypto-address` | address |
| `CRYPTO_HDKEY` | `ur:crypto-hdkey` | `ExtendedKey` + optional name |
| `CRYPTO_OUTPUT` | `ur:crypto-output` | `OutputDescriptor` |
| `CRYPTO_ACCOUNT` | `ur:crypto-account` | `List<Wallet>` (one wallet per contained descriptor) |
| `CRYPTO_SEED`, `CRYPTO_BIP39` | seeds | `DeterministicSeed` |
| `PSBT` | `ur:psbt` | PSBT (post-2023 registry rename) |
| `ADDRESS` | `ur:address` | address |
| `HDKEY` | `ur:hdkey` | `ExtendedKey` |
| `OUTPUT_DESCRIPTOR` | `ur:output-descriptor` | `OutputDescriptor` |
| `ACCOUNT_DESCRIPTOR` | `ur:account-descriptor` | `List<Wallet>` |

Anything else: `"UR type " + urRegistryType + " is not supported"`.

So Sparrow accepts **both generations** of the Blockchain Commons registry — the `crypto-*`
names (BCR-2020-007 `crypto-hdkey`, BCR-2020-010 `crypto-output`, BCR-2020-015 `crypto-account`)
and the post-2023 renames (`hdkey`, `output-descriptor`, `account-descriptor`).

*Plain-text branch* (lines 317+). The order of attempts is load-bearing — the **first** parse that
succeeds wins:

1. `ExtendedKey.fromDescriptor(qrtext)` — a bare base58 extended key.
2. BIP21 URI, 3. address, 4. base64/hex PSBT, 5. raw-bytes PSBT, … else raw text.

A **text output descriptor** is not parsed in `QRScanDialog` itself; it reaches
`OutputDescriptor.getOutputDescriptor(String)` through the wallet-import path
(`io/Descriptor.java`, `isWalletImportScannable() == true`, so "Import Wallet → Output Descriptor"
accepts it by QR as well as by file).

**ColdCard-style JSON** — `io/ColdcardSinglesig.java`, `isKeystoreImportScannable() == true` and
`isWalletImportScannable() == true`, so it is accepted **by QR**. Requirements read off
`getKeystore()`:

- top-level `"xfp"` must be present, else `"Export was not a valid Coldcard wallet export"`;
- it iterates keys starting with `bip`, parses each as `{name, xfp, deriv, xpub, ...}`;
- `name` is mapped to a `ScriptType` by
  `ScriptType.valueOf(ck.name.replace("p2wpkh-p2sh","p2sh_p2wpkh").replace("-","_").toUpperCase())`
  — so `"p2wpkh"` → `P2WPKH` and `"p2tr"` → `P2TR` both resolve (drongo's `ScriptType` has
  `P2TR`); a script type with no matching `bipNN` block gives
  `"Correct derivation not found for script type: …"`;
- the key read is `ck.xpub`, **not** `ck._pub` — i.e. Sparrow takes the plain `xpub`/`tpub` field
  from the ColdCard JSON, not the SLIP-132 one.

**Taproot.** Supported on the descriptor path: `getScriptType(List<ScriptExpression>)` maps
`List.of(ScriptExpression.TAPROOT)` → `ScriptType.P2TR` (QRScanDialog). So `crypto-output` /
`output-descriptor` / text `tr(...)` all carry BIP86 into Sparrow. There is **no** taproot
SLIP-132 header (see item 3), so a bare-key import cannot express BIP86 — the script type has to
be chosen in the import UI instead.

### Blue Wallet — SETTLED

Repo `BlueWallet/BlueWallet` @ `97f9d7277504b6acf93f80bcf920384587eca401` (master, 2026-08-21).

**QR dispatch.** `screen/send/ScanQRCode.tsx` → `onBarCodeRead(ret)` tests prefixes in order
(lines 163–200), case-insensitively:

| prefix | route |
|---|---|
| `UR:CRYPTO-ACCOUNT` | UR v2 decoder |
| `UR:CRYPTO-PSBT` | UR v2 decoder |
| `UR:CRYPTO-OUTPUT` | UR v2 decoder |
| `UR:CRYPTO-HDKEY` | UR v2 decoder |
| `UR:CRYPTO-MULTI-ACCOUNTS` | UR v2 decoder (Keystone's type) |
| `B$` | BBQr |
| `UR:BYTES` (3 slash-parts, `-` in part 2) | UR v2 decoder |
| any other `UR…` | legacy URv1 decoder |
| else | plain text → `WalletImport` |

Note what is **absent**: the post-2023 renamed types `ur:hdkey`, `ur:output-descriptor`,
`ur:account-descriptor` do **not** appear. They fall through to the URv1 branch
(`_onReadUniformResource`, which calls `extractSingleWorkload` expecting the `ur:bytes/1of3/…`
shape) and will not decode. **Blue Wallet accepts only the `crypto-*` generation of the registry.**

**What the decoder produces.** `blue_modules/ur/index.js`, `class BlueURDecoder.toString()`:

- `crypto-psbt` → base64 PSBT.
- `crypto-output` → `output.toString()`, i.e. a **text output descriptor**, handed on to
  `setSecret`.
- `crypto-hdkey` → `_hdKeyToResult(hdKey, null)` → `JSON.stringify([result])`.
- `crypto-account` → one `{ExtPubKey, MasterFingerprint, AccountKeyPath}` object per contained
  descriptor, as a JSON **array**.
- `crypto-multi-accounts` → same shape, one per key.

Those JSON arrays are consumed in `class/wallet-import.ts:592-601`: for each element having all
three of `ExtPubKey`, `MasterFingerprint`, `AccountKeyPath`, a `WatchOnlyWallet` is created.

**Plain-text / descriptor path.** `class/wallets/abstract-wallet.ts` → `setSecret(newSecret)`
(line 221) is the real grammar. In order:

1. **Output descriptor** — accepted if the string starts with `wpkh(`, `pkh(`, `sh(` or `tr(`
   (lines 238–243). The key is located by
   `Math.max(indexOf('xpub'), indexOf('ypub'), indexOf('zpub'))`; origin is taken from the `[...]`
   bracket (or, "old (or broken) format", from the `(`); `h` in the path is normalised to `'`; the
   fingerprint hex is **byte-reversed** and stored as a decimal number. Then:
   `tr(` → `segwitType='p2tr'`, secret kept as `xpub`; `wpkh(` → `p2wpkh`, secret **converted to
   `zpub`**; `sh(wpkh(` → `p2sh(p2wpkh)` → `ypub`; `pkh(` → `p2pkh` → `xpub`.
2. **Bare `[fingerprint/path]key`** — regex `/\[([^\]]+)\](.*)/`. Fingerprint must be exactly 8 hex
   chars or it is ignored. `m/84'/0'/`+`xpub` → converted to `zpub`; `m/49'/0'/` → `ypub`.
3. **Electrum-style JSON** `{"keystore":{"xpub":…,"ckcc_xfp"|"root_fingerprint":…,"derivation":…,"label":…,"type":"hardware"}}`.
4. **Cobo-Vault JSON** `{"ExtPubKey":…,"MasterFingerprint":…,"AccountKeyPath":…}` (fingerprint
   byte-reversed).
5. **Wasabi-from-ColdCard JSON** `{"MasterFingerprint":…,"ExtPubKey":…}` — forced to `zpub`/BIP84
   regardless of what it actually is ("technically we should allow choosing … but meh…").

**ColdCard generic JSON** — `class/wallet-import.ts:606-620`. Requires `json.chain === 'BTC'` and
`json.xfp`, then walks `['bip86','bip84','bip49','bip44']` and imports `json[account].desc` — the
**descriptor** field, not the `xpub` field. So Blue Wallet reads the ColdCard export only via its
embedded descriptors, and only for `chain: "BTC"`.

**Bare key with no origin at all.** `class/wallet-import.ts:494-519`: a `WatchOnlyWallet` is built
from the text; `valid()` returns true only when the secret starts with `xpub`, `ypub` or `zpub`
(`watch-only-wallet.ts`). For a bare `xpub` the importer additionally tries the `ypub` and `zpub`
re-encodings and keeps whichever shows on-chain history (`wasUsed`) — an Electrum-server query,
i.e. it needs network, and on a fresh wallet with no history it falls back to interpreting a bare
`xpub` as **BIP44 legacy** (see item 2).

**Taproot.** `class/wallets/hd-taproot-wallet.ts` exists and `WatchOnlyWallet.init()` selects
`HDTaprootWallet` when `segwitType === 'p2tr'` **or** when `_derivationPath` starts with `m/86'`.
So BIP86 arrives correctly via a `tr(...)` descriptor (script type explicit) and via
`crypto-account`/`crypto-hdkey` (path-based). The `crypto-account` conversion does **not** special-
case BIP86 — the key is re-encoded with `zpub` version bytes `0x04b24746` and taproot is recognised
from the path alone; this is stated in a source comment in `_hdKeyToResult`:

> `// BIP-86 m/86'/0'/ (Taproot) also falls through with zpub bytes; BlueWallet detects`
> `// Taproot via the derivation path rather than the version prefix.`

### Blockstream App / Green — SETTLED (with one version-pin caveat)

Repo `Blockstream/green_android` @ `49096a4ea3a985f7ef05c953b434d8418e2a8f6b`, tag
`release_5.6.0` (2026-08-11). It is a Kotlin Multiplatform app; the same `commonMain` code backs
Android, iOS and desktop, so these findings are not Android-specific. Green delegates all key and
UR parsing to **GDK** (`Blockstream/gdk` @ `8af8abd6fb0659bc97f4afef08ad6953c3752b0e`, 2026-08-20),
which in turn delegates BC-UR to **ur-c** (`Blockstream/ur-c` @ `f887196…`, 2024-10-07).

**The watch-only single-sig import screen.**
`compose/…/models/onboarding/watchonly/WatchOnlySinglesigViewModel.kt`. There is exactly one text
field (`watchOnlyDescriptor`) fed by typing, by a file picker, and by the QR scanner. On submit it
builds one of **two** credential kinds and nothing else:

```kotlin
val watchOnlyCredentials = if (isOutputDescriptors.value) {
    WatchOnlyCredentials(coreDescriptors = watchOnlyDescriptors)
} else {
    WatchOnlyCredentials(slip132ExtendedPubkeys = watchOnlyDescriptors)
}
```

So Green's accepted set is, by construction: **output descriptors** (`core_descriptors`) or
**SLIP-132 extended pubkeys** (`slip132_extended_pubkeys`). Multiple entries are allowed, split on
`|`, `\n` (and `,` in the detector).

**Format classification** — `data/…/utils/WatchOnlyDetector.kt`:

- `detectInputType`: `ur:crypto-*` (case-insensitive) → `InputType.BCUR`; `isDescriptor` →
  `DESCRIPTOR`; valid-or-plausible xpub → `XPUB`; contains `,`/`\n`/`|` → `MULTIPLE`; else
  `INVALID`.
- `isDescriptor` matches on the substrings `wpkh(`, `wsh(`, `pkh(`, `sh(`, `tr(`, `slip77(`,
  `combo(`, `raw(`, `addr(`, `multi(`, `sortedmulti(`, `musig(` — **`tr(` is included**, so a text
  taproot descriptor is recognised.
- `looksLikeXpub` accepts the prefixes `xpub ypub zpub tpub upub vpub Ltub Mtub` and requires
  length 100–120.
- `InputType.BCUR` yields `DetectionResult(isValid = false)`. That is only reached when raw `ur:`
  text lands in the field, which the QR path avoids (below).

**BC-UR does work by QR, via GDK.** `WatchOnlySinglesigScreen.kt:182` opens the camera with
`isDecodeContinuous = true`; `AbstractScannerViewModel.kt:62` routes anything starting `ur:` into
`session.bcurDecode(...)`, and the resulting `BcurDecodedData.simplePayload` —
`descriptors?.joinToString(",") ?: descriptor ?: psbt ?: data ?: ""` — is appended to the field. So
a `crypto-account` arrives as comma-separated **text descriptors**, which the detector then
classifies as `MULTIPLE`/`CORE_DESCRIPTORS`.

**Which UR types GDK decodes** — `gdk/src/bcur_auth_handlers.cpp:277-295`, an exhaustive chain on
the lower-cased UR type:

| ur type | handled as |
|---|---|
| `crypto-psbt`, `psbt` | PSBT |
| `crypto-output` | one formatted descriptor |
| `crypto-account` | `master_fingerprint` + list of formatted descriptors |
| `jade-bip8539-reply`, `jade-pin` | Jade-specific |
| anything else | `return_raw_data = true` — returned as opaque `data` |

So **`crypto-hdkey` is NOT decoded by Green**, nor are the renamed `hdkey` /
`output-descriptor` / `account-descriptor` types. They come back as raw bytes and then fail
`WatchOnlyDetector`.

**Taproot over BC-UR is refused — explicitly.** ur-c's `crypto-output` deserializer
(`src/output.c:64-67`) has:

```c
case urc_urtypes_tags_output_taproot:
    result = URC_ETAPROOTNOTSUPPORTED;
    goto exit;
```

and `include/urc/tags.h` defines `urc_urtypes_tags_output_taproot = 409`. Its `output_type` enum
has no taproot member at all (`na`, `__`, `sh`, `wsh`, `sh_wsh`, `rawscript`) and its
`keyexp_type` set is `pk`, `pkh`, `wpkh`, `cosigner`.

Worse for a multi-script export: `src/account.c:62-97` skips a taproot descriptor inside a
`crypto-account` but then **converts the whole result back to the error** —
`if (result == URC_OK && taproot_found) { result = URC_ETAPROOTNOTSUPPORTED; }`. GDK's
`deserialize_account` treats any non-`URC_OK` as fatal (`GDK_RUNTIME_ASSERT_MSG("ur-c: Parsing
account failed…")`), falling back only to `urc_jade_account_deserialize`, which has the same
taproot handling (`src/jadeaccount.c:70,96`). **A `crypto-account` containing a `tr(...)`
descriptor is therefore rejected wholesale — including its BIP84 descriptor.**

*Caveat:* GDK links ur-c as a prebuilt external dependency (`find_package(urc REQUIRED)`,
`gdk/CMakeLists.txt:76-85`), so the exact linked ur-c revision is **UNCONFIRMED**. What is
confirmed is that `Blockstream/ur-c` **master** — the newest commit in the repo, 2024-10-07, with no
tags — still returns `URC_ETAPROOTNOTSUPPORTED`. Confirming the pin would mean reading GDK's
dependency-fetch tooling (`tools/`, `docker/`) or a built artefact's manifest.

**Taproot over a text descriptor does work.** `isDescriptor` matches `tr(`, and the ColdCard
file-import path (`WatchOnlySinglesigViewModel.importFile`) explicitly whitelists
`AccountType.BIP86_TAPROOT.gdkType == "p2tr"` alongside `"p2pkh"`, `"p2sh-p2wpkh"`, `"p2wpkh"`
(`data/…/gdk/data/AccountType.kt:14-17`). Whether GDK's `register_user`/watch-only login then
accepts a `tr()` core descriptor is **UNCONFIRMED** — it was not read in this ticket; the check is
GDK's `core_descriptors` validation path.

**ColdCard JSON** — accepted, but by **file only**, not by QR: `importFile(source: Source)` is fired
from the file picker. It walks every top-level object, keeps those whose `name` is one of the four
`gdkType` strings above, and takes **`_pub` in preference to `xpub`** — i.e. Green prefers the
SLIP-132 field. It also reads Electrum's `keystore.xpub`. If nothing matched:
`throw Exception("id_format_is_not_supported_or_no_data")`.

**A bare extended key is accepted with no origin at all** — that is the whole point of
`slip132ExtendedPubkeys`, and `looksLikeXpub`/`isValidXpub` never look for a fingerprint. Script
type is inferred from the SLIP-132 prefix by GDK.

## 2. Fingerprint and derivation path

### Sparrow — SETTLED

Sparrow **never rejects** an import for a missing fingerprint or path; it substitutes a placeholder
and carries on. Two places do the substitution, and both use the same sentinel:

- `QRScanDialog.getKeyDerivation(CryptoKeypath)`:
  `String fingerprint = cryptoKeypath.getSourceFingerprint() == null ? KeyDerivation.DEFAULT_WATCH_ONLY_FINGERPRINT : …`
- `io/Descriptor.java` → `ensureKeyDerivations(Wallet)`: if the keystore's master fingerprint or
  derivation path is null, it sets
  `new KeyDerivation(KeyDerivation.DEFAULT_WATCH_ONLY_FINGERPRINT, wallet.getScriptType().getDefaultDerivationPath())`.

`KeyDerivation.DEFAULT_WATCH_ONLY_FINGERPRINT = "00000000"` (drongo,
`src/main/java/com/sparrowwallet/drongo/KeyDerivation.java:11`).

Consequence for the appliance: a bare `xpub` **does** import into Sparrow, but the resulting wallet
carries fingerprint `00000000` and the *default* path for the chosen script type. Any PSBT Sparrow
then builds carries that placeholder origin. Whether the appliance would still recognise its own
inputs from such a PSBT is a **separate question this ticket does not settle** — it depends on
whether the signer matches by fingerprint or by re-deriving the pubkey. Flagged for the PSBT-review
ticket.

`crypto-account` / `account-descriptor` is the one form where the fingerprint is *structurally*
present: `getWallets(CryptoAccount)` reads `cryptoAccount.getMasterFingerprint()` and passes it to
`outputDescriptor.toKeystoreWallet(masterFingerprint)`. In `crypto-output` alone, the fingerprint
rides in the contained `crypto-hdkey`'s `origin.source-fingerprint`, which is optional per
BCR-2020-007 — so a `crypto-output` *can* arrive fingerprint-less and take the `00000000` path.

Also note `getKeyDerivation` throws on non-index path components:
`"Only indexed derivation path components are supported"` — no wildcard/range components in the
*origin* path.

### Blue Wallet — SETTLED

Blue Wallet does not reject a fingerprint-less import either, but the failure mode is worse than
Sparrow's because the **script type is guessed from the key prefix**.

- `masterFingerprint` is a plain `number`, initialised to `0`
  (`abstract-wallet.ts:69`, `watch-only-wallet.ts`). `getMasterFingerprintHex()` returns
  `'00000000'` when it is falsy.
- Missing path: `setSecret` end-of-function fallback (`abstract-wallet.ts:351-359`) —
  `xpub` → `m/44'/0'/0'`, `ypub` → `m/49'/0'/0'`, `zpub` → `m/84'/0'/0'`.
- `WatchOnlyWallet.init()` final fallback: `xpub` → `HDLegacyP2PKHWallet`, `ypub` →
  `HDSegwitP2SHWallet`, `zpub` → `HDSegwitBech32Wallet`.

So **a bare `xpub` sent to Blue Wallet becomes a BIP44 legacy wallet**, not BIP84 and never BIP86.
A bare key is therefore not a usable export for this appliance's script types: the appliance must
send at least an origin (`[fp/84h/0h/0h]xpub…`) or a full descriptor, or — for BIP84 only — a
`zpub`.

The `crypto-account` route is the one that always carries a real fingerprint:
`result.MasterFingerprint = uint8ArrayToHex(cryptoAccount.getMasterFingerprint()).toUpperCase()`.
For `crypto-hdkey` and `crypto-multi-accounts`, `_hdKeyToResult` uses
`origin.getSourceFingerprint()` and sets `MasterFingerprint` to the **empty string** when it is
absent — and `wallet-import.ts:595` requires `account.MasterFingerprint` to be truthy, so a
`crypto-hdkey` **with no `source-fingerprint` in its origin is silently dropped, no wallet is
created**. `_hdKeyToResult` also returns `null` (dropping the key) when the origin is missing or has
no components: `'crypto-hdkey: missing origin or components'`.

That is the sharpest constraint found in this ticket: **Blue Wallet requires the master fingerprint
and a full origin path inside `crypto-hdkey`, or it imports nothing.**

### Blockstream App / Green — SETTLED

Green is the most permissive of the three about a missing origin, because it has a credential kind
built for exactly that case (`slip132_extended_pubkeys`). Nothing in
`WatchOnlySinglesigViewModel` or `WatchOnlyDetector` requires a fingerprint or a path.

What it does with the origin when one *is* present:

- Text descriptor: passed through verbatim as a `core_descriptors` entry, origin included. Green
  does not parse the `[fp/path]` itself; GDK does.
- `crypto-account` over QR: GDK returns `master_fingerprint` as `"%08x"` of
  `account.master_fingerprint`, **but Green only consumes `simplePayload`**, which is the descriptor
  list — the separate `master_fingerprint` field of `BcurDecodedData` is never read on this path
  (`data/…/data/ScanResult.kt` + `BcurDecodedData.simplePayload`). The fingerprint still reaches
  Green because ur-c's formatter embeds it in each descriptor string:
  `format_keyorigin` (`urc/src/hdkey.c:651-687`) writes `[%08x` + the path components + `]`, using
  `origin.source_fingerprint` and falling back to `parent_fingerprint`, or `0` for a master key.
- Additionally, in `BIP44_compatible` mode ur-c appends `/0/*` when the key origin has exactly 3
  levels and no explicit children path (`urc/src/output.c:198-206`) — so the descriptor Green
  receives is a complete `wpkh([abcd1234/84h/0h/0h]xpub…/0/*)`.

## 3. SLIP-132 vs descriptor; taproot

### Sparrow — SETTLED

drongo's `ExtendedKey.Header` enum (`ExtendedKey.java`) is the exhaustive list of version bytes
Sparrow will decode. Full table as written in source:

| header | hex | default script type | mainnet |
|---|---|---|---|
| `xpub` | `0x0488B21E` | P2PKH | yes |
| `ypub` | `0x049D7CB2` | P2SH_P2WPKH | yes |
| `zpub` | `0x04B24746` | P2WPKH | yes |
| `Ypub` | `0x0295B43F` | P2SH_P2WSH | yes |
| `Zpub` | `0x02AA7ED3` | P2WSH | yes |
| `tpub` | `0x043587CF` | P2PKH | no |
| `upub` | `0x044A5262` | P2SH_P2WPKH | no |
| `vpub` | `0x045F1CF6` | P2WPKH | no |
| `Upub` | `0x024289EF` | P2SH_P2WSH | no |
| `Vpub` | `0x02575483` | P2WSH | no |

(plus the matching `*prv` privates). These match SLIP-0132's registered values.

**There is no taproot version byte** — not in drongo, and not in SLIP-0132 itself. SLIP-0132's
registry stops at P2WSH; no `*pub` prefix was ever registered for P2TR. Therefore **BIP86 cannot be
expressed by version bytes at all**, in any wallet. Taproot must travel as either
(a) an output descriptor `tr(...)`, (b) a `crypto-output` whose script expression is `TAPROOT`
(BCR tag 409), or (c) a plain `xpub`/`tpub` with the script type chosen out-of-band in the
importing wallet's UI.

**Sparrow's preference.** `getExtendedKeyBytes()` serializes using
`Network.get().getXpubHeader()` — i.e. Sparrow's own *output* is always plain `xpub`/`tpub`, never
SLIP-132, and `ColdcardSinglesig` reads the plain `xpub` field in preference to `_pub`. Sparrow
*accepts* SLIP-132 on input but does not prefer it.

**Network mismatch is a hard error, not a warning.** `Header.fromExtendedKey(String)` throws
`"Provided <hdr> extended key invalid on configured <net> network. Use a <net> configuration to use
this extended key."` when the prefix belongs to another network, and
`ExtendedKey.fromDescriptor(descriptor, ignoreNetwork=false)` throws `"Unknown header bytes for
extended key on <net>"`. So the appliance's chosen network must match the wallet's configured
network — the key itself only distinguishes mainnet from "some testnet".

## 4. Intersection

### SETTLED: there is exactly one format all three accept, and it is the text output descriptor

| encoding | Sparrow | Green | Blue Wallet |
|---|---|---|---|
| **text output descriptor** `wpkh([fp/84h/0h/0h]xpub…/0/*)` | **yes** (`io/Descriptor.java`, scannable) | **yes** (`core_descriptors`) | **yes** (`setSecret`, `wpkh(`/`tr(` prefixes) |
| **text descriptor `tr(...)`** (BIP86) | **yes** (`ScriptType.P2TR`) | **yes** (`isDescriptor` matches `tr(`; `AccountType.BIP86_TAPROOT`) | **yes** (`segwitType='p2tr'`) |
| bare `xpub`/`tpub` alone | imports, fingerprint `00000000`, script type from UI | imports as `slip132_extended_pubkeys` | imports **as BIP44 legacy** — wrong for our script types |
| bare `zpub` (SLIP-132, BIP84 only) | yes | yes | yes — this is its native form |
| `[fp/84h/0h/0h]xpub` (origin, no script wrapper) | yes (`ExtendedKey.fromDescriptor` fails; goes via descriptor import) — **UNCONFIRMED**, see below | classified `XPUB`?/`DESCRIPTOR`? — **UNCONFIRMED** (no `(` so `isDescriptor` is false; `looksLikeXpub` requires length ≤120 so 131 chars fails → `INVALID`) | **yes** (explicit regex branch) |
| `ur:crypto-output` | yes | yes (BIP84); **NO for taproot** | yes |
| `ur:crypto-account` | yes | yes (BIP84); **rejects the whole account if it contains taproot** | yes |
| `ur:crypto-hdkey` | yes | **no** (GDK returns it as raw data) | yes, but only with fingerprint + origin present |
| `ur:output-descriptor` / `account-descriptor` / `hdkey` (2023 renames) | yes | **no** | **no** |
| ColdCard generic JSON | yes, by QR (reads `xpub`, needs `xfp`) | yes, **file only** (reads `_pub`, falls back to `xpub`) | yes (reads `bipNN.desc`, needs `chain:"BTC"`) |

**Minimum set the appliance must emit: one format — a text output descriptor per script type,
`wpkh(...)` for BIP84 and `tr(...)` for BIP86, each with `[masterfingerprint/path]` origin and a
`/0/*` child suffix.** No per-wallet menu is required for the format; the appliance may still want
one for *convenience* (e.g. offering `zpub` for Blue Wallet users who prefer the classic flow).

**The outlier depends on which axis you look along:**

- On **taproot**: **Green** is the outlier. It is the only one that cannot receive BIP86 over
  BC-UR at all, and a taproot descriptor inside a `crypto-account` breaks the BIP84 one with it. If
  the appliance ever emits `crypto-account`, it must emit BIP84 and BIP86 in **separate** URs, not
  one account.
- On **networks**: **Blue Wallet** is the outlier — mainnet only, and the coin-type-0 filter is
  explicit in source.
- On **key encoding**: **Blue Wallet** is again the outlier — it re-encodes everything into
  SLIP-132 and identifies wallet type from the base58 prefix, where Sparrow and Green (via ur-c)
  both prefer plain `xpub`/`tpub`.
- On **UR registry generation**: **Sparrow** is the only one that accepts the post-2023 names. If
  the appliance emits UR at all it must emit the **deprecated `crypto-*` spellings** to reach all
  three.

Two `UNCONFIRMED` items in the table above worth resolving before the appliance commits to a
fallback format, both cheap to settle by running the wallet:

1. Does Sparrow accept a bare `[fp/84h/0h/0h]xpub…` (origin, no script wrapper) by QR? The
   plain-text branch tries `ExtendedKey.fromDescriptor(qrtext)`, which base58-decodes the **whole**
   string and would fail on the bracket. `OutputDescriptor.getOutputDescriptor` in drongo was not
   read for this ticket.
2. Green's `looksLikeXpub` requires `trimmed.length in 100..120`; the origin form is 131 chars and
   has no `(`, so `detectInputType` should return `INVALID`. That is a code-level inference, not an
   observed failure — worth a run.

## 5. Size and QR frames

### SETTLED

All figures below use the **BIP86 test-vector account xpub** from the BIP text itself
(`bip-0086.mediawiki`, "Account 0, root = m/86'/0'/0'"):
`xpub6BgBgsespWvERF3LHQu6CnqdvfEvtMcQjYrcRzx53QJjSxarj2afYWcLteoGVky7D3UKDP9QyrLprQ3VCECoY49yfdDEHGCtMMj92pReUsQ`
— **111 characters**, with an 8-hex-char fingerprint `73c5da0a`. QR versions computed with `segno`;
side length in modules is `4·version + 17`.

**Text forms.** Base58 is mixed-case, so a bare key or a descriptor **cannot use QR alphanumeric
mode** — it is byte mode, 8 bits per character (confirmed: `segno.make(xpub).mode == 'byte'`).

| form | chars | QR-L | QR-M | QR-Q | QR-H |
|---|---|---|---|---|---|
| bare `xpub` / `zpub` / `tpub` | 111 | v6 (41px) | v7 (45px) | v9 (53px) | v10 (57px) |
| `[73c5da0a/84h/0h/0h]xpub…` | 131 | v6 | v8 (49px) | v10 | v11 (61px) |
| `wpkh([…]xpub…/0/*)` no checksum | 141 | v7 (45px) | v8 | v10 | v12 (65px) |
| `wpkh([…]xpub…/0/*)#cksum` | 150 | v7 | v8 | v10 | v12 |
| `tr([…/86h/…]xpub…/0/*)#cksum` | 148 | v7 | v8 | v10 | v12 |
| both descriptors, newline-joined | 299 | v11 (61px) | v13 (69px) | v16 (81px) | v18 (89px) |

So **a full single-sig output descriptor with fingerprint and path is a single QR at any error
level** — worst case version 12, 65×65 modules. The origin plus script wrapper costs 39 characters
over the bare key (131→150 vs 111), which is two QR versions at ECC H. That is a rounding error
against the appliance's PSBT frames; there is no size argument for the bare-key form.

**BC-UR forms.** Bytewords "minimal" style is **2 characters per byte** plus an 8-character CRC-32
(BCR-2020-012, BCR-2020-005: "For a single-part UR, `message` is created by simply encoding the
untagged CBOR structure as Bytewords"), so a single-part UR is
`len("ur:<type>/") + 2·(cbor_len + 4)` characters, all lowercase — **uppercased for the QR it
becomes alphanumeric mode**, 5.5 bits per character.

| form | chars | QR-L | QR-M | QR-Q | QR-H |
|---|---|---|---|---|---|
| `ur:crypto-output`, one hdkey + origin + children — **measured** from BCR-2020-010's own test vector (tag 403 `pkh`; `wpkh`=404 and `tr`=409 are the same CBOR size) | 259 | v8 (49px) | v9 (53px) | v11 (61px) | v13 (69px) |
| `ur:crypto-account` with 2 single-sig descriptors — **derived** (117-byte payload each + 2-byte tag + 9-byte account wrapper = 247 bytes) | ~520 | v12 (65px) | v14 (73px) | v17 (85px) | v20 (97px) |
| `ur:crypto-account` with 7 descriptors — **measured**, BCR-2020-015's own test vector | 1572 | v23 (109px) | v27 (125px) | v32 (145px) | v37 (165px) |

Reference alphanumeric capacities (computed, not quoted): v10 = 311 chars at M / 174 at H;
v13 = 483 / 259; v20 = 970 / 557; v25 = 1451 / 779; v40 = 3391 / 1852.

**Conclusions on size:**

- The text descriptor is the **smallest** form that carries everything, and the only one that fits
  in a sub-v13 symbol at ECC H.
- A single-part `ur:crypto-output` is roughly **1.7× the characters** of the equivalent text
  descriptor (259 vs 150) and needs v13 at ECC H — still one frame.
- A `ur:crypto-account` carrying both script types is ~520 characters → **v20 at ECC H (97×97
  modules)**. Single-frame, but the module count is where a webcam-and-screen channel starts to
  care about optics. The BCR-2020-015 example at 1572 characters is v37 at ECC H — the practical
  ceiling for a single frame, and an argument for one UR per script type rather than one account
  carrying everything.
- Note this cuts the same way as item 4's Green finding: emitting BIP84 and BIP86 as **two separate
  single-frame exports** is both smaller *and* the only shape Green can read.

**Not measured:** the appliance's own multi-part UR framing (`ur:crypto-account/1-3/…`) and any
BBQr sizing. Out of scope here; that is [#4](https://github.com/allisson/aobs/issues/4)'s
territory, and every candidate above fits one frame anyway.

### Blue Wallet — SETTLED

Blue Wallet **strongly prefers SLIP-132 and normalises everything into it**. It is the outlier of
the three:

- `_xpubToZpub` writes version `0x04b24746` (`zpub`), `_xpubToYpub` writes `0x049d7cb2` (`ypub`),
  `_zpubToXpub` writes `0x0488b21e` — `abstract-wallet.ts:455-490`.
- Every internal wallet-class decision keys off the base58 prefix (`isHd()`, `valid()`,
  `isXpubValid()`, `init()`'s final fallback).
- `_ypubToXpub` is the only converter that validates its input version
  (`if (data.readUInt32BE() !== 0x049d7cb2) throw new Error('Not a valid ypub extended key!')`);
  the others blindly replace the first four bytes.

**It rejects `tpub`/`vpub` outright.** `WatchOnlyWallet.valid()` and `isHd()` test only
`startsWith('xpub'|'ypub'|'zpub')`. The descriptor parser locates the key with
`Math.max(indexOf('xpub'), indexOf('ypub'), indexOf('zpub'))` — a `tpub`/`vpub` descriptor yields
`-1` and mis-parses. There is no `tpub` or `vpub` branch anywhere in the watch-only path.

For **taproot**, Blue Wallet expects the key to still carry `zpub` version bytes and identifies
BIP86 from the `m/86'` path (source comment quoted in item 1), or from a `tr(` descriptor prefix in
which case the key stays `xpub`. Either works; a `zpub`-with-`m/86'` and an `xpub`-inside-`tr()`
both land on `HDTaprootWallet`.

### Blockstream App / Green — SETTLED

Green is the only one of the three whose *credential type name* is SLIP-132
(`WatchOnlyCredentialType.SLIP132_EXTENDED_PUBKEYS`), and it accepts the full mainnet and testnet
prefix set including `tpub`/`upub`/`vpub` (`WatchOnlyDetector.looksLikeXpub`, `.detectNetwork`) —
plus `Ltub`/`Mtub` (Litecoin), which it will happily classify and then presumably fail on later.

But its BC-UR path forces the *other* choice: `urc_hdkey_getversion` (`urc/src/hdkey.c`) emits only

```c
CRYPTO_COININFO_MAINNET → BIP32_VER_MAIN_PUBLIC   // 0x0488B21E, xpub
CRYPTO_COININFO_TESTNET → BIP32_VER_TEST_PUBLIC   // 0x043587CF, tpub
default                 → URC_EUNHANDLEDCASE
```

so a descriptor produced from a UR always carries a **plain `xpub`/`tpub`**, never SLIP-132. Green's
own `Network.kt` mirrors those two constants
(`BIP32_VER_MAIN_PUBLIC = 0x0488B21E`, `BIP32_VER_TEST_PUBLIC = 0x043587CF`, and
`getVerPublic()` picks between them on `isMainnet`).

**Taproot: this is where Green is the outlier.** A text `tr(...)` descriptor is recognised
(`isDescriptor`) and `AccountType.BIP86_TAPROOT` exists; but the BC-UR route refuses taproot
outright (`URC_ETAPROOTNOTSUPPORTED`, item 1), and a taproot descriptor inside a `crypto-account`
poisons the entire account. And a SLIP-132 bare key cannot express taproot in any wallet, because no
taproot version byte exists.

So for BIP86 into Green the only confirmed-shaped export is a **text output descriptor**
`tr([fp/86h/…]xpub…/0/*)` delivered as plain QR text.

## 6. testnet4

### Sparrow — SETTLED

drongo `Network.java` declares the enum, and testnet4 is a first-class member:

```
MAINNET ("mainnet",  … hrp "bc",   xprv/xpub headers, port 8332)
TESTNET ("testnet",  "Testnet3", … hrp "tb", tprv/tpub, port 18332)
REGTEST ("regtest",  … hrp "bcrt", tprv/tpub, port 18443)
SIGNET  ("signet",   … hrp "tb",   tprv/tpub, port 38332)
TESTNET4("testnet4", "Testnet4", … hrp "tb", tprv/tpub, port 48332)
```

All four non-mainnet networks share the **testnet version bytes** (`tprv`/`tpub`, and via
`Header.getHeaders(Network)` also `upub`/`vpub`/`Upub`/`Vpub`). That method explicitly maps
`TESTNET` headers onto `REGTEST`, `SIGNET` **and `TESTNET4`**:

```java
.filter(header -> header.getNetwork() == network
    || (header.getNetwork() == Network.TESTNET && network == Network.REGTEST)
    || (header.getNetwork() == Network.TESTNET && network == Network.SIGNET)
    || (header.getNetwork() == Network.TESTNET && network == Network.TESTNET4))
```

So: **testnet4 is supported by Sparrow, and it expects `tpub` (or `vpub`) — the same bytes as
testnet3, signet and regtest.** The key carries no signal distinguishing them; the network is
Sparrow-side configuration. Address HRP for testnet4 is `tb`, same as testnet3/signet, so nothing in
the export distinguishes them either.

Note `CANONICAL_VALUES = {MAINNET, TESTNET, REGTEST, SIGNET}` excludes TESTNET4 — testnet4 is
canonicalised to `TESTNET` for error-message and (per `getCanonical()`) some display purposes.
Whether that has any effect on *import* behaviour is **UNCONFIRMED**; check would be reading every
`Network.getCanonical()` call site.

### Blue Wallet — SETTLED, and the answer is no

Blue Wallet has **no testnet, signet, regtest or testnet4 support** for on-chain Bitcoin wallets.
Three independent confirmations in source:

1. Every `bitcoinjs-lib` network reference in `class/` and `blue_modules/` is
   `bitcoin.networks.bitcoin`. Grepping `bitcoin.networks|networks:` across those trees returns
   exactly five hits — `segwit-p2sh-wallet.ts:55`, `segwit-bech32-wallet.ts:47` and `:67`,
   `taproot-wallet.ts:30`, `legacy-wallet.ts:564` — all mainnet. There is no
   `networks.testnet`/`networks.regtest` anywhere. The only matches for `testnet`/`signet` in the
   whole tree are in `class/wallets/lightning-ark-wallet.ts` (Ark/Lightning service endpoints, not
   Bitcoin address or key handling).
2. `_hdKeyToResult` (`blue_modules/ur/index.js`) **drops any key whose BIP44 coin type is not 0**:
   `if (components.length >= 2 && components[1].getIndex() !== 0) return null;` with the comment
   "BIP-44 standard: coin type 0 = Bitcoin mainnet. Skip non-Bitcoin keys". A testnet account at
   `m/84'/1'/0'` is therefore silently discarded from `crypto-hdkey` and `crypto-multi-accounts`.
3. The version-byte re-encoding branches are all coin-type-0-specific: `m/49'/0'/`, `m/44'/0'/`,
   and in `setSecret` `m/84'/0'/` and `m/49'/0'/`. And the ColdCard generic JSON path requires
   `json.chain === 'BTC'` (ColdCard writes `"XTN"` for testnet).

Consequence: any appliance test against Blue Wallet has to be on **mainnet**, or against a
different wallet. testnet4 in particular is not merely unimplemented — the coin-type filter would
have to be removed as well as a network selector added.

### Blockstream App / Green — SETTLED: mainnet and one testnet, no signet, no regtest, no testnet4

Green's single-sig network ids are exactly four (`data/…/gdk/data/Network.kt:143-146`):

```
electrum-mainnet   electrum-liquid   electrum-testnet   electrum-testnet-liquid
```

plus the multisig set `mainnet / liquid / testnet / testnet-liquid`, `greenlight-mainnet`,
`liquid-amp2`, `testnet-liquid-amp2`. There is **no `signet`, `regtest` or `testnet4`** identifier
anywhere in `Network.kt`, and `WatchOnlyDetector.detectNetwork` can only return
`ElectrumMainnet`, `ElectrumTestnet`, `ElectrumLiquid` or `ElectrumTestnetLiquid`.

`electrum-testnet` is testnet**3**: it is selected by `tpub`/`upub`/`vpub` prefixes and by coin type
`1'` paths, which testnet4 shares — so an appliance export "for testnet4" would be indistinguishable
from a testnet3 export and Green would connect to its testnet3 Electrum backend. Whether Green's
backend config can be pointed at a testnet4 or signet Electrum server through the personal-node
setting is **UNCONFIRMED** (check: `network/` module and GDK's network registry) — but there is no
testnet4 *network identity*, so address and key handling would still be testnet3's, which for
addresses and version bytes is byte-identical anyway.

### Summary of item 6

| network | Sparrow | Green | Blue Wallet |
|---|---|---|---|
| mainnet | yes, `xpub` | yes, `xpub`/`zpub` | yes, `xpub`/`ypub`/`zpub` |
| testnet3 | yes, `tpub`/`vpub` | yes, `tpub`/`upub`/`vpub` | **no** |
| testnet4 | **yes**, `tpub`/`vpub` (own `Network.TESTNET4`) | **no network id**; `tpub` would be read as testnet3 | **no** |
| signet | yes, `tpub`/`vpub` | **no** | **no** |
| regtest | yes, `tpub`/`vpub` | **no** | **no** |

Nothing in any export format distinguishes testnet3 / testnet4 / signet / regtest: they all share
BIP32 version bytes `0x043587CF` (`tpub`) and, for the first three, the bech32 HRP `tb`. The network
is always receiver-side configuration. **The appliance cannot signal which testnet it means**, and
for BIP84/86 the coin type is `1'` on all of them.

## Findings

1. **One format reaches all three: the text output descriptor**, `wpkh([fp/84h/0h/0h]xpub…/0/*)`
   and `tr([fp/86h/0h/0h]xpub…/0/*)`, as plain QR text. Every other candidate fails at least one
   wallet.
2. **A bare extended key is not a usable export for BIP84/BIP86.** Blue Wallet reads a bare `xpub`
   as BIP44 legacy; Sparrow substitutes fingerprint `00000000` and a default path. Only `zpub`
   (BIP84, mainnet) is unambiguous everywhere — and no SLIP-132 prefix exists for taproot, in any
   wallet, because SLIP-0132 never registered one.
3. **Green cannot receive taproot over BC-UR at all** — ur-c returns `URC_ETAPROOTNOTSUPPORTED` for
   CBOR tag 409, and a `crypto-account` containing a taproot descriptor is rejected *whole*,
   BIP84 descriptor included. If the appliance emits UR, BIP84 and BIP86 must be separate URs.
4. **Blue Wallet requires the master fingerprint and full origin inside `crypto-hdkey`** or it
   silently creates no wallet. It is also the only wallet that normalises everything into SLIP-132.
5. **Blue Wallet is mainnet-only.** No testnet3, testnet4, signet or regtest, with an explicit
   coin-type-≠-0 filter in the UR path. Green has mainnet + testnet3 only. Only **Sparrow** covers
   all four networks in the map's scope, and it is the only place testnet4 exists as a network
   identity.
6. **Nothing in any export distinguishes testnet3 / testnet4 / signet / regtest** — same `tpub`
   version bytes `0x043587CF`, same `tb` HRP, same coin type `1'`. The network is always
   receiver-side configuration.
7. **If the appliance emits UR, it must emit the deprecated `crypto-*` spellings.** Only Sparrow
   accepts the post-2023 `hdkey` / `output-descriptor` / `account-descriptor` renames.
8. **Size is not a constraint for any candidate.** The full descriptor is 150 characters →
   one QR, version 12 at ECC H. The origin + script wrapper costs 39 characters over a bare key.

### What this does not settle

- Whether an appliance can still recognise its own inputs in a PSBT built by a wallet that imported
  a fingerprint-less key (Sparrow's `00000000` case). Belongs to the PSBT-review ticket.
- Whether GDK's watch-only login validates and accepts a `tr()` core descriptor (Green's text-
  descriptor taproot path). Check: GDK's `core_descriptors` validation.
- Which ur-c revision a shipped GDK actually links (external `find_package`). Repo master still
  refuses taproot.
- Whether Sparrow accepts a bare `[fp/path]xpub` (no script wrapper) by QR, and whether Green
  rejects the same string on its 100–120-character `looksLikeXpub` bound. Both are code-level
  inferences; a run would settle them in minutes.
- Whether Green can be pointed at a testnet4 or signet Electrum backend despite having no network
  identity for either.

## Evidence index

| source | revision / date | what it settles |
|---|---|---|
| `sparrowwallet/sparrow` `src/main/java/com/sparrowwallet/sparrow/control/QRScanDialog.java` | `70f9c844b78bb07a3bbaa2307ead4a07508f4b21`, 2026-08-24 | Sparrow's accepted UR registry types, plain-text parse order, `getScriptType` taproot mapping, `00000000` fingerprint fallback |
| …`/io/Descriptor.java` | same | text-descriptor wallet import, `ensureKeyDerivations` |
| …`/io/ColdcardSinglesig.java` | same | ColdCard JSON: `xfp` required, `bipNN` walk, `xpub` (not `_pub`), QR-scannable |
| `sparrowwallet/drongo` `ExtendedKey.java` | cloned 2026-08-24 | full SLIP-132 header table, `fromDescriptor`, network-mismatch error |
| `sparrowwallet/drongo` `Network.java` | same | `TESTNET4` enum member, `getHeaders` testnet-header mapping |
| `sparrowwallet/drongo` `KeyDerivation.java:11` | same | `DEFAULT_WATCH_ONLY_FINGERPRINT = "00000000"` |
| `BlueWallet/BlueWallet` `class/wallets/abstract-wallet.ts:221-374` | `97f9d7277504b6acf93f80bcf920384587eca401`, 2026-08-21 | `setSecret` grammar: descriptors, `[fp/path]key`, three JSON shapes, path/prefix fallbacks, SLIP-132 converters |
| …`class/wallets/watch-only-wallet.ts` | same | `valid()`/`isHd()` accept only `xpub`/`ypub`/`zpub`; `init()` script-type selection; `getMasterFingerprintHex` |
| …`class/wallet-import.ts:486-620` | same | watch-only discovery, `[{ExtPubKey,MasterFingerprint,AccountKeyPath}]` array, ColdCard `chain:"BTC"` + `bipNN.desc` |
| …`blue_modules/ur/index.js` | same | `BlueURDecoder.toString()` per-type conversion, `_hdKeyToResult` coin-type-0 filter and BIP86-keeps-zpub comment |
| …`screen/send/ScanQRCode.tsx:163-200` | same | the UR prefix whitelist (crypto-* only) |
| `Blockstream/green_android` `compose/…/watchonly/WatchOnlySinglesigViewModel.kt` | `49096a4…`, tag `release_5.6.0`, 2026-08-11 | the two credential kinds; ColdCard file import preferring `_pub`; network selection |
| …`data/…/utils/WatchOnlyDetector.kt` | same | `InputType`, `isDescriptor` (incl. `tr(`), `looksLikeXpub` prefix set + 100–120 length, `detectNetwork` |
| …`data/…/gdk/data/Network.kt:137-165` | same | the four single-sig network ids; `BIP32_VER_*_PUBLIC` |
| …`data/…/gdk/data/AccountType.kt:14-17,58-62` | same | `p2wpkh` / `p2tr` gdkType strings |
| …`compose/…/abstract/AbstractScannerViewModel.kt:62` + `data/…/data/ScanResult.kt` + `BcurDecodedData.kt` | same | QR `ur:` → `session.bcurDecode`; `simplePayload` = descriptors joined by `,` |
| `Blockstream/gdk` `src/bcur_auth_handlers.cpp:39-95,277-295` | `8af8abd6fb0659bc97f4afef08ad6953c3752b0e`, 2026-08-20 | exhaustive UR-type dispatch; `BIP44_compatible` format mode; `master_fingerprint` as `%08x` |
| `Blockstream/gdk` `CMakeLists.txt:75-85` | same | ur-c linked as an external prebuilt dependency (why the pin is unconfirmed) |
| `Blockstream/ur-c` `src/output.c:64-67`, `include/urc/tags.h`, `include/urc/crypto_output.h:42-47` | `f887196736f9ece307ff798f7c14bcfcbf809be8`, 2024-10-07 (repo HEAD, no tags) | `URC_ETAPROOTNOTSUPPORTED` for tag 409; `output_type` / `keyexp_type` sets with no taproot |
| `Blockstream/ur-c` `src/account.c:62-97`, `src/jadeaccount.c:70,96` | same | taproot-in-account skipped then re-raised as an error for the whole account |
| `Blockstream/ur-c` `src/hdkey.c:651-687,710-780`, `src/output.c:168-206` | same | `format_keyorigin` `[%08x…]`; `urc_hdkey_getversion` mainnet/testnet only; `/0/*` appended in BIP44-compatible mode |
| BIP 86 (`bip-0086.mediawiki`) | bitcoin/bips master, fetched 2026-08-24 | the account xpub test vector used for all byte counts |
| BIP 380 / BIP 386 | same | descriptor general operation; `tr()` key expressions must be x-only |
| SLIP-0132 (`slip-0132.md`) | satoshilabs/slips master, fetched 2026-08-24 | the registered version-byte table, and that it stops at P2WSH — no taproot prefix exists |
| BCR-2020-007 (`crypto-hdkey`) | Blockchain Commons Research master, fetched 2026-08-24 | `origin`/`children`/`parent-fingerprint` are all optional; `source-fingerprint` optional |
| BCR-2020-010 (`crypto-output`), test vectors | same | measured single-part UR length 259 chars for one hdkey + origin + children; marked DEPRECATED in favour of BCR-2023-010 |
| BCR-2020-015 (`crypto-account`) | same | measured 1572-char example with 7 descriptors incl. tag 409; marked DEPRECATED in favour of BCR-2023-019 |
| BCR-2020-005 (UR), BCR-2020-012 (Bytewords) | same | single-part UR = Bytewords of the untagged CBOR; minimal style = 2 chars/byte + 8-char CRC-32 |
| `segno` (local, in-sandbox) | — | every QR version figure in item 5, and that base58 forces byte mode |
