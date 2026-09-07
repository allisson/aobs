# Secret hygiene

What holds seed material, for how long, and what the appliance therefore may and may not claim about
it.

The amnesia guarantee ([#10](https://github.com/allisson/aobs/issues/10)) settled the *claim*; this
document asks whether it is **sufficient** now that the architecture around it is fixed, and answers
yes — with the escalation in the kernel config rather than in Python.

## The wording stands, and one half of it got stronger

Claim (iii) in `docs/threat-model.md` has two halves, and #12 left them in very different shape.

**"Nothing recoverable from RAM during the session by another process" is no longer a promise — it is
structurally true.** The appliance runs exactly one userspace process: PID 1, which is the app. There
is no second process to open `/proc/self/mem`, no shell running, no daemon. The claim needs no defence
because the thing it defends against cannot be instantiated. `ls -d /proc/[0-9]*` shows one PID.

**"Never dumped" is the half that needed work**, and it is answered in the kernel config below rather
than by trusting the process to behave.

## Both escalations are rejected, on facts

### `mlock` buys nothing here

What `mlock` prevents is a page reaching **swap or a hibernation image**. #10 settled no swap and #12
settled no hibernation — the event it exists to stop **cannot occur** on this appliance. Adding it
would be a measure that protects nobody while reading, to anyone scanning the source, as though secret
pages were being protected from something. That is precisely the kind of claim this project's wording
bar rejects.

### A signing subprocess does not erase anything

Process exit **frees** pages; it does not zero them. The parent must hold the mnemonic in order to
feed the child, so the copy the subprocess was meant to avoid exists anyway. And it could not use the
obvious plumbing: `CONFIG_NET=n` removes `AF_UNIX` along with `AF_INET`, taking `multiprocessing` with
it (#13), so this would be raw `os.fork` plus pipes — real complexity in the most security-critical
path, for no change in what is recoverable.

## What is conceded, and stays conceded

**CPython copies freely and the copies cannot be counted.** `str` objects from key events, `bytes`
slices through BIP32 derivation, interpreter temporaries. This document does not fix that and must not
imply it does.

What it does is **shorten dwell where shortening it is free**, and refuse to claim more.

### Secrets do not go in Textual's `Input`

A purpose-built entry widget accumulates into **one `bytearray`, zeroed on teardown**, and never
assigns the secret to a Textual reactive. Reactives are watched, copied and retained **by design** —
that is what they are for, which makes the general-purpose widget the wrong tool here rather than
merely a risky one.

Honest accounting of what this buys: per-keystroke `str` objects still come from the event system and
cannot be scrubbed. What it removes is the one **retained, long-lived, framework-owned** copy — the one
that would sit in a reactive for the rest of the session and could be rendered by an errant refresh.
It shortens dwell. It does not achieve erasure.

Test: after the widget is torn down, no attribute on it and no reactive in the app holds the sentinel.

## Kernel configuration

**Core dumps are compiled out: `CONFIG_EXPERT=y`, `CONFIG_COREDUMP=n`.**

Confirmed against kernel sources rather than assumed — `CONFIG_COREDUMP` is `bool "Enable core dump
support" if EXPERT`, `default y`, so it is compile-outable but only visible under `EXPERT`.

`resource.setrlimit(RLIMIT_CORE, (0, 0))` is *also* called at startup, as belt-and-braces — but it must
never be the claim. A userspace call is made by the same code that would be failing. With
`CONFIG_COREDUMP=n` there is **no dumper in the kernel at all**, and that lands on #12's build-time
assertion list instead of in a runtime hope.

Alongside it:

- **`CONFIG_PROC_KCORE=n`** — a virtual ELF image of live kernel memory is exactly the wrong thing to
  ship on this appliance.
- **`CONFIG_PROC_PAGE_MONITOR=n`.**

### `init_on_free=1`

Boot with it. Its documented effect is *"Fill freed pages and heap objects with zeroes"*, so a page
CPython returns to the kernel does not retain a key.

**Its limit is stated in the same breath: it does not cover reuse inside musl's allocator**, which
recycles within an arena without returning pages to the kernel.

That limit is why it belongs here at all. #10 rejected a full RAM overwrite as theatre; this is the
version that is neither theatre nor a full promise — a real partial mitigation, honestly bounded, on an
appliance with no performance budget to protect.

## Nothing renders a secret

**The app installs its own `sys.excepthook`, and no library decides this.**

Rich can render tracebacks with local variables. A Textual crash screen drawing the frame that holds
the mnemonic would defeat every other measure in this document in one screenful — at the exact moment
the user is staring at the display.

So:

- The top-level handler required by #12 shows **the exception type and a fixed message**. Never the
  traceback, never locals.
- `show_locals` is pinned off **explicitly, regardless of the library default** — a default is not a
  decision, and it can change under us on an upgrade.
- **No logging framework, no log file, no `print` of any object that could hold key material.** The
  full traceback goes nowhere, because there is nowhere for it to go.

Test, and it is the one that matters most here: **raise from inside a frame holding a known sentinel
seed and assert the sentinel appears in no rendered screen, no stream, and no exception message.**

## The passphrase is entered once

**Do not hold two passphrases. Confirm via the master fingerprint.**

Ask once, derive, show the resulting fingerprint; the user checks it against what they saw last time.

Type-it-twice is the reflex and it is **both weaker and worse**: it doubles the copies by
construction, and it cannot catch the failure that actually matters — a passphrase typed *consistently*
through the wrong keymap (#12). The fingerprint catches that; a second entry does not.

**The cost is real and the UI must say it:** a first-ever passphrase has no fingerprint to compare
against, so on wallet creation the fingerprint is something the user **records**, not something the
appliance can check for them.

The screens belong to [#18](https://github.com/allisson/aobs/issues/18). What is settled here is the
rule: one entry, fingerprint comparison, no second copy retained.

## Tests

Prose is not a guarantee. These live in #13's suite and #12's build assertions.

**Build-time**: `CONFIG_COREDUMP=n`, `CONFIG_PROC_KCORE=n`, `CONFIG_PROC_PAGE_MONITOR=n`, no swap
support.

**Harness**:
- Sentinel-in-output — raise from a frame holding a known seed; assert it appears nowhere rendered,
  streamed, or in an exception message.
- Widget teardown — no attribute and no reactive retains the sentinel.
- Import-graph — the app's module closure pulls in no `logging` handler writing to a stream, alongside
  #13's existing `socket`/`ssl` assertion.

**Boot checklist**: `ulimit -c` reads `0`, and killing the app with `SIGSEGV` produces no core file
anywhere in the tmpfs — which it cannot, because no dumper exists.
