//! The QR boundary, inbound: the payload classes, the four bounds and decoder discipline
//! (`03-transport.md` §2, §3 and §4).
//!
//! **This is the wrapper around the riskiest parser in the tree.** `ur` 0.5's
//! `Decoder::receive` adopts `sequence_count` from the first part it sees, unvalidated, so one
//! frame declaring `seqLen = 0xFFFFFFFF` asks for a `Vec<usize>` and a `Vec<f64>` of 4.29
//! billion elements — ~34 GB each, on a no-swap LiveCD, **before any key material is touched**.
//! §3's bounds are the mitigation and they are requirements rather than hygiene: nothing here
//! hands a part to the dependency before all four have been checked.
//!
//! **The class check lives here rather than in the shell** (§2). The shell hands us a decoded
//! string plus the class the screen asked for and receives an [`Outcome`]; it compares nothing.
//! *"Is this the class this screen asked for"* is a branch on a validation outcome, which the
//! shell is forbidden (standing rule 4) — and putting it here puts the payload-class guarantee
//! inside the 98% bar instead of in the untested layer.
//!
//! **Two of the three classes never touch the fountain decoder at all.** [`Class::Address`]
//! because a coordinator emits a receive QR as plain text or a BIP-21 URI and never as a UR, and
//! [`Class::Backup`] because it is single-part by rule (§7). That is the second and third path
//! removing itself from the reach of the fountain decoder, and it is why a multi-part `ur:bytes`
//! at the restore prompt is refused rather than decoded.
//!
//! **What the dependency does not let us do, and what we do instead.** `fountain::Part` is
//! constructible only inside `ur` — `from_cbor`, `sequence` and `sequence_count` are
//! `pub(crate)` and `message_length` and `checksum` have no accessor at all — so a part cannot
//! be inspected between parsing and reception. [`read_header`] therefore reads the four header
//! fields out of the part's own CBOR itself, which is what makes *before any part reaches `ur`*
//! true of `messageLen` and not only of `seqLen`. Two consequences are deliberate:
//!
//! - The bytewords body is decoded twice per part — once by us to read the header, once by the
//!   dependency. It is bounded work on a bounded string and it buys the ordering §3 states.
//! - **Two readers reading one field is only safe if they cannot disagree about it**, and this
//!   pair cannot: both read the same bytes at the same offset under the same five width rules,
//!   so the declared `messageLen` this scan bounds is the one the dependency truncates the
//!   reassembled message to. Where the readers *do* differ is that ours stops after the fourth
//!   field and never inspects the fragment — so it can compute a header for a part the
//!   dependency then refuses, which is handled and leaves no trace (nothing is pinned on a part
//!   that was not accepted).
//!
//! **No wall-clock scan timeout** (§3). Cancel stays live at all times, which is what a user
//! with a bad camera angle actually needs; bounded *work* is the security property and
//! [`PART_BUDGET`] is what bounds it.

use ::ur::bytewords::Style;
use ::ur::ur::Kind;

/// §3's first bound: `messageLen` ≤ 64 KiB, ~17× the largest realistic payload (3 744 B).
///
/// Generous enough that no honest user reaches it. It bounds what *arrives*; the outbound
/// fragment length (`03-transport.md` §9) faces the opposite direction and is not this number.
pub const MAX_MESSAGE_LEN: usize = 64 * 1024;

/// §3's second bound: `seqLen` ≤ 64 frames.
///
/// 64 KiB at v40-L density is ~32 frames; 64 leaves room for sparser v27 codes without
/// admitting a four-billion-frame claim. This is the field the 34 GB allocation is computed
/// from, and it is checked on the decimal in the URI path before anything is decoded at all.
pub const MAX_SEQUENCE_COUNT: usize = 64;

/// §3's third bound: total parts accepted ≤ 1 024, then refuse.
///
/// `seqLen` bounds the *claim*; this bounds the *work*. Fountain coding lets a hostile animation
/// feed well-formed, mutually consistent parts forever without completing — the dependency's
/// `buffer` of un-resolved index sets grows with every one of them — and only a counter on parts
/// actually received stops that.
pub const PART_BUDGET: usize = 1_024;

/// [`Refusal::PartBudgetSpent`]'s sentence writes the budget out with a thousands separator, so
/// the number cannot be interpolated. This is what stops the copy drifting from the bound.
const _: () = assert!(PART_BUDGET == 1_024);

