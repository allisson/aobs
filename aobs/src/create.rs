//! Creating a wallet: the dice, the wait, and the 24 words (04-screens.md §2, §3).
//!
//! **One screen does both jobs.** The rolls are needed before the mnemonic exists, which is
//! exactly when `getrandom(2)` is still blocking, so the dead time carries the optional
//! feature at the cost of no extra step — and a screen with something to do on it cannot
//! read as a hang. That is why the gathering runs on threads of its own: the event loop
//! stays free to count rolls and seconds while the kernel and the camera take their time.
//!
//! Four absences are load-bearing, each rejected by name in 02-core.md §3, and every one of
//! them would need code in this file to exist: **no minimum roll count, no bit counter, no
//! progress meter, and no running hash of the rolls on screen.** The last is the sharpest —
//! because we mix rather than replace, the rolls are *not* sufficient to reconstruct the
//! wallet, and displaying their hash would hand that property straight back. The roll count
//! is the whole of what this screen reports about them.
//!
//! **Nothing here decides anything about money.** The mix and the phrase are core's
//! (02-core.md §3, §4); this module gathers three byte strings, hands them over, and shows
//! what comes back.

use std::cell::{Cell, RefCell};
use std::rc::Rc;
use std::sync::mpsc::{self, Receiver, Sender};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use aobs_core::bip39::Mnemonic;
use aobs_core::entropy::mix;
use aobs_core::entry::Entry;
use aobs_core::secret::{Csprng32, Dice, Luma};
use slint::{ComponentHandle, ModelRc, Timer, TimerMode, VecModel};
use zeroize::Zeroizing;

use crate::entropy::EntropyUnavailable;
use crate::fail::Failure;
use crate::{camera, entropy, AppWindow, Screen, Word};

/// Words per column. **Twelve, in two column-major columns** — 04-screens.md §3, and the
/// number is the shape of the card being copied onto rather than a layout preference.
const COLUMN: usize = 12;

/// How many rolls the buffer is allocated for up front.
///
/// Free entry with no minimum and **no cap of our own** (04-screens.md §2): this is not a
/// limit, and nothing refuses a 4 097th roll. It is what keeps standing rule 5 honest in
/// practice — a `Vec` that grows past its capacity copies itself and leaves the old contents
/// in memory no `Zeroize` impl can reach — and 4 096 is far past any hand that has ever
/// rolled a die into a keyboard. **The 4 097th roll is not a hole either**: what a realloc
/// abandons is a *freed* allocation, and this appliance boots `init_on_free=1`
/// (01-boot-layer.md §5), which is the kernel poisoning exactly those pages. The rolls are
/// also the one input here that cannot reconstruct the wallet on their own, which is the
/// whole point of mixing rather than replacing (02-core.md §3).
const ROLL_CAPACITY: usize = 4096;

/// The state one wallet creation accumulates, and the two threads that fill it.
pub struct Create {
    /// The rolls, as the ASCII digits the user typed. Wiped when `entropy` exists, which is
    /// where 02-core.md §3's lifetime rule puts it.
    rolls: RefCell<Zeroizing<Vec<u8>>>,
    /// Where the camera thread leaves its frame, if it ever produces one.
    frame: Arc<Mutex<Option<Luma>>>,
    /// Where the entropy thread leaves the syscall's answer. A channel rather than a second
    /// mutex because the value is taken exactly once and the send is what orders it against
    /// the callback that comes after.
    inbox: Receiver<Result<Csprng32, EntropyUnavailable>>,
    outbox: Sender<Result<Csprng32, EntropyUnavailable>>,
    /// The 32 bytes, once they have arrived. **Their presence is what unlocks Continue**,
    /// and nothing else: the screen never auto-advances, because the user may still be
    /// rolling (04-screens.md §2).
    csprng: RefCell<Option<Csprng32>>,
    /// The elapsed-seconds ticker. Indeterminate and in seconds — there is no percentage,
    /// because `getrandom(2)` emits no progress signal and a bar would report a number the
    /// system cannot know, and a fabricated one stalling near the end reads *more* like a
    /// hang than a spinner does.
    ticker: Timer,
    gathering: Cell<bool>,
    failure: Cell<Option<Failure>>,
    /// The phrase, once it exists, for as long as the session does.
    ///
    /// It stays in core's zeroizing type and never becomes anything else here: 04-screens.md
    /// §4's retype compares against it and 02-core.md §4 puts that comparison in core, so what
    /// this module can do with it is hand out an [`Entry`] that already holds it
    /// ([`Self::type_back`]) — and read the words for the screen, which is what §3 is.
    phrase: RefCell<Option<Mnemonic>>,
}

