# ADR-0001 — aobs is GPL-3.0-only, because Slint's royalty-free licence cannot be relied on

- **Status**: accepted
- **Date**: 2026-08-15
- **Decides**: [#12 — GUI toolkit licensing: GPL-3.0 for Slint, or stay MIT?](https://github.com/allisson/aobs/issues/12)
- **Follows from**: [#5 — Tauri viability](https://github.com/allisson/aobs/issues/5), `docs/research/05-tauri-viability.md`

## Context

The Tauri viability research ruled Tauri out and selected Slint on `backend-linuxkms` +
`renderer-software`, which renders straight to KMS/DRM with no X server and no compositor. That
choice is measured and settled; it costs 22 packages and 21 MiB against Tauri's 268 and 650 MiB.

Slint is triple-licensed: `GPL-3.0-only OR LicenseRef-Slint-Royalty-free-2.0 OR
LicenseRef-Slint-Software-3.0`. This repository was MIT, which is incompatible with the first
option, so the toolkit decision left an open licence question.

The royalty-free licence is free of charge but **excludes embedded systems**, defining an Embedded
System as *"a computer system designed to perform a specific task within a larger mechanical or
electrical system"* — examples given are *"the controller driving the screen of an appliance, a
point-of-sale terminal, or a car dashboard"*. It contrasts this with a Desktop Application,
*"designed to run on a general-purpose computer (PC or notebook), typically installed and executed
locally on the computer's operating system."*

**aobs sits between those definitions and cannot be confidently placed in either.** It runs on a
general-purpose amd64 PC, which reads as Desktop. It is a single-purpose appliance shipped as its
own bootable operating system, which reads as Embedded — and it is emphatically not "installed and
executed locally on the computer's operating system", because it *is* the operating system.

The royalty-free licence also requires attribution, via an `AboutSlint` widget reachable from the
application or a Slint badge on the download page.

## Decision

**Relicense the entire repository, code and documentation alike, to `GPL-3.0-only`.**

Slint's GPL-3.0 option explicitly covers *"desktop, mobile, and web applications, as well as for
embedded systems"* at no cost. Under it, the embedded-versus-desktop question carries no
consequence, because both categories are permitted. The ambiguity is not resolved — it is made
irrelevant.

`GPL-3.0-only` rather than `-or-later`, to match Slint exactly. A GPL-3.0-only dependency pins the
combined work to GPL-3.0-only regardless of what we declare, so `-or-later` would have the repo
promising terms that a user of the actual binary never receives.

## Consequences

**What this buys beyond removing the ambiguity.** Copyleft on the exact binary a user boots is a
feature for a security appliance, not a cost: anyone distributing a modified aobs ISO must publish
its source. That is precisely the property this project's threat model depends on and has no other
mechanism to enforce. It also removes the royalty-free licence's attribution requirement, which
would otherwise place third-party branding inside a signing device's UI — training users to accept
unexplained branding on the one screen where they should question everything.

**What it costs.** The MIT alternative was priced and is worse than a licence-versus-licence
comparison suggests. iced + `tiny-skia` is +83 packages and +221 MiB, and — decisively —
`iced_winit` has X11 and Wayland backends and **no KMS backend at all**, so staying MIT would put a
Wayland compositor back onto an image whose entire design premise was removing one. egui is worse
still, requiring a display server *and* a GL implementation. Writing our own UI layer saves nothing:
Slint's 22 packages are `libinput`, `libseat`, `libxkbcommon`, `freetype`, `fontconfig` and
`fonts-dejavu` — input, seat management, keymaps and font rasterisation. That is the floor for any
KMS GUI, not Slint's overhead.

**What it does not affect.** This licence covers this repository. The released ISO also aggregates
Debian components under their own licences; aggregation on a distribution medium is not a derived
work, and relicensing here does not touch them.

**GPLv3 anti-tivoization.** The User Products clause binds anyone shipping aobs preinstalled on
hardware that restricts what the user may run. aobs is distributed as an ISO booted on the user's
own machine, so it does not bind us — and where it would bind a downstream hardware vendor, the
obligation is aligned with the project rather than a cost to it.

**No burden on users.** Nothing here is a library and nothing links against aobs. Copyleft
constrains redistributors, not the people who boot the appliance.

**Timing.** Executed before any product code exists, with a single copyright holder. Relicensing
cost rises with every commit and every contributor; this was its minimum.

## Alternatives rejected

- **Stay MIT with iced + `tiny-skia`** — reintroduces the display server that the Tauri research
  existed to eliminate, at +83 packages and +221 MiB.
- **Stay MIT with egui** — needs a display server *and* a GL implementation, meaning Mesa's llvmpipe
  purely to fake a GL context.
- **Write the UI directly against KMS/DRM with no toolkit** — saves none of the 22 packages, which
  are the irreducible floor for input, seat management and font rendering on bare KMS.
- **Rely on the royalty-free licence and argue aobs is a Desktop Application** — the definitions do
  not settle it, and an unresolved licence ambiguity is not something to ship under a security
  product.
- **Write to SixtyFPS for a ruling** — a multi-week round trip for an answer that changes nothing
  once we are GPL-3.0, and a vendor email is not a licence grant.
