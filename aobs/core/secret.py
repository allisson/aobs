"""Holding a secret for as long as it must be held, and no longer.

`docs/secret-hygiene.md` is explicit about what this can and cannot claim. CPython copies freely
and the copies cannot be counted — `str` objects from key events, `bytes` slices through BIP32
derivation, interpreter temporaries. This module does not fix that and must not imply it does.

What it does is remove the one **retained, long-lived, framework-owned** copy: the secret
accumulates into a single `bytearray` that is zeroed on teardown, and it is never assigned to a
Textual reactive, because reactives are watched, copied and retained by design.

It shortens dwell. It does not achieve erasure.
"""

from __future__ import annotations


class SecretBuffer:
    """One `bytearray`, appended to and zeroed. Never rendered, never compared to a `str`."""

    def __init__(self) -> None:
        self._data = bytearray()
        self._closed = False

    def append(self, text: str) -> None:
        if self._closed:
            raise ValueError("the buffer has been closed")
        self._data.extend(text.encode("utf-8"))

    def backspace(self) -> None:
        """Drop the last character. Decoding is done on the buffer, so multi-byte input does not
        leave a half-character behind."""
        if self._closed:
            raise ValueError("the buffer has been closed")
        text = self._data.decode("utf-8")[:-1]
        self._zero()
        self._data = bytearray(text.encode("utf-8"))

    def value(self) -> str:
        """The accumulated secret. Called once, at the moment it is used to derive."""
        if self._closed:
            raise ValueError("the buffer has been closed")
        return self._data.decode("utf-8")

    def __len__(self) -> int:
        return len(self._data.decode("utf-8")) if not self._closed else 0

    def close(self) -> None:
        """Zero the buffer. Idempotent, so a teardown path that runs twice is not a bug."""
        self._zero()
        self._data = bytearray()
        self._closed = True

    @property
    def closed(self) -> bool:
        return self._closed

    def _zero(self) -> None:
        for i in range(len(self._data)):
            self._data[i] = 0

    def __enter__(self) -> SecretBuffer:
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()

    def __repr__(self) -> str:
        return f"<SecretBuffer {len(self)} characters>"

    __str__ = __repr__
