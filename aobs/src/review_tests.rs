//! The review panel's pure half, which is all of it that can be asserted without a display.
//!
//! The fixture builds `psbt::Review` directly rather than validating a PSBT. That is
//! deliberate: core already owns the question *does this transaction produce this model* —
//! `psbt_tests.rs` and `corpus_tests.rs` are twenty-four named cases of it — and what is left
//! for this file is the question core cannot answer, which is *does the panel say what the
//! model carries*. Driving it through a PSBT here would test core twice and the panel once.

use std::num::NonZeroU64;
use std::str::FromStr as _;

use aobs_core::bitcoin::bip32::DerivationPath;
use aobs_core::bitcoin::{Address, Amount};
use aobs_core::derive::Network;
use aobs_core::psbt::{OutputKind, OutputRow, Rederivation, Review as Model, Warning};
// `ModelRc` is a handle; iterating one is the `Model` trait's job. The panel's group lists are
// models because that is what a Slint `for` consumes.
use slint::Model as _;

use super::{address_width, label, rows, settled, walk, warning, WIDEST_ADDRESS_CHARS};

/// The widest address class we ship, from BIP-86's own test vector: 62 characters.
const P2TR: &str = "bc1p5cyxnuxmeuwuvkwfem96lqzszd02n6xdcjrs20cac6yqjjwudpxqkedrcr";
/// A 42-character P2WPKH address, which is what the in-tree prototype only ever rendered.
const P2WPKH: &str = "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4";

fn address(text: &str) -> Address {
    Address::from_str(text)
        .expect("a well-formed address")
        .assume_checked()
}

fn payment(text: &str, sat: u64) -> OutputRow {
    OutputRow {
        address: address(text),
        amount: Amount::from_sat(sat),
        kind: OutputKind::Payment,
    }
}

fn change(text: &str, sat: u64, path: &str) -> OutputRow {
    OutputRow {
        address: address(text),
        amount: Amount::from_sat(sat),
        kind: OutputKind::Change {
            path: DerivationPath::from_str(path).expect("a well-formed path"),
            verdict: Rederivation::MatchedByteForByte,
        },
    }
}

/// The prototype's own transaction: two inputs, one payment, one change.
fn model(outputs: Vec<OutputRow>) -> Model {
    let paying: u64 = outputs
        .iter()
        .filter(|row| matches!(row.kind, OutputKind::Payment))
        .map(|row| row.amount.to_sat())
        .sum();
    let returning: u64 = outputs
        .iter()
        .filter(|row| matches!(row.kind, OutputKind::Change { .. }))
        .map(|row| row.amount.to_sat())
        .sum();
    let fee = 5_200;

    Model {
        network: Network::Mainnet,
        input_count: 2,
        input_total: Amount::from_sat(paying + returning + fee),
        leaving: Amount::from_sat(paying + fee),
        paying: Amount::from_sat(paying),
        returning: Amount::from_sat(returning),
        fee: Amount::from_sat(fee),
        vsize: NonZeroU64::new(208).expect("non-zero"),
        outputs,
        warning: None,
    }
}

// --- the rows ----------------------------------------------------------------------------

/// §11.2: payment and change both count as rows, in the transaction's own order.
#[test]
fn every_output_is_a_row_and_the_numbering_is_the_transactions_own() {
    let built = rows(&model(vec![
        payment(P2TR, 4_855_200),
        change(P2WPKH, 30_000, "m/84'/0'/0'/1/7"),
        payment(P2WPKH, 1_000),
    ]));

    assert_eq!(built.len(), 3);
    let numbers: Vec<&str> = built.iter().map(|row| row.index.as_str()).collect();
    assert_eq!(numbers, ["1", "2", "3"]);
    let labels: Vec<&str> = built.iter().map(|row| row.label.as_str()).collect();
    assert_eq!(labels, ["Payment", "Change", "Payment"]);
}

/// §0: **payment addresses are never truncated.** Asserted as *every character of the address
/// is present in the groups*, because truncation is the failure this rule exists against and
/// the groups are the only thing the layout sees.
#[test]
fn a_payment_address_reaches_the_panel_whole() {
    let built = rows(&model(vec![payment(P2TR, 4_855_200)]));
    let joined: String = built[0]
        .groups
        .iter()
        .map(|group| group.to_string())
        .collect();

    assert_eq!(joined, P2TR);
    assert_eq!(joined.chars().count(), WIDEST_ADDRESS_CHARS as usize);
}

