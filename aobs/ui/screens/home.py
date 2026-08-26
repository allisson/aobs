"""What this session can do, and what it cannot do and why.

The only decision this screen carries at the shell stage is the one `docs/failure-states.md`
settled about a missing camera:

> Refusing to boot without a camera is the obvious move and it is wrong: **generating a wallet and
> exporting its descriptor need no camera at all** — both are outbound.

So a missing camera disables the paths that scan and **nothing else**, with one sentence saying
why. The same reasoning applies to a session that has no wallet yet: a path that needs one is shown
as unavailable rather than hidden, because a user who cannot find *sign a transaction* concludes
the appliance cannot sign.

Each path is opened by the spec that builds its screen. The three that scan all lead to the one
scan screen, which is what `docs/scan-feedback.md` settled — the user is doing the same physical
thing in all three cases, and two aiming implementations would drift.

**This is also the wallet screen.** *Generate*, *type a seed in* and *restore from an encrypted
wallet QR* sit here as peers of each other and of everything else, rather than under an *import*
submenu — `docs/seed-entry.md` is explicit that burying the encrypted QR would hide the path two
tickets were spent making safe. The network is chosen here too, for the same reason: it must be
settled before a wallet is constructed, and this is the last screen before every path that
constructs one. """

from __future__ import annotations

from dataclasses import dataclass

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Static

from aobs.core.wallet import Network
from aobs.ui.scanning import ScanTarget


@dataclass(frozen=True)
class Path:
    """One thing the user can do, and what the session needs before they can do it."""

    name: str
    needs_camera: bool = False
    needs_wallet: bool = False
    #: What this path scans, for the three that scan. `None` is a path whose own spec opens it.
    scans: ScanTarget | None = None
    #: The method on the app that opens this path, for the ones that open a screen directly.
    #: Named rather than referenced so this table stays a value with no import in it.
    opens: str | None = None


PATHS: tuple[Path, ...] = (
    Path("Generate a new wallet", opens="open_generate"),
    Path("Type a seed in", opens="open_seed_entry"),
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
    Path("Browse your addresses", needs_wallet=True, opens="open_address_list"),
    Path("Export the descriptor", needs_wallet=True, opens="open_descriptor"),
    Path("Export the encrypted wallet QR", needs_wallet=True, opens="open_wallet_export"),
    Path("Show recovery words", needs_wallet=True, opens="open_recovery_words"),
)

#: One sentence, and it says what happened rather than what to do: a camera authorised after
#: `authorized_default=0` cannot be authorised later, so there is no retry to offer.
NO_CAMERA = "No camera was found, so the paths that scan a QR code are unavailable this session."

NO_WALLET = "No wallet is loaded yet, so the paths that need one are unavailable."

#: Network selection is **not settled by any document in `docs/`**. This implements the parent
#: spec's stated assumption: chosen here, before the wallet is constructed, defaulting to mainnet,
#: with `account` fixed at 0 and not user-selectable. It is shown in the header of every screen
#: that shows money, which is what makes the choice checkable rather than remembered. If the
#: assumption is wrong the correction is one screen and one constructor argument, and it belongs
#: on the map rather than in a diff.
CHOOSE_NETWORK = "left/right changes the network. It is fixed once a wallet is loaded."

#: What is left to say once it is fixed. Not an apology and not an offer: the wallet's addresses
#: are derived on this network and changing it now would mean a different wallet.
NETWORK_FIXED = "The network is fixed for the rest of this session."


def is_available(path: Path, *, camera: bool, wallet: bool) -> bool:
    return (camera or not path.needs_camera) and (wallet or not path.needs_wallet)


class HomeScreen(Screen):
    BINDINGS = [
        Binding("up", "previous", "Previous path"),
        Binding("down", "next", "Next path"),
        Binding("left", "previous_network", "Previous network"),
        Binding("right", "next_network", "Next network"),
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
            yield Static(
                NETWORK_FIXED if wallet else CHOOSE_NETWORK, classes="note", id="network"
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

    # --- the network -------------------------------------------------------------------------

    def _cycle_network(self, delta: int) -> None:
        """Only while there is no wallet: after that the addresses are derived on this network,
        and changing it would silently mean a different wallet."""
        app = self.app
        if app.wallet is not None:  # type: ignore[attr-defined]
            return
        networks = list(Network)
        app.network = networks[  # type: ignore[attr-defined]
            (networks.index(app.network) + delta) % len(networks)  # type: ignore[attr-defined]
        ]
        self.refresh(recompose=True)

    def action_previous_network(self) -> None:
        self._cycle_network(-1)

    def action_next_network(self) -> None:
        self._cycle_network(1)

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
        elif path.opens is not None:
            getattr(app, path.opens)()
