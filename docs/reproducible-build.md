# The reproducibility contract

What `bitcoin-signer-amd64.iso` promises about how it was built. It is a property of the **build**,
checkable with no release in sight, which is why it lives here and not in `docs/release.md`.

The bar is the one `docs/threat-model.md` sets: **a claim that cannot be tested is not a claim.** So
each numbered claim below is phrased so that a command, a test or a CI job can contradict it.

The claim this document exists to make possible is not really about bytes. It is that **a stranger
who trusts nobody can rebuild the ISO and get the published sha256** — and that a maintainer accused
of shipping a backdoor can be rebutted by anyone with a container runtime, rather than by assurances.

## The claims

**1. The output is byte-identical on any host.** Build path, hostname, user, uid, clock, locale,
timezone, umask, CPU count, host kernel version **and host architecture** do not affect the ISO.

Architecture is in deliberately. The most important reproduction in this system is the maintainer's
offline arm64 build against CI's x86_64 witness; excluding architecture would put that comparison
outside the published claim, which is the one place it needs to be inside it. The cost is claim 2.

**2. `make -j` and `zstd -T` are fixed constants. Nothing in the build calls `nproc`.** `zstd`'s
output genuinely varies with the thread count; `make`'s does not, and it is pinned anyway, because
"nothing in the build reads the machine" is checkable and "only the one that matters" is a judgement
remade every time somebody edits the build.

*Checked by* `build/verify.py`'s `check_pinned_parallelism`, run in `mkiso.sh` stage 0 and driven
with hostile inputs by `tests/test_build_verifier.py`. `zstd -T0` is rejected specifically: it is a
literal integer that *means* one thread per core.

**3. `SOURCE_DATE_EPOCH` is the commit date of `HEAD`, derived by the build and never passed in.**

Not the tag date — an untagged working build has none, and a fallback is a second contract nobody
tests. Not a constant — a commit date makes the ISO's internal timestamps an assertion about *which
commit built it*.

**Consequence, written down because it will surprise someone: a rebase that rewrites commit dates
changes the ISO hash.** That is correct. The hash is a claim about a commit, and a rewritten commit
is a different commit.

*Checked by* the third of `docs/release.md`'s four refusals: a `SOURCE_DATE_EPOCH` that is not the
tagged commit's date means it was set by hand.

**4. Every byte the build consumes comes from `build/inputs/`, and the build touches no network.**

`build/fetch-inputs.sh` populates that directory — from Alpine's CDN today, from the unpacked release
asset in 2030. **There is no second build path**, which is the whole point: the divergence between
today and 2030 is confined to *fetching*, and the *building* is the same code path CI walks on every
commit rather than one nobody has exercised since it was written.

**5. `build/inputs/` is checked against `build/inputs.sha256` on hash and on set equality before
stage 1 runs, and the build refuses otherwise.**

The set equality is the half a naive implementation omits. A rebuilder in 2030 unpacks a release
asset into that directory; an unexpected `.apk` there must be a **failure and not an ignore**,
because `apk` resolving a closure against a local repository is exactly the kind of thing that would
pick one up.

The enforcement is in `mkiso.sh` and **not** in `fetch-inputs.sh`. Verification only in the fetcher
is verification a hand-populated directory walks straight past — and a hand-populated directory is
precisely what the 2030 path is.

*Checked by* `check_inputs`, with a wrong hash, a missing file and an extra file each driven as a
hostile input.

**6. The root of the build is a tarball, not a registry tag.** `build/Dockerfile.iso` is
`FROM scratch` plus `alpine-minirootfs-3.24.1-x86_64.tar.gz`. Alpine keeps every point release's
minirootfs forever with a `.sha256` and an `.asc` beside it; Docker Hub's retention for untagged
digests could not be established, and a Hub digest is checkable only by pulling from that registry.

**7. `bitcoin-signer-amd64.iso` and `aobs-inputs-vMAJOR.MINOR.tar` are both deterministic.** A
witness confirms the archive as well as the image, so a swapped input set is caught by the same
comparison that catches a swapped ISO.

