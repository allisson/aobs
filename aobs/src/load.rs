//! Wallet load: the passphrase, the network, and the one screen both of them live on
//! (04-screens.md §5, `02-core.md` §5 and §6).
//!
//! **One screen, always present, on every load path.** It carries the two parameters that
//! enter at *derivation* rather than at generation, which is why there is no "creation vs
//! load" split to make: in BIP-39 the passphrase is not an input to mnemonic generation at
//! all, and neither is the network — a generated seed carries no network and neither does a
//! mnemonic.
//!
//! **The network sits above the passphrase**, and that order is forced: the confirm control's
//! label is a function of whether the passphrase field is empty, so the passphrase has to be
//! the last thing touched before confirming. A selector *below* it would be reached after the
//! label had already settled.
//!
//! **Clear text, always, no toggle.** Masking defends against a shoulder-surfer — a present
//! adversary the threat model explicitly declines to defend — so it would sell a defence we
//! have already declined and charge for it in the one currency that matters: an invisible typo
//! becomes a different, valid, empty wallet, discovered years later. Rendering is the
//! mitigation instead, which is what [`Typed::render`] is, and retyping is not: a user who
//! types a trailing space twice has confirmed nothing.
//!
//! **Nothing here judges the passphrase.** No meter, no minimum, no double entry, no lecture —
//! a passphrase is strictly additive over a 24-word mnemonic and therefore never worse than
//! none, and a signer with no rate limiting could not compensate for a weak one anyway. The
//! one line of copy that replaces all of it is on the screen, not in this file.

use std::cell::{Cell, RefCell};
use std::rc::Rc;

use aobs_core::derive::{Network, Wallet};
use aobs_core::secret::Passphrase;
use slint::ComponentHandle;
use zeroize::Zeroizing;

use crate::create::Create;
use crate::identity;
use crate::session::Session;
use crate::AppWindow;

/// The start delimiter, and the end one. **Explicit, and outside printable ASCII by
/// construction** (04-screens.md §5.1).
///
/// That is the whole reason they are these two code points rather than `[` and `]`: brackets are
/// themselves printable ASCII and so can be *inside* a passphrase this field accepts, which
/// would make the screen ambiguous about where the string starts and ends — the one thing the
/// delimiters exist to say. A guillemet cannot be typed here on any layout.
///
/// The retype's caret makes the same argument with a 2 px rule and no glyph at all; that is not
/// available here, because a rule cannot follow a string that *wraps*, and 128 characters at
/// the 800×600 floor wrap. Both of these are Latin-1 Supplement, which is the coverage floor of
/// any font that renders ASCII at all, so this leans on no glyph `fonts-dejavu` might lack.
const START: char = '«';
const END: char = '»';

/// What a space is drawn as. A space that looked like a space would be the invisible-typo
/// failure this screen exists to remove, and it is outside printable ASCII for the same reason
/// the delimiters are: `·` cannot be a character the user typed.
const SPACE_MARK: char = '·';

/// What one keystroke did. **A rejected keystroke says so** (04-screens.md §5.1), and these are
/// the only two ways one can be rejected.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Push {
    /// The byte is in the buffer.
    Accepted,
    /// Outside `0x20–0x7E`. The shell owns this restriction, not core: core takes arbitrary
    /// UTF-8 (BIP-39 in full), and what stops a non-ASCII passphrase here is that we render it
    /// for the user to verify and a font with CJK coverage is ~100 MiB against a 21 MiB stack.
    /// Drawing tofu boxes is worse than refusing. **Named cost: a user whose existing
    /// passphrase contains non-ASCII cannot enter it, and aobs cannot sign for that wallet.**
    NotAscii,
    /// The fixed 128-byte buffer is full. The cap is structural — growable secret types are
    /// forbidden (standing rule 5) — and 128 is above every mainstream wallet's own limit.
    Full,
}

