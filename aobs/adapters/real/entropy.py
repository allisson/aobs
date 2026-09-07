"""The `EntropySource` real adapter: the kernel CSPRNG, and only that.

The port's contract is already written as *`count` bytes from the kernel CSPRNG*, and it stays
narrowly that. `docs/entropy-mixing.md`'s phrase "getrandom, camera, dice" describes the mixing
construction as a whole, not this one port: camera frames and dice rolls reach `core.mix()` by
their own routes, and folding either into this adapter would put an I/O dependency inside the one
source the mixer requires to be unconditional.

**`GRND_NONBLOCK` first**, so an uninitialised pool becomes a message rather than a silent hang.
The appliance boots with `random.trust_cpu=off random.trust_bootloader=off`
(`docs/entropy-mixing.md`), which is what makes a cold machine's pool genuinely slow to
initialise — and the whole reason the distinction is surfaced rather than swallowed. `ready()` is
the answerable question a caller needs in order to wait *visibly*; falling back to the blocking
call is what happens **after** the user has been told, never instead of telling them.
"""

from __future__ import annotations

import os


class KernelEntropySource:
    def ready(self) -> bool:
        """Is the kernel's randomness pool initialised?

        Asked by drawing one byte non-blocking, which is the only honest way to ask: there is no
        query that does not also consume, and a byte is what the answer costs.
        """
        try:
            os.getrandom(1, os.GRND_NONBLOCK)
        except BlockingIOError:
            return False
        return True

    def random_bytes(self, count: int) -> bytes:
        """`count` bytes from the kernel CSPRNG.

        Non-blocking first; on `BlockingIOError` this blocks, and by then the caller has already
        shown the wait screen — `SignerApp.generate_wallet` asks `ready()` before it draws.
        """
        out = bytearray()
        while len(out) < count:
            want = count - len(out)
            try:
                out += os.getrandom(want, os.GRND_NONBLOCK)
            except BlockingIOError:
                out += os.getrandom(want)
        return bytes(out)
