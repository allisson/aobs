# Debian base image and Debian's stock kernel

The predecessor built its appliance on an Alpine minirootfs and compiled a vanilla kernel.org LTS
tarball against a hand-written `build/kernel.config` — no networking, no modules, no block layer,
exactly two USB class drivers. That config was the mechanism behind the project's two headline
promises: *offline* and *amnesic* were not policies but impossibilities, checkable as the absence of
`/proc/net/dev` and of any block device. It also cost a kernel toolchain in the build, a 613-symbol
config to verify, a 249 s compile, and the largest single source of reproducibility divergence in the
pipeline.

**We now build on Debian 13 (trixie) pinned to a `snapshot.debian.org` timestamp, and we ship
Debian's `linux-image-amd64` unmodified.** Networking and storage are removed from the *image* — the
modules tree is pruned to an explicit allowlist and all of `kernel/net`, `drivers/net` and every
storage driver are deleted — rather than removed from the kernel.

## What this costs

Two claims drop from **structural** to **absence**, and this is the whole substance of the trade:

- *Offline* was "no network stack and no network drivers exist in the running kernel". It is now "no
  network module and no network tool is in the image".
- *Amnesic (i)*, "nothing is written to any persistent medium", rested on there being no block layer
  to mount from. `CONFIG_BLOCK=y` in Debian's kernel, so it now rests on no storage driver being in
  the image. The related claim — that only tmpfs and pseudo-filesystems are mounted — stays
  structural, because the whole rootfs is the initramfs and there is nothing to mount from.

An absence claim is checkable by a stranger with `find` and `ls`, which is most of what made the
original claims valuable. It is defeated by an adversary who already has code execution on the
appliance, which the structural version was not. `docs/threat-model.md` states each at its actual
strength; `docs/overview.md` tabulates which is which. **Neither may be restated as structural.**

## What it buys

The kernel toolchain, `kernel.config`, its verification suite and the compile stage all leave the
build — and with them the pipeline's most divergence-prone stage. Debian's kernel is 6.12.107, the
same LTS series the predecessor compiled by hand at 6.12.106, so nothing is given up in kernel
version. `snapshot.debian.org` pins the input set more firmly than reading Alpine's `APKINDEX` by
hand ever did, and Debian's source packages make the copyleft source archive exact rather than
reconstructed. `mmdebstrap --mode=unshare` also removes the `--privileged` requirement from the
build, which was a real barrier to the independent rebuilds the trust model depends on.

## Considered and rejected

- **Accept a full downgrade** — stock Debian with networking present and merely not brought up. This
  is what "disable networking in Debian" literally means, and it is the option a code-execution
  adversary walks straight past. Rejected: the pruning is a `find` and an `rm` in the build, and it
  buys back most of the claim's checkability.
- **Keep compiling a custom kernel for this one property.** Rejected: it reintroduces the exact
  complexity this restart exists to delete, for a property that pruning approximates well.
- **`live-build` with systemd and a squashfs root.** The simplest thing to author, and it would have
  retired the *one userspace process* claim, complicated the amnesia story, and put a login-capable
  console in the image. Rejected: the complexity worth deleting was the kernel compile, not
  `build/init` — five `mount`s and an `echo` into sysfs, already written and already documented.

## Consequences

The full rootfs is resident in RAM, so the RAM floor rises and is now derived from the measured
unpacked size rather than hand-picked. `CONFIG_MODULES=y` means `authorized_default=0` is one of two
mechanisms rather than a corollary of the config — the module allowlist is the claim, the `modprobe`
blacklist is a second line and is never cited as the claim. Debian ships `python3-textual` 2.1.2
against an application written for `textual>=0.80`, which makes the UI port a milestone of its own.
`python3-embit` and `python3-urtypes` do not exist in Debian, exactly as in Alpine, so vendoring
carries over unchanged.
