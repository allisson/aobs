"""PROTOTYPE variant B — "Instrument".

The bet: this is an appliance, not a document, and it should look like one — a drawn frame that
says where the machine's screen ends, a titled panel for the paths, and an F-key bar welded to the
bottom row of the console the way every BIOS and every installer the user has ever met has one.

Colour is used for exactly one thing beyond structure: the network. It is the only money-affecting
value on the screen, so mainnet is the loud one and a test chain is not, and that is the only
place a colour carries meaning rather than decoration.

Every glyph here is CP437 (`solid` and `double` borders only). `round` and `heavy` are not: the
appliance never runs `setfont`, so the font is the kernel's built-in 8x16 and `{U+256D}` has
nowhere to land.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Static

from aobs.core.release import identity_line
from aobs.core.wallet import Network
from aobs.ui.screens.home import (
    CHOOSE_NETWORK,
    NETWORK_FIXED,
    NO_CAMERA,
    NO_WALLET,
    PATHS,
    HomeScreen,
    is_available,
    label,
)

from bar import PrototypeBar

NAME = "Instrument panel"

CSS = """
VariantB { align-horizontal: center; }
VariantB #frame {
    width: 96; max-width: 100%; height: 1fr;
    border: double ansi_white; padding: 1 2;
    border-title-align: left; border-subtitle-align: right;
}

VariantB #head {
    height: 1; margin-bottom: 1;
    background: ansi_blue; color: ansi_bright_white;
}
VariantB #head-label { width: 1fr; padding: 0 1; }
VariantB #head-network { width: auto; text-style: bold; padding: 0 1; }

/* `1fr`, so the panel reaches the bottom of the frame and the session box sits under it. The
   variant's whole claim is that the machine's screen is a drawn instrument, and an instrument
   whose panel stops a third of the way down is a document with a border on it. */
VariantB #panel {
    height: 1fr; border: solid ansi_white; padding: 0 1;
    border-title-align: left;
}
VariantB .row { height: 1; }
VariantB .row-name { width: 1fr; }
VariantB .row-why { width: auto; color: ansi_yellow; }
VariantB .selected { background: ansi_blue; color: ansi_bright_white; text-style: bold; }
VariantB .unavailable { color: ansi_white; text-style: dim; }

VariantB #notes {
    height: auto; margin-top: 1; border: solid ansi_white; padding: 0 1;
    border-title-align: left;
}
/* `margin: 0` on purpose: `.note` is `HomeScreen`'s own class and its `DEFAULT_CSS` puts a
   `margin-top: 1` on it, which inside a box reads as a stray blank row. */
VariantB .note { height: auto; margin: 0; }

/* Two rows welded to the bottom of the console: the F-key bar, and the prototype's own bar under
   it. They need the wrapper — two siblings docked to the same edge overlap. */
VariantB #footbars { dock: bottom; height: 2; }
VariantB #keybar {
    height: 1; width: 100%;
    background: ansi_blue; color: ansi_bright_white;
}
"""

#: The F-key bar. Reads as a bar rather than a sentence, which is the point of the variant.
KEYBAR = (
    f"  {chr(0x2191)}{chr(0x2193)} choose "
    f" {chr(0x2502)}  F10 open this path "
    f" {chr(0x2502)}  F12 power off  "
)


def tag(path, *, camera: bool, wallet: bool, network_fixed: bool) -> str:
    if not is_available(path, camera=camera, wallet=wallet, network_fixed=network_fixed):
        return "unavailable"
    return ""


class VariantB(HomeScreen):
    def compose(self) -> ComposeResult:
        with Vertical(id="footbars"):
            yield Static(KEYBAR, id="keybar")
            yield PrototypeBar(1, 3, NAME)

        app = self.app
        camera = app.camera_available
        wallet = app.wallet is not None
        fixed = app.network_fixed
        state = {"camera": camera, "wallet": wallet, "network_fixed": fixed}
        loud = app.network is Network.MAINNET

        with Vertical(id="frame") as frame:
            frame.border_title = "aobs"
            frame.border_subtitle = identity_line(app.release)

            # The network badge, and the one place colour carries meaning here: mainnet is the
            # loud one because it is the only value on the screen that costs money to get wrong.
            with Horizontal(id="head"):
                yield Static("OFFLINE SIGNER", id="head-label")
                badge = Static(app.network.value.upper(), id="head-network")
                badge.styles.background = "ansi_bright_yellow" if loud else "ansi_cyan"
                badge.styles.color = "ansi_black"
                yield badge

            with Vertical(id="panel") as panel:
                panel.border_title = "PATHS"
                for index, path in enumerate(PATHS):
                    selected = index == self._selected
                    available = is_available(path, **state)
                    extra = ("selected" if selected else "") + ("" if available else " unavailable")
                    with Horizontal(classes=f"row {extra}"):
                        yield Static(
                            f"{chr(0x25BA) if selected else ' '} {label(path, app)}",
                            classes=f"row-name {extra}",
                        )
                        yield Static(tag(path, **state), classes=f"row-why {extra}")

            with Vertical(id="notes") as notes:
                notes.border_title = "THIS SESSION"
                yield Static(NETWORK_FIXED if fixed else CHOOSE_NETWORK, classes="note")
                if not camera:
                    yield Static(NO_CAMERA, classes="note")
                if not wallet:
                    yield Static(NO_WALLET, classes="note")
                if app.notice:
                    yield Static(app.notice, classes="note")
