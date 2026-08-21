//! The outbound animation and the one re-display slot (`04-screens.md` §11.5, `02-core.md` §12).
//!
//! **The symbol is core's; the pixels are this module's.** `aobs_core::outbound` picks the version,
//! the ECC level and the fragment length and hands back a module matrix — so nothing here decides
//! whether a payload fit, and nothing here can make the animation refuse (`03-transport.md` §8).
//! What is left is a timer at 4 fps and one buffer of black and white pixels.
//!
//! **One slot, overwritten by each new signature. No list and no selection UI** (`02-core.md`
//! §12). Holding many would create a state in which the user picks which signed transaction to
//! transmit from a list they cannot verify: with no names, no labels and no clock the only
//! distinguishing facts are amount and destination, which is exactly what §11.5 removes from this
//! path. With one slot there is nothing to select and the class does not exist.
//!
//! **Nothing is zeroized between transactions, and that is a decision rather than an omission**
//! (`02-core.md` §12). Every artifact that turns over on this path is public: the inbound PSBT, the
//! signed transaction, the review model. The only secret in play is the wallet's key material,
//! which the session model deliberately grants the whole session — and a scrub step here would
//! reintroduce exactly the lifetime boundary that model rejects, bought for material that is not
//! secret. Standing rule 9 applies to why it would be a promise we could not verify.
//!
//! **The animation stops when the screen is left, and the slot does not.** Those are two different
//! lifetimes: the timer is about what is on screen, and the slot is about the rest of the session.

use std::cell::RefCell;
use std::rc::Rc;
use std::time::Duration;

use aobs_core::outbound::{Animation, Symbol};
use slint::{ComponentHandle, Image, Rgb8Pixel, SharedPixelBuffer, Timer, TimerMode};

use crate::{AppWindow, Screen};

/// §11.5's static part count. **No counter, no percentage** — the count is stated once and the
/// symbol's own flicker carries liveness.
fn parts_note(parts: usize) -> String {
    // Nothing at all in the single-part case (§11.5): there is no fraction, and a *"1 part"* would
    // be a statement about our encoding rather than about what the user has to do.
    if parts == 1 {
        return String::new();
    }
    format!("{parts} parts, on a loop. Keep the camera steady until your wallet says it has the transaction.")
}

/// The signing path's far side: the slot, and the animation that is running now.
pub struct Outbound {
    /// §12's one slot: the most recently signed transaction's bytes, or nothing yet.
    ///
    /// A `Vec<u8>` and not a `Psbt`, because what this holds is what goes on the wire and the
    /// serialisation is the one form a re-display has to reproduce byte for byte.
    signed: RefCell<Option<Vec<u8>>>,
    /// The animation the timer is drawing from.
    ///
    /// An `Rc` of its own rather than a field the timer's closure reaches through `self`: the
    /// closure is stored in `timer`, so a closure holding an `Rc<Outbound>` would be a cycle and
    /// the slot would never be dropped — which is the one thing `session.rs` is not allowed to be
    /// either, for the same reason.
    animation: Rc<RefCell<Option<Animation>>>,
    timer: Timer,
}

/// Build the slot. It wires no callback: every press on §11.5's screen is an intent.
pub fn wire() -> Rc<Outbound> {
    Rc::new(Outbound {
        signed: RefCell::new(None),
        animation: Rc::new(RefCell::new(None)),
        timer: Timer::default(),
    })
}

impl Outbound {
    /// A signature has just been produced. **Take the slot and show it.**
    ///
    /// The previous occupant is replaced with no warning, which `02-core.md` §12 settles: the
    /// warning would clear the bar — we cannot know whether the host received the last one, and
    /// the user can — but it would land several screens away from the hold that actually replaces
    /// it, and what is at stake is time rather than money.
    pub fn arrived(&self, ui: &AppWindow, bytes: Vec<u8>) {
        self.signed.replace(Some(bytes));
        self.show(ui);
    }