/// §0's grouping, as data: 4 characters per group and a short last group, never padded.
#[test]
fn the_groups_are_four_characters_and_the_gap_is_not_among_them() {
    let built = rows(&model(vec![payment(P2TR, 4_855_200)]));
    let groups: Vec<String> = built[0].groups.iter().map(|g| g.to_string()).collect();

    assert_eq!(
        groups.len(),
        16,
        "62 characters is 15 full groups and a pair"
    );
    for group in &groups[..15] {
        assert_eq!(group.chars().count(), 4, "{group}");
    }
    assert_eq!(groups[15].chars().count(), 2);
    // The separation is the layout's sub-cell gap. A space character anywhere in a group
    // would mean it had become a cell of its own.
    assert!(groups.iter().all(|group| !group.contains(' ')));
}

/// §11.2.1: eight decimals, never trimmed, and the digits carry no unit.
#[test]
fn amounts_are_eight_decimals_with_the_unit_left_to_the_label() {
    let built = rows(&model(vec![payment(P2TR, 4_855_200), payment(P2WPKH, 1)]));

    assert_eq!(built[0].amount.as_str(), "0.04855200");
    assert_eq!(built[1].amount.as_str(), "0.00000001");
    assert!(built.iter().all(|row| !row.amount.contains("BTC")));
}

// --- change is settled -------------------------------------------------------------------

/// §11.2: change is presented as **settled**, labelled as re-derived from the seed at its path
/// and matched byte for byte — and the path is in the notation the hub writes paths in.
#[test]
fn change_states_the_path_and_that_the_bytes_matched() {
    let stated = settled(&change(P2WPKH, 30_000, "m/84'/0'/0'/1/7").kind);

    // No `m/` prefix, which is the dependency's own `Display` and therefore the hub's too
    // (`identity.rs` prints `84h/0h/0h`). The two screens agreeing matters more than either
    // notation does: the user is matching one against the other.
    assert_eq!(
        stated,
        "re-derived from the seed at 84h/0h/0h/1/7 and matched byte for byte"
    );
    assert!(
        !stated.contains('\''),
        "the hub writes `h`, so this does too"
    );
}

/// A payment carries no such statement, because nothing was re-derived for it — and §11.2 says
/// **no suspicion attaches to it** either, so the absence is an absence and not a caveat.
#[test]
fn a_payment_carries_no_re_derivation_statement() {
    assert_eq!(settled(&payment(P2TR, 1).kind), "");
    assert_eq!(label(&payment(P2TR, 1).kind), "Payment");
}

// --- the warning -------------------------------------------------------------------------

/// 02-core.md §9's one warning, and §11.2's *copy states the fact and never advises*.
#[test]
fn the_warning_states_the_fact_and_advises_nothing() {
    let sentence = warning(Some(Warning::FeeAbovePayment));

    assert_eq!(
        sentence,
        "You are paying miners more than you are paying your recipient."
    );
    for forbidden in ["may indicate", "are you sure", "I understand", "should"] {
        assert!(
            !sentence.to_lowercase().contains(forbidden),
            "{forbidden} in {sentence}"
        );
    }
}

/// No warning is no sentence. Empty, so the element is absent rather than blank — an empty line
/// where a sentence goes reads as one that failed to print.
#[test]
fn no_warning_is_no_sentence() {
    assert_eq!(warning(None), "");
}

// --- the walk ----------------------------------------------------------------------------

/// §11.3: one screen per **payment** address, and change is not among them — it was settled by
/// the byte-compare before this screen existed.
#[test]
fn the_walk_visits_the_payments_and_skips_the_change() {
    let transaction = model(vec![
        payment(P2TR, 4_855_200),
        change(P2WPKH, 30_000, "m/84'/0'/0'/1/7"),
        payment(P2WPKH, 1_000),
    ]);

    let first = walk(&transaction, 0).expect("a first payment");
    assert_eq!(first.heading, "Payment 1 of 2");
    assert_eq!(first.groups.concat(), P2TR);
    assert!(!first.last);

    let second = walk(&transaction, 1).expect("a second payment");
    assert_eq!(second.heading, "Payment 2 of 2");
    assert_eq!(second.groups.concat(), P2WPKH);
    assert!(second.last, "and it is the last, which the copy turns on");

    assert!(
        walk(&transaction, 2).is_none(),
        "past the last payment is the gate, not a third screen"
    );
}

