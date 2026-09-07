"""Making attacker-controlled text inert.

Every string the core hands out may have arrived over the QR channel, which
`docs/threat-model.md` names Tier 1. `docs/test-harness.md` requires this to be a tested rule
rather than an assumed Rich behaviour, so the core strips the escapes itself and never relies on
what a renderer happens to do with them.
"""

from __future__ import annotations

#: C0 controls, DEL, and the C1 range. Nothing the core exposes is ever multi-line or coloured,
#: so the whole set goes, tab and newline included.
_STRIPPED = frozenset(
    [chr(c) for c in range(0x00, 0x20)] + [chr(0x7F)] + [chr(c) for c in range(0x80, 0xA0)]
)


def inert(text: str) -> str:
    """`text` with every control character removed.

    Removed rather than escaped: an escaped sequence still shows the attacker's characters to
    the user, and nothing the core exposes has a legitimate use for one.
    """
    return "".join(ch for ch in text if ch not in _STRIPPED)


def is_inert(text: str) -> bool:
    return not any(ch in _STRIPPED for ch in text)
