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

use bitcoin::bip32::{ChildNumber, DerivationPath, Xpriv, Xpub};
use bitcoin::hashes::Hash as _;
use bitcoin::secp256k1::Secp256k1;
use bitcoin::ScriptBuf;

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

// --- the re-derivation byte-compare (`02-core.md` §7) --------------------------------------

/// The `scriptPubKey` of one of our addresses, and the path a coordinator declares for it.
fn ours(
    wallet: &Wallet,
    family: Family,
    branch: Branch,
    index: u32,
) -> (DerivationPath, ScriptBuf) {
    let branch_index = match branch {
        Branch::Receive => 0,
        Branch::Change => 1,
    };
    let path = wallet.account_path(family).extend([
        ChildNumber::Normal {
            index: branch_index,
        },
        ChildNumber::Normal { index },
    ]);
    let spk = wallet
        .address(family, branch, index)
        .expect("a normal index")
        .script_pubkey();
    (path, spk)
}

/// The honest case, in all four families and on **both branches**.
///
/// §7's *both branches count* is the assertion here: an output that byte-verifies on the
/// receive branch is provably ours and provably scannable, so treating branch `1` as the only
/// legitimate change branch would refuse transactions that are fine.
#[test]
fn every_family_verifies_on_both_branches() {
    for network in [Network::Mainnet, Network::Testnet] {
        let wallet = wallet(network);
        for family in Family::ALL {
            for branch in [Branch::Receive, Branch::Change] {
                let (path, spk) = ours(&wallet, family, branch, 7);
                assert_eq!(
                    wallet.verify(&path, &spk),
                    Verdict::Ours {
                        family,
                        branch,
                        index: 7
                    },
                    "{family:?} {branch:?} on {network:?}"
                );
            }
        }
    }
}

/// The claimed path is read for *where to look* and nothing else: our path, another key's
/// bytes, and the answer is [`Verdict::Mismatch`] rather than *ours*.
#[test]
fn our_path_over_someone_elses_script_is_a_mismatch() {
    let wallet = wallet(Network::Mainnet);
    let (path, _) = ours(&wallet, Family::Bip84, Branch::Change, 0);
    let theirs = ScriptBuf::new_p2wpkh(&bitcoin::WPubkeyHash::from_byte_array([0x44; 20]));

    assert_eq!(wallet.verify(&path, &theirs), Verdict::Mismatch);
}

/// The **declared script type is the path's purpose**, so a BIP84 path over a BIP44 address of
/// our own is a mismatch — same key material, wrong script.
///
/// This is why the byte-compare needs no separate script-type parameter: `m/84h/…` says P2WPKH
/// and nothing else may answer for it.
#[test]
fn the_purpose_declares_the_script_type() {
    let wallet = wallet(Network::Mainnet);
    let (bip84_path, _) = ours(&wallet, Family::Bip84, Branch::Receive, 0);
    let (_, bip44_spk) = ours(&wallet, Family::Bip44, Branch::Receive, 0);

    assert_eq!(wallet.verify(&bip84_path, &bip44_spk), Verdict::Mismatch);
}

/// Every way a path leaves the space we scan. Each of these is `AOBS-R09` on the review path,
/// and none of them derives anything: the compare never runs.
#[test]
fn a_path_we_would_never_scan_is_unscannable() {
    let wallet = wallet(Network::Mainnet);
    let (_, spk) = ours(&wallet, Family::Bip84, Branch::Receive, 0);
    let hardened = |index| ChildNumber::Hardened { index };
    let normal = |index| ChildNumber::Normal { index };

    let cases: [(&str, DerivationPath); 8] = [
        // Another account. §6 offers no account-index choice, so account 1 is unreachable.
        (
            "account 1",
            DerivationPath::from(vec![
                hardened(84),
                hardened(0),
                hardened(1),
                normal(0),
                normal(0),
            ]),
        ),
        // The other network's coin type — a testnet path against a mainnet wallet.
        (
            "coin type 1h",
            DerivationPath::from(vec![
                hardened(84),
                hardened(1),
                hardened(0),
                normal(0),
                normal(0),
            ]),
        ),
        // A purpose outside the four families.
        (
            "purpose 45h",
            DerivationPath::from(vec![
                hardened(45),
                hardened(0),
                hardened(0),
                normal(0),
                normal(0),
            ]),
        ),
        // A third branch: `path[-2] ∉ {0, 1}`.
        (
            "branch 2",
            DerivationPath::from(vec![
                hardened(84),
                hardened(0),
                hardened(0),
                normal(2),
                normal(0),
            ]),
        ),
        // A hardened branch, which is not `0` or `1` however it prints.
        (
            "branch 0h",
            DerivationPath::from(vec![
                hardened(84),
                hardened(0),
                hardened(0),
                hardened(0),
                normal(0),
            ]),
        ),
        // A hardened final index: `path[-1] >= 2^31`.
        (
            "index 0h",
            DerivationPath::from(vec![
                hardened(84),
                hardened(0),
                hardened(0),
                normal(0),
                hardened(0),
            ]),
        ),
        // Too short, and too long. A path of the wrong length names no address of ours.
        (
            "four children",
            DerivationPath::from(vec![hardened(84), hardened(0), hardened(0), normal(0)]),
        ),
        (
            "six children",
            DerivationPath::from(vec![
                hardened(84),
                hardened(0),
                hardened(0),
                normal(0),
                normal(0),
                normal(0),
            ]),
        ),
    ];

    for (name, path) in cases {
        assert_eq!(wallet.verify(&path, &spk), Verdict::Unscannable, "{name}");
    }
}

