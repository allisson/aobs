# Context

Glossary for the Amnesic Offline Bitcoin Signer. Terms only — no implementation detail, no
decisions. Decisions live in `docs/roadmap.md` and in `docs/adr/`.

## Appliance

The whole shipped thing: the bootable image plus the application it runs. Not "the app" and not
"the ISO" — a claim about the appliance is a claim about both together, and most of this project's
security claims only hold at that level.

## Session

One boot of the appliance, from power-on to power-off. The unit of the appliance's memory: a
Wallet exists for exactly one Session and no state crosses the boundary between two of them.

## Amnesic

The property that no Session leaves anything behind. Never a single guarantee: the word covers
three separate ones — nothing written to a persistent medium, nothing recoverable from RAM after
power-off, and nothing recoverable from RAM during the Session by another process. They hold at
different strengths, so a sentence using "amnesic" without saying which one it means is not yet a
claim. `docs/threat-model.md` states each.

The three hold at different strengths and the words for those strengths are fixed here. **Structural**
means the mechanism does not exist and the claim cannot be violated: no filesystem beyond tmpfs and
pseudo-filesystems is mounted, because the whole rootfs is the initramfs and there is nothing to mount
from; and exactly one userspace process exists, so there is no other process to read from. **Absence**
means the mechanism is not in the image: no block device enumerates because no storage driver ships,
which is weaker — an adversary already executing code on the appliance can defeat it, and Debian's
kernel does have a block layer. Only the second guarantee — after power-off — is **best-effort**, and
none of the three is byte-zeroing. A sentence using "amnesic" without naming which strength it means
is not yet a claim.

## Boot medium

The USB stick or disc the appliance is booted from. It is **not** a data path: it is read by
firmware before Linux starts and never read again, so it can be physically removed for the rest of
the Session. Do not call it storage — nothing is ever written to it, which is what makes pulling it
out the cheapest check of the amnesia guarantee.

## Offline

The appliance's network property: **no network module and no network configuration tool is present in
the image** — `kernel/net` and `drivers/net` are deleted from the modules tree and no `iproute2`,
`ifupdown`, `wpasupplicant`, `curl`, `wget` or `ssh` is installed. An **absence** claim, not a
structural one: Debian's kernel has a network stack, and an adversary already executing code on the
appliance could in principle reach it.

Do not say "disabled". Nothing is turned off — there is nothing there to turn off, and "disabled"
promises a switch someone could flip back. A `modprobe` blacklist exists as a second line and is
never what the claim rests on. The stronger reading — no network stack in the kernel — was true of
this project's Alpine ancestry and is **no longer true**; see
`docs/adr/0001-debian-base-and-stock-kernel.md`. The weaker one — an interface merely never brought
up — was never what the word meant here.

## Adversary tier

The rank an adversary holds in `docs/threat-model.md`, and the unit in which this project promises
anything. **Tier 1** is defended with a testable defence, **Tier 2** is acknowledged with stated
limits and explicitly not defended, **Tier 3** is accepted risk with no defence implied. Naming an
adversary without its tier says nothing: "we considered it" and "we stop it" are different
statements, and the tier is what separates them.

## No data path

The appliance's transport claim: **no block device, no filesystem, and no network interface is
ever mounted or brought up; USB is permitted for exactly two device classes, HID and UVC, and no
device is authorized once the appliance is up.**

The mounting half is structural; the driver half is a Module allowlist, which is absence. Both halves
are stated at their own strength in `docs/threat-model.md`.

The blanket phrasing "no USB" is wrong and must not be used — the keyboard is a USB device and so
is the camera, and the kernel enumerates and binds a driver to both. Two classes, not one: HID
carries mnemonic and passphrase entry, UVC is the QR channel's only inbound route. Storage,
networking, audio, printer, and serial classes are refused.

"USB is restricted to the HID class" was the earlier wording and it was **false** — a webcam is
USB *Video* Class. Do not reintroduce it. The mechanism, the tests, and the stated limits live in
`docs/threat-model.md`; this entry defines only the term.

## Claim strength

Which of three things a security sentence in this project is asserting, and the word is mandatory
wherever the distinction could matter. **Structural**: the mechanism does not exist, so the claim
cannot be violated — checkable, and not defeatable by code execution on the appliance. **Absence**:
the mechanism is not in the image — checkable by listing a directory, and defeatable by an adversary
who already runs code here. **Best-effort**: neither, and stated as a limit rather than a promise.

Since the base OS is Debian and the kernel is Debian's, several claims that were structural in this
project's ancestry are now absence. A sentence that omits the strength is not yet a claim, and
restating an absence claim as structural is a defect rather than a wording preference.

## Module allowlist

