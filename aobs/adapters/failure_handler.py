"""The process-level half of `docs/secret-hygiene.md`'s "nothing renders a secret".

It lives outside the core because it touches process state — `sys.excepthook`, `RLIMIT_CORE` —
and the core performs no I/O and reads no ambient state. The rule it enforces is the core's; the
enforcement is here.
"""

from __future__ import annotations

import resource
import sys
from types import TracebackType

from aobs.core.failure import describe


def excepthook(
    kind: type[BaseException],
    exception: BaseException,
    traceback: TracebackType | None,
) -> None:
    """The top-level handler: the described failure, and nothing else.

    Never the traceback, never locals, never `str(exception)` — an exception raised from inside a
    frame holding a mnemonic must not be trusted to be free of it.
    """
    del kind, traceback  # deliberately unused: the traceback goes nowhere
    sys.stderr.write(describe(exception) + "\n")


def install() -> None:
    """Install the handler, and disable core dumps as belt-and-braces.

    `RLIMIT_CORE` is **never the claim**: it is a userspace call made by the same code that would
    be failing. The claim is `CONFIG_COREDUMP=n` — a build-time assertion on a kernel with no
    dumper in it at all.
    """
    sys.excepthook = excepthook
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
