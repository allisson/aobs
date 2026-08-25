"""Security tests that are not about a module.

`docs/secret-hygiene.md` names the one that matters most: raise from inside a frame holding a
known sentinel seed, and assert the sentinel appears in no rendered screen, no stream, and no
exception message.
"""

from __future__ import annotations

import io
import json
import traceback
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

from aobs.adapters.fake import (
    FixedEntropySource,
    ImageFileFrameSource,
    RecordingKeymap,
    RecordingPower,
)
from aobs.adapters.failure_handler import excepthook
from aobs.core.failure import describe
from aobs.core.review import review
from aobs.core.secret import SecretBuffer
from aobs.core.signing import SigningRefused, sign
from aobs.core.text import inert, is_inert
from aobs.core.wallet import Network, Wallet
from aobs.ui.widgets.failure import Failure

from conftest import VECTOR_MNEMONIC

CORPUS = Path(__file__).parent.parent / "fixtures" / "psbt"

SENTINEL = "correct-horse-battery-staple-SENTINEL-SEED"


def _raise_holding_the_sentinel() -> None:
    """A frame that holds the secret in a local, which is exactly the frame a crash screen would
    render if anything rendered locals."""
    seed = SENTINEL  # noqa: F841 - held on purpose
    raise ValueError(f"failed while deriving from {seed}")


# --- The sentinel ----------------------------------------------------------------------------------


def test_the_sentinel_reaches_no_stream_and_no_message() -> None:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        try:
            _raise_holding_the_sentinel()
        except ValueError as failure:
            excepthook(type(failure), failure, failure.__traceback__)

    assert SENTINEL not in out.getvalue()
    assert SENTINEL not in err.getvalue()
    assert err.getvalue().startswith("ValueError.")


async def test_a_fault_inside_the_running_app_never_puts_the_sentinel_on_the_display() -> None:
    """The real application, faulting for real.

    Textual's own crash renderer is `Traceback(show_locals=True)` — it would print the local named
    `seed` above, on the display the user is staring at. `SignerApp` replaces it, and this is the
    assertion that the replacement holds.
    """
    from aobs.ui.app import SignerApp

    app = SignerApp(
        frames=ImageFileFrameSource([]),
        entropy=FixedEntropySource(),
        power=RecordingPower(),
        keymap=RecordingKeymap(),
    )
    with pytest.raises(ValueError):
        async with app.run_test(size=(128, 48)) as pilot:
            app.call_next(_raise_holding_the_sentinel)
            await pilot.pause()

    assert app.fatal_message is not None
    assert SENTINEL not in app.fatal_message
    assert app.fatal_message.startswith("ValueError.")
    assert "Traceback" not in app.fatal_message


def test_the_described_failure_is_the_type_and_a_fixed_message() -> None:
    try:
        _raise_holding_the_sentinel()
    except ValueError as failure:
        described = describe(failure)
        assert described == "ValueError. The session cannot continue. Power off and start again."
        # And it is not `str(exception)`, which does hold the sentinel — the point of the rule.
        assert SENTINEL in str(failure)
        assert SENTINEL not in described
        # Nor is it the traceback, which holds the frame.
        rendered_traceback = "".join(
            traceback.format_exception(type(failure), failure, failure.__traceback__)
        )
        assert SENTINEL in rendered_traceback
        assert rendered_traceback not in described


def test_a_refusal_raised_over_a_real_wallet_leaks_nothing() -> None:
    wallet = Wallet.from_mnemonic(VECTOR_MNEMONIC, network=Network.SIGNET)
    with pytest.raises(SigningRefused) as raised:
        sign((CORPUS / "foreign_input.psbt").read_bytes(), wallet)
    message = str(raised.value)
    assert wallet.root.to_base58() not in message
    assert describe(raised.value) == (
        "SigningRefused. The session cannot continue. Power off and start again."
    )


# --- The secret buffer -------------------------------------------------------------------------------


def test_the_buffer_is_zeroed_on_teardown_and_retains_nothing() -> None:
    buffer = SecretBuffer()
    for character in SENTINEL:
        buffer.append(character)
    assert buffer.value() == SENTINEL

    held = buffer._data  # the one retained copy, so the test can look at it after teardown
    buffer.close()
    assert set(held) <= {0}
    assert not any(
        SENTINEL.encode() in bytes(value)
        for value in vars(buffer).values()
        if isinstance(value, (bytes, bytearray))
    )
    assert SENTINEL not in repr(buffer)
    assert buffer.closed


def test_the_buffer_is_never_rendered() -> None:
    with SecretBuffer() as buffer:
        buffer.append("hunter2")
        assert "hunter2" not in f"{buffer!r} {buffer!s}"
        assert len(buffer) == 7
        buffer.backspace()
        assert buffer.value() == "hunter"
    assert buffer.closed


def test_a_closed_buffer_cannot_be_read_or_appended_to() -> None:
    buffer = SecretBuffer()
    buffer.append("x")
    buffer.close()
    for call in (buffer.value, lambda: buffer.append("y"), buffer.backspace):
        with pytest.raises(ValueError):
            call()
    buffer.close()  # idempotent: a teardown path that runs twice is not a bug


# --- Escape injection ---------------------------------------------------------------------------------


def test_a_psbt_carrying_ansi_escapes_renders_inert() -> None:
    """`docs/test-harness.md` requires this to be a tested rule rather than an assumed Rich
    behaviour."""
    meta = json.loads((CORPUS / "ansi_escape_label.json").read_text())
    psbt_bytes = (CORPUS / "ansi_escape_label.psbt").read_bytes()
    wallet = Wallet.from_mnemonic(VECTOR_MNEMONIC, network=Network(meta["network"]))
    result = review(psbt_bytes, wallet)

    # The hostile field is in the PSBT's bytes and reaches no field of the review.
    assert b"\x1b[2J" in psbt_bytes
    for output in result.outputs:
        assert is_inert(output.address or "")
        assert is_inert(output.script_pubkey_hex)
        assert is_inert(output.claimed_path or "")

    # And the app-side boundary applies the same rule to text the core never touched. Every
    # widget-bound string in `aobs/ui/` goes through a value object that calls `inert()` on
    # construction, so a caller cannot forget to. The full end-to-end assertion — hostile bytes
    # through the running review screen — lands with that screen.
    hostile = "\x1b[2J\x07this is not a PSBT\x00"
    failure = Failure(condition=hostile, happened=hostile, next_steps=(hostile,))
    assert is_inert(failure.condition)
    assert is_inert(failure.happened)
    assert is_inert(failure.next_steps[0])


def test_the_sanitiser_removes_rather_than_escapes() -> None:
    hostile = "\x1b[31mPAY\x1b[0m\x07 HERE\x00"
    assert inert(hostile) == "[31mPAY[0m HERE"
    assert is_inert(inert(hostile))
    assert not is_inert(hostile)
