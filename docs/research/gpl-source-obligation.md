# Does the aports pointer satisfy the GPL, and does Alpine keep the distfiles?

Research for [#70](https://github.com/allisson/aobs/issues/70), under the map
[Producing the ISO](https://github.com/allisson/aobs/issues/54). **This file surfaces facts; it does
not make the decision the ticket blocks.**

Every observation below was made on **2026-09-01** against `distfiles.alpinelinux.org`,
`dl-cdn.alpinelinux.org`, `gitlab.alpinelinux.org`, `mirrors.alpinelinux.org`, `www.gnu.org`, GitHub
and the Internet Archive, using this repo's own `build/inputs.sha256` as the package set. Commands
are given so a reader can re-run them. Licence texts are quoted from the canonical texts, not
paraphrased.

---

## Short answer

**The two halves come out in opposite directions, and that is the finding.**

**Distfiles retention is good — much better than `.apk` retention, and better than #57 assumed.**
`distfiles.alpinelinux.org` is partitioned per release branch and *accumulates*: superseded versions
are kept beside current ones, and the branch directories go back to **v3.10** (2019). Every one of
the **123 upstream source tarballs** this repo's 114 origin aports name is fetchable today, and for
the three packages `NOTICE` names — busybox, kbd, grub — the full chain verifies end to end:
`.PKGINFO` commit → APKBUILD at that commit → `sha512sums` → the tarball on distfiles, **byte-for-byte
match**. `NOTICE:48-51`'s claim that distfiles retention is "plausibly as lossy as its `.apk`
retention" is, as of today, **false**.

**But the pointer still does not discharge the GPLv2 obligation, and for a reason `NOTICE` does not
address.** GPLv3 §6(d) explicitly permits Corresponding Source on "a different server (operated by
you or a third party)" — with clear directions, and with the distributor still "obligated to ensure
that it is available." GPLv2 §3 has **no such allowance**: its only network route is "offering
equivalent access to copy the source code **from the same place**." Nine of our origin aports (18
`.apk` files) are GPLv2-only-family with no "or later" escape — **busybox among them** — and for those
the third-party pointer is not one of the three permitted routes.

**The FSF's own FAQ says the same, and only under GPLv3.** Asked our exact question — binaries on one
server, source on another — it answers "Yes. **Section 6(d)** allows this", with clear instructions
and a duty to keep the source available; it offers no GPLv2 route. And the one entry addressing a
recipes-only pointer rejects it, for the reason this file measures: "a user that wants the source a
year from now may be unable to get the proper version from another site at that time" (§2.3).

Three further facts sharpen it:

- **`NOTICE`'s section titled "Written offer" is not a written offer.** It names where recipes are.
  GPLv2 §3(b) wants a promise to *give* a copy, valid three years. Neither §3(a) nor §3(b) is met.
- **The recipe is not the Corresponding Source.** aports carries the patches and build scripts; the
  upstream tarball is the other half, and `NOTICE` does not mention distfiles at all.
- **The example trio is mis-selected.** Of "busybox, kbd and grub", only busybox is GPL-2.0-only;
  kbd is GPL-2.0-**or-later** and grub GPL-3.0-or-later, both of which *can* use §6(d).

**What archiving sources would cost**: **766.0 MB** for all 123 tarballs, **446.3 MB** for the
copyleft-touched subset, **180.8 MB** for the GPLv2-only family — of which 157.1 MB is one kernel
tarball pulled in by `linux-headers`. **Excluding it, the strict GPLv2 "same place" set is 23.7 MB.**

---

## 1. Does Alpine keep the distfiles?

### 1.1 The store is per-branch and goes back to 2019

```sh
curl -s https://distfiles.alpinelinux.org/distfiles/ | grep -oE 'href="[^"]+"'
```

Sixteen directories today: `edge/`, `buildlogs/`, and **`v3.10/` through `v3.24/`**. `v3.9/` and
everything older return **404**.

| branch dir | HTTP |
|---|---|
| `v3.2/`, `v3.5/`, `v3.8/`, `v3.9/` | **404** |
| `v3.10/` | **200** (4787 files) |
| `v3.23/` | **200** (13146 files) |
| `v3.24/` | **200** (12739 files) |

