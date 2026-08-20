//! The router. **It marshals, and that is the whole of it.**
//!
//! 04-screens.md opens on the rule this module is the structural home of: the shell *decides
//! nothing about money and branches on no validation outcome*. That rule is what keeps the
//! shell honestly outside 05-testing-and-release.md §1's coverage gate, and it is only worth
//! anything if it is visible in one place instead of asserted in a comment. So:
//!
//! * The frame hands over an [`Intent`] — what the user asked for — and never a value.
//! * Every arm below is a screen assignment or an ending. No arm inspects a PSBT, an
//!   address, a checksum or a byte the user typed; there is nothing here for a validation
//!   outcome to reach.
//! * **A later slice adding a screen adds an arm and changes no decision.** That is the
//!   acceptance criterion in [#69](https://github.com/allisson/aobs/issues/69), and the
//!   shape that satisfies it is a `match` over intents with one destination each.
//!
//! Refusals are core's (`02-core.md` §7), and they reach the user as a screen the router was
//! *told* to show, never as a branch taken here.

use std::cell::Cell;
use std::rc::Rc;

use slint::ComponentHandle;

use crate::confirm::Confirm;
use crate::create::Create;
use crate::load::Load;
use crate::power;
use crate::session::Session;
use crate::{AppWindow, Intent, Screen};

/// How the session ended, and therefore how the process exits.
///
/// **The exit status is the shutdown mechanism, and it is the whole of it** (ADR-0017,
/// 01-boot-layer.md §2). The app dies first and the machine goes down afterwards, which is
/// what makes the RAM wipe unconditional: `init_on_free=1` poisons pages when they are
/// *freed*, and process death is what frees them. Never `systemctl poweroff` and never
/// `reboot(2)` — both leave the seed in RAM while the machine goes down, and the second one
/// powers off from inside the kernel without killing userspace at all.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Ending {
    /// *Shut down*, which is the same action as *end the session* (04-screens.md §13).
    Shutdown,
    /// *Start over with a different wallet*: a fresh process with a fresh `OnceLock`
    /// (ADR-0010), delivered by `Restart=always`, not by rebooting the machine.
    Restart,
}

impl Ending {
    /// The status the unit is written against.
    ///
    /// 42 is declared successful and restart-prevented, so the unit reaches inactive and
    /// `SuccessAction=poweroff` fires. 0 is a plain successful exit that `Restart=always`
    /// brings straight back. Anything else is a crash, which is 01-boot-layer.md §2's
    /// stated product fact and not ours to produce here.
    pub fn exit_code(self) -> i32 {
        match self {
            Self::Shutdown => 42,
            Self::Restart => 0,
        }
    }
}

