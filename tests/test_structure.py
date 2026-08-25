"""Tests of the repository rather than of a module.

The seam, the import closure and the fixture allow-list are all rules that decay silently. Left
to memory, the first session that puts I/O inside the core destroys the seam before anyone
notices; left to CI, the change fails here.
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from aobs.core.vendor.embit.psbt import PSBT

ROOT = Path(__file__).parent.parent
CORE = ROOT / "aobs" / "core"
CORPUS = ROOT / "fixtures" / "psbt"

#: Every fingerprint any fixture may carry. The BIP39 test-vector mnemonic, and the second
#: published vector mnemonic the fixtures use for a stranger's addresses. A contributor pasting
#: in a PSBT from their own wallet fails here rather than quietly committing a real xpub.
ALLOWED_FINGERPRINTS = {
    "73c5da0a",  # abandon abandon … about
    "b8688df1",  # legal winner thank … yellow
}


def _core_modules() -> list[Path]:
    return [
        path
        for path in sorted(CORE.rglob("*.py"))
        # The vendored UR library is upstream code, diffed against its own commit rather than
        # linted here.
        if "vendor" not in path.parts
    ]


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module)
    return found


# --- The seam ---------------------------------------------------------------------------------


def test_core_imports_no_adapter() -> None:
    """The one rule `docs/test-harness.md` says carries weight."""
    offenders = {
        path.relative_to(ROOT): sorted(
            name
            for name in _imports(path)
            if name.startswith(("aobs.adapters", "aobs.ui", "aobs.ports"))
        )
        for path in _core_modules()
    }
    assert not {path: names for path, names in offenders.items() if names}


def test_core_reads_no_ambient_state() -> None:
    """Bytes in, value objects out: no clock, no environment, no randomness of its own.

    `pathlib` is on the list too, and for a second reason: on Python 3.12 it imports
    `urllib.parse`, which the module-closure assertion below forbids.
    """
    forbidden = {
        "os", "pathlib", "time", "datetime", "random", "secrets", "socket", "subprocess",
    }
    for path in _core_modules():
        assert not (_imports(path) & forbidden), path


def test_the_ports_have_two_adapters_each() -> None:
    from aobs import ports
    from aobs.adapters import fake

    assert set(ports.__all__) == {
        "DEFAULT_LAYOUT",
        "EntropySource",
        "Frame",
        "FrameSource",
        "Keymap",
        "Power",
    }
    # The harness half exists today; the real half is a later spec, named by the ports.
    assert set(fake.__all__) == {
        "FixedEntropySource",
        "ImageFileFrameSource",
        "RecordingKeymap",
        "RecordingPower",
    }


def test_there_is_no_screen_port() -> None:
    """The tree and `docs/test-harness.md` say the same thing, or neither is trustworthy.

    `Screen`'s two adapters were "Textual on the console" and "Textual `run_test()`" — the same
    application under two drivers, not two implementations of an interface. The app is the display
    seam now, and the port table says so.
    """
    assert not (ROOT / "aobs" / "ports" / "screen.py").exists()
    assert not (ROOT / "aobs" / "adapters" / "fake" / "screen.py").exists()

    port_table = (ROOT / "docs" / "test-harness.md").read_text(encoding="utf-8")
    assert "| `Screen` |" not in port_table
    assert "| `Keymap` |" in port_table


# --- The import closure ---------------------------------------------------------------------------

_CLOSURE_PROBE = """
import importlib, sys, logging
for module in {modules!r}:
    importlib.import_module(module)
