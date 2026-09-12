"""Tests of the repository rather than of a module.

The seam, the import closure and the fixture allow-list are all rules that decay silently. Left
to memory, the first session that puts I/O inside the core destroys the seam before anyone
notices; left to CI, the change fails here.
"""

from __future__ import annotations

import ast
import re
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import screentext
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
    from aobs.adapters import fake, real

    assert set(ports.__all__) == {
        "DEFAULT_LAYOUT",
        "EntropySource",
        "Frame",
        "FrameSource",
        "Keymap",
        "Power",
    }
    assert set(fake.__all__) == {
        "FixedEntropySource",
        "ImageFileFrameSource",
        "RecordingKeymap",
        "RecordingPower",
    }
    assert set(real.__all__) == {
        "ForcedPowerOff",
        "KernelEntropySource",
        "LoadkeysKeymap",
        "V4L2FrameSource",
    }


def test_the_application_names_the_real_adapters_in_exactly_one_place() -> None:
    """`aobs/ui/` knows only the ports, and `aobs/__main__.py` is the one module that knows which
    adapters are real. That is what lets the whole application be driven headless with the fakes
    and carry no conditional asking what it is running on."""
    app_tree = [
        path
        for path in (ROOT / "aobs").rglob("*.py")
        if "vendor" not in path.parts and path.name != "__main__.py"
    ]
    for path in app_tree:
        assert not any(
            name.startswith("aobs.adapters.real") for name in _imports(path)
        ), path


def test_the_application_cannot_be_started_with_a_fake_wired_in() -> None:
    """A fake `Power` does not power off and a fake `EntropySource` returns a deterministic
    counter, so an appliance started with either would look correct on screen and be worthless in
    every claim it makes. There is no flag and no fallback that could select one."""
    entry = ROOT / "aobs" / "__main__.py"
    assert not any(name.startswith("aobs.adapters.fake") for name in _imports(entry))
    #: No flag and no fallback: nothing here reads the environment or the command line, so there
    #: is no input at all that could select a different set of adapters.
    read = {
        node.attr
        for node in ast.walk(ast.parse(entry.read_text(encoding="utf-8")))
        if isinstance(node, ast.Attribute)
    }
    assert not read & {"environ", "getenv", "argv"}


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


def _function_keys_bound_but_not_printed(source: str) -> list[str]:
    """Function keys a screen module binds and never puts on screen, given its source.

    **Two kinds of string do not count as printed**, and both exclusions are the point. A
    docstring, because the picker's own docstring could have named `F10` while the screen showed
    the user nothing. And `Binding("f10", ...)`'s own arguments — measured while writing this: with
    those counted, every screen trivially "prints" every key it binds and the rule passes for the
    wrong reason. `tests/test_structure.py::test_the_printed_key_rule_bites` is what caught that.
    """
    tree = ast.parse(source)
    binding_arguments = {
        id(argument)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "Binding"
        for argument in [*node.args, *(keyword.value for keyword in node.keywords)]
    }
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
        and isinstance(node.body[0].value.value, str)
    }
    bound = {
        node.args[0].value.lower()
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "Binding"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
    }
    rendered = " ".join(
        node.value.lower()
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
        and id(node) not in binding_arguments
    )
    # Function keys only. `up`/`down`/`escape` are the reserved vocabulary of
    # `docs/failure-states.md` and are printed in prose — `up/down choose`, `esc back` — not as a
    # token this check could match without guessing.
    return [
        f"binds {key.upper()} and never prints it"
        for key in sorted(key for key in bound if re.fullmatch(r"f\d+", key))
        if key not in rendered
    ]


