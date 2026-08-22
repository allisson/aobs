//! The shared word-entry component: prefix matching over a fixed slot array, the two
//! correction keys, and the type-back's byte compare (`02-core.md` §4).
//!
//! **One component, four screens.** Seed import (`04-screens.md` §6) types words with no
//! answer to compare against; the creation retype (§4) and the backup's type-back (§9) type
//! them against an answer we hold; the backup restore (§10) types eight words over a
//! different wordlist. The wordlist and the slot count are therefore parameters, and the
//! *answer* is the one thing that changes the failure path — with one, a wrong word is
//! rejected immediately and by position; without one, nothing here can say a word is wrong at
//! all and the checksum has the last word ([`crate::bip39::Mnemonic::from_indices`]).
//!
//! Six behaviours are settled decisions rather than preferences, and each is a rule this file
//! is the only home of (`02-core.md` §4):
//!
//! 1. **Prefix matching, and space commits.** Every BIP-39 word is unique within four
//!    characters, so four keystrokes and a space is the whole of typing one.
//! 2. **No auto-accept on a unique prefix.** Auto-accept fires at an unpredictable letter and
//!    the rest of the word lands in the *next* slot, silently shifting the phrase — which
//!    fails the checksum exactly as a wrong word does: globally and unlocalisably. The price
//!    of refusing it is one keystroke per word.
//! 3. **An off-list keystroke does not land**, and the screen names the key that was ignored.
//!    The consequence shapes everything after it: an off-list word is *unrepresentable*, so a
//!    checksum failure can only ever mean real words in the wrong place.
//! 4. **The checksum is not here.** It covers the phrase as a whole and is evaluated once, at
//!    the end, by the type that owns it. Nothing in this file validates a phrase.
//! 5. **The final word is never offered as a candidate.** [`Entry::ghost`] completes the word
//!    being *typed* and never proposes one; the appliance supplies no key material the user
//!    did not.
//! 6. **The length is inferred, not declared.** This file names no accepted length — the
//!    caller supplies them ([`Entry::inferred`]) and a type-back simply wants every slot
//!    ([`Entry::open`]). What this file *does* own is the shape a phrase has to have:
//!    [`Entry::can_finish`] counts the words settled so far and refuses a run with a hole in
//!    it, because a slot filled past an empty one is not the twelfth word of anything.
//!
//! **The sixth action `02-core.md` §4 names — `discard` — is deliberately absent.** Per the
//! session model discard *is* a restart (ADR-0010), so it ends the process rather than
//! resetting this state; it lands in the shell's router, and a reducer arm for it would be a
//! second, quieter way to reach a decision that has exactly one.
//!
//! The reducer takes `&mut self` rather than `(state, action) -> state` by value, and that is
//! not a style choice: moving a [`ZeroizeOnDrop`] value copies its bytes and leaves the
//! source copy unzeroized, so the by-value shape would scatter the phrase across the stack
//! once per keystroke. Same function, no copies.

use core::fmt;

use zeroize::{Zeroize, ZeroizeOnDrop};

use crate::secret::redacted;

/// The most slots any entry screen has: 24, BIP-39's longest phrase.
pub const MAX_SLOTS: usize = 24;

/// The buffer one word is typed into, in bytes.
///
/// Sixteen against a longest BIP-39 word of 8 and a longest EFF long-list word of 9, and the
/// slack is not laziness: [`Action::Back`] lifts a settled word back into this buffer as
/// editable text, so it has to hold the longest word either list can produce. That the words
/// fit is a constructor invariant rather than a check per keystroke — see [`Entry::open`].
const MAX_WORD: usize = 16;

