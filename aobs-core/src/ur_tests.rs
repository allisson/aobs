//! `03-transport.md` §2, §3 and §4 — the payload classes, the four bounds and decoder
//! discipline.
//!
//! **Every stream here is built rather than recorded**, because the cases that matter are the
//! ones no honest encoder emits: a `seqLen` of `0xFFFFFFFF`, a part whose `messageLen`
//! disagrees with the stream it joined, a well-formed animation that never completes. That is
//! why `corpus_tests.rs`'s `part` writes the CBOR by hand — `ur::Encoder` cannot be asked for a
//! part that lies.

use super::{
    Announced, Class, Discard, Outcome, Payload, Refusal, Scanner, MAX_ADDRESS_LEN,
    MAX_MESSAGE_LEN, MAX_SEQUENCE_COUNT, PART_BUDGET,
};

// --- fixtures ----------------------------------------------------------------------------
//
// The part builders live in `corpus_tests.rs` alongside the transport corpus that also uses
// them: `03-transport.md`'s cases need parts no honest encoder emits, and one hand-written CBOR
// writer serving both tables is one fewer place for the two to drift apart.

use proptest::prelude::*;

use crate::corpus::{checksum_of, part, raw_part, single, stream, transport_message as message};

/// Feed a whole animation and hand back the last outcome.
fn feed(scanner: &mut Scanner, symbols: &[String]) -> Outcome {
    let mut last = Outcome::Discarded(Discard::Unreadable);
    for symbol in symbols {
        last = scanner.receive(symbol);
    }
    last
}

// --- §2: the payload classes -------------------------------------------------------------

#[test]
fn the_signing_prompt_accepts_all_three_transaction_spellings() {
    for ur_type in ["crypto-psbt", "psbt", "bytes"] {
        let payload = message(3_000);
        let mut scanner = Scanner::new(Class::Psbt);
        let parts = stream(ur_type, &payload, 1_000, 3);
        assert_eq!(
            feed(&mut scanner, &parts),
            Outcome::Complete(Payload::Transaction(payload)),
            "{ur_type}"
        );
    }
}

#[test]
fn the_signing_prompt_accepts_the_single_part_form() {
    let payload = message(300);
    let mut scanner = Scanner::new(Class::Psbt);
    assert_eq!(
        scanner.receive(&single("crypto-psbt", &payload)),
        Outcome::Complete(Payload::Transaction(payload))
    );
}

#[test]
fn the_signing_prompt_refuses_plain_text_naming_both_sides() {
    let mut scanner = Scanner::new(Class::Psbt);
    let outcome = scanner.receive("bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4");
    assert_eq!(
        outcome,
        Outcome::Refused(Refusal::WrongClass {
            expected: Class::Psbt,
            announced: Announced::PlainText,
        })
    );
    let Outcome::Refused(refusal) = outcome else {
        panic!("refused")
    };
    assert_eq!(refusal.code(), "AOBS-R10");
    let reason = refusal.reason();
    assert!(reason.contains("plain text"), "{reason}");
    assert!(reason.contains("transaction to sign"), "{reason}");
}

#[test]
fn the_signing_prompt_refuses_a_ur_type_we_do_not_use() {
    let mut scanner = Scanner::new(Class::Psbt);
    assert_eq!(
        scanner.receive(&single("crypto-account", b"whatever")),
        Outcome::Refused(Refusal::WrongClass {
            expected: Class::Psbt,
            announced: Announced::ForeignUr,
        })
    );
}

#[test]
fn the_type_is_read_before_anything_decodes_it() {
    // §3's fourth bound. The body here is not bytewords at all, so a class check that ran
    // after decoding would report a bad scan and never reach the wrong-class refusal.
    let mut scanner = Scanner::new(Class::Psbt);
    assert_eq!(
        scanner.receive("ur:crypto-account/1-2/!!!not!!!bytewords!!!"),
        Outcome::Refused(Refusal::WrongClass {
            expected: Class::Psbt,
            announced: Announced::ForeignUr,
        })
    );
}

#[test]
fn the_address_prompt_accepts_one_plain_text_symbol() {
    let mut scanner = Scanner::new(Class::Address);
    let address = "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4";
    assert_eq!(
        scanner.receive(address),
        Outcome::Complete(Payload::Address(address.to_owned()))
    );
}

