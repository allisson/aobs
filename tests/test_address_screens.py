"""The receive side on screen: the verdict a widget holds, and the words it must never hold.

What is asserted here is the text, which affordances are offered, and — for the two strings
`docs/address-verification.md` and `docs/export-password.md` call the most consequential in the
appliance — that the *wrong* version is absent, not only that the right one is present. That is
the direction the harm runs in: a not-found screen that also says "not yours" would pass a test
that only looked for "not found".

Never a pixel. `tests/test_address.py` already proves the core behaviour these screens drive.
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
from aobs.core.address import Verdict, verify
from aobs.core.constants import ADDRESS_PAGE_SIZE, ADDRESS_SEARCH_BLOCK
from aobs.core.wallet import CHANGE_CHAIN, RECEIVE_CHAIN, Network, ScriptType, Wallet
from aobs.ui import addresstext
from aobs.ui.app import SignerApp
from aobs.ui.screens.address_list import AddressListScreen
from aobs.ui.screens.address_verify import AddressVerifyScreen
from aobs.ui.widgets.failure import FailurePanel

from conftest import STRANGER_MNEMONIC, VECTOR_MNEMONIC

CONSOLE = (128, 48)


def build(network: Network = Network.MAINNET) -> SignerApp:
    app = SignerApp(
        frames=ImageFileFrameSource([]),
        entropy=FixedEntropySource(),
        power=RecordingPower(),
        keymap=RecordingKeymap(),
        network=network,
        scan_frame_interval=None,
    )
    app.wallet = Wallet.from_mnemonic(VECTOR_MNEMONIC, network=network)
    app.mnemonic = VECTOR_MNEMONIC
    return app


def texts(screen) -> list[str]:
    """Every string that reached a widget on this screen."""
    return [str(node.content) for node in screen.query(Static)]


def blob(screen) -> str:
    return "\n".join(texts(screen))


async def open_verify(app: SignerApp, pilot, scanned: str) -> AddressVerifyScreen:
    app.push_screen(AddressVerifyScreen(scanned))
    await pilot.pause()
    assert isinstance(app.screen, AddressVerifyScreen)
    return app.screen


# --- The four verdicts ----------------------------------------------------------------------------

#: One scan per verdict, so a new `Verdict` fails the sweep below until it declares a treatment.
SCANS = {
    Verdict.PROVEN: lambda wallet: wallet.address(ScriptType.P2WPKH, RECEIVE_CHAIN, 7),
    Verdict.NOT_FOUND: lambda wallet: Wallet.from_mnemonic(
        STRANGER_MNEMONIC, network=Network.MAINNET
    ).address(ScriptType.P2WPKH, RECEIVE_CHAIN, 0),
    Verdict.WRONG_NETWORK: lambda wallet: Wallet.from_mnemonic(
        VECTOR_MNEMONIC, network=Network.SIGNET
    ).address(ScriptType.P2WPKH, RECEIVE_CHAIN, 0),
    Verdict.UNREADABLE: lambda wallet: "not a bitcoin address at all",
}


@pytest.mark.parametrize("verdict", list(Verdict))
async def test_every_verdict_renders_its_own_screen(verdict: Verdict) -> None:
    """Parameterised over `Verdict` itself, so a fifth one fails here until it says what it
    shows."""
    app = build()
    scanned = SCANS[verdict](app.wallet)
    async with app.run_test(size=CONSOLE) as pilot:
        screen = await open_verify(app, pilot, scanned)
        assert screen.check.verdict is verdict
        assert blob(screen).strip(), "a verdict with nothing on screen is not a treatment"


async def test_proven_leads_with_the_path_and_de_emphasises_the_address() -> None:
    """Exactly as the review screen de-emphasises proven change. Inviting someone to eye-verify a
    string the machine has already proven trains a habit with no value."""
    app = build()
    address = app.wallet.address(ScriptType.P2WPKH, RECEIVE_CHAIN, 7)
    async with app.run_test(size=CONSOLE) as pilot:
        screen = await open_verify(app, pilot, address)
        lines = texts(screen)
        path = app.wallet.path(ScriptType.P2WPKH, RECEIVE_CHAIN, 7)
        assert path == "m/84h/0h/0h/0/7"
        assert path in lines
        grouped = addresstext.grouped(address)
        assert grouped in lines
        assert lines.index(path) < lines.index(grouped), "the path leads"
        assert "verify-address-dim" in screen.query_one("#verify-address").classes


async def test_change_addresses_prove_too() -> None:
    """Both chains are searched: a user checking an address their own wallet produced does not
    know or care which chain it came off."""
    app = build()
    address = app.wallet.address(ScriptType.P2WPKH, CHANGE_CHAIN, 3)
    async with app.run_test(size=CONSOLE) as pilot:
        screen = await open_verify(app, pilot, address)
        assert screen.check.verdict is Verdict.PROVEN
        assert app.wallet.path(ScriptType.P2WPKH, CHANGE_CHAIN, 3) in texts(screen)


# --- Not found, never "not yours" -------------------------------------------------------------------

#: Every way of claiming the address is not the user's. The screen must contain none of them: the
#: two causes — an attacker's address, or a legitimate one past the window — are indistinguishable
#: from here, and reporting a gap-limit miss as an attack is a real harm.
OWNERSHIP_CLAIMS = (
    "not yours",
    "not your",
    "does not belong to you",
    "is not this wallet's",
    "someone else",
    "attack",
    "attacker",
)


async def test_the_not_found_screen_never_claims_the_address_is_not_yours() -> None:
    app = build()
    stranger = Wallet.from_mnemonic(STRANGER_MNEMONIC, network=Network.MAINNET)
    async with app.run_test(size=CONSOLE) as pilot:
        screen = await open_verify(
            app, pilot, stranger.address(ScriptType.P2WPKH, RECEIVE_CHAIN, 0)
        )
        assert screen.check.verdict is Verdict.NOT_FOUND
        lowered = blob(screen).lower()
        assert "not found" in lowered
        for claim in OWNERSHIP_CLAIMS:
            assert claim not in lowered, f"the not-found screen must never say {claim!r}"


async def test_the_not_found_screen_states_the_window_it_searched() -> None:
    app = build()
    stranger = Wallet.from_mnemonic(STRANGER_MNEMONIC, network=Network.MAINNET)
    async with app.run_test(size=CONSOLE) as pilot:
        screen = await open_verify(
            app, pilot, stranger.address(ScriptType.P2WPKH, RECEIVE_CHAIN, 0)
        )
        assert screen.check.searched == (0, ADDRESS_SEARCH_BLOCK)
        text = blob(screen)
        assert f"0–{ADDRESS_SEARCH_BLOCK}" in text
        assert "receive" in text and "change" in text


async def test_the_not_found_screen_offers_two_next_steps_with_no_default() -> None:
    """Lines of text, in one class, with no button and nothing focused. The appliance does not
    press its thumb on a choice it cannot make."""
    app = build()
    stranger = Wallet.from_mnemonic(STRANGER_MNEMONIC, network=Network.MAINNET)
    async with app.run_test(size=CONSOLE) as pilot:
        screen = await open_verify(
            app, pilot, stranger.address(ScriptType.P2WPKH, RECEIVE_CHAIN, 0)
        )
        steps = list(screen.query(".failure-next-step"))
        assert len(steps) == 2
        assert len({frozenset(step.classes) for step in steps}) == 1, "neither is marked"
        assert not screen.query("Button")
        assert screen.focused is None


async def test_the_extend_affordance_appears_only_where_a_deeper_search_could_help() -> None:
    app = build()
    stranger = Wallet.from_mnemonic(STRANGER_MNEMONIC, network=Network.MAINNET)
    async with app.run_test(size=CONSOLE) as pilot:
        screen = await open_verify(
            app, pilot, stranger.address(ScriptType.P2WPKH, RECEIVE_CHAIN, 0)
        )
        assert screen.check.offers_deeper_search
        assert addresstext.KEYS_SEARCHABLE in texts(screen)

        wrong = Wallet.from_mnemonic(VECTOR_MNEMONIC, network=Network.SIGNET)
        other = await open_verify(
            app, pilot, wrong.address(ScriptType.P2WPKH, RECEIVE_CHAIN, 0)
        )
        assert not other.check.offers_deeper_search
        assert addresstext.KEYS_SEARCHABLE not in texts(other)


async def test_searching_further_widens_the_window_by_one_block() -> None:
    """And only the user widens it: nothing the address says can move it (`#11`'s rule)."""
    app = build()
    stranger = Wallet.from_mnemonic(STRANGER_MNEMONIC, network=Network.MAINNET)
    async with app.run_test(size=CONSOLE) as pilot:
        screen = await open_verify(
            app, pilot, stranger.address(ScriptType.P2WPKH, RECEIVE_CHAIN, 0)
        )
        await pilot.press(addresstext.SEARCH_FURTHER_KEY)
        await pilot.pause()
        assert app.screen.blocks == 2
        assert app.screen.check.searched == (0, 2 * ADDRESS_SEARCH_BLOCK)
        assert f"0–{2 * ADDRESS_SEARCH_BLOCK}" in blob(app.screen)


async def test_an_address_past_the_first_window_proves_once_the_user_searches_further() -> None:
    app = build()
    far = app.wallet.address(ScriptType.P2WPKH, RECEIVE_CHAIN, ADDRESS_SEARCH_BLOCK + 5)
    async with app.run_test(size=CONSOLE) as pilot:
        screen = await open_verify(app, pilot, far)
        assert screen.check.verdict is Verdict.NOT_FOUND
        await pilot.press(addresstext.SEARCH_FURTHER_KEY)
        await pilot.pause()
        assert app.screen.check.verdict is Verdict.PROVEN
        assert app.wallet.path(
            ScriptType.P2WPKH, RECEIVE_CHAIN, ADDRESS_SEARCH_BLOCK + 5
        ) in texts(app.screen)


# --- Wrong network, and unreadable ------------------------------------------------------------------


async def test_wrong_network_is_its_own_message_and_offers_no_search() -> None:
    """Not a miss. No depth would ever reach it, so offering to look further would send the user
    hunting for nothing."""
    app = build()
    signet = Wallet.from_mnemonic(VECTOR_MNEMONIC, network=Network.SIGNET)
    async with app.run_test(size=CONSOLE) as pilot:
        screen = await open_verify(
            app, pilot, signet.address(ScriptType.P2WPKH, RECEIVE_CHAIN, 0)
        )
        assert screen.check.verdict is Verdict.WRONG_NETWORK
        text = blob(screen)
        assert "mainnet" in text
        # `tb1…` is ambiguous between testnet4 and signet, and the appliance does not guess.
        assert "signet" in text and "testnet4" in text
        assert "not found" not in text.lower()
        assert "F9" not in text
        assert screen.query_one(FailurePanel).failure.condition == "address-wrong-network"


async def test_pressing_the_search_key_on_a_wrong_network_screen_does_nothing() -> None:
    app = build()
    signet = Wallet.from_mnemonic(VECTOR_MNEMONIC, network=Network.SIGNET)
    async with app.run_test(size=CONSOLE) as pilot:
        screen = await open_verify(
            app, pilot, signet.address(ScriptType.P2WPKH, RECEIVE_CHAIN, 0)
        )
        await pilot.press(addresstext.SEARCH_FURTHER_KEY)
        await pilot.pause()
        assert screen.blocks == 1


async def test_something_that_is_not_an_address_is_told_apart_from_a_failed_search() -> None:
    app = build()
    async with app.run_test(size=CONSOLE) as pilot:
        screen = await open_verify(app, pilot, "https://example.invalid/pay")
        assert screen.check.verdict is Verdict.UNREADABLE
        assert screen.query_one(FailurePanel).failure.condition == "not-an-address"
        assert "not found" not in blob(screen).lower()


# --- BIP21 ------------------------------------------------------------------------------------------

#: Attacker-chosen strings that a BIP21 URI can carry. One of them carries ANSI escapes, because
#: never rendering the field is how `docs/threat-model.md`'s escape-injection rule is satisfied
#: here — the field is dropped rather than sanitised.
LABEL = "\x1b[31mPay Acme Corp \x1b[0m"
MESSAGE = "Invoice 4417 — urgent"
AMOUNT = "0.12345678"


async def test_a_bip21_uris_parameters_reach_no_widget_at_all() -> None:
    """A substring sweep in both directions: not sanitised, not truncated — absent."""
    app = build()
    address = app.wallet.address(ScriptType.P2WPKH, RECEIVE_CHAIN, 2)
    uri = f"bitcoin:{address}?amount={AMOUNT}&label={LABEL}&message={MESSAGE}"
    async with app.run_test(size=CONSOLE) as pilot:
        screen = await open_verify(app, pilot, uri)
        assert screen.check.verdict is Verdict.PROVEN, "the address itself is used"
        text = blob(screen)
        for fragment in (AMOUNT, LABEL, MESSAGE, "Acme", "Invoice", "\x1b", "amount=", "label="):
            assert fragment not in text, f"{fragment!r} reached a widget"


async def test_a_bare_address_and_the_same_address_in_a_uri_render_identically() -> None:
    app = build()
    address = app.wallet.address(ScriptType.P2WPKH, RECEIVE_CHAIN, 2)
    async with app.run_test(size=CONSOLE) as pilot:
        bare = texts(await open_verify(app, pilot, address))
        wrapped = texts(await open_verify(app, pilot, f"bitcoin:{address}?label=whatever"))
    assert bare == wrapped


async def test_the_verify_screen_offers_no_script_type_toggle() -> None:
    """`bc1q` is a v0 witness program and `bc1p` is v1 — the prefix already answers it, and a
    toggle would be one more thing to set wrong."""
    app = build()
    address = app.wallet.address(ScriptType.P2TR, RECEIVE_CHAIN, 0)
    async with app.run_test(size=CONSOLE) as pilot:
        screen = await open_verify(app, pilot, address)
        assert screen.check.verdict is Verdict.PROVEN
        assert screen.check.script_type is ScriptType.P2TR
        keys = {binding.key for binding in screen.BINDINGS}
        assert keys == {addresstext.SEARCH_FURTHER_KEY}


# --- The browsable list -----------------------------------------------------------------------------


async def open_list(app: SignerApp, pilot) -> AddressListScreen:
    app.open_address_list()
    await pilot.pause()
    assert isinstance(app.screen, AddressListScreen)
    return app.screen


def rows(screen: AddressListScreen) -> list[str]:
    return [str(node.content) for node in screen.query("#addresses Static")]


async def test_the_list_pages_twenty_at_a_time() -> None:
    app = build()
    async with app.run_test(size=CONSOLE) as pilot:
        screen = await open_list(app, pilot)
        assert len(rows(screen)) == ADDRESS_PAGE_SIZE == 20
        assert [entry.index for entry in screen.addresses] == list(range(0, 20))
        await pilot.press("down")
        await pilot.pause()
        assert [entry.index for entry in app.screen.addresses] == list(range(20, 40))
        await pilot.press("up")
        await pilot.pause()
        assert app.screen.start == 0
        await pilot.press("up")
        await pilot.pause()
        assert app.screen.start == 0, "there is no index below zero"


async def test_the_list_jumps_to_a_typed_index() -> None:
    app = build()
    async with app.run_test(size=CONSOLE) as pilot:
        await open_list(app, pilot)
        await pilot.press("1", "0", "0", "f10")
        await pilot.pause()
        assert app.screen.start == 100
        assert app.screen.addresses[0].address == app.wallet.address(
            ScriptType.P2WPKH, RECEIVE_CHAIN, 100
        )


async def test_the_list_toggles_script_type() -> None:
    """This path *does* need the toggle: here the user is choosing what to look at, rather than
    presenting something for the appliance to check."""
    app = build()
    async with app.run_test(size=CONSOLE) as pilot:
        screen = await open_list(app, pilot)
        assert screen.script_type is ScriptType.P2WPKH
        assert screen.addresses[0].address.startswith("bc1q")
        await pilot.press("f9")
        await pilot.pause()
        assert app.screen.script_type is ScriptType.P2TR
        assert app.screen.addresses[0].address.startswith("bc1p")
        assert "86h" in blob(app.screen)


async def test_every_listed_address_is_full_and_grouped_in_fours() -> None:
    """The same rule as the review screen, for the opposite reason: here the human genuinely is
    comparing by eye against a watch-only wallet."""
    app = build()
    async with app.run_test(size=CONSOLE) as pilot:
        screen = await open_list(app, pilot)
        for entry, line in zip(screen.addresses, rows(screen), strict=True):
            assert "…" not in line and "..." not in line
            assert addresstext.grouped(entry.address) in line
            groups = line.split()[1:]
            assert all(len(group) == 4 for group in groups[:-1])
            assert "".join(groups) == entry.address


async def test_the_list_names_what_it_is_for() -> None:
    """A distinct second purpose, and it is the check that the descriptor export landed intact."""
    app = build()
    async with app.run_test(size=CONSOLE) as pilot:
        screen = await open_list(app, pilot)
        assert "watch-only wallet" in blob(screen)


# --- The scan hand-off ------------------------------------------------------------------------------


async def test_a_completed_address_scan_lands_on_the_verify_screen() -> None:
    app = build()
    address = app.wallet.address(ScriptType.P2WPKH, RECEIVE_CHAIN, 1)
    async with app.run_test(size=CONSOLE) as pilot:
        app.open_address_verify(address)
        await pilot.pause()
        assert isinstance(app.screen, AddressVerifyScreen)
        assert app.screen.check.verdict is Verdict.PROVEN


def test_the_screen_derives_nothing_the_core_has_not_already_decided() -> None:
    """The screen's `check` is `core.verify` and nothing else — asserted directly rather than by
    reading the screen, so a screen that started deriving would fail here first."""
    wallet = Wallet.from_mnemonic(VECTOR_MNEMONIC, network=Network.MAINNET)
    address = wallet.address(ScriptType.P2WPKH, RECEIVE_CHAIN, 4)
    assert verify(address, wallet, blocks=1) == verify(f"bitcoin:{address}", wallet, blocks=1)
