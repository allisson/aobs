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
//! §10) in later slices. What changes between them is the wordlist, the slot count and
//! whether an answer is known — all three of them parameters of core's constructor — so those
//! screens bring their own drawing and their own copy, and nothing else.

use std::cell::RefCell;
use std::rc::Rc;

use aobs_core::entry::{Action, Entry, Outcome};
use slint::{ComponentHandle, ModelRc, VecModel};

use crate::create::Create;
use crate::{AppWindow, Screen, Slot};

/// Slots per column. Twelve, in two column-major columns, the same geometry the phrase is
/// drawn in (04-screens.md §3) — so the paper, the phrase screen and this screen all agree
/// on where word 13 is, and the copy stays positional rather than sequential.
const COLUMN: usize = 12;

/// One retype, or none yet.
pub struct Confirm {
    /// **Built once per phrase and kept across a rejection**, which is what *destroys
    /// nothing* means as state rather than as a promise: coming back from the repair returns
    /// to the words already typed, at the position that was refused.
    entry: RefCell<Option<Entry>>,
}

/// Wire the three callbacks that carry a keystroke rather than an intent.
///
/// They bypass the router for the reason a die face does (standing rule 4): a letter of the
/// mnemonic is a value the user typed, and the router's claim is that no arm of it inspects
/// one. What the letter *does* is not decided here either — it is handed to core.
pub fn wire(ui: &AppWindow) -> Rc<Confirm> {
    let confirm = Rc::new(Confirm {
        entry: RefCell::new(None),
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
    pub fn begin(&self, ui: &AppWindow, create: &Create) {
        if self.entry.borrow().is_none() {
            self.entry.replace(create.type_back());
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
            // §5's passphrase-and-network screen is a later slice, so the frame says so
            // rather than swallowing the press (standing rule 8).
            Outcome::Complete => ui.set_screen(Screen::Unbuilt),
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

/// The retype as two columns: **1–12 left, 13–24 right**, column-major, for the reason
/// 04-screens.md §3 gives — a column of twelve is the shape of the card being copied *from*
/// here, so the two screens and the paper share one geometry.
///
/// **Only what the user typed crosses.** A committed word is echoed, because nothing in this
/// product is masked and an off-by-one has to be visible as a *shift* rather than as a mystery
/// rejection at word 20. The slot being typed into shows the buffer instead, so a word in
/// progress is never confused with one that landed.
fn columns(entry: &Entry) -> (Vec<Slot>, Vec<Slot>) {
    let slot = |position: usize| {
        let current = position == entry.cursor();
        let typed = entry.buffer();
        Slot {
            position: i32::try_from(position).unwrap_or_default() + 1,
            text: if current && !typed.is_empty() {
                typed.into()
            } else {
                entry.word(position).unwrap_or_default().into()
            },
            ghost: if current { entry.ghost() } else { "" }.into(),
            current,
        }
    };
    (
        (0..COLUMN).map(slot).collect(),
        (COLUMN..2 * COLUMN).map(slot).collect(),
    )
}

/// What the live line says about the action that just ran, or `""` for one that simply
/// worked.
///
/// The two things it can report are both 02-core.md §4's: **the key that was ignored**, and
/// how many words a prefix still matches. Neither is a judgement — the outcome came from
/// core, and this turns it into a sentence.
fn refusal(entry: &Entry, action: Action, outcome: Outcome) -> String {
    match (action, outcome) {
        (Action::Char(key), Outcome::Ignored) => {
            format!(
                "“{key}” did nothing: no word in the list begins “{}{key}”.",
                entry.buffer()
            )
        }
        (Action::Commit, Outcome::Ignored) if entry.matches() > 1 => {
            format!(
                "“{}” still matches {} words. Keep typing.",
                entry.buffer(),
                entry.matches()
            )
        }
        _ => String::new(),
    }
}

/// The standing line: how to type a word, and what the screen is not showing.
///
/// It puts a fragment of the phrase — the prefix, and the word it resolves to — into a
/// `String`, and that is the same trade `create.rs` names for the phrase itself: those bytes
/// are already on screen in the slot above, so this is one copy of something a frame buffer
/// is holding anyway. Nothing here is material the user has not just typed.
fn hint(entry: &Entry) -> String {
    let typed = entry.buffer();
    if typed.is_empty() {
        "Four letters and the space bar are enough for any word. Backspace steps back.".to_owned()
    } else if entry.matches() == 1 {
        format!("“{typed}{}” — press space to place it.", entry.ghost())
    } else {
        format!("“{typed}” matches {} words.", entry.matches())
    }
}

#[cfg(test)]
mod tests {
    use super::{columns, hint, refusal, COLUMN};
    use aobs_core::bip39::Mnemonic;
    use aobs_core::entry::{Action, Entry, Outcome};
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

    #[test]
    fn the_grid_is_twelve_and_twelve_column_major() {
        let (left, right) = columns(&retype());
        assert_eq!(left.len(), COLUMN);
        assert_eq!(right.len(), COLUMN);
        assert_eq!(left[0].position, 1);
        assert_eq!(left[COLUMN - 1].position, 12);
        assert_eq!(right[0].position, 13);
        assert_eq!(right[COLUMN - 1].position, 24);
    }

    #[test]
    fn a_fresh_retype_shows_nothing_at_all() {
        // 04-screens.md §4: the mnemonic is never re-shown during the retype. The phrase is in
        // the entry — the compare needs it — and no slot can draw it.
        let (left, right) = columns(&retype());
        for slot in left.iter().chain(right.iter()) {
            assert_eq!(slot.text, "");
            assert_eq!(slot.ghost, "");
        }
        assert!(left[0].current);
    }

    #[test]
    fn committed_words_are_echoed_and_the_slot_being_typed_shows_the_buffer() {
        let mut entry = retype();
        letters(&mut entry, "aban");
        entry.apply(Action::Commit);
        letters(&mut entry, "aba");

        let (left, _) = columns(&entry);
        assert_eq!(left[0].text, "abandon");
        assert!(!left[0].current);
        // The word in progress, with the rest of the single match ghosted after it.
        assert_eq!(left[1].text, "aba");
        assert_eq!(left[1].ghost, "ndon");
        assert!(left[1].current);
        // And nothing anywhere else.
        assert_eq!(left[2].text, "");
        assert_eq!(left[2].ghost, "");
    }

    #[test]
    fn the_ignored_key_is_named_along_with_the_prefix_that_refused_it() {
        let mut entry = retype();
        letters(&mut entry, "aba");
        let outcome = entry.apply(Action::Char('x'));
        assert_eq!(outcome, Outcome::Ignored);
        assert_eq!(
            refusal(&entry, Action::Char('x'), outcome),
            "“x” did nothing: no word in the list begins “abax”."
        );
    }

    #[test]
    fn a_space_on_an_ambiguous_prefix_says_how_many_words_are_left() {
        let mut entry = retype();
        letters(&mut entry, "ab");
        let outcome = entry.apply(Action::Commit);
        assert_eq!(outcome, Outcome::Ignored);
        assert!(refusal(&entry, Action::Commit, outcome).starts_with("“ab” still matches "));
    }

    #[test]
    fn an_action_that_worked_says_nothing_and_leaves_the_hint_in_place() {
        let mut entry = retype();
        letters(&mut entry, "aban");
        let outcome = entry.apply(Action::Commit);
        assert_eq!(outcome, Outcome::Accepted);
        assert_eq!(refusal(&entry, Action::Commit, outcome), "");
        assert!(hint(&entry).starts_with("Four letters"));
    }

    #[test]
    fn the_hint_becomes_the_word_the_prefix_resolves_to() {
        let mut entry = retype();
        letters(&mut entry, "aban");
        assert_eq!(hint(&entry), "“abandon” — press space to place it.");
    }
}
