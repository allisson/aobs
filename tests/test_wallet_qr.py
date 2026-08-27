"""The encrypted wallet QR and the export password.

`docs/test-harness.md` puts the hardest testing here on purpose: every real failure across Krux,
SeedSigner and Specter-DIY was plumbing rather than cryptography — a misused CBC IV, a heap
overflow, a lossy iteration encoding. So: round trips, at every parameter value the format
admits.
"""

from __future__ import annotations

import hashlib
import inspect

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from aobs.core.constants import (
    ARGON2_MEMORY_KIB,
    ARGON2_PARALLELISM,
    ARGON2_TIME_COST,
    WALLET_QR_MAGIC,
    WALLET_QR_NETWORK_BYTE,
    WALLET_QR_TOTAL_BYTES,
    WALLET_QR_VERSION,
)
from aobs.core.export_password import ExportPassword, candidates, generate, resolve, wordlist
from aobs.core import wallet_qr
from aobs.core.wallet import Network
from aobs.core.wallet_qr import (
    Argon2Params,
    AuthenticationFailed,
    ForeignContainer,
    decode,
    export_wallet,
)

from conftest import fixed_bytes

#: Argon2id at 64 MiB is ~0.1 s a call, which a property test cannot afford hundreds of. The
#: parameter *encoding* — the thing that broke Krux — is exercised over the whole admissible
#: range below; the cipher round trip uses cheap parameters and one full-strength case.
CHEAP = Argon2Params(memory_kib=64, time_cost=1, parallelism=1)


# --- The shape the format promises ---------------------------------------------------------------


def test_container_is_89_bytes_with_the_documented_framing() -> None:
    exported = export_wallet(bytes(range(32)), fixed_bytes(), network=Network.MAINNET, params=CHEAP)
    assert len(exported.container) == WALLET_QR_TOTAL_BYTES == 89
    assert exported.container[:4] == WALLET_QR_MAGIC
    assert exported.container[4] == WALLET_QR_VERSION == 2


def test_the_tag_is_never_truncated() -> None:
    exported = export_wallet(bytes(range(32)), fixed_bytes(), network=Network.MAINNET, params=CHEAP)
    # 89 = 4 + 1 + 1 + 6 + 16 + 12 + 33 + 16. The last 16 are the full Poly1305 tag.
    assert len(exported.container) - (4 + 1 + 1 + 6 + 16 + 12 + 33) == 16


# --- The network byte ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("network", "byte"),
    [
        (Network.MAINNET, 0x00),
        (Network.TESTNET4, 0x01),
        (Network.SIGNET, 0x02),
        (Network.REGTEST, 0x03),
    ],
)
def test_the_network_byte_is_at_the_documented_offset_with_the_documented_value(
    network: Network, byte: int
) -> None:
    """Against literals, never against `Network`'s iteration order: an ordinal would make
    reordering the enum a silent reinterpretation of every container already written."""
    exported = export_wallet(bytes(range(32)), fixed_bytes(), network=network, params=CHEAP)
    assert WALLET_QR_NETWORK_BYTE[network.value] == byte
    assert exported.container[5] == byte
    assert decode(exported.container, exported.password).network is network


def test_every_network_has_a_byte_and_no_two_share_one() -> None:
    assert set(WALLET_QR_NETWORK_BYTE) == {network.value for network in Network}
    assert len(set(WALLET_QR_NETWORK_BYTE.values())) == len(WALLET_QR_NETWORK_BYTE)


@pytest.mark.parametrize("network", list(Network))
@pytest.mark.parametrize("word_count", [12, 15, 18, 21, 24])
def test_a_container_round_trips_on_every_network_at_every_word_count(
    network: Network, word_count: int
) -> None:
    entropy = hashlib.sha256(f"{network.value}-{word_count}".encode()).digest()[
        : word_count * 4 // 3
    ]
    exported = export_wallet(entropy, fixed_bytes(), network=network, params=CHEAP)
    decoded = decode(exported.container, exported.password)
    assert (decoded.entropy, decoded.word_count, decoded.network) == (entropy, word_count, network)


def test_flipping_the_network_byte_fails_authentication_exactly_as_a_wrong_password_does() -> None:
    """The tag covers the header, so the cleartext byte buys an attacker nothing — which is why
    the scan screen's early gate is a courtesy and the authenticated check is the boundary."""
    exported = export_wallet(bytes(range(32)), fixed_bytes(), network=Network.MAINNET, params=CHEAP)
    substituted = bytearray(exported.container)
    substituted[5] = WALLET_QR_NETWORK_BYTE[Network.SIGNET.value]
    with pytest.raises(AuthenticationFailed) as flipped:
        decode(bytes(substituted), exported.password)

    other = generate(fixed_bytes(b"someone-else"))
    with pytest.raises(AuthenticationFailed) as wrong_password:
        decode(exported.container, other)
    assert str(flipped.value) == str(wrong_password.value) == "wrong password or tampering"


