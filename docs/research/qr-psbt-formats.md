# Research: QR-PSBT transport formats accepted by the target watch-only wallets

Ticket: [#4](https://github.com/allisson/aobs/issues/4). Branch `research/qr-psbt-formats` —
findings only, no decision. The map ([#1](https://github.com/allisson/aobs/issues/1)) and the
human own the decision.

Scope fixed by the map: single-sig, **BIP84** (native segwit) and **BIP86** (taproot), on
**mainnet, testnet4, signet, regtest**. Target watch-only wallets: **Sparrow**, **Blockstream
App / Green**, **Blue Wallet**.

All source-code claims below are pinned to a commit or tag of the wallet's own repository, cloned
on 2026-08-24. Spec claims are pinned to the BCR/BIP text itself. Anything not read directly is
marked **UNCONFIRMED** with the check that would settle it.

## Status of this document

**IN PROGRESS** — captured incrementally as each item is settled. Items not yet marked settled
carry no weight.

- [ ] 1. What each wallet ACCEPTS (scans) — signed PSBT, device → wallet
- [ ] 2. What each wallet PRODUCES (displays) — unsigned PSBT, wallet → device
- [ ] 3. The intersection, and the minimum set the appliance must implement
- [ ] 4. Fragment sizing and frame counts
- [ ] 5. Version / compatibility traps

## Candidate formats (the vocabulary this document uses)

| name | what it is | owner |
|---|---|---|
| **BC-UR v1** | Blockchain Commons Uniform Resources, first generation. `ur:bytes/1of3/<seq>/<payload>` style multi-part, fixed sequencing, no fountain code. | Blockchain Commons |
| **BC-UR v2** | Second generation. `ur:crypto-psbt/<seqNum>-<seqLen>/<fragment>` with a **fountain code** (rateless), so a receiver can recover from any sufficient subset of frames. | Blockchain Commons, BCR-2020-005 / BCR-2020-006 |
| **`crypto-psbt`** | The UR *type* registered for a PSBT: a CBOR byte string wrapping the raw BIP174 binary. BCR-2020-006. | Blockchain Commons |
| **`ur:psbt`** | Post-2023 rename of the same registry entry under the CBOR-tag-cleanup (`crypto-psbt` → `psbt`). Same payload. | Blockchain Commons |
| **BBQr** | Coinkite's format: `B$` header, base32/zlib, `<encoding><filetype><total><index>` header per frame. | Coinkite |
| **plain base64** | The BIP174 base64 serialization in a single QR, no envelope. | BIP174 |
| **raw binary** | The BIP174 binary serialization straight into a QR byte-mode segment. | BIP174 |
| **legacy `pNofM`** | Specter's ad-hoc chunking: `p1of3 <base64 chunk>`. | Specter |

## Sparrow

Pinned to `sparrowwallet/sparrow` **master @ `70f9c84`** (2026-08-24), `version = '2.5.4'` in
`build.gradle`. UR is not hand-rolled: `build.gradle:75` declares
`implementation('com.sparrowwallet:hummingbird:1.7.4')` — Sparrow's own Java port of
Blockchain Commons' URKit (`hummingbird` @ `6f06b2c`, `version '1.7.4'`).

### What Sparrow ACCEPTS (scans) — `control/QRScanDialog.java`

Three decoders are instantiated side by side and the fragment text decides which one gets it
(`QRScanDialog.java:91-93`):

```java
this.urDecoder = new URDecoder();
this.legacyUrDecoder = new LegacyURDecoder();
this.bbqrDecoder = new BBQRDecoder();
```

Dispatch order in the scan loop (`QRScanDialog.java:234-270`):

1. `LegacyURDecoder.isLegacyURFragment(qrtext)` → **UR v1** (`ur:bytes/<checksum>/<i>of<n>/<bc32>`).
2. otherwise `urDecoder.receivePart(qrtext)` → **UR v2** (fountain).
3. `BBQRDecoder.isBBQRFragment(qrtext)` → **BBQr**.

For UR v2, the registry type is then switched on (`QRScanDialog.java:433-535`). Both PSBT spellings
are handled:

- `RegistryType.BYTES` (`ur:bytes`, line 435) — the raw bytes are tried as a PSBT
  (`new PSBT(urBytes, false)`), then as a transaction, then as UTF-8 text.
- `RegistryType.CRYPTO_PSBT` (`ur:crypto-psbt`, line 465) — `CryptoPSBT.getPsbt()`.
- `RegistryType.PSBT` (`ur:psbt`, line 502) — the post-2023 registry name.

`RegistryType` (hummingbird `registry/RegistryType.java`) fixes the two spellings and their CBOR
tags: `CRYPTO_PSBT("crypto-psbt", 310, …)` and `PSBT("psbt", 40310, …)`.

**Single-frame (non-UR) text** is also accepted (`QRScanDialog.java:317-397`), tried in order:

| attempt | source line |
|---|---|
| `PSBT.fromString(qrtext, false)` — base64 **or** hex PSBT | 348 |
| `new PSBT(qrResult.getRawBytes(), false)` — raw binary QR payload | 360 |
| `new Transaction(Utils.hexToBytes(qrtext))` — hex raw tx | 368 |
| `new Transaction(qrResult.getRawBytes())` — binary raw tx | 376 |
| `new PSBT(Base43.decode(qrtext), false)` — **Base43** (Electrum's encoding) | 385 |

So Sparrow's scan side is maximally permissive: UR v1, UR v2 (`bytes`/`crypto-psbt`/`psbt`), BBQr,
and single-QR base64 / hex / raw-binary / base43.

### What Sparrow PRODUCES (displays) — `control/QRDisplayDialog.java`

`control/QREncoding.java` enumerates exactly three display encodings:

```java
public enum QREncoding { UR("UR"), BBQR("BBQr"), RAW("Raw"); }
```

The PSBT-to-device path is `transaction/HeadersController.java:1013-1031` (`showPSBT`):

```java
boolean includeNonWitnessUtxos = !Arrays.asList(ScriptType.WITNESS_TYPES).contains(headersForm.getSigningWallet().getScriptType());
byte[] psbtBytes = headersForm.getPsbt().getForExport().serialize(true, includeNonWitnessUtxos);
CryptoPSBT cryptoPSBT = new CryptoPSBT(psbtBytes);
BBQR bbqr = addBbqrOption ? new BBQR(BBQRType.PSBT, psbtBytes) : null;
QRDisplayDialog qrDisplayDialog = new QRDisplayDialog(cryptoPSBT.toUR(), bbqr, addLegacyEncodingOption, true, encoding);
```

- **Default and always-available: `ur:crypto-psbt`** (UR v2 fountain). Not `ur:psbt` — Sparrow
  accepts `ur:psbt` but does not emit it.
- **BBQr** is offered only when a keystore's `WalletModel.showBbqr()` is true, and pre-selected only
  when every keystore's `selectBbqr()` is true (`HeadersController.java:1019-1020`). Type code `P`
  (`io/bbqr/BBQRType.java`), `DEFAULT_BBQR_ENCODING = BBQREncoding.ZLIB`
  (`QRDisplayDialog.java:51`) — i.e. `B$Z…`.
- **UR v1 ("Legacy Encoding (Cobo Vault)")** is a toggle button, offered only when a keystore's
  `WalletModel.showLegacyQR()` is true. It re-wraps as `RegistryType.BYTES`
  (`QRDisplayDialog.java:282`) — so UR v1 from Sparrow is `ur:bytes`, never `ur:crypto-psbt`. The
  code carries `//TODO: Remove once Cobo Vault support has been removed`
  (`HeadersController.java:1017`).
- **RAW** is not offered on the PSBT path: `showPSBT` passes no `raw` argument, and the RAW combo
  entry is added only `if(raw != null)` (`QRDisplayDialog.java:406`).

Notable for item 4: for witness script types (BIP84 and BIP86 both), Sparrow **strips
`PSBT_IN_NON_WITNESS_UTXO`** before display — "Don't include non witness utxo fields for segwit
wallets when displaying the PSBT as a QR - it can add greatly to the time required for scanning"
(`HeadersController.java:1022`).

### Fragment sizing (Sparrow)

`control/QRDensity.java`:

```java
NORMAL("Normal", 400, 2000),
LOW("Low", 80, 1000);
```

— `maxUrFragmentLength` / `maxBbqrFragmentLength`. `QRDisplayDialog.java:45` sets
`MIN_FRAGMENT_LENGTH = 10` and `ANIMATION_PERIOD_MILLIS = 200d` (**5 fps**, matching the 5 fps scan
rate settled in [#6](https://github.com/allisson/aobs/issues/6)). The encoder is
`new UREncoder(ur, Config.get().getQrDensity().getMaxUrFragmentLength(), MIN_FRAGMENT_LENGTH, 0)`
(`QRDisplayDialog.java:95`). Scroll-wheel on the QR adjusts the period between
`ANIMATION_PERIOD_MILLIS/2` (100 ms) and `ANIMATION_PERIOD_MILLIS*10` (2000 ms).

Fragment count follows hummingbird `fountain/FountainEncoder.java:103-114`:

```java
static int findNominalFragmentLength(int messageLen, int minFragmentLen, int maxFragmentLen) {
    int maxFragmentCount = Math.max(1, messageLen / minFragmentLen);
    int fragmentLen = 0;
    for(int fragmentCount = 1; fragmentCount <= maxFragmentCount; fragmentCount++) {
        fragmentLen = (int)Math.ceil((double)messageLen / (double)fragmentCount);
        if(fragmentLen <= maxFragmentLen) break;
    }
    return fragmentLen;
}
```

So `seqLen = ceil(cborLen / 400)` at Normal density, `ceil(cborLen / 80)` at Low — where `cborLen`
is the CBOR encoding of the `crypto-psbt` byte string, not the PSBT length itself.

### Sparrow trap: BBQr and UR v1 are gated on the keystore's `WalletModel`

`drongo/src/main/java/com/sparrowwallet/drongo/wallet/WalletModel.java:147-169` (drongo master, cloned 2026-08-24):

```java
public boolean showLegacyQR() { if(this == COBO_VAULT) return true; else return false; }
public boolean showBbqr()     { if(this == COLDCARD || this == SPARROW || this == KRUX) return true; else return false; }
public boolean selectBbqr()   { if(this == COLDCARD) return true; else return false; }
```

So for a keystore whose `WalletModel` is none of `COLDCARD`/`SPARROW`/`KRUX`, Sparrow offers
**UR only** on the PSBT display — no BBQr button at all. Which `WalletModel` an aobs-exported
keystore ends up with depends on the import pane the user chose
(`control/FileImportPane.java:210`: `keystore.setWalletModel(importer.getWalletModel())`) —
**UNCONFIRMED** for aobs, and not decidable from source: it depends on how aobs presents its xpub
export and which entry the user picks in Sparrow's import list. `ScriptType.WITNESS_TYPES`
(`drongo .../protocol/ScriptType.java:1497`) includes `P2TR`, so the non-witness-UTXO stripping
applies to BIP86 as well as BIP84.

## Blue Wallet

Pinned to `BlueWallet/BlueWallet` **master @ `97f9d72`** (2026-08-21), `"version": "8.0.2"` in
`package.json`. UR libraries (`package.json:98-99`):

```json
"@keystonehq/bc-ur-registry": "0.8.0",
"@ngraveio/bc-ur": "1.1.13",
```

BBQr is Blue Wallet's own implementation, vendored at `blue_modules/bbqr/{split,join}.ts`. UR v1 is
a vendored copy of the old `bc-ur` at `blue_modules/bc-ur/dist/`.

### What Blue Wallet ACCEPTS (scans) — `screen/send/ScanQRCode.tsx`

Dispatch is by **literal uppercased string prefix** (`ScanQRCode.tsx:165-201`):

```js
if (ret.data.toUpperCase().startsWith('UR:CRYPTO-ACCOUNT'))       return _onReadUniformResourceV2(ret.data);
if (ret.data.toUpperCase().startsWith('UR:CRYPTO-PSBT'))          return _onReadUniformResourceV2(ret.data);
if (ret.data.toUpperCase().startsWith('UR:CRYPTO-OUTPUT'))        return _onReadUniformResourceV2(ret.data);
if (ret.data.toUpperCase().startsWith('UR:CRYPTO-HDKEY'))         return _onReadUniformResourceV2(ret.data);
if (ret.data.toUpperCase().startsWith('UR:CRYPTO-MULTI-ACCOUNTS'))return _onReadUniformResourceV2(ret.data);
if (ret.data.toUpperCase().startsWith('B$')) { useBBQRRef.current = true; return _onReadUniformResourceV2(ret.data); }
if (ret.data.toUpperCase().startsWith('UR:BYTES')) {
  const splitted = ret.data.split('/');
  if (splitted.length === 3 && splitted[1].includes('-')) return _onReadUniformResourceV2(ret.data);
}
if (ret.data.toUpperCase().startsWith('UR')) return _onReadUniformResource(ret.data);   // deprecated UR v1
```

So Blue Wallet accepts, for a signed PSBT:

- **`ur:crypto-psbt`** (UR v2, fountain) — via `BlueURDecoder extends URDecoder`
  (`blue_modules/ur/index.js`), whose `toString()` handles `decoded.type === 'crypto-psbt'` and
  returns base64.
- **`ur:bytes`** — v2 when the fragment has three `/`-separated parts and a `-` in the sequence
  component; otherwise treated as UR v1.
- **UR v1** — `_onReadUniformResource`, explicitly annotated
  `@deprecated remove when we get rid of URv1 support` (`ScanQRCode.tsx:124-125`). It sniffs the
  decoded payload with `startsWith('psbt')` and re-encodes to base64.
- **BBQr** — any `B$…` fragment; `BlueURDecoder.receivePart` diverts it, and `joinQRs` with
  `fileType === 'P'` returns base64.
- **Base43** (Electrum) single QR — `Base43.decode` then `bitcoin.Psbt.fromHex`
  (`ScanQRCode.tsx:203-206`).
- **Anything else** falls through verbatim to `onBarScanned(ret.data, …)`.

**Trap — `ur:psbt` is NOT supported.** The prefix list has no `UR:PSBT` entry, so `ur:psbt/…`
matches only the final `startsWith('UR')` and is routed to the **UR v1** decoder, which fails on a
v2 fragment. And even if it reached v2, `BlueURDecoder.toString()` only special-cases
`crypto-psbt`, `bytes`, `crypto-account`, `crypto-output`, `crypto-hdkey` and
`crypto-multi-accounts`; anything else falls through to `return decoded.cbor.toString('hex')`.
Confirmed by reading `blue_modules/ur/index.js` in full — `'psbt'` never appears as a UR type.

**Plain base64 in a single QR — works, but by accident.** The fall-through hands the raw string to
`screen/send/psbtWithHardwareWallet.tsx:76-88`:

```js
if (data.toUpperCase().startsWith('UR')) presentAlert({ message: 'BC-UR not decoded. This should never happen' });
if (data.indexOf('+') === -1 && data.indexOf('=') === -1 && data.indexOf('=') === -1) {
  // this looks like NOT base64, so maybe its transaction's hex
  setTxHex(data); return;
}
```

A base64 PSBT that happens to contain no `+` and no `=` is misread as a transaction hex. A PSBT
whose length is a multiple of 3 has no `=` padding, and `+` appears only when the byte stream
produces that sextet — so this is a **real, if uncommon, failure mode** for single-QR base64. Not
device-tested; the code path is read in full.

### What Blue Wallet PRODUCES (displays) — `components/DynamicQRCode.tsx` + `blue_modules/ur/index.js`

`screen/send/psbtWithHardwareWallet.tsx:259`:

```jsx
{psbt && <DynamicQRCode value={psbt.toHex()} ref={dynamicQRCode} walletID={walletID} />}
```

`DynamicQRCode.tsx:49-51` — `const { value, capacity = 175, … } = this.props;` then
`this.fragments = encodeUR(value, capacity, walletID ?? null);`. Three protocol paths in
`encodeUR` (`blue_modules/ur/index.js`):

| condition | output |
|---|---|
| `forceProtocol === 'BBQR'` or `walletID` in `USE_BBQR_WALLET_IDS` | BBQr, `splitQRs(bytes, 'P', {minSplit})` |
| `useURv1` (AsyncStorage key `USE_UR_V1`) | UR v1 via the vendored `origEncodeUR` |
| default | **UR v2 `ur:crypto-psbt`** via `new CryptoPSBT(data).toUREncoder(len)` |

- Default is **`ur:crypto-psbt`** — never `ur:psbt`.
- UR v1 is a **user-facing settings toggle**: `setUseURv1()` is called from
  `components/Context/SettingsProvider.tsx:285`, read back by `isURv1Enabled()` at line 173.
- BBQr is **auto-learned per wallet**: `components/Context/StorageProvider.tsx:474-479` — if the
  scan that imported the wallet was BBQr (`getScanWasBBQR()`), the wallet's ID is recorded via
  `setWalletIdMustUseBBQR(w.getID())` and that wallet thereafter displays BBQr. There are also
  explicit `'BBQR'` and `'URv2'` force buttons on the QR component
  (`DynamicQRCode.tsx:86`, `:102`).
- Frame rate: `setInterval(this.moveToNextFragment, 1000)` (`DynamicQRCode.tsx:116`) — **1 fps**,
  five times slower than Sparrow.
- Fragment size: **175 bytes** default capacity.
- Unlike Sparrow, Blue Wallet does **not** strip `PSBT_IN_NON_WITNESS_UTXO`: it displays
  `psbt.toHex()` of whatever it built.

## Blockstream App / Green

Pinned to `Blockstream/green_android` **master @ `49096a4`** (2026-07-22). Green does not implement
UR itself: it calls GDK's `bcur_encode` / `bcur_decode`. GDK pinned to `Blockstream/gdk`
**master @ `8af8abd`** (2026-08-20), `CHANGELOG.md` head = **Release 0.77.9 (26-08-20)**. GDK in
turn wraps the C++ `bc-ur` library plus `ur-c` (`src/bcur_auth_handlers.cpp`).

### What Green ACCEPTS (scans)

`compose/.../models/abstract/AbstractScannerViewModel.kt:62`:

```kotlin
if ((isDecodeContinuous && scannedText.startsWith(prefix = "ur:", ignoreCase = true)) || bcurPartEmitter != null) {
```

Any `ur:`-prefixed fragment is fed to `session.bcurDecode(BcurDecodeParams(part = scannedText))`.
The PSBT screen launches the scanner with `isDecodeContinuous = true`
(`compose/.../screens/jade/JadeQRScreen.kt:279`).

GDK decides the types — `gdk/src/bcur_auth_handlers.cpp:277-295`:

```cpp
auto ur_type = boost::algorithm::to_lower_copy(ur.type());
if (ur_type == "crypto-psbt" || ur_type == "psbt") {
} else if (ur_type == "crypto-output") {
} else if (ur_type == "crypto-account") {
} else if (ur_type == "jade-bip8539-reply") {
} else if (ur_type == "jade-pin") {
} else {
    return_raw_data = true; // bytes or an unknown type, return raw
}
```

- **`ur:crypto-psbt` and `ur:psbt` are both accepted** — Green is the only one of the three that
  takes the new spelling. The decoded PSBT is surfaced as base64
  (`bcur_auth_handlers.cpp:47`: `{ "psbt", base64_from_bytes(...) }`).
- **UR v2 only.** The decoder is `ur::URDecoder` from the C++ `bc-ur` library
  (`bcur_auth_handlers.cpp:253`). No UR v1 / `pNofM` path exists in GDK's bcur handler or in
  Green's scanner. **UR v1 is not supported.**
- **No BBQr.** `grep -rn 'bbqr\|B\$'` over `green_android` (Kotlin) and `gdk` (C++) returns nothing.
- **Plain single-QR base64 appears to work, by pass-through.** A non-`ur:` scan becomes
  `ScanResult(result = <raw text>)`; `JadeQRViewModel.setScanResult` for `JadeQrOperation.Psbt`
  posts it as `SideEffects.Success(scanResult.result)` (`JadeQRViewModel.kt:446-449`);
  `screens/send/SendConfirmScreen.kt:110-115` turns that into
  `BroadcastPsbtTransaction(psbt = it.result)` → `BroadcastTransactionParams(psbt = …)`, and GDK's
  broadcast takes a **base64** PSBT string. Every hop is read, but this is
  **inferred from the code path and not device-tested**.

### What Green PRODUCES (displays)

`data/.../gdk/GdkSession.kt:2573-2580`:

```kotlin
suspend fun jadePsbtRequest(psbt: String): BcurEncodedData {
    val params = BcurEncodeParams(urType = "crypto-psbt", data = psbt)
    return bcurEncode(params)
}
```

- **`ur:crypto-psbt` only.** No BBQr, no UR v1, no raw/base64 display option on this path. GDK
  normalises anyway: `prepare_psbt_ur` returns `{ "crypto-psbt", { cbor, cbor + cbor_len } }`
  (`bcur_auth_handlers.cpp:191`), so even `ur_type: "psbt"` comes out labelled `crypto-psbt`
  (`bcur_auth_handlers.cpp:222`).
- **Fragment size 50 bytes.** `BcurEncodeParams.maxFragmentLen` defaults to `50`
  (`data/.../gdk/params/BcurEncodeParams.kt:23`) and `jadePsbtRequest` does not override it — 8×
  smaller than Sparrow's Normal density, 3.5× smaller than Blue Wallet's.
- **Frame rate 2 fps.** `JadeQRViewModel.kt:242` — `delay(500L)` between parts. Green cycles
  `parts` in order (not a fountain stream) and flips `_isValid` once half the parts have been shown
  (`JadeQRViewModel.kt:237-239`).
- The PSBT reaching this path is whatever GDK produced (`it.psbt` in
  `CreateTransactionViewModel.kt:471`); there is no QR-specific field stripping.

## Findings

_(populated below as each item lands)_

## Evidence index

_(populated below)_
