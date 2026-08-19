# ADR-0018 — The repository is public before the signer works

- **Status**: accepted
- **Date**: 2026-08-19
- **Decides**: no ticket. Raised while looking at a CI bill and settled in the same session; this
  file is the record, and the map ([issue #1](https://github.com/allisson/aobs/issues/1)) gets a
  line pointing here rather than to a resolution comment.

## Context

GitHub Actions bills every minute a **private** repository spends on a runner. The measurement, taken
on 2026-08-19: **36 runs and 1 490 job-minutes between 1 and 19 August**, against the Free plan's
2 000 minutes a month — a full month extrapolates to roughly 2 350. The `/timing` endpoint reports
`billable.UBUNTU.total_ms: 0` for this repository and is not the instrument; the number is the sum of
each job's `started_at` → `completed_at`.

Where a single 41-minute run goes: `image` 25.4, `source` 8.6, `fuzz` 3.7, `coverage` 3.5. The
`image` job is the eight-row QEMU harness of `05-testing-and-release.md` §6.2 plus the ISO build, and
it is the expensive one because booting three machines under TCG is what §6 asks for.

The first proposal was to keep the cheap gates on GitHub and run the expensive ones on a developer's
machine. Two facts killed it. The development machine is **arm64 macOS with TCG only** — no HVF for
an x86 guest — and the ISO is amd64, so every one of those boots would be x86 emulated on ARM, and
`ci/local-inner.sh` already runs the build under `--platform linux/amd64` for the same reason. And
more decisively: §6 exists because **Coldcard's seed generation resolved to MicroPython's software
PRNG for five years while the source stayed correct**. A gate the platform refuses a merge over is a
gate. A gate a human remembers to run refuses nothing, and the section that exists because a check
was believed in and never performed is the last place to put one.

**Public repositories get unlimited standard-runner minutes.** All four jobs are `ubuntu-latest`.

## Decision

**The repository goes public now, while the signer does not work, behind a warning that says so.**

1. **Public, on standard runners.** The bill goes to zero and no gate moves off the platform. Every
   §6 row stays where a merge can be refused over it.
2. **A `README.md` warning is a precondition, not a follow-up.** It names the three absences —
   PSBT validation and the rejection policy, the transaction review screen, the signing path — and
   states that any key an ISO from this tree touches should be treated as disclosed. *"There is no
   release"* was already there; that is a statement about our process, and a stranger needs one about
   their funds.
3. **Fork pull requests require approval from all outside collaborators.** The workflows reference no
   secrets, so a fork PR can exfiltrate nothing; it can still spin eight QEMU machines on demand.
4. **No release, no signed artifact.** ADR-0012's minisign path is what makes an ISO ours to stand
   behind, and nothing published before the release gate is.

## Why

**Auditability is not a feature of this project; it is the collateral.** ADR-0001 already put the
repository under GPL-3.0-only. `01-boot-layer.md`'s reproducibility work, ADR-0012's signed release
and §6's whole premise — *verify the shipped artifact, not just the source* — are arguments addressed
to someone who is not us. A signer nobody outside can read is a signer nobody outside should trust,
so public was always the destination. The CI bill only settled the date.

**Publishing early is what makes the design record worth having.** Twenty-seven decision tickets and
seventeen ADRs were written before the code, precisely so the reasoning could be attacked. Held until
the code is finished, they document a thing that can no longer change cheaply.

**The banner is aimed at the one failure this timing creates.** The repository *reads* finished: a
closed spec, a booting ISO with a start menu, seed generation and BIP-39 both ways
([#70](https://github.com/allisson/aobs/issues/70)). The gap between how complete it looks and what
it can safely do is the whole risk of publishing now, and it is a gap only prose can close today.

**Free minutes were the trigger and are the smaller half.** They buy runway through implementation —
the period with the most runs, not the fewest — and they unlock branch protection, which is what lets
a §6 gate become a *required* check instead of a convention.

## Costs, named

- **This does not un-happen.** Clones, forks, code search, archives and training corpora do not
  respect a later flip back to private. Everything in 46 commits is out, permanently.
- **`allisson@gmail.com` is the author address on every one of those commits** and becomes public
  with them.
- **A half-built signer is now something a stranger can build and boot.** The mitigation is a warning
  in a README, which is the weakest kind of mitigation there is — it works only on people who read
  it. Accepted because the alternative that actually removes the risk is not publishing, and that
  costs the runway this decision exists to buy.
- **The threat model's out-of-reach list is public too**, along with every rejected alternative. That
  was already true of anyone who read `docs/specs/`; it is now true of everyone.
- **Free is not fast.** A pull request still waits 41 job-minutes, and public repositories queue on a
  shared pool, so latency can get worse. The bill stopped being the reason to shorten the run; the
  wait did not.

## What was checked before flipping the switch

No Actions secrets exist and no workflow references `secrets.`, so fork PRs have nothing to reach.
No submodules. `LICENSE` present, and GitHub already resolves it as GPL-3.0. The full history — 46
commits, 372 KiB — carries no key, token or credential-shaped string, in the tree or in any diff.

## Alternatives rejected

| Candidate | Why not |
|---|---|
| Move the QEMU rows to a developer's machine | The original proposal. The machine is arm64 with TCG only against an amd64 ISO, so the rows get slower, not cheaper — and enforcement moves from the platform to a person, which is the failure §6 was written about. |
| Pay for minutes, or GitHub Pro | Buys 3 000 minutes instead of 2 000 — still finite, still rising with the run count, and it buys nothing for the auditability the project's security argument rests on. |
| Cache the build environment in GHCR | Real: `ci/build-env.Dockerfile` is rebuilt in all four jobs, ~2.6 min each. Worth ~7 minutes of wall clock, in exchange for a registry, a login and a staleness question. Deferred until the wait has a number that hurts. |
| Hold publication until the review panel exists | Removes the one risk this ADR accepts, and costs the free minutes exactly during the months with the most runs. The banner buys most of the same protection for one commit. |
| Publish bare, with no warning | The README's *"there is no release"* would carry the whole load, and it does not say what a person about to boot an ISO needs to hear. |
