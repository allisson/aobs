"""Reading `/etc/aobs-release`. The one line of filesystem contact behind the identity row.

It lives here rather than in `aobs/core/release.py` for the reason every other adapter exists:
`tests/test_structure.py` forbids the core `pathlib`, `os` and `time`, and that rule is what keeps
the core a set of pure functions over bytes. Parsing and formatting are the core's; opening the file
is this module's.

It is not a port, and there is no fake half. `aobs/adapters/failure_handler.py` is the precedent: a
port exists where there are genuinely two implementations, and reading one file has one. The seam the
tests actually need is a `Release` value handed to `SignerApp`, which they construct directly —
`aobs/__main__.py` is the only caller of this function.

**An absent file is a development build**, never an error and never a version. That is the appliance
running from a source tree, which is exactly what `DEVELOPMENT BUILD` on screen is for.
"""

from __future__ import annotations

from pathlib import Path

from aobs.core.release import UNKNOWN, RELEASE_PATH, Release, parse


def read(path: str = RELEASE_PATH) -> Release:
    """The file, parsed. Anything that goes wrong reading it is a development build.

    Deliberately broad: a truncated file, a directory where the file should be, a permission error.
    None of them is a condition the user can act on and none of them may be allowed to stop the
    session — but neither may any of them produce a version-shaped string, which is why the
    fallback is `UNKNOWN` and not a partial parse.
    """
    try:
        return parse(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return UNKNOWN
