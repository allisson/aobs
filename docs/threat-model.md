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

**7. A malicious USB device impersonating a permitted class.** **Acknowledged, not defended.** The
appliance permits exactly two USB class drivers and authorizes no new device once it is up (see
*Permitted USB device classes* below), but a purpose-built device asserting that it is a keyboard
or a camera is admitted **by design** — that is what permitting the class means. `uvcvideo` in
particular parses descriptors and streaming payloads from the device, and the appliance does not
claim to withstand an attack on the HID or UVC driver itself.

Reaching this requires physically inserting hardware, which is why it sits here and not in Tier 3:
unlike a malicious CPU there are real mitigations, and they are taken.

Note the distinction this draws, which was previously blurred: the **watch-only wallet** sends
hostile *bytes* and is Tier 1, defended. The **camera** could be hostile *hardware* and is Tier 2,
not defended. Same QR channel, two different promises.

### Tier 3 — accepted risk, no defence

Stated plainly, with no mitigations, because a mitigation note beside these reads as partial
defence:

8. A compromised build host.
9. A malicious CPU, firmware, or management engine.
10. Physical coercion of the user.
11. Supply-chain compromise of embit or of Alpine packages.

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

The core of the term, and it is promised in its strongest form: **no block device exists on the
running appliance at all, and the boot medium can be physically removed once the appliance is up.**

The mechanism is that the entire system ships inside the initramfs, which the firmware loads before
Linux starts. The kernel therefore contains **no block or storage drivers and no loadable modules**,
so after handoff the medium is never read again, and there is no `usb-storage`, `sr_mod`, or loop
device for anything to be mounted from. There is also no modloop: an all-built-in kernel has no
modules to load from a squashfs.

This wording is a correction. It previously read "no block device is mounted at any point in the
session", which was **false** for a stock Alpine LiveCD: Alpine has no `copytoram` boot option, and
its `modloop` service loop-mounts the kernel modules squashfs from the boot medium and keeps it
mounted for the whole session. The claim was written from how it ought to work rather than how it
does.

How to check it, in ascending order of trust required:

1. **Remove the medium.** Boot, pull the stick out, then complete a full sign. This requires
   trusting nothing and no tooling, and it belongs in the published README.
2. **Image the medium and diff it.** `dd` the stick before booting, run a full session, power off,
   image again: the two must be byte-identical. This is the direct proof that nothing was written.
3. **On the running appliance:** `/proc/mounts` shows only tmpfs, proc, sys, dev, devpts and shm —
   nothing block-backed; `/proc/swaps` is empty; and no `/dev/sd*`, `/dev/sr*` or `/dev/loop*` node
   exists, because no driver exists to create one.
4. **Kernel config inspection** for the negative claims: no swap, no block drivers, no modules.

**The fallback, named so it cannot be shipped silently.** The cost of this architecture is that the
firmware must load an initramfs containing the whole system. If the measured image turns out too
large for common firmware, the fallback is to keep a storage driver for boot, copy to RAM, unmount
and eject — and that weakens the claim to *"no block device is mounted after boot completes"*. Taking
the fallback **requires rewording this section downward**; the boot pipeline may not adopt it while
these words stand.

**Minimum RAM.** The floor is the unpacked rootfs in tmpfs, plus the kernel, plus the app's working
set (a PSBT, camera frames, the Python heap). The only measured inputs so far are `python3` at
34.79 MiB and the capture/decode stack at +1.35 MiB; the floor itself is **unmeasured** and is pinned
by the boot-pipeline work, not asserted here. The appliance **checks available RAM at boot and
refuses to start with a clear message below the floor**, rather than failing mid-session with a
wallet loaded.

Note that `modloop_verify`, Alpine's signature check on the modules squashfs, verifies against a
public key on the same medium — exactly the meaningless self-check rejected under *No boot-time
self-verification*. It does not exist under this architecture, and it must not be presented as
integrity verification if the fallback is ever taken.

### (ii) Nothing is recoverable from RAM after power-off — best-effort, not guaranteed

See Tier 2 item 5. The appliance does the cheap things and states, in the same breath, that an
attacker holding the DIMMs is not stopped.

What it does at shutdown, and nothing more: **forces power-off rather than reboot**, so there is no
warm handoff to another OS that could read RAM; runs with **no swap and no hibernation**, so nothing
was ever paged out; and makes a **best-effort wipe of the derived key material the app itself
holds** — labelled best-effort, never as "RAM is cleared".

