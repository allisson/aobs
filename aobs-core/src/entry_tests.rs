//! The six settled behaviours, the correction keys, and the type-back's compare
//! (`02-core.md` §4, `04-screens.md` §4).
//!
//! Every test here is one line of a settled decision rather than a case somebody thought of:
//! prefix matching, space commits, **no** auto-accept, an off-list keystroke that does not
//! land, the two correction keys, and — the one thing the retype adds to import — a wrong
//! word rejected immediately and by position with nothing destroyed.

use proptest::prelude::*;

use super::*;
use crate::bip39::{Mnemonic, WORDS};
use crate::secret::Entropy;

/// A four-word list that is not BIP-39's, which is what proves the component is
/// parameterised rather than wired to one wordlist (`04-screens.md` §9's EFF type-back is
/// the second caller). `alpha` and `alpine` share a prefix on purpose.
static TINY: [&str; 4] = ["alpha", "alpine", "beta", "gamma"];

/// BIP-39's own all-zero vector: `abandon` twenty-three times, then `art`.
///
/// The repetition is what makes the position tests readable — the one word that is not
/// `abandon` is the only thing that can be in the wrong place.
fn generated() -> Mnemonic {
    Mnemonic::from_entropy(&Entropy::new(&[0u8; 32]).expect("32 bytes")).expect("24 words")
}

fn retype() -> Entry {
    generated().type_back()
}

fn import() -> Entry {
    Entry::open(&WORDS, 24).expect("the BIP-39 list drives entry")
}

/// Type the letters of `word` and hand back the last outcome.
fn letters(entry: &mut Entry, word: &str) -> Outcome {
    let mut last = Outcome::Accepted;
    for letter in word.chars() {
        last = entry.apply(Action::Char(letter));
    }
    last
}

/// Type a word and commit it with the space bar.
fn word(entry: &mut Entry, word: &str) -> Outcome {
    letters(entry, word);
    entry.apply(Action::Commit)
}

// --- 1. Prefix matching, and space commits ----------------------------------------

#[test]
fn a_prefix_narrows_to_one_word_and_space_commits_it() {
    let mut entry = import();

    letters(&mut entry, "aban");
    assert_eq!(entry.matches(), 1);
    assert_eq!(entry.buffer(), "aban");
    // The single remaining word, ghosted inline: the screen draws the buffer and then this.
    assert_eq!(entry.ghost(), "don");

    assert_eq!(entry.apply(Action::Commit), Outcome::Accepted);
    assert_eq!(entry.word(0), Some("abandon"));
    assert_eq!(entry.cursor(), 1);
    assert_eq!(entry.buffer(), "");
}

#[test]
fn four_characters_are_enough_for_every_word_in_the_list() {
    // 02-core.md §4's first behaviour rests on this, and `bip39_tests.rs` asserts the
    // uniqueness of the list itself. Here it is asserted *through the reducer*: four
    // characters of any word resolve to that word, which is what makes space-commits work.
    for chunk in WORDS.chunks(24) {
        let mut entry = import();
        for (slot, expected) in chunk.iter().enumerate() {
            let prefix: String = expected.chars().take(4).collect();
            letters(&mut entry, &prefix);
            assert_eq!(entry.apply(Action::Commit), Outcome::Accepted, "{expected}");
            assert_eq!(entry.word(slot), Some(*expected));
        }
    }
}

#[test]
fn a_word_that_is_also_a_prefix_commits_as_itself() {
    // `add` is a word and `address` continues it, so the ambiguity is real and an exact
    // match has to win. Without this, ten of the 2048 words could not be typed at all.
    let mut entry = import();
    assert_eq!(word(&mut entry, "add"), Outcome::Accepted);
    assert_eq!(entry.word(0), Some("add"));
}

