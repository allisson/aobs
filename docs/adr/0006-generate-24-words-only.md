# ADR-0006 — Generate 24-word seeds only, and never offer the choice

- **Status**: accepted
- **Date**: 2026-08-15
- **Decides**: [#16 — Seed length: 12 or 24 words, and is it the user's choice?](https://github.com/allisson/aobs/issues/16)

## Context

This was never decided while the rest of the map assumed it. The backup-crypto ticket assumed 24
words in passing when sizing the ciphertext; the entropy policy specified a truncation to 16 bytes
for the 128-bit case without saying whether that case exists.

**The case for 12 is real and is recorded so it is not rediscovered later as an oversight.**
secp256k1 provides roughly 128-bit security regardless of seed length — Pollard rho on a 256-bit
group — so 256 bits of seed entropy yields a key no harder to attack than one from 128 bits. Against
that, mis-transcription is the dominant loss mode, one that surfaces years later at recovery, and it
bites harder here than on a dedicated device: aobs has no PIN, no secure element, no rate limiting
and no wipe-on-failure, so **the entire security of a wallet reduces to the entropy of the seed and
the physical security of the user's paper backup.** Twenty-four words is double the transcription
surface protecting a wallet whose paper backup *is* the wallet.

## Decision

**aobs generates 24-word seeds only. Import accepts all five BIP39 lengths — 12, 15, 18, 21, 24.
Seed length is not a user-facing choice in either direction.**

Three reasons decide it against the above:

1. 256 bits of seed entropy retains ~128-bit resistance **under Grover** against an address whose
   public key has never been revealed, where 128 bits would retain only ~64.
2. It matches the ecosystem default that users of Coldcard, Passport and Jade will compare against.
   A 12-word default invites a "less secure" reading that costs support burden and trust on a device
   with no brand to lean on.
3. A seed generated once and kept for a decade is the wrong place to spend a security margin to save
   transcription effort that happens twice.

**No choice is offered at creation.** Presenting 12-versus-24 would imply a security judgement the
user is not equipped to referee, on the screen where they are least equipped to referee it. A user
who wants a different length generates it elsewhere and imports.

**Import takes all five lengths** because the backup format is `35 + entropy_len` and therefore
already length-generic; refusing 15 or 21 words would strand a user holding a mnemonic the standard
permits, purely because our validator's list was written from the common cases.

## Consequences

- **Accepted cost, stated plainly:** the transcription surface is doubled on the failure mode most
  likely to lose funds. That raises the stakes on the creation and confirmation screens rather than
  changing any settled backup policy — and it is exactly why the confirmation became a **full 24-word
  retype from paper**, which detects 100% of single-word errors where a 4-position sample detects
  17% and a tick detects 0%.
- **The truncation branch disappears from generation.** `entropy = csprng_32 XOR supplement` is used
  whole at 32 bytes, always. The entropy known-answer vectors lose their "16-byte truncation" case.
- **The backup's entropy-length set widens** from `{16, 24, 32}` to `{16, 20, 24, 28, 32}`, so the
  restore-side exact-length check admits `{51, 55, 59, 63, 67}` bytes. Generated wallets always
  produce the 67-byte ciphertext, which remains a single-part QR.
- It is the first of several decisions that refuse to hand the user a choice at the moment of least
  attention — later repeated for the script type, the account index, the network on restore, and the
  colour scheme.

## Alternatives rejected

- **Generate 12** — cheaper to transcribe, and defensible on secp256k1's ceiling alone, but loses the
  Grover margin and the ecosystem-default comparison.
- **Offer the choice** — asks the user to referee a security judgement they cannot, and forces every
  downstream screen to handle both.
- **Refuse 15 and 21 on import** — strands users holding standard mnemonics for no reason.
