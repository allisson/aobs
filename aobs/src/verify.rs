//! Receive-address verification: the verdict a completed address scan lands on
//! (`04-screens.md` §12, `02-core.md` §10).
//!
//! **Core searches; this states the answer.** `Wallet::find_address` owns §10's four
//! normalization steps and the 8,000-derivation window, and every fact on either screen comes
//! back typed from it — the family, the branch, the index, the path and *our* address. Nothing
//! below compares a string, strips a prefix or decides what *yours* means.
//!
//! **The scanned string never reaches a screen.** It is attacker-controlled text and there is
//! nothing on either verdict a user could do with it that they cannot do with the address in
//! their other hand — which is the Coldcard 2019 lesson applied one screen over: the review
//! screen was the vulnerability. What the positive verdict draws is the address *we derived*,
//! which for a shouted bech32 QR is a different string from the one that arrived.
//!
//! **Nothing here is originated.** §10 cut origination — index in, address and QR out — because
//! the bypass does not bypass anything: an originated address still reaches the payer through
//! the user's online machine, where it is altered exactly as before. So this module has no way
//! to produce an address and no reason to want one.

use std::rc::Rc;
use std::time::Instant;

use aobs_core::derive::{Branch, Family, Found, Wallet, SEARCH_INDICES, SEARCH_WINDOW};

use crate::review::Landed;
use crate::session::Session;
use crate::{console, identity, AppWindow, Screen};

/// Unreachable by navigation, and stated rather than unwrapped: §7's hub is the only door to an
/// address scan and the hub does not exist until a wallet does (ADR-0010). The same sentence
/// [`crate::review`] carries for the same reason, narrowed to what this screen was going to
/// check.
const NO_WALLET: &str = "No wallet is loaded, so there is nothing to check this against.";

/// §12's subordinate line, and it is the whole of the negative verdict's honesty.
///
/// A `None` from the search cannot mean *not yours*; it means *not in what I searched*. The
/// headline does not hedge — a hedged headline invites treating an unmatched address as safe,
/// which is the failure this feature exists to prevent — so the window is stated here instead,
/// in full: every account, both branches, and the index range **read off the constant the search
/// actually walked**. If `05-testing-and-release.md` §6.4's fallback is ever taken and the window
/// narrows, this sentence narrows with it rather than becoming a lie.
///
/// **Nothing here counts the accounts in words.** *"all four"* would be a number this sentence
/// asserts and `Family::ALL` supplies — one that a fifth family would turn into a lie here while
/// every `match` in core failed to compile, which is the wrong way round. The paths are listed,
/// which says how many there are without claiming it.
fn searched(wallet: &Wallet) -> String {
    let accounts: Vec<String> = Family::ALL
        .iter()
        .map(|family| identity::notation(&wallet.account_path(*family)))
        .collect();
    // `split_last` rather than two index expressions: the list is `Family::ALL`'s length, and a
    // sentence about the search must not be the one thing in this file that can panic.
    let (last, rest) = accounts
        .split_last()
        .expect("Family::ALL is not empty, and the product derives all of it");

    format!(
        "Searched every account — {}{}{} — on both the receive and the change branch, at indices \
         0 to {}. An address beyond that window, or from a different seed, passphrase or network, \
         would not be found here either.",
        rest.join(", "),
        if rest.is_empty() { "" } else { " and " },
        last,
        SEARCH_INDICES - 1,
    )
}

/// Which branch, in the words §12 puts on the screen.
///
/// Two names for core's two variants, and the BIP-44 word beside the plain one because a
/// coordinator says *change* and a descriptor says `/1/`. A third arm would be a compile error
/// here rather than a row that quietly said nothing.
fn branch(branch: Branch) -> &'static str {
    match branch {
        Branch::Receive => "receive (external)",
        Branch::Change => "change (internal)",
    }
}

/// The search's own cost, as the console line `05-testing-and-release.md` §6.4's owed
/// measurement is read off.
///
/// **`matched` is what makes the number interpretable.** A match returns on the first hit, so
/// only `matched=no` is the full [`SEARCH_WINDOW`] — the worst case, and the one the owed
/// measurement is about. `window` is that constant rather than a count of what was walked, which
/// is why the two fields have to be read together. It comes from core, because how many
/// derivations a search performs is a fact about the search and not arithmetic for a shell to
/// redo over three of core's constants.
///
/// Nothing secret rides here: a count, a duration and a verdict the user is already looking at
/// (01-boot-layer.md §9 — fixed strings and typed names, never formatted program state).
fn timing(matched: bool, started: &Instant) -> String {
    format!(
        "AOBS_SEARCH window={SEARCH_WINDOW} matched={} elapsed-ms={}",
        if matched { "yes" } else { "no" },
        started.elapsed().as_millis(),
    )
}

/// §12's flow: it holds the session and nothing else, because a verdict is not state.
pub struct Verify {
    session: Rc<Session>,
}

