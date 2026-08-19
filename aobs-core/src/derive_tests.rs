//! The four accounts, against the BIPs' own published vectors, plus the network assertions
//! `05-testing-and-release.md` §2 names (the *BIP-32* and *Network* rows).
//!
//! **Where the vectors come from.** BIP-49, BIP-84 and BIP-86 each publish a table for the
//! `abandon … about` mnemonic, and BIP-86's table also publishes the master `xprv`/`xpub` for
//! it — so the whole path from BIP-39 entropy to a rendered address is pinned to text we did
//! not write. Sources:
//!
//! - <https://github.com/bitcoin/bips/blob/master/bip-0049.mediawiki> (testnet)
//! - <https://github.com/bitcoin/bips/blob/master/bip-0084.mediawiki>
//! - <https://github.com/bitcoin/bips/blob/master/bip-0086.mediawiki>
//!
//! **BIP-44 publishes no test vectors** — the document has no vector section at all. So the
//! BIP44 family is pinned differently and the difference is stated rather than hidden: the
//! master key is parsed from BIP-86's published `rootpriv` and `m/44'/0'/0'/0/0` is derived
//! through the dependency's own API, then compared against what [`Wallet`] produced. That
//! pins our path assembly and our key material against an independently parsed root; the one
//! step it cannot pin is `Address::p2pkh`, which is the dependency's and carries the
//! dependency's own suite.
//!
//! The §2 *BIP-32* row — *derivation across all four families* — is these four tables. Adding
//! BIP-32's own vector chains (`m/0'/1/2'/…`) would assert the dependency's derivation rather
//! than ours, since nothing here exposes an arbitrary path.

use std::str::FromStr as _;

use bitcoin::bip32::{DerivationPath, Xpriv, Xpub};
use bitcoin::secp256k1::Secp256k1;

use super::*;
use crate::secret::Entropy;

/// `abandon abandon … about`: BIP-39 entropy of sixteen zero bytes, which is the mnemonic
/// every one of the three vector tables is written for.
fn abandon() -> Mnemonic {
    Mnemonic::from_entropy(&Entropy::new(&[0u8; 16]).expect("16 bytes fit"))
        .expect("16 bytes is an accepted length")
}

fn no_passphrase() -> Passphrase {
    Passphrase::new("").expect("empty fits")
}

fn wallet(network: Network) -> Wallet {
    Wallet::load(&abandon(), &no_passphrase(), network)
}

/// BIP-86's table, mainnet.
const ROOTPRIV: &str = "xprv9s21ZrQH143K3GJpoapnV8SFfukcVBSfeCficPSGfubmSFDxo1kuHnLisriDvSnRRuL2Qrg5ggqHKNVpxR86QEC8w35uxmGoggxtQTPvfUu";
const ROOTPUB: &str = "xpub661MyMwAqRbcFkPHucMnrGNzDwb6teAX1RbKQmqtEF8kK3Z7LZ59qafCjB9eCRLiTVG3uxBxgKvRgbubRhqSKXnGGb1aoaqLrpMBDrVxga8";
const BIP86_ACCOUNT_XPUB: &str = "xpub6BgBgsespWvERF3LHQu6CnqdvfEvtMcQjYrcRzx53QJjSxarj2afYWcLteoGVky7D3UKDP9QyrLprQ3VCECoY49yfdDEHGCtMMj92pReUsQ";

/// `(family, branch, index, address)`, all mainnet except the BIP49 row, which is the only
/// network BIP-49 publishes.
const MAINNET_VECTORS: &[(Family, Branch, u32, &str)] = &[
    // BIP-84: first receiving, second receiving, first change.
    (
        Family::Bip84,
        Branch::Receive,
        0,
        "bc1qcr8te4kr609gcawutmrza0j4xv80jy8z306fyu",
    ),
    (
        Family::Bip84,
        Branch::Receive,
        1,
        "bc1qnjg0jd8228aq7egyzacy8cys3knf9xvrerkf9g",
    ),
    (
        Family::Bip84,
        Branch::Change,
        0,
        "bc1q8c6fshw2dlwun7ekn9qwf37cu2rn755upcp6el",
    ),
    // BIP-86: the same three positions.
    (
        Family::Bip86,
        Branch::Receive,
        0,
        "bc1p5cyxnuxmeuwuvkwfem96lqzszd02n6xdcjrs20cac6yqjjwudpxqkedrcr",
    ),
    (
        Family::Bip86,
        Branch::Receive,
        1,
        "bc1p4qhjn9zdvkux4e44uhx8tc55attvtyu358kutcqkudyccelu0was9fqzwh",
    ),
    (
        Family::Bip86,
        Branch::Change,
        0,
        "bc1p3qkhfews2uk44qtvauqyr2ttdsw7svhkl9nkm9s9c3x4ax5h60wqwruhk7",
    ),
];

