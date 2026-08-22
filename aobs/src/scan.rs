//! The scanning screen: one component, three configurations (04-screens.md §11.1).
//!
//! Signing, verify and restore differ in exactly two things — the copy naming what this screen
//! wants, and whether a progress element exists at all — and **both answers come from
//! [`Class`]** rather than from a table here. That is what makes *three configurations* one
//! screen instead of three that drifted.
//!
//! **Nothing here decides anything about a payload.** Every symbol goes straight into core's
//! [`Scanner`], which owns §2's class check and §3's four bounds; what comes back is a typed
//! outcome this module renders. In particular the one distinction the screen turns on — a
//! wrong-class refusal leaves the camera up, a spent part budget does not — is read off
//! [`Scanner::spent`] rather than by inspecting which refusal arrived (standing rule 4).
//!
//! A completed scan is matched on its [`Payload`] variant, and that is the one place this could
//! be misread. **It is a branch on which door was already open, not a judgement about bytes:**
//! the class was fixed when the [`Scanner`] was built, so the variant is the [`Class`] the router
//! asked for and nothing about what arrived. What a transaction *is* — refusable, reviewable, or
//! not a PSBT at all — is [`crate::review`]'s question, and it asks core.
//!
//! **Two threads' worth of discipline in one thread.** Capture and decode run on the same
//! thread, so a decode that cannot keep up cannot queue behind itself; the preview is published
//! *before* the decode starts, so a slow decoder costs capture probability and never aiming
//! feedback. 03-transport.md §5 names the alternative as the trap: with a queue the user aims
//! at where the code was.

use std::cell::{Cell, RefCell};
use std::rc::Rc;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::mpsc::{self, Receiver, Sender};
use std::sync::{Arc, Mutex};

use aobs_core::ur::{Class, Outcome, Payload, Scanner};
use slint::{ComponentHandle, Image, Rgb8Pixel, SharedPixelBuffer};

use crate::review::{Landed, Review};
use crate::verify::Verify;
use crate::{camera, qr, AppWindow, Screen};

/// The preview's ceiling, in the design canvas's own pixels (04-screens.md §0).
///
/// **Modest size rather than full screen** (§11.1). A full-screen preview would cost a
/// software renderer a 1280×720 blit every frame to show the user something they only need
/// enough of to aim, and it would leave no room for the copy naming what this screen wants.
const PREVIEW_WIDTH: usize = 320;
/// The other half of the ceiling. 4:3 rather than 16:9, because the subsample preserves the
/// camera's own aspect and this box only has to contain it.
const PREVIEW_HEIGHT: usize = 240;

/// What a camera that stopped answering says. **No code** (06-codes.md §4): nothing was
/// refused and nothing was discarded, and filing an unplugged cable under the same heading as
/// an attack is what that section exists to prevent.
const LOST: &str = "The camera stopped answering. Plug it back in — aobs looks for it again \
                    the next time you scan.";

/// One frame, subsampled for the preview, on its way to the event loop.
///
/// Luma only, and it stays luma: **the preview displays exactly what the decoder sees**
/// (§11.1) rather than a prettier version of it, and on a GPU-less software renderer that is
/// also the cheap answer — there is no colour conversion here, only a subsample.
struct Preview {
    pixels: Vec<u8>,
    width: u32,
    height: u32,
}

/// What the capture thread has to say.
enum Signal {
    /// One decoded QR symbol, straight from `rqrr`. Unvalidated, unbounded, hostile.
    Symbol(String),
    /// The device stopped delivering, or there was none to open.
    Lost,
}