#[test]
fn the_address_prompt_accepts_a_bip21_uri_because_that_is_plain_text_too() {
    let mut scanner = Scanner::new(Class::Address);
    let uri = "bitcoin:bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4?amount=0.1";
    assert_eq!(
        scanner.receive(uri),
        Outcome::Complete(Payload::Address(uri.to_owned()))
    );
}

#[test]
fn the_address_prompt_refuses_every_ur_form() {
    let mut scanner = Scanner::new(Class::Address);
    for symbol in [
        single("crypto-psbt", b"transaction"),
        single("bytes", b"backup"),
        part(1, 2, 40, 7, b"twenty bytes of data"),
    ] {
        let outcome = scanner.receive(&symbol);
        assert!(
            matches!(
                outcome,
                Outcome::Refused(Refusal::WrongClass {
                    expected: Class::Address,
                    ..
                })
            ),
            "{symbol}: {outcome:?}"
        );
    }
}

#[test]
fn the_address_prompt_drops_text_it_cannot_accept_without_naming_a_class() {
    // §2 says *≤ 256 bytes, printable ASCII, or rejected*, and neither failure is a
    // wrong-class payload — there is no class these bytes belong to, so claiming one would be
    // a false statement about what was scanned.
    let mut scanner = Scanner::new(Class::Address);
    for symbol in [
        "a".repeat(MAX_ADDRESS_LEN + 1),
        "bc1q\u{7f}abc".to_owned(),
        "bc1q\tabc".to_owned(),
        "bc1qÿabc".to_owned(),
        String::new(),
    ] {
        assert_eq!(
            scanner.receive(&symbol),
            Outcome::Discarded(Discard::Unreadable),
            "{symbol:?}"
        );
    }
}

#[test]
fn the_address_prompt_accepts_the_length_bound_exactly() {
    let mut scanner = Scanner::new(Class::Address);
    let address = "a".repeat(MAX_ADDRESS_LEN);
    assert_eq!(
        scanner.receive(&address),
        Outcome::Complete(Payload::Address(address))
    );
}

#[test]
fn the_restore_prompt_accepts_single_part_bytes_only() {
    let backup = message(67);
    let mut scanner = Scanner::new(Class::Backup);
    assert_eq!(
        scanner.receive(&single("bytes", &backup)),
        Outcome::Complete(Payload::Backup(backup))
    );
}

#[test]
fn the_restore_prompt_refuses_a_multi_part_bytes_stream() {
    // §7: the multi-part path is forbidden by rule on this prompt, which is what keeps the
    // restore path out of the fountain decoder entirely.
    let mut scanner = Scanner::new(Class::Backup);
    let parts = stream("bytes", &message(3_000), 1_000, 3);
    assert_eq!(
        feed(&mut scanner, &parts),
        Outcome::Refused(Refusal::WrongClass {
            expected: Class::Backup,
            announced: Announced::Bytes,
        })
    );
}

#[test]
fn the_restore_prompt_refuses_a_transaction_on_the_type_string() {
    // §7: *"a PSBT scanned at the restore prompt is rejected on the type string rather than on
    // a crypto failure"*.
    let mut scanner = Scanner::new(Class::Backup);
    let outcome = scanner.receive(&single("crypto-psbt", b"transaction"));
    assert_eq!(
        outcome,
        Outcome::Refused(Refusal::WrongClass {
            expected: Class::Backup,
            announced: Announced::Transaction,
        })
    );
    let Outcome::Refused(refusal) = outcome else {
        panic!("refused")
    };
    let reason = refusal.reason();
    assert!(reason.contains("transaction"), "{reason}");
    assert!(reason.contains("encrypted backup"), "{reason}");
}

#[test]
fn uppercase_ur_text_is_accepted() {
    // §1 requires we *emit* uppercase for Specter's scanner regexes, so a coordinator that
    // does the same is the ordinary case and not an edge one.
    let payload = message(300);
    let mut scanner = Scanner::new(Class::Psbt);
    assert_eq!(
        scanner.receive(&single("crypto-psbt", &payload).to_uppercase()),
        Outcome::Complete(Payload::Transaction(payload))
    );
}

