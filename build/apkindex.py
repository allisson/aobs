"""Everything read off Alpine's **verbatim** `APKINDEX.tar.gz` files in `build/inputs/apks/`.

    printf 'busybox-1.37.0-r31.apk\\n' | python3 build/apkindex.py build/inputs
    python3 build/apkindex.py build/inputs --notice
    python3 build/apkindex.py build/inputs --aports-commit alpine-release

Three questions, one parser:

**Which repository is a package in.** `apk` resolves a local repository from
`<repo>/<arch>/APKINDEX.tar.gz`, so `main` and `community` cannot be flattened into one directory,
and the membership has to come from somewhere. It comes from the index rather than from a guess at
the URL. **A package in neither index is a hard failure**: skipping one silently would produce an
archive that passes its own checksum list and cannot build, and the failure would surface in 2030 to
somebody with no way to tell it from a tampered release.

**What the archive redistributes.** `--notice` emits the per-package record that meets the source
obligation: name, version, licence *as Alpine's own metadata declares it*, the origin aport, and the
**aports git commit** that built it. #57 settled that buildable sources are explicitly not promised —
Alpine's distfiles retention is unverified and plausibly as lossy as its `.apk` retention — and what
the commit does guarantee is locatable recipes in a history that does not expire.

**Which single aports commit the manifest names.** `--aports-commit` prints one package's, and the
manifest uses `alpine-release`'s: that package *is* the branch's release marker, rebuilt for each
point release, so its recipe commit locates the branch state. It is a pointer, not the whole record;
the whole record is the NOTICE, and the manifest says so.

This is a fetch-time tool, not a build-time judgement. It reads files and prints text; it decides
nothing about the artifact, which is why it is not in `build/verify.py`.
"""

from __future__ import annotations

import sys
import tarfile
from pathlib import Path

REPOSITORIES = ("main", "community")

#: `P:` name, `V:` version, `L:` licence, `o:` origin aport, `c:` aports commit. Alpine's format is
#: stanzas of `KEY:value` lines separated by blank lines, and apk's own filenames are `<P>-<V>.apk`.
_FIELDS = {"P": "name", "V": "version", "L": "licence", "o": "origin", "c": "aports-commit"}


def index(path: Path) -> dict[str, dict[str, str]]:
    """`APKINDEX.tar.gz` → `{name-version.apk: {name, version, licence, origin, aports-commit}}`."""
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
        elif key in _FIELDS:
            stanza[_FIELDS[key]] = value
    flush()
    return found


def _everything(inputs: Path) -> dict[str, tuple[str, dict[str, str]]]:
    """`{name-version.apk: (repository, stanza)}` across both indexes, `main` winning a tie."""
    where: dict[str, tuple[str, dict[str, str]]] = {}
    for repository in REPOSITORIES:
        for package, stanza in index(inputs / "apks" / repository / "x86_64" / "APKINDEX.tar.gz").items():
            where.setdefault(package, (repository, stanza))
    return where


def _archived(inputs: Path) -> list[str]:
    """Every `.apk` actually in `build/inputs/apks/`, sorted. What the archive redistributes."""
    return sorted(
        path.name
        for repository in REPOSITORIES
        for path in (inputs / "apks" / repository / "x86_64").glob("*.apk")
    )


NOTICE_HEADER = """\
# Third-party binaries redistributed in this archive

This archive carries Alpine Linux `.apk` packages **unmodified**, exactly as Alpine published them,
with their upstream signatures intact — `build/mkiso.sh` installs them without
`--allow-untrusted`, which is only possible because neither the packages nor Alpine's own
`APKINDEX.tar.gz` was regenerated here.

Several are under the GPL (busybox, kbd, grub among them). The per-package licence below is the one
declared in Alpine's own metadata, and the **aports commit** is the commit of
<https://gitlab.alpinelinux.org/alpine/aports> that built that package. Written offer: the
corresponding build recipes are those in the aports tree at the commit named for each package.

**Buildable upstream sources are not promised.** Alpine's distfiles retention is unverified and
plausibly as lossy as its `.apk` retention, so a claim that the sources remain downloadable is a
claim nobody has checked. What the commits above do guarantee is locatable recipes in a history that
does not expire.

  package | licence | origin aport | aports commit
"""


def notice(inputs: Path) -> str:
    everything = _everything(inputs)
    lines = [NOTICE_HEADER]
    for package in _archived(inputs):
        entry = everything.get(package)
        if entry is None:
            raise SystemExit(f"in neither APKINDEX: {package}")
        _, stanza = entry
        lines.append(
            "  {} | {} | {} | {}".format(
                package,
                stanza.get("licence", "declared by no metadata"),
                stanza.get("origin", package),
                stanza.get("aports-commit", "not recorded in the index"),
            )
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    if not argv:
        sys.stderr.write(__doc__ or "")
        return 2
    inputs = Path(argv[0])
    rest = argv[1:]

    if rest[:1] == ["--notice"]:
        sys.stdout.write(notice(inputs))
        return 0

    if rest[:1] == ["--aports-commit"]:
        wanted = rest[1]
        for _, stanza in _everything(inputs).values():
            if stanza.get("name") == wanted:
                print(stanza.get("aports-commit", ""))
                return 0
        sys.stderr.write(f"{wanted} is in neither APKINDEX\n")
        return 1

    where = _everything(inputs)
    wanted = sorted({line.strip() for line in sys.stdin if line.strip()})
    missing = [package for package in wanted if package not in where]
    if missing:
        sys.stderr.write("in neither APKINDEX: " + ", ".join(missing) + "\n")
        return 1
    for package in wanted:
        print(where[package][0], package)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
