//! The zeroizing secret types (`02-core.md` §2, standing rule 5).
//!
//! **The guarantee lives in what these types do not implement.** No `Clone` and no `Copy`,
//! because every `clone()` makes a copy nothing will ever zeroize. No `String` and no
//! growable `Vec`, because a realloc leaves the old contents behind in freed memory. Every
//! buffer here is allocated at its final size, every one is `ZeroizeOnDrop`, and `Debug`
//! and `Display` are hand-written as `[redacted]`.
//!
//! **Not claimed:** that a test observes a freed page (standing rule 9). It is not reliably
//! observable from safe Rust, so nothing here pretends to prove it. What *is* asserted, in
//! `secret_tests.rs`, is the observable half: a compile-time trait bound that every secret
//! type in the crate is `ZeroizeOnDrop`, and that neither formatter emits any of the
//! material.
//!
//! Three shapes, because three invariants:
//!
//! | Shape | Invariant | Types |
//! |---|---|---|
//! | exact | exactly `N` bytes, always | [`Csprng32`], [`Supplement`], [`Seed`], [`MasterXprv`] |
//! | slice | a length only the caller knows, allocated once at that size | [`Dice`], [`Luma`] |
//! | its own | a cap plus a rule that is the type's whole point | [`Entropy`], [`Passphrase`] |
//!
//! The exact shape is what removes the panic path: a type that cannot be built at the wrong
//! length needs no `expect()` at the point of use.

use core::fmt;

use unicode_normalization::UnicodeNormalization;
use zeroize::{Zeroize, ZeroizeOnDrop};

/// `Debug` and `Display`, hand-written as `[redacted]` and nothing else.
///
/// Not the type name either: these appear inside the `Debug` output of larger structures,
/// and a name is what tells a reader there is something worth grepping for.
macro_rules! redacted {
    ($name:ident) => {
        impl fmt::Debug for $name {
            fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
                f.write_str("[redacted]")
            }
        }

        impl fmt::Display for $name {
            fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
                f.write_str("[redacted]")
            }
        }
    };
}

pub(crate) use redacted;