/// §2's bound on the address class: ≤ 256 bytes of printable ASCII, single-part plain text.
pub const MAX_ADDRESS_LEN: usize = 256;

/// The CBOR overhead of a part around its fragment: the five-element array header, four
/// integers at their `u32` widest, and a byte-string header.
///
/// `fountain::Part`'s `Encode` impl makes four `.u32()` calls (`03-transport.md` §9.1), so no
/// integer is wider than five bytes.
const PART_CBOR_OVERHEAD: usize = 1 + 4 * 5 + 5;

/// Bytewords minimal spends two characters per byte and appends a four-byte CRC-32, which is
/// doubled with everything else (`03-transport.md` §9.1's `2n + 8`).
const BYTEWORDS_CRC_CHARS: usize = 8;

/// `ur:`, a type string, `/`, two ten-digit decimals and `-`, and a second `/`.
///
/// The type is the one term that is not fixed by the format, and it does not need to be: a type
/// longer than this leaves the accepted set on the name, so anything charged here is slack.
const MAX_URI_PREFIX_CHARS: usize = 64;

/// The longest symbol we will look at, **derived from [`MAX_MESSAGE_LEN`] rather than chosen**.
///
/// §3 orders the `messageLen` bound before the decoder, and a bound read out of the CBOR has
/// already paid for the bytewords allocation that produced the CBOR. So the same bound is
/// applied first to the only form the symbol has before we are allowed to decode it. Nothing
/// here is a fifth bound — it is §3's first bound, enforced as early as it can be, and every
/// term of it is one of the format's own.
const MAX_SYMBOL_CHARS: usize =
    2 * (MAX_MESSAGE_LEN + PART_CBOR_OVERHEAD) + BYTEWORDS_CRC_CHARS + MAX_URI_PREFIX_CHARS;

/// The three payload classes (§2). **No screen can be handed a payload it did not ask for.**
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Class {
    /// Signing. Multi-part or single-part `ur:crypto-psbt` / `ur:psbt` / `ur:bytes`, under §3's
    /// bounds.
    Psbt,
    /// Receive-address verification. One QR symbol, single-part plain text.
    Address,
    /// Encrypted-backup restore. Single-part `ur:bytes` only.
    Backup,
}

impl Class {
    /// What this screen asked for, for the wrong-class copy — and for the screen's own heading.
    ///
    /// **Public because those are the same phrase.** `04-screens.md` §11.1 puts one component in
    /// three configurations where *the copy names what this screen wants*, and §11.1's
    /// wrong-class refusal names the same want; two spellings of it would be two places for the
    /// heading and the refusal to drift into naming different things.
    #[must_use]
    pub fn wanted(self) -> &'static str {
        match self {
            Self::Psbt => "a transaction to sign",
            Self::Address => "a receive address",
            Self::Backup => "an encrypted backup",
        }
    }

    /// Whether a stream of this class can run to more than one part — §2's table, as an answer.
    ///
    /// The scanning screen's progress element is **absent for a single-part class**
    /// (`04-screens.md` §11.1), and *which classes are single-part* is §2's own column rather
    /// than a reading the shell is allowed to take of it (standing rule 4). Two of the three
    /// classes never touch the fountain decoder at all, so for them there is no fraction of
    /// parts that could be reported truthfully.
    #[must_use]
    pub fn multi_part(self) -> bool {
        match self {
            Self::Psbt => true,
            Self::Address | Self::Backup => false,
        }
    }
}

/// What a symbol announces itself to be — which is all a class check may rest on, because §3's
/// fourth bound puts the type check *before* decoding.
///
/// **The observed type string is named by category and never echoed.** An attacker chooses it,
/// and the Coldcard 2019 lesson is that the review screen was the vulnerability; a category is
/// enough to state both sides of the refusal truthfully.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Announced {
    /// `ur:crypto-psbt` or `ur:psbt` — a transaction and nothing else.
    Transaction,
    /// `ur:bytes` — the one spelling two classes share (§1 accepts it for a PSBT, §7 requires it
    /// for the backup), so it is a wrong class only at the address prompt.
    Bytes,
    /// A UR of some other type. Named as a kind we do not use rather than quoted.
    ForeignUr,
    /// Not a UR at all: plain text within the address class's bounds, which is the only form a
    /// receive address arrives in.
    PlainText,
}

