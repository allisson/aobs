//! The creation retype: 24 words typed from paper, with the phrase off screen
//! (04-screens.md §4).
//!
//! **The reframe that decides everything in this file: this is not a gate proving the phrase
//! was written down, it is an instrument for making the paper correct — so a failure is the
//! feature working.** Which is why a rejection here goes *back to the phrase* with the
//! position marked instead of forward to an error screen, why nothing is cleared on the way,
//! and why there is no `restart` control anywhere on the screen: restart voids everything
//! already written down and re-asks the same transcription of someone who has just proved
//! they can slip.
//!
//! **Nothing in this file compares a word.** The state, the prefix matching and the per-word
//! byte compare against the generated phrase are all `aobs_core::entry`'s, which is where
//! standing rule 4 puts them — the shell owns the keyboard and the drawing, and its whole
//! contribution to the decision is mapping the space bar to a commit. The phrase itself never
//! reaches this module: what crosses is an [`Entry`] that already holds the answer and hands
//! back only the words the user typed.
//!
//! The same [`Entry`] drives seed import (§6) and both halves of the encrypted backup (§9,
//! §10). What changes between them is the wordlist, the slot count and whether an answer is
//! known — all three of them parameters of core's constructor — so what each screen brings is
//! its own **copy**: the heading, the standing hint and the Done control's note. The two
//! adapters that restate what core said are shared and live in [`crate::typing`], because two
//! copies of *the key that did not land* are two places that can disagree about it.

use std::cell::RefCell;
use std::rc::Rc;

use aobs_core::entry::{Action, Entry, Outcome};
use slint::{ComponentHandle, ModelRc, VecModel};

use crate::phrase::Phrase;
use crate::typing::{columns, refusal};
use crate::{AppWindow, Screen};

/// One retype, or none yet.
pub struct Confirm {
    /// **Built once per phrase and kept across a rejection**, which is what *destroys
    /// nothing* means as state rather than as a promise: coming back from the repair returns
    /// to the words already typed, at the position that was refused.
    entry: RefCell<Option<Entry>>,
    /// The phrase this is typed against, which never reaches this module: what crosses is an
    /// [`Entry`] that already holds the answer (04-screens.md §5's slot, `phrase.rs`).
    phrase: Rc<Phrase>,
}

/// Wire the three callbacks that carry a keystroke rather than an intent.
///
/// They bypass the router for the reason a die face does (standing rule 4): a letter of the
/// mnemonic is a value the user typed, and the router's claim is that no arm of it inspects
/// one. What the letter *does* is not decided here either — it is handed to core.
pub fn wire(ui: &AppWindow, phrase: Rc<Phrase>) -> Rc<Confirm> {
    let confirm = Rc::new(Confirm {
        entry: RefCell::new(None),
        phrase,
    });

    let handle = ui.as_weak();
    let owner = confirm.clone();
    ui.on_typed(move |text| {
        if let Some(ui) = handle.upgrade() {
            owner.typed(&ui, &text);
        }
    });

    let handle = ui.as_weak();
    let owner = confirm.clone();
    ui.on_entry_back(move || {
        if let Some(ui) = handle.upgrade() {
            owner.act(&ui, Action::Back);
        }
    });

    let handle = ui.as_weak();
    let owner = confirm.clone();
    ui.on_entry_step(move |delta| {
        if let Some(ui) = handle.upgrade() {
            owner.step(&ui, delta);
        }
    });

    confirm
}

impl Confirm {
    /// Show the retype — the first time from the phrase, and afterwards exactly as it was
    /// left.
    pub fn begin(&self, ui: &AppWindow) {
        if self.entry.borrow().is_none() {
            self.entry.replace(self.phrase.type_back());
        }
        ui.set_screen(Screen::Retype);
        self.draw(ui, "");
    }

    /// Forget a retype in progress, because the phrase it was typed against is gone.
    ///
    /// Called when *create* is chosen from the start menu, which is the one path that can
    /// generate a second phrase in one session (ADR-0010's `OnceLock` arrives with the load
    /// path). A kept entry would compare the new words against the old answer and refuse
    /// every one of them.
    pub fn forget(&self) {
        self.entry.replace(None);
    }

    /// `⏎` is Done (02-core.md §4). Reachable only while core says the phrase is whole.
    pub fn done(&self, ui: &AppWindow) {
        self.act(ui, Action::Finish);
    }

    /// One printable keystroke.
    fn typed(&self, ui: &AppWindow, text: &str) {
        let mut letters = text.chars();
        let (Some(key), None) = (letters.next(), letters.next()) else {
            return;
        };
        // Slint delivers named keys as characters too, and the ones the frame does not bind
        // arrive here as private-use code points. A key with no printable form has no name to
        // report either, so it is dropped rather than announced — the alternative is a screen
        // naming a key the user cannot see (standing rule 8).
        if key != ' ' && !key.is_ascii_graphic() {
            return;
        }
        // **Space commits.** The keystroke-to-action mapping is the shell's whole share of
        // 02-core.md §4: what a letter does with the wordlist is core's.
        self.act(
            ui,
            if key == ' ' {
                Action::Commit
            } else {
                Action::Char(key)
            },
        );
    }

