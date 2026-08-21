//! The outbound animation: the signed PSBT as QR symbols (`03-transport.md` §6, §8, §9).
//!
//! **It lives here, not in the shell**, and ADR-0004's seam is why: *drawing* a QR symbol touches
//! hardware, *computing* one does not. So this module emits a module matrix and `aobs/` paints
//! it — the review-model seam a second time, and the consequence is the point. Version selection,
//! the ECC level, the v27 cap, the fragment length and the refusal that cannot happen all sit
//! under the 95% region gate and test from a byte fixture, and the shell keeps no branch on
//! whether a payload fit.
//!
//! **Both of §6's rules are one call**, not a loop we maintain:
//! `encode_segments_advanced(segs, Low, Version::MIN, v27, None, false)`. The smallest version
//! that fits is the library's search; the cap is `maxversion`; exceeding it is `Err` rather than a
//! larger symbol. `boostecl` is pinned `false` because it would raise the ECC level whenever a
//! payload left slack in its version — which costs nothing in density but makes the emitted level
//! a function of payload size, where §6 and §7 *name* the level.
//!
//! **The fragment length is the number *"no outbound size cap"* actually rests on** (§9). The
//! version follows the part size, so the part size is the only thing that can make the encoder
//! refuse; at 960 the largest part the animation can ever emit is 2 013 characters against
//! v27-L's 2 132, with every CBOR field at its `u32` maximum and both decimals ten digits wide.
//! So the refusal is unreachable by arithmetic rather than merely unlikely — which is why
//! [`Animation::psbt`] cannot fail and returns no `Result`. It is a **parameter** of
//! [`Animation::with_fragment_length`] and not a constant, so
//! `05-testing-and-release.md` §3's property test can sweep other values and watch this one hold.
//!
//! **A single-frame payload is an animation of length one that happens not to move** (§6): same
//! type, same call, same screen. One encoding rule rides with it — when the message fits one
//! fragment, the emitted UR is the **single-part form with no `seq` component**, not `1-1`. That
//! is the one place this module branches, and it branches on a fragment count rather than on
//! anything about the bytes.
//!
//! **The UR text is uppercased before encoding.** §1 already requires the uppercase spelling on
//! the wire because Specter's scanner regexes match `UR:CRYPTO-*`, and it pays for itself twice:
//! `QrSegment::make_segments` then picks alphanumeric mode on its own, where lowercase would fall
//! to byte mode and cost about a third of the capacity — a v27 symbol at ECC L carries 2 132
//! alphanumeric characters but only 1 465 bytes.
//!
//! **What the UR message is, stated because it is the one thing §6 leaves implicit.** The message
//! is the PSBT's serialised bytes, which is the same convention [`crate::ur`] accepts on the way
//! in and the one §9.1's arithmetic is written over — `messageLen` is the PSBT's own length there,
//! with no wrapper charged. Emitting anything else would make the inbound and outbound halves of
//! this crate disagree about what a `crypto-psbt` carries.
//!
//! **Whether that is what a coordinator expects is
//! [#112](https://github.com/allisson/aobs/issues/112)**, and no test in this crate can answer it:
//! BCR-2020-006 defines the payload as a CBOR byte string wrapping the PSBT, our own decoder reads
//! our own encoder, and symmetry holds whichever convention we picked. It moves in both directions
//! at once or in neither (§6a).

use qrcodegen::{QrCode, QrCodeEcc, QrSegment, Version};

/// `03-transport.md` §9's number, named once, here.
///
/// Nothing in `aobs/` names it: a shell constant would put the only value that can make the
/// signing path refuse outside every gate that judges code.
pub const MAX_FRAGMENT_LEN: usize = 960;

/// §6's version cap — module pitch, not frame count.
///
/// On a ~700 px usable square, v40's 177 modules plus quiet zone gives ≈3.8 px/module against
/// v27's 133 → ≈5.3. **`05-testing-and-release.md` §6.4's owed measurement is where this gets
/// re-priced**, and if it flips to v40 then [`MAX_FRAGMENT_LEN`] is re-derived from the new cap
/// rather than kept.
const MAX_VERSION: u8 = 27;

/// §6's error-correction level: the backup QR's decision run in the opposite direction on the
/// same evidence.
///
/// BBQr's ECC-L advice is premised on *"a perfect LCD screen"*, which is false for paper and
/// exactly true here — and for a multi-part payload the fountain code is already the error
/// correction that matters.
const ECC: QrCodeEcc = QrCodeEcc::Low;

/// §1: emit the deprecated `crypto-psbt` spelling, not the registry's newer `psbt`/40310.
///
/// Sparrow decodes `psbt` but never writes it, and Specter's scanner regexes match only
/// `UR:CRYPTO-*` and `UR:BYTES/`, so `ur:psbt/…` falls through unhandled.
const UR_TYPE: &str = "crypto-psbt";

/// One QR symbol, as the matrix of bits it is.
///
/// **Not pixels.** The shell paints it; tests assert on it. That is the same seam
/// [`crate::psbt::Review`] sits on, and the reason the version cap is testable at all.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Symbol {
    size: u32,
    dark: Vec<bool>,
}

impl Symbol {
    /// The side length in modules, quiet zone excluded — the quiet zone is the painter's, since
    /// it is background and not data.
    #[must_use]
    pub fn size(&self) -> u32 {
        self.size
    }

    /// Whether the module at `(x, y)` is dark. Out of range is light, which is what the quiet
    /// zone is.
    #[must_use]
    pub fn dark(&self, x: u32, y: u32) -> bool {
        if x >= self.size || y >= self.size {
            return false;
        }
        self.dark[(y * self.size + x) as usize]
    }

