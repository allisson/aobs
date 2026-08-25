"""The money path, driven the way the appliance is driven.

Every test presses real keys against a real `SignerApp` through `run_test()`. What is asserted is
the text a widget holds, which key does what, and the session state a refusal leaves behind — never
a pixel. Pixel-diffing a TUI produces tests that fail on a font change and pass on a wrong address.

The corpus is the instrument, not a set of hand-written amounts: `fixtures/psbt/` declares each
attack's verdict beside it, so the screen's rendering is checked against the same files the model
is (`tests/test_adversarial_corpus.py`).
"""

from __future__ import annotations

import json

import pytest
from textual.widgets import Button, Static

from aobs.adapters.fake import (
    FixedEntropySource,
    ImageFileFrameSource,
    RecordingKeymap,
    RecordingPower,
)
from aobs.core.review import OutputCategory, RefusalReason, review
from aobs.core.text import is_inert
from aobs.core.wallet import Network, Wallet
from aobs.ui import reviewtext
from aobs.ui.app import SignerApp
from aobs.ui.screens.confirm import ConfirmScreen
from aobs.ui.screens.emit import EmitScreen
from aobs.ui.screens.refusal import RefusalScreen
from aobs.ui.screens.review import ReviewScreen
from aobs.ui.screens.scan import ScanScreen

from conftest import CORPUS, VECTOR_MNEMONIC, render_qrs

CONSOLE = (128, 48)

#: Where *sign a transaction* sits on the home screen's inventory.
TRANSACTION = 3

SIGNABLE = [
    "honest_p2wpkh", "honest_p2tr", "honest_mainnet", "many_inputs", "many_outputs",
    "change_address_attack", "change_index_out_of_window", "fee_absurd",
    "input_past_the_ceiling", "ansi_escape_label",
]


def network_of(name: str) -> Network:
    return Network(json.loads((CORPUS / f"{name}.json").read_text())["network"])


def psbt_of(name: str) -> bytes:
    return (CORPUS / f"{name}.psbt").read_bytes()


def build(name: str, *, paths: list | None = None) -> SignerApp:
    app = SignerApp(
        frames=ImageFileFrameSource(paths or []),
        entropy=FixedEntropySource(),
        power=RecordingPower(),
        keymap=RecordingKeymap(),
        network=network_of(name),
        scan_frame_interval=None,
        emit_animated=False,
    )
    app.wallet = Wallet.from_mnemonic(VECTOR_MNEMONIC, network=network_of(name))
    return app


def label_of(heading: str) -> str:
    """The category label out of an output's heading line, whatever the amount beside it is."""
    return heading.split(maxsplit=1)[1].split("  ")[0]


def texts(screen) -> str:
    return "\n".join(str(widget.content) for widget in screen.query(Static))


def displayed(screen) -> str:
    """Only what is actually on screen. A widget hidden by `display: none` holds text nobody can
    read, and the lock line and the key line take turns being that widget."""
    return "\n".join(
        str(widget.content) for widget in screen.query(Static) if widget.display
    )


async def open_review(app: SignerApp, pilot, name: str) -> ReviewScreen | RefusalScreen:
    """Straight to the money path through the app's own entry point.

    The scan screen's hand-off is exercised end to end once, in
    `test_a_scanned_transaction_arrives_at_the_review_screen`; forty QR images per test to reach
    the same place would buy nothing and cost minutes.
    """
    await pilot.press("f10")  # accept the keymap
    app.open_review(psbt_of(name))
    await pilot.pause()
    return app.screen


# --- The output list ------------------------------------------------------------------------------


@pytest.mark.parametrize("name", SIGNABLE)
async def test_a_signable_transaction_reaches_the_review_screen(name: str) -> None:
    app = build(name)
    async with app.run_test(size=CONSOLE) as pilot:
        screen = await open_review(app, pilot, name)
        assert isinstance(screen, ReviewScreen)
        rendered = texts(screen)
        assert "Review transaction" in rendered
        assert app.network.value in rendered