#[test]
fn a_symbol_that_is_not_a_ur_and_not_an_address_is_dropped_at_every_prompt() {
    for class in [Class::Psbt, Class::Address, Class::Backup] {
        let mut scanner = Scanner::new(class);
        assert_eq!(
            scanner.receive(&"x".repeat(MAX_ADDRESS_LEN + 1)),
            Outcome::Discarded(Discard::Unreadable),
            "{class:?}"
        );
    }
}

#[test]
fn a_ur_with_no_type_is_dropped() {
    let mut scanner = Scanner::new(Class::Psbt);
    for symbol in ["ur:", "ur:bytes", "ur:/1-2/aeae"] {
        assert_eq!(
            scanner.receive(symbol),
            Outcome::Discarded(Discard::Unreadable),
            "{symbol}"
        );
    }
}

// --- §3: the four bounds -----------------------------------------------------------------

#[test]
fn a_frame_declaring_seq_len_0xffffffff_is_dropped() {
    // The 34 GB claim (§1). It is dropped on the decimal in the URI path, before a single
    // byte is bytewords-decoded, which is why the body below need not even be valid.
    let mut scanner = Scanner::new(Class::Psbt);
    assert_eq!(
        scanner.receive("ur:crypto-psbt/1-4294967295/aeaeaeae"),
        Outcome::Discarded(Discard::SequenceCountTooLarge)
    );
}

#[test]
fn the_sequence_count_bound_holds_at_its_edge() {
    let mut scanner = Scanner::new(Class::Psbt);
    assert_eq!(
        scanner.receive(&part(
            1,
            MAX_SEQUENCE_COUNT + 1,
            40,
            7,
            b"twenty bytes of data"
        )),
        Outcome::Discarded(Discard::SequenceCountTooLarge)
    );

    // At the bound itself the part reaches the decoder and is accepted.
    let mut scanner = Scanner::new(Class::Psbt);
    let payload = message(MAX_SEQUENCE_COUNT * 1_000);
    let parts = stream("crypto-psbt", &payload, 1_000, MAX_SEQUENCE_COUNT);
    assert_eq!(
        feed(&mut scanner, &parts),
        Outcome::Complete(Payload::Transaction(payload))
    );
}

#[test]
fn a_sequence_count_or_number_of_zero_is_dropped() {
    let mut scanner = Scanner::new(Class::Psbt);
    for symbol in [
        part(1, 0, 40, 7, b"twenty bytes of data"),
        part(0, 2, 40, 7, b"twenty bytes of data"),
    ] {
        assert_eq!(
            scanner.receive(&symbol),
            Outcome::Discarded(Discard::SequenceCountTooLarge),
            "{symbol}"
        );
    }
}

#[test]
fn indices_that_are_not_two_decimals_are_dropped() {
    let mut scanner = Scanner::new(Class::Psbt);
    for symbol in [
        "ur:crypto-psbt/1/aeaeaeae",
        "ur:crypto-psbt/1-/aeaeaeae",
        "ur:crypto-psbt/-2/aeaeaeae",
        "ur:crypto-psbt/one-two/aeaeaeae",
        "ur:crypto-psbt/1-99999999999999999999999999/aeaeaeae",
        "ur:crypto-psbt/1--2/aeaeaeae",
    ] {
        assert!(
            matches!(scanner.receive(symbol), Outcome::Discarded(_)),
            "{symbol}"
        );
    }
}

#[test]
fn the_message_length_bound_holds_at_its_edge() {
    // §5's *"the 64 KiB boundary at exactly the limit and one byte over"*. The fragment length
    // is the same on both sides so that `messageLen` is the only field that differs — at
    // 1 000 bytes per fragment the one-over case would trip the `seqLen` bound first.
    let exact = message(MAX_MESSAGE_LEN);
    let mut scanner = Scanner::new(Class::Psbt);
    let parts = stream("crypto-psbt", &exact, 2_048, 32);
    assert_eq!(
        feed(&mut scanner, &parts),
        Outcome::Complete(Payload::Transaction(exact))
    );

    let over = message(MAX_MESSAGE_LEN + 1);
    let mut scanner = Scanner::new(Class::Psbt);
    let parts = stream("crypto-psbt", &over, 2_048, 33);
    assert_eq!(
        feed(&mut scanner, &parts),
        Outcome::Discarded(Discard::MessageTooLarge)
    );
}

