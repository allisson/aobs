//! Derivation, and what "ours" means (`02-core.md` §6).
//!
//! **Four accounts, always, derived together:** BIP44 (P2PKH), BIP49 (P2SH-P2WPKH), BIP84
//! (P2WPKH) and BIP86 (P2TR key-path), at account 0, on the loaded network. Nothing here
//! takes a script type or an account index, because neither is offered anywhere: *"is your
//! old wallet BIP44 or BIP84?"* is a question the product refuses to ask, and the price is
//! four derivations instead of one.
//!
//! Those four accounts are the definition of *ours* — for the change re-derivation
//! byte-compare (§7), for receive verification (§10) and for the watch-only export
//! (`03-transport.md` §7).
//!
//! **The network is a load parameter**, not a property of a seed (ADR-0015), and it is two
//! states rather than three — see [`Network`].

use bitcoin::bip32::{ChildNumber, DerivationPath, Fingerprint, Xpriv, Xpub};
use bitcoin::secp256k1::{All, Secp256k1};
use bitcoin::{Address, KnownHrp, NetworkKind, Script};

use crate::bip39::Mnemonic;
use crate::secret::{MasterXprv, Passphrase};

/// The loaded network. **Two states, not three.**
///
/// Testnet and signet share coin type `1h`, the `tb` HRP and the same base58 versions, so
/// nothing in a key, an address or a descriptor distinguishes them — a third state would be a
/// label with no derivable consequence, and the backup header spends one bit for the same
/// reason (`02-core.md` §6).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Network {
    /// Mainnet: `xpub`, coin type `0h`, `bc` addresses.
    Mainnet,
    /// Testnet or signet: `tpub`, coin type `1h`, `tb` addresses.
    Testnet,
}

impl Network {
    /// BIP-44's coin type: `0h` on mainnet, `1h` on testnet and signet.
    ///
    /// Visible to the crate because `psbt.rs` compares it against the coin type a PSBT's inputs
    /// *declare* — which selects the copy on `AOBS-R06` and decides nothing (standing rule 1).
    pub(crate) fn coin_type(self) -> ChildNumber {
        match self {
            Self::Mainnet => ChildNumber::Hardened { index: 0 },
            Self::Testnet => ChildNumber::Hardened { index: 1 },
        }
    }

    /// What the base58 version bytes of an extended key and a P2PKH/P2SH address carry.
    fn kind(self) -> NetworkKind {
        match self {
            Self::Mainnet => NetworkKind::Main,
            Self::Testnet => NetworkKind::Test,
        }
    }

    /// The bech32 human-readable part. `KnownHrp::Testnets` is `tb`, which is why signet
    /// needs no state of its own.
    fn hrp(self) -> KnownHrp {
        match self {
            Self::Mainnet => KnownHrp::Mainnet,
            Self::Testnet => KnownHrp::Testnets,
        }
    }

    /// The other one. Total, because there are two states and not three.
    ///
    /// It exists for one caller: the `AOBS-R06` copy variant that says *this transaction was
    /// built for the other network* outright (`02-core.md` §7). Naming the other network is
    /// only possible because the space is two-valued.
    #[must_use]
    pub fn other(self) -> Self {
        match self {
            Self::Mainnet => Self::Testnet,
            Self::Testnet => Self::Mainnet,
        }
    }

    /// How copy names this network **inside a sentence**.
    ///
    /// Deliberately not the selector's own labels (`04-screens.md` §5.2, *Mainnet* and *Testnet /
    /// signet*): a label sits alone on a row and a refusal's copy has to read as prose, and
    /// *"the wallet you loaded is for Testnet / signet"* does not. It is the same two states in
    /// the same order, lower-cased and joined with a word — testnet and signet share one name
    /// here because they share everything a key, an address or a descriptor can express.
    #[must_use]
    pub fn name(self) -> &'static str {
        match self {
            Self::Mainnet => "mainnet",
            Self::Testnet => "testnet or signet",
        }
    }

    /// The dependency's network, for the one thing that needs the whole of it: rendering a
    /// `scriptPubKey` as the address a person reads.
    ///
    /// Signet's addresses are testnet's, so `Testnet` serves both — which is why this is not a
    /// third state (`02-core.md` §6).
    pub(crate) fn params(self) -> bitcoin::Network {
        match self {
            Self::Mainnet => bitcoin::Network::Bitcoin,
            Self::Testnet => bitcoin::Network::Testnet,
        }
    }
}