async def test_the_fake_change_output_is_labelled_exactly_like_a_genuine_payment() -> None:
    """`change_address_attack`'s NOT PROVEN output against `honest_mainnet`'s real payment: the
    same label, byte for byte, and the difference is the inline warning."""
    attack = build("change_address_attack")
    async with attack.run_test(size=CONSOLE) as pilot:
        screen = await open_review(attack, pilot, "change_address_attack")
        fake = str(screen.query_one("#output-2").query_one(".output-heading", Static).content)
        note = str(screen.query_one("#output-2-note-0", Static).content)

    honest = build("honest_mainnet")
    async with honest.run_test(size=CONSOLE) as pilot:
        screen = await open_review(honest, pilot, "honest_mainnet")
        genuine = str(screen.query_one("#output-1").query_one(".output-heading", Static).content)

    assert label_of(fake) == label_of(genuine) == "PAYMENT"
    assert reviewtext.WARNING_MARK in note
    assert "your own change" in note


async def test_an_addresss_line_is_never_wrapped_and_never_elided() -> None:
    """Asserted on the widget's own region: a line that wrapped would be two rows high."""
    app = build("honest_p2tr")
    async with app.run_test(size=CONSOLE) as pilot:
        screen = await open_review(app, pilot, "honest_p2tr")
        addresses = list(screen.query(".output-address"))
        assert len(addresses) == 2
        for widget in addresses:
            text = str(widget.content)
            assert widget.region.height == 1, f"wrapped: {text}"
            assert "…" not in text and "..." not in text


async def test_proven_change_shows_the_path_above_a_dimmed_but_complete_address() -> None:
    app = build("honest_p2wpkh")
    async with app.run_test(size=CONSOLE) as pilot:
        screen = await open_review(app, pilot, "honest_p2wpkh")
        change = screen.query_one("#output-2")
        path = str(change.query_one(".output-path", Static).content)
        address_widget = change.query_one(".output-address", Static)

        assert path == "m/84h/1h/0h/1/0"
        assert "output-address-dim" in address_widget.classes
        reviewed = review(psbt_of("honest_p2wpkh"), app.wallet)
        expected = reviewed.outputs[1].address
        assert expected is not None
        assert str(address_widget.content).replace(" ", "") == expected


# --- The pinned footer ----------------------------------------------------------------------------


async def test_per_transaction_warnings_sit_above_the_totals_and_outside_the_scrolling_list() -> (
    None
):
    """Pinned means they cannot be scrolled off, which is a structural fact rather than a
    scroll-position one — so it is asserted structurally."""
    app = build("fee_absurd")
    async with app.run_test(size=CONSOLE) as pilot:
        screen = await open_review(app, pilot, "fee_absurd")
        warning = screen.query_one("#transaction-warning-0", Static)
        assert "unusually high" in str(warning.content)

        footer = screen.query_one("#footer")
        assert warning in footer.query(Static)
        assert not screen.query_one("#outputs").query("#transaction-warning-0")
        assert warning.region.y < screen.query_one("#headline-0").region.y


async def test_a_whole_balance_spend_says_so_above_the_totals() -> None:
    app = build("input_past_the_ceiling")
    async with app.run_test(size=CONSOLE) as pilot:
        screen = await open_review(app, pilot, "input_past_the_ceiling")
        assert "spends your entire balance" in str(
            screen.query_one("#transaction-warning-0", Static).content
        )


async def test_the_headline_and_the_fee_match_the_corpus_verdict() -> None:
    declared = json.loads((CORPUS / "honest_p2wpkh.json").read_text())["expected"]["headline"]
    app = build("honest_p2wpkh")
    async with app.run_test(size=CONSOLE) as pilot:
        screen = await open_review(app, pilot, "honest_p2wpkh")
        first = str(screen.query_one("#headline-0", Static).content)
        second = str(screen.query_one("#headline-1", Static).content)
        fee = str(screen.query_one("#fee", Static).content)

    assert reviewtext.btc(declared["payments_sats"]) in first
    assert reviewtext.btc(declared["fee_sats"]) in first
    assert reviewtext.btc(declared["total_leaving_sats"]) in first
    assert reviewtext.satoshis(declared["total_leaving_sats"]) in second
    assert f"{reviewtext.satoshis(declared['fee_sats'])} sats" in fee
    assert "sat/vB" in fee and "% of the amount sent" in fee


# --- The scroll-to-end lock -----------------------------------------------------------------------