#[test]
fn a_declared_message_length_above_the_bound_never_reaches_the_decoder() {
    let mut scanner = Scanner::new(Class::Psbt);
    assert_eq!(
        scanner.receive(&part(1, 2, MAX_MESSAGE_LEN + 1, 7, b"twenty bytes of data")),
        Outcome::Discarded(Discard::MessageTooLarge)
    );
    assert_eq!(
        scanner.receive(&part(1, 2, 0, 7, b"twenty bytes of data")),
        Outcome::Discarded(Discard::MessageTooLarge)
    );
}

#[test]
fn a_single_part_message_above_the_bound_is_dropped() {
    let mut scanner = Scanner::new(Class::Psbt);
    assert_eq!(
        scanner.receive(&single("crypto-psbt", &message(MAX_MESSAGE_LEN + 1))),
        Outcome::Discarded(Discard::MessageTooLarge)
    );
}

#[test]
fn a_stream_that_never_completes_is_refused_when_the_part_budget_is_spent() {
    // §3: `seqLen` bounds the claim, this bounds the work. Fountain coding lets a hostile
    // animation feed well-formed parts forever, so the counter is on parts actually received.
    //
    // Every part here is sequence 1 of a 4-part stream: well-formed, consistent with the
    // stream's identity, and carrying one fragment that never completes it.
    let payload = message(4_000);
    let first = stream("crypto-psbt", &payload, 1_000, 1);
    let mut scanner = Scanner::new(Class::Psbt);

    for i in 0..PART_BUDGET {
        assert_eq!(
            scanner.receive(&first[0]),
            Outcome::Received { parts: 1, of: 4 },
            "part {i}"
        );
    }
    let outcome = scanner.receive(&first[0]);
    assert_eq!(outcome, Outcome::Refused(Refusal::PartBudgetSpent));
    let Outcome::Refused(refusal) = outcome else {
        panic!("refused")
    };
    assert_eq!(refusal.code(), "AOBS-R11");
    assert!(refusal.reason().contains("1,024"), "{}", refusal.reason());
}

#[test]
fn a_stream_that_completes_inside_the_budget_is_not_refused() {
    let payload = message(3_000);
    let mut scanner = Scanner::new(Class::Psbt);
    let parts = stream("crypto-psbt", &payload, 1_000, 3);
    assert_eq!(
        feed(&mut scanner, &parts),
        Outcome::Complete(Payload::Transaction(payload))
    );
}

#[test]
fn a_symbol_longer_than_the_message_bound_can_describe_is_dropped_unread() {
    // The `messageLen` bound applied to the only form the symbol has before we are allowed to
    // decode it. Without it the bytewords allocation happens before the bound that governs it
    // can be read, which is the one thing §3's ordering is about.
    let mut scanner = Scanner::new(Class::Psbt);
    let huge = format!("ur:crypto-psbt/1-2/{}", "ae".repeat(MAX_MESSAGE_LEN + 64));
    assert_eq!(
        scanner.receive(&huge),
        Outcome::Discarded(Discard::Unreadable)
    );
}

// --- §4: decoder discipline --------------------------------------------------------------

#[test]
fn a_part_disagreeing_on_sequence_count_is_dropped_and_the_stream_survives() {
    let payload = message(4_000);
    let parts = stream("crypto-psbt", &payload, 1_000, 4);
    let mut scanner = Scanner::new(Class::Psbt);

    assert_eq!(
        scanner.receive(&parts[0]),
        Outcome::Received { parts: 1, of: 4 }
    );
    assert_eq!(
        scanner.receive(&part(1, 8, 4_000, 7, &[0u8; 1_000])),
        Outcome::Discarded(Discard::ForeignPart)
    );
    assert_eq!(
        feed(&mut scanner, &parts[1..]),
        Outcome::Complete(Payload::Transaction(payload))
    );
}

