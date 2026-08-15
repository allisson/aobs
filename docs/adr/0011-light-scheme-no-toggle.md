# ADR-0011 — Light, one scheme throughout, no toggle

- **Status**: accepted
- **Date**: 2026-08-15
- **Decides**: [#26 — Screen rendering: light or dark](https://github.com/allisson/aobs/issues/26)
- **Artifact**: `docs/prototypes/light-dark.html`

## Context

The transaction-review prototype committed to dark throughout without the question being asked. It is
cheap to settle before two more screen flows exist and expensive to flip afterwards.

Decided **against the real artifact**, as the ticket required: the prototype renders the two settled
screens — the dense review panel and the per-address confirmation — **from a single markup
template**, so only the token block differs and the two schemes cannot drift apart. Shown on a
neutral mid-grey ground so neither scheme gets a flattering backdrop.

The expectation going in was that dark would hold up. Rendered, it does not.

## Decision

**Light, one scheme throughout, and no user toggle. No theme switch exists in the code** — not a
setting defaulted off, but absent.

**Light-on-dark text blooms.** Halation thickens light glyphs against a dark ground, which is
precisely the failure mode for distinguishing characters in a 42-character address at 17–22 px
monospace. Bech32 already removed `1`, `b`, `i` and `o` from its charset, but `q`/`g`, `5`/`s`, `2`/`z`
and `u`/`v` remain, and bloom is what makes those pairs converge. Dark-on-light does the opposite:
thin stems stay separated.

Two further reasons are specific to this appliance rather than general taste:

- **Unpredictable hardware.** aobs boots on whatever laptop the user has, which after UEFI-only is
  any machine from roughly 2012 onward. A cheap or aged panel renders a dark theme muddy and
  dark-on-light acceptably. **We are choosing for the worst screen we will ever run on, not the
  best.**
- **Unpredictable lighting.** In a bright room a dark screen becomes a mirror and the user compares
  an address through their own reflection. A light screen's emitted light overwhelms it.

## Consequences

- **Named cost:** a genuinely dark room gets a bright screen. Unpleasant, not a correctness problem.
- A single light token set, defined once and consumed by every screen. The prototype's palette is a
  starting point, not a mandate: `--ground #eef1f5`, `--panel #ffffff`, `--ink #0f151c`,
  `--ink-mid #414d5c`, `--ink-dim #66717f`, with `--ok`, `--warn`, `--crit` and `--focus` darkened
  from their dark-scheme values to hold contrast against a white panel.
- Address rendering keeps the 4-character groups with both ends emphasised; **the emphasis is now
  weight and ink, not luminance against a dark field.**
- The wallet-creation and seed-import prototypes were built light from the start rather than
  converted later, which is the whole reason this was settled before them. The review prototype's
  dark rendering is superseded; its structure is unchanged.

## Alternatives rejected

- **Dark.** The case was lower emitted light with a camera in the room — which the threat model
  explicitly declines to defend — plus night comfort. **Against a screen whose entire job is
  character-level comparison, comfort does not win.**
- **A different treatment for the address screens specifically.** Rejected because the argument runs
  the same direction on both screens: if light wins for legibility, it wins hardest exactly where the
  split would have applied it, leaving nothing for the other scheme to be better at. A scheme that
  flips mid-flow is also a surprise on the one screen where the user must be attending to content.
- **A per-session toggle.** There is a real argument for it — *the user knows their room and we do
  not* — and it is declined anyway: nothing persists, so it would be re-set every boot; it adds a
  control to an appliance whose posture is that it offers no settings; and it asks the user to choose
  at the moment of least attention, before they have seen which screen matters. **If users ask for
  it, that is evidence for v2 rather than a gap in v1.**
