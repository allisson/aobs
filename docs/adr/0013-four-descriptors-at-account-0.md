# ADR-0013 — Four descriptors at account 0, exported as `ur:crypto-account`

- **Status**: accepted
- **Date**: 2026-08-15
- **Decides**: [#27 — Watch-only export: how public key material leaves the device](https://github.com/allisson/aobs/issues/27)

## Context

Surfaced while resolving the passphrase ticket, as a **hole in the map rather than a fog patch**:
aobs could create a 24-word wallet, but nothing let any public key material out. Without it no
coordinator can derive addresses or construct a PSBT, so **a freshly created wallet could never
receive funds or be spent from — the create path dead-ended.**

This decides more than a format. Receive-address verification had already deferred to it — *"which
accounts count as loaded follows whatever this settles"* — so what is settled here is also what the
rejection policy re-derives against and what the address search searches.

## Decision

**A single `ur:crypto-account` QR carrying output descriptors for all four BIP families at account
0**, on the identity screen and as the closing step of creation, with a text fallback behind it and
the master fingerprint always in view.

**Descriptors, not a bare xpub.** `wpkh([9c1f4e02/84h/0h/0h]xpub…)`. A bare xpub carries neither
script type nor origin path, so the user must tell the coordinator both by hand — and getting it
wrong does not fail, it produces *valid but wrong* addresses: money sent to a wallet this device will
never look at, with no error raised anywhere. That is the silent-failure class the seed-import and
passphrase decisions both spent themselves removing. BIP-380's checksum then catches a mis-scan for
free.

**All four families, because the alternative is an unrefereeable question.** *"Is your old wallet
BIP44 or BIP84?"* is exactly the choice this project has repeatedly refused to ask. The spec authors
agree: BCR-2023-019 exists to reduce "the burden on users to select the script type manually".

**`crypto-account` (311), not `account-descriptor` (40311)** — decided on coordinator source, not
docs. Sparrow accepts both; **Specter Desktop accepts `crypto-account` only**; Nunchuk is **left
unverified rather than assumed**. The 2020 type is the strict superset, exactly as UR2 was the strict
superset over BBQr, so emitting the newer type would silently drop Specter.

**Account 0 only.** A user who does not already know what a BIP44 account index is cannot judge it,
and one who does can keep their account-1 wallet on the device that made it.

## Consequences

- **The four accounts are now the definition of "ours"** — for change re-derivation, for the address
  search, and for the "no input is ours" refusal.
- **The security property does not weaken.** Acceptance still rests on re-deriving from our own key
  material and byte-comparing the `scriptPubKey`. What widens is *which of our own accounts count*,
  not what we trust: a foreign output still fails the comparison against all four.
- **Costs, named.** Four xpubs leave the device instead of one, each disclosing every address in its
  account, past and future, forever. The address search grows to 4 accounts × 2 branches × 1000
  indices = **8,000 derivations**, inheriting the obligation to be timed on target hardware.
- **The account-0 dead end is real:** someone whose existing wallet lives on account 1 or 3 can
  import their seed, watch aobs derive a wallet they do not recognise, and then have *every* PSBT
  refused as not ours. **Mitigated by copy, not by code — the "no input is ours" refusal must name
  account 0 as the assumption.**
- **Single-part, always.** Estimated ~460 B of CBOR → ~1,000 UR characters, one QR at ECC H near
  version 30. **Derived, not measured**, and on the release-gate list. **If four descriptors ever
  fail to fit one QR, the fix is narrowing what we export, never animating it.**
- **A text fallback screen** shows the same four account-level descriptors, so a coordinator that
  refuses our QR does not leave an air-gapped device with no channel. Specter accepts a pasted xpub
  and Sparrow accepts typed descriptors, so it is real rather than theoretical.
- **One factual sentence about privacy on the export screen, with no icon and no confirmation step.**
  It is a fact the user may not have, not a judgement they can act on differently, and the export is
  mandatory for the product to function at all — a gate would be a dismissal prompt in disguise.
- Riders folded in without argument: **no wallet name** in the export (a name is state); the
  **passphrase needs no special handling**, because it changes the seed and the exported xpubs
  already *are* its wallet; the identity screen stays reachable all session; and the network follows
  the loaded wallet.
- **Named cost: we ship a superseded encoding.** BCR-2023-019 exists because BCR-2020-015's schema
  had problems — though the ones it names are in the multisig `cosigner()` shapes we never emit.
  **Recorded revisit trigger: when Specter accepts `account-descriptor`, this flips.**

## Alternatives rejected

- **A bare xpub, or SLIP-132 (`zpub`/`ypub`)** — SLIP-132 encodes the script type in the prefix but
  is non-standard, Bitcoin Core rejects it, and coordinators disagree on it.
- **One account, chosen by the user at load** — the unrefereeable question above.
- **`ur:crypto-output`** — Nunchuk accepts it and Specter does not; it also carries one descriptor,
  not four.
- **Animating the export if it does not fit** — narrow what we export instead.
- **Address origination** (index in, address and QR out) — considered under the address-verification
  ticket and cut, because **the bypass does not bypass anything**: an originated address still
  reaches the payer through the user's online machine.
