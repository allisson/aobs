# PROTOTYPE — UI surface (wayfinder ticket #3)

Throwaway. This branch is a **primary source**, not code that goes to `main`. It exists to
answer one question: is the appliance's UI surface a framebuffer TUI, a native toolkit, or a
kiosk browser?

All three stubs render **the same screen** from **the same fixture** (`fixture.py`): a two-input,
two-output PSBT review with a fee and a warning, plus a real 77×77-module QR carrying a
735-byte UR-style payload — realistic density for one frame of a signed PSBT.

Addresses are derived with embit from the published BIP39 test-vector mnemonic on **signet**
(`m/84'/1'/0'`). Nothing here is ever a live mainnet wallet.

## Run them

Nothing is installed into the project; `uv` fetches each stub's dependencies into a throwaway
environment.

```sh
cd prototypes/ui-surface

# (a) framebuffer TUI — Textual
uv run --python 3.12 --with embit --with segno --with textual python tui_textual.py

# (b) native toolkit — Qt6 via PySide6   (first run downloads ~130 MB)
uv run --python 3.12 --with embit --with segno --with pyside6 python qt_pyside.py

# (c) kiosk browser — localhost HTTP server, opens your browser
uv run --python 3.12 --with embit --with segno python browser.py
```

`space` flips between the review screen and the QR screen in all three. `q` quits (a) and (b);
ctrl-c stops (c).

## What to judge, in priority order

1. **Scannability.** Put the QR screen up and point your phone's camera at it. Which decode,
   how fast, from how far. This is a hard pass/fail and it transfers to the appliance almost
   exactly. For (a), make the terminal window large first: the QR needs **85 columns × 43 rows**
   of character cells, so an 80×24 terminal cannot show it at all.
2. **Information density.** Can a stranger about to move real money read the review screen
   without ambiguity, on one 1024×768-ish screen?
3. **Looks** — noted, but discount it. Font rendering, DPI, and the terminal's cell aspect ratio
   on macOS are all different from a Linux framebuffer, so impressions here are unreliable in a
   way the two criteria above are not.

## Known fidelity gaps

- macOS is not the target. (b) uses Qt because GTK4 here would test Homebrew, not the appliance;
  the fork being decided is "native toolkit or not", and GTK4-vs-Qt is a smaller, later question.
- (a)'s module aspect ratio depends on the terminal's cell being exactly 1:2. A Linux console with
  an 8×16 font gives square modules; your terminal may not.
- (c) proves the *rendering* is easy. It does not address the objection the ticket raises against
  it, which is about claim coherence, not looks.
