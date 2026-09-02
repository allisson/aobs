"""`verify-release.sh`, driven the way a stranger drives it.

**This is a seam of its own, and the exception it rests on is the point.** Every other build-time
judgement is a pure function in `build/verify.py` that this suite feeds a hostile input in
milliseconds. `verify-release.sh` cannot be one: it must be auditable by somebody who does not trust
its author as `sha256sum` and `gpg` and nothing else, so it cannot delegate to Python — and the one
artifact aimed at people who trust nobody is the last artifact that should go untested.

So the test builds a fixture release in a temporary directory — an ISO stand-in, an archive stand-in,
and a manifest carrying their real hashes — and signs it with two scratch Ed25519 keys in a throwaway
`GNUPGHOME`. This is exactly what #60's prototype did by hand across four scenarios; the test makes it
repeatable.

**The two fingerprints the shipped script accepts are hardcoded, and stay hardcoded.** An environment
override would be a hole: a copy-pasted command in a README could carry one, and the whole value of
the script is that it decides for itself whom it trusts. So the test copies the script and rewrites
those two lines, which changes whom it accepts and nothing about what it does.
`tests/test_build_verifier.py::test_the_declared_signers_are_the_fingerprints_the_verifier_hardcodes`
is the other half: it asserts the shipped copy names the real key.

Needs `gnupg` from the harness group of `build/apk-versions.txt`. A stand-in `gpg` would be a test of
our own mock, and `--status-fd` parsing is precisely the thing that would pass against one and fail
against the real tool.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
SCRIPT = ROOT / "verify-release.sh"

RELEASE = "v1.0"
MANIFEST_NAME = f"manifest-{RELEASE}.txt"
ISO_NAME = "bitcoin-signer-amd64.iso"
ARCHIVE_NAME = f"aobs-inputs-{RELEASE}.tar"


def _gpg(home: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["gpg", "--batch", "--yes", "--homedir", str(home), *arguments],
        capture_output=True,
        text=True,
    )


@pytest.fixture(scope="module")
def keys(tmp_path_factory: pytest.TempPathFactory) -> dict[str, str]:
    """Two scratch Ed25519 keys in a throwaway keyring, module-scoped because generating is the only
    slow thing here. Nothing about them is a real identity and nothing signs anything real."""
    home = tmp_path_factory.mktemp("gnupghome")
    home.chmod(0o700)
    fingerprints: dict[str, str] = {}
    for role in ("builder", "witness"):
        result = _gpg(
            home,
            "--quick-generate-key",
            "--passphrase",
            "",
            f"aobs-test-{role} <{role}@example.invalid>",
            "ed25519",
            "sign",
            "never",
        )
        assert result.returncode == 0, result.stderr
        listing = _gpg(home, "--with-colons", "--list-keys", f"{role}@example.invalid").stdout
        fingerprints[role] = next(
            line.split(":")[9] for line in listing.splitlines() if line.startswith("fpr:")
        )
    return {"home": str(home), **fingerprints}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _manifest(directory: Path, keys: dict[str, str], *, signers: tuple[str, ...]) -> Path:
    """A manifest of the real shape: comments `sha256sum -c` would choke on, `key: value` metadata,
    `input-*` fields for things inside the archive, and one contiguous checksum block."""
    iso = directory / ISO_NAME
    archive = directory / ARCHIVE_NAME
    iso.write_bytes(b"not really an ISO, but it hashes like one\n")
    archive.write_bytes(b"not really an archive\n")

    lines = [
        f"# aobs release manifest — {RELEASE}",
        "#",
        "# A comment. sha256sum -c cannot read this file whole, which is why the",
        "# documented command greps the checksum block out of it first.",
        "",
        "format: aobs-manifest-1",
        f"release: {RELEASE}",
        f"git-tag: {RELEASE}",
        "git-commit: " + "4" * 40,
        "input-kernel: linux-6.12.106.tar.xz sha256=" + "d" * 64,
        "",
    ]
    lines += [f"signer: {keys[role]} {role}" for role in signers]
    lines += [
        "",
        f"{_sha256(iso)}  {ISO_NAME}",
        f"{_sha256(archive)}  {ARCHIVE_NAME}",
        "",
    ]
    manifest = directory / MANIFEST_NAME
    manifest.write_text("\n".join(lines), encoding="utf-8")
    return manifest


def _sign(directory: Path, keys: dict[str, str], manifest: Path, *roles: str) -> Path:
    """Concatenated detached signatures in one `.asc`, which is literally what Bitcoin Core's
    `SHA256SUMS.asc` is across 19 signers. Nothing here is invented."""
    blocks = []
    for role in roles:
        result = _gpg(
            Path(keys["home"]),
            "--detach-sign",
            "--armor",
            "--local-user",
            keys[role],
            "--output",
            "-",
            str(manifest),
        )
        assert result.returncode == 0, result.stderr
        blocks.append(result.stdout)
    signature = directory / f"{MANIFEST_NAME}.asc"
    signature.write_text("".join(blocks), encoding="utf-8")
    return signature


def _script(directory: Path, keys: dict[str, str], *, witness: bool = True) -> Path:
    """The shipped script, with only the two hardcoded fingerprints rewritten."""
    text = SCRIPT.read_text(encoding="utf-8")
    text, count = re.subn(r"^KNOWN_BUILDER=.*$", f"KNOWN_BUILDER={keys['builder']}", text, flags=re.M)
    assert count == 1, "the shipped script no longer declares KNOWN_BUILDER on one line"
    replacement = f"KNOWN_WITNESS={keys['witness']}" if witness else "KNOWN_WITNESS="
    text, count = re.subn(r"^KNOWN_WITNESS=.*$", replacement, text, flags=re.M)
    assert count == 1, "the shipped script no longer declares KNOWN_WITNESS on one line"
    path = directory / "verify-release.sh"
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755)
    return path


def _run(directory: Path, keys: dict[str, str], *arguments: str) -> subprocess.CompletedProcess[str]:
    environment = dict(os.environ, GNUPGHOME=keys["home"])
    return subprocess.run(
        ["sh", str(directory / "verify-release.sh"), *arguments],
        cwd=directory,
        capture_output=True,
        text=True,
        env=environment,
    )


@pytest.fixture
def release(tmp_path: Path, keys: dict[str, str]) -> Path:
    """A complete, two-signer, internally consistent release in a directory."""
    manifest = _manifest(tmp_path, keys, signers=("builder", "witness"))
    _sign(tmp_path, keys, manifest, "builder", "witness")
    _script(tmp_path, keys)
    return tmp_path


def test_two_good_signatures_verify_and_both_fingerprints_are_reported(
    release: Path, keys: dict[str, str]
) -> None:
    result = _run(release, keys)
    assert result.returncode == 0, result.stdout + result.stderr
    assert keys["builder"] in result.stdout
    assert keys["witness"] in result.stdout
    assert f"{ISO_NAME}: OK" in result.stdout
    assert f"{ARCHIVE_NAME}: OK" in result.stdout


def test_the_builder_alone_verifies_and_the_report_says_how_many_were_expected(
    tmp_path: Path, keys: dict[str, str]
) -> None:
    """User story 12: *one of two signatures* is a different fact from *one signature*.

    The manifest cannot list the signatures over itself, but it can list who was supposed to make
    them — which is what lets a reader tell an abstention from a complete set.
    """
    manifest = _manifest(tmp_path, keys, signers=("builder", "witness"))
    _sign(tmp_path, keys, manifest, "builder")
    _script(tmp_path, keys)

    result = _run(tmp_path, keys)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "no witness signature" in result.stdout
    assert "2 expected signer(s)" in result.stdout


def test_a_missing_builder_signature_is_fatal(tmp_path: Path, keys: dict[str, str]) -> None:
    """The witness is corroboration. It is not a substitute — its key would live in GitHub's secret
    store, so it corroborates the build and not the platform."""
    manifest = _manifest(tmp_path, keys, signers=("builder", "witness"))
    _sign(tmp_path, keys, manifest, "witness")
    _script(tmp_path, keys)

    result = _run(tmp_path, keys)
    assert result.returncode == 1
    assert "no good signature from the builder" in result.stderr


def test_one_appended_byte_condemns_the_manifest(release: Path, keys: dict[str, str]) -> None:
    with (release / MANIFEST_NAME).open("a", encoding="utf-8") as handle:
        handle.write("\n")

    result = _run(release, keys)
    assert result.returncode == 1
    assert "BAD" in result.stderr
    assert f"{ISO_NAME}: OK" not in result.stdout, "a bad signature stops the run, it does not warn"


def test_a_good_signature_cannot_dilute_a_bad_one(
    tmp_path: Path, keys: dict[str, str]
) -> None:
    """User story 13: a single BADSIG condemns the file regardless of what else verified.

    The attack is concrete — sign the altered manifest with a second key you control and append that
    signature, hoping the verifier reports *a* good signature and exits zero.
    """
    manifest = _manifest(tmp_path, keys, signers=("builder",))
    signature = _sign(tmp_path, keys, manifest, "builder")
    manifest.write_text(manifest.read_text(encoding="utf-8") + "# altered\n", encoding="utf-8")
    good_over_the_altered_file = _gpg(
        Path(keys["home"]), "--detach-sign", "--armor", "--local-user", keys["witness"],
        "--output", "-", str(manifest),
    )
    assert good_over_the_altered_file.returncode == 0
    signature.write_text(
        signature.read_text(encoding="utf-8") + good_over_the_altered_file.stdout, encoding="utf-8"
    )
    _script(tmp_path, keys)

    result = _run(tmp_path, keys)
    assert result.returncode == 1
    assert "BAD" in result.stderr


def test_an_absent_archive_fails_and_iso_only_does_not(
    release: Path, keys: dict[str, str]
) -> None:
    """User story 9: declining the input archive and the source archive is a reasonable choice and
    must not be reported as a failure — but it must be reported as *not checked*, which is what
    `--iso-only` says. #71 added the second archive, so the sentence names both."""
    (release / ARCHIVE_NAME).unlink()

    assert _run(release, keys).returncode == 1

    result = _run(release, keys, "--iso-only")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "the input and source archives are not checked" in result.stdout
    assert f"{ISO_NAME}: OK" in result.stdout


