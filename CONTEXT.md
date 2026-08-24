# Context

Glossary for the Amnesic Offline Bitcoin Signer. Terms only — no implementation detail, no
decisions. Decisions live in the wayfinder map and in `docs/adr/`.

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

The first of the three is the strongest and is unconditional: no block device exists on the running
appliance, and the Boot medium can be removed once it is up.

## Boot medium

The USB stick or disc the appliance is booted from. It is **not** a data path: it is read by
firmware before Linux starts and never read again, so it can be physically removed for the rest of
the Session. Do not call it storage — nothing is ever written to it, which is what makes pulling it
out the cheapest check of the amnesia guarantee.

## Offline

The appliance's network property: no network stack and no network drivers exist in the running
kernel. Weaker readings — an interface merely never brought up — and stronger ones — radio
hardware unpowered — are both *not* what the word means here, and neither may be substituted for
it.

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

The blanket phrasing "no USB" is wrong and must not be used — the keyboard is a USB device and so
is the camera, and the kernel enumerates and binds a driver to both. Two classes, not one: HID
carries mnemonic and passphrase entry, UVC is the QR channel's only inbound route. Storage,
networking, audio, printer, and serial classes are refused.

"USB is restricted to the HID class" was the earlier wording and it was **false** — a webcam is
USB *Video* Class. Do not reintroduce it. The mechanism, the tests, and the stated limits live in
`docs/threat-model.md`; this entry defines only the term.

## QR channel

The only data path in or out of the appliance. Inbound is a webcam reading QR codes; outbound is
QR codes rendered on the screen. Both directions may need multiple frames. A "QR channel" claim
is about the *channel*, not about any one format carried over it.

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

## Encrypted wallet QR

A Wallet exported as a single QR code, encrypted under an export password. The export password
is eight words drawn from the EFF large wordlist, stretched with Argon2id.

## Watch-only wallet

The untrusted counterparty across the QR channel: Sparrow, Blockstream App/Green, or Blue Wallet,
holding the exported xpub, building unsigned PSBTs, and broadcasting signed ones. "Untrusted" is
load-bearing — the appliance derives everything it shows the user from the PSBT and its own keys,
never from what the watch-only wallet asserts.
