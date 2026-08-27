"""The `EntropySource` fake: fixed bytes.

Deterministic, so a test that exports a wallet gets the same container every time. It is a
counter through SHA-256 rather than a constant, because a constant would hide a caller that draws
the salt and the nonce from the same call.
"""

from __future__ import annotations

import hashlib


class FixedEntropySource:
    def __init__(self, seed: bytes = b"aobs-fake-entropy") -> None:
        self._seed = seed
        self._counter = 0
        self.calls: list[int] = []
        #: How many `ready()` calls answer *not yet* before the pool comes up. Zero — a pool that
        #: was ready before it was asked — is the ordinary case, so it is the default and every
        #: existing test keeps its behaviour. A test that wants the wait screen sets it.
        self.not_ready_for = 0
        self.readiness_asked = 0

    def ready(self) -> bool:
        self.readiness_asked += 1
        return self.readiness_asked > self.not_ready_for

    def random_bytes(self, count: int) -> bytes:
        self.calls.append(count)
        out = b""
        while len(out) < count:
            out += hashlib.sha256(self._seed + self._counter.to_bytes(4, "big")).digest()
            self._counter += 1
        return out[:count]
