"""The one column budget, and the floor below which the appliance refuses to run.

`docs/review-screen.md` settled both. The appliance meets at least three real console geometries —
128×48 from a 1024×768 firmware framebuffer, 240×67 on a 1080p panel, more on 4K — and the answer is
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
#:
#: **Both numbers are above the 85×43 a QR needs, and the row one was not.** `MIN_ROWS` was 30,
#: which admitted a console the emit screen cannot draw a QR code on — the appliance's only path
#: out — and `tests/screentext.py` said so in a comment while driving 128×48 to avoid picturing it.
#: A floor below the thing it exists to guarantee is not a floor. 43 is the QR row count and the
#: appliance will not start under it.
MIN_COLUMNS = 100
MIN_ROWS = 43


def fits(columns: int, rows: int) -> bool:
    return columns >= MIN_COLUMNS and rows >= MIN_ROWS
