//! The power button, read from its own input device.
//!
//! No `systemd-logind` runs on this image and no D-Bus is installed, so nothing else can
//! answer the button (01-boot-layer.md §2, ADR-0017). The kernel presents the ACPI button
//! as its own device — named `Power Button`, carrying `KEY_POWER` — and `signer`'s `input`
//! group already reaches it, so a press routes to 04-screens.md §13's confirm and the
//! physical button does exactly what the on-screen row does, confirmation included.
//!
//! **Not through Slint's key path.** Slint delivers the key, but with no identity: the text
//! is a single NUL byte, which is what any keysym with no UTF-8 form yields, so matching on
//! it would make a USB keyboard's volume keys end the session. On this node the identity is
//! exact. Measured on the built ISO in
//! [#89](https://github.com/allisson/aobs/issues/89): `event1 name=Power Button`,
//! `code=116`, and Slint's `len=1 hex=00`.
//!
//! **No crate, and no ioctl.** The name is in sysfs, which is a `read_to_string`, and the
//! event is 24 fixed bytes. `EVIOCGNAME` would need `libc` and an `unsafe` block to learn
//! the same string.

use std::io::Read;

/// `EV_KEY` — the only event type this appliance reads.
const EV_KEY: u16 = 1;
/// `KEY_POWER`. Observed on the built ISO, not read off a header.
const KEY_POWER: u16 = 116;

/// `struct input_event` on a 64-bit kernel: a 16-byte `timeval`, then `type`, `code` and a
/// 32-bit `value`. The size is fixed, which is what makes this a `read_exact` and not a
/// parser.
const EVENT_SIZE: usize = 24;

/// The device's name in sysfs. Compared exactly, after trimming the newline sysfs appends:
/// `Sleep Button` is a sibling node on the same ACPI driver, and it is not this one.
fn is_power_button(name: &str) -> bool {
    name.trim() == "Power Button"
}

/// Whether this record is the button going **down**.
///
/// Only the press: a release is the other half of the same gesture, and acting on both
/// would land on §13's confirm twice.
fn is_press(record: &[u8]) -> bool {
    if record.len() < EVENT_SIZE {
        return false;
    }
    let kind = u16::from_ne_bytes([record[16], record[17]]);
    let code = u16::from_ne_bytes([record[18], record[19]]);
    let value = i32::from_ne_bytes([record[20], record[21], record[22], record[23]]);

    kind == EV_KEY && code == KEY_POWER && value == 1
}

/// The `/dev/input/event*` node the kernel gave the power button, found by name.
///
/// By name and never by index: #89 saw `event1` on one machine under one QEMU, which is a
/// measurement and not a promise.
fn node() -> Option<std::path::PathBuf> {
    for entry in std::fs::read_dir("/sys/class/input").ok()?.flatten() {
        let name = entry.file_name();
        let name = name.to_string_lossy();
        if !name.starts_with("event") {
            continue;
        }
        let device_name = std::fs::read_to_string(entry.path().join("device/name")).ok();
        if device_name.is_some_and(|it| is_power_button(&it)) {
            return Some(std::path::Path::new("/dev/input").join(&*name));
        }
    }
    None
}

/// Watch the button, calling `on_press` for every press until the node stops reading.
///
/// Silent when there is no such node and silent when it cannot be opened: what the button
/// cannot reach is stated in ADR-0017 rather than engineered around, and the one output
/// channel this could complain on is the panel the app is about to paint (01-boot-layer.md
/// §2 forbids writing to it after the first frame).
pub fn watch(on_press: impl Fn() + Send + 'static) {
    let Some(node) = node() else {
        return;
    };
    let Ok(mut device) = std::fs::File::open(node) else {
        return;
    };

    std::thread::spawn(move || {
        let mut record = [0u8; EVENT_SIZE];
        while device.read_exact(&mut record).is_ok() {
            if is_press(&record) {
                on_press();
            }
        }
    });
}

#[cfg(test)]
mod tests {
    use super::{is_power_button, is_press, EVENT_SIZE};

    /// One `struct input_event`, in the layout the kernel writes.
    fn event(kind: u16, code: u16, value: i32) -> [u8; EVENT_SIZE] {
        let mut record = [0u8; EVENT_SIZE];
        record[16..18].copy_from_slice(&kind.to_ne_bytes());
        record[18..20].copy_from_slice(&code.to_ne_bytes());
        record[20..24].copy_from_slice(&value.to_ne_bytes());
        record
    }

    #[test]
    fn the_power_key_going_down_is_a_press() {
        assert!(is_press(&event(1, 116, 1)));
    }

    #[test]
    fn nothing_else_is() {
        // A release is the other half of the same gesture, an autorepeat is a hold — which
        // §13 rules is not the gesture — and every other key on the machine arrives here on
        // its own node in any case.
        assert!(!is_press(&event(1, 116, 0)), "release");
        assert!(!is_press(&event(1, 116, 2)), "autorepeat");
        assert!(!is_press(&event(1, 142, 1)), "KEY_SLEEP");
        assert!(!is_press(&event(4, 4, 116)), "EV_MSC scancode carrying 116");
        assert!(!is_press(&event(0, 0, 0)), "EV_SYN");
    }

    #[test]
    fn a_short_read_is_not_a_press() {
        // The guard is what keeps the offsets below from indexing past the buffer.
        assert!(!is_press(&[]));
        assert!(!is_press(&event(1, 116, 1)[..EVENT_SIZE - 1]));
    }

    #[test]
    fn the_offsets_are_where_the_kernel_puts_them() {
        // A 16-byte timeval precedes the fields. Reading `type` from offset 0 would match
        // an event whose seconds happened to be 1, which is every event in the first
        // second of the epoch and none after — a bug no boot would ever show.
        let record = event(1, 116, 1);
        assert_eq!(
            &record[..16],
            &[0u8; 16],
            "the timeval is untouched by this test"
        );
        assert_ne!(&record[16..24], &[0u8; 8], "and the fields are not");
    }

    #[test]
    fn the_button_is_matched_by_name_with_the_newline_sysfs_appends() {
        assert!(is_power_button("Power Button\n"));
        assert!(is_power_button("Power Button"));
    }

    #[test]
    fn and_its_siblings_are_not() {
        assert!(!is_power_button("Sleep Button\n"));
        assert!(!is_power_button("AT Translated Set 2 keyboard\n"));
        assert!(!is_power_button("Power Button Simulator\n"));
        assert!(!is_power_button(""));
    }
}
