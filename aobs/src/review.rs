//! The review panel, the per-address walk, and the screen a refusal ends on
//! (04-screens.md §11.2, §11.3; 02-core.md §7).
//!
//! **This is the mitigation.** If the user cannot verify what they are signing, no other
//! property of this appliance matters — so the whole of what this module does is turn core's
//! typed model into strings and hand them to a layout, and the whole of what it must not do is
//! decide anything. Both halves are visible here rather than promised:
//!
//! * **Every number arrives written.** `aobs_core::format` is the only thing that turns an
//!   `Amount` into digits, an address into groups, or a fee into a rate — the ninth 98%
//!   component, because this screen is what it exists for. Nothing below divides, rounds or
//!   truncates.
//! * **The warning is a variant, and stays one until the last possible moment.** [`warning`] is
//!   one `match` over core's [`Warning`], which is what makes adding a second condition a
//!   compile error here rather than a sentence someone forgot to write. The condition itself is
//!   never re-tested (02-core.md §9).
//! * **Nothing that should stop a transaction is on the panel.** There is no path from hostile
//!   bytes to [`Screen::Review`] that does not go through [`psbt::validate`], because that call
//!   is the only thing in this module that produces an [`Accepted`] — and a rejection lands on
//!   [`Screen::Refused`] or back on the live scanning screen instead.
//!
//! **The walk is over payments, and the panel is over outputs.** They are two different lists:
//! §11.3 exists to guarantee that a *payment* address was alone on screen at the moment of
//! approval, and change has already been settled by the byte-compare, so putting a change
//! output on its own screen would spend the user's attention on the one row that needs none.

use std::cell::{Cell, RefCell};

use std::rc::Rc;

use aobs_core::format;
use aobs_core::psbt::{
    self, Accepted, OutputKind, OutputRow, Rederivation, Refusal, Rejection, Review as Model,
    Warning,
};
use aobs_core::sign;
use slint::{ModelRc, SharedString, VecModel};
use zeroize::Zeroizing;

use crate::identity;
use crate::outbound::Outbound;
use crate::session::Session;
use crate::{AppWindow, Output, Screen};

/// **Failing to decode is not the same as rejecting** (02-core.md §7). Bytes that never became
/// a PSBT are overwhelmingly a bad scan, so this says so and the camera stays up — and it
/// carries **no code**, because filing the commonest harmless event under the same heading as
/// an attack is exactly what 06-codes.md §4 rules out.
const NOT_A_TRANSACTION: &str =
    "Those bytes are not a transaction. Point the camera at the animation again.";

/// Unreachable by navigation, and stated rather than unwrapped: §7's hub is the only door to a
/// transaction scan and the hub does not exist until a wallet does (ADR-0010).
const NO_WALLET: &str = "No wallet is loaded, so there is nothing to check this against.";

/// The one advisory warning, as the sentence §11.2 puts inline on the fee row.
///
/// **It states the fact and does not advise** — no *this may indicate an error*, no *are you
/// sure?*. There is nothing to acknowledge and no key to press.
const FEE_ABOVE_PAYMENT: &str = "You are paying miners more than you are paying your recipient.";

