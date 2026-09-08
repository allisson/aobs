"""PROTOTYPE chrome — the switcher bar. Not part of any design being judged.

Deliberately ugly and deliberately the last row of the console, so nothing about it reads as a
proposal. It never ships: `prototypes/` sits outside `aobs/`, and `build/mkiso.sh` tars `aobs`.
"""

from __future__ import annotations

from textual.widgets import Static

from aobs.ui.geometry import MIN_COLUMNS, MIN_ROWS


class PrototypeBar(Static):
    DEFAULT_CSS = """
    PrototypeBar {
        dock: bottom;
        height: 1;
        width: 100%;
        background: ansi_bright_white;
        color: ansi_black;
        text-style: bold;
    }
    """

    def __init__(self, index: int, total: int, name: str) -> None:
        super().__init__()
        self.index = index
        self.total = total
        self.variant_name = name

    def render(self) -> str:
        app = self.app
        columns, rows = app.size.width, app.size.height
        floor = "" if (columns >= MIN_COLUMNS and rows >= MIN_ROWS) else "  UNDER THE 100x30 FLOOR"
        return (
            f" PROTOTYPE {chr(0x2190)}{chr(0x2192)} {self.index + 1}/{self.total} {self.variant_name} "
            f" {chr(0xB7)}  w wallet:{'yes' if app.wallet else 'no'}"
            f"  c camera:{'yes' if app.camera_available else 'no'}"
            f"  n notice:{'yes' if app.notice else 'no'}"
            f"  {chr(0xB7)}  {columns}x{rows}{floor}"
        )
