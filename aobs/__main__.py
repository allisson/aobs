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
    """The appliance's own halves of the four ports, and the single place they are named.

    Nothing here is conditional and nothing here is a fake. That is the point: a fake `Power` does
    not power off and a fake `EntropySource` returns a deterministic counter, so an appliance
    started with either silently wired in would look correct on screen and be worthless in every
    claim it makes. There is no flag, no environment variable and no fallback that could select
    one — the dangerous configuration is unreachable by construction rather than by care.

    **A missing camera is not a reason to refuse.** It is a normal session with fewer paths, which
    the application already models: the probe answers honestly, the home screen offers the
    outbound paths and disables the ones that scan. Generating a wallet and exporting a descriptor
    both need no camera at all.
    """
    from aobs.adapters.real import (
        ForcedPowerOff,
        KernelEntropySource,
        LoadkeysKeymap,
        V4L2FrameSource,
    )

    return {
        "frames": V4L2FrameSource(),
        "entropy": KernelEntropySource(),
        "power": ForcedPowerOff(),
        "keymap": LoadkeysKeymap(),
    }


def main() -> int:
    failure_handler.install()

    from aobs.ui.app import SignerApp

    adapters = real_adapters()
    app = SignerApp(**adapters)
    app.run()

    # `F12` does not return on the appliance — `Power.power_off` stops the machine — so reaching
    # this line at all means the session ended some other way, and the only other way is an
    # unrecoverable fault. `docs/boot-pipeline.md`: the app names the failure and **waits for a
    # keypress** before forcing power-off, because a silent power-off is indistinguishable from a
    # hardware fault and invites exactly the blind retry the refusal model refused to train.
    if app.fatal_message is not None:
        sys.stderr.write(app.fatal_message + "\n")
        _wait_for_a_key()
    adapters["power"].power_off()
    return app.return_code or 0


def _wait_for_a_key() -> None:
    """Hold the failure on screen until the user has read it. Never a timeout.

    There is no recovery to offer and nothing the user can do but read, so the only thing that
    would be wrong here is proceeding without them.
    """
    try:
        sys.stdin.read(1)
    except (OSError, ValueError):  # pragma: no cover - no console to wait on
        pass


if __name__ == "__main__":
    sys.exit(main())