impl Announced {
    /// What was scanned, for the wrong-class copy.
    fn named(self) -> &'static str {
        match self {
            Self::Transaction => "a transaction",
            Self::Bytes => "binary data — an encrypted backup, or a transaction written that way",
            Self::ForeignUr => "a kind of QR aobs does not use",
            Self::PlainText => "plain text, which is how a receive address arrives",
        }
    }
}

/// A refusal at the QR boundary: its reason in plain language and its stable code.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Refusal {
    /// `AOBS-R10` — a wrong-class payload at a prompt expecting another class.
    ///
    /// Both sides are carried because both sides are stated (`04-screens.md` §11.1). The screen
    /// **stays live** afterwards: the rejected payload remains unusable, so this is an
    /// invitation to point the camera elsewhere rather than an escape hatch.
    WrongClass {
        /// The class this screen asked for.
        expected: Class,
        /// What the symbol announced itself to be.
        announced: Announced,
    },
    /// `AOBS-R11` — [`PART_BUDGET`] parts were accepted without the stream completing.
    PartBudgetSpent,
}

impl Refusal {
    /// Every variant, for the tests that hold the codes to `06-codes.md` §6.
    ///
    /// One entry per variant, not per copy: [`Refusal::WrongClass`] has twelve sentences across
    /// three expected classes and four announced kinds, and those are asserted in `ur_tests.rs`.
    pub const ALL: [Self; 2] = [
        Self::WrongClass {
            expected: Class::Psbt,
            announced: Announced::PlainText,
        },
        Self::PartBudgetSpent,
    ];

    /// The stable machine-readable code, from `06-codes.md` §6's `AOBS-R##` space.
    #[must_use]
    pub fn code(self) -> &'static str {
        match self {
            Self::WrongClass { .. } => "AOBS-R10",
            Self::PartBudgetSpent => "AOBS-R11",
        }
    }

    /// The specific reason, in plain language, for the screen to state verbatim.
    ///
    /// Computed here and never assembled by the shell, which marshals and evaluates nothing
    /// (standing rule 4).
    #[must_use]
    pub fn reason(self) -> String {
        match self {
            Self::WrongClass {
                expected,
                announced,
            } => format!(
                "This QR is {}, and this screen is expecting {}.",
                announced.named(),
                expected.wanted()
            ),
            // The budget is written the way a person reads it rather than interpolated, and
            // the const assertion above is what stops the sentence drifting from the bound.
            Self::PartBudgetSpent => "aobs took in 1,024 frames of this animation without it \
                 completing, so it has stopped taking more. An animation that never finishes is \
                 either damaged or is not trying to finish."
                .to_owned(),
        }
    }
}

/// Why a symbol was dropped without anything being refused.
///
/// **None of these carries a code** (`06-codes.md` §4): a symbol we cannot make anything of is
/// overwhelmingly a bad scan, the screen says nothing and stays live, and giving it a code would
/// file the commonest harmless event under the same heading as an attack. The variants exist
/// because the tests, the corpus and the fuzz target assert on *which* bound tripped — not
/// because the shell branches on them.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Discard {
    /// Not a form we accept at all: longer than [`MAX_SYMBOL_CHARS`], or plain text outside the
    /// address class's length and printable-ASCII bounds, or a `ur:` with no type.
    ///
    /// Deliberately **not** a wrong-class refusal: there is no class these bytes belong to, so
    /// naming one would be a false statement about what was scanned.
    Unreadable,
    /// §3's second bound — `seqLen` outside `1..=`[`MAX_SEQUENCE_COUNT`]. This is the 34 GB
    /// claim, and it is dropped on the decimal in the URI path.
    SequenceCountTooLarge,
    /// §3's first bound — a declared or delivered `messageLen` outside
    /// `1..=`[`MAX_MESSAGE_LEN`].
    MessageTooLarge,
    /// A UR of an accepted type that did not decode into a part, or a part the dependency
    /// refused.
    NotAPart,
    /// §4 — a part whose `seqLen`, `messageLen` or checksum disagrees with the stream already
    /// established. The stream itself is untouched.
    ForeignPart,
    /// The scan already ended, in a completion or in a refusal. There is no reset (§4).
    Spent,
}

/// The payload a completed scan hands back, named for the class that asked for it.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Payload {
    /// A PSBT's bytes, for `psbt::validate`.
    Transaction(Vec<u8>),
    /// The address text, exactly as scanned.
    Address(String),
    /// The encrypted backup's bytes. Its header is `02-core.md` §11's to validate, not ours.
    Backup(Vec<u8>),
}

