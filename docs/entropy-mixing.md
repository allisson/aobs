# Entropy mixing

How system entropy, webcam frames and dice rolls become the 256 bits behind a 24-word mnemonic.

Judged against the *strong entropy* claim in `docs/threat-model.md`: **the final 256 bits are no
weaker than the strongest single contributing source, and no single source can drag them down.**

## The construction

**HKDF-Extract-then-Expand** over a length-prefixed, domain-separated concatenation of the
conditioned sources.

Each source contributes as `label ‖ length ‖ bytes`, so no source can impersonate another's framing
or shift a boundary. Salt is a fixed protocol label; Expand produces 256 bits, which become the
BIP39 entropy.

**XOR is disqualified.** An adversary who controls one input and can observe the others cancels them
outright. Plain concatenate-then-SHA256 would be acceptable *only* with unambiguous framing, which is
what the length prefixes above provide — HKDF is preferred because it is a reviewed standard doing
exactly this job.

Any single adversarial or constant input leaves the others' entropy intact: reversing a hash is the
attacker's only route.

### The kernel CSPRNG is unconditional, by construction

The trap this ticket names — dice *replacing* rather than augmenting system entropy — is closed in
code shape, not by policy: **the kernel CSPRNG is an input with no branch that can omit it.** Dice and
camera bytes are appended. A code path in which dice substitute for system entropy must not be
reachable, not merely discouraged.

## Per-source conditioning

### System

`getrandom()` for 32 bytes. Called with `GRND_NONBLOCK` **first**, so an uninitialised pool becomes a
message rather than a silent hang.

`getrandom()` blocks until the urandom source is initialised, which means a cold boot cannot quietly
hand the appliance weak bytes — the failure mode is a wait, and a wait can be explained.

### Webcam

**Hash whole raw frames, several of them, and make no entropy estimate whatsoever.**

An all-constant frame is rejected as a sanity check on the *hardware*, but the contribution stays
additive either way, so passing or failing that check cannot move the floor.

No pixel statistics, no min-entropy calculation, no buffer arithmetic. This is deliberate: Krux's one
real memory-safety failure was a 49 KB heap overflow **in its camera entropy estimator** (26.08.0).
The estimator is the part that bit them, so this design does not have one.

### Dice

**Hash the ASCII roll string. Never bit-pack.** Both Krux and SeedSigner do this, and it sidesteps
mod-6 bias completely rather than correcting for it.

**99 D6 rolls** is 256 bits (log₂6 ≈ 2.585). Since dice are additive, any count is accepted and the
appliance displays the bits contributed rather than demanding a quota.

## Kernel RNG trust

**Boot with `random.trust_cpu=off` and `random.trust_bootloader=off`.**

Both default to *on*, meaning the kernel will initialise its RNG from RDRAND or a bootloader-supplied
seed alone. Left at the defaults, our floor claim would quietly rest on RDRAND on machines with
little early entropy — contradicting the threat model's statement that RDRAND is never a sole or
direct source.

The cost is that `getrandom()` may block, and this appliance has no disk I/O to generate interrupt
entropy. What it does have is the two device classes #14 permits: a keyboard someone is typing a
mnemonic on, and a camera producing frames — both generate interrupts, the camera generously.

So entropy-consuming work is sequenced **after** user interaction has begun. If the pool is not ready,
the appliance says so plainly — *keep typing, point the camera at something* — rather than freezing.

## What is optional

The system CSPRNG is unskippable by construction. The camera contributes without being asked, and is
present in every session regardless, being the QR channel. **Dice are the only optional source.**

**How dice are described matters, and the usual framing is a lie.** Under the floor claim, dice do
not make the seed stronger — the kernel CSPRNG already sets the floor. Dice add a *source*.

So: **dice protect you if you distrust this machine's RNG.** That is the real reason to roll them and
an honest one. Never "more entropy", never a progress bar filling toward "secure", never a strength
meter. A user who skips dice is not shown a degraded state, because their guarantee is not degraded.

## Verification

Anything the appliance displays about its own mixing is a claim by the same code that would be lying,
and per-source digests do not help — the CSPRNG's bytes are secret, so the user can recompute nothing.

**On screen: facts, not assurances.** Which sources contributed and in what quantity — *system: 32
bytes · camera: 8 frames · dice: 99 rolls* — plus the resulting wallet fingerprint. No entropy
estimate, no score, no reassuring tick.

**Real verification lives in the repo:** this spec plus test vectors, running the mixing function on
fixed adversarial inputs (all-zero camera, constant dice, a stubbed CSPRNG) with asserted outputs, so
anyone can check the construction against the source.

One property is the floor claim expressed as a test, and it is the important one:

> Feed the mixer an adversarial constant for any single source and assert the output still varies with
> the others.

#7 found that every real failure across Krux, SeedSigner and Specter-DIY was plumbing rather than
cryptography — a misused CBC IV, that heap overflow, a lossy iteration encoding. Round-trip fixtures
are where the safety actually lives.
