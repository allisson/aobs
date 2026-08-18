# ADR-0017 — The appliance answers its own power button, and the app dies before the machine does

- **Status**: accepted
- **Date**: 2026-08-18
- **Decides**: [#87 — Nothing on the image handles the power button, and control 1 is
  inert](https://github.com/allisson/aobs/issues/87), measured by
  [#89](https://github.com/allisson/aobs/issues/89)

## Context

Building and booting the reconciled ISO ([#65](https://github.com/allisson/aobs/issues/65)) found
that `system_powerdown` from the QEMU monitor — an ACPI power button press — produced **no reaction
in 120 s**. Not a build defect: the image is exactly what the package list asks for.
`bitcoin-signer-amd64.packages` lists no D-Bus implementation, `systemd-logind.service` declares
`BusName=org.freedesktop.login1`, so the binary is on the image and nothing it needs is.

Two spec claims rested on that daemon, and one of them was load-bearing:

- **`01-boot-layer.md` §2's no-shell-escape control 1** was `NAutoVTs=0` and `ReserveVT=0` in
  `logind.conf`. The property held — control 3's hook masks every getty unit — but §2 credited the
  file, and did so at the moment it explains why `TTYVTDisallocate=yes` could be dropped.
- **§4's lid and suspend-key handling** was `HandleLidSwitch=ignore` and friends in the same file.

And a third thing was missing rather than inert: **nothing on the image could turn the machine off.**
`04-screens.md` §13's *end the session* had no mechanism either. The ticket assumed the app could
call `reboot(2)` itself; it cannot — the unit is `User=signer` with no `AmbientCapabilities`, and
`reboot(2)` needs `CAP_SYS_BOOT` — and it must not, because `reboot(RB_POWER_OFF)` powers the machine
off from inside the kernel **without killing userspace**, so nothing is freed and `init_on_free=1`
never fires. That is §5's hard power cut, executed by our own hand, on the path that exists to avoid
it. The physical button and the on-screen action were never two questions.

## Decision

**No D-Bus joins the package floor. The appliance answers its own power button, and the app dies
before the machine does.**

1. **The power button is an input event, read from its own evdev node.** The kernel presents the ACPI
   button as a device named `Power Button` carrying `KEY_POWER`; `signer`'s `input` group already
   reaches it. A press routes to §13's confirm-then-exit path, so the physical button does exactly
   what the menu entry does — confirmation included.
2. **Not through Slint's key path.** Slint delivers the key, but with no identity: the text is a
   single NUL byte, which is what any keysym with no UTF-8 form yields. Matching on that would make
   every unnamed key end the session, and a USB keyboard's volume keys are that class.
3. **Shutdown is the app exiting.** `exit 42` → `RestartPreventExitStatus=` lets it stay dead,
   `SuccessExitStatus=` makes that an honest success, and `SuccessAction=poweroff` on the `[Unit]`
   section takes the machine down.
4. **Restart is the app exiting with 0** and `Restart=always` bringing it back — a fresh process with
   a fresh `OnceLock` (ADR-0010), not a machine reboot.
5. **`logind.conf.d/10-aobs.conf` is deleted**, and §2 and §4 are rewritten to lean on what actually
   holds their properties. `dbus`, `dbus-daemon` and `dbus-broker` join the shell-escape hook's
   forbidden list, so the absence is checked rather than intended.

## Why

**A bus is a daemon, not a download.** §2's floor is a list of absences each carrying a reason, and
*"a permanently running message bus, so that a key we already receive can be routed back to us
through a second process"* is not a reason that survives being written down. The appliance is already
the only consumer of `/dev/input/*`.

**Dying first is what makes the RAM wipe unconditional.** `init_on_free=1` poisons pages when they
are *freed*, and process death is what frees them. Under exit-first, the process is gone and its
pages are poisoned **before** anything begins shutting the machine down — so the guarantee holds even
if what follows is forced, hangs, or is a mechanism a later change gets wrong. The rejected shape is
the app asking something still running to take the machine down and waiting to be stopped: the seed
then sits in RAM while the request is in flight, and a guarantee becomes a claim about someone else's
ordering. This is the half most likely to be undone by a well-meaning *"just call `systemctl
poweroff`"*, which is why it is an ADR and not a comment.

**A reboot buys nothing that a fresh process does not.** The kernel holds no wallet state, and §5
already records that a reboot frees neither the overlay upper dir nor the page cache. What the user
is promised is a different wallet, and a `OnceLock` in a new process is exactly that, thirty seconds
sooner, on the path §2 already documents as crash behaviour.

**An inert control is worse than an absent one.** ADR-0016 is on the record because a mechanism
believed in and never checked cost this project months. A config file is the more dangerous shape of
that failure, because it is the first thing someone edits to change the behaviour.

## Costs, named

- **The button is dead before the GUI is up, and dead on §9's parked diagnostic screen.** There the
  four-second hold is the only way off the machine — and that hold is a hard power cut, with the RAM
  wipe forfeited. `01-boot-layer.md` §5 now says so beside the wipe's other limits instead of leaving
  it to be discovered.
- **A wedged app is an unresponsive power button**, which a `logind` or `acpid` would have survived.
  Accepted: the appliance restarts on crash, and a process wedged *without* crashing is a state
  nothing else on this image would notice either.
- **"Restart" means something narrower than the machine's word for it**, so the label has to say what
  it does rather than borrow it.

## What was measured, and what was not

[#89](https://github.com/allisson/aobs/issues/89) built a throwaway probe into the ISO and booted it
on the `ramfb`/no-GPU row: `event1 name=Power Button`, `code=116` press and release reaching an
unprivileged app, and Slint delivering the key as `len=1 hex=00`. A control press went first —
without it a silent run cannot be told from a broken probe, which is the ambiguity #65 was left with.

`systemd-analyze verify` on the image's own systemd (`257.13-1~deb13u1`) accepts the three unit
directives and rejects a bad value for any of them. It also rejected `SuccessAction=` in `[Service]`,
where it was written first — a silent no-op of exactly the kind control 1 was.

**Not established**: that the exit-status contract fires end to end. Nothing in the crate exits 42
yet, so that waits for [#69](https://github.com/allisson/aobs/issues/69) and the CI row
`05-testing-and-release.md` §6.2 now carries. And the probe ran under QEMU's ACPI implementation
only; the button on real firmware is on §6.3's by-hand list, for the reason ADR-0016 records about
`ramfb`.

## Alternatives rejected

| Candidate | Why not |
|---|---|
| `dbus` + `systemd-logind` | Answers the button, the lid and the suspend key with no code from us, and reads the file we already ship. Rejected on the daemon, not the megabytes — and it would have hidden that §2's control 1 was inert rather than fixing it. |
| `acpid` | A smaller daemon than a bus, with a root handler. Still a daemon, for a key the app already receives. Held as the fallback had #89 come back empty; it did not. |
| The app calls `reboot(2)` | Needs `CAP_SYS_BOOT` the app does not have, and defeats the RAM wipe even if granted. |
| A `.path` unit watching `/run`, or a socket | Works and needs no privilege, but leaves the seed in RAM while the request is in flight, and adds a file to the image for something an exit status already carries. |
| Ignore the button, and say so | Honest, and cheapest. Rejected because the gesture it pushes users toward is the four-second hold, which is the one thing §5 says the wipe does not survive — the product would be teaching the failure. |
