# ADR-0015 — The network is a load parameter, chosen beside the passphrase

- **Status**: accepted
- **Date**: 2026-08-15
- **Decides**: [#34 — Network selection for a created or imported wallet](https://github.com/allisson/aobs/issues/34)

## Context

Support for mainnet and testnet/signet was a standing constraint from the start, but nothing ever
said how a wallet acquires its network. The restore path knew — bit0 of the backup header — and every
other path did not. Nothing infers it: a freshly generated seed carries no network, and neither does
a BIP-39 mnemonic.

The question is awkward because this spec has refused a user choice four times running — seed length,
passphrase strength, colour scheme, script type — each time on the same ground, that the choice
appears at the moment of least attention. A fifth control invites the reading that we were
inconsistent.

Two facts found while deciding, both of which narrow the problem:

- **The master fingerprint is identical on every network.** BIP-32 derives the master key with a
  single constant and the identifier is `HASH160` over a 33-byte compressed pubkey; the network lives
  only in the base58 version bytes, which the fingerprint is not taken over. So the safety net the
  passphrase decision leaned on **does not exist here**, and the network line stands alone.
  *[Read from the BIP-32 text, not measured — it carries an assertion in the suite.]*
- **Testnet and signet are one wallet.** Same coin type `1h`, same `tb` HRP, same base58 versions.
  There was never a three-way choice, which is why the backup header spends one bit.

## Decision

**The network is a load parameter, exactly like the BIP-39 passphrase: a two-state selector on the
wallet load screen, mainnet preselected, asked for created and typed-in seeds and merely stated for a
restore.**

**Why this is a legitimate choice when the other four were not.** Each refused choice asks the user
to adjudicate something about *the system* — entropy margin, passphrase quality, ambient contrast,
which BIP family an old wallet used — which they are not equipped to referee. *"Are you practising,
or is this real?"* is a question about **their intent**. They are the only entity in the room holding
the answer, and no expertise substitutes for it.

**Why the load screen, and not GRUB or the start menu.** This is structural rather than a preference.
The restore path must not be prompted, because the header already holds the answer and a prompt could
only manufacture the mismatch the bit exists to prevent. A control answered *before the device knows
which path the user is on* would therefore take a value the header then silently discards — a control
whose answer is thrown away, which is the silent-disagreement class removed everywhere else in this
spec. On the load screen, restore **states** where the other two paths **ask**, and no such moment
exists.

The precedent is the same mechanism rather than an analogy: in BIP-39 the passphrase is not an input
to mnemonic generation and enters at seed derivation; the network is not an input to generation
either and enters one step further down, at the derivation path. Both are load parameters, so this is
the passphrase screen taking its second parameter.

**Asking late costs nothing, because the seed is network-independent.** The words written on paper
during creation are a valid backup on either network, so a user who chooses at load has wasted no
work and restarts nothing. That is what removes the only real objection to the placement.

## Consequences

- **Mainnet is preselected and the pick is not forced.** A forced choice on a 95/5 split is a
  click-through trainer on the one screen where click-through is expensive.
- The state this creates deserves naming and then deflates: an inattentive rehearser lands on mainnet
  believing they are practising. **Signing requires coins, and a rehearser has none on mainnet** — the
  coordinator shows an empty xpub and there is nothing to sign. The default's failure is an empty
  wallet; a testnet default would instead put the *common* path into a `tpub` a coordinator rejects.
- **A wrong network is loud, unlike a wrong passphrase.** Different HRP, a `tpub`, network-scoped
  coordinators. Named cost: the stop lands on somebody else's error message rather than ours.
- **The refusal copy gains a third cause.** `scriptPubKey`s are network-agnostic bytes, so a testnet
  PSBT loaded as mainnet fails re-derivation with no distinguishing symptom and arrives as *"no input
  is ours"* — which already owes the passphrase and account 0. Because three causes in a list name
  nothing, **when every input's declared coin type disagrees with the loaded network the refusal says
  so outright.** This does not breach *re-derive, never trust*: the path selects the **copy** and
  never affects acceptance.
- **The network is stated in both directions, never encoded as an absence** — the same rule the
  passphrase-in-use bit carries, for the same reason: stating only one case leaves the mirrored
  silent failure alive.
- **No rehearsal livery.** Same chrome, same colour scheme, no reduced ceremony. A rehearsal has to
  look identical to the real thing or it is not a rehearsal, and a mode dressed as a toy teaches the
  user to click through the exact ceremony we want rehearsed.
- **A new verification obligation**: assert that one seed's master fingerprint is byte-identical
  across networks. The identity screen's only network signal rests on a claim read from a
  specification rather than measured, so the assertion is the alarm if it ever stops holding.

## Alternatives rejected

- **Mainnet only, testnet dropped from v1** — the answer that makes every downstream question vanish.
  It is a scope change against a standing constraint, and it deletes rehearsal on a product that
  imposes a 24-word retype, an 8-word type-back and an unlocalisable checksum failure. Meeting all of
  that for the first time with real money on the table is the wrong introduction, and rehearsal costs
  nothing.
- **A GRUB entry** — the worst-attention moment in the product (the user is booting, not yet deciding
  what they came to do), a value the restore header would discard, and entries already spent on the
  low-memory fallback.
- **A start-menu variant** — cross-products three self-disambiguating entries into six, and discards
  the user's answer on the restore path exactly as GRUB does.
- **A forced pick with no default** — trains dismissal on the screen where dismissal is most
  expensive.
- **A distinct visual treatment for testnet sessions** — self-defeating, per the consequence above.