#[test]
fn an_ambiguous_prefix_does_not_commit_and_says_how_many_words_it_matches() {
    let mut entry = import();
    letters(&mut entry, "ab");
    assert!(entry.matches() > 1);
    // Nothing to ghost: there is no single remaining word.
    assert_eq!(entry.ghost(), "");

    assert_eq!(entry.apply(Action::Commit), Outcome::Ignored);
    assert_eq!(entry.word(0), None);
    assert_eq!(entry.buffer(), "ab");
}

#[test]
fn space_on_an_empty_buffer_does_nothing() {
    let mut entry = import();
    assert_eq!(entry.apply(Action::Commit), Outcome::Ignored);
    assert_eq!(entry.cursor(), 0);
    assert_eq!(entry.settled(), 0);
}

#[test]
fn nothing_is_matched_before_a_letter_is_typed() {
    let entry = import();
    assert_eq!(entry.matches(), 0);
    assert_eq!(entry.ghost(), "");
    assert_eq!(entry.buffer(), "");
}

// --- 2. No auto-accept on a unique prefix -----------------------------------------

#[test]
fn a_unique_prefix_does_not_commit_itself() {
    // The whole word, typed out, with no space: still nothing in the slot. Auto-accept fires
    // at an unpredictable letter and the rest of the word lands in the *next* slot, which
    // fails the checksum exactly as a wrong word does — globally and unlocalisably.
    let mut entry = import();
    letters(&mut entry, "abandon");
    assert_eq!(entry.matches(), 1);
    assert_eq!(entry.word(0), None);
    assert_eq!(entry.cursor(), 0);
    assert_eq!(entry.settled(), 0);
}

// --- 3. An off-list keystroke does not land ---------------------------------------

#[test]
fn a_keystroke_that_continues_no_word_does_not_land() {
    let mut entry = import();
    letters(&mut entry, "bit");
    // `bit` is fine — `bitter` continues it — and `bitc` has nowhere to go.
    assert_eq!(entry.apply(Action::Char('c')), Outcome::Ignored);
    assert_eq!(entry.buffer(), "bit");
}

#[test]
fn a_letter_past_the_longest_matching_word_does_not_land() {
    let mut entry = import();
    letters(&mut entry, "abandon");
    assert_eq!(entry.apply(Action::Char('x')), Outcome::Ignored);
    assert_eq!(entry.buffer(), "abandon");
}

#[test]
fn a_capital_a_digit_and_a_letter_with_a_diacritic_are_all_off_list() {
    // The wordlist is `a`–`z` and the appliance pins a `us` keymap with no dead keys, so
    // these are exactly the keys 02-core.md §4's third behaviour is about: they do not land,
    // and the screen names the key it ignored. The last two are the classes that would need
    // their own arm if the byte came from the keystroke rather than from the wordlist.
    let mut entry = import();
    for keystroke in ['A', '4', 'é', ' ', 'あ'] {
        assert_eq!(entry.apply(Action::Char(keystroke)), Outcome::Ignored);
        assert_eq!(entry.buffer(), "");
    }
}

// --- 4. Committed words are echoed, and nothing is masked -------------------------

#[test]
fn committed_words_are_readable_and_the_uncommitted_slots_are_empty() {
    let mut entry = import();
    word(&mut entry, "aban");
    word(&mut entry, "abil");

    assert_eq!(entry.word(0), Some("abandon"));
    assert_eq!(entry.word(1), Some("ability"));
    assert_eq!(entry.word(2), None);
    assert_eq!(entry.word(23), None);
    assert_eq!(entry.word(24), None);
    assert_eq!(entry.settled(), 2);
}

// --- The correction keys ----------------------------------------------------------

#[test]
fn leaving_a_slot_settles_a_buffer_that_resolves() {
    let mut entry = import();
    letters(&mut entry, "aban");
    assert_eq!(entry.apply(Action::Goto(1)), Outcome::Accepted);
    assert_eq!(entry.word(0), Some("abandon"));
    assert_eq!(entry.cursor(), 1);
    assert_eq!(entry.buffer(), "");
}

