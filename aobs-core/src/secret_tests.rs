//! What can honestly be asserted about a secret type (`02-core.md` §2).
//!
//! Two of these are the ones the spec names as *testable, and therefore required*: the
//! compile-time `ZeroizeOnDrop` bound over every secret type, and the redaction of both
//! formatters. The rest are the constructors' boundaries.
//!
//! **Standing rule 9 is respected here by omission.** Nothing below claims to observe a
//! freed page, because nothing in safe Rust reliably can, and a test that appeared to prove
//! it would be worse than the absence.

use super::*;
use crate::bip39::Mnemonic;

/// The compile-time trait-bound assertion. A secret type that stops being `ZeroizeOnDrop` —
/// a hand-written `Drop` added, a derive lost in a merge — fails to *compile* here rather
/// than shipping.
///
/// **Adding a secret type means adding a row.** The list is the only thing that makes
/// "every" true, so `02-core.md` §2's wrapped list and this block are one decision in two
/// places. The three still unwritten — the decrypted backup plaintext, the 8 EFF backup
/// words, and the mnemonic's own text form if one ever exists — join it with the slice that
/// introduces them.
const fn assert_zeroize_on_drop<T: ZeroizeOnDrop>() {}

const _: () = {
    assert_zeroize_on_drop::<Csprng32>();
    assert_zeroize_on_drop::<Supplement>();
    assert_zeroize_on_drop::<Seed>();
    assert_zeroize_on_drop::<MasterXprv>();
    assert_zeroize_on_drop::<Dice>();
    assert_zeroize_on_drop::<Luma>();
    assert_zeroize_on_drop::<Entropy>();
    assert_zeroize_on_drop::<Passphrase>();
    assert_zeroize_on_drop::<Mnemonic>();
};

#[test]
fn both_formatters_are_redacted_for_every_type() {
    let material = [0xde, 0xad, 0xbe, 0xef];
    let mut thirty_two = [0u8; 32];
    thirty_two[..4].copy_from_slice(&material);
    let mut sixty_four = [0u8; 64];
    sixty_four[..4].copy_from_slice(&material);
    let mut seventy_eight = [0u8; 78];
    seventy_eight[..4].copy_from_slice(&material);

    let formatted: Vec<(String, String)> = vec![
        render(&Csprng32::new(thirty_two)),
        render(&Supplement::new(thirty_two)),
        render(&Seed::new(sixty_four)),
        render(&MasterXprv::new(seventy_eight)),
        render(&Dice::new(b"6533214")),
        render(&Luma::new(&material)),
        render(&Entropy::new(&thirty_two).expect("32 bytes fit")),
        render(&Passphrase::new("correct horse battery staple").expect("28 bytes fit")),
        render(
            &Mnemonic::from_entropy(&Entropy::new(&thirty_two).expect("32 fits"))
                .expect("32 bytes is a length"),
        ),
    ];

    for (debug, display) in formatted {
        assert_eq!(debug, "[redacted]");
        assert_eq!(display, "[redacted]");
    }
}

/// The redaction test the spec asks for in its own words: *the formatted output contains none
/// of the material*. Equality with `[redacted]` above already implies it; this states it
/// against material that would be legible if it leaked, which is the form a reader can check
/// at a glance.
#[test]
fn no_formatter_leaks_the_material() {
    let passphrase = Passphrase::new("correct horse battery staple").expect("28 bytes fit");
    let dice = Dice::new(b"6533214");

    for rendered in [
        format!("{passphrase:?}"),
        format!("{passphrase}"),
        format!("{dice:?}"),
        format!("{dice}"),
        // The shape secrets are usually seen in: nested inside a larger `Debug`.
        format!("{:?}", Some(&passphrase)),
    ] {
        assert!(!rendered.contains("horse"), "{rendered}");
        assert!(!rendered.contains("6533214"), "{rendered}");
    }
}

fn render<T: fmt::Debug + fmt::Display>(secret: &T) -> (String, String) {
    (format!("{secret:?}"), format!("{secret}"))
}

