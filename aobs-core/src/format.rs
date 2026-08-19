//! Address and amount formatting — the ninth 98%-coverage component, because the review
//! screen *is* the mitigation (`05-testing-and-release.md` §1).
//!
//! **Only the address half exists.** `04-screens.md` §0 fixes address rendering everywhere it
//! appears — 4-character groups, monospace, never truncated for a payment address — and this
//! module is that rule as data. Amount rendering has no such rule yet: §11.2 names *what* the
//! rail states (amount leaving, amount paying, fee absolute, as a rate and as a percentage)
//! and no spec text fixes the unit, the decimal places or the thousands treatment. That is a
//! ticket rather than a gap to fill in here —
//! [#100](https://github.com/allisson/aobs/issues/100) — and it lands with `02-core.md` §9's
//! review model, where the numbers first exist.

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

#[cfg(test)]
#[path = "format_tests.rs"]
mod tests;
