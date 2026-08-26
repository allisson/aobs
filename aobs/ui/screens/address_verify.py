"""The scanned address, proved or not proved — and never called *not yours*.

The screen renders `core.address.verify(scanned, wallet, blocks=…)` and derives nothing. It holds
the scanned text and how many blocks the *user* has asked for, and that is the whole of its
state: `docs/address-verification.md`'s rule is that the window is never widened by anything the
address itself says, and the only way to guarantee that is for the widening to live in a key
press.

Four verdicts, four treatments:

* **Proven** leads with the path and de-emphasises the address, exactly as the review screen
  de-emphasises proven change. Inviting someone to eye-verify a string the machine has already
  proven trains a habit with no value, and habits with no value are what make the checks that
  matter get skipped.
* **Not found** is the failure shape: what was searched, and two next steps with no default.
  Never *not yours* — the two causes are indistinguishable from here.
* **Wrong network** is its own message, and **no search is offered**: no depth would ever reach it.
* **Unreadable** says the scan carried no address at all, which is a different thing from a miss.

Nothing an attacker chose is on this screen but the address itself. `amount`, `label` and
`message` were dropped by `parse_scanned()` and never reach here in any form.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Static

from aobs.core.address import AddressCheck, Verdict, verify
from aobs.core.constants import ADDRESS_SEARCH_BLOCK
from aobs.ui import addresstext
from aobs.ui.widgets.failure import FailurePanel


class AddressVerifyScreen(Screen):
    BINDINGS = [
        Binding(addresstext.SEARCH_FURTHER_KEY, "search_further", "Search further"),
    ]

    DEFAULT_CSS = """
    AddressVerifyScreen #verify-lead { margin-bottom: 1; }
    AddressVerifyScreen #verify-path { text-style: bold; margin-left: 2; }
    AddressVerifyScreen #verify-address { margin-left: 2; margin-top: 1; }
    AddressVerifyScreen .verify-address-dim { text-style: dim; }
    AddressVerifyScreen #verify-note { margin-top: 1; }
    AddressVerifyScreen #verify-keys { margin-top: 1; }
    """

    def __init__(self, scanned: str) -> None:
        super().__init__()
        self._scanned = scanned
        #: How many blocks of `ADDRESS_SEARCH_BLOCK` the **user** has asked for. One to begin
        #: with, and it only ever grows by a key press.
        self.blocks = 1

    @property
    def check(self) -> AddressCheck:
        """The verdict as it stands. Recomputed rather than cached: 200 addresses derive in 47 ms
        and a cache is one more thing that can disagree with the window on screen."""
        return verify(self._scanned, self.app.wallet, blocks=self.blocks)  # type: ignore[attr-defined]

    def compose(self) -> ComposeResult:
        check = self.check
        with Vertical(id="frame"):
            yield Static(addresstext.TITLE, id="title")
            if check.verdict is Verdict.PROVEN:
                yield from self._proven(check)
            else:
                yield from self._not_proven(check)

    def _proven(self, check: AddressCheck) -> ComposeResult:
        assert check.proven is not None
        yield Static(addresstext.PROVEN_LEAD, id="verify-lead")
        yield Static(check.proven.path, id="verify-path")
        # De-emphasised, and below the path: the path is the substance and the address is the
        # thing the machine has already checked.
        yield Static(
            addresstext.scanned_address(check) or "",
            id="verify-address",
            classes="verify-address-dim",
        )
        yield Static(addresstext.PROVEN_NOTE, id="verify-note")
        yield Static(addresstext.KEYS, id="verify-keys")

    def _not_proven(self, check: AddressCheck) -> ComposeResult:
        yield FailurePanel(
            addresstext.verdict_failure(
                check,
                self.app.wallet.network,  # type: ignore[attr-defined]
                block=ADDRESS_SEARCH_BLOCK,
            ),
            id="verify-failure",
        )
        address = addresstext.scanned_address(check)
        if address is not None:
            # What was scanned, in full and grouped in fours. Nothing else off the QR is shown.
            yield Static(address, id="verify-address")
        yield Static(
            addresstext.KEYS_SEARCHABLE if check.offers_deeper_search else addresstext.KEYS,
            id="verify-keys",
        )

    def action_search_further(self) -> None:
        """One more block on each chain, because the user asked for one.

        Offered only where a deeper search could ever help — a wrong-network address could not
        match at any index, and offering to look further would send the user hunting for nothing.
        """
        if not self.check.offers_deeper_search:
            return
        self.blocks += 1
        self.refresh(recompose=True)