This is the structure `.apk` retention does not have. Alpine's package CDN carries exactly one
version per package per branch (#55, §1.1); distfiles carries **many**.

### 1.2 Superseded versions are kept, not deleted

Directly observable in a single listing. In `v3.23/`:

```
git-2.51.0.tar.xz  git-2.51.1.tar.xz  git-2.51.2.tar.xz  git-2.52.0.tar.xz
cryptography-46.0.2.tar.gz  46.0.3  46.0.5  46.0.7   (+ matching cryptography_vectors)
```

In `v3.24/`: `Python-3.14.3`, `3.14.5`, `3.14.7`; `grub-2.12.tar.xz` **and** `grub-2.14.tar.xz`;
`binutils-2.45.1` beside `binutils-with-gold-2.44`. Even `v3.10/`, EOL since 2021, still holds
`grub-0.97.tar.gz`, `gnupg-1.4.23`, `gnupg-2.2.15/16/19`, `linux-4.11`, `linux-4.19`.

**A bumped package does not evict its predecessor's source.** This is the opposite of the `.apk`
behaviour #55 measured, and it is why the two questions had to be measured separately rather than
reasoned across.

### 1.3 Every source our archive needs is there

Method — derived rather than assumed, from this repo's own inputs:

1. Parse the 182 `.apk` basenames out of `build/inputs.sha256`.
2. Match each against `APKINDEX` for `v3.24/main` and `v3.24/community` (28 641 stanzas).
   **182/182 matched, 0 missing.** Read each one's `o:` (origin aport), `L:` (licence) and `c:`
   (aports commit) fields. → **114 distinct origin aports.**
3. Fetch each origin's `APKBUILD` from `gitlab.alpinelinux.org` **at the exact commit `.PKGINFO`
   records**. → **114/114 fetched, HTTP 200, no failures.** The pointer `NOTICE` promises is live and
   complete, not just for busybox/kbd/grub.
4. Source each APKBUILD in a shell and expand `$source`. → **0 origins failed to parse**;
   **123 remote tarballs** and **247 local files** (patches, configs, init scripts — these live in
   aports git, so the recipe pointer does cover them).
5. `HEAD` each of the 123 against `distfiles/v3.24/` and against its own upstream URL.

| | present |
|---|---|
| on `distfiles/v3.24/` | **122 / 123** |
| the one miss, `apk-tools-v3.0.8.tar.gz`, on `distfiles/edge/` | **present** |
| **across `{v3.24, edge}`** | **123 / 123** |
| at the upstream URL today | 119 / 123 |

The `apk-tools` miss is instructive, not an anomaly: the branch directory records what the *branch*
builders fetched. A package built on edge and later pulled into the branch leaves its distfile only
in `edge/` — and `edge/` is a moving target. A rebuilder must be told to look in both.

### 1.4 The chain verifies end to end for the packages `NOTICE` names

For each of busybox, kbd and grub: take the aports commit recorded in the package's own `.PKGINFO`,
fetch the APKBUILD at that commit, read its `sha512sums`, download the named tarball from
`distfiles/v3.24/`, hash it.

| package | aports commit | distfile | bytes | sha512 vs APKBUILD |
|---|---|---|---|---|
| `busybox` | `c3ef5d10e6ef6528852c51f0564963e2f8c1be19` | `busybox-1.37.0.tar.bz2` | 2 565 764 | **match** |
| `kbd` | `8b9313df10ed04f8840a6437d3187341a1cbdaa5` | `kbd-2.8.0.tar.gz` | 2 958 768 | **match** |
| `grub` | `507b6419f67731e13ad07794b80c23c9df70330d` | `grub-2.14.tar.xz` | 7 725 668 | **match** |

So the mechanism `NOTICE` describes *works today*, and works better than `NOTICE` claims. The
question left is not whether it works but whether it is permitted, and how long it lasts.

### 1.5 Upstream is already lossy — distfiles is what is holding

Four of the 123 upstream URLs did not answer 200. One is a real, persistent loss:

| origin | tarball | upstream today | on distfiles |
|---|---|---|---|
| `ncurses` | `ncurses-6.6-20260516.tgz` | **404** (invisible-mirror rotates `current/` snapshots) | **200** |
| `acl` | `acl-2.3.2.tar.gz` | 502 on first probe, **200** on retry | 200 |
| `freetype` | `freetype-2.14.3.tar.xz` | **502** on every probe this session | 200 |
| `attr` | `attr-2.5.2.tar.gz` | **502** on every probe this session | 200 |

`freetype` and `attr` are both on Savannah, which returned 502 throughout this session; that is
plausibly a Savannah outage, not a deletion, and **this file does not conclude they are gone**.
`ncurses` is different: the URL pattern is a rolling snapshot directory, and the file Alpine pinned
is simply no longer there.

**One of our 123 sources is unobtainable from upstream on day one.** Any plan that says "the
rebuilder can just fetch from upstream" is already wrong by at least one package.

### 1.6 The retention history: one deletion in twelve years

Measured against Internet Archive snapshots of the `distfiles/` index (`id_` raw captures, so no
Wayback rewriting):

| snapshot | branch directories present |
|---|---|
| 2014-07-13 | `v3.0` |
| 2017-05-17 | `v3.0` … `v3.6` |
| 2020-02-25 | `v3.2` … `v3.11` |
| 2023-01-30 | `edge`, `v3.2` … `v3.17` |
| 2025-01-23 | `edge`, `v3.2` … `v3.21` (21 dirs) |
| **2025-09-06** | `edge`, **`v3.2` … `v3.9`** … `v3.22` (22 dirs) |
| **2026-01-20** | `edge`, **`v3.10`** … `v3.23` (15 dirs) — **`v3.2`–`v3.9` gone** |
| 2026-05-09, 2026-06-13 | `edge`, `v3.10` … `v3.24` (16 dirs) |

For **eleven years the store only grew.** Then, in a window between **2025-09-06 and 2026-01-20**,
eight legacy branches were deleted at once. After that, `v3.24` was *added* without anything else
being removed.

This is a materially different risk shape from #55's finding. `.apk` deletion is **continuous and
automatic** — it happens on every version bump, silently, as a consequence of how the repository
works. Distfiles deletion is **discrete and administrative** — it happened once, to branches four to
eleven years past EOL, and was survivable with a year's warning if anyone had been watching.

**But it is not a policy.** No Alpine announcement, wiki page or documented retention rule for
distfiles was found (see §4). Whether the 2025 cleanup was capacity-driven, EOL-driven, or a
keep-last-15-branches rule cannot be distinguished from one deletion event, and a single-event
sample supports no forecast. The honest statement is: *distfiles has been kept for a decade, and was
pruned once, on a schedule nobody has published.*

### 1.7 Distfiles is one host, with no CDN and no mirrors

This is where distfiles is *worse* than the package CDN.

```sh
dig +short distfiles.alpinelinux.org   # -> deu5-dev1.alpinelinux.org. -> 172.105.82.32  (one host)
dig +short dl-cdn.alpinelinux.org      # -> dualstack.j.sni.global.fastly.net. -> 4 anycast addrs
curl -sI https://distfiles.alpinelinux.org/distfiles/v3.24/busybox-1.37.0.tar.bz2 | grep -i server
# server: nginx        (no Via, no X-Served-By, no X-Cache — not behind a CDN)
```

And the mirror network does not carry it. Probing **all 106 mirrors** in
`https://mirrors.alpinelinux.org/mirrors.json` for
`<root>/distfiles/v3.24/busybox-1.37.0.tar.bz2`:

- 98 → 404, 1 → 403, 1 → 500, 5 → connection error/timeout, **1 → 200**.
- The single 200, `mirrors.sdu.edu.cn`, is a **false positive**: it answers 200 with a
  `text/html` error page for *any* path under `/distfiles/`, including the fabricated filename
  `definitely-not-a-real-file-xyz.tar.gz`.

**0 of 106 official mirrors serve Alpine distfiles.** The package CDN has Fastly plus 106 mirrors;
distfiles has one nginx box — and the name it resolves through, `deu5-dev1.alpinelinux.org`, reads
like a development host rather than a service given a durable identity. That is an inference from a
hostname and nothing more, but it is the only signal available about how Alpine regards this
service's permanence, and it does not point the reassuring way.

So the two halves of the availability picture invert: distfiles **retains** far better than the CDN
and is **served** far worse.

---

## 2. Does a recipe pointer discharge the obligation?

### 2.1 What GPLv2 §3 actually permits

Quoted from `https://www.gnu.org/licenses/old-licenses/gpl-2.0.txt`, verbatim:

> 3. You may copy and distribute the Program (or a work based on it, under Section 2) in object code
> or executable form under the terms of Sections 1 and 2 above provided that you also do **one of the
> following**:
>
> **a)** Accompany it with the complete corresponding machine-readable source code […] on a medium
> customarily used for software interchange; or,
>
> **b)** Accompany it with a **written offer, valid for at least three years**, to give any third
> party, for a charge no more than your cost of physically performing source distribution, a complete
> machine-readable copy of the corresponding source code […]; or,
>
> **c)** Accompany it with the information you received as to the offer to distribute corresponding
> source code. (This alternative is allowed **only for noncommercial distribution** and only if you
> received the program in object code or executable form with such an offer, in accord with
> Subsection b above.)

