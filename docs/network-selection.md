# Network selection

Which chain a session is on, where the user chooses it, and what happens when the choice is wrong.

[#27](https://github.com/allisson/aobs/issues/27) named this as an open question and deliberately did
not decide it. [#31](https://github.com/allisson/aobs/issues/31) implemented #27's *stated assumption*
so the work could proceed, and left a comment in `aobs/ui/app.py` saying so.
[#46](https://github.com/allisson/aobs/issues/46) is where the assumption was argued out. A reading
that survived because nothing contradicted it is not the same as a reading that was decided, and the
next session has no way to tell the two apart — which is the whole reason this document exists rather
than a diff.

**Not in question anywhere below:** the set of networks (mainnet, testnet4, signet, regtest — testnet3
is out of scope on [#1](https://github.com/allisson/aobs/issues/1)), that `account` stays **0** and is
not user-selectable, and that a mismatch must **refuse**, which
[#11](https://github.com/allisson/aobs/issues/11) settled.

## The network is a path, not an arrow key

**It is chosen from the wallet screen**, which is `aobs/ui/screens/home.py`. That placement survived
the grilling on its own argument: it is the last screen before *every* path that constructs a wallet —
generate, type a seed in, restore from an encrypted QR — and the network must be settled before any of
them runs. A dedicated screen before the home screen would settle it even harder and charge every
mainnet user a keypress on every boot, which is the opposite of what this appliance is for.

**What did not survive is `left`/`right`.** Until #46 the network moved under arrow keys on the home
screen, and that made it:

- the **only setting on the appliance that changed without `F10`**, the one accept key every other
  screen teaches;
- a money-affecting choice sitting **one key away from the `up`/`down` that selects a path**, on a
  screen with nine peer entries.

So it is a path like the others — *Choose the network*, opened with `F10` onto `NetworkScreen`. It
**sits last** in `PATHS` because it is a setting rather than a way in, and because the three peer ways
in stay first, which `docs/seed-entry.md` settled. `NetworkScreen` opens on the session's current
network, so `esc` and an unmoved `F10` are the same no-op.

The cost of being wrong about placement was always small — one screen and one `SignerApp` argument —
which is why proceeding on an assumption was right, and why leaving it undecided was not.

## Mainnet is the default, and the default is stated rather than asked

**Mainnet, and it costs no keypress.** The appliance is written to the publishable bar: strangers boot
the ISO with real funds. The most common path must not be the one that asks the most, so there is no
*which network?* prompt on the way in and no confirmation step.

**A free default is not the same as a silent one.** A developer on signet who does not notice the
default gets a wallet that is not theirs — recoverable, but only after a refusal they will not
immediately understand. So the current answer is stated in three places, and none of them charges a
keypress:

| where | what it says |
|---|---|
| The home screen header | `aobs · mainnet` |
| The path's own line, beside the question | `Choose the network · mainnet` |
| The fingerprint screen | `network mainnet · fixed for the rest of this session` |

The third is the one that matters most, and it is the one that was missing before #46. **The master
fingerprint comes from the seed, so it is identical on all four networks.** A user restoring a known
wallet into the wrong session is told to *compare this fingerprint against the one you recorded* — and
it will match. The addresses will still be different. That line is the only thing on that screen a
wrong-network session changes, so the screen that exists to confirm the wallet has to carry it.

> Nothing in `docs/` ever required the network in the header of every screen that shows money, despite
> #46 saying so — `docs/review-screen.md` mentions networks only to size address columns. Today it is
> in the header of the home screen and the emit screen. Whether the review, confirm and address
> screens should carry it too is a separate question and is not settled here.

## Fixed for the rest of the session

**Once a wallet has been constructed, the network never moves again**, and the rule is a one-way latch
— `SignerApp.network_fixed`, closed in `finish_wallet()` — not a guard on `self.wallet`.

The two are identical today, because `self.wallet` is written in exactly one place and never cleared;
there is no way to walk a session back to *no wallet*. That identity is exactly the trap. Expressed as
*fixed once a wallet is loaded*, the rule is a test of wallet presence, and the day a *forget this
wallet* path is added, network switching quietly comes back — at which point the same seed can be
restored onto a different chain with only the header changing. The rule this session actually has is
*fixed for the rest of the session*, so that is the rule that is written down and asserted.

While the latch is open the choice is fully reversible; once closed, the path renders unavailable
rather than hidden — a path a user cannot find teaches them the appliance cannot do it — and pressing
`F10` on it does nothing at all.

### The encrypted wallet QR states its network — closed by #52

It carried no network, and that was the gap this section named. Restoring a backup exported from a
signet session into a session still on mainnet derived a different wallet silently, and the one
check a careful user knows to make actively misled them: **the master fingerprint comes from the
seed and is identical on all four networks**, so the wrong chain compares *equal* against a recorded
fingerprint while deriving entirely different addresses. On testnet4 and signet even the addresses
compare equal, because those two share an HRP and version bytes.

The answer, settled in [#52](https://github.com/allisson/aobs/issues/52) and specified in
`docs/encrypted-wallet-qr.md`: **the container states which network it was exported from, and a
session on a different network refuses to restore it.** One byte in the header, covered by the
Poly1305 tag, checked from cleartext at the scan screen before the eight words are typed and again
from the authenticated bytes after they verify. The refusal names the network the backup was written
for, because unlike a PSBT arriving from a watch-only wallet, **here the appliance knows which side
is wrong**: the container is authoritative about the chain it came from, and the session's network
is still changeable at that moment.

It is a refusal with no override, not a warning. It offers no switch: the network changes on the
path opened with `F10` and never as a side effect of a scan. And the export screen now names the
network the backup is for, so what the user writes on the paper agrees with what the QR carries.

## A wrong choice has an honest recovery

`RefusalReason.NETWORK_MISMATCH` was classed *nothing on this device will help*, whose third sentence
is *your wallet must build the transaction differently*. That is true of the PSBT and **false of the
session**: when the user picked the wrong network, the fix is entirely on this device — power off and
start again.

The appliance cannot tell the two apart, so it names both and recommends neither. That is a third
refusal kind, and `docs/failure-states.md` carries it along with the reasoning. It is still one
sentence, so the three-sentence failure shape is unchanged.

## What a test asserts

- Mainnet is the default, and it is on the header and on the path's line without a keypress.
- `left`/`right` on the home screen change nothing.
- The network path opens on the session's current network and returns to the home screen.
- Constructing a wallet closes the latch, and the path is unavailable and inert afterwards —
  **including after `app.wallet` is cleared**, which is what makes it a latch and not a guard.
- The fingerprint screen names the network, and the same seed's fingerprint is identical across
  networks, which is why it must.
- Exactly one `RefusalReason` is of the either-side kind, and its sentence names both fixes.