/// What one scanned symbol produced.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Outcome {
    /// The stream advanced. `04-screens.md` §11.1 draws this as `parts` of `of` — resolved
    /// fragments over the **clamped** `seqLen`, so the worst a hostile stream buys is a wrong
    /// denominator on a bounded display. A single-part class never produces it.
    Received {
        /// Fragments resolved so far, directly or by XOR elimination.
        parts: usize,
        /// The stream's clamped `seqLen`.
        of: usize,
    },
    /// The payload is here and the screen dismisses immediately (`04-screens.md` §11.1).
    Complete(Payload),
    /// Nothing was refused: the screen stays live and the user points the camera again.
    Discarded(Discard),
    /// A refusal in the standard shape, carrying its code and one action.
    Refused(Refusal),
}

/// The three header fields a stream's identity is pinned on (§4).
#[derive(Clone, Copy, PartialEq, Eq)]
struct Identity {
    sequence_count: usize,
    /// Attacker-declared, so it is carried at the width the CBOR can express rather than
    /// narrowed into a `usize` first: a claim of 2^40 is a number to refuse, not a conversion
    /// to fail. On this target the two widths are the same and the narrowing would be a branch
    /// nothing can take.
    message_len: u64,
    checksum: u32,
}

/// One scan, for one class, with one fountain decoder.
///
/// **A fresh decoder on every entry to the scanning screen** (§4) — a stale pool from an
/// abandoned scan mixing into the next one is a correctness hazard on the path that produces a
/// signature. What core can offer for that is that a decoder is reachable only through
/// [`Scanner::new`]: there is no reset, no `Default` and no `Clone`, and a scanner that finished
/// discards instead of decoding. A stale pool has nowhere to come from.
pub struct Scanner {
    expected: Class,
    decoder: ::ur::Decoder,
    stream: Option<Identity>,
    parts: usize,
    done: bool,
}

impl Scanner {
    /// A scanner for the class this screen asked for.
    #[must_use]
    pub fn new(expected: Class) -> Self {
        Self {
            expected,
            decoder: ::ur::Decoder::default(),
            stream: None,
            parts: 0,
            done: false,
        }
    }

    /// Whether this scan is over, in a completion or in a refusal that ended it.
    ///
    /// **The shell asks rather than decides.** `04-screens.md` §11.1 keeps the screen live after
    /// a wrong-class refusal — the rejected payload stays unusable, so it is an invitation to
    /// point the camera elsewhere — and stops it when the part budget is spent. Both are facts
    /// about this scanner, not a distinction the shell is allowed to draw between two
    /// [`Refusal`] variants (standing rule 4), and every further symbol from here is
    /// [`Discard::Spent`].
    #[must_use]
    pub fn spent(&self) -> bool {
        self.done
    }

    /// Take in one decoded QR symbol.
    ///
    /// The whole of §2, §3 and §4 is this function and the two it calls. The order is the
    /// design: the symbol's length, then its type, then the class, then `seqLen`, then
    /// `messageLen` and the stream's identity, then the parts budget — and only then does
    /// anything reach the dependency.
    pub fn receive(&mut self, symbol: &str) -> Outcome {
        if self.done {
            return Outcome::Discarded(Discard::Spent);
        }
        if symbol.len() > MAX_SYMBOL_CHARS {
            return Outcome::Discarded(Discard::Unreadable);
        }

        let Some(rest) = strip_scheme(symbol) else {
            return self.plain_text(symbol);
        };
        let Some((ur_type, body)) = rest.split_once('/') else {
            return Outcome::Discarded(Discard::Unreadable);
        };

        // §3's fourth bound: the UR type is checked here, before a single byte is decoded.
        let announced = if ur_type.eq_ignore_ascii_case("crypto-psbt")
            || ur_type.eq_ignore_ascii_case("psbt")
        {
            Announced::Transaction
        } else if ur_type.eq_ignore_ascii_case("bytes") {
            Announced::Bytes
        } else if ur_type.is_empty() {
            return Outcome::Discarded(Discard::Unreadable);
        } else {
            Announced::ForeignUr
        };

        // The dependency splits the body on its **last** separator, so the split is taken here,
        // the same way, once — and `Some` versus `None` is exactly what multi-part means. Taking
        // it here rather than inside `multi_part` also leaves no arm for a split that cannot
        // fail to exist.
        let split = body.rsplit_once('/');

        // §2's table, as a match rather than as a check. The multi-part column is what keeps
        // the address and backup classes out of the fountain decoder entirely.
        match (self.expected, announced, split) {
            (Class::Psbt, Announced::Transaction | Announced::Bytes, None) => {
                self.single_part(symbol, Payload::Transaction)
            }
            (Class::Psbt, Announced::Transaction | Announced::Bytes, Some((indices, payload))) => {
                self.multi_part(symbol, indices, payload)
            }
            (Class::Backup, Announced::Bytes, None) => self.single_part(symbol, Payload::Backup),
            _ => Outcome::Refused(Refusal::WrongClass {
                expected: self.expected,
                announced,
            }),
        }
    }

