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
///
/// The codes are `06-codes.md` §5's registry, which is the authority: they are permanent
/// from the first signed ISO, never renumbered, and never reused for another condition.
/// `AOBS-E00` is not here because it is not ours — the wrapper prints it when this binary
/// never spoke at all, which is the one code the app cannot report.
#[derive(Debug)]
pub enum Failure {
    /// The kernel CSPRNG refused to fill a buffer.
    EntropyUnavailable,
    /// No display at all: no DRM device and no firmware framebuffer.
    DisplayUnavailable,
    /// The event loop returned. Nothing on this appliance asks it to.
    EventLoopExited,
    /// The program unwound out of an internal error.
    Panicked,
    /// A display device exists and the renderer could not negotiate a pixel format with
    /// it — `LinuxFBDisplay`'s five accepted arms (01-boot-layer.md §7).
    PixelFormatUnsupported,
    /// A framebuffer exists and its mode is below the 800×600 floor (04-screens.md §0).
    ModeBelowFloor,
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
            Self::PixelFormatUnsupported => "PixelFormatUnsupported",
            Self::ModeBelowFloor => "ModeBelowFloor",
        }
    }

    /// The short code a bug report quotes.
    fn code(&self) -> &'static str {
        match self {
            Self::EntropyUnavailable => "AOBS-E01",
            Self::DisplayUnavailable => "AOBS-E02",
            Self::EventLoopExited => "AOBS-E03",
            Self::Panicked => "AOBS-E04",
            Self::PixelFormatUnsupported => "AOBS-E05",
            Self::ModeBelowFloor => "AOBS-E06",
        }
    }

    /// What failed.
    fn what(&self) -> &'static str {
        match self {
            Self::EntropyUnavailable => "The kernel's random number generator returned no bytes.",
            Self::DisplayUnavailable => "aobs found no display it could draw on.",
            Self::EventLoopExited => "The screen closed on its own.",
            Self::Panicked => "aobs stopped on an internal error.",
            Self::PixelFormatUnsupported => {
                "This machine has a display, and aobs could not agree with it on a pixel \
                 format."
            }
            Self::ModeBelowFloor => "This screen is smaller than aobs can draw on.",
        }
    }

    /// What it likely means.
    fn means(&self) -> &'static str {
        match self {
            Self::EntropyUnavailable => {
                "A request that is not supposed to be refusable was refused, so this \
                 machine cannot be trusted to generate a wallet."
            }
            // What was observed, and no guess at a cause: this copy used to blame legacy
            // BIOS, which ADR-0016 falsified — `vesafb` means such a machine would have
            // had a framebuffer too (06-codes.md §5).
            Self::DisplayUnavailable => {
                "This machine's firmware handed over no framebuffer, and it has no \
                 graphics driver aobs could use instead."
            }
            Self::EventLoopExited => {
                "Nothing in this appliance asks the screen to close, so something ended \
                 the session that was not you."
            }
            Self::Panicked => {
                "Any wallet held in memory was erased as the program unwound, and nothing \
                 survives a boot in any case."
            }
            Self::PixelFormatUnsupported => {
                "This is a bug we can fix once we know which format your firmware \
                 reports, and it is worth reporting."
            }
            Self::ModeBelowFloor => {
                "aobs needs 800 by 600 pixels to show a transaction honestly, and it \
                 refuses to sign on a screen where it cannot."
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
                "Use another machine as your signer. Report the failure code below."
            }
            Self::EventLoopExited | Self::Panicked => {
                "Power the machine off, boot it again, and report the failure code below."
            }
            // Not "boot it again": the format is what the firmware reports every time, so
            // rebooting changes nothing. 06-codes.md §5 — this is the one display failure
            // whose remedy is a bug report.
            Self::PixelFormatUnsupported => {
                "Use another machine as your signer, and report the failure code below."
            }
            Self::ModeBelowFloor => {
                "Use a screen of at least 800 by 600, or another machine as your signer."
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

    const ALL: [Failure; 6] = [
        Failure::EntropyUnavailable,
        Failure::DisplayUnavailable,
        Failure::EventLoopExited,
        Failure::Panicked,
        Failure::PixelFormatUnsupported,
        Failure::ModeBelowFloor,
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
    fn the_codes_are_exactly_the_registrys_startup_space() {
        // 06-codes.md §5's table, and §7: a variant added in code with an invented code
        // fails a test rather than shipping. `AOBS-E00` is the wrapper's own — the app
        // cannot report the case where it never spoke — so its absence here is the point.
        let mut codes: Vec<&str> = ALL.iter().map(|f| f.code()).collect();
        codes.sort_unstable();
        assert_eq!(
            codes,
            ["AOBS-E01", "AOBS-E02", "AOBS-E03", "AOBS-E04", "AOBS-E05", "AOBS-E06"]
        );
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
