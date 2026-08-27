"""Every string the money path puts on screen, and not one decision about the money.

`docs/review-screen.md` owns the layout; `docs/psbt-review-model.md` owns the model. This module is
the layout half, and it derives nothing: it is handed a `Review` and hands back lines. Nothing here
re-parses, re-categorises or re-computes — the whole point of the review model being pure is that
the screen has nothing left to get wrong.

It is Textual-free on purpose. The grouping arithmetic, the space-separated thousands, the two-line
headline and the refusal split are what a wrong address hides behind, and they are testable here
without an application at all.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from aobs.core.review import (
    OutputCategory,
    Refusal,
    RefusalReason,
    Review,
    ReviewedOutput,
    WarningCode,
)
from aobs.core.text import inert
from aobs.ui.geometry import MAX_COLUMNS
from aobs.ui.widgets.failure import Failure

#: The content block, less the two columns of padding on each side of it. Every line this module
#: composes is laid out against this width, which is why there is one layout to test across the
#: three real console geometries.
ROW_COLUMNS = MAX_COLUMNS - 4

#: Where an address, a path and a note sit under the output they belong to. Five columns, which is
#: exactly what `f"{index:>3}  "` occupies, so the label and the address share a left edge.
INDENT = 5

#: `NOT_PROVEN` and `PAYMENT` render the same label, byte-identically. A third on-screen label
#: would reintroduce the third category as a *middle ground*, and a middle ground is where a user
#: parks a decision (`docs/review-screen.md`).
LABELS = {
    OutputCategory.PAYMENT: "PAYMENT",
    OutputCategory.NOT_PROVEN: "PAYMENT",
    OutputCategory.CHANGE_PROVEN: "CHANGE, PROVEN",
}

WARNING_MARK = "⚠ "

#: Names the wallet's claim, says where the fix is — this is not a scan to retry — and does not
#: accuse the wallet: a gap-limit miss and an attack are indistinguishable from here.
NOT_PROVEN_WARNING = (
    "Your wallet says this output is your own change. This appliance could not derive it from "
    "its own keys, so it is shown as a payment and counted as leaving. Verify this address as "
    "you would any recipient."
)

#: A neutral fact, not a warning. It is true of essentially every legitimate payment, and at
#: warning strength everywhere it is noise that teaches skipping.
ADDRESS_NOT_SEEN = "Address not seen before."

TRANSACTION_WARNINGS = {
    WarningCode.FEE_ABOVE_THRESHOLD: "The fee is unusually high for the amount being sent.",
    WarningCode.WHOLE_BALANCE_SPEND: "This transaction spends your entire balance.",
}

#: `F10 sign` is deliberately absent from the locked line. Printing a key that does nothing
#: teaches pressing keys that do nothing.
LOCKED_KEYS = "↓ PgDn scroll  ·  esc discard  ·  F12 power off"
UNLOCKED_KEYS = "F10 sign  ·  esc discard  ·  F12 power off"
CONFIRM_KEYS = "y  sign      ·      esc  back to the review"


# --- Numbers ------------------------------------------------------------------------------------


def btc(sats: int) -> str:
    """All eight decimals, ungrouped. Telling `0.01400000` from `0.14000000` at a glance is the
    most likely misread on this screen, and grouping the decimals would invent a convention."""
    whole, fraction = divmod(sats, 100_000_000)
    return f"{whole}.{fraction:08d}"


def satoshis(sats: int) -> str:
    """Thousands separated by **spaces**, not commas.

    The appliance has no locale, and a screen already printing `0.01400000` with a decimal point
    cannot also spend `,` without being ambiguous for half the world.
    """
    digits = str(sats)
    groups = [digits[max(0, i - 3) : i] for i in range(len(digits), 0, -3)]
    return " ".join(reversed(groups))


def grouped(text: str) -> str:
    """An address in groups of four, on one line, never wrapped and never elided.

    A truncated address is exactly what an attacker holding a vanity-prefix collision wants, and
    the widest atom the appliance can ever show — a regtest taproot `bcrt1p…`, 64 characters — is
    79 columns grouped, which fits inside the column budget with the indent to spare.
    """
    clean = inert(text)
    return " ".join(clean[i : i + 4] for i in range(0, len(clean), 4))


def _rule(width: int = ROW_COLUMNS) -> str:
    return "─" * width


def _spread(left: str, right: str, width: int = ROW_COLUMNS) -> str:
    """`left` at the left edge, `right` at the right, at least two columns between them."""
    return left + " " * max(2, width - len(left) - len(right)) + right


# --- The header ---------------------------------------------------------------------------------


def header_lines(review: Review) -> tuple[str, str]:
    counts = f"{_plural(len(review.inputs), 'input')}  ·  {_plural(len(review.outputs), 'output')}"
    return _spread("Review transaction", review.network), counts


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


# --- The output list ----------------------------------------------------------------------------


@dataclass(frozen=True)
class Note:
    """One line under an address. `warning` is what earns warning styling, and only NOT PROVEN
    does — `docs/review-screen.md` reserves it so that the styling still means something."""

    text: str
    warning: bool = False


@dataclass(frozen=True)
class OutputBlock:
    """One output, as lines. The screen places these and adds nothing to them."""

    #: 1-based, because that is what the lock line counts and the two must agree.
    number: int
    heading: str
    #: Set only on proven change, and it leads: the derivation path is the substance.
    path: str | None
    #: Always full. The no-middle-ellipsis rule takes no exception for the category we derived
    #: ourselves — carving one teaches the eye that ellipses are normal here.
    address: str
    #: True on proven change, where eye-verifying the address adds nothing.
    address_dimmed: bool
    notes: tuple[Note, ...]


def output_blocks(review: Review) -> tuple[OutputBlock, ...]:
    width = max((len(satoshis(out.amount_sats)) for out in review.outputs), default=1)
    return tuple(_block(review, out, width) for out in review.outputs)


def _block(review: Review, out: ReviewedOutput, sats_width: int) -> OutputBlock:
    amount = f"{btc(out.amount_sats)} BTC  ·  {satoshis(out.amount_sats):>{sats_width}} sats"
    proven = out.category is OutputCategory.CHANGE_PROVEN
    return OutputBlock(
        number=out.index + 1,
        heading=_spread(f"{out.index + 1:>3}  {LABELS[out.category]}", amount),
        path=out.proven.path if proven and out.proven is not None else None,
        address=_address_of(out),
        address_dimmed=not out.address_needs_checking,
        notes=tuple(_notes(review, out)),
    )


def _address_of(out: ReviewedOutput) -> str:
    """The address, grouped — or the raw script for a script with no address form at all.

    An `OP_RETURN` has no address, and inventing one or printing nothing are both worse than
    saying what is actually there. It is grouped and unelided under the same rule.
    """
    if out.address is not None:
        return grouped(out.address)
    return f"script  {grouped(out.script_pubkey_hex)}"


def _notes(review: Review, out: ReviewedOutput) -> list[Note]:
    notes: list[Note] = []
    for warning in review.warnings_for_output(out.index):
        if warning.code is WarningCode.OUTPUT_NOT_PROVEN:
            notes.append(Note(NOT_PROVEN_WARNING, warning=True))
        elif warning.code is WarningCode.ADDRESS_NOT_SEEN_BEFORE:
            notes.append(Note(ADDRESS_NOT_SEEN))
    return notes


# --- The pinned footer --------------------------------------------------------------------------


def transaction_warning_lines(review: Review) -> tuple[str, ...]:
    """Pinned directly above the totals, because they are statements about the footer's number.

    Not a block at the top: read before the thing it describes it reads as boilerplate, and it
    makes the user carry *output 3 is suspect* down a scrolling list.
    """
    return tuple(
        WARNING_MARK + TRANSACTION_WARNINGS[warning.code]
        for warning in review.transaction_warnings
        if warning.code in TRANSACTION_WARNINGS
    )


def headline_lines(review: Review) -> tuple[str, ...]:
    """Payments + fee = total leaving, on two lines, BTC then sats.

    The composition stays visible so the figure is checkable rather than asserted, and the sats
    figure of the *total* gets its own line directly under the figure it restates — it is the
    number this screen most wants to be unmisreadable.
    """
    headline = review.headline
    if headline is None:
        return ()
    total = headline.total_leaving_sats
    first = (
        f"Leaving:   {btc(headline.payments_sats)} payments"
        f"  +  {btc(headline.fee_sats)} fee"
        f"  =  {btc(total)} BTC"
    )
    return first, f"{satoshis(total)} sats".rjust(len(first))


def fee_line(review: Review) -> str | None:
    """The fee three ways: absolute sats, the rate, and the share of what is being sent.

    The percentage is the form in which an absurd fee is obvious to a non-expert, and it is
    omitted rather than faked on a spend with no payment at all, where it has no meaning.
    """
    fee = review.fee
    if fee is None:
        return None
    parts = [f"{satoshis(fee.sats)} sats", f"{fee.sat_per_vbyte:.1f} sat/vB"]
    if fee.share_of_sent is not None:
        parts.append(f"{fee.share_of_sent * 100:.2f}% of the amount sent")
    return "Fee:  " + "  ·  ".join(parts)


def lock_line(first: int, last: int, total: int) -> str:
    """What is missing, in place of a key that would do nothing."""
    return f"Outputs {first}–{last} of {total} — scroll to the end to unlock signing."


def footer_rule() -> str:
    return _rule()


# --- The confirm screen -------------------------------------------------------------------------


def confirm_title(review: Review) -> str:
    return _spread("You are about to sign.", review.network)


def confirm_lines(review: Review) -> tuple[str, ...]:
    """Numbers, counts and the NOT PROVEN tally. **No addresses.**

    A second, necessarily shallower pass at the moment of commitment *substitutes* for the first
    rather than adding to it — the user starts skimming the review because *I'll check it on the
    confirm screen*. The confirm's job is the number, which is what makes the change-address
    attack visible; the NOT PROVEN count travels with it because it explains why the number is
    what it is.
    """
    headline = review.headline
    lines: list[str] = []
    if headline is not None:
        total = headline.total_leaving_sats
        lines.append(f"Leaving this wallet      {btc(total)} BTC       {satoshis(total)} sats")
        lines.append(
            f"   {btc(headline.payments_sats)} in payments"
            f"  +  {btc(headline.fee_sats)} fee"
        )
        lines.append("")
    fee = review.fee
    if fee is not None:
        parts = [f"{satoshis(fee.sats)} sats", f"{fee.sat_per_vbyte:.1f} sat/vB"]
        if fee.share_of_sent is not None:
            parts.append(f"{fee.share_of_sent * 100:.2f}%")
        lines.append("Fee                      " + "  ·  ".join(parts))
        lines.append("")
    lines.extend(_confirm_counts(review))
    return tuple(lines)


def _confirm_counts(review: Review) -> list[str]:
    leaving = [out for out in review.outputs if out.is_leaving]
    not_proven = [out for out in leaving if out.category is OutputCategory.NOT_PROVEN]
    change = [out for out in review.outputs if not out.is_leaving]
    lines = [_plural(len(leaving), "payment output")]
    if not_proven:
        lines[0] += (
            f", {len(not_proven)} of which this appliance could not prove"
            if len(not_proven) > 1
            else ", 1 of which this appliance could not prove"
        )
        lines.append("is your own change.")
    else:
        lines[0] += "."
    if change:
        returning = sum(out.amount_sats for out in change)
        lines.append(
            f"{_plural(len(change), 'proven change output')} "
            f"{'return' if len(change) > 1 else 'returns'} {btc(returning)} BTC to this wallet."
        )
    else:
        lines.append("No change returns to this wallet.")
    return lines


# --- Refusals -----------------------------------------------------------------------------------


class RefusalKind(str, Enum):
    """The three kinds, and the only three.

    Getting the split wrong in any direction is a real failure: telling someone to retry a
    transaction that can never be accepted teaches them the appliance is broken; telling someone
    a truncated scan is unfixable sends them back to their wallet for no reason; and telling
    someone whose session is on the wrong network that their wallet must build differently sends
    them off to rebuild a transaction that was already correct.
    """

    #: The bytes did not arrive intact. A retry is the honest fix, and this is the only kind
    #: that gets one.
    TRANSFER_FAILED = "transfer-failed"
    #: Nothing on this device will help. The wallet has to build a different transaction.
    DEVICE_CANNOT_HELP = "device-cannot-help"
    #: The fix may be on either side and the appliance cannot tell which. Both are named and
    #: neither is recommended — `docs/network-selection.md`.
    EITHER_SIDE = "either-side"


RETRY_STEP = "Try scanning again."
NO_RETRY_STEP = (
    "Retrying will not change this; your wallet must build the transaction differently."
)
#: One sentence, two fixes, no default. A mismatch has two causes the appliance cannot tell apart
#: — the session is on the wrong network, or the transaction is — and `NO_RETRY_STEP` silently
#: picks the second, sending someone off to rebuild a transaction that was already correct.
EITHER_SIDE_STEP = (
    "Retrying will not change this: either this session is on the wrong network — power off and "
    "start it again on the one you meant — or your wallet must build the transaction differently."
)

#: Every reason declares its kind here, in one place. A new `RefusalReason` fails the test that
#: sweeps this mapping until it says which kind it is.
REFUSAL_KINDS: dict[RefusalReason, RefusalKind] = {
    RefusalReason.MALFORMED: RefusalKind.TRANSFER_FAILED,
    RefusalReason.NETWORK_MISMATCH: RefusalKind.EITHER_SIDE,
    RefusalReason.MISSING_UTXO: RefusalKind.DEVICE_CANNOT_HELP,
    RefusalReason.SIGHASH_NOT_ALL: RefusalKind.DEVICE_CANNOT_HELP,
    RefusalReason.UNSIGNABLE_INPUT: RefusalKind.DEVICE_CANNOT_HELP,
}

#: The third sentence, per kind. Every kind is here or the sweep test fails.
REFUSAL_STEPS: dict[RefusalKind, str] = {
    RefusalKind.TRANSFER_FAILED: RETRY_STEP,
    RefusalKind.DEVICE_CANNOT_HELP: NO_RETRY_STEP,
    RefusalKind.EITHER_SIDE: EITHER_SIDE_STEP,
}

#: Two sentences per reason: what it is, and why it stops. The third — where the fix is — comes
#: from the kind, so no reason can quietly invent its own retry advice.
REFUSAL_SENTENCES: dict[RefusalReason, tuple[str, str, str]] = {
    RefusalReason.MALFORMED: (
        "psbt-malformed",
        "This transaction did not arrive intact.",
        "Part of it is missing or unreadable, so there is nothing here to review.",
    ),
    RefusalReason.NETWORK_MISMATCH: (
        "psbt-network-mismatch",
        "This transaction was built for a different network than this wallet.",
        "A wallet on one network is never talked into a signature on another.",
    ),
    RefusalReason.MISSING_UTXO: (
        "psbt-missing-utxo",
        "This transaction does not say what one of its inputs is worth.",
        "Without every input's amount and script the fee cannot be computed and the signature "
        "would not be valid.",
    ),
    RefusalReason.SIGHASH_NOT_ALL: (
        "psbt-sighash-not-all",
        "One of the inputs asks to be signed under something other than SIGHASH_ALL.",
        "That would leave part of the transaction free to change after you had signed it.",
    ),
    RefusalReason.UNSIGNABLE_INPUT: (
        "psbt-unsignable-input",
        "This appliance could not derive one of the inputs from its own keys.",
        "It signs every input of a transaction or none of them, so it signs none of this one.",
    ),
}


def refusal_failure(refusal: Refusal) -> Failure:
    """The refusal, in the one failure shape: what it is, why it stops, where the fix is.

    Three sentences, and no override and no confirmation button — the shape is
    `docs/failure-states.md`'s and the widget cannot hold a `Button` at all.
    """
    condition, what, why = REFUSAL_SENTENCES[refusal.reason]
    step = REFUSAL_STEPS[REFUSAL_KINDS[refusal.reason]]
    return Failure(condition=condition, happened=f"{what} {why}", next_steps=(step,))
