# The PSBT review screen

What the review screen looks like. [`psbt-review-model.md`](./psbt-review-model.md) owns the *model* —
the proof rule, the three output categories, the refuse and warn lists, the headline number, and the
display rules — and explicitly not the layout. This document owns the layout, and settles nothing the
model already settled.

It inherits its global keys from [`failure-states.md`](./failure-states.md) rather than inventing
them: `esc` backs out, `F12` powers off from anywhere, and confirm is never `enter` and never `esc`.

## The canvas is 128 × 48, not 85 × 43

[#3](https://github.com/allisson/aobs/issues/3)'s **85 columns × 43 rows** is the half-block grid a
QR code occupies. It is not the console. `boot-pipeline.md` fixes the console at **128 × 48** — 1024×768
via `vga=791`, kernel 8×16 font — and [#17](https://github.com/allisson/aobs/issues/17)'s
five-rows-of-chrome budget was a constraint of the QR screen, which has to fit a 77-module symbol.
The review screen has the whole console and subtracts nothing.

**128 × 48 is a floor, not a target.** `vga=791` pins the BIOS path exactly, but the UEFI path takes
`efifb` at the GOP's native mode: a 1920×1080 panel gives 240×67, a 4K one gives far more. So the
appliance will meet at least three real geometries.

**Rows are fluid, columns are capped at 96, and the block is centred.** More rows is pure win — more
outputs visible before scrolling, and the pinned-region model below does not care. More columns is
not: 96 is chosen against the widest atom on the screen (see below), and it stops a warning sentence
from stretching to 240 columns, which is unreadable. One column budget also means **one layout to
test**, so [#13](https://github.com/allisson/aobs/issues/13)'s golden-file assertions stay stable
across every geometry. A startup check refuses to run below 100 × 30 rather than degrading silently.

## The output row

The widest address the appliance can ever be asked to display is a **regtest taproot `bcrt1p…`, 64
characters** → 16 groups of four → 79 columns, plus a 5-column indent = 84. Mainnet taproot is 79
columns of address, native segwit 54, a legacy recipient 44. **Every address type on every network
fits one unwrapped line inside 96**, so:

**The address is a single line, grouped in fours, never wrapped.** A fixed grid — say 8 groups per
row, so group *n* always lands in the same column — buys positional stability the single line already
has, and pays for it with a wrap point that exists for taproot and not for segwit. The user then
learns two shapes, and *"am I on the second row"* becomes a way to compare the wrong group against
the phone. The phone shows the address as one string; one line is the closest analogue to the thing
being compared.

```
  2  PAYMENT                                0.01400000 BTC  ·  1 400 000 sats
     bc1q ar0s rrr7 xfkv y5l6 43ly xpvz adao mjwd 3nsr yq
     Address not seen before.

  3  PAYMENT                                0.00250000 BTC  ·    250 000 sats
     bc1p mfr3 p9j0 0pfx jh0z myp3 fndz c6qx cuvr fzcz e5da q0q4 pxdu wsev tep6
     ⚠ Your wallet says this output is your own change. This appliance could
       not derive it from its own keys, so it is shown as a payment and
       counted as leaving. Verify this address as you would any recipient.

  4  CHANGE, PROVEN                         0.03291744 BTC  ·  3 291 744 sats
     m/84h/0h/0h/1/14
     bc1q w508 d6qe jxtd g4y5 r3za rvar y0c5 xw7k v8f3 t4                   (dim)
```

**Thousands are separated by spaces, not commas.** The appliance has no locale, and a screen already
printing `0.01400000` with a decimal point cannot also spend `,` without being ambiguous for half the
world. The BTC figure keeps all eight decimals ungrouped — grouping them would invent a convention.

**Proven change leads with the proof, not the address.** The derivation path is the substance; the
address is dimmed beneath it because eye-verifying it adds nothing. It stays **full and untruncated**
anyway: the model's no-middle-ellipsis rule exists because a truncated address is what an attacker
holding a vanity-prefix collision wants, and carving an exception for the one category we derived
ourselves teaches the eye that ellipses are normal on this screen.

One blank line separates outputs. Legibility beats density here; scrolling exists.

## NOT PROVEN reads as PAYMENT, with the wallet's claim named

The model requires NOT PROVEN to be displayed and counted as a payment, warned, and never described
as change. The screen's problem is that the user is about to see an output their wallet *told them*
is change, labelled `PAYMENT` — and an unexplained label is where
[#20](https://github.com/allisson/aobs/issues/20)'s blind retry starts.

So the label is `PAYMENT`, byte-identical to any other payment, full address shown, plus the warning
in the row template above. A **third on-screen label** (`UNVERIFIED` and friends) is rejected: it
reintroduces the third category as a *middle ground* between payment and change, and a middle ground
is where a user parks a decision. The model collapses three categories into two screen treatments on
purpose.

The wording **names the claim** so the label is not baffling, **names where the fix is** (this is not
a scan to retry), and **does not accuse the wallet** — a gap-limit miss and an attack are
indistinguishable from here, which is the same restraint
[#19](https://github.com/allisson/aobs/issues/19) imposed with *not found, never "not yours"*.

## Warnings split by kind

The model's four warn conditions are of two kinds, and they go to two places.

- **Per-output** — NOT PROVEN, address never seen before — sit **inline**, in the output's own
  indent, directly under the address the user's eye is already working on.
- **Per-transaction** — fee above threshold, spend consumes the entire balance — sit in a block
  **pinned directly above the totals**, because they are statements about the footer's number and
  not about any output. Pinned means they cannot be scrolled off, which is the protection the model
  already gave the fee.

A single warnings block at the top is rejected: read before the thing it describes, it reads as
boilerplate, and it makes the user carry *"output 3 is suspect"* down a scrolling list.

**"Address not seen before" is rendered as a neutral fact, not a warning.** It is true of essentially
every legitimate payment; at warning strength on every payment it is noise that teaches skipping.
Warning styling is reserved for NOT PROVEN.

## Three regions: fixed header, scrolling list, pinned footer

```
  Review transaction                                            mainnet
  2 inputs  ·  4 outputs                                                  ← header, fixed
  ───────────────────────────────────────────────────────────────────────
                                                                          ← list, scrolls
     …outputs…

  ───────────────────────────────────────────────────────────────────────
  ⚠ This transaction spends your entire balance.                          ← footer, pinned
  Leaving:   0.01650000 payments  +  0.00003100 fee  =  0.01653100 BTC
                                                        1 653 100 sats
  Fee:  3 100 sats  ·  14.2 sat/vB  ·  0.19% of the amount sent
  ───────────────────────────────────────────────────────────────────────
  Outputs 1–4 of 9 — scroll to the end to unlock signing.
  ↓ PgDn scroll  ·  esc discard  ·  F12 power off
```

**The headline number keeps its composition on two lines, BTC then sats.** The sats figure of the
*total* is the number this screen most wants to be unmisreadable, so it gets its own line directly
under the figure it restates.

**`F10 sign` is not shown while the confirm is locked.** Printing a key that does nothing teaches
pressing keys that do nothing; the lock line says what is missing instead. It replaces itself with
`F10 sign · esc discard · F12 power off` the moment the last row renders — at first paint, if all
outputs already fit.

**There is no jump-to-end key.** No `end`, no `G`. Scroll-to-end is the whole mechanism, and a
one-keystroke bypass of it is the mash-trainer the model refused wearing a different hat. Scrolling
is `↓`/`↑` by line and `PgDn`/`PgUp` by page; reaching the bottom of nine outputs costs about three
keypresses.

## Confirming: `F10` opens, `y` signs

The two-step is the model's own — *one confirmation, and it restates the total*. The review screen's
key is therefore not a confirmation but *"I am done reading"*, which is why scroll-to-end gates it.

**The two keys are deliberately different.** A user who mashes `F10` twice lands on the confirm
screen and stops, because the second press does nothing. `y` is safe on that screen precisely because
the screen is unreachable by momentum — there is no way to arrive without a deliberate `F10` — and it
is unambiguous in a way `F7` never is. `F10` sits two keys from `F12`, and a slip in that direction
powers off, which is the harmless direction.

```
  You are about to sign.                                        mainnet

     Leaving this wallet      0.01653100 BTC       1 653 100 sats
        0.01650000 in payments  +  0.00003100 fee

     Fee                      3 100 sats  ·  14.2 sat/vB  ·  0.19%

     4 payment outputs, 1 of which this appliance could not prove
     is your own change.
     1 proven change output returns 0.03291744 BTC to this wallet.

  y  sign      ·      esc  back to the review
```

**No addresses on the confirm screen.** They were just read at full width with the eye doing
positional work; a second, necessarily shallower pass at the moment of commitment **substitutes for
the first** rather than adding to it — the user starts skimming the review because *"I'll check it on
the confirm screen"*. The confirm screen's job is the number, which is what makes the change-address
attack visible in the first place, and the NOT PROVEN count travels with it because it explains why
the number is what it is.

`esc` returns to the review with the scroll position intact and the confirm still unlocked. Backing
out of a confirmation is not a reason to re-scroll nine outputs, and making it one would teach the
user to avoid `esc`.