/// The passphrase as the user is typing it: printable ASCII in a fixed 128-byte buffer.
///
/// Fixed rather than growable for standing rule 5's reason — a `Vec` that outgrows its capacity
/// copies itself and leaves the old contents where no `Zeroize` impl can reach them — and the
/// length is `Passphrase::CAPACITY` because that is the buffer this is on its way into.
struct Typed {
    bytes: Zeroizing<[u8; Passphrase::CAPACITY]>,
    len: usize,
}

impl Typed {
    /// An empty field. Allocated at full size up front, which is what the fixed cap means.
    fn new() -> Self {
        Self {
            bytes: Zeroizing::new([0u8; Passphrase::CAPACITY]),
            len: 0,
        }
    }

    /// One keystroke, appended. **Never trimmed** — `"hunter2 "` and `"hunter2"` are different
    /// wallets, BIP-39 defines no trimming rule, and trimming ourselves would silently disagree
    /// with every other implementation on the same input.
    fn push(&mut self, key: char) -> Push {
        if !(key == ' ' || key.is_ascii_graphic()) {
            return Push::NotAscii;
        }
        if self.len == Passphrase::CAPACITY {
            return Push::Full;
        }
        self.bytes[self.len] = key as u8;
        self.len += 1;
        Push::Accepted
    }

    /// Backspace. The only correction this field has, because the only cursor it has is the end.
    fn pop(&mut self) {
        if self.len > 0 {
            self.len -= 1;
            self.bytes[self.len] = 0;
        }
    }

    /// The characters typed so far, which is what the count on screen reports.
    fn len(&self) -> usize {
        self.len
    }

    /// Spent, once the wallet is derived: the passphrase cannot be changed mid-session
    /// (`02-core.md` §5, §12), so there is nothing left for the buffer to hold.
    fn clear(&mut self) {
        self.bytes.fill(0);
        self.len = 0;
    }

    /// The bytes as they were typed, for core.
    ///
    /// Always valid UTF-8: every byte in the buffer came through [`Self::push`], which accepts
    /// `0x20–0x7E` and nothing else.
    fn as_str(&self) -> &str {
        std::str::from_utf8(&self.bytes[..self.len]).expect("printable ASCII is UTF-8")
    }

    /// The field as it is drawn: **explicit start and end delimiters, and every space a visible
    /// mark** (04-screens.md §5.1).
    ///
    /// The `Zeroizing` is what this module can promise. The copy Slint then holds — and the one
    /// in the frame buffer after it — is not zeroized, which is the same trade `create.rs` names
    /// for the 24 words: a passphrase the user has to be able to read is a passphrase on screen.
    fn render(&self) -> Zeroizing<String> {
        let mut out = String::with_capacity(Passphrase::CAPACITY + 2);
        out.push(START);
        for &byte in &self.bytes[..self.len] {
            out.push(if byte == b' ' {
                SPACE_MARK
            } else {
                char::from(byte)
            });
        }
        out.push(END);
        Zeroizing::new(out)
    }
}

/// The load screen's state: what has been typed, and which of the two networks is chosen.
pub struct Load {
    typed: RefCell<Typed>,
    /// **Mainnet preselected, and the choice is not forced** (`02-core.md` §6): a forced pick on
    /// a 95/5 split is a click-through trainer on the screen where that is most expensive, and
    /// the state it would create — an inattentive rehearser on mainnet — is self-limiting,
    /// because signing needs coins and a rehearser has none there.
    network: Cell<Network>,
    /// Where the phrase is, behind a closure that never hands it out.
    create: Rc<Create>,
    /// Where the wallet goes, once.
    session: Rc<Session>,
}

