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

## Findings

_(populated below as each item lands)_

## Evidence index

_(populated below)_
