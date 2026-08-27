"""Which chain this session is on, chosen before any wallet exists.

`docs/network-selection.md` settled the three things this screen encodes:

- **Mainnet is the default and costs nothing.** The appliance is written for a stranger booting the
  ISO with real funds, and the most common path is not the one that should ask the most. Nobody
  reaches this screen unless they mean to.
- **It is opened with `F10`, like every other path.** It used to move under `left`/`right` on the
  home screen, which made it the only setting on the appliance that changed without the one accept
  key the appliance teaches — and put a money-affecting choice one key away from the `up`/`down`
  that selects a path.
- **It is reachable only while the network is still unfixed.** Once a wallet has been constructed
  the addresses are derived on this network, and `SignerApp.network_fixed` never goes back.

There is no *are you sure*: the choice is reversible right up until a wallet is made, and it is
stated again on the fingerprint screen at the moment it stops being.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Static

from aobs.core.wallet import Network

NETWORKS: tuple[Network, ...] = tuple(Network)

WHY = (
    "A wallet's addresses are derived on this network, so it is chosen before the wallet and "
    "fixed for the rest of the session once one is loaded. Mainnet is the real chain; the other "
    "three are for testing."
)

KEYS = "up/down choose  ·  F10 use this network  ·  esc back  ·  F12 power off"


class NetworkScreen(Screen):
    BINDINGS = [
        Binding("up", "previous", "Previous network"),
        Binding("down", "next", "Next network"),
        # Never `enter`, never `esc` — `docs/failure-states.md`.
        Binding("f10", "accept", "Use this network"),
    ]

    DEFAULT_CSS = """
    NetworkScreen #networks { height: auto; margin: 1 0; }
    NetworkScreen .network { margin-left: 2; }
    NetworkScreen .network-selected { text-style: bold; }
    NetworkScreen #network-keys { margin-top: 1; }
    """

    def __init__(self, current: Network) -> None:
        super().__init__()
        #: Opens on the session's current network rather than at the top of the list, so `esc` and
        #: `F10` without moving are the same no-op and neither can change the session by accident.
        self._selected = NETWORKS.index(current)

    @property
    def selected_network(self) -> Network:
        return NETWORKS[self._selected]

    def compose(self) -> ComposeResult:
        with Vertical(id="frame"):
            yield Static("Which network?", id="title")
            yield Static(WHY, id="network-why")
            with Vertical(id="networks"):
                for index in range(len(NETWORKS)):
                    yield Static("", classes="network", id=f"network-{index}")
            yield Static(KEYS, id="network-keys")

    def on_mount(self) -> None:
        self._repaint()

    def action_previous(self) -> None:
        self._selected = (self._selected - 1) % len(NETWORKS)
        self._repaint()

    def action_next(self) -> None:
        self._selected = (self._selected + 1) % len(NETWORKS)
        self._repaint()

    def action_accept(self) -> None:
        self.app.accept_network(self.selected_network)  # type: ignore[attr-defined]

    def _repaint(self) -> None:
        for index, network in enumerate(NETWORKS):
            widget = self.query_one(f"#network-{index}", Static)
            chosen = index == self._selected
            widget.update(f"{'>' if chosen else ' '} {network.value}")
            widget.set_class(chosen, "network-selected")