/// A secret that is always exactly `$n` bytes.
macro_rules! exact_secret {
    ($(#[$attr:meta])* $name:ident, $n:literal) => {
        $(#[$attr])*
        #[derive(Zeroize, ZeroizeOnDrop)]
        pub struct $name([u8; $n]);

        impl $name {
            /// The one and only length, in bytes.
            pub const LEN: usize = $n;

            /// Takes ownership of the bytes.
            #[must_use]
            pub fn new(bytes: [u8; $n]) -> Self {
                Self(bytes)
            }

            /// The bytes, as an array — which is what lets callers avoid a fallible
            /// conversion and therefore a panic path.
            #[must_use]
            pub fn as_array(&self) -> &[u8; $n] {
                &self.0
            }

            /// The bytes.
            #[must_use]
            pub fn as_bytes(&self) -> &[u8] {
                &self.0
            }
        }

        redacted!($name);
    };
}

/// A secret whose length is the caller's, heap-allocated once at exactly that length.
///
/// `Box<[u8]>` rather than `Vec<u8>`: it cannot grow, so it cannot realloc, so it cannot
/// leave a copy behind — which is the whole reason the spec forbids the growable one.
macro_rules! slice_secret {
    ($(#[$attr:meta])* $name:ident) => {
        $(#[$attr])*
        #[derive(Zeroize, ZeroizeOnDrop)]
        pub struct $name(Box<[u8]>);

        impl $name {
            /// Copies `bytes` into an allocation of exactly their length.
            #[must_use]
            pub fn new(bytes: &[u8]) -> Self {
                Self(Box::from(bytes))
            }

            /// The bytes.
            #[must_use]
            pub fn as_bytes(&self) -> &[u8] {
                &self.0
            }
        }

        redacted!($name);
    };
}

exact_secret! {
    /// The 32 bytes the kernel CSPRNG gave the shell.
    ///
    /// Core never calls `getrandom` (ADR-0004): these arrive as a parameter, which is what
    /// makes the mixing vectors possible at all and leaves the provenance release gate
    /// exactly one syscall site to trace.
    Csprng32, 32
}

exact_secret! {
    /// `SHA-256` over the framed supplements — the value XORed into the CSPRNG output.
    Supplement, 32
}

exact_secret! {
    /// The 512-bit BIP-39 seed: `PBKDF2-HMAC-SHA512`, 2048 iterations.
    Seed, 64
}

exact_secret! {
    /// The BIP-32 master extended private key, as the 78-byte serialisation BIP-32 defines.
    ///
    /// Stored as the serialisation rather than as a `bitcoin::bip32::Xpriv` because that type
    /// is the dependency's: it is not `ZeroizeOnDrop`, and its chain code sits behind a
    /// private field that no safe code can clear.
    /// [`crate::derive::Wallet::with_master`] is the only way back to an `Xpriv`, and it
    /// erases the private key of the copy it decodes.
    MasterXprv, 78
}

slice_secret! {
    /// The user's D6 rolls, as the ASCII digits they typed.
    ///
    /// Free entry with no minimum and no cap of our own (`04-screens.md` §2), so the length
    /// is the shell's and the allocation is made once at it. **Empty means absent**, never
    /// a zero-length field — see [`crate::entropy::mix`].
    Dice
}

slice_secret! {
    /// One camera frame's luma plane, captured silently for the mix.
    ///
    /// Core never sees a camera (ADR-0004); the shell hands over the plane it read. Empty
    /// means absent, the same as [`Dice`] — a machine with no camera skips it silently.
    Luma
}

/// BIP-39 entropy: 32 bytes when we generate it, 16–32 when it arrives from an import or a
/// backup restore.
///
/// Which of those five lengths are legal is BIP-39's arithmetic and is checked in
/// [`crate::bip39`], not here — this type owns the buffer and the cap, and the cap is 32
/// because generation is 24 words always (ADR-0006).
#[derive(Zeroize, ZeroizeOnDrop)]
pub struct Entropy {
    bytes: [u8; Self::CAPACITY],
    len: usize,
}

impl Entropy {
    /// The buffer size, and so the longest entropy this type can hold.
    pub const CAPACITY: usize = 32;

    /// Copies `bytes` in, or returns `None` if they do not fit.
    #[must_use]
    pub fn new(bytes: &[u8]) -> Option<Self> {
        if bytes.len() > Self::CAPACITY {
            return None;
        }
        let mut buf = [0u8; Self::CAPACITY];
        buf[..bytes.len()].copy_from_slice(bytes);
        Some(Self {
            bytes: buf,
            len: bytes.len(),
        })
    }

    /// Takes a full buffer and keeps its first `len` bytes.
    ///
    /// `len` is clamped rather than checked, which makes this total: no panic path, and no
    /// arm no test can reach. It is `pub(crate)` precisely because clamping is the wrong
    /// contract to offer the outside world — both callers in this crate compute a length
    /// that is 32 or below by arithmetic.
    pub(crate) fn prefix(bytes: [u8; Self::CAPACITY], len: usize) -> Self {
        Self {
            bytes,
            len: len.min(Self::CAPACITY),
        }
    }

    /// The entropy, without the zero tail.
    #[must_use]
    pub fn as_bytes(&self) -> &[u8] {
        &self.bytes[..self.len]
    }
}

redacted!(Entropy);

/// The BIP-39 passphrase, in a fixed 128-byte buffer (`02-core.md` §5).
///
/// **The buffer holds the NFKD form**, normalised once here at construction, because that
/// is the only form PBKDF2 is ever allowed to see and holding the other one would invite a
/// second normalisation site. Core takes arbitrary UTF-8 (BIP-39 in full); the *shell* is
/// what restricts entry to printable ASCII, over which NFKD is the identity — so lifting
/// that restriction later is a shell change and a font, not a crypto change.
///
/// The cap is structural: growable secret types are forbidden, and 128 is above every
/// mainstream wallet's own limit. It applies to the normalised form, which is the same
/// number under the shell's ASCII restriction.
///
/// **Empty is no passphrase**, and nothing is ever trimmed: `"hunter2 "` and `"hunter2"`
/// are different wallets, and BIP-39 defines no trimming rule. There is no strength meter,
/// no minimum and no lecture — a passphrase is strictly additive over a 24-word mnemonic,
/// and a meter would imply a signer with no rate limiting could compensate for a weak one.
#[derive(Zeroize, ZeroizeOnDrop)]
pub struct Passphrase {
    bytes: [u8; Self::CAPACITY],
    len: usize,
}

impl Passphrase {
    /// The buffer size, in bytes of the NFKD form.
    pub const CAPACITY: usize = 128;

    /// Normalises `text` NFKD and copies it in, or returns `None` if the normalised form
    /// does not fit.
    ///
    /// `Passphrase::new("")` is the no-passphrase case and is not special anywhere.
    #[must_use]
    pub fn new(text: &str) -> Option<Self> {
        let mut bytes = [0u8; Self::CAPACITY];
        let mut len = 0;
        let mut utf8 = [0u8; 4];
        for c in text.nfkd() {
            let encoded = c.encode_utf8(&mut utf8).as_bytes();
            if len + encoded.len() > Self::CAPACITY {
                return None;
            }
            bytes[len..len + encoded.len()].copy_from_slice(encoded);
            len += encoded.len();
        }
        Some(Self { bytes, len })
    }

    /// The NFKD bytes, which are what PBKDF2 salts with.
    #[must_use]
    pub fn as_bytes(&self) -> &[u8] {
        &self.bytes[..self.len]
    }
}

redacted!(Passphrase);

#[cfg(test)]
#[path = "secret_tests.rs"]
mod tests;
