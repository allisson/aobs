"""The four ports.

`docs/test-harness.md` fixes them, and each has exactly two adapters. This package declares the
interfaces; `aobs/adapters/fake/` holds the harness half and the real half lands with the
appliance's own spec.
"""

from .entropy_source import EntropySource
from .frame_source import Frame, FrameSource
from .power import Power
from .screen import Screen

__all__ = ["EntropySource", "Frame", "FrameSource", "Power", "Screen"]
