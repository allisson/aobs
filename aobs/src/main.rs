//! `aobs` — the shell.
//!
//! It draws, it reads the keyboard, it answers the power button, and it takes the one camera
//! frame the entropy mix wants. **It decides nothing about money and branches on no
//! validation outcome** (`04-screens.md`); that rule is what keeps it honestly outside the
//! coverage gate, and `router` is where it is visible rather than asserted.
//!
//! The frame is [#69](https://github.com/allisson/aobs/issues/69): the start menu, the
//! chrome that does not vanish, and §13's ending. Creating a wallet is
//! [#72](https://github.com/allisson/aobs/issues/72) — `create`, the dice and the 24 words —
//! and [#73](https://github.com/allisson/aobs/issues/73) closes it with `confirm`, the retype.
//! [#74](https://github.com/allisson/aobs/issues/74) is `load`, `session` and `identity`: the
//! passphrase, the network, ADR-0010's `OnceLock`, and the hub the first journey ends on.
//! [#75](https://github.com/allisson/aobs/issues/75) is `import`, §6's seed entry — and the two
//! modules it made structural: `phrase`, which is §5's *one screen on every load path* as state,
//! and `typing`, the two adapters every word-entry screen restates core with.
//! [#78](https://github.com/allisson/aobs/issues/78) is the QR boundary's near side: `camera`
//! grew the capture loop, `qr` is `rqrr` on a luma plane, and `scan` is §11.1's one screen in
//! its three configurations. [#81](https://github.com/allisson/aobs/issues/81) is `review`:
//! §11.2's panel, §11.3's per-address walk, and the screen 02-core.md §7's refusal ends on.
//! [#82](https://github.com/allisson/aobs/issues/82) is the far side of it: §11.4's hold-to-confirm
//! gate, core's signing call, and `outbound` — §11.5's animation at 4 fps and 02-core.md §12's one
//! re-display slot. [#83](https://github.com/allisson/aobs/issues/83) is `verify`: §12's two
//! verdicts over core's receive-address search.

mod buildinfo;
mod camera;
mod confirm;
mod console;
mod create;
mod display;
mod entropy;
mod fail;
mod gate;
mod identity;
mod import;
mod load;
mod notify;
mod outbound;
mod phrase;
mod power;
mod qr;
mod review;
mod router;
mod scan;
mod session;
mod typing;
mod verify;

use std::rc::Rc;

use fail::Failure;
use router::Ending;

slint::include_modules!();

fn main() -> ! {
    // The default panic hook prints the panic payload and a source location to stderr,
    // and systemd puts stderr on the kernel console. That is the one output path that
    // survives a crash, and 01-boot-layer.md §9 rules it prints **only fixed strings and
    // typed error-variant names, never formatted program state** — the same rule that
    // governs logs and `Debug`. A panic payload is formatted program state by
    // construction, so the hook is silenced and `fail::halt` writes the whole diagnostic.
    std::panic::set_hook(Box::new(|_| {}));

    // `panic = "unwind"`, never `abort` (01-boot-layer.md §10): drop glue is where the
    // zeroization guarantee lives, and abort skips it. Catching here is the other half —
    // the top level catches, unwinding has already dropped, and we exit into §9.
    match std::panic::catch_unwind(run) {
        // The exit status is the shutdown mechanism, and it is the whole of it (ADR-0017,
        // 01-boot-layer.md §2). `run` has returned, so the window is dropped, DRM master is
        // released and every frame between here and the wallet is gone — the app dies first
        // and the machine goes down afterwards, which is what makes §5's RAM wipe
        // unconditional rather than a claim about someone else's ordering.
        Ok(Ok(ending)) => std::process::exit(ending.exit_code()),
        Ok(Err(failure)) => fail::halt(failure),
        Err(_) => fail::halt(Failure::Panicked),
    }
}