/// Where a completed scan left the appliance.
///
/// Two arms because 02-core.md §7 has two, and they end differently: a screen is up and the scan
/// is over, or nothing came of the payload and the scanning screen stays live with a sentence on
/// it. **Shared with [`crate::verify`]**, which asks the same question of an address scan — it
/// lives here because this is where the two-armed answer first had to exist, and a second copy
/// of it would be a second vocabulary for one fact.
pub enum Landed {
    /// The panel or the refusal screen is showing. The camera is down.
    Shown,
    /// Still scanning, and this is what to say. No code (06-codes.md §4).
    Scanning(&'static str),
}

/// The signing flow's state: one accepted transaction, and where the walk is in it.
pub struct Review {
    session: Rc<Session>,
    /// Where a signature goes once it exists (04-screens.md §11.5). Held rather than routed,
    /// because signed bytes are a value and no value crosses the router (standing rule 4).
    outbound: Rc<Outbound>,
    /// The transaction the panel is about, kept because §11.3's walk and §11.4's gate are both
    /// about the same one — and because [`Accepted`] pairs the document with the model, so
    /// keeping it is what stops a later screen pairing this review with different bytes.
    ///
    /// `None` between transactions. Dropped on discard rather than overwritten, so a screen
    /// reached without a scan has nothing to draw instead of drawing the previous one.
    accepted: RefCell<Option<Accepted>>,
    /// Which payment the walk is on, zero-based. Not a Slint property: the frame counts no
    /// addresses (04-screens.md §11.3), and a position is a value, so it never crosses the
    /// router either.
    walk: Cell<usize>,
}

/// Build the flow's state. It wires no callback: every press on these three screens is an
/// intent, and the router is where intents land.
pub fn wire(session: Rc<Session>, outbound: Rc<Outbound>) -> Rc<Review> {
    Rc::new(Review {
        session,
        outbound,
        accepted: RefCell::new(None),
        walk: Cell::new(0),
    })
}

impl Review {
    /// A completed transaction scan. **Core validates; this shows whichever screen its answer
    /// names.**
    ///
    /// The bytes are taken by value and wrapped, so §7's *discard, zeroize, no retry with the
    /// same bytes* is the shape of the call rather than a rule someone remembers: there is no
    /// copy left for a caller to hand back, and what there was is gone as this returns.
    pub fn arrived(&self, ui: &AppWindow, bytes: Vec<u8>) -> Landed {
        let bytes = Zeroizing::new(bytes);

        let Some(wallet) = self.session.wallet() else {
            return Landed::Scanning(NO_WALLET);
        };

        match psbt::validate(wallet, &bytes) {
            Ok(accepted) => {
                self.panel(ui, &accepted.review);
                self.accepted.replace(Some(accepted));
                self.walk.set(0);
                Landed::Shown
            }
            // §7's refusal, in the standard shape and with exactly one action. Both strings
            // come from core, which is where the refusal is.
            Err(Rejection::Refused(refusal)) => {
                refused(ui, refusal);
                Landed::Shown
            }
            Err(Rejection::NotAPsbt) => Landed::Scanning(NOT_A_TRANSACTION),
        }
    }

    /// *Sign* on the panel: the walk starts at its first payment address (§11.3).
    pub fn sign(&self, ui: &AppWindow) {
        self.walk.set(0);
        self.step(ui);
    }

    /// One walk screen confirmed. The next address, or §11.4's gate once there are none left.
    pub fn advance(&self, ui: &AppWindow) {
        self.walk.set(self.walk.get().saturating_add(1));
        self.step(ui);
    }

    /// Escape inside the walk. **The panel is the nearer answer**, which is what §0's *Escape
    /// cancels wherever a cancel exists* comes to here: §11.3 is a walk *through* the review,
    /// so going back means the review and not the hub.
    pub fn back(&self, ui: &AppWindow) {
        let accepted = self.accepted.take();
        if let Some(accepted) = accepted {
            self.panel(ui, &accepted.review);
            self.accepted.replace(Some(accepted));
        }
    }

    /// §11.4's hold completed. **This is where a signature comes into existence**, and it is the
    /// only place in the appliance that one does.
    ///
    /// Core does the whole of it: `psbt::validate` established every precondition and `sign::sign`
    /// adds partial signatures to the document it was handed. Nothing here reads the transaction,
    /// asks whether it should be signed, or touches the bytes on the way past — what crosses is a
    /// serialisation, and it goes to the one slot that holds it (02-core.md §12).
    ///
    /// The `Accepted` stays in hand until the screen is left, because §8's *a re-sign is
    /// byte-identical* is only free while the document that produced it is still here — and
    /// because holding it is what makes the transaction the panel showed and the transaction that
    /// got signed the same one.
    pub fn confirm(&self, ui: &AppWindow) {
        // The borrow ends before any property is set, which is this crate's standing discipline
        // around `RefCell` and Slint.
        let signed = {
            let accepted = self.accepted.borrow();
            let (Some(accepted), Some(wallet)) = (accepted.as_ref(), self.session.wallet()) else {
                // Unreachable by navigation: the gate is only ever reached from a walk over a
                // transaction in hand, and the hub does not exist until a wallet does (ADR-0010).
                return;
            };
            sign::sign(wallet, accepted).serialize()
        };

        self.outbound.arrived(ui, signed);
    }

