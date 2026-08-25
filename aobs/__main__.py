"""`python3 -m aobs` — what PID 1 `exec`s, and the only module that knows which adapters are real.

Order matters here and is the whole reason this module is separate from `aobs.ui.app`. The failure
handler is installed **before anything is constructed**, so there is no window in which an
exception could reach Python's default traceback printer. Everything after that point fails into
`describe()`: the exception type and one fixed sentence, never locals and never a stack.

`aobs/ui/` knows only the four ports. This module is where the real halves are chosen, which is
what lets the whole application be driven headless with the fakes and no conditional anywhere
inside it.
"""

from __future__ import annotations

import sys

from aobs.adapters import failure_handler


def real_adapters() -> dict:
    """The appliance's own halves of the four ports.

    Not built yet, on purpose: V4L2 `mmap` capture, `getrandom` + camera + dice, a forced
    power-off and `loadkeys` are their own spec. This function is the single place they get wired
    in, and until they exist `python3 -m aobs` says so rather than starting an appliance whose
    ports are fakes — which is the one failure mode worth ruling out by construction, since a fake
    `Power` does not power off and a fake `EntropySource` returns a constant.
    """
    raise NotImplementedError(
        "The real adapters are not built yet. Run the application through the test harness."
    )


def main() -> int:
    failure_handler.install()

    from aobs.ui.app import SignerApp

    app = SignerApp(**real_adapters())
    app.run()
    return app.return_code or 0


if __name__ == "__main__":
    sys.exit(main())
