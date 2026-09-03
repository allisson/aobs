"""Alpine package metadata, read from the two places that hold it.

    printf 'busybox-1.37.0-r31.apk\\n' | python3 build/apkindex.py /tmp/indexes
    python3 build/apkindex.py /tmp/indexes --aports-commit alpine-release
    python3 build/apkindex.py build/inputs --notice

Three questions, two sources, and #68 is why they are two.

**Which repository is a package in** — the only question an `APKINDEX.tar.gz` can answer, because
membership is a fact about Alpine's repositories and not about the file. `apk` resolves a local
repository from `<repo>/<arch>/APKINDEX.tar.gz`, so `main` and `community` cannot be flattened into
one directory, and the membership has to come from somewhere. It comes from the index rather than
from a guess at the URL. **A package in neither index is a hard failure**: skipping one silently
would produce an archive that passes its own checksum list and cannot build, and the failure would
surface in 2030 to somebody with no way to tell it from a tampered release.

This is asked at fetch time, when `build/fetch-inputs.sh` has just downloaded the indexes to a
scratch directory, and the answer is recorded in the archive as directory placement. **The indexes
themselves are not archived** (#68): Alpine regenerates and re-signs them whenever anything lands in
the branch, so their bytes move with nothing this repository depends on having changed — which made
them unpinnable by hash and made `aobs-inputs-<release>.tar` non-deterministic between two
fetches hours apart. `build/mkiso.sh` generates its own index from the archived `.apk` files.

**Which single aports commit the manifest names** — also the index, and for a reason worth stating:
the manifest uses `alpine-release`'s, and **`alpine-release` is neither installed nor archived**.
That package *is* the branch's release marker, rebuilt for each point release, so its recipe commit
locates the branch state — which is exactly why it is the right pointer and exactly why the archive
cannot answer for it. `build/fetch-inputs.sh` asks here, while it still has an index, and records
the answer in `build/inputs/CLOSURES.txt`; `build/gather.py` reads it from there, so a manifest can
still be generated from an unpacked release asset with no index and no network.

**What the archive redistributes** is answered from each `.apk`'s own `.PKGINFO` — the file Alpine's
index is itself generated from, which is why the two agree field for field. `--notice` emits the
per-package record that meets the source obligation: name, version, licence *as Alpine's own
metadata declares it*, the origin aport, and the **aports git commit** that built it. #57 settled
that buildable sources are explicitly not promised — Alpine's distfiles retention is unverified and
plausibly as lossy as its `.apk` retention — and what the commit does guarantee is locatable recipes
in a history that does not expire. Reading it from the bytes the archive carries is what makes the
NOTICE a statement about those bytes rather than about a file fetched beside them.

This is a fetch-time tool, not a build-time judgement. It reads files and prints text; it decides
nothing about the artifact, which is why it is not in `build/verify.py`.
"""

from __future__ import annotations

import gzip
import io
import re
import sys
import tarfile
from pathlib import Path

REPOSITORIES = ("main", "community")

#: The copyleft families whose sources #71 archives. Matched as whole tokens against Alpine's own
#: `L:` field — the same string `--notice` prints — because that field is what #70's census was
#: taken over and what makes the 446.3 MB figure reproducible from `build/inputs.sha256`.
#:
#: **This is Alpine's declaration, not an audit.** #70 was explicit that nobody read the packages'
#: own `COPYING` files, so a package Alpine mislabels as permissive is a package whose source this
#: predicate does not fetch. The predicate is deliberately wider than the strict obligation to leave
#: room for that: GPLv2-only is the 18 `.apk` files with no other permitted route, and everything
#: else here is fetched so that no copyleft claim in `NOTICE` rests on a host this project does not
#: control. MPL is matched at 2.0 and later only, following the census that produced the figure.
_COPYLEFT = re.compile(r"(?:^|[^A-Za-z0-9])(?:[AL]?GPL|MPL-[2-9]|EPL|CDDL)(?![A-Za-z])", re.I)


def is_copyleft(licence: str) -> bool:
    """Does this `L:` field oblige us to accompany the binary with its source?

    A miss here is silent in the direction that matters: the release ships, the archive verifies
    against its own list, and a GPL binary goes out with no source beside it. That is why the
    predicate is a tested pure function and not a `grep -i gpl` in the fetch script.
    """
    return bool(_COPYLEFT.search(licence))