The explicit list of kernel modules the image keeps — framebuffer/DRM, `uvcvideo`, `usbhid` and their
dependencies — with everything else deleted from the modules tree at build time, `kernel/net`,
`drivers/net` and every storage driver included. It is the mechanism behind the current *Offline*
claim and behind half of *No data path*, at **absence** strength.

The `modprobe` blacklist beside it is a second line and is **never** the claim: a blacklist is a
policy, and the allowlist is a fact about what is in the image. Say "the module is not present",
never "the module is blocked".

## QR channel

The only data path in or out of the appliance. Inbound is a webcam reading QR codes; outbound is
QR codes rendered on the screen. Both directions may need multiple frames. A "QR channel" claim
is about the *channel*, not about any one format carried over it.

## Framing aid

The coarse live image shown while the user points the camera at a QR code. It answers *is the code
in frame*, and nothing else — the console's grey ramp and cell grid put it far below the module pitch
of the codes being read, so it can never answer *is the code in focus*. Never call it a preview: the
word promises focus feedback the appliance does not have, and a user who moves the phone to fix a
blur that was never real is being misled by our vocabulary.

## Slot map

How a scan in progress is shown: one cell per part of the incoming message, filled once that part
has arrived and hollow while it has not. It is never a bar, and the reason is the encoding — the
parts do not arrive in order, so a bar fills, stalls and jumps at exactly the moment the transfer is
working, while holes filling in is what is actually happening. Above the point where one cell per
part no longer fits a row, the fraction stands alone rather than one cell standing for a range.

## Keymap picker

The first screen of a Session, shown before any secret exists: choose the console's keyboard layout,
and prove the choice is right by typing on it. It exists for the Passphrase and for nothing else —
Mnemonic words and Export password words are `a-z` and survive almost any Latin layout, while a
Passphrase is arbitrary text and a wrong layout turns it silently into a Wallet that cannot be
reopened. The proof is the echo, not the list of names.

## Failure screen

The one shape every refusal, every wrong-QR message and every *not found* is drawn in: what
happened, next steps carrying no default and no highlighted button, and a short stable **condition
name**. The condition name is a name, not a code and not a stack location — it is what a user can
carry into a bug report typed on a different machine, and it is deliberately the only thing a
failure lets off the appliance.

## Global keys

The three keys reserved identically on every screen: `esc` backs out without acting, `F12` powers
off, and the confirm key is per-screen and never `enter` and never `esc`. Reserved means no screen
may redefine them — a user who learned `esc` means *back* must never meet a screen where it means
*proceed*. A screen may bind keys of its own beyond these; those are **per-screen keys**, and they
are settled in that screen's document rather than globally. What each screen prints beside `esc`
varies with what leaving it costs; the key's meaning does not.

## Wallet

A single-sig BIP32 keychain derived from a Mnemonic and an optional Passphrase, held in RAM for
one Session. Always single-sig; a multisig keychain is not a Wallet in this project's vocabulary
and is out of scope.

## Mnemonic

A BIP39 word sequence. 24 words when the appliance generates one; 12, 15, 18, 21, or 24 words
when the user imports one. The asymmetry is deliberate: generation has no reason to offer less
than maximum, import must accept what exists in the world.

## Passphrase

The BIP39 passphrase, the optional 25th-word secret that turns one Mnemonic into a different
Wallet. Distinct from the **export password**, which protects an Encrypted wallet QR and is
never the same thing — do not let either term stand in for the other.

## Read-back

Typing a set of words back into the appliance from the paper just written, and being refused until
they match. Performed on all of the words and never on a sample: sampling three of eight misses a
single mistranscribed word most of the time. It checks **the paper**, not the words — the appliance
already holds the correct ones — and nothing else in the session ever checks the paper.

## Master fingerprint

The four bytes BIP32 derives from a Wallet's root key, shown as eight hex characters. The
appliance's confirmation that a Passphrase was typed as intended: the same Mnemonic with a
different Passphrase gives a different fingerprint. On a wallet made here there is nothing to
compare it against, which is a thing the appliance says rather than papers over.

## Encrypted wallet QR

A Wallet exported as a single QR code, encrypted under an export password. The export password
is eight words drawn from the EFF large wordlist — about 103 bits, which is what actually protects
the export. The words are run through Argon2id, but the stretching is defence-in-depth, not the
protection: do not describe the KDF as what keeps the wallet safe. The QR never carries the
Passphrase, so it is not by itself a complete backup.

## Export password

The eight EFF large-wordlist words that protect an Encrypted wallet QR. Always machine-generated at
full entropy and never user-chosen — a self-chosen one is not a weaker Export password, it is not one.
Distinct from the **Passphrase** in both what it protects and who picks it, and the two must never be
used interchangeably.

## Proof rule

The appliance shows an output as change only when it can **prove** it — by reproducing the output's
script from its own key at a path it recognises. A derivation field in the PSBT is input to that
check, never the answer. Everything unproven is money leaving. Say "proven change", never just
"change", whenever the distinction could matter.