and, on network distribution:

> If distribution of executable or object code is made by offering access to copy from a designated
> place, then offering equivalent access to copy the source code **from the same place** counts as
> distribution of the source code, even though third parties are not compelled to copy the source
> along with the object code.

Three observations, each load-bearing:

1. **There is no third-party-server route.** The network paragraph says *the same place*. A release
   asset on GitHub and a tarball on `distfiles.alpinelinux.org` are not the same place under any
   reading that gives the phrase content.
2. **§3(c) is not available to us.** It is limited to noncommercial distribution *and* requires that
   we received the binaries with a §3(b) written offer. We did not: we fetched them from a CDN.
3. **§3(b) is a promise, not a pointer.** It obliges the distributor to hand over a copy for three
   years. Naming somebody else's git tree is not that promise.

**What GPLv2 defines as the source** also matters here:

> The source code for a work means the preferred form of the work for making modifications to it.
> For an executable work, complete source code means all the source code for all modules it contains,
> plus any associated interface definition files, plus **the scripts used to control compilation and
> installation** of the executable.

The aports recipe is the *scripts*. The upstream tarball is the *source code*. `NOTICE` points at the
first and is silent about the second — it does not name distfiles at all. Even read charitably as a
pointer, the pointer is to half the object.

### 2.2 What GPLv3 §6 permits, and the duty it attaches

