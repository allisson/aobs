"""PROTOTYPE — throwaway. Candidate (a): framebuffer TUI, Textual on the Linux console.

Run:  uv run --python 3.12 --with embit --with segno --with textual python tui_textual.py

Two screens, `space` to switch:
  REVIEW — the PSBT review screen, the appliance's hardest layout
  QR     — a real 77x77-module QR (735-byte UR-ish payload) rendered in character cells

The question this stub exists to answer: does the QR actually scan off a terminal?
Point a phone at the QR screen. Half-block rendering gives two vertical modules per
character cell, so on a console with an 8x16 font each module lands 8x8 — square.
In a proportional-ish macOS terminal it will be square only if the cell is 1:2.
"""

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Static

import fixture as fx

QUIET = 4


def qr_text():
    rows, size, ver = fx.qr_matrix()
    pad = [[False] * (size + QUIET * 2) for _ in range(QUIET)]
    body = [[False] * QUIET + r + [False] * QUIET for r in rows]
    grid = pad + body + pad
    if len(grid) % 2:
        grid.append([False] * len(grid[0]))

    out = Text()
    for y in range(0, len(grid), 2):
        top, bot = grid[y], grid[y + 1]
        for x in range(len(top)):
            t, b = top[x], bot[x]
            out.append(
                "█" if (t and b) else "▀" if t else "▄" if b else " ",
                style="black on white",
            )
        out.append("\n")
    return out, size, ver, len(grid[0])


class Review(Static):
    def compose(self) -> ComposeResult:
        r = fx.REVIEW
        yield Static(
            f"[b]REVIEW AND SIGN[/b]   network [b]{r['network']}[/b]   "
            f"wallet [b]{r['fingerprint']}[/b]",
            classes="hdr",
        )
        with Horizontal():
            with Vertical(classes="col"):
                yield Static("[b]SPENDING[/b]", classes="sub")
                for i in r["inputs"]:
                    yield Static(
                        f"  {fx.btc(i['sats'])} BTC\n"
                        f"  [dim]{i['txid'][:16]}…:{i['vout']}[/dim]\n"
                        f"  [dim]{i['derivation']}[/dim]"
                    )
                yield Static(
                    f"\n  total [b]{fx.btc(r['spending_total_sats'])} BTC[/b]",
                    classes="tot",
                )
            with Vertical(classes="col"):
                yield Static("[b]PAYING[/b]", classes="sub")
                for o in r["outputs"]:
                    tag = (
                        "[b white on dark_green] CHANGE [/]"
                        if o["kind"] == "change"
                        else "[b white on dark_red] PAYMENT [/]"
                    )
                    yield Static(
                        f"  {tag} [b]{fx.btc(o['sats'])} BTC[/b]\n"
                        f"  {o['address']}\n"
                        + (f"  [green]✓ {o['note']}[/green]" if o["note"] else "")
                    )
        yield Static(
            f"\n[b]FEE[/b] {fx.btc(r['fee_sats'])} BTC  ({fx.sats(r['fee_sats'])} sats, "
            f"{r['fee_rate']}, {r['vsize']} vB)",
            classes="fee",
        )
        for w in r["warnings"]:
            yield Static(f"[b black on yellow] ! [/] {w}", classes="warn")


class QRScreen(Static):
    def compose(self) -> ComposeResult:
        art, size, ver, cols = qr_text()
        yield Static(
            f"[b]SCAN THIS[/b]   signed PSBT, frame 1 of 3   "
            f"[dim]QR v{ver}, {size}×{size} modules, {cols} cells wide[/dim]",
            classes="hdr",
        )
        yield Static(art)


class Proto(App):
    CSS = """
    Screen { background: black; }
    .hdr { background: $primary; color: white; padding: 0 1; }
    .sub { color: $accent; padding: 1 0 0 0; }
    .col { width: 1fr; padding: 0 1; }
    .fee { padding: 0 1; }
    .warn { padding: 0 1; }
    .tot { padding: 0 1; }
    """
    BINDINGS = [
        Binding("space", "flip", "review / qr"),
        Binding("q", "quit", "quit"),
    ]

    def __init__(self):
        super().__init__()
        self.showing_qr = False

    def compose(self) -> ComposeResult:
        yield Review(id="rev")
        yield QRScreen(id="qr")
        yield Footer()

    def on_mount(self):
        self.query_one("#qr").display = False

    def action_flip(self):
        self.showing_qr = not self.showing_qr
        self.query_one("#rev").display = not self.showing_qr
        self.query_one("#qr").display = self.showing_qr


if __name__ == "__main__":
    Proto().run()