def test_every_screen_that_binds_a_key_prints_that_key() -> None:
    """A key nothing renders is a key the user does not have.

    The keymap picker bound `F10`, `docs/failure-states.md` fixed it, every other screen printed
    its own line — and the picker did not. The first boot that reached a screen ended with a user
    sitting on it unable to leave, which is the whole cost of one missing `Static`.

    Source-level on purpose: driving every screen to the point where it renders means walking the
    whole session, and this rule is about the source saying two things consistently. What it checks
    is narrow and mechanical: a module that binds a function key must contain that key as text
    somewhere too.
    """
    screens = sorted((ROOT / "aobs" / "ui" / "screens").glob("*.py"))
    assert len(screens) > 10, "the screen tree moved; this test is looking in the wrong place"

    # Some screens keep their line in a shared text module — `reviewtext.UNLOCKED_KEYS`,
    # `addresstext.LIST_KEYS` — so the text a screen can render is its own plus that of the
    # `aobs.ui` modules it imports. One level, because that is the indirection the tree actually
    # uses and a general resolver would be a guess about the next one.
    shared = {
        path.stem: path.read_text(encoding="utf-8")
        for path in sorted((ROOT / "aobs" / "ui").glob("*.py"))
    }
    offenders: list[str] = []
    for screen in screens:
        source = screen.read_text(encoding="utf-8")
        imported = "\n".join(
            text
            for name, text in shared.items()
            if re.search(rf"\bimport +{re.escape(name)}\b|\bfrom +aobs\.ui\.{re.escape(name)}\b", source)
        )
        for complaint in _function_keys_bound_but_not_printed(source + "\n" + imported):
            offenders.append(f"{screen.name}: {complaint}")
    assert not offenders, offenders


def test_the_printed_key_rule_bites() -> None:
    """Fed a screen shaped like the picker before the fix, and one shaped like it after."""
    bound_only = (
        '"""A screen. Press F10 to go on."""\n'
        'BINDINGS = [Binding("f10", "accept", "Use this layout")]\n'
        'def compose():\n    yield Static("Keyboard layout", id="title")\n'
    )
    assert _function_keys_bound_but_not_printed(bound_only) == ["binds F10 and never prints it"]

    printed = bound_only + 'KEYS = "F10 use this layout"\n'
    assert _function_keys_bound_but_not_printed(printed) == []


# --- The key inventory in `docs/failure-states.md` ---------------------------------------------

#: The two keys the document reserves globally. They are settled in its own three-key inventory
#: above the table, so the table does not repeat them and this check does not look for them.
_RESERVED_GLOBALLY = frozenset({"escape", "f12"})

#: How a bound key is spelled in the table, which is prose for a human to read. A key with no entry
#: here fails rather than being skipped — a new *kind* of key is exactly the case where someone has
#: to go and write the document, which is the whole point of the check.
_KEY_IN_THE_INVENTORY = {
    "f2": "`F2`",
    "f5": "`F5`",
    "f9": "`F9`",
    "f10": "`F10`",
    "y": "`y`",
    "up": "`↑`",
    "down": "`↓`",
    "left": "`←`",
    "right": "`→`",
    "pageup": "`PgUp`",
    "pagedown": "`PgDn`",
}


def _module_level_strings(tree: ast.Module) -> dict[str, str]:
    """`STEP_DOWN_KEY = "f9"` and nothing cleverer. A key assembled at runtime would not resolve
    here, and should not: the document has to name a literal for a human to read."""
    return {
        target.id: node.value.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
        for target in node.targets
        if isinstance(target, ast.Name)
    }