Quoted from the canonical GPL-3.0 text, §6(d), verbatim:

> **d)** Convey the object code by offering access from a designated place (gratis or for a charge),
> and offer equivalent access to the Corresponding Source in the same way through the same place at
> no further charge. You need not require recipients to copy the Corresponding Source along with the
> object code. **If the place to copy the object code is a network server, the Corresponding Source
> may be on a different server (operated by you or a third party) that supports equivalent copying
> facilities, provided you maintain clear directions next to the object code saying where to find the
> Corresponding Source. Regardless of what server hosts the Corresponding Source, you remain
> obligated to ensure that it is available for as long as needed to satisfy these requirements.**

GPLv3 **fixes exactly the gap GPLv2 leaves**, and it is the difference between the two licences that
decides this ticket. But the allowance is conditional twice over:

- *"clear directions next to the object code"* — `NOTICE` travels inside the archive, beside the
  binaries. This condition is plausibly already met, if the directions named distfiles.
- *"you remain obligated to ensure that it is available for as long as needed"* — this is a
  **durability duty on us**, discharged through infrastructure **we do not control** and which §1.6
  shows has been wholesale-deleted once and §1.7 shows runs on a single unmirrored host. A disclaimer
  saying availability is not promised does not lift a duty the licence assigns.

And §1's definition of what must be available:

> The "Corresponding Source" for a work in object code form means all the source code needed to
> generate, install, and (for an executable work) run the object code and to modify the work,
> **including scripts to control those activities**.

Same shape as GPLv2: recipe *plus* upstream source, not recipe alone.

### 2.3 The FSF's own reading agrees, and is narrower than the licence text alone

`www.gnu.org/licenses/gpl-faq.html`, fetched 2026-09-01. Four entries are directly on point, and the
striking thing is not any single answer but **which licence each answer is given under**.

> **Can I put the binaries on my Internet server and put the source on a different Internet site?**
> (`#SourceAndBinaryOnDifferentSites`)
> Yes. **Section 6(d)** allows this. However, you must provide clear instructions people can follow to
> obtain the source, and **you must take care to make sure that the source remains available for as
> long as you distribute the object code.**

This is our exact question, and the FSF answers it **only under GPLv3 §6(d)**. It offers no GPLv2
equivalent — consistent with §2.1, where GPLv2 §3 has no such route to offer. The durability duty is
restated in the FSF's own words, and it is unconditional on who runs the server.