/// Wire the three callbacks that carry a value rather than an intent.
///
/// They bypass the router for the reason a die face and a letter of the retype do (standing rule
/// 4): a character of the passphrase and a network selection are values, and the router's whole
/// claim is that no arm of it inspects one.
pub fn wire(ui: &AppWindow, create: Rc<Create>, session: Rc<Session>) -> Rc<Load> {
    let load = Rc::new(Load {
        typed: RefCell::new(Typed::new()),
        network: Cell::new(Network::Mainnet),
        create,
        session,
    });

    // The screen's initial state, set here rather than defaulted in the `.slint` file, so
    // mainnet-preselected is one fact in one place — and so that **an empty field draws its two
    // delimiters** rather than nothing at all: a field whose delimiters appeared with the first
    // keystroke would say nothing about where an empty string starts and ends, which is the one
    // case 04-screens.md §5.1's confirm label exists to keep separate from a deliberate one.
    ui.set_network_testnet(false);
    load.draw(ui, "");

    let handle = ui.as_weak();
    let owner = load.clone();
    ui.on_network(move |testnet| {
        if let Some(ui) = handle.upgrade() {
            owner.choose(&ui, testnet);
        }
    });

    let handle = ui.as_weak();
    let owner = load.clone();
    ui.on_passphrase_typed(move |text| {
        if let Some(ui) = handle.upgrade() {
            owner.typed(&ui, &text);
        }
    });

    let handle = ui.as_weak();
    let owner = load.clone();
    ui.on_passphrase_back(move || {
        if let Some(ui) = handle.upgrade() {
            owner.back(&ui);
        }
    });

    load
}

impl Load {
    /// §5.2's two-state selector. Two states and not three: nothing in a key, an address or a
    /// descriptor distinguishes testnet from signet.
    fn choose(&self, ui: &AppWindow, testnet: bool) {
        self.network.set(if testnet {
            Network::Testnet
        } else {
            Network::Mainnet
        });
        ui.set_network_testnet(testnet);
    }

    /// One keystroke.
    fn typed(&self, ui: &AppWindow, text: &str) {
        let mut keys = text.chars();
        let (Some(key), None) = (keys.next(), keys.next()) else {
            return;
        };
        if !nameable(key) {
            return;
        }
        let push = self.typed.borrow_mut().push(key);
        self.draw(ui, &note(key, push));
    }

    /// Backspace.
    fn back(&self, ui: &AppWindow) {
        self.typed.borrow_mut().pop();
        self.draw(ui, "");
    }

    /// Derive the wallet and hand the session its one wallet (04-screens.md §5, §7).
    ///
    /// **This is the only place a wallet comes into existence.** It reads a passphrase and a
    /// network the user set, hands both to core with the phrase, and shows what came back —
    /// there is no validation outcome here to branch on.
    pub fn confirm(&self, ui: &AppWindow) {
        let network = self.network.get();
        let wallet = {
            let typed = self.typed.borrow();
            // Cannot be `None`: at most 128 bytes of printable ASCII, over which NFKD is the
            // identity, so the normalised form is the same 128 bytes. A wrong belief here
            // unwinds into 06-codes.md §5's `AOBS-E04` rather than becoming a branch no test
            // can take.
            let passphrase = Passphrase::new(typed.as_str())
                .expect("128 printable ASCII bytes are their own NFKD form");
            self.create
                .with_phrase(|phrase| Wallet::load(phrase, &passphrase, network))
        };
        let Some(wallet) = wallet else {
            return;
        };

        // Spent (`02-core.md` §5, §12): there is no re-derivation path and the passphrase cannot
        // change mid-session, so the buffer and the copy on screen both go now rather than
        // waiting for the session to end.
        self.typed.borrow_mut().clear();
        self.draw(ui, "");

        // ADR-0010. A second `set` returns `Err` and the wallet it refuses is dropped — and so
        // zeroized — right here. Nothing routes to this screen twice, so the `Err` is the
        // enforcement standing behind that routing rather than a case with a screen.
        let _ = self.session.load(wallet);
        if let Some(wallet) = self.session.wallet() {
            identity::show(ui, wallet);
        }
    }

