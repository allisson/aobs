//! Reporting a failure the GUI cannot report itself (01-boot-layer.md §9).
//!
//! One sentence naming what failed, one on what it likely means, one on what to do, the
//! version and build date, and a short failure code so a bug report is actionable. Not a
//! stack trace, not systemd's default spew.
//!
//! **Fixed strings and typed error-variant names only, never formatted program state** —
//! the same rule that governs logs and `Debug`, extended to the one output path that
//! survives a crash. The version and build date are the sole exception, and §10 already
//! rules that they make no security claim.

use crate::buildinfo;
use crate::console;

/// Everything that can stop aobs before or during the one screen it draws.
///
/// Each variant is a *typed* name that the diagnostic prints verbatim, so a bug report
/// carries the arm that was taken rather than a rendering of what went through it.
#[derive(Debug)]
pub enum Failure {
    /// The kernel CSPRNG refused to fill a buffer.
    EntropyUnavailable,
    /// No KMS display was available to draw on.
    DisplayUnavailable,
    /// The event loop returned. Nothing on this appliance asks it to.
    EventLoopExited,
    /// The program unwound out of an internal error.
    Panicked,
}

impl Failure {
    /// The variant's own name, written out rather than derived, so the diagnostic cannot
    /// start printing something else if `Debug` is ever changed.
    fn variant(&self) -> &'static str {
        match self {
            Self::EntropyUnavailable => "EntropyUnavailable",
            Self::DisplayUnavailable => "DisplayUnavailable",
            Self::EventLoopExited => "EventLoopExited",
            Self::Panicked => "Panicked",
        }
    }

    /// The short code a bug report quotes.
    fn code(&self) -> &'static str {
        match self {
            Self::EntropyUnavailable => "AOBS-E01",
            Self::DisplayUnavailable => "AOBS-E02",
            Self::EventLoopExited => "AOBS-E03",
            Self::Panicked => "AOBS-E04",
        }
    }

    /// What failed.
    fn what(&self) -> &'static str {
        match self {
            Self::EntropyUnavailable => "The kernel's random number generator returned no bytes.",
            Self::DisplayUnavailable => "aobs found no display it could draw on.",
            Self::EventLoopExited => "The screen closed on its own.",
            Self::Panicked => "aobs stopped on an internal error.",
        }
    }

    /// What it likely means.
    fn means(&self) -> &'static str {
        match self {
            Self::EntropyUnavailable => {
                "A request that is not supposed to be refusable was refused, so this \
                 machine cannot be trusted to generate a wallet."
            }
            Self::DisplayUnavailable => {
                "This machine most likely booted in legacy BIOS mode. aobs requires UEFI, \
                 which is what guarantees a display without a graphics driver."
            }
            Self::EventLoopExited => {
                "Nothing in this appliance asks the screen to close, so something ended \
                 the session that was not you."
            }
            Self::Panicked => {
                "Any wallet held in memory was erased as the program unwound, and nothing \
                 survives a boot in any case."
            }
        }
    }

    /// What to do.
    fn what_to_do(&self) -> &'static str {
        match self {
            Self::EntropyUnavailable => {
                "Do not use this machine as a signer. Report the failure code below."
            }
            Self::DisplayUnavailable => {
                "Reboot, enter the firmware settings, and select UEFI boot."
            }
            Self::EventLoopExited | Self::Panicked => {
                "Power the machine off, boot it again, and report the failure code below."
            }
        }
    }
}

/// Print the diagnostic block and halt with it visible. Never returns, never powers off.
///
/// Parking rather than exiting is load-bearing: the systemd unit carries
/// `Restart=always` (01-boot-layer.md §2), so an exit here would restart the binary and
/// scroll the only explanation the user is ever going to get off the screen.
pub fn halt(failure: Failure) -> ! {
    let rule = "=".repeat(72);

    console::emit("");
    console::emit(&rule);
    console::emit("aobs could not start.");
    console::emit("");
    console::emit(&format!("  {}", failure.what()));
    console::emit(&format!("  {}", failure.means()));
    console::emit(&format!("  {}", failure.what_to_do()));
    console::emit("");
    console::emit(&format!(
        "  version {}   build {}   {}   {}",
        buildinfo::VERSION,
        buildinfo::build_date(),
        failure.variant(),
        failure.code(),
    ));
    console::emit(&rule);
    console::emit("This machine has halted. Power it off when you have read this.");

    loop {
        std::thread::sleep(std::time::Duration::from_secs(3600));
    }
}

#[cfg(test)]
mod tests {
    use super::Failure;

    const ALL: [Failure; 4] = [
        Failure::EntropyUnavailable,
        Failure::DisplayUnavailable,
        Failure::EventLoopExited,
        Failure::Panicked,
    ];

    #[test]
    fn every_variant_has_a_distinct_code() {
        let mut codes: Vec<&str> = ALL.iter().map(|f| f.code()).collect();
        codes.sort_unstable();
        let before = codes.len();
        codes.dedup();
        assert_eq!(codes.len(), before, "two failures share a code");
    }

    #[test]
    fn every_variant_answers_all_three_questions() {
        // §9 fixes the shape: what failed, what it means, what to do. A variant added
        // later with an empty arm would print a diagnostic that says nothing.
        for failure in &ALL {
            assert!(failure.what().ends_with('.'), "{:?}", failure);
            assert!(failure.means().ends_with('.'), "{:?}", failure);
            assert!(failure.what_to_do().ends_with('.'), "{:?}", failure);
        }
    }

    #[test]
    fn the_variant_name_is_written_out_not_derived() {
        for failure in &ALL {
            assert_eq!(failure.variant(), format!("{failure:?}"));
        }
    }
}