async def test_signing_is_unlocked_at_first_paint_when_every_output_fits() -> None:
    """The lock costs nothing when it protects nothing."""
    app = build("honest_p2wpkh")
    async with app.run_test(size=CONSOLE) as pilot:
        screen = await open_review(app, pilot, "honest_p2wpkh")
        assert screen.unlocked
        assert reviewtext.UNLOCKED_KEYS in displayed(screen)
        assert "scroll to the end" not in displayed(screen)


async def test_the_lock_holds_until_the_last_row_renders() -> None:
    """Nine outputs on a 30-row console: `F10` does nothing, and `F10 sign` is not printed."""
    app = build("many_outputs")
    async with app.run_test(size=(100, 30)) as pilot:
        screen = await open_review(app, pilot, "many_outputs")
        assert not screen.unlocked, "nine outputs do not fit in this console"

        lock = str(screen.query_one("#lock", Static).content)
        assert lock.startswith("Outputs 1–")
        assert lock.endswith("of 9 — scroll to the end to unlock signing.")
        shown = displayed(screen)
        assert "F10" not in shown, "a key that does nothing is not printed"
        assert reviewtext.LOCKED_KEYS in shown

        await pilot.press("f10")
        await pilot.pause()
        assert isinstance(app.screen, ReviewScreen), "F10 did nothing at all"

        for _ in range(6):
            await pilot.press("pagedown")
        await pilot.pause()
        assert screen.unlocked
        assert reviewtext.UNLOCKED_KEYS in displayed(screen)
        assert "scroll to the end" not in displayed(screen)

        await pilot.press("f10")
        await pilot.pause()
        assert isinstance(app.screen, ConfirmScreen)


async def test_scrolling_by_line_reaches_the_end_too() -> None:
    app = build("many_outputs")
    async with app.run_test(size=(100, 30)) as pilot:
        screen = await open_review(app, pilot, "many_outputs")
        assert not screen.unlocked
        for _ in range(60):
            await pilot.press("down")
        await pilot.pause()
        assert screen.unlocked


@pytest.mark.parametrize("key", ["end", "home", "g", "G", "ctrl+end", "space"])
async def test_no_key_jumps_to_the_end(key: str) -> None:
    """The absence is the decision, so the absence is what is pinned.

    Scroll-to-end is the whole mechanism and a one-keystroke bypass of it is the mash-trainer the
    model refused wearing a different hat.
    """
    app = build("many_outputs")
    async with app.run_test(size=(100, 30)) as pilot:
        screen = await open_review(app, pilot, "many_outputs")
        assert not screen.unlocked
        for _ in range(4):
            await pilot.press(key)
        await pilot.pause()
        assert not screen.unlocked, f"{key} unlocked signing"

        await pilot.press("f10")
        await pilot.pause()
        assert isinstance(app.screen, ReviewScreen)


async def test_the_scrolling_list_supplies_no_bindings_of_its_own() -> None:
    """Textual's `ScrollableContainer` binds `end` and `home`. It never gets focus here, which is
    what keeps those keys from existing at all."""
    app = build("many_outputs")
    async with app.run_test(size=(100, 30)) as pilot:
        screen = await open_review(app, pilot, "many_outputs")
        view = screen.query_one("#outputs")
        assert not view.can_focus
        assert screen.focused is None

        bound = {
            binding.key
            for keymap in (screen._bindings, app._bindings)
            for binding in keymap.key_to_bindings.values()
            for binding in binding
        }
        assert not bound & {"end", "home", "g", "G", "ctrl+end"}


# --- The confirm ----------------------------------------------------------------------------------


async def test_the_confirm_screen_carries_no_address_from_the_psbt() -> None:
    """A substring sweep over every output address, not a layout check."""
    app = build("many_outputs")
    async with app.run_test(size=CONSOLE) as pilot:
        screen = await open_review(app, pilot, "many_outputs")
        screen.unlocked = True
        await pilot.press("f10")
        await pilot.pause()
        assert isinstance(app.screen, ConfirmScreen)

        rendered = texts(app.screen)
        reviewed = review(psbt_of("many_outputs"), app.wallet)
        for out in reviewed.outputs:
            assert out.address is not None
            assert out.address not in rendered
            assert reviewtext.grouped(out.address) not in rendered
            assert out.address[:12] not in rendered


