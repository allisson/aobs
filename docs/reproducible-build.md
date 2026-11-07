# Reproducible build

The reproducibility contract: which facts of a build environment must not reach the bytes of
`out/bitcoin-signer-amd64.iso`, what holds each one out today, and what is not claimed.
`docs/threat-model.md` claim (ix) states the promise; this document states the mechanism.
`docs/boot-pipeline.md` is how the image is built; this document is only about whether two builds
agree.

**Almost nothing in this document has been demonstrated.** The guard — two builds under deliberately
hostile variation, compared byte for byte — has not run. What has run is one pair of local builds of
one tree, below, which varied exactly one fact. Every other *held* and *closed* is a reading of the
code, cited to the line, and is a claim the guard has not yet tested. The contract is written before
the guard so that the guard knows what to vary and a failure knows what it broke.

**One pair, identical.** 2026-11-07, `build/mkiso-docker.sh` twice in a row on one machine, the
second build starting after the first had finished (about five minutes apart): both ISOs
`824e01249914322a3e39172bf62b9a5295cd98643ebb2d0e7a090648a6e15f7d`. Same container, same uid, same
umask, same CPU count, same filesystem, same path — so the one fact varied was the clock (fact 4),
and the pair shows only that the wall clock no longer reaches the bytes. The pair before it, without
`--set_all_file_dates`, differed in 114 bytes, every one of them a directory or file date in the ISO
9660 and Rock Ridge records; the initramfs, kernel, EFI image and loaders already matched.

## What the contract is about

**The output** is one number: the sha256 of `out/bitcoin-signer-amd64.iso`.

**What is allowed to determine it**, and nothing else:

1. **The commit.** The tree `build/mkiso.sh` reads, which includes every pin file.
2. **The input archive.** `build/inputs/`, gated by `build/inputs.sha256` on hash and on set
   equality in stage 0 (`build/mkiso.sh:93-100`). The archive itself being reproducible is a separate
   M4 row and is not claimed here.
3. **`SOURCE_DATE_EPOCH`**, which is not a free variable: `build/mkiso.sh:111-117` derives it from
   the commit's own timestamp, ignores any value in the caller's environment, refuses a checkout with
   no git metadata, and exports it.
4. **The versions of the host's arranging tools**, by decision (`docs/roadmap.md` M4). mmdebstrap,
   xorriso, mtools, zstd, `grub-mkstandalone`, the host's `depmod` and the host's pip supply no
   bytes — every byte comes from the input archive — but they decide how those bytes are laid out,
   and they are the host's and unpinned. The build prints each one's version beside the ISO's
   digest. A rebuild that disagrees compares those lines first: if they differ, it has found this
   input, not a defect.

**The boot chain is not among them.** `isolinux.bin`, `ldlinux.c32`, `isohdpfx.bin` and the GRUB
`kernel.img` and modules `bootx64.efi` is assembled from are extracted from the pinned pool in stage
5 with `dpkg-deb -x`, as stage 3 extracts the kernel. Until M4 they were copied off the build host;
`build/verify.py`'s `no_loader_read_from_the_host` fails the suite if a host loader path returns.

## The contract: facts that must not reach the bytes

Each fact carries one status:

- **held** — a mechanism in the code keeps it out, and always did, cited. Unmeasured until the guard
  runs.
- **closed** — it leaked, and a change now keeps it out, cited. Stays *closed* rather than *held*
  until a guard run has varied it (*What changes this document*, below).
- **leaks** — a mechanism carries it into the bytes, cited. *Observed* where a build was inspected;
  *read* where only the code was.
- **refused** — the build stops rather than tolerate variation.
- **unknown** — nothing read so far either holds it out or lets it in.

The original observations come from one local build of `9124dd9` (2026-09-12, via
`build/mkiso-docker.sh`), inspected in `out/work/`; the closures were checked on a build of this
change, 2026-11-07. One build can show that a value is present or absent; only two builds can show
that it varies.

