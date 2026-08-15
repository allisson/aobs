# ADR-0008 — `random.trust_cpu=off`, and manual entropy XORed rather than hashed

- **Status**: accepted
- **Date**: 2026-08-15
- **Decides**: [#8 — Entropy policy: system CSPRNG at live boot, and manual entropy](https://github.com/allisson/aobs/issues/8)
- **Findings**: `docs/research/04-amnesic-boot-layer.md`

## Context

The generated seed is the single point of total failure, and the prior-art survey is blunt that our
entropy story is the weakest of the six devices on the merits: RDRAND plus a kernel pool with no
accumulated history, against Passport's avalanche diode and Coldcard's three independent hardware
RNGs.

The kernel facts, read from `random.c` rather than assumed: `random_init_early()` credits 512 bits
from RDSEED/RDRAND against a 256-bit `POOL_READY_BITS` threshold **before the first userspace
instruction**, so `getrandom(2)` never blocks on a live system with no seed file. `random.trust_cpu`
is on by default and is no longer a build option. Crucially, `extract_entropy()` pulls RDSEED into
**every** extraction, unconditionally — `trust_cpu` has no bearing on that.

## Decision

**Boot with `random.trust_cpu=off`.** That withdraws the initialisation credit and makes the pool
fill from timing jitter instead, while the CPU RNG continues to be mixed into every extraction. **The
CPU RNG is still used; it just never determines readiness on its own word.** We already decline to
trust this machine's firmware, and trusting an opaque instruction from the same vendor to solely
determine the state that generates a wallet seed was the inconsistency.

**Manual entropy is offered, mixed only, never a replacement — and combined by XOR:**

```
supplement = SHA-256( "aobs/seed-entropy/v1" ‖ framed(camera_luma) ‖ framed(dice_ascii) )
entropy    = csprng_32 XOR supplement          // skipped entirely when neither is present
```

Every surveyed device concatenates and hashes. That is only never-worse **under the random-oracle
assumption**. XOR with any value independent of the CSPRNG output preserves uniformity
**unconditionally**, so "never worse" stops being an assumption and becomes arithmetic — and it cuts
the other way too: against a backdoored CPU RNG whose output the attacker knows, they still face the
full entropy of `SHA-256(dice)`.

Independence holds because nothing in this path is attacker-visible: the user rolls the dice, we
capture the frame, and neither can be chosen after seeing `csprng_32`.

## Consequences

- **Cost: ~1–16 s once at boot** — derived arithmetically from `random.c` with Debian's
  `CONFIG_HZ=250`, **not measured**, and on the release gate's measurement list. The signer blocks on
  `getrandom(buf, len, 0)` behind a visible **"gathering entropy"** state rather than appearing hung,
  and that state is where the dice screen lives — a screen with something to do on it cannot read as
  a hang.
- **No distribution sanity-check, no minimum roll count, no bit counter, no progress meter.** Coldcard
  rejects a die face over 30% and Krux computes Shannon entropy over the rolls *and* their first
  differences; both check because both offer a replacement mode. Under XOR, fifty identical faces is
  a seed exactly as strong as `getrandom` alone. A validator would defend an invariant we do not
  have and would teach the user that the check is what protects them.
- **One line of copy carries the whole model:** *your rolls are combined with the system random
  number generator; they can only add randomness, never remove it.*
- **Never display a running hash of the rolls.** Because we mix rather than replace, the rolls on
  screen are not sufficient to reconstruct the wallet — which is why aobs needs none of Coldcard's
  *"anyone who photographs this hash can recreate your wallet"* warning. A displayed hash would hand
  that property straight back.
- **The camera is an entropy source in its cheapest form**: one frame at seed generation, hashed into
  the mix, skipped silently when absent. It is the only randomness in the machine that does not
  originate with the CPU vendor.
- **Testing is provenance, not statistics.** Coldcard's substituted PRNG passes every cheap
  statistical check, so an on-device randomness self-test is theatre. What ships instead: the seed
  path calls `getrandom` as a **raw syscall** with no crate-level indirection a build change can
  re-resolve, and a **release gate over the actual ISO under QEMU** traces that syscall and asserts
  the wallet's entropy bytes are byte-identical to what it returned, with zero opens of
  `/dev/urandom`.
- The mixing function carries the 98% bar, plus a property test that is the safety proof: **it is
  injective in the `csprng_32` argument for every fixed supplement.**

## Alternatives rejected

- **Trust the CPU RNG for readiness** (the default) — the inconsistency above, for a boot-time
  saving.
- **A dice-only replacement mode** (Coldcard's *"these dice rolls will be the only source of
  randomness"*, SeedSigner's `sha256(roll_string)`) — buys external verifiability against a web tool
  and pays for it by breaking the never-worse invariant and putting a screen in front of the user
  whose photograph is total, silent compromise. **An amnesic device with no PIN and no rate limiting
  ships no mode whose failure is silent and total.**
- **Offering no manual entropy at all** — leaves the weakest entropy story in the field
  unsupplemented.
- **Concatenate-and-hash** — the field standard, and conditional on SHA-256 being a random oracle.
- **`/dev/urandom`, `GRND_RANDOM`, `GRND_INSECURE`, a seed file** — documented as insecure, a no-op,
  never, and the persistence we forbid, respectively.