#[test]
fn a_part_disagreeing_on_message_length_or_checksum_is_dropped() {
    let payload = message(4_000);
    let parts = stream("crypto-psbt", &payload, 1_000, 4);

    for wrong in [
        part(2, 4, 4_001, checksum_of(&parts[0]), &[0u8; 1_000]),
        part(
            2,
            4,
            4_000,
            checksum_of(&parts[0]).wrapping_add(1),
            &[0u8; 1_000],
        ),
    ] {
        let mut scanner = Scanner::new(Class::Psbt);
        assert_eq!(
            scanner.receive(&parts[0]),
            Outcome::Received { parts: 1, of: 4 }
        );
        assert_eq!(
            scanner.receive(&wrong),
            Outcome::Discarded(Discard::ForeignPart),
            "{wrong}"
        );
        assert_eq!(
            feed(&mut scanner, &parts[1..]),
            Outcome::Complete(Payload::Transaction(payload.clone()))
        );
    }
}

#[test]
fn two_scanners_share_nothing() {
    // §4's first requirement is a fresh decoder on every entry to the scanning screen, and
    // what core can offer is that a decoder is only reachable through `Scanner::new`: there is
    // no reset, no `Default` and no `Clone`, so a stale pool has nowhere to come from.
    let payload = message(4_000);
    let parts = stream("crypto-psbt", &payload, 1_000, 4);

    let mut abandoned = Scanner::new(Class::Psbt);
    assert_eq!(
        feed(&mut abandoned, &parts[..2]),
        Outcome::Received { parts: 2, of: 4 }
    );

    let mut fresh = Scanner::new(Class::Psbt);
    assert_eq!(
        feed(&mut fresh, &parts[2..]),
        Outcome::Received { parts: 2, of: 4 },
        "the fresh scanner started from nothing"
    );
}

#[test]
fn a_scanner_that_finished_is_not_a_decoder_any_more() {
    let payload = message(300);
    let mut scanner = Scanner::new(Class::Psbt);
    assert_eq!(
        scanner.receive(&single("crypto-psbt", &payload)),
        Outcome::Complete(Payload::Transaction(payload))
    );
    assert_eq!(
        scanner.receive(&single("crypto-psbt", b"anything")),
        Outcome::Discarded(Discard::Spent)
    );
}

#[test]
fn a_scanner_that_spent_its_budget_stays_refused() {
    let payload = message(4_000);
    let first = stream("crypto-psbt", &payload, 1_000, 1);
    let mut scanner = Scanner::new(Class::Psbt);
    for _ in 0..PART_BUDGET {
        scanner.receive(&first[0]);
    }
    assert_eq!(
        scanner.receive(&first[0]),
        Outcome::Refused(Refusal::PartBudgetSpent)
    );
    assert_eq!(
        scanner.receive(&first[0]),
        Outcome::Discarded(Discard::Spent)
    );
}

#[test]
fn a_part_that_does_not_decode_is_dropped_without_ending_the_scan() {
    let payload = message(4_000);
    let parts = stream("crypto-psbt", &payload, 1_000, 4);
    let mut scanner = Scanner::new(Class::Psbt);

    for symbol in [
        "ur:crypto-psbt/1-4/zzzz".to_owned(),
        "ur:crypto-psbt/1-4/ae".to_owned(),
        part(1, 4, 4_000, 7, &[]),
    ] {
        assert!(
            matches!(scanner.receive(&symbol), Outcome::Discarded(_)),
            "{symbol}"
        );
    }
    assert_eq!(
        feed(&mut scanner, &parts),
        Outcome::Complete(Payload::Transaction(payload))
    );
}

// --- progress ----------------------------------------------------------------------------

#[test]
fn progress_counts_resolved_fragments_over_the_clamped_sequence_count() {
    // 04-screens.md §11.1: the denominator is attacker-supplied and clamped, so the worst a
    // hostile stream buys is a wrong denominator on a bounded display.
    let payload = message(4_000);
    let parts = stream("crypto-psbt", &payload, 1_000, 3);
    let mut scanner = Scanner::new(Class::Psbt);

    assert_eq!(
        scanner.receive(&parts[0]),
        Outcome::Received { parts: 1, of: 4 }
    );
    assert_eq!(
        scanner.receive(&parts[1]),
        Outcome::Received { parts: 2, of: 4 }
    );
    assert_eq!(
        scanner.receive(&parts[2]),
        Outcome::Received { parts: 3, of: 4 }
    );
}

