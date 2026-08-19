//! Whether there is a camera to point at a QR.
//!
//! **Enumerated at the point of use, not cached at startup** (01-boot-layer.md §7), so a
//! camera plugged in later simply works: no udev monitoring, no daemon, no reboot. This is
//! the *use* the start menu makes of it — 04-screens.md §1's third entry is visibly
//! unavailable with its reason stated when the answer is no, never hidden.

/// Whether the machine presents a V4L2 capture device.
///
/// **Node presence only, and that is not the whole question.** 01-boot-layer.md §7 rules
/// v1 in for USB UVC and out for the MC-centric IPU6/MIPI cameras, told apart by
/// `V4L2_CAP_VIDEO_CAPTURE` **without** `V4L2_CAP_IO_MC` — which is a `VIDIOC_QUERYCAP`
/// ioctl, and the camera slice is where that ioctl and the buffer loop arrive together. A
/// laptop with an IPU6 camera therefore reads as *present* here and will have to say so
/// clearly at the point it opens the device, which is where §7 puts that sentence anyway.
pub fn present() -> bool {
    (0..10).any(|n| std::path::Path::new(&format!("/dev/video{n}")).exists())
}
