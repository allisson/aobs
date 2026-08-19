//! BIP-39, in both directions (`02-core.md` §4, §5).
//!
//! Entropy to mnemonic, mnemonic to entropy, and mnemonic to the 512-bit seed. **English
//! only in v1**: CJK is excluded by roughly 100 MiB of glyph coverage against a 21 MiB
//! stack, and the Latin lists need diacritics the pinned `us` keymap cannot produce, so a
//! non-English mnemonic cannot be typed at all and the import screen names English before
//! the user starts.
//!
//! **Generation is 24 words, always** (ADR-0006). There is no length parameter and no
//! truncation branch anywhere in this file: [`crate::entropy::mix`] hands over 32 bytes and
//! 32 bytes is 24 words. Import accepts 12/15/18/21/24, which is the *only* reason the
//! shorter lengths appear below.
//!
//! What is deliberately *not* here: prefix matching and the 24-slot reducer
//! (`02-core.md` §4's import reducer, its own slice), and BIP-32 derivation from the seed.
//! [`Mnemonic`] carries word indices rather than text because that is the whole secret — the
//! wordlist itself is public, so a word looked up by index leaks nothing that
//! [`WORDS`] does not already publish.

mod english;

use core::fmt;

use bitcoin::hashes::{hmac::Hmac, hmac::HmacEngine, sha256, sha512, Hash, HashEngine};
use zeroize::{Zeroize, ZeroizeOnDrop, Zeroizing};

use crate::secret::{redacted, Entropy, Passphrase, Seed};

pub use english::WORDS;

/// The accepted word counts. Twelve through twenty-four in steps of three, and the length is
/// *inferred* from the count rather than declared (`02-core.md` §4).
pub const LENGTHS: [usize; 5] = [12, 15, 18, 21, 24];

/// The longest phrase, and so the size of every buffer here.
const MAX_WORDS: usize = 24;

/// Bits per word: the wordlist is 2048 words.
const BITS_PER_WORD: usize = 11;

/// `MAX_WORDS * 11` bits, rounded up to whole bytes — entropy plus checksum at 24 words.
const MAX_PACKED: usize = (MAX_WORDS * BITS_PER_WORD).div_ceil(8);

/// The longest English word is 8 bytes, and 24 of them take 23 separators.
const MAX_SENTENCE: usize = MAX_WORDS * 8 + (MAX_WORDS - 1);

/// PBKDF2 iterations, fixed by BIP-39.
const ITERATIONS: usize = 2048;

/// What a mnemonic can fail to be.
///
/// **None of these carries an `AOBS-R##` code, and that is deliberate** (`06-codes.md` §4): a
/// failed checksum on import refused nothing and discarded nothing — the words stay on
/// screen and the screen states what the check covers.
#[derive(Debug, PartialEq, Eq)]
pub enum Error {
    /// The entropy is not 16, 20, 24, 28 or 32 bytes. Carries the length that was offered.
    EntropyLength(usize),
    /// The word count is not one of [`LENGTHS`]. Carries the count that was offered.
    WordCount(usize),
    /// A word index is outside the 2048-word list. Carries the index that was offered.
    WordIndex(u16),
    /// The checksum does not cover the words.
    ///
    /// **The rejection cannot name the wrong word, and must not pretend to**: the checksum
    /// covers the phrase as a whole. An off-list word is unrepresentable — the reducer
    /// refuses the keystroke — so this can only ever mean real words in the wrong place.
    Checksum,
}

/// A BIP-39 mnemonic of 12, 15, 18, 21 or 24 words, whose checksum has already been checked.
///
/// Validity is the type's invariant rather than a method: every constructor either returns a
/// phrase whose checksum covers it or returns [`Error`]. That is what makes [`Self::entropy`]
/// and [`Self::seed`] infallible.
#[derive(Zeroize, ZeroizeOnDrop)]
pub struct Mnemonic {
    indices: [u16; MAX_WORDS],
    len: usize,
}