/// One of the four BIP families, which is a purpose and a script type together.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Family {
    /// BIP44, P2PKH.
    Bip44,
    /// BIP49, P2SH-P2WPKH.
    Bip49,
    /// BIP84, P2WPKH.
    Bip84,
    /// BIP86, P2TR key-path.
    Bip86,
}

impl Family {
    /// All four, in the order the identity screen and the export list them.
    ///
    /// Every walk over the accounts goes through this — an account the product derives but
    /// forgets to search is a false *"this address is not yours"*.
    pub const ALL: [Self; 4] = [Self::Bip44, Self::Bip49, Self::Bip84, Self::Bip86];

    /// BIP-43's purpose field.
    ///
    /// Visible to the crate for the same reason [`Network::coin_type`] is: `psbt.rs` reads the
    /// purpose a PSBT's inputs *declare*, to tell a path that names one of these four families
    /// from one that names something else entirely. It selects copy and decides nothing.
    pub(crate) fn purpose(self) -> ChildNumber {
        let index = match self {
            Self::Bip44 => 44,
            Self::Bip49 => 49,
            Self::Bip84 => 84,
            Self::Bip86 => 86,
        };
        ChildNumber::Hardened { index }
    }

    /// Whether this family's addresses are bech32 or bech32m rather than base58.
    ///
    /// **This is the whole of `02-core.md` §10's third step, and it is read off the family
    /// rather than off the candidate.** BIP-173 says encoders MUST emit lowercase but that QR
    /// presentation SHOULD use uppercase for alphanumeric mode, so a scanned bech32 address is
    /// usually all uppercase and an exact compare would report *not yours* for the user's own
    /// address. Base58 is case-sensitive, so comparing *it* loosely would report **yours** for
    /// an address the user mistyped in case.
    ///
    /// A `match` over four variants rather than a reading of a derived address's type: there is
    /// no unknown arm to default, and adding a fifth family would be a compile error here.
    fn bech32(self) -> bool {
        match self {
            Self::Bip44 | Self::Bip49 => false,
            Self::Bip84 | Self::Bip86 => true,
        }
    }

    /// Its slot in [`Family::ALL`] and in [`Wallet`]'s account array.
    fn slot(self) -> usize {
        match self {
            Self::Bip44 => 0,
            Self::Bip49 => 1,
            Self::Bip84 => 2,
            Self::Bip86 => 3,
        }
    }
}

/// BIP-44's two branches under an account. Change is not a lesser case: it is re-derived and
/// byte-compared on every review, and it is searched on every receive verification.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Branch {
    /// The external branch, `0`.
    Receive,
    /// The internal branch, `1`.
    Change,
}

impl Branch {
    /// Both of them, in the order the receive search walks them.
    ///
    /// It exists for the same reason [`Family::ALL`] does: a branch the product derives but
    /// forgets to search is a false *"this address is not yours"*, and §10 includes change
    /// because excluding it would produce exactly that for a user checking one.
    pub const ALL: [Self; 2] = [Self::Receive, Self::Change];

    fn child(self) -> ChildNumber {
        match self {
            Self::Receive => ChildNumber::Normal { index: 0 },
            Self::Change => ChildNumber::Normal { index: 1 },
        }
    }
}

/// How many indices the receive search walks on each branch of each account: **0–999**
/// (`02-core.md` §10).
///
/// 1000 is far past BIP-44's gap limit of 20, which is what makes a negative answer worth
/// something. It is public because the screen that reports a negative has to name *precisely
/// what was searched* — and if §6.4's fallback is ever taken and the window narrows, the
/// sentence has to narrow with it. One constant is what makes that impossible to forget.
pub const SEARCH_INDICES: u32 = 1_000;

