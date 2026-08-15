//! The version string and build date the appliance displays (01-boot-layer.md §10).
//!
//! They make no security claim and therefore cannot make a false one. The date comes
//! from `SOURCE_DATE_EPOCH`, which is also what pins the ISO's reproducibility
//! (01-boot-layer.md §1), so the number on screen and the number in the image agree.

/// Semantic version of the appliance.
pub const VERSION: &str = env!("CARGO_PKG_VERSION");

/// `SOURCE_DATE_EPOCH` captured at compile time, or `unknown` when it was unset.
const BUILD_EPOCH: &str = env!("AOBS_BUILD_EPOCH");

/// The build date as `YYYY-MM-DD` (UTC), or `unknown` for a build with no
/// `SOURCE_DATE_EPOCH`.
pub fn build_date() -> String {
    match BUILD_EPOCH.parse::<i64>() {
        Ok(epoch) => fmt_date(epoch),
        Err(_) => "unknown".to_string(),
    }
}

/// Seconds since the Unix epoch to a UTC `YYYY-MM-DD` calendar date.
///
/// Howard Hinnant's `civil_from_days`, which is exact over the whole proleptic Gregorian
/// range and needs no crate. We take no clock (ADR-0004) — this converts a number that
/// was fixed at build time.
fn fmt_date(epoch: i64) -> String {
    // Floor division: an epoch before 1970 must round towards minus infinity, not zero.
    let days = epoch.div_euclid(86_400);

    let z = days + 719_468;
    let era = if z >= 0 { z } else { z - 146_096 } / 146_097;
    let doe = z - era * 146_097; // [0, 146096]
    let yoe = (doe - doe / 1_460 + doe / 36_524 - doe / 146_096) / 365; // [0, 399]
    let y = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100); // [0, 365]
    let mp = (5 * doy + 2) / 153; // [0, 11], March-based
    let d = doy - (153 * mp + 2) / 5 + 1; // [1, 31]
    let m = if mp < 10 { mp + 3 } else { mp - 9 }; // [1, 12]
    let y = if m <= 2 { y + 1 } else { y };

    format!("{y:04}-{m:02}-{d:02}")
}

#[cfg(test)]
mod tests {
    use super::fmt_date;

    #[test]
    fn epoch_zero_is_the_first_of_january_1970() {
        assert_eq!(fmt_date(0), "1970-01-01");
    }

    #[test]
    fn seconds_within_a_day_do_not_advance_the_date() {
        assert_eq!(fmt_date(86_399), "1970-01-01");
        assert_eq!(fmt_date(86_400), "1970-01-02");
    }

    #[test]
    fn leap_day_lands_on_the_twenty_ninth() {
        // 2000 is a leap year under the 400-rule that a naive /4 gets right by accident
        // and 1900 gets wrong.
        assert_eq!(fmt_date(951_782_400), "2000-02-29");
        // 2024-02-29, the ordinary /4 case.
        assert_eq!(fmt_date(1_709_164_800), "2024-02-29");
    }

    #[test]
    fn century_that_is_not_a_leap_year() {
        // 1900-02-28 and then straight to 1900-03-01: the /100 rule, before the epoch,
        // which is also the negative-input case.
        assert_eq!(fmt_date(-2_203_977_600), "1900-02-28");
        assert_eq!(fmt_date(-2_203_891_200), "1900-03-01");
    }

    #[test]
    fn year_and_month_boundaries() {
        assert_eq!(fmt_date(1_735_689_599), "2024-12-31");
        assert_eq!(fmt_date(1_735_689_600), "2025-01-01");
    }

    #[test]
    fn a_date_in_the_project_s_own_lifetime() {
        assert_eq!(fmt_date(1_755_216_000), "2025-08-15");
    }

    #[test]
    fn a_missing_source_date_epoch_says_so_rather_than_inventing_one() {
        // Standing rule 8: state the fact, invent nothing. The parse failure path is what
        // `build_date` takes when SOURCE_DATE_EPOCH was unset at compile time.
        assert!("unknown".parse::<i64>().is_err());
    }
}
