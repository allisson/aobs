"""The camera was there and is not any more, and that is permanent.

`docs/failure-states.md` draws a consequence of #14 that is not obvious: **`authorized_default=0`
is set before the first secret is entered, so a camera unplugged and replugged is not
re-authorized.** It is gone until the next boot.

So this screen offers no retry, because there is nothing to retry — an honest dead end beats a user
replugging a cable that can never work. Backing out lands on the home screen with the scan paths
disabled and the same sentence the no-camera session shows, which is the truth of what is left.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Static

from aobs.ui.widgets.failure import Failure, FailurePanel

CAMERA_LOST = Failure(
    condition="camera-lost",
    happened=(
        "The camera was disconnected and cannot be re-enabled this session; power off and start "
        "again."
    ),
    next_steps=(
        "Power off with F12, reconnect the camera, and boot again.",
        "The paths that do not scan — generating a wallet, exporting a descriptor — still work.",
    ),
)


class CameraLostScreen(Screen):
    def compose(self) -> ComposeResult:
        with Vertical(id="frame"):
            yield Static("Camera lost", id="title")
            yield FailurePanel(CAMERA_LOST)
