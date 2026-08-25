"""What the appliance says when something goes wrong, and what it must never say.

A Textual crash screen drawing the frame that holds the mnemonic would defeat every other
measure in `docs/secret-hygiene.md` in one screenful — at the exact moment the user is staring
at the display. So the app installs its own handler and no library decides this:

* the exception **type** and a fixed message, never the traceback and never locals;
* `show_locals` pinned off explicitly, regardless of any library default, because a default is
  not a decision and can change under us on an upgrade;
* no logging framework, no log file, no `print` of an object that could hold key material. The
  full traceback goes nowhere, because there is nowhere for it to go.

`describe()` is the pure half and lives here. Installing the handler touches process state, so it
lives in `aobs/adapters/failure_handler.py` — the seam holds even for this.
"""

from __future__ import annotations

#: What the user is shown alongside the exception type. It says what to do, because there is only
#: one thing to do: the session ends and nothing survives it.
FAILURE_MESSAGE = "The session cannot continue. Power off and start again."


def describe(exception: BaseException) -> str:
    """The whole of what may reach a screen: the exception's type, and a fixed sentence.

    Not `str(exception)` — an exception's own message is written by whoever raised it, and one
    raised from inside a frame holding a mnemonic must not be trusted to be free of it.
    """
    return f"{type(exception).__name__}. {FAILURE_MESSAGE}"
