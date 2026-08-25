"""`Power`: ending the session.

Two adapters: a forced power-off on the appliance, and a recorder in the harness. A session ends
by the machine stopping, which is what makes the amnesia guarantee a property of the appliance
rather than of the app's own tidiness.
"""

from __future__ import annotations

from typing import Protocol


class Power(Protocol):
    def power_off(self) -> None:
        """End the session. Does not return on the appliance."""
        ...
