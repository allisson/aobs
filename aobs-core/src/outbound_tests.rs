//! `03-transport.md` §6, §8 and §9, and `05-testing-and-release.md` §3's *"the outbound
//! animation never refuses"*.
//!
//! **The claim is stated in characters, so the tests are too.** §9.1 gives a closed form for the
//! length of a part string, and its whole value is that it can be charged every field's `u32`
//! maximum — which no emitted part ever is, so a sweep over what the encoder happens to produce
//! would not be the bound. [`ceiling`] is that form; [`the_closed_form_predicts_what_ur_emits`] is
//! what earns the right to use it.

use proptest::prelude::*;

use super::{Animation, Symbol, ECC, MAX_FRAGMENT_LEN, MAX_VERSION, UR_TYPE};
use crate::ur::{Class, Outcome, Payload, Scanner};

/// v27's alphanumeric capacity at ECC L, measured (§9.2) — the budget every part must fit.
const V27_LOW_CAPACITY: usize = 2_132;

/// §1's largest realistic PSBT: the 10-in/2-out P2WPKH spend with `non_witness_utxo` attached.
const REALISTIC_PSBT: usize = 3_744;

/// A PSBT of `len` bytes that is not all one value, so a fragment's bytewords are not all the
/// same word either.
///
/// **Not a message.** §1's message is this wrapped in a CBOR byte string, and every figure in §9
/// is stated over the *message* — so the tests below take [`wrapped`] of this rather than its own
/// length wherever they compute one.
fn psbt(len: usize) -> Vec<u8> {
    (0..len).map(|i| (i % 251) as u8).collect()
}

/// The UR message [`Animation`] actually emits for a PSBT of `len` bytes: §1's CBOR byte string
/// around it, which is three bytes at every size §1's capacity table names.
fn wrapped(len: usize) -> usize {
    crate::ur::wrap(&psbt(len)).len()
}

/// The minimal CBOR width of a uint, in bytes including the head — `ur` writes every integer
/// field `as u32`, so this never exceeds 5.
fn width(value: u64) -> usize {
    match value {
        0..=23 => 1,
        24..=0xff => 2,
        0x100..=0xffff => 3,
        _ => 5,
    }
}

/// The CBOR byte-string header for a fragment of `len` bytes.
fn header(len: usize) -> usize {
    match len {
        0..=23 => 1,
        24..=0xff => 2,
        0x100..=0xffff => 3,
        _ => 5,
    }
}

/// §9.1's closed form: the length in characters of the part string `ur` emits.
///
/// ```text
/// 15 + digits(seq) + 1 + digits(seqLen) + 1
///    + 2·(1 + w(seq) + w(seqLen) + w(messageLen) + 5 + h(F) + F) + 8
/// ```
///
/// `15` is `"ur:crypto-psbt/"`, the `1`s are the two separators, the inner `1` is the five-element
/// array head, the `5` is the CRC-32 field (a four-byte string plus its head), and bytewords
/// minimal costs two characters a byte plus a doubled four-byte CRC.
fn length(seq: u64, sequence_count: u64, message_len: u64, fragment: usize) -> usize {
    let digits = |n: u64| n.to_string().len();
    15 + digits(seq)
        + 1
        + digits(sequence_count)
        + 1
        + 2 * (1
            + width(seq)
            + width(sequence_count)
            + width(message_len)
            + 5
            + header(fragment)
            + fragment)
        + 8
}

/// The largest part this stream can **ever** emit: every integer field at its `u32` maximum and
/// both decimals ten digits wide.
///
/// That is what makes this a bound rather than a sample. §9.2's own figures are computed this way,
/// and §9.3's third trap is why: the sequence number grows for as long as the animation runs, in
/// both the CBOR and the decimal prefix.
fn ceiling(sequence_count: u64, message_len: u64, fragment: usize) -> usize {
    length(u64::from(u32::MAX), sequence_count, message_len, fragment)
        // The `seqLen` decimal is the stream's own and never widens, but charge it the ten digits
        // §9.1 charges anyway: the point of the ceiling is that no field is read from the part.
        + (10 - sequence_count.to_string().len())
        + 2 * (5 - width(sequence_count))
        + 2 * (5 - width(message_len))
}

/// `ur`'s own fragment length: `ceil(len / ceil(len / max))`, which is **not** `max` except where
/// the even split lands on it exactly (§9.3's first trap).
fn fragment_length(len: usize, max: usize) -> usize {
    len.div_ceil(len.div_ceil(max))
}

/// §8: the emitted level is the one §6 *names*, not a floor `boostecl` is free to raise.
#[test]
fn the_error_correction_level_is_the_one_the_spec_names() {
    assert_eq!(ECC, qrcodegen::QrCodeEcc::Low);
}

