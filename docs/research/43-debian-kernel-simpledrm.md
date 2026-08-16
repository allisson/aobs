# Does any Debian 13 kernel package already ship `simpledrm`?

Research findings for [aobs#43](https://github.com/allisson/aobs/issues/43), the cheapest candidate
exit from [#40](https://github.com/allisson/aobs/issues/40). Map: [aobs#1](https://github.com/allisson/aobs/issues/1).

Every value below is read from a Debian source of record: the kernel team's config tree on
salsa, the `.config` **inside the built binary packages** on `deb.debian.org`, the Debian bug
tracker, `packages.debian.org`'s contents index, and upstream Kconfig/source at `git.kernel.org`.
Nothing here is read from a running system, and nothing is inferred from a config file's silence —
the built `.config` was fetched for every flavour claimed about.

Versions pinned, all fetched 2026-08-15:

| Suite | `linux` version | Why it is here |
| --- | --- | --- |
| trixie (stable) | `6.12.94-1` | what the ISO installs today |
| trixie-proposed-updates | `6.12.101-1` | the exact kernel #40 built and booted (`6.12.101+deb13-amd64`) |
| trixie-backports | `7.1.7-1~bpo13+1` | current backport; also spot-checked `6.16.3-1~bpo13+1`, the first one |
| sid (unstable) | `7.1.8-1` | predicts where trixie-backports goes next |

---

## Answer

**No. No Debian kernel package on any suite enables either symbol, and no package in Debian
contains `simpledrm.ko` at all.** `CONFIG_SYSFB_SIMPLEFB` is explicitly disabled on x86 with an
in-tree comment citing a 2016 bug, and `CONFIG_DRM_SIMPLEDRM` is simply never turned on — not `=y`,
not `=m`, on no amd64 flavour, no backport, no other architecture. Option 4 of #40 is closed: **there
is no package to switch to.**

Two things soften and sharpen that at once:

- The recorded reason for the disable **has expired**, and Debian knows it. The config comment says
  *"Doesn't support handover; see #822575"* — a 2016 decision taken on upstream advice that
  explicitly said *"once the SimpleDRM driver is upstream, there will be infrastructure to do the hw
  handover"*. SimpleDRM landed in Linux 5.14. See [§3](#3-the-position-is-recorded-and-its-stated-reason-has-expired).
- Debian is **actively moving toward enabling it**, but for *forky*, not trixie. Merge request
  [!1453](https://salsa.debian.org/kernel-team/linux/-/merge_requests/1453) is open against
  `7.2~rc6-1~exp1`, and the Debian kernel maintainer himself posted the RFC for it in May 2026. That
  is aobs's v2 exit, not its v1 exit. See [§4](#4-what-is-in-flight-and-which-release-it-lands-in).

The 6.18-era successors do not rescue it either: `CONFIG_DRM_EFIDRM` and `CONFIG_DRM_VESADRM`, which
bind the `efi-framebuffer` device directly and would not need `SYSFB_SIMPLEFB` at all, are **also
unset** in both trixie-backports 7.1.7 and sid 7.1.8 ([§2](#2-the-built-configs-flavour-by-flavour)).

---

## 1. There are exactly three amd64 flavours, and they share one config file

`debian/config/amd64/defines.toml` on the trixie branch declares two flavours — `amd64` and
`cloud-amd64` — plus a `rt` featureset restricted to the `amd64` flavour, which is the third binary
image, `rt-amd64`. ([defines.toml](https://salsa.debian.org/kernel-team/linux/-/blob/debian/6.12/trixie/debian/config/amd64/defines.toml))
All three are signed: each appears in the `linux-signed-amd64` pool.
([pool listing](https://deb.debian.org/debian/pool/main/l/linux-signed-amd64/))

There is **no i386 kernel flavour in trixie** — `debian/config/` has no `i386` directory on that
branch, so `debian/config/kernelarch-x86/config` is amd64's file alone.
([config tree](https://salsa.debian.org/kernel-team/linux/-/tree/debian/6.12/trixie/debian/config))

That file carries the decision, with its reason attached:

```
##
## file: drivers/firmware/Kconfig
##
...
#. Doesn't support handover; see #822575
# CONFIG_SYSFB_SIMPLEFB is not set
```

([`kernelarch-x86/config` L543-544](https://salsa.debian.org/kernel-team/linux/-/blob/debian/6.12/trixie/debian/config/kernelarch-x86/config#L543))

`CONFIG_DRM_SIMPLEDRM` appears **nowhere** in `debian/config/` on any branch checked
(`debian/6.12/trixie`, `debian/6.12/trixie-security`, `debian/7.1/trixie-backports`,
`debian/latest`). Upstream gives it no `default`, so absence means `n` — and the built configs in §2
confirm that rather than assuming it.

`featureset-rt/config` touches only `SCHED_AUTOGROUP`, the preemption choice, `RCU_EXPERT` and four
tracers. It changes nothing about display.
([featureset-rt/config](https://salsa.debian.org/kernel-team/linux/-/blob/debian/6.12/trixie/debian/config/featureset-rt/config))

## 2. The built configs, flavour by flavour

Read out of `usr/src/linux-headers-*/.config` inside each `linux-headers` binary package, and — for
the flavour aobs actually ships — out of `boot/config-*` inside the **signed** `linux-image` package.

| Package (all from [`pool/main/l/linux`](https://deb.debian.org/debian/pool/main/l/linux/)) | `SYSFB_SIMPLEFB` | `DRM_SIMPLEDRM` | `DRM` |
| --- | --- | --- | --- |
| `linux-image-6.12.94+deb13-amd64` (signed, trixie) | not set | **not set** | `m` |
| `linux-headers-6.12.94+deb13-amd64` (trixie) | not set | **not set** | `m` |
| `linux-headers-6.12.94+deb13-cloud-amd64` (trixie) | not set | *(absent — `DRM` is off)* | **not set** |
| `linux-headers-6.12.94+deb13-rt-amd64` (trixie) | not set | **not set** | `m` |
| `linux-headers-6.12.101+deb13-amd64` (proposed-updates) | not set | **not set** | `m` |
| `linux-headers-6.16.3+deb13-amd64` (trixie-backports) | not set | **not set** | `m` |
| `linux-headers-7.1.7+deb13-amd64` (trixie-backports) | not set | **not set** | `m` |
| `linux-headers-7.1.7+deb13-cloud-amd64` (trixie-backports) | not set | *(absent)* | **not set** |
| `linux-headers-7.1.7+deb13-rt-amd64` (trixie-backports) | not set | **not set** | `m` |
| `linux-headers-7.1.8+deb14-amd64` (sid) | not set | **not set** | `m` |
| `linux-headers-6.12.94+deb13-arm64` | not set | **not set** | `m` |
| `linux-headers-6.12.94+deb13-riscv64` | not set | **not set** | `m` |

**`=m` nowhere.** The ticket asked specifically whether Debian builds it as a module somewhere, since
that would be a different fix. It does not — not on amd64, and not on the two non-x86 architectures
spot-checked. In the `cloud-amd64` flavour the symbol cannot even appear, because `CONFIG_DRM is not
set` outright: that flavour is *further* from a KMS display than the default one, not closer.

Confirmed against the shipped artifact rather than the source tree, per the project's standing rule.
Inside `linux-image-6.12.94+deb13-amd64_6.12.94-1_amd64.deb`:

```
./boot/config-6.12.94+deb13-amd64          →  # CONFIG_DRM_SIMPLEDRM is not set
                                              # CONFIG_SYSFB_SIMPLEFB is not set
./usr/lib/modules/6.12.94+deb13-amd64/kernel/drivers/gpu/drm/tiny/
    bochs.ko.xz
    cirrus.ko.xz
```

`drm/tiny/` exists in the package and holds exactly two modules; `simpledrm.ko` is not one of them.
The `rt-amd64` image ships the identical pair.

And no other package supplies it. `packages.debian.org`'s contents index returns *"your search gave
no results"* for `simpledrm.ko` in **trixie, trixie-updates, trixie-backports, sid and forky**, the
last four searched across *all* architectures. Control for the search itself: the same query for
`bochs.ko` in trixie/amd64 returns 8 results, so the index and the substring match both work.
([contents search](https://packages.debian.org/search?searchon=contents&keywords=simpledrm.ko&mode=filename&suite=trixie&arch=amd64))

### The 6.18-era alternatives are off too

Linux 6.18 split `simpledrm`'s family into `drivers/gpu/drm/sysfb/`, adding `DRM_EFIDRM` and
`DRM_VESADRM` — drivers that bind the **`efi-framebuffer`** and `vesa-framebuffer` platform devices
directly, which would give a KMS node *without* `SYSFB_SIMPLEFB`. In both `7.1.7+deb13-amd64`
(trixie-backports) and `7.1.8+deb14-amd64` (sid):

```
# CONFIG_SYSFB_SIMPLEFB is not set
# CONFIG_DRM_EFIDRM is not set
# CONFIG_DRM_SIMPLEDRM is not set
# CONFIG_DRM_VESADRM is not set
# CONFIG_FRAMEBUFFER_CONSOLE_DEFERRED_TAKEOVER is not set
```

So the newest kernel Debian ships anywhere still has no driverless DRM path on amd64.

## 3. The mechanism, and why one symbol without the other is useless

#40 asserted the relationship; it holds, and here is the code that makes it hold. At `v6.12`:

`CONFIG_SYSFB_SIMPLEFB` is the gate. Its own help text states the consequence of leaving it off:
*"If this option is not selected, all system framebuffers are always marked as fallback platform
framebuffers as usual."*
([`drivers/firmware/Kconfig` L187](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/drivers/firmware/Kconfig?h=v6.12#n187))
`sysfb.c` says it again in its file comment: *"If CONFIG_SYSFB_SIMPLEFB is not selected, never
register 'simple-framebuffer' platform devices, but only use legacy framebuffer devices for
backwards compatibility."*
([`drivers/firmware/sysfb.c` L19](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/drivers/firmware/sysfb.c?h=v6.12#n19))

The enforcement is a compile-time stub, not a runtime branch. With the symbol off,
`sysfb_parse_mode()` is `static inline … { return false; }`
([`include/linux/sysfb.h`](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/include/linux/sysfb.h?h=v6.12#n97)),
so `sysfb_init()`'s `if (compatible)` can never be taken and it falls through to
`name = "efi-framebuffer"`
([`sysfb.c` L146-166](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/drivers/firmware/sysfb.c?h=v6.12#n146)).

`simpledrm` only ever binds the other name — `.name = "simple-framebuffer", /* connect to sysfb */`,
with an OF match table containing that one compatible
([`simpledrm.c` L1058-1071](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/drivers/gpu/drm/tiny/simpledrm.c?h=v6.12#n1058)).
Upstream states the pairing directly in `DRM_SIMPLEDRM`'s help: *"On x86 BIOS or UEFI systems, you
should also select SYSFB_SIMPLEFB"*
([`drivers/gpu/drm/tiny/Kconfig` L82](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/drivers/gpu/drm/tiny/Kconfig?h=v6.12#n82)).

**So a custom kernel must set both.** `DRM_SIMPLEDRM=y` alone binds nothing on a UEFI Debian machine,
exactly as #43 suspected. `DRM_SIMPLEDRM` is a `tristate` with no `default`, so `=m` is available if
we want it modular.

One further wrinkle worth knowing before anyone reads a config: **trixie's amd64 kernel has
`CONFIG_FB_SIMPLE=y`** (the *fbdev* `simplefb`, re-enabled at some point after 2016). It is equally
dead for the same reason — with `SYSFB_SIMPLEFB=n` no `simple-framebuffer` device is ever registered,
so neither `simplefb` nor `simpledrm` has anything to bind. Do not read `FB_SIMPLE=y` as a sign the
path works.

## 4. The position is recorded, and its stated reason has expired

Debian did not omit this by accident. Bug
[#822575](https://bugs.debian.org/cgi-bin/bugreport.cgi?bug=822575) — *"debian regression: no more
console output after 'switching to mgag200drmfb from simple'"*, filed 2016-04-25 against src:linux,
now archived — is the origin, and the config comment still points at it.

The chain, in the bug's own words:

- **The symptom** was a *handover* failure: with `CONFIG_X86_SYSFB=y` (the symbol later renamed
  `SYSFB_SIMPLEFB`) the boot framebuffer held the video RAM, and when the native KMS driver loaded it
  could not claim the aperture — `*ERROR* can't reserve VRAM`, then `Console: switching to colour
  dummy device`, i.e. a *black screen after* the real driver arrived. Philipp Hahn's analysis names
  SUSE and Ubuntu having disabled the same option.
  ([msg#55](https://bugs.debian.org/cgi-bin/bugreport.cgi?bug=822575#55))
- **The authority** was upstream. David Herrmann, `sysfb`'s author, replying to Hahn:
  *"Right now CONFIG_X86_SYSFB should remain disabled. Once the SimpleDRM driver is upstream, there
  will be infrastructure to do the hw handover. Right now, it breaks if you hand over hw from one
  driver to another."*
  ([msg#60](https://bugs.debian.org/cgi-bin/bugreport.cgi?bug=822575#60))
- **The action**, the next day: Ben Hutchings — *"Thanks, I've committed this change for the next
  uploads to unstable and stable."*
  ([msg#65](https://bugs.debian.org/cgi-bin/bugreport.cgi?bug=822575#65)) The changelog entry is
  `[x86] video: Disable X86_SYSFB, FB_SIMPLE (Closes: #822575)`, and the bug is marked fixed in
  `4.9~rc7-1~exp1`, `4.8.11-1` and `3.16.39-1`.

**The condition upstream attached has been met since Linux 5.14**: `drivers/gpu/drm/tiny/simpledrm.c`
404s at `v5.13` and exists at `v5.14`, and `sysfb_disable()` — the handover machinery Herrmann
promised — is present and exported in 6.12
([`sysfb.c` L67](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/drivers/firmware/sysfb.c?h=v6.12#n67)).
Debian's comment is therefore **a stale annotation, not a live objection**, and that is
the framing #40's option 1 should use: a custom kernel is not overriding a considered Debian refusal,
it is anticipating a change Debian has already agreed to in principle (§5).

### The standing request

[#993640](https://bugs.debian.org/cgi-bin/bugreport.cgi?bug=993640) — *"Please turn on the SimpleDRM
driver in 6.11"* — has been **open since 2021-09-04**, tagged `patch`, and merged with two newer
duplicates: [#1122035](https://bugs.debian.org/cgi-bin/bugreport.cgi?bug=1122035) (Dec 2025, a
Zhaoxin laptop where GNOME 49 will not start without it) and
[#1125148](https://bugs.debian.org/cgi-bin/bugreport.cgi?bug=1125148) (Jan 2026, flicker-free boot).
Nobody from the kernel team ever posted a *refusal* in that bug. The only in-BTS response is Luca
Boccassi in April 2025 pointing at two implementations and asking the team which it prefers
([msg#43](https://bugs.debian.org/cgi-bin/bugreport.cgi?bug=993640#43)); nothing follows it.

## 5. What is in flight, and which release it lands in

| | State | What it does |
| --- | --- | --- |
| [MR !1312](https://salsa.debian.org/kernel-team/linux/-/merge_requests/1312) (Alper Nebi Yasak) | **closed** 2025-04-23 | `DRM_SIMPLEDRM=m` + `SYSFB_SIMPLEFB=y`, with the initramfs/installer plumbing a modular build needs |
| [MR !1453](https://salsa.debian.org/kernel-team/linux/-/merge_requests/1453) (Luca Boccassi) | **open**, rebased 2026-08-03 | built-in: `SYSFB_SIMPLEFB=y`, `DRM=y`, `DRM_SIMPLEDRM=y` on amd64 |

!1453's diff is precisely the change #40's option 1 would make by hand — it deletes the
`#. Doesn't support handover; see #822575` line — and its changelog stanza targets
**`linux (7.2~rc6-1~exp1) UNRELEASED`**. That is experimental → sid → **forky**. Its description
makes the same argument as §4: *"CONFIG_SYSFB_SIMPLEFB was disabled for #822575 as the simpledrm
driver didn't exist at the time… It is now available and enabled, so turn this option back on."*
([MR !1453 diff](https://salsa.debian.org/kernel-team/linux/-/merge_requests/1453.diff))

The strongest signal is who is driving it. On 2026-05-10 **Ben Hutchings posted
[an RFC to debian-kernel](https://lists.debian.org/debian-kernel/2026/05/msg00304.html)**, *"[RFC]
Using SimpleDRM in the initramfs"*, cross-posted to debian-boot, GRUB and plymouth, stating as a goal
that on systems where firmware sets up a usable framebuffer, SimpleDRM should be *"included in either
the kernel image or the initramfs"*, *"bind to that framebuffer"*, and that
*"`CONFIG_SYSFB_SIMPLEFB` and `CONFIG_DRM_SIMPLE` must be enabled for all relevant architectures.
The above merge request would do this on amd64."* The one reply on record, 2026-06-27:
*"We got no objections to this letter, so I think we can proceed with your plan."*
([msg](https://lists.debian.org/debian-kernel/2026/06/msg00315.html))

It has not landed. sid's `7.1.8-1`, built after that exchange, still has all four symbols unset (§2),
and there is no further simpledrm traffic in the debian-kernel archives for July or August 2026.

Two caveats that matter to us, both from Ben's own writing:

- The blocker he names is **not** the 2016 one. It is that *"we cannot assume that an EFI framebuffer
  is always usable. In particular, older versions of GRUB may break it by using a native graphics
  driver, but without clearing whatever signals the kernel that it is available."* aobs controls its
  own bootloader and its own GRUB config, so this specific hazard is ours to close, not ours to
  inherit — but it is a real thing to test, not a paper risk.
- His earlier position, [October 2024](https://lists.debian.org/debian-kernel/2024/10/msg00152.html),
  pointed the other way for the same problem: *"On PCs booting with EFI, the built-in efifb driver
  should work"*. That mail drew no replies on debian-kernel. It is not a ruling against simpledrm,
  but it is evidence that "use `efifb`" is a position a Debian kernel maintainer has held in print —
  relevant if #48/#49 weigh a non-DRM renderer.

## 6. What this means for aobs

1. **#40's option 4 is dead.** No package name closes this. Choose among options 1, 2 and 3 on their
   merits; there is no fourth door.
2. **If option 1 (custom kernel) is chosen, the patch is already written.** MR !1453 is the exact
   config delta, reviewed in public, authored by a DD, and it can be applied to trixie's
   `debian/6.12/trixie` branch — where the line to change is `kernelarch-x86/config`, not
   `amd64/config` as on `debian/latest`. Set **both** symbols; `DRM_SIMPLEDRM=y` alone is inert (§3).
   Whether to follow !1453's `DRM=y` or keep Debian's `DRM=m` is an open build question this ticket
   does not answer.
3. **Time is on option 2's side but not on v1's.** The driverless path is coming to Debian for forky
   via a change its kernel maintainer is championing. A v1 that ships native-KMS-only and publishes a
   tested-hardware list gets the guarantee back for free on a trixie-backports or forky kernel, if
   and when !1453 merges. That is an argument about v2, and it should not be spent as if it were an
   argument about v1.
4. **Do not expect `EFIDRM` to arrive first.** It is the symbol that would need no `SYSFB_SIMPLEFB`
   at all, and Debian has it off in 7.1 as well.
5. **One incidental finding for `05-testing-and-release.md` §6.2.** Debian's amd64 kernel *does* ship
   `bochs.ko` and `cirrus.ko` in `drm/tiny/`. Under QEMU/OVMF, a `bochs-display` or `-vga std` guest
   therefore has a native KMS driver where `ramfb` has none. That does not restore the §6.2 `ramfb`
   row — which asserts `simpledrm` specifically and still cannot pass — but it means a *DRM* test rig
   exists today without a custom kernel. Treating it as equivalent to the `ramfb` case would be
   wrong; it exercises a native driver, which is the path #40 says is now the only one.

---

## What was not checked

- **MR !1453's review discussion.** Salsa's notes/discussions API returns `401 Unauthorized`
  anonymously and the web UI renders comments client-side, so **I could not read whether any Debian
  kernel maintainer objected inside the MR.** Everything reported about the team's position comes
  from the BTS, the mailing-list archives and the MR description/diff. The "no objections" quote is
  one contributor's summary of the RFC thread, not a maintainer's approval.
- **A full-text bug search was not possible.** `bugs.debian.org`'s search endpoint redirects to
  `bugs-search.debian.org`, which does not resolve. Instead the complete `src:linux` bug list was
  fetched with `archive=both` (9.3 MB, and it does contain the archived #822575) and **titles** were
  grepped. A bug whose title omits `simpledrm`/`simplefb` would have been missed.
- **No kernel was built, patched or booted.** That both symbols being set actually yields
  `/dev/dri/card0` on a Debian trixie kernel is untested here — it is #40's option 1 to prove, and
  ADR-0009's original claim remains sourced from upstream code only.
- **Slint was not exercised against `simpledrm`.** `backend-linuxkms` + `renderer-software` on a
  `simpledrm` node is still an unverified assumption of ADR-0002/0009.
- **#40's own ISO evidence was taken as given** and not re-derived. Its `/boot/config` values do match
  the packaged `6.12.101+deb13-amd64` config read here, independently.
- **Non-Debian kernels** (Liquorix, XanMod, Ubuntu's) were not examined: they are outside "a Debian
  kernel package", which is what the ticket asked.
- **Architectures beyond amd64/arm64/riscv64** were spot-checked only through the config tree (which
  mentions `DRM_SIMPLEDRM` nowhere), not through built packages.

---

## Sources

| Claim | Source |
| --- | --- |
| trixie amd64 flavours: `amd64`, `cloud-amd64`, `rt` featureset | [`debian/config/amd64/defines.toml`](https://salsa.debian.org/kernel-team/linux/-/blob/debian/6.12/trixie/debian/config/amd64/defines.toml) |
| `# CONFIG_SYSFB_SIMPLEFB is not set` + `#. Doesn't support handover; see #822575` | [`debian/config/kernelarch-x86/config` L543](https://salsa.debian.org/kernel-team/linux/-/blob/debian/6.12/trixie/debian/config/kernelarch-x86/config#L543) |
| Same line still present in sid / trixie-backports (moved to `amd64/config`) | [`debian/latest` `amd64/config`](https://salsa.debian.org/kernel-team/linux/-/blob/debian/latest/debian/config/amd64/config), [`debian/7.1/trixie-backports`](https://salsa.debian.org/kernel-team/linux/-/blob/debian/7.1/trixie-backports/debian/config/amd64/config) |
| No i386 flavour; whole config tree | [`debian/config/` tree, trixie](https://salsa.debian.org/kernel-team/linux/-/tree/debian/6.12/trixie/debian/config) |
| rt featureset changes nothing about display | [`featureset-rt/config`](https://salsa.debian.org/kernel-team/linux/-/blob/debian/6.12/trixie/debian/config/featureset-rt/config) |
| Built `.config` per flavour and per suite | [`pool/main/l/linux/`](https://deb.debian.org/debian/pool/main/l/linux/) — `linux-headers-{6.12.94,6.12.101,6.16.3,7.1.7}+deb13-*`, `linux-headers-7.1.8+deb14-amd64` |
| Shipped signed image: config + `drm/tiny/` contents | [`pool/main/l/linux-signed-amd64/`](https://deb.debian.org/debian/pool/main/l/linux-signed-amd64/) — `linux-image-6.12.94+deb13-amd64_6.12.94-1_amd64.deb` |
| No package contains `simpledrm.ko` (trixie, -updates, -backports, sid, forky) | [contents search](https://packages.debian.org/search?searchon=contents&keywords=simpledrm.ko&mode=filename&suite=trixie&arch=amd64) |
| `SYSFB_SIMPLEFB` Kconfig and its "fallback platform framebuffers" note | [`drivers/firmware/Kconfig` v6.12](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/drivers/firmware/Kconfig?h=v6.12#n187) |
| `sysfb_init()` falls through to `efi-framebuffer`; `sysfb_disable()` handover | [`drivers/firmware/sysfb.c` v6.12](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/drivers/firmware/sysfb.c?h=v6.12) |
| `sysfb_parse_mode()` compile-time stub | [`include/linux/sysfb.h` v6.12](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/include/linux/sysfb.h?h=v6.12#n97) |
| `DRM_SIMPLEDRM` is `tristate`, no default, "you should also select SYSFB_SIMPLEFB" | [`drivers/gpu/drm/tiny/Kconfig` v6.12](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/drivers/gpu/drm/tiny/Kconfig?h=v6.12#n82) |
| `simpledrm` binds only `simple-framebuffer` | [`simpledrm.c` v6.12](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/drivers/gpu/drm/tiny/simpledrm.c?h=v6.12#n1058) |
| `simpledrm` first exists in v5.14 (404 at v5.13) | `git.kernel.org` `plain/drivers/gpu/drm/tiny/simpledrm.c?h=v5.13` vs `?h=v5.14` |
| The 2016 disable: symptom, upstream advice, commit, changelog | [Bug #822575](https://bugs.debian.org/cgi-bin/bugreport.cgi?bug=822575), msgs [#55](https://bugs.debian.org/cgi-bin/bugreport.cgi?bug=822575#55) [#60](https://bugs.debian.org/cgi-bin/bugreport.cgi?bug=822575#60) [#65](https://bugs.debian.org/cgi-bin/bugreport.cgi?bug=822575#65) |
| Config line last touched by a mechanical cleanup, not a re-decision | salsa blame of `kernelarch-x86/config` → `94b62572b82b` *"debian/config: Clean up with the help of kconfigeditor2"*, 2021-11-07 |
| Open request since 2021, merged with two 2025/2026 duplicates | [#993640](https://bugs.debian.org/cgi-bin/bugreport.cgi?bug=993640), [#1122035](https://bugs.debian.org/cgi-bin/bugreport.cgi?bug=1122035), [#1125148](https://bugs.debian.org/cgi-bin/bugreport.cgi?bug=1125148) |
| Two proposed implementations; states and diff | [MR !1312](https://salsa.debian.org/kernel-team/linux/-/merge_requests/1312) (closed), [MR !1453](https://salsa.debian.org/kernel-team/linux/-/merge_requests/1453) + [`.diff`](https://salsa.debian.org/kernel-team/linux/-/merge_requests/1453.diff) (open) |
| Ben Hutchings' RFC and its goals; the "no objections" reply | [debian-kernel 2026/05 msg00304](https://lists.debian.org/debian-kernel/2026/05/msg00304.html), [2026/06 msg00315](https://lists.debian.org/debian-kernel/2026/06/msg00315.html) |
| Earlier "efifb should work" position | [debian-kernel 2024/10 msg00152](https://lists.debian.org/debian-kernel/2024/10/msg00152.html) |
