# ADR-0014 — The BIP39 passphrase is accepted, never generated, and shown in clear

- **Status**: accepted
- **Date**: 2026-08-15
- **Decides**: [#20 — BIP39 passphrase: generation policy and entry](https://github.com/allisson/aobs/issues/20)

## Context

The backup password is 8 EFF words that aobs generates and the user cannot choose (ADR-0007). The
obvious move is to apply the same reasoning to the BIP39 passphrase. It does not transfer, and the
reason is precise.

**The backup password protects a ciphertext, so a wrong one fails loudly** — Poly1305 rejects and the
screen says so. That loud failure is what makes it safe to hand a user 103 unchecksummed bits. **A
BIP39 passphrase has no checksum, no authentication tag and no ciphertext: a wrong one derives a
different, valid, empty wallet**, and nothing in the protocol can say otherwise. Generating one would
stack a silent failure mode on top of the top loss mode.

A reframe collapsed half the ticket. It asked whether a passphrase is offered "at creation, at load,
or both" — a false split. In BIP39 the passphrase is not an input to mnemonic generation at all; the
mnemonic comes from entropy and the passphrase enters at seed derivation. **There is exactly one
moment — wallet load — and a freshly generated mnemonic arrives there indistinguishable from an
imported one.**

## Decision

**aobs never generates a BIP39 passphrase. It accepts one, in clear text, printable ASCII only, at a
single always-present prompt on wallet load, and makes no judgement about it.**

**No strength meter, no minimum, no lecture.** A passphrase is **strictly additive** over a 24-word
mnemonic: if the mnemonic is safe the passphrase is irrelevant, and if the mnemonic is stolen the
passphrase is the only thing left. It is *never worse than none* — the same unconditional-guarantee
shape as the entropy XOR. A signer with no rate limiting cannot compensate for a weak one anyway, and
a meter would imply it could. One line of copy replaces the strength UI: **this is never checked and
never recoverable.**

**Clear text, always, no toggle.** Masking defends against a shoulder-surfer — a present adversary
the threat model **explicitly declines to defend**. It would therefore sell a defence we have already
declined and charge for it in the one currency that matters here: an invisible typo becomes a
different wallet, discovered years later. **Masked-with-a-reveal-toggle is the worst of the three**,
because it makes clear text an opt-in that a hurrying user skips on precisely the entry that most
needs checking.

**Never trim.** `"hunter2 "` and `"hunter2"` are different wallets. BIP39 defines no trimming rule,
and trimming ourselves would silently disagree with every other implementation on the same input.

## Consequences

- **No double entry.** Retyping is the mitigation for a *masked* field — you retype because you
  cannot read. Clear text removes the need, and double entry would not catch the failure worth
  fearing anyway: a user who types a trailing space twice has confirmed nothing. **The mitigation
  that works is rendering**: fixed-width, spaces drawn as a visible mark, explicit start and end
  delimiters, character count shown.
- **Encoding splits across the crate boundary.** Core is full BIP39 — arbitrary UTF-8 in, **NFKD**
  before PBKDF2. The shell accepts **printable ASCII only**, because we render the passphrase so the
  user can verify it and a font with CJK coverage is ~100 MiB against a 21 MiB stack; **drawing tofu
  boxes is worse than refusing.** **Named cost: a user whose existing passphrase contains non-ASCII
  cannot enter it, and aobs cannot sign for that wallet.** It is the shell's limitation, so lifting it
  later is a shell change and a font, not a crypto change.
- **A fixed 128-byte buffer**, because growable secret types are forbidden. The cap is structural,
  not a preference, and sits above every mainstream wallet's own.
- **One prompt, empty by default; empty *is* no passphrase.** The rejected alternative is a menu
  branch ("load wallet" / "load wallet with passphrase") — a branch is where people take the wrong
  one, and it makes the passphrase feel like a mode rather than a field. The confirm control states
  which of the two is happening: **"Continue without passphrase"** or **"Use this passphrase"**, so
  an accidental empty confirm cannot pass as a deliberate one.
- **Detecting a wrong passphrase has no cryptographic answer**, so three things are done instead: a
  **wallet identity screen after every load** (fingerprint, network, script type) so comparison is a
  habit rather than a passphrase-specific ritual; the observation that **the failure is already loud
  where it costs money**, since a wrong passphrase means no input is ours and the signing path
  refuses; and a **copy requirement** that the refusal names the passphrase as the likely cause.
  The 4-byte fingerprint is adequate *here* despite being a hint-only value for derivation — there it
  faces an attacker choosing collisions, here it faces a typo, which cannot collide.
- **"A passphrase is in use" is stated explicitly** on the identity screen and the backup export
  screen, and carried into the review header — the fingerprint is technically a complete indicator,
  but only to a user who compares it, and the users who most need the reminder are the ones who will
  not.
- **Japanese BIP39 vectors are mandatory in the suite.** `㍍` (U+334D) decomposes only under NFKD and
  is untouched by NFD, so they are the only vectors that catch an implementation reaching for the
  wrong normalization form.
- **The passphrase cannot change mid-session** (ADR-0010).
- **This ticket surfaced the watch-only export hole** that became ADR-0013.

## Alternatives rejected

- **Generate the passphrase, as we do the backup password** — hands the user an unchecksummed
  high-entropy secret whose only failure mode is silent.
- **Mask it**, or mask with a reveal toggle — sells a declined defence and charges for it in typos.
- **A strength meter or minimum length** — implies a compensation the device cannot provide.
- **Trim leading and trailing whitespace** — silently disagrees with every other implementation.
- **Two prompts, one per load path** — the false split; there is only one moment.
