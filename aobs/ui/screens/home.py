"""What this session can do, and what it cannot do and why.

The only decision this screen carries at the shell stage is the one `docs/failure-states.md`
settled about a missing camera:

> Refusing to boot without a camera is the obvious move and it is wrong: **generating a wallet and
> exporting its descriptor need no camera at all** — both are outbound.

So a missing camera disables the paths that scan and **nothing else**, with a sentence saying why.
The same reasoning applies to a session that has no wallet yet: a path that needs one is shown as
unavailable rather than hidden, because a user who cannot find *sign a transaction* concludes the
appliance cannot sign.

**Which sentence is four sentences, not one.** `CameraReason` names the four ways the probe can
fail and three of them mean a camera was found and then failed, which *No camera was found* denies.
And when no capture node was found at all, this screen adds what the USB bus says: any **late
arrival** is named by `idVendor:idProduct` and its descriptor string, and never interpreted. The
appliance cannot know that the late device was the camera — the class lives in an interface
descriptor that is never read for an unauthorised one — so it reports and stops, and the operator
recognises their own webcam. `docs/failure-states.md` fixes all of it.

Each path is opened by the spec that builds its screen. The three that scan all lead to the one
scan screen, which is what `docs/scan-feedback.md` settled — the user is doing the same physical
thing in all three cases, and two aiming implementations would drift.

**This is also the wallet screen.** *Generate*, *type a seed in* and *restore from an encrypted
wallet QR* sit here as peers of each other and of everything else, rather than under an *import*
submenu — `docs/seed-entry.md` is explicit that burying the encrypted QR would hide the path two
tickets were spent making safe. The network is chosen from here too, for the same reason: it must
be settled before a wallet is constructed, and this is the last screen before every path that
constructs one.

**All three close once the session has a wallet** (`docs/seed-entry.md`): a session holds one, and
there is no unloading. They stay on the screen with the reason beside them, like every other
unavailable path. Before that, walking one with a wallet loaded replaced it silently and left the
previous wallet's encrypted backup in `SignerApp.export` to be re-shown under the new wallet's
name.

**The network is a path, not an arrow key** (`docs/network-selection.md`). It used to move under
`left`/`right` on this screen, which made it the only setting on the appliance that changed without
`F10` — and put a money-affecting choice one key away from the `up`/`down` that selects a path. It
sits last because it is a setting rather than a way in, and it goes unavailable for good once a
wallet has been constructed. """

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Static

from aobs.ports.frame_source import CameraReason
from aobs.ports.usb_bus import LateArrival
from aobs.ui.geometry import MAX_COLUMNS
from aobs.ui.scanning import ScanTarget


@dataclass(frozen=True)
class Path:
    """One thing the user can do, and what the session needs before they can do it."""

    name: str
    needs_camera: bool = False
    needs_wallet: bool = False
    #: Unavailable once the session **has** a wallet: the three ways in. Deliberately a question
    #: about `app.wallet` rather than a latch beside `network_fixed`, because the rule really is
    #: *a session holds one wallet* — nothing clears it, and a latch would restate the wallet's
    #: own existence. A *forget this wallet* path would re-open these, which is why
    #: `docs/seed-entry.md` rules that path out rather than leaving it to this flag.
    needs_no_wallet: bool = False
    #: Unavailable once the session's network is fixed. Only the network path itself, which stops
    #: being a choice the moment a wallet is derived on the answer.
    needs_unfixed_network: bool = False
    #: What this path scans, for the three that scan. `None` is a path whose own spec opens it.
    scans: ScanTarget | None = None
    #: The method on the app that opens this path, for the ones that open a screen directly.
    #: Named rather than referenced so this table stays a value with no import in it.
    opens: str | None = None
    #: An enum-valued session setting whose current value is shown after the name, for a path that
    #: carries a setting rather than an action. Named rather than referenced, like `opens`.
    shows: str | None = None


