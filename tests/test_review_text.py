"""The review screen's text, without a screen.

Everything asserted here is a rule `docs/review-screen.md` settled and a wrong address could hide
behind: the grouping, the space-separated thousands, the two-line headline, the fee three ways, the
byte-identical label, and the refusal split. It is pure text in and pure text out, which is why
none of it needs an application — and why the app suite beside it can be about keys and screens.
"""

from __future__ import annotations

import json

import pytest

from aobs.core.review import (
    OutputCategory,
    Refusal,
    RefusalReason,
    Review,
    review,
)
from aobs.core.wallet import Network, ScriptType, Wallet
from aobs.ui import reviewtext
from aobs.ui.geometry import MAX_COLUMNS
from aobs.ui.reviewtext import RefusalKind

from conftest import CORPUS, VECTOR_MNEMONIC


def _review(name: str) -> Review:
    network = Network(json.loads((CORPUS / f"{name}.json").read_text())["network"])
    wallet = Wallet.from_mnemonic(VECTOR_MNEMONIC, network=network)
    return review((CORPUS / f"{name}.psbt").read_bytes(), wallet)


SIGNABLE = ["honest_p2wpkh", "honest_p2tr", "honest_mainnet", "many_inputs",
            "change_address_attack", "change_index_out_of_window", "fee_absurd",
            "input_past_the_ceiling", "ansi_escape_label"]


# --- Amounts --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("sats", "expected"),
    [(0, "0.00000000"), (1, "0.00000001"), (1_400_000, "0.01400000"),
     (14_000_000, "0.14000000"), (100_000_000, "1.00000000")],
)
def test_btc_carries_all_eight_decimals_ungrouped(sats: int, expected: str) -> None:
    """`0.01400000` against `0.14000000` is the most likely misread on this screen, and grouping
    the decimals would invent a convention the appliance has no locale to justify."""
    assert reviewtext.btc(sats) == expected


@pytest.mark.parametrize(
    ("sats", "expected"),
    [(0, "0"), (999, "999"), (1_000, "1 000"), (250_000, "250 000"),
     (1_653_100, "1 653 100"), (2_100_000_000_000_000, "2 100 000 000 000 000")],
)
def test_thousands_are_separated_by_spaces_and_never_by_commas(sats: int, expected: str) -> None:
    """A screen already printing `0.01400000` cannot also spend `,` without being ambiguous for
    half the world."""
    assert reviewtext.satoshis(sats) == expected
    assert "," not in reviewtext.satoshis(sats)


# --- Addresses ------------------------------------------------------------------------------------


def test_the_widest_address_the_appliance_can_show_fits_one_unwrapped_line() -> None:
    """A regtest taproot `bcrt1p…` is the widest atom on this screen, and the 96-column cap was
    chosen against it: 16 groups of four is 79 columns, plus the 5-column indent."""
    wallet = Wallet.from_mnemonic(VECTOR_MNEMONIC, network=Network.REGTEST)
    address = wallet.address(ScriptType.P2TR, 0, 0)
    grouped = reviewtext.grouped(address)
    assert "\n" not in grouped
    assert reviewtext.INDENT + len(grouped) <= MAX_COLUMNS - 4
    assert "…" not in grouped and "..." not in grouped


@pytest.mark.parametrize("name", ["honest_p2wpkh", "honest_p2tr", "honest_mainnet"])
def test_every_address_is_grouped_in_fours_with_no_ellipsis_in_any_category(name: str) -> None:
    """Including proven change: the no-middle-ellipsis rule takes no exception for the one
    category the appliance derived itself."""
    reviewed = _review(name)
    categories = {out.category for out in reviewed.outputs}
    assert OutputCategory.CHANGE_PROVEN in categories, "the case being tested is included"

    for block, out in zip(reviewtext.output_blocks(reviewed), reviewed.outputs, strict=True):
        assert out.address is not None
        assert block.address == " ".join(
            out.address[i : i + 4] for i in range(0, len(out.address), 4)
        )
        assert block.address.replace(" ", "") == out.address, "full, and nothing dropped"
        assert "…" not in block.address and "..." not in block.address
        assert "\n" not in block.address


