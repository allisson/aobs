"""The reading half. Gathers an input, hands it to `build/verify.py`, prints the verdict.

`build/mkiso.sh` cannot call a Python function, so this is the thin shim between them:

    python3 build/gather.py kernel-config build/kernel.config
    python3 build/gather.py rootfs /build/rootfs-listing.txt
    python3 build/gather.py apk-manifest /build/apk-manifest.txt build/apk-versions.txt

Exit 0 means no violations; exit 1 prints each violation — the claim it broke and what was seen —
and the build stops there.

**All the filesystem contact lives here and none of the judgement does.** `verify.py` never opens a
file, which is exactly what lets `tests/test_build_verifier.py` feed it a deliberately broken input
in milliseconds instead of building an image to find out whether an assertion still bites.

Two subcommands decide nothing and are here because they touch the same files. `pins-of-group`
prints one group of `build/apk-versions.txt` as `apk add` arguments. `prune-busybox-applets`
**deletes** the applet symlinks whose names the claims forbid — a mutation, in a module otherwise
about reading, and deliberately not in `build/mkiso.sh`: which links may be removed is a *policy*
("only a symlink, only into busybox, never a regular file"), a policy that deletes files inside the
image is exactly the kind that must be tested, and shell is where it could not be. The verifier
judges the result independently either way, so an applet nobody listed fails the build.
"""

from __future__ import annotations

import hashlib
import importlib.util
import os
import stat
import subprocess
import sys
from pathlib import Path

_here = Path(__file__).parent
_spec = importlib.util.spec_from_file_location("aobs_build_verify", _here / "verify.py")
assert _spec is not None and _spec.loader is not None
verify = importlib.util.module_from_spec(_spec)
sys.modules["aobs_build_verify"] = verify
_spec.loader.exec_module(verify)


def _read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def _listing(path: str) -> list[str]:
    return [line for line in _read(path).splitlines() if line.strip()]


def _tree(root: str) -> list[str]:
    base = Path(root)
    return [
        str(path.relative_to(base.parent))
        for path in base.rglob("*")
        if "__pycache__" not in path.parts
    ]


def _report(violations: list) -> int:
    if not violations:
        return 0
    sys.stderr.write(f"\n{len(violations)} violation(s):\n\n")
    for violation in violations:
        sys.stderr.write(f"  {violation}\n\n")
    return 1


def main(argv: list[str]) -> int:
    if not argv:
        sys.stderr.write(__doc__ or "")
        return 2
    command, arguments = argv[0], argv[1:]

    if command == "kernel-config":
        return _report(verify.check_kernel_config(_read(arguments[0])))

    if command == "cmdline":
        firmware, path = arguments
        extract = verify.FIRMWARE_EXTRACTORS[firmware]
        return _report(verify.check_cmdline(extract(_read(path)), firmware))

    if command == "rootfs":
        return _report(verify.check_rootfs(_listing(arguments[0])))

    if command == "vendored-tree":
        return _report(verify.check_vendored_tree(_tree(arguments[0])))

    if command == "apk-manifest":
        manifest, pins = arguments
        return _report(verify.check_apk_manifest(_read(manifest), _read(pins)))

    if command == "pins-of-group":
        group, path = arguments
        pins = verify.parse_pins(_read(path))
        print(" ".join(f"{name}={version}" for name, version in pins[group].items()))
        return 0

    if command == "prune-busybox-applets":
        return _prune_busybox_applets(arguments[0])

    # --- The release engineering half (#54's eight tickets) ---------------------------------------

    if command == "inputs":
        directory, listing = arguments
        return _report(verify.check_inputs(_hashes(directory), _read(listing)))

    if command == "toolchain-list":
        return _report(verify.check_toolchain_list(_read(arguments[0])))

    if command == "pinned-parallelism":
        return _report(
            verify.check_pinned_parallelism({path: _read(path) for path in arguments})
        )

    if command == "tree-manifest":
        print(_tree_manifest(arguments[0]))
        return 0

    if command == "write-release":
        source, destination = arguments
        return _write_release(source, destination)

    if command == "embedded-release":
        source, release_file = arguments
        git = _git_facts(source)
        return _report(
            verify.check_embedded_release(
                _read(release_file),
                tag=git.tag,
                head_commit=git.head_commit,
                dirty=git.dirty,
                source_date_epoch=_source_date_epoch(source),
            )
        )

    if command == "release-preflight":
        source = arguments[0]
        release_file = arguments[1] if len(arguments) > 1 else None
        manifest = arguments[2] if len(arguments) > 2 else None
        return _report(
            verify.check_release_preflight(
                _git_facts(source),
                # Explicitly, because this subcommand exists only for the release ritual: the four
                # refusals are release-mode-only by decision (#65), not by accident of who calls.
                release_mode=True,
                # **From `/etc/aobs-release` when the build has produced one**, and that is what makes
                # this refusal bite at all. `build/mkiso.sh` derives `SOURCE_DATE_EPOCH` itself and
                # ignores the environment, so comparing the *shell's* variable against the tagged
                # commit's date compares two values the invocation just set from the same source —
                # vacuously equal. The embedded value is what the build actually used, so a future
                # edit that let the build honour an inherited variable would fail here.
                source_date_epoch=(
                    verify.parse_fields(_read(release_file)).get("source-date-epoch", "")
                    if release_file
                    else os.environ.get("SOURCE_DATE_EPOCH", "")
                ),
                manifest_commit=(
                    verify.parse_fields(_read(manifest)).get("git-commit", "")
                    if manifest
                    else None
                ),
            )
        )

    if command == "write-manifest":
        source, release_file, published = arguments
        print(_manifest(source, release_file, published), end="")
        return 0

    if command == "manifest":
        source, manifest, release_file, published = arguments
        return _report(
            verify.check_manifest(
                _read(manifest),
                release_text=_read(release_file),
                inputs_list_sha256=_sha256(Path(source) / "build" / "inputs.sha256"),
                published=_published(published),
            )
        )

    sys.stderr.write(f"unknown command: {command}\n")
    return 2