#[test]
fn a_repeated_part_does_not_advance_progress_but_does_spend_budget() {
    let payload = message(4_000);
    let parts = stream("crypto-psbt", &payload, 1_000, 1);
    let mut scanner = Scanner::new(Class::Psbt);

    assert_eq!(
        scanner.receive(&parts[0]),
        Outcome::Received { parts: 1, of: 4 }
    );
    assert_eq!(
        scanner.receive(&parts[0]),
        Outcome::Received { parts: 1, of: 4 }
    );
}

// --- the registry ------------------------------------------------------------------------

#[test]
fn the_codes_are_the_two_the_registry_names() {
    let codes: Vec<&str> = Refusal::ALL.iter().map(|refusal| refusal.code()).collect();
    assert_eq!(codes, ["AOBS-R10", "AOBS-R11"]);
}

#[test]
fn every_wrong_class_pair_names_both_sides() {
    for expected in [Class::Psbt, Class::Address, Class::Backup] {
        for announced in [
            Announced::Transaction,
            Announced::Bytes,
            Announced::ForeignUr,
            Announced::PlainText,
        ] {
            let reason = Refusal::WrongClass {
                expected,
                announced,
            }
            .reason();
            assert!(
                reason.contains(expected.wanted()),
                "{expected:?}/{announced:?}: {reason}"
            );
            assert!(
                reason.contains(announced.named()),
                "{expected:?}/{announced:?}: {reason}"
            );
        }
    }
}

#[test]
fn no_reason_is_empty_and_none_ends_without_a_stop() {
    for refusal in Refusal::ALL {
        let reason = refusal.reason();
        assert!(!reason.is_empty(), "{refusal:?}");
        assert!(reason.ends_with('.'), "{refusal:?}: {reason}");
    }
}

// --- the property ------------------------------------------------------------------------

proptest! {
    /// **No sequence of scanned symbols produces an outcome outside the transport bounds.**
    ///
    /// This is the same claim `fuzz/fuzz_targets/fountain_decode.rs` asserts, in the form that
    /// runs in `cargo test`: the fuzz target reaches shapes a strategy will not, and this
    /// reaches every shape on every commit rather than in a nightly job. Both exist because
    /// `05-testing-and-release.md` §1 says coverage is necessary and not sufficient — a clamp
    /// that stopped clamping would still be *covered*.
    #[test]
    fn no_sequence_of_symbols_escapes_the_transport_bounds(
        expected in class(),
        symbols in prop::collection::vec(symbol(), 0..40),
    ) {
        let mut scanner = Scanner::new(expected);
        let mut accepted = 0usize;

        for symbol in &symbols {
            match scanner.receive(symbol) {
                Outcome::Received { parts, of } => {
                    accepted += 1;
                    prop_assert!(of <= MAX_SEQUENCE_COUNT, "seqLen {of} passed the clamp");
                    prop_assert!(parts <= of, "{parts} fragments out of {of}");
                    prop_assert!(accepted <= PART_BUDGET, "{accepted} parts past the budget");
                }
                Outcome::Complete(Payload::Transaction(bytes) | Payload::Backup(bytes)) => {
                    prop_assert!(!bytes.is_empty());
                    prop_assert!(bytes.len() <= MAX_MESSAGE_LEN, "{} bytes", bytes.len());
                }
                Outcome::Complete(Payload::Address(text)) => {
                    prop_assert!(!text.is_empty());
                    prop_assert!(text.len() <= MAX_ADDRESS_LEN, "{} bytes", text.len());
                    prop_assert!(text.bytes().all(|byte| (0x20..=0x7e).contains(&byte)));
                }
                Outcome::Discarded(_) | Outcome::Refused(_) => {}
            }
        }
    }
}

fn class() -> impl Strategy<Value = Class> {
    prop_oneof![Just(Class::Psbt), Just(Class::Address), Just(Class::Backup),]
}

/// Three kinds of symbol in the proportions that matter: parts from one honest animation, parts
/// forged field by field, and text that is not a UR at all.
///
/// The honest stream is what lets a forged part be *near-miss* rather than obviously wrong — a
/// generator producing only garbage would never establish a stream for a foreign part to
/// disagree with.
fn symbol() -> impl Strategy<Value = String> {
    let honest = prop::sample::select(stream("crypto-psbt", &message(4_000), 1_000, 12));
    let forged = (
        0usize..70,
        0usize..70,
        0usize..70_000usize,
        any::<u32>(),
        0usize..40,
    )
        .prop_map(|(seq, count, message_len, checksum, fragment)| {
            part(seq, count, message_len, checksum, &vec![0xab; fragment])
        });
    let text = "(ur:)?[ -~]{0,60}".prop_map(String::from);

    prop_oneof![honest, forged, text]
}

