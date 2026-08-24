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

- [x] 1. What each wallet ACCEPTS (scans) — signed PSBT, device → wallet
- [x] 2. What each wallet PRODUCES (displays) — unsigned PSBT, wallet → device
- [x] 3. The intersection, and the minimum set the appliance must implement
- [x] 4. Fragment sizing and frame counts
- [x] 5. Version / compatibility traps
- [x] 6. Python implementation on Alpine/musl, and embit's coverage (ticket item 3)

Every source-code claim below was read at the pinned commit. Nothing here was tested against a
running wallet — see **What is NOT settled here**.

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

## 1 + 2. Accept / produce matrix

Signed PSBT **into** the wallet (device → wallet) = ACCEPT. Unsigned PSBT **out of** the wallet
(wallet → device) = PRODUCE.

| format | Sparrow 2.5.4 | Blue Wallet 8.0.2 | Green (GDK 0.77.9) |
|---|---|---|---|
| `ur:crypto-psbt` (UR v2) | accept ✔ / **produce ✔ (default)** | accept ✔ / **produce ✔ (default)** | accept ✔ / **produce ✔ (only)** |
| `ur:psbt` (UR v2, registry-preferred) | accept ✔ / produce ✘ | **accept ✘** / produce ✘ | accept ✔ / produce ✘ (normalised to `crypto-psbt`) |
| `ur:bytes` (UR v2) | accept ✔ (sniffed as PSBT) / produce ✘ on this path | accept ✔ / produce ✘ | accept ✔ (returned raw) / produce ✘ |
| UR v1 (`ur:bytes/<crc>/<i>of<n>/…`) | accept ✔ / produce ✔ *(only if keystore model = `COBO_VAULT`)* | accept ✔ (deprecated path) / produce ✔ *(only if `USE_UR_V1` toggled)* | **accept ✘ / produce ✘** |
| BBQr (`B$…`) | accept ✔ / produce ✔ *(only if keystore model ∈ {COLDCARD, SPARROW, KRUX})* | accept ✔ / produce ✔ *(only if the wallet was imported from a BBQr scan, or forced)* | **accept ✘ / produce ✘** |
| plain base64, single QR | accept ✔ (`PSBT.fromString`) / produce ✘ | accept ~ (fall-through; **breaks if the base64 has no `+` and no `=`**) / produce ✘ | accept ~ (fall-through, **not device-tested**) / produce ✘ |
| hex PSBT, single QR | accept ✔ / produce ✘ | accept ✘ (read as a raw tx hex) / produce ✘ | accept ✘ / produce ✘ |
| raw binary QR payload | accept ✔ (`new PSBT(rawBytes)`) / produce ✘ | accept ✘ / produce ✘ | accept ✘ / produce ✘ |
| Base43 (Electrum) | accept ✔ / produce ✘ | accept ✔ / produce ✘ | accept ✘ / produce ✘ |
| Specter `p1of3` | accept ✘ / produce ✘ | accept ✘ / produce ✘ | accept ✘ / produce ✘ |

Nothing proprietary turned up in any of the three for PSBT transport. Green's `jade-pin` and
`jade-bip8539-request` UR types are proprietary but belong to Jade PIN unlock and BIP85, not to
PSBT signing.

## 3. The intersection

**Yes — there is exactly one format all three both accept and produce: `ur:crypto-psbt`,
UR v2, animated multi-part.** It is the default on the produce side of all three, and it is on the
accept side of all three.

**The minimum set the appliance must implement is therefore one format**, in both directions:

- **Emit** `ur:crypto-psbt`, UR v2, multi-part.
- **Accept** `ur:crypto-psbt` and, for robustness at no cost, `ur:psbt` and `ur:bytes` — since
  Sparrow can emit `ur:bytes` on other paths and the registry pushes toward `psbt`.

**Do NOT emit `ur:psbt`,** even though BCR-2020-006 marks `crypto-psbt` deprecated and says
deprecated types "should only be read, not written". Blue Wallet cannot parse `ur:psbt` at all: its
prefix dispatcher has no `UR:PSBT` case, so the fragment is routed to the UR **v1** decoder and
fails. Blue Wallet is the outlier here, and following the registry would break it.

**Outliers by direction:**

- **Green is the outlier on breadth**: UR v2 only. No UR v1, no BBQr. If the appliance ever wanted
  BBQr as a denser alternative, Green would be left out entirely.