> **Am I complying with GPLv3 if I offer binaries on an FTP server and sources by way of a link to a
> source code repository in a version control system, like CVS or Subversion?** (`#SourceInCVS`)
> This is acceptable as long as the source checkout process does not become burdensome or otherwise
> restrictive. […] Users should be provided with clear and convenient instructions for how to get the
> source **for the exact object code they downloaded** — they may not necessarily want the latest
> development code, after all.

Good news for the GPLv3 half of the archive: a VCS link is explicitly blessed, and the "exact object
code" requirement is precisely what the per-package `c:` commit in the archive's `NOTICE` satisfies
(§1.3). Again scoped to GPLv3.

> **Can I make binaries available on a network server, but send sources only to people who order
> them?** (`#AnonFTPAndSendSources`)
> […] you can alternatively provide instructions for getting the source from another server, or even
> a version control system. No matter what you do, **the source should be just as easy to access as
> the object code**, though. **This is all specified in section 6(d) of GPLv3.**

A bar worth noting against §1.7: the object code is a GitHub release asset; the source would be one
unmirrored nginx host. Whether that clears "just as easy to access" is arguable, and nobody has argued
it.

> **I want to distribute binaries, but distributing complete source is inconvenient. Is it ok if I
> give users the diffs from the "standard" version along with the binaries?**
> (`#DistributingSourceIsInconvenient`)
> This is a well-meaning request, but this method of providing the source doesn't really do the job.
> **A user that wants the source a year from now may be unable to get the proper version from another
> site at that time.** […] So you need to provide complete sources, not just diffs, with the binaries.

This is the closest thing in the FAQ to a verdict on our current posture, and it is unfavourable. The
aports recipe **is** the diffs-and-scripts half; distfiles **is** the "another site"; and the FSF's
stated reason for rejecting the arrangement is exactly the durability worry §1.6 and §1.7 measure.

One more, confirming §2.1's third point:

> **I downloaded just the binary from the net. If I distribute copies, do I have to get the source and
> distribute that too?** (`#UnchangedJustBinary`)
> Yes. The general rule is, if you distribute binaries, you must distribute the complete corresponding
> source code too. **The exception for the case where you received a written offer for source code is
> quite limited.**

We fetched the `.apk` files from a CDN, with no written offer attached, so §3(c) is not available to
us — the FSF's "quite limited" exception is the one we do not qualify for.

**Net effect: the FAQ confirms the reading in §2.1 and §2.2 and tightens it.** Every permission the
FSF grants for source-on-another-site is granted under GPLv3 §6(d); the one entry that addresses a
recipes-only pointer rejects it, on third-party-site durability grounds.

### 2.4 `NOTICE`'s "Written offer" section is not a written offer

`NOTICE:41-53` is headed **Written offer** and reads, in full:

> The corresponding build recipes for each redistributed package are those in the Alpine aports tree
> […] at the commit named for that package in the archive's `NOTICE`.
>
> **Buildable upstream sources are explicitly not promised.** […] What the recorded commits do
> guarantee is **locatable recipes in a history that does not expire.**

Read against §2.1, this is:

- **not §3(a)** — nothing is accompanied by source;
- **not §3(b)** — it makes no offer to give anyone a copy of anything, for any period;
- **not the "same place" route** — the place is `gitlab.alpinelinux.org`;
- **not §3(c)** — unavailable to us, per §2.1.

The heading claims a licence route the body does not take. That is a documentation defect
independent of whichever posture the project settles on.

### 2.5 Which packages are actually affected, and by which licence

Licence census over the 182 `.apk` files in `build/inputs.sha256`, read from Alpine's own `L:` field:

| scope | source bytes | origin aports | `.apk` files |
|---|---|---|---|
| every origin in the archive | **766.0 MB** | 113 | 181 |
| copyleft-touched (any GPL / MPL-2 / EPL / CDDL term) | **446.3 MB** | 48 | 80 |
| **GPLv2-only family** (no "or later" → §6(d) unavailable) | **180.8 MB** | 9 | 18 |

*(113/181 rather than 114/182: `build-base` is a meta-package with an empty `source=`, so it has no
tarball to size. `apk-tools` is counted, at 0 bytes — its distfile is in `edge/`, not `v3.24/`.)*

The GPLv2-only-family set, in full:

