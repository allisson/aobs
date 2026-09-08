# The console's appearance

Every other document here fixes what a screen *says*. None of them fixed what it looks like, and
the gap was not an oversight that survived review — it was invisible, because nothing rendered
outside a test until M3. `aobs/ui/app.py` carried three CSS rules; every screen's `DEFAULT_CSS` was
margins, `bold` and `dim`. The application therefore had no visual design at all, and the first
photograph of it running on real hardware reads as unfinished for that reason and not because a
Textual theme degraded on a framebuffer.

Three treatments were prototyped against the home screen and the colourless one won. What follows
is that treatment stated as rules, plus the four facts about the console it is drawn against —
because two of those facts had never been written down anywhere, and one of them makes a mechanism
the review screen relies on possibly invisible.

**The winner was already in the repository.** `aobs/ui/reviewtext.py` has had `_rule()` and
`_spread()` since the review screen was built — a full-width `─` and a left/right split at
`ROW_COLUMNS`, which is this same 92 columns — because the review screen is the one screen that got
a layout document. So this is not a new visual language: it is the one the only designed screen
already used, applied to the other nineteen, and the widths agree to the character on purpose.

This document fixes legibility. **Nothing in it is a security claim** and none of it appears in
`docs/overview.md`'s claim table. It does carry one correctness rule, in *Availability is stated in
words* below, and that rule is there because the current screen fails it.

## The console this is drawn on

| fact | where it comes from | how well it is known |
|---|---|---|
| **128×48** at the BIOS floor; 240×67 on a 1080p panel, more on 4K | `build/isolinux.cfg`'s `vga=791` → `vesafb` → `fbcon`; `docs/boot-pipeline.md` | **observed** on the target machine in M3 |
| **96 columns, centred, rows fluid**, and a refusal below 100×30 | `aobs/ui/geometry.py`, fixed by `docs/review-screen.md` | settled, and enforced by `fits()` |
| **16 ANSI colours, not truecolor** | `build/init` exports no `TERM`, so `rich` resolves the console to its `standard` system | **derived, not observed.** `rich.Console(force_terminal=True, _environ={})` answers `standard`; nobody has checked the panel |
| **The kernel's built-in 8×16 font**, whose repertoire is the IBM one | `build/init` runs `loadkeys` and never `setfont`; `printf '%G'` puts the console in UTF-8 | **derived, not observed** |

The third and fourth are the ones with consequences, and both have the shape M3 already named
twice: *a claim the repository stated correctly in prose and never checked.* Neither had even been
stated.

## No palette

**The only two colours are the terminal's own foreground and background.** Not a restrained
palette — none.

The reason is the third row of that table rather than taste. Textual's default themes are written
in RGB, and on a console resolved to `standard` every one of those values is downsampled to the
nearest of sixteen on the way out. Choosing an RGB theme is therefore not choosing a colour; it is
choosing a downsample nobody picked and nobody can see until the appliance is in front of them. So
the theme is **`ansi-dark`**, in which every value is one of the sixteen the console actually has,
and screens name colours as `ansi_*` or not at all.

Measured, on variant A's selected row: `ESC[1;30;47m`. Bold, black on white, from the sixteen. No
RGB triple is emitted anywhere.

A palette is not forbidden for ever — it is forbidden until somebody has looked at the panel. Nine
of the sixteen are unusable on a dark ground before you start, and *which* nine is a property of
this machine's framebuffer.

## Selection is the reversed row, never `bold` alone

Five screens carry a moving selection — the home screen, the keymap picker, the network picker, the
word-count picker, and the word grid's current slot. All five expressed it as `text-style: bold`
against text that is already the terminal's default white.

**The selected row is drawn as the whole row, foreground and background swapped.** It is the one
place the system spends the console's strongest available signal, because it answers *what will
`F10` do* — the question every one of those screens exists to ask.

`bold` stays on it, as reinforcement rather than as the mechanism.

## Availability is stated in words

This is the rule that is about correctness rather than looks.

The home screen distinguishes a path that can be walked from one that cannot, and until now that
distinction rested entirely on `text-style: dim`. Whether `fbcon` renders half-bright at all on
this panel **is not known** — the photograph is too reflective to settle it, and nothing in the
repository ever asked. If it does not, then every unavailable path on the appliance is
indistinguishable from an available one, and *sign a transaction* looks exactly as walkable with no
wallet loaded as with one.

So: **no distinction may rest on `dim` alone.** On the home screen the reason is now on the row, in
words, right-aligned — `needs a wallet`, `needs a camera`, `fixed for this session`. `dim` stays
alongside it and carries nothing by itself.

This does not change which paths are offered or the sentences that explain them. An unavailable
path is still shown rather than hidden, and the sentence under the list still says what happened
rather than what to do — `aobs/ui/screens/home.py` fixes both and neither is in question here.

## `dim` is only ever redundant

Three other places use `dim`, and all three are fixed by documents that predate this one:

