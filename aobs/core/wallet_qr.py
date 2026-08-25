"""The encrypted wallet QR: 88 bytes carrying the BIP39 entropy, and never the passphrase.

Container layout, exactly as `docs/encrypted-wallet-qr.md` fixes it:

    magic 4 | version 1 | Argon2id m,t,p 6 | salt 16 | nonce 12 | ciphertext 33 | tag 16

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
    WALLET_QR_NONCE_BYTES,
    WALLET_QR_PLAINTEXT_BYTES,
    WALLET_QR_SALT_BYTES,
    WALLET_QR_TAG_BYTES,
    WALLET_QR_TOTAL_BYTES,
    WALLET_QR_VERSION,
)
from .export_password import ExportPassword, generate

#: BIP39 word counts, and the entropy length each implies. A word count is one byte in the
#: container and is what lets the words be shown back exactly as they were.
WORD_COUNTS = (12, 15, 18, 21, 24)


class ForeignContainer(Exception):
    """The magic bytes or version did not parse: this is not one of our containers.

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


def export_wallet(
    entropy: bytes,
    random_bytes: Callable[[int], bytes],
    *,
    params: Argon2Params | None = None,
) -> ExportedWallet:
    """Encrypt `entropy` under a freshly generated export password.

    **There is no password parameter, and this is the enforcement.** A user-chosen password would
    move the security of the export onto a KDF `docs/encrypted-wallet-qr.md` has already said is
    not load-bearing, and the only enforcement that cannot be talked around later is the absence
    of the feature.

    `random_bytes` is the caller's randomness — the `EntropySource` port in the appliance.
    """
    word_count = _word_count_for(entropy)
    password = generate(random_bytes)
    container = _seal(
        entropy=entropy,
        word_count=word_count,
        password=password,
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

    header = container[:11]
    params = Argon2Params.parse(container[5:11])
    salt = container[11:27]
    nonce = container[27:39]
    sealed = container[39:]

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
    return DecodedWallet(entropy=plaintext[:entropy_length], word_count=word_count)


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
    salt: bytes,
    nonce: bytes,
    params: Argon2Params,
) -> bytes:
    if len(salt) != WALLET_QR_SALT_BYTES or len(nonce) != WALLET_QR_NONCE_BYTES:
        raise ValueError("salt or nonce is the wrong length")
    # Padded to a fixed 33 bytes so the container's size never states the word count.
    plaintext = entropy.ljust(WALLET_QR_PLAINTEXT_BYTES - 1, b"\x00") + bytes([word_count])
    header = WALLET_QR_MAGIC + bytes([WALLET_QR_VERSION]) + params.serialize()
    key = _derive_key(password, salt, params)
    sealed = ChaCha20Poly1305(key).encrypt(nonce, plaintext, header)
    container = header + salt + nonce + sealed
    if len(container) != WALLET_QR_TOTAL_BYTES:  # pragma: no cover - arithmetic, checked anyway
        raise ValueError("container is not 88 bytes")
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
