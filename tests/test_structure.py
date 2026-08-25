"""Tests of the repository rather than of a module.

The seam, the import closure and the fixture allow-list are all rules that decay silently. Left
to memory, the first session that puts I/O inside the core destroys the seam before anyone
notices; left to CI, the change fails here.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest
from embit.psbt import PSBT

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


def test_embit_signs_with_the_native_secp256k1_and_not_its_python_fallback() -> None:
    """embit falls back to pure-Python EC arithmetic silently, and `rm -f` fails silently too.

    Its prebuilt `libsecp256k1` is glibc-linked, so on musl it cannot relocate and a bare `except:`
    inside embit turns that into `py_secp256k1` with no message anywhere. The authoritative tier
    ran that way and nothing said so — the only symptom was 50x on every derivation-heavy test.

    The fix lives in `build/Dockerfile.test`, and it is a `rm -f` over a glob: it succeeds whether
    or not it matched anything. So the fix cannot be its own check, and this is the check.
    """
    from embit.util import secp256k1

    backend = secp256k1.ec_pubkey_create.__module__
    assert backend.endswith("ctypes_secp256k1"), (
        f"embit is using {backend}: signing is pure-Python here, and not constant-time"
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
