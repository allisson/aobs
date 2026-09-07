"""The one column budget, and the floor below which the appliance refuses to run.

`docs/review-screen.md` settled both. The appliance meets at least three real console geometries —
128×48 on the BIOS floor with `vga=791`, 240×67 on a 1080p panel, more on 4K — and the answer is
not a layout per geometry:

**Rows are fluid, columns are capped at 96, and the block is centred.** More rows is pure win. More
columns is not: 96 is chosen against the widest atom the appliance can ever show (a regtest taproot
address, 64 characters grouped in fours = 79 columns plus a 5-column indent), and it stops a warning
sentence from stretching to 240 columns, which is unreadable.

One column budget also means one layout to test, which is what keeps `docs/test-harness.md`'s
golden-file assertions stable across every geometry. The cap is a testing decision as much as a
layout one.
"""

from __future__ import annotations

#: The widest the content block is ever drawn, regardless of how wide the console is.
MAX_COLUMNS = 96

#: Below this the appliance refuses to start rather than degrading into an unreadable layout.
#: Chosen under 128×48 so the BIOS floor clears it with room, and above the 85×43 a QR needs.
MIN_COLUMNS = 100
MIN_ROWS = 30


def fits(columns: int, rows: int) -> bool:
    return columns >= MIN_COLUMNS and rows >= MIN_ROWS
