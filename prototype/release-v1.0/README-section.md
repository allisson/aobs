# Verifying what you downloaded

<!-- PROTOTYPE. Draft of the section a first-time user reads. See ../README-prototype.md. -->

You are about to boot an image and type a seed phrase into it. Verify it first. This takes two
commands and needs nothing you do not already have: `sha256sum` and `gpg`.

## 1. Get the maintainer's key, from somewhere that is not this page

```sh
gpg --locate-key allisson@gmail.com     # from keys.openpgp.org
```

Then confirm the fingerprint you got matches:

```
C853 2ED6 8A59 6CFB B7F9  2D04 3607 18E3 09BE AA9F
```

**Confirm it against a second source before you rely on it.** The same fingerprint is published on
[x.com/allisson](https://x.com/allisson), an account that predates this project by years. Two
sources with different operators, neither of them GitHub, is the whole point of this step.

## 2. Verify the release

```sh
gpg --verify manifest-v1.0.txt.asc manifest-v1.0.txt
grep -E '^[0-9a-f]{64}  ' manifest-v1.0.txt | sha256sum -c -
```

That is the entire verification. `verify-release.sh` in the release does the same thing and, more
usefully, prints what it could *not* check — but it is a convenience, not an authority. It is about
120 lines, it shells out only to the two commands above, and you should read it before you run it.

The `grep` is required: `sha256sum -c` treats the manifest's comments as malformed checksum lines
and fails on them.

## What this proves, and what it does not

**It proves** that the person holding that key vouches for these exact bytes, and that the bytes you
have are the bytes they vouched for.

**It does not prove the image is honest.** For that, rebuild it and compare — the manifest names the
commit, the inputs, and `SOURCE_DATE_EPOCH` precisely so that you can:

```sh
git checkout v1.0 && ./build/fetch-inputs.sh && ./build/mkiso.sh
```

A matching sha256 means a stranger's build and the published build are the same file. That is the
claim this project actually rests on; the signature only tells you who to blame if it fails.

## What GitHub could forge

Say it plainly, because most projects do not:

**GitHub serves you the ISO, the manifest, the signature, and this README.** If GitHub is
compromised or coerced, all four change together and nothing on this page detects it — including the
fingerprint printed above, and including the key listed on the maintainer's GitHub profile, which is
the same origin as everything else here.

What GitHub cannot forge is a signature by a key it does not hold. So the one step that has to come
from elsewhere is step 1: **get the fingerprint from keys.openpgp.org or from the account linked
above, not from this file.** Everything after that is arithmetic you run yourself.

Two smaller admissions, in the same spirit:

- **The maintainer's key lives on an ordinary networked computer**, not a hardware token and not an
  air-gapped machine. Whoever compromises that computer can sign releases. This is a one-person
  project and that is the honest limit of it.
- **The `witness-ci` signature is worth less than the builder's.** It says a GitHub Actions runner
  independently rebuilt the image and got the same hash — valuable, and exactly what independent
  reproduction is for — but the key it signs with lives in GitHub's secret store, so it is not
  independent *of GitHub*. It corroborates the build, not the platform.