- **Blue Wallet is the outlier on spelling**: the only one of the three that rejects `ur:psbt`.
- **Sparrow is the outlier on generosity**: it accepts everything, including single-QR base64,
  hex, raw binary and base43. Sparrow will never be the constraint.

BBQr is not a viable common denominator: Green has no BBQr code at all, and in both Sparrow and
Blue Wallet BBQr is conditional on per-keystore/per-wallet state the appliance does not control.

## 4. Fragment sizing and frame counts

### Fragment size, animation period, and part-stream shape

| wallet | UR fragment size (bytes) | frame period | parts emitted |
|---|---|---|---|
| Sparrow, Normal density | **400** (`QRDensity.NORMAL`) | **200 ms** (`ANIMATION_PERIOD_MILLIS`), scroll-adjustable 100–2000 ms | unbounded fountain stream (`UREncoder.nextPart()` in a `ScheduledService`) |
| Sparrow, Low density | **80** (`QRDensity.LOW`) | same | same |
| Blue Wallet | **175** (`DynamicQRCode` `capacity` default) | **1000 ms** (`setInterval(…, 1000)`) | exactly `encoder.fragmentsLength` parts, cycled |
| Green | **50** (`BcurEncodeParams.maxFragmentLen`) | **500 ms** (`delay(500L)`) | **`3 × seqLen`** parts, cycled (`bcur_auth_handlers.cpp:230`) |

Sparrow's min fragment length is 10 (`QRDisplayDialog.MIN_FRAGMENT_LENGTH`), and the fragment
length actually used is `findNominalFragmentLength(messageLen, 10, maxUrFragmentLength)` — i.e. the
message is divided into the smallest number of equal fragments that fit under the cap, so real
fragments are usually smaller than the cap.

GDK over-provisions: `const size_t num_parts = m_encoder->seq_len() == 1 ? 1 : 3 * m_encoder->seq_len();`
(`gdk/src/bcur_auth_handlers.cpp:230`). Parts beyond `seqLen` are fountain-coded mixes
(BCR-2020-005), so the extra 2× is redundancy, not new data.

### Frame counts for a signed single-sig PSBT

Sizes below are a **byte-by-byte accounting from BIP174/BIP371 field layouts**, not measured from a
real wallet — the arithmetic is in this document's `Method` note. UR frame count is
`ceil(cborLen / fragmentSize)` where `cborLen` is the CBOR byte-string encoding of the PSBT
(1 + 3 header bytes for a 256–65535-byte payload; BCR-2020-006 requires the top-level object to be
**untagged**, so `crypto-psbt` is a bare CBOR `bytes`).

| case | PSBT bytes | CBOR bytes | Sparrow /400 | Sparrow /80 | Blue /175 | Green /50 |
|---|---|---|---|---|---|---|
| **BIP84 P2WPKH, 2-in/2-out, signed** | 633 | 636 | **2** | 8 | **4** | **13** |
| **BIP86 P2TR, 2-in/2-out, signed** | 702 | 705 | **2** | 9 | **5** | **15** |
| BIP84 P2WPKH, 4-in/2-out, signed | 1123 | 1126 | 3 | 15 | 7 | 23 |
| BIP86 P2TR, 4-in/2-out, signed | 1202 | 1205 | 4 | 16 | 7 | 25 |

Minimum transmission time (one pass over `seqLen` parts; in practice a receiver needs a few extra
frames):

| case | Sparrow @200 ms | Blue Wallet @1000 ms | Green @500 ms (one pass) | Green (full `3×seqLen` cycle) |
|---|---|---|---|---|
| BIP84 2-in/2-out | 0.4 s | 4.0 s | 6.5 s | 19.5 s |
| BIP86 2-in/2-out | 0.4 s | 5.0 s | 7.5 s | 22.5 s |

