"""The `Power` real adapter: a forced power-off.

**Not a shutdown sequence.** There is no init system to ask, no filesystem to unmount and no
service to stop — the appliance's amnesia rests on the machine stopping, not on the application's
tidiness (`docs/boot-pipeline.md`). So this is `reboot(2)` with `RB_POWER_OFF`, issued by the
process that is PID 1, and it does not return.

**The wipe is not here, and that is deliberate.** `docs/threat-model.md` claims a best-effort wipe
of "the derived key material **the app itself holds**" — which is `SignerApp`'s session state, not
something an adapter behind a one-method port can reach. `SignerApp.action_power_off` wipes and
then calls this, in that order, which is a sequence the harness can watch with the fake; a wipe
smuggled in here would be observable by nothing at all. A full RAM overwrite stays rejected as
theatre, and "best-effort" stays the honest word.
"""

from __future__ import annotations

import ctypes
import os

#: `LINUX_REBOOT_CMD_POWER_OFF`. libc's `reboot(int)` wrapper supplies the two magic words.
RB_POWER_OFF = 0x4321FEDC


class ForcedPowerOff:
    def power_off(self) -> None:
        """End the session. Does not return on the appliance."""
        libc = ctypes.CDLL(None, use_errno=True)
        libc.reboot(RB_POWER_OFF)
        # Only reachable if the call failed — off the appliance, or not privileged. There is
        # nothing left to show and nothing that could fix it, so the process ends rather than
        # returning to a screen that would imply the session is still live.
        os._exit(1)
