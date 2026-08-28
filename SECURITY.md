# Security

## The signing key

```
C853 2ED6 8A59 6CFB B7F9  2D04 3607 18E3 09BE AA9F
```

Ed25519, the maintainer's own personal key, used as it is. No invented organisational identity: a
one-person project that publishes an "aobs release engineering" key is describing a structure that
does not exist.

**Custody, stated rather than engineered away.** The key lives on the maintainer's ordinary networked
computer. Not a hardware token, not an air-gapped machine. Whoever compromises that computer can sign
releases. This is a one-person project and that is the honest limit of it.

**No expiry, deliberately.** An expiry is a scheduled outage — it breaks verification for people
holding old releases on a date nobody will remember. Revocation is the capability that actually
matters, and it is available at any time.

## Getting the fingerprint from somewhere that is not this page

This is the one step that has to come from elsewhere, and the reason is flat:

**GitHub serves you the ISO, the manifest, the signature, and this file.** If GitHub is compromised
or coerced, all four change together and nothing here detects it — including the fingerprint printed
above, **and including the key listed on the maintainer's GitHub profile, which is the same origin as
everything else here.** The profile's GPG key API is not an independent channel.

What GitHub cannot forge is a signature by a key it does not hold. So confirm the fingerprint against
at least one of these, neither of which resolves to GitHub:

- **keys.openpgp.org** — verified email, independent operator, no web of trust to reason about:

  ```sh
  gpg --locate-key allisson@gmail.com
  ```

- **[x.com/allisson](https://x.com/allisson)** — a personal account that predates this project by
  years. Age is why it is here: an anchor created alongside the project anchors nothing.

A personal domain with WKD would be a better second anchor than the social account and remains a
swap-in. None is claimed today, because claiming one that is not yet published would be worse than
having two.

## Rotation and revocation

Rotation has **no scheduled trigger**. The plan is *revoke and re-anchor*, written down before it is
needed rather than improvised during an incident:

1. Publish the revocation certificate to **keys.openpgp.org**, which propagates it without GitHub's
   cooperation.
2. Post the revocation and the replacement fingerprint to the anchors above.
3. Amend this file with the revocation date, the replacement fingerprint, and which releases were
   signed by the revoked key.

Releases already signed by a revoked key stay downloadable and stay verifiable against that key. A
revocation says *stop trusting new signatures*, not *the old ones were forged*.

## Reporting a vulnerability

Open a GitHub issue for anything that is not itself exploitable — a wrong claim in the docs, a check
that has stopped checking, a build assertion that can be bypassed. For something that could cost
someone money, email the address on the key above, encrypted to it if you can.

There is no bug bounty and no disclosure timeline to negotiate. What there is: an advisory, published
under the process below, naming what an owner of an affected build has to do.

## Advisories

`ADVISORIES.txt` in the repository root, with a detached `ADVISORIES.txt.asc` signed by the key above
and re-attached as an asset to **every subsequent release**.

Three properties are load-bearing, and each of them is why the list is a file in git rather than a
page somewhere:

- **It is in git history.** A clone from any mirror carries it, and an edit to a past entry shows up
  in a diff. Append-only is enforced by history, not by a promise.
- **It is signed by a key you already have.** No second trust root to establish, and `gpg --verify` is
  the identical command you already ran on the manifest.
- **It is attached to every later release**, so the copy you are holding is dated and a stale one is
  recognisably stale.

**GitHub Security Advisories is a mirror for reach, never the source of truth.** A user who distrusts
GitHub verifies the signature, and the fingerprint comes from the non-GitHub anchors above.

### When an advisory is required

**Could this have cost someone money without them noticing?** If yes, it is an advisory. If no, it is
a note in the next release's notes.

Concretely: a wrong signature or address, weakened entropy, a secret that outlived the session, a
review screen that misrepresented where funds were going. The test is deliberately that one sentence,
because it is the only line a one-person project applies consistently under pressure — and an
incident is exactly when a more careful threshold gets re-litigated instead of applied.

### What an entry says

Six fields, and the last one is the one most advisory formats omit:

- **id and date** — append-only ordering.
- **affected versions**, written **as the appliance displays them**, so a user can match the list
  against the row on their screen.
- **what is wrong.**
- **what an owner of an affected stick should do.**
- **what funds signed on that build imply.**
- **whether upgrading is sufficient, or whether keys generated on the affected build are permanently
  compromised and need sweeping.**

That last field exists because of Coldcard's entropy defect: seeds generated between 2021 and July
2026 carried roughly 72 bits of entropy rather than 128, and a firmware update does not repair an
already-generated seed. **A format with no slot for that distinction will silently tell a user to
upgrade when what they actually need to do is move their coins.**

### What the appliance does not do

**It attempts no advisory detection of its own.** The first screen and every failure screen carry a
static line saying where advisories live; that line cannot check, does not check, and is worded so
that it cannot be mistaken for having checked.

Rejected: the appliance computing its own age. There is no trustworthy clock offline, a wrong "this
build is old" is worse than silence, and a modified image would lie about it anyway.
