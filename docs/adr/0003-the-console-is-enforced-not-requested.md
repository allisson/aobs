# The console is enforced by the appliance, not requested from the firmware

From the first commit until M3, `build/isolinux.cfg` carried `vga=791` on both boot labels and three
documents named it as the mechanism that gives the appliance a console large enough to draw a QR
code. `docs/boot-pipeline.md` said *"Legacy BIOS needs `vga=791`, and this is not cosmetic"*;
`build/isolinux.cfg` said *"`vga=791` IS NOT COSMETIC"* and, on the inspection label, *"`vga=791` in
particular has to stay, or `I-7` measures a console the appliance never uses"*.

**`vga=791` has never once set a video mode on any machine this project has booted.**

**We now ship no `vga=` at all — the two cmdlines are identical — and the console size is enforced
inside the appliance, which refuses to start below 100 × 43 and says on screen what it needs and
what it got.**

## What the M3 boot runs found

The boot screen prints:

```
Undefined video mode number: 317
Press <ENTER> to see video modes available, <SPACE> to continue, or wait 30 sec
```

`0x317` is the hex of 791, printed by `arch/x86/boot/video.c:334`. It routes to VBE `0x117` through
`VIDEO_FIRST_VESA` (`video.h:33`, `video-vesa.c:277`) — 1024×768×**16bpp**. The machine's
framebuffer is 32bpp (`/sys/class/graphics/fb0/bits_per_pixel` = `32`), and its SeaVGABIOS offers
`341`–`344` — VBE `0x141`–`0x144`, an OEM range. Standard 1024×768×32 is `0x118` → `vga=792`, and
that is not on the list either.

So the mode-set fails, `video.c:331`–`337` leaves `vid_mode` unset, `orig_video_isVGA` stays
`VIDEO_TYPE_VGAC`, and `sysfb` registers a `vga-framebuffer` device (`sysfb.c:159`) that nothing in
this image binds. The console the appliance actually drew on came from the **coreboot table**:
`framebuffer-coreboot` registers a `simple-framebuffer` device
(`drivers/firmware/google/framebuffer-coreboot.c:64`) and `simplefb` binds it, unopposed, at
`1.765199`.

**The coincidence that hid this for the life of the project:** coreboot's framebuffer is 1024×768,
which is also the resolution `vga=791` asks for. The console measured 128×48 — exactly what the
failing parameter predicted — so `I-7` passed and nobody looked further.

## Why no `vga=` value is the answer

- **A working value is one firmware's mode number, not a fixed one.** `vga=791` is right for a
  generic VBE BIOS and wrong here; `vga=836` (`0x344`) is right here and would be wrong almost
  everywhere else. Choosing either hard-codes one machine class into the image and moves the
  30-second stall onto the other.
- **There is no portable form.** The kernel's resolution syntax matches
  `mode == (mi->y << 8) + mi->x` (`video-mode.c:88`) and `video-vesa.c` fills those fields with
  **pixels**, so 1024×768 computes to `0x30400` and never fits the `u16` it is compared against.
  The `0xRRCC` form reaches text modes only.
- **The failure mode is bad.** A `vga=` the firmware does not offer does not fall back quietly: it
  prints an error, shows a mode menu, and waits 30 seconds — on an appliance whose premise is that
  nothing unexplained happens between power-on and the signing screen.

## What the appliance does instead

`aobs/ui/geometry.py` sets `MIN_COLUMNS = 100`, `MIN_ROWS = 43`, and `aobs/ui/app.py` pushes
`ConsoleTooSmallScreen` below that, before the keymap picker and before anything else in the
session. A machine whose firmware brings up a framebuffer too small gets a legible refusal naming
both numbers, instead of a clipped QR code.

**`MIN_ROWS` was 30 when this decision was made, and that was a defect in its own right.** The QR
display is 85 × 43, so the floor admitted a console the appliance's only outbound path cannot be
drawn on. `tests/screentext.py` had recorded the clipping in a comment and drove 128×48 to avoid
picturing it. `tests/test_emit_screen.py` now asserts the floor against the rendered code, so a
larger QR version moves the floor rather than silently outgrowing it.

## What this costs

**A generic BIOS machine with no firmware framebuffer is regressed from "works" to "refuses with an
explanation".** With `vga=791`, such a machine would have got a VESA linear framebuffer and a 128×48
console. Without it, it gets `vgacon` at 80×25 and the refusal screen.

This is accepted, and the reason is the ordering `docs/roadmap.md` already enforces: **a machine
this project has never booted does not outrank the one it has.** The regressed class is
hypothetical; the 30-second stall was on every boot of the only real machine. The refusal screen
also tells that user what to do, including that a `vga=` value may help and that the kernel's own
mode menu will say which one — which is more than the silent version ever did.

**`FB_VESA` stays asserted in `build/verify.py`.** The driver is still the mechanism on that machine
class, and `vga=` at the boot prompt is still the way to reach it. What changed is that the image no
longer claims to have arranged it.

## What would reverse this

A second hardware boot, on a non-coreboot BIOS machine, showing that the refusal screen is reached
in practice and that adding `vga=` back at the prompt is too obscure a remedy. That is a
compatibility claim this project does not yet have and will not infer.
