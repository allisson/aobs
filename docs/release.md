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
git tag -s v1.0 -m 'aobs v1.0'
```

**Never through the GitHub UI.** `main`'s HEAD is otherwise signed by GitHub's key
`B5690EEEBB952194`, not the maintainer's, and a tag created in a browser carries the platform's
signature rather than a person's. `SECURITY.md` holds the fingerprint this must be.

**3. Fetch the inputs, then build.**

```sh
docker run --rm --platform=linux/amd64 -v "$PWD:/src" -w /src \
    alpine:3.24 sh build/fetch-inputs.sh
docker build -f build/Dockerfile.iso -t aobs-iso .
mkdir -p out && docker run --rm --privileged -v "$PWD:/src" -v "$PWD/out:/out" aobs-iso
```

The stage-3 assertion binds `/etc/aobs-release` to that tag. Record the hash ladder the build prints:
CI's witness build prints the same five rungs, and the first one that differs is where a divergence
began.

Then run the preflight, which is the four refusals and nothing else:

```sh
SOURCE_DATE_EPOCH=$(git log -1 --format=%ct) ./build/release-preflight.sh
```

**4. Build the input archive and the manifest, and verify locally by running the published command
from the published instructions.**

```sh
mkdir -p release && cp out/bitcoin-signer-amd64.iso release/

# One deterministic tar: sorted members, fixed mtime, uid, gid and mode, uncompressed —
# the .apk files and the kernel tarball are already compressed.
tar --sort=name --owner=0 --group=0 --numeric-owner \
    --mtime="@$(git log -1 --format=%ct)" --format=gnu \
    -C build -cf release/aobs-inputs-v1.0.tar inputs

python3 build/gather.py write-manifest . \
    /path/to/etc-aobs-release release >release/manifest-v1.0.txt
python3 build/gather.py manifest . \
    release/manifest-v1.0.txt /path/to/etc-aobs-release release

cd release
gpg --detach-sign --armor --output manifest-v1.0.txt.asc manifest-v1.0.txt
gpg --verify manifest-v1.0.txt.asc manifest-v1.0.txt
grep -E '^[0-9a-f]{64}  ' manifest-v1.0.txt | sha256sum -c -
./verify-release.sh
```

The two raw commands are run **as the README prints them**, not as an equivalent. SeedSigner's first
signed release shipped a file that gave `gpg: not a detached signature`, and an outsider found it.
The cost of catching that here is thirty seconds.

`/path/to/etc-aobs-release` is the copy the build wrote into the rootfs. Extract it from the
initramfs, or take it from the builder's `$WORK/rootfs/etc/aobs-release` — the manifest's `release`
and `git-commit` are generated **from that file** (#61), which is what leaves the image and the
manifest nothing to disagree about.

**5. Push the tag. This is the first irreversible act, and it happens only after the build has
succeeded.**

```sh
git push origin v1.0
```

**6. CI's witness build runs from the pushed tag**, compares hashes, and signs the manifest.

- **A witness that disagrees blocks the release.** If the hashes differ, that is a reproducibility
  defect, and the contract's position — a stranger who rebuilds and gets a different hash has found a
  defect, not a difference of opinion — has to bind us before it binds anyone else. No signature, no
  publication: fix it and re-tag.
- **A witness that cannot run is a different case from one that disagrees.** On an infrastructure
  outage the release may be published single-signed: the witness signature is already non-fatal to
  verification, and the `signer:` lines make its absence visible rather than silent. **Publishing over
  a witness that ran and disagreed is never permitted.**

**7. Publish the Release — once.**

Assets: `bitcoin-signer-amd64.iso`, `aobs-inputs-v1.0.tar`, `manifest-v1.0.txt`,
`manifest-v1.0.txt.asc` carrying **both** signatures concatenated, `verify-release.sh`,
`ADVISORIES.txt` and `ADVISORIES.txt.asc`.

**A single publication is the point.** Appending the witness signature to an already-published `.asc`
would mutate a signed asset that strangers may already hold, and there is no way to tell a reader
which version of it they got.

**8. Re-verify the *published* assets as a stranger would, then refresh the README's advisory list.**

```sh
mkdir /tmp/stranger && cd /tmp/stranger
gh release download v1.0
gpg --verify manifest-v1.0.txt.asc manifest-v1.0.txt
grep -E '^[0-9a-f]{64}  ' manifest-v1.0.txt | sha256sum -c -
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
2. **`HEAD` not at a signed annotated tag matching `vMAJOR.MINOR`.**
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

One plain-text, line-oriented `manifest-vMAJOR.MINOR.txt`, readable with `cat`, with three kinds of
line:

- **`key: value` metadata** — `format`, `release`, `released`, `git-tag`, `git-commit`,
  `source-date-epoch`, `iso-name`, `alpine-branch`, `aports-commit`, `inputs-list-sha256`, and
  `signer:` lines.
- **`input-*` fields** for upstream inputs. These live *inside* the archive, so a reader running the
  checksum command does not have them on disk; recording them as checksum lines would produce a
  spurious failure for everyone.
- **A contiguous block of `<sha256>  <name>` lines** for the files published beside the manifest, in
  `sha256sum -c` format exactly.

**The format was decided by measurement, not taste.** `sha256sum -c` cannot read a file containing
comments — pointed at the manifest whole, busybox coreutils prints `comment line: FAILED` and exits 1.
So the documented command is:

```sh
grep -E '^[0-9a-f]{64}  ' manifest-v1.0.txt | sha256sum -c -
```

One file, at the cost of a one-liner nobody would guess unaided. The alternative — a bare `SHA256SUMS`
plus a separate metadata file — splits the thing the signature covers, and the signature covers the
manifest *because* the manifest names the inputs.

`inputs-list-sha256` does the real work: it pins the archive to `build/inputs.sha256` **as committed at
the tag**, so a swapped archive is caught even if the asset were replaced in place.

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