/// How many derivations a search that finds nothing performs: **8,000** — four accounts, both
/// branches, [`SEARCH_INDICES`] each.
///
/// It is here rather than multiplied out by whoever needs it, because it is a fact about the
/// search and the shell prints it (`05-testing-and-release.md` §6.2). A shell computing it from
/// three of core's constants would be a second place that has to be right about the shape of the
/// walk.
pub const SEARCH_WINDOW: usize = SEARCH_INDICES as usize * Family::ALL.len() * Branch::ALL.len();

/// Where a scanned address turned out to live in our own key material (`02-core.md` §10).
///
/// It carries the path *and* the three components the path is assembled from, because
/// `04-screens.md` §12 states all of them: the full derivation path, the index, and which
/// branch it came from. A screen that had to take the index back out of the path would be
/// parsing something we already knew.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Found {
    /// Which of the four families the address belongs to.
    pub family: Family,
    /// Receive or change — §12 names it, because a user checking a change address is a
    /// case the search deliberately covers.
    pub branch: Branch,
    /// The index, within [`SEARCH_INDICES`].
    pub index: u32,
    /// The full five-level path, for the screen to state.
    pub path: DerivationPath,
    /// The address **we derived**, not the string that was scanned. That is the whole point:
    /// what the screen shows is our own material, so a candidate that matched loosely on case
    /// is displayed in the form the wallet actually holds.
    pub address: Address,
}

/// What a claimed derivation path and a `scriptPubKey` amount to when checked against our own
/// key material — the re-derivation byte-compare (`02-core.md` §7).
///
/// **The claimed derivation selects a candidate; the byte-compare is the only authority.** The
/// path is attacker-supplied (standing rule 1), so it is read for *where to look* and for
/// nothing else; what decides is whether the bytes we derive there are the bytes we were
/// handed. The three arms are the three answers, and two of them are refusals on the review
/// path: [`Verdict::Unscannable`] is `AOBS-R09` and [`Verdict::Mismatch`] is `AOBS-R08`.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Verdict {
    /// The path is one of our four accounts, on either branch, at a normal index — and the
    /// `scriptPubKey` we derive there is byte-identical to the one we were handed.
    Ours {
        /// Which of the four families the path's purpose and coin type name.
        family: Family,
        /// Receive or change. **Both count** (§7): an output that byte-verifies on the receive
        /// branch is provably ours and provably scannable.
        branch: Branch,
        /// The final index, always a normal child.
        index: u32,
    },
    /// A path this wallet would never look at, so nothing was derived and nothing compared.
    ///
    /// Anything outside `m/{44,49,84,86}h/{coin}h/0h/{0,1}/{index < 2^31}`: another account,
    /// another coin type, a third branch, a hardened final index, or a path of the wrong
    /// length. On the review path this is Coldcard's 2019 change-path ransom — coins that are
    /// yours and that your wallet will never find.
    Unscannable,
    /// The path is one of ours; the `scriptPubKey` is not the one it derives.
    ///
    /// This is the change-substitution class, and it is where it dies: the fingerprint said
    /// *ours*, the path said *here*, and the bytes said otherwise.
    Mismatch,
}

/// A loaded wallet: the four accounts, the facts the identity screen states, and the master
/// key the signing path needs.
///
/// One per boot — the `OnceLock` that enforces it is the shell's (`02-core.md` §12), because
/// core is stateless functions and has no wallet to replace.
pub struct Wallet {
    /// Wrapped and zeroized on drop; reachable only through [`Wallet::with_master`].
    master: MasterXprv,
    network: Network,
    passphrase_in_use: bool,
    fingerprint: Fingerprint,
    /// Indexed by [`Family::slot`]. Public material, so not wrapped.
    accounts: [Xpub; 4],
    /// One context for the session: `02-core.md` §10's receive search is 8,000 derivations
    /// and allocating a secp256k1 context per address would dominate it.
    secp: Secp256k1<All>,
}

