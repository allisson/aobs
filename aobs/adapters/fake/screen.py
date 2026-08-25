"""The `Screen` fake: Textual, headless, through `run_test()`.

`docs/test-harness.md` established that the display side of this harness needs no framebuffer, no
VM and no X — `run_test()` drives a real Textual app with no display of any kind. So the fake is
not a stub that records strings: it renders through the same library the appliance renders
through, and hands back what actually reached the terminal.

What a test asserts on is that text and the widget state behind it. Screenshots are a
human-reviewed artifact and never a passing assertion: pixel-diffing a TUI produces tests that
fail on a font change and pass on a wrong address.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

from textual.app import App, ComposeResult
from textual.widgets import Static


class _OneViewApp(App):
    """The smallest app that can render one view. The appliance's own screens are a later spec;
    this exists so the seam has a second adapter now rather than a hypothetical one."""

    def __init__(self, text: str) -> None:
        super().__init__()
        self._text = text

    def compose(self) -> ComposeResult:
        yield Static(self._text, id="view")


class TextualScreen:
    """A `Screen` whose keystrokes are scripted and whose rendering is real."""

    def __init__(self, keys: Sequence[str] = ()) -> None:
        self._keys = list(keys)
        self.shown: list[object] = []
        self.rendered: list[str] = []

    def show(self, view: object) -> None:
        self.shown.append(view)
        self.rendered.append(asyncio.run(self._render(str(view))))

    async def _render(self, text: str) -> str:
        app = _OneViewApp(text)
        async with app.run_test() as pilot:
            await pilot.pause()
            widget = app.query_one("#view", Static)
            # The rendered text, as the terminal received it — not the string we passed in.
            return str(widget.render())

    def next_key(self) -> str:
        if not self._keys:
            raise AssertionError("the test ran out of scripted keys")
        return self._keys.pop(0)