/// One scanning screen's state.
pub struct Scan {
    /// Bumped on every entry and on every departure. The capture thread carries the value it
    /// started with and stops the moment they differ, which is the whole of the teardown: a
    /// thread that has already been asked to stop cannot post a frame into the next scan.
    generation: Arc<AtomicUsize>,
    /// The newest preview frame, and only that one. **A slot rather than a channel**, so
    /// 03-transport.md §5's *drop any that arrived while we were busy* is true of the preview
    /// as well as of the decode — a channel here would grow a backlog of stale pictures the
    /// event loop then drew in order.
    preview: Arc<Mutex<Option<Preview>>>,
    /// Symbols, which are the opposite case: every one of them counts against the part budget,
    /// so none may be dropped in favour of a newer one.
    inbox: Receiver<Signal>,
    outbox: Sender<Signal>,
    /// **A fresh decoder on every entry** (03-transport.md §4). Core makes that the only
    /// possibility — a [`Scanner`] has no reset and no `Clone` — so this is where the new one
    /// is built, and dropping it is what makes leaving the screen final.
    scanner: RefCell<Option<Scanner>>,
    /// Which of §11.1's three configurations is up. Remembered rather than re-derived, because
    /// a stream that spent its one life on bytes that were not a PSBT gets a fresh decoder for
    /// **the same class** — and asking the old decoder what it was built for would be asking
    /// the thing being replaced.
    class: Cell<Class>,
    /// Where a completed transaction goes (04-screens.md §11.2). Held rather than routed: a
    /// payload is a value, and no value crosses the router (standing rule 4).
    review: Rc<Review>,
    /// And where a completed address goes (§12), held for the same reason: a scanned address is
    /// a value too, so it never crosses the router either.
    verify: Rc<Verify>,
    /// Held by a capture thread for the whole of its run, so **two of them can never hold the
    /// device at once.**
    ///
    /// [`Scan::leave`] cannot join the outgoing thread — it runs on the event loop and that
    /// thread is blocked in `VIDIOC_DQBUF` — so an Escape immediately followed by another entry
    /// would otherwise have the new thread call `STREAMON` while the old one still owns the
    /// node, and report the `EBUSY` as *the camera stopped answering*. Waiting instead costs at
    /// most the one frame the outgoing thread is waiting for.
    ///
    /// **Named cost:** a driver that never delivers another frame never releases this, so the
    /// next scan waits rather than reporting a loss. That is the better silence of the two — the
    /// screen says it is waiting, which is true, instead of saying the camera is gone, which is
    /// a guess — and it is the same wedged-driver case `camera::luma_frame` already accepts.
    device: Arc<Mutex<()>>,
}

/// Build the state and wire the one callback the capture thread rings.
///
/// `scan-tick` carries nothing at all: the frame and the symbols are already in the slot and
/// the channel, and the callback exists only because a `Send` closure cannot hold an `Rc`
/// (the same shape as `create`'s `gathered`).
pub fn wire(ui: &AppWindow, review: Rc<Review>, verify: Rc<Verify>) -> Rc<Scan> {
    let (outbox, inbox) = mpsc::channel();
    let scan = Rc::new(Scan {
        generation: Arc::new(AtomicUsize::new(0)),
        preview: Arc::new(Mutex::new(None)),
        inbox,
        outbox,
        scanner: RefCell::new(None),
        class: Cell::new(Class::Psbt),
        review,
        verify,
        device: Arc::new(Mutex::new(())),
    });

    let handle = ui.as_weak();
    let owner = scan.clone();
    ui.on_scan_tick(move || {
        if let Some(ui) = handle.upgrade() {
            owner.tick(&ui);
        }
    });

    scan
}

impl Scan {
    /// Show the scanning screen for one class and put the camera up behind it.
    pub fn begin(&self, ui: &AppWindow, class: Class) {
        // Anything left in the channel belongs to a scan that is over. Draining it here rather
        // than trusting it to be empty is the channel's half of §4's fresh decoder: a symbol
        // from an abandoned scan must not count against this one's budget.
        while self.inbox.try_recv().is_ok() {}
        let _ = self.preview.lock().map(|mut slot| slot.take());
        self.scanner.replace(Some(Scanner::new(class)));
        self.class.set(class);

        ui.set_scan_heading(format!("Scan {}", class.wanted()).into());
        ui.set_scan_multi_part(class.multi_part());
        ui.set_scan_progress(String::new().into());
        ui.set_scan_note(String::new().into());
        ui.set_scan_code(String::new().into());
        ui.set_scan_stopped(false);
        ui.set_scan_preview(Image::default());
        ui.set_screen(Screen::Scan);

        let generation = self.generation.fetch_add(1, Ordering::SeqCst) + 1;
        let current = self.generation.clone();
        let slot = self.preview.clone();
        let outbox = self.outbox.clone();
        let device = self.device.clone();
        let handle = ui.as_weak();
        std::thread::spawn(move || {
            let mine = || current.load(Ordering::SeqCst) == generation;
            // Whatever thread was here before us gets to finish first. A poisoned lock means one
            // panicked, and this scan is over before it began — the screen stays as `begin` left
            // it and Escape is still live, which is what it would be on a lost camera too.
            let Ok(_held) = device.lock() else {
                return;
            };
            if !mine() {
                return;
            }
            let ended = camera::stream(|frame| {
                if !mine() {
                    return false;
                }
                // The preview first, and its own wake-up. A decode that takes 200 ms on floor
                // hardware then costs capture probability — which is the variable the transport
                // maths already models — instead of costing the user their aim.
                if let Ok(mut slot) = slot.lock() {
                    *slot = Some(subsample(frame.luma, frame.width, frame.height));
                }
                let _ = handle.upgrade_in_event_loop(|ui| ui.invoke_scan_tick());

                let symbols = qr::symbols(frame.luma, frame.width, frame.height);
                if symbols.is_empty() {
                    return true;
                }
                for symbol in symbols {
                    if outbox.send(Signal::Symbol(symbol)).is_err() {
                        return false;
                    }
                }
                let _ = handle.upgrade_in_event_loop(|ui| ui.invoke_scan_tick());
                true
            });
            // A camera that went away while somebody was still watching. If this scan has
            // already been left, the loss is nobody's news.
            if matches!(ended, camera::Ended::Lost) && mine() {
                let _ = outbox.send(Signal::Lost);
                let _ = handle.upgrade_in_event_loop(|ui| ui.invoke_scan_tick());
            }
        });
    }

