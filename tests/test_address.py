"""Address verification: the receive-side proof rule, and the wording it must not overstate."""

from __future__ import annotations

import pytest

from aobs.core.address import Verdict, page, parse_scanned, verify
from aobs.core.constants import ADDRESS_PAGE_SIZE
from aobs.core.wallet import CHANGE_CHAIN, Network, ScriptType, Wallet

from conftest import VECTOR_MNEMONIC



@pytest.fixture
def wallet() -> Wallet:
    return Wallet.from_mnemonic(VECTOR_MNEMONIC, network=Network.MAINNET)


# --- Proven ---------------------------------------------------------------------------------------


def test_a_receive_address_is_proven_and_leads_with_its_path(wallet: Wallet) -> None:
    result = verify("bc1qnjg0jd8228aq7egyzacy8cys3knf9xvrerkf9g", wallet)
    assert result.verdict is Verdict.PROVEN
    assert result.proven is not None
    assert result.proven.path == "m/84h/0h/0h/0/1"
    assert result.address == "bc1qnjg0jd8228aq7egyzacy8cys3knf9xvrerkf9g"


def test_a_taproot_address_proves_without_a_toggle(wallet: Wallet) -> None:
    address = wallet.address(ScriptType.P2TR, 0, 7)
    result = verify(address, wallet)
    assert result.verdict is Verdict.PROVEN
    assert result.script_type is ScriptType.P2TR
    assert result.proven is not None and result.proven.path == "m/86h/0h/0h/0/7"


def test_the_change_chain_is_searched_too(wallet: Wallet) -> None:
    address = wallet.address(ScriptType.P2WPKH, CHANGE_CHAIN, 3)
    assert verify(address, wallet).proven.path == "m/84h/0h/0h/1/3"


# --- The URI --------------------------------------------------------------------------------------


def test_a_bip21_uri_is_accepted_and_its_parameters_are_dropped(wallet: Wallet) -> None:
    uri = (
        "bitcoin:bc1qcr8te4kr609gcawutmrza0j4xv80jy8z306fyu"
        "?amount=0.01&label=Pay%20me%20instead&message=%1b%5b31mURGENT"
    )
    result = verify(uri, wallet)
    assert result.verdict is Verdict.PROVEN
    assert result.address == "bc1qcr8te4kr609gcawutmrza0j4xv80jy8z306fyu"
    # There is no field for them to arrive in: the core never carries a label or a message.
    assert not hasattr(result, "label")
    assert not hasattr(result, "message")
    assert "URGENT" not in repr(result)


def test_a_uri_with_malformed_parameters_is_still_usable(wallet: Wallet) -> None:
    """Strict about the address, lenient about the rest."""
    uri = "BITCOIN:bc1qcr8te4kr609gcawutmrza0j4xv80jy8z306fyu?=&amount&&%%%=1"
    assert verify(uri, wallet).verdict is Verdict.PROVEN


def test_parse_scanned_returns_only_an_address() -> None:
    assert parse_scanned("bitcoin:bc1qx?amount=1") == "bc1qx"
    assert parse_scanned("  bc1qx  ") == "bc1qx"
    assert parse_scanned("") is None
    assert parse_scanned("bitcoin:") is None


# --- Not found, never "not yours" -------------------------------------------------------------------


def test_a_stranger_address_is_not_found_and_states_the_window(wallet: Wallet) -> None:
    stranger = "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4"
    result = verify(stranger, wallet)
    assert result.verdict is Verdict.NOT_FOUND
    assert result.searched == (0, 200)
    assert result.proven is None
    assert result.offers_deeper_search


def test_our_own_address_past_the_window_is_also_only_not_found(wallet: Wallet) -> None:
    """The appliance cannot tell this case from the previous one, and does not pretend to."""
    far = wallet.address(ScriptType.P2WPKH, 0, 250)
    assert verify(far, wallet).verdict is Verdict.NOT_FOUND
    # Extended deliberately, by the caller, in blocks of 200 — never by anything the address says.
    extended = verify(far, wallet, blocks=2)
    assert extended.verdict is Verdict.PROVEN
    assert extended.searched == (0, 400)


# --- Wrong network is not a miss ---------------------------------------------------------------------


def test_a_testnet_address_on_a_mainnet_wallet_gets_its_own_verdict(wallet: Wallet) -> None:
    result = verify("tb1qw508d6qejxtdg4y5r3zarvary0c5xw7kxpjzsx", wallet)
    assert result.verdict is Verdict.WRONG_NETWORK
    assert result.address_networks == frozenset({Network.TESTNET4, Network.SIGNET})
    # No search is offered: it could never match at any depth.
    assert not result.offers_deeper_search
    assert result.searched is None


def test_a_signet_wallet_accepts_a_tb1_address() -> None:
    signet = Wallet.from_mnemonic(VECTOR_MNEMONIC, network=Network.SIGNET)
    own = signet.address(ScriptType.P2WPKH, 0, 0)
    assert verify(own, signet).verdict is Verdict.PROVEN


def test_something_that_is_not_an_address_at_all(wallet: Wallet) -> None:
    assert verify("hello world", wallet).verdict is Verdict.UNREADABLE
    assert verify("1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2", wallet).verdict is Verdict.UNREADABLE


# --- The browsable list --------------------------------------------------------------------------------


def test_the_list_is_twenty_at_a_time_with_jump_to_index(wallet: Wallet) -> None:
    first = page(wallet, ScriptType.P2WPKH)
    assert len(first) == ADDRESS_PAGE_SIZE == 20
    assert first[0].address == "bc1qcr8te4kr609gcawutmrza0j4xv80jy8z306fyu"
    assert first[0].path == "m/84h/0h/0h/0/0"

    jumped = page(wallet, ScriptType.P2TR, start=100, count=5)
    assert [listed.index for listed in jumped] == [100, 101, 102, 103, 104]
    assert jumped[0].address == wallet.address(ScriptType.P2TR, 0, 100)


def test_the_list_covers_both_chains_and_both_script_types(wallet: Wallet) -> None:
    change = page(wallet, ScriptType.P2WPKH, chain=CHANGE_CHAIN, count=1)
    assert change[0].address == "bc1q8c6fshw2dlwun7ekn9qwf37cu2rn755upcp6el"


def test_addresses_are_full_strings(wallet: Wallet) -> None:
    for listed in page(wallet, ScriptType.P2TR, count=3):
        assert "…" not in listed.address and "..." not in listed.address
        assert len(listed.address) == 62