fn run() -> Result<Ending, Failure> {
    // The first of the eight owed measurements (00-overview.md). Derived as 1–16 s under
    // `random.trust_cpu=off`; this is what makes it a number. The "gathering entropy"
    // screen belongs with wallet creation (04-screens.md §2), not here.
    console::emit("AOBS_ENTROPY_WAIT_BEGIN");
    let elapsed_ms = entropy::time_until_ready().map_err(|_| Failure::EntropyUnavailable)?;
    console::emit(&format!("AOBS_ENTROPY_MS={elapsed_ms}"));

    // Creating the window is what opens the display, so the mode is learned here and not
    // before: `AppWindow::new()` failing means there was nothing to learn it from, and
    // display::window_failure() is what splits 06-codes.md §5's two conditions apart.
    let ui = AppWindow::new().map_err(|_| display::window_failure())?;
    ui.set_version(buildinfo::VERSION.into());
    ui.set_build_date(buildinfo::build_date().into());

    // The mode is an input; the scale factor is the whole of our answer to it
    // (04-screens.md §0). Above the design canvas the layout does not grow — the type
    // does; at or below it the scale stays 1 and reflow bends instead.
    let mode = ui.window().size();
    let scale = display::scale(mode.width, mode.height);
    let (logical_width, logical_height) = display::logical(mode.width, mode.height);
    console::emit(&format!(
        "AOBS_PANEL mode={}x{} scale={:.2} logical={}x{}",
        mode.width, mode.height, scale, logical_width, logical_height,
    ));

    // Below the floor we refuse before anything is drawn, on the live console §9 leaves us
    // (04-screens.md §0). The window is dropped as this returns, which releases DRM master
    // and gives the kernel its console back on `lastclose`, so the diagnostic `main` then
    // prints has a panel to land on. **A UI is never shown** — a screen too small to
    // review a transaction on must not be a screen the user can sign from.
    if display::below_floor(mode.width, mode.height) {
        return Err(Failure::ModeBelowFloor);
    }

    ui.window()
        .dispatch_event(slint::platform::WindowEvent::ScaleFactorChanged {
            scale_factor: scale,
        });

    // 04-screens.md §3's owed measurement, taken against the canvas the appliance just
    // learned rather than in a browser frame: the words screen's own heights — the same
    // properties the layout is built from — against the room the chrome leaves it. Printed
    // on every boot, and asserted by the CI row that runs at the 800×600 floor
    // (05-testing-and-release.md §6.2), which is the only geometry where it can fail: at or
    // above the design size the logical canvas is never smaller than 1280×800.
    let metrics = ui.global::<Metrics>();
    let slot_height = logical_height as f32 - metrics.get_slot_chrome();
    let words_required = metrics.get_words_required();
    console::emit(&format!(
        "AOBS_WORDS required={words_required:.0} available={slot_height:.0} fits={}",
        if words_required <= slot_height {
            "yes"
        } else {
            "no"
        },
    ));

    // §0's second breakpoint, decided once for the whole appliance and read by every screen
    // that has two states. The mode cannot change under a running appliance — the DRM tier
    // took the connector's preferred mode and the fbdev tier took the firmware's — so this is
    // an input like the mode itself, not something the layout recomputes.
    let wide = display::wide(mode.width, mode.height);
    ui.set_wide(wide);

    // How much width an address gets, at the two places one is drawn at full width. Handed in
    // rather than derived inside the layout, because an address block's height is a function of
    // it (04-screens.md §11.2, `display::rooms`).
    let padding = if wide {
        metrics.get_slot_padding_wide()
    } else {
        metrics.get_slot_padding()
    };
    let (review_room, walk_room) = display::rooms(
        logical_width,
        wide,
        padding,
        metrics.get_rail_width(),
        metrics.get_rail_gap(),
    );
    ui.set_review_room(review_room);
    ui.set_walk_room(walk_room);

    // §11.5's symbol is a square, so it takes the tighter of the two axes — and it is handed in
    // for the reason the two rooms above are: a square sized by what is left over is a constraint
    // derived from the space it consumes.
    ui.set_outbound_room(display::qr_side(
        walk_room,
        slot_height,
        metrics.get_outbound_chrome(),
    ));

    // 04-screens.md §1: with no camera the third start entry is visibly unavailable with its
    // reason stated, not hidden. Probed here because this is where the start menu is about
    // to be drawn — 01-boot-layer.md §7 enumerates V4L2 devices at the point of use, so a
    // camera plugged in later is not something a startup decision can have ruled out.
    ui.set_camera_present(camera::present());

    // 04-screens.md §5's *one screen, always present, on every load path*, as the state that
    // makes it true: create and import both write the phrase here and the load screen reads it,
    // so there is no arm anywhere choosing between two sources.
    let phrase = Rc::new(phrase::Phrase::new());

    // The create path's own state, and the two callbacks that carry a value rather than an
    // intent (04-screens.md §2). Wired before the router, which holds it to reach §2 and §3.
    let create = create::wire(&ui, phrase.clone());

    // §4's retype, and the three callbacks that carry a keystroke rather than an intent. Its
    // state is core's — the phrase, the prefix matching and the per-word compare — and this
    // module holds only what the screen draws.
    let confirm = confirm::wire(&ui, phrase.clone());

    // §6's seed import: the same reducer over the same grid, knowing no answer, with its own
    // three keystroke callbacks — two screens holding two entries, so neither callback has to
    // ask which one is live.
    let import = import::wire(&ui, phrase.clone());

    // ADR-0010's `OnceLock`, and the reason it is a local rather than a `static`: a `static` is
    // never dropped, so the wallet's wrapped master key would never be zeroized and §5's wipe
    // would rest on `init_on_free` alone. This dies as `run` returns, which is before `main`
    // exits into the shutdown status.
    let session = Rc::new(session::Session::new());

    // §5's one load screen, and the three callbacks that carry a value rather than an intent. It
    // holds the phrase's owner and the session, because confirming is where a wallet comes into
    // existence and both are what that needs.
    let load = load::wire(&ui, phrase, session.clone());

    // §11.2's panel and §11.3's walk. It holds the session because validating a transaction is
    // the one thing on this path that needs the wallet, and it is built before `scan` because a
    // completed transaction scan hands its payload straight to it (standing rule 4: a payload is
    // a value and does not cross the router).
    // §11.4's hold. Wired before the router because it produces an intent the router marshals,
    // and it holds nothing but a clock (04-screens.md §11.4).
    let _gate = gate::wire(&ui);

    // §11.5's animation and 02-core.md §12's one slot. Built before `review`, which holds it:
    // signed bytes are a value, so they go from the screen that produced them to the screen that
    // shows them rather than through the router (standing rule 4).
    let outbound = outbound::wire();

    let review = review::wire(session.clone(), outbound.clone());

    // §12's verdict. It holds the session for the same reason `review` does — the search is over
    // our own key material — and it is built before `scan` because a completed address scan hands
    // its payload straight to it (standing rule 4: a scanned address is a value too).
    let verify = verify::wire(session.clone());

    // §11.1's one scanning screen, in whichever of its three configurations the router asks
    // for. It holds no wallet and no payload: the camera thread and core's `Scanner` are the
    // whole of its state.
    let scan = scan::wire(&ui, review.clone(), verify);

    // Everything the user can ask for goes through here, and nothing else. The cell is where
    // §13's answer lands, because the event loop is what ends and it carries nothing back.
    let ending = router::wire(
        &ui,
        router::Screens {
            create: create.clone(),
            confirm,
            import,
            load,
            scan,
            review,
            outbound,
            session,
        },
    );

    // The readiness line, printed from inside the running event loop rather than before
    // it. That placement is the point: the line asserts the loop came up, which is what
    // the QEMU harness keys on instead of diffing a screenshot
    // (05-testing-and-release.md §6.2). Its *absence* is what marks the §9 path.
    //
    // It carries the tier that won (01-boot-layer.md §2), without which a green display
    // row would prove only that *something* drew.
    let handle = ui.as_weak();
    slint::Timer::single_shot(std::time::Duration::ZERO, move || {
        console::emit(&format!(
            "AOBS_READY version={} build={} display={}",
            buildinfo::VERSION,
            buildinfo::build_date(),
            display::tier(),
        ));

        // 04-screens.md §11.2's two owed measurements, both taken against the canvas the
        // appliance learned and the font it actually has (00-overview.md,
        // 05-testing-and-release.md §6.2). **From inside the loop rather than beside
        // `AOBS_WORDS`**: the address half is a text measurement, and a Text's preferred width
        // is not a number this backend has before the font is loaded — printing it earlier
        // would print a zero and call it a pass.
        //
        // The row half is arithmetic over the panel's own heights, the same way the words
        // screen's is. The address half divides the measured width of one 4-character group by
        // four, so both halves are numbers the layout is built from rather than numbers
        // computed a second time beside it.
        if let Some(ui) = handle.upgrade() {
            console::emit(&measurement(&ui, slot_height, review_room));
        }
    });

    // Readiness for `Type=notify` (01-boot-layer.md §2), and it must land **after** the
    // first frame. The detach it releases unbinds `fbcon` from the framebuffer the app
    // draws into, and unbinding may clear that memory on the way out — Slint does not
    // repaint pixels it believes unchanged, so a detach landing before the first frame
    // would be indistinguishable from a working one until a machine somewhere showed a
    // black panel. Nothing is written to the console here either: after the first paint
    // anything printed stays on the panel (§2), which is what makes this a bare datagram
    // rather than a marker line.
    //
    // The delay is the crude part. Slint's software renderer supports no rendering
    // notifier, so there is no "first frame presented" callback to hook; three seconds is
    // far longer than a first software-rendered frame takes even under TCG, and it costs
    // three seconds of boot. If Slint grows a presented-frame signal on this backend,
    // this becomes that signal.
    slint::Timer::single_shot(std::time::Duration::from_secs(3), notify::ready);

    // A loop that ends is a loop that ended, whether it returns `Ok` or an error: the
    // display was there, since it drew. `AOBS-E02` is no longer that case — 06-codes.md §5
    // narrowed it to *no display at all* — and E03 is what covers a loop nothing asked to
    // return.
    let outcome = ui.run();

    // A failure raised from inside the loop outranks both the ending and the loop's own
    // return, because it is *why* the loop ended: `AOBS-E01` is the only one that can be,
    // and it means the kernel refused a request that is not supposed to be refusable
    // (06-codes.md §5). Read before `outcome`, so the real reason is not overwritten by the
    // generic one.
    if let Some(failure) = create.failure() {
        return Err(failure);
    }
    outcome.map_err(|_| Failure::EventLoopExited)?;

    // Nothing but §13 ends the loop, so a loop that ended with no ending in the cell ended
    // for a reason nobody asked for — which is exactly what `AOBS-E03` is (06-codes.md §5).
    ending.get().ok_or(Failure::EventLoopExited)
}