    /// Leave the screen: stop the camera and drop the decoder.
    ///
    /// Called by the router's cancel arm, which is teardown rather than a decision — every way
    /// off this screen except a completed scan is an Escape or the row that fires the same
    /// intent. A no-op when no scan is running, which is every other screen.
    pub fn leave(&self) {
        self.generation.fetch_add(1, Ordering::SeqCst);
        self.scanner.replace(None);
    }

    /// The capture thread has a frame, or symbols, or bad news.
    fn tick(&self, ui: &AppWindow) {
        if let Some(preview) = self.preview.lock().ok().and_then(|mut slot| slot.take()) {
            ui.set_scan_preview(image_of(&preview));
        }
        while let Ok(signal) = self.inbox.try_recv() {
            let finished = match signal {
                Signal::Lost => {
                    self.lost(ui);
                    true
                }
                Signal::Symbol(symbol) => self.received(ui, &symbol),
            };
            // Draining the rest would feed a scanner that is over, or a screen that has already
            // gone. What is left belongs to the next scan's drain, where it is discarded.
            if finished {
                return;
            }
        }
    }

    /// One symbol, into core. `true` once this scan is over.
    fn received(&self, ui: &AppWindow, symbol: &str) -> bool {
        // The borrow ends before any property is set: a `RefCell` still held across a Slint
        // property change is the shape that panics the day something re-enters here.
        let outcome = {
            let mut scanner = self.scanner.borrow_mut();
            let Some(scanner) = scanner.as_mut() else {
                return true;
            };
            scanner.receive(symbol)
        };

        match outcome {
            // §11.1: parts received over the **clamped** `seqLen`, so the worst a hostile
            // stream buys is a wrong denominator on a bounded display.
            //
            // A part of the class this screen asked for also **answers** any wrong-class
            // sentence above it, so the note goes with it. Leaving it would put a refusal of
            // something else beside a live count of the right thing, which is a false statement
            // about what is happening now — and §11.1's *the screen stays live* is what makes
            // that sequence the ordinary one rather than a corner.
            Outcome::Received { parts, of } => {
                ui.set_scan_note(String::new().into());
                ui.set_scan_code(String::new().into());
                ui.set_scan_progress(format!("{parts} of {of}").into());
            }
            // A symbol we could make nothing of says nothing (06-codes.md §4) — and the note
            // stays, because a refusal already on screen is more use than the silence that
            // would replace it. A frame with no symbol in it never reaches here at all.
            Outcome::Discarded(_) => {}
            // A refusal in the standard shape: the reason and the code, both computed in core.
            // Whether the camera stays up is `spent`'s answer below, not this arm's.
            Outcome::Refused(refusal) => {
                ui.set_scan_note(refusal.reason().into());
                ui.set_scan_code(refusal.code().into());
            }
            // **Dismissed immediately, with no confirmation step** (§11.1): whatever follows is
            // itself the confirmation, so a *scanned OK, continue?* would be a dead press
            // between the user and the thing they asked for.
            //
            // The payload goes where its own variant says, and that is the whole of the
            // dispatch: a transaction to `review`, which validates it in core; the address
            // verdict and the restore words to the screens later tickets bring. **This is a
            // branch on a payload class, never on a validation outcome** — the class was fixed
            // when the [`Scanner`] was built, so the arm below is which door was already open
            // and not a judgement about the bytes (standing rule 4).
            Outcome::Complete(payload) => match payload {
                Payload::Transaction(bytes) => match self.review.arrived(ui, bytes) {
                    // Core made a document of it, or refused it by name. Either way a screen is
                    // up and the camera has no further use.
                    Landed::Shown => {
                        self.leave();
                        return true;
                    }
                    // **Failing to decode is not the same as rejecting** (02-core.md §7): the
                    // bytes never became a PSBT, which is overwhelmingly a bad scan, so this is
                    // the same shape as a wrong-class refusal — the sentence goes up, no code
                    // goes with it, and the camera stays live so the user can aim again. The
                    // decoder is replaced because §4 allows a stream exactly one life.
                    Landed::Scanning(note) => {
                        self.scanner.replace(Some(Scanner::new(self.class.get())));
                        ui.set_scan_progress(String::new().into());
                        ui.set_scan_note(note.into());
                        ui.set_scan_code(String::new().into());
                    }
                },
                // §12's verdict, and it is the same shape the transaction arm is: core answers
                // and `verify` shows whichever screen the answer names. The one difference is
                // that a candidate address has no *not a PSBT* case — a string either matches
                // our own material or does not — so the `Scanning` arm here is only the
                // unreachable no-wallet one.
                Payload::Address(candidate) => match self.verify.arrived(ui, &candidate) {
                    Landed::Shown => {
                        self.leave();
                        return true;
                    }
                    Landed::Scanning(note) => {
                        self.scanner.replace(Some(Scanner::new(self.class.get())));
                        ui.set_scan_note(note.into());
                        ui.set_scan_code(String::new().into());
                    }
                },
                // The restore words (§10) are a later ticket, and `Screen::Unbuilt` says so
                // instead of swallowing the press (standing rule 8).
                Payload::Backup(_) => {
                    self.leave();
                    ui.set_screen(Screen::Unbuilt);
                    return true;
                }
            },
        }

        let spent = self.scanner.borrow().as_ref().is_some_and(Scanner::spent);
        if spent {
            // The note is already on screen — the refusal that spent the scan wrote it one arm
            // above — so this only takes the camera down. Rewriting the sentence here would be a
            // second copy of it, in the file that is supposed to hold none.
            self.leave();
            ui.set_scan_stopped(true);
            ui.set_scan_preview(Image::default());
        }
        spent
    }