/// What the keyboard did, as the shell's keymap resolved it.
///
/// **No `Debug`.** A [`Self::Char`] is a letter of the user's mnemonic, and `01-boot-layer.md`
/// §9 rules the console prints only fixed strings and typed variant names — never formatted
/// program state. A derive here would be a way to print one.
#[derive(Clone, Copy, PartialEq, Eq)]
pub enum Action {
    /// A printable keystroke, appended to the buffer if some word continues it.
    Char(char),
    /// The space bar: settle the buffer into the current slot and move on.
    Commit,
    /// Backspace: a letter, or — at an empty buffer — a step back that returns the previous
    /// word as editable text.
    Back,
    /// An arrow key resolved to a destination slot: settle or drop the buffer, then move.
    Goto(usize),
    /// `⏎`: settle the buffer and finish, if every slot is settled.
    Finish,
}

/// What came of an [`Action`], and the whole of what the screen has to draw a consequence
/// from.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Outcome {
    /// The state changed.
    Accepted,
    /// **Nothing changed.** After a [`Action::Char`] the screen names the key that was
    /// ignored; after anything else the control it came from was not offered in the first
    /// place.
    Ignored,
    /// A type-back only: the word offered at this position is not the one we hold.
    ///
    /// The slot stays empty, the buffer is dropped, the cursor stays where the repair is, and
    /// **every other slot is untouched** — `04-screens.md` §4's *destroys nothing*, as the
    /// shape of the state rather than as a promise. The position is what the screen marks.
    Wrong(usize),
    /// Every slot holds a settled word. [`Action::Finish`] and nothing else produces this.
    Complete,
}

/// One screen's worth of word entry: a wordlist, a fixed array of slots, and the word being
/// typed into one of them.
///
/// Secret by construction — the words typed here *are* the phrase — so: no `Clone`, no `Copy`,
/// fixed buffers allocated at full size, [`ZeroizeOnDrop`], and `Debug` written as
/// `[redacted]` (standing rule 5). The wordlist is skipped by the zeroizer because it is
/// public data the appliance ships.
#[derive(Zeroize, ZeroizeOnDrop)]
pub struct Entry {
    #[zeroize(skip)]
    words: &'static [&'static str],
    slots: usize,
    /// The word counts Done unlocks at, or `None` for *every slot*. Public data — five
    /// numbers out of BIP-39 — so the zeroizer skips it.
    #[zeroize(skip)]
    lengths: Option<&'static [usize]>,
    /// The answer, when there is one. Indices into [`Self::words`], and there is no accessor
    /// that hands them back: `04-screens.md` §4's *the mnemonic is never re-shown* is a
    /// missing method, not a screen that remembers to hide it.
    answer: [usize; MAX_SLOTS],
    known: bool,
    placed: [usize; MAX_SLOTS],
    filled: [bool; MAX_SLOTS],
    buffer: [u8; MAX_WORD],
    len: usize,
    cursor: usize,
}