async def test_the_confirm_screen_restates_the_number_and_the_not_proven_tally() -> None:
    app = build("change_address_attack")
    async with app.run_test(size=CONSOLE) as pilot:
        await open_review(app, pilot, "change_address_attack")
        await pilot.press("f10")
        await pilot.pause()
        rendered = texts(app.screen)
        assert reviewtext.btc(1_200_000) in rendered
        assert reviewtext.satoshis(1_200_000) in rendered
        assert "could not prove" in rendered
        assert "y  sign" in rendered


async def test_esc_returns_to_the_review_with_the_scroll_position_and_the_lock_intact() -> None:
    """Backing out of a confirmation is not a reason to re-scroll nine outputs, and making it one
    would teach the user to avoid `esc`."""
    app = build("many_outputs")
    async with app.run_test(size=(100, 30)) as pilot:
        screen = await open_review(app, pilot, "many_outputs")
        for _ in range(6):
            await pilot.press("pagedown")
        await pilot.pause()
        assert screen.unlocked
        offset = screen.query_one("#outputs").scroll_offset.y

        await pilot.press("f10")
        await pilot.pause()
        assert isinstance(app.screen, ConfirmScreen)

        await pilot.press("escape")
        await pilot.pause()
        assert app.screen is screen
        assert screen.query_one("#outputs").scroll_offset.y == offset
        assert screen.unlocked
        assert reviewtext.UNLOCKED_KEYS in displayed(screen)


async def test_mashing_the_open_key_lands_on_the_confirm_and_stops() -> None:
    """`F10` and `y` are deliberately different keys, so the second press does nothing."""
    app = build("honest_p2wpkh")
    async with app.run_test(size=CONSOLE) as pilot:
        await open_review(app, pilot, "honest_p2wpkh")
        await pilot.press("f10")
        await pilot.press("f10")
        await pilot.pause()
        assert isinstance(app.screen, ConfirmScreen)


async def test_y_on_the_confirm_signs_the_bytes_the_scan_produced() -> None:
    from aobs.core.signing import sign

    app = build("honest_p2wpkh")
    async with app.run_test(size=CONSOLE) as pilot:
        await open_review(app, pilot, "honest_p2wpkh")
        await pilot.press("f10")
        await pilot.pause()
        await pilot.press("y")
        await pilot.pause()

        assert isinstance(app.screen, EmitScreen)
        assert app.screen.signed_psbt == sign(psbt_of("honest_p2wpkh"), app.wallet)


async def test_y_does_nothing_on_the_review_screen() -> None:
    """The confirm key is safe on the confirm screen precisely because that screen is unreachable
    by momentum. It must not also work one screen earlier."""
    app = build("honest_p2wpkh")
    async with app.run_test(size=CONSOLE) as pilot:
        screen = await open_review(app, pilot, "honest_p2wpkh")
        await pilot.press("y")
        await pilot.pause()
        assert app.screen is screen


# --- Refusals -------------------------------------------------------------------------------------


REFUSED = {
    "malformed": RefusalReason.MALFORMED,
    "network_mismatch": RefusalReason.NETWORK_MISMATCH,
    "network_mismatch_foreign_fingerprint": RefusalReason.NETWORK_MISMATCH,
    "taproot_missing_witness_utxo": RefusalReason.MISSING_UTXO,
    "sighash_not_all": RefusalReason.SIGHASH_NOT_ALL,
    "foreign_input": RefusalReason.UNSIGNABLE_INPUT,
}


@pytest.mark.parametrize("name", sorted(REFUSED))
async def test_a_refused_psbt_shows_three_sentences_and_no_button(name: str) -> None:
    app = build(name)
    async with app.run_test(size=CONSOLE) as pilot:
        screen = await open_review(app, pilot, name)
        assert isinstance(screen, RefusalScreen)
        assert screen.refusal.reason is REFUSED[name]

        expected = reviewtext.refusal_failure(screen.refusal)
        rendered = texts(screen)
        assert expected.happened in rendered
        assert f"condition: {expected.condition}" in rendered
        assert expected.next_steps[0] in rendered
        # No override and no confirmation button, which the widget cannot hold at all.
        assert not screen.query(Button)
        assert screen.focused is None


