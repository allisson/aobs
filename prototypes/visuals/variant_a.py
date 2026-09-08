"""PROTOTYPE variant A — "Typeset".

The bet: nothing is wrong with the *shape* of the home screen, it is simply not typeset. No
palette at all — the only two colours are the terminal's own foreground and background, swapped
for the selected row. Survives a monochrome console, a broken palette and a photograph of a glossy
Chromebook panel, which is the strongest thing that can be said for a design here.

What it changes: a header row with the session state on the right of it, a rule under it, a
section label, a full-width selection bar instead of `>` plus `bold`, a right-hand reason on every
unavailable row instead of `dim` alone, and the keys pinned to the bottom of the console so the
block stops floating in a third of the screen.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Rule, Static

from aobs.ui.screens.home import (
    CHOOSE_NETWORK,
    KEYS,
    NETWORK_FIXED,
    NO_CAMERA,
    NO_WALLET,
    PATHS,
    HomeScreen,
    is_available,
    label,
)

from bar import PrototypeBar

NAME = "Typeset (no colour)"

CSS = """
/* One block, vertically centred. There are 48 rows and about 22 of content, so a hole is not
   avoidable — it is only placeable, and split above and below reads as composition rather than as
   a block that fell to the top of the screen. */
VariantA { align: center middle; }
VariantA #frame { width: 96; max-width: 100%; height: auto; padding: 0 3; }

VariantA #head { height: 1; }
VariantA #head-name { width: 1fr; text-style: bold; }
VariantA #head-state { width: auto; }
VariantA Rule { margin: 0; }

VariantA #section { margin-top: 1; }
VariantA #paths { height: auto; margin-top: 1; }
VariantA .row { height: 1; }
VariantA .row-name { width: 1fr; }
VariantA .row-why { width: auto; }
VariantA .selected { background: ansi_white; color: ansi_black; text-style: bold; }
VariantA .unavailable { text-style: dim; }

VariantA #notes { height: auto; margin-top: 1; }
VariantA #foot { height: 2; margin-top: 1; }
VariantA #keys { height: 1; }
"""


def reason(path, *, camera: bool, wallet: bool, network_fixed: bool) -> str:
    """The short right-hand tag. Redundant with `dim` on purpose — half-bright on `fbcon` is
    exactly the kind of thing that is either subtle or absent, and the distinction between a path
    that can be walked and one that cannot is not allowed to rest on it."""
    if path.needs_wallet and not wallet:
        return "needs a wallet"
    if path.needs_camera and not camera:
        return "needs a camera"
    if path.needs_unfixed_network and network_fixed:
        return "fixed for this session"
    return ""


class VariantA(HomeScreen):
    def compose(self) -> ComposeResult:
        yield PrototypeBar(0, 3, NAME)

        app = self.app
        camera = app.camera_available
        wallet = app.wallet is not None
        fixed = app.network_fixed
        state = {"camera": camera, "wallet": wallet, "network_fixed": fixed}

        with Vertical(id="frame"):
            with Horizontal(id="head"):
                yield Static("aobs", id="head-name")
                yield Static(
                    f"{app.network.value}  {chr(0xB7)}  {app.release.version_label}",
                    id="head-state",
                )
            yield Rule(line_style="solid")
            yield Static("WHAT YOU CAN DO", id="section")

            with Vertical(id="paths"):
                for index, path in enumerate(PATHS):
                    available = is_available(path, **state)
                    selected = index == self._selected
                    extra = ("selected" if selected else "") + ("" if available else " unavailable")
                    with Horizontal(classes=f"row {extra}"):
                        marker = chr(0x25BA) if selected else " "
                        yield Static(f"{marker} {label(path, app)}", classes=f"row-name {extra}")
                        yield Static(
                            reason(path, **state) + " ", classes=f"row-why {extra}"
                        )

            with Vertical(id="notes"):
                yield Static(NETWORK_FIXED if fixed else CHOOSE_NETWORK)
                if not camera:
                    yield Static(NO_CAMERA)
                if not wallet:
                    yield Static(NO_WALLET)
                if app.notice:
                    yield Static(app.notice)

            with Vertical(id="foot"):
                yield Rule(line_style="solid")
                yield Static(KEYS, id="keys")