#[test]
fn the_exact_types_hand_back_what_they_were_given() {
    let bytes = [7u8; 32];
    assert_eq!(Csprng32::new(bytes).as_array(), &bytes);
    assert_eq!(Csprng32::new(bytes).as_bytes(), &bytes);
    assert_eq!(Supplement::new(bytes).as_array(), &bytes);
    assert_eq!(Supplement::new(bytes).as_bytes(), &bytes);
    assert_eq!(Seed::new([9u8; 64]).as_array(), &[9u8; 64]);
    assert_eq!(Seed::new([9u8; 64]).as_bytes(), &[9u8; 64]);

    assert_eq!(Csprng32::LEN, 32);
    assert_eq!(Supplement::LEN, 32);
    assert_eq!(Seed::LEN, 64);
}

#[test]
fn the_slice_types_allocate_at_the_length_they_are_handed() {
    assert_eq!(Dice::new(b"1234").as_bytes(), b"1234");
    assert_eq!(Dice::new(b"").as_bytes(), b"");
    assert_eq!(Luma::new(&[0u8; 4096]).as_bytes().len(), 4096);
    assert_eq!(Luma::new(&[]).as_bytes(), b"");
}

#[test]
fn entropy_takes_16_to_32_bytes_and_refuses_more() {
    assert_eq!(
        Entropy::new(&[1u8; 16]).expect("16 fits").as_bytes(),
        &[1u8; 16]
    );
    assert_eq!(
        Entropy::new(&[1u8; 32]).expect("32 fits").as_bytes(),
        &[1u8; 32]
    );
    assert!(Entropy::new(&[1u8; 33]).is_none());
    assert_eq!(Entropy::CAPACITY, 32);
}

/// `prefix` is total: an over-long length is clamped to the capacity rather than panicking.
/// Neither in-crate caller can reach the clamp — both compute 32 or below — so this is the
/// only place it is exercised, and it is exercised so the arm is not a guess.
#[test]
fn entropy_prefix_keeps_the_first_bytes_and_clamps() {
    let mut bytes = [0u8; 32];
    bytes[..4].copy_from_slice(&[1, 2, 3, 4]);
    assert_eq!(Entropy::prefix(bytes, 4).as_bytes(), &[1, 2, 3, 4]);
    assert_eq!(Entropy::prefix(bytes, 32).as_bytes(), &bytes);
    assert_eq!(Entropy::prefix(bytes, 99).as_bytes(), &bytes);
}

#[test]
fn a_passphrase_is_normalised_nfkd_at_construction() {
    // `㍍` — U+334D SQUARE MEETORU, the first character of the bip32JP passphrase — is a
    // *compatibility* character: NFKD decomposes it to the four katakana below, and NFD
    // leaves it alone. The buffer must hold the NFKD form, because that is the only form
    // PBKDF2 may see.
    let passphrase = Passphrase::new("\u{334D}").expect("fits");
    assert_eq!(
        passphrase.as_bytes(),
        "\u{30E1}\u{30FC}\u{30C8}\u{30EB}".as_bytes()
    );

    // Idempotence: normalising an already-normalised passphrase changes nothing.
    let twice = Passphrase::new("\u{30E1}\u{30FC}\u{30C8}\u{30EB}").expect("fits");
    assert_eq!(passphrase.as_bytes(), twice.as_bytes());
}

#[test]
fn a_passphrase_is_never_trimmed_and_empty_is_no_passphrase() {
    assert_eq!(Passphrase::new("a").expect("fits").as_bytes(), b"a");
    assert_eq!(Passphrase::new(" a").expect("fits").as_bytes(), b" a");
    assert_eq!(Passphrase::new("a ").expect("fits").as_bytes(), b"a ");
    assert_eq!(Passphrase::new("").expect("fits").as_bytes(), b"");
}

#[test]
fn the_passphrase_cap_is_128_bytes_of_the_normalised_form() {
    let ascii = "a".repeat(Passphrase::CAPACITY);
    assert_eq!(
        Passphrase::new(&ascii).expect("128 fits").as_bytes().len(),
        128
    );
    assert!(Passphrase::new(&"a".repeat(Passphrase::CAPACITY + 1)).is_none());

    // The cap applies after normalisation, not before: 40 of these are 120 bytes as typed
    // and 480 bytes NFKD, so the refusal has to come from the expanded form.
    assert!(Passphrase::new(&"\u{3350}".repeat(40)).is_none());
}
