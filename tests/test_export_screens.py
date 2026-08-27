"""The outbound exports: the exact payload behind each QR, and the two screens kept apart.

Two of the assertions here are the point of the whole module, and both are written as *the wrong
thing is absent* rather than only *the right thing is present*, because that is the direction the
harm runs in:

* **The password and the container never appear on the same screen** — swept in both directions.
* **The closing message branches on whether a passphrase is set.** Printing the passphrase-set
  message to a user with no passphrase is a lie that gets people robbed.

Never a pixel. `tests/test_wallet_qr.py` and `tests/test_wallet_interop.py` already prove the
container and the descriptor's CBOR.
"""

from __future__ import annotations

import pytest
from textual.widgets import Static

from aobs.adapters.fake import (
    FixedEntropySource,
    ImageFileFrameSource,
    RecordingKeymap,
    RecordingPower,
)
from aobs.core.constants import (
    EXPORT_PASSWORD_WORDS,
    QR_ECC_STATIC,
    WALLET_QR_MAGIC,
    WALLET_QR_TOTAL_BYTES,
)
from aobs.core.descriptor import output_descriptor_ur
from aobs.core.wallet import Network, ScriptType, Wallet
from aobs.core.wallet_qr import decode
from aobs.ui import addresstext, qrcodes
from aobs.ui.app import SignerApp
from aobs.ui.screens.descriptor import DescriptorScreen
from aobs.ui.screens.wallet_export import (
    ExportDoneScreen,
    ExportPasswordShowScreen,
    ReadBackScreen,
    WalletQrScreen,
)

from conftest import VECTOR_MNEMONIC

CONSOLE = (128, 48)


def build(*, passphrase: str = "", network: Network = Network.MAINNET) -> SignerApp:
    app = SignerApp(
        frames=ImageFileFrameSource([]),
        entropy=FixedEntropySource(),
        power=RecordingPower(),
        keymap=RecordingKeymap(),
        network=network,
        scan_frame_interval=None,
    )
    app.wallet = Wallet.from_mnemonic(
        VECTOR_MNEMONIC, network=network, passphrase=passphrase
    )
    app.mnemonic = VECTOR_MNEMONIC
    return app


def texts(screen) -> list[str]:
    return [str(node.content) for node in screen.query(Static)]


def blob(screen) -> str:
    return "\n".join(texts(screen))


# --- The descriptor QR --------------------------------------------------------------------------


async def test_the_descriptor_qr_payload_is_byte_identical_to_the_cores_own() -> None:
    app = build()
    async with app.run_test(size=CONSOLE) as pilot:
        app.open_descriptor()
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, DescriptorScreen)
        assert screen.payload == output_descriptor_ur(app.wallet, ScriptType.P2WPKH)
        assert screen.payload.startswith("UR:CRYPTO-OUTPUT/")


async def test_the_descriptor_qr_is_static_and_at_the_static_ecc() -> None:
    """One code, read once, at an unknown angle: `QR_ECC_STATIC` (H), and no animation at all."""
    app = build()
    async with app.run_test(size=CONSOLE) as pilot:
        app.open_descriptor()
        await pilot.pause()
        screen = app.screen
        assert QR_ECC_STATIC == "H"
        expected = qrcodes.render(screen.payload, ecc=QR_ECC_STATIC)
        assert str(screen.query_one("#descriptor-qr", Static).content) == expected.text
        # At ECC L the same payload needs a different code; asserting inequality is what makes
        # this a test of the parameter rather than of the renderer.
        assert expected.text != qrcodes.render(screen.payload).text
        assert not hasattr(screen, "advance"), "nothing here animates"


async def test_the_descriptor_screen_reaches_both_script_types() -> None:
    """BIP84 and BIP86 are separate URs on purpose — Green rejects a combined one whole — so only
    one can be on screen and the user needs a way to the other."""
    app = build()
    async with app.run_test(size=CONSOLE) as pilot:
        app.open_descriptor()
        await pilot.pause()
        assert app.screen.script_type is ScriptType.P2WPKH
        await pilot.press("f9")
        await pilot.pause()
        assert app.screen.payload == output_descriptor_ur(app.wallet, ScriptType.P2TR)
        assert "BIP86" in blob(app.screen)


# --- The encrypted wallet QR --------------------------------------------------------------------


async def open_export(app: SignerApp, pilot) -> WalletQrScreen:
    app.open_wallet_export()
    await pilot.pause()
    assert isinstance(app.screen, WalletQrScreen)
    return app.screen