def test_proven_change_leads_with_the_path_and_dims_the_address() -> None:
    reviewed = _review("honest_p2wpkh")
    payment, change = reviewtext.output_blocks(reviewed)
    assert change.path == "m/84h/1h/0h/1/0"
    assert change.address_dimmed
    assert payment.path is None
    assert not payment.address_dimmed


# --- The label ------------------------------------------------------------------------------------


def test_not_proven_renders_the_payment_label_byte_identically() -> None:
    """A third on-screen label would reintroduce the third category as a middle ground, and a
    middle ground is where a user parks a decision."""
    attack = reviewtext.output_blocks(_review("change_address_attack"))
    honest = reviewtext.output_blocks(_review("honest_mainnet"))

    fake_change = attack[1]
    assert _label_of(fake_change) == _label_of(attack[0]) == _label_of(honest[0]) == "PAYMENT"
    assert "PROVEN" not in fake_change.heading
    assert "UNVERIFIED" not in fake_change.heading


def _label_of(block: reviewtext.OutputBlock) -> str:
    return block.heading.split(maxsplit=1)[1].split("  ")[0]


def test_the_not_proven_warning_names_the_claim_without_accusing_the_wallet() -> None:
    fake_change = reviewtext.output_blocks(_review("change_address_attack"))[1]
    (note,) = fake_change.notes
    assert note.warning
    assert "your own change" in note.text
    assert "could not derive it from its own keys" in note.text
    assert "Verify this address" in note.text
    # Not a scan to retry, and not an accusation: a gap-limit miss and an attack are
    # indistinguishable from here.
    assert "scan" not in note.text.lower()
    assert "attack" not in note.text.lower()


def test_address_not_seen_before_is_a_neutral_fact_and_not_a_warning() -> None:
    """It is true of essentially every legitimate payment. At warning strength everywhere it is
    noise that teaches skipping, and warning styling is reserved for NOT PROVEN."""
    payment = reviewtext.output_blocks(_review("honest_p2wpkh"))[0]
    (note,) = payment.notes
    assert note.text == reviewtext.ADDRESS_NOT_SEEN
    assert not note.warning


# --- The footer -----------------------------------------------------------------------------------


def test_the_headline_shows_its_composition_on_two_lines_btc_then_sats() -> None:
    reviewed = _review("honest_p2wpkh")
    assert reviewed.headline is not None
    first, second = reviewtext.headline_lines(reviewed)

    assert reviewtext.btc(reviewed.headline.payments_sats) in first
    assert reviewtext.btc(reviewed.headline.fee_sats) in first
    assert reviewtext.btc(reviewed.headline.total_leaving_sats) in first
    assert "+" in first and "=" in first
    assert second.strip() == f"{reviewtext.satoshis(1_403_420)} sats"
    assert len(first) <= reviewtext.ROW_COLUMNS


def test_the_fee_renders_three_ways() -> None:
    reviewed = _review("fee_absurd")
    assert reviewed.fee is not None
    line = reviewtext.fee_line(reviewed)
    assert line is not None
    assert "400 000 sats" in line
    assert f"{reviewed.fee.sat_per_vbyte:.1f} sat/vB" in line
    assert "80.00% of the amount sent" in line


def test_the_percentage_is_omitted_rather_than_faked_when_it_has_no_meaning() -> None:
    """A spend with no payment at all — everything proven change — has no share-of-sent."""
    reviewed = Review(network="signet", fingerprint_hex="73c5da0a", refusal=None)
    assert reviewtext.fee_line(reviewed) is None


@pytest.mark.parametrize("name", SIGNABLE)
def test_every_footer_line_fits_the_column_budget(name: str) -> None:
    """One column budget means one layout to test across the three real console geometries."""
    reviewed = _review(name)
    lines = [
        *reviewtext.header_lines(reviewed),
        *reviewtext.transaction_warning_lines(reviewed),
        *reviewtext.headline_lines(reviewed),
        reviewtext.fee_line(reviewed) or "",
        reviewtext.LOCKED_KEYS,
        reviewtext.UNLOCKED_KEYS,
        reviewtext.lock_line(1, 4, len(reviewed.outputs)),
    ]
    assert all(len(line) <= reviewtext.ROW_COLUMNS for line in lines), name
    for block in reviewtext.output_blocks(reviewed):
        assert len(block.heading) <= reviewtext.ROW_COLUMNS
        assert reviewtext.INDENT + len(block.address) <= reviewtext.ROW_COLUMNS