| # | Fact | Status | Where |
|---|---|---|---|
| 1 | Build path | held | below |
| 2 | Hostname | held | below |
| 3 | User name and uid | closed | below |
| 4 | Clock | closed, varied once locally | below |
| 5 | Locale | unknown | below |
| 6 | Timezone | unknown | below |
| 7 | umask | closed | below |
| 8 | CPU count | held, measured on zstd alone | below |
| 9 | Host kernel | unknown | below |
| 10 | Host architecture | refused | below |
| 11 | Host filesystem | closed | below |

### 1. Build path — held

- The initramfs names every member relative to the rootfs (`build/mkinitramfs.py:127`), so the
  checkout's location is not in the archive.
- The pool is staged at a `mktemp` path (`build/mkiso.sh:179`), and mmdebstrap writes that path into
  the chroot's apt sources and list filenames. Stage 3b deletes `etc/apt` and `var/lib/apt`
  (`build/mkiso.sh:316-327`), so the random name does not survive.
- The signing check compiles nothing to disk (fact 4), so no bytecode records a source path.

### 2. Hostname — held

mmdebstrap copies the host's `etc/hostname` and `etc/resolv.conf` into the chroot; the first
customize hook deletes both (`build/mkiso.sh:232`).

### 3. User name and uid — closed

- **Held in the initramfs.** Every `newc` member is written `uid 0, gid 0` whoever built it
  (`build/mkinitramfs.py:96-97`).
- **Closed in the ISO.** xorriso writes Rock Ridge records, and they carried the owner of
  `$ISO_TREE` on the build host — observed `uid 1001 gid 1001` on the root directory, `BOOT` and
  `EFIBOOT.IMG`, the `builder` user of `build/Dockerfile.isohost`. `-uid 0 -gid 0`
  (`build/mkiso.sh:481`) now writes every record as root; observed on the root directory of the
  2026-11-07 build. Not varied: both builds of the pair ran as uid 1001.

### 4. Clock — closed, varied once locally

`SOURCE_DATE_EPOCH` is the commit's timestamp and is exported (`build/mkiso.sh:111-117`), so every
tool that reads it sees it. What it reaches:

- **The initramfs mtimes** (`build/mkinitramfs.py:175`) and the date in `/etc/aobs-release`
  (`build/mkiso.sh:262`), as before.
- **The ISO volume dates**, which xorriso takes from the environment. They read the wall clock
  (`2026-09-12 17:24:56` against an SDE of `16:58:53`) and now read the commit's time.
- **The ISO file and directory dates**, which xorriso does *not* take from the environment under
  `-as mkisofs`: measured on 1.5.6, with SOURCE_DATE_EPOCH exported, every record still carried its
  host mtime. `--set_all_file_dates` (`build/mkiso.sh:482`) pins them.
