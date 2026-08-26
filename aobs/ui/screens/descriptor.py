"""The descriptor going out: one static `ur:crypto-output`, at ECC H.

Static, roughly 150 characters, and read once. Size is a non-issue and the angle is not — so this
is `QR_ECC_STATIC` (H) and there is no animation, no fountain and no step-down ladder. It reuses
#30's renderer at static parameters rather than growing a second rendering path.

**BIP84 and BIP86 are separate URs on purpose**, so `F9` toggles which one is on screen. Green's
`ur-c` returns `URC_ETAPROOTNOTSUPPORTED` for the taproot tag and rejects a combined export
*whole*, taking the BIP84 descriptor down with it (`aobs/core/descriptor.py`). Separate URs means
Green's taproot gap costs the user taproot and nothing else — but it also means only one of the
two can be on screen at a time, and the user needs a way to reach the other.

Nothing here can spend: the payload carries the account *public* key, its origin path and the
master fingerprint.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Center, Vertical
from textual.screen import Screen
from textual.widgets import Static

from aobs.core.constants import QR_ECC_STATIC
from aobs.core.descriptor import output_descriptor_ur
from aobs.core.wallet import ScriptType
from aobs.ui import addresstext, qrcodes

SCRIPT_TYPE_KEY = "f9"


class DescriptorScreen(Screen):
    BINDINGS = [Binding(SCRIPT_TYPE_KEY, "toggle_script_type", "Script type")]

    DEFAULT_CSS = """
    DescriptorScreen #qr-row { height: auto; }
    DescriptorScreen #descriptor-qr { width: auto; height: auto; }
    DescriptorScreen #descriptor-which { margin-top: 1; text-style: bold; }
    DescriptorScreen #descriptor-keys { margin-top: 1; }
    """

    def __init__(self, script_type: ScriptType = ScriptType.P2WPKH) -> None:
        super().__init__()
        self.script_type = script_type

    @property
    def payload(self) -> str:
        """The exact string behind the code, so a test asserts the payload and not a rendering.

        Derived rather than stored: a cached copy is one more thing that can disagree with the
        script type on screen, and the encoding is a few hundred microseconds.
        """
        return output_descriptor_ur(
            self.app.wallet,  # type: ignore[attr-defined]
            self.script_type,
        )

    def compose(self) -> ComposeResult:
        with Vertical(id="frame"):
            yield Static(addresstext.DESCRIPTOR_TITLE, id="title")
            with Center(id="qr-row"):
                yield Static(
                    qrcodes.render(self.payload, ecc=QR_ECC_STATIC).text, id="descriptor-qr"
                )
            yield Static(addresstext.SCRIPT_TYPE_NAMES[self.script_type], id="descriptor-which")
            yield Static(addresstext.DESCRIPTOR_INSTRUCTION, id="descriptor-instruction")
            yield Static(addresstext.DESCRIPTOR_NEXT, id="descriptor-next")
            yield Static(addresstext.DESCRIPTOR_KEYS, id="descriptor-keys")

    def action_toggle_script_type(self) -> None:
        self.script_type = (
            ScriptType.P2TR if self.script_type is ScriptType.P2WPKH else ScriptType.P2WPKH
        )
        self.refresh(recompose=True)