| source bytes | origin | declared licence |
|---|---|---|
| 157.14 MB | `linux-headers` | GPL-2.0-only |
| 10.64 MB | `util-linux` | BSD-3-Clause; **LGPL-1.0-only**; LGPL-2.1-or-later |
| 8.13 MB | `git` | GPL-2.0-only |
| 2.57 MB | **`busybox`** | GPL-2.0-only |
| 2.18 MB | `lddtree` | GPL-2.0-only |
| 0.12 MB | `pax-utils` | GPL-2.0-only |
| 0.04 MB | `mkinitfs` | GPL-2.0-only |
| 0.02 MB | `alpine-baselayout` | GPL-2.0-only |
| (in `edge/`) | `apk-tools` | GPL-2.0-only |

**Two things fall out of this table.**

First, **`NOTICE:31` picks the wrong examples.** "busybox, kbd and grub among them" suggests the three
hardest cases. In fact `kbd` is **GPL-2.0-or-later** and `grub` is **GPL-3.0-or-later** — both carry
the "or later" escape, so a recipient may take GPLv3 terms and §6(d)'s third-party-server allowance
applies to them. Busybox is the one of the three with no escape. The sentence names two easy cases
and one hard one, and reads as if all three were the same.

Second, **the strict problem is small.** `linux-headers` is 157.1 MB of the 180.8 — and it is a
toolchain package whose distfile is a vanilla kernel tarball, the same *kind* of artifact the archive
already carries one of (`linux-6.12.106.tar.xz`, `build/inputs.sha256`). **Without it, the entire
GPLv2-only-family source set is 23.7 MB** — under 7% of the 360 MB archive #57 was weighing.

### 2.6 What other redistributors of Alpine binaries actually do

**Alpine itself** hosts the recipes (`gitlab.alpinelinux.org/alpine/aports`) **and** the corresponding
sources (`distfiles.alpinelinux.org`), both on its own infrastructure, both partitioned by the same
release branch. That is the "same place" discharge, done by the party with the standing to do it.
We are not in that position: we redistribute Alpine's binaries from GitHub release assets, and we
control neither server.

**The Docker Official Image for `alpine`** is the largest redistributor of these exact binaries there
is, and it is the useful comparison because its distribution shape is ours — binaries in a release
artifact, sources nowhere in it. Three primary sources, all fetched 2026-09-01:

- **The Docker Hub page** (`docker-library/docs`, `alpine/README.md:86-94`) has a `# License` section
  that offers a link to `pkgs.alpinelinux.org` for "license information for the software contained in
  this image" — **licence information, not source**. It then says: *"As for any pre-built image usage,
  it is the image user's responsibility to ensure that any use of this image complies with any
  relevant licenses for all software contained within."*
- **`alpinelinux/docker-alpine`**, the image's own repository, has **no licence or source section at
  all** in its README.
- **`docker-library/repo-info`** is the closest thing to our `NOTICE`: per tag, per package, it
  records description, **`license:`** (the same SPDX string from the same `L:` field we read in
  §2.5), installed size, and a `webpage:` link — `git.alpinelinux.org/cgit/aports/tree/main/<origin>`.
  **That link carries no commit.** It resolves to the *current* recipe, not the one that built the
  binary in the image.

So the largest redistributor of Alpine binaries does **strictly less than our `NOTICE` already does**:
no source, no written offer, and a recipe pointer that is not version-pinned — where ours pins the
exact per-package commit and was measured at 114/114 resolving (§1.3). Its stated position is to push
the compliance question onto the downstream user.

**This is a fact about practice, not about legality, and it is not a defence.** "Everyone does it"
does not appear in GPLv2 §3 or GPLv3 §6, and the FSF entries in §2.3 do not soften for scale. The
finding is worth recording for exactly one reason: it establishes that no widely-followed convention
exists for this distribution shape that we could adopt and rely on. There is no industry norm here to
match — only a common practice of not addressing it, which this project's stated bar (a stranger boots
this ISO with real funds) is a deliberate choice not to meet.

**postmarketOS could not be observed.** Every postmarketOS host — `wiki.postmarketos.org` and
`gitlab.postmarketos.org` alike — sits behind an Anubis proof-of-work bot gate that answers every
scripted request, real page or not, with an identical challenge page. Its practice is **not** recorded
here, and the 7448-byte responses noted in an earlier draft of this file were that gate, not content.

---

## 3. Facts the decision now has

Stated so the decision in #57 can be re-opened against evidence rather than assumption.