    /// §2's address class: one symbol, plain text, ≤ 256 bytes, printable ASCII or rejected.
    fn plain_text(&mut self, symbol: &str) -> Outcome {
        if symbol.is_empty()
            || symbol.len() > MAX_ADDRESS_LEN
            || !symbol.bytes().all(|byte| (0x20..=0x7e).contains(&byte))
        {
            return Outcome::Discarded(Discard::Unreadable);
        }
        if self.expected != Class::Address {
            return Outcome::Refused(Refusal::WrongClass {
                expected: self.expected,
                announced: Announced::PlainText,
            });
        }
        self.done = true;
        Outcome::Complete(Payload::Address(symbol.to_owned()))
    }

    /// A UR with no `seq` component — §6's *"an animation of length one that happens not to
    /// move"*, and the only form the backup class accepts.
    fn single_part(&mut self, symbol: &str, wrap: fn(Vec<u8>) -> Payload) -> Outcome {
        match ::ur::ur::decode(symbol) {
            Ok((Kind::SinglePart, message)) => {
                if message.is_empty() || message.len() > MAX_MESSAGE_LEN {
                    return Outcome::Discarded(Discard::MessageTooLarge);
                }
                self.done = true;
                Outcome::Complete(wrap(message))
            }
            _ => Outcome::Discarded(Discard::NotAPart),
        }
    }

    /// One fountain part, through all four of §3's bounds and §4's identity pin.
    fn multi_part(&mut self, symbol: &str, indices: &str, payload: &str) -> Outcome {
        let Some((sequence, sequence_count)) = parse_indices(indices) else {
            return Outcome::Discarded(Discard::NotAPart);
        };

        // §3's second bound, and the only one that can be checked with no allocation at all:
        // the 34 GB claim arrives as a decimal in the URI path.
        if sequence == 0 || sequence_count == 0 || sequence_count > MAX_SEQUENCE_COUNT {
            return Outcome::Discarded(Discard::SequenceCountTooLarge);
        }

        let Some(identity) = read_header(payload, sequence, sequence_count) else {
            return Outcome::Discarded(Discard::NotAPart);
        };

        // §3's first bound, on the claim.
        if identity.message_len == 0 || identity.message_len > MAX_MESSAGE_LEN as u64 {
            return Outcome::Discarded(Discard::MessageTooLarge);
        }

        // §4: after the first **accepted** part, any part disagreeing on `seqLen`, `messageLen`
        // or the message checksum is rejected. The dependency's own `validate` compares the same
        // three plus the fragment length, so this is a second line rather than the only one —
        // but it is the line at our call site, which is what §4 asks for.
        //
        // **Accepted is the load-bearing word, and getting it wrong is an attack.** Pinning on
        // a part the decoder then refused would let one hostile frame — a header we accept
        // carrying a fragment the dependency does not — claim the stream's identity and lock
        // the honest animation out of the scan for as long as the user keeps aiming at it.
        if self.stream.is_some_and(|pinned| pinned != identity) {
            return Outcome::Discarded(Discard::ForeignPart);
        }

        // §3's third bound: the work. Checked before the part is handed over, so exactly
        // `PART_BUDGET` parts can ever reach the dependency.
        if self.parts >= PART_BUDGET {
            self.done = true;
            return Outcome::Refused(Refusal::PartBudgetSpent);
        }
        if self.decoder.receive(symbol).is_err() {
            return Outcome::Discarded(Discard::NotAPart);
        }
        self.parts += 1;
        self.stream = Some(identity);

        if self.decoder.complete() {
            // No second length check here, and that is a claim rather than an omission: the
            // dependency truncates the reassembled message to the `messageLen` it pinned, which
            // is the same field this scan bounded — see [`read_header`] on why the two readers
            // cannot disagree about its value.
            //
            // **A stream that completes into something the dependency refuses — nonzero
            // padding, or a message that fails its own CRC-32 — leaves this scanner unable to
            // complete ever again**, because the decoder stays `complete()` and its message
            // stays bad. That is a dead end the screen cannot see: it stays live and every
            // further symbol is discarded. No honest encoder can produce it, the remedy is
            // cancel and re-enter, and inventing a reset here would be a decision
            // `03-transport.md` §4 does not make — it is recorded rather than papered over.
            let Ok(Some(message)) = self.decoder.message() else {
                return Outcome::Discarded(Discard::NotAPart);
            };
            self.done = true;
            return Outcome::Complete(Payload::Transaction(message));
        }

        Outcome::Received {
            parts: self.decoder.resolved_fragment_count().unwrap_or(0),
            of: sequence_count,
        }
    }
}