    /// Discard: drop the transaction. §7's one action, and also what Escape off the panel does.
    ///
    /// A no-op everywhere else, which is why the router can call it on every cancel without
    /// knowing which screen it is on.
    pub fn leave(&self) {
        self.accepted.replace(None);
        self.walk.set(0);
    }

    /// Push the model onto §11.2's panel and show it.
    ///
    /// It takes the model rather than the [`Accepted`] it came out of, because the panel is
    /// exactly `02-core.md` §9's list and the document is not on it. What pairs the two is
    /// [`Accepted`] itself, one field away, which is what a later screen signs.
    fn panel(&self, ui: &AppWindow, model: &Model) {
        ui.set_review_leaving(format::btc(model.leaving).into());
        ui.set_review_paying(format::btc(model.paying).into());
        ui.set_review_returning(format::btc(model.returning).into());
        ui.set_review_inputs(model.input_count.to_string().into());
        ui.set_review_input_total(format::btc(model.input_total).into());
        ui.set_review_fee(format::btc(model.fee).into());
        ui.set_review_fee_sat(groups(format::sat_groups(model.fee)));
        ui.set_review_fee_rate(format::fee_rate_sat_per_vb(model.fee, model.vsize).into());
        // §11.2.1: a consolidation has no ratio at all, and the absence is typed in core rather
        // than rendered as a zero, an infinity or a dash. Empty here is what *typed* looks like
        // once it reaches a layout — the element is absent, not blank.
        ui.set_review_fee_percent(
            format::fee_percent_of_paying(model.fee, model.paying)
                .unwrap_or_default()
                .into(),
        );
        ui.set_review_warning(warning(model.warning).into());
        ui.set_review_outputs(ModelRc::new(VecModel::from(rows(model))));
        ui.set_screen(Screen::Review);
    }

    /// One screen of the walk, or the gate once the payments run out.
    ///
    /// The borrow ends before any property is set, which is this crate's standing discipline
    /// around `RefCell` and Slint: a borrow still held across a property change is the shape
    /// that panics the day something re-enters here.
    fn step(&self, ui: &AppWindow) {
        let screen = {
            let accepted = self.accepted.borrow();
            accepted
                .as_ref()
                .map(|accepted| walk(&accepted.review, self.walk.get()))
        };

        match screen {
            Some(Some(step)) => {
                ui.set_address_heading(step.heading.into());
                ui.set_address_amount(step.amount.into());
                ui.set_address_groups(groups(step.groups));
                ui.set_address_last(step.last);
                ui.set_screen(Screen::Address);
            }
            // Every payment address has been confirmed, so §11.4's gate is next. **No signature
            // is produced here**: the gate is a screen, and the hold on it is what produces one
            // ([`Review::confirm`]).
            Some(None) => ui.set_screen(Screen::Gate),
            // No transaction: unreachable by navigation, since these screens are only ever
            // shown with one in hand. Nothing drawn is the honest answer to nothing held.
            None => {}
        }
    }
}

/// §7's refusal screen: the reason, the code, and one action.
fn refused(ui: &AppWindow, refusal: Refusal) {
    ui.set_refusal_reason(refusal.reason().into());
    ui.set_refusal_code(refusal.code().into());
    ui.set_screen(Screen::Refused);
}

/// One screen of §11.3's walk.
struct Step {
    heading: String,
    amount: String,
    groups: Vec<String>,
    /// Whether this is the last payment. The copy on the one control says which of the two
    /// things the press does, so the screen needs the fact and not the count.
    last: bool,
}

/// Which payment address the walk is on, or `None` when it is over.
///
/// **Payments only.** Change was settled by the byte-compare before this screen existed, and
/// giving it a confirmation screen would spend the user's attention on the one row that needs
/// none. A consolidation therefore has no walk at all, and goes straight to the gate.
fn walk(model: &Model, position: usize) -> Option<Step> {
    let payments: Vec<&OutputRow> = model
        .outputs
        .iter()
        .filter(|row| matches!(row.kind, OutputKind::Payment))
        .collect();
    let row = payments.get(position)?;

    Some(Step {
        heading: format!("Payment {} of {}", position + 1, payments.len()),
        amount: format::btc(row.amount),
        groups: format::address_groups(&row.address.to_string())
            .into_iter()
            .map(str::to_owned)
            .collect(),
        last: position + 1 == payments.len(),
    })
}

/// The panel's output rows, in the transaction's own order — payment and change alike, because
/// §11.2 counts a row as a row.
fn rows(model: &Model) -> Vec<Output> {
    model
        .outputs
        .iter()
        .enumerate()
        .map(|(index, row)| Output {
            index: (index + 1).to_string().into(),
            label: label(&row.kind).into(),
            settled: settled(&row.kind).into(),
            amount: format::btc(row.amount).into(),
            groups: groups(
                format::address_groups(&row.address.to_string())
                    .into_iter()
                    .map(str::to_owned)
                    .collect(),
            ),
        })
        .collect()
}

/// What the output is. Two words, and **no suspicion attaches to a payment**: it is what an
/// output with no claim of ours on it is, not what we think of it.
fn label(kind: &OutputKind) -> &'static str {
    match kind {
        OutputKind::Payment => "Payment",
        OutputKind::Change { .. } => "Change",
    }
}