#[test]
fn leaving_a_slot_drops_a_buffer_that_does_not_resolve() {
    let mut entry = import();
    letters(&mut entry, "ab");
    assert_eq!(entry.apply(Action::Goto(1)), Outcome::Accepted);
    assert_eq!(entry.word(0), None);
    assert_eq!(entry.cursor(), 1);
    assert_eq!(entry.buffer(), "");
}

#[test]
fn a_slot_off_the_end_is_not_a_destination() {
    let mut entry = import();
    letters(&mut entry, "aban");
    assert_eq!(entry.apply(Action::Goto(24)), Outcome::Ignored);
    // The refused move takes nothing with it: the buffer is still being typed.
    assert_eq!(entry.buffer(), "aban");
    assert_eq!(entry.cursor(), 0);
}

#[test]
fn backspace_deletes_a_letter() {
    let mut entry = import();
    letters(&mut entry, "aban");
    assert_eq!(entry.apply(Action::Back), Outcome::Accepted);
    assert_eq!(entry.buffer(), "aba");
}

#[test]
fn backspace_at_an_empty_buffer_steps_back_and_returns_the_word_as_editable_text() {
    let mut entry = import();
    word(&mut entry, "aban");
    word(&mut entry, "abil");
    assert_eq!(entry.cursor(), 2);

    assert_eq!(entry.apply(Action::Back), Outcome::Accepted);
    assert_eq!(entry.cursor(), 1);
    // Editable text, not a re-selected slot: the next backspace deletes a letter of it.
    assert_eq!(entry.buffer(), "ability");
    assert_eq!(entry.word(1), None);
    assert_eq!(entry.settled(), 1);

    assert_eq!(entry.apply(Action::Back), Outcome::Accepted);
    assert_eq!(entry.buffer(), "abilit");
}

#[test]
fn backspace_into_an_empty_slot_just_moves_the_cursor() {
    let mut entry = import();
    entry.apply(Action::Goto(3));
    assert_eq!(entry.apply(Action::Back), Outcome::Accepted);
    assert_eq!(entry.cursor(), 2);
    assert_eq!(entry.buffer(), "");
}

#[test]
fn backspace_at_the_first_slot_with_nothing_typed_does_nothing() {
    let mut entry = import();
    assert_eq!(entry.apply(Action::Back), Outcome::Ignored);
    assert_eq!(entry.cursor(), 0);
}

// --- The type-back: we know the answer -------------------------------------------

#[test]
fn the_generated_phrase_is_not_readable_from_the_entry_state() {
    // 04-screens.md §4: the mnemonic is never re-shown during the retype. The target is in
    // here — the compare needs it — and there is no accessor that hands it back, so the only
    // words the screen can draw are the ones the user typed.
    let entry = retype();
    for position in 0..entry.slots() {
        assert_eq!(entry.word(position), None);
    }
    assert_eq!(entry.buffer(), "");
    assert_eq!(entry.slots(), 24);
}

#[test]
fn a_wrong_word_is_rejected_immediately_and_by_position() {
    let mut entry = retype();
    word(&mut entry, "aban");

    // Word 2 of the generated phrase is `abandon`; `ability` is a real word in the wrong
    // place, which after behaviour 3 is the only kind of mistake that can be made.
    assert_eq!(word(&mut entry, "abil"), Outcome::Wrong(1));

    // Nothing is destroyed: the first word stands, the cursor is at the position to repair,
    // and the slot the wrong word would have gone into is empty.
    assert_eq!(entry.word(0), Some("abandon"));
    assert_eq!(entry.word(1), None);
    assert_eq!(entry.cursor(), 1);
    assert_eq!(entry.buffer(), "");
    assert_eq!(entry.settled(), 1);
}

#[test]
fn the_position_that_was_wrong_can_simply_be_typed_again() {
    let mut entry = retype();
    assert_eq!(word(&mut entry, "abil"), Outcome::Wrong(0));
    assert_eq!(word(&mut entry, "aban"), Outcome::Accepted);
    assert_eq!(entry.word(0), Some("abandon"));
    assert_eq!(entry.cursor(), 1);
}

