//! Seed import: a phrase typed in word by word, with nothing to compare it against
//! (04-screens.md §6).
//!
//! **The reframe that decides everything on this screen is what it does *not* know.** The
//! retype next door holds the answer, so a wrong word is refused at the keystroke that placed
//! it and named by position. Here there is no answer, and the only verdict that exists is
//! BIP-39's checksum over the phrase as a whole — evaluated once, at the end, and unable to
//! say which word is wrong. A device that pointed at a word would be lying.
//!
//! What makes that verdict tolerable is the one thing core's reducer guarantees: **an off-list
//! word is unrepresentable** (02-core.md §4, behaviour 3). `bitc` has nowhere to go, so the
//! `c` does not land and the screen names it. So a failed checksum can only ever mean real
//! words in the wrong place — a smaller search than *somewhere in here is a word that is not a
//! word*, and one the user can walk with their paper beside them.
//!
//! Which is also why **a failed checksum keeps the words**. Wiping destroys no secret — the
//! phrase is on the user's paper — it destroys the diff between paper and screen, which is the
//! user's only instrument for finding their own mistake. Here that is not a rule this module
//! remembers: [`Mnemonic::from_entry`] takes the entry by reference and there is nothing in
//! this file that could clear a slot.
//!
//! **The length is inferred, not declared** (behaviour 6). Twenty-four slots are drawn for a
//! twelve-word phrase, which is what makes the accepted lengths self-evident at a glance, and
//! Done unlocks at one of the five — core's `can_finish`, over core's own `LENGTHS`, so this
//! file counts nothing.
//!
//! **Discard is available at every moment, and discard is a restart** (§6, ADR-0010). It is
//! the frame's appended *restart / shut down* row, on this screen as on every other, so it is
//! structural rather than a control this file remembers to draw — and there is deliberately
//! nothing else here that clears the words.
//!
//! **A non-English mnemonic fails as a wall rather than a message**: the pinned `us` keymap
//! cannot produce `é` or `ř` at all, and the wordlist would refuse them anyway. That is why
//! the standing line names English *and* the keymap before the user starts.

use std::cell::RefCell;
use std::rc::Rc;

use aobs_core::bip39::{self, Mnemonic};
use aobs_core::entry::{Action, Entry, Outcome};
use slint::{ComponentHandle, ModelRc, VecModel};

use crate::phrase::Phrase;
use crate::typing::{columns, refusal};
use crate::{AppWindow, Screen};

/// One import in progress, or none yet.
pub struct Import {
    /// **Built once and kept.** Escape leads to the start menu, and coming back to import
    /// returns to the words already typed: twenty words are twenty words, and an accidental
    /// keystroke is not a reason to ask for them again. The one control that does clear them
    /// is the restart the frame offers on every screen, which ends the process.
    entry: RefCell<Option<Entry>>,
    /// Where a phrase that checks out goes: 04-screens.md §5's one slot, which the load screen
    /// reads without knowing which path filled it.
    phrase: Rc<Phrase>,
}

/// Wire the three callbacks that carry a keystroke rather than an intent.
///
/// They bypass the router for the reason the retype's do (standing rule 4): a letter of a
/// mnemonic is a value the user typed, and the router's claim is that no arm of it inspects
/// one.
pub fn wire(ui: &AppWindow, phrase: Rc<Phrase>) -> Rc<Import> {
    let import = Rc::new(Import {
        entry: RefCell::new(None),
        phrase,
    });

    let handle = ui.as_weak();
    let owner = import.clone();
    ui.on_import_typed(move |text| {
        if let Some(ui) = handle.upgrade() {
            owner.typed(&ui, &text);
        }
    });

    let handle = ui.as_weak();
    let owner = import.clone();
    ui.on_import_back(move || {
        if let Some(ui) = handle.upgrade() {
            owner.act(&ui, Action::Back);
        }
    });

    let handle = ui.as_weak();
    let owner = import.clone();
    ui.on_import_step(move |delta| {
        if let Some(ui) = handle.upgrade() {
            owner.step(&ui, delta);
        }
    });

    import
}

impl Import {
    /// Show the screen — the first time empty, and afterwards exactly as it was left.
    pub fn begin(&self, ui: &AppWindow) {
        if self.entry.borrow().is_none() {
            self.entry.replace(Some(bip39::import()));
        }
        ui.set_screen(Screen::Import);
        self.draw(ui, "");
    }

    /// `⏎` is Done (02-core.md §4). Reachable only while core says the words make a phrase of
    /// an accepted length — which is not the same as saying they are the right words, and
    /// this is the screen where that distinction is the whole point.
    pub fn done(&self, ui: &AppWindow) {
        self.act(ui, Action::Finish);
    }