def _keys_bound_across_the_ui() -> tuple[set[str], list[str]]:
    """Every key any `Binding(...)` in `aobs/ui` takes, with the constants resolved.

    Three forms exist in the tree and all three are resolved: a literal, a module-level constant in
    the same file, and one reached through an `aobs.ui` module — `addresstext.SEARCH_FURTHER_KEY`.
    Anything else is returned as unresolved and fails the caller rather than being dropped, because
    a key this cannot read is a key that could be missing from the document unnoticed.
    """
    paths = sorted((ROOT / "aobs" / "ui").rglob("*.py"))
    assert len(paths) > 20, "the UI tree moved; this test is looking in the wrong place"
    trees = {path: ast.parse(path.read_text(encoding="utf-8")) for path in paths}
    constants = {path.stem: _module_level_strings(tree) for path, tree in trees.items()}

    keys: set[str] = set()
    unresolved: list[str] = []
    for path, tree in trees.items():
        local = constants[path.stem]
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "Binding"
                and node.args
            ):
                continue
            argument = node.args[0]
            if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                keys.add(argument.value.lower())
            elif isinstance(argument, ast.Name) and argument.id in local:
                keys.add(local[argument.id].lower())
            elif (
                isinstance(argument, ast.Attribute)
                and isinstance(argument.value, ast.Name)
                and argument.attr in constants.get(argument.value.id, {})
            ):
                keys.add(constants[argument.value.id][argument.attr].lower())
            else:
                unresolved.append(f"{path.name}:{argument.lineno}")
    return keys, unresolved


def _inventory_table() -> str:
    """The three-row table under *Per-screen keys are named in their own screen's document*."""
    document = (ROOT / "docs" / "failure-states.md").read_text(encoding="utf-8")
    rows = [line for line in document.splitlines() if line.startswith("| **")]
    assert len(rows) == 3, f"the inventory table is not three rows: {len(rows)}"
    return "\n".join(rows)


def _keys_missing_from_the_inventory(keys: set[str], table: str) -> list[str]:
    return sorted(
        f"{key} is bound and the inventory does not name it"
        for key in keys - _RESERVED_GLOBALLY
        if _KEY_IN_THE_INVENTORY.get(key, f"`{key}`") not in table
    )


def test_the_key_inventory_names_every_key_the_ui_binds() -> None:
    """`docs/failure-states.md`'s table says it is there *so the inventory is not silently
    incomplete*. It went silently incomplete anyway, twice: `F2` was never in it, and `F9` grew
    from one meaning to four across five screens without the table moving.

    Prose that claims completeness and nothing checks is the shape this repository rejects
    elsewhere, so this is the check. It is deliberately narrow — every key bound anywhere under
    `aobs/ui` must appear in the table, and nothing here reads the *meaning* beside it. A wrong
    description is a review's job; a missing key is a mechanical fact and belongs here.
    """
    keys, unresolved = _keys_bound_across_the_ui()
    assert not unresolved, f"a Binding key this check cannot read: {unresolved}"
    assert "f10" in keys, "no Binding was found at all; the resolver is broken, not the document"
    assert not _keys_missing_from_the_inventory(keys, _inventory_table())


def test_the_key_inventory_rule_bites() -> None:
    """Fed the table as it stood before this check existed — `F9` present, `F2` absent."""
    before = "| **Its own** | `F9` — *step the QR down one rung* | emit |"
    assert _keys_missing_from_the_inventory({"f9", "f2"}, before) == [
        "f2 is bound and the inventory does not name it"
    ]
    assert _keys_missing_from_the_inventory({"f9"}, before) == []
    # And the reserved keys are never looked for: they are settled above the table, not in it.
    assert _keys_missing_from_the_inventory({"escape", "f12"}, before) == []


# --- The inspection boot's command line ------------------------------------------------------

#: Everything published that could tell a reader how to reach the inspection boot. A wrong
#: parameter here is not a typo: the inspection boot is what makes every ABSENCE claim checkable
#: by a stranger, so an instruction that silently boots the appliance instead costs them the only
#: means of checking anything.
_DOCUMENTS_THAT_NAME_THE_INSPECTION_BOOT = (
    "README.md",
    "CONTEXT.md",
    "docs/overview.md",
    "docs/boot-checklist.md",
    "docs/boot-pipeline.md",
    "docs/roadmap.md",
    "build/isolinux.cfg",
    "build/grub.cfg",
)


