# Reproducible build

The reproducibility contract: which facts of a build environment must not reach the bytes of
`out/bitcoin-signer-amd64.iso`, what holds each one out today, and what is not claimed.
`docs/threat-model.md` claim (ix) states the promise; this document states the mechanism.
`docs/boot-pipeline.md` is how the image is built; this document is only about whether two builds
agree.

**Nothing in this document has been demonstrated.** No two builds of one commit have been compared
byte for byte, on one host or on two. Every *held* below is a reading of the code, cited to the
line, and is a claim the reproducibility guard has not yet tested. The guard is the next M4 row, and
the contract is written first so that the guard knows what to vary and a failure knows what it
broke.

## What the contract is about

**The output** is one number: the sha256 of `out/bitcoin-signer-amd64.iso`.

**What is allowed to determine it**, and nothing else:

1. **The commit.** The tree `build/mkiso.sh` reads, which includes every pin file.
2. **The input archive.** `build/inputs/`, gated by `build/inputs.sha256` on hash and on set
   equality in stage 0 (`build/mkiso.sh:88-95`). The archive itself being reproducible is a separate
   M4 row and is not claimed here.
3. **`SOURCE_DATE_EPOCH`**, which is not a free variable: `build/mkiso.sh:239` derives it from the
   commit's own timestamp.

**What is not yet true**: a fourth thing determines it today — the versions of the build host's own
tools. See *Not claimed*, item 1. Until that is closed, the contract is stated **relative to a host
with the same tool versions**, and a rebuild on a different distribution that disagrees has found
the open question below, not a defect.

## The contract: facts that must not reach the bytes

Each fact carries one status:

- **held** — a mechanism in the code keeps it out, cited. Unmeasured until the guard runs.
- **leaks** — a mechanism carries it into the bytes, cited. *Observed* where a build was inspected;
  *read* where only the code was.
- **refused** — the build stops rather than tolerate variation.
- **unknown** — nothing read so far either holds it out or lets it in.

The observations below come from one local build of `9124dd9` (2026-09-12, via
`build/mkiso-docker.sh`), inspected in `out/work/`. One build can show that a value is present; only
two builds can show that it varies, and the statement is limited to that.

| # | Fact | Status | Where |
|---|---|---|---|
| 1 | Build path | held | below |
| 2 | Hostname | held | below |
| 3 | User name and uid | **leaks**, observed | below |
| 4 | Clock | **leaks**, observed | below |
| 5 | Locale | unknown | below |
| 6 | Timezone | unknown | below |
| 7 | umask | **leaks**, read | below |
| 8 | CPU count | unknown | below |
| 9 | Host kernel | unknown | below |
| 10 | Host architecture | refused | below |
| 11 | Host filesystem | **leaks**, read | below |

### 1. Build path — held

- The initramfs names every member relative to the rootfs (`build/mkinitramfs.py:127`), so the
  checkout's location is not in the archive.
- The pool is staged at a `mktemp` path (`build/mkiso.sh:161`), and mmdebstrap writes that path into
  the chroot's apt sources and list filenames. Stage 3b deletes `etc/apt` and `var/lib/apt`
  (`build/mkiso.sh:294-305`), so the random name does not survive.
- The bytecode the signing check writes is compiled *inside* the chroot, so its embedded source path
  is `/opt/...` and not the host's. (That bytecode leaks the clock instead; see fact 4.)

### 2. Hostname — held

mmdebstrap copies the host's `etc/hostname` and `etc/resolv.conf` into the chroot; the first
customize hook deletes both (`build/mkiso.sh:209`).

### 3. User name and uid — leaks, observed

- **Held in the initramfs.** Every `newc` member is written `uid 0, gid 0` whoever built it
  (`build/mkinitramfs.py:96-97`).
- **Leaks in the ISO.** xorriso writes Rock Ridge records, and they carry the owner of
  `$ISO_TREE` on the build host. Observed: the root directory, `BOOT` and `EFIBOOT.IMG` all read
  `uid 1001 gid 1001` — the `builder` user of `build/Dockerfile.isohost`. A build by any other uid
  writes a different ISO.

### 4. Clock — leaks, observed

`SOURCE_DATE_EPOCH` is derived from the commit (`build/mkiso.sh:239`) and fixes every initramfs mtime
(`build/mkinitramfs.py:175`) and the date in `/etc/aobs-release` (`build/mkiso.sh:240`). Three things
get past it:

- **It is never exported.** `: "${SOURCE_DATE_EPOCH:=...}"` assigns a shell variable. Only
  `mkinitramfs.py` is handed it, explicitly (`build/mkiso.sh:384`). mmdebstrap and xorriso read
  `SOURCE_DATE_EPOCH` from the environment and see none unless the caller happened to export one;
  whether `grub-mkstandalone` and `mformat`/`mcopy` read it at all is not checked.
- **The ISO volume dates are the wall clock.** Observed: the primary volume descriptor's creation and
  modification dates read `2026-09-12 17:24:56` UTC; the commit's `SOURCE_DATE_EPOCH` is `16:58:53`
  that day.
- **The bytecode carries the checkout's mtimes.** The signing check runs the image's own interpreter
  in the chroot (`build/mkiso.sh:213`), which imports the app and writes `__pycache__` beside it.
  Observed: **338 `.pyc` files in 37 directories** under `/opt/aobs` and `/opt/aobs-python`, all
  timestamp-validated (flags `0`), the one inspected recording a source mtime of
  `2026-09-07 21:59:25` UTC — when the file was written to that checkout, not the commit time. Stage
  1a deletes `__pycache__` from the staged trees (`build/mkiso.sh:145`, `:159`) and the signing check
  writes it back afterwards. PID 1 sets `PYTHONDONTWRITEBYTECODE=1` (`build/init:159`); the build
  does not.

