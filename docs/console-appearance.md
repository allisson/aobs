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
| **128×48** on the target machine; 240×67 on a 1080p panel, more on 4K | whatever firmware framebuffer came up → `fbcon`; `docs/boot-pipeline.md` | **observed** on the target machine in M3 — coreboot's 1024×768 through `simplefb`, **not** `vga=791` → `vesafb`, which never set a mode there |
| **96 columns, centred, rows fluid**, and a refusal below 100×43 | `aobs/ui/geometry.py`, fixed by `docs/review-screen.md` | settled, and enforced by `fits()` — this is the console guarantee, and no boot parameter is |
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
distinction rested entirely on `text-style: dim`. Whether `fbcon` renders half-bright at all was
not known when this was written, and if it did not, every unavailable path on the appliance was
indistinguishable from an available one — *sign a transaction* looking exactly as walkable with no
wallet loaded as with one.

**It does render.** A photograph of the appliance booted on the target machine — BIOS path,
`simplefb`, 128×48 — shows the six rows that need a wallet visibly greyer than the four that do not.
That is one panel and one framebuffer driver, so it is an observation and not a guarantee; the
rule below is unchanged by it, because a distinction that survives only where somebody happened to
look is not a distinction the appliance can publish.

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

The home screen's photograph says all three do something on this panel. The first two are on
screens nobody has photographed yet, so seeing them is still a checklist item.

## The shape of a screen

The home screen, which is where the treatment was chosen. Nothing here is a new widget — the two
rules are borders on widgets that already existed:

```
aobs                                                     mainnet  ·  DEVELOPMENT BUILD
──────────────────────────────────────────────────────────────────────────────────────────

WHAT YOU CAN DO

  > Generate a new wallet
    Type a seed in
    Restore from an encrypted wallet QR                                    needs a camera
    Sign a transaction                                                     needs a wallet
    ...
    Choose the network  ·  mainnet

The network is chosen before a wallet is made, and fixed for good once one is.
No wallet is loaded yet, so the paths that need one are unavailable.

──────────────────────────────────────────────────────────────────────────────────────────
up/down choose  ·  F10 open this path  ·  F12 power off
```

- **The title row is a row**, not a line: the appliance's name at the left edge, what this session
  is at the right. The weight is on the name only.
- **A section label above the list**, uppercase. The console has one font at one weight, so case is
  the only typographic register there is — a label cannot be "smaller" or "lighter" here, only
  differently cased.
- **The sentences under the list are one block**, with a blank row before it and none inside it.
  They are one statement about the session; a blank between each made three paragraphs of it.
- **A rule under the title, and a rule above the keys.** Both are drawn as the *border* of a widget
  that already exists — `#title`'s bottom border, the keys line's top border — so no screen grows a
  widget, and a screen that is only a message does not gain furniture it cannot fill.
- **The keys line is a footer.** It was the last thing in the flow on every screen already; it now
  has the rule above it and the class that says so.

The selection marker stays `>`, which is ASCII and therefore in the budget below. A reversed row
does not need a marker at all; it keeps one because every list screen prints it and replacing it
would be copy churn bought with nothing.

**The right-hand end of the title row is per-screen and stays that way.** On the home screen it is
the network and the build label — the same header `docs/network-selection.md` already names as one
of the three places the network is stated, re-laid-out rather than moved. Whether the review,
confirm and address screens should carry the network too is an open question in that document
§*Mainnet is the default*, and this one does not close it: an appearance pass is exactly the wrong
place to start printing the network on screens a settled document deliberately left alone.

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

**Somebody looked, and five of them had no glyph.** This section used to list five characters as
*at risk* and leave them alone until a hardware check. The check turned out not to need hardware:
`build/init` never calls `setfont` and `loadkeys` does not touch the console map, so the vt uses the
kernel's default map, which is generated from `drivers/tty/vt/cp437.uni` — **303 codepoints, and
none of the five is among them.** That is checkable by a reader, which a photograph is not.

| glyph | where | verdict | now |
|---|---|---|---|
| `⚠` U+26A0 | `aobs/ui/reviewtext.py`, the NOT PROVEN marker | **no glyph** | `!` — two columns, as `⚠ ` was, so `docs/review-screen.md`'s row widths are unchanged |
| `▮` U+25AE, `▯` U+25AF | `aobs/ui/scanning.py`, the slot map | **no glyph** | `█` and `░` — solid versus dither keeps holes looking like holes; `docs/scan-feedback.md` |
| `—` U+2014, `–` U+2013 | 25 rendered strings across nine modules | **no glyph** | `-`, width-preserving. Not `--`, which reads as a typo in a rendered sentence |
| `•` U+2022 | `aobs/ui/widgets/secretinput.py:31`, the passphrase mask | **renders** | unchanged, and the narrowest escape here |
| `↑` `↓` `►` `─` `·` `§` `×` `≈` `→` `▀` `▄` `█` | rules, markers, the QR renderer | **render** | unchanged |