    /// §7's re-display row: the same screen, from the slot, for the rest of the session.
    ///
    /// **A fresh animation rather than a resumed one.** BC-UR is rateless, so where the previous
    /// animation had got to is not information — and starting again is what makes a re-display and
    /// a first display the same screen.
    pub fn redisplay(&self, ui: &AppWindow) {
        self.show(ui);
    }

    /// Leaving §11.5's screen: stop drawing. **The slot is untouched** — that is what makes the
    /// absent *did it scan?* prompt safe (§11.5).
    ///
    /// A no-op on every other screen, which is why the router can call it on every cancel without
    /// knowing where it is.
    pub fn leave(&self) {
        self.timer.stop();
        self.animation.replace(None);
    }

    /// Put the slot on screen and start the animation at 4 fps.
    ///
    /// Nothing is drawn when the slot is empty: unreachable by navigation, since §7's row does not
    /// exist until a signature does, and nothing drawn is the honest answer to nothing held
    /// (standing rule 8).
    fn show(&self, ui: &AppWindow) {
        let Some(bytes) = self.signed.borrow().clone() else {
            return;
        };

        let mut animation = Animation::psbt(&bytes);
        ui.set_outbound_parts(parts_note(animation.parts()).into());
        ui.set_outbound_qr(image_of(&animation.next_symbol(), quiet_zone(ui)));
        ui.set_signed_available(true);
        ui.set_screen(Screen::Outbound);
        self.animation.replace(Some(animation));

        // **4 fps, looping indefinitely with fresh parts** (`03-transport.md` §6). No stop
        // condition: with no feedback channel, any stop condition would be arbitrary.
        let source = self.animation.clone();
        let handle = ui.as_weak();
        let quiet = quiet_zone(ui);
        self.timer
            .start(TimerMode::Repeated, frame_interval(ui), move || {
                // The borrow ends before the property is set, which is this crate's standing
                // discipline around `RefCell` and Slint.
                let Some(symbol) = source
                    .borrow_mut()
                    .as_mut()
                    .map(aobs_core::outbound::Animation::next_symbol)
                else {
                    return;
                };
                if let Some(ui) = handle.upgrade() {
                    ui.set_outbound_qr(image_of(&symbol, quiet));
                }
            });
    }
}

/// §6's frame rate, read off the layout rather than restated here — it is the number the
/// recovery-time arithmetic was computed at, and one copy of it is one number.
fn frame_interval(ui: &AppWindow) -> Duration {
    // A Slint `duration` crosses the generated interface as milliseconds in an `i64`.
    let millis = ui.global::<crate::Metrics>().get_outbound_frame();
    Duration::from_millis(u64::try_from(millis).unwrap_or(250))
}

/// The quiet zone in modules, from the same global.
fn quiet_zone(ui: &AppWindow) -> u32 {
    u32::try_from(ui.global::<crate::Metrics>().get_quiet_zone()).unwrap_or(4)
}

/// One symbol as one pixel per module, plus `quiet` modules of light border on every side.
///
/// **One pixel per module and the layout scales it**, which is why the frame draws it
/// `pixelated`: a smoothing filter applied to a matrix of bits blurs exactly the edges a scanner
/// is looking for. Slint offers no monochrome buffer, so black and white go into all three
/// channels — the same number three times, which is not a colour conversion.
fn image_of(symbol: &Symbol, quiet: u32) -> Image {
    let side = symbol.size() + 2 * quiet;
    let mut buffer = SharedPixelBuffer::<Rgb8Pixel>::new(side, side);
    for (index, pixel) in buffer.make_mut_slice().iter_mut().enumerate() {
        let index = index as u32;
        let (x, y) = (index % side, index / side);
        let dark = x >= quiet && y >= quiet && symbol.dark(x - quiet, y - quiet);
        let value = if dark { 0 } else { 255 };
        *pixel = Rgb8Pixel {
            r: value,
            g: value,
            b: value,
        };
    }
    Image::from_rgb8(buffer)
}