/// A hardened final index is refused by the **type**, not by an inequality: `2^31` and above is
/// exactly what `ChildNumber::Hardened` holds, so there is no off-by-one to get wrong.
#[test]
fn the_largest_normal_index_verifies_and_the_next_one_cannot_exist() {
    let wallet = wallet(Network::Mainnet);
    let largest = (1u32 << 31) - 1;
    let (path, spk) = ours(&wallet, Family::Bip84, Branch::Change, largest);

    assert_eq!(
        wallet.verify(&path, &spk),
        Verdict::Ours {
            family: Family::Bip84,
            branch: Branch::Change,
            index: largest
        }
    );
    assert!(wallet
        .address(Family::Bip84, Branch::Change, 1 << 31)
        .is_none());
}

/// The two networks and the two names, which `AOBS-R06`'s copy is assembled from.
#[test]
fn the_network_names_itself_and_the_other_one() {
    assert_eq!(Network::Mainnet.other(), Network::Testnet);
    assert_eq!(Network::Testnet.other(), Network::Mainnet);
    assert_eq!(Network::Mainnet.name(), "mainnet");
    assert_eq!(Network::Testnet.name(), "testnet or signet");
    assert_ne!(Network::Mainnet.name(), Network::Testnet.name());
}
// --- §10's receive-address verification ---------------------------------------------------
//
// **A miss is 8,000 derivations, so the misses are counted rather than sprinkled.** Every
// candidate that fails to match walks the whole window, and in a debug build one point
// derivation is roughly a thousand times what the string comparison costs — so each test below
// asserts a *rule* on the smallest number of full walks that can carry it, and the rules that
// are purely about strings are asserted against `normalize` and `matches` directly, where they
// live.

/// The QR form of a bech32 address: BIP-173 SHOULD use uppercase for alphanumeric mode, which
/// is what makes step 3's `eq_ignore_ascii_case` load-bearing rather than lenient.
fn qr_form(address: &str) -> String {
    address.to_uppercase()
}

/// `05-testing-and-release.md` §2's *Address verification* row: **derived addresses across all
/// four families, matched in both lowercase and uppercase QR forms.**
///
/// The two halves are not symmetric, and that asymmetry is the whole of `02-core.md` §10's
/// third step: a bech32 address matches whatever case it arrives in, and a base58 one matches
/// only as it was derived. Both are asserted here, in one table, because a change that made the
/// compare uniform in either direction would break exactly one of them — and the base58 half is
/// the direction that would report **yours** for an address the user mistyped in case.
#[test]
fn every_derived_address_is_found_and_only_bech32_matches_loosely_on_case() {
    let wallet = wallet(Network::Mainnet);

    for family in Family::ALL {
        for branch in Branch::ALL {
            // The two ends of the window, which is also the cheapest and the dearest match.
            for index in [0u32, SEARCH_INDICES - 1] {
                let derived = address_of(&wallet, family, branch, index);

                let found = wallet
                    .find_address(&derived)
                    .unwrap_or_else(|| panic!("{family:?} {branch:?} {index} was not found"));
                assert_eq!(
                    (found.family, found.branch, found.index),
                    (family, branch, index)
                );
                assert_eq!(found.address.to_string(), derived);
            }
        }
    }

    // The case rule is a property of the family, so one address per family carries it. For the
    // two bech32 families the shouted form matches and **what comes back is our own form**, not
    // the string that was scanned; for the two base58 families it is a different string.
    for family in Family::ALL {
        let derived = address_of(&wallet, family, Branch::Receive, 0);
        let shouted = wallet.find_address(&qr_form(&derived));

        if family.bech32() {
            let found = shouted.unwrap_or_else(|| panic!("{family:?}: the QR form must match"));
            assert_eq!(found.index, 0);
            assert_eq!(found.address.to_string(), derived, "{family:?}");
        } else {
            assert!(
                shouted.is_none(),
                "{family:?}: base58 is case-sensitive, so an uppercased one is a different \
                 string and must not match"
            );
        }
    }
}