/// Build the state and wire the two callbacks that carry a value rather than an intent.
///
/// `roll` is deliberately not an [`crate::Intent`]: a die face is a byte the user typed, and
/// the router's whole claim is that no arm of it inspects one (standing rule 4). It lands
/// here instead, where it is appended to a buffer and counted.
pub fn wire(ui: &AppWindow) -> Rc<Create> {
    let (outbox, inbox) = mpsc::channel();
    let create = Rc::new(Create {
        rolls: RefCell::new(Zeroizing::new(Vec::new())),
        frame: Arc::new(Mutex::new(None)),
        inbox,
        outbox,
        csprng: RefCell::new(None),
        ticker: Timer::default(),
        gathering: Cell::new(false),
        failure: Cell::new(None),
        phrase: RefCell::new(None),
    });

    let handle = ui.as_weak();
    let owner = create.clone();
    ui.on_roll(move |face| {
        if let Some(ui) = handle.upgrade() {
            owner.roll(&ui, face);
        }
    });

    let handle = ui.as_weak();
    let owner = create.clone();
    ui.on_gathered(move || {
        if let Some(ui) = handle.upgrade() {
            owner.arrived(&ui);
        }
    });

    create
}

impl Create {
    /// Show the dice screen and start gathering behind it.
    pub fn begin(&self, ui: &AppWindow) {
        self.rolls
            .replace(Zeroizing::new(Vec::with_capacity(ROLL_CAPACITY)));
        ui.set_rolls(0);
        ui.set_screen(Screen::Dice);

        // Coming back to this screen does not ask the kernel again. The bytes are as good as
        // they were a minute ago, and re-blocking would be a wait invented for the sake of
        // showing one.
        if self.csprng.borrow().is_some() {
            ui.set_entropy_ready(true);
            return;
        }
        ui.set_entropy_ready(false);
        if self.gathering.replace(true) {
            return;
        }

        ui.set_wait_seconds(0);
        let handle = ui.as_weak();
        let started = Instant::now();
        self.ticker
            .start(TimerMode::Repeated, Duration::from_secs(1), move || {
                if let Some(ui) = handle.upgrade() {
                    // `as i32` from a wait counted in seconds: the cast is unreachable at
                    // any elapsed time a person is present for, and saturating it would be
                    // an arm no test could take.
                    ui.set_wait_seconds(started.elapsed().as_secs() as i32);
                }
            });

        // Two threads, not one, and that is the whole timeout story. The camera can block
        // for as long as a broken driver likes without holding up the syscall that unlocks
        // Continue; whatever it has produced by the time the user presses on goes into the
        // mix, and whatever it has not is an absent supplement, which 02-core.md §3 already
        // treats as the camera-less case.
        let frame = self.frame.clone();
        std::thread::spawn(move || {
            let luma = camera::luma_frame();
            if let Ok(mut slot) = frame.lock() {
                *slot = luma;
            }
        });

        let outbox = self.outbox.clone();
        let handle = ui.as_weak();
        std::thread::spawn(move || {
            let _ = outbox.send(entropy::csprng_32());
            let _ = handle.upgrade_in_event_loop(|ui| ui.invoke_gathered());
        });
    }

    /// One D6 face, appended.
    ///
    /// **No undo, and none is missing.** A mistyped roll cannot make the entropy worse — the
    /// supplement is XORed into the kernel's bytes, so any string of digits can only add
    /// (02-core.md §3). A key that removed one would be a control whose only honest label is
    /// *this changes nothing*.
    fn roll(&self, ui: &AppWindow, face: i32) {
        if !(1..=6).contains(&face) {
            return;
        }
        let count = {
            let mut rolls = self.rolls.borrow_mut();
            rolls.push(b'0' + face as u8);
            rolls.len() as i32
        };
        // The borrow ends before the property is set: a `RefCell` still held across a Slint
        // property change is the shape that panics the day something re-enters here.
        ui.set_rolls(count);
    }

    /// The entropy thread has something for us.
    fn arrived(&self, ui: &AppWindow) {
        self.ticker.stop();
        match self.inbox.try_recv() {
            Ok(Ok(csprng)) => {
                self.csprng.replace(Some(csprng));
                ui.set_entropy_ready(true);
            }
            // A request that is not supposed to be refusable was refused (06-codes.md §5,
            // `AOBS-E01`). The session ends on the console rather than on a screen offering
            // to carry on: this machine cannot be trusted to generate a wallet.
            Ok(Err(_)) => {
                self.failure.set(Some(Failure::EntropyUnavailable));
                let _ = slint::quit_event_loop();
            }
            // The send happens before the invoke that brought us here, so an empty channel
            // is not reachable through it. Ignored rather than asserted, because the cost of
            // being wrong is one screen that stays locked and the cost of a panic is the
            // session.
            Err(_) => {}
        }
    }

