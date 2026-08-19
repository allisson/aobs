//! The address grouping rule, at the three address lengths the appliance actually renders,
//! plus the amount rules at the boundaries where a formatter turns into an evaluator
//! (`05-testing-and-release.md` §2), and the properties that make all of it safe on anything (§3).

use core::num::NonZeroU64;

use bitcoin::Amount;
use proptest::prelude::*;

use super::*;

/// The vsize the prototype's `25.0 sat/vB` divides by: two P2WPKH inputs, three outputs.
const PROTOTYPE_VSIZE: NonZeroU64 = NonZeroU64::new(208).unwrap();

/// The three lengths §0 reasons about: a 34-character base58 P2PKH, a 42-character P2WPKH and
/// a 62-character P2TR — the one the gap-not-space rule exists for.
#[test]
fn the_three_rendered_address_lengths_group_in_fours() {
    for address in [
        "1LqBGSKuX5yYUonjxT5qGfpUsXKYYWeabA",
        "bc1qcr8te4kr609gcawutmrza0j4xv80jy8z306fyu",
        "bc1p5cyxnuxmeuwuvkwfem96lqzszd02n6xdcjrs20cac6yqjjwudpxqkedrcr",
    ] {
        let groups = address_groups(address);

        assert_eq!(groups.len(), address.len().div_ceil(4), "{address}");
        assert_eq!(groups.concat(), address, "{address}");
        assert!(
            groups.iter().rev().skip(1).all(|group| group.len() == 4),
            "{groups:?}"
        );
    }
}

/// 62 characters is 15 gaps, which is the arithmetic §0 rests the six-output bound on.
#[test]
fn a_p2tr_address_is_sixteen_groups_and_fifteen_gaps() {
    let groups = address_groups("bc1p5cyxnuxmeuwuvkwfem96lqzszd02n6xdcjrs20cac6yqjjwudpxqkedrcr");

    assert_eq!(groups.len(), 16);
    assert_eq!(groups[15], "cr");
}

#[test]
fn nothing_in_gives_nothing_out() {
    assert!(address_groups("").is_empty());
}

/// The three amounts the prototype renders, which §11.2.1 turned into the rule.
#[test]
fn the_prototypes_amounts_are_written_the_way_the_prototype_writes_them() {
    assert_eq!(btc(Amount::from_sat(4_855_200)), "0.04855200");
    assert_eq!(btc(Amount::from_sat(4_850_000)), "0.04850000");
    assert_eq!(btc(Amount::from_sat(5_200)), "0.00005200");
    assert_eq!(btc(Amount::from_sat(354_800)), "0.00354800");
}

/// Eight decimals at both ends: one satoshi is representable and nothing is trimmed.
#[test]
fn eight_decimals_hold_from_zero_to_the_top_of_the_type() {
    assert_eq!(btc(Amount::ZERO), "0.00000000");
    assert_eq!(btc(Amount::from_sat(1)), "0.00000001");
    assert_eq!(btc(Amount::ONE_BTC), "1.00000000");
    assert_eq!(btc(Amount::MAX_MONEY), "21000000.00000000");
    assert_eq!(btc(Amount::MAX), "184467440737.09551615");
}

/// Satoshi grouping is threes from the right, at every boundary the length crosses one.
#[test]
fn satoshi_digits_group_in_threes_from_the_right() {
    for (sat, expected) in [
        (0, vec!["0"]),
        (1, vec!["1"]),
        (999, vec!["999"]),
        (1_000, vec!["1", "000"]),
        (5_200, vec!["5", "200"]),
        (999_999, vec!["999", "999"]),
        (1_000_000, vec!["1", "000", "000"]),
        (100_000_000, vec!["100", "000", "000"]),
    ] {
        assert_eq!(sat_groups(Amount::from_sat(sat)), expected, "{sat}");
    }
}

/// The prototype's rate, and half-up rounding on the digit that decides it.
#[test]
fn the_fee_rate_is_one_decimal_rounded_half_up() {
    assert_eq!(
        fee_rate_sat_per_vb(Amount::from_sat(5_200), PROTOTYPE_VSIZE),
        "25.0"
    );
    // 5 300 / 208 = 25.48…, which is 25.5 rounded and 25.4 truncated.
    assert_eq!(
        fee_rate_sat_per_vb(Amount::from_sat(5_300), PROTOTYPE_VSIZE),
        "25.5"
    );
    assert_eq!(
        fee_rate_sat_per_vb(Amount::ZERO, PROTOTYPE_VSIZE),
        "0.0",
        "a genuinely zero fee is a zero, not a bound"
    );
}