And one fallback: with no git metadata, `SOURCE_DATE_EPOCH` falls back to `date +%s`
(`build/mkiso.sh:239`) — the clock, directly.

### 5. Locale — unknown

The orderings that reach the image are locale-free: `mkinitramfs.py` sorts with Python's codepoint
order (`:125`). The host `sort` and `find` in stage 3d produce listings for `build/verify.py`, which
are not in the image. What maintainer scripts write under the host's locale inside mmdebstrap has not
been looked at.

### 6. Timezone — unknown

The one date the build formats uses `date -u` (`build/mkiso.sh:240`). Nothing else has been looked at.

### 7. umask — leaks, read

The build is unprivileged, and an unprivileged `tar -x` applies the caller's umask to every mode it
restores (`--no-same-permissions` is GNU tar's default for non-root). The rootfs is unpacked that way
(`build/mkiso.sh:225`), the staged Python layer and app tree are created under it
(`build/mkiso.sh:136-159`), and `mkinitramfs.py` writes each file's `st_mode` into its header. A
`umask 077` build packs different modes from a `umask 022` build. `build/mkiso.sh` never sets one.

### 8. CPU count — unknown

The one CPU-count-dependent flag in the build is `zstd -T0` (`build/mkiso.sh:386`), which sizes the
worker pool to the host. Whether zstd's output depends on the worker count has not been checked; the
guard answers it, and `-T1` removes the question if the answer is yes.

### 9. Host kernel — unknown

The host kernel decides whether `--mode=unshare` works at all — `docs/boot-pipeline.md` records
where it does and where it does not — but nothing read so far writes a host-kernel fact into the
image.

### 10. Host architecture — refused

Stage 0 stops on anything but `x86_64` (`build/mkiso.sh:62-67`). That refuses a native foreign host;
it does not cover an amd64 container under emulation, which reports `x86_64` and is what
`build/mkiso-docker.sh` uses on an arm64 machine. Whether emulation changes a byte is unmeasured.

### 11. Host filesystem — leaks, read

Not in the roadmap's list, and found by reading stage 3c. The RAM floor is derived from
`du -sk` of the unpacked rootfs (`build/mkiso.sh:326`), and `du` reports **allocated blocks**, which
depend on the filesystem the build runs on — block size, inline data, sparse allocation. The derived
`RAM_REQUIRED_MIB` is substituted into `/init` (`build/mkiso.sh:332-335`), so it is in the initramfs.
The published floor is rounded to a power of two and will usually survive a difference; the
unrounded figure PID 1 compares against will not.

## Not claimed

1. **The versions of the host's build tools.** This is the largest hole and it is an open question,
   not an oversight.

   *Bytes of the ISO come from the host's own packages*, not from `build/inputs/`: `isolinux.bin`,
   `ldlinux.c32` and `isohdpfx.bin` are copied out of the host's `/usr/lib/ISOLINUX` and
   `/usr/lib/syslinux` (`build/mkiso.sh:402-406`, `:425`), and `bootx64.efi` is assembled by
   `grub-mkstandalone` from the host's GRUB modules (`:411-413`). On CI those are `ubuntu-24.04`'s,
   installed unpinned (`.github/workflows/tests.yml`, *The build tools*). They are the boot chain's
   first code, so this is a trust question as well as a reproducibility one.

   *Arrangement comes from host tools too*: xorriso lays out the ISO, `mformat`/`mcopy` the EFI
   partition, zstd the initramfs compression, the host's `depmod` writes `modules.dep*` into the
   rootfs (`build/mkiso.sh:278`), and the host's pip writes each wheel's install metadata
   (`:137-144`). A different version of any of them may write different bytes from identical inputs.

   **Half of the answer already exists and is unused.** The harness group pins `mmdebstrap`,
   `xorriso`, `isolinux`, `grub-efi-amd64-bin`, `zstd` and `cpio` at the snapshot, with a comment
   saying they are there "so Dockerfile.iso reads one pinned file". No such Dockerfile exists, and
   `syslinux-common` (which ships `ldlinux.c32`) and `mtools` are not pinned at all.

   *Why it is open*: the obvious fix — build inside an image made from the pinned harness pool — is a
   container, and on the hosts measured so far a container can only reach stage 1 `--privileged`
   (`build/mkiso-docker.sh`). The build's unprivileged claim is measured on a bare `ubuntu-24.04`
   runner. The two endings, and the recommendation, are in `docs/roadmap.md` M4.

2. **That the input archive is reproducible.** A separate M4 row. This contract takes
   `build/inputs/` as given, checked by hash.

3. **Anything about the written medium.** The contract ends at the ISO file. What reaches a stick,
   and what the firmware reads from it, is `docs/boot-checklist.md`'s *Write the medium*, at its
   stated strength.

4. **That a reproduced ISO is a safe one.** Two hashes agreeing says the same inputs produced the same
   bytes. It says nothing about whether the inputs were honest; that is what the source archive and
   the pinned snapshot are for, and it is `docs/threat-model.md`'s question.

5. **The privileged local build as evidence of anything.** `build/mkiso-docker.sh` is a different
   host from CI's — a container, privileged, under emulation on an arm64 machine. If it and CI
   agree, that is corroboration; the guard is what the claim will rest on.

## What changes this document

A fact moves from *leaks* or *unknown* to *held* only with the change that holds it out **and** a
guard run that varied it. A fact may be added; none may be removed without saying here why it no
longer applies. When the open question in *Not claimed* is closed, item 1 moves into the contract or
stays out of it by decision, and the README's *On reproducibility* paragraph changes with it.
