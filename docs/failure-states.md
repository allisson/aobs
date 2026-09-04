# Failure and error states

What the user sees when something goes wrong, and what they do next.

[#11](https://github.com/allisson/aobs/issues/11) settled *what* refuses — missing UTXO data, an
unsignable input, network mismatch, any sighash other than `SIGHASH_ALL`, an unparseable PSBT — and
that refusals carry **no override**. Removing the override removed one failure and created its
opposite: an explanation so thin the user retries blindly.

This document is about that, and about every other way the appliance can fail to do what was asked.

## The shape of a failure screen

Reused verbatim from [#19](https://github.com/allisson/aobs/issues/19), which arrived at it first:

- **State exactly what happened**, in the terms the user can act on.
- **Offer next steps with no default and no highlighted button.** The appliance does not press its
  thumb on a choice it cannot make.
- **Never pretend to an interpretation it does not have.**
- No error codes without words. **No traceback, ever** (#15).
- **The release identity row** — the same two lines the keymap picker carries
  (`boot-pipeline.md`): `aobs v0.1.0 · 4f1c8a6e2b90 · 2026-09-14`, and where advisories live.

The identity row is here for the same reason the condition name is, and it is the same trade: **a bug
report carrying no build identity is a bug report about nothing.** A user typing up what they saw on a
different machine can copy a version and a commit prefix off the screen, and neither costs anything
or carries anything off the machine. It is one shape for every failure screen, so it is one line in
one widget — not a decision each screen makes for itself.

It **identifies, it does not attest**: a modified image can print anything, and nothing here should be
read as the appliance vouching for itself.

## A QR that decodes but is not ours

**Name what it actually is.** Lumping these into *unrecognised QR* discards information the appliance
already holds.

| what was scanned | what it says |
|---|---|
| Not a UR, not our container | *This is not a PSBT or a wallet backup.* |
| A UR of the wrong type (`ur:crypto-account`, `ur:crypto-hdkey`) | *This is a wallet descriptor, not a transaction* — a user who scanned on the wrong screen learns exactly that. |
| Our container, wrong version | #9's magic-and-version framing already separates this from a bad password; the message is that the appliance and the QR are different versions. |
| Our container, exported on another network | *This is one of our wallet backups, and it was exported on `<network>`* — and the next step is to choose that network from the home screen and scan again. |
| Our container, naming a network this version does not know | Its own words, never *wrong password*: the user is not sent hunting for a typing mistake they did not make. Its next step matches the wrong-version case. |

### Neither network failure is a `RefusalKind`

Both follow the ordinary three-sentence shape — what it is, why it stops, where the fix is — and
neither needs the fourth refusal kind that `RefusalReason.NETWORK_MISMATCH` needed.

The reasoning that made network mismatch its own kind was that **the appliance cannot tell which
side is wrong**: a PSBT built on another chain and a session started on the wrong one are
indistinguishable, so it names both and recommends neither. Here the opposite holds. The container
is authoritative about the chain it was exported for; the session's network is still changeable at
that moment, and *Choose the network* is one path away on the home screen. So the *where* is
singular and directed, and the failure is an ordinary one.

The wrong-network refusal happens **twice**, and both must exist. At the scan screen it is read from
the cleartext header — the courtesy, so eight words are not typed in full before the user finds out.
After the password verifies it is read from the same byte, now covered by the Poly1305 tag — the
guarantee. Anyone who can substitute the QR can flip the cleartext byte, so only the second is the
security boundary; a later simplification that deletes one must not delete that one.

### `ur:psbt` is accepted inbound

**And this does not contradict #4.** #4 established we must never *emit* `ur:psbt`, because BlueWallet
routes that prefix to its UR v1 decoder, where it fails. That is a constraint on our **output**.

It carries the same CBOR payload, so refusing it inbound would mean rejecting a PSBT the user's wallet
legitimately produced, for bookkeeping reasons. **Liberal inbound, strict outbound.**

Written down explicitly because the next reader will see `ur:psbt` in the accept list and think it is a
mistake.

## No webcam, or a webcam that disappears

**Start anyway. Disable only what needs the camera.**

Refusing to boot without a camera is the obvious move and it is wrong: **generating a wallet and
exporting its descriptor need no camera at all** — both are outbound. A user setting up a new wallet on
a machine with an unplugged webcam should get a working appliance with the scan paths disabled and one
sentence saying why, not a dead screen.

### Losing it mid-session is permanent, and the appliance must say so

A consequence of #14 that is not obvious: **`authorized_default=0` is set before the first secret is
entered, so a camera unplugged and replugged is not re-authorized.** It is gone until the next boot.

So the message is *the camera was disconnected and cannot be re-enabled this session; power off and
start again* — not a retry prompt. **An honest dead end beats a silent one**, and the alternative is a
user replugging a cable that can never work.

## An inbound stream that stalls

**Never time out.** #17 settled the outbound side — the animation never stops, the cycle count is the
diagnostic. Inbound mirrors it: no automatic abort, and **give up** is something the user chooses.

What makes this useful is distinguishing three states rather than showing one spinner:

- **Parts arriving, count rising.** Normal. *17 of 27.*
- **Frames decoding, but no new parts.** The sender is stuck on a subset or showing a static frame — a
  different problem with a different fix, and the appliance knows which one it has.
- **Nothing decoding at all.** Aiming, focus, or density. This is the inbound counterpart of #17's
  step-down key: the user's wallet may be emitting too dense a code.

**Parts from a different message are detectable for free**, since each UR part carries the message
length and checksum. A user who starts scanning transaction B midway through A gets *these frames are
from a different transaction* and a reset — not a stream that silently never completes.

## How a refusal is explained

**Three sentences in a fixed shape: what it is, why it stops, and where the fix is.** The third is the
one that prevents blind retry, and it is the whole point.

Every refusal in #11's list is one of three kinds, and the appliance always says which:

- **Nothing on this device will help.** Non-`SIGHASH_ALL`, an unsignable input, missing UTXO data.
  The transaction must be rebuilt. *Retrying will not change this; your wallet must build the
  transaction differently.*
- **The transfer failed.** An unparseable PSBT can be a truncated scan. *Try scanning again* is honest
  here — and **nowhere else**.
- **The fix may be on either side, and the appliance cannot tell which.** Network mismatch, and only
  network mismatch. *Retrying will not change this: either this session is on the wrong network —
  power off and start it again on the one you meant — or your wallet must build the transaction
  differently.*

Getting that split wrong in either direction is a real failure: telling someone to retry a transaction
that can never be accepted teaches them the appliance is broken; telling someone a truncated scan is
unfixable sends them back to their wallet for no reason.

### Why network mismatch is its own kind

It was *nothing on this device will help* until
[#46](https://github.com/allisson/aobs/issues/46), and that was the split being wrong in a third
direction the two kinds could not express. A mainnet PSBT arriving at a signet session has two causes
the appliance cannot distinguish: **the user chose the wrong network**, or **the watch-only wallet
built the wrong transaction**. The first has its fix on this device — power off, start again — and
saying *your wallet must build the transaction differently* silently picks the second, sending someone
off to rebuild a transaction that was already correct.

This is `docs/address-verification.md`'s **"not found", never "not yours"** applied to a refusal: two
indistinguishable causes, so state what happened and name both fixes with neither recommended. It is
still one sentence, so the three-sentence shape holds. `docs/network-selection.md` holds the rest of
the network decision.

## What a failure costs

**Nothing ends the session but an unrecoverable fault (#12) and the user's own choice.** A refused PSBT
returns to the scan screen with the wallet still loaded.

Treating a hostile PSBT as a security event and dropping the wallet is the tempting alternative, and it
is wrong twice. It **buys nothing** — the wallet is in RAM regardless, and a refusal means the attack
failed. And it **costs a great deal**: re-entering a 24-word seed and a passphrase after every bad scan
is the surest way to make people stop using the appliance, or to keep a wallet loaded by avoiding scans
altogether.

Ending the session stays one deliberate act away, which is the property that makes never ending it
automatically safe.

## Global keys

Three reserved keys, identical on every screen, and nothing else reserved:

| key | meaning |
|---|---|
| `esc` | Back out of this screen without acting. |
| `F12` | Power off. From anywhere, always. |
| per-screen | Confirm — **never `enter`, never `esc`**. |

#11 fixed the first half of that last rule. The second half matters as much: a user who has learned
`esc` means *back* must never meet a screen where it means *proceed*.

**Settled here rather than in the layout tickets because failure screens are the screens users reach
while confused**, and they are exactly where a key that behaves differently gets pressed by momentum.
#21 and #22 inherit this rather than each inventing one.

`F12` for power-off specifically: hard to hit by accident, impossible to hit while touch-typing a
mnemonic — and a power-off that needs a menu is one people avoid, which leaves wallets loaded on
unattended machines.

### Per-screen keys are named in their own screen's document

**The inventory above stays three, and it is not the whole keyboard.** A screen may bind a key of its
own beyond the confirm — and where it does, the key and the reasoning for it belong in that screen's
document, not here. This document owns what is *identical everywhere*; a key that exists on one
screen is a fact about that screen.

Named here so the inventory is not silently incomplete, every key any screen binds today falls into
one of three kinds:

| kind | keys | screens |
|---|---|---|
| **Confirm** | `F10`, and `y` on the confirm | keymap, home, review, confirm |
| **Navigation** | `↑` `↓` `PgUp` `PgDn` — move a selection or a viewport, act on nothing | keymap, home, review |
| **Its own** | `F9` — *step the QR down one rung of the density ladder* (`docs/qr-emit-parameters.md`) | emit |

**Only the third kind is new ground**, and there is one key in it: `F9` is the only key in the
appliance that changes state without confirming anything and without being navigation. That is why
it needed a ticket of its own, and why the next one will too.

It chooses a **function key** for the same reason `F12` does: the keymap is whatever the user picked
on the first screen, so a letter key is not in a known place and a function key is. A per-screen key
that wants to be a letter is a per-screen key that needs re-arguing — the confirm's `y` is the one
that carried that argument, and it carried it on the strength of being unreachable by momentum.

### The word beside `esc` is per-screen; the key is not

`esc` means *back out without acting* on every screen, and that is the part nothing may vary. **What
each screen prints beside it does vary**, and should: the review says `esc discard`, the confirm says
`esc back to the review`, the emit screen says `esc done`. Each names what leaving *that* screen
costs, which is more use to the user than one word repeated.

The rule this protects is unchanged — a user who has learned `esc` means *back* must never meet a
screen where it means *proceed*. A screen whose honest label for `esc` would be a commit has a
design problem, not a wording problem.

## There is no diagnostic export, on purpose

**No log file, no diagnostic QR, no "copy error details".**

A diagnostic export is a data path out. #15 removed logging entirely, and the reasoning applies with
more force to anything the user could carry off the machine: a dump written while a wallet is loaded is
the artifact most likely to contain key material, and it would leave by the QR channel — the one
channel this project spent four tickets constraining.

What a failure screen gives instead is **a short stable identifier for the condition — a name, not a
code, and not a stack location** — so the user can accurately describe what they saw in a bug report
they type on a different machine. That costs nothing and carries nothing.

Stated in the published docs as a deliberate limitation rather than an oversight: **this appliance is
harder to debug in the field on purpose**, and the trade is made in favour of the funds.
