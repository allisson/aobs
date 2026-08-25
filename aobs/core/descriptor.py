"""Descriptor export: the account xpub, its origin and the master fingerprint.

Two forms of the same thing, and both are needed:

* **The text output descriptor** (`Wallet.descriptor`) — `research/xpub-export-formats` finding 1:
  the only format Sparrow, Green and Blue Wallet all accept.
* **`ur:crypto-output`** — the UR the appliance animates. The deprecated `crypto-*` spelling on
  purpose: only Sparrow accepts the post-2023 `output-descriptor` rename.

**BIP84 and BIP86 are separate URs.** Green's ur-c returns `URC_ETAPROOTNOTSUPPORTED` for the
taproot tag and rejects a `crypto-account` containing one *whole* — taking the BIP84 descriptor
down with it. Separate URs means Green's taproot gap costs the user taproot and nothing else.

No wallet name is ever included.
"""

from __future__ import annotations

from .urcodec import encode_single_part
from .vendor.ur2.cbor_lite import CBOREncoder, Tag_Major_semantic
from .wallet import RECEIVE_CHAIN, Network, ScriptType, Wallet

CRYPTO_OUTPUT_UR_TYPE = "crypto-output"

#: Blockchain Commons registry tags (BCR-2020-007, -010, -015).
_TAG_HDKEY = 303
_TAG_KEYPATH = 304
_TAG_COININFO = 305
_SCRIPT_EXPRESSION_TAG = {ScriptType.P2WPKH: 404, ScriptType.P2TR: 409}


def output_descriptor_ur(
    wallet: Wallet, script_type: ScriptType, *, chain: int = RECEIVE_CHAIN
) -> str:
    """One `ur:crypto-output`, single part, uppercased. Static, so it is rendered at ECC H."""
    return encode_single_part(
        CRYPTO_OUTPUT_UR_TYPE, _output_cbor(wallet, script_type, chain)
    )


def _output_cbor(wallet: Wallet, script_type: ScriptType, chain: int) -> bytearray:
    encoder = CBOREncoder()
    # The script expression wraps a tagged crypto-hdkey: `wpkh(303({…}))`.
    encoder.encodeTagAndValue(Tag_Major_semantic, _SCRIPT_EXPRESSION_TAG[script_type])
    encoder.encodeTagAndValue(Tag_Major_semantic, _TAG_HDKEY)
    _encode_hdkey(encoder, wallet, script_type, chain)
    return bytearray(encoder.get_bytes())


def _encode_hdkey(
    encoder: CBOREncoder, wallet: Wallet, script_type: ScriptType, chain: int
) -> None:
    account = wallet.account_key(script_type).to_public()
    encoder.encodeMapSize(6)

    encoder.encodeUnsigned(3)  # key-data
    encoder.encodeBytes(account.key.sec())

    encoder.encodeUnsigned(4)  # chain-code
    encoder.encodeBytes(account.chain_code)

    encoder.encodeUnsigned(5)  # use-info
    encoder.encodeTagAndValue(Tag_Major_semantic, _TAG_COININFO)
    encoder.encodeMapSize(2)
    encoder.encodeUnsigned(1)
    encoder.encodeUnsigned(0)  # coin type: bitcoin
    encoder.encodeUnsigned(2)
    # 1 is "testnet" in the registry, and it is all the registry has: nothing in any export
    # distinguishes testnet3, testnet4, signet and regtest. The network is receiver-side
    # configuration, here as everywhere else.
    encoder.encodeUnsigned(0 if wallet.network is Network.MAINNET else 1)

    encoder.encodeUnsigned(6)  # origin: the full path, and our master fingerprint
    encoder.encodeTagAndValue(Tag_Major_semantic, _TAG_KEYPATH)
    encoder.encodeMapSize(3)
    encoder.encodeUnsigned(1)
    encoder.encodeArraySize(6)
    for element in (script_type.purpose, wallet.network.coin_type, wallet.account):
        encoder.encodeUnsigned(element)
        encoder.encodeBool(True)
    encoder.encodeUnsigned(2)
    encoder.encodeUnsigned(int.from_bytes(wallet.fingerprint, "big"))
    encoder.encodeUnsigned(3)
    encoder.encodeUnsigned(3)  # depth: m/purpose'/coin'/account'

    encoder.encodeUnsigned(7)  # children: /<chain>/*
    encoder.encodeTagAndValue(Tag_Major_semantic, _TAG_KEYPATH)
    encoder.encodeMapSize(1)
    encoder.encodeUnsigned(1)
    encoder.encodeArraySize(4)
    encoder.encodeUnsigned(chain)
    encoder.encodeBool(False)
    encoder.encodeArraySize(0)  # the wildcard
    encoder.encodeBool(False)

    encoder.encodeUnsigned(8)  # parent fingerprint: the key one level up, m/purpose'/coin'
    encoder.encodeUnsigned(int.from_bytes(account.fingerprint, "big"))