# --- Hashing and listing -------------------------------------------------------------------------


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _hashes(directory: str) -> dict[str, str]:
    """`{path relative to the directory: sha256}` for every regular file under it.

    Symlinks are followed by `is_file()` and there are none in an input archive; a directory is not
    a file and contributes nothing, which is why the set equality in `check_inputs` is over files.
    """
    base = Path(directory)
    return {
        str(path.relative_to(base)): _sha256(path)
        for path in sorted(base.rglob("*"))
        if path.is_file()
    }


def _published(directory: str) -> dict[str, str]:
    """What the manifest's checksum block covers: every published file **except** two kinds.

    The manifest cannot list itself — it would have to contain its own hash — and it does not list a
    `.asc`, because a signature is what verifies the manifest rather than something the manifest
    verifies. Everything else is in, `verify-release.sh` and `ADVISORIES.txt` included: a tampered
    verifier is a real attack, and user story 4 asks for *one* command that checks every published
    file's hash at once.
    """
    return {
        name: value
        for name, value in _hashes(directory).items()
        if not (name.startswith("manifest-") and name.endswith(".txt"))
        and not name.endswith(".asc")
    }


def _closures(inputs: Path) -> dict[str, list[str]]:
    """`build/inputs/CLOSURES.txt`, written by the fetcher and archived with the bytes it describes.

    The appliance/toolchain split is not recoverable from the `.apk` files alone — the two closures
    overlap — and re-resolving it would need the network the build does not have. So the fetcher
    records it, the archive carries it, and `build/inputs.sha256` pins it like everything else.
    """
    found: dict[str, list[str]] = {}
    current: list[str] | None = None
    for raw in _read(str(inputs / "CLOSURES.txt")).splitlines():
        line = raw.strip()
        if line.startswith("# @closure "):
            current = found.setdefault(line.split()[-1], [])
        elif line and current is not None:
            current.append(line)
    return found


def _aports_commit(inputs: Path) -> str:
    """The `# @aports-commit alpine-release <sha>` marker at the head of `CLOSURES.txt`.

    `alpine-release` is the branch's release marker and this build neither installs nor archives it,
    so its recipe commit is answerable only while an `APKINDEX` is in hand — which the release is
    not (#68). The fetcher asks and records; this reads what was archived and hashed. A missing
    marker is a hard failure: a manifest that silently names no commit is a written offer pointing
    nowhere.
    """
    for raw in _read(str(inputs / "CLOSURES.txt")).splitlines():
        if raw.startswith("# @aports-commit "):
            return raw.split()[-1]
    raise SystemExit(
        f"{inputs / 'CLOSURES.txt'} carries no `# @aports-commit` marker: "
        "re-run build/fetch-inputs.sh, or unpack a release input archive that has one"
    )


def _tree_manifest(root: str) -> str:
    """One line per path: mode, owner, and either a content hash or a symlink target.

    The first rung of `docs/reproducible-build.md`'s failure ladder. A single hash of the initramfs
    says two builds differ; this says *which file*, and whether it differs in content or in a
    permission bit — which is the difference between a useful bug report and "the hashes differ".
    """
    base = Path(root)
    lines = []
    for path in sorted(base.rglob("*")):
        info = path.lstat()
        relative = str(path.relative_to(base))
        if stat.S_ISLNK(info.st_mode):
            content = "-> " + os.readlink(path)
        elif path.is_dir():
            content = "dir"
        else:
            content = _sha256(path)
        lines.append(f"{info.st_mode:06o} {info.st_uid}:{info.st_gid} {content} /{relative}")
    return "\n".join(lines)