/// §11.2's *change is presented as settled, not as a thing to check* — labelled as re-derived
/// from the seed at its path and matched byte for byte.
///
/// **The verdict is matched rather than assumed.** A screen may not state something the model
/// does not carry, so a second [`Rederivation`] arm would be a compile error here and not a
/// sentence that quietly became false.
fn settled(kind: &OutputKind) -> String {
    match kind {
        OutputKind::Payment => String::new(),
        OutputKind::Change {
            path,
            verdict: Rederivation::MatchedByteForByte,
        } => format!(
            "re-derived from the seed at {} and matched byte for byte",
            identity::notation(path)
        ),
    }
}

/// The one advisory warning, or nothing.
///
/// One `match` and no condition: core decided, and this is where its decision becomes copy.
fn warning(warning: Option<Warning>) -> &'static str {
    match warning {
        None => "",
        Some(Warning::FeeAbovePayment) => FEE_ABOVE_PAYMENT,
    }
}

/// Groups as a model, ready for the layout that separates them with §0's sub-cell gap.
///
/// The gap is the layout's, not ours: `format.rs` returns groups **as data** precisely so that
/// nothing on the way here can turn the gap into a space character occupying a full monospace
/// cell (§0, §11.2.1).
///
/// `pub(crate)` for §12's verdict screen, which draws an address at full width for the same
/// reason §11.3's walk does: one function, so the two cannot disagree about what a group is.
pub(crate) fn groups(groups: Vec<String>) -> ModelRc<SharedString> {
    ModelRc::new(VecModel::from(
        groups
            .into_iter()
            .map(SharedString::from)
            .collect::<Vec<_>>(),
    ))
}

/// The widest address class this appliance ships: a 62-character P2TR bech32m address.
///
/// It is the number 00-overview.md's owed measurement is written about, and the reason it is a
/// constant rather than a reading off a real transaction is that the claim has to hold for an
/// address nobody has scanned yet.
pub const WIDEST_ADDRESS_CHARS: u32 = 62;

/// How wide an address of `chars` characters is when laid out in §0's 4-character groups: the
/// cells, plus one sub-cell gap between each pair of groups.
///
/// `cell` and `gap` are **measured**, from the component that draws — see `AddressBlock` in
/// `app.slint`. That is what makes the number this returns a fact about the font on the shipped
/// image rather than a fact about our arithmetic.
#[must_use]
pub fn address_width(chars: u32, cell: f32, gap: f32) -> f32 {
    let groups = chars.div_ceil(4);
    chars as f32 * cell + groups.saturating_sub(1) as f32 * gap
}

#[cfg(test)]
#[path = "review_tests.rs"]
mod tests;
