"""What this session can do, and what it cannot do and why.

The only decision this screen carries at the shell stage is the one `docs/failure-states.md`
settled about a missing camera:

> Refusing to boot without a camera is the obvious move and it is wrong: **generating a wallet and
> exporting its descriptor need no camera at all** — both are outbound.

So a missing camera disables the paths that scan and **nothing else**, with one sentence saying
why. The same reasoning applies to a session that has no wallet yet: a path that needs one is shown
as unavailable rather than hidden, because a user who cannot find *sign a transaction* concludes
the appliance cannot sign.

The paths themselves do nothing yet. Each is opened by the spec that builds its screen; this table
is the inventory the shell knows about, not an implementation of any of them.
"""

from __future__ import annotations

from dataclasses import dataclass

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Static


@dataclass(frozen=True)
class Path:
    """One thing the user can do, and what the session needs before they can do it."""

    name: str
    needs_camera: bool = False
    needs_wallet: bool = False


PATHS: tuple[Path, ...] = (
    Path("Generate a new wallet"),
    Path("Type a seed in"),
    Path("Restore from an encrypted wallet QR", needs_camera=True),
    Path("Sign a transaction", needs_camera=True, needs_wallet=True),
    Path("Verify a receive address", needs_camera=True, needs_wallet=True),
    Path("Browse your addresses", needs_wallet=True),
    Path("Export the descriptor", needs_wallet=True),
    Path("Export the encrypted wallet QR", needs_wallet=True),
    Path("Show recovery words", needs_wallet=True),
)

#: One sentence, and it says what happened rather than what to do: a camera authorised after
#: `authorized_default=0` cannot be authorised later, so there is no retry to offer.
NO_CAMERA = "No camera was found, so the paths that scan a QR code are unavailable this session."

NO_WALLET = "No wallet is loaded yet, so the paths that need one are unavailable."


def is_available(path: Path, *, camera: bool, wallet: bool) -> bool:
    return (camera or not path.needs_camera) and (wallet or not path.needs_wallet)


class HomeScreen(Screen):
    DEFAULT_CSS = """
    HomeScreen #paths { height: auto; margin: 1 0; }
    HomeScreen .path { margin-left: 2; }
    HomeScreen .path-unavailable { text-style: dim; }
    HomeScreen .note { margin-top: 1; }
    """

    def compose(self) -> ComposeResult:
        app = self.app
        camera = app.camera_available  # type: ignore[attr-defined]
        wallet = app.wallet is not None  # type: ignore[attr-defined]
        network = app.network  # type: ignore[attr-defined]

        with Vertical(id="frame"):
            yield Static(f"aobs  ·  {network.value}", id="title")
            with Vertical(id="paths"):
                for index, path in enumerate(PATHS):
                    available = is_available(path, camera=camera, wallet=wallet)
                    yield Static(
                        path.name,
                        id=f"path-{index}",
                        classes="path" if available else "path path-unavailable",
                    )
            if not camera:
                yield Static(NO_CAMERA, classes="note", id="no-camera")
            if not wallet:
                yield Static(NO_WALLET, classes="note", id="no-wallet")
