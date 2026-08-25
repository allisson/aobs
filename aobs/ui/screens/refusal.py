"""A refused PSBT: three sentences, and back to the scan screen with the wallet still loaded.

The three sentences are **what it is, why it stops, and where the fix is** — so that the user does
not retry blindly (`docs/failure-states.md`). Which fix is offered comes from
`reviewtext.REFUSAL_KINDS`, where every `RefusalReason` declares its kind in one place, and
`MALFORMED` is the only reason that says *try scanning again*: a truncated scan is the only cause a
retry fixes, and diluting that one honest retry with five dishonest ones is how a user learns to
ignore it.

**No override and no confirmation button.** The failure widget cannot hold a `Button` at all, which
is the point of there being one widget. `esc` returns to the scan screen with the wallet still
loaded — dropping it buys nothing (it is in RAM regardless, and a refusal means the attack failed)
and costs 24 words and a passphrase.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Static

from aobs.core.review import Refusal
from aobs.ui.reviewtext import refusal_failure
from aobs.ui.widgets.failure import FailurePanel


class RefusalScreen(Screen):
    def __init__(self, refusal: Refusal) -> None:
        super().__init__()
        self.refusal = refusal
        self.failure = refusal_failure(refusal)

    def compose(self) -> ComposeResult:
        with Vertical(id="frame"):
            yield Static("This transaction was not signed", id="title")
            yield FailurePanel(self.failure)