**8. A rebuild that diverges says where.** `mkiso.sh` prints the sha256 of every intermediate it
already produced — the rootfs tree manifest, `bzImage`, `initramfs.zst`, `efi.img`, the ISO — and the
CI guard names the first rung that differs. The ladder lives in `mkiso.sh` rather than in a CI script
that re-derives the hashes, because a ladder in the CI job goes stale the day the build changes.

The rootfs rung is a **tree manifest**, not a hash of the archive: mode, owner and content hash per
path. A single number says two builds differ; a manifest says *which file*, and whether it differs in
content or in a permission bit. That is the difference between a useful report and "the hashes
differ".

`diffoscope` on the two ISOs is uploaded as a CI artifact to explain *why*. **`diffoscope` is a tool
a maintainer must obtain, never a verifier**: the "tools the reader already has" rule governs
verification UX, and debugging is not on that path.

## The ten divergence sources, and what fixed each

Every one of these was in the build before this contract existed. `SOURCE_DATE_EPOCH` was set
nowhere, so two independent builders got two different files and neither could rebut a claim that the
other had shipped a backdoor.

| # | Source | Fix, in `build/mkiso.sh` |
|---|---|---|
| 1 | `find . \| cpio` has no sort, so directory order leaks in | `find . -print0 \| LC_ALL=C sort -z \| cpio --null` |
| 2 | cpio member mtimes come from the filesystem | every path `touch -h -d @$SOURCE_DATE_EPOCH` first, plus `cpio --reproducible` for device and inode numbers |
| 3 | `grub-mkstandalone` embeds a memdisk tar carrying mtimes | `grub.cfg` is staged into `$WORK` and touched, rather than passed from a working tree whose mtimes are whatever `git checkout` set |
| 4 | `mkfs.vfat` stamps `efi.img` with a volume ID from the clock | `mkfs.vfat -i` with an ID derived from `SOURCE_DATE_EPOCH`; `BOOTX64.EFI` touched before `mcopy`, because mtools writes file dates into the FAT directory entry — in *local* time, which is why `TZ` is forced |
| 5 | `xorriso` writes ISO9660 creation timestamps and derives the volume UUID from them | `--modification-date=`, which sets all four volume timestamps at once |
| 6 | `zstd -T0` varies its output with the core count | `zstd -T1`, and `check_pinned_parallelism` rejects `-T0` |
| 7 | `apk` writes `/var/log/apk.log`, carrying the wall clock *and* its own `--root` and `--repositories-file` arguments — so `$WORK` and the bind-mount path ship inside the image | the log is removed with the rest of the apk residue, and `check_rootfs` names `apk.log` separately, because its basename is not `apk` |
| 8 | Alpine's `busybox` post-install creates the `klogd` user, and `adduser` stamps `/etc/shadow`'s last-change field with today in days since the epoch | every non-empty last-change field is rewritten to the `SOURCE_DATE_EPOCH` day |
| 9 | `KBUILD_BUILD_TIMESTAMP` was pinned to the label `aobs`. `usr/Makefile` passes it to `gen_initramfs.sh` as `-d "$KBUILD_BUILD_TIMESTAMP"`, which runs `date -d"$1" +%s \|\| :`; on a string that is not a date it drops the `-t` argument and stamps the built-in initramfs with the wall clock, and that reaches `bzImage` through `vmlinux` | `mkiso.sh` exports it as the `SOURCE_DATE_EPOCH` date, in a form `date -d` parses |
| 10 | `mkfs.fat`'s `-n` writes a volume-label *directory entry* whose creation and write times come from its own clock — four bytes inside `efi.img` that `-i` does not reach and that touching the payload cannot fix | `mkfs.vfat --invariant`, with `-i` after it so the volume ID stays derived from `SOURCE_DATE_EPOCH` rather than the constant |