PATHS: tuple[Path, ...] = (
    Path("Generate a new wallet", needs_no_wallet=True, opens="open_generate"),
    Path("Type a seed in", needs_no_wallet=True, opens="open_seed_entry"),
    Path(
        "Restore from an encrypted wallet QR",
        needs_camera=True,
        needs_no_wallet=True,
        scans=ScanTarget.WALLET_BACKUP,
    ),
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
    Path(
        "Choose the network",
        needs_unfixed_network=True,
        opens="open_network",
        shows="network",
    ),
)

#: One sentence per condition, and each says what happened rather than what to do: a camera
#: authorised after `authorized_default=0` cannot be authorised later, so there is no retry to
#: offer whichever way it failed.
#:
#: The trailing clause is identical in all four deliberately — the consequence is the same session
#: with the same paths disabled, and only the cause differs. Three of the four used to print
#: `NO_CAMERA`, which was false: a camera that answered and then failed is not one that is absent.
#: `docs/failure-states.md` tables these.
NO_CAMERA = "No camera was found, so the paths that scan a QR code are unavailable this session."

_UNAVAILABLE = "so the paths that scan a QR code are unavailable this session."

CAMERA_CONDITIONS: dict[CameraReason, str] = {
    CameraReason.NO_CAPTURE_DEVICE: NO_CAMERA,
    CameraReason.NO_USABLE_FORMAT: (
        f"The camera offers no image format this appliance can read, {_UNAVAILABLE}"
    ),
    CameraReason.NO_BUFFERS: f"The camera granted no capture buffers, {_UNAVAILABLE}",
    CameraReason.NO_FRAMES: f"The camera was found but produced no frames, {_UNAVAILABLE}",
}

#: The lead line above the late arrivals, singular and plural. It reports and stops: naming the
#: device as the camera is a claim the appliance cannot make, because the class of a UVC camera
#: lives in an interface descriptor that is never read for an unauthorised device. `CONTEXT.md`
#: holds the term and that limit together.
LATE_ARRIVAL = "One USB device arrived after the bus was closed and was not authorised:"
LATE_ARRIVALS = "{count} USB devices arrived after the bus was closed and were not authorised:"


def camera_note(condition: CameraReason | None) -> str | None:
    """The sentence for a camera condition, or `None` when the camera works."""
    return None if condition is None else CAMERA_CONDITIONS[condition]


def late_arrival_lines(arrivals: Sequence[LateArrival]) -> tuple[str, ...]:
    """The lead line and one line per device, or nothing at all when none arrived late.

    One line each rather than one sentence listing them: at `aobs/ui/geometry.py`'s `MAX_COLUMNS`
    the single-sentence form does not fit even one device, and per-device lines are also what lets
    an operator match a name against the sticker on their own machine.
    """
    if not arrivals:
        return ()
    lead = LATE_ARRIVAL if len(arrivals) == 1 else LATE_ARRIVALS.format(count=len(arrivals))
    return (lead, *(f"  {_describe(arrival)}" for arrival in arrivals))


def _describe(arrival: LateArrival) -> str:
    identity = f"{arrival.vendor_id}:{arrival.product_id}"
    return identity if arrival.name is None else f"{identity} {arrival.name}"


NO_WALLET = "No wallet is loaded yet, so the paths that need one are unavailable."

#: Its counterpart, and the sentence `docs/seed-entry.md` settled. It states the model rather than
#: apologising: there is nothing to offer, because powering off *is* the way to a second wallet.
HAVE_WALLET = (
    "This session has its wallet. Making or restoring another means powering off and booting again."
)

#: Settled by `docs/network-selection.md`. Mainnet is the default and costs nothing, and the
#: choice is stated rather than asked: here, and again on the fingerprint screen at the moment it
#: stops being reversible. `account` stays 0 and is not user-selectable.
CHOOSE_NETWORK = "The network is chosen before a wallet is made, and fixed for good once one is."

