"""What the appliance says when something goes wrong, and what it must never say.

A Textual crash screen drawing the frame that holds the mnemonic would defeat every other
measure in `docs/secret-hygiene.md` in one screenful — at the exact moment the user is staring
at the display. So the app installs its own handler and no library decides this:

* the exception **type** and a fixed message, never the traceback and never locals — with one
  named carve-out, `ImportError`, whose message is written by the import machinery and names a
  module or a library rather than a value the application held;
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

#: The one exception type whose own message reaches the screen, and the reason it is exactly one.
#:
#: An `ImportError` is raised by the import machinery rather than by application code, and its
#: message names a module or a shared library — `libstdc++.so.6: cannot open shared object file` —
#: never a value the application was holding. Against that, `docs/failure-states.md` promises the
#: user "a short stable identifier for the condition, so they can accurately describe what they saw
#: in a bug report": on an appliance with no logs, no shell and deliberately no diagnostic export,
#: the fault screen is the only channel a fault has.
#:
#: MEASURED, and this is why the carve-out exists: the missing C++ runtime that stopped the second
#: hardware boot reached the screen as `ImportError.` and nothing else. Identifying it took the
#: initramfs unpacked on another machine and a chroot. The name would have been enough.
NAMED_MESSAGE_TYPES = (ImportError,)

#: A bound on what a named message may put on screen. The import machinery's own messages are one
#: short line; this is here so the carve-out above cannot become an arbitrary amount of text on the
#: one screen `docs/secret-hygiene.md` is about.
MESSAGE_LIMIT = 200


def describe(exception: BaseException) -> str:
    """The whole of what may reach a screen: the exception's type, a fixed sentence, and — for the
    one type in `NAMED_MESSAGE_TYPES` — the message the import machinery wrote.

    Not `str(exception)` in the general case: an exception's own message is written by whoever
    raised it, and one raised from inside a frame holding a mnemonic must not be trusted to be free
    of it. The carve-out is by exception type and not by inspection of the text, because "does this
    string look like a secret?" is not a question with an answer.
    """
    detail = ""
    if isinstance(exception, NAMED_MESSAGE_TYPES):
        message = " ".join(str(exception).split())[:MESSAGE_LIMIT]
        if message:
            detail = f" {message}."
    return f"{type(exception).__name__}.{detail} {FAILURE_MESSAGE}"
