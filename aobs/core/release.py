"""What the appliance says about itself, as one row of text.

`aobs v0.1.0 · 4f1c8a6e2b90 · 2026-09-14` — and #61 settled every part of it:

- **The 12-hex commit prefix is what makes the line checkable.** A version alone cannot distinguish
  a rebuild from the published build; the prefix can be matched against the manifest a user has
  already verified, which is the only reason the line is worth showing.
- **Nothing derived from the image can be embedded in it** — not the ISO hash, not the manifest
  hash, and not the initramfs hash either, since the initramfs *is* the whole system. Version,
  commit and `SOURCE_DATE_EPOCH` are the complete embeddable set, so the truncation trade-off #61
  posed never existed.
- **It identifies, it does not attest.** A modified image can print anything it likes. What the row
  is for is the user who booted a stick found in a drawer and wants to know what they are about to
  type a mnemonic into; the README says so in those words, and so does `docs/boot-pipeline.md`.
- **A build that is not a release says `DEVELOPMENT BUILD` and never a version-shaped string**, so
  that nobody signs with one months later believing it was a release.

The date is a **field, not a computation.** `tests/test_structure.py` forbids the core `datetime`
and `time`, and that rule is the right one — the appliance has no clock it has any reason to trust.
So the build formats `source-date-epoch` once, writes it into `/etc/aobs-release` as `released:`,
and `build/verify.py` asserts the two agree. Nothing here asks what time it is.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Where the build puts it. A stage-1 output, so stage 3 can assert it against the tag before
#: `cpio` puts it inside an archive.
RELEASE_PATH = "/etc/aobs-release"

#: What `release:` says when the build was not cut from a clean tag. Matches `build/verify.py`.
DEVELOPMENT = "development"

#: What the user sees in place of a version for one of those. Deliberately not version-shaped.
DEVELOPMENT_LABEL = "DEVELOPMENT BUILD"

#: How much of the commit the row carries. Twelve hex is unambiguous for any repository this size
#: and short enough that the row clears the 96-column cap with room to spare.
COMMIT_PREFIX = 12

#: Where advisories live, as a static string. **The appliance attempts no detection of its own**
#: (#62): there is no trustworthy clock offline, a wrong "this build is old" is worse than silence,
#: and a modified image would lie about it anyway. So the row points, and is written so that it
#: cannot be mistaken for something that checked.
ADVISORIES_URL = "github.com/allisson/aobs/blob/main/ADVISORIES.txt"
#: 92 columns, which is what fixes the wording: the 96-column cap (`aobs/ui/geometry.py`) is a hard
#: budget, and a line that wraps on the first screen reads as a layout defect rather than a pointer.
ADVISORIES_LINE = f"Advisories: {ADVISORIES_URL} — this appliance cannot check."

#: The separator. A middle dot rather than a pipe or a dash: the row sits under a keymap picker
#: whose whole purpose is that the user may be on any Latin layout, and a character they cannot
#: type is one they will not mistake for something they are meant to enter.
SEPARATOR = " · "


@dataclass(frozen=True)
class Release:
    """`/etc/aobs-release`, parsed. A value object: no I/O, no clock, no filesystem.

    The read lives in `aobs/adapters/release.py`, which is also where a missing file becomes a
    development build — the appliance running from a source tree has no `/etc/aobs-release` at all,
    and that is a development build by every definition this project uses.
    """

    #: `v0.1.0`, or `development`.
    release: str
    #: `YYYY-MM-DD`, formatted by the build from `source-date-epoch`.
    released: str
    #: The full 40-hex commit. The row shows the first `COMMIT_PREFIX` characters of it.
    commit: str
    #: Whether the tree the build ran against had uncommitted changes.
    dirty: bool

    @property
    def is_development(self) -> bool:
        return self.release == DEVELOPMENT

    @property
    def version_label(self) -> str:
        return DEVELOPMENT_LABEL if self.is_development else self.release

    @property
    def commit_label(self) -> str:
        """The prefix, with `-dirty` when the tree was not clean.

        The suffix is on the *commit* and not on the version, because a dirty tree is a statement
        about which source produced the image and the commit is the part that names the source.
        """
        return self.commit[:COMMIT_PREFIX] + ("-dirty" if self.dirty else "")


#: The build always writes the file, so this is only ever reached from a source tree — a developer
#: running `python3 -m aobs` on a laptop, and the test suite. It says so on screen.
UNKNOWN = Release(release=DEVELOPMENT, released="unknown", commit="", dirty=True)


def parse(text: str) -> Release:
    """`/etc/aobs-release`'s `key: value` lines. Anything absent reads as unknown, never as a claim.

    A truncated or hostile file must not be able to make the appliance *look* like a release: every
    fallback here is towards `DEVELOPMENT`, and `release:` has to say a version explicitly for one
    to be displayed.
    """
    fields: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition(":")
        if separator and " " not in key:
            fields[key.strip()] = value.strip()
    return Release(
        release=fields.get("release", DEVELOPMENT) or DEVELOPMENT,
        released=fields.get("released", "unknown") or "unknown",
        commit=fields.get("git-commit", ""),
        dirty=fields.get("dirty", "yes") != "no",
    )


def identity_line(release: Release) -> str:
    """The row itself. One line, always three parts, never wider than the column cap.

    An empty commit — a source tree with no `/etc/aobs-release` — drops its part rather than
    printing an empty one, because `aobs DEVELOPMENT BUILD ·  · unknown` reads as a bug in the
    appliance rather than as the absence of a release.
    """
    parts = [f"aobs {release.version_label}"]
    if release.commit:
        parts.append(release.commit_label)
    parts.append(release.released)
    return SEPARATOR.join(parts)
