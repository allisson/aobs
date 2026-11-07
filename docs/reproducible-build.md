# Reproducible build

The reproducibility contract: which facts of a build environment must not reach the bytes of
`out/bitcoin-signer-amd64.iso`, what holds each one out today, and what is not claimed.
`docs/threat-model.md` claim (ix) states the promise; this document states the mechanism.
`docs/boot-pipeline.md` is how the image is built; this document is only about whether two builds
agree.

**The guard runs on every push and pull request**, as the last steps of the `image` job in
`.github/workflows/tests.yml`: the commit is built twice on one `ubuntu-24.04` runner, the second
build under deliberately hostile variation, and the job fails on any differing byte. On a difference
it prints which files of the ISO tree and which 2 KiB sectors of the image differ.

| | Build A | Build B |
|---|---|---|
| User and uid | `runner` | `rebuilder`, created for the run |
| Path | `$GITHUB_WORKSPACE` | `/mnt/rebuild/elsewhere` |
| Filesystem | the runner's | tmpfs |
| Hostname | the runner's | `rebuild-b`, kernel and `/etc/hostname` |
| Caller's umask | the runner's | `077` |
| Timezone | the runner's | `Pacific/Chatham` |
| Locale | the runner's | `LC_ALL=C` |
| `SOURCE_DATE_EPOCH` in the environment | unset | `1`, which the script must ignore |
| Clock | — | a minute or more later |

