"""Shared fixtures, and the two conditions under which this suite is not evidence.

The mnemonic every test derives from is the one printed in BIP39 itself, so nothing in this
repository is ever a live wallet (`docs/test-harness.md`). It lives here rather than in eight test
modules so that "the test seeds are published vectors" is one fact in one place.

The rest of this module is not fixtures. It is the pair of session-level gates `docs/roadmap.md`
M1 requires, and both exist because a suite can pass while proving nothing:

  * **The EC backend.** With no loadable `libsecp256k1`, the vendored embit silently resolves to
    `py_secp256k1` and every test still passes — 50-80x slower, through the one code path
    `docs/boot-pipeline.md` forbids on the appliance. So every run says which backend is live, and
    a run in the authoritative tier refuses to start on the fallback.
  * **Skips.** A tier that reports skips is not authoritative. Each expected skip is named by node
    id below with the milestone that deletes it; an unnamed skip fails the session, and so does an
    entry that no longer skips.
"""

from __future__ import annotations

import hashlib
import os
import platform
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest
import qrcode
from qrcode.constants import ERROR_CORRECT_L

from aobs.core.wallet import Network, Wallet

#: Set by `build/Dockerfile.test` and by nothing else. It means "this environment is the
#: appliance's userland, at the versions the ISO installs", which is what makes an assertion about
#: `libsecp256k1` or about `getrandom` a claim about the appliance rather than about a dev host.
AUTHORITATIVE_TIER = os.environ.get("AOBS_AUTHORITATIVE_TIER") == "1"

#: The module embit binds when it has loaded a real `libsecp256k1` through `ctypes`.
NATIVE_EC_BACKEND = "ctypes_secp256k1"

#: The skips this tier tolerates, each with the milestone that removes it. `docs/roadmap.md` M1
#: says no test may be skipped here; these four have absent *subjects* rather than absent
#: coverage, and each disappears when its subject arrives. A node id here that does not skip is
#: as much a failure as one that skips without being here — a stale entry is a lie about what the
#: suite covers.
SKIPS_ALLOWED = {
    "tests/test_structure.py::test_there_is_no_screen_port": "docs/test-harness.md arrives at M2",
    "tests/test_structure.py::test_the_readme_carries_the_advisory_list_verbatim": (
        "ADVISORIES.txt and the README's advisory section arrive at M5"
    ),
    # `[NOTSET]` is pytest's id for an empty parameter set: the corpus is empty, so the
    # parametrised test collects one item that cannot run. Not a typo — the id is what
    # `report.nodeid` carries, and it changes to real capture ids the moment frames are added,
    # which is precisely when this entry should stop matching.
    "tests/test_wallet_interop.py::test_a_captured_stream_reassembles_to_the_wallets_own_psbt"
    "[NOTSET]": "no captured wallet frames — fixtures/wallet_frames/README.md",
    "tests/test_wallet_interop.py::test_the_corpus_is_present": (
        "no captured wallet frames — fixtures/wallet_frames/README.md"
    ),
}

_skipped: set[str] = set()


def live_ec_backend() -> str:
    """The short name of the module embit's EC operations actually resolved to.

    Read from `ec_pubkey_create.__module__` rather than from whether a `.so` exists on disk:
    `secp256k1.py` binds its symbols inside a bare `except:`, so a library that is present but
    unloadable — Debian shipping 0.7+, which dropped the deprecated alias embit binds — produces a
    pure-Python signer and no error at all. What was bound is the only honest question.
    """
    from aobs.core.vendor.embit.util import secp256k1

    return secp256k1.ec_pubkey_create.__module__.rsplit(".", 1)[-1]


def pytest_report_header() -> list[str]:
    """Name the interpreter and the live EC backend on every run, in both tiers.

    On a dev machine this is the whole point: a green 22-minute run through `py_secp256k1` is not
    wrong, but it is not evidence about the code that ships, and the header is what stops a
    milestone being checked off from one. `CLAUDE.md` states the rule; this prints it.
    """
    backend = live_ec_backend()
    header = [
        f"aobs: python {platform.python_version()}, EC backend {backend}, "
        f"authoritative tier {'yes' if AUTHORITATIVE_TIER else 'no'}"
    ]
    if backend != NATIVE_EC_BACKEND:
        header.append(
            f"aobs: EC runs in {backend}, not {NATIVE_EC_BACKEND} — this run exercises the code "
            "path docs/boot-pipeline.md forbids on the appliance and is NOT evidence about it"
        )
    return header