    /// Mix, derive the phrase, and show it. **Reachable only once Continue is unlocked.**
    pub fn words(&self, ui: &AppWindow) {
        let Some(csprng) = self.csprng.borrow_mut().take() else {
            return;
        };
        // These 32 bytes are spent. A second wallet in the same session — the user escaped
        // back to the start menu and chose *create* again — asks the kernel again rather
        // than reusing them, which is what re-arming this flag buys.
        self.gathering.set(false);

        // 02-core.md §3's lifetime rule, as a sequence of moves rather than as a comment:
        // the luma plane, the dice buffer and the 32 bytes are all taken by value, and
        // `mix` drops — and so zeroizes — every one of them before it returns.
        let luma = self.frame.lock().ok().and_then(|mut slot| slot.take());
        let rolls = self.rolls.replace(Zeroizing::new(Vec::new()));
        let dice = (!rolls.is_empty()).then(|| Dice::new(&rolls));
        drop(rolls);

        let entropy = mix(csprng, luma, dice);
        // 32 bytes is 24 words. `from_entropy` refuses only a length BIP-39 has no checksum
        // rule for, and `mix` returns exactly `Csprng32::LEN` — so this unwinds into
        // `AOBS-E04` rather than branching, which is what E04 is for.
        let mnemonic = Mnemonic::from_entropy(&entropy).expect("mix returns 32 bytes");

        // The phrase leaves the zeroizing types here, and it has to: a screen showing 24
        // words is 24 words in a frame buffer. What crosses is `&'static str` out of the
        // public wordlist — the secret is the *sequence*, and the sequence now lives in the
        // two models for the rest of the session, because 04-screens.md §4's retype returns
        // to this screen with a position marked. `Entropy` is dropped, and so zeroized, as
        // this function returns.
        let (left, right) = columns(&mnemonic);
        ui.set_left_column(ModelRc::new(VecModel::from(left)));
        ui.set_right_column(ModelRc::new(VecModel::from(right)));
        // A first arrival at the phrase marks nothing: the mark is §4's rejection, and this
        // screen is reached from both sides.
        ui.set_marked(0);
        ui.set_screen(Screen::Words);

        // The `Mnemonic` itself stays, in the type that zeroizes it, because the retype has
        // to compare against it and the load path has to derive from it.
        self.phrase.replace(Some(mnemonic));
    }

    /// The retype's entry state: core's byte compare, already holding the answer
    /// (04-screens.md §4).
    ///
    /// `None` before a phrase exists, which the one caller cannot reach — the intent that
    /// leads here is fired from the phrase screen, and that screen is what [`Self::words`]
    /// shows after storing one.
    pub fn type_back(&self) -> Option<Entry> {
        self.phrase.borrow().as_ref().map(Mnemonic::type_back)
    }

    /// The failure that ended the session, if one did.
    pub fn failure(&self) -> Option<Failure> {
        self.failure.get()
    }
}

/// The phrase as two columns: **1–12 left, 13–24 right**.
///
/// **Column-major fill is the whole point and is easy to get wrong** (04-screens.md §3). A
/// row-flow grid renders 1,2 / 3,4 and inverts the argument, which is the paper: a column of
/// twelve is the shape of the card or steel plate being copied onto, so screen and
/// destination share a geometry and the copy becomes positional rather than sequential. The
/// test below is the one that fails if a later edit hands the model to a grid instead.
fn columns(mnemonic: &Mnemonic) -> (Vec<Word>, Vec<Word>) {
    let word = |position: usize| Word {
        position: position as i32 + 1,
        text: mnemonic.word(position).unwrap_or_default().into(),
    };
    (
        (0..COLUMN).map(word).collect(),
        (COLUMN..2 * COLUMN).map(word).collect(),
    )
}

#[cfg(test)]
mod tests {
    use super::{columns, COLUMN};
    use aobs_core::bip39::Mnemonic;
    use aobs_core::secret::Entropy;

    fn phrase() -> Mnemonic {
        // BIP-39's own all-zero vector: `abandon … abandon art`.
        Mnemonic::from_entropy(&Entropy::new(&[0u8; 32]).unwrap()).unwrap()
    }

    #[test]
    fn twelve_and_twelve() {
        let (left, right) = columns(&phrase());
        assert_eq!(left.len(), COLUMN);
        assert_eq!(right.len(), COLUMN);
    }

    #[test]
    fn the_left_column_is_one_to_twelve_and_the_right_thirteen_to_twenty_four() {
        let (left, right) = columns(&phrase());
        assert_eq!(left[0].position, 1);
        assert_eq!(left[COLUMN - 1].position, 12);
        assert_eq!(right[0].position, 13);
        assert_eq!(right[COLUMN - 1].position, 24);
    }

    #[test]
    fn the_fill_is_column_major_rather_than_row_flow() {
        // The phrase is `abandon` twenty-three times and `art` last, so a row-flow grid —
        // 1,2 / 3,4 — would put word 24 at the foot of the *left* column. The one word that
        // is not `abandon` is what makes this observable at all.
        let (left, right) = columns(&phrase());
        assert_eq!(left[COLUMN - 1].text, "abandon");
        assert_eq!(right[COLUMN - 1].text, "art");
    }
}
