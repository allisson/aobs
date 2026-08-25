"""End to end against a real validator. Opt-in, outside the default loop.

    uv run pytest -m regtest

Fixture round-tripping cannot tell you a signature is *valid*. A wrong sighash produces a
perfectly well-formed signature that every appliance-side check accepts and only a validator
rejects — and BIP86 taproot is exactly where that happens, because the sighash commits to all
input amounts and scripts. This suite is the only instrument in the harness that catches it.

`walletcreatefundedpsbt` builds it, the core signs it, `finalizepsbt` and `testmempoolaccept`
judge it. Not broadcast-and-confirm: mempool acceptance asserts the same thing without generating
blocks for it.

It needs a `bitcoind` in regtest mode and `bitcoin-cli` on the path. A contributor with no node
still gets the full default suite, which is the point of it being opt-in.
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import uuid

import pytest

from aobs.core.review import review
from aobs.core.signing import sign
from aobs.core.wallet import Network, ScriptType, Wallet

pytestmark = pytest.mark.regtest

VECTOR_MNEMONIC = (
    "abandon abandon abandon abandon abandon abandon abandon abandon "
    "abandon abandon abandon about"
)

CLI = os.environ.get("BITCOIN_CLI", "bitcoin-cli")
CLI_ARGS = os.environ.get("BITCOIN_CLI_ARGS", "-regtest").split()


def cli(*args: str, wallet: str | None = None) -> str:
    command = [CLI, *CLI_ARGS]
    if wallet:
        command.append(f"-rpcwallet={wallet}")
    command += [str(arg) for arg in args]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise AssertionError(f"{' '.join(command)}\n{result.stderr.strip()}")
    return result.stdout.strip()


def rpc(*args: str, wallet: str | None = None):
    out = cli(*args, wallet=wallet)
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return out


@pytest.fixture(scope="module", autouse=True)
def node_available() -> None:
    if shutil.which(CLI) is None:
        pytest.skip(f"{CLI} is not on the path")
    try:
        cli("getblockchaininfo")
    except AssertionError as failure:  # pragma: no cover - environment, not logic
        pytest.skip(f"no regtest node: {failure}")


@pytest.fixture(scope="module")
def miner() -> str:
    name = f"aobs-miner-{uuid.uuid4().hex[:8]}"
    cli("createwallet", name)
    address = rpc("getnewaddress", wallet=name)
    cli("generatetoaddress", "101", address, wallet=name)
    return name


def watch_only(wallet: Wallet, script_type: ScriptType) -> str:
    """Import our descriptors into a watch-only wallet — the coordinator, played by Core."""
    name = f"aobs-watch-{script_type.value}-{uuid.uuid4().hex[:8]}"
    cli("createwallet", name, "true", "true", "", "false", "true")  # disable_private_keys
    requests = [
        {
            "desc": wallet.descriptor(script_type, chain=chain),
            "active": True,
            "internal": chain == 1,
            "timestamp": "now",
        }
        for chain in (0, 1)
    ]
    result = rpc("importdescriptors", json.dumps(requests), wallet=name)
    assert all(entry["success"] for entry in result), result
    return name


@pytest.mark.parametrize("script_type", list(ScriptType))
def test_a_signature_from_the_core_is_accepted_by_the_mempool(
    miner: str, script_type: ScriptType
) -> None:
    wallet = Wallet.from_mnemonic(VECTOR_MNEMONIC, network=Network.REGTEST)
    watcher = watch_only(wallet, script_type)

    # Fund two of our own addresses, so the spend has more than one input to commit to.
    for index in range(2):
        cli("sendtoaddress", wallet.address(script_type, 0, index), "1.0", wallet=miner)
    cli("generatetoaddress", "1", rpc("getnewaddress", wallet=miner), wallet=miner)

    destination = rpc("getnewaddress", wallet=miner)
    funded = rpc(
        "walletcreatefundedpsbt",
        "[]",
        json.dumps([{destination: 1.5}]),
        "0",
        json.dumps({"includeWatching": True, "changeAddress": wallet.address(script_type, 1, 0)}),
        wallet=watcher,
    )
    psbt_bytes = base64.b64decode(funded["psbt"])

    reviewed = review(psbt_bytes, wallet)
    assert reviewed.signable, reviewed.refusal
    assert any(out.category.value == "change_proven" for out in reviewed.outputs)

    signed = sign(psbt_bytes, wallet)
    finalised = rpc(
        "finalizepsbt", base64.b64encode(signed).decode(), wallet=watcher
    )
    assert finalised["complete"], finalised

    accepted = rpc("testmempoolaccept", json.dumps([finalised["hex"]]), wallet=watcher)
    assert accepted[0]["allowed"], accepted