/// Build it. No callback: both screens' one row is an intent, and the router is where intents
/// land.
pub fn wire(session: Rc<Session>) -> Rc<Verify> {
    Rc::new(Verify { session })
}

impl Verify {
    /// A completed address scan. **Core answers; this shows whichever screen its answer names.**
    ///
    /// [`Landed`] is the scanning screen's own vocabulary, shared with [`crate::review`] because
    /// the question is the same one: did a screen go up, or is the camera still live. The one
    /// arm that leaves it live here is the unreachable no-wallet case.
    pub fn arrived(&self, ui: &AppWindow, candidate: &str) -> Landed {
        let Some(wallet) = self.session.wallet() else {
            return Landed::Scanning(NO_WALLET);
        };

        let started = Instant::now();
        let found = wallet.find_address(candidate);
        console::emit(&timing(found.is_some(), &started));

        match found {
            Some(found) => self.matched(ui, &found),
            None => {
                ui.set_verify_searched(searched(wallet).into());
                ui.set_screen(Screen::NotYours);
            }
        }

        Landed::Shown
    }

    /// §12's positive verdict, from the typed answer and nothing else.
    fn matched(&self, ui: &AppWindow, found: &Found) {
        ui.set_verify_path(identity::notation(&found.path).into());
        ui.set_verify_branch(branch(found.branch).into());
        ui.set_verify_index(found.index.to_string().into());
        ui.set_verify_groups(crate::review::address(&found.address));
        ui.set_screen(Screen::Verified);
    }
}

#[cfg(test)]
mod tests {
    use super::{branch, searched, timing};
    use aobs_core::bip39::Mnemonic;
    use aobs_core::derive::{Branch, Family, Network, Wallet, SEARCH_INDICES, SEARCH_WINDOW};
    use aobs_core::secret::{Entropy, Passphrase};
    use std::time::Instant;

    fn wallet(network: Network) -> Wallet {
        let mnemonic =
            Mnemonic::from_entropy(&Entropy::new(&[0u8; 32]).expect("32 bytes")).expect("24 words");
        Wallet::load(
            &mnemonic,
            &Passphrase::new("").expect("empty fits"),
            network,
        )
    }

    /// §12: *a subordinate line naming precisely what was searched — account path, both
    /// branches, indices 0–999.* All three, and the paths are the loaded network's.
    #[test]
    fn the_negative_verdict_names_every_account_both_branches_and_the_window() {
        let sentence = searched(&wallet(Network::Mainnet));

        for family in Family::ALL {
            let path = super::identity::notation(&wallet(Network::Mainnet).account_path(family));
            assert!(sentence.contains(&path), "{path} missing from {sentence}");
        }
        assert!(sentence.contains("receive"), "{sentence}");
        assert!(sentence.contains("change"), "{sentence}");
        assert!(sentence.contains("0 to 999"), "{sentence}");
        // The count is shown by listing rather than claimed in words, so a fifth family could
        // never make this sentence say the wrong number.
        assert!(!sentence.contains("four"), "{sentence}");
    }

    /// The window in the sentence is the window the search walked, not a literal typed twice.
    #[test]
    fn the_window_in_the_sentence_is_the_constant_the_search_used() {
        let sentence = searched(&wallet(Network::Mainnet));
        assert!(
            sentence.contains(&format!("indices 0 to {}", SEARCH_INDICES - 1)),
            "{sentence}"
        );
    }

    /// A testnet session states testnet paths, because the accounts are the loaded network's
    /// (ADR-0015) — and a sentence naming mainnet paths on a testnet wallet would describe a
    /// search that did not happen.
    #[test]
    fn a_testnet_session_names_its_own_coin_type() {
        let sentence = searched(&wallet(Network::Testnet));
        assert!(sentence.contains("84h/1h/0h"), "{sentence}");
        assert!(!sentence.contains("84h/0h/0h"), "{sentence}");
    }

    /// No path on any screen carries an apostrophe (`identity::notation`), including these.
    #[test]
    fn no_path_in_the_sentence_carries_an_apostrophe() {
        assert!(!searched(&wallet(Network::Mainnet)).contains('\''));
    }

    #[test]
    fn the_two_branches_have_two_distinct_names() {
        assert_ne!(branch(Branch::Receive), branch(Branch::Change));
        assert!(branch(Branch::Receive).contains("receive"));
        assert!(branch(Branch::Change).contains("change"));
    }

    /// The console line's `window` is the product §10 names — 4 accounts × 2 branches × 1000
    /// indices — and `matched` is what says whether that window was actually walked.
    #[test]
    fn the_timing_line_carries_the_window_and_whether_it_was_walked() {
        let started = Instant::now();
        let missed = timing(false, &started);
        assert_eq!(SEARCH_WINDOW, 8_000);
        assert!(missed.starts_with("AOBS_SEARCH window=8000 matched=no elapsed-ms="));
        assert!(timing(true, &started).contains(" matched=yes "));
    }
}