1. **#57's stated premise is false as written.** `NOTICE:48-51` says distfiles retention is
   "unverified and plausibly as lossy as its `.apk` retention". It is now verified, and it is
   **not** as lossy: distfiles accumulates superseded versions and holds branches back to v3.10
   (§1.1, §1.2). Whatever posture the project keeps, that sentence must change, because it is the
   stated reason for the posture.

2. **All 123 sources are obtainable today, and the recipe pointers all resolve** (§1.3, §1.4). The
   mechanism is not broken; the question is licence permission and durability.

3. **GPLv3 and GPLv2 diverge, and the split is measurable**: §6(d) allows a third-party server for the
   GPLv3 and "or later" packages; GPLv2 §3 allows it for none. **9 origins / 18 `.apk` files** are in
   the GPLv2-only family, busybox among them (§2.5).

4. **The FSF's own FAQ confirms the split and rejects the recipes-only shape** (§2.3). Every
   permission it grants for source-on-another-site is granted under GPLv3 §6(d), never under GPLv2;
   and `#DistributingSourceIsInconvenient` refuses a diffs-and-scripts pointer precisely because the
   other site may not have the right version later. It also *helps* the GPLv3 half: `#SourceInCVS`
   blesses a VCS link, and asks for instructions naming "the exact object code" — which is what the
   archive's per-package `c:` commit already provides.

5. **Even under §6(d), the durability duty stays with us** — "you remain obligated to ensure that it
   is available" — and the host is a **single unmirrored nginx box** (§1.7) that was wholesale-pruned
   once, in a window between 2025-09-06 and 2026-01-20, on no published policy (§1.6).

6. **The byte cost is now a number, not a fear.** 766.0 MB for everything; **446.3 MB** for the
   copyleft-touched subset; **180.8 MB** for the strict GPLv2-only family; **23.7 MB** for that family
   minus the `linux-headers` kernel tarball (§2.5). #57 weighed "multiplying a 360 MB archive"; the
   narrowest honest scope is **under 7%** of it.

7. **`NOTICE`'s "Written offer" heading names a licence route its text does not take** (§2.4), and its
   example trio mis-selects two easy cases as if they were hard (§2.5). Both are defects regardless of
   which posture is chosen.

8. **There is no industry norm to adopt.** The Docker Official Image for `alpine` — the largest
   redistributor of these binaries — offers no source, no written offer, and a recipe pointer with no
   commit in it, and disclaims compliance onto the downstream user (§2.6). Our `NOTICE` already does
   more than that. This is not a defence, and §2.3 does not soften for scale; it means only that
   nothing widely-followed exists to copy.

9. **Upstream is already lossy at t=0**: `ncurses-6.6-20260516.tgz` 404s upstream today and survives
   only on distfiles (§1.5). "The rebuilder can fetch from upstream" is false for at least one package
   on the day of release.

The three options the ticket names, re-stated with the measurements attached:

- **Archive buildable sources.** Costs 23.7 MB (GPLv2-only family, no kernel), 180.8 MB (with it),
  446.3 MB (all copyleft), or 766.0 MB (everything). Converts the obligation from a pointer we cannot
  guarantee into a §3(a)/§6(a)-shaped accompaniment we control, and simultaneously repairs the
  reproducibility story for a rebuilder who wants to rebuild rather than re-verify.
- **Make `NOTICE` a real written offer.** Cheap in bytes, but §3(b) binds us to supply a copy for
  three years — which in practice means keeping the sources anyway, just privately, and being the
  party who is asked. It does not avoid the storage; it hides it.
- **Keep #57's posture.** Requires, at minimum, rewriting the false premise in `NOTICE:48-51`, fixing
  the "Written offer" heading, naming distfiles as well as aports, and accepting that for 18 GPLv2-only
  `.apk` files no permitted GPLv2 §3 route is being taken.

---

## 4. What was not established

Recorded because these gaps bound how far the facts above can be pushed.

- **No lawyer reviewed this.** §2 is a reading of the licence texts, quoted verbatim so the reading
  can be checked. It is not legal advice, and the "same place" phrase in GPLv2 §3 has no definition
  inside the licence.
- **The prior-art survey is partial.** Alpine's own practice and the Docker Official Image's are
  recorded from primary sources (§2.6). **postmarketOS is not**: every postmarketOS host sits behind
  an Anubis proof-of-work gate that returns an identical challenge page to any scripted request, so
  nothing about its practice was read. `wiki.alpinelinux.org` likewise returns **403** to scripted
  fetches, `action=raw` and `Special:Export` included, with a browser user-agent — which is why no
  Alpine wiki page is cited anywhere in this file. Both need a real browser, not another retry.
