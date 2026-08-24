# PSBT review model

What the appliance shows, and what it checks, before signing a PSBT is safe.

A signing appliance's real job is not signing — it is letting the user **refuse**. The watch-only
wallet is Tier 1 in `docs/threat-model.md`: it actively sends attacker-controlled bytes every
session. So everything the user needs in order to authorise a transaction is derived from the PSBT's
own internal consistency and the appliance's own keys, and never from a label the PSBT asserts.

This document owns the **model**. It deliberately does not own the screen layout — see *Out of scope*
at the end.

## The proof rule

**The appliance shows an output as change only when it can prove it, and treats everything else as
money leaving.**

To prove an output is its own, the appliance reproduces the output's script from its own seed at a
path it recognises. A `PSBT_OUT_BIP32_DERIVATION` field is **input to that check, never the answer**:
the appliance derives the claimed path itself and confirms the resulting script matches the output.
A field that claims a path proves nothing on its own.

## Output categories

Three, never two. Collapsing them is the change-address attack.

| Category | Meaning | How it is shown |
|---|---|---|
| **PAYMENT** | Not ours. | Full address shown; the user verifies it against the recipient. |
| **CHANGE, PROVEN** | Script reproduced from our own key at a recognised path. | Shown as change; address de-emphasised, because eye-verifying it adds nothing. |
| **NOT PROVEN** | Claims to be ours, but we could not reproduce it. | Treated and displayed as a **payment**, with a warning. Never as change. |

**NOT PROVEN degrades to payment, never to change.** That is the safe direction: the failure mode is
a user scrutinising an output that turned out to be their own, not a user waving through an
attacker's.

### The derivation window

Proving an output requires a bounded set of paths to try. The bound is a real trade-off — too tight
and legitimate change from a long-used wallet falls to NOT PROVEN; too loose and the appliance
derives thousands of keys per review on a slow CPU.

A legitimate change index is close to the highest index this appliance can see in the PSBT's own
inputs. So: **derive candidates from index 0 to (highest index appearing in the PSBT's inputs + 20),
capped at an absolute ceiling**, on both the change and the receive chain.

A path outside that window is **not** accepted merely because the PSBT asked for it — otherwise the
attacker chooses the window. Such an output falls to NOT PROVEN, which is the safe direction.

## What blocks signing

**Refuse. No override, no confirmation button.**

- **UTXO data missing for any input.** Without it the fee is unknown, and an unknown fee is an
  unbounded loss. For taproot it is also simply impossible — see below.
- **An input the appliance cannot sign.** Sign nothing rather than partially: a partially-signed PSBT
  invites a retry loop nobody is tracking.
- **Network mismatch** against the appliance's current network.
- **Any sighash flag other than `SIGHASH_ALL`,** on any input. The flags change what the signature
  commits to, and no review screen can honestly explain that to a stranger in the moment.
- **A PSBT that fails to parse, or is internally inconsistent.**

The refusal list is short and absolute on purpose. **An override path is a trained reflex within
three uses** — if a condition is dangerous enough to stop, it is dangerous enough to have no button.

## What warns

The user may proceed.

- **Fee above a sane threshold** — a share of the amount sent, or an absolute rate ceiling.
  Legitimate high-fee spends exist, so refusing outright would be noise.
- **An output paying an address never seen before.** True of most payments; worth stating anyway.
- **A spend consuming the entire balance.**
- **Any NOT PROVEN output**, per the table above.

## Taproot

BIP86 is in scope, and taproot signing needs the full `witness_utxo` for **every** input, not only
the one being signed, because the sighash commits to all input amounts and scripts.

This makes the "missing UTXO data" refusal **free rather than extra**: segwit v0 needs it to compute
the fee, taproot needs it to sign at all. One rule, two reasons.

It also inflates the PSBT — each input carries its own UTXO, so QR frame count grows with input count
rather than staying near-constant. The measured frame counts belong to
[#4](https://github.com/allisson/aobs/issues/4). If many-input taproot spends prove painful, that is
a fountain-encoding parameter question, not a review-model question.

## Display rules

The trap is showing a 42-character bech32 address in a way that invites checking while making real
checking impossible.

- **Full address, never truncated with a middle ellipsis.** A truncated address is exactly what an
  attacker holding a vanity-prefix collision wants. Break it into fixed-width groups of four so the
  eye can compare positionally against the recipient's copy rather than reading it as a string.
- **Amounts in BTC with all eight decimals, plus the sats figure alongside.** Telling `0.01400000`
  from `0.14000000` at a glance is the most likely misread on this screen.
- **Fee three ways: absolute sats, rate, and as a percentage of the amount being sent.** The
  percentage is the form in which an absurd fee is obvious to a non-expert.

## The headline number

**Total leaving = the sum of outputs not proven to be ours, plus the fee.**

Not sum-of-outputs, which hides the fee. Not sum-of-inputs, which counts change as a loss and would
show a large number for a small payment funded by a big UTXO — the sort of thing that trains users to
ignore the number.

Shown with its composition visible (payments subtotal + fee = total), so the figure is checkable
rather than asserted. It counts **proven** change only, so a NOT PROVEN output counts as leaving.

Note what that gives for free: **an attacker's fake-change output raises the headline number**, so
the change-address attack surfaces in the one figure the user is most likely to read.

## The review flow

A flow that trains the user to mash through is worse than no review at all.

- **No per-output confirmation stepper.** That is precisely the mash-trainer: the user learns the
  sequence and pre-empts it.
- **One review screen showing every output**, scrollable if it overflows, with the totals and fee
  **pinned** so they can never be scrolled off.
- **One confirmation**, and it **restates** the total leaving and the fee rather than asking "sign?"
  about something off-screen.
- **Scroll-to-end enforced.** If the outputs do not fit, show the count and require the user to reach
  the end before the confirm unlocks. An unseen output is never authorised.
- **The confirm keystroke is not `enter`** — it must be something the user cannot hit by momentum.

## Out of scope for this document

The **screen layout**. The UI surface is settled ([#3](https://github.com/allisson/aobs/issues/3): a
framebuffer TUI) and the prototype carries a stub layout, but a real layout depends on the
failure-and-error states and the seed-entry flow, both still open. Pinning pixel-level layout here
would only be rewritten by whoever settles those.
