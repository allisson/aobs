//! The camera: which nodes are ours, one frame off one for the entropy mix, and the capture
//! loop the scanning screen runs on.
//!
//! **Enumerated at the point of use, not cached at startup** (01-boot-layer.md §7), so a
//! camera plugged in later simply works: no udev monitoring, no daemon, no reboot. That is
//! also the whole of *recovers on re-plug* (03-transport.md §5) — there is nothing to
//! recover, because nothing was remembered.
//!
//! **Nothing here decides anything.** It opens a device, negotiates a format we can read
//! luma out of, and hands packed planes to a closure; what a plane means is
//! [`crate::qr`]'s and then core's.

use std::path::{Path, PathBuf};

use aobs_core::secret::Luma;
use v4l::buffer::Type;
use v4l::capability::Flags;
use v4l::format::Format;
use v4l::framesize::FrameSizeEnum;
use v4l::io::mmap::Stream;
use v4l::io::traits::CaptureStream;
use v4l::video::Capture;
use v4l::{Device, FourCC};
use zeroize::Zeroizing;

/// Luma, one byte per pixel, and the whole buffer is the plane.
pub(crate) const GREY: [u8; 4] = *b"GREY";
/// 4:2:2 with luma at every other byte. `Y Cb Y Cr`, so the plane is a stride-2 read.
pub(crate) const YUYV: [u8; 4] = *b"YUYV";

/// `V4L2_CAP_IO_MC`, which `v4l`'s own [`Flags`] does not name.
///
/// 01-boot-layer.md §7 tells v1's devices from the ones it excludes with exactly this pair:
/// `V4L2_CAP_VIDEO_CAPTURE` **without** `V4L2_CAP_IO_MC`. A modern Intel IPU6/MIPI laptop
/// camera sets both and needs a media-controller pipeline, proprietary firmware and
/// libcamera — none of which v1 has — so it has to read as *no camera at all* rather than as
/// a camera that fails obscurely the moment someone asks it for a frame.
const IO_MC: u32 = 0x2000_0000;

/// 03-transport.md §5's resolution ceiling. A 640×480 frame reading a v40 symbol leaves under
/// 3 px/module before optics and blur, so larger is better right up to here; past it we would
/// be paying for pixels `rqrr` has to walk on hardware that may already not keep up at 30 fps.
const MAX_WIDTH: u32 = 1280;
/// The other half of the ceiling.
const MAX_HEIGHT: u32 = 720;

/// How many buffers the capture stream is given, and **this number is the drop policy**.
///
/// 03-transport.md §5: *capture at the camera's native rate with no throttle; always decode
/// the newest frame; drop any that arrived while we were busy.* With two buffers there is
/// exactly one frame in flight while we decode, so a frame arriving behind it has nowhere to
/// be queued and the driver discards it — the dropping is the kernel's, by construction,
/// rather than a policy we implement and could get wrong. A larger count would turn a slow
/// decode into growing latency and a visibly lagging preview, which is the trap §5 names: the
/// user then aims at where the code *was*.
const BUFFERS: u32 = 2;

/// The V4L2 capture nodes this machine presents, in device order.
///
/// The `VIDIOC_QUERYCAP` ioctl 01-boot-layer.md §7 asks for is here, and it is the whole of
/// the filter: `v4l` reads `device_caps` — the per-node capabilities, which is the field §7's
/// distinction is about — so an IPU6 node reads as *not ours* here instead of at the point
/// somebody tries to stream from it.
fn nodes() -> impl Iterator<Item = PathBuf> {
    (0..10)
        .map(|n| PathBuf::from(format!("/dev/video{n}")))
        .filter(|node| node.exists() && ours(node))
}

/// Whether this node is a plain V4L2 capture device we can drive with ioctls alone.
fn ours(node: &Path) -> bool {
    Device::with_path(node).is_ok_and(|device| {
        device.query_caps().is_ok_and(|caps| {
            caps.capabilities.contains(Flags::VIDEO_CAPTURE)
                && caps.capabilities.bits() & IO_MC == 0
        })
    })
}

