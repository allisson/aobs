# Threat model and security claims

The standing frame for the Amnesic Offline Bitcoin Signer. Every later design decision is judged
against this document: a decision that weakens a Tier 1 defence, or that quietly promises more than
a claim here allows, is wrong regardless of how convenient it is.

The rigor bar is **publishable appliance** — strangers boot the ISO with real funds. Two rules
follow from that bar and govern everything below:

1. **A claim that cannot be tested is not a claim.** Every promise here is written so that a test,
   a command, or a code reading can contradict it.
2. **Honesty outranks coverage.** Where the appliance cannot defend, it says so plainly and offers
   no mitigation column to blur the line.

## Adversary tiers

The adversaries are ranked into three tiers. The tier *is* the promise: Tier 1 is defended, Tier 2
is acknowledged with stated limits, Tier 3 is accepted risk with no defence implied. Lumping 2 and 3
together would let "we thought about this" read as "we stop this", which is the specific failure this
document exists to prevent.

### Tier 1 — defended, and the defence is testable

**1. The watch-only wallet, feeding a hostile or lying PSBT.** The *primary* adversary: the one
thing that actively sends the appliance attacker-controlled bytes in every session.

- Every figure shown to the user is derived from the appliance's own keys and the PSBT's own
  internal consistency — never from a label the PSBT asserts. Change outputs in particular are
  proven from the appliance's own derivation.
- Malformed, inconsistent, or wrong-network input **refuses**; it never guesses, repairs, or
  proceeds on a best interpretation.
- Testable by construction: adversarial PSBT fixtures (lying change labels, mismatched amounts,
  wrong network, absent inputs) assert refusal or correct display.

**2. A thief of the powered-off machine.** Defended by the amnesia guarantee below: nothing was
ever written, so there is nothing on the medium to take.

**3. A thief of the ISO or the boot medium, untampered.** The image holds no secrets. Defended by
construction.

### Tier 2 — acknowledged, with stated limits. Not "defended"

**4. Evil maid — a tampered boot medium between two boots.** **Not defended.** Reproducible builds
and release signing are out of scope for this effort, and a generic amd64 machine offers no measured
boot or TPM to anchor to. The appliance therefore claims nothing about its own integrity.

*User-side mitigation, the only one that works:* keep custody of the boot medium, and verify its
checksum on a machine you trust **before** booting it. Verification that happens on the possibly
tampered appliance itself proves nothing.

**5. Cold-boot recovery of RAM after power-off.** **Partially mitigated at best.** What the
appliance does: wipes key material on the shutdown path, configures no swap and no hibernation,
and prefers power-off to reboot. What it does not do: defeat DRAM remanence against an attacker who
takes the DIMMs.

**6. Someone in the room, watching the screen or the keyboard.** Inherent to entering a mnemonic
and passphrase on a laptop. Mitigated by UI discipline and explicit warnings, not by cryptography.
Cameras in the room are not defended.

### Tier 3 — accepted risk, no defence

Stated plainly, with no mitigations, because a mitigation note beside these reads as partial
defence:

7. A compromised build host.
8. A malicious CPU, firmware, or management engine.
9. Physical coercion of the user.
10. Supply-chain compromise of embit or of Alpine packages.

**On coercion specifically:** the BIP39 passphrase makes decoy wallets possible, and this appliance
**does not present that as a duress or plausible-deniability feature.** A user who bets their
physical safety on a decoy wallet is betting that the coercer does not know this tool exists and
does not ask "and the passphrase?" — and a published appliance makes that bet worse over time, not
better. Users who want a decoy wallet get one as a consequence of BIP39; the appliance never
advertises it and builds no UI for it.

## What "amnesic" promises

Three separate guarantees at three different strengths. They are worded separately on purpose:
collapsing them is how a reader ends up trusting the weakest one.

### (i) Nothing is written to any persistent medium — promised unconditionally

The core of the term. Testable, all four assertable on a running appliance:

- no block device is mounted at any point in the session;
- the only writable filesystems are tmpfs;
- no swap and no hibernation are configured;
- the boot medium is mounted read-only or copied to RAM and released.

### (ii) Nothing is recoverable from RAM after power-off — best-effort, not guaranteed

See Tier 2 item 5. The appliance does the cheap things and states, in the same breath, that an
attacker holding the DIMMs is not stopped.

### (iii) Nothing is recoverable from RAM during the session by another process — promised structurally

The basis is that there is no other process worth the name: a single workload, no network, no shell
on the console, no untrusted code loaded. The limit, stated: anything running as root can read the
address space, so the claim is **"no other program is present"**, not "the memory is protected from
one".

**This claim is about process lifetime, not about zeroing bytes.** CPython copies `bytes` freely and
cannot reliably scrub them, so *"seed material is wiped from memory as soon as it is used"* is a
claim the appliance cannot keep and must never make. *"Seed material exists only inside a process
that is never dumped and dies at power-off"* is one it can.

## What "offline" promises

**No network stack and no network drivers exist in the running kernel.** Nothing can be brought up,
including by accident or by a future bug.

Rejected as too weak: "no interface is ever brought up" with a stack present — untestable against
code that does not exist yet. Rejected as unpromisable: "no radio hardware is powered" — on a laptop
with soldered WiFi that cannot be honestly claimed, and offering it would invite the user to assume
the chip is dead.

All radios are rfkill-blocked as a **best-effort addition that is explicitly not claimed** as
powered-down hardware.

Testable: no network device exists in the running kernel, and `/proc/net/dev` is absent.

The kernel configuration that delivers this is owned by the boot-pipeline design; this document owns
only the claim.

## What "strong entropy" promises

The promise is a **floor**, not a source: **the final 256 bits are no weaker than the strongest
single contributing source, and no single source can drag them down.**

That fixes the design:

- All sources are hash-combined into one 256-bit output — never selected between, and never combined
  such that a chosen input can cancel another.
- The kernel CSPRNG is a **mandatory** contributor.
- Webcam frames and dice are **optional additive** contributors. The appliance never *requires*
  dice: a user who cannot roll them will invent them badly, which is worse than not having them.
- A webcam feeding a lens cap or a hostile constant frame gets a sanity check that rejects constant
  frames, but its contribution is additive either way, so passing or failing that check cannot lower
  the floor.
- RDRAND is never a sole or direct source.

Explicitly **not** promised: safety when every source is compromised simultaneously.

Testable: feed the mixing function adversarial constant inputs and assert the output still varies
with the remaining source.

## Permitted USB device classes — OPEN, not yet claimed

This document does not yet state what USB device classes the appliance permits, and that is a
known gap rather than an oversight: the glossary's old wording, *"USB is restricted to the HID
class"*, turned out to be false once the webcam was priced — a webcam is USB **Video** Class.

Until [issue #14](https://github.com/allisson/aobs/issues/14) settles the permitted set, its
enforcement mechanism, and the corrected wording, **no claim about USB device classes may be
quoted from this project as settled.** Note that permitting UVC admits a considerably larger
kernel surface than HID alone, reachable by Tier 1 input, so #14 may add or qualify a claim here.

## No boot-time self-verification

The appliance performs **no self-attestation at boot**, and displays no integrity indicator.

With evil maid in Tier 2 and reproducible builds out of scope, any self-check is code the tamperer
also controls: a check that passes proves nothing, and an "integrity OK" message actively misleads.
The verification that does work is the user-side one in Tier 2 item 4 — checksum the ISO on a
machine you trust, before booting it — and that instruction belongs on the boot screen alongside the
appliance's claims.

Adding a real self-check later is cheap if reproducible builds ever come into scope. The harm of
shipping a meaningless green tick is not recoverable.
