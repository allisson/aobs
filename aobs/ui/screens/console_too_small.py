"""The console is smaller than the appliance will draw on.

`docs/review-screen.md`: *a startup check refuses to run below 100 × 30 rather than degrading
silently.* Degrading is the tempting alternative and it is wrong — the screens this appliance
draws are the ones a user compares an address against, and a layout that has quietly reflowed is
exactly where a truncated address goes unnoticed.

It uses the ordinary failure shape. A user who reaches this has not learned that shape yet, but
the appliance has only one and this is not the place to invent a second.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Static

from aobs.ui.geometry import MIN_COLUMNS, MIN_ROWS
from aobs.ui.widgets.failure import Failure, FailurePanel


def console_too_small(columns: int, rows: int) -> Failure:
    return Failure(
        condition="console-too-small",
        happened=(
            f"This console is {columns} columns by {rows} rows. "
            f"The appliance needs at least {MIN_COLUMNS} by {MIN_ROWS}."
        ),
        next_steps=(
            "Boot with a larger console mode — on legacy BIOS, the `vga=791` boot parameter.",
            "Use a display the firmware can drive at 1024x768 or better.",
        ),
    )


class ConsoleTooSmallScreen(Screen):
    """Reached instead of the keymap picker, so nothing else in the session ever starts."""

    def __init__(self, columns: int, rows: int) -> None:
        super().__init__()
        self._failure = console_too_small(columns, rows)

    def compose(self) -> ComposeResult:
        with Vertical(id="frame"):
            yield Static("Cannot start", id="title")
            yield FailurePanel(self._failure)
