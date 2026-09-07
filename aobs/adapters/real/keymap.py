"""The `Keymap` real adapter: `loadkeys`.

Smallest of the four and deliberately first, because its failure is the one that is silent and
permanent. `docs/boot-pipeline.md`:

> A user on AZERTY or ABNT2 who types a passphrase through a US map creates a wallet they can
> never reopen — no error, no signal, discovered when the funds are gone.

So this adapter never assumes success. `loadkeys` exiting non-zero raises, and the raise reaches
the application's unrecoverable-fault path, which names the failure on a screen — while the picker
is still the first screen and no secret exists yet. A silently failed application is exactly the
wrong-map failure the port exists to prevent.

Two decisions shape the rest:

* **The offered layouts are the maps the image actually ships**, read from the keymap tree, not a
  hardcoded list. The fake's list is what the harness offers the picker; the two are allowed to
  differ, and the picker is written against the port rather than against either list.
* **The default layout is a genuine no-op.** PID 1 has already set the console keymap
  (`docs/boot-pipeline.md`, boot sequence step 2), so US is loaded before the picker draws.
  Accepting it re-applies nothing and therefore cannot fail.
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Iterable, Sequence
from pathlib import Path

from aobs.ports.keymap import DEFAULT_LAYOUT

#: Where `kbd` installs its maps. Alpine's `kbd-misc` puts them under an architecture directory
#: and then a language one, so the tree is walked rather than listed.
KEYMAP_ROOT = Path("/usr/share/keymaps")

LOADKEYS = "loadkeys"

#: The small set of Latin maps `docs/boot-pipeline.md` calls for, in the order the picker lists
#: them, US first. This is a *filter over what is installed*, never the answer by itself: a name
#: here that the image does not ship is not offered, because offering a map that cannot load is
#: the failure this adapter exists to prevent.
#:
#: **These are not the fake's names, and they are not meant to be.** `docs/test-harness.md` allows
#: the two lists to differ precisely because the harness invents its list and this one is read off
#: the image: Alpine's `kbd-misc` ships the **xkb** naming, where the UK map is `gb`, the
#: Brazilian ABNT2 map is `br`, and Dvorak is `us-dvorak`. Naming them the way the fake does would
#: have offered a picker whose non-US entries all failed to load — which is the failure this port
#: exists to catch, arrived at by being tidy.
PREFERRED: tuple[str, ...] = (
    "us",
    "gb",
    "de",
    "fr",  # AZERTY
    "br",  # ABNT2
    "es",
    "it",
    "us-dvorak",
)

#: The suffixes `kbd` uses, longest first so `.map.gz` is not read as `.map` plus rubbish.
MAP_SUFFIXES = (".map.gz", ".kmap.gz", ".map", ".kmap")

#: A layout name is a bare word that reaches `loadkeys` as `argv[1]`. There is no shell, so this
#: is not an injection guard — it is a guard against a name that begins with `-` being read as an
#: option, and against a path component reaching a loader that searches by name.
_VALID_NAME = re.compile(r"\A[a-z][a-z0-9._-]*\Z")


class KeymapError(RuntimeError):
    """`loadkeys` did not apply the layout. Named, so the fault screen can name it."""


def layout_name(filename: str) -> str | None:
    """The layout a keymap filename offers, or `None` if it is not a keymap at all.

    A pure function from a directory listing to a name, which is the whole of what can be decided
    about the keymap tree without a keymap tree.
    """
    for suffix in MAP_SUFFIXES:
        if filename.endswith(suffix):
            name = filename[: -len(suffix)]
            return name if _VALID_NAME.match(name) else None
    return None


def offered(installed: Iterable[str]) -> tuple[str, ...]:
    """The layouts the picker lists: `PREFERRED`, in that order, kept to what is installed.

    `DEFAULT_LAYOUT` is always offered whether or not a file for it was found, because it is not
    loaded from a file at all — it is the map the kernel already has, and accepting it applies
    nothing. An image whose keymap tree is missing entirely still gets a working picker with one
    honest entry rather than an empty list.
    """
    present = set(installed)
    return tuple(
        name for name in PREFERRED if name == DEFAULT_LAYOUT or name in present
    )


class LoadkeysKeymap:
    def layouts(self) -> Sequence[str]:
        return offered(self._installed())

    def apply(self, name: str) -> None:
        """Load `name`, or raise. Called once, before any secret exists.

        `stdout` and `stderr` go nowhere: there is no logging on this appliance, nothing on screen
        may quote a subprocess, and the exit status is the whole of what this needs to read.
        """
        if name == DEFAULT_LAYOUT:
            # Already loaded by PID 1. Re-applying it could only introduce a failure that
            # accepting the default is specified never to have.
            return
        if not _VALID_NAME.match(name):
            raise KeymapError("not a layout name")
        try:
            result = subprocess.run(
                [LOADKEYS, name],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        except OSError as error:  # loadkeys is not in the image
            raise KeymapError("the keymap loader could not be run") from error
        if result.returncode != 0:
            raise KeymapError("the keymap loader refused the layout")

    def _installed(self) -> Iterable[str]:
        try:
            entries = list(KEYMAP_ROOT.rglob("*"))
        except OSError:  # pragma: no cover - an unreadable tree is one with no maps in it
            return ()
        names = (layout_name(entry.name) for entry in entries)
        return [name for name in names if name is not None]