#[test]
fn leaving_a_slot_with_the_wrong_word_in_the_buffer_is_the_same_rejection() {
    let mut entry = retype();
    letters(&mut entry, "abil");
    assert_eq!(entry.apply(Action::Goto(1)), Outcome::Wrong(0));
    // The move does not happen: the repair is at the position that was wrong.
    assert_eq!(entry.cursor(), 0);
    assert_eq!(entry.word(0), None);
}

#[test]
fn the_whole_phrase_typed_back_from_paper_completes() {
    let mut entry = retype();
    let phrase = generated();

    for position in 0..24 {
        let expected = phrase.word(position).expect("24 words");
        assert!(
            !entry.can_finish() || position == 23,
            "not done before word 24"
        );
        assert_eq!(
            word(&mut entry, expected),
            Outcome::Accepted,
            "word {position}"
        );
    }

    assert_eq!(entry.settled(), 24);
    assert!(entry.can_finish());
    assert_eq!(entry.apply(Action::Finish), Outcome::Complete);
}

#[test]
fn the_last_word_can_be_finished_without_committing_it_first() {
    // `⏎` is Done (02-core.md §4), and leaving a slot settles a buffer that resolves — so the
    // 24th word does not need a space after it before Done becomes reachable.
    let mut entry = retype();
    for _ in 0..23 {
        word(&mut entry, "aban");
    }
    letters(&mut entry, "art");
    assert!(entry.can_finish());
    assert_eq!(entry.apply(Action::Finish), Outcome::Complete);
    assert_eq!(entry.word(23), Some("art"));
}

#[test]
fn the_last_word_being_wrong_is_the_same_rejection_by_position() {
    let mut entry = retype();
    for _ in 0..23 {
        word(&mut entry, "aban");
    }
    // 23 `abandon`s and a 24th is the phrase with its last word wrong — the mis-copy this
    // whole screen exists to catch.
    letters(&mut entry, "aban");
    assert_eq!(entry.apply(Action::Finish), Outcome::Wrong(23));
    assert_eq!(entry.settled(), 23);
}

#[test]
fn done_is_unreachable_until_every_slot_is_settled() {
    let mut entry = retype();
    word(&mut entry, "aban");
    assert!(!entry.can_finish());
    assert_eq!(entry.apply(Action::Finish), Outcome::Ignored);
    // Refused, and it took nothing with it.
    assert_eq!(entry.word(0), Some("abandon"));
    assert_eq!(entry.settled(), 1);
}

#[test]
fn a_junk_buffer_is_dropped_by_done_rather_than_blocking_it() {
    let mut entry = retype();
    for _ in 0..23 {
        word(&mut entry, "aban");
    }
    word(&mut entry, "art");
    // Every slot is settled and the user has started typing into the last one again.
    letters(&mut entry, "ab");
    assert!(entry.can_finish());
    assert_eq!(entry.apply(Action::Finish), Outcome::Complete);
    assert_eq!(entry.buffer(), "");
    assert_eq!(entry.word(23), Some("art"));
}

// --- Parameterised by wordlist ---------------------------------------------------

#[test]
fn the_same_code_drives_a_wordlist_that_is_not_bip39s() {
    let mut entry = Entry::open(&TINY, 3).expect("a four-word list drives entry");
    assert_eq!(entry.slots(), 3);

    letters(&mut entry, "alp");
    assert_eq!(entry.matches(), 2);
    assert_eq!(entry.apply(Action::Commit), Outcome::Ignored);

    letters(&mut entry, "h");
    assert_eq!(entry.matches(), 1);
    assert_eq!(entry.ghost(), "a");
    assert_eq!(entry.apply(Action::Commit), Outcome::Accepted);
    assert_eq!(entry.word(0), Some("alpha"));

    assert_eq!(word(&mut entry, "beta"), Outcome::Accepted);
    assert_eq!(word(&mut entry, "gamma"), Outcome::Accepted);
    assert_eq!(entry.apply(Action::Finish), Outcome::Complete);
}

