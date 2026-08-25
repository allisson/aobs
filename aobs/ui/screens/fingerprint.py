"""The wallet is loaded: its fingerprint, and — when it was generated here — the mixing facts.

**Facts, never a score.** `core.mixing_report()` says which sources contributed and in what
quantity — *system: 32 bytes · dice: 0 rolls* — and that is the whole of what the appliance is
allowed to claim about its own mixing. Anything it displayed as a score would be a claim by the
same code that would be lying; the real verification is this repository's own test vectors
(`docs/entropy-mixing.md`).

**Zero rolls renders identically to ninety-nine.** The dice line is always present and always the
same shape, so the absence of dice is not dressed up as a deficiency: no warning, no amber state,
no bar short of full. `mix()` records no dice contribution at all when there were no rolls, so
this screen supplies the zero rather than letting the row disappear — a missing row is itself a
difference, and differences here read as verdicts.

**The fingerprint is a comparison, except the one time it cannot be.** On a wallet created here
there is nothing to compare against, and the appliance says so and tells the user to record it —
rather than showing a number that looks like a confirmation and is not (`docs/secret-hygiene.md`).
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Static

from aobs.core.entropy import MixingReport, SourceLabel

#: Verbatim, and distinct from the compare text below. A user reading the wrong one of these two
#: sentences draws exactly the wrong conclusion from the same eight hex characters.
RECORD_IT = (
    "This wallet was made here, so there is nothing to compare this fingerprint against. Write it "
    "down beside your recovery words: the same words with a different passphrase give a different "
    "fingerprint and a different wallet."
)

COMPARE_IT = (
    "Check this fingerprint against the one you recorded. If it differs, a word or the passphrase "
    "is not what you used before — and the addresses will not be yours."
)

KEYS = "F10 done  ·  F12 power off"


def facts(report: MixingReport) -> str:
    """The mixing, as a line of facts with the dice always stated."""
    parts = [
        f"{contribution.label.value}: {contribution.quantity} {contribution.unit}"
        for contribution in report.contributions
    ]
    if not any(c.label is SourceLabel.DICE for c in report.contributions):
        parts.append("dice: 0 rolls")
    return "  ·  ".join(parts)


class FingerprintScreen(Screen):
    BINDINGS = [
        # Never `enter`, never `esc` — `docs/failure-states.md`.
        Binding("f10", "done", "Done"),
    ]

    DEFAULT_CSS = """
    FingerprintScreen #mixing-facts { margin-top: 1; }
    FingerprintScreen #fingerprint { margin-top: 1; text-style: bold; }
    FingerprintScreen #fingerprint-advice { margin-top: 1; }
    FingerprintScreen #fingerprint-keys { margin-top: 1; }
    """

    def __init__(
        self,
        fingerprint_hex: str,
        *,
        created_here: bool,
        report: MixingReport | None = None,
    ) -> None:
        super().__init__()
        self._fingerprint_hex = fingerprint_hex
        self._created_here = created_here
        self._report = report

    def compose(self) -> ComposeResult:
        with Vertical(id="frame"):
            yield Static("Your wallet is loaded", id="title")
            if self._report is not None:
                yield Static(facts(self._report), id="mixing-facts")
            yield Static(f"master fingerprint  {self._fingerprint_hex}", id="fingerprint")
            yield Static(
                RECORD_IT if self._created_here else COMPARE_IT, id="fingerprint-advice"
            )
            yield Static(KEYS, id="fingerprint-keys")

    def action_done(self) -> None:
        self.app.return_home()  # type: ignore[attr-defined]