    /// Push the field onto the screen. An empty `note` leaves the standing count line in place.
    fn draw(&self, ui: &AppWindow, note: &str) {
        let (rendered, count) = {
            let typed = self.typed.borrow();
            (
                typed.render(),
                i32::try_from(typed.len()).unwrap_or_default(),
            )
        };
        // The borrow ends before a single property is set, for the reason `create.rs` gives: a
        // `RefCell` still held across a Slint property change is the shape that panics the day
        // something re-enters here.
        ui.set_passphrase(rendered.as_str().into());
        ui.set_passphrase_count(count);
        ui.set_passphrase_note(note.into());
    }
}

/// Whether a key that did not land can be *named* on screen.
///
/// Slint delivers named keys — F1, Home, the media keys — as private-use code points, and a key
/// with no printable form has no name to report either: naming it would be a screen quoting a
/// character the user cannot see (standing rule 8). Those are dropped silently, the same call
/// `confirm.rs` makes. A key that *does* have a form and is still outside printable ASCII is
/// named, which is 04-screens.md §5.1's *a rejected keystroke says so*.
fn nameable(key: char) -> bool {
    !key.is_control() && !('\u{e000}'..='\u{f8ff}').contains(&key)
}

/// What the live line says about the keystroke that just ran, or `""` for one that landed.
fn note(key: char, push: Push) -> String {
    match push {
        Push::Accepted => String::new(),
        Push::NotAscii => format!("“{key}” did nothing: printable ASCII only."),
        Push::Full => format!("“{key}” did nothing: 128 characters is the limit."),
    }
}

#[cfg(test)]
mod tests {
    use super::{nameable, note, Push, Typed, END, SPACE_MARK, START};
    use aobs_core::secret::Passphrase;

    fn typed(text: &str) -> Typed {
        let mut buffer = Typed::new();
        for key in text.chars() {
            assert_eq!(buffer.push(key), Push::Accepted, "{key}");
        }
        buffer
    }

    #[test]
    fn an_empty_field_is_two_delimiters_and_nothing_between_them() {
        let buffer = Typed::new();
        assert_eq!(buffer.len(), 0);
        assert_eq!(buffer.render().as_str(), format!("{START}{END}"));
    }

    #[test]
    fn what_was_typed_is_what_is_drawn() {
        assert_eq!(
            typed("hunter2").render().as_str(),
            format!("{START}hunter2{END}")
        );
    }

    /// Every space is a visible mark, wherever it is — which is the whole of the defence against
    /// the invisible typo, since this field is never masked and never retyped.
    #[test]
    fn spaces_are_drawn_as_a_mark_at_both_ends_and_in_the_middle() {
        let drawn = typed(" a b ").render();
        assert_eq!(
            drawn.as_str(),
            format!("{START}{SPACE_MARK}a{SPACE_MARK}b{SPACE_MARK}{END}")
        );
        // Two adjacent spaces are two marks, so a double space is not a single one.
        assert_eq!(
            typed("a  b").render().as_str(),
            format!("{START}a{SPACE_MARK}{SPACE_MARK}b{END}")
        );
    }

    /// **Never trimmed** (`02-core.md` §5): the bytes handed to core are the bytes typed, and
    /// the three passphrases below are three different wallets. Core proves they derive three
    /// different seeds; this proves the shell does not flatten them before core sees them.
    #[test]
    fn nothing_is_trimmed_on_the_way_to_core() {
        for text in ["a", " a", "a ", " a ", "  "] {
            assert_eq!(typed(text).as_str(), text);
        }
    }

    /// The delimiters and the space mark are all outside printable ASCII, so none of them can
    /// be a character the user typed. That is what makes the render unambiguous.
    #[test]
    fn no_mark_this_field_draws_is_a_character_it_accepts() {
        for mark in [START, END, SPACE_MARK] {
            assert!(!mark.is_ascii(), "{mark}");
            let mut buffer = Typed::new();
            assert_eq!(buffer.push(mark), Push::NotAscii, "{mark}");
            assert_eq!(buffer.len(), 0);
        }
    }

