"""The encrypted wallet QR: 89 bytes carrying the BIP39 entropy, and never the passphrase.

Container layout, exactly as `docs/encrypted-wallet-qr.md` fixes it:

    magic 4 | version 1 | network 1 | Argon2id m,t,p 6 | salt 16 | nonce 12 | ciphertext 33 | tag 16

The whole 12-byte header is the AEAD's associated data, so **the network byte is authenticated
without being encrypted**: readable before the password is typed, and still covered by the tag
once it has been. The network was never a secret, and the appliance holds no network-dependent
secret a cleartext byte could leak.

**This module does not compare the network against a session.** The core holds no session; the
comparison is the application's, and this stays a pure codec.

ChaCha20-Poly1305 with the full 16-byte tag — never truncated, because this format has no size
pressure and the tag is the one field that authenticates the backup. Argon2id parameters are
encoded exactly: Krux shipped a lossy iteration encoding and produced backups that could not be
decrypted, which is the failure this layout exists to avoid.

**The passphrase is not in here.** What is encrypted is the entropy and the word count, so
someone holding the QR *and* the paper with the eight words still cannot spend.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from argon2.low_level import Type, hash_secret_raw
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305

from .constants import (
    ARGON2_MEMORY_KIB,
    ARGON2_PARALLELISM,
    ARGON2_TIME_COST,
    WALLET_QR_MAGIC,
    WALLET_QR_NETWORK_BYTE,
    WALLET_QR_NONCE_BYTES,
    WALLET_QR_PLAINTEXT_BYTES,
    WALLET_QR_SALT_BYTES,
    WALLET_QR_TAG_BYTES,
    WALLET_QR_TOTAL_BYTES,
    WALLET_QR_VERSION,
)
from .export_password import ExportPassword, generate
from .wallet import Network

#: The header's network byte, both ways, from the one explicit table in `constants` — so the two
#: directions cannot drift apart. `NETWORK_FOR_BYTE` is public because the scan screen reads the
#: same byte out of the cleartext header before any decryption, and a second copy of this mapping
#: over there is a second thing to keep in step.
BYTE_FOR_NETWORK = {network: WALLET_QR_NETWORK_BYTE[network.value] for network in Network}
NETWORK_FOR_BYTE = {byte: network for network, byte in BYTE_FOR_NETWORK.items()}

#: BIP39 word counts, and the entropy length each implies. A word count is one byte in the
#: container and is what lets the words be shown back exactly as they were.
WORD_COUNTS = (12, 15, 18, 21, 24)


class ForeignContainer(Exception):
    """The magic bytes, version or network did not parse: this is not one of our containers.

    Distinguished *before* decryption and by framing rather than by cryptography — an AEAD tag
    cannot tell a wrong password from a foreign QR, and a password verifier that could would hand
    an offline attacker an oracle.
    """


class AuthenticationFailed(Exception):
    """Our container, and the tag did not verify.

    Wrong password or tampering, without a claim about which: the tag cannot tell them apart, so
    neither does the appliance.
    """


@dataclass(frozen=True)
class Argon2Params:
    """Encoded exactly, never lossily. Six bytes: memory as four, time and parallelism as one
    each — which is the whole admissible range of each, with nothing rounded."""

    memory_kib: int = ARGON2_MEMORY_KIB
    time_cost: int = ARGON2_TIME_COST
    parallelism: int = ARGON2_PARALLELISM

    def __post_init__(self) -> None:
        if not 8 <= self.memory_kib <= 0xFFFFFFFF:
            raise ValueError("memory_kib outside the range the container admits")
        if not 1 <= self.time_cost <= 0xFF:
            raise ValueError("time_cost outside the range the container admits")
        if not 1 <= self.parallelism <= 0xFF:
            raise ValueError("parallelism outside the range the container admits")
        if self.memory_kib < 8 * self.parallelism:
            raise ValueError("Argon2id requires memory_kib >= 8 * parallelism")

    def serialize(self) -> bytes:
        return (
            self.memory_kib.to_bytes(4, "big")
            + self.time_cost.to_bytes(1, "big")
            + self.parallelism.to_bytes(1, "big")
        )

    @classmethod
    def parse(cls, raw: bytes) -> Argon2Params:
        if len(raw) != 6:
            raise ForeignContainer("Argon2 parameter field is not six bytes")
        return cls(
            memory_kib=int.from_bytes(raw[:4], "big"),
            time_cost=raw[4],
            parallelism=raw[5],
        )


@dataclass(frozen=True)
class ExportedWallet:
    """What an export produces: the QR's bytes, and the password the user must write down.

    They are returned together and shown apart — `docs/export-password.md` keeps the password and
    the QR off the same screen, because together they are one photograph.
    """

    container: bytes
    password: ExportPassword


@dataclass(frozen=True)
class DecodedWallet:
    entropy: bytes
    word_count: int
    #: The network the container was exported from, read from the header the tag covers. It is
    #: what lets a session refuse a backup written for another chain — a check the master
    #: fingerprint cannot make, because the fingerprint comes from the seed and is identical on
    #: all four networks.
    network: Network


def export_wallet(
    entropy: bytes,
    random_bytes: Callable[[int], bytes],
    *,
    network: Network,
    params: Argon2Params | None = None,
) -> ExportedWallet:
    """Encrypt `entropy` under a freshly generated export password.

    **There is no password parameter, and this is the enforcement.** A user-chosen password would
    move the security of the export onto a KDF `docs/encrypted-wallet-qr.md` has already said is
    not load-bearing, and the only enforcement that cannot be talked around later is the absence
    of the feature.

    `random_bytes` is the caller's randomness — the `EntropySource` port in the appliance.

    `network` has **no default**. Every caller has one, and a default here would be the
    silent-mainnet bug this format's network byte exists to catch, reintroduced one layer down.
    """
    word_count = _word_count_for(entropy)
    password = generate(random_bytes)
    container = _seal(
        entropy=entropy,
        word_count=word_count,
        password=password,
        network=network,
        salt=random_bytes(WALLET_QR_SALT_BYTES),
        nonce=random_bytes(WALLET_QR_NONCE_BYTES),
        params=params or Argon2Params(),
    )
    return ExportedWallet(container=container, password=password)


def decode(container: bytes, password: ExportPassword) -> DecodedWallet:
    """Read one of our containers back.

    Raises `ForeignContainer` when the framing does not parse — a different message to the user,
    decided before any decryption — and `AuthenticationFailed` when it does parse and the tag
    does not verify.
    """
    if len(container) != WALLET_QR_TOTAL_BYTES:
        raise ForeignContainer("wrong length")
    if container[:4] != WALLET_QR_MAGIC:
        raise ForeignContainer("wrong magic")
    if container[4] != WALLET_QR_VERSION:
        raise ForeignContainer("unknown version")
    network = NETWORK_FOR_BYTE.get(container[5])
    if network is None:
        # Framing before cryptography, like the magic and the version: a container naming a
        # network this build does not know is reported in its own words, never as a wrong
        # password, which would send the user hunting for a typing mistake they did not make.
        raise ForeignContainer("unknown network")

    header = container[:12]
    params = Argon2Params.parse(container[6:12])
    salt = container[12:28]
    nonce = container[28:40]
    sealed = container[40:]

    key = _derive_key(password, salt, params)
    try:
        plaintext = ChaCha20Poly1305(key).decrypt(nonce, sealed, header)
    except Exception as failure:  # cryptography raises InvalidTag
        raise AuthenticationFailed("wrong password or tampering") from failure

    word_count = plaintext[-1]
    if word_count not in WORD_COUNTS:
        # Authenticated, so this is our own bytes disagreeing with themselves.
        raise AuthenticationFailed("wrong password or tampering")
    entropy_length = word_count * 4 // 3
    return DecodedWallet(
        entropy=plaintext[:entropy_length], word_count=word_count, network=network
    )


# --- Internals ------------------------------------------------------------------------------------


def _word_count_for(entropy: bytes) -> int:
    if len(entropy) not in (16, 20, 24, 28, 32):
        raise ValueError("BIP39 entropy is 16 to 32 bytes, in steps of four")
    return len(entropy) * 3 // 4


def _seal(
    *,
    entropy: bytes,
    word_count: int,
    password: ExportPassword,
    network: Network,
    salt: bytes,
    nonce: bytes,
    params: Argon2Params,
) -> bytes:
    if len(salt) != WALLET_QR_SALT_BYTES or len(nonce) != WALLET_QR_NONCE_BYTES:
        raise ValueError("salt or nonce is the wrong length")
    # Padded to a fixed 33 bytes so the container's size never states the word count.
    plaintext = entropy.ljust(WALLET_QR_PLAINTEXT_BYTES - 1, b"\x00") + bytes([word_count])
    header = (
        WALLET_QR_MAGIC
        + bytes([WALLET_QR_VERSION, BYTE_FOR_NETWORK[network]])
        + params.serialize()
    )
    key = _derive_key(password, salt, params)
    sealed = ChaCha20Poly1305(key).encrypt(nonce, plaintext, header)
    container = header + salt + nonce + sealed
    if len(container) != WALLET_QR_TOTAL_BYTES:  # pragma: no cover - arithmetic, checked anyway
        raise ValueError("container is not 89 bytes")
    if len(sealed) != WALLET_QR_PLAINTEXT_BYTES + WALLET_QR_TAG_BYTES:  # pragma: no cover
        raise ValueError("the Poly1305 tag was truncated")
    return container


def _derive_key(password: ExportPassword, salt: bytes, params: Argon2Params) -> bytes:
    return hash_secret_raw(
        secret=password.text.encode("utf-8"),
        salt=salt,
        time_cost=params.time_cost,
        memory_cost=params.memory_kib,
        parallelism=params.parallelism,
        hash_len=32,
        type=Type.ID,
    )
