# ADR-0010 — One wallet per boot, enforced by a `OnceLock`

- **Status**: accepted
- **Date**: 2026-08-15
- **Decides**: [#25 — Multiple wallets in one session, and what switching means for zeroization](https://github.com/allisson/aobs/issues/25)

## Context

Amnesia is a session property, and "session" had never been pinned down. Three shapes were on the
table: one wallet per boot; one *seed* per boot with the passphrase re-enterable; and full
multi-wallet with one active.

Full multi-wallet was dropped outright — N concurrent secret lifetimes, and a review screen obliged
to prove *which* wallet is signing at precisely the moment its density was spent making the
destination unambiguous.

The argument that decides the rest is **the module-boundary ADR's own admission**: zeroization is
guaranteed by what the types do not implement, and we state plainly that *we do not claim a test
observes a freed page.*

> **Any switch boundary rests on a correctness property the test suite has already conceded it
> cannot verify.**

## Decision

**One wallet per boot. No switch, no unload, no idle timeout. "End the session" *is* shutdown, and
restart is the sanctioned way to reach a different wallet.**

Reboot-to-switch replaces an unverifiable promise with a power cycle plus `init_on_free=1` — a
guarantee we do not have to be right about.

The second argument is independent of cold-boot scope and matters even though cold-boot attacks are
out of the threat model: **with no switch, there is no state in which wallet A's material exists
while wallet B is active.** No later bug — a stray render, a log line, an out-of-bounds read — can
surface the wrong wallet's keys, because that state never exists. **The class stops existing rather
than being defended.**

**The property is enforced by stdlib, not by a test.** Core is stateless pure functions, so it has no
wallet to replace and exposes no unload; the whole thing is a shell-side **`OnceLock`** — set once,
no `take`, no replace. *"There is no second wallet"* becomes a type-level fact, and **the enforcement
and the proof are the same mechanism**: a second `set` returns `Err`.

## Consequences

- **Cost, named and accepted: switching passphrase on the same seed means retyping a 24-word
  mnemonic** — the most laborious action in the product. The middle option existed precisely to buy
  that back, and it is declined in exchange for the one-sentence property *every secret's lifetime is
  exactly one boot*.
- **This closes the question the passphrase ticket deferred: the passphrase cannot change
  mid-session.**
- **Shutdown covers secrets twice, because the mechanisms fail differently.** `ZeroizeOnDrop` (kept
  alive through a crash by `panic = "unwind"`) covers clean exit and panic but not a kernel abort;
  `init_on_free=1` covers the process dying any which way but survives no hard power cut. **No third
  mechanism** — a scrubbing ceremony would imply defending the cold-boot adversary the map declined.
- **No lock screen, no logout, no sign-out.** Locking is meaningless on a device that persists
  nothing, because there is no state to return to.
- **Restart is offered alongside shutdown, explicitly labelled as the way to load a different
  wallet**, which turns the accepted cost from a dead end into a discoverable affordance.
- Both confirm once, with a **press rather than a hold** — an accidental shutdown mid-review is now
  the most expensive accident in the product, and one press is the cheapest guard proportional to it.
- **No idle timeout.** The threat is a present adversary mid-session, which is not defended; the
  false-trigger cost is maximal; and structurally it would be the shell holding a policy about when
  secrets die.
- Creation and import flows run exactly once per boot, so neither needs a re-entry path.
- Carried forward verbatim so nobody later adds a comforting fake: **we do not claim a test observes
  a freed page.**

Two consequences settled later, by
[#35](https://github.com/allisson/aobs/issues/35), which asked what else the session holds:

- **Transactions are not wallets: signing is unlimited per session, but the re-display slot holds
  exactly one — the most recent, overwritten by each new signature.** The reason is this ADR's own
  second argument pointed at a different object. A list of signed transactions on a device with no
  names, no labels and no clock can only be distinguished by amount and destination — the facts the
  outbound screen deliberately omits — so the user would select which transaction to transmit from a
  list they cannot verify, and transmitting B while believing it is A is destination substitution
  arriving at their own hands. One slot means there is nothing to select: **the class stops existing
  rather than being defended.** Named cost: signing A, failing to hand it over, then signing B costs
  a re-scan, re-review and re-sign for A.
- **Nothing is zeroized between transactions, and the absence is deliberate.** Everything that turns
  over is public — the inbound PSBT, the signed transaction, the review model — so a scrub step here
  would buy nothing while reintroducing exactly the unverifiable boundary this ADR rejected. The "no
  third mechanism" rule above extends to it unchanged.

## Alternatives rejected

- **One seed per boot, passphrase re-enterable** — the tempting middle. It buys back the 24-word
  retype and costs the unambiguous secret lifetime.
- **Full multi-wallet with one active** — N lifetimes plus an ambiguity on the signing screen.
- **A "close wallet" action returning to the start screen** — a switch wearing a different name.
- **An idle timeout** — defends an undefended threat while punishing a user who takes a phone call.