/// The review panel's two owed measurements as one console line
/// (`05-testing-and-release.md` §6.2).
///
/// ```text
/// AOBS_REVIEW rows-required=… rows-available=… rows-fit=yes|no \
///             address-required=… address-available=… address-one-line=yes|no|unknown
/// ```
///
/// **`unknown` rather than a guess** when the group measurement came back at or below zero
/// (standing rule 8). A zero would make `address-required` zero and every canvas a pass, which
/// is the one way this line could report a green that means nothing — so it says it does not
/// know, and `ci/qemu-boot.sh` fails a boot that says so.
///
/// Both halves are read off the layout, not recomputed: `review-required` is the sum
/// `Metrics.review-required` builds the panel from, and the address cell is the width
/// `AddressBlock`'s own ruler measured in the face and size it draws in.
fn measurement(ui: &AppWindow, slot_height: f32, room: f32) -> String {
    let rows_required = ui.global::<Metrics>().get_review_required();
    let cell = ui.get_address_cell();
    let gap = ui.get_address_gap();
    let required = review::address_width(review::WIDEST_ADDRESS_CHARS, cell, gap);

    let one_line = if cell <= 0.0 {
        "unknown"
    } else if required <= room {
        "yes"
    } else {
        "no"
    };

    format!(
        "AOBS_REVIEW rows-required={rows_required:.0} rows-available={slot_height:.0} \
         rows-fit={} address-required={required:.0} address-available={room:.0} \
         address-one-line={one_line}",
        if rows_required <= slot_height {
            "yes"
        } else {
            "no"
        },
    )
}
