//! `aobs` — the shell.
//!
//! It draws, and in later slices it reads the keyboard and runs the camera. **It decides
//! nothing about money and branches on no validation outcome** (`04-screens.md`); that
//! rule is what keeps it honestly outside the coverage gate.
//!
//! This is the walking skeleton ([#39](https://github.com/allisson/aobs/issues/39)): one
//! Slint screen on `backend-linuxkms` + `renderer-software`, holding DRM master on tty1.
//! No wallet logic, no camera, no QR.

mod buildinfo;
mod console;
mod entropy;
mod fail;
mod notify;

use fail::Failure;

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
        Ok(Ok(())) => fail::halt(Failure::EventLoopExited),
        Ok(Err(failure)) => fail::halt(failure),
        Err(_) => fail::halt(Failure::Panicked),
    }
}

fn run() -> Result<(), Failure> {
    // The first of the eight owed measurements (00-overview.md). Derived as 1–16 s under
    // `random.trust_cpu=off`; this is what makes it a number. The "gathering entropy"
    // screen belongs with wallet creation (04-screens.md §2), not here.
    console::emit("AOBS_ENTROPY_WAIT_BEGIN");
    let elapsed_ms = entropy::time_until_ready().map_err(|_| Failure::EntropyUnavailable)?;
    console::emit(&format!("AOBS_ENTROPY_MS={elapsed_ms}"));

    let ui = AppWindow::new().map_err(|_| Failure::DisplayUnavailable)?;
    ui.set_version(buildinfo::VERSION.into());
    ui.set_build_date(buildinfo::build_date().into());

    // The readiness line, printed from inside the running event loop rather than before
    // it. That placement is the point: the line asserts the loop came up, which is what
    // the QEMU harness keys on instead of diffing a screenshot
    // (05-testing-and-release.md §6.2). Its *absence* is what marks the §9 path.
    slint::Timer::single_shot(std::time::Duration::ZERO, || {
        console::emit(&format!(
            "AOBS_READY version={} build={}",
            buildinfo::VERSION,
            buildinfo::build_date(),
        ));
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

    ui.run().map_err(|_| Failure::DisplayUnavailable)?;
    Ok(())
}