/// A real fee never reads as no fee — §11.2.1's first round-to-zero bound.
#[test]
fn a_non_zero_fee_below_a_tenth_reads_as_a_bound() {
    let huge = NonZeroU64::new(1_000_000).unwrap();

    assert_eq!(fee_rate_sat_per_vb(Amount::from_sat(1), huge), "< 0.1");
    assert_eq!(fee_rate_sat_per_vb(Amount::from_sat(49_999), huge), "< 0.1");
    assert_eq!(fee_rate_sat_per_vb(Amount::from_sat(50_000), huge), "0.1");
}

/// The prototype's percentage, and §2's `≥` boundary written as a number.
#[test]
fn the_percentage_is_three_decimals() {
    assert_eq!(
        fee_percent_of_paying(Amount::from_sat(5_200), Amount::from_sat(4_850_000)),
        Some("0.107".to_string())
    );
    assert_eq!(
        fee_percent_of_paying(Amount::from_sat(4_850_000), Amount::from_sat(4_850_000)),
        Some("100.000".to_string()),
        "a fee equal to the amount paying is the warning's own boundary"
    );
    assert_eq!(
        fee_percent_of_paying(Amount::ZERO, Amount::from_sat(4_850_000)),
        Some("0.000".to_string())
    );
}

/// A consolidation: §9 says the ratio is undefined and nothing fires, so nothing is written.
#[test]
fn a_consolidation_has_no_percentage_at_all() {
    assert_eq!(
        fee_percent_of_paying(Amount::from_sat(5_200), Amount::ZERO),
        None
    );
    assert_eq!(fee_percent_of_paying(Amount::ZERO, Amount::ZERO), None);
}

/// Neither extreme is clamped, in either direction.
#[test]
fn the_percentage_states_the_fact_at_both_extremes() {
    assert_eq!(
        fee_percent_of_paying(Amount::from_sat(5_200), Amount::from_sat(1)),
        Some("520000.000".to_string()),
        "a one-satoshi payment against a real fee"
    );
    assert_eq!(
        fee_percent_of_paying(Amount::from_sat(1), Amount::MAX_MONEY),
        Some("< 0.001".to_string()),
        "and a real fee that would otherwise print as no fee"
    );
}

proptest! {
    /// Never truncated: the groups always concatenate back to the input, whatever it is.
    #[test]
    fn every_character_survives(text: String) {
        prop_assert_eq!(address_groups(&text).concat(), text);
    }

    /// And no group is ever wider than the column was measured for.
    #[test]
    fn no_group_holds_more_than_four_characters(text: String) {
        for group in address_groups(&text) {
            prop_assert!(group.chars().count() <= 4, "{:?}", group);
        }
    }

    /// The column shape §11.2.1 rests on: one point, eight digits after it, always.
    #[test]
    fn the_btc_form_is_always_eight_decimals(sat: u64) {
        let written = btc(Amount::from_sat(sat));
        let (integer, decimals) = written.split_once('.').expect("a point");

        prop_assert_eq!(decimals.len(), 8, "{}", written);
        prop_assert!(!decimals.contains('.'), "{}", written);
        prop_assert!(!integer.is_empty(), "{}", written);
        prop_assert!(written.chars().all(|c| c.is_ascii_digit() || c == '.'), "{}", written);
    }

    /// Grouping is lossless and every group but the first is full — the digits are the digits.
    #[test]
    fn satoshi_grouping_is_lossless(sat: u64) {
        let groups = sat_groups(Amount::from_sat(sat));

        prop_assert_eq!(groups.concat(), sat.to_string());
        prop_assert!((1..=3).contains(&groups[0].len()), "{:?}", groups);
        prop_assert!(groups.iter().skip(1).all(|g| g.len() == 3), "{:?}", groups);
    }

    /// A fee that exists is never written as a fee that does not — in either form.
    #[test]
    fn a_fee_that_exists_is_never_written_as_zero(fee in 1u64.., vsize in 1u64.., paying in 1u64..) {
        let vsize = NonZeroU64::new(vsize).expect("non-zero");

        prop_assert_ne!(fee_rate_sat_per_vb(Amount::from_sat(fee), vsize), "0.0");
        prop_assert_ne!(
            fee_percent_of_paying(Amount::from_sat(fee), Amount::from_sat(paying)),
            Some("0.000".to_string())
        );
    }
}
