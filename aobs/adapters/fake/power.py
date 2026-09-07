"""The `Power` fake: records the call.

The real adapter does not return, so the fake's whole job is to be observable — a test asserts
that the session ended, which is a thing no real power-off could ever report.
"""

from __future__ import annotations


class RecordingPower:
    def __init__(self) -> None:
        self.powered_off = False

    def power_off(self) -> None:
        self.powered_off = True
