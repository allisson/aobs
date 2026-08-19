//! What the display turned out to be, and the layout policy that follows from it.
//!
//! **The appliance cannot choose its mode** (04-screens.md §0): the DRM tier takes the
//! connector's preferred mode and the fbdev tier takes whatever the firmware handed
//! `efifb`. So the mode is an input, learned once at startup, and the only free variable
//! is what we draw into it — scale above the design canvas, reflow below it, refuse below
//! the floor.

use crate::fail::Failure;

/// The design canvas every panel is expressed in (04-screens.md §0).
const DESIGN_WIDTH: f32 = 1280.0;
const DESIGN_HEIGHT: f32 = 800.0;

/// The minimum supported mode. Below it the appliance refuses at startup rather than
/// drawing a review screen it cannot draw honestly — the same class of failure as a pixel
/// format outside the renderer's five arms (04-screens.md §0, 01-boot-layer.md §7).
const FLOOR_WIDTH: u32 = 800;
const FLOOR_HEIGHT: u32 = 600;

/// `scale = max(1, min(width / 1280, height / 800))`, from the mode we just learned.
///
/// The `max(1, …)` is the load-bearing half: **below the design canvas the scale stays 1
/// and type never shrinks.** Reflow and wrapping are what bend there, because the type
/// floor *is* the legibility argument the whole visual system rests on (04-screens.md §0).
pub fn scale(width: u32, height: u32) -> f32 {
    let horizontal = width as f32 / DESIGN_WIDTH;
    let vertical = height as f32 / DESIGN_HEIGHT;
    horizontal.min(vertical).max(1.0)
}

/// The logical canvas the scale above produces — what the layout is written against.
pub fn logical(width: u32, height: u32) -> (u32, u32) {
    let scale = scale(width, height);
    (
        (width as f32 / scale).round() as u32,
        (height as f32 / scale).round() as u32,
    )
}

/// Which side of §0's second breakpoint this mode lands on — **two states and no third.**
///
/// The threshold is the design width, which `04-screens.md` §11.2 names in the concrete: the
/// review panel's money-facts rail sits beside the outputs above it and stacks above them
/// below it. Note what the `max(1, …)` in [`scale`] does to this: a physical panel at or
/// above 1280 wide always produces a logical width of at least 1280, so the stacked state is
/// reached only by panels genuinely narrower than the design canvas — 1024×768 and the
/// 800×600 floor, not a 4K screen.
///
/// **Computed here rather than in the frame's own expression language.** Deriving it from the
/// window's width inside Slint makes the layout's own constraints depend on the width they
/// produce, which Slint reports as a binding loop and warns may panic at runtime. The mode is
/// an input; so is this.
pub fn wide(width: u32, height: u32) -> bool {
    logical(width, height).0 >= DESIGN_WIDTH as u32
}

/// Whether this mode is below the floor, in physical pixels.
pub fn below_floor(width: u32, height: u32) -> bool {
    width < FLOOR_WIDTH || height < FLOOR_HEIGHT
}

/// Which of ADR-0016's two tiers won, for the readiness line (01-boot-layer.md §2).
///
/// **Observed, not predicted.** Slint chooses between the tiers itself, in its own
/// `or_else` — a DRM dumb buffer first, `/dev/fb0` if that fails — and exposes no way to
/// ask which arm it took. Re-running that decision here would be a second implementation
/// of it, free to disagree with the first.
///
/// **Two sources, because the two tiers leave different traces.** `DumbBufferDisplay`
/// holds its `/dev/dri/*` descriptor open for the life of the display, so the DRM tier
/// shows up in `/proc/self/fd`. `LinuxFBDisplay` does not: it `mmap`s `/dev/fb0` and drops
/// the descriptor — correctly, since the mapping outlives it — so the fbdev tier shows up
/// only in `/proc/self/maps`. Reading one and not the other would report `unknown` on
/// exactly the tier this whole path exists for.
///
/// Neither found says so rather than picking the likelier answer (standing rule 8):
/// `unknown` fails CI's display rows, which is the right outcome for a tier nobody can
/// name.
pub fn tier() -> &'static str {
    let mut evidence = std::fs::read_to_string("/proc/self/maps").unwrap_or_default();
    if let Ok(fds) = std::fs::read_dir("/proc/self/fd") {
        for fd in fds.flatten() {
            if let Ok(target) = std::fs::read_link(fd.path()) {
                evidence.push('\n');
                evidence.push_str(&target.to_string_lossy());
            }
        }
    }

    if evidence.contains("/dev/dri/") {
        "drm"
    } else if evidence.contains("/dev/fb") {
        "fbdev"
    } else {
        "unknown"
    }
}

/// Why the window could not be created, from what is on the machine.
///
/// 06-codes.md §5 splits the old four-meaning `AOBS-E02` on exactly this question, and
/// Slint reports it as a formatted string the §9 rule forbids us to print and a refactor
/// upstream is free to reword. Device *presence* answers it without reading that string:
/// nothing to draw on at all is `E02`, and a display we could not negotiate with is
/// `E05`. Being wrong in this direction costs a bug report we can act on; being wrong the
/// other way tells a user their firmware handed over nothing when it did.
pub fn window_failure() -> Failure {
    let dri = std::fs::read_dir("/dev/dri").is_ok_and(|mut entries| entries.next().is_some());
    let framebuffer = (0..10).any(|n| std::path::Path::new(&format!("/dev/fb{n}")).exists());

    if dri || framebuffer {
        Failure::PixelFormatUnsupported
    } else {
        Failure::DisplayUnavailable
    }
}

#[cfg(test)]
mod tests {
    use super::{below_floor, logical, scale, wide};

    #[test]
    fn the_design_canvas_and_everything_under_it_scales_by_one() {
        // The whole point of `max(1, …)`: type does not shrink to fit a small panel.
        for (width, height) in [(1280, 800), (1024, 768), (800, 600), (1280, 600)] {
            assert_eq!(scale(width, height), 1.0, "{width}x{height}");
            assert_eq!(logical(width, height), (width, height), "{width}x{height}");
        }
    }

    #[test]
    fn a_larger_panel_scales_by_its_tighter_axis() {
        // 04-screens.md §0: 1920x1080 and 3840x2160 both land on a 1422x800 logical
        // canvas — a 4K panel gets larger type, not more content.
        assert_eq!(scale(1920, 1080), 1.35);
        assert_eq!(logical(1920, 1080), (1422, 800));
        assert_eq!(logical(3840, 2160), (1422, 800));
    }

    #[test]
    fn the_breakpoint_is_the_design_width_and_scaling_keeps_big_panels_on_its_wide_side() {
        // 04-screens.md §0, §11.2: two states, and the threshold is the design width.
        assert!(wide(1280, 800), "the design canvas is the wide state");
        assert!(
            wide(1920, 1080),
            "and so is everything the scale factor lifts onto it"
        );
        assert!(wide(3840, 2160));
        assert!(!wide(1024, 768), "narrower than the canvas stacks");
        assert!(
            !wide(800, 600),
            "including the floor, which is where six outputs are counted"
        );
        // A tall, narrow mode is the reason this reads the logical width and not the scale:
        // the height would happily scale, and the address column is what is short.
        assert!(!wide(1024, 1600));
    }

    #[test]
    fn the_floor_is_eight_hundred_by_six_hundred_on_both_axes() {
        assert!(!below_floor(800, 600));
        assert!(below_floor(799, 600));
        assert!(below_floor(800, 599));
        assert!(below_floor(640, 480));
    }
}
