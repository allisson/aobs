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

The property that no Session leaves anything behind. What "anything" and "behind" precisely mean
is the subject of the amnesia guarantee (see the map) — the term is defined here so that loose
uses can be caught, not so the guarantee can be assumed.

## No data path

The appliance's transport claim, stated precisely: **no block device, no filesystem, and no
network interface is ever mounted or brought up; USB is restricted to the HID class.**

The blanket phrasing "no USB" is wrong and must not be used — seed and passphrase entry is a USB
keyboard, which the kernel enumerates and binds a driver to. HID input is the one permitted USB
class; storage, networking, and everything else are refused. Stated this way the claim is
testable, which the blanket version is not.

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
