//! Address and amount formatting — the ninth 98%-coverage component, because the review
//! screen *is* the mitigation (`05-testing-and-release.md` §1).
//!
//! Two rules as data. `04-screens.md` §0 fixes address rendering everywhere it appears —
//! 4-character groups, monospace, never truncated for a payment address. §11.2.1 fixes every
//! number on the review panel ([#100](https://github.com/allisson/aobs/issues/100)): BTC with
//! eight decimals never trimmed, satoshi digits grouped in threes, `sat/vB` to one decimal
//! against the predicted signed vsize, and the fee against the amount paying to three
//! decimals.
//!
//! **Nothing here decides anything.** The one advisory warning is a typed variant in the review
//! model (`02-core.md` §9) and the shell renders it; this module never evaluates a condition,
//! and never reads a network — the unit is `BTC` on both, so ADR-0015's identical sessions stay
//! identical. The two places where rounding *would* have asserted something are the bounds
//! below: a real fee is never written as no fee, and an undefined ratio is never written as a
//! zero.
//!
//! Units are the shell's labels, not ours: these functions return digits.

use core::num::NonZeroU64;

use bitcoin::Amount;

/// The eight decimals [`btc`] never trims.
const SAT_PER_BTC: u64 = 100_000_000;

/// An address split into the 4-character groups it is rendered in.
///
/// **The separation is a gap, not a space** (`04-screens.md` §0), so the groups come back
/// separately for the shell to lay out with a sub-cell gap of about 0.25 em. Joining them with
/// a space character would cost a full monospace cell per gap — 77 cells instead of 62 + 15
/// gaps for a P2TR address, which wraps at the 800×600 floor and turns §11.2's six-output
/// bound into a three-output one.
///
/// Empty input gives no groups; a final short group is returned as it is. Grouping is over
/// characters rather than bytes: every address we derive is ASCII, and this cannot be the
/// place a scanned string panics.
#[must_use]
pub fn address_groups(address: &str) -> Vec<&str> {
    let starts: Vec<usize> = address
        .char_indices()
        .step_by(4)
        .map(|(offset, _)| offset)
        .collect();

    starts
        .iter()
        .enumerate()
        .map(|(group, &start)| match starts.get(group + 1) {
            Some(&end) => &address[start..end],
            None => &address[start..],
        })
        .collect()
}

/// An amount in BTC with **eight decimals, never trimmed**: `0.00000001`, `0.04855200`,
/// `21000000.00000000`.
///
/// Eight decimals is exactly what BTC needs to carry one satoshi, so nothing is rounded and
/// nothing the type can hold is unrepresentable. The fixed width is the point: the decimal
/// point lands in the same column on every row of the rail, so a magnitude error reads as a
/// misaligned column rather than as digits to count. The cost — six meaningless zeros in front
/// of a small number — is what [`sat_groups`] buys back for the fee, the one row that pays it.
///
/// The digits are not grouped. The fixed point already anchors the magnitude, so a second
/// grouping rule beside the address rule would buy no scan help (`04-screens.md` §11.2.1).
#[must_use]
pub fn btc(amount: Amount) -> String {
    let sat = amount.to_sat();

    format!("{}.{:08}", sat / SAT_PER_BTC, sat % SAT_PER_BTC)
}

/// An amount in satoshis, split into the 3-digit groups it is rendered in: `5 200` comes back
/// as `["5", "200"]`.
///
/// **The separation is §0's sub-cell gap, not a space character** — the same mechanism as
/// [`address_groups`], which is why the groups come back separately for the shell to lay out. A
/// real space costs a full monospace cell per gap where the gap costs a quarter, and cells at
/// the 800×600 floor are what §11.2's six-output bound is made of.
///
/// Threes rather than the address rule's fours because the jobs differ: four for characters
/// compared one at a time, three for digits read as a magnitude. Only the fee is rendered this
/// way — it is the number [`btc`] serves worst, and the only one compared against a market
/// quoted in satoshis.
#[must_use]
pub fn sat_groups(amount: Amount) -> Vec<String> {
    let mut sat = amount.to_sat();
    let mut groups = Vec::new();

    while sat >= 1_000 {
        groups.push(format!("{:03}", sat % 1_000));
        sat /= 1_000;
    }
    groups.push(sat.to_string());
    groups.reverse();

    groups
}

/// The fee rate in `sat/vB` to one decimal: `25.0`.
///
/// `vsize` is the **predicted vsize of the signed transaction**, which the review model computes
/// from our own four script types — the PSBT carries an unsigned transaction, so the size is a
/// prediction, and it is charged the smaller 71-byte ECDSA signature element so the rate is
/// never displayed lower than what will be paid (`02-core.md` §9, `04-screens.md` §11.2.1). It
/// is a [`NonZeroU64`] because a transaction has a size: the divisor's non-zero-ness is a
/// property of the input, not a case for this function to have an opinion about.
///
/// A non-zero fee that would round to `0.0` comes back as `< 0.1` instead. Writing a real fee as
/// no fee would be this function asserting something, and asserting is deciding.
#[must_use]
pub fn fee_rate_sat_per_vb(fee: Amount, vsize: NonZeroU64) -> String {
    let tenths = round_div(u128::from(fee.to_sat()) * 10, u128::from(vsize.get()));

    if tenths == 0 && fee != Amount::ZERO {
        return "< 0.1".to_string();
    }

    format!("{}.{}", tenths / 10, tenths % 10)
}

/// The fee as a percentage of the amount paying, to three decimals: `0.107`.
///
/// `paying` is the total to non-change outputs — §9's own warning denominator, so the two
/// numbers cannot disagree about what they are about. **`None` for a consolidation**: with no
/// non-change outputs the ratio is undefined, §9 says nothing fires, and the absence is typed
/// rather than rendered as a zero, an infinity or a dash.
///
/// A non-zero ratio that would round to `0.000` comes back as `< 0.001`, for the reason
/// [`fee_rate_sat_per_vb`] gives. Nothing is clamped at the other end: a 5 200-satoshi fee
/// against a one-satoshi payment is `520000.000`, which is the fact.
#[must_use]
pub fn fee_percent_of_paying(fee: Amount, paying: Amount) -> Option<String> {
    let paying = NonZeroU64::new(paying.to_sat())?;
    let thousandths = round_div(u128::from(fee.to_sat()) * 100_000, u128::from(paying.get()));

    if thousandths == 0 && fee != Amount::ZERO {
        return Some("< 0.001".to_string());
    }

    Some(format!(
        "{}.{:03}",
        thousandths / 1_000,
        thousandths % 1_000
    ))
}

/// Integer division rounding half up. `u128` throughout because the numerators carry a scale
/// factor over an amount that may be [`Amount::MAX`].
fn round_div(numerator: u128, denominator: u128) -> u128 {
    (numerator + denominator / 2) / denominator
}

#[cfg(test)]
#[path = "format_tests.rs"]
mod tests;