/// §9's number, in the one place it is named.
#[test]
fn the_fragment_length_is_the_number_section_nine_settles() {
    assert_eq!(MAX_FRAGMENT_LEN, 960);
    assert_eq!(MAX_VERSION, 27);
}

/// The claim §9.1 rests on, checked character for character against what `ur` 0.5.2 actually
/// emits — across the widths that matter: `messageLen` at one, two and three bytes, the
/// fragment header at two and three, and `seq` from one digit upward.
#[test]
fn the_closed_form_predicts_what_ur_emits() {
    for len in [
        1,
        22,
        23,
        24,
        100,
        253,
        255,
        256,
        700,
        957,
        958,
        2_000,
        REALISTIC_PSBT,
        8_192,
    ] {
        for max in [64, 256, 960, 1_024] {
            let bytes = psbt(len);
            // §1's message, which is what every field of the part CBOR is about — the lengths
            // that straddle a CBOR width boundary are in the list twice for that reason: 22 and
            // 23 put the *wrapper* on either side of 24, and 253 and 255 on either side of 256.
            let message_len = wrapped(len);
            let mut animation = Animation::with_fragment_length(&bytes, max);
            let parts = animation.parts();
            if parts == 1 {
                // The single-part form has no `seq` component at all, so the closed form is not
                // about it. `the_single_part_form_carries_no_seq_component` is.
                continue;
            }
            let fragment = fragment_length(message_len, max);
            for seq in 1..=(parts as u64 + 2) {
                let part = animation.next_part();
                assert_eq!(
                    part.len(),
                    length(seq, parts as u64, message_len as u64, fragment),
                    "len={len} max={max} seq={seq}\n{part}"
                );
            }
        }
    }
}

/// §9.2's headline figure, reproduced: **2 013 characters against 2 132, 119 spare.**
#[test]
fn the_arithmetic_ceiling_at_the_settled_length_is_two_thousand_and_thirteen() {
    let ceiling = ceiling(u64::from(u32::MAX), u64::from(u32::MAX), MAX_FRAGMENT_LEN);
    assert_eq!(ceiling, 2_013);
    assert_eq!(V27_LOW_CAPACITY - ceiling, 119);
}

/// §9.2's rejected candidate, reproduced from the other side: **1 024 refuses at the ceiling.**
///
/// This is the whole reason 960 is the number, and it is the candidate a reader reaches for — so
/// the arithmetic that rejects it is asserted rather than described.
#[test]
fn the_round_candidate_above_it_would_refuse() {
    let ceiling = ceiling(u64::from(u32::MAX), u64::from(u32::MAX), 1_024);
    assert_eq!(ceiling, 2_141);
    assert!(ceiling > V27_LOW_CAPACITY, "{ceiling}");
}

/// §9.3's first trap: the worst case is a maximal *fragment*, not the largest message. Inside the
/// 64 KiB transport bound that message is 23 017 bytes, whose 24-way split leaves exactly 960.
#[test]
fn the_worst_message_inside_the_transport_bound_splits_on_the_fragment_length_exactly() {
    assert_eq!(fragment_length(23_017, MAX_FRAGMENT_LEN), MAX_FRAGMENT_LEN);
    // 64 KiB does not: the even split gives 950, which is why the largest message is not the
    // worst one.
    assert_eq!(fragment_length(64 * 1024, MAX_FRAGMENT_LEN), 950);
}

/// §6: **the smallest version that fits, never a fixed version.**
#[test]
fn a_small_payload_lands_on_a_small_version() {
    let mut animation = Animation::psbt(&psbt(20));
    let symbol = animation.next_symbol();
    assert!(symbol.version() < MAX_VERSION, "{}", symbol.version());
    assert_eq!(symbol.size(), 17 + 4 * u32::from(symbol.version()));
}

/// §1's capacity table, at the row §9 is priced against: the 3 744 B PSBT is **four parts**, and
/// every one of them is inside the cap.
#[test]
fn the_largest_realistic_psbt_is_four_parts_inside_the_cap() {
    let mut animation = Animation::psbt(&psbt(REALISTIC_PSBT));
    assert_eq!(animation.parts(), 4);
    for _ in 0..12 {
        assert!(animation.next_symbol().version() <= MAX_VERSION);
    }
}