impl Entry {
    /// Entry with no answer to compare against, finished when **every** slot holds a word:
    /// the restore side of the backup (`04-screens.md` §10), whose eight words are eight
    /// words.
    ///
    /// `None` when the buffers could not hold what this wordlist would put in them — a word
    /// that is empty, longer than [`MAX_WORD`] or not ASCII, an empty list, a list longer
    /// than an index fits in, or a slot count outside 1..=[`MAX_SLOTS`]. Both wordlists the
    /// appliance ships satisfy all of it, which is what lets every keystroke below index
    /// without a bound check of its own.
    #[must_use]
    pub fn open(words: &'static [&'static str], slots: usize) -> Option<Self> {
        Self::build(words, slots, None)
    }

    /// Entry whose Done unlocks at any of `lengths` rather than at a full array: seed import
    /// (`04-screens.md` §6), where twenty-four slots are always drawn and the length is
    /// *inferred* from where the words stop (`02-core.md` §4, behaviour 6).
    ///
    /// **The accepted counts are the caller's.** This file still names none; what it adds is
    /// that they have to be reachable — `None` on everything [`Self::open`] refuses, plus an
    /// empty set and any count outside `1..=slots`.
    #[must_use]
    pub fn inferred(
        words: &'static [&'static str],
        slots: usize,
        lengths: &'static [usize],
    ) -> Option<Self> {
        if lengths.is_empty() || !lengths.iter().all(|count| (1..=slots).contains(count)) {
            return None;
        }
        Self::build(words, slots, Some(lengths))
    }

    fn build(
        words: &'static [&'static str],
        slots: usize,
        lengths: Option<&'static [usize]>,
    ) -> Option<Self> {
        let usable = (1..=MAX_SLOTS).contains(&slots)
            && !words.is_empty()
            // An index into the list is handed out as a `u16` ([`Self::indices`]); 2048
            // BIP-39 words and 7776 EFF ones are both far under it.
            && words.len() <= usize::from(u16::MAX)
            && words
                .iter()
                .all(|word| word.is_ascii() && (1..=MAX_WORD).contains(&word.len()));
        usable.then(|| Self {
            words,
            slots,
            lengths,
            answer: [0; MAX_SLOTS],
            known: false,
            placed: [0; MAX_SLOTS],
            filled: [false; MAX_SLOTS],
            buffer: [0; MAX_WORD],
            len: 0,
            cursor: 0,
        })
    }

    /// Entry against an answer we hold: the creation retype (`04-screens.md` §4) and the
    /// backup's type-back (§9).
    ///
    /// `None` on everything [`Self::open`] refuses, plus an answer that is empty, longer than
    /// [`MAX_SLOTS`], or names a word off the list.
    #[must_use]
    pub fn type_back(words: &'static [&'static str], answer: &[u16]) -> Option<Self> {
        let mut entry = Self::open(words, answer.len())?;
        for (slot, &index) in entry.answer.iter_mut().zip(answer) {
            *slot = usize::from(index);
            if *slot >= words.len() {
                return None;
            }
        }
        entry.known = true;
        Some(entry)
    }

    /// Feed one keystroke's worth of intent in, and read the consequence out.
    pub fn apply(&mut self, action: Action) -> Outcome {
        match action {
            Action::Char(letter) => self.letter(letter),
            Action::Commit => self.commit(),
            Action::Back => self.back(),
            Action::Goto(position) => self.goto(position),
            Action::Finish => self.finish(),
        }
    }

    /// How many slots this screen has.
    #[must_use]
    pub fn slots(&self) -> usize {
        self.slots
    }

    /// Which slot the buffer is being typed into.
    #[must_use]
    pub fn cursor(&self) -> usize {
        self.cursor
    }

    /// The settled word at `position`, or `None` for a slot nothing has landed in.
    ///
    /// **This is the echo** (`02-core.md` §4: nothing is masked, anywhere), and it is also the
    /// whole of what a screen can read back — a type-back's answer is not reachable through
    /// it, so the words drawn are the words typed.
    #[must_use]
    pub fn word(&self, position: usize) -> Option<&'static str> {
        (position < self.slots && self.filled[position]).then(|| self.words[self.placed[position]])
    }

    /// The letters typed into the current slot so far.
    #[must_use]
    pub fn buffer(&self) -> &str {
        // Every byte in here came from a word in the list, and the list is ASCII by
        // constructor invariant, so this is infallible rather than defensive.
        core::str::from_utf8(&self.buffer[..self.len]).unwrap_or_default()
    }

    /// How many words the buffer can still become, and `0` before a letter is typed.
    #[must_use]
    pub fn matches(&self) -> usize {
        if self.len == 0 {
            return 0;
        }
        self.words
            .iter()
            .filter(|word| word.as_bytes().starts_with(self.prefix()))
            .count()
    }

    /// The rest of the single remaining word, for the screen to ghost inline after the
    /// buffer — or `""` while more than one word is still possible.
    ///
    /// It completes what is being typed and proposes nothing: behaviour 5 is that the
    /// appliance never offers a word the user did not reach on their own.
    #[must_use]
    pub fn ghost(&self) -> &'static str {
        if self.matches() != 1 {
            return "";
        }
        self.words
            .iter()
            .find(|word| word.as_bytes().starts_with(self.prefix()))
            .map_or("", |word| &word[self.len..])
    }

    /// How many slots hold a settled word.
    ///
    /// This is the progress an import screen reports — *fourteen words typed* — and it is
    /// deliberately not the same question as [`Self::can_finish`]: fourteen is a count and
    /// not a length.
    #[must_use]
    pub fn settled(&self) -> usize {
        self.filled
            .iter()
            .take(self.slots)
            .filter(|at| **at)
            .count()
    }

    /// The settled words as indices into the wordlist, written into `out`, and how many of
    /// them there are — or `None` for the run [`Self::length`] refuses.
    ///
    /// **What the user typed, and only that.** A type-back's answer is no more reachable
    /// through this than through [`Self::word`]: the indices are of the words that landed.
    #[must_use]
    pub fn indices(&self, out: &mut [u16; MAX_SLOTS]) -> Option<usize> {
        let count = self.settled();
        if !self.filled[..count].iter().all(|at| *at) {
            return None;
        }
        for (slot, &index) in out.iter_mut().zip(&self.placed[..count]) {
            // `as` rather than a fallible conversion: `open` refuses a wordlist longer than
            // `u16::MAX`, so every index this can hold already fits.
            *slot = index as u16;
        }
        Some(count)
    }

    /// Whether `⏎` has anything to do: the words settle into a phrase-shaped run, and its
    /// length is one this entry accepts.
    #[must_use]
    pub fn can_finish(&self) -> bool {
        self.length().is_some_and(|count| match self.lengths {
            Some(lengths) => lengths.contains(&count),
            None => count == self.slots,
        })
    }

    /// How many words the phrase would have if Done were pressed now, or `None` when the
    /// settled slots do not form a run from the first.
    ///
    /// Two halves, and each is a rule. The buffer counts as a word when it resolves and the
    /// slot it is going into is empty — which is what stops the last word of a phrase needing
    /// a space after it before Done unlocks. And **a slot filled past an empty one is a
    /// hole**: with twenty-four slots always drawn (behaviour 6), the arrow keys can reach
    /// slot 20 with eleven words typed, and eleven words plus one is not a twelve-word
    /// phrase.
    fn length(&self) -> Option<usize> {
        let pending = !self.filled[self.cursor] && self.resolve().is_some();
        let count = self.settled() + usize::from(pending);
        (0..count)
            .all(|position| self.filled[position] || (pending && position == self.cursor))
            .then_some(count)
    }

    /// The prefix being typed, as bytes.
    fn prefix(&self) -> &[u8] {
        &self.buffer[..self.len]
    }

    /// A keystroke lands only if some word continues the buffer with it (behaviour 3).
    ///
    /// **The byte that lands comes out of the wordlist, not out of the keystroke.** That is
    /// what makes this total without a fallible conversion: a key no word continues — a
    /// capital, a digit, a letter with a diacritic, anything outside Latin-1 — matches
    /// nothing and is refused by the same arm, and there is no second path into the buffer.
    ///
    /// The scan is also what keeps the write in bounds without a guard: a word *longer* than
    /// the buffer is what makes the byte at `len` writable at all, and the constructor
    /// already refused any word longer than [`MAX_WORD`].
    fn letter(&mut self, letter: char) -> Outcome {
        let landing = self.words.iter().find_map(|word| {
            let word = word.as_bytes();
            // `get` rather than an index: a word no longer than the buffer has no next byte
            // to offer, and that is the same answer as a word that offers a different one.
            let next = *word.get(self.len)?;
            (word[..self.len] == *self.prefix() && char::from(next) == letter).then_some(next)
        });
        let Some(byte) = landing else {
            return Outcome::Ignored;
        };
        self.buffer[self.len] = byte;
        self.len += 1;
        Outcome::Accepted
    }

    /// The word the buffer resolves to: an exact match, or a prefix that only one word has.
    ///
    /// The exact match has to win. `add` is a word and `address` continues it, so without
    /// that arm ten of the 2048 words could not be typed at all.
    fn resolve(&self) -> Option<usize> {
        if self.len == 0 {
            return None;
        }
        let mut unique = None;
        let mut count = 0usize;
        for (index, word) in self.words.iter().enumerate() {
            let word = word.as_bytes();
            if word == self.prefix() {
                return Some(index);
            }
            if word.starts_with(self.prefix()) {
                count += 1;
                unique = Some(index);
            }
        }
        (count == 1).then_some(unique).flatten()
    }

    /// Settle a resolved word into the current slot — **and, in a type-back, compare it.**
    ///
    /// The comparison is a byte compare of the two words against each other, not a check of
    /// their indices and not a checksum (`02-core.md` §4). It is core's because the shell
    /// must not branch on a validation outcome (standing rule 4), and it is *bytes* because
    /// that is the claim a later reader can check without knowing that two indices into one
    /// list are the same thing as two words.
    fn place(&mut self, index: usize) -> Outcome {
        let position = self.cursor;
        if self.known
            && self.words[index].as_bytes() != self.words[self.answer[position]].as_bytes()
        {
            self.drop_buffer();
            return Outcome::Wrong(position);
        }
        self.placed[position] = index;
        self.filled[position] = true;
        self.drop_buffer();
        Outcome::Accepted
    }

    /// Zeroize the buffer rather than just resetting its length: the bytes are a word of the
    /// phrase, and a length that no longer covers them is not the same as their absence.
    fn drop_buffer(&mut self) {
        self.buffer.zeroize();
        self.len = 0;
    }

    /// Space: settle the buffer and step to the next slot. A buffer that resolves to nothing
    /// stays exactly where it is — the screen already says how many words it still matches.
    fn commit(&mut self) -> Outcome {
        let Some(index) = self.resolve() else {
            return Outcome::Ignored;
        };
        let outcome = self.place(index);
        if outcome == Outcome::Accepted && self.cursor + 1 < self.slots {
            self.cursor += 1;
        }
        outcome
    }

    /// Backspace: a letter, or a step back that lifts the previous word out of its slot and
    /// back into the buffer **as editable text** (`02-core.md` §4's correction rule).
    fn back(&mut self) -> Outcome {
        if self.len > 0 {
            self.len -= 1;
            self.buffer[self.len] = 0;
            return Outcome::Accepted;
        }
        if self.cursor == 0 {
            return Outcome::Ignored;
        }
        self.cursor -= 1;
        if self.filled[self.cursor] {
            let word = self.words[self.placed[self.cursor]].as_bytes();
            self.buffer[..word.len()].copy_from_slice(word);
            self.len = word.len();
            self.filled[self.cursor] = false;
            self.placed[self.cursor] = 0;
        }
        Outcome::Accepted
    }

    /// An arrow key: **leaving a slot settles the buffer if it resolves and drops it if it
    /// does not.** A rejection keeps the cursor where the repair is, so the move does not
    /// happen.
    fn goto(&mut self, position: usize) -> Outcome {
        if position >= self.slots {
            return Outcome::Ignored;
        }
        if let Some(index) = self.resolve() {
            if let Outcome::Wrong(at) = self.place(index) {
                return Outcome::Wrong(at);
            }
        } else {
            self.drop_buffer();
        }
        self.cursor = position;
        Outcome::Accepted
    }

    /// `⏎` is Done: settle the last word, then say whether the phrase is whole.
    ///
    /// A buffer that resolves to nothing is *dropped* here rather than blocking Done, because
    /// finishing is leaving the slot and leaving a slot drops what does not resolve.
    fn finish(&mut self) -> Outcome {
        if !self.can_finish() {
            return Outcome::Ignored;
        }
        match self.resolve() {
            Some(index) => {
                if let Outcome::Wrong(at) = self.place(index) {
                    return Outcome::Wrong(at);
                }
            }
            None => self.drop_buffer(),
        }
        Outcome::Complete
    }
}

redacted!(Entry);

#[cfg(test)]
#[path = "entry_tests.rs"]
mod tests;