#[test]
fn a_type_back_over_another_wordlist_compares_the_same_way() {
    // 04-screens.md §9's eight EFF words, in miniature: a known answer over a list that is
    // not BIP-39's, driving the same compare.
    let mut entry = Entry::type_back(&TINY, &[2, 0]).expect("two of four words");
    assert_eq!(entry.slots(), 2);
    assert_eq!(word(&mut entry, "beta"), Outcome::Accepted);
    assert_eq!(word(&mut entry, "alpine"), Outcome::Wrong(1));
    assert_eq!(word(&mut entry, "alpha"), Outcome::Accepted);
    assert_eq!(entry.apply(Action::Finish), Outcome::Complete);
}

#[test]
fn a_wordlist_or_a_slot_count_the_buffers_cannot_hold_is_refused() {
    static LONG: [&str; 1] = ["antidisestablishmentarian"];
    static WIDE: [&str; 1] = ["café"];
    static EMPTY: [&str; 1] = [""];

    assert!(Entry::open(&LONG, 1).is_none());
    assert!(Entry::open(&WIDE, 1).is_none());
    assert!(Entry::open(&EMPTY, 1).is_none());
    assert!(Entry::open(&[], 1).is_none());
    assert!(Entry::open(&TINY, 0).is_none());
    assert!(Entry::open(&TINY, MAX_SLOTS + 1).is_none());
    assert!(Entry::type_back(&TINY, &[]).is_none());
    assert!(Entry::type_back(&TINY, &[9]).is_none());
    assert!(Entry::type_back(&TINY, &[0; MAX_SLOTS + 1]).is_none());
}

// --- What the state says about itself --------------------------------------------

#[test]
fn debug_and_display_are_redacted() {
    let entry = retype();
    assert_eq!(format!("{entry:?}"), "[redacted]");
    assert_eq!(format!("{entry}"), "[redacted]");
}

proptest! {
    /// **No sequence of keystrokes can put a word in a slot that is not the generated one**,
    /// and none can push the state out of its own arrays.
    ///
    /// The first half is the retype's whole safety claim, asserted against sequences nobody
    /// wrote a case for rather than against the ones we thought of. The second half is here
    /// because every action indexes fixed arrays, and an out-of-bounds index is a panic that
    /// ends a session mid-transcription (`06-codes.md` §5, `AOBS-E04`) — it also earned its
    /// place: the first draft of [`Entry::apply`]'s `Char` arm evaluated its landing byte
    /// eagerly and indexed one past a short word.
    #[test]
    fn no_sequence_of_keystrokes_places_a_word_we_did_not_generate(
        codes in prop::collection::vec(0u8..=40, 0..120),
    ) {
        let phrase = generated();
        let mut entry = phrase.type_back();

        for code in codes {
            let action = match code {
                letter @ 0..=25 => Action::Char(char::from(b'a' + letter)),
                26 => Action::Commit,
                27 => Action::Back,
                28 => Action::Finish,
                // Three keystrokes that cannot be on the list, so the refusal arm is walked
                // as often as the accepting one.
                29 => Action::Char('A'),
                30 => Action::Char('7'),
                31 => Action::Char('あ'),
                // Destinations on and off the end of the grid.
                slot => Action::Goto(usize::from(slot - 32) * 3),
            };
            entry.apply(action);

            prop_assert!(entry.cursor() < entry.slots());
            prop_assert!(entry.settled() <= entry.slots());
            // The longest word in the list, which is what bounds the buffer in practice.
            prop_assert!(entry.buffer().len() <= 8);

            for position in 0..entry.slots() {
                if let Some(placed) = entry.word(position) {
                    prop_assert_eq!(placed, phrase.word(position).expect("24 words"));
                }
            }
        }
    }
}
