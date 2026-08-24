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

## Findings

_(populated below as each item lands)_

## Evidence index

_(populated below)_
