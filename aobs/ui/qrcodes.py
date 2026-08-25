"""A QR payload, as text a framebuffer console can draw.

`payload → module matrix → half-block text`, and nothing else. It is Textual-free so the module
arithmetic — which is where a code that no wallet can read comes from — is testable with no
application at all.

`qrcode` rather than `segno`, because `py3-qrcode` is what Alpine packages and
`docs/boot-pipeline.md` installs no wheels from PyPI on the authoritative tier.

**Two module rows per character row.** The console is 128×48 characters, which is 128×96 module
rows once each character cell carries an upper and a lower half-block — and 77 modules plus an
8-module quiet zone is 85 columns and 43 character rows (`docs/qr-emit-parameters.md`).

**Light modules are drawn as ink.** The appliance's console is white on black, so a filled block
is a *light* module and an empty cell is a dark one. That renders the code in its true polarity —
dark modules dark — rather than inverted, which is what a scanner expects even where zxing would
cope with either.
"""

from __future__ import annotations

from dataclasses import dataclass

import qrcode
from qrcode.constants import ERROR_CORRECT_H, ERROR_CORRECT_L

from aobs.core.constants import QR_ECC_ANIMATED, QR_ECC_STATIC

#: Modules of margin on every side. Four is the QR specification's own quiet zone.
QUIET_ZONE = 4

_ECC = {QR_ECC_ANIMATED: ERROR_CORRECT_L, QR_ECC_STATIC: ERROR_CORRECT_H}

#: Upper half only, lower half only, both, neither — indexed by `(upper, lower)` light modules.
_GLYPHS = {(False, False): " ", (True, False): "▀", (False, True): "▄", (True, True): "█"}


@dataclass(frozen=True)
class QrCode:
    """One rendered code: the matrix it came from, and the text that draws it."""

    #: `True` is a dark module, which is `qrcode`'s own convention and the specification's.
    matrix: tuple[tuple[bool, ...], ...]
    version: int
    text: str

    @property
    def modules(self) -> int:
        """Side length in modules, quiet zone included — 85 for a version 15 code."""
        return len(self.matrix)

    @property
    def rows(self) -> int:
        """Character rows the text occupies: two module rows per row, rounded up."""
        return (self.modules + 1) // 2


def render(payload: str, *, ecc: str = QR_ECC_ANIMATED) -> QrCode:
    """`payload`, as a code and as the text that draws it.

    The version is whatever the payload needs and is reported rather than pinned: the fragment
    size is what keeps it inside version 15, and the step-down ladder is what the user reaches
    for when it is not enough.
    """
    code = qrcode.QRCode(error_correction=_ECC[ecc], border=QUIET_ZONE)
    code.add_data(payload)
    code.make(fit=True)
    matrix = tuple(tuple(bool(cell) for cell in row) for row in code.get_matrix())
    return QrCode(matrix=matrix, version=code.version, text=half_blocks(matrix))


def half_blocks(matrix: tuple[tuple[bool, ...], ...]) -> str:
    """Two module rows per character row, drawing the *light* modules as ink.

    An odd number of module rows leaves the last character row half-height, and its lower half is
    treated as dark: the quiet zone is what sits there, and a code whose bottom margin is one
    module short of the specification is the one thing worth being conservative about.
    """
    lines = []
    for top in range(0, len(matrix), 2):
        upper = matrix[top]
        lower = matrix[top + 1] if top + 1 < len(matrix) else None
        lines.append(
            "".join(
                _GLYPHS[(not upper[column], lower is None or not lower[column])]
                for column in range(len(upper))
            )
        )
    return "\n".join(lines)


def from_half_blocks(text: str) -> tuple[tuple[bool, ...], ...]:
    """The inverse of `half_blocks`, so a test can check the encoding rather than trust it.

    Always an even number of rows: a QR matrix's side is always odd, so the last character row
    carries one real module row and one row of the dark padding `half_blocks` writes there.
    """
    rows: list[tuple[bool, ...]] = []
    inverse = {glyph: halves for halves, glyph in _GLYPHS.items()}
    for line in text.split("\n"):
        halves = [inverse[glyph] for glyph in line]
        rows.append(tuple(not upper for upper, _lower in halves))
        rows.append(tuple(not lower for _upper, lower in halves))
    return tuple(rows)
