"""`EntropySource`: the randomness the core is handed.

Two adapters: `getrandom()`, the camera and the dice on the appliance; fixed bytes in the
harness. The core never reaches for randomness itself — that is what keeps `review()`, `mix()`
and `export_wallet()` pure functions of their arguments.
"""

from __future__ import annotations

from typing import Protocol


class EntropySource(Protocol):
    def random_bytes(self, count: int) -> bytes:
        """`count` bytes from the kernel CSPRNG.

        On the appliance this is `getrandom()` with `GRND_NONBLOCK` first, so an uninitialised
        pool becomes a message rather than a silent hang.
        """
        ...
