//! The one mnemonic a load reads from, wherever it came from (04-screens.md §5).
//!
//! §5 is *one screen, always present, on every load path* — created, imported or restored —
//! and this is the half of that sentence the load screen cannot say for itself. Before it,
//! the phrase lived in `create.rs` and `load.rs` reached into that module for it, which was
//! true only for as long as creation was the only path there was. A second source would then
//! have meant a second reach and a branch choosing between them, on the one screen whose
//! whole argument is that it has no branches.
//!
//! So the slot is a value both writers hand a phrase to and the reader takes it from. Nothing
//! here decides anything: it holds a [`Mnemonic`] and answers two questions about it.
//!
//! **Not an `Rc<RefCell<Mnemonic>>` handed round bare, and not a `OnceLock`.** A closure
//! rather than an accessor, for the reason `Create` already gave and `Wallet::with_master`
//! before it: a phrase out by value is key material with a second lifetime to reason about.
//! And it is deliberately *replaceable* where [`crate::session::Session`] is not — ADR-0010
//! binds the **wallet** to the boot, not the phrase, and a user who escapes back to the start
//! menu and creates a second one has not loaded anything yet.

use std::cell::RefCell;

use aobs_core::bip39::Mnemonic;
use aobs_core::entry::Entry;

/// The phrase this session's load will derive from, or none yet.
pub struct Phrase {
    slot: RefCell<Option<Mnemonic>>,
}

impl Phrase {
    /// An empty slot: the state at boot, and on the start menu.
    pub fn new() -> Self {
        Self {
            slot: RefCell::new(None),
        }
    }

    /// Hand over a phrase. **The one it replaces is dropped here**, and so zeroized — which
    /// is what makes *create, escape, create again* leave one phrase in memory rather than
    /// two.
    pub fn set(&self, phrase: Mnemonic) {
        self.slot.replace(Some(phrase));
    }

    /// Run `f` over the phrase. `None` before one exists.
    pub fn with<T>(&self, f: impl FnOnce(&Mnemonic) -> T) -> Option<T> {
        self.slot.borrow().as_ref().map(f)
    }

    /// The retype's entry state: core's byte compare, already holding the answer
    /// (04-screens.md §4).
    ///
    /// Here rather than at the call site because the answer must not cross into the shell:
    /// what comes back is an [`Entry`] that holds the phrase and has no accessor that gives
    /// it back.
    pub fn type_back(&self) -> Option<Entry> {
        self.with(Mnemonic::type_back)
    }
}

#[cfg(test)]
mod tests {
    use super::Phrase;
    use aobs_core::bip39::Mnemonic;
    use aobs_core::secret::Entropy;

    fn generated(byte: u8) -> Mnemonic {
        Mnemonic::from_entropy(&Entropy::new(&[byte; 32]).expect("32 bytes")).expect("24 words")
    }

    #[test]
    fn an_empty_slot_answers_nothing() {
        let phrase = Phrase::new();
        assert!(phrase.with(|_| ()).is_none());
        assert!(phrase.type_back().is_none());
    }

    #[test]
    fn the_phrase_the_load_reads_is_the_last_one_handed_over() {
        // Which is what makes 04-screens.md §5's *one screen, every path* true of the
        // second path as well: import writes here and the load screen reads here, with no
        // arm anywhere choosing between two sources.
        let phrase = Phrase::new();
        phrase.set(generated(0));
        assert_eq!(phrase.with(|held| held.word(23)), Some(Some("art")));

        phrase.set(generated(0x5a));
        assert_ne!(phrase.with(|held| held.word(23)), Some(Some("art")));
    }

    #[test]
    fn the_retype_holds_the_answer_and_hands_back_no_words() {
        let phrase = Phrase::new();
        phrase.set(generated(0));
        let entry = phrase.type_back().expect("a phrase was handed over");
        assert_eq!(entry.slots(), 24);
        // The answer is in there — the compare needs it — and every slot is empty.
        assert_eq!(entry.word(0), None);
        assert_eq!(entry.settled(), 0);
    }
}
