"""The four ports.

`docs/test-harness.md` fixes them, and each has exactly two adapters. This package declares the
interfaces; `aobs/adapters/fake/` holds the harness half and the real half lands with the
appliance's own spec.

There was a fifth name here, `Screen`, and it was wrong. Its two adapters were "Textual on the
console" and "Textual `run_test()`" — the *same* application under two drivers, not two
implementations of an interface — so the port sat between two halves of one thing. The app is the
display seam now, driven headless by `run_test()`, and `Keymap` took the vacated fourth slot:
applying a keyboard layout really does have two implementations, `loadkeys` and a recorder.
"""

from .entropy_source import EntropySource
from .frame_source import Frame, FrameSource
from .keymap import DEFAULT_LAYOUT, Keymap
from .power import Power

__all__ = ["DEFAULT_LAYOUT", "EntropySource", "Frame", "FrameSource", "Keymap", "Power"]
