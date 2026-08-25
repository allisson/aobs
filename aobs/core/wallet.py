"""The wallet: derivation, addresses and descriptor export.

Single-sig, BIP84 (P2WPKH) and BIP86 (P2TR key-path) only, account 0. Everything the rest of the
core knows about "ours" comes from here — never from a field a PSBT asserts.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from embit import bip32, bip39, script
from embit.networks import NETWORKS

#: The bech32 data charset (BIP173). Read to take a witness version off an address; the encoding
#: itself is embit's.
BECH32_CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"

RECEIVE_CHAIN = 0
CHANGE_CHAIN = 1


class Network(str, Enum):
    """The four networks in scope. testnet3 is ruled out on the map."""

    MAINNET = "mainnet"
    TESTNET4 = "testnet4"
    SIGNET = "signet"
    REGTEST = "regtest"

    @property
    def embit(self) -> dict:
        return NETWORKS[_EMBIT_KEY[self]]

    @property
    def hrp(self) -> str:
        """The bech32 human-readable part. Note it does not identify the network on its own:
        testnet4 and signet share `tb`, which is why an address prefix answers *which family*
        and the wallet answers *which network*."""
        return self.embit["bech32"]

    @property
    def coin_type(self) -> int:
        return 0 if self is Network.MAINNET else 1


_EMBIT_KEY = {
    Network.MAINNET: "main",
    # testnet4 shares testnet3's version bytes, HRP and coin type: no export distinguishes them
    # (research/xpub-export-formats, finding 6). The network is our configuration, not the bytes'.
    Network.TESTNET4: "test",
    Network.SIGNET: "signet",
    Network.REGTEST: "regtest",
}

#: Networks that share an address family. A `tb1…` address is ambiguous between testnet4 and
#: signet, so wrong-network detection compares the HRP, not the network name.
_HRP_TO_NETWORKS: dict[str, set[Network]] = {}
for _n in Network:
    _HRP_TO_NETWORKS.setdefault(_n.hrp, set()).add(_n)


class ScriptType(str, Enum):
    """The two script types in scope. BIP44 and BIP49 are ruled out on the map."""

    P2WPKH = "p2wpkh"  # BIP84
    P2TR = "p2tr"  # BIP86 key-path

    @property
    def purpose(self) -> int:
        return 84 if self is ScriptType.P2WPKH else 86

    @property
    def descriptor_function(self) -> str:
        return "wpkh" if self is ScriptType.P2WPKH else "tr"

    @property
    def witness_version(self) -> int:
        return 0 if self is ScriptType.P2WPKH else 1


def script_type_from_address(address: str) -> ScriptType | None:
    """The script type a bech32 address states in its own witness version.

    `docs/address-verification.md`: the prefix already says which, so there is no toggle to set
    wrong. Returns None for an address this appliance has no script type for at all.
    """
    body = address.strip().lower()
    if "1" not in body:
        return None
    data = body.rsplit("1", 1)[1]
    if not data:
        return None
    if data[0] not in BECH32_CHARSET:
        return None
    version = BECH32_CHARSET.index(data[0])
    for script_type in ScriptType:
        if script_type.witness_version == version:
            return script_type
    return None


def networks_for_address(address: str) -> set[Network]:
    """Which networks an address's HRP could belong to; empty if none of ours."""
    body = address.strip().lower()
    if "1" not in body:
        return set()
    hrp = body.rsplit("1", 1)[0]
    return set(_HRP_TO_NETWORKS.get(hrp, ()))


