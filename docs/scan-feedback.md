# Camera aiming and scan feedback

What the user sees while pointing the camera at a QR code.

[#3](https://github.com/allisson/aobs/issues/3) chose a framebuffer TUI and recorded a coarse
block-character viewfinder with `/dev/fb0` as an unproven escape hatch;
[#6](https://github.com/allisson/aobs/issues/6) measured what the bare VT can actually draw;
[#20](https://github.com/allisson/aobs/issues/20) settled the stall *policy* — never time out, three
distinguishable states, `esc` backs out, `F12` powers off. This document settles the screen.

## The live image is a framing aid, and is called one

**A coarse half-block viewfinder in the TUI. Greys only. No `/dev/fb0`.**

Sizing follows #6's cell grid: the 8×16 font at the 1024×768 floor gives **128×48 cells**, and the
viewfinder takes **~64×24 of them**, centred — half-blocks (`▀`, foreground over background) put two
vertical luma samples in each cell, so 64×24 cells carry a **128×48 sample** image.

What matters more than the size is what the thing is *for*. #6 found the console has **4 true greys**,
and at 128×48 samples the module pitch of a version 15 QR is far below the sample pitch. So the
viewfinder can show **where the bright rectangle is**, and it can never show whether the code is in
focus. It is a framing aid. Calling it a preview would promise focus feedback it cannot deliver, and a
user who trusts a blurry-looking preview will move the phone for the wrong reason.

**It disappears on the first successful decode.** Once bytes are arriving, aiming is solved and the
screen's job is progress — which is #3's argument, applied at the exact moment it becomes true rather
than for the whole scan.

### `/dev/fb0` is rejected, not deferred again

#3 left it viable-but-unproven; this is the evidence call it asked for, and the deciding fact is not
performance.

Drawing pixels means putting the tty into `KD_GRAPHICS` (`KDSETMODE`, #6), **which blanks the text
console**. The preview then cannot coexist with the status line, the part count, the instruction, or a
refusal — and the scan screen is the screen most likely to *become* a refusal. Adopting it means a
second rendering path plus a guaranteed way back into text mode on every error, for the one screen
where a half-broken transition is least affordable.

Secondary, but pointing the same way: #6 documented the API from kernel source and **never measured
`mmap` throughput from Python**. Taking the hatch now would mean adopting an unproven mechanism to fix
a problem the block viewfinder has not been shown to have.

**Consequence for the boot pipeline:** #12 sets `CONFIG_FB_DEVICE=y` "needed only if #3's escape hatch
is ever taken". It is not taken, so that line is now dead weight and should be reconsidered when the
`.config` is next touched. Nothing else depends on it — `CONFIG_FB=y` and fbcon are what the text
console needs, and `FB_DEVICE` is independent of both.

## Progress is a slot map, because the parts do not arrive in order

**One cell per part index — `▮` received, `▯` missing — above the line *17 of 27 parts*.**

A progress bar was rejected as **actively misleading**. #6's reading of BC-UR/MUR: the first `seqLen`
parts are the pure fragments in order, and mixed XOR parts follow to repair losses. A bar that fills,
stalls near the end and then jumps reads as broken at exactly the moment the fountain is doing its job.

The slot map makes out-of-order arrival *look* like what it is: holes filling in. It also makes #20's
second state visible without any extra wording — **a stuck sender is the same holes never filling.**

`seqLen` is the sender's choice and varies by an order of magnitude (#4, #6: Sparrow 400-char
fragments, SeedSigner's HIGH 120, Green's encoder 50 B — so 3 parts or 45), which the map absorbs.
Above ~96 parts it no longer fits one row: **fall back to the fraction alone** rather than compressing
several parts into one cell, which would show a filled cell for an incomplete range.

## Three states, three fixes, one status line

The status line **changes its wording**; there is no spinner. Each state names where the fix is, which
is #20's rule for refusals applied to a stream that has not failed yet:

| state | what the line says |
|---|---|
| parts arriving, count rising | *Scanning — 17 of 27 parts.* |
| frames decoding, no new parts | *Frames are decoding but no new parts are arriving — your wallet may be showing a still frame.* |
| nothing decoding at all | *Nothing is decoding — move closer, or ask your wallet for a lower QR density.* |

**The density hint is delayed a few seconds.** Shown instantly it is advice handed to someone who is
merely still aiming, and it would train exactly the click-through #11 refused. This is the inbound
counterpart of #17's outbound step-down key: on the way out we lower our own density, on the way in we
can only ask the sender to lower theirs.

**No timeout, per #20.** `esc` is the give-up, and it **discards the partials** — with the count shown
on the way out, because a user who reached 26 of 27 should know they nearly had it rather than
concluding the appliance cannot scan.

## One scan screen, for one QR or forty-five

#19's address scan and #9's encrypted-wallet QR are single static frames: no fountain, no part count.
They use **the same screen**, and the slot map and fraction simply never appear, because `seqLen` is 1
and there is nothing to count.

Two screens would mean two aiming implementations, which drift; and the user is doing the same physical
thing in both cases — holding a code in front of a camera.