impl Wallet {
    /// Derive everything from the mnemonic, the passphrase and the network.
    ///
    /// The seed is BIP-39's; the master key is BIP-32's, from the one constant every network
    /// shares. Both are transient here — what survives is the wrapped master key, the four
    /// account xpubs and the three facts below.
    #[must_use]
    pub fn load(mnemonic: &Mnemonic, passphrase: &Passphrase, network: Network) -> Self {
        let seed = mnemonic.seed(passphrase);
        let secp = Secp256k1::new();
        let mut master = Xpriv::new_master(network.kind(), seed.as_bytes())
            .expect("a 64-byte seed is BIP-32's own input length");

        let fingerprint = master.fingerprint(&secp);
        let accounts = Family::ALL.map(|family| {
            let account = master
                .derive_priv(&secp, &account_path(family, network))
                .expect("three hardened children of a master key always derive");
            Xpub::from_priv(&secp, &account)
        });
        let wrapped = MasterXprv::new(master.encode());

        // The local copy is not `ZeroizeOnDrop` — `Xpriv` is the dependency's type — so the
        // private key is erased by hand. Two things this does not reach, stated rather than
        // papered over: the chain code sits behind a private field, and the array
        // `encode()` returned was moved into the wrapper by copy. Standing rule 9 applies —
        // nothing here claims a freed page is observably clean.
        master.private_key.non_secure_erase();

        Self {
            master: wrapped,
            network,
            passphrase_in_use: !passphrase.as_bytes().is_empty(),
            fingerprint,
            accounts,
            secp,
        }
    }

    /// The loaded network — the identity screen's whole network signal, because the
    /// fingerprint carries none (`04-screens.md` §7).
    #[must_use]
    pub fn network(&self) -> Network {
        self.network
    }

    /// The 4-byte master fingerprint, which is **identical on both networks**.
    ///
    /// It is what a user compares against their coordinator, and a hint only for derivation:
    /// on the review path it selects a candidate and never authorises anything (§7).
    #[must_use]
    pub fn fingerprint(&self) -> Fingerprint {
        self.fingerprint
    }

    /// Whether a passphrase was in use at load. Empty is no passphrase.
    ///
    /// Stated on the identity screen, and it rides in the backup's AAD, which is why the
    /// backup cannot exist before the passphrase is known.
    #[must_use]
    pub fn passphrase_in_use(&self) -> bool {
        self.passphrase_in_use
    }

    /// The account-level xpub for one family: `m/purpose'/coin'/0'`.
    #[must_use]
    pub fn account_xpub(&self, family: Family) -> &Xpub {
        &self.accounts[family.slot()]
    }

    /// The account-level path for one family, for display and for the export's descriptors.
    #[must_use]
    pub fn account_path(&self, family: Family) -> DerivationPath {
        account_path(family, self.network)
    }

    /// The address at `family`/`branch`/`index`, or `None` if `index` is not a normal child
    /// index (`>= 2^31`).
    ///
    /// `None` rather than a panic because the index reaching this can come from a PSBT's
    /// claimed derivation path, which is attacker-supplied (standing rule 1).
    #[must_use]
    pub fn address(&self, family: Family, branch: Branch, index: u32) -> Option<Address> {
        if index >= 1 << 31 {
            return None;
        }

        Some(self.address_at(family, &self.branch_xpub(family, branch), index))
    }

    /// The branch-level key, `m/purpose'/coin'/0'/{0,1}`.
    ///
    /// Split out for [`Wallet::find_address`], which derives it **once per branch** instead of
    /// once per index: the search is 8,000 addresses and the branch child is one of the two
    /// point derivations each of them would otherwise pay for. Measured at 415 ms down to
    /// 246 ms — see `05-testing-and-release.md` §6.4.
    fn branch_xpub(&self, family: Family, branch: Branch) -> Xpub {
        self.accounts[family.slot()]
            .derive_pub(&self.secp, &[branch.child()])
            .expect("a normal child of an xpub always derives")
    }