def test_an_unrecognised_network_byte_is_framing_and_never_authentication() -> None:
    """Told in its own words, before any key derivation — never *wrong password*, which would
    send the user hunting for a typing mistake they did not make."""
    exported = export_wallet(bytes(range(32)), fixed_bytes(), network=Network.MAINNET, params=CHEAP)
    unknown = exported.container[:5] + b"\x7f" + exported.container[6:]
    with pytest.raises(ForeignContainer):
        decode(unknown, exported.password)


def test_export_wallet_has_no_default_network() -> None:
    """A default here is the silent-mainnet bug reintroduced one layer down."""
    network = inspect.signature(export_wallet).parameters["network"]
    assert network.default is inspect.Parameter.empty
    assert network.kind is inspect.Parameter.KEYWORD_ONLY


def test_default_parameters_are_the_documented_ones() -> None:
    params = Argon2Params()
    assert (params.memory_kib, params.time_cost, params.parallelism) == (
        ARGON2_MEMORY_KIB,
        ARGON2_TIME_COST,
        ARGON2_PARALLELISM,
    )
    assert ARGON2_MEMORY_KIB == 64 * 1024


def test_the_export_interface_exposes_no_password_argument() -> None:
    """Enforcement by absence. Adding "advanced options" later fails here."""
    names = " ".join(inspect.signature(export_wallet).parameters).lower()
    assert "password" not in names
    assert "passphrase" not in names
    # And there is no second door: nothing else in the module encrypts.
    public = [
        name
        for name, value in vars(wallet_qr).items()
        if not name.startswith("_")
        and inspect.isfunction(value)
        and value.__module__ == wallet_qr.__name__
    ]
    assert public == ["export_wallet", "decode"]


def test_the_passphrase_is_not_in_the_container() -> None:
    """The load-bearing half of the format: the QR alone is not the wallet."""
    entropy = bytes(range(32))
    exported = export_wallet(entropy, fixed_bytes(), network=Network.MAINNET, params=CHEAP)
    assert decode(exported.container, exported.password) == wallet_qr.DecodedWallet(
        entropy=entropy, word_count=24, network=Network.MAINNET
    )
    # There is nowhere for a passphrase to go: the plaintext is 33 bytes, all accounted for.
    assert b"TREZOR" not in exported.container


# --- Round trips ----------------------------------------------------------------------------------