def test_no_document_tells_a_stranger_to_type_init_instead_of_rdinit() -> None:
    """`init=` is accepted by the bootloader, ignored by the kernel, and boots the appliance.

    The rootfs is the initramfs, so the kernel never mounts a root: `init/main.c` runs
    `ramdisk_execute_command` — `/init` by default, `rdinit=` to override — and only falls through
    to `init=` if that fails. `/init` is `build/init` and it succeeds.

    So the wrong parameter produces no error and no hint. It was in six documents, nobody had run
    the boot they described, and the fault was found by a person at a machine typing what the
    README told them to. This test is what stops it coming back, in the same shape as every other
    assertion this milestone added: read what the repository says, and check it.
    """
    wrong = []
    for name in _DOCUMENTS_THAT_NAME_THE_INSPECTION_BOOT:
        text = (ROOT / name).read_text(encoding="utf-8")
        for number, line in enumerate(text.splitlines(), start=1):
            #: `rdinit=/bin/sh` contains `init=/bin/sh`, so the match has to be anchored to what
            #: precedes it — a bare `init=`, not the tail of the correct one.
            if re.search(r"(?<![a-z])init=/bin/sh", line):
                wrong.append(f"{name}:{number}")
    assert not wrong, (
        f"{wrong} tell a reader to type `init=/bin/sh`. The kernel ignores it on an "
        "initramfs-only image and boots the appliance; the parameter is `rdinit=/bin/sh`"
    )


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
    against the tree as committed, and it is not gated because correctness must hold under
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
    reason="off-container runs use whatever the host provides; which library performs the EC is a "
    "claim about the appliance, checked where the appliance's environment is reproduced (#34)",
)
def test_the_authoritative_tier_signs_with_the_native_secp256k1() -> None:
    """Which library does the EC is a claim about the *appliance*, so it is checked where the
    appliance's environment is reproduced.

    Off-container this assertion would only have been testing whether a PyPI wheel shipped a
    prebuilt blob for that platform — the very blob #34 decided the appliance must not use. The
    correctness check above is not gated and runs everywhere, which is what catches the schnorr
    gap; `uv run pytest` on a host with no system `libsecp256k1` is slow but not wrong (#35).
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


def _advisories_section() -> str:
    """Everything under the `Advisories` heading of ADVISORIES.txt, to end of file."""
    text = (ROOT / "ADVISORIES.txt").read_text()
    heading = "Advisories\n----------\n\n"
    assert heading in text, "ADVISORIES.txt has lost its Advisories heading"
    return text.split(heading, 1)[1].strip()


def _readme_advisories_section() -> str:
    """The body of README.md's `## Security advisories` section."""
    text = (ROOT / "README.md").read_text()
    heading = "## Security advisories\n"
    assert heading in text, "README.md has lost its Security advisories heading"
    body = text.split(heading, 1)[1]
    return body.split("\n## ", 1)[0]


@pytest.mark.skipif(
    not (ROOT / "ADVISORIES.txt").exists(),
    reason="ADVISORIES.txt and the README's advisory section arrive at M5 (docs/roadmap.md)",
)
def test_the_readme_carries_the_advisory_list_verbatim() -> None:
    """#62 requires every release's README to carry the full list, so the list exists twice.

    Twice by design, not by discipline: two hand-maintained copies of one safety-relevant list
    drift, and the copy that drifts is the one a reader met first. `docs/release.md` step 2 edits
    both files and then runs this suite, so a half-done edit fails here rather than shipping.
    """
    assert _advisories_section() in _readme_advisories_section()


# --- The glyph budget ----------------------------------------------------------------------------

