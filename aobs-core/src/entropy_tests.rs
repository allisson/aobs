//! The mixing vectors and the property that is the safety proof
//! (`05-testing-and-release.md` §2, §3).
//!
//! **The vectors are ours**, because the construction is ours: no published suite covers
//! `SHA-256("aobs/seed-entropy/v1" ‖ framed(luma) ‖ framed(dice))`. They were computed by a
//! second implementation in a second language — CPython's `hashlib.sha256` over the framing
//! written out by hand — so a defect would have to be made twice, in two languages, to pass.
//! Any of them can be re-derived in one line:
//!
//! ```text
//! python3 -c 'import hashlib,struct
//! TAG=b"aobs/seed-entropy/v1"
//! f=lambda x: struct.pack("<I",len(x))+x
//! c=bytes(range(32)); luma=bytes(range(0x80,0x90)); dice=b"6533214"
//! s=hashlib.sha256(TAG+f(luma)+f(dice)).digest()
//! print(bytes(a^b for a,b in zip(c,s)).hex())'
//! ```
//!
//! The property test is the part that carries weight the vectors cannot: XOR against a fixed
//! supplement is a bijection, so uniform in is uniform out — verified rather than argued.

use bitcoin::hex::FromHex;
use proptest::prelude::*;

use super::*;

/// `csprng_32` for every vector below: `00 01 02 … 1f`.
fn csprng() -> Csprng32 {
    let mut bytes = [0u8; Csprng32::LEN];
    for (index, byte) in bytes.iter_mut().enumerate() {
        *byte = u8::try_from(index).expect("32 fits in a u8");
    }
    Csprng32::new(bytes)
}

/// A stand-in luma plane: 16 bytes, `80 81 … 8f`.
fn luma() -> Luma {
    Luma::new(&[
        0x80, 0x81, 0x82, 0x83, 0x84, 0x85, 0x86, 0x87, 0x88, 0x89, 0x8a, 0x8b, 0x8c, 0x8d, 0x8e,
        0x8f,
    ])
}

/// Seven D6 rolls as the ASCII digits the user typed.
fn dice() -> Dice {
    Dice::new(b"6533214")
}

const CSPRNG_ALONE: &str = "000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f";
const DICE_ONLY: &str = "45b700b9d921a09cedbf5267705066210467daf27d41bdae7c3e5fd50de38ade";
const CAMERA_ONLY: &str = "122f218b09a0d255ad2a7f21068bd552bc895586d0cbcde725e61b20aee1e518";
const BOTH: &str = "a82aad935cfab236575648bb5a31dbb3dc9ddf8b8446166907f9a4fed6525d91";
const FIELDS_SWAPPED: &str = "ececf16a70f454c7657eaa3fb893275865d21ec1f7b96e6c7740143e1b3fb3e1";

fn unhex(hex: &str) -> Vec<u8> {
    Vec::<u8>::from_hex(hex).expect("a test vector is valid hex")
}

/// The vector the whole construction rests on: with **neither** supplement present the XOR is
/// skipped entirely and the entropy is the CSPRNG's bytes, verbatim.
#[test]
fn with_neither_supplement_the_entropy_is_the_csprng_byte_for_byte() {
    let entropy = mix(csprng(), None, None);
    assert_eq!(entropy.as_bytes(), unhex(CSPRNG_ALONE));
    assert_eq!(entropy.as_bytes(), csprng().as_bytes());
    assert_eq!(entropy.as_bytes().len(), 32);
}

#[test]
fn dice_only() {
    assert_eq!(
        mix(csprng(), None, Some(dice())).as_bytes(),
        unhex(DICE_ONLY)
    );
}

#[test]
fn camera_only() {
    assert_eq!(
        mix(csprng(), Some(luma()), None).as_bytes(),
        unhex(CAMERA_ONLY)
    );
}

