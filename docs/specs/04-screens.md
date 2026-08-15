# 04 — Screens

The shell. It draws, it reads the keyboard, it runs the camera, and **it decides nothing about money
and branches on no validation outcome.**

Sources: [#9](https://github.com/allisson/aobs/issues/9),
[#17](https://github.com/allisson/aobs/issues/17),
[#18](https://github.com/allisson/aobs/issues/18),
[#19](https://github.com/allisson/aobs/issues/19),
[#20](https://github.com/allisson/aobs/issues/20),
[#21](https://github.com/allisson/aobs/issues/21),
[#22](https://github.com/allisson/aobs/issues/22),
[#25](https://github.com/allisson/aobs/issues/25),
[#26](https://github.com/allisson/aobs/issues/26),
[#27](https://github.com/allisson/aobs/issues/27),
[#30](https://github.com/allisson/aobs/issues/30),
[#31](https://github.com/allisson/aobs/issues/31).

Reference artifacts, walkable: `docs/prototypes/transaction-review.html`,
`docs/prototypes/seed-import.html`, `docs/prototypes/wallet-creation.html`,
`docs/prototypes/light-dark.html`. The prototypes are the *structure*; the light scheme supersedes
the review prototype's dark rendering.

## 0. The visual system

**Light, one scheme throughout, no user toggle. No theme switch exists in the code** — not a setting
defaulted off, but absent.

Light-on-dark text blooms, and halation is precisely what makes `q`/`g`, `5`/`s`, `2`/`z` and `u`/`v`
converge in a 42-character address at 17–22 px monospace. Two reasons are specific to this appliance
rather than general taste: **we are choosing for the worst screen we will ever run on**, since aobs
boots on any UEFI machine with any panel; and in a bright room a dark screen becomes a mirror, so the
user compares an address through their own reflection.

**Named cost:** a genuinely dark room gets a bright screen. Unpleasant, not a correctness problem.

Starting palette, from the prototype — a starting point, not a mandate:

```
--ground   #eef1f5     --ink       #0f151c
--panel    #ffffff     --ink-mid   #414d5c
                       --ink-dim   #66717f
--ok  --warn  --crit  --focus      darkened from their dark-scheme values
                                   to hold contrast against a white panel
```

**Address rendering, everywhere it appears:** 4-character groups, monospace, both ends emphasised —
the emphasis carried by weight and ink, not luminance. **Payment addresses are never truncated.**
Change and input addresses may be, because they are verified or ours.

**Keyboard only.** The software renderer draws no mouse cursor and the appliance has no pointer; the
UI is fully keyboard-navigable by design, not by retrofit. Escape cancels wherever a cancel exists.

**Chrome does not vanish for any screen**, including the ones showing secret material — a frame that
disappears for a single screen is a surprise on the screen demanding the most attention. There is no
"seed on screen" chip: a warning is legitimate only when the device knows something the user does
not, and that one announces what they are already looking at.

## 1. Start menu

A **flat three-entry menu, labelled by the input the user is holding**:

```
create a new wallet
type a seed phrase
scan an encrypted backup
```

Labelling by artifact fails here: the encrypted QR is a re-encoding of the mnemonic, so "backup"
names both artifacts and "restore" names both actions. What the user is *holding* — paper with words,
or a QR — is self-disambiguating. A "load existing" submenu was rejected: it buys a step and hides
the rarer path.

With no camera, the third entry is **visibly unavailable with its reason stated**, not hidden.

This is a boot-time menu, not a mode switch. One wallet per boot; there is no way back to it.

## 2. Create — gathering entropy, with the dice on it

**One screen, doing both jobs.** The rolls are needed *before* the mnemonic exists, which is exactly
when `getrandom(2)` is still blocking — so the dead time carries the optional feature at the cost of
no extra step, and the hang problem dies for free: **a screen with something to do on it cannot read
as a hang.**

- Free D6 entry, no minimum, **roll count displayed and nothing else**.
- The mandated line of copy, on this screen where it will actually be read:
  > *Your rolls are combined with the system random number generator. They can only add randomness,
  > never remove it.*
- **The screen must not auto-advance.** Entropy readiness only *unlocks* Continue, because the user
  may still be rolling.
- The wait is **indeterminate, with elapsed seconds and no percentage**. `getrandom(2)` emits no
  progress signal, so a bar would report a number the system cannot know — and a fabricated bar
  stalling near the end reads *more* like a hang than a spinner does.
- Burying dice behind an "advanced" detour was rejected: a feature nobody can find is not a feature,
  and burying it also buries the one line of copy that does the work.

A camera frame is captured here for the mix, silently, and skipped silently when no camera is
present.

## 3. Create — the 24 words

**Two column-major columns of 12: 1–12 left, 13–24 right, all visible at once.**

**Column-major fill is load-bearing and easy to get wrong** — a row-flow grid renders 1,2 / 3,4 and
inverts the entire argument. The argument is the paper: *a column of 12 is the shape of the card or
steel plate being copied onto*, so screen and destination share a geometry and the copy becomes
positional rather than sequential.

Pages were rejected because a page turn sits exactly where a place gets lost during transcription,
and because it makes cross-checking impossible when half the phrase is never on screen with the
other half. A 4×6 grid fits but has no natural reading order.

An instructional banner above the words stays; it carries information.

*Owed: that two columns of 12 fit a 1280×800 panel at the settled type size. Measured in a 16:10
browser frame, not on hardware.*

## 4. Create — the confirmation

**A full 24-word retype, typed from paper, with the phrase off screen**, using the entry component
from §6.

The arithmetic settles it. Against a single mis-copied word — the top loss mode, the one that
surfaces years later — ticking *"written down"* detects **0%**, and a 4-position sample detects
**4/24 ≈ 17%**. A check that misses five errors in six is not a check, it is the ceremony of one. The
full retype detects **100%**, costs nothing to build, and buys something neither alternative can: the
user **rehearses the restore** while the paper is still fresh enough to correct.

**Named cost:** the most laborious minute in the product. That cost was already accepted when
generation was fixed at 24 words; this is where it lands.

**The reframe that decides the failure path: this is not a gate proving the phrase was written down,
it is an instrument for making the paper correct — so a failure is the feature working.**

- A wrong word is rejected **immediately and by position**. Unlike import, we know the answer, and
  naming the position *is* the repair.
- It returns to the phrase with that position marked, and **destroys nothing**.
- **`restart` was rejected as actively harmful**: it voids everything already written down and
  re-asks the same transcription of someone who has just proved they can slip, teaching that care is
  punished.
- **Committed words are echoed** during the retype. Nothing in this product is masked, and the echo
  makes an off-by-one visible as a *shift* rather than as a mystery rejection at word 20. The
  mnemonic itself is never re-shown, so the input still comes from paper.

## 5. Wallet load — passphrase and network

**One screen, always present, on every load path — created, imported or restored.** It carries the
two parameters that enter at derivation rather than at generation: the passphrase and the network.

**The network sits above the passphrase.** The confirm control's label is a function of whether the
passphrase field is empty (§5.1), so the passphrase must be the last thing touched before confirming;
a two-state selector below it would be reached after the label had already settled.

### 5.1 Passphrase

**Empty by default.**

The rejected alternative is a menu branch ("load wallet" / "load wallet with passphrase"). A branch
is where people take the wrong one, and it makes the passphrase feel like a mode rather than a field.

- **Clear text, always, no toggle.** Masking defends against a shoulder-surfer — a present adversary
  the map explicitly declines to defend. It would therefore sell a defence we have already declined,
  and charge for it in the one currency that matters: an invisible typo becomes a different wallet,
  discovered years later. Masked-with-a-reveal-toggle is the worst of the three, since it makes clear
  text an opt-in that a hurrying user skips.
- **Rendering is the mitigation, not retyping:** fixed-width, **spaces drawn as a visible mark**,
  explicit start and end delimiters, character count shown. Never trimmed.
- One line of copy replaces the strength UI: **this is never checked and never recoverable.**
- The confirm control states which of the two is happening: **"Continue without passphrase"** when
  the field is empty, **"Use this passphrase"** when it is not. An accidental empty confirm cannot
  pass as a deliberate one.
- Printable ASCII only; a rejected keystroke says so.

### 5.2 Network

**A two-state selector — mainnet or testnet/signet — with mainnet preselected.** Two states, not
three: nothing in a key, an address or a descriptor distinguishes testnet from signet
(`02-core.md` §6).

- **Created and typed-in seeds are asked. The restore path is not** — the header's bit0 already
  holds the answer, so this screen **states** the network for a restore instead of offering it. That
  asymmetry is the reason the control lives here rather than in GRUB or on the start menu: a control
  answered before the device knows the path would set a value the header then discards.
- **No forced pick.** The user can confirm straight through and get mainnet.
- Copy states what the selection is for and nothing else: testnet/signet is for rehearsal, and coins
  on it are not real. No advice, no confirmation step for choosing testnet.
- **Nothing else about the session changes.** Same chrome, same colour scheme, no rehearsal livery —
  a rehearsal has to look identical to the real thing or it is not a rehearsal, and a mode dressed as
  a toy would teach the user to click through the exact ceremony we want rehearsed.

The network is shown in the chrome and on the identity screen in **both** directions and is never
encoded as an absence. The master fingerprint is identical on both networks (`02-core.md` §6), so
unlike a passphrase typo there is no second signal — this line is the only one.

## 6. Import — word-by-word seed entry

A fixed 24-slot grid on one screen, driven by core's reducer. All six behaviours are core's (see
`02-core.md` §4); the shell owns only the keyboard and the drawing.

On screen: the matches for the current prefix, the single remaining word ghosted inline, and the
committed words. **The screen names English before the user starts.**

Off-list keystroke → the key does not land, and the screen names the key that was ignored.
Failed checksum → the words stay, and the screen states plainly that the check covers the phrase as a
whole and **cannot** say which word is wrong. Discard is available at every moment and, per the
session model, discard is a restart.

## 7. The identity screen

Shown after **every** load, and reachable all session. It is the hub.

Always in view: **master fingerprint, network, script type**, and whether a **passphrase is in use**.

The fingerprint is what a user with an existing wallet compares against their coordinator. It is
adequate *here* despite being a hint-only value for derivation: there it faces an attacker choosing
collisions, here it faces a typo, which cannot collide. For a freshly created wallet there is nothing
to compare against and no screen can invent one.

**The fingerprint says nothing about the network** — it is identical on both (`02-core.md` §6). It
catches a passphrase typo and cannot catch a network mistake, so the network line stands alone and
its copy carries that weight by itself.

Actions:

| Action | Placement |
|---|---|
| **Watch-only export** (§8) | Primary, permanently available, and the closing step of creation. |
| **Sign a transaction** (§11) | Primary. Greyed with a stated reason when no camera. |
| **Verify a receive address** (§12) | Primary. Greyed with a stated reason when no camera. |
| **Re-display the most recently signed transaction** | Appears once a transaction has been signed this session. One slot, overwritten by each new signature — see `02-core.md` §12. |
| **Export an encrypted backup** (§9) | **Secondary.** Its position is forced, not chosen: the passphrase-in-use bit rides in the AAD, so the backup cannot exist before the passphrase is known. |
| **Restart / shut down** (§13) | Always. |

## 8. Watch-only export

**A single `ur:crypto-account` QR carrying output descriptors for all four BIP families at account 0**
— `wpkh([9c1f4e02/84h/0h/0h]xpub…)` and its three siblings, not a bare xpub.

A bare xpub carries neither script type nor origin path, so the user must tell the coordinator both
by hand — and getting it wrong does not fail, it produces *valid but wrong* addresses: money sent to
a wallet this device will never look at, with no error raised anywhere. A descriptor also carries
BIP-380's checksum, so a mis-scan is caught by the coordinator for free.

On screen with the QR: **the master fingerprint**, so the artifact can be confirmed by eye, and one
factual sentence about privacy — an account xpub reveals every address in that account, past and
future, to whoever holds it, and this export carries four. **No icon, no confirmation step**: it is a
fact the user may not have, not a judgement they can act on differently, and the export is mandatory
for the product to function at all. A gate would be a dismissal prompt in disguise.

**A second screen shows the same four account-level descriptors as text**, so a coordinator that
refuses our QR does not leave an air-gapped device with no channel at all. Specter accepts a pasted
xpub and Sparrow accepts typed descriptors, so the fallback is real rather than theoretical. It shows
exactly what the QR carries — account level, no branch specifiers — so the two paths cannot disagree.

**As the closing step of creation it is leavable, but only through an explicit acknowledgement naming
what skipping costs.** A created wallet that never exports is inert: no coordinator knows it exists,
so it can neither receive nor spend, and "later" means rebooting and retyping 24 words. It is not a
hard gate, because restart is the universal escape hatch.

No wallet name is ever included — a name is state, and an amnesic device knows nothing about what the
user calls this wallet.

## 9. Encrypted backup — export

**The door is the gate.** The requirement that the QR is offered only after the mnemonic is confirmed
recorded has already been paid for: a created wallet reached this screen through the full 24-word
retype, an imported one by the user typing a mnemonic they hold. **No additional gate, no "I have
written it down" tick** — already priced at 0% detection.

1. **One plain statement screen**: this is a second copy of the same mnemonic, for storage you do not
   fully trust.
2. **The 8 EFF words, a single numbered column**, same typography as the mnemonic. 8 is short enough
   that one column removes reading-order ambiguity entirely, where 2×4 would reintroduce the
   fill-order trap for no vertical gain. Rendering them as a lesser artifact would contradict the
   copy that says they are as critical as the seed.
3. **Type-back**, words off screen, from the user's own transcription, using the same entry component
   over the EFF long list: wrong word rejected immediately by position, committed words echoed, an
   off-list keystroke that does not land, failure destroying nothing.
   **Unlimited attempts, and an explicit "show the words again" that returns to step 2 and restarts
   the type-back.** No lockout — the words are in RAM on the device the user is standing at, so a
   limit defends nothing and can destroy a correct backup; and since a rejection names the wrong word
   without naming the right one, without re-display the repair instrument is a dead end.
4. **The QR**, at ECC H, single-part.

**The standing rule this screen adds: the 8 words are never on screen at the same time as the QR.**
Ciphertext and its password in one camera frame make a single photograph total, silent compromise.

Alongside the QR: the fingerprint, and one sentence that *is* the security model —
*store this QR and the 8 words in different places; either one alone is useless, both together are
your wallet.*

**No text fallback, in either direction.** This artifact's only consumer is aobs' own camera, so a
fallback would mean hand-transcribing ~150 characters of ciphertext with no feedback until the tag
fails years later. Restore accepts no typed ciphertext either, which keeps the keyboard off the
ciphertext path entirely.

**Re-export always mints a fresh artifact** — new salt, new 8 words, never a re-display. Holding the
password in RAM against the possibility of being asked again contradicts zeroizing it at use. Named
cost: two valid ciphertexts can circulate, each inert without its own words.

The Argon2id wait is indeterminate with elapsed seconds and no percentage, on both export and
restore.

## 10. Encrypted backup — restore

**Scan first, then the words.** The header is readable before any key derivation, so a payload that
is not ours dies in seconds rather than after eight words of typing, and `entropy_len` plus the flags
let the later screens state facts instead of generalities.

- **A failed decryption names the words and refuses to hedge.** Poly1305 cannot distinguish a wrong
  password from a tampered ciphertext, so the temptation is *"wrong words, or the data may be
  corrupt"* — technically true and practically harmful, because it invites abandoning a search that
  is still correct. After ECC-H error correction and the exact-length header check, corruption is the
  implausible branch. Copy: **these 8 words did not open this backup**, with a subtitle stating that
  the QR decoded cleanly and the header is intact.
- **The scanned ciphertext and the typed words both survive a failure. No attempt limit, no wipe.**
  Retry is editing the wrong word, never rescanning. Rate limiting is not available to us anyway, and
  on an amnesic device a lockout is theatre against a reboot while being a real loss for a user with
  a smudged word.
- **The passphrase-in-use bit is stated in both directions and never blocks.**
  Set: *this backup was made with a BIP-39 passphrase; without it you will load a different, empty
  wallet.* Clear: *this backup was made without a passphrase.* Stating only the set case would leave
  the mirrored silent failure alive. An empty passphrase entry is never refused when the bit is set —
  the user knows whether they hold it and we do not.
- **The network bit sets the network; no choice is offered.** The file already knows the answer, so a
  prompt could only manufacture the mismatch the bit exists to prevent. §5.2's selector therefore
  *states* rather than asks on this path — and that requirement is what fixed where the selector
  lives at all.

## 11. Signing

### 11.1 The scanning screen

One component, three configurations (signing, verify, restore); the copy names what this screen
wants, and the progress element simply does not appear for a single-part class.

- **A live greyscale preview, rendered from the luma plane only, at modest size rather than full
  screen.** Aiming a camera you cannot see through is guesswork. Luma-only is simultaneously the
  cheap answer and the honest one: it costs no colour conversion on a GPU-less software renderer, and
  it **displays exactly what the decoder sees** rather than a prettier version of it.
- **Progress is shown here, and the asymmetry with the outbound screen is the whole point.** Inbound,
  the decoder's state *is* our reception, so a fraction of parts received is the one thing we can
  report truthfully. `seqLen` is attacker-supplied but clamped to ≤ 64, so the worst a hostile stream
  buys is a wrong denominator on a bounded display.
- When the 1 024-part budget is spent, that is a **refusal in the standard shape** — named reason, no
  escape hatch: *this stream is not completing.*
- **A wrong-class payload is a named refusal stating both sides** — *this is a transaction QR; this
  screen is expecting an encrypted backup.* The screen **stays live** afterwards. That is not an
  escape hatch: the rejected payload remains unusable; it is only an invitation to point the camera
  at something else.
- **Escape cancels from the first frame, always**, and nothing else is reachable while the camera is
  up.
- **A successful scan dismisses immediately, with no confirmation step.** Whatever follows is itself
  the confirmation, so a *scanned OK, continue?* is a dead press between the user and the thing they
  asked for.

### 11.2 The review panel

**A single non-scrolling panel carrying the whole transaction.** This is where aobs spends the
advantage it actually has: every surveyed device compromises its review screen because it has
320×240, and we do not.

- **A fixed left rail with the money facts:** amount leaving, amount paying, **fee — absolute, as a
  rate, and as a percentage of the amount** — input count, input total, amount returning.
- **The outputs at full address width on the right.**
- **Change is presented as settled, not as a thing to check** — labelled as re-derived from the seed
  at its path and matched byte for byte. That is only honest if the re-derivation actually ran, which
  is what makes it a security boundary rather than a display detail.
- **The single advisory warning renders inline on the fee row**, as a full sentence, in colour and
  weight. **No icon** — an icon needs a legend and there is nowhere to put one. A banner or a
  dedicated screen would sever the statement from the number it is about and manufacture a dismissal
  keystroke.
- **Copy states the fact and never advises.** No *"this may indicate an error"*, no *"are you
  sure?"*, no *"I understand"* acknowledgement. There is nothing to acknowledge and no key to press.
- Nothing that should stop a transaction appears here. Refusals happen before this screen is drawn at
  all.

### 11.3 Per-address confirmation

Pressing sign walks **one full-width screen per payment address** before the signature is produced.
Destination substitution is the attack this whole screen exists to catch, and this is the only
structure that guarantees the address was alone on screen at the moment of approval. Typical
transactions have one payment, so it is typically one extra screen.

**The warning is absent from these screens.** They exist for one job, and a fee statement on them
dilutes exactly the property they were bought for.

Typed confirmation of address characters was considered and rejected: it trains the habit of checking
only the substring typed, which is exactly what a vanity-grinding attacker matches.

### 11.4 The gate

**Signing is hold-to-confirm; refusing is a single press.** The asymmetry is deliberate: the
irreversible action costs more than the safe one, and refusal is always reachable without hunting.

**The gate is byte-identical with and without the warning.** Lengthening the hold when the warning
fires would convert an advisory into a soft block, punish the user who is legitimately paying a high
fee, and teach that hold duration carries meaning.

### 11.5 The outbound QR

Nothing on screen but the title, the QR and the part count. **No repeat of the amounts** — the review
was the moment of truth, and restating money facts afterwards invites verification at the one moment
when nothing can be changed.

The part count is **static**: *4 parts, keep the camera steady until your wallet says it has the
transaction.* No counter, no percentage. Nothing at all in the single-part case.

**One "done", returning to the identity screen, with no confirmation prompt.** Asking *"did it
scan?"* is a dismissal prompt in disguise, and we cannot check the answer. What makes the absent
prompt safe is that **the most recently signed transaction stays re-displayable from the identity
screen for the rest of the session** — the alternative recovery is re-scanning, re-reviewing and
re-signing, and deterministic nonces make a re-sign byte-identical anyway.

**There is no second exit from this screen. No "sign another".** The action lives on the identity
screen one keystroke away, and a second control here is a second thing to press by accident at the
moment the user should be holding the device still.

The word *most recently* is load-bearing and the net is narrower than it looks: signing again
replaces what this slot holds, so a user who signs A, fails to hand it over, then signs B pays a
re-scan, re-review and re-sign for A. `02-core.md` §12 carries the reasoning and the cost.

## 12. Verify a receive address

Scan (single-part text class), then the verdict.

- **Match:** the full derivation path, the index, which branch it came from, and the address rendered
  in 4-character groups.
- **No match:** headline **"This address is not yours."**, rendered with the weight of a refusal
  though no transaction is involved, plus a subordinate line naming precisely what was searched —
  account path, both branches, indices 0–999.

## 13. Ending the session

**"End the session" and "shut down" are the same action.** Any *close wallet and return to the start
screen* is a switch wearing a different name.

**No lock screen, no logout, no sign-out** — locking is meaningless on a device that persists
nothing.

**Restart is offered alongside shutdown, explicitly labelled as the way to load a different wallet.**
That turns the accepted cost of one-wallet-per-boot from a dead end into a discoverable affordance.

Both confirm once, with a **press rather than a hold**. An accidental shutdown mid-review is now the
most expensive accident in the product — it costs a 24-word retype — and one press is the cheapest
guard proportional to it.

For a created wallet the final screen exists to say the one thing only it can say: **the 24 words on
paper are now the only copy that exists.** It is not an *are-you-sure*.