/// §6: *"a single-frame payload is an animation of length one that happens not to move"* — and
/// the encoding rule that rides with it, **the single-part form with no `seq` component**.
#[test]
fn the_single_part_form_carries_no_seq_component() {
    let bytes = psbt(400);
    let mut animation = Animation::psbt(&bytes);
    assert_eq!(animation.parts(), 1);

    let text = animation.next_part();
    assert!(text.starts_with("UR:CRYPTO-PSBT/"), "{text}");
    // Two slashes would be `1-1`. One is the single-part form.
    assert_eq!(text.matches('/').count(), 1, "{text}");
    assert!(!text.contains("1-1/"), "{text}");

    // And it round-trips through the decoder that will read it.
    let (kind, decoded) = ::ur::ur::decode(&text).expect("we emitted it");
    assert_eq!(kind, ::ur::ur::Kind::SinglePart);
    assert_eq!(decoded, crate::ur::wrap(&bytes));
}

/// §1's message form, on the wire, in the one place it can be read without a decoder: the
/// single-part text's CBOR is `59 01 90` and then the PSBT.
///
/// **This is the byte-level statement of the whole of [#112](https://github.com/allisson/aobs/issues/112).**
/// A coordinator implementing BCR-2020-006 reads exactly this header and casts on it — Sparrow
/// throws a `ClassCastException` without it, Specter's `getData()` returns something that is not
/// the PSBT — so the three bytes are the interoperability property and not an encoding detail.
#[test]
fn the_message_is_the_registry_form_and_not_the_bare_psbt() {
    let bytes = psbt(400);
    let mut animation = Animation::psbt(&bytes);
    let (_, message) = ::ur::ur::decode(&animation.next_part()).expect("we emitted it");

    assert_eq!(&message[..3], &[0x59, 0x01, 0x90], "400 = 0x0190");
    assert_eq!(&message[3..], &bytes[..]);
    assert_eq!(crate::ur::unwrap(&message), Some(&bytes[..]));
}

/// The acceptance criterion no symmetry test in the tree could carry before: **the appliance can
/// read what it emits**, through the same [`Scanner`] a coordinator's animation goes through.
///
/// It is not the interoperability claim — that one is `docs/research/02-qr-transport-format.md`
/// §7's coordinator source plus `05-testing-and-release.md` §6.3's by-hand round trip, and this
/// test would pass under either convention. What it *is* is the thing that broke when only one
/// half moved, which is the failure mode [#112](https://github.com/allisson/aobs/issues/112) had
/// to design against.
#[test]
fn the_appliance_reads_what_it_emits() {
    for len in [1, 400, 957, 958, REALISTIC_PSBT] {
        let bytes = psbt(len);
        let mut animation = Animation::psbt(&bytes);
        let mut scanner = Scanner::new(Class::Psbt);

        // Two more than the fragment count, because past it the encoder is mixing and the scan
        // has to complete out of fountain parts rather than out of the first pass.
        let mut payload = None;
        for _ in 0..(animation.parts() + 2) {
            if let Outcome::Complete(Payload::Transaction(scanned)) =
                scanner.receive(&animation.next_part())
            {
                payload = Some(scanned);
                break;
            }
        }
        assert_eq!(payload.as_deref(), Some(&bytes[..]), "len={len}");
    }
}

/// The boundary §9.3 names: a message of exactly the fragment length is **one** fragment, and one
/// byte more is two — which collapses the symbol from v26 to v18.
///
/// §1's wrapper is what puts the boundary at a **957-byte PSBT** rather than a 960-byte one, and
/// that is the only thing about §9 the wrapper moved: the message it produces is still 960 bytes
/// and still 1 943 characters at v26.
#[test]
fn the_fragment_length_exactly_is_one_part_and_one_byte_more_is_two() {
    assert_eq!(wrapped(957), MAX_FRAGMENT_LEN);

    let mut one = Animation::psbt(&psbt(957));
    assert_eq!(one.parts(), 1);
    assert_eq!(one.next_part().len(), 1_943);
    assert_eq!(one.next_symbol().version(), 26);

    let mut two = Animation::psbt(&psbt(958));
    assert_eq!(two.parts(), 2);
    assert_eq!(two.next_part().len(), 1_017);
    assert_eq!(two.next_symbol().version(), 18);
}

/// §6: **fresh fountain parts, not a fixed set cycled.** Past the fragment count the encoder is
/// mixing, so the sequence numbers keep climbing and the parts keep differing.
#[test]
fn the_animation_generates_fresh_parts_rather_than_cycling() {
    let mut animation = Animation::psbt(&psbt(REALISTIC_PSBT));
    let first: Vec<String> = (0..4).map(|_| animation.next_part()).collect();
    let second: Vec<String> = (0..4).map(|_| animation.next_part()).collect();

    assert_ne!(first, second, "the second pass must not repeat the first");
    for (index, part) in second.iter().enumerate() {
        assert!(
            part.starts_with(&format!("UR:CRYPTO-PSBT/{}-4/", index + 5)),
            "{part}"
        );
    }
}