| where | what `dim` marks | fixed by |
|---|---|---|
| `ReviewScreen .output-address-dim` | the address under a *proven change* output, which needs no eye-verifying | `docs/review-screen.md` |
| `AddressVerifyScreen .verify-address-dim` | the same, on the address screen | `docs/address-verification.md` |
| `ScanScreen #framing-aid` | the framing aid's hint line | `docs/scan-feedback.md` |

All three are **kept as they are.** In each, `dim` de-emphasises something whose meaning is already
carried by the line above it — a derivation path, a heading — so a console that ignores half-bright
costs legibility and not meaning. That is the test: `dim` may say *this matters less*, never *this
is not available*.

The first two are still worth a look on real hardware, and that is a checklist item, not a change.

## The shape of a screen

Unchanged from what every screen already composes, with two additions and no new widgets:

```
aobs  ·  mainnet
────────────────────────────────────────────────────────────────────────────────────────────

  > Generate a new wallet
    Type a seed in
    Restore from an encrypted wallet QR                            needs a camera
    Sign a transaction                                             needs a wallet
    ...

The network is chosen before a wallet is made, and fixed for good once one is.
No wallet is loaded yet, so the paths that need one are unavailable.
────────────────────────────────────────────────────────────────────────────────────────────
up/down choose  ·  F10 open this path  ·  F12 power off
```

The selection marker stays `>`, which is ASCII and therefore in the budget below. A reversed row
does not need a marker at all; it keeps one because every list screen prints it and replacing it
would be copy churn bought with nothing.

- **A rule under the title, and a rule above the keys.** Both are drawn as the *border* of a widget
  that already exists — `#title`'s bottom border, the keys line's top border — so no screen grows a
  widget, and a screen that is only a message does not gain furniture it cannot fill.
- **The keys line is a footer.** It was the last thing in the flow on every screen already; it now
  has the rule above it and the class that says so.

**The right-hand end of the title row is per-screen and stays that way.** The home screen and the
emit screen put the network there. Whether the review, confirm and address screens should too is an
open question in `docs/network-selection.md` §*Mainnet is the default*, and this document does not
close it — an appearance pass is exactly the wrong place to start printing the network on screens
that a settled document deliberately left alone.

## Vertically centred, but only where the content cannot overflow

The console has 48 rows and most screens have twenty of content, so a hole is not avoidable — it is
only placeable. Split above and below it reads as composition; all of it below reads as a block
that fell to the top of the screen.

So a screen whose content is a fixed, small number of rows is centred vertically. A screen whose
content can exceed the console is not, because centring clips symmetrically and the thing that gets
cut is as likely to be the top as the bottom:

| centred | top-aligned, and why |
|---|---|
| home, keymap picker, network, word count, dice, passphrase, randomness wait, fingerprint, confirm, refusal, camera lost, console too small, address verify, export password, export done | review (scrolls, and pins a region), address list (scrolls), scan (viewfinder), the three QR screens (85×43 of QR), recovery words and seed entry (a 24-word grid) |

## The glyph budget

The font is the kernel's built-in one, so the safe repertoire is **ASCII, Latin-1, and the box and
block characters the QR renderer already proves** (`▀ ▄ █`, and `─ ·`). That rules out Textual's
`round` and `heavy` borders — `╭`, `┏` — and leaves `solid` and `double`.

Thirteen non-ASCII characters currently reach the screen. Eight are inside the budget. **Five are
outside it and are not fixed in this pass:**

| glyph | where | what breaks if the console has no glyph for it |
|---|---|---|
| `⚠` U+26A0 | `aobs/ui/reviewtext.py:48` | the NOT PROVEN warning — the strongest marker on the review screen — loses its marker |
| `▮` U+25AE, `▯` U+25AF | `aobs/ui/scanning.py:45`, `:46` | the slot map, which is the whole of the scan screen's feedback |
| `—` U+2014, `–` U+2013 | 24 places, mostly `aobs/ui/addresstext.py` and `aobs/ui/reviewtext.py` | a hole in the middle of a sentence |
| `•` U+2022 | `aobs/ui/widgets/secretinput.py:31` | the passphrase field's masking character |

`•`, `↑` and `↓` are in the IBM repertoire but at positions the console reaches through its unicode
map, so they sit on the line between the two lists until somebody looks.

They are **left alone deliberately.** Replacing them is a change to rendered copy, and two of them
are inside row templates that `docs/review-screen.md` and `docs/scan-feedback.md` fix character by
character. Changing those inside an appearance diff is precisely the move `CLAUDE.md` forbids: the
decision would live nowhere. The check comes first, on real hardware, and it is cheap — one screen
showing all thirteen.

## Open

- **Does `fbcon` render half-bright on this panel?** It decides whether the four `dim` uses are
  doing anything at all. `docs/boot-checklist.md`.
- **Which of the thirteen glyphs resolve?** Same checklist, same screen.
- **Which of the sixteen colours are legible on this panel?** Only needed if a palette is ever
  wanted; the system as written needs none.