    /// Which QR version this symbol is, 1..=40. The cap is a fact about the animation and this
    /// is how a test reads it.
    #[must_use]
    pub fn version(&self) -> u8 {
        // Version 1 is 21 modules and each version adds 4.
        ((self.size - 17) / 4) as u8
    }
}

/// The outbound animation: **fresh fountain parts, forever** (§6).
///
/// BC-UR is rateless, so looping properly means *generating* parts rather than cycling a fixed
/// set — which is also why `04-screens.md` §11.5 states the part count once and statically:
/// *"part 3 of 4"* becomes a lie on the second pass, and any percentage would describe our
/// animation rather than their reception. There is no stop condition, because with no feedback
/// channel no stop condition can be anything but arbitrary.
pub struct Animation {
    source: Source,
    parts: usize,
}

/// Where the next part comes from — §6's *"an animation of length one that happens not to move"*
/// as a type.
enum Source {
    /// One fragment: the single-part UR form, with no `seq` component. The text is kept beside
    /// the symbol so that *the same code path* is true of the tests too — and the symbol is
    /// encoded once, because it never changes.
    Single { text: String, symbol: Symbol },
    /// Two or more: the fountain encoder, which never runs out.
    Fountain(Box<::ur::Encoder<'static>>),
}

impl Animation {
    /// The animation for one signed PSBT, at §9's fragment length.
    ///
    /// # Panics
    ///
    /// If `message` is empty. A serialised PSBT never is — it carries the magic bytes and an
    /// unsigned transaction — and the only way to reach this is with bytes no `Accepted` produced.
    #[must_use]
    pub fn psbt(message: &[u8]) -> Self {
        Self::with_fragment_length(message, MAX_FRAGMENT_LEN)
    }

    /// The same, at a chosen fragment length.
    ///
    /// It exists so `05-testing-and-release.md` §3's property test can sweep values other than
    /// §9's and watch that one hold (§9.4). **Nothing outside this crate's tests calls it**, and
    /// nothing in `aobs/` could: the shell reaches [`Animation::psbt`].
    ///
    /// # Panics
    ///
    /// If `message` is empty or `max_fragment_length` is zero.
    #[must_use]
    pub fn with_fragment_length(message: &[u8], max_fragment_length: usize) -> Self {
        let encoder = ::ur::Encoder::new(message, max_fragment_length, UR_TYPE)
            .expect("a signed PSBT is never empty and the fragment length is never zero");
        let parts = encoder.fragment_count();

        // §6's one encoding rule, and the only branch in this module: when it fits, the
        // single-part form and not `1-1`. The fountain encoder would happily emit `1-1` for a
        // one-fragment message, and a coordinator reading it would be reading a multi-part
        // stream of length one — which is a different thing on the wire from a UR that is
        // simply not fragmented.
        let source = if parts == 1 {
            let text = ::ur::ur::encode(message, &::ur::Type::Custom(UR_TYPE)).to_ascii_uppercase();
            Source::Single {
                symbol: symbol(&text),
                text,
            }
        } else {
            Source::Fountain(Box::new(encoder))
        };

        Self { source, parts }
    }

    /// How many fragments the message was split into — `04-screens.md` §11.5's static count.
    ///
    /// One means the single-part case, where §11.5 says nothing at all.
    #[must_use]
    pub fn parts(&self) -> usize {
        self.parts
    }

    /// The next symbol to draw. It never runs out and it never refuses (§6, §9).
    #[must_use]
    pub fn next_symbol(&mut self) -> Symbol {
        match &mut self.source {
            Source::Single { symbol, .. } => symbol.clone(),
            Source::Fountain(_) => symbol(&self.next_part()),
        }
    }

    /// The next part's UR text, uppercased — what actually goes on the wire.
    ///
    /// Private: the shell has no use for the text, and §8 forbids it a branch on whether a
    /// payload fit. The tests use it, because §9's bound is stated in characters.
    fn next_part(&mut self) -> String {
        match &mut self.source {
            Source::Single { text, .. } => text.clone(),
            Source::Fountain(encoder) => encoder
                .next_part()
                .expect("`Part::cbor` serialises four integers and a byte string")
                .to_ascii_uppercase(),
        }
    }
}

/// One UR part's text as a symbol: **§6's two rules as the library's own behaviour.**
///
/// # Panics
///
/// If the text does not fit [`MAX_VERSION`] at [`ECC`]. §9 makes that unreachable by arithmetic
/// at [`MAX_FRAGMENT_LEN`] — the ceiling is 2 013 characters against 2 132 — and
/// `05-testing-and-release.md` §3's property test is what keeps it unreachable if the fragment
/// length is ever raised without redoing that arithmetic. Refusing to emit a signature we have
/// already produced is the worst failure available to this device (§6), so this is the one place
/// it may not silently become a `Result` somebody handles by discarding.
fn symbol(text: &str) -> Symbol {
    let segments = QrSegment::make_segments(text);
    let code = QrCode::encode_segments_advanced(
        &segments,
        ECC,
        Version::MIN,
        Version::new(MAX_VERSION),
        None,
        false,
    )
    .expect("03-transport.md §9 bounds every part below the cap's capacity");

    let size = u32::try_from(code.size()).expect("a QR side is 21..=177 modules");
    let mut dark = Vec::with_capacity((size * size) as usize);
    for y in 0..code.size() {
        for x in 0..code.size() {
            dark.push(code.get_module(x, y));
        }
    }

    Symbol { size, dark }
}

#[cfg(test)]
#[path = "outbound_tests.rs"]
mod tests;
