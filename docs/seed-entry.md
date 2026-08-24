# Seed and passphrase entry

Getting a wallet into the appliance: generating one, typing one in, or scanning one back — and the
passphrase that turns any of them into a different wallet.

## The BIP39 list, measured

#16 found that a widely-repeated property of the EFF large wordlist was simply false, so the same
check was run here before anything was built on it:

- **2048 words, unique at exactly four characters** — 2048 distinct 4-prefixes, against 1,410 words
  still ambiguous at three. The four-character rule is real for BIP39.
- Charset is pure `a–z`; lengths run **3 to 8**; **103 words are three letters long**.
- **49 words are a prefix of another** (`add` / `addict` / `address`).

Checksum strength, which is load-bearing further down:

| words | entropy | checksum bits | a wrong phrase validates with p |
|---|---|---|---|
| 12 | 128 | 4 | **1/16** |
| 15 | 160 | 5 | 1/32 |
| 18 | 192 | 6 | 1/64 |
| 21 | 224 | 7 | 1/128 |
| 24 | 256 | 8 | 1/256 |

## Entering a word

**Type up to four characters; the word resolves as soon as the prefix is unique. Space or enter
commits the exact word when the buffer is itself a list word.**

The second clause is not a nicety. **49 words are prefixes of other words**, so a user typing `add` has
three live candidates; auto-resolution would have to guess or stall. The explicit commit is what makes
short words enterable at all.

Full-word typing keeps working for anyone who prefers it — the four-character rule is a shortcut, not a
mode. Numeric index entry (SeedSigner's approach) is rejected: it exists for devices with four buttons,
and this appliance has a keyboard.

> **Do not unify this with the export-password widget.** #16 established that the EFF large list is
> **not** prefix-unique — 5,502 of 7,776 words are still ambiguous at four characters. Same widget,
> different wordlist, different rule. The next person to read both will try to merge them.

## Word count is asked, not detected

**One screen, up front: 12 / 15 / 18 / 21 / 24.**

Detection is tempting — accept words and offer *done* whenever the checksum happens to validate — and
it fails badly at the short end. At 12 words **1 in 16 wrong phrases validates by chance**, so a user
with a 24-word seed who mistypes early could be handed a perfectly valid 12-word wallet that is not
theirs, with no error shown anywhere.

The user knows their word count. Asking costs one keystroke and removes a class of silent wrong-wallet.

Generation does not ask: always 24 (#8).

## An editable grid, not a wizard

**Numbered slots on one screen, freely navigable.**

The reason is that **a checksum failure names no word.** The appliance cannot know which slot is wrong,
so the user must be able to go to slot 17, change it, and retry — without retyping the sixteen they got
right. A wizard forces that retype, and the retype is where a *second* error gets introduced.

On failure the message says what is true and no more: **checksum failed — one or more words are
wrong**, with every slot still editable. No guess at which one, no "did you mean".

## Generation

24 words, always. Entropy comes from #8's mixer.

### Dice

**One optional screen on the generate path, offered before generation.** The wording is the decision,
not the placement: **"roll dice if you don't trust this machine's random number generator."** Never
"add more entropy", never a bar filling toward "secure".

That framing has a consequence for the screen: **a user who skips is shown no degraded state** — no
warning, no amber anything — because #8 settled that their guarantee is not degraded. Roll count and
bits contributed are displayed as they accumulate; the user stops when they like. No quota, no minimum,
because dice are additive.

The screen after generation shows facts, not a score — *system: 32 bytes · camera: 8 frames · dice: 0
rolls* — and **0 rolls renders identically to 99**.

### Read-back: all 24 words

**And the reason is not the obvious one.** The BIP39 checksum does not help at generation: the
appliance holds the correct words, and what can be wrong is **the paper**. The checksum only fires
later, on import from that paper — by which time the wallet may hold funds and the paper may be the
only copy.

**Read-back is the only check on the paper, and nothing else performs it.** So #16's argument applies
and applies harder: a partial check misses a single bad word most of the time, and here a single bad
word is the whole wallet.

Cost is 24 × 4 = **96 keystrokes**, the honest price of the only verification that exists. As in #16, a
failed read-back retries **the same words**, never freshly generated ones.

## The passphrase

**Masked by default, with a hold-to-reveal key, a live character count, and confirmation by master
fingerprint — never by typing it twice.**

#15 settled the no-second-copy rule. What this document settles is what the user may see.

**Hold-to-reveal is right despite putting the passphrase on screen.** Someone in the room is Tier 2 —
acknowledged, explicitly not defended — whereas a passphrase silently mistyped through the wrong keymap
is a total loss, which #12 called the appliance's worst failure mode. The character count is always
visible, because a doubled or dropped keystroke is the common error and counting is free.

Then the fingerprint, with #15's caveat surfaced rather than buried: **on a first-ever passphrase there
is nothing to compare against.** The appliance says so and tells the user to record it, instead of
showing a fingerprint that looks like a confirmation and is not.

## Three ways in, one way back out

**One wallet screen with three peer choices: generate, type words, scan encrypted QR.** They are peers
and should read as peers — burying the encrypted QR under an import submenu would hide the path #9 and
#16 spent two tickets making safe.

**Recovery words are re-showable on demand once a wallet is loaded**, behind an explicit *show recovery
words* action and never on the way to anything else.

This is the contested half and it should be allowed. It puts 24 words on screen mid-session, which is
real exposure — but the words are in RAM regardless (#15 concedes the copies are uncounted), so
refusing protects almost nothing, while a user who cannot check their paper against the appliance
either trusts a backup they never verified or writes down a second guess. That is the argument that
settled #16's re-showable password, and it does not come out differently here.