/// `ur:`, case-insensitively — §1 requires the uppercase spelling on the wire, so a coordinator
/// that sends it is the ordinary case.
fn strip_scheme(symbol: &str) -> Option<&str> {
    let (scheme, rest) = symbol.split_at_checked(3)?;
    scheme.eq_ignore_ascii_case("ur:").then_some(rest)
}

/// `{seq}-{seqLen}`, as two decimals and nothing else.
///
/// A `seqLen` too wide for a `usize` fails here rather than being truncated into range, which is
/// the direction that matters: `0xFFFFFFFF` parses and is then refused by the bound, and
/// something wider is refused for not being a number.
fn parse_indices(indices: &str) -> Option<(usize, usize)> {
    let (sequence, sequence_count) = indices.split_once('-')?;
    Some((sequence.parse().ok()?, sequence_count.parse().ok()?))
}

/// The part's own header, read out of its CBOR before the dependency sees it.
///
/// `fountain::Part` is `[seq, seqLen, messageLen, checksum, fragment]` with every integer
/// written by a `.u32()` call, so five bytes is the widest any of them can honestly be. The
/// wider `0x1b` form is read anyway rather than rejected outright: a value that does not fit
/// where it is going fails the bound that governs it, and a reader that is stricter than
/// `minicbor` can only ever refuse a part the dependency would have taken — never the reverse.
///
/// Returns `None` unless the CBOR is a five-element array whose first two integers are the
/// decimals the URI already stated. The dependency checks that agreement too; doing it here is
/// what makes the pinned identity exact rather than approximate.
///
/// **This reader and `minicbor`'s cannot disagree about a value.** Both take the same byte at
/// the same offset and apply the same widths — `0x00..=0x17` inline, then one, two, four and
/// eight bytes big-endian — so a non-minimal or eight-byte encoding is read identically by both.
/// That is what lets the bound checked on the declared `messageLen` stand for the delivered
/// message without a second check downstream.
fn read_header(payload: &str, sequence: usize, sequence_count: usize) -> Option<Identity> {
    let cbor = ::ur::bytewords::decode(payload, Style::Minimal).ok()?;
    let mut at = 0usize;

    if *cbor.first()? != 0x85 {
        return None;
    }
    at += 1;

    let declared_sequence = read_uint(&cbor, &mut at)?;
    let declared_count = read_uint(&cbor, &mut at)?;
    let message_len = read_uint(&cbor, &mut at)?;
    let checksum = read_uint(&cbor, &mut at)?;

    if declared_sequence != sequence as u64 || declared_count != sequence_count as u64 {
        return None;
    }

    Some(Identity {
        sequence_count,
        message_len,
        checksum: u32::try_from(checksum).ok()?,
    })
}

/// One CBOR unsigned integer, at any of the five widths the major type allows.
fn read_uint(cbor: &[u8], at: &mut usize) -> Option<u64> {
    let head = *cbor.get(*at)?;
    *at += 1;
    let width = match head {
        0x00..=0x17 => return Some(u64::from(head)),
        0x18 => 1,
        0x19 => 2,
        0x1a => 4,
        0x1b => 8,
        _ => return None,
    };
    let bytes = cbor.get(*at..*at + width)?;
    *at += width;
    Some(
        bytes
            .iter()
            .fold(0u64, |value, &byte| (value << 8) | u64::from(byte)),
    )
}

#[cfg(test)]
#[path = "ur_tests.rs"]
mod tests;
