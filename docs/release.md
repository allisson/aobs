# Cutting a release

The ordered checklist, so that the release is not reconstructed from memory each time.

**The split between this document and `build/release-preflight.sh` is deliberate and specific: the
script enforces what a human cannot reliably check, the prose holds what a human must actually look
at.** Signing, publishing and the post-publish stranger's-eye verification stay manual with the
commands written out, because those are precisely the steps where a human's attention *is* the
control — and a script that performs them hides the thing being checked.

## The circularity, and how the order resolves it

The stage-3 assertion binds the version embedded in the image to `git describe --exact-match --tags`,
so **the tag must exist before the build**. But a tag pushed for a build that then fails is permanent
litter in a repository strangers clone.

**A local tag is retractable and a pushed one is not.** So the push moves after the build, and the
first irreversible act in this ritual is step 5.

## The checklist

**1. Clean tree on `main`, tests pass.**

```sh
git switch main && git pull --ff-only
git status --porcelain            # must be empty
docker run --rm -v "$PWD:/src" -w /src aobs-test
```

**2. Create the signed annotated tag — locally, not pushed.**

```sh
git tag -s v0.1.0 -m 'aobs v0.1.0'
```

**Never through the GitHub UI.** `main`'s HEAD is otherwise signed by GitHub's key
`B5690EEEBB952194`, not the maintainer's, and a tag created in a browser carries the platform's
signature rather than a person's. `SECURITY.md` holds the fingerprint this must be.

**3. Preflight the cheap half, fetch the inputs, then build.**

The tree and the tag first, because they are what a several-hour kernel compile should not be spent
discovering:

```sh
SOURCE_DATE_EPOCH=$(git log -1 --format=%ct) ./build/release-preflight.sh
```

This form's epoch check is the weaker one, and the script's header says why: `mkiso.sh` derives
`SOURCE_DATE_EPOCH` itself and ignores the environment, so comparing this shell's variable against the
tagged commit's date compares two values you just set from the same source. Step 4 runs it again with
the file the build wrote, which is the form that bites.

```sh
docker run --rm --platform=linux/amd64 -v "$PWD:/src" -w /src \
    alpine:3.24 sh build/fetch-inputs.sh
docker run --rm --platform=linux/amd64 -v "$PWD:/src" -w /src \
    alpine:3.24 sh build/fetch-sources.sh
docker build -f build/Dockerfile.iso -t aobs-iso .
mkdir -p out && docker run --rm --privileged -v "$PWD:/src" -v "$PWD/out:/out" aobs-iso
```