## Output category

One of exactly three verdicts the appliance reaches about an output of a PSBT: **payment** (not
ours), **proven change** (script reproduced from our own key), or **not proven** (claims to be ours,
could not be reproduced). Two categories is the change-address attack; the third exists so that
"we could not prove it" never gets rounded to "change".

## Not proven

The third Output category, and the one with a rule attached: it is displayed and counted as a
**payment**, with a warning. It must never be described as change in prose, in code, or on screen —
the whole point of the term is that it degrades in the safe direction.

## Watch-only wallet

The untrusted counterparty across the QR channel: Sparrow, Blockstream App/Green, or Blue Wallet,
holding the exported xpub, building unsigned PSBTs, and broadcasting signed ones. "Untrusted" is
load-bearing — the appliance derives everything it shows the user from the PSBT and its own keys,
never from what the watch-only wallet asserts.

## Reproducibility contract

The stated, checkable claim about which facts of a build environment do not reach the bytes of
`bitcoin-signer-amd64.iso`. Not "the build is reproducible" — the word alone promises nothing. The
contract is a list of environment facts that must not matter, so that a stranger who rebuilds from
the same commit and gets a different hash has found a defect rather than a difference of opinion.

## Input archive

Every byte the build consumes that the build did not write: the two `.deb` closures — appliance and
harness — resolved at the pinned `snapshot.debian.org` timestamp, and the kernel package among them.
Named as one thing because it is fetched, verified and published as one thing — the archive is what
makes a release rebuildable after the upstream that served those bytes has stopped serving them.

**Every member is a function of the package set**, which is what lets the archive itself be
reproducible. A byte upstream can rewrite on its own schedule — a rolling package index is the worked
example, and a pinned snapshot is what removes it — is not an input the archive can hold, because
holding it makes two fetches of the same package set produce two different archives.

## Source archive

The corresponding source for every copyleft-touched package the input archive redistributes: each
Debian source package — `.dsc`, orig tarball and debian tarball — at the exact version that built the
binary, taken from the same pinned snapshot. Published beside the input archive as its own release
asset.

**It is an accompaniment, not an input.** No build reads a byte of it — which is why it is a second
archive with a second list rather than a larger first one. What makes it the *corresponding* source is
the pinning: the binary's own metadata records its source package and version, the snapshot serves
exactly that version, and the `.dsc` checksums verify the rest.

## Witness build

An independent rebuild of a release by someone other than the builder, published so that a third
party can see the two hashes agree. Not a signature and not an approval: a witness asserts only
that the same inputs produced the same output on a machine the builder does not control, which is
the single observation that turns a reproducibility claim into a checkable one.

## Manifest

The plain-text, line-oriented file a release signature covers. It names the release, the commit, the
inputs, and the sha256 of every file published beside it. The manifest is what is signed and the ISO
is not, and the reason is one sentence: a signature over the ISO says who vouches for those bytes,
while a signature over a file that *names the inputs* also says which inputs produced them — which
is what an independent reproduction needs.

## Attestation

A statement by an identified party about an artifact, which a reader can check without trusting the
artifact. A signed manifest is an attestation. **The version row the appliance shows on its first
screen is not one** — it is an identification aid, self-reported by an image that could have been
modified, and the distinction is load-bearing everywhere the row is described.

## Advisory

A signed, dated entry in `ADVISORIES.txt` saying that a released version could have produced a wrong
or unsafe result its user could not have seen. Distinguished from a release note by one test — *could
this have cost someone money without them noticing* — and from most advisory formats by one field:
whether upgrading is sufficient, or whether keys generated on the affected build are permanently
compromised and the funds must move.

**An empty list of advisories is not an attestation either.** It reports that no qualifying finding
reached the maintainer; it says nothing about whether one exists, and nobody outside this project has
looked. The test that decides what qualifies does not vary with which release is current.

## Pre-trust release

A release whose published claim is deliberately lower than the project's own bar, because named
evidence for the higher one does not exist yet. It is a statement about what has been *observed*,
never about what has been *found*: "nobody outside this project has rebuilt this image" is
pre-trust, "we found a flaw" is an advisory, and conflating them makes both unreadable. A pre-trust
claim carries the conditions that retract it, or it becomes permanent by accident.

## Boot-checklist run record

The record that the boot checklist was run, on which machine, and what each item answered — one per
release, published beside the ISO. The checklist is the *procedure*; the run record is the
*evidence*, and only the second one is a thing a stranger can check. It is an attestation: signed,
naming an identified operator and an identified machine. Its verdicts are *pass*, *fail* and
*deviated*, and the third is the load-bearing one — it marks where a release's evidence stops
matching the checklist's claim, which a missing row or a generous *pass* would hide.
