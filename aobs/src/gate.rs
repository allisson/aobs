//! §11.4's hold, and the clock behind it (`04-screens.md` §11.4).
//!
//! **The hold is measured against wall clock, not counted in ticks**, and that distinction is a
//! defect this module exists to have already fixed. The first version accumulated
//! `Metrics.hold-tick` inside the frame on every tick of a Slint `Timer` — which is three seconds
//! only if every tick lands on time, and on the software renderer at 800×600 a tick that repaints a
//! progress bar does not: **3.5 s of held key reached 97% of the bar** on the built ISO. A hold that
//! silently takes longer than it says is the safe direction, and it is still a screen lying about
//! what it wants.
//!
//! **The gesture is here rather than in the frame for two reasons.** One is the above: `Instant` is
//! the shell's to read and the frame has no clock. The other is that it makes the arithmetic a
//! function — [`progress`] — instead of an expression inside a layout, so the one number that gates
//! the irreversible action is testable.
//!
//! **It decides nothing about money** (standing rule 4). What it produces is
//! [`crate::Intent::SignConfirm`], which is *what the user asked for*, and it goes through the same
//! callback every other press does. Whether there is a transaction to sign is
//! [`crate::review`]'s question and it asks core.

use std::cell::Cell;
use std::rc::Rc;
use std::time::{Duration, Instant};

use slint::{ComponentHandle, Timer, TimerMode};

use crate::{AppWindow, Intent, Metrics};

/// How far through the hold, clamped to `0.0..=1.0`.
///
/// A ratio rather than a remaining time, because §11.4's control is a bar: a number counting down
/// invites watching the number instead of deciding.
fn progress(elapsed: Duration, duration: Duration) -> f32 {
    if duration.is_zero() {
        return 1.0;
    }
    (elapsed.as_secs_f32() / duration.as_secs_f32()).clamp(0.0, 1.0)
}

/// The hold's state: when the key went down, and the clock watching it.
pub struct Gate {
    /// `Some` while a key is down on the hold row. **Cleared before the intent is dispatched**, so
    /// the screen change that follows cannot find a hold still running.
    started: Cell<Option<Instant>>,
    timer: Timer,
}

/// Wire the frame's two hold callbacks.
///
/// They are callbacks rather than intents because neither is something the user asked *for*: a key
/// going down is not a decision, and the decision is what the clock dispatches.
pub fn wire(ui: &AppWindow) -> Rc<Gate> {
    let gate = Rc::new(Gate {
        started: Cell::new(None),
        timer: Timer::default(),
    });

    let metrics = ui.global::<Metrics>();
    // Slint durations cross the generated interface as milliseconds in an `i64`.
    let duration = millis(metrics.get_hold_duration(), 3_000);
    let tick = millis(metrics.get_hold_tick(), 50);

    let owner = gate.clone();
    let handle = ui.as_weak();
    ui.on_hold_begin(move || {
        let Some(ui) = handle.upgrade() else {
            return;
        };
        owner.begin(&ui, duration, tick);
    });

    let owner = gate.clone();
    let handle = ui.as_weak();
    ui.on_hold_end(move || {
        if let Some(ui) = handle.upgrade() {
            owner.end(&ui);
        }
    });

    gate
}

impl Gate {
    /// A key went down on the hold row.
    ///
    /// **Idempotent while the hold runs**, so a key repeat neither restarts the clock nor extends
    /// it. This backend synthesises no repeat today; a backend that started to must not be able to
    /// change how long the hold takes.
    fn begin(&self, ui: &AppWindow, duration: Duration, tick: Duration) {
        if self.started.get().is_some() {
            return;
        }
        let began = Instant::now();
        self.started.set(Some(began));
        ui.set_hold_progress(0.0);

        let handle = ui.as_weak();
        self.timer.start(TimerMode::Repeated, tick, move || {
            let Some(ui) = handle.upgrade() else {
                return;
            };
            let elapsed = began.elapsed();
            if elapsed < duration {
                ui.set_hold_progress(progress(elapsed, duration));
                return;
            }
            // **The intent is dispatched last, and from a state that already says the hold is
            // over.** Showing §11.5's animation changes the screen, which the frame answers by
            // calling `hold-end` — so the clock has to be stopped and the bar cleared before that
            // reaches back in here, not after.
            ui.invoke_hold_end();
            ui.invoke_intent(Intent::SignConfirm);
        });
    }

    /// The key came up, the cursor moved, or the screen changed. **Any of the three is a cancel.**
    ///
    /// Releasing early is what makes a tap safe: the intent is dispatched only by the clock
    /// reaching the duration, and this is the only other way the clock ever stops.
    fn end(&self, ui: &AppWindow) {
        self.timer.stop();
        self.started.set(None);
        ui.set_hold_progress(0.0);
    }
}

/// A Slint `duration` as a [`Duration`], with a fallback for the negative value the type allows
/// and the layout never holds.
fn millis(value: i64, fallback: u64) -> Duration {
    Duration::from_millis(u64::try_from(value).unwrap_or(fallback))
}

#[cfg(test)]
mod tests {
    use super::{millis, progress};
    use std::time::Duration;

    const THREE_SECONDS: Duration = Duration::from_secs(3);

    /// §11.4's bar, at its two ends and its middle.
    #[test]
    fn the_bar_runs_from_empty_to_full_across_the_hold() {
        assert_eq!(progress(Duration::ZERO, THREE_SECONDS), 0.0);
        assert!((progress(Duration::from_millis(1_500), THREE_SECONDS) - 0.5).abs() < 1e-6);
        assert_eq!(progress(THREE_SECONDS, THREE_SECONDS), 1.0);
    }

    /// **A slow repaint overruns the duration rather than shortening it**, and the bar stops at
    /// full rather than drawing past the end of its track. This is the defect the ISO walk found,
    /// as an assertion: the first version accumulated ticks, so wall clock past the duration read
    /// as *less* than full.
    #[test]
    fn an_overrun_is_full_and_never_more() {
        assert_eq!(progress(Duration::from_secs(4), THREE_SECONDS), 1.0);
        assert_eq!(progress(Duration::from_secs(600), THREE_SECONDS), 1.0);
    }

    /// A zero duration would be a gate that is not one, so it reads as complete rather than
    /// dividing by zero. It is not a state the layout can be in — `Metrics.hold-duration` is
    /// `3s` — and this is what stops a future edit to that constant from being a panic.
    #[test]
    fn a_zero_duration_is_already_complete() {
        assert_eq!(progress(Duration::ZERO, Duration::ZERO), 1.0);
    }

    #[test]
    fn a_negative_slint_duration_falls_back_rather_than_wrapping() {
        assert_eq!(millis(50, 999), Duration::from_millis(50));
        assert_eq!(millis(-1, 999), Duration::from_millis(999));
    }
}
