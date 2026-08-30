"""One shape for every way the appliance can fail to do what was asked.

`docs/failure-states.md` fixed the shape, and it is reused verbatim by every refusal, every
wrong-QR message and every *not found*:

- **State exactly what happened**, in terms the user can act on.
- **Offer next steps with no default and no highlighted button.** The appliance does not press its
  thumb on a choice it cannot make — so the steps are lines of text, never `Button`s, and nothing
  here takes focus.
- **No error codes without words. No traceback, ever.**

And instead of a diagnostic export — which `docs/failure-states.md` rules out as a data path off
the machine — a **short stable name for the condition**: a name, not a code and not a stack
location, so the user can describe accurately what they saw in a bug report typed on a different
machine. That costs nothing and carries nothing.

Alongside it, the **release identity footer** (#61) — the same row the keymap picker shows. It is
here rather than on one particular screen because `docs/failure-states.md` fixes *one* shape for
every failure, and a bug report carrying no build identity is a bug report about nothing. It is the
other half of the same trade as the condition name: what a report needs, at no cost and carrying
nothing off the machine.

One widget, parameterised, because failure screens are the screens users reach while confused and
learning to read them once is worth more than tailoring each one.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static

from aobs.core.text import inert
from aobs.ui.widgets.release import ReleaseFooter


@dataclass(frozen=True)
class Failure:
    """What a failure screen says. A value object: no widget, no Textual, no I/O.

    Every field is passed through `core.text.inert()` on construction rather than at render time.
    Much of what reaches this widget is attacker-controlled — a label out of a PSBT, a string out
    of a scanned QR — and a rule applied at the boundary is one the next caller cannot forget to
    apply. `docs/test-harness.md` requires this to be a tested rule rather than an assumed Rich
    behaviour.
    """

    #: A short stable name for the condition. Lower-case, hyphenated, never a number.
    condition: str
    #: What happened, in one or two sentences the user can act on.
    happened: str
    #: What to do next. No default, no recommendation, no ordering that implies one.
    next_steps: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "condition", inert(self.condition))
        object.__setattr__(self, "happened", inert(self.happened))
        object.__setattr__(self, "next_steps", tuple(inert(step) for step in self.next_steps))


class FailurePanel(Vertical):
    """`Failure`, rendered. Contains no `Button` and takes no focus, by construction."""

    DEFAULT_CSS = """
    FailurePanel {
        height: auto;
    }
    FailurePanel > #failure-happened {
        margin-bottom: 1;
    }
    FailurePanel > .failure-next-step {
        margin-left: 2;
    }
    FailurePanel > #failure-condition {
        margin-top: 1;
    }
    """

    def __init__(self, failure: Failure, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self.failure = failure

    def compose(self) -> ComposeResult:
        yield Static(self.failure.happened, id="failure-happened")
        for index, step in enumerate(self.failure.next_steps):
            # A line of text, not a button: a button would have to be focused or not, and either
            # answer is the appliance recommending one of them.
            yield Static(step, classes="failure-next-step", id=f"failure-next-step-{index}")
        yield Static(f"condition: {self.failure.condition}", id="failure-condition")
        yield ReleaseFooter(self.app.release)  # type: ignore[attr-defined]