#[test]
fn both_supplements() {
    assert_eq!(
        mix(csprng(), Some(luma()), Some(dice())).as_bytes(),
        unhex(BOTH)
    );
}

/// An empty dice string is **absent**, not a zero-length field: it frames nothing and
/// contributes nothing, so it lands on the unmixed case rather than on a fourth vector.
///
/// This is the one the spec calls out by name, and it is the difference between a user who
/// rolled nothing getting `getrandom`'s bytes and getting them hashed against a constant.
#[test]
fn an_empty_dice_string_is_absent_rather_than_a_zero_length_field() {
    assert_eq!(
        mix(csprng(), None, Some(Dice::new(b""))).as_bytes(),
        unhex(CSPRNG_ALONE)
    );
    // And absent alongside a present camera, where framing it as empty *would* show up.
    assert_eq!(
        mix(csprng(), Some(luma()), Some(Dice::new(b""))).as_bytes(),
        unhex(CAMERA_ONLY)
    );
}

/// The same for the camera: a machine with no camera skips it silently, and a zero-length
/// plane is the same thing as no plane.
#[test]
fn an_empty_luma_plane_is_absent_too() {
    assert_eq!(
        mix(csprng(), Some(Luma::new(&[])), None).as_bytes(),
        unhex(CSPRNG_ALONE)
    );
    assert_eq!(
        mix(csprng(), Some(Luma::new(&[])), Some(dice())).as_bytes(),
        unhex(DICE_ONLY)
    );
}

/// The camera is framed first and the dice second. Swapping which bytes arrive in which field
/// changes the supplement — which is what the two distinct types are for, and what stops a
/// later refactor from silently reordering the hash input.
#[test]
fn the_camera_is_framed_before_the_dice() {
    let swapped = mix(
        csprng(),
        Some(Luma::new(b"6533214")),
        Some(Dice::new(luma().as_bytes())),
    );
    assert_eq!(swapped.as_bytes(), unhex(FIELDS_SWAPPED));
    assert_ne!(swapped.as_bytes(), unhex(BOTH));
}

proptest! {
    /// **The safety proof.** The mixing function is injective in `csprng_32` for every fixed
    /// supplement: XOR against a constant is a bijection, so distinct CSPRNG outputs stay
    /// distinct and uniform in is uniform out. Stated as the stronger equality it follows
    /// from — the XOR of two results equals the XOR of their inputs — which pins the
    /// *structure* and not only the injectivity.
    #[test]
    fn mixing_is_injective_in_the_csprng_for_a_fixed_supplement(
        left: [u8; 32],
        right: [u8; 32],
        supplement_dice: Vec<u8>,
        supplement_luma: Vec<u8>,
    ) {
        let mixed_left = mix(
            Csprng32::new(left),
            Some(Luma::new(&supplement_luma)),
            Some(Dice::new(&supplement_dice)),
        );
        let mixed_right = mix(
            Csprng32::new(right),
            Some(Luma::new(&supplement_luma)),
            Some(Dice::new(&supplement_dice)),
        );

        prop_assert_eq!(left == right, mixed_left.as_bytes() == mixed_right.as_bytes());
        for (index, (out_left, out_right)) in
            mixed_left.as_bytes().iter().zip(mixed_right.as_bytes()).enumerate()
        {
            prop_assert_eq!(out_left ^ out_right, left[index] ^ right[index]);
        }
    }

    /// The supplement is a hash, so it is total over any input the shell can hand us: no
    /// length of dice string or luma plane makes `mix` do anything but return 32 bytes.
    #[test]
    fn mixing_is_total_and_always_yields_32_bytes(
        csprng: [u8; 32],
        dice: Vec<u8>,
        luma: Vec<u8>,
    ) {
        let entropy = mix(Csprng32::new(csprng), Some(Luma::new(&luma)), Some(Dice::new(&dice)));
        prop_assert_eq!(entropy.as_bytes().len(), 32);
    }
}
