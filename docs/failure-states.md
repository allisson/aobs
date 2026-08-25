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

## A QR that decodes but is not ours

**Name what it actually is.** Lumping these into *unrecognised QR* discards information the appliance
already holds.

| what was scanned | what it says |
|---|---|
| Not a UR, not our container | *This is not a PSBT or a wallet backup.* |
| A UR of the wrong type (`ur:crypto-account`, `ur:crypto-hdkey`) | *This is a wallet descriptor, not a transaction* — a user who scanned on the wrong screen learns exactly that. |
| Our container, wrong version | #9's magic-and-version framing already separates this from a bad password; the message is that the appliance and the QR are different versions. |

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

Every refusal in #11's list is one of two kinds, and the appliance always says which:

- **Nothing on this device will help.** Non-`SIGHASH_ALL`, network mismatch, an unsignable input,
  missing UTXO data. The transaction must be rebuilt. *Retrying will not change this; your wallet must
  build the transaction differently.*
- **The transfer failed.** An unparseable PSBT can be a truncated scan. *Try scanning again* is honest
  here — and **nowhere else**.

Getting that split wrong in either direction is a real failure: telling someone to retry a transaction
that can never be accepted teaches them the appliance is broken; telling someone a truncated scan is
unfixable sends them back to their wallet for no reason.

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