/// Wire the frame's one callback and the power button, and hand back the cell the ending
/// lands in.
///
/// The cell rather than a return value because the ending is produced from inside a running
/// event loop: `slint::quit_event_loop` is what ends `ui.run()`, and it carries nothing.
/// `None` after the loop returns is 06-codes.md §5's `AOBS-E03` — a loop that ended without
/// anyone asking it to.
pub fn wire(
    ui: &AppWindow,
    create: Rc<Create>,
    confirm: Rc<Confirm>,
    load: Rc<Load>,
    session: Rc<Session>,
) -> Rc<Cell<Option<Ending>>> {
    let ending = Rc::new(Cell::new(None));

    let sink = ending.clone();
    let handle = ui.as_weak();
    ui.on_intent(move |intent| {
        let Some(ui) = handle.upgrade() else {
            return;
        };
        match intent {
            // 04-screens.md §2 and §3, and the shape of the rule holds: each arm is a
            // destination. `begin` shows the dice screen and starts gathering behind it;
            // `words` mixes what was gathered and shows the phrase. Neither returns a value
            // to branch on, and nothing here reads a roll, a byte or a word.
            //
            // `forget` is not a second decision: choosing *create* is choosing a phrase, and
            // a retype in progress was typed against the previous one. Dropping it here is
            // what keeps the two from being compared to each other.
            Intent::Create => {
                confirm.forget();
                create.begin(&ui);
            }
            Intent::CreateContinue => create.words(&ui),

            // 04-screens.md §4's retype, from either side of it: the first visit and the
            // return from a marked position are the same destination, because the entry state
            // is kept and *nothing is destroyed*. `done` is `⏎`, which core answers.
            Intent::CreateConfirm => confirm.begin(&ui, &create),
            Intent::CreateDone => confirm.done(&ui),

            // The other two start entries. Their screens arrive in later slices.
            Intent::Import | Intent::Restore => ui.set_screen(Screen::Unbuilt),

            // 04-screens.md §5's confirm, and the one place a wallet comes into existence. The
            // arm is still a destination: `confirm` derives, hands the session its one wallet
            // and shows §7's hub, and nothing here reads the passphrase, the network or the
            // fingerprint that comes back.
            Intent::LoadConfirm => load.confirm(&ui),

            // §7's four actions. One destination for four intents, because they *have* one
            // destination in this build — the frame names what the user asked for and says so
            // rather than swallowing the press (standing rule 8), and each of them becomes its
            // own arm when its screen exists.
            Intent::WatchOnly | Intent::Sign | Intent::VerifyAddress | Intent::BackupExport => {
                ui.set_screen(Screen::Unbuilt)
            }

            // §13's confirm, reached identically from the footer row and from the physical
            // button. Idempotent on purpose: a second press is not a faster path to
            // shutdown, so an accidental knock costs a press to undo rather than a session.
            Intent::SessionEnd => ui.set_screen(Screen::Ending),

            // Escape. *Whether a cancel exists* is answered here, by there being somewhere
            // to go back to — the start menu is where every path in this build begins, and
            // cancelling on it is a no-op rather than a hidden exit.
            //
            // The retype is the first screen with a nearer answer than the start menu, and
            // 04-screens.md §4 is why: cancelling out of it has to return to the phrase, with
            // the mark still on it, because the paper is what the user is holding.
            //
            // **And once a wallet exists the start menu is no longer an answer at all**, which
            // is the change [#69](https://github.com/allisson/aobs/issues/69) predicted this arm
            // would need: 04-screens.md §13 rules that any *close the wallet and return to the
            // start screen* is a switch wearing a different name (ADR-0010), so Escape returns
            // to §7's hub instead. On the hub itself that is the no-op cancelling on the start
            // menu is — there is somewhere to go back to, and it is where you are.
            Intent::Cancel => match ui.get_screen() {
                Screen::Retype => ui.set_screen(Screen::Words),
                _ if session.loaded() => ui.set_screen(Screen::Identity),
                _ => ui.set_screen(Screen::Start),
            },

            Intent::ShutDown => {
                sink.set(Some(Ending::Shutdown));
                let _ = slint::quit_event_loop();
            }
            Intent::Restart => {
                sink.set(Some(Ending::Restart));
                let _ = slint::quit_event_loop();
            }
        }
    });

    // The button lands on the same confirm the footer row does, by going through the same
    // callback rather than by setting the screen itself — one path, so the two cannot drift
    // apart (ADR-0017).
    let handle = ui.as_weak();
    power::watch(move || {
        let _ = handle.upgrade_in_event_loop(|ui| ui.invoke_intent(Intent::SessionEnd));
    });

    ending
}

#[cfg(test)]
mod tests {
    use super::Ending;

    #[test]
    fn shutdown_exits_forty_two_and_restart_exits_zero() {
        assert_eq!(Ending::Shutdown.exit_code(), 42);
        assert_eq!(Ending::Restart.exit_code(), 0);
    }

    #[test]
    fn the_unit_is_written_against_the_same_numbers() {
        // The exit status and the unit are one decision in two files (ADR-0017), and this
        // is the cheap half of 05-testing-and-release.md §6's rule about verifying the
        // shipped artifact: a crate that exited 41 while the unit still declared 42 would
        // power the machine off through a *failed* unit, or not at all.
        let unit = include_str!(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../image/config/includes.chroot/etc/systemd/system/aobs.service"
        ));
        let shutdown = Ending::Shutdown.exit_code();

        assert!(
            unit.contains(&format!("\nSuccessExitStatus={shutdown}\n")),
            "the unit must declare the shutdown status successful"
        );
        assert!(
            unit.contains(&format!("\nRestartPreventExitStatus={shutdown}\n")),
            "the unit must let the shutdown status stay dead"
        );
        assert!(
            unit.contains("\nSuccessAction=poweroff\n"),
            "and something has to take the machine down once it does"
        );

        // The restart path is the same key doing nothing special: 0 is not prevented, so
        // `Restart=always` brings a fresh process back.
        assert_eq!(Ending::Restart.exit_code(), 0);
        assert!(unit.contains("\nRestart=always\n"));
    }
}