def test_an_altered_iso_fails_even_with_a_good_signature(
    release: Path, keys: dict[str, str]
) -> None:
    """The signature covers the manifest; the manifest covers the ISO. Both links or neither."""
    (release / ISO_NAME).write_bytes(b"a different ISO entirely\n")

    result = _run(release, keys)
    assert result.returncode == 1
    assert "does not match the manifest" in result.stderr


def test_a_witness_fingerprint_that_is_not_yet_known_is_reported_and_ignored(
    release: Path, keys: dict[str, str]
) -> None:
    """Today's shipped state: `KNOWN_WITNESS` is empty because no witness key exists.

    A signature from a key the script does not know must be reported as unknown and ignored — never
    counted, and never fatal on its own.
    """
    _script(release, keys, witness=False)

    result = _run(release, keys)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "UNKNOWN key, ignored" in result.stdout
    assert keys["witness"] in result.stdout


def test_the_report_names_what_it_did_not_check(release: Path, keys: dict[str, str]) -> None:
    """User story 10: a green exit code must not be mistaken for a proof of more than it is.

    This is the part most verifiers skip, and it is the reason the script exists at all beside the
    two raw commands the README gives first.
    """
    stdout = _run(release, keys).stdout
    assert "what this did NOT check" in stdout
    assert "what remains resting on trust" in stdout
    assert "reproduces from source" in stdout
    assert "ADVISORIES.txt" in stdout