#: Every non-ASCII character the appliance's console can draw, and the reason it is a fixed list.
#: `build/init` never calls `setfont` and `loadkeys` does not touch the console map, so the vt uses
#: the kernel's DEFAULT map — generated by `conmakehash` from `drivers/tty/vt/cp437.uni`, 303
#: codepoints, 207 of them outside ASCII. A character outside this set has no glyph and draws as
#: nothing. Regenerate by extracting every `U+xxxx` from that file in the pinned kernel's tree.
#:
#: `docs/console-appearance.md` carries the budget in prose; this is the same statement, checkable.
CONSOLE_REPERTOIRE = frozenset(
    "".join(chr(c) for c in range(0x20, 0x7F))
    + "\xa0¡¢£¤¥¦§¨©ª«¬\xad®°±²´µ¶·¸º»¼½¿ÀÁÂÃÄÅÆÇÈÉÊËÌÍÎÏÐÑÒÓÔÕÖ×ØÙÚÛÜÝßàáâãäåæçèéêëìíîïðñòóôõ"
    "ö÷øùúûüýÿƒΓΘΣΦΩαβδεμπστφ•‼ⁿ₧ΩKÅ←↑→↓↔↕↨∈∙√∞∟∩≈≡≤≥⌂⌐⌠⌡⎽─│┌┐└┘├┤┬┴┼═║╒╓╔╕╖╗╘╙╚╛╜╝╞╟╠╡╢╣╤╥╦╧"
    "╨╩╪╫╬▀▄█▌▐░▒▓■▬▲▶►▼◀◄◆○◘◙☺☻☼♀♂♠♣♥♦♪♫"
    + "\n"
)


def _outside_the_repertoire(text: str) -> list[str]:
    return sorted({f"{ch!r} U+{ord(ch):04X}" for ch in text if ch not in CONSOLE_REPERTOIRE})


@pytest.mark.parametrize("name", list(screentext.SCREENS))
async def test_every_screen_draws_only_characters_the_console_has(name: str) -> None:
    """A character with no glyph draws as nothing, and says nothing about having failed.

    This is `docs/console-appearance.md`'s glyph budget, enforced. It was prose for a year and
    five characters were outside it the whole time: `⚠` on the NOT PROVEN marker, `▮`/`▯` for the
    slot map — the whole of the scan screen's feedback — and both dashes. None of them would have
    raised anything; they would have left holes.
    """
    rendered = await screentext.SCREENS[name]()
    bad = _outside_the_repertoire(rendered)
    assert not bad, f"the {name} screen draws {bad}, which the console has no glyph for"


def test_no_ui_string_constant_leaves_the_repertoire() -> None:
    """The four rendered screens are not every screen, so the constants are checked too.

    The review screen's NOT PROVEN warning is the case that matters and is deliberately **not** a
    README block (`docs/console-appearance.md`: no refusal, no adversarial case), which is exactly
    how `⚠` sat unchecked. Reading the string constants reaches it, and everything else a screen
    can put on the console, without driving every screen through the harness.
    """
    offenders: list[str] = []
    for path in sorted((ROOT / "aobs" / "ui").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        docstrings = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                first = node.body[0] if node.body else None
                if (
                    isinstance(first, ast.Expr)
                    and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)
                ):
                    docstrings.add(id(first.value))
        #: `SignerApp.CSS` is parsed by Textual and never drawn, and its comments are prose.
        #: Every `Constant` *inside* it, not the assignment's own value: `CSS` is an f-string, so
        #: the value is a `JoinedStr` and the literal pieces hang below it.
        css = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "CSS" for t in node.targets
            ):
                css.update(id(inner) for inner in ast.walk(node.value))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and id(node) not in docstrings
                and id(node) not in css
            ):
                bad = _outside_the_repertoire(node.value)
                if bad:
                    offenders.append(f"{path.relative_to(ROOT)}:{node.lineno} {bad}")
    assert not offenders, (
        "these rendered strings use characters the console has no glyph for: " + "; ".join(offenders)
    )


def test_the_glyph_budget_rule_bites() -> None:
    """Fed the exact characters this milestone found on the appliance's own screens."""
    assert _outside_the_repertoire("PAYMENT 0.001 BTC") == []
    assert _outside_the_repertoire("█░█░") == []
    assert _outside_the_repertoire("⚠") == ["'⚠' U+26A0"]
    assert _outside_the_repertoire("▮▯") == ["'▮' U+25AE", "'▯' U+25AF"]
    assert _outside_the_repertoire("a — b") == ["'—' U+2014"]


# --- The README's screen blocks --------------------------------------------------------------------