#: What is left to say once it is fixed. Not an apology and not an offer: the wallet's addresses
#: are derived on this network and changing it now would mean a different wallet.
NETWORK_FIXED = "The network is fixed for the rest of this session."

#: The keys, in the shape the other screens print them.
#:
#: Missing until a source-level rule in `tests/test_structure.py` went looking: this screen bound
#: `F10` and printed nothing, exactly as the keymap picker did, and the picker is where a user
#: actually got stuck. No `esc back` — home is the root of the session and there is nowhere behind
#: it, which is the same reason the picker prints none either.
KEYS = "up/down choose  ·  F10 open this path  ·  F12 power off"

#: What the list under the rule is. A label rather than a heading, and uppercase because the
#: console has one font at one weight, so case is the only typographic register there is
#: (`docs/console-appearance.md`). It says *can do* deliberately: half these rows are on the screen
#: precisely because they cannot be walked yet, and the sentence under them says why.
SECTION = "WHAT YOU CAN DO"

#: The selection marker, and the one glyph on this screen that `docs/console-appearance.md`'s
#: budget flags: `►` is in the built-in font's repertoire, but at a position the console reaches
#: through its unicode map rather than directly. `aobs/ui/addresstext.py` already prints `↑` and
#: `↓` from that same range, so this is not a new risk — it is the same one, now on the first
#: screen of the session, where the next boot answers it. If it draws as a blank or a box, this
#: constant is the whole of the revert.
MARKER = "►"


def label(path: Path, app: object) -> str:
    """The line for a path: its name, and for a path that carries a setting, the setting's value.

    A stranger who wants mainnet pays nothing for it, and the way that stays honest rather than
    silent is that the current answer is on the screen beside the question.
    """
    if path.shows is None:
        return path.name
    return f"{path.name}  ·  {getattr(app, path.shows).value}"


def is_available(path: Path, *, camera: bool, wallet: bool, network_fixed: bool) -> bool:
    return (
        (camera or not path.needs_camera)
        and (wallet or not path.needs_wallet)
        and (not wallet or not path.needs_no_wallet)
        and (not network_fixed or not path.needs_unfixed_network)
    )


def reason(path: Path, *, camera: bool, wallet: bool, network_fixed: bool) -> str:
    """Why this path cannot be walked, in the fewest words that name the missing thing.

    `docs/console-appearance.md` requires it to be words. Until it was, the difference between a
    path that can be walked and one that cannot rested entirely on `text-style: dim`, and whether
    `fbcon` rendered half-bright at all was not known. It does, on the one panel that has been
    photographed — which is an observation and not a guarantee, so this stays: a distinction that
    survives only where somebody happened to look is not one the appliance can publish.

    A path can be short of two things at once — *sign a transaction* needs both a camera and a
    wallet — so the order here is fixed rather than meaningful. The sentence under the list is
    where both are stated; this names one so that the row itself is never silent.
    """
    if path.needs_wallet and not wallet:
        return "needs a wallet"
    if path.needs_no_wallet and wallet:
        return "one wallet per session"
    if path.needs_camera and not camera:
        return "needs a camera"
    if path.needs_unfixed_network and network_fixed:
        return "fixed for this session"
    return ""


#: The row's own width: the 96-column budget less `#frame`'s padding and `.path`'s indent. The
#: reason is right-aligned inside it, and that needs a number rather than a layout — **one
#: `Static` per path**, so the selected row's reversed bar covers the whole row and `#path-N` stays
#: the single thing a test has to read.
PATH_COLUMNS = MAX_COLUMNS - 6


def row(path: Path, app: object, *, selected: bool, why: str) -> str:
    """The whole rendered row: the marker, the label, and the reason at the right edge."""
    left = f"{MARKER if selected else ' '} {label(path, app)}"
    if not why:
        return left
    return left + " " * max(2, PATH_COLUMNS - len(left) - len(why)) + why