The two that would have hurt most are the slot map and the passphrase mask, and they fell on
opposite sides: the map would have drawn as nothing, taking the whole of the scan screen's feedback
with it, while `•` was in the repertoire all along.

**The budget is now a build-time rule, not a prose one.** `tests/test_structure.py` renders every
screen through `tests/screentext.py` and fails if any character is outside the repertoire, with
CP437 as a frozenset citing the kernel file above. The rule covers the review screen with a NOT
PROVEN case specifically, because that screen is deliberately not one of the README blocks and is
exactly where `⚠` lived unchecked. Textual's `round` and `heavy` borders — `╭`, `┏` — are still out;
`solid` and `double` are still in.

**The hardware check still happens** and is `I-9` in `docs/boot-checklist.md`. What it can add is
*observation* to a derivation: this section's claim is now derived from the kernel's own map, which
is stronger than the "derived, not observed" it used to carry, and weaker than a run record saying
somebody saw it.

## The blocks in the README

`README.md` shows four screens, and this section fixes what they are. They are **renders**: the
characters a console would show, produced by driving the real `SignerApp` through the test harness
and exporting the composited screen as text. They are not photographs. A photograph is evidence
that the image renders on the target panel — the claim this document's *The console this is drawn
on* makes — and a render is evidence of nothing beyond what the code draws. Captioning one as the
other would upgrade a claim's strength, which `CLAUDE.md` calls a defect.

**Text, not an image, and the reason is mechanical.** Textual's SVG export
(`rich/_export_format.py`) embeds an `@font-face` fetching Fira Code from `cdnjs.cloudflare.com`
and places every glyph at that font's 0.61 aspect ratio (`rich/console.py`). Inside an `<img>` the
browser blocks that fetch, so the glyphs land at Fira Code's metrics in whatever fallback the
reader has. A README about an appliance with no network has no business shipping an artifact that
makes its readers' browsers call a CDN, and a fenced block avoids the question entirely: the
appliance is colourless monospace, which is what a fenced block already is. It also diffs as text.

**What the blocks show, and at what size.** The console is 128×48 — what the target machine's
firmware framebuffer gave, and the size every screen suite drives. Not the floor of `MIN_COLUMNS ×
MIN_ROWS`, which is a minimum rather than a representative screen: the blocks picture a roomy
console on purpose, so a
floor-sized block would picture a screen no operator sees. The content block is capped at 96 and
centred, so every line carries the same left gutter on a 128-column console; the gutter is removed
so the README does not scroll sideways. Every character and every relative position survives that.

**The data is the published BIP39 vector** already fixed in `tests/conftest.py`, and one corpus
case for all four blocks, so the reader follows one transaction in and out. Two rules on which
screens may appear:

- **No screen whose content is a secret.** `RecoveryWordsScreen` and `ExportPasswordScreen` are out
  permanently. Poisoning the vector does not save them: once poisoned there is nothing left to
  show, and `docs/export-password.md` already says the password screen and the QR screen in one
  frame *is* the attack — teaching that framing with a synthetic pair is still teaching it.
- **No refusal, and no adversarial case.** A reader cannot tell a pictured refusal from a pictured
  signing at a glance, and the corpus attacks are demonstrated in `tests/test_review_screen.py`
  where a verdict is asserted beside them.

**Captions use `CONTEXT.md`'s terms.** *Framing aid*, never "preview"; *slot map*, never "bar";
*proven change*, never bare "change". A caption is prose written last and is where the wrong word
gets back in.

**A stale block is a false claim, so the suite regenerates and compares.**
`tests/test_structure.py` renders the four screens and asserts the README carries each one
character for character — the same device that already keeps the advisory list honest — and a
companion test mutates a screen's text to prove the comparison bites. This is the golden-file
assertion `aobs/ui/geometry.py` and `docs/review-screen.md` both already refer to. It is not the
pixel-diffing `docs/test-harness.md` forbids: text has no font, so it cannot fail on a font change.
What it does not do is catch a wrong address — it asserts the README agrees with the screen, never
that the screen is right.

The one fragile part is confined on purpose. `tests/screentext.py` reaches `Screen._compositor`,
because Textual 8.2.8 has no plain-text export and that private attribute is what its own
`export_screenshot()` uses. A Textual upgrade can break it; when it does, one module fails loudly.

## Open

- ~~**Does `fbcon` render half-bright on this panel?**~~ **Answered: yes**, on the target machine's
  BIOS path, on `simplefb`. Observed on the home screen, where the rows that need a wallet are
  visibly greyer. One panel, one driver — the redundancy rule stands regardless.
- **Which of the thirteen glyphs resolve?** Still open, and the home screen exercises none of the
  five doubtful ones. `docs/boot-checklist.md`, one screen showing all thirteen.
- **Which of the sixteen colours are legible on this panel?** Only needed if a palette is ever
  wanted; the system as written needs none.
