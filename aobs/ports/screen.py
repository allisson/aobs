"""`Screen`: where a view is shown and a keystroke comes back.

Two adapters: Textual on the Linux console, and Textual's own `run_test()` in the harness — which
`docs/test-harness.md` established needs no framebuffer, no VM and no X.

The port carries a view object, not a rendered string: what is asserted in tests is the emitted
payload and widget state, never pixels. Pixel-diffing a TUI produces tests that fail on a font
change and pass on a wrong address.
"""

from __future__ import annotations

from typing import Protocol


class Screen(Protocol):
    def show(self, view: object) -> None:
        """Display a view. The view is a value object from the core; rendering is the adapter's."""
        ...

    def next_key(self) -> str:
        """Block until the user presses a key, and return it."""
        ...