    /// One printable keystroke.
    fn typed(&self, ui: &AppWindow, text: &str) {
        let mut letters = text.chars();
        let (Some(key), None) = (letters.next(), letters.next()) else {
            return;
        };
        // A key with no printable form has no name to report either, so it is dropped rather
        // than announced — the same call the retype and the passphrase field make (standing
        // rule 8).
        if key != ' ' && !key.is_ascii_graphic() {
            return;
        }
        // **Space commits.** The keystroke-to-action mapping is this module's whole share of
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
    /// **The one place this file asks a question about the phrase is the `Complete` arm**, and
    /// it does not answer it: [`Mnemonic::from_entry`] evaluates the checksum, and what comes
    /// back is a destination — the load screen, or this screen with a sentence on it.
    fn act(&self, ui: &AppWindow, action: Action) {
        let (outcome, note) = {
            let mut held = self.entry.borrow_mut();
            let Some(entry) = held.as_mut() else {
                return;
            };
            let outcome = entry.apply(action);
            (outcome, refusal(entry, action, outcome))
        };

        if outcome != Outcome::Complete {
            self.draw(ui, &note);
            return;
        }

        // `⏎` on a phrase-shaped run of an accepted length. **This is the only place in the
        // product a checksum is evaluated**, and it is core that evaluates it.
        let checked = {
            let held = self.entry.borrow();
            let Some(entry) = held.as_ref() else {
                return;
            };
            Mnemonic::from_entry(entry)
        };

        match checked {
            // §5's one load screen, which every path reaches: the passphrase and the network
            // enter at derivation, so a phrase that has just checked out has nothing left to
            // do but be loaded.
            Ok(phrase) => {
                self.phrase.set(phrase);
                self.draw(ui, "");
                ui.set_screen(Screen::Load);
            }
            // The words stay, and they stay by construction: `from_entry` took the entry by
            // reference and there is nothing in this file that could clear a slot.
            Err(_) => self.draw(ui, CHECKSUM),
        }
    }

    /// Push core's state onto the screen. An empty `note` means *nothing was refused*, and
    /// the standing hint takes the line instead.
    fn draw(&self, ui: &AppWindow, note: &str) {
        let (left, right, progress, done, note) = {
            let held = self.entry.borrow();
            let Some(entry) = held.as_ref() else {
                return;
            };
            let (left, right) = columns(entry);
            let line = if note.is_empty() {
                hint(entry)
            } else {
                note.to_owned()
            };
            (left, right, done_note(entry), entry.can_finish(), line)
        };

        // The borrows end before a single property is set: a `RefCell` still held across a
        // Slint property change is the shape that panics the day something re-enters here.
        ui.set_import_left(ModelRc::new(VecModel::from(left)));
        ui.set_import_right(ModelRc::new(VecModel::from(right)));
        ui.set_import_progress(progress.into());
        ui.set_import_done(done);
        ui.set_import_note(note.into());
    }
}

/// What a failed checksum says, and what it refuses to say (02-core.md §4, `04-screens.md` §6).
///
/// It states the two facts and stops: the check covers the phrase as a whole, and it cannot
/// name the wrong word. **No code**, because nothing was refused and nothing was discarded
/// (06-codes.md §4) — the words are still on screen and the user is still holding the paper.
const CHECKSUM: &str = "These words do not check out. The check covers the phrase as a whole, \
    so it cannot say which word is wrong — compare every word and its place against your paper.";

/// The standing line: **English, the keymap**, and how to type a word.
///
/// `02-core.md` §4 names the cost this states: a non-English mnemonic cannot be imported at
/// all, and the failure is a wall — the first word simply will not type — rather than a
/// message. So English is named before the user starts, which is what this line being on
/// screen at the first paint means; it is replaced by the live line as soon as a key lands.
/// The keymap is here for §5.1's reason, and here it degrades gently: the wordlist is `a`–`z`,
/// the pinned `us` keymap puts those on the same physical keys on every board, and only the
/// legends can mislead — after which an off-list keystroke names itself on this same line.
fn hint(entry: &Entry) -> String {
    let typed = entry.buffer();
    if typed.is_empty() {
        "English wordlist, US keyboard layout. Four letters and a space place any word; \
         Backspace steps back."
            .to_owned()
    } else if entry.matches() == 1 {
        format!("“{typed}{}” — press space to place it.", entry.ghost())
    } else {
        format!("“{typed}” matches {} words.", entry.matches())
    }
}

/// The Done control's note while it is locked, and what it says when it is not.
///
/// **The accepted lengths are read out of core's own constant**, so the sentence and the
/// control that enforces it cannot drift: `can_finish` and this line are the same five
/// numbers. Twenty-four slots are drawn either way, which is what makes them self-evident at
/// a glance (02-core.md §4, behaviour 6).
fn done_note(entry: &Entry) -> String {
    if entry.can_finish() {
        return "Press Enter to finish.".to_owned();
    }
    let lengths: Vec<String> = bip39::LENGTHS.iter().map(usize::to_string).collect();
    let (last, rest) = lengths
        .split_last()
        .expect("BIP-39 has five accepted lengths");
    format!(
        "{} typed. Done unlocks at {} or {last} words.",
        entry.settled(),
        rest.join(", "),
    )
}

#[cfg(test)]
mod tests {
    use super::{done_note, hint, CHECKSUM};
    use aobs_core::bip39::{self, Error, Mnemonic};
    use aobs_core::entry::{Action, Entry, Outcome};