    /// The address at `index` under an already-derived branch key.
    ///
    /// **One implementation of *which script this family means*,** shared by the single-address
    /// path and the search. Two would be free to disagree, and the one that disagreed would be
    /// the one deciding whether an address is the user's.
    fn address_at(&self, family: Family, branch: &Xpub, index: u32) -> Address {
        let key = branch
            .derive_pub(&self.secp, &[ChildNumber::Normal { index }])
            .expect("normal children of an xpub always derive");

        match family {
            Family::Bip44 => Address::p2pkh(key.to_pub(), self.network.kind()),
            Family::Bip49 => Address::p2shwpkh(&key.to_pub(), self.network.kind()),
            Family::Bip84 => Address::p2wpkh(&key.to_pub(), self.network.hrp()),
            Family::Bip86 => {
                Address::p2tr(&self.secp, key.to_x_only_pub(), None, self.network.hrp())
            }
        }
    }

    /// Receive-address verification: **scan one address, compare strings, answer**
    /// (`02-core.md` §10).
    ///
    /// The window is all four accounts, both branches, indices `0..`[`SEARCH_INDICES`] — 8,000
    /// derivations, and the first match wins. `None` cannot honestly mean *not yours*; it means
    /// *not in what was searched*, and `04-screens.md` §12 is where that distinction is paid for
    /// in copy rather than hedged here.
    ///
    /// **The candidate's form is never consulted, inferred or trusted.** [`normalize`] strips
    /// what BIP-21 allows and nothing else; the comparison's looseness comes from
    /// [`Family::bech32`], which is a fact about material we derived ourselves.
    ///
    /// Nothing here originates an address (§10): origination was cut because an originated
    /// address still reaches the payer through the user's online machine, where it is altered
    /// exactly as before.
    #[must_use]
    pub fn find_address(&self, candidate: &str) -> Option<Found> {
        let candidate = normalize(candidate);

        for family in Family::ALL {
            for branch in Branch::ALL {
                let key = self.branch_xpub(family, branch);
                for index in 0..SEARCH_INDICES {
                    let address = self.address_at(family, &key, index);
                    if !matches(family, &address, candidate) {
                        continue;
                    }

                    let path = self
                        .account_path(family)
                        .extend([branch.child(), ChildNumber::Normal { index }]);

                    return Some(Found {
                        family,
                        branch,
                        index,
                        path,
                        address,
                    });
                }
            }
        }

        None
    }

    /// The re-derivation byte-compare: what a claimed path and a `scriptPubKey` amount to
    /// (`02-core.md` §7).
    ///
    /// This is the function most of the product's security reduces to. It is called on every
    /// input (to answer *can we sign anything here at all*) and on every output that claims our
    /// fingerprint (to answer *is this really our change*), and its `Ours` arm is the only thing
    /// in the crate that may conclude a `scriptPubKey` is ours.
    ///
    /// **The path is read, never trusted.** It selects one of at most four candidates; the
    /// answer is a byte comparison against material we derived ourselves. A path we would never
    /// scan is not derived at all — see [`Verdict::Unscannable`].
    #[must_use]
    pub fn verify(&self, path: &DerivationPath, script_pubkey: &Script) -> Verdict {
        let Some((family, branch, index)) = self.scannable(path) else {
            return Verdict::Unscannable;
        };
        let derived = self
            .address(family, branch, index)
            .expect("a scannable index is a normal child");

        if derived.script_pubkey().as_script() == script_pubkey {
            Verdict::Ours {
                family,
                branch,
                index,
            }
        } else {
            Verdict::Mismatch
        }
    }

    /// Whether this path is one this wallet would ever look at — [`Wallet::scannable`]'s
    /// question without the answer.
    ///
    /// It exists for [`crate::sign`], which needs the *bound* rather than the location: what it
    /// derives is a private key, so the set of paths it will derive at has to be a set this
    /// module decides and not a set a PSBT does.
    pub(crate) fn scannable_path(&self, path: &DerivationPath) -> bool {
        self.scannable(path).is_some()
    }

    /// The session's one secp256k1 context, for the signing path.
    ///
    /// `pub(crate)` rather than public: it is not a fact about a wallet, it is the context
    /// [`Wallet::load`] already built. A second one in [`crate::sign`] would be a second
    /// allocation of the precomputation tables for the same session.
    pub(crate) fn secp(&self) -> &Secp256k1<All> {
        &self.secp
    }