/// Whether the machine presents a V4L2 capture device we can use.
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

    let mut stream = Stream::with_buffers(&device, Type::VideoCapture, BUFFERS).ok()?;
    let (frame, _) = stream.next().ok()?;
    Some(Luma::new(&luma(fourcc, frame)))
}

/// The luma bytes of one frame, by format.
///
/// A stride-2 read for `YUYV` and the buffer itself for `GREY`. Never a decode — the mix
/// hashes these bytes and nothing looks at them, so a wrong stride would cost image
/// quality nobody sees rather than entropy. [`pack`] is the same read for the frames that
/// *are* decoded, and it is a second function rather than a shared one precisely because it
/// owes the row geometry this one is free to ignore.
fn luma(fourcc: [u8; 4], frame: &[u8]) -> Zeroizing<Vec<u8>> {
    Zeroizing::new(if fourcc == GREY {
        frame.to_vec()
    } else {
        frame.iter().step_by(2).copied().collect()
    })
}

/// One frame's luma plane, packed to one byte per pixel, with the geometry it was packed at.
///
/// Not a secret: a QR animation is attacker-supplied bytes on their way to core's bounds, and
/// wrapping them in a zeroizing type would claim a protection they do not need. The entropy
/// frame is the one that does, and it takes [`Luma`] instead.
pub struct Frame<'a> {
    /// `width * height` bytes, row-major, padding and chroma already gone.
    pub luma: &'a [u8],
    /// Pixels per row.
    pub width: usize,
    /// Rows actually delivered, which is not always the height the format declared.
    pub height: usize,
}

/// Why a capture run ended.
pub enum Ended {
    /// The closure returned `false`: the caller has what it wanted, or has left the screen.
    Asked,
    /// There was no usable node to open, or the one we opened stopped delivering.
    ///
    /// 03-transport.md §5: *a camera that disappears mid-scan states so plainly and returns
    /// to the previous screen, recovering on re-plug.* The recovery is free — [`nodes`] runs
    /// at the point of use, so the next entry to the screen asks the machine again.
    Lost,
}

