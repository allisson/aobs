# The export password

How eight EFF words get out of the appliance and back in without being mistranscribed.

[#9](https://github.com/allisson/aobs/issues/9) settled that the Encrypted wallet QR is protected by
**eight EFF large-wordlist words, ~103 bits** — and that entropy is worthless if the words do not
survive the trip through a human's handwriting. This is where a backup silently becomes unreadable,
and the failure surfaces months later, when the QR is the only copy of a wallet.

## The wordlist, measured

Computed over the actual EFF large list rather than assumed:

- **7,776 words**, log₂(7776) = 12.925 bits each, **8 words = 103.4 bits** — confirming #9's figure.
- Word lengths **3 to 9** characters.
- **No word is a prefix of another.**
- Charset is **not** plain `a–z`: four words contain a hyphen — `drop-down`, `felt-tip`, `t-shirt`,
  `yo-yo`.

### The list is not prefix-unique, and the belief that it is was wrong

| prefix length | distinct prefixes | words still ambiguous |
|---|---|---|
| 3 | 1,375 | 7,297 |
| **4** | 3,748 | **5,502** |
| 5 | 5,823 | 3,165 |
| 7 | 7,559 | 417 |
| 8 | 7,746 | 60 |
| 9 | 7,776 | 0 |

**Uniqueness arrives only at the full word.** The "unique at a few characters" property belongs to
EFF's *short* lists, not this one — and to BIP39, which *is* unique at four characters.

That asymmetry matters and must not be forgotten when the mnemonic entry flow is built: **BIP39 entry
may use a four-character prefix; export-password entry may not.**

## The wordlist stays

Entry is **full-word, with autocomplete that narrows as you type and accepts only an exact match.**
The prefix shortcut is dropped; the list is not.

**Switching to the BIP39 wordlist was considered and rejected.** It is genuinely tempting — unique at
four characters, pure `a–z`, and the appliance already ships the list and a word-entry widget for the
mnemonic, so it would mean one wordlist, one autocomplete, one set of tests. It loses to a safety
argument: **a user must never confuse their export password with a seed phrase.** Words drawn from the
same vocabulary as the mnemonic invite exactly that — writing the export password down believing it is
the backup, or trying to restore a wallet from it. A visibly different vocabulary is doing real work.

The cost of keeping EFF is that typing is slower, and it is paid once per export.

### The four hyphenated words are kept

Pruning them costs almost nothing in entropy (103.39 vs 103.40 bits) and would turn *the EFF large
wordlist* into **a custom list that must then be published byte-exactly and matched forever by every
implementation**. #9's central lesson from Krux is precisely that failure mode: a derived, subtly
different encoding produced backups that could not be decrypted. Unmodified, anyone can fetch the list
from EFF and check us.

The hyphen is handled explicitly instead. The entry widget accepts `-` as an ordinary character, and
the display renders a hyphenated word so it cannot be read as a line break — **that is the real
transcription hazard here, not the typing.**

## Display

**The password and the QR are never on screen together.** One screen holds the ciphertext, another
holds the password. Together they are one photograph, and that is the whole attack. The QR screen
states plainly that the password is not on it.

The eight words are shown **numbered 1–8, one per line, in a fixed-width column, on a screen with
nothing else on it.**

**Re-showable on demand for the rest of the session.** Show-once is a security reflex and it is wrong
here: the password is in RAM either way, so refusing to redisplay protects nothing — while a user who
looks away mid-transcription and cannot get the words back either abandons the export or writes down a
guess. That is the exact failure this document exists to prevent.

## Read-back before the export completes

**All eight words, typed back, and not a subset.**

This is the only moment a transcription error is cheap to catch. After it, the error surfaces months
later, when the QR is the only copy of a wallet.

Subset read-back — the SeedSigner-style "type words 3, 5 and 7" — is the obvious economy and it is
wrong here. It leaves five words unverified, and the failure mode is **exactly one mistranscribed
word**: sampling 3 of 8 misses that error 62% of the time.

Typing eight words is tedious, and that is the point. **If you cannot type them now, you cannot type
them in two years**, and finding out now costs a minute.

A failed read-back retries **the same password**, not a fresh one — a new password would silently
invalidate whatever the user has already written down.

## No user-chosen password, enforced by absence

**The export function takes no password parameter.** The generator is its only source. The enforcement
is the absence of a feature, which is the only kind that cannot be talked around later by someone
adding "advanced options".

Backed by a test in #13's suite: the export interface exposes no password argument, so adding one
fails CI. #9 was explicit that a user-chosen password would move the entire security of the export
onto a KDF it had just declared not load-bearing.

## What the user is told

Write the words on paper; store the paper apart from the QR. **The wording branches on whether a
passphrase is set, because the truth genuinely differs**, and the appliance knows which case it is in.

- **Passphrase set.** The QR plus the eight words reconstruct your BIP39 *words*, not your wallet. The
  passphrase is in neither and nothing is spendable without it. This is #9's second factor working as
  designed.
- **No passphrase.** The QR plus the eight words **are** the wallet. Anyone holding both can spend, and
  keeping them apart is the only thing protecting the funds.

**Printing the first message to a user in the second situation is a lie that gets people robbed.**

## Failure states on import

- **A word not in the list** is rejected at entry, in its own slot, before anything is decrypted.
  Nothing proceeds on a word the appliance cannot resolve.
- **A wrong word count is impossible** — there are eight fixed slots.
- **Eight valid words that are the wrong password** reach the AEAD and fail its tag. Per #9 the
  appliance says *wrong password or tampering*, without claiming which, because the tag cannot tell
  them apart and a verifier that could would hand an offline attacker an oracle.
- **A foreign or corrupt QR** is distinguished earlier and separately, by #9's magic-and-version
  framing — not by cryptography, and the message is different.