def copyleft_origins(stanzas: list[dict[str, str]]) -> list[tuple[str, str, str]]:
    """The distinct copyleft origins to fetch source for: `(origin, aports-commit, licence)`, sorted.

    The fetcher walks *origins*, not packages — 18 `.apk` files come from 9 origin aports, and one
    aport builds one set of tarballs however many subpackages it splits into.

    **Two `.apk` files from one origin at two different commits is a hard failure.** It should not
    happen inside a single branch snapshot, and if it does there is no single recipe to fetch:
    picking either one archives source that did not build the other binary, which is worse than no
    source at all because it looks like compliance.
    """
    found: dict[str, tuple[str, str]] = {}
    for stanza in stanzas:
        origin = stanza.get("origin", "")
        if not origin or not is_copyleft(stanza.get("licence", "")):
            continue
        commit = stanza.get("aports-commit", "")
        seen = found.setdefault(origin, (commit, stanza.get("licence", "")))
        if seen[0] != commit:
            raise SystemExit(
                f"{origin} is recorded at two aports commits, {seen[0]} and {commit}: "
                "there is no single recipe to archive source from"
            )
    return sorted((origin, commit, licence) for origin, (commit, licence) in found.items())

#: `P:` name, `V:` version, `c:` aports commit. Alpine's index format is stanzas of `KEY:value`
#: lines separated by blank lines, and apk's own filenames are `<P>-<V>.apk`. Only what the two
#: index questions need — membership, and the commit of a package the archive does not carry.
#: Everything about a package the archive *does* carry is read off `.PKGINFO` instead.
_INDEX_FIELDS = {"P": "name", "V": "version", "c": "aports-commit"}

#: The `.PKGINFO` half of the same map. `apk index` copies these into the index verbatim, so a
#: record built from here is the record Alpine's index would have given — established by diffing a
#: regenerated stanza against the published one, field for field.
_PKGINFO_FIELDS = {
    "pkgname": "name",
    "pkgver": "version",
    "license": "licence",
    "origin": "origin",
    "commit": "aports-commit",
}


def index(path: Path) -> dict[str, dict[str, str]]:
    """`APKINDEX.tar.gz` → `{name-version.apk: {name, version, aports-commit}}`."""
    with tarfile.open(path, "r:gz") as archive:
        member = archive.extractfile("APKINDEX")
        if member is None:  # pragma: no cover - a truncated index is not a case to paper over
            raise SystemExit(f"{path} carries no APKINDEX member")
        text = member.read().decode("utf-8")

    found: dict[str, dict[str, str]] = {}
    stanza: dict[str, str] = {}

    def flush() -> None:
        if stanza.get("name") and stanza.get("version"):
            found.setdefault(f"{stanza['name']}-{stanza['version']}.apk", dict(stanza))

    for line in text.splitlines() + [""]:
        key, separator, value = line.partition(":")
        if not separator:
            flush()
            stanza.clear()
        elif key in _INDEX_FIELDS:
            stanza[_INDEX_FIELDS[key]] = value
    flush()
    return found


def pkginfo(path: Path) -> dict[str, str]:
    """`.apk` → `{name, version, licence, origin, aports-commit}`, from its own `.PKGINFO`.

    An `.apk` is *concatenated* gzip streams — signature, control, data — each a tar of its own.
    `gzip` joins the members transparently; `ignore_zeros` is what carries `tarfile` past the
    end-of-archive padding between them, and without it the control segment holding `.PKGINFO` is
    never reached.
    """
    with gzip.open(path, "rb") as stream:
        joined = io.BytesIO(stream.read())
    with tarfile.open(fileobj=joined, mode="r:", ignore_zeros=True) as archive:
        try:
            member = archive.extractfile(".PKGINFO")
        except KeyError:
            member = None
        if member is None:
            raise SystemExit(f"{path} carries no .PKGINFO")
        text = member.read().decode("utf-8")

    stanza: dict[str, str] = {}
    for line in text.splitlines():
        key, separator, value = line.partition(" = ")
        if separator and key in _PKGINFO_FIELDS:
            stanza.setdefault(_PKGINFO_FIELDS[key], value)
    return stanza