impl Mnemonic {
    /// Derives the phrase from entropy, appending BIP-39's `ENT/32` checksum bits.
    ///
    /// 32 bytes in is 24 words out. The shorter lengths exist for the restore path, not for
    /// a choice offered to the user.
    pub fn from_entropy(entropy: &Entropy) -> Result<Self, Error> {
        let bytes = entropy.as_bytes();
        let checksum_bits = checksum_bits(bytes.len()).ok_or(Error::EntropyLength(bytes.len()))?;

        let mut packed = Zeroizing::new([0u8; MAX_PACKED]);
        packed[..bytes.len()].copy_from_slice(bytes);
        packed[bytes.len()] = sha256::Hash::hash(bytes).to_byte_array()[0];

        let len = (bytes.len() * 8 + checksum_bits) / BITS_PER_WORD;
        let mut indices = [0u16; MAX_WORDS];
        for (word, slot) in indices.iter_mut().take(len).enumerate() {
            *slot = read_bits(&packed, word * BITS_PER_WORD);
        }
        Ok(Self { indices, len })
    }

    /// Accepts word indices — what the import reducer collects — and checks the checksum.
    ///
    /// The checksum is evaluated here and nowhere earlier: it covers the phrase as a whole,
    /// so there is nothing to say about a partial one.
    pub fn from_indices(words: &[u16]) -> Result<Self, Error> {
        if !LENGTHS.contains(&words.len()) {
            return Err(Error::WordCount(words.len()));
        }
        if let Some(&bad) = words.iter().find(|&&w| usize::from(w) >= WORDS.len()) {
            return Err(Error::WordIndex(bad));
        }

        let mut packed = Zeroizing::new([0u8; MAX_PACKED]);
        for (word, &index) in words.iter().enumerate() {
            write_bits(&mut packed, word * BITS_PER_WORD, index);
        }

        let entropy_len = entropy_len(words.len());
        let checksum_bits = entropy_len / 4;
        let expected = sha256::Hash::hash(&packed[..entropy_len]).to_byte_array()[0];
        let shift = 8 - checksum_bits;
        if packed[entropy_len] >> shift != expected >> shift {
            return Err(Error::Checksum);
        }

        let mut indices = [0u16; MAX_WORDS];
        indices[..words.len()].copy_from_slice(words);
        Ok(Self {
            indices,
            len: words.len(),
        })
    }

    /// How many words the phrase has: one of [`LENGTHS`].
    #[must_use]
    pub fn word_count(&self) -> usize {
        self.len
    }

    /// The word at `position`, or `None` past the end of the phrase.
    ///
    /// A `&'static str` out of the public wordlist, which is why this is not a secret escape
    /// hatch: the secret is the *sequence*, and the sequence stays in `self`.
    #[must_use]
    pub fn word(&self, position: usize) -> Option<&'static str> {
        (position < self.len).then(|| WORDS[usize::from(self.indices[position])])
    }

    /// Recovers the entropy the phrase encodes.
    #[must_use]
    pub fn entropy(&self) -> Entropy {
        let mut packed = Zeroizing::new([0u8; MAX_PACKED]);
        for (word, &index) in self.indices.iter().take(self.len).enumerate() {
            write_bits(&mut packed, word * BITS_PER_WORD, index);
        }
        let entropy_len = entropy_len(self.len);
        let mut bytes = Zeroizing::new([0u8; Entropy::CAPACITY]);
        bytes[..entropy_len].copy_from_slice(&packed[..entropy_len]);
        Entropy::prefix(*bytes, entropy_len)
    }

    /// The 512-bit seed: `PBKDF2-HMAC-SHA512(phrase, "mnemonic" ‖ passphrase, 2048)`.
    ///
    /// The phrase is assembled into a fixed buffer and **not** normalised: every word in
    /// [`WORDS`] is ASCII and therefore its own NFKD form, which `bip39_tests.rs` asserts
    /// over the whole list rather than leaving to inspection. The passphrase arrives already
    /// normalised — [`Passphrase`] does it at construction.
    #[must_use]
    pub fn seed(&self, passphrase: &Passphrase) -> Seed {
        let mut sentence = Zeroizing::new([0u8; MAX_SENTENCE]);
        let mut len = 0;
        for &index in self.indices.iter().take(self.len) {
            if len > 0 {
                sentence[len] = b' ';
                len += 1;
            }
            let word = WORDS[usize::from(index)].as_bytes();
            sentence[len..len + word.len()].copy_from_slice(word);
            len += word.len();
        }
        pbkdf2_hmac_sha512(&sentence[..len], passphrase.as_bytes())
    }
}

