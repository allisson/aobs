# CONTEXT — the vocabulary of aobs

Terms as this project uses them. Vocabulary only: what a word *means* here, not how the thing is
built. Implementation lives in `docs/specs/`, reasoning in `docs/adr/` and on the map's tickets.

Where a word has a general meaning and a narrower one here, the narrow one wins. Using these words
loosely is how a settled decision gets reopened by accident.

---

## The product

**aobs** — *Amnesic Offline Bitcoin Signer.* The whole thing: the Rust binary and the bootable image
it ships inside.

**The appliance** — aobs as the user meets it: a machine that boots into one program and does one
job. Deliberately not "the app", which implies something installed alongside other things.

**The image / the ISO** — `bitcoin-signer-amd64.iso`, the distributed artifact.

**Session** — one boot. It begins at power-on and ends at shutdown, and it holds at most one wallet.
"End the session" and "shut down" are the same act; there is no logging out of a session and no
returning to its start.

**Amnesic** — nothing survives a session. No config file, no wallet database, no history, no cache,
no settings. A property of the product, not a mode it can be in.

**Air-gapped by construction** — the machine has no link layer to any physical interface, because the
image ships no drivers for one. Distinct from *configured offline*, which is a policy anyone can
undo.

## The two halves

**Core** (`aobs-core`) — everything that decides anything, as pure functions from data to a decision.
Touches no hardware.

**The shell** (`aobs`) — the binary around core: drawing, keyboard, camera, the one syscall. **The
shell marshals; it holds no decision about money and branches on no validation outcome.** "That
belongs in the shell" and "that belongs in core" are arguments about which of those two sentences a
piece of code satisfies.

**Seam** — a place where core and the shell meet. Every seam here is *data* — a string, an array of
bytes, a typed model — never an interface with one implementation.

**Model** — a typed value core hands the shell to render: the review model, the export model, a
warning variant. A model is never a formatted string, because a string would put the judgement in the
shell.

## Trust and refusal

**Refusal** — a decision that a payload will not be acted on, taken before any screen showing it is
drawn. A refusal names its reason, carries a stable code, and offers **only discard**.

**Warning (advisory)** — a statement on the review screen that never blocks. **A warning is only
legitimate when the user knows something we don't.** Exactly one exists in v1.

**Failing to decode** — bytes that never became a payload at all. Not a refusal: it is overwhelmingly
a bad scan, and it returns to scanning.

**Re-derivation** — deriving a key from our own seed at a claimed path, building the `scriptPubKey`
for the declared script type, and **byte-comparing** it against the one actually present. The
compare is the authority; the claim only nominates a candidate.

**Assertion** — anything the PSBT says about itself. Derivation paths and fingerprints are assertions
by the coordinator, to be proven, never facts.

**Hint** — a value used to narrow a search but never to authorise. The 4-byte master fingerprint is a
hint, always.

**Ours** — belonging to the loaded wallet, meaning: derived from this seed on one of the four
accounts, proven by byte-compare. An input or output is *ours* or it is not; there is no probable.

**Silent failure** — an error that produces a valid-looking result and reports nothing: a wrong
passphrase yielding a working empty wallet, a mis-typed final word yielding somebody else's phrase, a
bare xpub yielding valid but wrong addresses. **Removing silent failures is the single most repeated
motive in this project's decisions.**

**Loud failure** — an error the user meets immediately and unambiguously. A wrong backup password is
loud; that is what makes the backup design safe.

## Keys and wallets

**Wallet** — a seed plus a passphrase (possibly empty) plus a network. Changing the passphrase makes
a different wallet, not a variant of the same one.

**The four accounts** — BIP44, BIP49, BIP84 and BIP86 key-path, all at **account 0**, on the loaded
network. They are the definition of *ours*.

**Branch** — the second-to-last derivation element: `0` receive, `1` change. Both branches count as
ours.

**The mnemonic / the phrase / the words** — the BIP39 sentence that *is* the wallet. Generated at 24
words; imported at any of 12/15/18/21/24.

**The passphrase** — the BIP39 passphrase. Accepted, never generated. Empty *is* no passphrase.

**Fingerprint** — the 4-byte master key fingerprint. A human sanity check against confusion, never a
defence against an attacker.

**Watch-only export** — the four output descriptors leaving the device so a coordinator can derive
addresses and build PSBTs. Public material only.

**Descriptor** — an output descriptor carrying script type, origin path and xpub together, so the
coordinator has to be told nothing separately.