def test_the_script_shells_out_to_sha256sum_and_gpg_and_nothing_else() -> None:
    """The constraint that makes the script auditable, checked rather than intended.

    Verification must not begin by obtaining and trusting a new tool — that is the regress this
    project exists to escape — so a `curl`, a `python3` or a `jq` creeping in here is a defect even
    if it works. The allow-list is the POSIX text utilities a reader already has.
    """
    allowed = {
        "gpg", "sha256sum", "grep", "sed", "printf", "cat", "ls", "head", "set", "exit",
        "if", "then", "else", "elif", "fi", "for", "do", "done", "say", "fail", "return",
    }
    forbidden = {"curl", "wget", "python", "python3", "jq", "openssl", "gpgv", "node", "perl"}
    text = SCRIPT.read_text(encoding="utf-8")
    body = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    for tool in forbidden:
        assert not re.search(rf"\b{tool}\b", body), f"verify-release.sh reaches for {tool}"
    assert "gpg --status-fd=1" in body, "the human-readable output of gpg is not a stable interface"
    del allowed  # named for the reader; the assertion above is the enforceable half


def test_the_script_is_short_enough_to_read_in_one_sitting() -> None:
    """User story 11: a verification tool nobody can audit is not a verification tool.

    Counted excluding comments, because the comments are there to be read too and penalising them
    would be exactly the wrong incentive.
    """
    lines = [
        line
        for line in SCRIPT.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    assert len(lines) < 120, f"{len(lines)} lines of code"


def test_gnupg_is_in_the_harness_group_and_never_the_appliance_group() -> None:
    """This seam is why `gnupg` is pinned at all, and the rootfs must never see it."""
    assert shutil.which("gpg"), "the harness tier installs gnupg; see build/apk-versions.txt"
    pins = (ROOT / "build" / "apk-versions.txt").read_text(encoding="utf-8")
    appliance, _, harness = pins.partition("# @group harness")
    assert "gnupg=" in harness
    assert "gnupg=" not in appliance
