# ADR-0005 — A warning is only legitimate when the user knows something we don't

- **Status**: accepted
- **Date**: 2026-08-15
- **Decides**: [#13 — PSBT and QR input rejection policy](https://github.com/allisson/aobs/issues/13),
  [#22 — Which advisory warnings survive, and at what thresholds](https://github.com/allisson/aobs/issues/22)
- **Follows from**: [#9 — Transaction review screen](https://github.com/allisson/aobs/issues/9),
  [#3 — Prior-art survey](https://github.com/allisson/aobs/issues/3)

## Context

The review screen settled that warnings are advisory and never block. That forces the question of
what happens to everything that *should* stop a transaction — and it cannot be a warning, because a
signer that warns about everything trains the user to click through, after which the one warning that
mattered gets clicked through too.

## Decision

> **A warning is only legitimate when the user knows something we don't. Everything else is a
> refusal, and a refusal happens before a review screen is drawn.**

A 12% fee is a *warning*: the user may well know it is correct, because the transaction is urgent or
the absolute amount is trivial. A change output that fails re-derivation is a *refusal*: there is no
state of the user's knowledge that makes it acceptable, so asking them passes a decision they cannot
make better than we can.

**A refusal names its reason in plain language, carries a stable machine-readable code, and offers
exactly one action: discard.** No "proceed anyway" — not behind a confirmation, not in an advanced
menu. An escape hatch converts every refusal back into a warning and undoes the principle.

Applied, this yields **one advisory warning in the entire product**: `fee ≥ total sent to non-change
outputs`.

Two consequences of the principle are surprising enough to record here:

**We require a `non_witness_utxo` that hashes to its outpoint on every non-taproot input** — stricter
than Krux, which requires it only for legacy inputs. That deletes the whole BIP-143 amount-spoofing
class rather than its two published instances; Coldcard shipped it twice, six years apart. Taproot is
genuinely exempt, because BIP-341 commits to all input amounts. **Accepted cost: a coordinator
sending `witness_utxo` only is refused.**

**The fee threshold is not a percentage.** aobs has no mempool, no clock, no fee estimator and no
fiat rate, so **Coldcard's 5% and Krux's 10% encode an assumption about a market their devices cannot
observe either** — and percentage-of-spend fails at both ends anyway: 90% on a £3 spend is
unremarkable, 2% on £300,000 is not. *You are paying miners more than you are paying your recipient*
is the one fee statement true regardless of congestion, price, urgency or size, which is what makes
it sayable from inside a Faraday cage.

## Consequences

- **Failing to decode is not the same as rejecting.** Bytes that never became a PSBT are
  overwhelmingly a bad scan: say so, return to scanning. Bytes that decoded and *then* failed a check
  are hostile — discard, zeroize, no retry with the same bytes.
- **The 4-byte fingerprint is a hint only.** The byte-compare of a re-derived `scriptPubKey` is the
  sole authority, and a failed compare refuses the **whole transaction** rather than reclassifying
  the output as a plain spend.
- Change is accepted only on our own account paths with `path[-2] ∈ {0,1}`, which kills Coldcard's
  2019 change-path ransom. Coldcard warns on it; the user cannot evaluate whether their coordinator
  scans `m/84'/0'/7'/1/0`, so under this principle it is a refusal.
- **Two copy requirements** exist because these failures would otherwise read as bugs in aobs: the
  "no input is ours" refusal names the passphrase as a likely cause when one is in use, and names
  account 0 as the assumption.
- **Accepted miss, recorded:** a 1 BTC payment inflated to a 0.05 BTC fee is not caught by the one
  warning. The mitigation is the review panel already showing the fee four ways, not a second
  threshold.
- The warning renders **inline on the fee row** as a full sentence, is **absent from the per-address
  screens**, and **the signing gate is byte-identical with and without it** — lengthening the hold
  would make an advisory a soft block and teach that hold duration carries meaning.
- **Copy states the fact and never advises.** *"Are you sure?"* is a dismissal prompt in disguise.

## Alternatives rejected

- **Warn on change that fails re-derivation** (Coldcard's `Troublesome Change Outs`) — passes the
  user a decision they cannot make.
- **Refuse on fee ratio** (Coldcard refuses past a configurable 10%) — we cannot see the market that
  would justify a number.
- **An absurd-input-count cap** — the 64 KiB transport bound plus mandatory `non_witness_utxo` caps
  inputs transitively; a second arbitrary number would only refuse honest consolidations.
- **Krux's mixed-input-script-type refusal** — mixing P2WPKH and P2TR from one seed is legitimate,
  and the refusal is a *proxy* for per-input re-derivation, which we do directly.
- **An OP_RETURN carve-out** — "every output must be a renderable address" is the simpler rule.
- **Warning on non-zero locktime** — the trap. Bitcoin Core sets `nLockTime` as anti-fee-sniping, so
  it is the norm and would fire on nearly every modern transaction.
- **Warning on consolidations, output count, or dust** — cut on rarity, emptiness and loudness
  respectively.
