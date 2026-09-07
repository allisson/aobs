"""`Keymap`: which keyboard layout the console is using.

Two adapters, which is what makes this a seam: `loadkeys` on the appliance, and a recorder in the
harness. The port exists because applying a keymap is *process state* — the picker is an app
screen, but what it does reaches outside the app entirely.

It is here rather than folded into the app because of what
[`docs/boot-pipeline.md`](../../docs/boot-pipeline.md) says the picker is for: a user on AZERTY or
ABNT2 who types a BIP39 passphrase through a US map creates a wallet they can never reopen — no
error, no signal, discovered when the funds are gone. A test has to be able to assert that the
layout the user chose is the layout that was actually applied, and it can only do that if applying
one is something it can watch.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

#: The layout selected when the user presses the confirm key without choosing anything. US is the
#: default because it is the layout the kernel already has loaded, so accepting it is genuinely a
#: no-op rather than a re-application.
DEFAULT_LAYOUT = "us"


class Keymap(Protocol):
    def layouts(self) -> Sequence[str]:
        """The layout names on offer, in the order the picker lists them.

        A small set of Latin maps, not every keymap Linux ships: the picker is read by someone who
        does not know what a keymap is, and a scrolling list of two hundred is worse than eight.
        """
        ...

    def apply(self, name: str) -> None:
        """Make `name` the console's layout. Called once, before any secret exists."""
        ...