@dataclass(frozen=True)
class Wallet:
    """A wallet for one session.

    Holds the root key, so nothing here is printed: `__repr__` is overridden below and no field
    of this object may ever reach a screen, a log or an exception message
    (`docs/secret-hygiene.md`).
    """

    root: bip32.HDKey
    network: Network
    has_passphrase: bool = False
    account: int = 0

    # -- construction -------------------------------------------------------------------------

    @classmethod
    def from_mnemonic(
        cls,
        mnemonic: str,
        *,
        network: Network,
        passphrase: str = "",
        account: int = 0,
    ) -> Wallet:
        seed = bip39.mnemonic_to_seed(mnemonic, password=passphrase)
        root = bip32.HDKey.from_seed(seed, version=network.embit["xprv"])
        return cls(
            root=root,
            network=network,
            has_passphrase=bool(passphrase),
            account=account,
        )

    @classmethod
    def from_entropy(
        cls,
        entropy: bytes,
        *,
        network: Network,
        passphrase: str = "",
        account: int = 0,
    ) -> Wallet:
        return cls.from_mnemonic(
            bip39.mnemonic_from_bytes(entropy),
            network=network,
            passphrase=passphrase,
            account=account,
        )

    # -- identity -----------------------------------------------------------------------------

    @property
    def fingerprint(self) -> bytes:
        return self.root.my_fingerprint

    @property
    def fingerprint_hex(self) -> str:
        return self.fingerprint.hex()

    def __repr__(self) -> str:  # pragma: no cover - trivial, but load-bearing
        return f"<Wallet {self.network.value} {self.fingerprint_hex}>"

    __str__ = __repr__

    # -- derivation ---------------------------------------------------------------------------

    def account_path(self, script_type: ScriptType) -> str:
        return f"m/{script_type.purpose}h/{self.network.coin_type}h/{self.account}h"

    def path(self, script_type: ScriptType, chain: int, index: int) -> str:
        return f"{self.account_path(script_type)}/{chain}/{index}"

    def account_key(self, script_type: ScriptType) -> bip32.HDKey:
        return self.root.derive(self.account_path(script_type))

    def account_xpub(self, script_type: ScriptType) -> str:
        return self.account_key(script_type).to_public().to_base58(
            version=self.network.embit["xpub"]
        )

    def derive(self, script_type: ScriptType, chain: int, index: int) -> bip32.HDKey:
        return self.root.derive(self.path(script_type, chain, index))

    def script_pubkey(self, script_type: ScriptType, chain: int, index: int) -> script.Script:
        key = self.derive(script_type, chain, index).key
        if script_type is ScriptType.P2WPKH:
            return script.p2wpkh(key)
        return script.p2tr(key)

    def address(self, script_type: ScriptType, chain: int, index: int) -> str:
        return self.script_pubkey(script_type, chain, index).address(self.network.embit)

    # -- descriptor export --------------------------------------------------------------------

    def descriptor(self, script_type: ScriptType, chain: int = RECEIVE_CHAIN) -> str:
        """The text output descriptor, with checksum.

        `research/xpub-export-formats` finding 1: this is the one format Sparrow, Green and Blue
        Wallet all accept. No wallet name is ever included.
        """
        origin = self.account_path(script_type).removeprefix("m/")
        inner = (
            f"[{self.fingerprint_hex}/{origin}]{self.account_xpub(script_type)}/{chain}/*"
        )
        body = f"{script_type.descriptor_function}({inner})"
        return f"{body}#{descriptor_checksum(body)}"


# BIP380's descriptor checksum, transcribed from the BIP's own reference implementation.
_CHECKSUM_CHARSET = BECH32_CHARSET
_CHECKSUM_INPUT_CHARSET = (
    "0123456789()[],'/*abcdefgh@:$%{}"
    "IJKLMNOPQRSTUVWXYZ&+-.;<=>?!^_|~"
    "ijklmnopqrstuvwxyzABCDEFGH`#\"\\ "
)


def _polymod(c: int, val: int) -> int:
    c0 = c >> 35
    c = ((c & 0x7FFFFFFFF) << 5) ^ val
    if c0 & 1:
        c ^= 0xF5DEE51989
    if c0 & 2:
        c ^= 0xA9FDCA3312
    if c0 & 4:
        c ^= 0x1BAB10E32D
    if c0 & 8:
        c ^= 0x3706B1677A
    if c0 & 16:
        c ^= 0x644D626FFD
    return c


def descriptor_checksum(descriptor: str) -> str:
    c = 1
    cls = 0
    clscount = 0
    for ch in descriptor:
        pos = _CHECKSUM_INPUT_CHARSET.find(ch)
        if pos == -1:
            raise ValueError("character outside the descriptor charset")
        c = _polymod(c, pos & 31)
        cls = cls * 3 + (pos >> 5)
        clscount += 1
        if clscount == 3:
            c = _polymod(c, cls)
            cls = 0
            clscount = 0
    if clscount > 0:
        c = _polymod(c, cls)
    for _ in range(8):
        c = _polymod(c, 0)
    c ^= 1
    return "".join(_CHECKSUM_CHARSET[(c >> (5 * (7 - i))) & 31] for i in range(8))