    /// Where in our four accounts this path points, or `None` if nowhere we would ever look.
    ///
    /// The rule is §7's, in one place: five children, the first three equal to one of our four
    /// account paths on the loaded network, `path[-2] ∈ {0, 1}` and `path[-1] < 2^31`. The last
    /// of those is not a comparison — [`ChildNumber::Normal`] *is* the sub-2^31 half of the
    /// space, so a hardened final index fails the pattern rather than an inequality.
    fn scannable(&self, path: &DerivationPath) -> Option<(Family, Branch, u32)> {
        let children: &[ChildNumber] = path.as_ref();
        let [purpose, coin, account, branch, index] = children else {
            return None;
        };

        let family = Family::ALL.into_iter().find(|family| {
            let ours: &[ChildNumber] = &[
                family.purpose(),
                self.network.coin_type(),
                ChildNumber::Hardened { index: 0 },
            ];
            [*purpose, *coin, *account] == *ours
        })?;

        let branch = match *branch {
            ChildNumber::Normal { index: 0 } => Branch::Receive,
            ChildNumber::Normal { index: 1 } => Branch::Change,
            _ => return None,
        };
        let ChildNumber::Normal { index } = *index else {
            return None;
        };

        Some((family, branch, index))
    }

    /// Run `f` over the master extended private key, erasing the decoded copy afterwards.
    ///
    /// A closure rather than an accessor: an `Xpriv` returned by value would hand the caller
    /// material with no drop that clears it, and the erase would be a rule to remember
    /// instead of the only way through.
    pub fn with_master<T>(&self, f: impl FnOnce(&Xpriv) -> T) -> T {
        let mut master = Xpriv::decode(self.master.as_bytes()).expect("we encoded it in `load`");
        let out = f(&master);
        master.private_key.non_secure_erase();
        out
    }
}

/// The BIP-21 scheme, which that BIP makes case-insensitive.
const SCHEME: &[u8] = b"bitcoin:";

/// `02-core.md` §10's first two normalization steps: **strip an optional `bitcoin:` prefix
/// case-insensitively, then truncate at the first `?`.**
///
/// Total, allocation-free and non-indexing — it hands back a slice of what it was given, and
/// there is no third step that could reach for a heuristic. In particular it does not trim
/// whitespace, does not accept a second scheme, and does not look at what is left: a candidate
/// that is not one of these two shapes is simply compared as it arrived, and fails to match.
///
/// The prefix test is over **bytes**, so a candidate whose first eight bytes are not a
/// character boundary cannot panic here. Every address we could match is ASCII, and this cannot
/// be the place a scanned string dies.
fn normalize(candidate: &str) -> &str {
    let stripped = match candidate.as_bytes().get(..SCHEME.len()) {
        Some(prefix) if prefix.eq_ignore_ascii_case(SCHEME) => &candidate[SCHEME.len()..],
        _ => candidate,
    };

    match stripped.find('?') {
        Some(query) => &stripped[..query],
        None => stripped,
    }
}

/// §10's third step: **`eq_ignore_ascii_case` only when our address is bech32/bech32m, exact
/// `eq` otherwise.**
///
/// `ours` is the address *we derived*, and `family` is what tells us which of the two rules
/// applies. Nothing about `candidate` is examined beyond the comparison itself — no length, no
/// prefix, no case — because the moment the candidate's form selected the rule, an attacker
/// would be choosing how strictly their own string is compared.
fn matches(family: Family, ours: &Address, candidate: &str) -> bool {
    // The one allocation on this path, and it is the dependency's rendering rather than a step
    // of the normalization: §10's four steps are what stays allocation-free.
    let ours = ours.to_string();

    if family.bech32() {
        ours.eq_ignore_ascii_case(candidate)
    } else {
        ours == candidate
    }
}

/// `m/purpose'/coin'/0'` — the account index is `0` and is not a parameter anywhere.
fn account_path(family: Family, network: Network) -> DerivationPath {
    DerivationPath::from(vec![
        family.purpose(),
        network.coin_type(),
        ChildNumber::Hardened { index: 0 },
    ])
}

#[cfg(test)]
#[path = "derive_tests.rs"]
mod tests;
