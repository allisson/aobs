# Prototype for #52 — detaching `fbcon` while the app draws holds

[#48](https://github.com/allisson/aobs/issues/48) photographed two `pr_emerg` lines sitting on top of
the UI, permanently, on the fbdev tier. [#51](https://github.com/allisson/aobs/issues/51) showed the
DRM tier is immune because the console client owns a *different* framebuffer and the helper *"never
steals the display from an active drm master"*, restoring the console on `lastclose`.
[#49](https://github.com/allisson/aobs/issues/49) chose to reproduce that semantic on the fbdev tier
with sysfs: console detached exactly while the app draws, reattached when it stops.

**It works.** Two NMIs left the panel byte-identical with the console detached, on a machine where
the same injection printed to the panel four seconds earlier with the console attached. Two things
had to be found out first, and the second is a correction to a control `01-boot-layer.md` §2 states.

## What was run

Branch `proto/52-console-detach`, off `proto/48-noseat` (so `backend-linuxkms-noseat`, the fbdev
tier). `ci/proto-52-probe.sh`, OVMF + `-vga none -device ramfb`, no GPU — #48's configuration.

Four captures on **one** boot, which is what makes the result readable:

| Capture | When | Console |
| --- | --- | --- |
| `panel-0-console-attached` | NMI during the entropy wait, before the app has a window | attached |
| `panel-1-ready` | 2 s after `AOBS_PROTO_DETACH_OK` | detached |
| `panel-2-after-nmi` | first NMI after the detach | detached |
| `panel-3-after-nmi` | second NMI | detached |

`panel-0` is the control, and it is not optional: without it, a clean post-detach panel cannot be
told apart from an injection that never landed. #48's evidence cannot play that role — different
binary, different ISO, different boot.

The changes under test:

- `Type=notify` + `NotifyAccess=all`, with `aobs::notify` sending `READY=1` three seconds into the
  event loop, so `ExecStartPost` fires on a **drawn** screen rather than at `fork(2)`.
- `ExecStartPost=+/usr/lib/aobs/console-detach` — finds fbcon by name in
  `/sys/class/vtconsole/vtcon*/name`, never by a hardcoded index, and unbinds it.
- `ExecStopPost=+/usr/lib/aobs/console-attach` — the `lastclose` half.

**`NotifyAccess=main` would have failed silently**, and this is a permanent property rather than an
accident: `/usr/lib/aobs/launch` deliberately does not `exec` the binary — the §9 fallback text after
it is the whole reason the wrapper exists — so the notifying process is never the main PID.

## Cycle 1: the detach killed the appliance, and the panel went black

```
AOBS_PROTO_DETACH_UID=0
AOBS_PROTO_DETACH_OK /sys/class/vtconsole/vtcon1 ((M) frame buffer device) bind=0
AOBS_PROTO_ATTACH_OK /sys/class/vtconsole/vtcon1     ← ExecStopPost, immediately after
```

Five times in a row, `Restart=always` looping it, and `cycle-1/panel-1-ready.png` is **completely
black**: not the appliance, not kernel text, nothing. `cycle-1/panel-2` and `-3` show a clean
appliance screen only because systemd had restarted the app and Slint had redrawn from scratch — so
every comparison in that cycle was between captures of a restarting machine. The probe now counts
`AOBS_READY` lines and refuses to compare anything unless the appliance started exactly once.

The suspects were the four settings binding the unit to VT1 — `TTYPath=/dev/tty1`,
`StandardInput=tty`, `TTYVHangup=yes`, `TTYVTDisallocate=yes` — since a hangup on that tty kills the
process group and `TTYVTDisallocate` clears the VT on stop, which would explain both the death and
the blank panel without the unbind being destructive at all.

## Cycle 2: with the VT coupling removed, it holds

```
AOBS_ENTROPY_MS=3791
AOBS_READY version=0.1.0 build=2026-08-15
AOBS_PROTO_NOTIFY_READY
AOBS_PROTO_DETACH_UID=0
AOBS_PROTO_DETACH_OK /sys/class/vtconsole/vtcon1 ((M) frame buffer device) bind=0
```

One `AOBS_READY`. No `ATTACH_OK`, so the service never stopped. And:

| Capture | sha256 (16) |
| --- | --- |
| `panel-0-console-attached` | `12d882fc325b17d3` |
| `panel-1-ready` | `816b631875a0310b` |
| `panel-2-after-nmi` | `816b631875a0310b` |
| `panel-3-after-nmi` | `816b631875a0310b` |

**Byte-identical across two NMI injections**, the form #51 used on the DRM tier. The control on the
same boot carries the kernel's own text:

```
[ 43.992212] launch[661]: AOBS_ENTROPY_WAIT_BEGIN
[ 44.683572] Uhhuh. NMI received for unknown reason 21 on CPU 0.
[ 44.685470] Dazed and confused, but trying to continue
```

**The unbind does not clear the framebuffer.** `panel-1` shows the appliance screen intact. Cycle 1's
black panel was systemd, not the kernel — which matters, because a destructive unbind would have made
this mitigation unusable no matter what else was true.

## The three findings that belong in the spec

**1. The aobs unit cannot be coupled to VT1, and one of those settings is a stated control.**
`01-boot-layer.md` §2 lists `TTYVTDisallocate=yes` among the four no-shell-escape controls. On this
unit it kills the appliance the moment `fbcon` unbinds. Nothing is lost by dropping the VT coupling
here: the app reads no stdin (input is libinput on `/dev/input/*`), and `journal+console` keeps §9's
channel, which goes to `/dev/console` and needs no `TTYPath`. §2's intent — no VT holding readable
text — is met by `NAutoVTs=0`/`ReserveVT=0` leaving no getty to allocate one. **This is a spec
correction, not an implementation detail.**

**2. Anything written to the console after the first frame lands on the panel and stays there.**
`panel-1` carries two lines at 51.68 s and 51.80 s — `AOBS_PROTO_NOTIFY_READY` and
`AOBS_PROTO_DETACH_UID=0`, both ours, printed in the ~120 ms between the app drawing and the unbind
completing. Slint does not repaint them away, which is #48's persistence property working against us
from our own code. So: **`console-detach` must write nothing to stdout** (serial only), and the
appliance must not write to the console after readiness. The readiness line itself is safe — it is
emitted at the top of the event loop, before the first paint, and the first frame covers it.

**3. The reattach is unobserved.** `ExecStopPost` returned `AOBS_PROTO_ATTACH_OK` in cycle 1, but no
capture proves kernel text becomes visible again afterwards. The case §9 actually cares about is
covered structurally rather than by that path: `ExecStartPost` only runs after a *successful* start,
so a startup failure never detaches at all, and `panel-0` is the proof the console reaches the panel
in that state. The residual is "the app ran, then died" — where systemd restarts it anyway.

## Not established

- **Real hardware.** QEMU + `ramfb`, and the vtcon index/name came from this kernel.
- **That the rebind restores a visible console** (above).
- **Any driver but none.** This is the fbdev tier by construction; on the DRM tier the kernel already
  does this, per #51.
