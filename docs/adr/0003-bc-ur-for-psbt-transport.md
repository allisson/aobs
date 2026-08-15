# ADR-0003 — BC-UR for PSBT transport, knowingly taking the riskier parser

- **Status**: accepted
- **Date**: 2026-08-15
- **Decides**: [#2 — QR transport format for PSBTs and wallet backups](https://github.com/allisson/aobs/issues/2)
- **Findings**: `docs/research/02-qr-transport-format.md`

## Context

QR is the only data channel, so the transport format decides which desktop wallets can talk to aobs
at all. Candidates: BC-UR / UR2, BBQr, and plain chunked base64.

Verified against cloned wallet source (Sparrow, Specter Desktop, Electrum, libnunchuk, BlueWallet,
Coldcard firmware, all August 2026), not documentation:

| Wallet | scans `ur:crypto-psbt` | displays it | scans BBQr | displays BBQr |
|---|---|---|---|---|
| Sparrow | yes | **yes, default** | yes | keystore-gated |
| Nunchuk | yes | yes | yes | yes |
| BlueWallet | yes | **yes, default** | yes (v7.2.6+) | only if imported over BBQr |
| Specter Desktop | yes | yes | **no** | **no** |
| Electrum | no | no | no | no |

**Nothing in scope does BBQr and not UR2.** Specter does UR2 and not BBQr.

Two things that look like they should decide it, and do not:

- **Density does not.** Frames needed are within one of each other at every in-scope payload size
  (385 B–3 744 B).
- **Fountain coding does not.** Monte-Carlo over 20 000 trials at 4 fps: at N ≤ 4 frames the
  advantage over cyclic is **at most 1.2 s even at 50% capture loss**. It only becomes material past
  ~20 KB, which single-sig does not produce.

BBQr's parser is genuinely better on every security axis. It is bounded by construction
(`MAX_PARTS = 1295`, a spec ceiling), caps its zlib bomb at 16 MiB, and ships adversarial tests for
exactly our threat model.

`ur-rs` is the opposite. `Decoder::receive` adopts `sequence_count` from the **first part it sees,
unvalidated**; one frame declaring `seqLen = 0xFFFFFFFF` asks for two ~34 GB vectors on a no-swap
LiveCD before any key material is touched. Its fountain decoder — the only component that ever sees
hostile data — has **no upstream fuzz target**.

## Decision

**BC-UR / UR2 for PSBTs, both directions.** Emit `ur:crypto-psbt`; accept `crypto-psbt`, `psbt` and
`bytes`. Emit the *deprecated* `crypto-psbt` spelling, because Sparrow decodes `psbt` but never
writes it and Specter's scanner regexes match only `UR:CRYPTO-*` and `UR:BYTES/`.

**The encrypted backup uses the same codec: a single-part `ur:bytes` QR at ECC H**, with the
multi-part path forbidden by rule on that prompt.

## Consequences

**We take the riskier parser, and that is the trade.** Interoperability is the thing aobs cannot
manufacture for itself; hardening is. Two obligations follow, and they are spec requirements rather
than implementation notes:

1. **Clamp `seqLen` and `messageLen` at our call site** before any part reaches `ur-rs`, plus a cap
   on total parts accepted, because fountain coding lets a hostile animation feed well-formed parts
   forever.
2. **Write the fountain-decoder fuzz target ourselves.**

Two later decisions took paths *out* of that parser's reach entirely: receive-address verification
accepts plain text, and backup restore accepts a single-part `ur:bytes` at one of five exact lengths.

**Do not cite fountain coding as the justification for this decision later. It is a tie at our
sizes.**

Electrum is unreachable by animated QR whatever we chose — no `ur:`, no BBQr, no chunking, and its
`to_qr_data()` deliberately emits an incomplete PSBT.

**Revisit trigger:** if Specter Desktop ever accepts BBQr, this is worth re-running — but establish
first which `WalletModel` Sparrow assigns to an aobs keystore imported by QR, since Sparrow only
offers BBQr display for `COLDCARD`/`SPARROW`/`KRUX`.

## Alternatives rejected

- **BBQr** — better parser, strictly smaller supported set. Choosing it subtracts Specter and adds
  nobody. Its one exclusive counterparty is Coldcard Q, and aobs never talks to another signer.
- **A second, simpler codec for the backup** — BBQr type `B` would be denser (418 chars vs 529) but
  means carrying a whole second codec plus `flate2`, `data-encoding` and `radix_fmt` for a 250-byte
  blob. Not worth two QR versions.
- **Plain chunked base64** — no counterparty accepts it.