def _everything(indexes: Path) -> dict[str, tuple[str, dict[str, str]]]:
    """`{name-version.apk: (repository, stanza)}` across both indexes, `main` winning a tie."""
    where: dict[str, tuple[str, dict[str, str]]] = {}
    for repository in REPOSITORIES:
        path = indexes / "apks" / repository / "x86_64" / "APKINDEX.tar.gz"
        for package, stanza in index(path).items():
            where.setdefault(package, (repository, stanza))
    return where


def _archived(inputs: Path) -> list[Path]:
    """Every `.apk` actually in `build/inputs/apks/`, sorted. What the archive redistributes."""
    return sorted(
        (
            path
            for repository in REPOSITORIES
            for path in (inputs / "apks" / repository / "x86_64").glob("*.apk")
        ),
        key=lambda path: path.name,
    )


NOTICE_HEADER = """\
# Third-party binaries redistributed in this archive

This archive carries Alpine Linux `.apk` packages **unmodified**, exactly as Alpine published them,
with their upstream signatures intact. Alpine's own `APKINDEX.tar.gz` is deliberately *not* here:
its bytes are re-signed on Alpine's schedule rather than on this project's, which made the archive
non-reproducible between two fetches of the same package set. `build/mkiso.sh` generates its own
index from the `.apk` files below and installs with `--allow-untrusted`, because the trust those
files carry is the sha256 list in this repository's git history, checked before any of them is read.

Several are under a copyleft licence. `busybox` is **GPL-2.0-only**, which is the hard case: GPLv2
§3 offers no third-party-server route, so a pointer at somebody else's host is not one of the three
things §3 permits. (`kbd` is GPL-2.0-**or-later** and `grub` GPL-3.0-or-later; both carry the "or
later" escape and could have used GPLv3 §6(d). Only the first of those three is the hard case, and
an earlier version of this file named all three as if they were alike.)

The per-package licence below is the one declared in each package's own `.PKGINFO` — the same file
Alpine's index is generated from — and the **aports commit** is the commit of
<https://gitlab.alpinelinux.org/alpine/aports> that built that package.

**The corresponding source is published beside this archive**, as `aobs-sources-<release>.tar` on
the same GitHub release, and its sha256 is bound by the signed manifest's `sources-list-sha256`.
It carries, for every origin aport below whose licence names a GPL, LGPL, AGPL, MPL-2, EPL or CDDL
term: the `APKBUILD` and every patch and local file at the exact commit recorded here, plus the
upstream tarballs that recipe names. That is an accompaniment under GPLv2 §3(a) rather than an offer
or a pointer — the bytes travel with the binaries instead of depending on a host nobody here
controls.

For a package whose licence names none of those terms, no source is archived and the recipe commit
below is the record.

  package | licence | origin aport | aports commit
"""


def notice(inputs: Path) -> str:
    lines = [NOTICE_HEADER]
    for path in _archived(inputs):
        stanza = pkginfo(path)
        lines.append(
            "  {} | {} | {} | {}".format(
                path.name,
                stanza.get("licence", "declared by no metadata"),
                stanza.get("origin", path.name),
                stanza.get("aports-commit", "not recorded in .PKGINFO"),
            )
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    if not argv:
        sys.stderr.write(__doc__ or "")
        return 2
    directory = Path(argv[0])
    rest = argv[1:]

    if rest[:1] == ["--notice"]:
        sys.stdout.write(notice(directory))
        return 0

    if rest[:1] == ["--copyleft-origins"]:
        # One line per origin: `origin<TAB>aports-commit<TAB>licence`, for `build/fetch-sources.sh`
        # to walk. Read from the archived `.apk` files rather than from an index, so it answers the
        # same way in 2030 from an unpacked release asset with no network (#68).
        for origin, commit, licence in copyleft_origins([pkginfo(p) for p in _archived(directory)]):
            print(f"{origin}\t{commit}\t{licence}")
        return 0

    if rest[:1] == ["--aports-commit"]:
        wanted = rest[1]
        for _, stanza in _everything(directory).values():
            if stanza.get("name") == wanted:
                print(stanza.get("aports-commit", ""))
                return 0
        sys.stderr.write(f"{wanted} is in neither APKINDEX\n")
        return 1

    where = _everything(directory)
    wanted_packages = sorted({line.strip() for line in sys.stdin if line.strip()})
    missing = [package for package in wanted_packages if package not in where]
    if missing:
        sys.stderr.write("in neither APKINDEX: " + ", ".join(missing) + "\n")
        return 1
    for package in wanted_packages:
        print(where[package][0], package)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