async def test_the_wallet_qr_carries_the_container_bytes_unchanged() -> None:
    """Binary byte mode, no base64: a container that has been through a text codec on the way out
    is one the scan screen's magic-and-version framing would not recognise coming back."""
    app = build()
    async with app.run_test(size=CONSOLE) as pilot:
        screen = await open_export(app, pilot)
        assert screen.container.startswith(WALLET_QR_MAGIC)
        assert len(screen.container) == WALLET_QR_TOTAL_BYTES
        expected = qrcodes.render(screen.container, ecc=QR_ECC_STATIC)
        assert str(screen.query_one("#wallet-qr", Static).content) == expected.text


async def test_the_qr_screen_states_that_the_password_is_not_on_it() -> None:
    app = build()
    async with app.run_test(size=CONSOLE) as pilot:
        screen = await open_export(app, pilot)
        assert addresstext.PASSWORD_NOT_HERE in texts(screen)
        assert "not on this screen" in blob(screen)


@pytest.mark.parametrize("network", list(Network))
async def test_the_qr_screen_names_the_network_this_backup_is_for(network: Network) -> None:
    """What the QR carries and what the user writes on the paper have to agree.

    On mainnet this is `docs/network-selection.md`'s *stated rather than asked*: the default stays
    free and stops being silent at the one moment it is committed to paper.
    """
    app = build(network=network)
    async with app.run_test(size=CONSOLE) as pilot:
        screen = await open_export(app, pilot)
        assert addresstext.EXPORT_QR_NETWORK.format(network=network.value) in texts(screen)
        assert network.value in blob(screen)
        assert decode(screen.container, app.export.password).network is network


async def test_the_password_and_the_container_never_share_a_screen() -> None:
    """Swept in both directions: no word of the password on the QR screen, and no trace of the
    container on the password screen. Together they are one photograph, and that is the attack."""
    app = build()
    async with app.run_test(size=CONSOLE) as pilot:
        qr_screen = await open_export(app, pilot)
        export = qr_screen.export
        qr_text = blob(qr_screen)
        for word in export.password.words:
            assert word not in qr_text.split(), f"{word!r} is on the QR screen"
        assert export.password.text not in qr_text

        await pilot.press("f10")
        await pilot.pause()
        assert isinstance(app.screen, ExportPasswordShowScreen)
        password_text = blob(app.screen)
        assert export.password.text.split()[0] in password_text, "the words are here"
        assert not app.screen.query("#wallet-qr"), "no code on the password screen"
        for chunk in (export.container.hex(), qr_text.split("\n")[2]):
            assert chunk not in password_text


async def test_the_password_is_eight_numbered_words_one_per_line() -> None:
    app = build()
    async with app.run_test(size=CONSOLE) as pilot:
        export = (await open_export(app, pilot)).export
        await pilot.press("f10")
        await pilot.pause()
        lines = [str(node.content) for node in app.screen.query(".export-word")]
        assert len(lines) == EXPORT_PASSWORD_WORDS == 8
        for (number, word), line in zip(export.password.numbered(), lines, strict=True):
            assert line.split() == [str(number), word]
            assert "\n" not in line, "a hyphenated word is never broken across lines"


# --- The read-back --------------------------------------------------------------------------------


async def reach_read_back(app: SignerApp, pilot) -> ReadBackScreen:
    export = (await open_export(app, pilot)).export
    await pilot.press("f10")  # show the password
    await pilot.pause()
    await pilot.press("f10")  # type them back
    await pilot.pause()
    assert isinstance(app.screen, ReadBackScreen)
    assert app.screen.export is export
    return app.screen


async def type_words(pilot, words) -> None:
    for word in words:
        await pilot.press(*[character for character in word], "space")
    await pilot.pause()


async def test_all_eight_words_are_required_before_the_export_completes() -> None:
    """Not a subset: sampling three of eight misses the single mistranscribed word 62% of the
    time."""
    app = build()
    async with app.run_test(size=CONSOLE) as pilot:
        screen = await reach_read_back(app, pilot)
        assert screen.grid.slots == 8
        await type_words(pilot, screen.export.password.words[:7])
        await pilot.press("f10")
        await pilot.pause()
        assert isinstance(app.screen, ReadBackScreen), "seven words is not the password"
        assert "1 slot still to fill." == app.screen.grid.message


async def test_a_correct_read_back_completes_the_export() -> None:
    app = build()
    async with app.run_test(size=CONSOLE) as pilot:
        screen = await reach_read_back(app, pilot)
        await type_words(pilot, screen.export.password.words)
        await pilot.press("f10")
        await pilot.pause()
        assert isinstance(app.screen, ExportDoneScreen)


