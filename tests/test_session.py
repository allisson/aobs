"""Whole sessions, walked end to end across the seams between the five specs.

Every other app module tests one segment of the session and injects the state its segment starts
from: `tests/test_review_screen.py` and `tests/test_emit_screen.py` assign `app.wallet` directly,
`tests/test_wallet_entry.py` hands a container to `open_export_password()` rather than scanning
one, and `tests/test_export_screens.py` starts from a wallet that was never entered. Each of those
is the right shape for what it asserts — and none of them proves the joins hold.

This module is the joins. It walks the session the parent spec describes, one keystroke at a time,
from the keymap picker to the signed transaction leaving the appliance:

* **The money path** — a seed typed in, a passphrase declined, a transaction scanned off real QR
  images, reviewed, confirmed, and signed **by the wallet the appliance itself built**. Nothing is
  assigned into the session: if seed entry and the review screen disagree about what a `Wallet` is,
  it fails here rather than nowhere.
* **Generate and export** — dice, read-back, and the encrypted wallet QR whose container is
  asserted to carry the entropy the generated words came from.
* **The round trip** — a container scanned back in, restored under its eight words, and the
  restored wallet used to prove one of its own addresses is its own.

The rules of the surrounding suite hold: real keys through `run_test()`, real QR images through the
`FrameSource` fake and the same `zxing-cpp` the appliance uses, and never a pixel or a private
attribute. What is asserted at the end of each walk is the state a user would be able to see, and
the bytes the appliance would emit.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from pathlib import Path

from textual.widgets import Static

from aobs.adapters.fake import (
    FixedEntropySource,
    ImageFileFrameSource,
    RecordingKeymap,
    RecordingPower,
)
from aobs.core import mnemonic as bip39
from aobs.core.constants import ENTROPY_OUTPUT_BYTES
from aobs.core.entropy import mix
from aobs.core.signing import sign
from aobs.core.urcodec import PsbtStream
from aobs.core.wallet import Network, ScriptType, Wallet
from aobs.core.wallet_qr import decode, export_wallet
from aobs.ports.frame_source import Frame
from aobs.ui import addresstext
from aobs.ui.app import SignerApp
from aobs.ui.reviewtext import grouped
from aobs.ui.screens.address_verify import AddressVerifyScreen
from aobs.ui.screens.confirm import ConfirmScreen
from aobs.ui.screens.dice import DiceScreen
from aobs.ui.screens.emit import EmitScreen
from aobs.ui.screens.export_password import ExportPasswordScreen
from aobs.ui.screens.fingerprint import COMPARE_IT, RECORD_IT, FingerprintScreen
from aobs.ui.screens.home import NETWORK_FIXED, PATHS, HomeScreen
from aobs.ui.screens.keymap import KeymapScreen
from aobs.ui.screens.passphrase import PassphraseScreen
from aobs.ui.screens.recovery_words import RecoveryWordsScreen
from aobs.ui.screens.review import ReviewScreen
from aobs.ui.screens.scan import ScanScreen
from aobs.ui.screens.seed_entry import SeedEntryScreen
from aobs.ui.screens.wallet_export import (
    ExportDoneScreen,
    ExportPasswordShowScreen,
    ReadBackScreen,
    WalletQrScreen,
)
from aobs.ui.screens.word_count import WordCountScreen

from conftest import CORPUS, VECTOR_MNEMONIC, fixed_bytes, render_qr, render_qrs

CONSOLE = (128, 48)


class _HeldUpToTheCamera:
    """A camera that sees whatever the walk is currently holding up to it.

    `ImageFileFrameSource` replays one fixed list on every opening, which is right for a session
    with one scan in it and wrong for a session with two: the second scan would re-decode the
    first scan's code. A queue of openings is wrong too, because the appliance opens the stream
    more times than a walk can sensibly count — once for the presence probe before the first
    secret, once per scan screen mounted, and again whenever a spent scan screen is resumed on the
    way back past it. So what the camera sees is a property of the moment, which is also what it
    is in the room.
    """

    def __init__(self, showing: Sequence[Path] = ()) -> None:
        self.showing: list[Path] = list(showing)
        self.closed = False

    def frames(self) -> Iterator[Frame]:
        return ImageFileFrameSource(self.showing).frames()

    def close(self) -> None:
        self.closed = True


def blank_frame(directory: Path) -> Path:
    """One frame that decodes to nothing — all the presence probe ever needs."""
    from PIL import Image

    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "blank.png"
    Image.new("L", (64, 64), 0).save(path)
    return path


def one_qr(payload: str | bytes, directory: Path) -> Path:
    """`render_qr` writes into a directory it does not create, so this one does."""
    directory.mkdir(parents=True, exist_ok=True)
    return render_qr(payload, directory)


def build(**overrides: object) -> SignerApp:
    ports = {
        "frames": ImageFileFrameSource([]),
        "entropy": FixedEntropySource(),
        "power": RecordingPower(),
        "keymap": RecordingKeymap(),
        # The walks pull the scan screen's frames themselves, one call per frame: pacing
        # twenty-seven frames at 5 fps would cost the suite seven seconds to assert something
        # that is not Textual's clock.
        "scan_frame_interval": None,
        # And the emit screen's animation, for the same reason.
        "emit_animated": False,
    }
    ports.update(overrides)
    return SignerApp(**ports)  # type: ignore[arg-type]


def texts(app: SignerApp) -> str:
    return "\n".join(str(widget.content) for widget in app.screen.query(Static))


# --- Walking the session ----------------------------------------------------------------------
#
# One helper per step the user takes, named after what the user is doing rather than after the
# screen it lands on, so a walk below reads as the session and not as a screen list.


async def accept_the_keymap(app: SignerApp, pilot) -> None:
    assert isinstance(app.screen, KeymapScreen), "the picker is the first screen"
    await pilot.press("f10")
    await pilot.pause()
    assert isinstance(app.screen, HomeScreen)


async def open_path(app: SignerApp, pilot, name: str) -> None:
    """Walk the home screen to a path by name and open it, from wherever the cursor was left."""
    assert isinstance(app.screen, HomeScreen), type(app.screen).__name__
    target = next(index for index, path in enumerate(PATHS) if path.name == name)
    for _ in range((target - PATHS.index(app.screen.selected_path)) % len(PATHS)):
        await pilot.press("down")
    await pilot.press("f10")
    await pilot.pause()


async def type_bip39_words(pilot, words: Sequence[str]) -> None:
    """Four characters and a space for anything the BIP39 rule settles there, the whole of
    anything shorter — the way `tests/test_wallet_entry.py` types, for the reason it gives."""
    keys: list[str] = []
    for word in words:
        keys += [*word[:4], "space"] if len(word) >= 4 else [*word, "space"]
    await pilot.press(*keys)
    await pilot.pause()


async def type_eff_words(pilot, words: Sequence[str]) -> None:
    """Every character of every word: the export grid resolves nothing short of a full one, and
    `tests/test_wallet_entry.py` asserts that it must not."""
    for word in words:
        await pilot.press(*[character for character in word], "space")
    await pilot.pause()


async def decline_the_passphrase(app: SignerApp, pilot) -> None:
    assert isinstance(app.screen, PassphraseScreen)
    await pilot.press("f10")
    await pilot.pause()


async def leave_the_fingerprint(app: SignerApp, pilot) -> None:
    assert isinstance(app.screen, FingerprintScreen)
    await pilot.press("f10")
    await pilot.pause()
    assert isinstance(app.screen, HomeScreen)


def drain(app: SignerApp, frames: int) -> None:
    """Feed the scan screen `frames` frames, the way the appliance's own interval would."""
    screen = app.screen
    assert isinstance(screen, ScanScreen)
    for _ in range(frames):
        screen.scan_once()