- **The FAT image.** mtools reads SOURCE_DATE_EPOCH (the string is in `mformat`'s binary); the volume
  serial is fixed by `-N` regardless (`build/mkiso.sh:463`).
- **`bootx64.efi`** does not depend on the clock at all: `grub-mkstandalone` 2.12-1ubuntu7.3 produced
  the same binary from the pool's modules two seconds apart and with the config's mtime moved by
  three years. Measured, not read.

**The bytecode is gone.** The signing check imported the app in the chroot and left **338 `.pyc`
files in 37 directories** under `/opt`, timestamp-validated and recording the checkout's source
mtimes. It now runs under `python3 -B` (`build/mkiso.sh:236`); the 2026-11-07 build has no `.pyc`
under `/opt`. Nothing used them: each source's mtime in the initramfs is SOURCE_DATE_EPOCH, so each
one failed its timestamp check at boot and was recompiled in memory.

**The fallback is gone.** With no git metadata the build used `date +%s`; it now refuses to start.

What has not been looked at: whether the bytecode Debian's own maintainer scripts compile under
`/usr/lib/python3*` during mmdebstrap is byte-stable. Its source mtimes come from the `.deb`s, not
the clock, and the pair agreeing is consistent with that; the guard will say more.

### 5. Locale — unknown

The orderings that reach the image are locale-free: `mkinitramfs.py` sorts with Python's codepoint
order (`:125`). The host `sort` and `find` in stage 3d produce listings for `build/verify.py`, which
are not in the image. What maintainer scripts write under the host's locale inside mmdebstrap has not
been looked at.

### 6. Timezone — unknown

The one date the build formats uses `date -u` (`build/mkiso.sh:262`). Nothing else has been looked at.

### 7. umask — closed

The build is unprivileged, and an unprivileged `tar -x` applies the caller's umask to every mode it
restores (`--no-same-permissions` is GNU tar's default for non-root). The rootfs is unpacked that way
(`build/mkiso.sh:248`), the staged Python layer and app tree are created under it
(`build/mkiso.sh:153-177`), and `mkinitramfs.py` writes each file's `st_mode` into its header. The
script now sets `umask 022` before anything else (`build/mkiso.sh:23`). Not varied.

### 8. CPU count — held, measured on zstd alone

The one CPU-count-dependent flag in the build is `zstd -T0` (`build/mkiso.sh:410`), which sizes the
worker pool to the host. Measured 2026-11-07 on zstd 1.5.5, the host tool, against one initramfs
(6068 members, 128 MiB): `-T0` on an 8-CPU host and `-T1`, `-T2`, `-T3`, `-T4`, `-T8` and `-T16`
wrote the same bytes. Only `--single-thread`, which the build does not use, wrote different ones.
So a host with any number of CPUs writes the same initramfs.

This is *held* without a guard run that varied it, the one exception in this table, because no guard
can: every runner the guard has gets the same CPU count, and the measurement varies the one place the
count is read. It is a property of zstd 1.5.5 — another version is input 4, not this fact.

### 9. Host kernel — unknown

The host kernel decides whether `--mode=unshare` works at all — `docs/boot-pipeline.md` records
where it does and where it does not — but nothing read so far writes a host-kernel fact into the
image.

### 10. Host architecture — refused

Stage 0 stops on anything but `x86_64` (`build/mkiso.sh:67-72`). That refuses a native foreign host;
it does not cover an amd64 container under emulation, which reports `x86_64` and is what
`build/mkiso-docker.sh` uses on an arm64 machine. Whether emulation changes a byte is unmeasured.

### 11. Host filesystem — closed

Not in the roadmap's list, and found by reading stage 3c. The RAM floor was derived from `du -sk` of
the unpacked rootfs, and `du` reports **allocated blocks**, which depend on the filesystem the build
runs on; the derived `RAM_REQUIRED_MIB` is substituted into `/init` (`build/mkiso.sh:357-360`). The
EFI image was sized the same way. Both now sum the files' own lengths (`build/mkiso.sh:351`, `:461`),
which no filesystem changes. Not varied.

## Not claimed

1. **That a host with different arranging tools reproduces the ISO.** Input 4 above, stated here
   from the other side. xorriso lays out the ISO, `mformat`/`mcopy` the EFI partition, zstd the
   initramfs compression, the host's `depmod` writes `modules.dep*` into the rootfs, the host's pip
   writes each wheel's install metadata, and `grub-mkstandalone` assembles `bootx64.efi` from the
   pool's modules. A different version of any of them may write different bytes from identical
   inputs, and the contract does not promise otherwise.

   *Why the tools are not pinned too*: the harness group already pins mmdebstrap, xorriso and zstd
   at the snapshot, but using them means building inside an image made from that pool — a
   container — and on every host measured so far a container reaches stage 1 only `--privileged`
   (`build/mkiso-docker.sh`), while the build's unprivileged claim is measured on a bare
   `ubuntu-24.04` runner. Decided 2026-11-07, `docs/roadmap.md` M4; that ending stays available
   after v0.1 without reversing anything.

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
   agree, that is corroboration; the guard is what the claim will rest on. The identical pair above
   is that kind of corroboration and no more.

## What changes this document

A fact moves to *held* only with the change that holds it out **and** a guard run that varied it;
until then a fact with the change and no such run is *closed*. Fact 8 is the stated exception. A fact may be added; none may be
removed without saying here why it no longer applies. When the open question in *Not claimed* is
closed, item 1 moves into the contract or stays out of it by decision, and the README's *On
reproducibility* paragraph changes with it.
