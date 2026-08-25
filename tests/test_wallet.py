"""Derivation, against the published BIP84 and BIP86 test vectors.

Nothing here is a live wallet: every key comes from the BIP39 test-vector mnemonic, which is
public (`docs/test-harness.md`).
"""

import pytest

from aobs.core.wallet import (
    Network,
    ScriptType,
    Wallet,
    descriptor_checksum,
    networks_for_address,
    script_type_from_address,
)

from conftest import VECTOR_MNEMONIC



@pytest.fixture
def mainnet() -> Wallet:
    return Wallet.from_mnemonic(VECTOR_MNEMONIC, network=Network.MAINNET)


# --- BIP84, from bip-0084.mediawiki ------------------------------------------------------------


def test_bip84_receiving_addresses(mainnet: Wallet) -> None:
    assert mainnet.address(ScriptType.P2WPKH, 0, 0) == (
        "bc1qcr8te4kr609gcawutmrza0j4xv80jy8z306fyu"
    )
    assert mainnet.address(ScriptType.P2WPKH, 0, 1) == (
        "bc1qnjg0jd8228aq7egyzacy8cys3knf9xvrerkf9g"
    )


def test_bip84_first_change_address(mainnet: Wallet) -> None:
    assert mainnet.address(ScriptType.P2WPKH, 1, 0) == (
        "bc1q8c6fshw2dlwun7ekn9qwf37cu2rn755upcp6el"
    )


# --- BIP86, from bip-0086.mediawiki ------------------------------------------------------------


def test_bip86_account_xpub(mainnet: Wallet) -> None:
    assert mainnet.account_xpub(ScriptType.P2TR) == (
        "xpub6BgBgsespWvERF3LHQu6CnqdvfEvtMcQjYrcRzx53QJjSxarj2afYWcLteoGVky7D3UKDP9Qyr"
        "LprQ3VCECoY49yfdDEHGCtMMj92pReUsQ"
    )


def test_bip86_addresses(mainnet: Wallet) -> None:
    assert mainnet.address(ScriptType.P2TR, 0, 0) == (
        "bc1p5cyxnuxmeuwuvkwfem96lqzszd02n6xdcjrs20cac6yqjjwudpxqkedrcr"
    )
    assert mainnet.address(ScriptType.P2TR, 0, 1) == (
        "bc1p4qhjn9zdvkux4e44uhx8tc55attvtyu358kutcqkudyccelu0was9fqzwh"
    )
    assert mainnet.address(ScriptType.P2TR, 1, 0) == (
        "bc1p3qkhfews2uk44qtvauqyr2ttdsw7svhkl9nkm9s9c3x4ax5h60wqwruhk7"
    )


# --- Identity and networks ---------------------------------------------------------------------


def test_master_fingerprint(mainnet: Wallet) -> None:
    assert mainnet.fingerprint_hex == "73c5da0a"


def test_passphrase_changes_the_wallet_and_is_known_to_the_core() -> None:
    plain = Wallet.from_mnemonic(VECTOR_MNEMONIC, network=Network.MAINNET)
    with_passphrase = Wallet.from_mnemonic(
        VECTOR_MNEMONIC, network=Network.MAINNET, passphrase="TREZOR"
    )
    assert plain.has_passphrase is False
    assert with_passphrase.has_passphrase is True
    assert plain.fingerprint != with_passphrase.fingerprint


def test_coin_type_is_1_off_mainnet() -> None:
    signet = Wallet.from_mnemonic(VECTOR_MNEMONIC, network=Network.SIGNET)
    assert signet.account_path(ScriptType.P2WPKH) == "m/84h/1h/0h"
    assert signet.address(ScriptType.P2WPKH, 0, 0).startswith("tb1q")


def test_wallet_never_renders_key_material(mainnet: Wallet) -> None:
    # docs/secret-hygiene.md: nothing that could hold key material is ever printed.
    rendered = f"{mainnet!r} {mainnet!s}"
    assert "xprv" not in rendered
    assert mainnet.root.to_base58() not in rendered
    assert rendered.count("73c5da0a") == 2


# --- Descriptor export -------------------------------------------------------------------------


def test_descriptor_checksum_matches_bip380_reference() -> None:
    # Bitcoin Core's own worked example (doc/descriptors.md).
    body = (
        "wpkh([d34db33f/84h/0h/0h]xpub6DJ2dNUysrn5Vt36jH2KLBT2i1auw1tTSSomg8PhqNiUtx8QX2"
        "SvC9nrHu81fT41fvDUnhMjEzQgXnQjKEu3oaqMSzhSrHMxyyoEAmUHQbY/0/*)"
    )
    assert descriptor_checksum(body) == "cjjspncu"


def test_bip84_descriptor_carries_origin_and_fingerprint(mainnet: Wallet) -> None:
    descriptor = mainnet.descriptor(ScriptType.P2WPKH)
    assert descriptor.startswith("wpkh([73c5da0a/84h/0h/0h]xpub")
    assert descriptor.split("#")[0].endswith("/0/*)")
    body, checksum = descriptor.split("#")
    assert descriptor_checksum(body) == checksum


def test_bip86_descriptor_uses_tr(mainnet: Wallet) -> None:
    # research/xpub-export-formats: `tr(...)` is what carries BIP86 into all three wallets.
    assert mainnet.descriptor(ScriptType.P2TR).startswith("tr([73c5da0a/86h/0h/0h]xpub")


# --- Reading an address ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("address", "expected"),
    [
        ("bc1qcr8te4kr609gcawutmrza0j4xv80jy8z306fyu", ScriptType.P2WPKH),
        ("bc1p5cyxnuxmeuwuvkwfem96lqzszd02n6xdcjrs20cac6yqjjwudpxqkedrcr", ScriptType.P2TR),
        ("BC1QCR8TE4KR609GCAWUTMRZA0J4XV80JY8Z306FYU", ScriptType.P2WPKH),
        ("1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2", None),  # p2pkh: not a script type we have
        ("nonsense", None),
    ],
)
def test_script_type_comes_from_the_prefix(address: str, expected: ScriptType | None) -> None:
    assert script_type_from_address(address) == expected


def test_hrp_does_not_identify_a_single_network() -> None:
    # testnet4 and signet share `tb`, so wrong-network is decided on the family, not the name.
    assert networks_for_address("bc1qcr8te4kr609gcawutmrza0j4xv80jy8z306fyu") == {
        Network.MAINNET
    }
    assert networks_for_address("tb1qw508d6qejxtdg4y5r3zarvary0c5xw7kxpjzsx") == {
        Network.TESTNET4,
        Network.SIGNET,
    }
    assert networks_for_address("bcrt1qw508d6qejxtdg4y5r3zarvary0c5xw7kygt080") == {
        Network.REGTEST
    }
    assert networks_for_address("ltc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4") == set()