# --- The money path ---------------------------------------------------------------------------


async def test_a_typed_seed_signs_a_scanned_transaction_and_emits_it(tmp_path: Path) -> None:
    """The whole appliance, in one session: picker, seed, passphrase, scan, review, confirm, emit.

    The wallet that signs is the one the *appliance* built out of typed keystrokes. Every other
    test of the money path assigns `app.wallet` directly, which is what makes this walk worth its
    seconds: a disagreement between what seed entry constructs and what the review and signing
    screens expect has nowhere else to surface.
    """
    psbt_bytes = (CORPUS / "honest_mainnet.psbt").read_bytes()
    parts = list(PsbtStream(psbt_bytes).cycle())
    app = build(frames=ImageFileFrameSource(render_qrs(parts, tmp_path)))

    async with app.run_test(size=CONSOLE) as pilot:
        await accept_the_keymap(app, pilot)
        assert app.wallet is None

        # --- getting the wallet in ---
        await open_path(app, pilot, "Type a seed in")
        assert isinstance(app.screen, WordCountScreen), "the count is asked, never detected"
        await pilot.press("f10")  # twelve, the default and this vector's length
        await pilot.pause()
        assert isinstance(app.screen, SeedEntryScreen)
        await type_bip39_words(pilot, VECTOR_MNEMONIC.split())
        await pilot.press("f10")
        await pilot.pause()

        await decline_the_passphrase(app, pilot)
        assert isinstance(app.screen, FingerprintScreen)
        assert COMPARE_IT in texts(app), "a restored wallet has something to compare against"
        await leave_the_fingerprint(app, pilot)

        expected = Wallet.from_mnemonic(VECTOR_MNEMONIC, network=Network.MAINNET)
        assert app.wallet is not None
        assert app.wallet.fingerprint_hex == expected.fingerprint_hex
        assert NETWORK_FIXED in texts(app), "the network is settled once a wallet exists"

        # --- the transaction, off real QR images ---
        await open_path(app, pilot, "Sign a transaction")
        assert isinstance(app.screen, ScanScreen)
        drain(app, len(parts))
        await pilot.pause()

        assert isinstance(app.screen, ReviewScreen), texts(app)
        assert app.scanned == psbt_bytes, "the bytes that arrived are the bytes that were sent"

        # Two outputs fit the console, so signing is unlocked on first paint: the lock costs
        # nothing where it protects nothing. `tests/test_review_screen.py` owns the lock itself.
        await pilot.press("f10")
        await pilot.pause()
        assert isinstance(app.screen, ConfirmScreen)
        await pilot.press("y")
        await pilot.pause()

        # --- what leaves the appliance ---
        assert isinstance(app.screen, EmitScreen)
        assert app.screen.signed_psbt == sign(psbt_bytes, expected)

        # And the way back is the way in, screen by screen: the emit screen replaced the confirm,
        # so `esc` lands on the review with its lock still open (`tests/test_emit_screen.py` owns
        # that decision), then on the scan screen the transaction arrived through, then home.
        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(app.screen, ReviewScreen)
        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(app.screen, ScanScreen)
        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(app.screen, HomeScreen)
        assert app.wallet is not None, "signing costs the user neither the wallet nor the session"


