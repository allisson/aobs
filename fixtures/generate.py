#!/usr/bin/env python3
"""Generate every PSBT fixture from the published BIP39 test-vector mnemonic.

`docs/test-harness.md`: fixtures are generated artifacts committed next to the script, so a
reviewer regenerates and diffs rather than trusting a blob. Nothing here is ever a live wallet —
every key descends from the mnemonic printed in BIP39 itself.

Each fixture is two files in `fixtures/psbt/`:

    <name>.psbt   the bytes handed to `review()`
    <name>.json   what the appliance must say about them, declared here at construction time

The expectations are written from what this script *built*, never from what `review()` returns.
A corpus that records the reviewer's own output would assert nothing.

    uv run python fixtures/generate.py

Adding a refusal rule means adding a file here, and `tests/test_adversarial_corpus.py` picks it
up with no edit of its own.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from aobs.core.vendor.embit import script
from aobs.core.vendor.embit.psbt import SIGHASH, PSBT, DerivationPath
from aobs.core.vendor.embit.transaction import Transaction, TransactionInput, TransactionOutput

from aobs.core.wallet import CHANGE_CHAIN, RECEIVE_CHAIN, Network, ScriptType, Wallet

VECTOR_MNEMONIC = (
    "abandon abandon abandon abandon abandon abandon abandon abandon "
    "abandon abandon abandon about"
)

OUT_DIR = Path(__file__).parent / "psbt"

#: A stranger's address, used wherever a fixture needs an output that is genuinely not ours.
#: Derived from a second published vector mnemonic so it is public too.
STRANGER_MNEMONIC = (
    "legal winner thank year wave sausage worth useful legal winner thank yellow"
)


def wallet(network: Network = Network.SIGNET) -> Wallet:
    return Wallet.from_mnemonic(VECTOR_MNEMONIC, network=network)


def stranger(network: Network = Network.SIGNET) -> Wallet:
    return Wallet.from_mnemonic(STRANGER_MNEMONIC, network=network)


def fake_txid(tag: str) -> bytes:
    """A deterministic previous-output txid. The fixture's UTXOs live in `witness_utxo`, so no
    real previous transaction is needed and none is invented."""
    return hashlib.sha256(f"aobs-fixture/{tag}".encode()).digest()


def build(
    *,
    wallet: Wallet,
    inputs: list[dict],
    outputs: list[dict],
    version: int = 2,
    locktime: int = 0,
) -> PSBT:
    """Assemble a PSBT from a description of its inputs and outputs.

    An input is `{"chain", "index", "sats", "script_type"}` for one of ours, or `{"script",
    "sats"}` for a foreign one; optional `"sighash"`, `"omit_witness_utxo"` and
    `"omit_derivation"` produce the hostile cases.
    """
    vin = [
        TransactionInput(fake_txid(inp.get("tag", f"in{i}")), inp.get("vout", 0))
        for i, inp in enumerate(inputs)
    ]
    vout = [TransactionOutput(out["sats"], out["script"]) for out in outputs]
    psbt = PSBT(Transaction(version=version, vin=vin, vout=vout, locktime=locktime))

    for scope, spec in zip(psbt.inputs, inputs):
        script_pubkey = spec.get("script")
        if script_pubkey is None:
            script_pubkey = wallet.script_pubkey(
                spec["script_type"], spec["chain"], spec["index"]
            )
        if not spec.get("omit_witness_utxo"):
            scope.witness_utxo = TransactionOutput(spec["sats"], script_pubkey)
        if spec.get("sighash") is not None:
            scope.sighash_type = spec["sighash"]
        if "index" in spec and not spec.get("omit_derivation"):
            _claim(scope, wallet, spec["script_type"], spec["chain"], spec["index"])

    for scope, spec in zip(psbt.outputs, outputs):
        claim = spec.get("claim")
        if claim is not None:
            _claim(scope, wallet, claim["script_type"], claim["chain"], claim["index"])
        if spec.get("unknown"):
            # A fresh dict, never `scope.unknown[k] = v`: embit's scopes share one mutable
            # default, so mutating it in place leaks the field into every later PSBT.
            scope.unknown = dict(spec["unknown"])
    return psbt


def _claim(scope, wallet: Wallet, script_type: ScriptType, chain: int, index: int) -> None:
    """Write the PSBT's claim about a path. Claims are what the appliance checks, not what it
    believes, so a fixture is free to claim something untrue."""
    key = wallet.derive(script_type, chain, index).key.get_public_key()
    path = [
        0x80000000 + script_type.purpose,
        0x80000000 + wallet.network.coin_type,
        0x80000000 + wallet.account,
        chain,
        index,
    ]
    derivation = DerivationPath(wallet.fingerprint, path)
    if script_type is ScriptType.P2TR:
        scope.taproot_bip32_derivations[key] = ([], derivation)
    else:
        scope.bip32_derivations[key] = derivation


def write(name: str, psbt_bytes: bytes, meta: dict) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / f"{name}.psbt").write_bytes(psbt_bytes)
    meta = {"name": name, **meta}
    (OUT_DIR / f"{name}.json").write_text(json.dumps(meta, indent=2) + "\n")
    print(f"{name}: {len(psbt_bytes)} bytes")


# --- The fixtures --------------------------------------------------------------------------------


def honest_p2wpkh() -> None:
    w = wallet()
    payment = script.address_to_scriptpubkey("tb1qw508d6qejxtdg4y5r3zarvary0c5xw7kxpjzsx")
    psbt = build(
        wallet=w,
        inputs=[
            {"script_type": ScriptType.P2WPKH, "chain": RECEIVE_CHAIN, "index": 0, "sats": 1_200_000},
            {"script_type": ScriptType.P2WPKH, "chain": RECEIVE_CHAIN, "index": 2, "sats": 285_920},
        ],
        outputs=[
            {"sats": 1_400_000, "script": payment},
            {
                "sats": 82_500,
                "script": w.script_pubkey(ScriptType.P2WPKH, CHANGE_CHAIN, 0),
                "claim": {"script_type": ScriptType.P2WPKH, "chain": CHANGE_CHAIN, "index": 0},
            },
        ],
    )
    write(
        "honest_p2wpkh",
        psbt.serialize(),
        {
            "description": "A two-input BIP84 spend with one payment and one real change output.",
            "traces_to": "docs/psbt-review-model.md — the proof rule and the headline number",
            "network": "signet",
            "expected": {
                "refusal": None,
                "outputs": [
                    {"index": 0, "category": "payment", "sats": 1_400_000},
                    {"index": 1, "category": "change_proven", "sats": 82_500,
                     "proven_path": "m/84h/1h/0h/1/0"},
                ],
                "headline": {
                    "payments_sats": 1_400_000,
                    "fee_sats": 3_420,
                    "total_leaving_sats": 1_403_420,
                },
                "transaction_warnings": [],
            },
        },
    )


def honest_p2tr() -> None:
    w = wallet()
    payment = stranger().script_pubkey(ScriptType.P2TR, RECEIVE_CHAIN, 0)
    psbt = build(
        wallet=w,
        inputs=[
            {"script_type": ScriptType.P2TR, "chain": RECEIVE_CHAIN, "index": 0, "sats": 500_000},
        ],
        outputs=[
            {"sats": 300_000, "script": payment},
            {
                "sats": 199_600,
                "script": w.script_pubkey(ScriptType.P2TR, CHANGE_CHAIN, 0),
                "claim": {"script_type": ScriptType.P2TR, "chain": CHANGE_CHAIN, "index": 0},
            },
        ],
    )
    write(
        "honest_p2tr",
        psbt.serialize(),
        {
            "description": "A BIP86 key-path spend, every input carrying its witness_utxo.",
            "traces_to": "docs/psbt-review-model.md — taproot",
            "network": "signet",
            "expected": {
                "refusal": None,
                "outputs": [
                    {"index": 0, "category": "payment", "sats": 300_000},
                    {"index": 1, "category": "change_proven", "sats": 199_600,
                     "proven_path": "m/86h/1h/0h/1/0"},
                ],
                "headline": {
                    "payments_sats": 300_000,
                    "fee_sats": 400,
                    "total_leaving_sats": 300_400,
                },
                "transaction_warnings": [],
            },
        },
    )


def honest_mainnet() -> None:
    """Mainnet review behaviour is exactly what needs testing, and the vector mnemonic is public,
    so this is a mainnet fixture that is not a live wallet."""
    w = wallet(Network.MAINNET)
    payment = script.address_to_scriptpubkey("bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4")
    psbt = build(
        wallet=w,
        inputs=[
            {"script_type": ScriptType.P2WPKH, "chain": RECEIVE_CHAIN, "index": 1, "sats": 2_000_000},
        ],
        outputs=[
            {"sats": 1_000_000, "script": payment},
            {
                "sats": 999_000,
                "script": w.script_pubkey(ScriptType.P2WPKH, CHANGE_CHAIN, 1),
                "claim": {"script_type": ScriptType.P2WPKH, "chain": CHANGE_CHAIN, "index": 1},
            },
        ],
    )
    write(
        "honest_mainnet",
        psbt.serialize(),
        {
            "description": "The same review on mainnet, from the same published mnemonic.",
            "traces_to": "docs/test-harness.md — mainnet fixtures, vector mnemonic only",
            "network": "mainnet",
            "expected": {
                "refusal": None,
                "outputs": [
                    {"index": 0, "category": "payment", "sats": 1_000_000},
                    {"index": 1, "category": "change_proven", "sats": 999_000,
                     "proven_path": "m/84h/0h/0h/1/1"},
                ],
                "headline": {
                    "payments_sats": 1_000_000,
                    "fee_sats": 1_000,
                    "total_leaving_sats": 1_001_000,
                },
                "transaction_warnings": [],
            },
        },
    )


def change_address_attack() -> None:
    """The Tier 1 attack, made executable: an output that claims one of our change paths while
    paying a script we cannot reproduce."""
    w = wallet()
    attacker = stranger().script_pubkey(ScriptType.P2WPKH, RECEIVE_CHAIN, 0)
    psbt = build(
        wallet=w,
        inputs=[
            {"script_type": ScriptType.P2WPKH, "chain": RECEIVE_CHAIN, "index": 0, "sats": 1_200_000},
        ],
        outputs=[
            {"sats": 200_000, "script": script.address_to_scriptpubkey(
                "tb1qw508d6qejxtdg4y5r3zarvary0c5xw7kxpjzsx")},
            {
                "sats": 995_000,
                "script": attacker,
                # The lie: a claim on our own change path over someone else's script.
                "claim": {"script_type": ScriptType.P2WPKH, "chain": CHANGE_CHAIN, "index": 0},
            },
        ],
    )
    write(
        "change_address_attack",
        psbt.serialize(),
        {
            "description": (
                "PSBT_OUT_BIP32_DERIVATION claims m/84h/1h/0h/1/0 on an output whose script is a "
                "stranger's. The claim must not be the answer."
            ),
            "traces_to": "docs/psbt-review-model.md — the proof rule, output categories",
            "network": "signet",
            "expected": {
                "refusal": None,
                "outputs": [
                    {"index": 0, "category": "payment", "sats": 200_000},
                    {"index": 1, "category": "not_proven", "sats": 995_000,
                     "claimed_path": "m/84h/1h/0h/1/0"},
                ],
                # The whole point: the fake change is counted as leaving, so it raises the
                # headline number rather than hiding inside it.
                "headline": {
                    "payments_sats": 1_195_000,
                    "fee_sats": 5_000,
                    "total_leaving_sats": 1_200_000,
                },
                "output_warnings": {"1": ["output_not_proven"]},
                "transaction_warnings": ["whole_balance_spend"],
            },
        },
    )


def change_index_out_of_window() -> None:
    """Genuinely our change, at an index the window does not reach. NOT PROVEN is the safe
    direction — the attacker never chooses the window."""
    w = wallet()
    psbt = build(
        wallet=w,
        inputs=[
            {"script_type": ScriptType.P2WPKH, "chain": RECEIVE_CHAIN, "index": 0, "sats": 1_000_000},
        ],
        outputs=[
            {"sats": 400_000, "script": script.address_to_scriptpubkey(
                "tb1qw508d6qejxtdg4y5r3zarvary0c5xw7kxpjzsx")},
            {
                "sats": 599_000,
                "script": w.script_pubkey(ScriptType.P2WPKH, CHANGE_CHAIN, 500),
                "claim": {"script_type": ScriptType.P2WPKH, "chain": CHANGE_CHAIN, "index": 500},
            },
        ],
    )
    write(
        "change_index_out_of_window",
        psbt.serialize(),
        {
            "description": "Our own change at index 500, past the ceiling of 200.",
            "traces_to": "docs/psbt-review-model.md — the derivation window",
            "network": "signet",
            "expected": {
                "refusal": None,
                "outputs": [
                    {"index": 0, "category": "payment", "sats": 400_000},
                    {"index": 1, "category": "not_proven", "sats": 599_000,
                     "claimed_path": "m/84h/1h/0h/1/500"},
                ],
                "headline": {
                    "payments_sats": 999_000,
                    "fee_sats": 1_000,
                    "total_leaving_sats": 1_000_000,
                },
                "output_warnings": {"1": ["output_not_proven"]},
                "transaction_warnings": ["whole_balance_spend"],
            },
        },
    )


def taproot_missing_witness_utxo() -> None:
    w = wallet()
    psbt = build(
        wallet=w,
        inputs=[
            {"script_type": ScriptType.P2TR, "chain": RECEIVE_CHAIN, "index": 0, "sats": 500_000},
            {"script_type": ScriptType.P2TR, "chain": RECEIVE_CHAIN, "index": 1, "sats": 500_000,
             "omit_witness_utxo": True},
        ],
        outputs=[
            {"sats": 900_000, "script": stranger().script_pubkey(
                ScriptType.P2TR, RECEIVE_CHAIN, 0)},
            {
                "sats": 99_000,
                "script": w.script_pubkey(ScriptType.P2TR, CHANGE_CHAIN, 0),
                "claim": {"script_type": ScriptType.P2TR, "chain": CHANGE_CHAIN, "index": 0},
            },
        ],
    )
    write(
        "taproot_missing_witness_utxo",
        psbt.serialize(),
        {
            "description": (
                "One taproot input has no witness_utxo. The sighash commits to every input's "
                "amount and script, so this cannot be signed and the fee is unknown."
            ),
            "traces_to": "docs/psbt-review-model.md — what blocks signing, taproot",
            "network": "signet",
            "expected": {"refusal": {"reason": "missing_utxo", "input_index": 1}},
        },
    )


def sighash_not_all() -> None:
    w = wallet()
    psbt = build(
        wallet=w,
        inputs=[
            {"script_type": ScriptType.P2WPKH, "chain": RECEIVE_CHAIN, "index": 0, "sats": 400_000},
            {"script_type": ScriptType.P2WPKH, "chain": RECEIVE_CHAIN, "index": 1, "sats": 400_000,
             "sighash": SIGHASH.SINGLE},
            {"script_type": ScriptType.P2WPKH, "chain": RECEIVE_CHAIN, "index": 2, "sats": 400_000},
        ],
        outputs=[
            {"sats": 1_190_000, "script": script.address_to_scriptpubkey(
                "tb1qw508d6qejxtdg4y5r3zarvary0c5xw7kxpjzsx")},
        ],
    )
    write(
        "sighash_not_all",
        psbt.serialize(),
        {
            "description": "SIGHASH_SINGLE on the second of three inputs.",
            "traces_to": "docs/psbt-review-model.md — what blocks signing",
            "network": "signet",
            "expected": {"refusal": {"reason": "sighash_not_all", "input_index": 1}},
        },
    )


def network_mismatch() -> None:
    """Built for mainnet, presented to the signet wallet."""
    w = wallet(Network.MAINNET)
    psbt = build(
        wallet=w,
        inputs=[
            {"script_type": ScriptType.P2WPKH, "chain": RECEIVE_CHAIN, "index": 0, "sats": 1_000_000},
        ],
        outputs=[
            {"sats": 999_000, "script": script.address_to_scriptpubkey(
                "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4")},
        ],
    )
    write(
        "network_mismatch",
        psbt.serialize(),
        {
            "description": "A mainnet PSBT — coin type 0h — reviewed by a signet wallet.",
            "traces_to": "docs/psbt-review-model.md — what blocks signing",
            "network": "signet",
            "expected": {"refusal": {"reason": "network_mismatch", "input_index": None}},
        },
    )


def foreign_input() -> None:
    w = wallet()
    psbt = build(
        wallet=w,
        inputs=[
            {"script_type": ScriptType.P2WPKH, "chain": RECEIVE_CHAIN, "index": 0, "sats": 500_000},
            {"script": stranger().script_pubkey(ScriptType.P2WPKH, RECEIVE_CHAIN, 3),
             "sats": 500_000},
        ],
        outputs=[
            {"sats": 995_000, "script": script.address_to_scriptpubkey(
                "tb1qw508d6qejxtdg4y5r3zarvary0c5xw7kxpjzsx")},
        ],
    )
    write(
        "foreign_input",
        psbt.serialize(),
        {
            "description": "An input this appliance cannot sign. Sign nothing rather than partly.",
            "traces_to": "docs/psbt-review-model.md — what blocks signing",
            "network": "signet",
            "expected": {"refusal": {"reason": "unsignable_input", "input_index": 1}},
        },
    )


def ansi_escape_label() -> None:
    """Attacker-controlled text arriving in a PSBT field, carrying terminal escapes."""
    w = wallet()
    hostile = b"\x1b[2J\x1b[31mPAY THIS INSTEAD\x1b[0m\x07"
    psbt = build(
        wallet=w,
        inputs=[
            {"script_type": ScriptType.P2WPKH, "chain": RECEIVE_CHAIN, "index": 0, "sats": 500_000},
        ],
        outputs=[
            {
                "sats": 495_000,
                "script": script.address_to_scriptpubkey(
                    "tb1qw508d6qejxtdg4y5r3zarvary0c5xw7kxpjzsx"),
                "unknown": {b"\xfc\x04aobs": hostile},
            },
        ],
    )
    write(
        "ansi_escape_label",
        psbt.serialize(),
        {
            "description": (
                "An output carrying ANSI escapes in a proprietary field. The core exposes no "
                "such field, and anything it does expose renders inert."
            ),
            "traces_to": "docs/test-harness.md — the escape-injection rule",
            "network": "signet",
            "expected": {
                "refusal": None,
                "outputs": [{"index": 0, "category": "payment", "sats": 495_000}],
                "headline": {
                    "payments_sats": 495_000,
                    "fee_sats": 5_000,
                    "total_leaving_sats": 500_000,
                },
                "no_control_characters": True,
                "transaction_warnings": ["whole_balance_spend"],
            },
        },
    )


def many_inputs() -> None:
    """Twenty inputs: what a many-input spend does to PSBT size, and so to frame count."""
    w = wallet()
    psbt = build(
        wallet=w,
        inputs=[
            {"script_type": ScriptType.P2TR, "chain": RECEIVE_CHAIN, "index": i,
             "sats": 100_000, "tag": f"many{i}"}
            for i in range(20)
        ],
        outputs=[
            {"sats": 1_500_000, "script": stranger().script_pubkey(
                ScriptType.P2TR, RECEIVE_CHAIN, 0)},
            {
                "sats": 495_000,
                "script": w.script_pubkey(ScriptType.P2TR, CHANGE_CHAIN, 19),
                "claim": {"script_type": ScriptType.P2TR, "chain": CHANGE_CHAIN, "index": 19},
            },
        ],
    )
    write(
        "many_inputs",
        psbt.serialize(),
        {
            "description": "Twenty taproot inputs, each carrying its own witness_utxo.",
            "traces_to": "docs/qr-emit-parameters.md — frame count grows with input count",
            "network": "signet",
            "expected": {
                "refusal": None,
                "outputs": [
                    {"index": 0, "category": "payment", "sats": 1_500_000},
                    {"index": 1, "category": "change_proven", "sats": 495_000,
                     "proven_path": "m/86h/1h/0h/1/19"},
                ],
                "headline": {
                    "payments_sats": 1_500_000,
                    "fee_sats": 5_000,
                    "total_leaving_sats": 1_505_000,
                },
                "transaction_warnings": [],
            },
        },
    )


def malformed() -> None:
    """Structurally malformed bytes: a dead end, never a guess."""
    w = wallet()
    good = build(
        wallet=w,
        inputs=[
            {"script_type": ScriptType.P2WPKH, "chain": RECEIVE_CHAIN, "index": 0, "sats": 500_000},
        ],
        outputs=[
            {"sats": 495_000, "script": script.address_to_scriptpubkey(
                "tb1qw508d6qejxtdg4y5r3zarvary0c5xw7kxpjzsx")},
        ],
    ).serialize()
    write(
        "malformed",
        good[: len(good) // 2],
        {
            "description": "A PSBT truncated mid-map.",
            "traces_to": "docs/psbt-review-model.md — what blocks signing",
            "network": "signet",
            "expected": {"refusal": {"reason": "malformed", "input_index": None}},
        },
    )


def fee_absurd() -> None:
    w = wallet()
    psbt = build(
        wallet=w,
        inputs=[
            {"script_type": ScriptType.P2WPKH, "chain": RECEIVE_CHAIN, "index": 0, "sats": 1_000_000},
        ],
        outputs=[
            {"sats": 500_000, "script": script.address_to_scriptpubkey(
                "tb1qw508d6qejxtdg4y5r3zarvary0c5xw7kxpjzsx")},
            {
                "sats": 100_000,
                "script": w.script_pubkey(ScriptType.P2WPKH, CHANGE_CHAIN, 0),
                "claim": {"script_type": ScriptType.P2WPKH, "chain": CHANGE_CHAIN, "index": 0},
            },
        ],
    )
    write(
        "fee_absurd",
        psbt.serialize(),
        {
            "description": "400 000 sats of fee on a 500 000 sat payment. A warning, not a refusal.",
            "traces_to": "docs/psbt-review-model.md — what warns",
            "network": "signet",
            "expected": {
                "refusal": None,
                "outputs": [
                    {"index": 0, "category": "payment", "sats": 500_000},
                    {"index": 1, "category": "change_proven", "sats": 100_000,
                     "proven_path": "m/84h/1h/0h/1/0"},
                ],
                "headline": {
                    "payments_sats": 500_000,
                    "fee_sats": 400_000,
                    "total_leaving_sats": 900_000,
                },
                "transaction_warnings": ["fee_above_threshold"],
            },
        },
    )


def input_past_the_ceiling() -> None:
    """A long-used wallet spending its own UTXO at index 500.

    The derivation window bounds what may be believed to be *change*; an input is proven the same
    way but without that bound, because refusing to recognise an honest wallet's own UTXO would be
    a hard refusal on a legitimate transaction. The claim still proves nothing on its own — the
    script is reproduced from the claimed path before the input counts as ours.
    """
    w = wallet()
    psbt = build(
        wallet=w,
        inputs=[
            {"script_type": ScriptType.P2WPKH, "chain": RECEIVE_CHAIN, "index": 500,
             "sats": 900_000},
        ],
        outputs=[
            {"sats": 895_000, "script": script.address_to_scriptpubkey(
                "tb1qw508d6qejxtdg4y5r3zarvary0c5xw7kxpjzsx")},
        ],
    )
    write(
        "input_past_the_ceiling",
        psbt.serialize(),
        {
            "description": "One input at m/84h/1h/0h/0/500, past the window's ceiling of 200.",
            "traces_to": "docs/psbt-review-model.md — the derivation window, what blocks signing",
            "network": "signet",
            "expected": {
                "refusal": None,
                "outputs": [{"index": 0, "category": "payment", "sats": 895_000}],
                "headline": {
                    "payments_sats": 895_000,
                    "fee_sats": 5_000,
                    "total_leaving_sats": 900_000,
                },
                "transaction_warnings": ["whole_balance_spend"],
            },
        },
    )


def network_mismatch_foreign_fingerprint() -> None:
    """A mainnet PSBT whose derivations belong to someone else's master key.

    The network a PSBT was built for is stated by its coin type whoever signed the claim, so the
    refusal does not depend on the attacker choosing to name our fingerprint.
    """
    other = stranger(Network.MAINNET)
    psbt = build(
        wallet=other,
        inputs=[
            {"script_type": ScriptType.P2WPKH, "chain": RECEIVE_CHAIN, "index": 0,
             "sats": 1_000_000},
        ],
        outputs=[
            {"sats": 999_000, "script": script.address_to_scriptpubkey(
                "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4")},
        ],
    )
    write(
        "network_mismatch_foreign_fingerprint",
        psbt.serialize(),
        {
            "description": "Coin type 0h under a fingerprint that is not ours, on a signet wallet.",
            "traces_to": "docs/psbt-review-model.md — what blocks signing",
            "network": "signet",
            "expected": {"refusal": {"reason": "network_mismatch", "input_index": None}},
        },
    )


FIXTURES = [
    honest_p2wpkh,
    honest_p2tr,
    honest_mainnet,
    change_address_attack,
    change_index_out_of_window,
    taproot_missing_witness_utxo,
    sighash_not_all,
    network_mismatch,
    foreign_input,
    ansi_escape_label,
    many_inputs,
    malformed,
    fee_absurd,
    input_past_the_ceiling,
    network_mismatch_foreign_fingerprint,
]


def main() -> None:
    for fixture in FIXTURES:
        fixture()


if __name__ == "__main__":
    main()