def _readme_block(name: str) -> str:
    """The fenced block `README.md` carries for one screen, by its marker comment."""
    text = (ROOT / "README.md").read_text()
    marker = f"<!-- screen: {name} -->\n```text\n"
    assert marker in text, f"README.md has lost its {name} screen block"
    return text.split(marker, 1)[1].split("\n```", 1)[0]


@pytest.mark.parametrize("name", list(screentext.SCREENS))
async def test_the_readme_carries_each_screen_block_verbatim(name: str) -> None:
    """A stale block is a false claim about what the appliance shows.

    `docs/console-appearance.md`, *The blocks in the README*: the blocks are renders, so they are
    regenerated here and compared character for character — the same device that keeps the advisory
    list honest. This asserts the README agrees with the screen. It does not assert the screen is
    right; the money path is asserted in `tests/test_review_screen.py`.
    """
    rendered = await screentext.SCREENS[name]()
    assert _readme_block(name) == rendered, (
        f"README.md's {name} block no longer matches the screen. "
        "Regenerate the blocks rather than editing them by hand."
    )


async def test_the_readme_block_rule_bites() -> None:
    """The comparison above passes trivially if it is comparing something to itself.

    `build/verify.py`'s rule, applied here: feed the assertion a deliberately broken input and
    prove it still fails. One changed character in the screen's own text is the smallest edit a
    hand-written block would miss.
    """
    rendered = await screentext.SCREENS["home"]()
    mutated = rendered.replace("WHAT YOU CAN DO", "WHAT YOU CAN DQ", 1)
    assert mutated != rendered, "the mutation did not change anything"
    assert _readme_block("home") != mutated


def _kernel_options(text: str, marker: str) -> list[str]:
    """The kernel parameters on the one line of a boot config that carries them."""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(marker):
            return stripped[len(marker) :].split()
    raise AssertionError(f"no {marker!r} line found")


def test_the_two_firmware_paths_boot_the_same_cmdline() -> None:
    """BIOS and UEFI differ in bootloader, never in what the kernel is told.

    They used to differ by `vga=791`, on the argument that a BIOS boot needs a VESA mode set or it
    lands in 80x25 text. `docs/adr/0003-the-console-is-enforced-not-requested.md` records why that
    came out: on the one machine this project has booted, `vga=791` never set a mode — it printed
    `Undefined video mode number: 317` and stalled 30 seconds on every boot — and the console came
    from coreboot's own framebuffer at the resolution the parameter happened to ask for.

    A difference between the paths is worth an assertion in either direction. While one existed it
    meant `I-7` measured a console through a stall the appliance also paid for; now that none does,
    a reintroduced `vga=` would put it back with nothing to say so.
    """
    isolinux = (ROOT / "build" / "isolinux.cfg").read_text(encoding="utf-8")
    grub = (ROOT / "build" / "grub.cfg").read_text(encoding="utf-8")

    session = _kernel_options(isolinux, "APPEND ")
    uefi = _kernel_options(grub, "linux /boot/vmlinuz ")
    assert session == uefi, (
        f"the BIOS cmdline {session} and the UEFI cmdline {uefi} differ; "
        "an appliance that boots differently per firmware path is two appliances"
    )

    appended = [line for line in isolinux.splitlines() if line.strip().startswith("APPEND ")]
    assert len(appended) == 2, "one APPEND per label, and there are two labels"
    inspect = _kernel_options(appended[1] + "\n", "APPEND ")
    assert inspect == session + ["rdinit=/bin/sh"], (
        f"the inspection cmdline {inspect} differs from the session cmdline by more than "
        "`rdinit=/bin/sh`; an inspection boot must inspect the image that signs"
    )

    assert not [opt for opt in session if opt.startswith("vga=")], (
        "a `vga=` came back. There is no portable value: the kernel's resolution form matches on "
        "pixel counts that overflow the u16 it compares (`video-mode.c:88`), and a mode number is "
        "one firmware's. The console floor is enforced in `aobs/ui/geometry.py` instead"
    )