# --- Generate, and export what was generated --------------------------------------------------


async def test_a_generated_wallet_exports_a_container_carrying_its_own_entropy() -> None:
    """Generation through to the encrypted wallet QR, and the container opened to check.

    The two halves of this are settled by different specs and share one fact: the entropy behind
    the words the user wrote down. Decoding the container with the password the appliance showed is
    the only assertion that checks they agree.
    """
    rolls = "3141592653"
    entropy = mix(FixedEntropySource().random_bytes(ENTROPY_OUTPUT_BYTES), dice_rolls=rolls)
    generated = bip39.from_entropy(entropy.value)
    assert len(generated.split()) == 24, "generation is 24 words and asks no count"

    app = build()
    async with app.run_test(size=CONSOLE) as pilot:
        await accept_the_keymap(app, pilot)

        await open_path(app, pilot, "Generate a new wallet")
        assert isinstance(app.screen, DiceScreen), "the dice are offered before generation"
        await pilot.press(*rolls)
        await pilot.press("f10")
        await pilot.pause()

        assert isinstance(app.screen, RecoveryWordsScreen)
        assert all(word in texts(app) for word in generated.split())
        await pilot.press("f10")  # type them back
        await pilot.pause()

        assert isinstance(app.screen, SeedEntryScreen)
        await type_bip39_words(pilot, generated.split())
        await pilot.press("f10")
        await pilot.pause()

        await decline_the_passphrase(app, pilot)
        assert RECORD_IT in texts(app), "a wallet made here has nothing to compare against"
        await leave_the_fingerprint(app, pilot)

        assert app.mnemonic == generated
        assert app.wallet is not None
        assert app.wallet.fingerprint_hex == (
            Wallet.from_mnemonic(generated, network=Network.MAINNET).fingerprint_hex
        )

        # --- the encrypted wallet QR ---
        await open_path(app, pilot, "Export the encrypted wallet QR")
        assert isinstance(app.screen, WalletQrScreen)
        await pilot.press("f10")  # show the password
        await pilot.pause()
        assert isinstance(app.screen, ExportPasswordShowScreen)
        exported = app.export
        assert exported is not None
        await pilot.press("f10")  # type them back
        await pilot.pause()

        assert isinstance(app.screen, ReadBackScreen)
        await type_eff_words(pilot, exported.password.words)
        await pilot.press("f10")
        await pilot.pause()
        assert isinstance(app.screen, ExportDoneScreen)

    opened = decode(exported.container, exported.password)
    assert bip39.from_entropy(opened.entropy) == generated
    assert opened.word_count == 24