# --- What git says ------------------------------------------------------------------------------


def _git(source: str, *arguments: str) -> tuple[int, str]:
    """One git command against the tree being built, and never a write.

    `-c safe.directory` because the build reads a bind-mounted repository owned by another uid, and
    git's ownership check would otherwise refuse to look at it at all.
    """
    result = subprocess.run(
        ["git", "-C", source, "-c", f"safe.directory={source}", *arguments],
        capture_output=True,
        text=True,
    )
    return result.returncode, result.stdout.strip()


def _git_facts(source: str) -> "verify.GitFacts":
    """The five facts the release-mode refusals and the stage-3 assertion are decided from.

    Gathered here, judged in `verify.py`. That is the whole reason the four refusals are pure
    functions rather than shell conditions: a hostile set of facts is a value object away.
    """
    _, head = _git(source, "rev-parse", "HEAD")
    status_code, status = _git(source, "status", "--porcelain")
    tag_code, tag = _git(source, "describe", "--exact-match", "--tags", "HEAD")
    tag = tag if tag_code == 0 else ""
    signed = _git(source, "tag", "-v", tag)[0] == 0 if tag else False
    date = _git(source, "log", "-1", "--format=%ct", f"{tag}^{{commit}}")[1] if tag else ""
    return verify.GitFacts(
        head_commit=head,
        dirty=bool(status) or status_code != 0,
        tag=tag,
        tag_signed=signed,
        tag_commit_date=date,
    )


def _source_date_epoch(source: str) -> str:
    """`SOURCE_DATE_EPOCH` as the build set it, or the commit date of HEAD if nothing set it.

    The fallback is not a second contract: it is the same derivation `build/mkiso.sh` performs, in
    one place, so that a subcommand run by hand judges what a build would have judged.
    """
    return os.environ.get("SOURCE_DATE_EPOCH") or _git(source, "log", "-1", "--format=%ct")[1]


def _write_release(source: str, destination: str) -> int:
    """Generate `/etc/aobs-release`, and print the row the appliance will show.

    A mutation in a module otherwise about reading, and here for the same reason
    `prune-busybox-applets` is: it is a *policy* — what a build is allowed to call itself — and a
    policy that decides whether an image looks like a release is exactly the kind that must be
    tested. `build/verify.py`'s `check_embedded_release` is the independent judge of the result, so
    a generator that gets this wrong fails the build in stage 3 rather than shipping.
    """
    git = _git_facts(source)
    epoch = _source_date_epoch(source)
    is_release = verify.is_release_build(git.tag, git.dirty)
    fields = {
        "release": git.tag if is_release else verify.DEVELOPMENT,
        "released": verify.utc_date(epoch),
        "git-commit": git.head_commit,
        "source-date-epoch": epoch,
        "dirty": "yes" if git.dirty else "no",
    }
    text = "".join(f"{key}: {value}\n" for key, value in fields.items())
    output = Path(destination)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")

    # The fields, not the row. How the row is *worded* — `DEVELOPMENT BUILD`, the 12-hex prefix, the
    # separator — belongs to `aobs/core/release.py` and to nothing else; re-deriving it here for a
    # build-log line would mean a change to the prefix length silently diverging the two.
    print(" ".join(f"{key}={value}" for key, value in fields.items()))
    return 0


# --- The manifest ------------------------------------------------------------------------------

_MANIFEST_HEADER = """\
# aobs release manifest — {release}
#
# This file is what the signature covers. The ISO is not signed directly: it is named here, so
# verifying this file and then hashing the ISO tells you *which inputs produced that ISO* — which is
# what independent reproduction needs and what a bare signature over the ISO cannot say.
#
# Read it with `cat`. Check the files published beside it with:
#
#     grep -E '^[0-9a-f]{{64}}  ' {manifest_name} | sha256sum -c -
#
# The `grep` is not decoration: `sha256sum -c` reads this whole file as a checksum list and fails on
# every comment and `key: value` line. Measured against busybox coreutils — without the grep, exit
# status 1 and a `comment line: FAILED` for every one of them.

format: {format}
release: {release}
released: {released}

# What was built, and from what.

git-tag: {git_tag}
git-commit: {git_commit}
source-date-epoch: {source_date_epoch}
iso-name: {iso_name}

# The sha256 of `build/inputs.sha256` as committed at the tag above. This is the field that binds the
# archive to the source: without it, an archive replaced in place on GitHub Releases would still
# match its own hash. With it, the archive is pinned to a list a reader can regenerate from a
# `git checkout` of the tag.

inputs-list-sha256: {inputs_list_sha256}

# The inputs. These live inside the archive named in the file list below, so their hashes are
# recorded as fields rather than as checksum lines: a reader running the `sha256sum -c` one-liner has
# the archive on disk, not its contents.
#
# `aports-commit` is the aports recipe commit of `alpine-release`, the branch's release-marker
# package. It is a pointer into a history that does not expire, not the whole record — the complete
# per-package licence and aports commit is the `NOTICE` inside the archive. `alpine-release` is
# neither installed nor archived, so the fetcher records its commit in `CLOSURES.txt` while an
# index is still in hand and this reads it from there (#68).

alpine-branch: {alpine_branch}
aports-commit: {aports_commit}
{inputs}
# Who is expected to have signed this file. Listed here so a verifier can tell "one of two signers"
# from "one signer, and I have no idea whether there should be another" — the manifest cannot list
# the signatures over itself, but it can list who was supposed to make them. **A verifier must not
# trust these lines to decide who may sign**; `verify-release.sh` hardcodes the fingerprints it
# accepts, because trusting the manifest to say who may sign it is circular.

{signers}
# The published files. This block is `sha256sum -c` format on purpose.

{published}"""