def test_the_locked_key_line_does_not_print_the_sign_key() -> None:
    """Printing a key that does nothing teaches pressing keys that do nothing."""
    assert "F10" not in reviewtext.LOCKED_KEYS
    assert "sign" not in reviewtext.LOCKED_KEYS
    assert "F10 sign" in reviewtext.UNLOCKED_KEYS


# --- The confirm screen ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", SIGNABLE)
def test_the_confirm_text_carries_no_address_at_all(name: str) -> None:
    """A substring sweep over every output address, not a layout check: a second, shallower pass
    at the moment of commitment substitutes for the review rather than adding to it."""
    reviewed = _review(name)
    text = "\n".join(reviewtext.confirm_lines(reviewed))
    for out in reviewed.outputs:
        assert out.address is not None
        assert out.address not in text
        assert reviewtext.grouped(out.address) not in text


def test_the_confirm_text_carries_the_number_and_the_not_proven_tally() -> None:
    reviewed = _review("change_address_attack")
    text = "\n".join(reviewtext.confirm_lines(reviewed))
    assert reviewtext.btc(1_200_000) in text
    assert reviewtext.satoshis(1_200_000) in text
    assert "2 payment outputs, 1 of which this appliance could not prove" in text
    assert "is your own change." in text
    # The attack spends the whole balance, so nothing returns — and the screen says so rather
    # than leaving the reader to notice an absence.
    assert "No change returns to this wallet." in text


def test_a_transaction_with_nothing_unproven_says_nothing_about_proving() -> None:
    text = "\n".join(reviewtext.confirm_lines(_review("honest_p2wpkh")))
    assert "1 payment output." in text
    assert "could not prove" not in text
    assert "1 proven change output returns 0.00082500 BTC to this wallet." in text


# --- Refusals -------------------------------------------------------------------------------------


def test_every_refusal_reason_declares_its_kind() -> None:
    """A new `RefusalReason` fails here until it says which kind it is, which is the point of the
    mapping being in one place."""
    assert set(reviewtext.REFUSAL_KINDS) == set(RefusalReason)
    assert set(reviewtext.REFUSAL_SENTENCES) == set(RefusalReason)


@pytest.mark.parametrize("reason", list(RefusalReason))
def test_exactly_one_reason_says_try_scanning_again(reason: RefusalReason) -> None:
    """A truncated scan is the only cause a retry fixes. Diluting that one honest retry with five
    dishonest ones is how a user learns to ignore it."""
    failure = reviewtext.refusal_failure(Refusal(reason))
    retries = reviewtext.RETRY_STEP in failure.next_steps
    assert retries == (reason is RefusalReason.MALFORMED)
    if not retries:
        assert reviewtext.NO_RETRY_STEP in failure.next_steps


def test_only_malformed_is_a_failed_transfer() -> None:
    transfer = [
        reason
        for reason, kind in reviewtext.REFUSAL_KINDS.items()
        if kind is RefusalKind.TRANSFER_FAILED
    ]
    assert transfer == [RefusalReason.MALFORMED]


@pytest.mark.parametrize("reason", list(RefusalReason))
def test_a_refusal_is_three_sentences_and_a_stable_condition_name(reason: RefusalReason) -> None:
    """What it is, why it stops, where the fix is — so the user does not retry blindly."""
    failure = reviewtext.refusal_failure(Refusal(reason))
    assert failure.happened.count(". ") == 1, "what it is, and why it stops"
    assert failure.happened.endswith(".")
    assert len(failure.next_steps) == 1, "and where the fix is"
    assert failure.condition.islower()
    assert " " not in failure.condition
    assert not any(char.isdigit() for char in failure.condition)
