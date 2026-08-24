"""PROTOTYPE — throwaway. Shared fixture for the three UI-surface stubs (wayfinder #3).

Not production code. No tests, no error handling, no abstractions.

Addresses are derived from the published BIP39 test vector mnemonic on **signet**
(m/84'/1'/0'), so nothing here is ever a live mainnet wallet.
"""

from embit import bip32, bip39, script
from embit.networks import NETWORKS

MNEMONIC = "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about"
NET = NETWORKS["signet"]


def _addresses(n, change=False):
    seed = bip39.mnemonic_to_seed(MNEMONIC)
    root = bip32.HDKey.from_seed(seed, version=NET["xprv"])
    acct = root.derive("m/84h/1h/0h")
    branch = 1 if change else 0
    return [
        script.p2wpkh(acct.derive(f"m/{branch}/{i}").key).address(NET)
        for i in range(n)
    ]


_recv = _addresses(3)
_change = _addresses(1, change=True)

# The review screen: what the appliance shows before it will sign anything.
# Every field here is what the appliance DERIVED, never what the PSBT labelled.
REVIEW = {
    "network": "signet",
    "fingerprint": "73c5da0a",
    "spending_total_sats": 1_482_500,
    "fee_sats": 3_420,
    "fee_rate": "12.4 sat/vB",
    "vsize": 276,
    "inputs": [
        {"txid": "9f2c8b1e4a7d0c3f5b8e2a1d6c9f4b7e0a3d6c9f2b5e8a1d4c7f0b3e6a9d2c5f", "vout": 1, "sats": 1_200_000, "derivation": "m/84'/1'/0'/0/0", "address": _recv[0]},
        {"txid": "3e7a1d4c9f2b6e8a0d3c6f9b2e5a8d1c4f7b0e3a6d9c2f5b8e1a4d7c0f3b6e9a", "vout": 0, "sats": 285_920, "derivation": "m/84'/1'/0'/0/2", "address": _recv[2]},
    ],
    "outputs": [
        {
            "kind": "payment",
            "address": "tb1qw508d6qejxtdg4y5r3zarvary0c5xw7kxpjzsx",
            "sats": 1_400_000,
            "note": None,
        },
        {
            "kind": "change",
            "address": _change[0],
            "sats": 82_500,
            # Load-bearing: change is proven from the appliance's own derivation,
            # never from what the PSBT labelled as change.
            "note": "verified from our own derivation m/84'/1'/0'/1/0",
        },
    ],
    "warnings": [
        "Output 1 pays an address this wallet has never seen. Check it against the recipient.",
    ],
}

# A signed 2-in/2-out segwit PSBT is roughly 1.2–1.6 KB of base64. This stands in for
# one frame of that: realistic density is the whole point of the scannability test.
QR_PAYLOAD = (
    "UR:CRYPTO-PSBT/1-3/LPADAXCFADWKCYVDHDYNZTHDCXHKAOHDHNJKJNIHJTJYINJLJTCXJPJZINJKKKCXHSJZJYJP"
    "INHSJTCXHKAOAEAEAEAEAEADCYWKBWZMHDCXHKAOHDHNJKJNIHJTJYINJLJTCXJPJZINJKKKCXHSJZJYJPINHSJTCXHK"
    "AOAEAEAEAEADCYWKBWZMJKJNIHJTJYINJLJTCXJPJZINJKKKCXHSJZJYJPINHSJTCXHKAOAEAEAEAEADCYWKBWZMHDCX"
    "HKAOHDHNJKJNIHJTJYINJLJTCXJPJZINJKKKCXHSJZJYJPINHSJTCXHKAOAEAEAEAEADCYWKBWZMHDCXHKAOHDHNJKJN"
    "IHJTJYINJLJTCXJPJZINJKKKCXHSJZJYJPINHSJTCXHKAOAEAEAEAEADCYWKBWZMLPADAXCFADWKCYVDHDYNZTHDCXHK"
    "AOHDHNJKJNIHJTJYINJLJTCXJPJZINJKKKCXHSJZJYJPINHSJTCXHKAOAEAEAEAEADCYWKBWZMHDCXHKAOHDHNJKJNIH"
    "JTJYINJLJTCXJPJZINJKKKCXHSJZJYJPINHSJTCXHKAOAEAEAEAEADCYWKBWZMJKJNIHJTJYINJLJTCXJPJZINJKKKCX"
    "HSJZJYJPINHSJTCXHKAOAEAEAEAEADCYWKBWZMHDCXHKAOHDHNJKJNIHJTJYINJLJTCXJPJZINJKKKAEAEAEADCYWKBW"
)


def qr_matrix(payload=QR_PAYLOAD):
    """Return the QR as a list of rows of bools (True = dark module), plus its size."""
    import segno

    qr = segno.make(payload, error="l")
    rows = [list(r) for r in qr.matrix]
    return rows, len(rows), qr.version


def sats(n):
    return f"{n:,}".replace(",", " ")


def btc(n):
    return f"{n / 1e8:.8f}"
