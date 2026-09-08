#!/usr/bin/env python3
"""PROTOTYPE, throwaway — three answers to *what should the appliance's console look like*.

    uv run python prototypes/visuals/run.py            # starts on A
    uv run python prototypes/visuals/run.py C          # starts on C
    uv run python prototypes/visuals/run.py --truecolor    # opt out of the 16-colour emulation

`uv run`, or `.venv/bin/python`, and not a bare `python`: `textual` is a project dependency and
lives in the project's environment, not in the one on `PATH`.

Keys:  left/right cycle the variant  ·  w loaded wallet  ·  c camera  ·  n a notice
       F12 quits (the real key), esc does nothing (the real behaviour).

Three variants on the **home screen**, because that is the screen in the photograph and the one
with real density: ten paths, three availability rules, three sentences and a key line. Each
variant restyles the app-level chrome too, so a winner is a visual system rather than one screen.

`F10` is inert here. The session's wallet is a sentinel rather than a derived one — the point is
the ten rows and their availability, and `Wallet.from_mnemonic` on a dev machine without a
loadable `libsecp256k1` is the slow path `docs/boot-pipeline.md` forbids anyway.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# The appliance's PID 1 exports no `TERM` (`build/init`), so `rich` resolves the console to
# `standard` — 16 ANSI colours, and every truecolor value in a Textual theme gets downsampled into
# them. Emulating that here is the difference between judging the design and judging a downsample
# the appliance will never show. Must precede the first `textual` import: `textual.constants` reads
# the environment once.
if "--truecolor" not in sys.argv:
    os.environ["TEXTUAL_COLOR_SYSTEM"] = "standard"

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from textual.binding import Binding  # noqa: E402

from aobs.adapters.fake import (  # noqa: E402
    FixedEntropySource,
    ImageFileFrameSource,
    RecordingKeymap,
    RecordingPower,
)
from aobs.ui.app import SignerApp  # noqa: E402
from aobs.ui.screens.home import PATHS  # noqa: E402

import variant_a  # noqa: E402
import variant_b  # noqa: E402
import variant_c  # noqa: E402

VARIANTS = (
    (variant_a.VariantA, variant_a.NAME),
    (variant_b.VariantB, variant_b.NAME),
    (variant_c.VariantC, variant_c.NAME),
)

#: One sentence of the shape the appliance actually writes about its own state, to see where each
#: variant puts it.
SAMPLE_NOTICE = "The scan was left part-way through, so nothing was read."

_WALLET = object()  # `is_available` asks `is not None` and nothing else does.


class PrototypeApp(SignerApp):
    # One CSS source, base first and the variants after it, so a tie on specificity goes to the
    # variant. `VariantA #frame` (id + type) beats the base `#frame` (id) outright.
    CSS = (
        SignerApp.CSS
        + variant_a.CSS
        + variant_b.CSS
        + variant_c.CSS
        + """
    Screen { background: ansi_default; color: ansi_default; }
    """
    )

    BINDINGS = [
        *SignerApp.BINDINGS,
        Binding("right", "next_variant", "Next variant", priority=True),
        Binding("left", "previous_variant", "Previous variant", priority=True),
        Binding("w", "toggle_wallet", "Wallet", priority=True),
        Binding("c", "toggle_camera", "Camera", priority=True),
        Binding("n", "toggle_notice", "Notice", priority=True),
    ]

    def __init__(self, index: int) -> None:
        super().__init__(
            frames=ImageFileFrameSource([]),
            entropy=FixedEntropySource(),
            power=RecordingPower(),
            keymap=RecordingKeymap(),
        )
        self._index = index

    # Not `on_mount`: Textual dispatches an `on_` handler for *every* class in the MRO, so
    # `SignerApp.on_mount` runs too and pushes the keymap picker on top of whatever this does.
    # `Ready` fires after all of them, and `switch_screen` replaces the picker rather than
    # stacking over it.
    def on_ready(self) -> None:
        # `ansi-dark` is the only honest theme here: every value in it is one of the 16 the console
        # has, so nothing is being approximated on the way to the panel. The size floor is a
        # warning in the bar rather than `ConsoleTooSmallScreen`, so a small terminal still shows
        # the design.
        self.theme = "ansi-dark"
        self.camera_available = True
        self.switch_screen(VARIANTS[self._index][0]())

    def _show(self, index: int) -> None:
        self._index = index % len(VARIANTS)
        self.switch_screen(VARIANTS[self._index][0]())

    def action_next_variant(self) -> None:
        self._show(self._index + 1)

    def action_previous_variant(self) -> None:
        self._show(self._index - 1)

    def action_toggle_wallet(self) -> None:
        self.wallet = None if self.wallet is not None else _WALLET
        self.network_fixed = self.wallet is not None
        self.screen.refresh(recompose=True)

    def action_toggle_camera(self) -> None:
        self.camera_available = not self.camera_available
        self.screen.refresh(recompose=True)

    def action_toggle_notice(self) -> None:
        self.notice = None if self.notice else SAMPLE_NOTICE
        self.screen.refresh(recompose=True)

    def _inert(self, what: str) -> None:
        self.notice = f"[prototype] F10 would open: {what}"
        self.screen.refresh(recompose=True)

    def open_scan(self, target) -> None:
        self._inert(f"the scan screen, for {target.name.lower()}")


# Every `opens=` on the home screen, stubbed. A prototype answers what this looks like, not
# whether the paths work — and the sentinel wallet would take the real screens apart.
for _opens in sorted({path.opens for path in PATHS if path.opens}):
    setattr(PrototypeApp, _opens, (lambda name: lambda self: self._inert(name))(_opens))


def main() -> None:
    letters = "ABC"
    chosen = next(
        (arg.upper() for arg in sys.argv[1:] if arg.upper() in letters),
        os.environ.get("AOBS_VARIANT", "A").upper(),
    )
    PrototypeApp(letters.index(chosen if chosen in letters else "A")).run()


if __name__ == "__main__":
    main()
