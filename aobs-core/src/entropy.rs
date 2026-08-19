//! The entropy mixing construction (`02-core.md` §3, ADR-0008).
//!
//! ```text
//! supplement = SHA-256( "aobs/seed-entropy/v1" ‖ framed(camera_luma) ‖ framed(dice_ascii) )
//! entropy    = csprng_32 XOR supplement
//!
//! framed(x)  = u32_le(x.len()) ‖ x
//! ```
//!
//! **XOR, not concatenate-and-hash.** Every surveyed device concatenates and hashes, which
//! is only never-worse under the random-oracle assumption. XOR with any value independent
//! of the CSPRNG output preserves uniformity *unconditionally*, so "never worse" stops
//! being an assumption and becomes arithmetic — and against a backdoored CPU RNG whose
//! output the attacker knows, they still face the full entropy of `SHA-256(dice)`.
//! `entropy_tests.rs` carries that as a property test rather than as this paragraph: the
//! mixing function is injective in `csprng_32` for every fixed supplement.
//!
//! **The dice never *are* the entropy.** There is no replacement mode, no distribution
//! sanity-check, no minimum roll count and no bit counter, and a running hash of the rolls
//! is never displayed — each of those is rejected by name in `02-core.md` §3, and every one
//! of them would need code in this file to exist.
//!
//! Everything is taken by value. The spec's lifetime rule — *the dice buffer, the luma
//! plane, `csprng_32` and `supplement` are wiped as soon as `entropy` exists* — is
//! therefore the signature rather than a comment: all four are dropped, and so zeroized, by
//! the time [`mix`] returns.

use bitcoin::hashes::{sha256, Hash, HashEngine};
use zeroize::Zeroizing;

use crate::secret::{Csprng32, Dice, Entropy, Luma, Supplement};

/// The domain separation tag, versioned so a future construction cannot collide with this
/// one on the same inputs.
const TAG: &[u8] = b"aobs/seed-entropy/v1";

/// Mixes the optional supplements into the kernel CSPRNG's 32 bytes.
///
/// **With neither supplement present the XOR is skipped entirely** and the result is
/// `csprng_32` verbatim, byte for byte.
///
/// An **empty** supplement is *absent*, not a zero-length field: it contributes no framing
/// and no bytes, so a camera-less machine and a user who rolled nothing land on exactly the
/// unmixed case above. A supplement that is absent while the other is present is likewise
/// omitted from the hash rather than framed as empty — absence has no encoding here.
#[must_use]
pub fn mix(csprng: Csprng32, luma: Option<Luma>, dice: Option<Dice>) -> Entropy {
    let luma = luma.as_ref().map(Luma::as_bytes).filter(|b| !b.is_empty());
    let dice = dice.as_ref().map(Dice::as_bytes).filter(|b| !b.is_empty());

    // `Zeroizing` and not a bare array: this working copy holds the entropy for the length of
    // the XOR, and the copy that moves into `Entropy` is not the same bytes in memory.
    let mut out = Zeroizing::new(*csprng.as_array());
    if let Some(supplement) = supplement(luma, dice) {
        for (out, sup) in out.iter_mut().zip(supplement.as_bytes()) {
            *out ^= sup;
        }
    }
    Entropy::prefix(*out, Csprng32::LEN)
}

/// `SHA-256(TAG ‖ framed(luma) ‖ framed(dice))` over whichever fields are present, or
/// `None` when neither is.
fn supplement(luma: Option<&[u8]>, dice: Option<&[u8]>) -> Option<Supplement> {
    if luma.is_none() && dice.is_none() {
        return None;
    }

    let mut engine = sha256::Hash::engine();
    engine.input(TAG);
    for field in [luma, dice].into_iter().flatten() {
        // `as u32` is the spec's framing width. A supplement above 4 GiB is not
        // representable in it — a luma plane is megabytes and a dice string is bytes, so
        // the ceiling is unreachable rather than guarded, and a guard here would be an
        // arm no test could ever take.
        engine.input(&(field.len() as u32).to_le_bytes());
        engine.input(field);
    }
    Some(Supplement::new(
        sha256::Hash::from_engine(engine).to_byte_array(),
    ))
}

#[cfg(test)]
#[path = "entropy_tests.rs"]
mod tests;