    /// The camera went away. State it on the screen the user is already looking at.
    fn lost(&self, ui: &AppWindow) {
        self.leave();
        ui.set_scan_note(LOST.into());
        ui.set_scan_code(String::new().into());
        ui.set_scan_stopped(true);
        ui.set_scan_preview(Image::default());
        // 01-boot-layer.md §7's degraded path, restated the moment it becomes true: the two
        // camera rows on 04-screens.md §7's hub grey with their reason stated. **Re-probed
        // rather than assumed**, so a device that is still there — a transient read error, a
        // node we could not open this time — does not grey them on a guess.
        ui.set_camera_present(camera::present());
    }
}

/// The luma plane, subsampled to fit the preview box, and nothing else done to it.
///
/// Nearest neighbour on an integer step, because the honest reasons are the same ones: it is
/// the cheapest thing a software renderer can be handed, and an averaging filter would show the
/// user a *better* picture than the decoder is working from — which is the one thing a preview
/// whose purpose is aiming must not do.
fn subsample(luma: &[u8], width: usize, height: usize) -> Preview {
    let step = ceil_div(width, PREVIEW_WIDTH).max(ceil_div(height, PREVIEW_HEIGHT));
    let out_width = width / step;
    let out_height = height / step;
    let mut pixels = Vec::with_capacity(out_width * out_height);
    for y in 0..out_height {
        for x in 0..out_width {
            pixels.push(luma[y * step * width + x * step]);
        }
    }
    Preview {
        pixels,
        width: out_width as u32,
        height: out_height as u32,
    }
}