/// The verdict states the three things `04-screens.md` §12 puts on the screen, and the path is
/// assembled from them rather than beside them.
#[test]
fn a_match_carries_the_full_path_the_index_and_the_branch() {
    let wallet = wallet(Network::Mainnet);
    let derived = address_of(&wallet, Family::Bip84, Branch::Change, 7);

    let found = wallet.find_address(&derived).expect("ours");

    assert_eq!(found.family, Family::Bip84);
    assert_eq!(found.branch, Branch::Change);
    assert_eq!(found.index, 7);
    assert_eq!(found.path.to_string(), "84'/0'/0'/1/7");
    assert_eq!(found.address.to_string(), derived);
    // Both branches are searched (the test above walks them), and this is the one that would
    // otherwise be a false *not yours* for a user checking a change address.
    assert_ne!(found.branch, Branch::Receive);
}

/// The window is 0–999 inclusive, on the nose. 1000 is the first address that is genuinely
/// ours and that this search reports nothing about — which is why the negative screen names
/// what was searched instead of claiming the address is not the user's.
#[test]
fn the_window_ends_at_nine_hundred_ninety_nine() {
    let wallet = wallet(Network::Mainnet);
    assert_eq!(SEARCH_INDICES, 1_000);

    let last = address_of(&wallet, Family::Bip84, Branch::Receive, SEARCH_INDICES - 1);
    assert!(wallet.find_address(&last).is_some());

    let past = address_of(&wallet, Family::Bip84, Branch::Receive, SEARCH_INDICES);
    assert!(
        wallet.find_address(&past).is_none(),
        "the index one past the window is ours and is not searched"
    );
}

/// A BIP-21 URI, in both cases of the scheme and with and without a query string. The scheme is
/// case-insensitive by BIP-21, and the query is where a coordinator puts the amount and the label.
///
/// Every candidate here **matches**, so none of them pays for a full walk.
#[test]
fn a_bitcoin_uri_is_stripped_case_insensitively_and_truncated_at_the_query() {
    let wallet = wallet(Network::Mainnet);
    let derived = address_of(&wallet, Family::Bip44, Branch::Receive, 0);
    let bech32 = address_of(&wallet, Family::Bip84, Branch::Receive, 0);

    for candidate in [
        format!("bitcoin:{derived}"),
        format!("BITCOIN:{derived}"),
        format!("Bitcoin:{derived}"),
        format!("bitcoin:{derived}?amount=0.001"),
        format!("bitcoin:{derived}?amount=0.001&label=Coffee"),
        format!("{derived}?amount=0.001"),
        format!("bitcoin:{bech32}"),
        // The uppercase BIP-21 URI a bech32 QR actually carries: scheme, address and all.
        qr_form(&format!("bitcoin:{bech32}?amount=0.001")),
    ] {
        assert!(
            wallet.find_address(&candidate).is_some(),
            "{candidate} must match"
        );
    }
}

/// The two shapes the whole feature exists to catch, end to end: **one character different**,
/// and a truncated address. Two full walks, and they are the two worth paying for.
#[test]
fn one_character_different_and_a_truncation_are_not_found() {
    let wallet = wallet(Network::Mainnet);
    let derived = address_of(&wallet, Family::Bip84, Branch::Receive, 0);

    let mut altered = derived.clone();
    altered.pop();
    altered.push('q');
    assert_ne!(altered, derived);
    assert!(wallet.find_address(&altered).is_none(), "{altered}");

    let truncated = derived[..derived.len() - 4].to_owned();
    assert!(wallet.find_address(&truncated).is_none(), "{truncated}");
}