**A full RAM overwrite is rejected as theatre.** It would take a long and visible time on a
multi-gigabyte machine, it cannot reach page cache, freed allocations, or tmpfs pages, and CPython
cannot scrub its own copies anyway — which is why claim (iii) is worded as process lifetime rather
than byte-zeroing. It would buy almost nothing over the concession already made in Tier 2 item 5,
while making the appliance look like it defends something it does not.

### (iii) Nothing is recoverable from RAM during the session by another process — promised structurally

**Seed material exists only inside the single userspace process on the appliance — there is no
second process to read it, no core dumper in the kernel to write it out, and the process dies at
power-off.**

This wording is **stronger than the one first published here**, and deliberately so: it was written
before the boot pipeline was settled, and #12 changed the facts. The appliance runs exactly one
userspace process, PID 1, which is the application. The earlier hedge — "no other process *worth the
name*" — described a judgement; this describes a structure, and a stranger can check it by eye with
`ls -d /proc/[0-9]*`.

Each clause is separately testable: `CONFIG_COREDUMP=n` and `CONFIG_PROC_KCORE=n` are asserted at
build time, and the single-process fact is visible on the running appliance. The limit stays what it
was: anything running as root could read the address space, so the claim is **"no other program is
present"**, not "the memory is protected from one".

**None of that is byte-zeroing, and strengthening the sentence above must not be allowed to blur
it.** CPython copies `bytes` freely and cannot reliably scrub them, so *"seed material is wiped from
memory as soon as it is used"* is a claim the appliance cannot keep and must never make. The copies
are uncounted; what is promised is the process boundary and the process lifetime. `docs/secret-hygiene.md`
states what follows from that.

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

## Permitted USB device classes

**The kernel contains exactly two USB class drivers: `usbhid` and `uvcvideo`.** No driver for mass
storage, MTP, CDC/NCM/RNDIS networking, audio, printer, or USB-serial is compiled in, and no modules
are loadable — a device of any such class enumerates and then sits inert, because nothing binds to
it. **Once the appliance's own keyboard and camera have been enumerated, `authorized_default` is set
to `0` on every root hub**, so any device inserted later in the session is not authorized and no
driver probes it.

Two classes, not one, and each is load-bearing. HID is the only route for mnemonic and passphrase
entry. UVC is the only route for inbound data at all: a PSBT is 1.2–1.6 KB of base64 across several
fountain frames, so keyboard-only entry would mean a human transcribing it by hand, and every other
inbound path — storage, network, serial — is excluded by the *no data path* and *offline* claims
above. The camera is not a convenience.

Three tests can contradict this claim:

- the built-in driver list contains `usbhid` and `uvcvideo` and no other USB class driver, and module
  loading is unavailable;
- a USB mass-storage device inserted mid-session produces no block device and no driver bind;
- `authorized_default` reads `0` on every root hub once the appliance is up.

Three limits, stated because a careful reader finds them anyway:

- **Hubs are permitted.** The keyboard and camera may arrive through one, so hubs cannot be refused.
- **A device impersonating HID or UVC is admitted by design.** That is Tier 2 item 7, not a gap in
  this claim — permitting a class means admitting anything that asserts it.
- **The flip is not instantaneous.** Between power-on and the moment `authorized_default` is set to
  `0`, an inserted device would be authorized. That window is seconds long and requires someone
  physically inserting hardware during boot, but "no device is authorized after boot" must not be
  read as "no device is ever authorized".

The flip happens **after the appliance's own devices are enumerated and before the first secret is
entered** — before the mnemonic or passphrase prompt, not merely before signing. The strongest thing
a hostile HID device does is type, and what deserves protection from a typing attacker is the wallet
being created or imported, not only the transaction being signed.

Rejected alternatives, and why:

- **udev rules.** The kernel binds a driver during enumeration, so a userspace rule generally acts
  after the thing it is meant to prevent. A claim resting on udev would be close to decorative.
- **Booting with `usbcore.authorized_default=0`** and authorizing our own two devices explicitly.
  This closes the boot window, but it requires a userspace policy deciding *which* device is the real
  keyboard — a harder problem than the one it solves, and it puts a trust decision where we cannot
  test it.

The kernel configuration that delivers this belongs to the boot-pipeline design; this document owns
only the claim.

## No boot-time self-verification

The appliance performs **no self-attestation at boot**, and displays no integrity indicator.

With evil maid in Tier 2 and reproducible builds out of scope, any self-check is code the tamperer
also controls: a check that passes proves nothing, and an "integrity OK" message actively misleads.
The verification that does work is the user-side one in Tier 2 item 4 — checksum the ISO on a
machine you trust, before booting it — and that instruction belongs on the boot screen alongside the
appliance's claims.

Adding a real self-check later is cheap if reproducible builds ever come into scope. The harm of
shipping a meaningless green tick is not recoverable.
