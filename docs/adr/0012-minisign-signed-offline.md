# ADR-0012 — minisign, signed on an offline machine, GitHub Releases only

- **Status**: accepted
- **Date**: 2026-08-15
- **Decides**: [#23 — Release, signing keys and distribution](https://github.com/allisson/aobs/issues/23)

## Context

Release integrity for v1 is "signed ISO plus published hashes"; reproducible builds are a v2 goal.
Everything about how that works was open, and the prior-art survey's sharpest criticism lands here:
release integrity that the user must check, on another computer, correctly, every time — which most
will not.

## Decision

**CI builds the ISO. The maintainer signs `SHA256SUMS` with minisign on an offline machine. GitHub
Releases is the single distribution point.**

**The limitation is recorded, not dressed up:**

> **Until reproducible builds land, the signature attests "the maintainer intends this artifact to be
> the release", not "this artifact matches the source."**

A maintainer signing a CI output cannot themselves verify it corresponds to the tree. That is
precisely the gap that resolved Coldcard's seed generation to a software PRNG for five years while
the source stayed correct. What partially closes it in v1 is the entropy provenance gate, **promoted
from a build step to a published artifact run against the published ISO.**

**Key custody is decided by payload size.** The signature covers a few-hundred-byte `SHA256SUMS`, not
the gigabyte ISO, so the air-gap crossing is a hash file on a USB stick — small enough to type if it
came to that. The gap therefore costs nothing, which rules out CI holding the key under any scheme.
It also beats a hardware token: a YubiKey makes the key non-extractable but performs every signature
on a networked host, so an attacker owning that host can sign arbitrary bytes on any touch.

**minisign over GPG, and the deciding factor is not cryptographic.** Verification instructions are
part of the product: the public key is one short line that fits in a README, a release page, a QR and
the ISO itself; verification is `minisign -Vm SHA256SUMS -P <key>` with the key inline; there is no
keyring, no trust database, and none of `gpg: WARNING: This key is not certified…` — the most-ignored
warning in computing, which trains users that verification output is noise.

## Consequences

- **The honesty this decision owed**, stated in the docs **verbatim** rather than paraphrased into
  comfort:
  > **Signature verification defends against a compromised mirror or CDN. It does not defend against
  > a compromised project.**
  If the publication surface is compromised at first download, the attacker supplies the ISO, the key
  and the instructions together. **No signature scheme solves trust-on-first-use.**
- Four things narrow that window: **the key lives in-tree** with a commit history, so git is a free
  append-only log; **the key ships inside the ISO**, so a returning user verifies release N+1 with
  the key from N and **TOFU is exposure once per user, not once per release**; **a rotation policy
  published in advance** — a new key is only ever announced signed by the old one, which converts an
  unsigned key change from a surprise into an alarm; and **GitHub build attestation**, which is not a
  second signature but a *different claim* (repo and workflow provenance), forcing an attacker to
  compromise the download host **and** the repo identity.
- **The secret key is passphrase-encrypted with a printed backup.** Key continuity is the whole
  defence, so a lost key destroys it permanently.
- minisign's **`-t` trusted comment is covered by the signature and printed on successful
  verification**, so version, build date and the attestation reference ride inside it rather than in
  a separate unsigned file.
- **The published package manifest** makes the stripped-network claim auditable without building the
  image — one upload turning a security claim into a checkable one.
- **Verification is made the shortest path rather than an extra chore**: the download page leads with
  one copy-paste block that downloads and verifies in a single command, expected output shown
  verbatim so a failure looks visibly different, and **no "skip verification" alternative** — no
  torrent or mirror link that arrives without the same block.
- **Self-reported provenance is structurally theatre against an attacker and is labelled so.** A
  tampered ISO displays whatever its tampered code says. Version and build date: yes, because they
  make no security claim and therefore cannot make a false one. Self-hash: only as a corruption
  check. **Never a green tick or anything reading "verified".**
- Host compromise is bounded: **a compromised host cannot produce a valid signature.**

## Alternatives rejected

- **GPG alongside minisign** — two signing paths means two custody problems, and a user taking the
  weaker path gets the weaker guarantee while believing otherwise.
- **A hardware token** — non-extractable key, but every signature happens on a networked host.
- **CI holding the key** — incoherent for a signing appliance, and unnecessary at this payload size.
- **OpenTimestamps** — thematically apt for a Bitcoin project, cut because it duplicates the
  transparency-log role at the cost of a second tool the user must install.
- **A self-hosted mirror or project website** — a mirror nobody watches is a liability rather than
  resilience, and a website is a second surface to secure for no guarantee the release page does not
  already give.