def pytest_sessionstart() -> None:
    """Refuse to run the authoritative tier against the pure-Python fallback.

    Not a failing test: a session that never starts. A tier that ran 700 tests through
    `py_secp256k1` and reported them green would be asserting the appliance's behaviour against a
    library the appliance does not have, and the report would look exactly like a good one.
    """
    if not AUTHORITATIVE_TIER:
        return
    backend = live_ec_backend()
    if backend != NATIVE_EC_BACKEND:
        raise pytest.UsageError(
            f"the authoritative tier resolved embit to {backend}, not {NATIVE_EC_BACKEND}: "
            "libsecp256k1 is missing, or it is a version whose symbols embit's loader cannot "
            "bind (0.7+ dropped secp256k1_ec_privkey_negate). Running the suite here would "
            "prove the appliance's behaviour against a library the appliance does not have."
        )


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    if report.skipped:
        _skipped.add(report.nodeid)


def skip_policy_violations(
    skipped: set[str], allowed: dict[str, str], *, whole_suite: bool
) -> list[str]:
    """The policy itself, as a pure function of what skipped and what was allowed to.

    Two violations, not one. An **unnamed skip** is a test quietly not run. A **stale entry** is a
    node id the allowlist still excuses although it now runs — which is worse than harmless: it is
    a standing exemption nobody will notice has stopped applying, so the next skip of that test
    passes unremarked.

    Staleness is only checked for a whole-suite run. The dev loop runs one file in this same
    container, and the other allowlisted ids not appearing there means "not collected".
    """
    violations = [f"  UNNAMED SKIP  {nodeid}" for nodeid in sorted(skipped - set(allowed))]
    if whole_suite:
        violations += [
            f"  NO LONGER SKIPS  {nodeid}  ({allowed[nodeid]})"
            for nodeid in sorted(set(allowed) - skipped)
        ]
    return violations


def pytest_sessionfinish(session: pytest.Session) -> None:
    """`skip_policy_violations`, applied to the session that just ran, in this tier only."""
    if not AUTHORITATIVE_TIER:
        return

    violations = skip_policy_violations(
        _skipped, SKIPS_ALLOWED, whole_suite=not session.config.getoption("file_or_dir")
    )
    if not violations:
        return

    message = (
        "the authoritative tier skipped a test it does not name, or names one it no longer "
        "skips. docs/roadmap.md M1: a tier that reports skips is not authoritative. Add the "
        "node id to SKIPS_ALLOWED in tests/conftest.py with the milestone that removes it, or "
        "delete the entry that has stopped skipping.\n" + "\n".join(violations)
    )
    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    if reporter is not None:
        reporter.write_sep("=", "skip policy", red=True)
        reporter.write_line(message)
    else:  # pragma: no cover - pytest always registers it outside of `-p no:terminal`
        print(message)
    session.exitstatus = pytest.ExitCode.TESTS_FAILED


# --- The fixtures ---------------------------------------------------------------------------------

VECTOR_MNEMONIC = (
    "abandon abandon abandon abandon abandon abandon abandon abandon "
    "abandon abandon abandon about"
)

#: A second published vector mnemonic, for the addresses a fixture needs to be a stranger's.
STRANGER_MNEMONIC = (
    "legal winner thank year wave sausage worth useful legal winner thank yellow"
)

CORPUS = Path(__file__).parent.parent / "fixtures" / "psbt"


@pytest.fixture
def mainnet_wallet() -> Wallet:
    return Wallet.from_mnemonic(VECTOR_MNEMONIC, network=Network.MAINNET)


@pytest.fixture
def signet_wallet() -> Wallet:
    return Wallet.from_mnemonic(VECTOR_MNEMONIC, network=Network.SIGNET)


def fixed_bytes(seed: bytes = b"aobs-test") -> Callable[[int], bytes]:
    """A deterministic stand-in for the `EntropySource` port: a counter through SHA-256.

    Not a constant — a constant would hide a caller that draws the salt and the nonce from the
    same call.
    """
    state = {"n": 0}

    def draw(count: int) -> bytes:
        out = b""
        while len(out) < count:
            out += hashlib.sha256(seed + state["n"].to_bytes(4, "big")).digest()
            state["n"] += 1
        return out[:count]

    return draw


#: Eight screen pixels per QR module, as in `tests/test_qr_loopback.py`: the appliance's console is
#: 1024x768 for a 77x77 code, so this is the same order of magnitude a camera would see.
SCALE = 8


def render_qr(payload: str | bytes, directory: Path, index: int = 0) -> Path:
    """One frame, as an image file — which is what the `FrameSource` fake reads.

    Actual images, decoded by the same `zxing-cpp` the appliance uses. Handing the decoder a string
    instead would skip the component most likely to surprise us, which is the whole reason the
    `FrameSource` port carries frames and not payloads.
    """
    code = qrcode.QRCode(error_correction=ERROR_CORRECT_L, border=4, box_size=SCALE)
    code.add_data(payload)
    code.make(fit=True)
    path = directory / f"frame-{index:03d}.png"
    code.make_image().save(path)
    return path


def render_qrs(payloads: Sequence[str | bytes], directory: Path) -> list[Path]:
    return [render_qr(payload, directory, index) for index, payload in enumerate(payloads)]