## Backup

**The backup / the backup artifact** — the encrypted seed QR. It is a *secondary* backup, justified
solely by storage the user does not fully trust. **It is not "the backup" in the sense of the paper
mnemonic**, which is the primary one; when both are in play, say which.

**The 8 words** — the device-generated EFF password for the backup artifact. As critical as the
mnemonic, and never the same kind of thing as the mnemonic: a different wordlist, deliberately.

**Type-back** — re-entering generated words from the user's own paper, with the words off screen, to
prove the transcription is correct. Used for the 24-word mnemonic at creation and for the 8 words at
export.

**Retype** — the same instrument as a type-back; the word used for the mnemonic confirmation
specifically.

**The passphrase-in-use bit** — the header flag saying a BIP39 passphrase was in play when the backup
was made. It exists to make a restore say so, in both directions.

## Entry

**Prefix entry** — typing the beginning of a BIP39 word and committing with a space. **Nothing is
auto-accepted**, and a keystroke that could not begin any word **does not land**.

**Slot** — one word position in the fixed grid. Errors are named *by position* wherever the device
knows the answer.

**Commit** — settling the buffer into a slot.

**Rejection by position** — naming which word is wrong, possible only where we know the intended
answer (a retype), impossible for an imported phrase, where the checksum can only fail globally.

**Nothing is masked** — a standing rule. Neither the mnemonic, nor the passphrase, nor the 8 words.
Masking sells a defence against a present adversary the threat model declines.

## Entropy

**`csprng_32`** — the 32 bytes from the kernel CSPRNG, passed into core as a parameter.

**Supplement** — the hash of optional user and camera entropy.

**Mixing** — combining the supplement with `csprng_32` by **XOR**, so the result is never worse than
the CSPRNG alone, unconditionally.

**Replacement mode** — a design where user entropy *is* the seed rather than an addition to it. Other
devices offer one; aobs does not, and the word exists here mainly to name what we refuse.

## Transport

**The QR channel** — the only data channel, both directions. Everything crossing it is hostile input.

**Payload class** — what kind of thing a given screen will accept: a PSBT, an address, a backup. **A
screen is never handed a payload it did not ask for.**

**Part** — one frame of a multi-part payload. **Stream** — the sequence of parts belonging to one
payload, identified by its declared length and checksum.

**Rateless / fountain** — the property that a looping sender generates *fresh* parts rather than
cycling a fixed set. It is why an outbound progress counter would be a lie.

**Single-part** — a payload that fits one symbol and carries no sequence component. For two of the
three inbound classes it is a rule, not an observation, and it is what keeps those paths out of the
fountain decoder entirely.

**Clamp / bound** — a limit enforced at our call site *before* a third-party parser sees a value.
`seqLen` bounds the claim; the total-parts cap bounds the work.

## Screens

**The review panel** — the single non-scrolling screen carrying the whole transaction. The product
exists for it.

**The per-address screen** — one full-width screen per payment address, walked before a signature is
produced, so the destination was provably alone on screen at the moment of approval.

**The gate** — the confirm action itself: hold to sign, single press to refuse. **Byte-identical with
and without a warning.**

**The identity screen** — shown after every load and reachable all session: fingerprint, network,
script type, whether a passphrase is in use. The hub the other actions hang off.

**The scanning screen** — one component, three configurations, with a live greyscale preview of
exactly what the decoder sees.

**Chrome** — the persistent frame around a screen's content. It never vanishes, including where
secret material is shown.

**Degraded but useful** — the state of the appliance with no camera: actions that need a scan are
**visibly unavailable with a stated reason**, and everything else works. Distinct from *broken*.

## Verification and release

**Provenance gate** — a check that runs against the **shipped artifact**, proving the entropy path
resolves to the intended implementation. It exists because a source-only test is the test that passed
for five years while Coldcard shipped a software PRNG.

**Owed measurement** — a number the spec currently carries as *derived* rather than measured, with a
named fallback. Owed measurements block the release gate, never implementation.

**Release gate** — the set of checks and measurements a build must pass before it is published.

**The worst-screen rule** — design for the worst panel the appliance will ever run on, not the best.
It decided the colour scheme and it applies to every legibility question after it.

**Theatre** — a mechanism that looks like a security control and cannot be one against the attacker
it appears to address. Self-reported provenance is theatre; so is a lockout on an amnesic device. The
project's habit is to name theatre rather than ship it quietly.
