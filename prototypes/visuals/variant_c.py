"""PROTOTYPE variant C — "Session ledger".

The bet is structural, not decorative: the three sentences under the list on the current screen are
all answers to *what state is this session in*, and they are appended to the bottom where a user
reads them once and then stops seeing them. So the session state becomes a permanent right-hand
column — network, wallet, camera, build, always all four, always in the same place — and the
sentence that says why a path cannot be walked appears there too, about the path the user is
actually pointing at.

The list on the left stays a list. Nothing is hidden: an unavailable path keeps its row and gains a
gutter mark, and the sentence explaining it is one row-move away rather than absent.
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

NAME = "Session ledger (two columns)"

CSS = """
VariantC { align-horizontal: center; }
VariantC #frame { width: 96; max-width: 100%; height: 1fr; padding: 1 3 0 3; }

VariantC #head { height: 1; }
VariantC #head-name { width: 1fr; text-style: bold; }
VariantC #head-state { width: auto; }
VariantC Rule { margin: 0; }

VariantC #body { height: 1fr; margin-top: 1; }
VariantC #list { width: 1fr; height: auto; }
VariantC .row { height: 1; }
VariantC .row-name { width: 1fr; }
VariantC .row-mark { width: 3; text-align: right; }
VariantC .selected { background: ansi_white; color: ansi_black; text-style: bold; }
VariantC .unavailable { text-style: dim; }

VariantC #panel { width: 34; height: 1fr; border-left: solid ansi_white; padding: 0 0 0 2; }
VariantC .panel-head { text-style: bold; margin-bottom: 1; }
VariantC .kv { height: 1; }
VariantC .k { width: 10; }
VariantC .v { width: 1fr; }
VariantC #why { height: auto; margin-top: 1; }

VariantC #foot { dock: bottom; height: 2; }
VariantC #keys { height: 1; }
"""


def why(path, *, camera: bool, wallet: bool, network_fixed: bool) -> str:
    """The whole sentence, about the selected path only. Same sentences the screen prints today."""
    if path.needs_wallet and not wallet:
        return NO_WALLET
    if path.needs_camera and not camera:
        return NO_CAMERA
    if path.needs_unfixed_network:
        return NETWORK_FIXED if network_fixed else CHOOSE_NETWORK
    return ""


class VariantC(HomeScreen):
    def compose(self) -> ComposeResult:
        yield PrototypeBar(2, 3, NAME)

        app = self.app
        camera = app.camera_available
        wallet = app.wallet is not None
        fixed = app.network_fixed
        state = {"camera": camera, "wallet": wallet, "network_fixed": fixed}

        with Vertical(id="frame"):
            with Horizontal(id="head"):
                yield Static("aobs", id="head-name")
                yield Static(app.release.version_label, id="head-state")
            yield Rule(line_style="solid")

            with Horizontal(id="body"):
                with Vertical(id="list"):
                    for index, path in enumerate(PATHS):
                        selected = index == self._selected
                        available = is_available(path, **state)
                        extra = ("selected" if selected else "") + (
                            "" if available else " unavailable"
                        )
                        with Horizontal(classes=f"row {extra}"):
                            yield Static(
                                f"{chr(0x25BA) if selected else ' '} {label(path, app)}",
                                classes=f"row-name {extra}",
                            )
                            yield Static(
                                ("" if available else chr(0xD7)) + " ",
                                classes=f"row-mark {extra}",
                            )

                with Vertical(id="panel"):
                    yield Static("THIS SESSION", classes="panel-head")
                    for key, value in (
                        ("network", f"{app.network.value}{'' if fixed else ' (open)'}"),
                        ("wallet", "loaded" if wallet else "none"),
                        ("camera", "found" if camera else "none"),
                        ("build", "development" if app.release.is_development else "release"),
                    ):
                        with Horizontal(classes="kv"):
                            yield Static(key, classes="k")
                            yield Static(value, classes="v")

                    sentence = why(PATHS[self._selected], **state)
                    with Vertical(id="why"):
                        if sentence:
                            yield Static("THIS PATH", classes="panel-head")
                            yield Static(sentence)
                        if app.notice:
                            yield Static(app.notice)

            with Vertical(id="foot"):
                yield Rule(line_style="solid")
                yield Static(KEYS, id="keys")