async def test_a_failed_read_back_retries_the_same_password() -> None:
    """A fresh password would silently invalidate whatever the user has already written down —
    asserted by comparing the words offered on the retry to the words first shown."""
    app = build()
    async with app.run_test(size=CONSOLE) as pilot:
        screen = await reach_read_back(app, pilot)
        first = screen.export.password.words
        wrong = ("abacus",) + first[1:]
        assert wrong != first
        await type_words(pilot, wrong)
        await pilot.press("f10")
        await pilot.pause()
        assert isinstance(app.screen, ReadBackScreen)
        assert app.screen.export.password.words == first
        assert "not the password" in app.screen.grid.message

        await pilot.press(addresstext.SHOW_AGAIN_KEY)
        await pilot.pause()
        assert isinstance(app.screen, ExportPasswordShowScreen)
        assert app.screen.export.password.words == first


async def test_the_password_is_re_showable_after_the_export_completes() -> None:
    """Show-once is a security reflex and it is wrong here: the password is in RAM either way, so
    refusing to redisplay protects nothing and costs a user a written-down guess."""
    app = build()
    async with app.run_test(size=CONSOLE) as pilot:
        screen = await reach_read_back(app, pilot)
        words = screen.export.password.words
        await type_words(pilot, words)
        await pilot.press("f10")
        await pilot.pause()
        assert isinstance(app.screen, ExportDoneScreen)
        await pilot.press(addresstext.SHOW_AGAIN_KEY)
        await pilot.pause()
        assert isinstance(app.screen, ExportPasswordShowScreen)
        shown = [str(node.content).split()[1] for node in app.screen.query(".export-word")]
        assert tuple(shown) == words


async def test_re_entering_the_export_path_shows_the_same_qr_and_the_same_password() -> None:
    """One export per session. A second one would hand the user a second password while the paper
    on their desk carries the first — the same silent invalidation a fresh password on a failed
    read-back would cause, arrived at by a different route."""
    app = build()
    async with app.run_test(size=CONSOLE) as pilot:
        first = (await open_export(app, pilot)).export
        await pilot.press("escape")
        await pilot.pause()
        second = (await open_export(app, pilot)).export
        assert second is first
        assert second.container == first.container
        assert second.password.words == first.password.words


# --- The closing message ----------------------------------------------------------------------------


async def closing_text(passphrase: str) -> str:
    app = build(passphrase=passphrase)
    async with app.run_test(size=CONSOLE) as pilot:
        screen = await reach_read_back(app, pilot)
        await type_words(pilot, screen.export.password.words)
        await pilot.press("f10")
        await pilot.pause()
        assert isinstance(app.screen, ExportDoneScreen)
        return blob(app.screen)


async def test_the_closing_message_branches_on_whether_a_passphrase_is_set() -> None:
    """**The test that stops the lie.** Two wallets, two distinct texts, and each asserted to be
    free of the other's claim."""
    with_passphrase = await closing_text("a second factor")
    without = await closing_text("")

    assert addresstext.WITH_PASSPHRASE in with_passphrase
    assert addresstext.WITHOUT_PASSPHRASE not in with_passphrase
    assert addresstext.WITHOUT_PASSPHRASE in without
    assert addresstext.WITH_PASSPHRASE not in without
    assert addresstext.WITH_PASSPHRASE != addresstext.WITHOUT_PASSPHRASE


async def test_the_no_passphrase_message_never_claims_the_qr_is_only_the_bip39_words() -> None:
    """The reassurance that is true with a passphrase and false without it. Printing it to a user
    in the second situation is the single highest-consequence string in this ticket."""
    without = (await closing_text("")).lower()
    assert "are your wallet" in without
    assert "anyone who holds both can spend" in without
    for false_reassurance in ("not your wallet", "your passphrase is in neither"):
        assert false_reassurance not in without


@pytest.mark.parametrize("passphrase", ["", "a second factor"])
async def test_both_paths_say_to_keep_the_paper_apart_from_the_qr(passphrase: str) -> None:
    text = await closing_text(passphrase)
    assert addresstext.KEEP_THEM_APART in text
    assert "paper" in text and "apart" in text


# --- No user-chosen password -----------------------------------------------------------------------


def test_nothing_on_the_export_path_offers_a_password_to_encrypt_under() -> None:
    """The enforcement is the absence of the feature — the only kind that cannot be talked around
    later by someone adding *advanced options*. `tests/test_wallet_qr.py` asserts the same of the
    core interface; this asserts it of the screens that drive it."""
    import inspect

    source = inspect.getsource(
        __import__("aobs.ui.screens.wallet_export", fromlist=["wallet_export"])
    )
    assert "password=" not in source
    assert "ExportPassword(" not in source, "the screens never construct one of their own"