@pytest.mark.parametrize("word_count", [12, 15, 18, 21, 24])
def test_every_word_count_round_trips(word_count: int) -> None:
    entropy = hashlib.sha256(str(word_count).encode()).digest()[: word_count * 4 // 3]
    exported = export_wallet(entropy, fixed_bytes(), network=Network.MAINNET, params=CHEAP)
    decoded = decode(exported.container, exported.password)
    assert decoded.entropy == entropy
    assert decoded.word_count == word_count


def test_a_full_strength_container_round_trips() -> None:
    """Once, at the real 64 MiB / t=3 / p=1."""
    entropy = bytes(range(16))
    exported = export_wallet(entropy, fixed_bytes(), network=Network.MAINNET)
    assert decode(exported.container, exported.password).entropy == entropy


@settings(max_examples=200, deadline=None)
@given(
    memory_kib=st.integers(min_value=8, max_value=0xFFFFFFFF),
    time_cost=st.integers(min_value=1, max_value=0xFF),
    parallelism=st.integers(min_value=1, max_value=0xFF),
)
def test_parameters_encode_exactly_across_the_whole_admissible_range(
    memory_kib: int, time_cost: int, parallelism: int
) -> None:
    """Krux's failure, as a property: parameters that do not survive their own encoding produce
    backups that cannot be decrypted."""
    if memory_kib < 8 * parallelism:
        return
    params = Argon2Params(memory_kib, time_cost, parallelism)
    assert Argon2Params.parse(params.serialize()) == params
    assert len(params.serialize()) == 6


@settings(max_examples=25, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    entropy=st.binary(min_size=32, max_size=32),
    time_cost=st.integers(min_value=1, max_value=3),
    parallelism=st.integers(min_value=1, max_value=4),
)
def test_the_container_round_trips_under_varying_parameters(
    entropy: bytes, time_cost: int, parallelism: int
) -> None:
    params = Argon2Params(memory_kib=64, time_cost=time_cost, parallelism=parallelism)
    exported = export_wallet(entropy, fixed_bytes(), network=Network.MAINNET, params=params)
    assert decode(exported.container, exported.password).entropy == entropy


# --- Failure behaviour ------------------------------------------------------------------------------


def test_a_wrong_password_fails_authentication_without_a_claim_about_which() -> None:
    exported = export_wallet(bytes(range(32)), fixed_bytes(), network=Network.MAINNET, params=CHEAP)
    other = generate(fixed_bytes(b"someone-else"))
    with pytest.raises(AuthenticationFailed) as raised:
        decode(exported.container, other)
    assert str(raised.value) == "wrong password or tampering"


def test_tampering_fails_the_same_way_as_a_wrong_password() -> None:
    exported = export_wallet(bytes(range(32)), fixed_bytes(), network=Network.MAINNET, params=CHEAP)
    flipped = bytearray(exported.container)
    flipped[50] ^= 0x01
    with pytest.raises(AuthenticationFailed):
        decode(bytes(flipped), exported.password)


def test_a_foreign_qr_is_distinguished_by_framing_before_any_decryption() -> None:
    exported = export_wallet(bytes(range(32)), fixed_bytes(), network=Network.MAINNET, params=CHEAP)
    foreign = b"XXXX" + exported.container[4:]
    with pytest.raises(ForeignContainer):
        decode(foreign, exported.password)
    with pytest.raises(ForeignContainer):
        decode(exported.container[:-1], exported.password)
    unknown_version = exported.container[:4] + b"\x01" + exported.container[5:]
    with pytest.raises(ForeignContainer):
        decode(unknown_version, exported.password)


# --- The wordlist ------------------------------------------------------------------------------------


def test_the_wordlist_is_the_published_eff_large_list() -> None:
    words = wordlist()
    assert len(words) == 7776
    assert words[0] == "abacus"
    assert words[-1] == "zoom"
    # The four hyphenated words are kept: pruning them would make this a custom list that must
    # then be published byte-exactly and matched forever.
    assert {"drop-down", "felt-tip", "t-shirt", "yo-yo"} <= set(words)


def test_the_list_is_not_prefix_unique_which_is_why_entry_is_full_word() -> None:
    words = wordlist()
    ambiguous = sum(
        1 for word in words if sum(1 for w in words if w[:4] == word[:4]) > 1
    )
    assert ambiguous == 5502
    assert resolve("abac") is None
    assert resolve("abacus") == "abacus"
    assert resolve("  Abacus ") == "abacus"
    assert resolve("notaword") is None


def test_autocomplete_narrows_without_accepting_a_prefix() -> None:
    narrowed = candidates("zoo")
    assert "zoom" in narrowed
    assert len(narrowed) > 1
    assert resolve("zoo") is None


def test_a_generated_password_is_eight_words_and_reproducible_from_its_randomness() -> None:
    first = generate(fixed_bytes())
    second = generate(fixed_bytes())
    assert first.words == second.words
    assert len(first.words) == 8
    assert all(word in set(wordlist()) for word in first.words)
    assert first.numbered()[0][0] == 1


def test_read_back_covers_all_eight_words() -> None:
    password = generate(fixed_bytes())
    assert password.read_back_matches(password.words)
    wrong = list(password.words)
    wrong[6] = "zoom" if wrong[6] != "zoom" else "abacus"
    assert not password.read_back_matches(wrong)
    # A subset is not a read-back: the interface takes eight slots and compares eight.
    assert not password.read_back_matches(password.words[:3])


def test_a_failed_read_back_retries_the_same_password() -> None:
    """A fresh password would silently invalidate what the user has already written down. The
    core makes that structurally so: the password is a value the caller already holds."""
    exported = export_wallet(bytes(range(32)), fixed_bytes(), network=Network.MAINNET, params=CHEAP)
    assert not exported.password.read_back_matches(["wrong"] * 8)
    assert exported.password.read_back_matches(exported.password.words)
    assert decode(exported.container, exported.password).word_count == 24


def test_a_password_never_renders_its_words() -> None:
    password = generate(fixed_bytes())
    rendered = f"{password!r} {password!s}"
    for word in password.words:
        assert word not in rendered


def test_a_password_must_be_eight_words_from_the_list() -> None:
    with pytest.raises(ValueError):
        ExportPassword(("abacus",) * 7)
    with pytest.raises(ValueError):
        ExportPassword(("notaword",) * 8)