// --- the header reader -------------------------------------------------------------------
//
// `read_header` is ours rather than the dependency's — `fountain::Part` cannot be constructed
// outside `ur` — so every arm of it is a case here. What it must never do is *accept* something
// `minicbor` would read differently; being stricter is free, because a part it turns down is a
// part the fountain decoder never sees.

#[test]
fn a_part_whose_cbor_is_not_a_five_element_array_is_dropped() {
    let mut scanner = Scanner::new(Class::Psbt);
    assert_eq!(
        scanner.receive(&raw_part(
            "1-2",
            &[0x84, 0x01, 0x02, 0x18, 0x28, 0x07, 0x40]
        )),
        Outcome::Discarded(Discard::NotAPart)
    );
    assert_eq!(
        scanner.receive(&raw_part("1-2", &[])),
        Outcome::Discarded(Discard::NotAPart)
    );
}

#[test]
fn a_part_whose_cbor_contradicts_its_own_indices_is_dropped() {
    // The URI says part 1 of 2 and the CBOR says part 3 of 2. The dependency checks this too;
    // ours runs first, which is what makes the pinned identity exact rather than approximate.
    let mut scanner = Scanner::new(Class::Psbt);
    assert_eq!(
        scanner.receive(&raw_part(
            "1-2",
            &[0x85, 0x03, 0x02, 0x18, 0x28, 0x07, 0x40]
        )),
        Outcome::Discarded(Discard::NotAPart)
    );
    assert_eq!(
        scanner.receive(&raw_part(
            "1-2",
            &[0x85, 0x01, 0x04, 0x18, 0x28, 0x07, 0x40]
        )),
        Outcome::Discarded(Discard::NotAPart)
    );
}

#[test]
fn a_header_field_that_is_not_an_integer_is_dropped() {
    let mut scanner = Scanner::new(Class::Psbt);
    // A byte string where `seq` belongs.
    assert_eq!(
        scanner.receive(&raw_part(
            "1-2",
            &[0x85, 0x40, 0x02, 0x18, 0x28, 0x07, 0x40]
        )),
        Outcome::Discarded(Discard::NotAPart)
    );
    // An integer header promising more bytes than the array carries.
    assert_eq!(
        scanner.receive(&raw_part("1-2", &[0x85, 0x01, 0x02, 0x1a, 0x00])),
        Outcome::Discarded(Discard::NotAPart)
    );
}

#[test]
fn the_widest_integer_encoding_is_read_rather_than_refused() {
    // `.u32()` never writes the eight-byte form, so a part using it is already lying about
    // something — but it is read at the same width `minicbor` reads it, so the value lands on
    // the bound that governs it instead of on a parse failure. A `messageLen` of 2^40 is
    // `MessageTooLarge`, not `NotAPart`.
    let mut scanner = Scanner::new(Class::Psbt);
    let mut cbor = vec![0x85, 0x01, 0x02, 0x1b];
    cbor.extend_from_slice(&(1u64 << 40).to_be_bytes());
    cbor.extend_from_slice(&[0x07, 0x40]);
    assert_eq!(
        scanner.receive(&raw_part("1-2", &cbor)),
        Outcome::Discarded(Discard::MessageTooLarge)
    );

    // A checksum wider than the `u32` it has to fit in is refused outright, because there is no
    // bound it could fail instead.
    let mut cbor = vec![0x85, 0x01, 0x02, 0x18, 0x28, 0x1b];
    cbor.extend_from_slice(&u64::MAX.to_be_bytes());
    cbor.push(0x40);
    assert_eq!(
        scanner.receive(&raw_part("1-2", &cbor)),
        Outcome::Discarded(Discard::NotAPart)
    );
}