class HomeScreen(Screen):
    BINDINGS = [
        Binding("up", "previous", "Previous path"),
        Binding("down", "next", "Next path"),
        # No `left`/`right`: the network is a path opened with `F10` like everything else, not a
        # setting that moves under an arrow key one row from the selection keys.
        # Never `enter`, never `esc` — `docs/failure-states.md`. `F10` is the one accept key the
        # appliance teaches, and the keymap picker already taught it.
        Binding("f10", "open", "Open this path"),
    ]

    DEFAULT_CSS = """
    /* The title row is a row, not a line: the appliance's name at the left edge, what this
       session is at the right. The rule under it and the `bold` are the app's. */
    HomeScreen #title { height: auto; }
    HomeScreen #title-name { width: 1fr; text-style: bold; }
    HomeScreen #title-state { width: auto; text-style: none; }

    HomeScreen #section { margin-bottom: 1; }
    HomeScreen #paths { height: auto; }
    HomeScreen .path-unavailable { text-style: dim; }
    /* One blank row before the block and none inside it: the sentences are one statement about
       the session, and a blank between each made three paragraphs out of it. */
    HomeScreen #notes { height: auto; margin-top: 1; }
    """

    def __init__(self) -> None:
        super().__init__()
        self._selected = 0

    def compose(self) -> ComposeResult:
        app = self.app
        condition = app.camera_condition  # type: ignore[attr-defined]
        camera = condition is None
        # Read on every composition rather than once at startup, and `on_screen_resume` recomposes,
        # so this is re-read on the way back from every path. The fault it exists to catch is a
        # device that enumerated late: a single reading taken at startup can be taken before the
        # device arrived, which would leave the appliance silent in exactly the case that matters.
        #
        # Only when the camera is unavailable. With the scan paths working there is no disabled
        # path for the line to be a reason for, and this screen is not a notification area —
        # `docs/failure-states.md` fixes the availability model it belongs to.
        arrivals = () if camera else app.usb.late_arrivals()  # type: ignore[attr-defined]
        wallet = app.wallet is not None  # type: ignore[attr-defined]
        network = app.network  # type: ignore[attr-defined]
        network_fixed = app.network_fixed  # type: ignore[attr-defined]
        notice = app.notice  # type: ignore[attr-defined]

        with Vertical(id="frame"):
            with Horizontal(id="title"):
                yield Static("aobs", id="title-name")
                yield Static(
                    f"{network.value}  ·  {app.release.version_label}",  # type: ignore[attr-defined]
                    id="title-state",
                )
            yield Static(SECTION, id="section")
            state = {"camera": camera, "wallet": wallet, "network_fixed": network_fixed}
            with Vertical(id="paths"):
                for index, path in enumerate(PATHS):
                    available = is_available(path, **state)
                    classes = ["path"] if available else ["path", "path-unavailable"]
                    if index == self._selected:
                        classes.append("path-selected")
                    yield Static(
                        row(
                            path,
                            app,
                            selected=index == self._selected,
                            why="" if available else reason(path, **state),
                        ),
                        id=f"path-{index}",
                        classes=" ".join(classes),
                    )
            with Vertical(id="notes"):
                yield Static(NETWORK_FIXED if network_fixed else CHOOSE_NETWORK, id="network")
                note = camera_note(condition)
                if note is not None:
                    yield Static(note, id="no-camera")
                for index, line in enumerate(late_arrival_lines(arrivals)):
                    yield Static(line, id=f"late-arrival-{index}")
                yield Static(NO_WALLET if not wallet else HAVE_WALLET, id="no-wallet")
                if notice:
                    yield Static(notice, id="notice")
            yield Static(KEYS, id="home-keys", classes="keys")

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
            network_fixed=app.network_fixed,  # type: ignore[attr-defined]
        ):
            return
        if path.scans is not None:
            app.open_scan(path.scans)  # type: ignore[attr-defined]
        elif path.opens is not None:
            getattr(app, path.opens)()
