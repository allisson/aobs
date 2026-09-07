"""The identity footer: two rows, on the first screen and on every failure screen.

`docs/boot-pipeline.md` and #61 fix where it goes and why it is not an About screen:

> A screen you must navigate to is a screen nobody visits, and this is meant to be seen by someone
> who did not think to look.

So it is a reserved row on the keymap picker — the first screen, before any secret exists — and it
is repeated by `FailurePanel`, because a bug report carrying no build identity is a bug report about
nothing.

The second row points at the advisories and **cannot be mistaken for having checked them**. #62 is
explicit that the appliance attempts no detection of its own: there is no trustworthy clock offline,
a wrong *this build is old* is worse than silence, and a modified image would lie about it anyway.
The wording ends in *this appliance cannot check* for that reason.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static

from aobs.core.release import ADVISORIES_LINE, Release, identity_line


class ReleaseFooter(Vertical):
    """`Release`, rendered as the two rows. Takes no focus and holds no `Button`."""

    DEFAULT_CSS = """
    ReleaseFooter { height: auto; margin-top: 1; }
    """

    def __init__(self, release: Release, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self.release = release

    def compose(self) -> ComposeResult:
        yield Static(identity_line(self.release), id="release-identity")
        yield Static(ADVISORIES_LINE, id="release-advisories")