**First green run**: 2026-11-07, run
[42391685056](https://github.com/allisson/aobs/actions/runs/42391685056) at `68bdd5a`, both builds
`bc55a73f86bb0709c6571e38f42ff32f9a8f8343ff6903e0d21393673aa3fa37`. The run before it failed and
found fact 6.

**What that shows, and what it does not.** One runner, so one host kernel, one CPU count and one set
of arranging tools — none of those was varied, and the roadmap's M4 exit, two builds on
*deliberately different hosts*, is not met by it. What it shows is that, on one host, none of the
facts in the table above it reaches the bytes.

**One cross-host pair**, 2026-11-07, at `244ec69`. CI run
[42406573050](https://github.com/allisson/aobs/actions/runs/42406573050) built
`651c90b65f16318e9a5c0fb0ec487e5f74f659cff051f7515d89cfaed9977ab1` twice. The same commit, built by
`build/mkiso-docker.sh` on an arm64 Mac, wrote `04a28662a0b4954830c824ddf1adf979cf3c642b1553d53983773ff9be89382a`.
The two builds printed identical arranging-tool lines except one: zstd 1.5.5 there, 1.5.7 on the
runner. That is input 4, and the local `initramfs.zst` was 33.2 MiB against CI's 33.1 MiB. Rebuilt
in the same container with zstd 1.5.7 taken from the pinned harness pool
(`build/inputs/deb/harness/zstd_1.5.7+dfsg-1_amd64.deb`, put first on `PATH`, no tracked file
changed), it wrote `651c90b6…7ab1` — CI's digest.

So the two hosts differed in kernel (the runner's against OrbStack's `7.2.12-orbstack`, 8 CPUs),
architecture under the container (amd64 emulated on arm64), filesystem (the runner's against a bind
mount from macOS) and privilege (unprivileged against `--privileged`), and agreed once their
arranging tools agreed. The runner's kernel version and CPU count were not recorded, so whether the
CPU count differed is not known. One pair, both builds started by the maintainer:
corroboration of facts 9 and 10, not a guard run, so neither moves to *held*, and not the
independent rebuild `docs/threat-model.md` claim (ix) asks for.

Before the guard, a pair of local `build/mkiso-docker.sh` builds varied only the clock and agreed
(`824e0124…5f7d`); the pair before that, without `--set_all_file_dates`, differed in 114 bytes of ISO
9660 and Rock Ridge record dates.

## What the contract is about

**The output** is one number: the sha256 of `out/bitcoin-signer-amd64.iso`.

**What is allowed to determine it**, and nothing else:

1. **The commit.** The tree `build/mkiso.sh` reads, which includes every pin file.
2. **The input archive.** `build/inputs/`, gated by `build/inputs.sha256` on hash and on set
   equality in stage 0 (`build/mkiso.sh:98-105`). The archive itself being reproducible is a separate
   M4 row and is not claimed here.
3. **`SOURCE_DATE_EPOCH`**, which is not a free variable: `build/mkiso.sh:116-122` derives it from
   the commit's own timestamp, ignores any value in the caller's environment, refuses a checkout with
   no git metadata, and exports it.
4. **The versions of the host's arranging tools**, by decision (`docs/roadmap.md` M4). mmdebstrap,
   xorriso, mtools, `grub-mkstandalone`, the host's `depmod` and the host's pip supply no
   bytes — every byte comes from the input archive — but they decide how those bytes are laid out,
   and they are the host's and unpinned. zstd was one of them until the cross-host pair below showed
   it differing between two stock Ubuntu 24.04 hosts; stage 4 now runs the pinned pool's
   (`build/mkiso.sh`, `pool_zstd`), and the build prints its version on a line of its own. The build prints each one's version beside the ISO's
   digest. A rebuild that disagrees compares those lines first: if they differ, it has found this
   input, not a defect.

**The boot chain is not among them.** `isolinux.bin`, `ldlinux.c32`, `isohdpfx.bin` and the GRUB
`kernel.img` and modules `bootx64.efi` is assembled from are extracted from the pinned pool in stage
5 with `dpkg-deb -x`, as stage 3 extracts the kernel. Until M4 they were copied off the build host;
`build/verify.py`'s `no_loader_read_from_the_host` fails the suite if a host loader path returns.

## The contract: facts that must not reach the bytes

Each fact carries one status:

- **held** — it is kept out, cited where a mechanism does it, **and a green guard run varied it**.
- **closed** — it leaked, and a change now keeps it out, cited. Stays *closed* rather than *held*
  until a guard run has varied it (*What changes this document*, below).
- **leaks** — a mechanism carries it into the bytes, cited. *Observed* where a build was inspected;
  *read* where only the code was.
- **refused** — the build stops rather than tolerate variation.
- **unknown** — nothing read so far either holds it out or lets it in.

The original observations come from one local build of `9124dd9` (2026-09-12, via
`build/mkiso-docker.sh`), inspected in `out/work/`. Every *held* below rests on run 42391685056.

| # | Fact | Status | Where |
|---|---|---|---|
| 1 | Build path | held | below |
| 2 | Hostname | held | below |
| 3 | User name and uid | held | below |
| 4 | Clock | held | below |
| 5 | Locale | held | below |
| 6 | Timezone | held — found by the guard | below |
| 7 | umask | held | below |
| 8 | CPU count | held, measured on the pool's zstd alone | below |
| 9 | Host kernel | unknown | below |
| 10 | Host architecture | refused | below |
| 11 | Host filesystem | held | below |

### 1. Build path — held

- The initramfs names every member relative to the rootfs (`build/mkinitramfs.py:127`), so the
  checkout's location is not in the archive.
- The pool is staged at a `mktemp` path (`build/mkiso.sh:184`), and mmdebstrap writes that path into
  the chroot's apt sources and list filenames. Stage 3b deletes `etc/apt` and `var/lib/apt`
  (`build/mkiso.sh:321-332`), so the random name does not survive.
- The signing check compiles nothing to disk (fact 4), so no bytecode records a source path.

Varied by the guard: `$GITHUB_WORKSPACE` against `/mnt/rebuild/elsewhere`.

### 2. Hostname — held

mmdebstrap copies the host's `etc/hostname` and `etc/resolv.conf` into the chroot; the first
customize hook deletes both (`build/mkiso.sh:237`). Varied by the guard: build B sets both the
kernel's hostname and `/etc/hostname` to `rebuild-b`.

### 3. User name and uid — held

- **Held in the initramfs.** Every `newc` member is written `uid 0, gid 0` whoever built it
  (`build/mkinitramfs.py:96-97`).
- **Closed in the ISO.** xorriso writes Rock Ridge records, and they carried the owner of
  `$ISO_TREE` on the build host — observed `uid 1001 gid 1001` on the root directory, `BOOT` and
  `EFIBOOT.IMG`, the `builder` user of `build/Dockerfile.isohost`. `-uid 0 -gid 0`
  (`build/mkiso.sh:486`) now writes every record as root; observed on the root directory of the
  2026-11-07 build. Varied by the guard: `runner` against a fresh `rebuilder`.

### 4. Clock — held

`SOURCE_DATE_EPOCH` is the commit's timestamp and is exported (`build/mkiso.sh:116-122`), so every
tool that reads it sees it. What it reaches:

- **The initramfs mtimes** (`build/mkinitramfs.py:175`) and the date in `/etc/aobs-release`
  (`build/mkiso.sh:267`), as before.
- **The ISO volume dates**, which xorriso takes from the environment. They read the wall clock
  (`2026-09-12 17:24:56` against an SDE of `16:58:53`) and now read the commit's time.
- **The ISO file and directory dates**, which xorriso does *not* take from the environment under
  `-as mkisofs`: measured on 1.5.6, with SOURCE_DATE_EPOCH exported, every record still carried its
  host mtime. `--set_all_file_dates` (`build/mkiso.sh:487`) pins them.
- **The FAT image.** mtools reads SOURCE_DATE_EPOCH (the string is in `mformat`'s binary); the volume
  serial is fixed by `-N` regardless (`build/mkiso.sh:468`). FAT stores local time, so the entry
  dates also depend on `TZ` — fact 6.
- **`bootx64.efi`** does not depend on the clock at all: `grub-mkstandalone` 2.12-1ubuntu7.3 produced
  the same binary from the pool's modules two seconds apart and with the config's mtime moved by
  three years. Measured, not read.

**The bytecode is gone.** The signing check imported the app in the chroot and left **338 `.pyc`
files in 37 directories** under `/opt`, timestamp-validated and recording the checkout's source
mtimes. It now runs under `python3 -B` (`build/mkiso.sh:241`); the 2026-11-07 build has no `.pyc`
under `/opt`. Nothing used them: each source's mtime in the initramfs is SOURCE_DATE_EPOCH, so each
one failed its timestamp check at boot and was recompiled in memory.

**The fallback is gone.** With no git metadata the build used `date +%s`; it now refuses to start.

Varied by the guard: build B starts after build A has finished, and is handed
`SOURCE_DATE_EPOCH=1`, which the script overrides with the commit's. Not looked at individually: the
bytecode Debian's own maintainer scripts compile under `/usr/lib/python3*` during mmdebstrap. Its
source mtimes come from the `.deb`s, and the guard agreeing says it did not vary across these two
builds.

### 5. Locale — held

No change was needed, and the guard varied it (`LC_ALL=C` against the runner's own environment). The
orderings that reach the image are locale-free: `mkinitramfs.py` sorts with Python's codepoint order
(`:125`). The host `sort` and `find` in stage 3d produce listings for `build/verify.py`, which are
not in the image. What maintainer scripts write under the host's locale was not read; the guard is
what says it does not reach the bytes.

### 6. Timezone — held

**Found by the guard's first run** (2026-11-07, run
[42390592651](https://github.com/allisson/aobs/actions/runs/42390592651)): build B, under
`TZ=Pacific/Chatham`, wrote an `efiboot.img` 56 bytes away from build A's under the runner's UTC, and
every other file in the ISO tree matched. FAT has no timezone field and stores local time, so mtools
turns SOURCE_DATE_EPOCH into the entry dates through `TZ`. Reproduced locally: one `bootx64.efi`, one
SOURCE_DATE_EPOCH, `TZ=UTC` and `TZ=Pacific/Chatham` write different images, while the locale and the
clock change nothing.

The script now exports `TZ=UTC` before anything else (`build/mkiso.sh:28`), which covers every tool
it runs rather than mtools alone. The one date the script formats itself already used `date -u`
(`build/mkiso.sh:267`). The next run, 42391685056, was green with the same variation.

### 7. umask — held

The build is unprivileged, and an unprivileged `tar -x` applies the caller's umask to every mode it
restores (`--no-same-permissions` is GNU tar's default for non-root). The rootfs is unpacked that way
(`build/mkiso.sh:253`), the staged Python layer and app tree are created under it
(`build/mkiso.sh:158-182`), and `mkinitramfs.py` writes each file's `st_mode` into its header. The
script now sets `umask 022` before anything else (`build/mkiso.sh:23`). Varied by the guard: build
B's caller runs under `umask 077`.

### 8. CPU count — held, measured on zstd alone

The one CPU-count-dependent flag in the build is `zstd -T0` (`build/mkiso.sh:415`), which sizes the
worker pool to the host. Measured 2026-11-07 on zstd 1.5.5, the host tool, against one initramfs
(6068 members, 128 MiB): `-T0` on an 8-CPU host and `-T1`, `-T2`, `-T3`, `-T4`, `-T8` and `-T16`
wrote the same bytes. Only `--single-thread`, which the build does not use, wrote different ones.
So a host with any number of CPUs writes the same initramfs.

This is *held* without a guard run that varied it, the one exception in this table, because no guard
can: every runner the guard has gets the same CPU count, and the measurement varies the one place the
count is read.

The build now runs the pinned pool's zstd 1.5.7 (`zstd_1.5.7+dfsg-1`), not the host's, so the
measurement was repeated on it, 2026-11-07, against the same initramfs (134,279,292 bytes
uncompressed), on a host reporting 8 CPUs: `-T0`, `-T1`, `-T2`, `-T3`, `-T4`, `-T8` and `-T16` all
wrote `63989a9c3f2a43dc770c9c288da07af063bbecea3c0f4c640021dbfa07e1f73e`; `--single-thread` wrote
`fd195f30…99a8`. The 1.5.5 result above is history, kept because it is what the guard's first
green run rested on.

### 9. Host kernel — unknown

The host kernel decides whether `--mode=unshare` works at all — `docs/boot-pipeline.md` records
where it does and where it does not — but nothing read so far writes a host-kernel fact into the
image. Observed once: the cross-host pair above, CI's runner kernel against OrbStack's, wrote
the same ISO. One pair is not a guard run, so the status stays.

### 10. Host architecture — refused

Stage 0 stops on anything but `x86_64` (`build/mkiso.sh:72-77`). That refuses a native foreign host;
it does not cover an amd64 container under emulation, which reports `x86_64` and is what
`build/mkiso-docker.sh` uses on an arm64 machine. Observed once: the cross-host pair above, amd64
emulated on an arm64 Mac, wrote the same ISO as a native amd64 runner once zstd matched. That is one
pair on one emulator, not a measurement of emulation in general.

### 11. Host filesystem — held

Not in the roadmap's list, and found by reading stage 3c. The RAM floor was derived from `du -sk` of
the unpacked rootfs, and `du` reports **allocated blocks**, which depend on the filesystem the build
runs on; the derived `RAM_REQUIRED_MIB` is substituted into `/init` (`build/mkiso.sh:362-365`). The
EFI image was sized the same way. Both now sum the files' own lengths (`build/mkiso.sh:356`, `:466`),
which no filesystem changes. Varied by the guard: build B runs on tmpfs.

## Not claimed

1. **That a host with different arranging tools reproduces the ISO.** Input 4 above, stated here
   from the other side. xorriso lays out the ISO, `mformat`/`mcopy` the EFI partition, the host's
   `depmod` writes `modules.dep*` into the rootfs, the host's pip
   writes each wheel's install metadata, and `grub-mkstandalone` assembles `bootx64.efi` from the
   pool's modules. A different version of any of them may write different bytes from identical
   inputs, and the contract does not promise otherwise.

   *Why the tools are not pinned too*: the harness group already pins mmdebstrap and xorriso
   at the snapshot, but using them means building inside an image made from that pool — a
   container — and on every host measured so far a container reaches stage 1 only `--privileged`
   (`build/mkiso-docker.sh`), while the build's unprivileged claim is measured on a bare
   `ubuntu-24.04` runner. Decided 2026-11-07, `docs/roadmap.md` M4; that ending stays available
   after v0.1 without reversing anything.

   *zstd is the exception, taken out of this item by evidence*: it differed between two real hosts,
   and it is one binary and one library that run extracted, with no install and no container. The
   same extraction was not tried for the tools above; none of them has yet differed between two
   hosts.

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
   and the cross-host pair at `244ec69` are that kind of corroboration and no more.

## What changes this document

A fact moves to *held* only with the change that holds it out **and** a guard run that varied it;
until then a fact with the change and no such run is *closed*. Fact 8 is the stated exception. A fact may be added; none may be
removed without saying here why it no longer applies. When the open question in *Not claimed* is
closed, item 1 moves into the contract or stays out of it by decision, and the README's *On
reproducibility* paragraph changes with it.