/// `ceil(n / d)`, never zero — a frame smaller than the box is shown at its own size rather
/// than scaled up, and a frame between one and two boxes wide still comes down to fit one.
fn ceil_div(n: usize, d: usize) -> usize {
    n.div_ceil(d).max(1)
}

/// One luma byte per pixel, into the three Slint has a pixel type for.
///
/// Slint offers no greyscale buffer, so `y` goes into all three channels. That is not a colour
/// conversion — it is the same number three times, which is what makes the claim *the preview
/// is what the decoder sees* survive the trip to the framebuffer.
fn image_of(preview: &Preview) -> Image {
    let mut buffer = SharedPixelBuffer::<Rgb8Pixel>::new(preview.width, preview.height);
    for (pixel, &y) in buffer.make_mut_slice().iter_mut().zip(&preview.pixels) {
        *pixel = Rgb8Pixel { r: y, g: y, b: y };
    }
    Image::from_rgb8(buffer)
}

#[cfg(test)]
mod tests {
    use super::{ceil_div, image_of, subsample, PREVIEW_HEIGHT, PREVIEW_WIDTH};

    #[test]
    fn a_frame_larger_than_the_box_is_subsampled_to_fit() {
        // 1280×720 is the resolution 03-transport.md §5 asks for, so this is the ordinary case.
        let frame = vec![0u8; 1280 * 720];
        let preview = subsample(&frame, 1280, 720);
        assert!(preview.width as usize <= PREVIEW_WIDTH, "{}", preview.width);
        assert!(
            preview.height as usize <= PREVIEW_HEIGHT,
            "{}",
            preview.height
        );
        assert_eq!(
            preview.pixels.len(),
            preview.width as usize * preview.height as usize
        );
    }

    #[test]
    fn the_subsample_keeps_the_cameras_aspect_ratio() {
        // One step for both axes, so a 4:3 frame stays 4:3 and a 16:9 one stays 16:9. Squeezing
        // it into the box would distort the picture the user is aiming with.
        let frame = vec![0u8; 640 * 480];
        let preview = subsample(&frame, 640, 480);
        assert_eq!((preview.width, preview.height), (320, 240));

        let wide = vec![0u8; 1280 * 720];
        let preview = subsample(&wide, 1280, 720);
        assert_eq!((preview.width, preview.height), (320, 180));
    }

    #[test]
    fn a_frame_smaller_than_the_box_is_shown_at_its_own_size() {
        let frame = vec![0u8; 160 * 120];
        let preview = subsample(&frame, 160, 120);
        assert_eq!((preview.width, preview.height), (160, 120));
        assert_eq!(ceil_div(160, PREVIEW_WIDTH), 1);
    }

    #[test]
    fn the_subsample_takes_pixels_the_frame_actually_has() {
        // 640×480 at step 2 is the top-left corner of each 2×2 block. Asserted against the
        // frame's own indices rather than against a copy of the arithmetic, because a stride
        // slip here is the defect that shears a preview while every dimension still checks out.
        let width = 640;
        let frame: Vec<u8> = (0..width * 480).map(|i| (i % 251) as u8).collect();
        let preview = subsample(&frame, width, 480);
        assert_eq!((preview.width, preview.height), (320, 240));
        assert_eq!(preview.pixels[0], frame[0]);
        assert_eq!(preview.pixels[1], frame[2]);
        assert_eq!(preview.pixels[319], frame[638]);
        assert_eq!(preview.pixels[320], frame[2 * width]);
        // The last preview pixel is row 239, column 319 — so source row 478, column 638.
        assert_eq!(*preview.pixels.last().unwrap(), frame[478 * width + 638]);
    }

    #[test]
    fn a_luma_byte_becomes_the_same_byte_three_times() {
        let frame: Vec<u8> = vec![7, 200, 0, 255];
        let preview = subsample(&frame, 2, 2);
        let image = image_of(&preview);
        assert_eq!(image.size().width, 2);
        assert_eq!(image.size().height, 2);
        // The claim is that nothing is converted; the pixel data is what proves it.
        let rgb = image.to_rgb8().expect("built from an rgb8 buffer");
        for (pixel, &y) in rgb.as_slice().iter().zip(&preview.pixels) {
            assert_eq!((pixel.r, pixel.g, pixel.b), (y, y, y));
        }
    }
}