- **No Alpine retention policy for distfiles was found.** The 2025 deletion window in §1.6 is
  inferred from Internet Archive snapshots, not from an Alpine announcement, and one event cannot
  distinguish a capacity cleanup from an EOL rule from a keep-last-N rule.
- **Licences are as Alpine declares them.** The census in §2.5 reads the `L:` field of Alpine's own
  `APKINDEX`, the same metadata `build/apkindex.py` uses. It was **not** audited against the packages'
  actual `COPYING` files. A declared SPDX expression can be wrong, stale, or incomplete — and for a
  compliance decision that is a real limitation, not a formality.
- **The appliance/toolchain split of the byte figures was not separated.** Which package belongs to
  which closure is recorded in `CLOSURES.txt` *inside a built archive*, and this session did not build
  one. Every figure in §2.5 is archive-scope — both closures — which is the right scope for the
  obligation, since the archive redistributes both, but it means "what would it cost for the ISO
  alone" is unanswered.
- **Dependency-closure completeness was not re-derived.** The 182 `.apk` set is taken from
  `build/inputs.sha256` as committed; this file did not re-resolve it.
- **The `freetype` and `attr` upstream 502s were not resolved.** Both are Savannah, both failed on
  every retry this session. They are recorded as *unavailable during this session*, not as gone.
- **Nothing was measured about how distfiles behaves under load, or whether it has any SLA.** The
  single-host finding in §1.7 is a DNS and header observation, not an availability measurement.

---

## 5. Reproducing these observations

```sh
# 1.1 — the store is per-branch, back to v3.10
curl -s https://distfiles.alpinelinux.org/distfiles/ | grep -oE 'href="[^"]+"'
for b in v3.9 v3.10 v3.24; do
  printf '%-6s %s\n' "$b" "$(curl -s -o /dev/null -w '%{http_code}' \
    https://distfiles.alpinelinux.org/distfiles/$b/)"
done

# 1.2 — superseded versions are kept
curl -s https://distfiles.alpinelinux.org/distfiles/v3.23/ \
  | grep -oE 'href="git-2\.5[12][^"]*"'

# 1.3/1.4 — origin, licence and aports commit come from Alpine's index; the chain then verifies
curl -s https://dl-cdn.alpinelinux.org/alpine/v3.24/main/x86_64/APKINDEX.tar.gz \
  | tar -xzO APKINDEX | awk -v RS='' '/(^|\n)P:busybox\n/'      # -> o:, L:, c:

c=c3ef5d10e6ef6528852c51f0564963e2f8c1be19   # the c: field above, busybox 1.37.0-r31
curl -s "https://gitlab.alpinelinux.org/alpine/aports/-/raw/$c/main/busybox/APKBUILD" \
  | grep -A3 sha512sums=
curl -s https://distfiles.alpinelinux.org/distfiles/v3.24/busybox-1.37.0.tar.bz2 | sha512sum

# 1.6 — the retention history
curl -s 'http://web.archive.org/cdx/search/cdx?url=distfiles.alpinelinux.org/distfiles/&output=json&filter=statuscode:200&collapse=timestamp:6'
curl -s 'https://web.archive.org/web/20250906225336id_/https://distfiles.alpinelinux.org/distfiles/' \
  | grep -oE 'href="v3\.[0-9]+/"'

# 1.7 — one host, no CDN, no mirrors
dig +short distfiles.alpinelinux.org
dig +short dl-cdn.alpinelinux.org
curl -sI https://distfiles.alpinelinux.org/distfiles/v3.24/busybox-1.37.0.tar.bz2 | grep -i '^server\|^via'
# and the false positive that makes the mirror sweep read 1/106 instead of 0/106:
curl -s -o /dev/null -w '%{http_code}\n' \
  https://mirrors.sdu.edu.cn/distfiles/v3.24/definitely-not-a-real-file-xyz.tar.gz   # -> 200
```

The §1.3 and §2.5 sweeps — 182 `.apk` → 114 origins → 123 tarballs → sizes and licences — were run as
a script over `build/inputs.sha256`, the two `APKINDEX` files, the 114 APKBUILDs, and a `HEAD` of each
tarball against both `distfiles/v3.24/` and its own upstream URL. Re-running it is the way to check
whether any of the numbers above have moved.