**On the taproot premise.** The ticket's framing — "a taproot PSBT needs all input UTXOs present" —
is true but does **not** inflate the PSBT much. BIP341's sighash commits to the amounts and
scriptPubKeys of *all* spent outputs, so every input needs a `PSBT_IN_WITNESS_UTXO` (32 bytes of
scriptPubKey + 8 of value + framing ≈ 46 bytes/input), whereas a segwit-v0 sighash only needs the
input's own. But a coordinator populates `witness_utxo` on every input anyway, so the 2-in taproot
PSBT is only ~11% larger than the segwit-v0 one (702 vs 633 bytes): the taproot growth comes from
`PSBT_IN_TAP_INTERNAL_KEY` and `PSBT_IN_TAP_BIP32_DERIVATION`, offset by the 64-byte Schnorr
signature being smaller than a 72-byte DER one. **What would explode the size is
`PSBT_IN_NON_WITNESS_UTXO`** — the full previous transaction per input, hundreds of bytes to
kilobytes each. Sparrow strips it for witness script types before display
(`HeadersController.java:1022`); Blue Wallet and Green do not, so a PSBT arriving from them may be
much larger than the table above. **Unconfirmed:** whether Blue Wallet's and Green's coordinators
ever populate `non_witness_utxo` for segwit/taproot inputs in practice. Confirming it would take
capturing a real PSBT from each app.