    /// BIP-39's own all-zero twelve-word vector.
    const TWELVE: &str = "abandon abandon abandon abandon abandon abandon \
                          abandon abandon abandon abandon abandon about";

    fn type_in(sentence: &str) -> Entry {
        let mut entry = bip39::import();
        for word in sentence.split_whitespace() {
            for letter in word.chars() {
                entry.apply(Action::Char(letter));
            }
            entry.apply(Action::Commit);
        }
        entry
    }

    /// 04-screens.md §6: **the screen names English and the US keymap before the user
    /// starts.** The standing line is what "before" means here — it is on screen at the first
    /// paint and is replaced by the live line as soon as a key lands.
    #[test]
    fn the_standing_line_names_english_and_the_keymap_before_the_user_starts() {
        let mut entry = bip39::import();
        let standing = hint(&entry);
        assert!(standing.contains("English wordlist"));
        assert!(standing.contains("US keyboard layout"));

        entry.apply(Action::Char('a'));
        assert!(!hint(&entry).contains("English wordlist"));
    }

    #[test]
    fn the_hint_becomes_the_word_the_prefix_resolves_to() {
        let mut entry = bip39::import();
        for letter in "aban".chars() {
            entry.apply(Action::Char(letter));
        }
        assert_eq!(hint(&entry), "“abandon” — press space to place it.");
    }

    /// Behaviour 6, as the sentence the locked control carries: the five lengths are stated,
    /// and they come from core rather than from this file.
    #[test]
    fn the_locked_control_states_the_five_accepted_lengths() {
        let note = done_note(&bip39::import());
        assert_eq!(note, "0 typed. Done unlocks at 12, 15, 18, 21 or 24 words.");
        for count in bip39::LENGTHS {
            assert!(note.contains(&count.to_string()), "{count}");
        }
    }

    #[test]
    fn done_unlocks_at_twelve_words_and_locks_again_at_thirteen() {
        let entry = type_in(TWELVE);
        assert!(entry.can_finish());
        assert_eq!(done_note(&entry), "Press Enter to finish.");

        let entry = type_in(&format!("{TWELVE} abandon"));
        assert!(!entry.can_finish());
        assert_eq!(
            done_note(&entry),
            "13 typed. Done unlocks at 12, 15, 18, 21 or 24 words."
        );
    }

    /// The whole of what this screen adds to the retype: there is no answer, so the checksum
    /// is the only verdict — and the sentence it produces says both what the check covers and
    /// what it cannot do.
    #[test]
    fn a_failed_checksum_says_it_cannot_name_the_wrong_word() {
        let entry = type_in(&TWELVE.replacen("abandon", "ability", 1));
        assert!(entry.can_finish());
        assert_eq!(Mnemonic::from_entry(&entry).err(), Some(Error::Checksum));

        assert!(CHECKSUM.contains("as a whole"));
        assert!(CHECKSUM.contains("cannot say which word is wrong"));
        // No `AOBS-` code: nothing was refused and nothing was discarded (06-codes.md §4).
        assert!(!CHECKSUM.contains("AOBS-"));
    }

    /// And the words survive it, which is the user's only repair instrument. It is structural
    /// rather than remembered: `from_entry` takes the entry by reference.
    #[test]
    fn a_failed_checksum_keeps_every_word() {
        let entry = type_in(&TWELVE.replacen("abandon", "ability", 1));
        assert!(Mnemonic::from_entry(&entry).is_err());
        assert_eq!(entry.word(0), Some("ability"));
        assert_eq!(entry.word(11), Some("about"));
        assert_eq!(entry.settled(), 12);
    }

    /// A phrase that checks out is a phrase, and `⏎` is what says so.
    #[test]
    fn a_valid_phrase_completes_and_is_the_one_that_was_typed() {
        let mut entry = type_in(TWELVE);
        assert_eq!(entry.apply(Action::Finish), Outcome::Complete);
        let phrase = Mnemonic::from_entry(&entry).expect("a published vector");
        assert_eq!(phrase.word_count(), 12);
        assert_eq!(phrase.word(11), Some("about"));
    }

    /// An off-list keystroke does not land, which is what makes a checksum failure mean
    /// *real words in the wrong place* and nothing else.
    #[test]
    fn a_word_that_is_not_a_word_cannot_be_typed_at_all() {
        let mut entry = bip39::import();
        for letter in "bit".chars() {
            assert_eq!(entry.apply(Action::Char(letter)), Outcome::Accepted);
        }
        assert_eq!(entry.apply(Action::Char('c')), Outcome::Ignored);
        assert_eq!(entry.buffer(), "bit");
    }
}