redacted!(Mnemonic);

/// The entropy length in bytes a phrase of `word_count` words encodes: `11` bits per word,
/// of which `ENT/32` are checksum, so `33` bits of phrase carry `4` bytes of entropy.
///
/// Only meaningful for a count in [`LENGTHS`], which is checked before every call.
fn entropy_len(word_count: usize) -> usize {
    word_count * BITS_PER_WORD / 33 * 4
}

/// BIP-39's `ENT/32` checksum length in bits, or `None` if `entropy_len` is not one of the
/// five accepted byte counts.
fn checksum_bits(entropy_len: usize) -> Option<usize> {
    matches!(entropy_len, 16 | 20 | 24 | 28 | 32).then_some(entropy_len * 8 / 32)
}

/// Reads the 11 bits at `from`, most significant first.
fn read_bits(packed: &[u8; MAX_PACKED], from: usize) -> u16 {
    let mut value = 0u16;
    for bit in from..from + BITS_PER_WORD {
        value = (value << 1) | u16::from(packed[bit / 8] >> (7 - bit % 8) & 1);
    }
    value
}

/// Writes the low 11 bits of `value` at `from`, most significant first.
fn write_bits(packed: &mut [u8; MAX_PACKED], from: usize, value: u16) {
    for offset in 0..BITS_PER_WORD {
        if value >> (BITS_PER_WORD - 1 - offset) & 1 == 1 {
            let bit = from + offset;
            packed[bit / 8] |= 1 << (7 - bit % 8);
        }
    }
}

/// `PBKDF2-HMAC-SHA512` at 2048 iterations with a 64-byte output — which is exactly one
/// block of SHA-512, so there is one block to derive and no block counter loop.
///
/// The loop is ours; the primitive is not. `bitcoin::hashes` is already in the tree, and
/// writing the outer PBKDF2 iteration over its HMAC is arithmetic with published
/// known-answer vectors, where pulling `pbkdf2` + `hmac` + `sha2` would put a second SHA-512
/// implementation in the closure for the same 15 lines.
///
/// One residue is named rather than papered over: `HmacEngine` holds the ipad/opad state
/// derived from the password for the whole loop, and the dependency does not zeroize it on
/// drop — nothing in this crate can reach inside it to do so. What covers it is what covers
/// every other stack residue in the process: `init_on_free=1` when the pages are freed
/// (`01-boot-layer.md` §5), which is why the app exits before the machine goes down.
///
/// The salt is *streamed* into the engine — `"mnemonic"`, then the normalised passphrase,
/// then the block index — so no concatenated copy of the passphrase is ever materialised.
fn pbkdf2_hmac_sha512(password: &[u8], salt: &[u8]) -> Seed {
    let base = HmacEngine::<sha512::Hash>::new(password);

    let mut engine = base.clone();
    engine.input(b"mnemonic");
    engine.input(salt);
    engine.input(&1u32.to_be_bytes());

    let mut block = Zeroizing::new(Hmac::from_engine(engine).to_byte_array());
    let mut out = Zeroizing::new(*block);
    for _ in 1..ITERATIONS {
        let mut engine = base.clone();
        engine.input(&block[..]);
        *block = Hmac::from_engine(engine).to_byte_array();
        for (out, block) in out.iter_mut().zip(block.iter()) {
            *out ^= block;
        }
    }
    Seed::new(*out)
}

#[cfg(test)]
#[path = "bip39_tests.rs"]
mod tests;