`fetch-sources.sh` populates `build/sources/` — ~456 MB, 48 origin aports, the corresponding source
for everything copyleft-touched the release redistributes (#71). It reads `build/inputs/`, so it runs
after `fetch-inputs.sh` and not before. **The build never opens it**: it is a release asset, not a
build input, which is why it has its own list rather than joining `build/inputs.sha256` — putting it
there would make every witness build and every 2030 rebuild download 456 MB the build is required to
have and required never to read.

Every file it fetches is checked against the `sha512sums` in the APKBUILD that named it, at the
commit the package's own `.PKGINFO` records — the same check `abuild` makes, against a list out of a
git history rather than off the host serving the bytes. Without `--refresh` it leaves
`build/sources.sha256` alone, so a source whose bytes moved shows up as a checksum failure during the
fetch; with `--refresh` it also rewrites the list, and a human commits that diff for the same reason
`build/inputs.sha256`'s is committed by hand.

The stage-3 assertion binds `/etc/aobs-release` to that tag. **Record the hash ladder the build
prints** — CI's witness build prints the same five rungs, and the first one that differs is where a
divergence began.

**4. Build the input archive and the manifest, and verify locally by running the published command
from the published instructions.**

`RELEASE_FILE` below is the `/etc/aobs-release` the build wrote into the rootfs. Extract it from the
initramfs, or take it from the builder's `$WORK/rootfs/etc/aobs-release`. The manifest's `release` and
`git-commit` are generated **from that file** (#61), which is what leaves the image and the manifest
nothing to disagree about — and it is what refusal 3 judges the epoch against.

```sh
RELEASE_FILE=/path/to/etc-aobs-release

mkdir -p release
cp out/bitcoin-signer-amd64.iso verify-release.sh ADVISORIES.txt release/

# One deterministic tar: sorted members, fixed mtime, uid, gid and mode, uncompressed —
# the .apk files and the kernel tarball are already compressed.
tar --sort=name --owner=0 --group=0 --numeric-owner \
    --mtime="@$(git log -1 --format=%ct)" --format=gnu \
    -C build -cf release/aobs-inputs-v0.1.0.tar inputs

# The source archive, same shape, same reasons. Separate asset because the build never reads it.
tar --sort=name --owner=0 --group=0 --numeric-owner \
    --mtime="@$(git log -1 --format=%ct)" --format=gnu \
    -C build -cf release/aobs-sources-v0.1.0.tar sources

python3 build/gather.py write-manifest . "$RELEASE_FILE" release >release/manifest-v0.1.0.txt
python3 build/gather.py manifest . release/manifest-v0.1.0.txt "$RELEASE_FILE" release

# All four refusals, now that there is a manifest and a release file to judge.
./build/release-preflight.sh "$RELEASE_FILE" release/manifest-v0.1.0.txt

gpg --detach-sign --armor --output release/manifest-v0.1.0.txt.asc release/manifest-v0.1.0.txt
gpg --detach-sign --armor --output release/ADVISORIES.txt.asc ADVISORIES.txt

cd release
gpg --verify manifest-v0.1.0.txt.asc manifest-v0.1.0.txt
grep -E '^[0-9a-f]{64}  ' manifest-v0.1.0.txt | sha256sum -c -
./verify-release.sh
```

The two raw commands are run **as the README prints them**, not as an equivalent. SeedSigner's first
signed release shipped a file that gave `gpg: not a detached signature`, and an outsider found it.
The cost of catching that here is thirty seconds.

`ADVISORIES.txt.asc` is produced here and **committed to the repository** as well as attached, because
#62 requires it to be in git history: a clone from any mirror must carry it, and an edit to a past
entry must show up in a diff. It is re-signed whenever a new entry is appended.

**5. Push the tag. This is the first irreversible act, and it happens only after the build has
succeeded.**

```sh
git push origin v0.1.0
```

**6. CI's witness build runs from the pushed tag** and publishes the hashes it got.

**It does not sign, today, and the release is therefore single-signed.** #58 created no witness key:
signing would need one in GitHub's secret store, and `verify-release.sh` hardcodes an empty
`KNOWN_WITNESS` rather than a placeholder fingerprint in the file strangers read to learn whom to
trust. The multi-signer layout exists and costs nothing to leave unused — when a key exists,
`witness.yml` gains a signing step, `verify-release.sh` gains one line, `verify.py`'s
`WITNESS_FINGERPRINT` gains one value, and the manifest gains one `signer:` line, with nothing already
published needing re-verification.

- **A witness that disagrees blocks the release, and the thing that blocks is this checklist rather
  than the workflow.** No CI job can block a publication CI does not perform: `witness.yml` builds,
  hashes, and uploads what it saw. Step 7 does not happen until that artifact has been read and its
  hash ladder found identical to the one step 3 printed. If they differ, that is a reproducibility
  defect, and the contract's position — a stranger who rebuilds and gets a different hash has found a
  defect, not a difference of opinion — has to bind us before it binds anyone else. Fix it and re-tag.

  ```sh
  gh run download --name witness && diff witness.txt your-own-ladder.txt
  ```
- **A witness that cannot run is a different case from one that disagrees.** On an infrastructure
  outage the release may be published single-signed: the witness signature is already non-fatal to
  verification, and the `signer:` lines make its absence visible rather than silent. **Publishing over
  a witness that ran and disagreed is never permitted.**

**7. Publish the Release — once.**

Assets: `bitcoin-signer-amd64.iso`, `aobs-inputs-v0.1.0.tar`, `aobs-sources-v0.1.0.tar`,
`manifest-v0.1.0.txt`, `manifest-v0.1.0.txt.asc`, `verify-release.sh`, `ADVISORIES.txt` and
`ADVISORIES.txt.asc`.

**The release notes open with the README's pre-trust banner, copied verbatim** — the section
`## v0.1.0 is a pre-trust release. Do not put real funds on it.` and everything under it, down to
the *Nothing else here is lowered* paragraph. Verbatim, not summarised: two wordings of one safety
claim drift, and the copy that drifts is always the one the reader met first. See *Pre-trust, and
what takes it off* below for when the banner stops being copied at all.

**`aobs-sources-v0.1.0.tar` is not optional and not a convenience.** It is the accompanying source
GPLv2 §3(a) requires for the 18 GPL-2.0-only `.apk` files in the input archive — §3(b) and §3(c) are
both unavailable to this project, and §3 grants no fourth route (#71). Publishing the input archive
without it redistributes those binaries under no permitted term. It carries the rest of the
copyleft-touched set too, so that no source claim in `NOTICE` depends on a host this project does not
control.

Everything but the manifest and the `.asc` files is named in the manifest's checksum block, so the
documented one-liner really does check every published file at once — **the verifier included**, which
matters, because a tampered `verify-release.sh` is a real attack.

**A single publication is the point**, and it is the reason step 6 waits for the witness rather than
publishing and appending. Adding a signature to an already-published `.asc` would mutate a signed
asset that strangers may already hold, with no way to tell a reader which version of it they got.
That constraint is what will still be true on the day a witness key exists.

**8. Re-verify the *published* assets as a stranger would, then refresh the README's advisory list.**

```sh
mkdir /tmp/stranger && cd /tmp/stranger
gh release download v0.1.0
gpg --verify manifest-v0.1.0.txt.asc manifest-v0.1.0.txt
grep -E '^[0-9a-f]{64}  ' manifest-v0.1.0.txt | sha256sum -c -
```

Downloaded, not copied from `release/`. What is being checked is what GitHub serves.

Every release's README must carry the **full advisory list** — that is one of #62's two discovery
mechanisms, and the only one that reaches a user who went to fetch a newer ISO without thinking to
look for advisories.

## The four refusals

`build/release-preflight.sh` runs these and does nothing else. Each fires only when something is
genuinely wrong, which is the design constraint: **a guard that fires during ordinary work gets
disabled, and then it guards nothing on the day it mattered.** A development build trips none of them,
because a development build never runs this.

1. **A dirty working tree.** An uncommitted edit is in the image and in nothing a stranger can check
   out.
2. **`HEAD` not at a signed annotated tag matching `vMAJOR.MINOR[.PATCH]`.**
3. **`SOURCE_DATE_EPOCH` not equal to the tagged commit's date.** A mismatch means it was set by
   hand, and the ISO's timestamps would then assert something about no commit at all.
4. **A manifest whose `git-commit` is not `HEAD`.** The signature covers the manifest *because* the
   manifest names the inputs; a manifest describing another commit signs nothing.

Already hard stops elsewhere and unchanged: the input-set equality in stage 0, the rootfs assertions
in stage 1, and the embedded-version check in stage 3.

**The judgement is not in the shell.** Every one of the four is a pure function in `build/verify.py`
fed a `GitFacts` value object gathered by `build/gather.py`, so `tests/test_build_verifier.py` drives
each refusal with a hostile input in milliseconds — instead of cutting a release to find out whether
a shell condition still bites.

## The manifest

One plain-text, line-oriented `manifest-<release>.txt`, readable with `cat`, with three kinds of
line:

- **`key: value` metadata** — `format`, `release`, `released`, `git-tag`, `git-commit`,
  `source-date-epoch`, `iso-name`, `alpine-branch`, `aports-commit`, `inputs-list-sha256`,
  `sources-list-sha256`, and `signer:` lines.
- **`input-*` fields** for upstream inputs. These live *inside* the archive, so a reader running the
  checksum command does not have them on disk; recording them as checksum lines would produce a
  spurious failure for everyone.
- **A contiguous block of `<sha256>  <name>` lines** for the files published beside the manifest, in
  `sha256sum -c` format exactly.

**The format was decided by measurement, not taste.** `sha256sum -c` cannot read a file containing
comments — pointed at the manifest whole, busybox coreutils prints `comment line: FAILED` and exits 1.
So the documented command is:

```sh
grep -E '^[0-9a-f]{64}  ' manifest-v0.1.0.txt | sha256sum -c -
```

One file, at the cost of a one-liner nobody would guess unaided. The alternative — a bare `SHA256SUMS`
plus a separate metadata file — splits the thing the signature covers, and the signature covers the
manifest *because* the manifest names the inputs.

`inputs-list-sha256` does the real work: it pins the archive to `build/inputs.sha256` **as committed at
the tag**, so a swapped archive is caught even if the asset were replaced in place.

`sources-list-sha256` is the same binding for `aobs-sources-<release>.tar` against
`build/sources.sha256`. #71 made the corresponding source an *accompaniment* rather than a pointer,
and an accompaniment nobody can pin is a pointer again — at whoever last uploaded the asset.

**Signers cannot disagree.** They sign the same file, so a divergence is CI declining to sign —
absence, not conflict. One good builder signature is the bar; a missing witness signature is reported,
not fatal. Multiple signers is one `.asc` holding concatenated detached signatures, which is literally
what Bitcoin Core's `SHA256SUMS.asc` is across 19 signers, verified by stock `gpg --verify`.

## Bumping a pin

```sh
docker run --rm --platform=linux/amd64 -v "$PWD:/src" -w /src \
    alpine:3.24 sh build/fetch-inputs.sh --refresh
git add build/inputs.sha256 && git diff --cached build/inputs.sha256
```

A human commits that diff, because **a changed hash for an unchanged version is exactly the
supply-chain event that should be visible in a pull request.**

**CI never runs `--refresh`.** CI's witness build fetches from the CDN *against the committed list*,
so it stays an independent reproduction rather than a replay of the builder's own bytes — and it fails
loudly the day a pin dies. Alpine's CDN keeps only the current version of each package (confirmed
against 7/7 official mirrors, with no archive host in existence), and measured churn puts roughly two
of this repository's pins dead within 79 days.

## Never yank

**A bad release stays downloadable.** Deleting it destroys the reproducibility archive to fix a
problem deletion does not fix: the bad ISO is already on the stranger's stick, and a user who can no
longer re-download it also can no longer confirm what they hold. This is universal practice across
Tails, Tor, Bitcoin Core and Coldcard. Remediation is `ADVISORIES.txt`, not deletion.

## Pre-trust, and what takes it off

`0.1.0` ships with a banner at the top of `README.md`, copied verbatim into the release notes,
saying it is a pre-trust release and not for real funds. That banner is the release's **only** safety
instrument: the appliance carries no mainnet lock, and the release identity footer identifies rather
than attests, so prose is what stands between a reader and a loss.

**A claim with no written retraction path becomes permanent by accident.** These are the three
conditions, and they are the exact negations of what the banner asserts, so the banner and its
retraction cannot drift apart:

1. **`docs/boot-checklist.md` run to completion on at least one machine outside this project**, and
   the run recorded — this negates the banner's first bullet, which says one machine and no other.
2. **At least one rebuild by a party outside this project reaching the published hash ladder** —
   this negates the second bullet's *no party outside this project has rebuilt this image*.
3. **A witness build that ran and agreed, so the manifest carries two signatures** — this negates
   the second bullet's *one signature, not two*. A witness that could not run does not satisfy this;
   single-signed publication is an escape hatch for shipping, never for retracting the claim.

When all three hold, the release that carries them **deletes the banner and states which evidence
met each condition**, naming the run record, the reproducer and the witness key. Until then every
release copies the banner forward. Retracting the claim is `1.0`'s work and has its own evidence
bar; this section exists so that the wording does not have to be reverse-engineered later.
