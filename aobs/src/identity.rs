//! The identity screen: the hub every load lands on (04-screens.md §7).
//!
//! Four facts are always in view — **master fingerprint, network, script type, and whether a
//! passphrase is in use** — and all four come off the loaded [`Wallet`] rather than out of
//! anything this module knows. What is here is the presentation: the two names each of core's
//! four families carries on screen, and the notation derivation paths are written in.
//!
//! **The network line is the whole of the network signal.** The master fingerprint is
//! byte-identical on both networks (`02-core.md` §6, asserted in `derive_tests.rs`), so it
//! catches a passphrase typo and cannot catch a network mistake. That is why the copy states
//! the network **in both directions and never as an absence** — a screen that said nothing
//! when the network was mainnet would make *"no line"* mean *"mainnet"*, which is a fact
//! carried by the absence of a fact.

use aobs_core::bitcoin::bip32::DerivationPath;
use aobs_core::derive::{Family, Network, Wallet};
use slint::{ModelRc, VecModel};

use crate::{Account, AppWindow, Screen};

/// Push the four facts onto the screen and show it.
pub fn show(ui: &AppWindow, wallet: &Wallet) {
    ui.set_fingerprint(fingerprint(wallet).into());
    ui.set_wallet_testnet(wallet.network() == Network::Testnet);
    ui.set_passphrase_in_use(wallet.passphrase_in_use());
    ui.set_accounts(ModelRc::new(VecModel::from(accounts(wallet))));
    ui.set_screen(Screen::Identity);
}

/// The 4-byte master fingerprint, as the eight hex digits a coordinator shows beside it.
///
/// Not grouped: `04-screens.md` §0's 4-character rule is about *addresses*, which are compared
/// one character at a time against a screen somewhere else. Eight digits are read whole.
fn fingerprint(wallet: &Wallet) -> String {
    wallet.fingerprint().to_string()
}

/// The four accounts, in [`Family::ALL`]'s order — which is the order the watch-only export
/// lists them in too, so the two screens never disagree about which one is which.
fn accounts(wallet: &Wallet) -> Vec<Account> {
    Family::ALL
        .map(|family| Account {
            family: label(family).into(),
            script: script_type(family).into(),
            path: path(wallet, family).into(),
        })
        .to_vec()
}

/// Which BIP the account is.
fn label(family: Family) -> &'static str {
    match family {
        Family::Bip44 => "BIP 44",
        Family::Bip49 => "BIP 49",
        Family::Bip84 => "BIP 84",
        Family::Bip86 => "BIP 86",
    }
}

/// Its script type, which is the fact §7 names. One string per family, because a family *is* a
/// purpose and a script type together (`02-core.md` §6) and neither is offered as a choice.
fn script_type(family: Family) -> &'static str {
    match family {
        Family::Bip44 => "P2PKH",
        Family::Bip49 => "P2SH-P2WPKH",
        Family::Bip84 => "P2WPKH",
        Family::Bip86 => "P2TR",
    }
}

/// The account path, in the notation this product writes paths in.
fn path(wallet: &Wallet, family: Family) -> String {
    notation(&wallet.account_path(family))
}

/// Any derivation path, in the notation this product writes paths in: `h` for hardened, not
/// `'`.
///
/// That is what `04-screens.md` §8's own descriptor example uses — `[9c1f4e02/84h/0h/0h]` — and
/// an apostrophe is the character a monospace line of hex and digits loses most easily. The
/// dependency prints `'`, so the substitution happens here rather than being a fact about
/// `bitcoin`'s `Display` that a version bump could change under us.
///
/// **One function rather than one per screen.** §11.2's change label states the path a change
/// output was re-derived at, and a panel writing `84'/0'/0'/1/7` beside a hub writing
/// `84h/0h/0h` would be two answers to a question the user is trying to match up.
pub fn notation(path: &DerivationPath) -> String {
    path.to_string().replace('\'', "h")
}

#[cfg(test)]
mod tests {
    use super::{accounts, fingerprint, path, script_type};
    use aobs_core::bip39::Mnemonic;
    use aobs_core::derive::{Family, Network, Wallet};
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
    fn the_fingerprint_is_eight_lowercase_hex_digits() {
        let shown = fingerprint(&wallet(Network::Mainnet));
        assert_eq!(shown.len(), 8, "{shown}");
        assert!(
            shown
                .chars()
                .all(|c| c.is_ascii_hexdigit() && !c.is_ascii_uppercase()),
            "{shown}"
        );
    }

    /// The identity screen's only network signal is the network line, because this holds
    /// (`02-core.md` §6). Core asserts it against the dependency; this asserts that the screen
    /// does not accidentally acquire a second signal by showing the fingerprint.
    #[test]
    fn the_fingerprint_is_the_same_on_both_networks() {
        assert_eq!(
            fingerprint(&wallet(Network::Mainnet)),
            fingerprint(&wallet(Network::Testnet))
        );
    }

    #[test]
    fn all_four_families_are_listed_in_core_s_own_order() {
        let rows = accounts(&wallet(Network::Mainnet));
        assert_eq!(rows.len(), Family::ALL.len());
        let scripts: Vec<&str> = rows.iter().map(|row| row.script.as_str()).collect();
        assert_eq!(scripts, ["P2PKH", "P2SH-P2WPKH", "P2WPKH", "P2TR"]);
        assert_eq!(rows[0].family, "BIP 44");
        assert_eq!(rows[3].family, "BIP 86");
    }

    #[test]
    fn the_four_script_types_are_four_distinct_names() {
        let mut seen: Vec<&str> = Family::ALL.iter().copied().map(script_type).collect();
        seen.sort_unstable();
        seen.dedup();
        assert_eq!(seen.len(), Family::ALL.len());
    }

    /// The coin type is the network's, and it is the only thing in the path that moves — which
    /// is what makes a testnet session's paths readable as testnet paths.
    #[test]
    fn the_coin_type_follows_the_loaded_network() {
        let mainnet = wallet(Network::Mainnet);
        let testnet = wallet(Network::Testnet);
        assert!(
            path(&mainnet, Family::Bip84).contains("84h/0h/0h"),
            "{}",
            path(&mainnet, Family::Bip84)
        );
        assert!(
            path(&testnet, Family::Bip84).contains("84h/1h/0h"),
            "{}",
            path(&testnet, Family::Bip84)
        );
    }

    #[test]
    fn no_path_carries_an_apostrophe() {
        let loaded = wallet(Network::Mainnet);
        for family in Family::ALL {
            let shown = path(&loaded, family);
            assert!(!shown.contains('\''), "{shown}");
            assert!(shown.contains('h'), "{shown}");
        }
    }

    #[test]
    fn the_four_paths_differ_only_in_the_purpose() {
        let loaded = wallet(Network::Mainnet);
        for (family, purpose) in Family::ALL.iter().zip(["44h", "49h", "84h", "86h"]) {
            assert!(
                path(&loaded, *family).contains(&format!("{purpose}/0h/0h")),
                "{}",
                path(&loaded, *family)
            );
        }
    }

    /// The account index is `0` and is not a parameter anywhere (`02-core.md` §6). Stated here
    /// because the identity screen is where a user would look for it.
    #[test]
    fn every_account_is_account_zero() {
        let loaded = wallet(Network::Mainnet);
        for family in Family::ALL {
            assert!(path(&loaded, family).ends_with("/0h"));
        }
    }
}
