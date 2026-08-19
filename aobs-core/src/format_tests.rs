//! The address grouping rule, at the three address lengths the appliance actually renders,
//! plus the two properties that make it safe on anything (`05-testing-and-release.md` §3).

use proptest::prelude::*;

use super::*;

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
}
