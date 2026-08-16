# Does Alpine's stock kernel bind `simpledrm` under UEFI?

Research findings for [aobs#44](https://github.com/allisson/aobs/issues/44). Parent:
[aobs#42](https://github.com/allisson/aobs/issues/42). Context:
[aobs#40](https://github.com/allisson/aobs/issues/40), which is where the same two symbols were
found *unset* on Debian 13.

Pinned at Alpine **3.24-stable** (the current stable branch), aport `main/linux-lts`,
**`pkgver=6.18.44` `pkgrel=0`**. Every config value below was read from Alpine's own aports tree and
then re-read from the resolved `.config` of the **built package**, not from prose.

## Answer

**The premise holds, and in the strongest form available: both symbols are set, and both are built
into the kernel image rather than shipped as modules.** In Alpine 3.24's `linux-lts` for x86_64:

```
CONFIG_SYSFB_SIMPLEFB=y
CONFIG_DRM=y
CONFIG_DRM_SIMPLEDRM=y
```

That is exactly the pair that `01-boot-layer.md` §7 assumed and that Debian falsified. `simpledrm`
is in `vmlinuz`, so it binds during kernel init with no initramfs, no module load and no userspace
involvement — there is not even an `=m` timing question to answer for this flavour.

Everything the ticket named as a way to "bind and still not help us" also checks out on `linux-lts`:
`CONFIG_DRM_GEM_SHMEM_HELPER=y` (the dumb-buffer support `backend-linuxkms` + `renderer-software`
needs), `CONFIG_DRM_KMS_HELPER=y`, `CONFIG_DRM_CLIENT_SELECTION=y`, `CONFIG_VT=y`,
`CONFIG_VT_CONSOLE=y`, `CONFIG_FRAMEBUFFER_CONSOLE=y`, `CONFIG_DRM_FBDEV_EMULATION=y`. `CONFIG_FB_EFI=y`
is also set but **cannot race** — upstream Kconfig states in terms that `efifb` is excluded from
generic system framebuffers whenever `SYSFB_SIMPLEFB` is selected (§4).

Two qualifications, neither of them fatal:

1. **`linux-edge` does not exist.** There is no such package in Alpine today; the non-LTS flavour is
   `community/linux-stable` (kernel 7.1.5), and it sets the same two symbols the same way (§2).
2. **`=y` is two releases old.** On 3.20-stable and 3.21-stable, `linux-lts` had `CONFIG_DRM=m` and
   `CONFIG_DRM_SIMPLEDRM=m`. It became `=y` in 3.22-stable. This is a value Alpine can flip back, so
   it belongs in the release gate as an assertion against the artifact, not as a remembered fact.

**Not answered here: nothing was booted.** This ticket verifies the kernel config claim, which is
what it was scoped to. The empirical counterpart of #40's OVMF test — `simpledrm` printing in the
log and `/dev/dri/card0` appearing on an Alpine kernel — is not in this file. See *What was not
checked*.

---

## 1. Which kernel flavours Alpine actually has

`main/linux-lts` is a single aport that builds **both** the `lts` and the `virt` flavours: its
`source=` lists `lts.x86_64.config` and `virt.x86_64.config`, and every `*.$CARCH.config` becomes a
flavour with its own subpackage. So `linux-virt` is not a separate aport.

| Package | Repository | Kernel | Exists? |
|---|---|---|---|
| `linux-lts` | `main` | 6.18.44-r0 | yes |
| `linux-virt` | `main` (same aport as `linux-lts`) | 6.18.44-r0 | yes |
| `linux-stable` | `community` | 7.1.5-r0 | yes |
| **`linux-edge`** | — | — | **no such package** |

`pkgs.alpinelinux.org` returns "No matching packages found" for `linux-edge` on `edge`/x86_64, and
`community/linux-edge`, `testing/linux-edge` and `main/linux-edge` are all 404 in aports on both
`3.24-stable` and `master`. The ticket's third flavour is therefore not a thing to evaluate;
`community/linux-stable` is its closest living equivalent and is covered below.

## 2. The two symbols, per flavour and per branch

Read from the aports config fragments (`<flavour>.x86_64.config`), with the line number in that file:

| Branch | Flavour | Kernel | `SYSFB_SIMPLEFB` | `DRM` | `DRM_SIMPLEDRM` | `FB_EFI` |
|---|---|---|---|---|---|---|
| 3.24-stable | `lts` | 6.18.44 | `=y` (L653) | `=y` (L2074) | `=y` (L2075) | `=y` (L2107) |
| 3.24-stable | `virt` | 6.18.44 | `=y` (L506) | `=m` (L747) | `=m` (L748) | absent |
| 3.24-stable | `stable` | 7.1.5 | `=y` (L647) | `=y` (L2054) | `=y` (L2076) | `=y` (L2087) |
| master (edge) | `lts` | 6.18.44 | `=y` (L653) | `=y` (L2074) | `=y` (L2075) | `=y` (L2107) |
| master (edge) | `stable` | 7.1.5 | `=y` (L642) | `=y` (L2020) | `=y` (L2042) | `=y` (L2053) |
| 3.23-stable | `lts` | — | `=y` (L653) | `=y` (L2074) | `=y` (L2075) | `=y` (L2107) |
| 3.22-stable | `lts` | — | `=y` (L666) | `=y` (L2087) | `=y` (L2114) | — |
| 3.21-stable | `lts` | — | `=y` (L660) | **`=m`** (L2080) | **`=m`** (L2107) | — |
| 3.20-stable | `lts` | — | `=y` (L665) | **`=m`** (L2105) | **`=m`** (L2133) | `=y` (L2140) |

Two readings:

- **`CONFIG_SYSFB_SIMPLEFB=y` has been set on every branch checked, back to 3.20.** This is the gate
  #40 identified, and Alpine has never had it unset in the range examined.
- **`DRM` and `DRM_SIMPLEDRM` moved from `=m` to `=y` in 3.22-stable** and have stayed there through
  3.23, 3.24 and edge. The commit that flipped it was not identified, so whether it was deliberate
  policy or incidental is unknown — which is the reason to assert it at build time rather than trust it.

## 3. Verified against the built package, not only against aports

The aports fragment alone is **not** proof. `_prepareconfig()` copies the fragment over `.config` and
then runs `make olddefconfig`:

```sh
cp "$srcdir"/$_config "$_builddir"/.config
make -C "$builddir" O="$_builddir" ARCH="$(_kernelarch $_arch)" olddefconfig
```

`olddefconfig` will drop a symbol whose dependencies are unmet, silently, and the fragments contain
no `# ... is not set` lines at all — so what the fragment asks for and what the build produces are
two different claims. Per the repo's standing rule, the shipped artifact was checked.

Method: fetched `linux-lts-dev-6.18.44-r0.apk` (21,988,025 bytes) and `linux-virt-dev-6.18.44-r0.apk`
(21,525,074 bytes) from `dl-cdn.alpinelinux.org/alpine/v3.24/main/x86_64/`, extracted
`usr/src/linux-headers-6.18.44-0-lts/.config` and `.../-virt/.config`. These are the resolved
configs of the same build as the `linux-lts` / `linux-virt` packages of the same `pkgver-pkgrel`.

Resolved values:

| Symbol | `lts` 6.18.44-0 | `virt` 6.18.44-0 |
|---|---|---|
| `CONFIG_EFI` / `CONFIG_EFI_STUB` | `y` / `y` | `y` / `y` |
| `CONFIG_SYSFB` | `y` | `y` |
| **`CONFIG_SYSFB_SIMPLEFB`** | **`y`** | **`y`** |
| **`CONFIG_DRM`** | **`y`** | **`m`** |
| **`CONFIG_DRM_SIMPLEDRM`** | **`y`** | **`m`** |
| `CONFIG_DRM_GEM_SHMEM_HELPER` | `y` | `m` |
| `CONFIG_DRM_KMS_HELPER` | `y` | `m` |
| `CONFIG_DRM_CLIENT_SELECTION` | `y` | `m` |
| `CONFIG_DRM_SYSFB_HELPER` | `y` | `m` |
| `CONFIG_DRM_FBDEV_EMULATION` | `y` | `y` |
| `CONFIG_DRM_I915` / `AMDGPU` / `NOUVEAU` / `RADEON` | `m` / `m` / `m` / `m` | not set / not set / — / — |
| `CONFIG_FB` / `CONFIG_FB_CORE` | `y` / `y` | `m` / `m` |
| `CONFIG_FB_EFI` | `y` | absent (needs `FB=y`) |
| `CONFIG_FB_VESA` | not set | — |
| `CONFIG_VT` / `CONFIG_VT_CONSOLE` | `y` / `y` | `y` / `y` |
| `CONFIG_FRAMEBUFFER_CONSOLE` | `y` | `y` |
| `CONFIG_FRAMEBUFFER_CONSOLE_DEFERRED_TAKEOVER` | `y` | not present |

The fragment and the resolved config agree on every symbol the ticket asked about. Nothing was lost
to `olddefconfig`.

The `linux-lts` package also ships **`/boot/config-6.18.44-0-lts`**, per Alpine's package-contents
index — so the same check is repeatable inside a built image, exactly the way #40 did it on Debian.

## 4. Why `CONFIG_FB_EFI=y` is not a race

`CONFIG_FB_EFI=y` on `lts` looks like the failure mode #40 hit, and it is not. Upstream Kconfig, read
from the 6.18.44 source tree Alpine builds (`drivers/firmware/Kconfig:186`):

```
config SYSFB_SIMPLEFB
	bool "Mark VGA/VBE/EFI FB as generic system framebuffer"
	...
	  This option, if enabled, marks VGA/VBE/EFI framebuffers as generic
	  framebuffers so the new generic system-framebuffer drivers can be
	  used instead. If the framebuffer is not compatible with the generic
	  modes, it is advertised as fallback platform framebuffer so legacy
	  drivers like efifb, vesafb and uvesafb can pick it up.
	  If this option is not selected, all system framebuffers are always
	  marked as fallback platform framebuffers as usual.

	  Note: Legacy fbdev drivers, including vesafb, efifb, uvesafb, will
	  not be able to pick up generic system framebuffers if this option
	  is selected.
```

That is the mechanism #40 inferred, stated by upstream from the other direction: with
`SYSFB_SIMPLEFB=y`, `efifb` gets a device **only** when the firmware framebuffer is incompatible with
simplefb. Keeping `efifb` built in is what the help text explicitly recommends ("you should still
keep vesafb and others enabled as fallback"), not a competing claim on the framebuffer.

Two 6.18-era details worth recording, since ADR-0009 cites `drivers/gpu/drm/tiny/simpledrm.c` and
that path no longer exists:

- **`simpledrm` now lives in `drivers/gpu/drm/sysfb/`.** `drivers/gpu/drm/tiny/` still exists but
  contains no `DRM_SIMPLEDRM`. The driver's Kconfig (`drivers/gpu/drm/sysfb/Kconfig:41`) is
  `tristate "Simple framebuffer driver"`, `depends on DRM && MMU`, and *selects*
  `DRM_GEM_SHMEM_HELPER`, `DRM_KMS_HELPER`, `DRM_CLIENT_SELECTION` and `DRM_SYSFB_HELPER` — so the
  dumb-buffer support ADR-0009 depends on is pulled in by the driver itself, not by luck of Alpine's
  config. Its help text: *"On x86 BIOS or UEFI systems, you should also select SYSFB_SIMPLEFB to use
  UEFI and VESA framebuffers."*
- **`DRM_EFIDRM` and `DRM_VESADRM` are new DRM drivers for the non-simplefb path**, and both are
  `depends on ... && (!SYSFB_SIMPLEFB || COMPILE_TEST)`. Upstream makes them mutually exclusive with
  `SYSFB_SIMPLEFB`. Alpine has neither enabled — consistent, since with `SYSFB_SIMPLEFB=y` they are
  unbuildable. Noted only because on a kernel *without* `SYSFB_SIMPLEFB`, `efidrm` would now be a
  second DRM route that did not exist when ADR-0009 was written. That is a fact about 6.18+, not
  about Alpine, and it does not change anything here.

## 5. `=m`, the initramfs, and why `virt` is not the flavour to ship

For `linux-lts` the question is moot: `=y` means `simpledrm` is in `vmlinuz` and binds during kernel
init.

For `linux-virt` it is not moot, and the answer is unfavourable:

- `CONFIG_DRM_SIMPLEDRM=m`, so it must be loaded.
- Alpine's `mkinitfs` does have a feature that would carry it — `features.d/kms.modules` lists
  `kernel/drivers/gpu` wholesale, which includes `simpledrm.ko`.
- But Alpine's own ISO profile does **not** enable it. `scripts/mkimg.base.sh`, `profile_base()`:
  `initfs_features="ata base bootchart cdrom dhcp ext4 mmc nvme raid scsi squashfs usb virtio"`
  (plus `nfit` on x86_64). No `kms`. So on a stock-profile Alpine image the DRM modules are not in
  the initramfs, and a `=m` `simpledrm` would bind only after the modloop is up.
- Independently, `virt` has no `i915`/`amdgpu` at all and `CONFIG_FB=m` (which is why `FB_EFI`
  vanishes — it is `depends on (FB = y) && EFI`). It is a VM kernel.

**Conclusion for the boot layer: `linux-lts`.** It is also the flavour `mkimg.base.sh` defaults to
(`kernel_flavors="lts"`). If a future decision moves to `virt` or to a hand-rolled initramfs, the
`kms` feature — or an explicit `simpledrm` in the module list — becomes load-bearing.

## 6. The kernel console §9's diagnostic block depends on

`CONFIG_VT=y`, `CONFIG_VT_CONSOLE=y`, `CONFIG_FRAMEBUFFER_CONSOLE=y` and
`CONFIG_DRM_FBDEV_EMULATION=y` on both flavours, so a text console exists over `simpledrm`'s fbdev
emulation and `01-boot-layer.md` §9's failure text has somewhere to land.

One observable difference from Debian: `lts` sets `CONFIG_FRAMEBUFFER_CONSOLE_DEFERRED_TAKEOVER=y`.
fbcon then takes over only at the first console output, so what the screen shows *before* the first
message differs from an immediate-takeover kernel. It does not remove the console and it does not
affect whether the diagnostic is printed. Flagged as something to look at when this is booted, not
as a problem.

## What was not checked

Stated plainly, because the file is only worth what it excludes:

- **Nothing was booted.** No Alpine ISO was run under OVMF with `ramfb`/no GPU, so
  `05-testing-and-release.md` §6.2's `simpledrm` row is still unproven — on Alpine it is now proven
  *possible*, not proven *working*. That test is the natural next step and it is not in this ticket's
  scope.
- **The 145 MB `linux-lts-6.18.44-r0.apk` was not downloaded.** The resolved `.config` came from
  `linux-lts-dev` of the same `pkgver-pkgrel`. `vmlinuz-lts` itself was not inspected, and the bytes
  of `/boot/config-6.18.44-0-lts` were not read — only its presence in the package-contents index.
- **The aports commit that changed `DRM` from `=m` to `=y` between 3.21 and 3.22 was not found**, so
  no claim is made about Alpine's intent or about how stable the `=y` is.
- **Slint was not run.** Dumb-buffer suitability is inferred from `DRM_GEM_SHMEM_HELPER` plus the
  driver's declared ops, the same inference ADR-0009 made. `backend-linuxkms` +
  `renderer-software` on an Alpine `simpledrm` device is untested.
- **x86_64 only.** Other architectures' configs were not read.
- **No Secure Boot / signed-kernel comparison.** `01-boot-layer.md` §3 valued Debian's signed kernel;
  what Alpine offers there is untouched here.
- **What an Alpine base costs the rest of the boot layer** — musl, package availability, image size,
  the Rust build — is explicitly out of this ticket's scope and is the ticket this one blocks.

## Sources

| Claim | Source |
|---|---|
| Current stable branch is `3.24-stable` | [aports branch list](https://gitlab.alpinelinux.org/api/v4/projects/alpine%2Faports/repository/branches) |
| `linux-lts` is 6.18.44-r0; builds both `lts` and `virt` flavours; `_prepareconfig` = `cp` + `make olddefconfig` | [`3.24-stable:main/linux-lts/APKBUILD`](https://gitlab.alpinelinux.org/alpine/aports/-/blob/3.24-stable/main/linux-lts/APKBUILD) |
| `lts` x86_64 fragment: `SYSFB_SIMPLEFB=y`, `DRM=y`, `DRM_SIMPLEDRM=y`, `FB_EFI=y` | [`3.24-stable:main/linux-lts/lts.x86_64.config`](https://gitlab.alpinelinux.org/alpine/aports/-/blob/3.24-stable/main/linux-lts/lts.x86_64.config) |
| `virt` x86_64 fragment: `SYSFB_SIMPLEFB=y`, `DRM=m`, `DRM_SIMPLEDRM=m` | [`3.24-stable:main/linux-lts/virt.x86_64.config`](https://gitlab.alpinelinux.org/alpine/aports/-/blob/3.24-stable/main/linux-lts/virt.x86_64.config) |
| Same values on edge | [`master:main/linux-lts/lts.x86_64.config`](https://gitlab.alpinelinux.org/alpine/aports/-/blob/master/main/linux-lts/lts.x86_64.config) |
| 3.23 / 3.22 `=y`; 3.21 / 3.20 `=m` | [3.23](https://gitlab.alpinelinux.org/alpine/aports/-/blob/3.23-stable/main/linux-lts/lts.x86_64.config), [3.22](https://gitlab.alpinelinux.org/alpine/aports/-/blob/3.22-stable/main/linux-lts/lts.x86_64.config), [3.21](https://gitlab.alpinelinux.org/alpine/aports/-/blob/3.21-stable/main/linux-lts/lts.x86_64.config), [3.20](https://gitlab.alpinelinux.org/alpine/aports/-/blob/3.20-stable/main/linux-lts/lts.x86_64.config) |
| `linux-edge` does not exist; flavours on edge/x86_64 are `linux-lts`, `linux-virt`, `linux-stable` | [pkgs.alpinelinux.org `linux-*`, edge, x86_64](https://pkgs.alpinelinux.org/packages?name=linux-%2A&branch=edge&arch=x86_64) |
| `linux-stable` is 7.1.5-r0 and sets the same two symbols | [`master:community/linux-stable/APKBUILD`](https://gitlab.alpinelinux.org/alpine/aports/-/blob/master/community/linux-stable/APKBUILD), [`stable.x86_64.config`](https://gitlab.alpinelinux.org/alpine/aports/-/blob/master/community/linux-stable/stable.x86_64.config), [`3.24-stable` copy](https://gitlab.alpinelinux.org/alpine/aports/-/blob/3.24-stable/community/linux-stable/stable.x86_64.config) |
| Resolved `.config` of the built packages | [`linux-lts-dev-6.18.44-r0.apk`](https://dl-cdn.alpinelinux.org/alpine/v3.24/main/x86_64/linux-lts-dev-6.18.44-r0.apk), [`linux-virt-dev-6.18.44-r0.apk`](https://dl-cdn.alpinelinux.org/alpine/v3.24/main/x86_64/linux-virt-dev-6.18.44-r0.apk) — `usr/src/linux-headers-6.18.44-0-{lts,virt}/.config` |
| `linux-lts` ships `/boot/config-6.18.44-0-lts` | [pkgs.alpinelinux.org contents, `linux-lts`, v3.24, x86_64](https://pkgs.alpinelinux.org/contents?file=config-*&name=linux-lts&branch=v3.24&arch=x86_64) |
| `SYSFB_SIMPLEFB` help text: legacy fbdev drivers cannot pick up generic system framebuffers | `drivers/firmware/Kconfig:186`, from the 6.18.44 source in `linux-lts-dev-6.18.44-r0.apk` (upstream: [`drivers/firmware/Kconfig`](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/drivers/firmware/Kconfig)) |
| `DRM_SIMPLEDRM` now in `drivers/gpu/drm/sysfb/Kconfig:41`; selects `DRM_GEM_SHMEM_HELPER`, `DRM_KMS_HELPER`, `DRM_CLIENT_SELECTION`, `DRM_SYSFB_HELPER` | `drivers/gpu/drm/sysfb/Kconfig`, same source tree (upstream: [`drivers/gpu/drm/sysfb/Kconfig`](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/drivers/gpu/drm/sysfb/Kconfig)) |
| `DRM_EFIDRM` / `DRM_VESADRM` are `depends on !SYSFB_SIMPLEFB` | same file |
| `FB_EFI` requires `FB=y` | `drivers/video/fbdev/Kconfig:436`, same source tree |
| `kms.modules` covers `kernel/drivers/gpu` | [`mkinitfs:features.d/kms.modules`](https://gitlab.alpinelinux.org/alpine/mkinitfs/-/blob/master/features.d/kms.modules) |
| Alpine's ISO profile omits `kms` from `initfs_features`, defaults `kernel_flavors="lts"` | [`3.24-stable:scripts/mkimg.base.sh`](https://gitlab.alpinelinux.org/alpine/aports/-/blob/3.24-stable/scripts/mkimg.base.sh) — `profile_base()` |

git.kernel.org's cgit is behind an anti-bot interstitial and could not be fetched directly; the
Kconfig text above was therefore read from the kernel source shipped inside Alpine's own
`linux-lts-dev` package, which is a strictly better provenance for this question — it is the source
Alpine 6.18.44-r0 was configured from. The upstream links are given for cross-checking.
