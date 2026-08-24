# Outbound QR emit parameters

What the appliance actually puts on screen when it shows a signed PSBT.

[#4](https://github.com/allisson/aobs/issues/4) fixed the format — `ur:crypto-psbt`, UR v2,
multi-part, and never `ur:psbt`. This document fixes our own emit parameters: QR version, error
correction, fragment size, frame rate, and how long the animation runs.

## Two measured facts it rests on

**Uppercased UR fits QR alphanumeric mode entirely.** The alphanumeric charset includes `-`, `/` and
`:` — the only non-alphanumeric characters a UR part contains. Worth about 1.55× over byte mode, for
nothing.

**Capacity, in alphanumeric characters**, measured by binary search rather than recalled from a table:

| version | modules | ECC L | ECC M | ECC Q | ECC H |
|---|---|---|---|---|---|
| 13 | 69×69 | 619 | 483 | 352 | 259 |
| **15** | **77×77** | **758** | 600 | 426 | 321 |
| 17 | 85×85 | 938 | 734 | 531 | 408 |

## Version 15, and there is no headroom

**77×77 modules**, which is #3's figure: 85 columns × 43 rows of half-blocks, inside a 1024×768
console's 128×48, with five rows left for chrome.

Going bigger was checked and rejected. **Rows bind, not columns**: 48 character rows give 96 module
rows, minus an 8-module quiet zone leaves 88 — and version 17 needs 85 modules plus quiet ≈ 46.5
character rows. It fits only by consuming every row of chrome: the frame counter, the progress line,
the instruction. Trading all on-screen feedback for 24% more payload is a bad deal on a channel whose
main UX problem is that the user cannot tell whether it is working.

## ECC L for the animation, H for anything static

**The fountain already is the error correction.** A frame that fails to decode costs one cycle and the
fountain emits again. QR's own checksum plus UR's per-part CRC32 mean a corrupted frame **fails to
decode rather than decoding wrongly**, so what L risks is latency, not silent corruption.

Against that, L buys **2.4× the payload** over H at the same physical size — 758 characters against 321
— which attacks frame count, the thing actually hurting this channel.

**The rule, stated once so it is not re-litigated per QR:**

| what | ECC | why |
|---|---|---|
| Animated PSBT stream | **L** | Re-emitted every cycle; latency is the only cost. |
| Encrypted wallet QR (#9) | **H** | Read once off paper, at an unknown angle, one chance. |
| Descriptor export (#5) | **H** | Static, ~150 characters, size is a non-issue. |

## Fragment size is ours, not Green's

**Sized to our display, with a named constant and an on-screen way down.**

**The conflation worth naming:** #4 measured what each wallet *emits* — Green at 50 B/frame. That is a
statement about Green's **encoder**, not its **scanner**, and only the scanner constrains us. Green
scans with zxing on Android, which reads far denser codes given resolution. Sizing our output to
Green's encoder would be copying a constraint that may not exist.

At version 15 / ECC L, 758 characters is roughly **340 payload bytes per fragment** after Bytewords'
two-characters-per-byte, the UR part header and the CRC. A 702-byte BIP86 PSBT becomes **3 fragments
instead of Green's 15**.

**Computed from the field layouts, not measured** — the same caveat #4 attached to its own byte counts,
and it is why the design carries a recovery path rather than a promise.

### The step-down ladder

Fragment size is **one named constant**, and the QR screen offers a key that steps it down a short
fixed ladder:

**340 → 200 → 120 → 50 bytes**, with the frame rate stepping **2 → 1 fps** alongside it.

This is a recovery path a user reaches for when a wallet will not read the code — not a configuration
menu they must understand in advance. Boot-checklist item 18, the real round trip with each wallet, is
what promotes the default from assumed to known.

## Frame rate: 2 fps

**Not the fastest all three can read — the slowest all three can read.**

#4 measured the wallets' own emitters at 1 fps (BlueWallet) and 2 fps (Green); Sparrow reads at 5. **A
scanner that misses a frame waits a whole cycle for it**, so with few frames, faster is actively worse:
at 3 fragments a missed frame costs 1.5 s at 2 fps, and the same again if missed again. Matching the
pace the two slowest wallets chose for their own *output* is the best available evidence about what
their scanners keep up with.

This is the outbound rate only. Inbound is unchanged at #6's measured 5 fps, 10 worst case.

## The animation does not stop

**Cycle the deterministic first `seqLen` parts, then continue with fountain parts, indefinitely, until
the user presses a key to say the wallet is done.** Not a fixed multiple.

GDK emits `3 × seqLen` because it is a phone showing a code and needs to get back to being a phone.
**The appliance has nothing else to do** — it is a kiosk whose entire purpose in that moment is being
scanned, and there is no next screen to reach. Stopping at any multiple creates a failure mode whose
only recovery is starting over, which is precisely what fountain encoding exists to avoid: a receiver
arriving late still converges.

**The screen shows the cycle count**, which doubles as the honest diagnostic. A user on cycle five knows
the wallet is not reading, and that is the moment the step-down key earns its place.

## No warning on long scans

#11 deferred here the question of whether a many-input taproot spend deserves a warning. **It does
not.** A warning is a modal interruption for something that is not an error, and #11 already
established that this appliance does not train users to click through things.

**The frame count is on screen for every scan anyway.** *"Frame 2 of 3"* and *"frame 2 of 47"* tell the
user everything a warning would, at the moment it is actionable, with no reflex to build.

If 47 frames proves genuinely unusable in the interop check, the answer is a shorter ladder or an
accepted limitation stated in the docs — a design change, not a dialog.
