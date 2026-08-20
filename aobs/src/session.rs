//! One wallet per boot (`02-core.md` §12, ADR-0010).
//!
//! **The whole property is the [`OnceLock`] below, and the enforcement and the test are the
//! same mechanism: a second `set` returns `Err`.** Core is stateless pure functions and has no
//! wallet to replace, so this lives in the shell — and it is the only wallet-shaped state the
//! appliance has.
//!
//! There is no `take`, no `replace`, no `unload` and no idle timeout, because the type offers
//! none of them: *"there is no second wallet"* is a type-level fact rather than an assertion
//! a test has to keep watching. Any switch boundary would rest on a correctness property the
//! suite has already conceded it cannot verify (standing rule 9 — we do not claim a test
//! observes a freed page); reboot-to-switch replaces that promise with a power cycle plus
//! `init_on_free=1`, which is what [`crate::router::Ending::Restart`] delivers.
//!
//! **Deliberately not a `static`.** A `static` is never dropped, so the wallet's wrapped
//! master key would never be zeroized and 01-boot-layer.md §5's wipe would rest on
//! `init_on_free` alone. This is held for the lifetime of `run()` and dies with it, before
//! `main` exits into the shutdown status.

use std::sync::OnceLock;

use aobs_core::derive::Wallet;

/// The session's one wallet slot.
pub struct Session {
    wallet: OnceLock<Wallet>,
}

impl Session {
    /// An empty session. Called once, from `run`.
    pub fn new() -> Self {
        Self {
            wallet: OnceLock::new(),
        }
    }

    /// Load the wallet, or hand it straight back if one is already loaded.
    ///
    /// The `Err` **is** ADR-0010, and the wallet it carries is dropped — and so zeroized — by
    /// the caller that ignores it. Nothing in the appliance routes to the load screen twice,
    /// so this is the enforcement standing behind that routing rather than a case with a
    /// screen of its own.
    ///
    /// `result_large_err` is allowed rather than obeyed: this **is** [`OnceLock::set`]'s own
    /// signature, and the wallet travelling back by value is the mechanism, not an oversight.
    /// Clippy's remedy — `Box<Wallet>` — would map the refusal through a heap allocation and put
    /// a second copy of the key material there on the one path where the point is that it dies
    /// immediately.
    #[allow(clippy::result_large_err)]
    pub fn load(&self, wallet: Wallet) -> Result<(), Wallet> {
        self.wallet.set(wallet)
    }

    /// The loaded wallet, or `None` before a load.
    pub fn wallet(&self) -> Option<&Wallet> {
        self.wallet.get()
    }

    /// Whether a wallet exists. What the router asks to know where Escape goes: once a wallet
    /// is loaded there is no start menu to return to (04-screens.md §13).
    pub fn loaded(&self) -> bool {
        self.wallet.get().is_some()
    }
}

#[cfg(test)]
mod tests {
    use super::Session;
    use aobs_core::bip39::Mnemonic;
    use aobs_core::derive::{Network, Wallet};
    use aobs_core::secret::{Entropy, Passphrase};

    fn wallet(network: Network) -> Wallet {
        let mnemonic =
            Mnemonic::from_entropy(&Entropy::new(&[0u8; 32]).expect("32 bytes")).expect("24 words");
        Wallet::load(
            &mnemonic,
            &Passphrase::new("").expect("empty fits"),
            network,
        )
    }

    #[test]
    fn an_empty_session_holds_nothing() {
        let session = Session::new();
        assert!(!session.loaded());
        assert!(session.wallet().is_none());
    }

    #[test]
    fn the_first_load_lands() {
        let session = Session::new();
        assert!(session.load(wallet(Network::Mainnet)).is_ok());
        assert!(session.loaded());
        assert_eq!(
            session.wallet().map(Wallet::network),
            Some(Network::Mainnet)
        );
    }

    /// ADR-0010, as the mechanism rather than as a promise: **the second `set` returns
    /// `Err`**, and the wallet it refused is handed back to be dropped.
    #[test]
    fn a_second_load_returns_err_and_the_first_wallet_stands() {
        let session = Session::new();
        assert!(session.load(wallet(Network::Mainnet)).is_ok());

        let refused = session.load(wallet(Network::Testnet));
        assert!(refused.is_err(), "a second wallet must be refused");
        // And it is refused *without* replacing the first: the network the session reports is
        // still the one it was loaded with, which is the observable half of the guarantee.
        assert_eq!(
            session.wallet().map(Wallet::network),
            Some(Network::Mainnet)
        );

        // The refused wallet comes back so the caller drops it. Dropping it here is what
        // zeroizes its wrapped master key.
        drop(refused);
    }
}
