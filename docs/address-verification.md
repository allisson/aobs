# Address display and verification

How the user checks that an address their watch-only wallet is showing them really belongs to their
wallet.

There are two jobs here and they deserve different mechanisms: **verifying an address before receiving
funds**, which happens often and is adversarial, and **verifying the descriptor export landed intact**,
which happens once at setup.

## Derivation is not the constraint

Measured before designing around a budget that turns out not to exist: **200 P2WPKH addresses derive in
47 ms with embit** (0.24 ms each), 200 P2TR in 44 ms — on arm64, Python 3.13.

The active secp256k1 backend was not pinned down, so treat the figure as optimistic. Even at a 10×
penalty on old amd64 hardware, a 400-address search stays well under a second. **That changes what the
search window can be**, and the window below is chosen on correctness grounds rather than cost.

## Scan and prove — the flow

**The user scans the address; the appliance proves it. The list is the fallback, not the flow.**

The user holds a phone showing a receive address, nearly always as a QR. The appliance already has a
camera, `zxing-cpp` and the derivation machinery, so it can answer a question rather than present
evidence: **this is yours, at `m/84h/0h/0h/0/7`** — or it is not.

**This is #11's proof rule applied to the receive side, and it is the same adversary.** #11 established
that the appliance must never trust what the watch-only wallet asserts about an output being ours. A
compromised watch-only wallet displaying an attacker's receive address is the exact mirror of the
change-address attack — and eye-comparing 42 bech32 characters is the defence #11 already judged
inadequate, which is why it banned middle-ellipsis truncation and grouped characters in fours.

Machine-checking removes the human from the comparison entirely. That is strictly better than making
the comparison prettier.

### What is scanned

**Both `bitcoin:` URIs and bare addresses. Only the address is used; every parameter is ignored.**

A BIP21 URI can carry `amount`, `label` and `message` — all attacker-controlled strings arriving over
the QR channel, which is the Tier 1 surface #11 named.

**Nothing here acts on them and nothing displays them.** There is no transaction being built and no
decision they could inform. Rendering a `label` would be the worst version: attacker-chosen text placed
beside an address the user is deciding to trust, which is a persuasion channel, not information. It is
also exactly where #3's escape-injection rule bites, and never rendering the field is the cheapest way
to satisfy it.

The parser is strict about the address and lenient about the rest: unknown or malformed parameters are
dropped rather than raised, so any URI whose address parses is a usable scan.

### Script type needs no toggle

**The prefix already says which.** `bc1q` is a v0 witness program (BIP84, P2WPKH); `bc1p` is v1
(BIP86, P2TR). The script type is unambiguous from the string, so verification searches only the
relevant tree — halving the work for free.

A toggle would be a control that exists solely to restate what the appliance already knows, and one
more thing to set wrong.

### The search window

**0 to 200 on both chains, searched eagerly, extendable in blocks of 200 by the user.**

The standard gap limit of 20 is the wrong number for this job: a gap limit governs how far a wallet
scans for *history*, whereas here the user holds an address their own wallet just produced, which may
sit past a run of unused ones.

**The window is never extended by anything the address itself says** — #11's rule restated. An attacker
choosing the window is the failure mode. The user extends it, deliberately, and can see that they did.

## The three verdicts

Deliberately parallel to #11's three output categories, using the same vocabulary.

| verdict | meaning | what is shown |
|---|---|---|
| **Proven yours** | Script reproduced from our own key at a recognised path. | Leads with the **path**; address de-emphasised. |
| **Not found** | No match within the searched window. | Says exactly that. Two next steps, no default. |
| **Wrong network** | A testnet/regtest address on a mainnet wallet, or the reverse. | Its own message. No search offered. |

### "Not found", never "not yours"

**This is the most important wording in this document.** The two causes are indistinguishable to the
appliance: an attacker's address, or a legitimate address past the window. Saying *not yours* to the
second user is a false alarm that teaches people to disbelieve the check; saying *not found* to the
first understates a real attack.

So the screen states what happened — **searched 0–200 on both chains, no match** — and offers two next
steps with **no default and no highlighted button**: search further, or treat it as foreign. The
interpretation is the user's, and the appliance does not pretend to hold it.

This is #11's **not proven**, and *not proven* never rounds to either verdict.

### Wrong network is not a miss

A `tb1`/`bcrt1` address on a mainnet wallet is neither an attack nor a near-match — it is the wrong
wallet open or the wrong device in hand, and it is common and recoverable.

Folding it into *not found* would send someone searching deeper for an address that could never match
at any depth. So it gets its own message — **"this is a testnet address; this wallet is mainnet"** — and
no search, because there is nothing to search. It reads the same way as #11's network-mismatch refusal.

## The browsable list

**A distinct second purpose, worth naming: it is the check that the descriptor export landed intact.**
After exporting to the watch-only wallet (#5), the user confirms that wallet derives the same addresses
the appliance does. A mismatch means a corrupted or substituted descriptor — caught once, at setup,
before any funds move.

Twenty at a time, jump-to-index, and a script-type toggle — which this path *does* need, because here
the user is choosing what to look at rather than presenting something to check.

**#11's display rules apply unchanged**: full address, never a middle ellipsis, fixed-width groups of
four for positional comparison. Here the human genuinely is doing the comparing, so the formatting
built for that is the right formatting.

## One consistency rule with #11

When an address has been **proven** by the scan flow, the appliance **leads with the path and
de-emphasises the address** — exactly as #11 de-emphasises proven change.

Inviting someone to eye-verify a string the machine has already proven trains a habit with no value,
and habits with no value are what make the checks that matter get skipped.