/// §11.2's bound as the walk inherits it: six outputs is at most six confirmation screens,
/// which is a walk a person completes.
#[test]
fn six_payments_are_six_screens_and_the_sixth_is_the_last() {
    let transaction = model((0..6).map(|_| payment(P2WPKH, 1_000)).collect());

    for position in 0..6 {
        let step = walk(&transaction, position).expect("a payment");
        assert_eq!(step.heading, format!("Payment {} of 6", position + 1));
        assert_eq!(step.last, position == 5);
    }
    assert!(walk(&transaction, 6).is_none());
}

/// A consolidation has no payment at all, so it has no walk — and the gate is the next screen
/// rather than a screen with nothing on it.
#[test]
fn a_consolidation_has_no_walk() {
    let transaction = model(vec![change(P2WPKH, 30_000, "m/84'/0'/0'/1/0")]);

    assert!(walk(&transaction, 0).is_none());
}

// --- the owed measurement ----------------------------------------------------------------

/// 00-overview.md's owed measurement, as the arithmetic the console line is printed from: a
/// 62-character address is 62 cells and **15** gaps, not 16.
#[test]
fn an_address_is_its_cells_plus_one_gap_between_each_pair_of_groups() {
    // The derivation in 04-screens.md §0, at 17 px in DejaVu Sans Mono: 62 cells + 15 gaps.
    let cell = 10.235;
    let gap = 0.25 * 17.0;

    let width = address_width(WIDEST_ADDRESS_CHARS, cell, gap);
    assert!(
        (width - 698.3).abs() < 1.0,
        "§0 derives about 698 px; got {width}"
    );

    // 42 characters is 11 groups and 10 gaps.
    let narrower = address_width(42, cell, gap);
    assert!(
        (narrower - (42.0 * cell + 10.0 * gap)).abs() < 0.001,
        "{narrower}"
    );
}

/// The gap count is one fewer than the group count, at every boundary — including the exact
/// multiple of four, where an off-by-one would add a gap after the last group.
#[test]
fn the_gap_count_is_one_fewer_than_the_group_count() {
    for (chars, groups) in [(1, 1), (4, 1), (5, 2), (8, 2), (62, 16), (90, 23)] {
        let width = address_width(chars, 10.0, 4.0);
        let expected = chars as f32 * 10.0 + (groups - 1) as f32 * 4.0;
        assert!((width - expected).abs() < 0.001, "{chars}: {width}");
    }
}

/// A zero-character address is not a case this appliance has — `AOBS-R07` refused every output
/// with no address form — but the arithmetic must not underflow on the way to saying so.
#[test]
fn no_characters_is_no_width_and_no_underflow() {
    assert_eq!(address_width(0, 10.0, 4.0), 0.0);
}

/// `04-screens.md` §11.4: **the gate is byte-identical with and without the warning.**
///
/// Asserted as the structure that makes it so rather than as an outcome. The gate screen has
/// exactly two inputs — where the cursor is, and how far the hold has got — so there is nothing
/// on it for a fee, a ratio or an advisory to reach, and no arm anywhere that could lengthen the
/// hold when one fires. A property added here would fail this test before it could fail a review.
///
/// It reads the frame the way `router.rs` reads the systemd unit: the claim spans two files, so
/// the test has to as well.
#[test]
fn the_gate_has_no_input_but_the_cursor_and_the_clock() {
    const FRAME: &str = include_str!("../ui/app.slint");

    let body = FRAME
        .split("component GateScreen inherits")
        .nth(1)
        .expect("the frame declares the gate screen");
    let body = body
        .split("\ncomponent ")
        .next()
        .expect("and something follows it");

    let properties: Vec<&str> = body
        .lines()
        .map(str::trim)
        .filter(|line| line.starts_with("in property"))
        .collect();

    assert_eq!(
        properties,
        [
            "in property <int> selected;",
            "in property <float> progress;"
        ],
        "the gate may carry nothing about the transaction"
    );
}
