//! PROTOTYPE ([#52](https://github.com/allisson/aobs/issues/52)) — `sd_notify(READY=1)`.
//!
//! The mitigation #49 chose detaches `fbcon` from the framebuffer while the app is
//! drawing, reproducing on the fbdev tier what a DRM master gets for free (#51). The
//! detach is `ExecStartPost=+`, so it fires when systemd considers the service started —
//! and with `Type=simple` that is at `fork(2)`, long before there are pixels. That
//! ordering is the whole risk: unbinding `fbcon` may clear the framebuffer on the way
//! out, and Slint does not redraw pixels it believes unchanged, which is exactly why
//! #48's kernel lines persisted. A detach that lands before the first frame would hide
//! that; a detach that lands after it is the production ordering.
//!
//! Hence `Type=notify` and this module. No dependency: the protocol is one datagram of
//! `READY=1` to `$NOTIFY_SOCKET`.

use std::os::unix::net::UnixDatagram;

/// Tell systemd the service is up. Silent on every failure — a service that cannot
/// notify must still draw, and this is a prototype path, not a product one.
pub fn ready() {
    let Ok(socket) = std::env::var("NOTIFY_SOCKET") else {
        return;
    };
    let Ok(sender) = UnixDatagram::unbound() else {
        return;
    };

    // systemd hands over either a filesystem path (Debian's `/run/systemd/notify`) or an
    // abstract name, marked by a leading `@`. Both are handled so that a wrong guess
    // fails the boot visibly here rather than three hours into a build.
    if let Some(name) = socket.strip_prefix('@') {
        use std::os::linux::net::SocketAddrExt;
        let Ok(address) = std::os::unix::net::SocketAddr::from_abstract_name(name.as_bytes()) else {
            return;
        };
        let _ = sender.send_to_addr(b"READY=1", &address);
    } else {
        let _ = sender.send_to(b"READY=1", socket);
    }
}
