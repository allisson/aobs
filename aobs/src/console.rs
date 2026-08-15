//! The one output channel that survives a GUI that never came up.
//!
//! Because `simpledrm` is guaranteed on UEFI (ADR-0009), the kernel console always
//! exists — there is always a channel (01-boot-layer.md §9). The systemd unit puts this
//! process's stdout on it.
//!
//! The serial mirror is what lets the QEMU harness (05-testing-and-release.md §6.2) read
//! the readiness line without diffing a screenshot. It is a mirror, not a second
//! behaviour: the same bytes, and nothing is written there that is not also written to
//! the console the user is looking at. On a machine with no serial port the open fails
//! and nothing happens.

use std::io::Write;

/// Write one line to the kernel console, and to the serial port if the machine has one.
pub fn emit(line: &str) {
    // `println!` panics if the write fails, and this is the function the panic path
    // itself calls. A broken stdout must not turn a reportable failure into a silent one.
    let mut out = std::io::stdout().lock();
    let _ = writeln!(out, "{line}");
    let _ = out.flush();
    drop(out);

    if let Ok(mut serial) = std::fs::OpenOptions::new().write(true).open("/dev/ttyS0") {
        let _ = writeln!(serial, "{line}");
    }
}