#[cfg(test)]
mod tests {
    use super::{image_of, parts_note};
    use aobs_core::outbound::Animation;

    /// §11.5: **nothing at all in the single-part case**, and the static count otherwise.
    #[test]
    fn the_part_count_is_stated_once_or_not_at_all() {
        assert_eq!(parts_note(1), "");
        assert!(parts_note(4).starts_with("4 parts"), "{}", parts_note(4));
    }

    /// **No counter and no percentage** (§11.5). Asserted against the sentence rather than
    /// promised, because the failure is somebody helpfully adding one.
    #[test]
    fn the_part_count_carries_no_progress() {
        let note = parts_note(7);
        assert!(!note.contains('%'), "{note}");
        assert!(!note.contains(" of "), "{note}");
        // **Static** is structural rather than asserted here: the sentence is a function of the
        // fragment count alone, so there is no argument a position could arrive through and no
        // sequence of frames that could change it.
        assert_eq!(note, parts_note(7));
    }

    /// The quiet zone is the painter's: `quiet` modules of light on every side, and the matrix in
    /// the middle.
    #[test]
    fn the_symbol_is_drawn_with_its_quiet_zone_around_it() {
        let mut animation = Animation::psbt(&[0x70, 0x73, 0x62, 0x74, 0xff]);
        let symbol = animation.next_symbol();
        let quiet = 4;
        let image = image_of(&symbol, quiet);

        let side = symbol.size() + 2 * quiet;
        assert_eq!(image.size().width, side);
        assert_eq!(image.size().height, side);

        let rgb = image.to_rgb8().expect("built from an rgb8 buffer");
        let pixels = rgb.as_slice();
        let at = |x: u32, y: u32| pixels[(y * side + x) as usize];

        // Every border pixel is light.
        for n in 0..side {
            assert_eq!(at(n, 0).r, 255);
            assert_eq!(at(0, n).r, 255);
            assert_eq!(at(n, side - 1).r, 255);
            assert_eq!(at(side - 1, n).r, 255);
        }
        // And the finder pattern's corner, which is dark in every QR code ever made, lands at the
        // top-left of the matrix rather than of the image.
        assert_eq!(at(quiet, quiet).r, 0);
        assert!(symbol.dark(0, 0));
    }

    /// `04-screens.md` §11.5: **no repeat of the amounts.** The review was the moment of truth,
    /// and restating money facts afterwards invites verification at the one moment when nothing
    /// can be changed — so the screen carries the symbol, the static count and the room to draw
    /// in, and has no input a number could arrive through.
    ///
    /// Read out of the frame, the same way `review_tests.rs` reads the gate's property list: the
    /// claim spans two files.
    #[test]
    fn the_outbound_screen_has_no_input_a_money_fact_could_arrive_through() {
        const FRAME: &str = include_str!("../ui/app.slint");

        let body = FRAME
            .split("component OutboundScreen inherits")
            .nth(1)
            .expect("the frame declares the outbound screen");
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
                "in property <image> qr;",
                "in property <string> parts;",
                "in property <length> side;",
                "in property <int> selected;",
            ]
        );
    }

    /// A dark module is black in all three channels and a light one is white in all three: the
    /// same number three times, so nothing on the way to the framebuffer tints it.
    #[test]
    fn a_module_is_the_same_number_three_times() {
        let mut animation = Animation::psbt(&[1, 2, 3, 4]);
        let symbol = animation.next_symbol();
        let image = image_of(&symbol, 0);
        let rgb = image.to_rgb8().expect("built from an rgb8 buffer");

        for pixel in rgb.as_slice() {
            assert!(pixel.r == 0 || pixel.r == 255, "{}", pixel.r);
            assert_eq!((pixel.r, pixel.g, pixel.b), (pixel.r, pixel.r, pixel.r));
        }
    }
}
