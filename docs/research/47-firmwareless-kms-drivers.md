# How much amd64 hardware has a KMS driver that works with no firmware?

Research findings for [aobs#47](https://github.com/allisson/aobs/issues/47). Map:
[aobs#1](https://github.com/allisson/aobs/issues/1). This sizes
[#40](https://github.com/allisson/aobs/issues/40)'s **option 2** — accept native-KMS-only and publish
a hardware list.

Pinned at **Linux `v6.12`** in the stable tree, and at Debian's **`linux` 6.12.101-1**, which is the
source package for `linux-image-6.12.101+deb13-amd64` — the exact kernel in the built ISO. Every
driver claim is read from the probe/init path at that tag, not from prose about it. Every Debian
claim is read from Debian's own `debian/config/` files at that version.

---

## Answer

**The floor is much higher than "a GPU Debian supports", and it is not evenly distributed: it is
generous on Intel and NVIDIA, and it excludes every AMD graphics device made since 2007.**

| Driver | Firmware-free KMS? | Where the line falls |
| --- | --- | --- |
| `i915` | **Yes, always** | Every generation i915 claims, i830 → Meteor/Arrow Lake. DMC, GuC and HuC are power management and GPU submission; none is on the modeset path. |
| `nouveau` | **Yes, up to Ampere** | NV04 → GA10x (RTX 30) modeset with no blob. Ada (RTX 40) does not bind at all. Blackwell is not in 6.12. |
| `radeon` | **Pre-R600 only** | R100–R500 (Radeon 7000 … X1000, ~2000–2006): microcode is acceleration-only. R600 (HD 2000, 2007) and everything newer refuse to initialise. |
| `amdgpu` | **No. No generation, no degraded mode.** | Microcode failure is remapped to `-ENODEV` *by design* so that init fails. |
| `xe` | **No** | GuC firmware is required to probe. Affects Lunar Lake and Battlemage, which `i915` does not claim. |
| `ast`, `mgag200`, `gma500`, `udl`, `hyperv` | **Yes** | No firmware at all; Debian builds all five on amd64. |
| `virtio-gpu`, `qxl`, `bochs`, `cirrus`, `vmwgfx` | **Yes** | No firmware. **Which is why a green CI row proves nothing about metal.** |

And the consequence #47 asked for last: **`AOBS-E02` on a readable `efifb` console is *not* uniformly
what the user gets.** Three drivers destroy the `efifb` console *before* the failure that dooms them
— `radeon` on R600+, `xe`, and `amdgpu` on SI — which produces exactly the silent blackness ADR-0009
was written to delete. See [§7](#7-what-the-user-actually-sees).

---

## 1. The premise, re-verified against Debian's own config

Debian's kernel does not build `simpledrm`, so the native driver is the requirement. #40 established
this from the built ISO; it is confirmed independently from Debian's source config, which is stronger
because it is the input rather than the output:

- `CONFIG_DRM_SIMPLEDRM` **appears nowhere** in `debian/config/config`,
  `debian/config/kernelarch-x86/config` or `debian/config/amd64/config`.
- `# CONFIG_SYSFB_SIMPLEFB is not set` — [`kernelarch-x86/config:544`][deb-x86].
- `CONFIG_FB_EFI=y`, `CONFIG_FB_VESA=y` — [`kernelarch-x86/config:1942-1943`][deb-x86].
- `CONFIG_EXTRA_FIRMWARE=""` — [`config:345`][deb-cfg]. No blob is linked into the kernel image
  either, so there is no back door by which a driver gets firmware without a `firmware-*` package.

What Debian *does* build as modules, all of it relevant here ([`config`][deb-cfg],
[`kernelarch-x86/config`][deb-x86]):

```
CONFIG_DRM_AMDGPU=m     CONFIG_DRM_AMDGPU_SI=y   CONFIG_DRM_AMDGPU_CIK=y
CONFIG_DRM_I915=m       CONFIG_DRM_XE=m
CONFIG_DRM_NOUVEAU=m    CONFIG_DRM_NOUVEAU_GSP_DEFAULT=y
CONFIG_DRM_RADEON=m
CONFIG_DRM_AST=m        CONFIG_DRM_MGAG200=m     CONFIG_DRM_GMA500=m
CONFIG_DRM_UDL=m        CONFIG_DRM_HYPERV=m
CONFIG_DRM_QXL=m        CONFIG_DRM_VIRTIO_GPU=m  CONFIG_DRM_BOCHS=m  CONFIG_DRM_CIRRUS_QEMU=m
```

No `CONFIG_DRM_I915_FORCE_PROBE` or `CONFIG_DRM_XE_FORCE_PROBE` is set in any of the three files, so
both Intel drivers use upstream's default platform gating.

**§3's module-deletion hook does not touch `drivers/gpu` — confirmed.**
[`image/config/hooks/normal/0200-aobs-no-network-modules.hook.chroot`](../../image/config/hooks/normal/0200-aobs-no-network-modules.hook.chroot)
deletes exactly three paths per `/lib/modules/*`:

```sh
"${modules_dir}/kernel/drivers/net"
"${modules_dir}/kernel/drivers/bluetooth"
"${modules_dir}/kernel/net"
```

and nothing else. No GPU driver is removed by the image build. And no firmware is installed:
`image/config/package-lists/aobs.list.chroot` requests six libraries plus `seatd`, and names
`firmware-*` in its *deliberately absent* list. (The `bitcoin-signer-amd64.packages` manifest is a
build artifact and is gitignored — `.gitignore:26`, `:59` — so the package list is the checked-in
authority.)

### One correction to #40

#40 says "`drivers/gpu/drm/tiny/` is absent from the modules tree entirely". Debian's config sets
`CONFIG_DRM_BOCHS=m` and `CONFIG_DRM_CIRRUS_QEMU=m`, both under the heading
`## file: drivers/gpu/drm/tiny/Kconfig` ([`config:836-840`][deb-cfg]), and both build from
[`drivers/gpu/drm/tiny/Makefile`][k-tiny-mk]. So `kernel/drivers/gpu/drm/tiny/` should exist and
contain `bochs.ko` and `cirrus.ko` — just not `simpledrm.ko`. #40's *load-bearing* claim (no
`simpledrm.ko`) is confirmed; the broader claim about the directory looks wrong and is worth a
re-check against the built artifact. I could not verify the ISO's module tree from here.

## 2. `amdgpu` — never, by design

There is no firmware-less amdgpu generation and no degraded modeset mode. The driver says so in a
comment:

> *"This is a helper that will use request_firmware and amdgpu_ucode_validate to load and run basic
> validation on firmware. **If the load fails, remap the error code to `-ENODEV`, so that early_init
> functions will fail to load.**"* — [`amdgpu_ucode.c`, `amdgpu_ucode_request()`][k-amdgpu-ucode]

Three call sites make that fatal rather than cosmetic, each in a *different* IP block, so no single
generation escapes:

- **Display itself needs a blob on DCN 2.1 and later.** `dm_early_init()` ends with
  `return dm_init_microcode(adev)`, and `dm_init_microcode()` does
  `amdgpu_ucode_request(adev, &adev->dm.dmub_fw, "%s", fw_name_dmub)` for every DCN from 2.1
  (Renoir) to 4.0.1 — [`amdgpu_dm.c`][k-amdgpu-dm]. This is not acceleration: it is the display
  microcontroller.
- **Graphics microcode is loaded during `early_init` on gfx9 and gfx11.** `gfx_v9_0_early_init()`
  ends `return gfx_v9_0_init_microcode(adev)` ([`gfx_v9_0.c`][k-gfx9]);
  `gfx_v11_0_early_init()` likewise ([`gfx_v11_0.c`][k-gfx11]).
- **On SI it is loaded in `sw_init`** — `gfx_v6_0_init_microcode()` is called from
  `gfx_v6_0_sw_init()` ([`gfx_v6_0.c`][k-gfx6]). Same outcome, different timing, and the timing is
  what decides whether the user gets a message (§7).

Both arms are fatal to probe. `amdgpu_device_init()` returns immediately if
`amdgpu_device_ip_early_init()` fails, and jumps to the failure path if `amdgpu_device_ip_init()`
fails with `"amdgpu_device_ip_init failed"` ([`amdgpu_device.c`][k-amdgpu-dev]); `amdgpu_pci_probe()`
propagates that out of `amdgpu_driver_load_kms()` ([`amdgpu_drv.c`][k-amdgpu-drv]).

For scale: `linux-firmware`'s `WHENCE` lists **677** files under `amdgpu/`, all covered by
*"Licence: Redistributable. See LICENSE.amdgpu for details."* ([`WHENCE`][lf-whence]) — the blobs
Debian ships in `firmware-amd-graphics`, which §3 declines to install.

**SI and CIK go to `radeon`, not `amdgpu`, on Debian.** `amdgpu_si_support` and `amdgpu_cik_support`
default to `0` whenever `CONFIG_DRM_RADEON` is enabled ([`amdgpu_drv.c`][k-amdgpu-drv]), and Debian
enables it. So the amdgpu-SI path above is reachable only with an explicit
`amdgpu.si_support=1`, and the practical answer for those cards is §4's.

## 3. `i915` — firmware never blocks modeset, on any generation

This is the good case, and it is good on purpose.

**DMC (gen9+) is power management only.** `intel_dmc_init()` returns `void`, queues the load onto a
work item, and the failure path is a notice:

> `"Failed to load DMC firmware %s (%pe). Disabling runtime power management."`
> — [`intel_dmc.c`, `dmc_load_work_fn()`][k-dmc]

No error is returned to anything. There is no generation where DMC is a modeset prerequisite.

**GuC/HuC failure wedges the GPU and keeps the display.** Firmware fetch is `void`
(`__uc_fetch_firmwares`, `intel_huc_init`, `intel_gsc_uc_init` all return nothing usable), and when
GuC load fails, `__uc_init_hw()` ends:

```c
	gt_probe_error(gt, "GuC initialization failed %pe\n", ERR_PTR(ret));

	/* We want to keep KMS alive */
	return -EIO;
```

— [`intel_uc.c`][k-uc]. `i915_gem_init()` then catches exactly that code:

```c
	if (ret == -EIO) {
		/*
		 * Allow engines or uC initialisation to fail by marking the GPU
		 * as wedged. ...
		 */
		...
		/* Minimal basic recovery for KMS */
		ret = i915_ggtt_enable_hw(dev_priv);
		i915_ggtt_resume(to_gt(dev_priv)->ggtt);
		intel_clock_gating_init(dev_priv);
	}
```

— [`i915_gem.c`][k-i915-gem]. The GGTT is deliberately re-enabled so that display can still scan
out. GuC submission is the default only from gen12 excluding Tiger Lake, Rocket Lake and
non-Raptor Alder Lake-S (`uc_expand_default_options()`, [`intel_uc.c`][k-uc]), so on gen11 and
earlier nothing is even attempted.

`i915` supplies `.dumb_create = i915_gem_dumb_create` ([`i915_driver.c`][k-i915-drv]), which is what
`backend-linuxkms` + `renderer-software` needs.

**Coverage:** `mtl_info` carries no `.require_force_probe` ([`i915_pci.c`][k-i915-pci]), and
`INTEL_MTL_IDS` expands to include `INTEL_ARL_IDS` ([`i915_pciids.h`][k-pciids]), so i915 claims
everything through Meteor Lake **and Arrow Lake** by default.

## 4. `radeon` — pre-R600 works, R600 and later do not

The pattern differs by ASIC family, and the difference is worth reading rather than assuming.

**R100–R500: microcode is acceleration-only.** `r100_cp_init()` calls
`r100_cp_init_microcode()` and returns its error, but the caller wraps it:

```c
	rdev->accel_working = true;
	r = r100_startup(rdev);
	if (r) {
		/* Somethings want wront with the accel init stop accel */
		dev_err(rdev->dev, "Disabling GPU acceleration\n");
		...
		rdev->accel_working = false;
	}
	return 0;
```

— [`r100.c`][k-r100]. **It returns 0.** The device binds, modesets, and simply has no acceleration —
which is exactly what a software renderer on dumb buffers wants.

**R600 and later: the microcode load is checked before that wrapper and returns hard.** Every family
does the same thing:

| Family | Site | Behaviour |
| --- | --- | --- |
| R600 (HD 2000/3000) | [`r600.c:3299`][k-r600] | `DRM_ERROR("Failed to load firmware!"); return r;` |
| RV770 (HD 4000) | [`rv770.c:1955`][k-rv770] | same |
| Evergreen (HD 5000) | [`evergreen.c:5233`][k-evergreen] | same |
| Northern Islands (HD 6000/7000) | [`ni.c:2376`][k-ni] | same, plus `"radeon: MC ucode required for NI+."` → `-EINVAL` |
| Southern Islands (HD 7000/R9) | [`si.c:6856`][k-si] | same |
| Sea Islands (R7/R9, Kaveri) | [`cik.c:8599`][k-cik] | same |

Evergreen carries the rule twice — the second time as a refusal to run at all: *"Don't start up if
the MC ucode is missing on BTC parts. The default clocks and voltages before the MC ucode is loaded
are not suffient for advanced operations."* ([`evergreen.c`][k-evergreen]).

`radeon` supplies `.dumb_create = radeon_mode_dumb_create` ([`radeon_drv.c`][k-radeon-drv]).
`WHENCE` lists 247 files under `radeon/`.

## 5. `nouveau` — firmware-free through Ampere; Ada does not bind

nouveau is built to degrade, and the mechanism is a per-subdevice firmware-variant table with a
fallback entry.

**The selector.** `nvkm_firmware_load()` walks a `fwif` list, calling each entry's `load` until one
returns 0 ([`core/firmware.h`][k-nvkm-fwh]). A trailing `{ -1, …_nofw, … }` entry is the graceful
arm. **A subdevice constructor that returns anything other than `-ENODEV` is fatal to the whole
device**, per the `NVKM_LAYOUT_ONCE`/`NVKM_LAYOUT_INST` macros in
[`nvkm/engine/device/base.c`][k-nvkm-dev]:

```c
		if (ret) {
			nvkm_subdev_del(&subdev);
			device->ptr = NULL;
			if (ret != -ENODEV) {
				nvdev_error(device, "%s ctor failed: %d\n", ...);
				goto done;
			}
		}
```

**Every firmware-hungry subdevice except one has that fallback:**

| Subdevice | Fallback entry | File |
| --- | --- | --- |
| `acr` GM20x/GP100 | `{ -1, gm200_acr_nofw, &gm200_acr }` | [`acr/gm200.c`][k-acr-gm200] |
| `acr` GP10x | `{ -1, gm200_acr_nofw, &gm200_acr }` | [`acr/gp102.c`][k-acr-gp102] |
| `acr` GV100 / TU10x / GA10x | same | [`gv100.c`][k-acr-gv100], [`tu102.c`][k-acr-tu102], [`ga102.c`][k-acr-ga102] |
| `gr` GM20x → GA10x | `{ -1, gm200_gr_nofw }`, which logs `"firmware unavailable"` and returns **`-ENODEV`** | [`gr/gm200.c`][k-gr-gm200], [`gp100.c`][k-gr-gp100], [`tu102.c`][k-gr-tu102], [`ga102.c`][k-gr-ga102] |
| `gsp` Turing | `{ -1, gv100_gsp_nofw, &gv100_gsp }` | [`gsp/tu102.c`][k-gsp-tu102] |
| `gsp` Ampere GA10x | `{ -1, gv100_gsp_nofw, &ga102_gsp }` | [`gsp/ga102.c`][k-gsp-ga102] |
| **`gsp` Ada AD10x** | **none — `ad102_gsps[] = { { 0, r535_gsp_load, … }, {} }`** | [`gsp/ad102.c`][k-gsp-ad102] |

So on Turing and Ampere, a missing GSP blob makes `r535_gsp_load()` return `-ENOENT`
([`gsp/r535.c`][k-gsp-r535]), the loop advances to the `nofw` entry, and the display engine takes
nouveau's own native path:

```c
int
ga102_disp_new(...)
{
	if (nvkm_gsp_rm(device->gsp))
		return r535_disp_new(&ga102_disp, device, type, inst, pdisp);

	return nvkm_disp_new_(&ga102_disp, device, type, inst, pdisp);
}
```

— [`disp/ga102.c`][k-disp-ga102]; `tu102_disp_new()` is identical
([`disp/tu102.c`][k-disp-tu102]). Debian's `CONFIG_DRM_NOUVEAU_GSP_DEFAULT=y` only changes which
entry is *tried first*; it does not remove the fallback.

**Ada is different in both places.** There is no `nofw` entry, so `nvkm_gsp_new_()` propagates
`-ENOENT`, which is not `-ENODEV`, which kills `nvkm_device_ctor()`. And even if it did not,
[`disp/ad102.c`][k-disp-ad102] says:

```c
int
ad102_disp_new(...)
{
	if (nvkm_gsp_rm(device->gsp))
		return r535_disp_new(&ad102_disp, device, type, inst, pdisp);

	return -ENODEV;
}
```

The newest chipsets in 6.12's table are `AD102`–`AD107` ([`device/base.c`][k-nvkm-dev]); Blackwell
(RTX 50) is not present at all, so those cards have no nouveau support to discuss.

`nouveau` supplies `.dumb_create = nouveau_display_dumb_create` ([`nouveau_drm.c`][k-nouveau-drv]).

## 6. The virtual drivers, and why CI cannot answer this question

`virtio-gpu`, `qxl`, `bochs`, `cirrus`, `vmwgfx` and `hyperv_drm` contain **no firmware request at
all** — no `request_firmware`, no `MODULE_FIRMWARE`, and `linux-firmware`'s `WHENCE` has no
`Driver:` block for any of them. All declare `DRIVER_MODESET | DRIVER_GEM` and provide dumb buffers:
`virtio_gpu_mode_dumb_create` ([`virtgpu_drv.c`][k-virtio]), `qxl_mode_dumb_create`
([`qxl_drv.c`][k-qxl]), `vmw_dumb_create` ([`vmwgfx_drv.c`][k-vmwgfx]), and `DRM_GEM_VRAM_DRIVER`
for bochs ([`tiny/bochs.c`][k-bochs]).

**So every VM target passes this test unconditionally, which is precisely why
`05-testing-and-release.md` §6.2's QEMU rows cannot stand in for the hardware question.** A CI matrix
that is green on `virtio-gpu` tells you the app works; it tells you nothing about whether the
machine in front of the user has a display.

The same "no firmware, has dumb buffers" property holds for four *physical* drivers Debian builds,
which widen the compatibility list usefully:

| Driver | Hardware | Evidence |
| --- | --- | --- |
| `ast` | ASPEED AST2xxx/AST25xx BMC display — most server motherboards | `DRM_GEM_SHMEM_DRIVER_OPS`, [`ast_drv.c`][k-ast] |
| `mgag200` | Matrox G200 / G200e server display | `DRM_GEM_SHMEM_DRIVER_OPS`, [`mgag200_drv.c`][k-mgag200] |
| `udl` | DisplayLink USB display adapters | `DRM_GEM_SHMEM_DRIVER_OPS`, [`udl_drv.c`][k-udl] |
| `gma500` | Poulsbo / Cedarview Atom netbooks | `psb_gem_dumb_create`, [`psb_drv.c`][k-gma500] |

`gma500` declares `DRIVER_MODESET | DRIVER_GEM` **without** `DRIVER_ATOMIC`, so it is legacy
modesetting. Whether `backend-linuxkms` accepts a non-atomic device is a Slint question, not a
kernel one, and I did not check it.

## 7. What the user actually sees

#40 established that a machine with no DRM device prints the §9 diagnostic on the `efifb` console
and halts — verified against the built ISO. **That behaviour survives only where the driver never
takes the framebuffer away.** It is not universal, because of one hard rule in the aperture helpers:

`efifb` owns its aperture via `devm_aperture_acquire_for_platform_device()`
([`efifb.c:571`][k-efifb]). When a DRM driver calls
`drm_aperture_remove_conflicting_pci_framebuffers()`, the helper calls `sysfb_disable(NULL)` — *"let's
assume that a real driver for the display was already probed and prevent sysfb to register devices
later"* — and then `platform_device_unregister()` on the firmware fb, because *"After the new driver
takes over the hardware, the firmware device's state will be lost"* ([`aperture.c`][k-aperture]).
nouveau states the consequence outright:

> *"We need to check that the chipset is supported before booting fbdev off the hardware, **as
> there's no way to put it back**."* — [`nouveau_drm.c`][k-nouveau-drv]

So the question per driver is: does the firmware-missing failure happen *before* or *after* that
call?

| Situation | Aperture call vs. failure | Result |
| --- | --- | --- |
| No driver claims the PCI ID (Ada, Blackwell, any unknown GPU) | never removed | **`AOBS-E02` readable.** The good failure. |
| `nouveau` on Ada | `nvkm_device_pci_new()` fails **before** the removal — the removal is the next statement ([`nouveau_drm.c`][k-nouveau-drv]) | **`AOBS-E02` readable.** |
| `amdgpu` on gfx9/gfx11/DCN2.1+ | firmware loads in `early_init`, which precedes `drm_aperture_remove_conflicting_pci_framebuffers()` in `amdgpu_device_init()` ([`amdgpu_device.c`][k-amdgpu-dev]) | **`AOBS-E02` readable.** |
| `i915` | never fails on firmware at all | display works |
| **`radeon` on R600+** | removal is at `radeon_pci_probe()` **before** `radeon_driver_load_kms()` ([`radeon_drv.c`][k-radeon-drv]); the microcode failure is inside the latter | **console destroyed, then probe fails. Blackness.** |
| **`xe` (Lunar Lake, Battlemage)** | removal is in `xe_device_create()` ([`xe_device.c:304`][k-xe-dev]); GuC fetch fails later in `xe_uc_init()` ([`xe_uc.c`][k-xe-uc], [`xe_uc_fw.c`][k-xe-ucfw]) | **console destroyed, then probe fails. Blackness.** |
| `amdgpu` on SI with `amdgpu.si_support=1` | microcode in `sw_init`, after the removal | **blackness** (non-default; see §2) |

**This is a real weakening of #40's mitigation, not a footnote.** #40 reports that "a user with no
supported GPU sees a written explanation and a failure code, not blackness". That is true for the
*unsupported* GPU. It is false for the *firmware-hungry* one on `radeon` R600+ and on `xe` — and
those are common machines, not corner cases.

`xe` also has an untested escape hatch worth recording: `xe_device_uc_enabled()` is
`!xe->info.force_execlist`, fed from the `xe.force_execlist` module parameter
([`xe_device.h`][k-xe-devh], [`xe_device.c:324`][k-xe-dev]), and `uc_fw_init()` returns 0 with status
`DISABLED` when uc is off rather than requesting a file ([`xe_uc_fw.c`][k-xe-ucfw]). Whether Lunar
Lake then modesets is **not verified** and should not be assumed; it is a lead for a later ticket,
not a fix.

`xe` platform coverage matters for how much hardware this touches: in 6.12 every `xe` platform
except Lunar Lake and Battlemage carries `.require_force_probe = true`
([`xe_pci.c`][k-xe-pci]), and `i915` claims those IDs instead. So `xe` is the only driver for LNL and
BMG, and the only driver for nothing else.

## 8. The compatibility statement, publishable as written

> **aobs needs a KMS/DRM device that initialises with no firmware blob, because the image ships
> none.** On Debian 13's 6.12 kernel, that is satisfied by:
>
> - **Intel integrated graphics, every generation** — i830 through Meteor Lake and Arrow Lake
>   (`i915`). Firmware on Intel affects power saving and GPU submission, never the display.
> - **NVIDIA up to and including Ampere** — GeForce RTX 30, GTX 16, GTX 10, 900, 700, 600 and older
>   (`nouveau`).
> - **AMD/ATI Radeon up to the X1000 series** (pre-R600, roughly 2000–2006) (`radeon`).
> - **Server board display controllers** — ASPEED AST and Matrox G200 (`ast`, `mgag200`), which is
>   how most rack hardware draws a screen.
> - **Atom netbooks** with Poulsbo/Cedarview graphics (`gma500`), subject to a legacy-modeset caveat.
> - **Virtual machines** — virtio-gpu, QXL, Bochs/stdvga, Cirrus, VMware, Hyper-V.
>
> It is **not** satisfied by:
>
> - **Every AMD GPU and APU from Radeon HD 2000 (2007) onward**, on either `radeon` or `amdgpu`.
> - **NVIDIA Ada (RTX 40) and Blackwell (RTX 50)**.
> - **Intel Lunar Lake, Battlemage and newer** (`xe`).

**The honest sentence about what this excludes:** every AMD graphics device made in the last eighteen
years is excluded — which means a current AMD laptop or desktop, and any Ryzen APU machine, cannot
display this appliance at all, and on those machines it will fail with a black screen rather than
with the failure code, because `radeon` and `amdgpu` take the firmware console away before they
discover they cannot continue.

## 9. What I could not verify

Stated plainly, because the report is worth less if these look settled:

1. **Nothing here was run on hardware.** Every claim is a reading of the 6.12 probe path. The i915
   "wedged GT still modesets" claim in particular is the kernel's *stated intent* (two comments and a
   deliberate GGTT re-enable); it is not a measurement, and on discrete Intel (DG2) where dumb
   buffers live in LMEM I did not trace whether allocation needs the migration engine that the wedge
   disables.
2. **Debian's config merge order.** `debian/config/config` has
   `# CONFIG_DRM_VMWGFX is not set` while `debian/config/kernelarch-x86/config` has
   `CONFIG_DRM_VMWGFX=m`. I assumed the arch-specific file wins on amd64 but did not verify Debian's
   merge rule, and did not check the built ISO's `/boot/config-*`. Only `vmwgfx` is affected; every
   other driver above appears once or agrees with itself.
3. **#40's `drivers/gpu/drm/tiny/` claim** (§1). Debian's config says `bochs.ko` and `cirrus.ko`
   should be there. I could not inspect the ISO.
4. **amdgpu per-ASIC console survival.** I traced `gfx_v9_0`, `gfx_v11_0`, `gfx_v6_0` and the DM/DMUB
   path. I did not trace `gfx_v7`, `gfx_v8`, `gfx_v10`, `gfx_v12`, `sdma_*`, `psp_v*` or `smu_*`, so
   the §7 row for amdgpu is right for the generations I read and plausible — not proven — for the
   rest.
5. **Whether `backend-linuxkms` requires `DRIVER_ATOMIC`.** Relevant only to `gma500`, and it is a
   Slint question this ticket did not cover.
6. **The `xe.force_execlist` escape hatch** (§7) is read from source and completely untested.
7. **`virtio-gpu`/`qxl`/`vmwgfx`/`bochs` firmware-freedom** was checked in each driver's main file
   plus `WHENCE`, not by grepping every file in each driver directory.

---

## Sources

Kernel sources are the `v6.12` tag of the stable tree. Debian config is `linux` 6.12.101-1.

| Claim | Source |
| --- | --- |
| Debian builds/omits which DRM drivers; `CONFIG_EXTRA_FIRMWARE=""`; no `SIMPLEDRM` | [`debian/config/config`][deb-cfg], [`debian/config/kernelarch-x86/config`][deb-x86] |
| `linux-image-6.12.101+deb13-amd64` comes from source 6.12.101-1 | [packages.debian.org/trixie/linux-image-amd64](https://packages.debian.org/trixie/linux-image-amd64) |
| amdgpu remaps firmware failure to `-ENODEV` so init fails | [`amdgpu/amdgpu_ucode.c`][k-amdgpu-ucode] |
| amdgpu DMUB blob requested from `dm_early_init` | [`amd/display/amdgpu_dm/amdgpu_dm.c`][k-amdgpu-dm] |
| amdgpu gfx microcode in `early_init` (gfx9, gfx11), `sw_init` (gfx6) | [`gfx_v9_0.c`][k-gfx9], [`gfx_v11_0.c`][k-gfx11], [`gfx_v6_0.c`][k-gfx6] |
| amdgpu init/aperture ordering | [`amdgpu/amdgpu_device.c`][k-amdgpu-dev], [`amdgpu/amdgpu_drv.c`][k-amdgpu-drv] |
| DMC failure disables runtime PM only | [`i915/display/intel_dmc.c`][k-dmc] |
| GuC failure → `-EIO`, "We want to keep KMS alive"; GuC default per platform | [`i915/gt/uc/intel_uc.c`][k-uc] |
| `-EIO` → wedged, "Minimal basic recovery for KMS" | [`i915/i915_gem.c`][k-i915-gem] |
| i915 aperture removal site; `dumb_create` | [`i915/i915_driver.c`][k-i915-drv] |
| i915 claims MTL by default; `INTEL_MTL_IDS` includes ARL | [`i915/i915_pci.c`][k-i915-pci], [`include/drm/intel/i915_pciids.h`][k-pciids] |
| xe: aperture removal in `xe_device_create`; `force_execlist` | [`xe/xe_device.c`][k-xe-dev], [`xe/xe_device.h`][k-xe-devh] |
| xe: GuC fetch failure propagates out of probe | [`xe/xe_uc.c`][k-xe-uc], [`xe/xe_uc_fw.c`][k-xe-ucfw] |
| xe: only LNL and BMG probe without `force_probe` | [`xe/xe_pci.c`][k-xe-pci] |
| nouveau fwif selector; non-`-ENODEV` ctor error is fatal | [`nouveau/include/nvkm/core/firmware.h`][k-nvkm-fwh], [`nvkm/engine/device/base.c`][k-nvkm-dev] |
| nouveau acr/gr `nofw` fallbacks | [`acr/gm200.c`][k-acr-gm200], [`acr/gp102.c`][k-acr-gp102], [`acr/gv100.c`][k-acr-gv100], [`acr/tu102.c`][k-acr-tu102], [`acr/ga102.c`][k-acr-ga102], [`gr/gm200.c`][k-gr-gm200], [`gr/gp100.c`][k-gr-gp100], [`gr/tu102.c`][k-gr-tu102], [`gr/ga102.c`][k-gr-ga102] |
| GSP fallback on Turing/Ampere, none on Ada | [`gsp/tu102.c`][k-gsp-tu102], [`gsp/ga102.c`][k-gsp-ga102], [`gsp/ad102.c`][k-gsp-ad102], [`gsp/r535.c`][k-gsp-r535] |
| Native disp path without GSP; Ada returns `-ENODEV` | [`disp/tu102.c`][k-disp-tu102], [`disp/ga102.c`][k-disp-ga102], [`disp/ad102.c`][k-disp-ad102] |
| nouveau probe order comment; `dumb_create` | [`nouveau/nouveau_drm.c`][k-nouveau-drv] |
| radeon pre-R600 swallows microcode failure | [`radeon/r100.c`][k-r100] |
| radeon R600+ returns hard | [`r600.c`][k-r600], [`rv770.c`][k-rv770], [`evergreen.c`][k-evergreen], [`ni.c`][k-ni], [`si.c`][k-si], [`cik.c`][k-cik] |
| radeon aperture removal precedes `load_kms`; `dumb_create` | [`radeon/radeon_drv.c`][k-radeon-drv] |
| Aperture removal unregisters the firmware fb and disables sysfb | [`drivers/video/aperture.c`][k-aperture], [`include/drm/drm_aperture.h`][k-drm-aperture] |
| `efifb` acquires the aperture as a platform device | [`drivers/video/fbdev/efifb.c`][k-efifb] |
| Virtual drivers: modeset + dumb, no firmware | [`virtio/virtgpu_drv.c`][k-virtio], [`qxl/qxl_drv.c`][k-qxl], [`vmwgfx/vmwgfx_drv.c`][k-vmwgfx], [`tiny/bochs.c`][k-bochs], [`tiny/Makefile`][k-tiny-mk] |
| Firmware-free physical drivers Debian builds | [`ast/ast_drv.c`][k-ast], [`mgag200/mgag200_drv.c`][k-mgag200], [`udl/udl_drv.c`][k-udl], [`gma500/psb_drv.c`][k-gma500] |
| amdgpu/radeon/nvidia blob counts and licence | [`linux-firmware/WHENCE`][lf-whence] |

[deb-cfg]: https://sources.debian.org/src/linux/6.12.101-1/debian/config/config/
[deb-x86]: https://sources.debian.org/src/linux/6.12.101-1/debian/config/kernelarch-x86/config/
[k-amdgpu-ucode]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/gpu/drm/amd/amdgpu/amdgpu_ucode.c?h=v6.12
[k-amdgpu-dm]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/gpu/drm/amd/display/amdgpu_dm/amdgpu_dm.c?h=v6.12
[k-amdgpu-dev]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/gpu/drm/amd/amdgpu/amdgpu_device.c?h=v6.12
[k-amdgpu-drv]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/gpu/drm/amd/amdgpu/amdgpu_drv.c?h=v6.12
[k-gfx9]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/gpu/drm/amd/amdgpu/gfx_v9_0.c?h=v6.12
[k-gfx11]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/gpu/drm/amd/amdgpu/gfx_v11_0.c?h=v6.12
[k-gfx6]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/gpu/drm/amd/amdgpu/gfx_v6_0.c?h=v6.12
[k-dmc]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/gpu/drm/i915/display/intel_dmc.c?h=v6.12
[k-uc]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/gpu/drm/i915/gt/uc/intel_uc.c?h=v6.12
[k-i915-gem]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/gpu/drm/i915/i915_gem.c?h=v6.12
[k-i915-drv]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/gpu/drm/i915/i915_driver.c?h=v6.12
[k-i915-pci]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/gpu/drm/i915/i915_pci.c?h=v6.12
[k-pciids]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/include/drm/intel/i915_pciids.h?h=v6.12
[k-xe-dev]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/gpu/drm/xe/xe_device.c?h=v6.12
[k-xe-devh]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/gpu/drm/xe/xe_device.h?h=v6.12
[k-xe-uc]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/gpu/drm/xe/xe_uc.c?h=v6.12
[k-xe-ucfw]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/gpu/drm/xe/xe_uc_fw.c?h=v6.12
[k-xe-pci]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/gpu/drm/xe/xe_pci.c?h=v6.12
[k-nvkm-fwh]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/gpu/drm/nouveau/include/nvkm/core/firmware.h?h=v6.12
[k-nvkm-dev]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/gpu/drm/nouveau/nvkm/engine/device/base.c?h=v6.12
[k-acr-gm200]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/gpu/drm/nouveau/nvkm/subdev/acr/gm200.c?h=v6.12
[k-acr-gp102]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/gpu/drm/nouveau/nvkm/subdev/acr/gp102.c?h=v6.12
[k-acr-gv100]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/gpu/drm/nouveau/nvkm/subdev/acr/gv100.c?h=v6.12
[k-acr-tu102]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/gpu/drm/nouveau/nvkm/subdev/acr/tu102.c?h=v6.12
[k-acr-ga102]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/gpu/drm/nouveau/nvkm/subdev/acr/ga102.c?h=v6.12
[k-gr-gm200]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/gpu/drm/nouveau/nvkm/engine/gr/gm200.c?h=v6.12
[k-gr-gp100]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/gpu/drm/nouveau/nvkm/engine/gr/gp100.c?h=v6.12
[k-gr-tu102]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/gpu/drm/nouveau/nvkm/engine/gr/tu102.c?h=v6.12
[k-gr-ga102]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/gpu/drm/nouveau/nvkm/engine/gr/ga102.c?h=v6.12
[k-gsp-tu102]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/gpu/drm/nouveau/nvkm/subdev/gsp/tu102.c?h=v6.12
[k-gsp-ga102]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/gpu/drm/nouveau/nvkm/subdev/gsp/ga102.c?h=v6.12
[k-gsp-ad102]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/gpu/drm/nouveau/nvkm/subdev/gsp/ad102.c?h=v6.12
[k-gsp-r535]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/gpu/drm/nouveau/nvkm/subdev/gsp/r535.c?h=v6.12
[k-disp-tu102]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/gpu/drm/nouveau/nvkm/engine/disp/tu102.c?h=v6.12
[k-disp-ga102]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/gpu/drm/nouveau/nvkm/engine/disp/ga102.c?h=v6.12
[k-disp-ad102]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/gpu/drm/nouveau/nvkm/engine/disp/ad102.c?h=v6.12
[k-nouveau-drv]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/gpu/drm/nouveau/nouveau_drm.c?h=v6.12
[k-r100]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/gpu/drm/radeon/r100.c?h=v6.12
[k-r600]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/gpu/drm/radeon/r600.c?h=v6.12
[k-rv770]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/gpu/drm/radeon/rv770.c?h=v6.12
[k-evergreen]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/gpu/drm/radeon/evergreen.c?h=v6.12
[k-ni]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/gpu/drm/radeon/ni.c?h=v6.12
[k-si]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/gpu/drm/radeon/si.c?h=v6.12
[k-cik]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/gpu/drm/radeon/cik.c?h=v6.12
[k-radeon-drv]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/gpu/drm/radeon/radeon_drv.c?h=v6.12
[k-aperture]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/video/aperture.c?h=v6.12
[k-drm-aperture]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/include/drm/drm_aperture.h?h=v6.12
[k-efifb]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/video/fbdev/efifb.c?h=v6.12
[k-virtio]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/gpu/drm/virtio/virtgpu_drv.c?h=v6.12
[k-qxl]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/gpu/drm/qxl/qxl_drv.c?h=v6.12
[k-vmwgfx]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/gpu/drm/vmwgfx/vmwgfx_drv.c?h=v6.12
[k-bochs]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/gpu/drm/tiny/bochs.c?h=v6.12
[k-tiny-mk]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/gpu/drm/tiny/Makefile?h=v6.12
[k-ast]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/gpu/drm/ast/ast_drv.c?h=v6.12
[k-mgag200]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/gpu/drm/mgag200/mgag200_drv.c?h=v6.12
[k-udl]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/gpu/drm/udl/udl_drv.c?h=v6.12
[k-gma500]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/gpu/drm/gma500/psb_drv.c?h=v6.12
[lf-whence]: https://git.kernel.org/pub/scm/linux/kernel/git/firmware/linux-firmware.git/tree/WHENCE