@pytest.mark.parametrize("name", sorted(REFUSED))
async def test_only_a_truncated_scan_is_told_to_scan_again(name: str) -> None:
    app = build(name)
    async with app.run_test(size=CONSOLE) as pilot:
        screen = await open_review(app, pilot, name)
        rendered = texts(screen)
        retries = reviewtext.RETRY_STEP in rendered
        assert retries == (REFUSED[name] is RefusalReason.MALFORMED)
        if not retries:
            assert reviewtext.NO_RETRY_STEP in rendered


async def test_a_refused_psbt_lands_back_on_the_scan_screen_with_the_wallet_loaded(
    tmp_path,
) -> None:
    """Dropping the wallet buys nothing — it is in RAM regardless, and a refusal means the attack
    failed — and costs 24 words and a passphrase."""
    name = "network_mismatch"
    from aobs.core.urcodec import PsbtStream

    parts = PsbtStream(psbt_of(name)).cycle()
    paths = render_qrs(list(parts), tmp_path)
    app = build(name, paths=paths)
    wallet = app.wallet
    async with app.run_test(size=CONSOLE) as pilot:
        await pilot.press("f10")
        for _ in range(TRANSACTION):
            await pilot.press("down")
        await pilot.press("f10")
        await pilot.pause()
        scan = app.screen
        assert isinstance(scan, ScanScreen)
        for _ in range(len(parts)):
            scan.scan_once()
        await pilot.pause()
        assert isinstance(app.screen, RefusalScreen)

        await pilot.press("escape")
        await pilot.pause()
        assert app.screen is scan
        assert app.wallet is wallet, "the wallet survives a refusal"


async def test_a_scanned_transaction_arrives_at_the_review_screen(tmp_path) -> None:
    """The hand-off from the inbound spec, end to end and once: the screen reviews the bytes the
    scan produced and nothing in between reinterprets them."""
    name = "honest_p2wpkh"
    from aobs.core.urcodec import PsbtStream

    parts = PsbtStream(psbt_of(name)).cycle()
    app = build(name, paths=render_qrs(list(parts), tmp_path))
    async with app.run_test(size=CONSOLE) as pilot:
        await pilot.press("f10")
        for _ in range(TRANSACTION):
            await pilot.press("down")
        await pilot.press("f10")
        await pilot.pause()
        scan = app.screen
        assert isinstance(scan, ScanScreen)
        for _ in range(len(parts)):
            scan.scan_once()
        await pilot.pause()

        assert isinstance(app.screen, ReviewScreen)
        assert app.screen.psbt_bytes == psbt_of(name) == app.scanned


# --- Attacker-controlled text ---------------------------------------------------------------------


async def test_escapes_from_the_psbt_reach_no_widget() -> None:
    """`docs/test-harness.md` names this a tested rule rather than an assumed Rich behaviour.

    The fixture carries `\\x1b[2J` and a BEL in a proprietary output field, and the assertion is
    on what reached the widgets — not on what the core chose to expose.
    """
    app = build("ansi_escape_label")
    async with app.run_test(size=CONSOLE) as pilot:
        screen = await open_review(app, pilot, "ansi_escape_label")
        for widget in screen.query(Static):
            assert is_inert(str(widget.content)), widget.id
        assert "PAY THIS INSTEAD" not in texts(screen)


# --- What the screen does not decide --------------------------------------------------------------


@pytest.mark.parametrize("name", SIGNABLE)
async def test_the_screen_shows_the_categories_the_model_decided(name: str) -> None:
    """The screen renders `Review` and derives nothing: two categories on screen for the model's
    three, and the mapping is the only thing the screen contributes."""
    app = build(name)
    reviewed = review(psbt_of(name), app.wallet)
    async with app.run_test(size=CONSOLE) as pilot:
        screen = await open_review(app, pilot, name)
        for out in reviewed.outputs:
            heading = str(
                screen.query_one(f"#output-{out.index + 1}")
                .query_one(".output-heading", Static)
                .content
            )
            expected = (
                "CHANGE, PROVEN"
                if out.category is OutputCategory.CHANGE_PROVEN
                else "PAYMENT"
            )
            assert label_of(heading) == expected
            assert reviewtext.satoshis(out.amount_sats) in heading