    /// An arrow key, as a destination slot. Off either end there is no destination, so
    /// nothing happens — and in particular the buffer is not settled by a move that is not
    /// going to happen.
    fn step(&self, ui: &AppWindow, delta: i32) {
        let Some(target) = self
            .entry
            .borrow()
            .as_ref()
            .map(Entry::cursor)
            .and_then(|cursor| cursor.checked_add_signed(delta as isize))
        else {
            return;
        };
        self.act(ui, Action::Goto(target));
    }

    /// Hand one action to core, draw what came back, and go where the outcome says.
    ///
    /// The `match` at the end is the only branch in this module and it is a marshal, not a
    /// decision: core has already decided, and each arm is one destination — the same shape
    /// the router holds itself to. Nothing here re-checks a word or reads the answer.
    fn act(&self, ui: &AppWindow, action: Action) {
        let (outcome, note) = {
            let mut held = self.entry.borrow_mut();
            let Some(entry) = held.as_mut() else {
                return;
            };
            let outcome = entry.apply(action);
            (outcome, refusal(entry, action, outcome))
        };
        self.draw(ui, &note);

        match outcome {
            // §4: back to the phrase with that position marked. The mark is 1-based because
            // that is how the phrase is numbered, on screen and on the paper.
            Outcome::Wrong(position) => {
                ui.set_marked(i32::try_from(position).unwrap_or_default() + 1);
                ui.set_screen(Screen::Words);
            }
            // §5's one load screen, which every path reaches: the passphrase and the network
            // enter at derivation, so a phrase that has just been proved correct is a phrase
            // with nothing left to do but be loaded.
            Outcome::Complete => ui.set_screen(Screen::Load),
            Outcome::Accepted | Outcome::Ignored => {}
        }
    }

    /// Push core's state onto the screen. An empty `note` means *nothing was refused*, and
    /// the standing hint takes the line instead.
    fn draw(&self, ui: &AppWindow, note: &str) {
        let (left, right, settled, done, note) = {
            let held = self.entry.borrow();
            let Some(entry) = held.as_ref() else {
                return;
            };
            let (left, right) = columns(entry);
            let settled = i32::try_from(entry.settled()).unwrap_or_default();
            let line = if note.is_empty() {
                hint(entry)
            } else {
                note.to_owned()
            };
            (left, right, settled, entry.can_finish(), line)
        };

        // The borrows end before a single property is set: a `RefCell` still held across a
        // Slint property change is the shape that panics the day something re-enters here.
        ui.set_retype_left(ModelRc::new(VecModel::from(left)));
        ui.set_retype_right(ModelRc::new(VecModel::from(right)));
        ui.set_retype_settled(settled);
        ui.set_retype_done(done);
        ui.set_retype_note(note.into());
    }
}

/// The standing line: **the keymap**, how to type a word, and what the screen is not showing.
///
/// The keymap is named before the user starts, which 04-screens.md §5.1 requires of every typing
/// screen and §6 requires of the word-entry ones by name. Here it degrades more gently than on
/// the passphrase field: the wordlist is `a`–`z`, the pinned `us` keymap puts those on the same
/// physical keys on every board, and only the legends can mislead — after which an off-list
/// keystroke names itself on this same line. It takes the standing line rather than a line of its
/// own because that line's height is a term in §3's measurement, and it is replaced the moment
/// the user types, which is exactly *before the user starts*.
///
/// It puts a fragment of the phrase — the prefix, and the word it resolves to — into a
/// `String`, and that is the same trade `create.rs` names for the phrase itself: those bytes
/// are already on screen in the slot above, so this is one copy of something a frame buffer
/// is holding anyway. Nothing here is material the user has not just typed.
fn hint(entry: &Entry) -> String {
    let typed = entry.buffer();
    if typed.is_empty() {
        "US keyboard layout. Four letters and the space bar are enough for any word. \
         Backspace steps back."
            .to_owned()
    } else if entry.matches() == 1 {
        format!("“{typed}{}” — press space to place it.", entry.ghost())
    } else {
        format!("“{typed}” matches {} words.", entry.matches())
    }
}

#[cfg(test)]
mod tests {
    use super::hint;
    use aobs_core::bip39::Mnemonic;
    use aobs_core::entry::{Action, Entry};
    use aobs_core::secret::Entropy;

    /// The retype of BIP-39's own all-zero vector: `abandon` twenty-three times, then `art`.
    fn retype() -> Entry {
        Mnemonic::from_entropy(&Entropy::new(&[0u8; 32]).expect("32 bytes"))
            .expect("24 words")
            .type_back()
    }

    fn letters(entry: &mut Entry, word: &str) {
        for letter in word.chars() {
            entry.apply(Action::Char(letter));
        }
    }

    /// 04-screens.md §5.1 and §6: **the screen names the keymap before the user starts.** The
    /// standing line is what "before" means here — it is on screen at the first paint and is
    /// replaced by the live line as soon as a key lands.
    #[test]
    fn the_standing_line_names_the_keymap_and_stops_doing_so_once_typing_begins() {
        let mut entry = retype();
        assert!(hint(&entry).contains("US keyboard layout"));
        letters(&mut entry, "aban");
        assert!(!hint(&entry).contains("US keyboard layout"));
    }

    #[test]
    fn the_hint_becomes_the_word_the_prefix_resolves_to() {
        let mut entry = retype();
        letters(&mut entry, "aban");
        assert_eq!(hint(&entry), "“abandon” — press space to place it.");
    }
}
