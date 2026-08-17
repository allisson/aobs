# What an Alpine base costs `01-boot-layer.md`, section by section

Research findings for [aobs#45](https://github.com/allisson/aobs/issues/45). Parent:
[aobs#42](https://github.com/allisson/aobs/issues/42). Feeds the decision in
[aobs#49](https://github.com/allisson/aobs/issues/49). Depends on
[aobs#44](https://github.com/allisson/aobs/issues/44), which verified the premise (Alpine 3.24
`linux-lts` 6.18.44 sets `CONFIG_DRM_SIMPLEDRM=y` and `CONFIG_SYSFB_SIMPLEFB=y`).

**This file prices; it does not decide.** Whether the total below is worth paying belongs to #49.

Pinned at Alpine **3.24-stable** throughout — branched 2026-06-09, EOL 2028-06-01. Versions read from
the `v3.24/{main,community}/x86_64` `APKINDEX` fetched 2026-08-16, and from the aports `3.24-stable`
branch: `alpine-base` 3.24.1-r0, `alpine-baselayout` 3.7.2-r1, `alpine-conf` 3.22.0-r0, `mkinitfs`
3.14.0-r0, `openrc` 0.63.2-r0, `busybox` 1.37.0-r31, `musl` 1.2.6-r2, `linux-lts` 6.18.44-r0. Against
Debian 13 trixie, kernel 6.12, `live-build` 1:20250814.

Where a number is *derived* from source rather than measured, it is marked **[derived]**. Nothing here
was booted; see *What was not checked*.

---

## The total, section by section

| Spec section | Alpine equivalent | Verdict |
|---|---|---|
| §1 emits an ISO | `aports/scripts/mkimage.sh` → `create_image_iso()` → `xorrisofs`. Yes, it emits a hybrid ISO. | **ports cleanly** |
| §1 `SOURCE_DATE_EPOCH` threading | `mkimage.sh:set_source_date()` exports it; `xorrisofs` honours it *itself* per the reproducible-builds spec; `mformat -N 0` + `touch -md` normalise the ESP. | **ports cleanly** |
| §1 rebuild-and-compare harness | None. No `test/rebuild.sh` equivalent anywhere in `aports/scripts/`. | **no equivalent** |
| §1 pinning against an archive | None. No `snapshot.debian.org` equivalent; superseded `-rN` builds are deleted from the mirror. | **no equivalent** |
| §1 customisation surface (`hooks/normal/*.hook.chroot`) | No hook mechanism. You get `apks=`, a `genapkovl-*.sh` overlay script, `initfs_features`, and *overriding shell functions* from a `$HOME/.mkimage/mkimg.aobs.sh` plugin. | **needs rework** |
| §1 build host | Must run on Alpine: `abuild`, `apk`, `alpine-conf`'s `update-kernel`, plus a `PACKAGER_PRIVKEY` to sign the modloop and the on-ISO `APKINDEX`. | **needs rework** |
| §2 the 22-package floor | All present. 25 packages / **19.8 MiB** beyond the base system without the seat path; 29 / 20.5 MiB with it. Against Debian's 22 / 21 MiB. | **ports cleanly** |
| §2 those packages on musl | Alpine builds them; nothing for us to patch. But `libinput`, `libevdev`, `mtdev`, `seatd`/`libseat` are in **community**, whose support ends six months after release. | **ports cleanly**, with a support-window cost |
| §2 the Rust build | `x86_64-unknown-linux-musl` is Tier 2 and **`crt-static` by default**; Alpine's own `rustc` sets `crt-static=false` for `x86_64-alpine-linux-musl`. Alpine ships Rust 1.96.1; `rust-toolchain.toml` pins 1.97.1. | **needs rework** |
| §2 udev for libinput | Slint 1.17.1 calls `Libinput::new_with_udev` on **both** the seat and no-seat paths, so `eudev` + `udev-init-scripts` must replace Alpine's default `mdev`. Alpine's own recipe: `setup-devd udev`. | **needs rework** |
| §2 the seat group | Alpine's `seatd` creates a real `seat` group (`pkggroups="seat"`) and runs `seatd -g seat`. The hook must read `seatd.initd`, not a systemd unit. | **needs rework** (small) |
| §2 `Restart=always` | `tty1::respawn:/usr/lib/aobs/launch` in `/etc/inittab`. busybox init documents that it *"does not stop processes from respawning out of control"*, with a 1 s sleep floor. | **ports cleanly** |
| §2 no gettys (`NAutoVTs=0`, `ReserveVT=0`) | Delete the six `tty[1-6]::respawn:/sbin/getty` lines that `alpine-baselayout` ships in `/etc/inittab`. | **ports cleanly**, and simpler |
| §2 `kernel.sysrq=0` | `/etc/sysctl.d/` drop-in; Alpine's own `sysctl.initd` reads it with busybox `sysctl -p`. Alpine's kernel sets `MAGIC_SYSRQ_DEFAULT_ENABLE=0x1`, so the control is still required. | **ports cleanly** |
| §2 `TTYVTDisallocate=yes` | No equivalent, and nothing to disallocate once no getty exists. | **no equivalent** (moot) |
| §3 delete `drivers/net`, `drivers/bluetooth`, `net/` | Same paths, and every driver is `=m`. But they live in `modloop-lts`, a **signed squashfs** built by `alpine-conf`'s `update-kernel`, not in a rootfs a hook can walk. | **needs rework** |
| §3 `depmod` after the delete | Free: `update-kernel` runs `depmod -b`, and the `modloop` service runs `depmod -A` at boot over a tmpfs overlay on `/lib/modules`. | **ports cleanly** |
| §3 install no `firmware-*` | `update-kernel` hardcodes `PACKAGES="$PACKAGES linux-$FLAVOR linux-firmware"`; `linux-firmware-none` provides `linux-firmware-any`, which does not satisfy it. | **needs rework** |
| §3 strip the initramfs (`MODULES=dep`) | `initfs_features`. The ISO default carries **no** `drivers/net` at all — `dhcp.modules` is only `kernel/net/packet/af_packet.ko`. | **ports cleanly**, and cheaper |
| §3 `install <mod> /bin/false` | busybox `modprobe` parses `alias`, `options` and `blacklist` only — **`install` is not implemented**. Needs the `kmod` package (130 KiB, main) to mean anything. | **needs rework** |
| §3 build check (`lsinitramfs` shows no `drivers/net`) | mkinitfs **silently skips** feature paths that do not exist, so nothing fails loudly. The check is ours to write either way. | **ports cleanly** |
| §4 never pass `persistence` / `swap` | No such parameters exist. But `nlplug-findfs` mounts **every** block device and unpacks the first `*.apkovl.tar.gz*` it finds into the root, unsigned, with no cmdline gate. | **no equivalent** — see §4.2 |
| §4 `systemctl mask swap.target` | OpenRC's `swap` service is not in the diskless default runlevel set; Alpine's `openrc` package ships empty runlevels. Nothing to mask. | **ports cleanly**, cost saved |
| §4 neuter `/sbin/swapon` | `swapon` is a busybox applet (`CONFIG_SWAPON=y`), so deleting the symlink leaves `busybox swapon`. Weaker than on Debian. | **needs rework** |
| §4 `nohibernate` | Cmdline parameter, unchanged; `CONFIG_HIBERNATION=y` on Alpine too, so still required. | **ports cleanly** |
| §4 `AllowHibernation=no`, `HandleLidSwitch=ignore` | No logind, no `acpid` in the profile's `apks=`, so nothing listens to the lid switch. Cost saved, but it becomes an *absence to assert* rather than a setting. | **no equivalent** (moot) |
| §4 coredumps `Storage=none` + `ProcessSizeMax=0` | Nothing on a stock Alpine writes a core: `core_pattern` is the kernel default `"core"` and `RLIMIT_CORE` soft is 0. **The seed-in-a-file failure mode does not exist by default.** | **no equivalent** — cost saved, see §4.3 |
| §4 no `kdump-tools`, no `crashkernel=` | Neither is in the profile. | **ports cleanly** |
| §4 no `udisks2`/`gvfs`/DE | None in the profile. The auto-mount that remains is the initramfs's, above. | **ports cleanly** |
| §5 `init_on_free=1` | Cmdline parameter, unchanged. Alpine additionally sets `CONFIG_INIT_ON_ALLOC_DEFAULT_ON=y`. | **ports cleanly** |
| §5 free the overlayfs upper dir | There is no overlay: Alpine's diskless root **is** a tmpfs that `apk` populates at boot. Deleting its contents frees the pages directly, but there is no `systemd-shutdown`-style pivot back to the initramfs. | **needs rework** |
| §6 kernel command line | Set via `kernel_cmdline` in the profile. `toram` has no Alpine spelling; the rest transfers verbatim. | **needs rework** |
| §6 `panic=0` | **Silently undone.** `alpine-baselayout` ships `kernel.panic = 120` in `/usr/lib/sysctl.d/00-alpine.conf`, applied in the `boot` runlevel, after the cmdline. | **needs rework** — see §6 |
| §7 UEFI-only | The `standard` profile is a BIOS+UEFI hybrid; `section_syslinux` fires unconditionally on x86_64. Overriding it is one function. | **needs rework** (small) |
| §7 `toram` — pull the stick | No equivalent boot option. The rootfs is already in RAM, but `modloop` stays mounted from the medium. `copy-modloop` (alpine-conf) does the job as a command, not a parameter. | **needs rework** |
| §7 camera, USB UVC | `CONFIG_USB_VIDEO_CLASS=m`, `CONFIG_MEDIA_SUPPORT=m` — same as Debian, zero extra packages. | **ports cleanly** |
| §8 `random.trust_cpu=off` | Cmdline parameter, unchanged. `random.c` is byte-identical on the entropy path between 6.12 and 6.18. | **ports cleanly** |
| §8 the ~1–16 s number | Alpine sets **`CONFIG_HZ=1000`** against Debian's 250. The arithmetic becomes **~0.26–16.9 s** **[derived]**. | **needs rework** (a number, not a mechanism) |
| §9 diagnostic on the kernel console | Console exists (#44 §6). No `StandardOutput=journal+console`; the wrapper's output goes wherever inittab puts it. | **needs rework** (small) |
| §10 `panic = "unwind"` | A Cargo profile setting; the CI check is unaffected by the base. | **ports cleanly** |
| Kernel signing / Secure Boot | **Alpine has no `shim` package at all.** `grub-mkimage` produces an unsigned `bootx64.efi`. `secureboot-hook` + `sbsigntool` sign a UKI with *your* keys, which needs firmware enrolment. | **no equivalent** |

Counted over 41 controls: **18 ports cleanly, 16 needs rework, 7 no equivalent** — of which two
are costs *saved* (coredumps, lid switch) and one is moot (`TTYVTDisallocate`). The four that are
costs paid and cannot be bought back with configuration are the rebuild harness, the package archive,
the unsigned boot chain, and the initramfs's unconditional apkovl scan.

---

## 1. Build toolchain

### 1.1 It emits an ISO, and that was the decisive constraint

`scripts/mkimage.sh` builds the image by merging *sections* into a `DESTDIR` and then dispatching on
`output_format`. For `iso` that is `create_image_iso()` in `mkimg.base.sh`, which runs `xorrisofs`
with `-isohybrid-mbr`, El Torito, and an `-eltorito-alt-boot` EFI entry pointing at a FAT image built
with `mformat`/`mcopy`. So §1's decisive test — *does it emit a bootable ISO9660 hybrid image* — passes
on the same terms `live-build` passed it.

- <https://gitlab.alpinelinux.org/alpine/aports/-/blob/3.24-stable/scripts/mkimage.sh>
- <https://gitlab.alpinelinux.org/alpine/aports/-/blob/3.24-stable/scripts/mkimg.base.sh>

### 1.2 Reproducibility: better than expected on timestamps, worse on everything else

The intuition "Debian threads `SOURCE_DATE_EPOCH` explicitly, Alpine does not" is wrong, and the
reason is worth recording because it changes the shape of the cost.

`mkimage.sh:22-37` defines and **exports** `SOURCE_DATE_EPOCH`, taking it from the aports git commit
date and falling back to `date -u +%s`. It does not pass `--modification-date` to `xorrisofs` — but it
does not need to, because xorriso implements the reproducible-builds environment variable itself:

> "Instead of setting each of them, it is possible to influence them all by the environment variable
> SOURCE_DATE_EPOCH. … If it contains a number, then it is used as time value to set the default of
> `--modification-date=`. `--gpt_disk_guid` defaults to "modification-date". The default of
> `--set_all_file_dates` is then "set_to_mtime"."
> — `xorrisofs(1)`, <https://www.gnu.org/software/xorriso/man_1_xorrisofs.html>

The ESP is deterministic for a different reason: `mformat -i … -C -f 1440 -N 0 ::` sets the FAT volume
serial to zero outright, and the image's mtime is then `touch -md "@${SOURCE_DATE_EPOCH}"`
(`mkimg.base.sh:263-265`). Package contents are normalised one layer down — `abuild` runs
`touch -h -d "@$SOURCE_DATE_EPOCH"` over the package tree and stamps `builddate` from the same value
(`abuild.in:117-123,1116,1771`). <https://gitlab.alpinelinux.org/alpine/abuild/-/blob/master/abuild.in>

What Alpine does *not* have:

1. **No rebuild-and-compare harness.** `aports/scripts/` contains exactly `bootstrap.sh`,
   `genapkovl-dhcp.sh`, `genapkovl-xen.sh`, `genrootfs.sh`, `mkimage-yaml.sh`, `mkimage.sh`,
   `mkimg.{arm,base,minirootfs,netboot,standard,uboot,xen}.sh`. There is no `test/rebuild.sh`
   equivalent and no published per-image reproducibility status page of the kind Debian keeps for its
   live images. Verified by listing the tree at `3.24-stable`:
   <https://gitlab.alpinelinux.org/api/v4/projects/alpine%2Faports/repository/tree?ref=3.24-stable&path=scripts>
2. **No package archive to pin against.** `snapshot.debian.org` has no Alpine counterpart:
   `archive.alpinelinux.org` does not resolve, and superseded revisions are removed from the mirror —
   `alpine-baselayout-3.7.2-r1.apk` returns 200 while `alpine-baselayout-3.7.2-r0.apk` returns 404 on
   `dl-cdn.alpinelinux.org/alpine/v3.24/main/x86_64/`. Rebuilding a given ISO byte-for-byte therefore
   requires that *we* keep the `.apk` files. One mitigation is structural and free: Alpine's ISO
   carries its own signed `apks/` repository (`build_apks()` in `mkimg.base.sh`), so the artifact is
   its own archive of everything it installs at boot.

Note also that xorriso stamps its own version into the Primary Volume Descriptor's Preparer Id by
default, so the xorriso version has to be pinned as well — the same obligation §1 already accepted for
`live-build`.

### 1.3 There is no hook mechanism, and that is where most of §3 and §4 goes

`live-build`'s customisation surface is four directories, and §1 names them:
`config/package-lists/*.list.chroot`, `config/includes.chroot/`, `config/hooks/normal/*.hook.chroot`,
`*.hook.binary`. The walking skeleton uses five hooks and seven `includes.chroot` files.

Alpine's surface is different in kind:

- **`apks="…"`** — the package list, which becomes the on-ISO repository, not an installed rootfs.
- **`apkovl=`** — a `genapkovl-*.sh` script run under `fakeroot` that emits a tarball of `/etc`
  overrides and runlevel symlinks. This is the closest thing to `includes.chroot`, and it is where
  `/etc/inittab`, `/etc/sysctl.d/`, `/etc/modprobe.d/` and the `signer` user would live.
  (`build_apkovl()`, `mkimg.base.sh:68-85`; example: `scripts/genapkovl-dhcp.sh`.)
- **`initfs_features`** — the initramfs contents (§3 below).
- **Function overriding.** `load_plugins()` sources `$scriptdir/mkimg.*.sh` and then
  `$HOME/.mkimage/mkimg.*.sh` (`mkimage.sh:99-111,202-205`), so a later plugin can redefine any shell
  function `mkimg.base.sh` defined — `build_kernel`, `section_syslinux`, `create_image_iso`. This is
  the sanctioned extension point and it is what the module-stripping control has to use.

Honest downsides, in the same spirit as §1's list for `live-build`: it is shell scripts; the build must
run on Alpine because it calls `apk`, `abuild-sign` and `alpine-conf`'s `update-kernel`; it needs
`fakeroot`; and with `modloop_sign=yes` (the profile default) it **requires a `PACKAGER_PRIVKEY`** or
it errors out (`build_kernel()`, `mkimg.base.sh:5-11`). A signing key becomes a build input, which
`live-build` never needed.

---

## 2. Kiosk

### 2.1 The 22-package floor is a 25-package, 19.8 MiB floor

Resolved transitively from the `v3.24` `main` + `community` `APKINDEX` (x86_64), rooted at
`libinput-libs`, `libxkbcommon`, `fontconfig`, `font-dejavu`, `eudev`, and excluding what
`alpine-base` already puts on the image:

| Package | Version | Repo | Installed |
|---|---|---|---|
| `font-dejavu` | 2.37-r6 | main | 9990 KiB |
| `xkeyboard-config` | 2.47-r0 | main | 3255 KiB |
| `libxml2` | 2.13.9-r2 | main | 1047 KiB |
| `brotli-libs` | 1.2.0-r1 | main | 958 KiB |
| `zstd-libs` | 1.5.7-r2 | main | 698 KiB |
| `freetype` | 2.14.3-r0 | main | 658 KiB |
| `eudev` | 3.2.14-r6 | main | 652 KiB |
| `encodings` | 1.1.0-r0 | main | 632 KiB |
| `fontconfig` | 2.17.1-r1 | main | 518 KiB |
| `libinput-libs` | 1.31.3-r0 | **community** | 357 KiB |
| `libxkbcommon` | 1.13.1-r0 | main | 356 KiB |
| `xz-libs`, `libblkid`, `libpng`, `libexpat`, `libeconf`, `kmod-libs`, `libbz2`, `libevdev`, `libfontenc`, `mtdev`, `mkfontscale`, `udev-init-scripts`, `busybox-binsh` | — | mixed | 1.6 MiB combined |
| **Total** | | | **25 packages / 19.8 MiB** |

Adding the seat path costs 4 packages and 0.7 MiB: `seatd` (42 KiB), `libseat` (38 KiB), `libelogind`
(556 KiB) and `libcap2` (47 KiB) — Alpine builds seatd with `-Dlibseat-logind=elogind`, so
`libseat 0.9.3-r0` carries a hard `so:libelogind.so.0` dependency even when
`LIBSEAT_BACKEND=seatd`. **29 packages / 20.5 MiB.**

Against §2's Debian figure of 22 packages / 21 MiB this is a wash, which is the useful result: musl
does not make the KMS GUI floor cheaper or dearer in any way that matters. Two caveats on
comparability: the Debian number counts a different thing (direct entries in
`aobs.list.chroot` plus apt's closure), and my exclusion set for "already on the image" is my own
judgement, not Alpine's. The shape — one ~10 MiB font package dominating, everything else small — is
the same on both.

Two Alpine-specific notes inside that number. `font-dejavu 2.37-r6` is 9990 KiB and is **not split**
the way Debian splits `fonts-dejavu-core` out; it also pulls `encodings` and `mkfontscale`, which are
X11 font tooling we have no other use for. And `libxkbcommon` pulls `xkeyboard-config` (3255 KiB) plus
`libxml2`, exactly as on Debian.

Sources: `https://dl-cdn.alpinelinux.org/alpine/v3.24/{main,community}/x86_64/APKINDEX.tar.gz`;
`https://gitlab.alpinelinux.org/alpine/aports/-/blob/3.24-stable/community/seatd/APKBUILD`.

### 2.2 The repository each package lives in is a real cost

`libinput`, `libinput-libs`, `libevdev`, `mtdev`, `seatd` and `libseat` are in **community**. Alpine
states the consequence itself:

> "Packages in the **community** repository are those made by users in team with the official
> developers … They are supported by those user(s) contributions, and support ends six months after
> their release."
> — <https://wiki.alpinelinux.org/wiki/Repositories>, citing
> <https://docs.alpinelinux.org/user-handbook/0.1a/Working/apk.html#_repositories_releases_and_mirrors>

Main, by contrast, is patched for the branch's life: 3.24 is supported to 2028-06-01
(<https://alpinelinux.org/releases.json>). So the display path's input library gets six months of
security support on a stable branch, and staying supported means tracking Alpine's ~6-month release
cadence (3.22 2025-05-30, 3.23 2025-12-03, 3.24 2026-06-09). Debian trixie patches the whole suite
for years. This is the cost that recurs rather than being paid once.

Good news in the same breath: `eudev`, `freetype`, `fontconfig`, `font-dejavu`, `libxkbcommon`,
`kmod` and **`rust`/`cargo`** are all in `main`.

### 2.3 The Rust build: `crt-static`, and which `rustc`

`x86_64-unknown-linux-musl` is **Tier 2 with Host Tools** (`x86_64-unknown-linux-gnu` is Tier 1), and
the Rust Reference names it explicitly as one of the targets that link the C runtime **statically by
default**:

> "All targets in the compiler have a default mode of linking to the C runtime. Typically targets are
> linked dynamically by default, but there are exceptions which are static by default such as: …
> `x86_64-unknown-linux-musl`"
> — <https://github.com/rust-lang/reference/blob/master/src/linkage.md> ("Static and dynamic C
> runtimes"); tier from
> <https://github.com/rust-lang/rust/blob/master/src/doc/rustc/src/platform-support.md>

We link `libinput`, `libxkbcommon`, `fontconfig` and `freetype` from Alpine's packages, so a static
CRT is the wrong mode and `-C target-feature=-crt-static` becomes mandatory — *unless* the build uses
Alpine's own toolchain, which already flips the default:

```
--set="target.$_target.crt-static=false"
```
— `main/rust/APKBUILD:307` (`_target="$CHOST"`, i.e. `x86_64-alpine-linux-musl`),
<https://gitlab.alpinelinux.org/alpine/aports/-/blob/3.24-stable/main/rust/APKBUILD>

So there are two shapes, and the choice is a real one: keep `rust-toolchain.toml`'s pinned **1.97.1**
via rustup and add the `x86_64-unknown-linux-musl` target plus the flag; or build with Alpine's
packaged **rust 1.96.1-r0** and drop toolchain pinning to whatever the branch ships. The repo
currently pins 1.97.1 with `targets = ["x86_64-unknown-linux-gnu"]`, so either way
`rust-toolchain.toml` changes.

One musl difference worth naming and then dismissing: musl's default thread stack is
`DEFAULT_STACK_SIZE 131072` — 128 KiB, against glibc's 8 MiB
(<https://git.musl-libc.org/cgit/musl/tree/src/internal/pthread_impl.h>). It does not reach the main
thread (sized by `RLIMIT_STACK`) and it does not reach Rust-spawned threads (`std::thread` sets its
own), so it can only bite threads created inside C libraries. Not verified against a running build.

### 2.4 udev is not optional, and Alpine's default is `mdev`

Slint 1.17.1's linuxkms input path uses libinput's **udev** backend on both branches of the
`libseat` feature flag:

```rust
#[cfg(not(feature = "libseat"))]
impl DirectDeviceAccess {
    pub fn new() -> input::Libinput {
        let mut libinput = input::Libinput::new_with_udev(Self {});
        libinput.udev_assign_seat("seat0").unwrap();
        libinput
    }
}
```
— `internal/backends/linuxkms/calloop_backend/input.rs` at `v1.17.1`,
<https://github.com/slint-ui/slint/blob/v1.17.1/internal/backends/linuxkms/calloop_backend/input.rs>

`alpine-base` depends on `busybox-mdev-openrc`, and the diskless boot enables `mdev` + `hwdrivers` in
`sysinit` — there is no `libudev` in that picture. So an Alpine image needs `eudev` (which provides
`udev=176` and `libudev.so.1`) plus `udev-init-scripts`, with `udev`, `udev-trigger` and `udev-settle`
in `sysinit` replacing `mdev`. Alpine's own script does exactly this, and it is the right primary
source for what Alpine thinks a seat/input stack needs:

```sh
enable_udev () {
	apk add --quiet eudev udev-init-scripts udev-init-scripts-openrc
	rc-update add --quiet udev sysinit
	rc-update add --quiet udev-trigger sysinit
	rc-update add --quiet udev-settle sysinit
	…
```
— `setup-devd.in`, alpine-conf 3.22.0,
<https://gitlab.alpinelinux.org/alpine/alpine-conf/-/blob/3.22.0/setup-devd.in>

Note what we do **not** need from Alpine's Wayland recipe: `setup-wayland-base` installs `elogind` +
`polkit-elogind` and enables `cgroups` + `dbus`
(<https://gitlab.alpinelinux.org/alpine/alpine-conf/-/blob/3.22.0/setup-wayland-base.in>). That is the
logind seat path, and the `-noseat` route [#46](https://github.com/allisson/aobs/issues/46) found
skips all of it.

### 2.5 The seat group question inverts

§2 records that `_seatd` "is the upstream and Arch convention; **Debian has no such group**", so on
Debian the seat group and the DRM group are both `video`, and the build hook reads the group out of
`seatd.service` rather than hardcoding a name. On Alpine the group exists and is called neither:

```
pkggroups="seat"
…
command_args="-g seat -l ${loglevel:-error} ${command_args:-}"
```
— `community/seatd/APKBUILD:12` and `community/seatd/seatd.initd`,
<https://gitlab.alpinelinux.org/alpine/aports/-/blob/3.24-stable/community/seatd/APKBUILD>

The hook's *principle* survives — read the group from the service definition, fail the build if it
moved — but the implementation reads an OpenRC init script instead of `systemctl show`, and `signer`
joins `video`, `input` and `seat` rather than `video`, `input`.

### 2.6 `Restart=always` and "no gettys" both get cheaper

`alpine-baselayout` 3.7.2-r1 ships an `/etc/inittab` with six gettys:

```
tty1::respawn:/sbin/getty 38400 tty1
…
tty6::respawn:/sbin/getty 38400 tty6
```
— <https://gitlab.alpinelinux.org/alpine/aports/-/blob/3.24-stable/main/alpine-baselayout/inittab>

On a live Alpine `root` has no password, so those gettys are the shell escape §2 forbids, and removing
them is a single file in the apkovl — cheaper than `logind.conf` plus six masked units plus the
`getty.target.wants` sweep the current hook performs. The same file provides the restart supervision:
busybox init's `respawn` action is documented as

> "'respawn' actions are run after the 'once' actions. When a process started with a 'respawn' action
> exits, init automatically restarts it. Unlike sysvinit, BusyBox init does not stop processes from
> respawning out of control."
> — busybox 1.37.0 `init/init.c` usage text, <https://busybox.net/downloads/busybox-1.37.0.tar.bz2>

with a `sleep1()` in the reap loop that keeps a crash loop off the CPU (`init.c:1215-1216`). That is
`Restart=always` + `RestartSec=1s` in one inittab line. §9's requirement that a *startup* failure not
restart is unaffected, because the wrapper parks rather than exiting.

`kernel.sysrq=0` is still needed — Alpine's kernel sets `CONFIG_MAGIC_SYSRQ_DEFAULT_ENABLE=0x1` — and
still works, because Alpine replaces OpenRC's upstream `sysctl` service (which calls
`sysctl --system`, an option busybox's `sysctl` does not implement — its option string is
`"neAapwq"`) with one that loops `sysctl -p "$f"` over `/lib/sysctl.d`, `/usr/lib/sysctl.d`,
`/etc/sysctl.d`, `/etc/sysctl.conf` and `/run/sysctl.d`, in that order.
— `main/openrc/sysctl.initd`,
<https://gitlab.alpinelinux.org/alpine/aports/-/blob/3.24-stable/main/openrc/sysctl.initd>;
busybox `procps/sysctl.c`.

---

## 3. No network

### 3.1 The modules are in a signed squashfs, not in the rootfs

This is the largest single rework in the file, and it is structural rather than a matter of
translating a hook.

On Debian the kernel modules are files in the chroot, so
`0200-aobs-no-network-modules.hook.chroot` deletes three directories, runs `depmod`, and
`update-initramfs` rebuilds. On Alpine the ISO has **no rootfs**. `update-kernel` (alpine-conf) installs
`linux-lts` into a throwaway tree, copies `$ROOTFS/lib/modules` plus a `modules/firmware` directory
into `$MODLOOP`, and runs:

```sh
mksquashfs $MODLOOP "$STAGING/$MODIMG" $MKSQUASHFS_OPTS -comp xz -exit-on-error $mksfs
if [ -n "$MODLOOPSIGN" ]; then
	sign_modloop "$STAGING/$MODIMG"
```
— <https://gitlab.alpinelinux.org/alpine/alpine-conf/-/blob/3.22.0/update-kernel.in>

`sign_modloop` is `openssl dgst -sha1 -sign "$PACKAGER_PRIVKEY"`, and the signature is verified at boot
by the `modloop` OpenRC service against `/etc/apk/keys/*.pub`, defaulting to on
(`KOPT_modloop_verify:=yes`) whenever a matching signature file is present
(<https://gitlab.alpinelinux.org/alpine/aports/-/blob/3.24-stable/main/openrc/modloop.initd>).

So the deletion has to happen **inside** `update-kernel`, between `_apk add` and `mksquashfs`. The
practical shapes are: fork `update-kernel` into the repo; or override `build_kernel()` in our own
`mkimg.aobs.sh` to run `update-kernel`, unsquash, strip, re-squash and re-sign. Either way a distro
script becomes part of our source tree, or a build step reimplements it. §3's guarantee is reachable;
its *one-hook* cost is not.

Two things do come free once the strip is in the right place:

- **`depmod` is handled twice over.** `update-kernel` runs `depmod -b $ROOTFS` before squashing, and at
  boot the `modloop` service runs `depmod -A` after mounting a tmpfs overlay on `/lib/modules`
  (`modloop.confd` sets `overlay_size=0`, so the overlay is always taken on a kernel with overlayfs).
- **The firmware cascade.** `update-kernel` copies only firmware that some installed module's
  `modinfo -F firmware` names, plus `wireless-regdb` if `cfg80211.ko` exists and `brcm/*.hcd` if
  `btbcm.ko` exists. Delete `drivers/net` and `drivers/bluetooth` first and most of that copy stops
  happening by itself.

Note also that `/lib/modules` being an overlay with a tmpfs upper layer is a live difference from
§3's argument that "the rootfs is a read-only squashfs … so there is no `.ko` on the medium to
`insmod`". On Alpine `/lib/modules` is writable at runtime. With no shell, no network and no
untrusted-write path this is not an attack, but the sentence in §3 would no longer be true as written.

### 3.2 `install no firmware-* package` cannot be done by package selection

`update-kernel` hardcodes it:

```sh
PACKAGES="$PACKAGES linux-$FLAVOR linux-firmware"
```

and `mkimg.base.sh:section_kernels()` passes `linux-firmware wireless-regdb` too. `linux-firmware-none`
exists in `main` (0 bytes) but its `provides` is `linux-firmware-any`, not `linux-firmware`, so it
cannot satisfy that literal dependency —
<https://gitlab.alpinelinux.org/alpine/aports/-/blob/3.24-stable/main/linux-firmware/APKBUILD>. §3's
"install no `firmware-*` package" therefore becomes "delete the modules that reference firmware before
the squashfs is built, and assert against the artifact that `modules/firmware` is empty".

### 3.3 The initramfs is where Alpine is *ahead*

§3 flags `initramfs-tools MODULES=most` as a hole in the boot path that has to be closed. Alpine's
equivalent is a named feature list, and the ISO profile's default already excludes network drivers:

```sh
initfs_features="ata base bootchart cdrom dhcp ext4 mmc nvme raid scsi squashfs usb virtio"   # + nfit on x86_64
```
— `profile_base()`, `mkimg.base.sh:330`

The only network-adjacent contribution is `dhcp.modules`, whose entire content is
`kernel/net/packet/af_packet.ko*`. `network.modules` — the one that lists
`kernel/drivers/net/ethernet`, `phy`, `hyperv`, `vmxnet3`, `virtio_net` — is **not** in the list.
Verified against mkinitfs 3.14.0's `features.d/`:
<https://gitlab.alpinelinux.org/alpine/mkinitfs/-/tree/3.14.0/features.d>

So dropping `dhcp` from `initfs_features` leaves an initramfs with no `drivers/net` and no
`kernel/net/` entry at all — a smaller, more legible control than `MODULES=dep`, which the walking
skeleton rejected anyway because `dep` resolves against the build machine's hardware.

One caveat that cuts the other way: `feature_files()` silently skips any path that does not exist
(`[ -d "$file" ] … elif [ -e "$file" ] … ` with no `else`), so a feature file naming a moved path
contributes nothing and the build still succeeds. mkinitfs 3.14.0's `base.modules` demonstrates it
today — it lists `kernel/drivers/gpu/drm/tiny/simpledrm.ko*`, a path that no longer exists in 6.18
(#44 §4). §3's "fail the build if the layout changed" check is therefore entirely ours to write, as it
is on Debian; nothing in mkinitfs will complain on our behalf.

### 3.4 `install <module> /bin/false` is a no-op with busybox

§3's control 3 relies on a `modprobe.d` directive busybox does not implement. busybox 1.37.0's
`modutils/modprobe.c` parses `alias`, `options` and — with `CONFIG_FEATURE_MODPROBE_BLACKLIST=y`, which
Alpine sets — `blacklist`. There is no `install` handling. Alpine's `hwdrivers` service calls
`modprobe -b -a`, i.e. busybox's, so a `/etc/modprobe.d/aobs-no-network.conf` full of
`install e1000e /bin/false` lines would be read and ignored.

Getting the control back costs the `kmod` package (34.2-r1, main, 130 KiB), which provides
`cmd:modprobe` and would take over `/sbin/modprobe`. Which provider wins the path in practice was not
verified.
— busybox config: <https://gitlab.alpinelinux.org/alpine/aports/-/blob/3.24-stable/main/busybox/busyboxconfig>

### 3.5 What ports without comment

Alpine's `linux-lts` builds every relevant driver as a module — `E1000=m`, `E1000E=m`, `R8169=m`,
`IWLWIFI=m`, `BT=m`, `USB_NET_DRIVERS=m`, `PACKET=m` — so the deletion is effective, and
`CONFIG_UNIX=y` means AF_UNIX survives deleting `kernel/net/`, exactly as §3 requires. Read from the
resolved `.config` inside `linux-lts-dev-6.18.44-r0.apk`
(`usr/src/linux-headers-6.18.44-0-lts/.config`).

---

## 4. No swap, no persistence, no crash dumps

### 4.1 Swap: nothing to mask

Alpine's `openrc` package ships **empty runlevels** — `rm -f "$pkgdir"/etc/runlevels/*/*` in
`package()`, and its `.post-install` only migrates pre-existing `rc[SL].d` symlinks and otherwise
exits 0. The services a diskless boot ends up with are exactly the ones `initramfs-init` writes:

```
sysinit:  devfs dmesg mdev hwdrivers modloop
boot:     modules sysctl hostname bootmisc syslog   (+ hwclock or swclock)
shutdown: mount-ro killprocs savecache
default:  firstboot
```
— `initramfs-init.in:948-975`, mkinitfs 3.14.0

`swap` is not among them, and neither is `localmount`, `netmount` or `seedrng` — the last of which
matters for §8, because OpenRC's `seedrng` service is precisely the seed-file practice §8 forbids, and
it is off by default here.

§4's "neuter `/sbin/swapon`" degrades, though: `swapon` is a busybox applet
(`CONFIG_SWAPON=y`), so removing the symlink leaves `busybox swapon` reachable. On a system with no
shell that is close to academic, but it is weaker than deleting a standalone binary.

`savecache` (shutdown) writes OpenRC's dependency cache to `/lib/rc/cache`, which on a tmpfs root is
RAM only. `bootmisc`'s `wipe_tmp` is switched to `no` by an Alpine patch
(`0008-bootmisc-switch-wipe_tmp-setting-to-no-by-default.patch`).

### 4.2 Persistence: the parameter disappears, and something worse appears

There is no `persistence` or `swap` boot parameter on Alpine, so §4's primary control — *never put them
on the cmdline* — has nothing to withhold. But Alpine's diskless boot has its own persistence
mechanism and **it is on by default with no cmdline gate**.

`initramfs-init` runs `nlplug-findfs … -a "$ROOT"/tmp/apkovls`, and `nlplug-findfs` mounts each block
device it discovers and scans its root:

```c
} else if (fnmatch("*.apkovl.tar.gz*", opts->filename, 0) == 0) {
	dbg("found apkovl %s", opts->path);
	append_line(conf->apkovls, opts->path);
	ctx->found |= FOUND_APKOVL;
}
```
— `nlplug-findfs/nlplug-findfs.c:902-905`, mkinitfs 3.14.0

The first hit is then unpacked into the tmpfs root, and for the `.gz` case there is no signature check
at all:

```sh
if [ "$suffix" = "gz" ]; then
	tar -C "$dest" -zxvf "$ovl" > $ovlfiles
	return $?
fi
```
— `initramfs-init.in:53-56` (`unpack_apkovl()`)

and its `/etc/apk/world` is added to the package set installed at boot. The device scan itself is not
optional: `searchdev(ev, conf->search_device, (conf->apkovls || conf->bootrepos))`
(`nlplug-findfs.c:1105`) scans whenever either output file is set, and the boot-repository scan is how
Alpine finds the ISO's own `apks/` directory. Passing an explicit `apkovl=<path>` does bypass the
*selection* (`initramfs-init.in:916`, `prepare_apkovl()`'s `*)` case), but not the mounting.

So on an Alpine base the initramfs mounts and parses filesystems on every attached block device
before our code runs, and absent an explicit `apkovl=`, an attacker-writable USB stick with a file
matching `*.apkovl.tar.gz*` in its root gets extracted into the root filesystem as root. Debian's
`live-boot` also probes devices to find its medium, so the mounting is not unique — the unsigned
config-overlay extraction, with no parameter required to enable it, has no Debian counterpart.
Mitigating it means an explicit `apkovl=` plus, if the mounting itself is unacceptable, patching
`initramfs-init`.

### 4.3 Crash dumps: Alpine's default is safer than Debian's, and this is a cost saved

§4 flags this as mattering more than it looks, because systemd's `Storage=external` default writes a
complete copy of the seed to a predictable filename. On a stock Alpine **no core file is written at
all**, for two independent reasons.

1. **`kernel.core_pattern` is the kernel default.** `fs/coredump.c:82` at v6.18 is
   `static char core_pattern[CORENAME_MAX_SIZE] = "core";` — a relative filename, not a pipe to a
   handler. The only sysctl defaults on a base Alpine image come from
   `alpine-baselayout`'s `/usr/lib/sysctl.d/00-alpine.conf`, which sets eleven `net.*` keys plus
   `kernel.panic`, `fs.protected_hardlinks`, `fs.protected_symlinks` and
   `kernel.unprivileged_bpf_disabled` — and **no `kernel.core_pattern`**. OpenRC ships only a README
   in `sysctl.d/`.
2. **`RLIMIT_CORE`'s soft limit is 0 and nothing raises it.** `include/asm-generic/resource.h`'s
   `INIT_RLIMITS` has `[RLIMIT_CORE] = { 0, RLIM_INFINITY }`, and that soft limit is inherited by
   every descendant of init. Debian's systemd raises it (`DefaultLimitCORE=`) and installs
   `systemd-coredump` as the pattern; Alpine has no logind and OpenRC's `rc_ulimit` is commented out
   in the shipped `rc.conf`. With a zero soft limit the dump is refused before a file is created:
   `coredump_file()` returns false when `cprm->limit < binfmt->min_coredump`, which for ELF is
   `ELF_EXEC_PAGESIZE` (`fs/coredump.c:883-884`, `fs/binfmt_elf.c:100`).

So the two lines of `coredump.conf.d/` become **one release-gate assertion instead of a control**:
check on the built artifact that `/proc/sys/kernel/core_pattern` is `core` and that the `signer`
process's `RLIMIT_CORE` soft limit is 0. The failure mode to watch is the inheritance: any wrapper that
raises `ulimit -c`, or a later `rc_ulimit`, brings the seed-in-a-file back silently. Per the standing
rule, that is a thing to assert against the artifact, not to remember.

Sources: <https://github.com/torvalds/linux/blob/v6.18/fs/coredump.c>,
<https://github.com/torvalds/linux/blob/v6.18/include/asm-generic/resource.h>,
<https://github.com/torvalds/linux/blob/v6.18/fs/binfmt_elf.c>,
<https://gitlab.alpinelinux.org/alpine/aports/-/blob/3.24-stable/main/alpine-baselayout/APKBUILD>,
<https://github.com/OpenRC/openrc/blob/0.63.2/etc/rc.conf>

### 4.4 Suspend and the lid switch: another absence

`CONFIG_HIBERNATION=y`, `CONFIG_SUSPEND=y` and `CONFIG_ACPI_BUTTON=m` on Alpine's `lts`, so the
kernel can do all of it — but nothing in userspace listens. There is no logind and no `elogind` unless
`setup-wayland-base` installs it; `acpid` is not in `profile_base`'s `apks=`. `nohibernate` stays on
the cmdline (it is a kernel parameter and still documented at 6.18), and `AllowHibernation=no` /
`HandleLidSwitch=ignore` have nothing to translate into. As with coredumps, the control becomes an
assertion that no seat/power daemon is installed.

---

## 5. RAM wipe at shutdown

`init_on_free=1` is a kernel parameter and transfers unchanged; Alpine additionally ships
`CONFIG_INIT_ON_ALLOC_DEFAULT_ON=y`, which zeroes pages at allocation — a partial extra, not a
substitute, since §5's concern is pages freed at shutdown that are never reallocated.

The second half of §5 — "freeing the overlayfs upper dir on shutdown" — has no direct equivalent
because **there is no overlay**. Alpine's diskless boot mounts a tmpfs as `$sysroot` and installs the
system into it with `apk add --initramfs-diskless-boot` from the ISO's own repository
(`initramfs-init.in:910`, `:1099-1108`). Consequences, all of which the spec would have to absorb:

- The read-write branch §5 wants freed *is* the root filesystem. Deleting its contents late in
  shutdown frees those pages immediately, which with `init_on_free=1` poisons them — so the mechanism
  Tails found "necessary but not sufficient" is, here, the whole job.
- The half Tails needed on top — `systemd-shutdown` switching root back into the initramfs so the root
  filesystem can be unmounted — has no OpenRC or busybox-init counterpart. `mount-ro` only remounts
  what it can read-only; a tmpfs root is never unmounted.
- The hazard is new and specific: the binaries the shutdown path is executing live in the tmpfs being
  deleted. Pages of an open inode are freed on last close, so ordering matters in a way it did not on
  a squashfs-backed root.
- Boot cost, in exchange: every boot runs `apk add` over the package set into RAM, rather than mounting
  a prebuilt squashfs. Not measured.

---

## 6. Kernel command line — and the one line Alpine silently undoes

The cmdline is set by `kernel_cmdline` in the profile, and both bootloaders' generators
(`syslinux_gen_config`, `grub_gen_config`) interpolate `$initfs_cmdline $kernel_cmdline`, so it lands
in one place as §6 wants. Every parameter in §6 exists at 6.18 and transfers verbatim — except one.

**`panic=0` does not survive userspace on Alpine.** `alpine-baselayout` ships:

```
# Restarts computer after 120 seconds after kernel panic
kernel.panic = 120
```
in `/usr/lib/sysctl.d/00-alpine.conf`, and the `sysctl` service applies it in the `boot` runlevel —
after the kernel has taken `panic=0` from the cmdline. §6's guarantee is that "a kernel panic **halts
with the message visible** instead of rebooting it away"; from the moment the `boot` runlevel
completes, an Alpine image reboots after 120 seconds and takes the message with it.

The fix is cheap and belongs in the apkovl: any `/etc/sysctl.d/*.conf` setting `kernel.panic = 0`
wins, because `sysctl.initd` applies `/etc/sysctl.d` after `/usr/lib/sysctl.d`; a same-named
`/etc/sysctl.d/00-alpine.conf` also shadows the original outright, by that script's explicit
`Ignoring $f due to /etc/sysctl.d/${f##*/}` rule. It is cheap *once known*, which is why it is
recorded here: this is a distribution default quietly reversing a spec decision, and it is exactly
the class of thing this survey exists to find.

---

## 7. Hardware floor

**UEFI-only** needs one override. `profile_standard` is a BIOS+UEFI hybrid: `section_syslinux()`
returns early only for non-x86 or non-ISO output, so `isolinux.bin` lands in the tree and
`create_image_iso()` takes the `-isohybrid-mbr … -eltorito-alt-boot` path. Redefining
`section_syslinux()` to `return 0` in our plugin gets the EFI-only branch, which the same function
already implements (`-efi-boot-part --efi-boot-image`).

**`toram` has no equivalent, and the property it buys is partly lost.** §7 earns `toram` on two product
grounds: the user can pull the stick once booted, and yanking it cannot kill a session mid-signature.
On Alpine the rootfs is in RAM by construction, so the *root* half is free — but `modloop` is mounted
from the medium by an OpenRC service and stays there, so pulling the stick removes the module tree.
That matters concretely for §7's own camera story: V4L2 devices are enumerated at the point of use, so
`uvcvideo` may need loading after the user has already removed the medium. Alpine ships the fix as a
command, not a boot parameter:

> "Copy kernel modules from modloop and unmount loopback device"
> — `copy-modloop`, alpine-conf 3.22.0,
> <https://gitlab.alpinelinux.org/alpine/alpine-conf/-/blob/3.22.0/copy-modloop.in>

So the equivalent is a boot service that runs `copy-modloop`, plus a decision about RAM: the modloop
copy is uncompressed modules in tmpfs, where `toram` holds a compressed squashfs. §7's provisional
2 GiB floor is derived from image size plus working set and would have to be re-derived. Not
attempted here.

**The camera is free, as on Debian.** `CONFIG_USB_VIDEO_CLASS=m` with `CONFIG_MEDIA_SUPPORT=m` in
`linux-lts`, so a USB UVC webcam costs zero extra packages; `v4l-utils` and `libv4l` stay out. The
MC-centric exclusion is a kernel-level fact and unchanged.

---

## 8. Entropy: the mechanism is identical, the number is not

`random.trust_cpu=off` transfers unchanged, and — checked rather than assumed — **the entropy path in
`drivers/char/random.c` is unchanged between v6.12 and v6.18**. A full diff of the two files shows
only the `chacha_state` struct refactor and the vDSO accessor rename (`__arch_get_k_vdso_rng_data()`
→ `vdso_k_rng_data`). `random_init_early()`, `trust_cpu`, `_credit_init_bits()`, `POOL_READY_BITS`,
`extract_entropy()`'s unconditional RDSEED pull and `try_to_generate_entropy()` are byte-identical.
Every claim in §8 and in `04-amnesic-boot-layer.md` §7 therefore survives the six-release jump.

What changes is `CONFIG_HZ`. Alpine's `lts` flavour sets **`CONFIG_HZ_1000=y` / `CONFIG_HZ=1000`**
against Debian's 250 (read from the resolved `.config` in `linux-lts-dev-6.18.44-r0.apk`). §8's
arithmetic is HZ-relative in two places:

```c
enum { NUM_TRIAL_SAMPLES = 8192, MAX_SAMPLES_PER_BIT = HZ / 15 };
…
stack->samples_per_bit = DIV_ROUND_UP(NUM_TRIAL_SAMPLES, num_different + 1);
if (stack->samples_per_bit > MAX_SAMPLES_PER_BIT)
	return;
…
/* Expiring the timer at `jiffies` means it's the next tick. */
stack->timer.expires = jiffies;
```
— <https://github.com/torvalds/linux/blob/v6.18/drivers/char/random.c> (`try_to_generate_entropy`),
with `entropy_timer()` crediting one bit every `samples_per_bit` firings.

| | Debian, `HZ=250` | Alpine `lts`, `HZ=1000` |
|---|---|---|
| Tick | 4 ms | 1 ms |
| `MAX_SAMPLES_PER_BIT` | 16 | 66 |
| 256 bits, 1 sample/bit | ~1.0 s | **~0.26 s** |
| 256 bits, worst accepted | ~16.4 s | **~16.9 s** |

**[derived]** — arithmetic off the source, not measured, exactly as the Debian figure was. So §8's
"~1–16 s" becomes **"~0.26–16.9 s"**: the same worst case, a roughly 4× better best case, and a
coarser TSC accepted before the jitter loop gives up (a higher `MAX_SAMPLES_PER_BIT` means more
machines take the timer path rather than falling through to interrupt entropy). The obligation §8
already owes — time it on target hardware — is unchanged in kind; only the number to compare against
moves. The verification command is unchanged too:
`dmesg | grep -E 'crng init done|RDRAND is not reliable'`.

Also relevant and favourable: OpenRC's `seedrng` service, which saves and restores a seed file, is not
in the diskless default runlevel set (§4.1). §8's "a seed file — it is exactly the persistence we
forbid" needs no action beyond not enabling it.

---

## 9. The diagnostic channel

#44 §6 already established that the console exists on Alpine: `CONFIG_VT=y`, `CONFIG_VT_CONSOLE=y`,
`CONFIG_FRAMEBUFFER_CONSOLE=y`, `CONFIG_DRM_FBDEV_EMULATION=y`, plus
`CONFIG_FRAMEBUFFER_CONSOLE_DEFERRED_TAKEOVER=y`, which Debian does not set. So §9's channel is there.

What does not port is the plumbing. The `aobs.service` unit routes output with
`TTYPath=/dev/tty1`, `StandardOutput=journal+console`, `TTYReset`, `TTYVHangup`,
`TTYVTDisallocate`. An inittab `respawn` line gives the process the tty as stdin/stdout/stderr
directly (busybox init sets `CONFIG_FEATURE_INIT_SCTTY=y`, so a leading `-` grants a controlling
tty), which is simpler but has no journal and no VT hygiene knobs. And the QEMU harness's serial-line
readiness signal, which currently rides `StandardOutput=journal+console` plus the `dialout` group
rather than `console=ttyS0`, needs a different arrangement on Alpine. Small, but it is CI-visible.

---

## 10. Costs no spec section names

**Secure Boot is lost outright, not merely unsigned.** The map has already ruled the loss admissible;
the size of it is worth recording. Debian's live ISO boots with Secure Boot enabled: live-build's
`binary_grub-efi` installs `shim-signed` and `grub-efi-amd64-signed` and uses the shim as
`bootx64.efi` (<https://salsa.debian.org/live-team/live-build/-/blob/master/scripts/build/binary_grub-efi>).
Alpine has **no `shim` package in `main` or `community`** — verified against both v3.24 indexes — and
`mkimg.base.sh:build_grub_efi()` produces `efi/boot/bootx64.efi` with `grub-mkimage` at build time,
unsigned. Alpine's Secure Boot story is `secureboot-hook` + `sbsigntool` (both in `main`) signing a
unified kernel image with keys you enrol in firmware yourself, plus `mokutil` in `community`. For an
appliance the user boots on their own machine, that means: Secure Boot must be turned off, or the user
enrols our key. The kernel itself is unsigned either way (`CONFIG_MODULE_SIG=y` is set, but
`MODULE_SIG_FORCE` is not, and that governs modules, not the image).

**The build moves into an Alpine container.** `ci/build-env.Dockerfile` is Debian today. `mkimage.sh`
needs `apk`, `abuild`, `alpine-conf`, `fakeroot`, `xorriso`, `mtools`, `squashfs-tools`, `grub-efi`
and `syslinux`, plus a generated `PACKAGER_PRIVKEY`. The Rust build moves with it, or the binary is
built elsewhere and injected as an `.apk` — which is itself a new build artifact and signing step the
Debian path does not have.

**And the release gate grows a row.** #44's finding that `DRM_SIMPLEDRM=y` is only two Alpine releases
old, and that the fragment-to-`olddefconfig` path can drop a symbol silently, means the config that
makes the display work is an assertion against the built artifact. `linux-lts` ships
`/boot/config-6.18.44-0-lts`, so the check is available inside the image.

---

## What was not checked

1. **Nothing was built and nothing was booted.** No Alpine ISO was produced, no `mkimage` run was
   attempted, and no image was started under OVMF. Every verdict above is read from sources.
2. **The 19.8 MiB / 25-package closure was computed, not observed.** It comes from resolving
   `APKINDEX` `D:` fields transitively and summing `I:`; `apk` may resolve a `so:` dependency to a
   different provider than my "first match" rule, and my "already on the image" exclusion set is my
   judgement rather than a measured `alpine-base` install. The Debian 21 MiB figure it is compared
   against was produced by a different method.
3. **The Rust build was not run.** That `cargo build` succeeds against Alpine's `libinput 1.31.3`,
   that the `input`/`input-sys` crates' pregenerated bindings match it, and that `xkbcommon 0.9` and
   `nix 0.31` behave on musl are all unverified. So is whether Slint 1.17.1 compiles at all with
   `crt-static=false` on `x86_64-alpine-linux-musl`.
4. **Whether `kmod`'s `modprobe` actually wins `/sbin/modprobe`** over busybox's applet symlink when
   both packages are installed was not verified, only that busybox's implementation ignores `install`
   and that `kmod` provides `cmd:modprobe`.
5. **No Alpine-owned statement on ISO reproducibility was found**, in either direction. The absence of
   a rebuild harness in `aports/scripts` is verified; the absence of a policy or a status page is
   merely "I did not find one".
6. **The package-archive claim rests on two HTTP status codes** (`-r1` 200, `-r0` 404) and one failed
   DNS lookup, not on an Alpine statement that superseded builds are deleted.
7. **`libseat`'s runtime behaviour on Alpine was not tested.** That `LIBSEAT_BACKEND=seatd` works with
   a `libseat` linked against `libelogind` but with no elogind running is inferred from libseat's
   backend selection, not observed. It may be moot if #46's `-noseat` route wins.
8. **The apkovl finding was not demonstrated.** That a crafted `*.apkovl.tar.gz*` on an attached USB
   stick is picked up and unpacked is read from `nlplug-findfs.c` and `initramfs-init.in`; I did not
   boot an image with a hostile stick attached. Nor did I establish whether an explicit `apkovl=` on
   the cmdline fully closes it, beyond the selection path.
9. **The `panic=0` conflict was not observed.** That `sysctl.initd` overwrites the cmdline value is
   read from the ordering of `/proc/cmdline` handling versus the `boot` runlevel; no panic was
   triggered on a running Alpine.
10. **RAM and boot-time figures are absent.** The `apk`-into-tmpfs boot cost, the modloop-in-RAM cost
    for a `copy-modloop` equivalent of `toram`, and the resulting revision of §7's 2 GiB floor were
    not estimated.
11. **Only x86_64 and only the `lts` flavour.** #44 already showed `virt` is the wrong flavour;
    `linux-stable` (7.1.5, community) was not priced.
12. **The migration itself was not scoped.** This file prices sections of `01-boot-layer.md`; it does
    not enumerate the changes to `05-testing-and-release.md`, ADR-0002, ADR-0009 or `ci/` that an
    Alpine base would drag with it.

---

## Sources

| Claim | Source |
|---|---|
| Alpine 3.24 branched 2026-06-09, EOL 2028-06-01; ~6-month cadence | <https://alpinelinux.org/releases.json> |
| community support ends six months after release; main is core-team supported | <https://wiki.alpinelinux.org/wiki/Repositories>, <https://docs.alpinelinux.org/user-handbook/0.1a/Working/apk.html#_repositories_releases_and_mirrors> |
| `mkimage.sh` exports `SOURCE_DATE_EPOCH`; loads `$HOME/.mkimage` plugins; requires `--repository` | [`3.24-stable:scripts/mkimage.sh`](https://gitlab.alpinelinux.org/alpine/aports/-/blob/3.24-stable/scripts/mkimage.sh) |
| `create_image_iso` uses `xorrisofs`; `mformat -N 0`; `profile_base`'s `initfs_features`, `apks`, `modloop_sign=yes`; `build_kernel` calls `update-kernel` | [`3.24-stable:scripts/mkimg.base.sh`](https://gitlab.alpinelinux.org/alpine/aports/-/blob/3.24-stable/scripts/mkimg.base.sh) |
| `profile_standard` is a BIOS+UEFI hybrid, `kernel_addons="xtables-addons"` | [`3.24-stable:scripts/mkimg.standard.sh`](https://gitlab.alpinelinux.org/alpine/aports/-/blob/3.24-stable/scripts/mkimg.standard.sh) |
| `aports/scripts/` contains no rebuild-and-compare harness | [tree listing, `3.24-stable:scripts`](https://gitlab.alpinelinux.org/api/v4/projects/alpine%2Faports/repository/tree?ref=3.24-stable&path=scripts) |
| `xorrisofs` honours `SOURCE_DATE_EPOCH` itself; stamps its version into Preparer Id | [`xorrisofs(1)`](https://www.gnu.org/software/xorriso/man_1_xorrisofs.html) |
| `abuild` normalises package mtimes and `builddate` from `SOURCE_DATE_EPOCH` | [`abuild.in`](https://gitlab.alpinelinux.org/alpine/abuild/-/blob/master/abuild.in) |
| superseded `.apk` revisions are removed; no `archive.alpinelinux.org` | `dl-cdn.alpinelinux.org/alpine/v3.24/main/x86_64/alpine-baselayout-3.7.2-r{0,1}.apk` (404 / 200); DNS lookup failure for `archive.alpinelinux.org` |
| `update-kernel` builds and signs `modloop`, hardcodes `linux-firmware`, runs `depmod -b` | [`alpine-conf 3.22.0:update-kernel.in`](https://gitlab.alpinelinux.org/alpine/alpine-conf/-/blob/3.22.0/update-kernel.in) |
| `copy-modloop` copies modules to RAM and unmounts the media | [`alpine-conf 3.22.0:copy-modloop.in`](https://gitlab.alpinelinux.org/alpine/alpine-conf/-/blob/3.22.0/copy-modloop.in) |
| `setup-devd udev` installs `eudev` + `udev-init-scripts`; `setup-wayland-base` installs elogind + dbus | [`setup-devd.in`](https://gitlab.alpinelinux.org/alpine/alpine-conf/-/blob/3.22.0/setup-devd.in), [`setup-wayland-base.in`](https://gitlab.alpinelinux.org/alpine/alpine-conf/-/blob/3.22.0/setup-wayland-base.in) |
| default `initfs_features` carries no `drivers/net`; `dhcp.modules` is only `af_packet`; `feature_files()` skips missing paths | [`mkinitfs 3.14.0:features.d`](https://gitlab.alpinelinux.org/alpine/mkinitfs/-/tree/3.14.0/features.d), [`mkinitfs.in`](https://gitlab.alpinelinux.org/alpine/mkinitfs/-/blob/3.14.0/mkinitfs.in) |
| diskless root is a tmpfs populated by `apk`; default runlevel set; `unpack_apkovl` untars `.gz` unverified; initramfs modprobes `simpledrm` | [`mkinitfs 3.14.0:initramfs-init.in`](https://gitlab.alpinelinux.org/alpine/mkinitfs/-/blob/3.14.0/initramfs-init.in) |
| `nlplug-findfs` mounts every block device and scans for `*.apkovl.tar.gz*` and `.boot_repository` | [`mkinitfs 3.14.0:nlplug-findfs/nlplug-findfs.c`](https://gitlab.alpinelinux.org/alpine/mkinitfs/-/blob/3.14.0/nlplug-findfs/nlplug-findfs.c) |
| `/etc/inittab` with six gettys; `kernel.panic = 120`; no `core_pattern`; `/etc/fstab` `noauto` entries | [`3.24-stable:main/alpine-baselayout/inittab`](https://gitlab.alpinelinux.org/alpine/aports/-/blob/3.24-stable/main/alpine-baselayout/inittab), [`APKBUILD`](https://gitlab.alpinelinux.org/alpine/aports/-/blob/3.24-stable/main/alpine-baselayout/APKBUILD) |
| openrc ships empty runlevels; Alpine overrides `sysctl`, `modloop`, `hwdrivers`, `modules` | [`3.24-stable:main/openrc/APKBUILD`](https://gitlab.alpinelinux.org/alpine/aports/-/blob/3.24-stable/main/openrc/APKBUILD), [`sysctl.initd`](https://gitlab.alpinelinux.org/alpine/aports/-/blob/3.24-stable/main/openrc/sysctl.initd), [`modloop.initd`](https://gitlab.alpinelinux.org/alpine/aports/-/blob/3.24-stable/main/openrc/modloop.initd), [`modloop.confd`](https://gitlab.alpinelinux.org/alpine/aports/-/blob/3.24-stable/main/openrc/modloop.confd), [`hwdrivers.initd`](https://gitlab.alpinelinux.org/alpine/aports/-/blob/3.24-stable/main/openrc/hwdrivers.initd) |
| `swap`/`seedrng` services; `rc_ulimit` commented out; `mount-ro` only remounts | [`openrc 0.63.2:init.d/swap.in`](https://github.com/OpenRC/openrc/blob/0.63.2/init.d/swap.in), [`seedrng.in`](https://github.com/OpenRC/openrc/blob/0.63.2/init.d/seedrng.in), [`etc/rc.conf`](https://github.com/OpenRC/openrc/blob/0.63.2/etc/rc.conf), [`init.d/mount-ro.in`](https://github.com/OpenRC/openrc/blob/0.63.2/init.d/mount-ro.in) |
| busybox `respawn` semantics; `sysctl` has no `--system`; `modprobe` has no `install`; `swapon` is an applet | busybox 1.37.0 `init/init.c`, `procps/sysctl.c`, `modutils/modprobe.c` (<https://busybox.net/downloads/busybox-1.37.0.tar.bz2>); [`3.24-stable:main/busybox/busyboxconfig`](https://gitlab.alpinelinux.org/alpine/aports/-/blob/3.24-stable/main/busybox/busyboxconfig) |
| package versions, sizes, repositories, dependencies | `https://dl-cdn.alpinelinux.org/alpine/v3.24/{main,community}/x86_64/APKINDEX.tar.gz` (fetched 2026-08-16) |
| `seatd` creates a `seat` group, runs `seatd -g seat`, built `-Dlibseat-logind=elogind` | [`3.24-stable:community/seatd/APKBUILD`](https://gitlab.alpinelinux.org/alpine/aports/-/blob/3.24-stable/community/seatd/APKBUILD), [`seatd.initd`](https://gitlab.alpinelinux.org/alpine/aports/-/blob/3.24-stable/community/seatd/seatd.initd) |
| `linux-firmware-none` provides `linux-firmware-any`, not `linux-firmware` | [`3.24-stable:main/linux-firmware/APKBUILD`](https://gitlab.alpinelinux.org/alpine/aports/-/blob/3.24-stable/main/linux-firmware/APKBUILD) |
| Alpine's rustc sets `crt-static=false` for `$CHOST` | [`3.24-stable:main/rust/APKBUILD`](https://gitlab.alpinelinux.org/alpine/aports/-/blob/3.24-stable/main/rust/APKBUILD) |
| `x86_64-unknown-linux-musl` is Tier 2 with host tools and `crt-static` by default | [`platform-support.md`](https://github.com/rust-lang/rust/blob/master/src/doc/rustc/src/platform-support.md), [`reference/linkage.md`](https://github.com/rust-lang/reference/blob/master/src/linkage.md) |
| musl default thread stack 128 KiB | [`musl:src/internal/pthread_impl.h`](https://git.musl-libc.org/cgit/musl/tree/src/internal/pthread_impl.h) |
| Slint 1.17.1 uses `Libinput::new_with_udev` on both seat paths; `libseat` is a Cargo feature | [`v1.17.1:calloop_backend/input.rs`](https://github.com/slint-ui/slint/blob/v1.17.1/internal/backends/linuxkms/calloop_backend/input.rs), [`Cargo.toml`](https://github.com/slint-ui/slint/blob/v1.17.1/internal/backends/linuxkms/Cargo.toml) |
| `random.c` entropy path identical v6.12 ↔ v6.18; `MAX_SAMPLES_PER_BIT = HZ/15`; timer fires next tick | [v6.12](https://github.com/torvalds/linux/blob/v6.12/drivers/char/random.c) vs [v6.18](https://github.com/torvalds/linux/blob/v6.18/drivers/char/random.c), full diff |
| `core_pattern` default `"core"`; `RLIMIT_CORE` soft 0; dump refused below `min_coredump` | [v6.18 `fs/coredump.c`](https://github.com/torvalds/linux/blob/v6.18/fs/coredump.c), [`include/asm-generic/resource.h`](https://github.com/torvalds/linux/blob/v6.18/include/asm-generic/resource.h), [`fs/binfmt_elf.c`](https://github.com/torvalds/linux/blob/v6.18/fs/binfmt_elf.c) |
| Alpine `lts` config: `HZ=1000`, all net drivers `=m`, `UNIX=y`, `USB_VIDEO_CLASS=m`, `MAGIC_SYSRQ_DEFAULT_ENABLE=0x1`, `INIT_ON_ALLOC_DEFAULT_ON=y`, `HIBERNATION=y`, `MODULE_SIG=y` | `usr/src/linux-headers-6.18.44-0-lts/.config` from [`linux-lts-dev-6.18.44-r0.apk`](https://dl-cdn.alpinelinux.org/alpine/v3.24/main/x86_64/linux-lts-dev-6.18.44-r0.apk) |
| no `shim` in Alpine; `secureboot-hook` + `sbsigntool` are the alternative | v3.24 `main`/`community` `APKINDEX` (no `shim` entry); `secureboot-hook 1.0-r2`, `sbsigntool 0.9.5-r3` |
| Debian live ISO boots Secure Boot via `shim-signed` + `grub-efi-amd64-signed` | [`live-build:scripts/build/binary_grub-efi`](https://salsa.debian.org/live-team/live-build/-/blob/master/scripts/build/binary_grub-efi) |

`git.kernel.org`'s cgit sits behind an anti-bot interstitial, so kernel sources were read from the
`torvalds/linux` GitHub mirror at the `v6.12` and `v6.18` tags — the same provenance
`04-amnesic-boot-layer.md` used.