    /// The whole printable-ASCII range lands, and it is exactly 95 characters — which is the
    /// number the pinned `us` keymap has to reach for offering no layout picker to be honest
    /// (04-screens.md §5.1).
    #[test]
    fn all_ninety_five_printable_ascii_characters_land() {
        let all: String = (0x20u8..=0x7e).map(char::from).collect();
        assert_eq!(all.chars().count(), 95);
        assert_eq!(typed(&all).as_str(), all);
    }

    /// The cap is structural and it is 128 (`02-core.md` §5): **128 accepted, 129 refused.**
    #[test]
    fn the_hundred_and_twenty_eighth_lands_and_the_hundred_and_twenty_ninth_does_not() {
        let mut buffer = Typed::new();
        for at in 0..Passphrase::CAPACITY {
            assert_eq!(buffer.push('x'), Push::Accepted, "at {at}");
        }
        assert_eq!(buffer.len(), Passphrase::CAPACITY);
        assert_eq!(buffer.push('x'), Push::Full);
        assert_eq!(buffer.len(), Passphrase::CAPACITY);
        // And the buffer core receives is exactly the 128 that landed.
        assert_eq!(buffer.as_str().len(), Passphrase::CAPACITY);
        assert!(Passphrase::new(buffer.as_str()).is_some());
    }

    /// A refused keystroke changes nothing, which is the other half of *it says so*: the field
    /// the user is reading is still the field they typed.
    #[test]
    fn a_refused_keystroke_leaves_the_field_alone() {
        let mut buffer = typed("hunter2");
        assert_eq!(buffer.push('é'), Push::NotAscii);
        assert_eq!(buffer.push('\u{e000}'), Push::NotAscii);
        assert_eq!(buffer.as_str(), "hunter2");
        assert_eq!(buffer.len(), 7);
    }

    #[test]
    fn backspace_removes_one_character_and_an_empty_field_survives_it() {
        let mut buffer = typed("ab");
        buffer.pop();
        assert_eq!(buffer.as_str(), "a");
        buffer.pop();
        assert_eq!(buffer.as_str(), "");
        buffer.pop();
        assert_eq!(buffer.as_str(), "");
        assert_eq!(buffer.len(), 0);
    }

    /// A backspaced byte is not left behind for the next `as_str` window to expose.
    #[test]
    fn backspace_wipes_the_byte_it_dropped() {
        let mut buffer = typed("ab");
        buffer.pop();
        buffer.push('c');
        assert_eq!(buffer.as_str(), "ac");
    }

    #[test]
    fn clearing_leaves_nothing_and_draws_as_empty() {
        let mut buffer = typed("hunter2 ");
        buffer.clear();
        assert_eq!(buffer.len(), 0);
        assert_eq!(buffer.as_str(), "");
        assert_eq!(buffer.render().as_str(), format!("{START}{END}"));
    }

    #[test]
    fn only_a_key_with_a_printable_form_is_named() {
        assert!(nameable('é'));
        assert!(nameable(' '));
        assert!(nameable('x'));
        // Slint's named keys, and the control characters.
        assert!(!nameable('\u{e000}'));
        assert!(!nameable('\u{f8ff}'));
        assert!(!nameable('\u{7}'));
    }

    #[test]
    fn a_keystroke_that_landed_says_nothing() {
        assert_eq!(note('x', Push::Accepted), "");
    }

    #[test]
    fn a_refusal_names_the_key_and_the_reason() {
        assert_eq!(
            note('é', Push::NotAscii),
            "“é” did nothing: printable ASCII only."
        );
        assert_eq!(
            note('x', Push::Full),
            "“x” did nothing: 128 characters is the limit."
        );
    }
}