# --- The round trip ---------------------------------------------------------------------------


async def test_a_scanned_container_restores_a_wallet_that_proves_its_own_address(
    tmp_path: Path,
) -> None:
    """A wallet backup scanned off a QR image, restored, and then used.

    This is the only walk in the suite that reaches the export-password grid the way a user does —
    every other test hands the container to `open_export_password()` — and the only one that
    proves the restored wallet is a working wallet rather than merely a fingerprint: it verifies
    one of its own receive addresses, scanned as a second QR in the same session.
    """
    exported = export_wallet(bip39.to_entropy(VECTOR_MNEMONIC), fixed_bytes())
    wallet = Wallet.from_mnemonic(VECTOR_MNEMONIC, network=Network.MAINNET)
    mine = wallet.address(ScriptType.P2WPKH, 0, 7)

    backup = one_qr(exported.container, tmp_path / "backup")
    address = one_qr(mine, tmp_path / "address")
    # A blank frame to begin with: the presence probe runs before any of this walk's keystrokes.
    camera = _HeldUpToTheCamera([blank_frame(tmp_path)])
    app = build(frames=camera)

    async with app.run_test(size=CONSOLE) as pilot:
        await accept_the_keymap(app, pilot)
        assert app.camera_available, "the probe saw a frame, so every path is offered"

        camera.showing = [backup]
        await open_path(app, pilot, "Restore from an encrypted wallet QR")
        assert isinstance(app.screen, ScanScreen)
        drain(app, 1)
        await pilot.pause()

        assert isinstance(app.screen, ExportPasswordScreen), texts(app)
        await type_eff_words(pilot, exported.password.words)
        await pilot.press("f10")
        await pilot.pause()

        await decline_the_passphrase(app, pilot)
        await leave_the_fingerprint(app, pilot)
        assert app.wallet is not None
        assert app.wallet.fingerprint_hex == wallet.fingerprint_hex

        # --- and the restored wallet is a wallet ---
        camera.showing = [address]
        await open_path(app, pilot, "Verify a receive address")
        assert isinstance(app.screen, ScanScreen)
        drain(app, 1)
        await pilot.pause()

        assert isinstance(app.screen, AddressVerifyScreen), texts(app)
        shown = texts(app)
        assert addresstext.PROVEN_LEAD in shown
        assert "m/84h/0h/0h/0/7" in shown
        assert grouped(mine) in shown, "shown in full, grouped in fours, never elided"
