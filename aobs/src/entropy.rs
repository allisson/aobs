//! `getrandom(2)`, as a raw syscall, and the measurement the spec still owes.
//!
//! aobs boots with `random.trust_cpu=off` (01-boot-layer.md §8), which withdraws the
//! 512 bits `random_init_early()` would otherwise credit from RDSEED/RDRAND and makes
//! the pool fill from timing jitter instead. The cost of that — **~1–16 s once at
//! boot** — is derived arithmetically from `random.c`, *not* measured, and it is the
//! first of the eight numbers `00-overview.md` still owes. This module is what turns it
//! into a number.
//!
//! **No crate sits between us and the kernel, on purpose.** Coldcard's seed generation
//! resolved to MicroPython's software PRNG for five years with correct source and a
//! broken linkage. 05-testing-and-release.md §6.2 traces one syscall site during a seed
//! generation and byte-compares the result; a crate-level indirection is exactly the
//! thing a build change is free to re-resolve underneath that trace.

use std::time::Instant;

use aobs_core::secret::Csprng32;
use zeroize::Zeroizing;

#[cfg(not(all(target_arch = "x86_64", target_os = "linux")))]
compile_error!(
    "aobs targets x86_64 Linux only (01-boot-layer.md §7: UEFI amd64). \
     On another host, work the core crate: `cargo test -p aobs-core`, or use \
     ci/build-env.Dockerfile."
);

/// `__NR_getrandom` on x86_64 Linux.
const SYS_GETRANDOM: usize = 318;

/// `-EINTR`. A blocking `getrandom` is interruptible by a signal and must be resumed.
const NEG_EINTR: isize = -4;

/// One `getrandom(2)` syscall. Returns the byte count, or a negative errno.
///
/// # Safety
///
/// `buf` must be valid for writes of `len` bytes.
unsafe fn getrandom_syscall(buf: *mut u8, len: usize, flags: usize) -> isize {
    let ret: isize;
    unsafe {
        std::arch::asm!(
            "syscall",
            inlateout("rax") SYS_GETRANDOM as isize => ret,
            in("rdi") buf,
            in("rsi") len,
            in("rdx") flags,
            lateout("rcx") _,
            lateout("r11") _,
            options(nostack),
        );
    }
    ret
}

/// The kernel refused to fill the buffer.
#[derive(Debug)]
pub struct EntropyUnavailable;

/// Fill `buf` from the kernel CSPRNG, blocking until it is ready.
///
/// Flags are `0`, always. `01-boot-layer.md` §8 forbids the alternatives and says why:
/// `/dev/urandom` is documented upstream as equivalent to `GRND_INSECURE`, `GRND_RANDOM`
/// is annotated `/* No effect */` in `uapi/linux/random.h`, and `GRND_INSECURE` is never.
fn fill(buf: &mut [u8]) -> Result<(), EntropyUnavailable> {
    let mut filled = 0;
    while filled < buf.len() {
        let remaining = buf.len() - filled;
        // SAFETY: the pointer is into `buf` at `filled`, and `remaining` is exactly the
        // number of bytes left in it.
        let ret = unsafe { getrandom_syscall(buf[filled..].as_mut_ptr(), remaining, 0) };
        match ret {
            NEG_EINTR => continue,
            n if n > 0 => filled += n as usize,
            _ => return Err(EntropyUnavailable),
        }
    }
    Ok(())
}

/// The wallet's 32 bytes, from one `getrandom(2)` and nothing between us and it.
///
/// **This is the site the provenance release gate traces** (05-testing-and-release.md
/// §6.2): one syscall during a seed generation, and the wallet's entropy byte-identical to
/// what it returned once core has XORed the supplements in. A crate here would be exactly
/// the indirection a build change is free to re-resolve underneath that trace, which is how
/// Coldcard shipped a software PRNG for five years with correct source.
///
/// It blocks, like every call in this module. By the time a user reaches the create screen
/// the pool is long initialised — `time_until_ready` waited for it before the UI came up —
/// so the wait is nominally over; 04-screens.md §2 still shows it rather than assuming it,
/// which is why this runs off the event loop.
pub fn csprng_32() -> Result<Csprng32, EntropyUnavailable> {
    // The array the syscall fills is a second copy of the material, and it is not the one
    // the secret type will zeroize. `Zeroizing` is what wipes it on the way out of scope.
    let mut buf = Zeroizing::new([0u8; Csprng32::LEN]);
    fill(&mut *buf)?;
    Ok(Csprng32::new(*buf))
}

/// Block until the kernel CSPRNG is ready and report how many milliseconds that took.
///
/// The bytes are discarded. Nothing derived from them ever becomes key material — the
/// wallet's entropy is generated later, from a single traced call, with the dice and
/// camera supplements mixed in (`02-core.md`). This exists solely to measure the wait.
pub fn time_until_ready() -> Result<u128, EntropyUnavailable> {
    let start = Instant::now();
    let mut buf = [0u8; 32];
    let outcome = fill(&mut buf);
    let elapsed = start.elapsed().as_millis();

    // Not secret material — but a buffer of CSPRNG output is not left lying on the stack
    // for the sake of two lines. Volatile so the write survives optimisation.
    for byte in buf.iter_mut() {
        // SAFETY: `byte` is a valid, aligned, exclusively-borrowed `u8`.
        unsafe { std::ptr::write_volatile(byte, 0) };
    }

    outcome.map(|()| elapsed)
}