#[test]
fn a_single_part_ur_whose_body_is_not_bytewords_is_dropped() {
    let mut scanner = Scanner::new(Class::Psbt);
    for symbol in ["ur:crypto-psbt/zzzz", "ur:crypto-psbt/ae"] {
        assert_eq!(
            scanner.receive(symbol),
            Outcome::Discarded(Discard::NotAPart),
            "{symbol}"
        );
    }
}

#[test]
fn a_stream_that_completes_into_something_the_dependency_rejects_is_dropped() {
    // Two fragments of 20 bytes for a 30-byte message, so the last ten are padding — which the
    // fountain decoder requires to be zero, and which these parts fill with data. No honest
    // encoder produces this; it is only reachable from a hostile or corrupt stream, and it is
    // the one path where `complete()` is true and there is still no message.
    let mut scanner = Scanner::new(Class::Psbt);
    assert_eq!(
        scanner.receive(&part(1, 2, 30, 7, &[0xab; 20])),
        Outcome::Received { parts: 1, of: 2 }
    );
    assert_eq!(
        scanner.receive(&part(2, 2, 30, 7, &[0xcd; 20])),
        Outcome::Discarded(Discard::NotAPart)
    );
}

#[test]
fn cbor_truncated_at_any_header_field_is_dropped() {
    // Four positions, because the reader walks the array field by field and each `?` is its own
    // way to run off the end. `[0x85]` alone stops before the first integer's head byte; the
    // rest stop between fields.
    let mut scanner = Scanner::new(Class::Psbt);
    for cbor in [
        vec![0x85],
        vec![0x85, 0x01],
        vec![0x85, 0x01, 0x02],
        vec![0x85, 0x01, 0x02, 0x18, 0x28],
    ] {
        assert_eq!(
            scanner.receive(&raw_part("1-2", &cbor)),
            Outcome::Discarded(Discard::NotAPart),
            "{cbor:02x?}"
        );
    }
}

// --- what the scanning screen reads off a scan (04-screens.md §11.1) ---------------------

#[test]
fn every_class_names_what_it_wants() {
    // The heading and the wrong-class refusal are the same phrase, so this asserts the phrase
    // once and both readers of it are covered.
    assert_eq!(Class::Psbt.wanted(), "a transaction to sign");
    assert_eq!(Class::Address.wanted(), "a receive address");
    assert_eq!(Class::Backup.wanted(), "an encrypted backup");
    for class in [Class::Psbt, Class::Address, Class::Backup] {
        assert!(
            Refusal::WrongClass {
                expected: class,
                announced: Announced::PlainText,
            }
            .reason()
            .contains(class.wanted()),
            "{class:?}"
        );
    }
}

#[test]
fn only_the_signing_class_can_run_to_more_than_one_part() {
    // §2's multi-part column, and the progress element's whole presence rule: the two classes
    // that never touch the fountain decoder have no fraction to report.
    assert!(Class::Psbt.multi_part());
    assert!(!Class::Address.multi_part());
    assert!(!Class::Backup.multi_part());
}

#[test]
fn a_fresh_scan_is_not_spent() {
    assert!(!Scanner::new(Class::Psbt).spent());
}

#[test]
fn a_wrong_class_refusal_leaves_the_scan_live_and_the_budget_does_not() {
    // The one distinction the screen turns on, and it is answered here rather than by the shell
    // reading the variant: §11.1's *the screen stays live afterwards* against §11.1's *no escape
    // hatch*.
    let mut live = Scanner::new(Class::Psbt);
    assert!(matches!(
        live.receive("bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4"),
        Outcome::Refused(Refusal::WrongClass { .. })
    ));
    assert!(!live.spent());
    // And it really is still live: the next symbol is taken rather than discarded as spent.
    assert_eq!(
        live.receive(&part(1, 2, 30, 7, &[0xab; 20])),
        Outcome::Received { parts: 1, of: 2 }
    );

    let mut budget = Scanner::new(Class::Psbt);
    for index in 0..=PART_BUDGET {
        budget.receive(&part(index % 2 + 1, 2, 30, 7, &[0xab; 20]));
    }
    assert!(budget.spent());
}

#[test]
fn a_completed_scan_is_spent() {
    let payload = message(300);
    let mut scanner = Scanner::new(Class::Psbt);
    assert!(matches!(
        scanner.receive(&single("crypto-psbt", &payload)),
        Outcome::Complete(_)
    ));
    assert!(scanner.spent());
}
