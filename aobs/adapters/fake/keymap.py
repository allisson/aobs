"""The `Keymap` fake: records what was applied.

The real adapter shells out to `loadkeys` and has nothing to report; the fake's whole job is to be
observable. `docs/boot-pipeline.md` names typing a passphrase through the wrong map as the worst
failure mode in the appliance, and the assertion that catches it is *the layout the user chose is
the layout that was applied, exactly once* — which needs a recorder on this side of the port.
"""

from __future__ import annotations

from collections.abc import Sequence

#: The small set of Latin maps `docs/boot-pipeline.md` calls for, US first. The real adapter reads
#: what the ISO actually ships; this list is what the harness offers the picker.
LAYOUTS: tuple[str, ...] = (
    "us",
    "uk",
    "de",
    "fr",  # AZERTY
    "br-abnt2",
    "es",
    "it",
    "dvorak",
)


class RecordingKeymap:
    def __init__(self, layouts: Sequence[str] = LAYOUTS) -> None:
        self._layouts = tuple(layouts)
        self.applied: list[str] = []

    def layouts(self) -> Sequence[str]:
        return self._layouts

    def apply(self, name: str) -> None:
        if name not in self._layouts:
            raise ValueError(f"no such layout: {name}")
        self.applied.append(name)
