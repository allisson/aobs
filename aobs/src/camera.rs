//! Whether there is a camera to point at a QR, and one frame off it for the entropy mix.
//!
//! **Enumerated at the point of use, not cached at startup** (01-boot-layer.md §7), so a
//! camera plugged in later simply works: no udev monitoring, no daemon, no reboot. This is
//! the *use* the start menu makes of it — 04-screens.md §1's third entry is visibly
//! unavailable with its reason stated when the answer is no, never hidden.

use std::path::{Path, PathBuf};

use aobs_core::secret::Luma;
use v4l::buffer::Type;
use v4l::io::mmap::Stream;
use v4l::io::traits::CaptureStream;
use v4l::video::Capture;
use v4l::{Device, FourCC};
use zeroize::Zeroizing;

/// Luma, one byte per pixel, and the whole buffer is the plane.
const GREY: [u8; 4] = *b"GREY";
/// 4:2:2 with luma at every other byte. `Y Cb Y Cr`, so the plane is a stride-2 read.
const YUYV: [u8; 4] = *b"YUYV";

/// The V4L2 capture nodes this machine presents, in device order.
///
/// **Node presence only, and that is not the whole question.** 01-boot-layer.md §7 rules
/// v1 in for USB UVC and out for the MC-centric IPU6/MIPI cameras, told apart by
/// `V4L2_CAP_VIDEO_CAPTURE` **without** `V4L2_CAP_IO_MC` — which is a `VIDIOC_QUERYCAP`
/// ioctl, and the camera slice ([#78](https://github.com/allisson/aobs/issues/78)) is where
/// that ioctl and the buffer loop arrive together. A laptop with an IPU6 camera therefore
/// reads as *present* here and will have to say so clearly at the point it opens the
/// device, which is where §7 puts that sentence anyway.
fn nodes() -> impl Iterator<Item = PathBuf> {
    (0..10)
        .map(|n| PathBuf::from(format!("/dev/video{n}")))
        .filter(|node| node.exists())
}

/// Whether the machine presents a V4L2 capture device.
pub fn present() -> bool {
    nodes().next().is_some()
}

/// One frame's luma plane, for the entropy mix — or `None`, silently.
///
/// **Silence is the contract** (04-screens.md §2): a machine with no camera, a node that is
/// not a capture device, a driver that offers neither `GREY` nor `YUYV` and a frame that
/// never arrives are one outcome here, because the mix treats an absent supplement and a
/// refused one identically (02-core.md §3). Nothing is announced, because nothing is worse
/// for having happened: with no supplement the entropy is `getrandom`'s 32 bytes verbatim.
///
/// This blocks for as long as the driver takes to hand over a buffer, and there is no
/// timeout — the caller runs it on a thread of its own and takes whatever has arrived when
/// the user presses on, which is why a camera that never delivers costs nothing but its
/// own thread.
pub fn luma_frame() -> Option<Luma> {
    nodes().find_map(|node| capture(&node))
}

/// Open one node, negotiate a format we can read luma out of, and take a single frame.
fn capture(node: &Path) -> Option<Luma> {
    let device = Device::with_path(node).ok()?;

    // **`GREY` or `YUYV`, never `MJPG`** (03-transport.md §5) — asked for in that order and
    // checked in the answer, because `VIDIOC_S_FMT` is free to hand back something else.
    // The resolution is left at whatever the driver already had: §5's *largest up to
    // 1280×720* is a decoding requirement, and this frame is never decoded.
    let mut format = device.format().ok()?;
    let fourcc = [GREY, YUYV].into_iter().find(|wanted| {
        format.fourcc = FourCC::new(wanted);
        device
            .set_format(&format)
            .is_ok_and(|got| got.fourcc.repr == *wanted)
    })?;

    let mut stream = Stream::with_buffers(&device, Type::VideoCapture, 2).ok()?;
    let (frame, _) = stream.next().ok()?;
    Some(Luma::new(&luma(fourcc, frame)))
}

/// The luma bytes of one frame, by format.
///
/// A stride-2 read for `YUYV` and the buffer itself for `GREY`. Never a decode — the mix
/// hashes these bytes and nothing looks at them, so a wrong stride would cost image
/// quality nobody sees rather than entropy.
fn luma(fourcc: [u8; 4], frame: &[u8]) -> Zeroizing<Vec<u8>> {
    Zeroizing::new(if fourcc == GREY {
        frame.to_vec()
    } else {
        frame.iter().step_by(2).copied().collect()
    })
}

#[cfg(test)]
mod tests {
    use super::{luma, GREY, YUYV};

    #[test]
    fn grey_is_luma_already() {
        assert_eq!(*luma(GREY, &[1, 2, 3, 4]), vec![1, 2, 3, 4]);
    }

    #[test]
    fn yuyv_is_every_other_byte() {
        // Y0 Cb Y1 Cr Y2 Cb Y3 Cr — two pixels per four bytes, luma leading each pair.
        assert_eq!(*luma(YUYV, &[1, 9, 2, 9, 3, 9, 4, 9]), vec![1, 2, 3, 4]);
    }
}