def _manifest(source: str, release_file: str, published: str) -> str:
    """The manifest, generated from the release file and the archive rather than assembled by hand.

    `release` and `git-commit` come from `/etc/aobs-release` (#61) — one source, so there is nothing
    for the image and the manifest to disagree about. Everything else is read off files.
    """
    root = Path(source)
    embedded = verify.parse_fields(_read(release_file))
    release = embedded["release"]
    inputs = root / "build" / "inputs"

    input_lines = [
        f"input-{name}: {path.name} sha256={_sha256(path)}"
        for name, path in (
            ("base-rootfs", next(inputs.glob("alpine-minirootfs-*.tar.gz"))),
            ("kernel", next(inputs.glob("linux-*.tar.xz"))),
        )
    ]
    for closure, packages in _closures(inputs).items():
        input_lines.append(f"input-apks-{closure}: {len(packages)} packages")

    aports = _aports_commit(inputs)

    files = _published(published)
    iso = next((name for name in files if name.endswith(".iso")), "bitcoin-signer-amd64.iso")

    return _MANIFEST_HEADER.format(
        format=verify.MANIFEST_FORMAT,
        manifest_name=f"manifest-{release}.txt",
        release=release,
        released=embedded["released"],
        git_tag=release,
        git_commit=embedded["git-commit"],
        source_date_epoch=embedded["source-date-epoch"],
        iso_name=iso,
        inputs_list_sha256=_sha256(root / "build" / "inputs.sha256"),
        alpine_branch=_alpine_branch(root),
        aports_commit=aports,
        inputs="".join(f"{line}\n" for line in input_lines),
        signers="".join(f"signer: {fingerprint} {who}\n" for fingerprint, who in verify.SIGNERS),
        published="".join(f"{files[name]}  {name}\n" for name in sorted(files)),
    )


def _alpine_branch(root: Path) -> str:
    """`ALPINE_BRANCH` as `build/fetch-inputs.sh` declares it. One declaration, read twice."""
    for line in _read(str(root / "build" / "fetch-inputs.sh")).splitlines():
        if line.startswith("ALPINE_BRANCH="):
            return line.split("=", 1)[1].strip()
    return ""


def _prune_busybox_applets(rootfs: str) -> int:
    """Remove the applet symlinks whose names a published claim forbids.

    Alpine's busybox package ships a symlink for a getty, a login, and most of a network toolbox.
    Deleting them is what makes "no getty, no network utility in the rootfs" true of the image.

    **Only symlinks are removed, never a real file.** A regular file with a forbidden name is a
    dependency of something, and quietly deleting it would trade a false claim for a broken
    appliance — so it is left where it is and `check_rootfs` fails the build on it. The verifier is
    an independent judge of the result: an applet nobody thought to list here fails the build
    rather than shipping.

    What this does **not** do is make the applets unreachable. `busybox wget` still exists as code
    inside the one binary, and no file listing can see that. What makes it inert is `CONFIG_NET=n`,
    checked in the kernel config where the claim actually lives — `docs/boot-pipeline.md` says the
    same thing about `sh`: busybox is in the image, Python can `os.execv` anything, and the true
    claim is the one the build checks.
    """
    root = Path(rootfs)
    for directory in ("bin", "sbin", "usr/bin", "usr/sbin"):
        base = root / directory
        if not base.is_dir():
            continue
        for entry in sorted(base.iterdir()):
            if entry.name not in verify.FORBIDDEN_BASENAMES or not entry.is_symlink():
                continue
            target = os.readlink(entry)
            if "busybox" not in target:
                continue
            entry.unlink()
            print(f"/{directory}/{entry.name} -> {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