**Green is the frame-count problem.** At 50 bytes/fragment and 500 ms/frame, 13–15 fragments and a
39–45-frame display cycle, Green's channel is roughly 30× slower than Sparrow's. The appliance's
**scan** side must therefore tolerate long acquisitions — the 5 fps decode rate settled in
[#6](https://github.com/allisson/aobs/issues/6) is ample against a 2 fps emitter, but the review
UI must show progress over tens of seconds rather than assume a sub-second read.

**The appliance's own emitter is unconstrained by these numbers.** Nothing in any of the three
wallets caps the fragment size it will *scan* — the fragment size is a property of the sender.
Sparrow's 400 bytes at Normal density is a reasonable model for what a phone camera decodes
reliably; Green's 50 is conservative. Choosing the appliance's own fragment size is a separate
question this ticket does not settle, and it should be validated against a real phone camera, not
computed.

## 5. Version and compatibility traps

1. **`crypto-psbt` vs `psbt` — the registry and the deployed wallets disagree.** BCR-2020-006
   (revised 2025-04-26) marks `crypto-psbt`/tag 310 deprecated in favour of `psbt`/tag 40310, and
   says deprecated types "should only be read, not written". None of the three wallets writes
   `psbt`, and **Blue Wallet cannot read it**. Following the registry's recommendation would break
   Blue Wallet. Emit `crypto-psbt`; accept both.
2. **UR v1 support is still required on the accept side of nothing — but is still *offered* on the
   produce side of two.** The appliance does not need to *emit* UR v1: nothing requires it. But it
   may *receive* UR v1 if the user toggles Blue Wallet's `USE_UR_V1` setting, or if a Sparrow
   keystore is typed `COBO_VAULT`. Both are user-reachable states. **Decision-relevant, not
   settled here:** whether the appliance's scanner implements UR v1 as a defensive measure or
   refuses it with a clear message.
3. **Blue Wallet's per-wallet BBQr latch is sticky.** If the wallet was imported into Blue Wallet
   from a BBQr scan, that wallet's ID goes into `USE_BBQR_WALLET_IDS`
   (`StorageProvider.tsx:474-479`) and it will thereafter *display* PSBTs as BBQr, not UR. Since
   the appliance will never emit BBQr for the xpub export, this latch should never trip — but it
   means "Blue Wallet produces UR v2" is true only conditional on how the wallet was imported.
4. **Sparrow's BBQr and legacy buttons are keystore-model-dependent**, not global settings
   (`WalletModel.java:147-169`). Which model an aobs keystore gets is **UNCONFIRMED** and depends
   on the import path chosen in Sparrow's UI.
5. **Blue Wallet's single-QR base64 heuristic** (`data.indexOf('+') === -1 && data.indexOf('=') === -1`)
   makes a padding-free, `+`-free base64 PSBT be read as a transaction hex. This is a reason to
   never rely on single-QR base64 as a fallback for Blue Wallet.
6. **Networks.** Nothing network-specific was found in any of the three QR/UR code paths: the
   transport carries the BIP174 blob and the network is inferred downstream from the wallet's own
   descriptor. So mainnet / testnet4 / signet / regtest do not change the transport question.
   **Whether each app supports testnet4/signet/regtest at all is a different question and is not
   settled here.**
7. **Versions move.** All three repos are on `master`, not a release tag: Sparrow `2.5.4`
   (`build.gradle:24`), Blue Wallet `8.0.2` (`package.json`), GDK `0.77.9` (`CHANGELOG.md`). Any
   claim above should be re-checked against the version a user actually runs.

## 6. A Python UR v2 implementation on Alpine/musl, and what embit covers

**embit covers none of it.** `diybitcoinhardware/embit` @ `eb6104f` (2026-08-08): a grep of the
entire `src/` tree for `bytewords`, `fountain`, `cbor`, `crypto-psbt` or "uniform resource" returns
**nothing**. `src/embit/` is `base58 bech32 bip32 bip39 bip85 compact descriptor ec finalizer
hashes liquid misc networks psbt psbtview script slip39 transaction util wordlists` — PSBT
serialization yes (including `psbtview.py`, a streaming parser), UR transport no. The QR layer is
entirely the appliance's to add.

**A pure-Python UR v2 implementation exists and is field-proven: SeedSigner's vendored `ur2`.**
`SeedSigner/seedsigner` @ `d70b322` (2026-08-22), `src/seedsigner/helpers/ur2/` —
**1642 lines across 15 modules**, BSD-2-Clause-Plus-Patent:

```
bytewords.py  cbor_lite.py  constants.py  crc32.py  fountain_decoder.py
fountain_encoder.py  fountain_utils.py  random_sampler.py  ur.py
ur_decoder.py  ur_encoder.py  utils.py  xoshiro256.py
```

The only non-local imports across the whole package are `math`, `sys` and `time`. It carries its
own CBOR (`cbor_lite.py`), CRC-32 (`crc32.py`), Bytewords codec and Xoshiro256 PRNG — so **no
native extension, no C dependency, nothing musl-sensitive**. Both directions are present:
`UREncoder` (fountain) and `URDecoder`.

The registry layer is the separate `urtypes` package — SeedSigner pins the selfcustody fork
(`requirements.txt`: `urtypes @ git+https://github.com/selfcustody/urtypes.git@7fb280e`); PyPI
`urtypes` 1.0.1 ships as `urtypes-1.0.1-py3-none-any.whl`, i.e. **pure Python, no wheels to build**.
`urtypes.crypto.PSBT` is the `crypto-psbt` type. For a single-sig appliance the needed surface is
small enough that vendoring only what is used is a live option — **not a decision for this ticket**.

SeedSigner also pins `embit==0.8.0`, the same embit line the appliance targets, so the two compose
in production today.

For calibration, SeedSigner's own UR fragment sizes (`models/encode_qr.py:295-300`) are
`LOW: 10, MEDIUM: 30, HIGH: 120` bytes — far below Sparrow's 400, because it renders on a small
screen. Its legacy `pXofY` encoder (`encode_qr.py:243-252`) uses `40 / 65 / 90`, and its docstring
says it exists only "for compatibility with much older versions of Specter Desktop. Can probably
eventually be removed" — corroborating that `pNofM` is dead for the three wallets in scope.

**Unconfirmed:** whether the `ur2` package is packaged for Alpine or on PyPI under a maintained
name — SeedSigner vendors it into its own tree rather than depending on a published package, so
the realistic path is vendoring it (or `urtypes`' own UR implementation) into the appliance.
Confirming a packaged alternative would mean searching the Alpine `APKINDEX` and PyPI, which this
pass did not do.

## Method note for the frame-count arithmetic

The PSBT sizes in item 4 were computed, not measured. Each record is
`compactsize(keylen) + key + compactsize(vallen) + value` per BIP174, with all compact sizes
1 byte at these magnitudes. Fields counted, per signed-not-finalized single-sig PSBT:

- global: `PSBT_GLOBAL_UNSIGNED_TX` (0x00) holding a segwit-stripped 2-in/2-out tx, + separator.
- per input, BIP84: `PSBT_IN_WITNESS_UTXO` (0x01, 31-byte txout), `PSBT_IN_PARTIAL_SIG` (0x02,
  33-byte key + 72-byte DER sig + sighash byte), `PSBT_IN_BIP32_DERIVATION` (0x06, 33-byte key +
  4-byte fingerprint + 5×4-byte path), + separator.
- per input, BIP86 (BIP371): `PSBT_IN_WITNESS_UTXO` (43-byte txout), `PSBT_IN_TAP_KEY_SIG` (0x13,
  64 bytes — default sighash, no trailing byte), `PSBT_IN_TAP_BIP32_DERIVATION` (0x16, 32-byte
  x-only key + zero leaf hashes + fingerprint + path), `PSBT_IN_TAP_INTERNAL_KEY` (0x17, 32 bytes),
  + separator.
- one change output carries its derivation fields; the other output is empty (a separator only).
- no `PSBT_GLOBAL_XPUB`, no `PSBT_IN_SIGHASH_TYPE`, no `PSBT_IN_NON_WITNESS_UTXO`.

Real PSBTs will differ by tens of bytes (DER signatures are 71 or 72 bytes; some coordinators emit
`PSBT_IN_SIGHASH_TYPE` and `PSBT_GLOBAL_XPUB`). At Sparrow's 400-byte fragments that noise does not
change the frame count; at Green's 50-byte fragments each ±50 bytes is ±1 frame. **These numbers are
computed from the specs and have not been checked against a PSBT produced by any of the three
apps** — doing so is the confirmation step, and it needs the apps.

## Evidence index

Repositories cloned 2026-08-24, `--depth 1`:

| repo | commit | version marker |
|---|---|---|
| `sparrowwallet/sparrow` | `70f9c844b78bb07a3bbaa2307ead4a07508f4b21` (2026-08-24) | `build.gradle:24` → `2.5.4` |
| `sparrowwallet/hummingbird` | `6f06b2cd6120fe397f31b2231532d303e628c4dd` (2024-10-22) | `build.gradle:10` → `1.7.4` |
| `sparrowwallet/drongo` | master (cloned 2026-08-24) | — |
| `BlueWallet/BlueWallet` | `97f9d7277504b6acf93f80bcf920384587eca401` (2026-08-21) | `package.json` → `8.0.2` |
| `Blockstream/green_android` | `49096a4ea3a985f7ef05c953b434d8418e2a8f6b` (2026-07-22) | — |
| `Blockstream/gdk` | `8af8abd6fb0659bc97f4afef08ad6953c3752b0e` (2026-08-20) | `CHANGELOG.md` → `0.77.9` |
| `diybitcoinhardware/embit` | `eb6104fd85d3becabba628756cd5e1b75619f3a1` (2026-08-08) | — |
| `SeedSigner/seedsigner` | `d70b322f1efde01d509b9672b982b5eb43eb8afa` (2026-08-22) | `requirements.txt` → `embit==0.8.0` |

Specs:

- **BIP174** — PSBT field types and `<keylen><key><vallen><value>` record layout.
- **BIP371** — taproot PSBT fields (`PSBT_IN_TAP_KEY_SIG` 0x13, `PSBT_IN_TAP_BIP32_DERIVATION`
  0x16, `PSBT_IN_TAP_INTERNAL_KEY` 0x17, `PSBT_OUT_TAP_INTERNAL_KEY` 0x05,
  `PSBT_OUT_TAP_BIP32_DERIVATION` 0x07).
- **BCR-2020-005** (UR, v2.1.0, revised 2023-08-21) — `ur:<type>/<seqNum>-<seqLen>/<fragment>`;
  parts with `seqNum <= seqLen` are plain fixed-rate fragments, parts beyond that are fountain
  mixes.
- **BCR-2020-006** (UR type registry, revised 2025-04-26) — `40310 ~~310~~ | psbt ~~crypto-psbt~~`;
  deprecated types "should only be read, not written"; a top-level UR object "MUST NOT be tagged",
  so `crypto-psbt` is a bare CBOR byte string wrapping the BIP174 blob.
- **BCR-2024-001** (Multipart UR implementation guide, 2024-01-09) — part structure
  `[uint32 seqNum, uint seqLen, uint messageLen, uint32 checksum, bytes data]`.

## What is NOT settled here

- Which `WalletModel` a Sparrow keystore imported from aobs receives, and therefore whether
  Sparrow even offers BBQr for it.
- Whether a single-QR base64 PSBT is actually accepted by Green on a device (code path read, not
  run).
- Whether Blue Wallet's and Green's coordinators populate `PSBT_IN_NON_WITNESS_UTXO` for
  segwit/taproot inputs, which would change the frame counts substantially.
- The PSBT byte sizes against real PSBTs from the three apps.
- Whether a maintained *packaged* pure-Python UR v2 library exists (Alpine `APKINDEX` / PyPI not
  searched); SeedSigner vendors its own, so vendoring is the confirmed-available path.
- Testnet4 / signet / regtest support in each app (orthogonal to the transport, but it gates the
  test plan).
- The appliance's own fragment size — needs a real camera, not arithmetic.
