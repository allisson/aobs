"""The framing aid: a coarse half-block image of what the camera sees.

`docs/scan-feedback.md` settled every number here. The 8x16 font at the 1024x768 floor gives
128x48 cells; the viewfinder takes **64x24 of them, centred**, and half-blocks (`▀`, foreground
over background) put two vertical luma samples in each cell — so 64x24 cells carry a **128x48
sample** image.

**It is a framing aid and never a preview.** At 128x48 samples the module pitch of a version 15 QR
is far below the sample pitch, so this can show where the bright rectangle is and can never show
whether the code is in focus. The screen says so in words, because a user who trusts a
blurry-looking preview moves the camera for the wrong reason.

Two consequences of #6's reading of `vt.c` shape the colours, and neither is a style choice:

* **Four true greys, and nothing else.** The bare VT quantises `38;5;n` and `38;2;r;g;b` alike down
  to three hue bits plus bold, so the palette is the Linux console's own black / dark grey / light
  grey / white.
* **The background half has only two of them.** The VT offers 16 foreground colours but **8
  backgrounds** — there is no bold bit for a background — so the lower sample of each cell rounds
  to black or light grey. Pretending otherwise would produce markup the appliance's own console
  renders differently from the developer's terminal.

Sampling is nearest-neighbour, not an area average. A framing aid does not need resampling quality,
and averaging a 640x480 frame down to 6144 samples in Python five times a second would cost 1.5M
pixel reads per second for a picture whose whole job is to say *the code is over to the left*.
"""

from __future__ import annotations

from aobs.ports.frame_source import Frame

#: Cells, not samples. Centring is the screen's job — the CSS centres the whole content block.
CELL_COLUMNS = 64
CELL_ROWS = 24

#: The Linux console palette's neutral column, dark to light: black, dark grey (bold black),
#: light grey, white.
GREYS = ("#000000", "#555555", "#aaaaaa", "#ffffff")

#: The two of them a background can be. Index into `GREYS`.
BACKGROUND_LEVELS = (0, 2)

#: Upper half-block: the foreground paints the top sample, the background the bottom one.
HALF_BLOCK = "▀"


def foreground_level(sample: int) -> int:
    """A luma byte to one of the four greys."""
    return min(len(GREYS) - 1, sample * len(GREYS) // 256)


def background_level(sample: int) -> int:
    """A luma byte to one of the two greys a background may be."""
    return BACKGROUND_LEVELS[0] if sample < 128 else BACKGROUND_LEVELS[1]


def cells(frame: Frame) -> tuple[tuple[tuple[int, int], ...], ...]:
    """`CELL_ROWS` rows of `CELL_COLUMNS` cells, each a `(foreground, background)` grey index.

    Returned as indexes rather than markup so the arithmetic can be asserted without parsing a
    colour string, which is the part that is actually easy to get wrong.
    """
    rows = []
    for row in range(CELL_ROWS):
        cells_in_row = []
        for column in range(CELL_COLUMNS):
            top = _sample(frame, column, row * 2)
            bottom = _sample(frame, column, row * 2 + 1)
            cells_in_row.append((foreground_level(top), background_level(bottom)))
        rows.append(tuple(cells_in_row))
    return tuple(rows)


def render(frame: Frame) -> str:
    """The framing aid as Rich markup, one line per cell row."""
    lines = []
    for row in cells(frame):
        line = "".join(
            f"[{GREYS[foreground]} on {GREYS[background]}]{HALF_BLOCK}[/]"
            for foreground, background in row
        )
        lines.append(line)
    return "\n".join(lines)


def _sample(frame: Frame, column: int, sample_row: int) -> int:
    """The luma at one of the 128x48 sample positions, nearest neighbour."""
    x = column * frame.width // CELL_COLUMNS
    y = sample_row * frame.height // (CELL_ROWS * 2)
    return frame.data[y * frame.width + x]
