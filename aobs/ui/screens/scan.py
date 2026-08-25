"""The scan screen: one screen for one QR or forty-five.

Every inbound path arrives here — a transaction to sign, an encrypted wallet backup to restore, a
receive address to check — because the user is doing the same physical thing in all three cases,
and two aiming implementations would drift (`docs/scan-feedback.md`).

The screen itself holds almost nothing. It pulls frames, hands each decoded payload and the elapsed
time to `ScanController`, and draws what comes back: the framing aid until the first decode, then
the slot map and one status line. **The elapsed time is counted in frames, not read from a
clock** — five frames is one second at the inbound rate — which is what keeps the whole of the
delayed hint testable without a `sleep`.

**Nothing here times out.** `esc` is the give-up, and it says the count on the way out.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Center, Vertical
from textual.screen import Screen
from textual.widgets import Static

from aobs.ports.frame_source import Frame
from aobs.ui import viewfinder
from aobs.ui.qrdecode import decode_frame
from aobs.ui.scanning import (
    AIMING_LINE,
    Completed,
    Foreign,
    Restarted,
    ScanController,
    ScanProgress,
    ScanTarget,
)
from aobs.ui.widgets.failure import Failure, FailurePanel

#: Inbound is 5 fps (10 worst case). The outbound rate is a different problem with a different
#: answer, and lives with the emit screen.
INBOUND_FRAME_RATE = 5

TITLES = {
    ScanTarget.TRANSACTION: "Sign a transaction",
    ScanTarget.WALLET_BACKUP: "Restore from an encrypted wallet QR",
    ScanTarget.ADDRESS: "Verify a receive address",
}

#: The viewfinder is named for what it is, on the screen, in words. At 128x48 samples it can show
#: where the bright rectangle is and can never show focus; calling it a preview would promise
#: feedback it cannot deliver.
FRAMING_AID_NOTE = "Framing aid: it shows where the code is, not whether it is in focus."


class ScanScreen(Screen):
    """Aim, then progress. The transition between the two is the first successful decode."""

    DEFAULT_CSS = """
    ScanScreen #progress { height: auto; }
    ScanScreen #status { margin-top: 1; }
    ScanScreen #reset-notice { margin-top: 1; }
    ScanScreen #framing-aid { text-style: dim; margin-top: 1; }
    ScanScreen #viewfinder-row { height: auto; }
    ScanScreen #viewfinder { width: auto; height: auto; }
    """

    def __init__(self, target: ScanTarget) -> None:
        super().__init__()
        self.target = target
        self.controller = ScanController(target)
        #: The bytes, once they are all here. `None` until then, and the end of this ticket.
        self.payload: bytes | None = None
        self._frames = None
        self._timer = None
        self._ticks = 0
        self._finished = False

    def compose(self) -> ComposeResult:
        """The words first, the picture last, and the slot map above the fraction.

        The order is a geometry decision the console floor forces. The framing aid is 24 rows of a
        28-row content block at 100x30, so anything drawn under it would be off the screen on the
        one geometry the appliance refuses to start below — and what would be lost is the status
        line, which is the whole point of the screen. Clipping the bottom of a framing aid costs
        nothing by comparison, and the text does not reflow when the aid disappears.
        """
        with Vertical(id="frame"):
            yield Static(TITLES[self.target], id="title")
            yield Vertical(id="progress")
            yield Static(AIMING_LINE, id="status")
            yield Static(FRAMING_AID_NOTE, id="framing-aid")
            with Center(id="viewfinder-row"):
                yield Static("", id="viewfinder")

    def on_mount(self) -> None:
        self._frames = self.app.frames.frames()  # type: ignore[attr-defined]
        interval = self.app.scan_frame_interval  # type: ignore[attr-defined]
        if interval is not None:
            self._timer = self.set_interval(interval, self.scan_once)

    def on_unmount(self) -> None:
        """Let go of the frame stream.

        The port promises an `Iterator`, not a generator, so `close()` is not guaranteed — the real
        V4L2 adapter is free to hand back something else. What is not acceptable is walking away
        from a capture stream and leaving it to a garbage collector: the adapter holds mapped
        buffers, and the next scan of the session opens a new stream of its own.
        """
        close = getattr(self._frames, "close", None)
        if close is not None:
            close()

    def leave_notice(self) -> str | None:
        """`esc` discards the partials, and says how far they got.

        The count is the point: a user who reached 26 of 27 should know they nearly had it rather
        than concluding the appliance cannot scan. A finished scan needs no notice — the screen it
        lands on has the bytes.
        """
        return None if self._finished else self.controller.give_up_notice()

    # --- one frame ---------------------------------------------------------------------------

    def scan_once(self) -> None:
        """Pull one frame and act on it.

        Called by the interval on the appliance, and called directly by the suite, which runs with
        no interval at all. Driving the timer in real time would mean waiting seven seconds to scan
        twenty-seven frames — and worse, a test whose frame count depends on how long the
        assertions before it took, which is a flake rather than a slow test.
        """
        if self._finished:
            return
        try:
            frame = next(self._frames)  # type: ignore[arg-type]
        except StopIteration:
            # The image-file fake ran out of frames. A camera does not do this, so it is not the
            # camera-lost condition — the screen simply has nothing further to look at.
            self._stop()
            return
        except OSError:
            self._stop()
            self._finished = True
            self.app.camera_lost()  # type: ignore[attr-defined]
            return

        self._ticks += 1
        event = self.controller.frame(decode_frame(frame), self._ticks / INBOUND_FRAME_RATE)
        if isinstance(event, Foreign):
            self._refuse(event.failure)
            return
        if isinstance(event, Restarted):
            # A named message and a reset. The line stays up once it appears, because the user
            # needs to know why the count they were watching went back to zero — and it is mounted
            # rather than reserved, because a blank row band costs the framing aid a row of image
            # on the smallest console the appliance runs on.
            notices = self.query("#reset-notice")
            if notices:
                notices.first(Static).update(event.message)
            else:
                self.query_one("#frame").mount(
                    Static(event.message, id="reset-notice"), after=self.query_one("#status")
                )
        self._draw(frame, self.controller.progress)
        if isinstance(event, Completed):
            self.payload = event.payload
            self.app.scanned = event.payload  # type: ignore[attr-defined]
            self._finished = True
            self._stop()

    # --- drawing ------------------------------------------------------------------------------

    def _draw(self, frame: Frame, progress: ScanProgress) -> None:
        if progress.framing_aid:
            self.query_one("#viewfinder", Static).update(viewfinder.render(frame))
        else:
            # Once bytes are arriving, aiming is solved and the screen's job is progress.
            for selector in ("#viewfinder-row", "#framing-aid"):
                for stale in self.query(selector):
                    stale.remove()

        slots = self.query("#slot-map")
        if progress.slot_map is None:
            for stale in slots:
                stale.remove()
        elif slots:
            slots.first(Static).update(progress.slot_map)
        else:
            self.query_one("#progress").mount(Static(progress.slot_map, id="slot-map"))

        self.query_one("#status", Static).update(progress.status)

    def _refuse(self, failure: Failure) -> None:
        """A QR that decoded and is not ours, named for what it is — in the one failure shape."""
        self._finished = True
        self._stop()
        for selector in (
            "#viewfinder-row",
            "#framing-aid",
            "#progress",
            "#status",
            "#reset-notice",
        ):
            for stale in self.query(selector):
                stale.remove()
        self.query_one("#frame").mount(FailurePanel(failure))

    def _stop(self) -> None:
        if self._timer is not None:
            self._timer.stop()
            self._timer = None