/// Open the first usable node and hand every frame it delivers to `on_frame`.
///
/// Returns [`Ended::Asked`] when the closure says it is finished and [`Ended::Lost`] when the
/// device does. **This blocks for the life of the scan** and is meant for a thread of its own:
/// there is no timeout here, because 03-transport.md §3 rules out a wall-clock scan timeout
/// and the closure returning `false` is how a cancel arrives.
pub fn stream(mut on_frame: impl FnMut(Frame<'_>) -> bool) -> Ended {
    let Some((device, format, fourcc)) = nodes().find_map(|node| negotiate(&node)) else {
        return Ended::Lost;
    };
    let Ok(mut stream) = Stream::with_buffers(&device, Type::VideoCapture, BUFFERS) else {
        return Ended::Lost;
    };

    let width = format.width as usize;
    let height = format.height as usize;
    let stride = format.stride as usize;
    // One buffer for the whole run. `pack` clears it and keeps its capacity, so the native
    // rate costs one allocation rather than one per frame.
    let mut plane = Vec::new();

    loop {
        let Ok((buffer, _)) = stream.next() else {
            return Ended::Lost;
        };
        let rows = pack(fourcc, buffer, width, height, stride, &mut plane);
        // A frame we could not read rows out of is a frame that says nothing, which is what
        // every bad scan is (06-codes.md §4). The next one is along in a thirtieth of a second.
        if rows > 0
            && !on_frame(Frame {
                luma: &plane,
                width,
                height: rows,
            })
        {
            return Ended::Asked;
        }
    }
}

/// Open one node and settle on a luma format at the largest size 03-transport.md §5 will take.
///
/// `GREY` before `YUYV` — one is the plane already and the other is a stride-2 read of it —
/// and **never `MJPG`**, which would put a JPEG decoder on the hostile-input path for nothing:
/// QR decoding needs luminance only. The format that comes back is what the driver agreed to
/// rather than what we asked for, because `VIDIOC_S_FMT` adjusts silently, and §5's *falling
/// back to whatever it has* is exactly the case where those two differ.
fn negotiate(node: &Path) -> Option<(Device, Format, [u8; 4])> {
    let device = Device::with_path(node).ok()?;
    let current = device.format().ok()?;

    for wanted in [GREY, YUYV] {
        let Some((width, height)) = largest(&device, wanted, &current) else {
            continue;
        };
        let mut format = current;
        format.fourcc = FourCC::new(&wanted);
        format.width = width;
        format.height = height;
        if let Ok(got) = device.set_format(&format) {
            if got.fourcc.repr == wanted {
                return Some((device, got, wanted));
            }
        }
    }
    None
}

/// The largest size this device offers for `fourcc` inside the ceiling, or what it already has.
///
/// `None` means the device does not offer this format at all — `VIDIOC_ENUM_FRAMESIZES`
/// answers `EINVAL` for a fourcc it does not support, so this doubles as the format probe.
///
/// **`FrameSizeEnum::to_discrete` is deliberately not called.** For a stepwise or continuous
/// device it materialises the whole cross product, which for step 1 over 1920×1080 is two
/// million `Discrete`s and about 16 MB — an allocation sized by a device's answer rather than
/// by us. The stepwise arm is the same choice as arithmetic instead.
fn largest(device: &Device, fourcc: [u8; 4], current: &Format) -> Option<(u32, u32)> {
    let sizes = device.enum_framesizes(FourCC::new(&fourcc)).ok()?;
    let best = sizes
        .into_iter()
        .filter_map(|size| match size.size {
            FrameSizeEnum::Discrete(d) => {
                (d.width <= MAX_WIDTH && d.height <= MAX_HEIGHT).then_some((d.width, d.height))
            }
            FrameSizeEnum::Stepwise(s) => Some((
                on_grid(s.min_width, s.max_width, s.step_width, MAX_WIDTH)?,
                on_grid(s.min_height, s.max_height, s.step_height, MAX_HEIGHT)?,
            )),
        })
        .max_by_key(|&(width, height)| u64::from(width) * u64::from(height));

    // §5's *falling back to whatever it has*, and it means what it says: a device whose every
    // offered size is above the ceiling still gets asked for this format, at the size it is
    // already set to — **which may itself be above the ceiling**, and is taken anyway. The
    // ceiling is a preference for the resolution that decodes best per pixel walked; refusing a
    // camera for offering only more pixels than that would be reading it as a limit. `S_FMT`
    // adjusts whatever we hand it and `negotiate` takes the answer rather than the request.
    best.or(Some((current.width, current.height)))
}

/// The largest multiple of `step` from `min` that is within both `max` and `ceiling`.
fn on_grid(min: u32, max: u32, step: u32, ceiling: u32) -> Option<u32> {
    if step == 0 || min > ceiling {
        return None;
    }
    Some(min + (ceiling.min(max).saturating_sub(min) / step) * step)
}

/// One frame's luma plane, packed to `width` bytes per row, into `out`.
///
/// Returns the rows written, which is the height the decoder and the preview are then told
/// about. **The declared height is a claim and the buffer length is the fact**: a driver
/// handing back less than its own format describes must cost the rows it did not deliver, not
/// a panic on a slice index — and a panic here is `AOBS-E04` and the end of the session.
///
/// Reachable from [`crate::qr`] because the recorded-frame corpus replays whole frames
/// (05-testing-and-release.md §6.3), and a frame is these bytes and this geometry.
pub(crate) fn pack(
    fourcc: [u8; 4],
    frame: &[u8],
    width: usize,
    height: usize,
    stride: usize,
    out: &mut Vec<u8>,
) -> usize {
    out.clear();
    // `GREY` is the plane; `YUYV` is `Y Cb Y Cr`, so luma leads every pair of bytes.
    let step = if fourcc == GREY { 1 } else { 2 };
    if width == 0 || height == 0 || stride < width * step {
        return 0;
    }
    let mut rows = 0;
    for y in 0..height {
        let Some(row) = frame.get(y * stride..y * stride + width * step) else {
            break;
        };
        out.extend(row.iter().step_by(step));
        rows += 1;
    }
    rows
}

#[cfg(test)]
mod tests {
    use super::{luma, on_grid, pack, GREY, MAX_HEIGHT, MAX_WIDTH, YUYV};

    #[test]
    fn grey_is_luma_already() {
        assert_eq!(*luma(GREY, &[1, 2, 3, 4]), vec![1, 2, 3, 4]);
    }

    #[test]
    fn yuyv_is_every_other_byte() {
        // Y0 Cb Y1 Cr Y2 Cb Y3 Cr — two pixels per four bytes, luma leading each pair.
        assert_eq!(*luma(YUYV, &[1, 9, 2, 9, 3, 9, 4, 9]), vec![1, 2, 3, 4]);
    }

    #[test]
    fn packing_grey_drops_the_stride_padding() {
        // Two rows of three pixels in a five-byte stride. The slack is what a wrong read would
        // pull into the middle of row two, which is how a QR stops decoding at the same time as
        // the preview starts shearing.
        let mut out = Vec::new();
        let frame = [1, 2, 3, 0xee, 0xee, 4, 5, 6, 0xee, 0xee];
        assert_eq!(pack(GREY, &frame, 3, 2, 5, &mut out), 2);
        assert_eq!(out, vec![1, 2, 3, 4, 5, 6]);
    }

    #[test]
    fn packing_yuyv_drops_the_chroma_and_the_padding() {
        let mut out = Vec::new();
        let frame = [1, 9, 2, 9, 0xee, 3, 9, 4, 9, 0xee];
        assert_eq!(pack(YUYV, &frame, 2, 2, 5, &mut out), 2);
        assert_eq!(out, vec![1, 2, 3, 4]);
    }

    #[test]
    fn a_short_buffer_costs_the_rows_it_did_not_carry() {
        // Three rows declared, two delivered. Nothing panics and the caller is told two.
        let mut out = Vec::new();
        let frame = [1, 2, 3, 4];
        assert_eq!(pack(GREY, &frame, 2, 3, 2, &mut out), 2);
        assert_eq!(out, vec![1, 2, 3, 4]);
    }

    #[test]
    fn a_stride_that_cannot_hold_a_row_yields_nothing() {
        // The one arm that makes the slice arithmetic above total, and the only reason `pack`
        // returns a count rather than trusting the format.
        let mut out = Vec::new();
        assert_eq!(pack(GREY, &[1, 2, 3, 4], 4, 1, 2, &mut out), 0);
        assert_eq!(pack(YUYV, &[1, 2, 3, 4], 2, 1, 3, &mut out), 0);
        assert_eq!(pack(GREY, &[1, 2, 3, 4], 0, 1, 2, &mut out), 0);
        assert_eq!(pack(GREY, &[1, 2, 3, 4], 2, 0, 2, &mut out), 0);
        assert!(out.is_empty());
    }

    #[test]
    fn packing_reuses_its_buffer() {
        let mut out = Vec::new();
        pack(GREY, &[1, 2, 3, 4, 5, 6], 6, 1, 6, &mut out);
        pack(GREY, &[7, 8], 2, 1, 2, &mut out);
        assert_eq!(
            out,
            vec![7, 8],
            "a second frame must not read as a longer one"
        );
    }

    #[test]
    fn the_stepwise_grid_lands_on_a_size_the_device_offers() {
        // 640..1920 in steps of 160: the ceiling is 1280, which is on the grid.
        assert_eq!(on_grid(640, 1920, 160, MAX_WIDTH), Some(1280));
        // 480..1080 in steps of 120: 720 is on the grid and is the ceiling exactly.
        assert_eq!(on_grid(480, 1080, 120, MAX_HEIGHT), Some(720));
        // A grid that straddles the ceiling lands below it rather than over it.
        assert_eq!(on_grid(640, 1920, 300, MAX_WIDTH), Some(1240));
        // A device whose smallest size is already past the ceiling offers us nothing.
        assert_eq!(on_grid(1600, 1920, 160, MAX_WIDTH), None);
        // And a step of zero is a device answer we divide by, so it is refused rather than
        // trusted.
        assert_eq!(on_grid(640, 1920, 0, MAX_WIDTH), None);
        // A maximum below the ceiling caps it, which is the ordinary webcam.
        assert_eq!(on_grid(160, 640, 160, MAX_WIDTH), Some(640));
    }
}