/// BIP-49's table is testnet: `m/49'/1'/0'/0/0`.
const BIP49_TESTNET_FIRST_RECEIVE: &str = "2Mww8dCYPUpKHofjgcXcBCEGmniw9CoaiD2";

fn address_of(wallet: &Wallet, family: Family, branch: Branch, index: u32) -> String {
    wallet
        .address(family, branch, index)
        .expect("a vector's index is a normal one")
        .to_string()
}

/// The whole path from BIP-39 entropy to the master key, against BIP-86's published root.
///
/// This is the assertion the other three tables rest on: if the seed or the master
/// derivation were wrong, every address below would be wrong together and consistently.
#[test]
fn the_master_key_is_bip86s_published_root() {
    let wallet = wallet(Network::Mainnet);
    let secp = Secp256k1::new();

    wallet.with_master(|master| {
        assert_eq!(master.to_string(), ROOTPRIV);
        assert_eq!(Xpub::from_priv(&secp, master).to_string(), ROOTPUB);
    });
}

#[test]
fn the_published_addresses_derive_on_mainnet() {
    let wallet = wallet(Network::Mainnet);

    for (family, branch, index, expected) in MAINNET_VECTORS {
        assert_eq!(
            address_of(&wallet, *family, *branch, *index),
            *expected,
            "{family:?} {branch:?} {index}"
        );
    }
}

#[test]
fn bip86s_account_xpub_is_the_published_one() {
    assert_eq!(
        wallet(Network::Mainnet)
            .account_xpub(Family::Bip86)
            .to_string(),
        BIP86_ACCOUNT_XPUB
    );
}

/// BIP-49's vector is the testnet one, which also exercises coin type `1h` end to end.
#[test]
fn bip49s_published_address_derives_on_testnet() {
    let wallet = wallet(Network::Testnet);

    assert_eq!(
        address_of(&wallet, Family::Bip49, Branch::Receive, 0),
        BIP49_TESTNET_FIRST_RECEIVE
    );
    assert_eq!(wallet.account_path(Family::Bip49).to_string(), "49'/1'/0'");
}

/// BIP-44 has no published vectors, so the family is cross-checked against an independently
/// parsed root — see this file's header for why that is the honest bound.
#[test]
fn bip44_agrees_with_the_same_path_derived_from_the_parsed_root() {
    let wallet = wallet(Network::Mainnet);
    let secp = Secp256k1::new();

    let root = Xpriv::from_str(ROOTPRIV).expect("BIP-86 publishes a valid xprv");
    let path = DerivationPath::from_str("m/44'/0'/0'/0/0").expect("a literal path parses");
    let expected = Xpub::from_priv(
        &secp,
        &root.derive_priv(&secp, &path).expect("a normal derivation"),
    );

    let ours = wallet
        .account_xpub(Family::Bip44)
        .derive_pub(
            &secp,
            &DerivationPath::from_str("m/0/0").expect("a literal path parses"),
        )
        .expect("normal children");

    assert_eq!(ours, expected);
    assert_eq!(
        address_of(&wallet, Family::Bip44, Branch::Receive, 0),
        bitcoin::Address::p2pkh(expected.to_pub(), bitcoin::NetworkKind::Main).to_string()
    );
}

