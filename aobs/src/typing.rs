//! What every word-entry screen draws, given core's state (02-core.md §4).
//!
//! Four functions, and none of them is a decision: two turn a keystroke into an [`Action`],
//! one turns an [`Entry`] into the [`Slot`] model the grid renders, and one turns an
//! [`Outcome`] into the sentence the live line reports. All four are pure adapters between the
//! keyboard and what core already said.
//!
//! **They are here rather than copied per screen for one reason: they are the only two places
//! the shell restates something core decided.** `columns` reads the buffer, the ghost and the
//! settled word back; `refusal` names the key that did not land and how many words a prefix
//! still matches. Two copies of that are two places that can disagree about what core said —
//! and disagreement here looks like a screen that draws a word the reducer did not place.
//!
//! Two more turn a keystroke into an [`Action`], which is the shell's whole share of §4 and is
//! the same share on every screen: **space commits**, a key with no printable form is dropped
//! rather than announced (standing rule 8), and an arrow key off either end of the array is not
//! a destination.
//!
//! What is deliberately **not** here is the copy. The heading, the standing hint and the Done
//! control's note are each screen's own: the retype is typing from paper against an answer we
//! hold (04-screens.md §4) and the import is typing a phrase we know nothing about (§6), and
//! the two say different things for that reason.

use aobs_core::entry::{Action, Entry, Outcome};

use crate::Slot;

/// Slots per column. Twelve, in two column-major columns, the same geometry the phrase is
/// drawn in (04-screens.md §3) — so the paper, the phrase screen and every screen that types
/// words back agree on where word 13 is, and the copy stays positional rather than sequential.
pub const COLUMN: usize = 12;

/// What one keystroke means, or `None` for one that means nothing.
///
/// **Space commits** — that mapping is the shell's whole contribution to 02-core.md §4, and what
/// a letter does with the wordlist is core's. Slint delivers named keys as characters too, and
/// the ones the frame does not bind arrive as private-use code points: a key with no printable
/// form has no name to report either, so it is dropped rather than announced (standing rule 8).
pub fn keystroke(text: &str) -> Option<Action> {
    let mut letters = text.chars();
    let (Some(key), None) = (letters.next(), letters.next()) else {
        return None;
    };
    match key {
        ' ' => Some(Action::Commit),
        printable if printable.is_ascii_graphic() => Some(Action::Char(printable)),
        _ => None,
    }
}

/// An arrow key, as a destination slot. Off either end there is no destination, so nothing
/// happens — and in particular the buffer is not settled by a move that is not going to happen.
pub fn destination(entry: &Entry, delta: i32) -> Option<usize> {
    entry.cursor().checked_add_signed(delta as isize)
}

/// An entry as two columns: **1–12 left, 13–24 right**, column-major.
///
/// **Only what the user typed crosses.** A committed word is echoed, because nothing in this
/// product is masked and an off-by-one has to be visible as a *shift* rather than as a mystery
/// rejection at word 20. The slot being typed into shows the buffer instead, so a word in
/// progress is never confused with one that landed.
pub fn columns(entry: &Entry) -> (Vec<Slot>, Vec<Slot>) {
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
pub fn refusal(entry: &Entry, action: Action, outcome: Outcome) -> String {
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

#[cfg(test)]
mod tests {
    use super::{columns, destination, keystroke, refusal, COLUMN};
    use aobs_core::bip39;
    use aobs_core::entry::{Action, Entry, Outcome};

    fn letters(entry: &mut Entry, word: &str) {
        for letter in word.chars() {
            entry.apply(Action::Char(letter));
        }
    }

    #[test]
    fn the_grid_is_twelve_and_twelve_column_major() {
        let (left, right) = columns(&bip39::import());
        assert_eq!(left.len(), COLUMN);
        assert_eq!(right.len(), COLUMN);
        assert_eq!(left[0].position, 1);
        assert_eq!(left[COLUMN - 1].position, 12);
        assert_eq!(right[0].position, 13);
        assert_eq!(right[COLUMN - 1].position, 24);
    }

    #[test]
    fn a_fresh_entry_shows_nothing_at_all() {
        let (left, right) = columns(&bip39::import());
        for slot in left.iter().chain(right.iter()) {
            assert_eq!(slot.text, "");
            assert_eq!(slot.ghost, "");
        }
        assert!(left[0].current);
    }

    #[test]
    fn committed_words_are_echoed_and_the_slot_being_typed_shows_the_buffer() {
        let mut entry = bip39::import();
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
        let mut entry = bip39::import();
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
        let mut entry = bip39::import();
        letters(&mut entry, "ab");
        let outcome = entry.apply(Action::Commit);
        assert_eq!(outcome, Outcome::Ignored);
        assert!(refusal(&entry, Action::Commit, outcome).starts_with("“ab” still matches "));
    }

    #[test]
    fn space_commits_and_a_key_with_no_printable_form_is_dropped() {
        // `assert!` rather than `assert_eq!`: `Action` has no `Debug`, deliberately — a
        // `Char` is a letter of the user's mnemonic (01-boot-layer.md §9).
        assert!(keystroke(" ") == Some(Action::Commit));
        assert!(keystroke("a") == Some(Action::Char('a')));
        // A capital and a digit are keys core will refuse, and they are still keystrokes: the
        // screen names what did not land, and it can only do that for a key it was handed.
        assert!(keystroke("A") == Some(Action::Char('A')));
        assert!(keystroke("7") == Some(Action::Char('7')));
        // A named key Slint delivers as a private-use code point, and a text run that is not
        // one character at all.
        assert!(keystroke("\u{f700}").is_none());
        assert!(keystroke("").is_none());
        assert!(keystroke("ab").is_none());
    }

    #[test]
    fn an_arrow_off_the_front_of_the_array_is_not_a_destination() {
        let mut entry = bip39::import();
        assert_eq!(destination(&entry, -1), None);
        assert_eq!(destination(&entry, 1), Some(1));
        letters(&mut entry, "aban");
        entry.apply(Action::Commit);
        assert_eq!(destination(&entry, -1), Some(0));
    }

    #[test]
    fn an_action_that_worked_says_nothing() {
        let mut entry = bip39::import();
        letters(&mut entry, "aban");
        let outcome = entry.apply(Action::Commit);
        assert_eq!(outcome, Outcome::Accepted);
        assert_eq!(refusal(&entry, Action::Commit, outcome), "");
    }
}
