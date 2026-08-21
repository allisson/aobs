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

### The panel: one design canvas, a scale factor, and a floor

**The layout is designed once, at 1280×800 logical pixels, and every panel is expressed in that
canvas.** The appliance cannot choose its mode — the DRM tier takes the connector's preferred mode
(Slint's `drmoutput.rs` picks `max_by(PREFERRED, then area)`) and the fbdev tier takes whatever the
firmware handed `efifb` — so the mode is an input, and the only free variable is what we draw into it.

- **Above the design size, scale; do not grow the layout.** The shell computes
  `scale = max(1, min(width / 1280, height / 800))` from the mode it just learned and dispatches
  `WindowEvent::ScaleFactorChanged`. Consequence: the logical canvas is **never smaller than 1280×800**
  on any panel at or above that size, and physical type grows with the panel — 1920×1080 and 3840×2160
  both land on a 1422×800 logical canvas. A 4K panel therefore gets 2.7× larger type, not 2.7× more
  content. **The prototype's `max-width: 1120px` is not the policy**: content-capping a 4K panel leaves
  a small island of unreadable text, which is the opposite failure to the one §0 is defending against.
- **Below the design size, reflow — two breakpoints and no third.** Above a logical width threshold the
  review panel is the fixed rail beside the outputs (§11.2); below it, the money facts stack above the
  outputs and the full width goes to the address column. Two states are testable and describable; a
  cascade of five is neither.
- **Type never shrinks below the floor in the palette above.** Addresses stay at 17–22 px logical. That
  floor *is* the legibility argument this whole section rests on, so shrinking type is the one bend
  that attacks the reason the visual system exists. Reflow and wrapping bend instead.
- **Minimum supported mode: 800×600 physical.** Below it the appliance refuses at startup, on a live
  console, in the shape `01-boot-layer.md` §9 specifies — the same class as a framebuffer format
  outside the renderer's five accepted arms, because it is the same failure: the panel is there and we
  cannot draw honestly on it. 800×600 is not a guess — it is edk2's default GOP mode
  (`MdeModulePkg.dec`: `PcdVideoHorizontalResolution|800`, `PcdVideoVerticalResolution|600`, where `0`
  would mean *highest available*), so it is what OVMF hands our own CI and what a BMC or an older
  firmware hands a user. **Named cost:** 640×480-class firmware is excluded, on machines at or below
  the ~2012 line `01-boot-layer.md` §7 already excludes.

**Group separation is a gap, not a space.** The 4-character groups are separated by a **sub-cell gap of
about 0.25 em**, not by a space character occupying a full monospace cell. This is load-bearing rather
than typographic: at 17 px in DejaVu Sans Mono a 62-character P2TR address is 62 cells + 15 gaps ≈ **698
px** and holds **one line** inside the floor's ~768 px of usable width, where the prototype's real-space
treatment is 77 cells ≈ **787 px** and wraps. A wrapped row costs ~86 px against ~57 px, and §11.2's
output bound is a row count — so this one detail is the difference between a six-output appliance and a
three-output one.

**Addresses wrap where they still do not fit; they are never truncated.** Wrapping in 4-character groups
keeps every character on screen, and it remains the treatment at §11.3's larger type, where a 22 px
address exceeds any canvas — that screen already wraps at 30 characters, so this is established rather
than invented here. Note that the in-tree prototype renders only 42-character P2WPKH addresses, so
**nothing in-tree has been measured against the widest address class we ship**.

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
present. **Silently also covers late**: the capture and the `getrandom` call run independently, so a
driver that never hands over a buffer cannot hold up the readiness that unlocks Continue — whatever
has arrived by the time the user presses on goes into the mix, and whatever has not is an absent
supplement, which `02-core.md` §3 already treats as the camera-less case. No timeout is written down
anywhere, because there is nothing for one to decide.

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

**Measured, and now asserted on every boot** ([#72](https://github.com/allisson/aobs/issues/72)).
The binding case moved to the floor when §0 fixed it: at or above the design size the logical canvas
is never smaller than 1280×800, so 800×600 is the only geometry where this can fail. The screen is
built from named heights — a 52 px banner, a 14 px gap, twelve **26 px** rows, a second gap and a
48 px continue row — which sum to **440 logical px**, against the **458 px** the chrome leaves in the
minimum canvas: 600 less a 44 px header, two 1 px rules, a 48 px footer and 24 px of slot padding top
and bottom. The appliance reads those same properties off the layout and prints
`AOBS_WORDS required=440 available=458 fits=yes` before the first paint; `ci/qemu-boot.sh` refuses a
boot reporting `fits=no`, and the `ramfb` row runs at exactly that geometry. **What a sum cannot
cover is a person looking at the panel** — `docs/qa-checklist.md` carries that row, and it is the one
that would catch a banner that wrapped to a third line.

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

**The screen is built from §3's heights, so §3's measurement covers it**
([#73](https://github.com/allisson/aobs/issues/73)): the same 52 px banner, the same twelve
26 px rows in two columns, the same 48 px control row — 440 px against the 458 px the chrome
leaves in the minimum canvas, which is what `AOBS_WORDS` prints on every boot. The live line the
entry needs — the key that did not land, or how many words the current prefix still matches —
sits **inside** the banner's fixed height rather than as a row of its own, which is what keeps
two screens on one measurement instead of two.

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
- **The keymap is a US layout, always, and no picker is offered.** The field is printable ASCII only,
  and group 1 of `us` reaches all 95 of those characters, so on a German, French or Brazilian keyboard
  nothing is *unreachable* — the legends are simply wrong. So **the screen names the layout before the
  user starts**, the way §6 names English; a stated fact beats a mystery under the fingers. A picker
  was rejected twice over. It would be answered on the start menu, before the user has typed a
  character or seen any evidence of a mismatch — the shape §5.2 rejects when it argues that a control
  answered before the device knows the path is in the wrong place. And its own failure is worse: a
  wrongly-picked `de` or `fr` swaps keys in the *other* direction and imports **dead keys**, where `^`
  produces nothing until the next keystroke. A wrong legend is a visible mode, because the clear-text
  render above shows exactly what landed; a dead key is an invisible one. The mechanism — three
  `XKB_DEFAULT_*` lines on the unit, no package, no code — is `01-boot-layer.md` §2.
- **Named cost:** a user on a non-US physical keyboard types the passphrase by hunt-and-peck against
  that render, with wrong legends under their fingers. Nothing is bought back by a choice: a
  passphrase containing a character outside printable ASCII is already unenterable here on any
  layout.

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
committed words. **The screen names English and the US keymap before the user starts** — the keymap for the reason in
§5.1, and here it degrades more gently than there: the wordlist is `a`–`z`, the pinned keymap puts
those on the same physical keys on every board, and only the legends can mislead — an off-list
keystroke then names itself, below.

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

**The tree carries this screen** as of [#78](https://github.com/allisson/aobs/issues/78) —
`aobs/src/scan.rs` and `ScanScreen` in `aobs/ui/app.slint`. Two things it had to settle:

- **Whether the camera stays up is read off the scanner, not off the refusal.** A wrong-class payload
  leaves the scan live and a spent part budget ends it, and both are already facts inside
  `aobs_core::ur::Scanner` — so the screen asks it (`spent()`) rather than telling the two `Refusal`
  variants apart itself. That keeps standing rule 4 true of the one branch on this screen that
  matters, and it is why the wrong-class sentence and the live preview appear together.
- **The two ways this screen stops — a spent budget, a camera that went away — each carry one row
  off it**, and Escape does the same thing. See `03-transport.md` §5a on why the return is a press
  rather than automatic. While the camera is up the screen contributes **no** rows at all, which is
  how *nothing else is reachable* is structural: the ring holds only §7's always-available row, and
  that one lands on a confirm rather than on an action.

### 11.2 The review panel

**A single non-scrolling panel carrying the whole transaction.** This is where aobs spends the
advantage it actually has: every surveyed device compromises its review screen because it has
320×240, and we do not.

- **A fixed left rail with the money facts:** amount leaving, amount paying, **fee — absolute, as a
  rate, and as a percentage of the amount** — input count, input total, amount returning.
- **The outputs at full address width on the right** — *full width* meaning every character, wrapped in
  4-character groups where the column is still narrower than the address, never truncated and never
  scrolled. §0's gap-not-space rule is what lets a 62-character P2TR hold one line even at the floor.
- **Below the design width the rail stops being beside the outputs and stacks above them** (§0's second
  breakpoint), which hands the whole width to the address column. Nothing is dropped in the stacked
  state: it is the same panel, in one column instead of two.
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

**The panel holds at most six outputs, and a seventh is a refusal rather than a scroll.** Payment and
change outputs both count — a row is a row. The count is checked in core, before this screen exists
(`02-core.md` §7), so the panel is never asked to draw something it cannot hold.

Six is **set by the minimum canvas, not by the panel in front of the user**: 600 px less chrome, the
stacked money facts, the list header and the footer leaves roughly 320 px of rows, and a single-line
output row costs about 57 px. A bound derived from the live mode would sign a PSBT on one machine and
refuse it on another, which no test row and no user could reason about. *Owed: that six rows fit the
minimum canvas. Provisional in the same way the RAM floor is provisional, and movable only before the
first signed ISO ships.*

### 11.2.1 How the numbers are written

Settled by [#100](https://github.com/allisson/aobs/issues/100). The prototype was already internally
consistent about amounts, and every one of its renderings is now a rule — with the boundaries stated
and the grouping reconciled against §0. Rendering is a pure function over `bitcoin::Amount` in
`aobs-core/src/format.rs`, the ninth 98% component, and it decides nothing: §9's warning is a typed
variant and stays one, so no arm of the formatter evaluates a condition and no arm of it reads a
network.

**Amounts are BTC with eight decimals, never trimmed.** `0.04855200`, `0.00005200`,
`21000000.00000000`. Eight decimals is exactly what BTC needs to carry one satoshi, so nothing the
appliance can hold is unrepresentable and nothing is rounded — a one-satoshi payment is `0.00000001`
and never `0.00`. Fixed decimals also make the digits a *shape*: the point lands in the same column on
every row of the rail, so a magnitude error reads as a misaligned column rather than as digits to
count. **Named cost:** six meaningless zeros in front of every small number — which is what the
satoshi form below buys back.

**The unit is a separate label, and it is `BTC` on both networks.** The formatter returns digits and
never a unit; the shell sets the label apart from them, dimmer and smaller (§0). There is no `tBTC`
and no different precision on testnet — ADR-0015 makes those sessions look identical to mainnet ones,
and a unit label is the one place the money would have leaked the network.

**The fee carries a second form in satoshis; no other row does.** `5 200 sat` beside
`0.00005200 BTC`. The fee is the number the eight-decimal form serves worst — routinely five zeros
and then the digits — and the only one a user compares against a market quoted in satoshis. Two units
on every row would be a units question on every row.

**Satoshi digits group in threes. BTC digits do not group at all.** The satoshi form is a free-length
integer with nothing anchoring its magnitude — `5200` and `52000` differ only by width — so it is
grouped, conventionally, in threes from the right. The BTC form is already anchored by the fixed point
and the fixed eight decimals, so grouping it would add a second reading rule and buy no scan help.
**Named cost:** an amount above 1 000 BTC has an ungrouped integer part.

**The separation is §0's gap, not a space character** — the same mechanism as an address, and the
group *size* differs because the jobs differ: four for characters being compared one at a time, three
for digits being read as a magnitude. The formatter therefore returns the satoshi groups **as data**,
the way address groups already come back, and the shell lays them out with the sub-cell gap. A real
space costs a full monospace cell per gap where §0's gap costs a quarter, and §0's whole argument is
that cells at the floor are what the six-output bound is made of. Two rules disagreeing about the same
gap, in the same panel, is the silent disagreement this spec removes everywhere else.

**The fee rate is `sat/vB` with one decimal, and it divides by the predicted vsize of the *signed*
transaction.** `25.0 sat/vB`. The PSBT carries an unsigned transaction, so the size is a prediction
rather than a measurement — and a sound one, because the wallet is single-sig across exactly four
known script types (`02-core.md` §6) and each input's witness or `scriptSig` is therefore a fixed
shape. The prediction sums **weight units** — the unsigned transaction's base size at ×4, plus each
input's own signing data at its own weight — and divides once, `vsize = ceil(weight / 4)` as BIP-141
defines it, never rounding per input. Each ECDSA input is charged a **71-byte** signature element, the
smaller of the two sizes low-S DER produces, so the error runs in one direction only: **the rate
displayed is never lower than the rate the broadcast transaction will pay.** A screen that made a fee
look cheaper than it is would be the one rounding error this panel cannot afford. **Named cost:**
about half of ECDSA inputs produce a 72-byte element instead, so the displayed rate reads high by a
fraction of a percent. The prediction against a real signed transaction is *owed*
(`00-overview.md`).

**The fee as a percentage of the amount paying is three decimals, and a consolidation has none at
all.** `0.107%`. The denominator is the amount paying — the total to non-change outputs — which is
exactly §9's warning denominator, so the two numbers cannot disagree about what they are about. With
no non-change outputs the ratio is undefined, §9 says nothing fires, and the formatter returns nothing
rather than a zero, an infinity or a dash: the absence is typed, not rendered.

**A number that would round to zero renders as a bound instead.** A non-zero fee under 0.05 sat/vB is
`< 0.1`, and a non-zero ratio under 0.0005% is `< 0.001`. Rounding a real fee to `0.0 sat/vB` or a
real ratio to `0.000%` would be the formatter quietly asserting *nothing*, and asserting is deciding —
§9's line. Otherwise both round half up. At the other extreme nothing is clamped: a 5 200-satoshi fee
against a one-satoshi payment is `520000.000%`, which is the fact.

### 11.3 Per-address confirmation

Pressing sign walks **one full-width screen per payment address** before the signature is produced.
Destination substitution is the attack this whole screen exists to catch, and this is the only
structure that guarantees the address was alone on screen at the moment of approval. Typical
transactions have one payment, so it is typically one extra screen.

**The warning is absent from these screens.** They exist for one job, and a fee statement on them
dilutes exactly the property they were bought for.

**The walk inherits §11.2's bound at no cost.** Six outputs is at most six confirmation screens, which
is a walk a person completes — which is the second reason the bound is a refusal rather than a paged
list. A device that pages 200 outputs has a review that quietly does not happen.

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

**Restart is a promise about the wallet, not the machine.** It is delivered by the app exiting and
systemd restarting it — a fresh process with a fresh `OnceLock` (ADR-0010), in about a second, on the
path `01-boot-layer.md` §2 already documents as crash behaviour and which is therefore the
best-tested path in the image. A machine reboot would buy nothing: the kernel holds no wallet state,
and §5 there records that a reboot frees neither the overlay upper dir nor the page cache either.
**The cost is the label**, and it is paid rather than hidden: the entry says what it does — *start
over with a different wallet* — instead of borrowing the machine's word for it and meaning something
narrower (ADR-0017).

**The physical power button is the same action as the menu entry**, confirmation included. It is not
a second, faster path to shutdown: a press lands on the same confirm, so an accidental knock costs a
press to undo rather than a session. The appliance receives it directly from its own input device —
no `systemd-logind`, no D-Bus (`01-boot-layer.md` §2, ADR-0017). **Where it cannot reach**, before
the GUI is up or on a parked diagnostic screen, the four-second hold is the only way off the machine,
and it is a hard power cut with what that costs recorded in `01-boot-layer.md` §5.

Both confirm once, with a **press rather than a hold**. An accidental shutdown mid-review is now the
most expensive accident in the product — it costs a 24-word retype — and one press is the cheapest
guard proportional to it.

For a created wallet the final screen exists to say the one thing only it can say: **the 24 words on
paper are now the only copy that exists.** It is not an *are-you-sure*.