forbidden = [m for m in ("socket", "ssl", "multiprocessing", "urllib") if m in sys.modules]
streaming = [
    type(handler).__name__
    for logger in [logging.getLogger()] + [
        logging.getLogger(name) for name in logging.root.manager.loggerDict
    ]
    if isinstance(logger, logging.Logger)
    for handler in logger.handlers
    if isinstance(handler, logging.StreamHandler)
]
print(repr({{"forbidden": forbidden, "streaming": streaming}}))
"""


def _closure_probe() -> dict:
    modules = [
        f"aobs.core.{path.stem}" if path.parent == CORE else "aobs.core"
        for path in _core_modules()
        if path.stem != "__init__"
    ]
    result = subprocess.run(
        [sys.executable, "-c", _CLOSURE_PROBE.format(modules=modules)],
        capture_output=True,
        text=True,
        check=True,
        cwd=ROOT,
    )
    return eval(result.stdout.strip())  # noqa: S307 - our own repr, in our own subprocess


#: The four modules `docs/test-harness.md` names. `CONFIG_NET=n` removes `AF_UNIX` as well as
#: `AF_INET`, taking `multiprocessing` with it.
NETWORK_STACK = ("socket", "ssl", "multiprocessing", "urllib")


def test_the_core_module_closure_pulls_in_no_network_stack() -> None:
    """That failure, caught on a laptop rather than on the appliance."""
    assert _closure_probe()["forbidden"] == []


def test_no_module_in_the_app_tree_imports_the_network_stack() -> None:
    """The app's closure cannot be asserted the way the core's can, and the reason is stdlib.

    `asyncio` — which Textual *is* — imports `socket` and `ssl`; `pathlib` on 3.12 imports
    `urllib.parse`. So an app-closure assertion would fail on every kernel and prove nothing about
    this one. The rule that is both true and enforceable is this one: **no module we write reaches
    for the network stack.** Its runtime counterpart, that a whole session constructs no socket at
    all, is `tests/test_app_shell.py::test_the_running_app_opens_no_socket` — and that is the one
    that actually checks the claim, because `import socket` succeeds on a `CONFIG_NET=n` kernel
    and only `socket()` fails.
    """
    offenders = {
        path.relative_to(ROOT): sorted(
            name for name in _imports(path) if name.split(".")[0] in NETWORK_STACK
        )
        for path in sorted((ROOT / "aobs").rglob("*.py"))
        if "vendor" not in path.parts
    }
    assert not {path: names for path, names in offenders.items() if names}


def test_the_module_closure_installs_no_logging_handler_that_writes_to_a_stream() -> None:
    """"The full traceback goes nowhere" is checked here rather than intended."""
    assert _closure_probe()["streaming"] == []


# --- The library underneath ---------------------------------------------------------------------


def test_the_vendored_embit_carries_no_prebuilt_binary() -> None:
    """The blob exists in no commit of embit — it is produced at wheel-build time.

    So vendoring from a tagged git commit removes it by construction rather than by a deletion
    step that can be skipped (#34). It matters that it stay gone: `_find_library()` returns the
    prebuilt path whenever the file merely *exists*, and does not fall through when *loading* it
    fails — which is exactly how the authoritative tier signed in pure Python for its whole life.
    """
    vendored = CORE / "vendor" / "embit"
    blobs = [
        p.relative_to(ROOT)
        for p in vendored.rglob("*")
        if p.suffix in {".so", ".dylib", ".dll"} or p.name == "prebuilt"
    ]
    assert blobs == [], f"binary artifacts in the vendored tree: {blobs}"


#: A BIP84 ECDSA signature over the published all-`abandon` BIP39 vector (passphrase `TREZOR`).
#: Byte-exact because ECDSA here is deterministic by spec — RFC6979 plus embit's low-R grinding —
#: and this value was confirmed identical under `py_secp256k1`, under embit's bundled blob, and
#: under Alpine's `libsecp256k1` 0.5.0.
#:
#: **BIP86 gets no expected bytes, and that is not laziness.** A BIP340 signature is not required
#: to be byte-stable: any valid nonce yields a valid signature, and Alpine's `libsecp256k1` and
#: embit's bundled blob measurably disagree on the one they pick. Pinning a Schnorr vector would
#: assert something BIP340 never promised, and it would fail on the authoritative tier — which is
#: exactly what it did before this comment existed. Signing and then verifying proves what the
#: check is actually for: that the `schnorrsig`/`xonly`/`keypair` symbols bound at all.
_VECTOR_MESSAGE = b"aobs build-time assertion"
_EXPECTED_ECDSA = (
    "30440220647bdba563ce32b34ad13b3d28a5d180e9b24f47e07f7444263b7310066b0ede"
    "02203c83e9e92ace3280d8f4e6506f70714228282eb878f3b5461413d232bd236e57"
)

# **`PublicKey.schnorr_verify` segfaults against any real `libsecp256k1`, and the appliance must
# never call it.** embit binds `secp256k1_schnorrsig_verify` with four arguments; since 0.3.0 the
# C function takes five, the fourth being `msglen`. So embit passes the x-only pubkey pointer
# where C reads a length and then dereferences whatever follows — a segfault, not an exception,
# which no `except:` anywhere can catch.
#
# Signing is unaffected and correct: a signature made through the ctypes path against Alpine's
# `libsecp256k1` 0.5.0 verifies. It simply picks a different nonce than embit's own bundled blob
# does, which is BIP340-legal and is why no Schnorr vector is pinned above.
#
# The appliance only ever signs, so nothing in `aobs/` calls this today. This note exists so that
# the next person to reach for it learns why it is missing rather than by crashing the appliance.


def live_secp256k1():
    """The EC backend embit actually selected, whichever it is."""
    from aobs.core.vendor.embit.util import secp256k1

    return secp256k1


def test_both_signature_schemes_produce_the_expected_bytes() -> None:
    """A name check on the backend module is not sufficient, and must not be substituted for this.

    embit binds the `schnorrsig`/`xonly`/`keypair` symbols inside their own bare `try:`/
    `except: pass`, so a `libsecp256k1` compiled without those modules imports cleanly, reports the
    native backend, and then fails at taproot signing — mid-session, with a wallet loaded, on BIP86
    only. A signature that verifies proves the symbols bound, the modules were compiled in, and the
    ABI matches; a symbol check only approximates all three.

    `docs/boot-pipeline.md` makes this a build-time assertion on the ISO. Here it is the same check
    against the tree as committed, and it runs in both tiers because correctness must hold under
    whichever backend is live.
    """
    import hashlib

    from aobs.core.vendor.embit import bip32, bip39
    from aobs.core.vendor.embit.ec import PrivateKey

    seed = bip39.mnemonic_to_seed("abandon " * 11 + "about", password="TREZOR")
    root = bip32.HDKey.from_seed(seed)
    message = hashlib.sha256(_VECTOR_MESSAGE).digest()

    key84 = root.derive("m/84h/0h/0h/0/0").key
    key86 = root.derive("m/86h/0h/0h/0/0").key
    assert isinstance(key84, PrivateKey) and isinstance(key86, PrivateKey)

    ecdsa = key84.sign(message).serialize().hex()
    assert ecdsa == _EXPECTED_ECDSA, "BIP84 ECDSA signature does not match the vector"

    # Signed by whichever backend is live; verified by the pure-Python one, which has no ABI
    # surface to get wrong and is an independent implementation of the same spec. Do **not**
    # replace this with `PublicKey.schnorr_verify`: see the note above `live_secp256k1`.
    from aobs.core.vendor.embit.util import py_secp256k1

    signature = live_secp256k1().schnorrsig_sign(message, key86._secret)
    xonly, _ = py_secp256k1.xonly_pubkey_from_pubkey(
        py_secp256k1.ec_pubkey_create(key86._secret)
    )
    assert py_secp256k1.schnorrsig_verify(signature, message, xonly), (
        "BIP86 Schnorr signature does not verify — a libsecp256k1 built without "
        "`schnorrsig`/`extrakeys` fails here and nowhere else"
    )


@pytest.mark.skipif(
    os.environ.get("AOBS_AUTHORITATIVE_TIER") != "1",
    reason="the fast tier runs on whatever the host provides; the appliance's backend is the "
    "authoritative tier's business (#34)",
)
def test_the_authoritative_tier_signs_with_the_native_secp256k1() -> None:
    """Which library does the EC is a claim about the *appliance*, so it is checked where the
    appliance's environment is reproduced.

    On a dev host this assertion would only have been testing whether a PyPI wheel shipped a
    prebuilt blob for that platform — the very blob #34 decided the appliance must not use. The
    fast tier keeps the correctness check above, which is what catches the schnorr gap; a system
    `libsecp256k1` there is recommended for speed, not required for correctness.
    """
    from aobs.core.vendor.embit.util import secp256k1

    backend = secp256k1.ec_pubkey_create.__module__
    assert backend.endswith("ctypes_secp256k1"), (
        f"embit is using {backend}: the appliance would sign in pure Python, ~48x slower and "
        "not the audited implementation"
    )


# --- The fixtures -------------------------------------------------------------------------------


def _fixture_fingerprints(psbt_bytes: bytes) -> set[str]:
    try:
        psbt = PSBT.parse(psbt_bytes)
    except Exception:
        return set()  # the deliberately malformed fixture
    found: set[str] = set()
    for scope in list(psbt.inputs) + list(psbt.outputs):
        for derivation in scope.bip32_derivations.values():
            found.add(derivation.fingerprint.hex())
        for _leaves, derivation in scope.taproot_bip32_derivations.values():
            found.add(derivation.fingerprint.hex())
    return found


@pytest.mark.parametrize(
    "fixture", sorted(CORPUS.glob("*.psbt")), ids=lambda path: path.stem
)
def test_every_fixture_fingerprint_is_in_the_allow_list(fixture: Path) -> None:
    assert _fixture_fingerprints(fixture.read_bytes()) <= ALLOWED_FINGERPRINTS


def test_every_fixture_declares_a_verdict() -> None:
    for fixture in sorted(CORPUS.glob("*.psbt")):
        meta = fixture.with_suffix(".json")
        assert meta.exists(), f"{fixture.name} has no declared verdict"
        declared = json.loads(meta.read_text())
        assert declared["name"] == fixture.stem
        assert declared["traces_to"], "a fixture names the decision it comes from"
        assert "expected" in declared


def test_the_fixtures_are_reproducible_from_the_generator() -> None:
    """A reviewer regenerates and diffs rather than trusting a blob."""
    before = {path: path.read_bytes() for path in sorted(CORPUS.glob("*.psbt"))}
    subprocess.run(
        [sys.executable, str(ROOT / "fixtures" / "generate.py")],
        capture_output=True,
        check=True,
        cwd=ROOT,
    )
    after = {path: path.read_bytes() for path in sorted(CORPUS.glob("*.psbt"))}
    assert before == after
