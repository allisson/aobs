# aobs — Amnesic Offline Bitcoin Signer

A Bitcoin signing appliance: a bootable Debian image run on an offline machine to review and sign a
PSBT, then powered off. QR codes are the only data path in or out.

Start with `docs/overview.md`. `docs/roadmap.md` is the map — what is settled, what is open, in what
order. `CONTEXT.md` is the vocabulary and its terms are load-bearing.

## Rules

**Read the document that fixes a behaviour before changing that behaviour.** A design decision made
only inside a code diff is invisible to the next session, which then decides it differently. If a
change needs an open decision answered, close it in `docs/roadmap.md` or an ADR first.

**Never restate a claim at a strength it does not have.** `CONTEXT.md` defines three: *structural*
(the mechanism does not exist), *absence* (the mechanism is not in the image), *best-effort* (neither,
and stated as a limit). `docs/overview.md` tabulates which claim is which. Several were structural in
this project's Alpine ancestry and are now absence — see
`docs/adr/0001-debian-base-and-stock-kernel.md`. Writing one of those up as structural is a defect.

**`aobs/core/` may not import any adapter, `aobs.ui`, or `aobs.ports`.** A test enforces it.

**A green suite on a dev machine is not evidence.** Without a loadable `libsecp256k1` the vendored
embit silently resolves to `py_secp256k1`, and every EC operation runs 50-80x slower through the code
path `docs/boot-pipeline.md` forbids on the appliance — while passing. Homebrew's 0.7 counts as
"without": it dropped the deprecated alias embit's loader binds. The authoritative tier is
`build/Dockerfile.test`, and that is where the full suite is run and where a claim about it comes
from. Locally, run the files you are working on.

**The build fails rather than warns** at the first stage where a published claim stops being true.
Every build-time assertion is a pure function in `build/verify.py`, and the suite feeds each one a
deliberately broken input to prove it still bites.

**`build/` is source**, not a build artifact: PID 1, the pinned package list, the assertions. The
`.gitignore` says so, because the Python-packaging default would silently untrack it.

## The vocabulary bites

Terms in `CONTEXT.md` were chosen against specific wrong alternatives, and the wrong ones must not
come back. A few that recur: it is *proven change*, never bare "change"; the camera view is a
*framing aid*, never a "preview"; the scan display is a *slot map*, never a bar; networking is
*removed from the image*, never "disabled"; the boot medium is not *storage*. `CONTEXT.md` says why
in each case.

## Milestones

`docs/roadmap.md`. M3 — boots on real hardware and signs a PSBT — is a **gate**: nothing past it
starts before it passes. The predecessor of this repo never cut a release and was never booted on
real hardware, which is the failure the ordering exists to prevent.
