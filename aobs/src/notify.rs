//! `sd_notify(READY=1)`, and why the unit cannot do without it.
//!
//! `01-boot-layer.md` §2 makes `Type=notify` load-bearing: `ExecStartPost=+` runs when
//! systemd considers the service started, and under `Type=simple` that is `fork(2)` —
//! long before there are pixels. A console detach landing there would unbind `fbcon`
//! from a framebuffer the app has not painted yet, and a startup failure would print §9's
//! diagnostic to a console that is already gone.
//!
//! No dependency: the protocol is one datagram of `READY=1` to `$NOTIFY_SOCKET`.

use std::os::unix::net::UnixDatagram;

/// Tell systemd the window is up.
///
/// Silent on every failure. A machine that cannot notify is a machine whose unit times
/// out and restarts — visible in the boot, and not something this function can improve by
/// writing to a console the app has already painted over (§2).
pub fn ready() {
    let Ok(socket) = std::env::var("NOTIFY_SOCKET") else {
        return;
    };
    let Ok(sender) = UnixDatagram::unbound() else {
        return;
    };

    // systemd hands over either a filesystem path (Debian's `/run/systemd/notify`) or an
    // abstract name, marked by a leading `@`. Both, because which one arrives is
    // systemd's choice and not ours.
    if let Some(name) = socket.strip_prefix('@') {
        use std::os::linux::net::SocketAddrExt;
        let Ok(address) = std::os::unix::net::SocketAddr::from_abstract_name(name.as_bytes())
        else {
            return;
        };
        let _ = sender.send_to_addr(b"READY=1", &address);
    } else {
        let _ = sender.send_to(b"READY=1", socket);
    }
}
