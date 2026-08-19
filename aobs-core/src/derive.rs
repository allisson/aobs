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
use bitcoin::{Address, KnownHrp, NetworkKind};

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
    fn coin_type(self) -> ChildNumber {
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
    fn purpose(self) -> ChildNumber {
        let index = match self {
            Self::Bip44 => 44,
            Self::Bip49 => 49,
            Self::Bip84 => 84,
            Self::Bip86 => 86,
        };
        ChildNumber::Hardened { index }
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
    fn child(self) -> ChildNumber {
        match self {
            Self::Receive => ChildNumber::Normal { index: 0 },
            Self::Change => ChildNumber::Normal { index: 1 },
        }
    }
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
        let key = self.accounts[family.slot()]
            .derive_pub(&self.secp, &[branch.child(), ChildNumber::Normal { index }])
            .expect("normal children of an xpub always derive");

        Some(match family {
            Family::Bip44 => Address::p2pkh(key.to_pub(), self.network.kind()),
            Family::Bip49 => Address::p2shwpkh(&key.to_pub(), self.network.kind()),
            Family::Bip84 => Address::p2wpkh(&key.to_pub(), self.network.hrp()),
            Family::Bip86 => {
                Address::p2tr(&self.secp, key.to_x_only_pub(), None, self.network.hrp())
            }
        })
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