/// §8's uppercasing, which is what makes §7's sizing *in characters* hold: lowercase would fall
/// to byte mode and cost about a third of the capacity.
#[test]
fn the_text_is_uppercase_and_encodes_as_alphanumeric() {
    let mut animation = Animation::psbt(&psbt(REALISTIC_PSBT));
    let text = animation.next_part();
    assert_eq!(text, text.to_ascii_uppercase());
    assert!(text.starts_with("UR:CRYPTO-PSBT/"), "{text}");

    // The alphanumeric charset is `0-9 A-Z $%*+-./: ` and nothing else; a single byte-mode
    // segment here would be the defect this assertion exists for.
    let segments = qrcodegen::QrSegment::make_segments(&text);
    assert_eq!(segments.len(), 1);
    assert_eq!(segments[0].mode(), qrcodegen::QrSegmentMode::Alphanumeric);
}

/// §1: the deprecated `crypto-psbt` spelling, because Specter's scanner regexes match only
/// `UR:CRYPTO-*` and `UR:BYTES/`.
#[test]
fn the_ur_type_is_the_spelling_the_coordinators_read() {
    assert_eq!(UR_TYPE, "crypto-psbt");
}

/// The symbol is a matrix and the quiet zone is the painter's: outside the side length is light.
#[test]
fn the_matrix_is_square_and_outside_it_is_light() {
    let mut animation = Animation::psbt(&psbt(200));
    let symbol: Symbol = animation.next_symbol();
    let size = symbol.size();

    // The top-left finder pattern's corner module is dark in every QR code ever made.
    assert!(symbol.dark(0, 0));
    assert!(!symbol.dark(size, 0));
    assert!(!symbol.dark(0, size));
    assert!(!symbol.dark(u32::MAX, u32::MAX));
}

/// Every animation is an animation of at least one part, whatever the message.
#[test]
fn a_one_byte_message_is_still_an_animation() {
    let mut animation = Animation::psbt(&[0x70]);
    assert_eq!(animation.parts(), 1);
    assert_eq!(animation.next_symbol(), animation.next_symbol());
}

proptest! {
    /// `05-testing-and-release.md` §3: **the outbound animation never refuses.**
    ///
    /// For every PSBT length, at §9's fragment length, no part the animation can emit exceeds
    /// v27-L's budget — charging the sequence number its full `u32` width rather than the one it
    /// happens to be emitted at. This is the assertion that catches a fragment length raised
    /// without redoing §9.1's arithmetic, and it is why the length is a parameter.
    ///
    /// **Swept over the PSBT and not the message**, because that is the argument the caller
    /// hands [`Animation::psbt`]: §1's wrapper is inside, so a sweep over message lengths would
    /// be a sweep over an input nothing can supply — and would miss the top of the range, where
    /// a 64 KiB PSBT is a 65 541-byte message.
    #[test]
    fn no_emitted_part_can_exceed_the_cap(len in 1usize..=(64 * 1024)) {
        let message_len = wrapped(len);
        let fragment = fragment_length(message_len, MAX_FRAGMENT_LEN);
        let parts = message_len.div_ceil(fragment) as u64;
        let ceiling = ceiling(parts, message_len as u64, fragment);
        prop_assert!(
            ceiling <= V27_LOW_CAPACITY,
            "len={len} message_len={message_len} fragment={fragment} ceiling={ceiling}"
        );
    }

    /// And the same claim swept over other fragment lengths, which is what §9.4 says the
    /// parameter is for: it watches §9's own value hold while the neighbours it was chosen over
    /// come and go.
    #[test]
    fn the_settled_length_is_the_largest_aligned_one_that_clears_the_ceiling(
        max in 1usize..=1_200,
    ) {
        let ceiling = ceiling(u64::from(u32::MAX), u64::from(u32::MAX), max);
        prop_assert_eq!(
            ceiling <= V27_LOW_CAPACITY,
            max <= 1_019,
            "max={} ceiling={}", max, ceiling
        );
        // §9.2's tie-break: 960 is the largest 64-byte-aligned value that clears it.
        if max > MAX_FRAGMENT_LEN && max % 64 == 0 {
            prop_assert!(ceiling > V27_LOW_CAPACITY, "max={} ceiling={}", max, ceiling);
        }
    }

    /// The bound above is arithmetic; this is the encoder agreeing with it. Sampled rather than
    /// swept, because a v27 encode is ~2.4 ms and 64 Ki of them is not a unit test.
    #[test]
    fn the_encoder_produces_a_symbol_inside_the_cap(len in 1usize..=8_192) {
        let bytes = psbt(len);
        let mut animation = Animation::with_fragment_length(&bytes, MAX_FRAGMENT_LEN);
        for _ in 0..3 {
            prop_assert!(animation.next_symbol().version() <= MAX_VERSION);
        }
    }
}
