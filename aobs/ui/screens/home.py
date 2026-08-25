"""What this session can do, and what it cannot do and why.

The only decision this screen carries at the shell stage is the one `docs/failure-states.md`
settled about a missing camera:

> Refusing to boot without a camera is the obvious move and it is wrong: **generating a wallet and
> exporting its descriptor need no camera at all** — both are outbound.

So a missing camera disables the paths that scan and **nothing else**, with one sentence saying
why. The same reasoning applies to a session that has no wallet yet: a path that needs one is shown
as unavailable rather than hidden, because a user who cannot find *sign a transaction* concludes
the appliance cannot sign.

Each path is opened by the spec that builds its screen. The three that scan are open: they all lead
to the one scan screen, which is what `docs/scan-feedback.md` settled — the user is doing the same
physical thing in all three cases, and two aiming implementations would drift. The rest are still
inventory.
"""

from __future__ import annotations

from dataclasses import dataclass

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Static

from aobs.ui.scanning import ScanTarget


@dataclass(frozen=True)
class Path:
    """One thing the user can do, and what the session needs before they can do it."""

    name: str
    needs_camera: bool = False
    needs_wallet: bool = False
    #: What this path scans, for the three that scan. `None` is a path whose own spec opens it.
    scans: ScanTarget | None = None


PATHS: tuple[Path, ...] = (
    Path("Generate a new wallet"),
    Path("Type a seed in"),
    Path("Restore from an encrypted wallet QR", needs_camera=True, scans=ScanTarget.WALLET_BACKUP),
    Path(
        "Sign a transaction",
        needs_camera=True,
        needs_wallet=True,
        scans=ScanTarget.TRANSACTION,
    ),
    Path(
        "Verify a receive address",
        needs_camera=True,
        needs_wallet=True,
        scans=ScanTarget.ADDRESS,
    ),
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
    BINDINGS = [
        Binding("up", "previous", "Previous path"),
        Binding("down", "next", "Next path"),
        # Never `enter`, never `esc` — `docs/failure-states.md`. `F10` is the one accept key the
        # appliance teaches, and the keymap picker already taught it.
        Binding("f10", "open", "Open this path"),
    ]

    DEFAULT_CSS = """
    HomeScreen #paths { height: auto; margin: 1 0; }
    HomeScreen .path { margin-left: 2; }
    HomeScreen .path-selected { text-style: bold; }
    HomeScreen .path-unavailable { text-style: dim; }
    HomeScreen .note { margin-top: 1; }
    """

    def __init__(self) -> None:
        super().__init__()
        self._selected = 0

    def compose(self) -> ComposeResult:
        app = self.app
        camera = app.camera_available  # type: ignore[attr-defined]
        wallet = app.wallet is not None  # type: ignore[attr-defined]
        network = app.network  # type: ignore[attr-defined]
        notice = app.notice  # type: ignore[attr-defined]

        with Vertical(id="frame"):
            yield Static(f"aobs  ·  {network.value}", id="title")
            with Vertical(id="paths"):
                for index, path in enumerate(PATHS):
                    available = is_available(path, camera=camera, wallet=wallet)
                    classes = ["path"] if available else ["path", "path-unavailable"]
                    if index == self._selected:
                        classes.append("path-selected")
                    yield Static(
                        f"{'>' if index == self._selected else ' '} {path.name}",
                        id=f"path-{index}",
                        classes=" ".join(classes),
                    )
            if not camera:
                yield Static(NO_CAMERA, classes="note", id="no-camera")
            if not wallet:
                yield Static(NO_WALLET, classes="note", id="no-wallet")
            if notice:
                yield Static(notice, classes="note", id="notice")

    def on_screen_resume(self) -> None:
        """Redraw on the way back from any path.

        Two things can have changed while the user was away and both belong on this screen: a
        camera that stopped answering, and how far a scan the user abandoned had got.
        """
        self.refresh(recompose=True)

    # --- selection ---------------------------------------------------------------------------

    @property
    def selected_path(self) -> Path:
        return PATHS[self._selected]

    def action_previous(self) -> None:
        self._selected = (self._selected - 1) % len(PATHS)
        self.refresh(recompose=True)

    def action_next(self) -> None:
        self._selected = (self._selected + 1) % len(PATHS)
        self.refresh(recompose=True)

    def action_open(self) -> None:
        """Open the selected path, if this session can.

        An unavailable path is shown rather than hidden — a user who cannot find *sign a
        transaction* concludes the appliance cannot sign — and pressing the accept key on one does
        nothing at all. It is not a place to explain again: the sentence saying why is already on
        the screen.
        """
        app = self.app
        path = self.selected_path
        if not is_available(
            path,
            camera=app.camera_available,  # type: ignore[attr-defined]
            wallet=app.wallet is not None,  # type: ignore[attr-defined]
        ):
            return
        if path.scans is not None:
            app.open_scan(path.scans)  # type: ignore[attr-defined]
