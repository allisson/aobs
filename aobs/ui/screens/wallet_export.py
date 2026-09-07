"""The encrypted wallet QR going out: four screens, and the password on none of the same ones.

`docs/export-password.md` and `docs/encrypted-wallet-qr.md` between them fix the whole shape:

1. **The ciphertext**, as one static QR at ECC H — read once, off paper, at an unknown angle.
   It states plainly that the password is not on it, because a user who does not know a second
   artifact exists photographs this one and believes they have a backup. It also names the
   network this backup is for: the container carries it, a session on another network refuses
   it, and what the user writes on the paper should agree with what the QR holds.
2. **The eight words**, numbered 1–8, one per line, in a fixed-width column, on a screen with
   nothing on it but the instruction to write them down. Never the same screen as the QR:
   together they are one photograph, and that is the whole attack.
3. **The read-back**, all eight and not a subset. Sampling three of eight misses the single
   mistranscribed word 62% of the time, and this is the only moment that error is cheap to catch.
   A failure retries **the same password** — a fresh one would silently invalidate whatever the
   user has already written down.
4. **The closing message**, which branches on `Wallet.has_passphrase` because the truth genuinely
   differs and the appliance knows which case it is in. Printing the passphrase-set message to a
   user with no passphrase is a lie that gets people robbed.

**The password is re-showable for the rest of the session** — `F9`, from the read-back and from
the closing screen. Show-once is a security reflex and it is wrong here: the password is in RAM
either way, so refusing to redisplay protects nothing, while a user who looked away mid-
transcription and cannot get the words back either abandons the export or writes down a guess.

**No user-chosen password.** `export_wallet()` takes no password parameter and nothing here
offers one; the enforcement is the absence of the feature.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Center, Vertical
from textual.screen import Screen
from textual.widgets import Static

from aobs.core.constants import EXPORT_PASSWORD_WORDS, QR_ECC_STATIC
from aobs.core.wallet_qr import ExportedWallet
from aobs.ui import addresstext, qrcodes
from aobs.ui.widgets.wordgrid import EFF
from aobs.ui.wordentry import WordEntryScreen


class WalletQrScreen(Screen):
    """The ciphertext, and a sentence saying where the password is not."""

    BINDINGS = [
        # Never `enter`, never `esc` — `docs/failure-states.md`.
        Binding("f10", "show_password", "Show the password"),
    ]

    DEFAULT_CSS = """
    WalletQrScreen #qr-row { height: auto; }
    WalletQrScreen #wallet-qr { width: auto; height: auto; }
    WalletQrScreen #wallet-qr-password-not-here { margin-top: 1; text-style: bold; }
    WalletQrScreen #wallet-qr-network { margin-top: 1; }
    WalletQrScreen #wallet-qr-keys { margin-top: 1; }
    """

    def __init__(self, export: ExportedWallet) -> None:
        super().__init__()
        self.export = export

    @property
    def container(self) -> bytes:
        """The exact bytes behind the code, so a test asserts the payload and not a rendering."""
        return self.export.container

    def compose(self) -> ComposeResult:
        with Vertical(id="frame"):
            yield Static(addresstext.EXPORT_QR_TITLE, id="title")
            with Center(id="qr-row"):
                yield Static(
                    qrcodes.render(self.export.container, ecc=QR_ECC_STATIC).text, id="wallet-qr"
                )
            yield Static(addresstext.PASSWORD_NOT_HERE, id="wallet-qr-password-not-here")
            yield Static(
                addresstext.EXPORT_QR_NETWORK.format(
                    network=self.app.network.value  # type: ignore[attr-defined]
                ),
                id="wallet-qr-network",
            )
            yield Static(addresstext.EXPORT_QR_INSTRUCTION, id="wallet-qr-instruction")
            yield Static(addresstext.EXPORT_QR_KEYS, id="wallet-qr-keys")

    def action_show_password(self) -> None:
        self.app.push_screen(ExportPasswordShowScreen(self.export))


class ExportPasswordShowScreen(Screen):
    """The eight words, numbered, and nothing that could be photographed with them.

    No QR, no ciphertext, no fingerprint — the separation this whole path depends on is the one
    thing this screen exists to hold.
    """

    BINDINGS = [Binding("f10", "read_back", "Type them back")]

    DEFAULT_CSS = """
    ExportPasswordShowScreen #export-words { margin: 1 0; }
    ExportPasswordShowScreen .export-word { margin-left: 2; }
    ExportPasswordShowScreen #export-password-keys { margin-top: 1; }
    """

    def __init__(self, export: ExportedWallet, *, first_showing: bool = True) -> None:
        super().__init__()
        self.export = export
        #: The first showing leads to the read-back. Every re-show leads back where it came from
        #: — a re-show is a user checking their paper, not a step on the way to anything.
        self._first_showing = first_showing

    def compose(self) -> ComposeResult:
        with Vertical(id="frame"):
            yield Static(addresstext.PASSWORD_TITLE, id="title")
            yield Static(addresstext.PASSWORD_WRITE_IT_DOWN, id="export-write-it-down")
            with Vertical(id="export-words"):
                for number, word in self.export.password.numbered():
                    # One per line, numbered, fixed-width — and the hyphenated words render whole,
                    # because a word broken across a line is the real transcription hazard here.
                    yield Static(
                        f"{number:>2}  {word}",
                        classes="export-word",
                        id=f"export-word-{number}",
                    )
            yield Static(
                addresstext.PASSWORD_KEYS
                if self._first_showing
                else addresstext.PASSWORD_AGAIN_KEYS,
                id="export-password-keys",
            )

    def action_read_back(self) -> None:
        """Only from the first showing, by construction rather than by inspecting the stack."""
        if not self._first_showing:
            return
        self.app.switch_screen(ReadBackScreen(self.export))


class ReadBackScreen(WordEntryScreen):
    """All eight words, typed back, before the export completes."""

    BINDINGS = [Binding(addresstext.SHOW_AGAIN_KEY, "show_again", "Show the words again")]

    def __init__(self, export: ExportedWallet) -> None:
        super().__init__(addresstext.READ_BACK_TITLE, EFF, EXPORT_PASSWORD_WORDS)
        self.export = export

    def intro(self) -> tuple[str, ...]:
        return (addresstext.READ_BACK_WHY,)

    def action_show_again(self) -> None:
        self.app.push_screen(ExportPasswordShowScreen(self.export, first_showing=False))

    def accept(self, words: tuple[str, ...]) -> None:
        """All eight, and not a subset. A failure keeps the same password by construction —
        nothing here regenerates one, and `self.export` is the same object either way."""
        if not self.export.password.read_back_matches(words):
            self.grid.say(addresstext.READ_BACK_WRONG)
            return
        self.app.switch_screen(ExportDoneScreen(self.export))


class ExportDoneScreen(Screen):
    """The closing message, and the one branch in it that matters."""

    BINDINGS = [Binding(addresstext.SHOW_AGAIN_KEY, "show_again", "Show the words again")]

    DEFAULT_CSS = """
    ExportDoneScreen #export-truth { margin-bottom: 1; text-style: bold; }
    ExportDoneScreen #export-done-keys { margin-top: 1; }
    """

    def __init__(self, export: ExportedWallet) -> None:
        super().__init__()
        self.export = export

    def compose(self) -> ComposeResult:
        with Vertical(id="frame"):
            yield Static(addresstext.DONE_TITLE, id="title")
            yield Static(
                addresstext.closing_message(self.app.wallet),  # type: ignore[attr-defined]
                id="export-truth",
            )
            yield Static(addresstext.KEEP_THEM_APART, id="export-keep-apart")
            yield Static(addresstext.DONE_KEYS, id="export-done-keys")

    def action_show_again(self) -> None:
        self.app.push_screen(ExportPasswordShowScreen(self.export, first_showing=False))