/// A correctly formed address from the **wrong account**: a real address of a different seed,
/// which is what a substituted address from another wallet looks like. Asserted in both
/// directions, so the two fixtures cannot accidentally be the same wallet.
#[test]
fn a_correctly_formed_address_from_another_wallet_is_not_found() {
    let ours = wallet(Network::Mainnet);
    let theirs = Wallet::load(
        &Mnemonic::from_entropy(&Entropy::new(&[7u8; 16]).expect("16 bytes fit"))
            .expect("16 bytes is an accepted length"),
        &no_passphrase(),
        Network::Mainnet,
    );
    assert_ne!(ours.fingerprint(), theirs.fingerprint());

    let foreign = address_of(&theirs, Family::Bip84, Branch::Receive, 0);
    assert!(ours.find_address(&foreign).is_none(), "{foreign}");

    let mine = address_of(&ours, Family::Bip84, Branch::Receive, 0);
    assert!(theirs.find_address(&mine).is_none(), "{mine}");
}

/// The network is a load parameter (ADR-0015) and the search is over the accounts the loaded
/// network derived, so a testnet address is not found by a mainnet session. Asserted on the one
/// family whose two networks share no prefix at all, in the direction a user would hit it.
#[test]
fn an_address_of_the_other_network_is_not_found() {
    let mainnet = wallet(Network::Mainnet);
    let testnet = wallet(Network::Testnet);

    let theirs = address_of(&testnet, Family::Bip84, Branch::Receive, 0);
    assert!(mainnet.find_address(&theirs).is_none(), "{theirs}");
}

/// The two normalization steps on their own, including the shapes that must not panic. A
/// scanned symbol is printable ASCII by the time `ur.rs` is done with it, but this function may
/// not rest on that: it is the one place a hostile string is sliced.
#[test]
fn the_normalization_is_two_slices_and_never_panics() {
    assert_eq!(normalize("bc1qexample"), "bc1qexample");
    assert_eq!(normalize("bitcoin:bc1qexample"), "bc1qexample");
    assert_eq!(normalize("BITCOIN:BC1QEXAMPLE"), "BC1QEXAMPLE");
    assert_eq!(normalize("bitcoin:bc1qexample?amount=1"), "bc1qexample");
    assert_eq!(normalize("bc1qexample?a=1?b=2"), "bc1qexample");
    assert_eq!(normalize("bitcoin:"), "");
    assert_eq!(normalize("?"), "");
    assert_eq!(normalize(""), "");
    // Shorter than the scheme, so the prefix slice does not exist at all.
    assert_eq!(normalize("bit"), "bit");
    // Multi-byte characters at and around the prefix boundary: no byte index taken here is
    // allowed to land inside one.
    assert_eq!(normalize("₿itcoin:abc"), "₿itcoin:abc");
    assert_eq!(normalize("bitcoin:₿ab?x"), "₿ab");
    assert_eq!(normalize("₿?₿"), "₿");
}

/// Everything the four steps deliberately **do not** do, asserted where the steps are rather
/// than through 8,000 derivations each: no whitespace trimming, no second scheme, no prefix
/// BIP-21 does not name, and no recovery from a leading `?`.
#[test]
fn nothing_but_those_four_steps_happens() {
    let wallet = wallet(Network::Mainnet);
    let bech32 = wallet
        .address(Family::Bip84, Branch::Receive, 0)
        .expect("a normal index");
    let base58 = wallet
        .address(Family::Bip44, Branch::Receive, 0)
        .expect("a normal index");

    for ours in [&bech32, &base58] {
        let derived = ours.to_string();
        let family = if ours == &bech32 {
            Family::Bip84
        } else {
            Family::Bip44
        };

        assert!(matches(family, ours, normalize(&derived)));

        for candidate in [
            format!(" {derived}"),
            format!("{derived} "),
            format!("lightning:{derived}"),
            format!("bitcoin://{derived}"),
            format!("?{derived}"),
            "bitcoin:".to_owned(),
            String::new(),
        ] {
            assert!(
                !matches(family, ours, normalize(&candidate)),
                "{family:?} {candidate:?} must not match"
            );
        }
    }

    // And the case rule, at the level it is implemented rather than through the search.
    assert!(matches(
        Family::Bip84,
        &bech32,
        &qr_form(&bech32.to_string())
    ));
    assert!(!matches(
        Family::Bip44,
        &base58,
        &qr_form(&base58.to_string())
    ));
}