/// The alarm `05-testing-and-release.md` §2 asks for by name.
///
/// BIP-32 derives the master key from one constant — HMAC-SHA512 with the key `"Bitcoin
/// seed"`, for every network — and an extended key's identifier is `HASH160` over its
/// 33-byte public key. The network appears only in the base58 version bytes, which the
/// fingerprint does not touch. **So the fingerprint cannot catch a network mistake**, which
/// is why `04-screens.md` §7 makes the network line carry that weight alone. Read from the
/// BIP-32 text rather than measured: this assertion is the alarm if it ever stops holding.
#[test]
fn the_master_fingerprint_is_byte_identical_on_both_networks() {
    let mainnet = wallet(Network::Mainnet);
    let testnet = wallet(Network::Testnet);

    assert_eq!(mainnet.fingerprint(), testnet.fingerprint());

    // And it is the fingerprint of BIP-86's published root, not merely of our own two runs.
    let root = Xpub::from_str(ROOTPUB).expect("BIP-86 publishes a valid xpub");
    assert_eq!(mainnet.fingerprint(), root.fingerprint());
}

/// The other half of §2's *Network* row: everything else about the two networks differs.
#[test]
fn the_same_seed_derives_different_accounts_and_addresses_across_the_networks() {
    let mainnet = wallet(Network::Mainnet);
    let testnet = wallet(Network::Testnet);

    for family in Family::ALL {
        let main_xpub = mainnet.account_xpub(family).to_string();
        let test_xpub = testnet.account_xpub(family).to_string();

        assert!(main_xpub.starts_with("xpub"), "{family:?} {main_xpub}");
        assert!(test_xpub.starts_with("tpub"), "{family:?} {test_xpub}");
        assert_ne!(main_xpub, test_xpub, "{family:?}");

        for branch in [Branch::Receive, Branch::Change] {
            assert_ne!(
                address_of(&mainnet, family, branch, 0),
                address_of(&testnet, family, branch, 0),
                "{family:?} {branch:?}"
            );
        }
    }
}

/// Coin type is the only thing the network changes in a path, and account 0 is not a choice.
#[test]
fn the_four_paths_are_the_purpose_the_coin_type_and_account_zero() {
    for (network, coin) in [(Network::Mainnet, "0'"), (Network::Testnet, "1'")] {
        let wallet = wallet(network);

        for (family, purpose) in Family::ALL.into_iter().zip(["44'", "49'", "84'", "86'"]) {
            assert_eq!(
                wallet.account_path(family).to_string(),
                format!("{purpose}/{coin}/0'"),
                "{family:?} on {network:?}"
            );
        }
    }
}

/// The review path takes its index from the PSBT, which is attacker-supplied, and the
/// receive search walks 0–999 (`02-core.md` §10): both need arbitrary indices, and the
/// hardened half of the range must be a `None` rather than a panic.
#[test]
fn addresses_derive_at_arbitrary_normal_indices_and_nowhere_else() {
    let wallet = wallet(Network::Mainnet);
    let mut seen = std::collections::BTreeSet::new();

    for index in [0, 1, 19, 20, 999, 1_000, (1 << 31) - 1] {
        for family in Family::ALL {
            for branch in [Branch::Receive, Branch::Change] {
                let address = wallet
                    .address(family, branch, index)
                    .expect("a normal index derives");
                assert!(
                    seen.insert(address.to_string()),
                    "{family:?} {branch:?} {index}"
                );
            }
        }
    }

    for index in [1u32 << 31, u32::MAX] {
        assert!(wallet
            .address(Family::Bip84, Branch::Receive, index)
            .is_none());
    }
}

/// The identity screen's remaining fact (`04-screens.md` §7). Empty is no passphrase, and a
/// passphrase changes the wallet rather than annotating it.
#[test]
fn the_passphrase_bit_is_whether_there_is_one() {
    let plain = wallet(Network::Mainnet);
    let with = Wallet::load(
        &abandon(),
        &Passphrase::new("TREZOR").expect("6 bytes fit"),
        Network::Mainnet,
    );

    assert!(!plain.passphrase_in_use());
    assert!(with.passphrase_in_use());
    assert_ne!(plain.fingerprint(), with.fingerprint());
    assert_eq!(plain.network(), Network::Mainnet);
}

/// The four are derived together, always — there is no argument anywhere that selects one.
#[test]
fn all_four_accounts_exist_on_every_wallet() {
    let mut xpubs = std::collections::BTreeSet::new();

    for network in [Network::Mainnet, Network::Testnet] {
        let wallet = wallet(network);
        for family in Family::ALL {
            assert!(xpubs.insert(wallet.account_xpub(family).to_string()));
        }
    }

    assert_eq!(xpubs.len(), 8);
}