Two environment facts sit alongside them. `LC_ALL`, `LANG`, `TZ` and `umask` are forced **inside
`mkiso.sh`** and not only in `Dockerfile.iso`, because `docker run -e` overrides an `ENV` and the
guard below deliberately varies them. So are `KBUILD_BUILD_USER`, `KBUILD_BUILD_HOST` and
`KBUILD_BUILD_TIMESTAMP`, the three values Kbuild otherwise reads off the machine: without them the
builder's user, hostname and clock end up inside `bzImage`. The timestamp cannot live in the
Dockerfile alone, because a default cannot know `SOURCE_DATE_EPOCH` — and source 9 is the reason it
must be a **date and not a label**. `include/generated/compile.h` accepts any string, so an
unparseable value looks correct in every place a reader would check; the only thing that catches it
is the guard's 37-hour clock push.

**What stays different between two builds, and why it does not matter.** `arch/x86/boot/*.o`,
`arch/x86/realmode/rm/{reboot,trampoline_64}.o` and all of `tools/objtool/` carry the absolute build
path in their debug info — those Makefiles set `KBUILD_CFLAGS` themselves and lose Kbuild's prefix
maps. None of it reaches the artifact: the boot objects are flattened by `objcopy -O binary` into
`setup.bin`, and `objtool` is a host tool whose own bytes are never shipped. Measured directly: with
the nine sources above fixed, two builds under the guard's full variation produce 79 differing files
in the kernel tree and an identical `bzImage`.

## The guard

`.github/workflows/reproducible.yml` builds the ISO **twice in one job** and fails on any differing
byte. The second build varies, all at once:

- the build path
- the hostname
- the clock, pushed forward 37 hours
- `TZ`, `LC_ALL` and `LANG`
- the umask, 022 → 077
- the CPU count, `--cpus=2` against the runner's full count

**The uid is not varied in the guard**, and the contract still claims it: stage 1 chroots into the
rootfs to run the in-rootfs signature assertions, so a non-root uid inside the container would fail
for a reason that has nothing to do with reproducibility. `cpio --reproducible` and the `touch` pass
are what neutralise ownership, and the release-time arm64/x86_64 comparison crosses a genuinely
different uid, user and host anyway.

The first four are free. **The CPU count costs real time and stays**, because it is what catches the
`zstd` hazard — the one divergence source whose fix a future edit could undo without any other
symptom.

**Architecture is in the contract but not in the guard.** An arm64 runner would emulate for hours.
It moves to `docs/boot-checklist.md` as a release-time human check, which is free, because the ritual
already compares the maintainer's arm64 build against CI's x86_64 witness build.

**Trigger: every release tag, and every pull request touching `build/`.** A tags-only guard learns
about decay at the worst possible moment — during a release, when the person who broke it is not the
person cutting it. The two halves cannot share one `push` filter: GitHub applies a `paths` filter to
tag pushes too and requires both to be satisfied, so `tags` plus `paths` in one block would skip the
guard for exactly the release tags it exists to protect.

**Written fallback, decided in advance rather than during the annoyance:** if the guard's first CI run
exceeds **40 minutes**, the trigger drops to tags plus `workflow_dispatch`. A guard slow enough to be
resented does not get made faster; it gets disabled.

The guard's runtime is an **estimate until it has run once**. So is whether a native amd64 kernel
build fits inside a free runner's 6-hour ceiling. Both are measured on the first run rather than
designed around a guess.

## What is not claimed

- **Nothing about the toolchain producing identical binaries across compiler versions.** The
  toolchain is pinned by exact version, which is a different and weaker statement, and the pinning
  is what makes claim 1 achievable rather than what makes it true.
- **Nothing about the image's integrity on a stick in your hand.** Reproducibility says the published
  bytes are the bytes this source produces. It says nothing about the bytes on your USB drive, which
  is `docs/release.md`'s signature chain, and nothing about a tampered medium between two boots,
  which `docs/threat-model.md` lists as adversary 4 and does not defend.
- **Nothing about upstream.** The archived `.apk` files, the minirootfs and the kernel tarball are
  pinned by sha256 against what Alpine and kernel.org published. That they are what those projects
  *meant* to publish is not something this build can establish.
