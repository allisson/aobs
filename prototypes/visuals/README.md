# PROTOTYPE — what should the appliance's console look like?

Throwaway. Nothing here ships: `prototypes/` sits outside `aobs/`, and `build/mkiso.sh` only tars
`aobs`, so no variant, no fake wiring and no switcher bar can reach the image. Delete the whole
directory once a variant has won and been folded in properly.

The question comes from a real boot: the app runs on a Chromebook off a LiveUSB and the screen
looks unfinished. Three variants of the **home screen** — the screen in that photograph, and the
one with real density: ten paths, three availability rules, three sentences, a key line.

    uv run python prototypes/visuals/run.py            # starts on A
    uv run python prototypes/visuals/run.py C
    uv run python prototypes/visuals/run.py --truecolor    # opt out of the 16-colour emulation

`uv run`, or `.venv/bin/python` — a bare `python` is the one on `PATH` and has no `textual` in it.

`left`/`right` cycle the variant. `w` loads a wallet, `c` toggles the camera, `n` raises a notice —
the availability rules are most of what the design has to carry, so they are drivable. `F12` quits.
`F10` is inert: this answers *what does it look like*, not *do the paths work*.

## What the current screen actually has, and does not

Read before judging anything: the app sets **no colour at all** today. `aobs/ui/app.py` is three
CSS rules, and every screen's `DEFAULT_CSS` is margins plus `bold` and `dim`. So the photograph is
not a Textual theme degrading on a framebuffer — it is a design that was never written.

Three constraints found in the tree, all of which the variants are built against:

- **16 colours, not truecolor.** `build/init` exports no `TERM`, so `rich` resolves the console to
  its `standard` system — 8 colours plus their bright halves — and every RGB value in a Textual
  theme gets downsampled into them. Verified by construction (`rich.Console(force_terminal=True,
  _environ={})` → `standard`), not on the appliance. `run.py` sets `TEXTUAL_COLOR_SYSTEM=standard`
  so the dev machine shows what the panel will, and the theme is `ansi-dark`, whose every value is
  one of the 16 the console actually has.
- **The font is the kernel's built-in 8x16.** `build/init` runs `loadkeys` and never `setfont`, so
  the glyph coverage is CP437's. That rules out Textual's `round` and `heavy` borders (`╭`, `┏`) and
  leaves `solid` and `double` (`┌`, `╔`), and it rules out `•`, `✓`, `✗`, `▸`. `─ │ ═ ║ ► × · ↑↓`
  are all in it, and the QR renderer already proves the half-blocks are.
- **96 columns, centred, rows fluid** (`aobs/ui/geometry.py`), and the appliance refuses under
  100×30. The real console is 128×48 at the BIOS floor, which is what `run.py`'s smoke size uses.

**`dim` is doing load-bearing work and may not be visible.** Availability — the difference between
a path that can be walked and one that cannot — rests entirely on `text-style: dim` today. Whether
`fbcon` renders half-bright at all on this panel is **not verified here**, and the photograph is
too reflective to settle it. So every variant encodes availability a second time, in text: a
reason, a tag or a gutter mark. If it turns out `dim` is invisible on the appliance, that is a
correctness bug in the current screen, not a taste question.

## The three bets

| | bet | primary affordance | colour |
|---|---|---|---|
| **A** Typeset | the shape is fine, it was simply never typeset | a full-width selection bar | none — terminal fg/bg only |
| **B** Instrument panel | it is an appliance and should look like one | a drawn frame and a welded F-key bar | structural, plus one meaningful use |
| **C** Session ledger | the state sentences belong in a permanent column, not appended under the list | a two-column ledger | one accent |

- **A** — header row with the session state on the right, rule, section label, selection as
  reversed foreground/background instead of `>` plus `bold`, a right-hand reason on every
  unavailable row, and the whole block vertically centred. Survives a monochrome console and a
  broken palette, which is the strongest thing that can be said for a design here.
- **B** — a `double` frame with a titled border, a header band, the paths in a bordered panel that
  reaches the bottom of the frame, the session sentences in a box of their own, and the key line as
  a full-console-width bar on the last row. Colour carries meaning exactly once: the network badge,
  because it is the only value on the screen that costs money to get wrong.
- **C** — the list keeps the left column; `THIS SESSION` (network, wallet, camera, build — always
  all four, always in the same place) takes the right. The sentence explaining a blocked path shows
  there, about the path the user is pointing at. Unavailable rows keep their row and gain a `×`.

Semantics are held constant across all three, because they are settled elsewhere and are not what
is being asked: an unavailable path is shown rather than hidden, the network is the last path and
goes unavailable once fixed, `F10` is the only accept key, and the sentences say what happened
rather than what to do.

## If one wins

The winner is a visual system, not a screen, so folding it in means `aobs/ui/app.py`'s `CSS` and
every screen's `DEFAULT_CSS`, and it fixes behaviour that has no document yet — the palette, the
glyph budget, where availability is encoded, whether the block is centred. Per `CLAUDE.md` that
document comes first: a decision made only inside a CSS diff is invisible to the next session.
