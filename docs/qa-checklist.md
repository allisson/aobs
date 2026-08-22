# QA checklist — by hand, because CI cannot

`05-testing-and-release.md` §6.3 names what QEMU cannot answer. This file is the running
list, extended as each slice lands. Nothing here is a substitute for a CI gate; these are
the claims that need a person and a machine.

A tested-hardware list is published with each release, naming exactly what was verified
rather than implying broader support (§6.3).

## Walking skeleton — [#39](https://github.com/allisson/aobs/issues/39)

### Found by building it: `simpledrm` is not in Debian's kernel

**ADR-0009's guaranteed display path does not exist on the distribution we ship.** Debian 13's
`linux-image-6.12.101+deb13-amd64` config carries:

```
# CONFIG_SYSFB_SIMPLEFB is not set
# CONFIG_DRM_SIMPLEDRM is not set
```

There is no `simpledrm.ko` anywhere in the built image, and a UEFI boot of the built ISO logs
`fb0: EFI VGA frame buffer device` — **`efifb` claims the framebuffer**. `efifb` is fbdev, not DRM,
which is exactly the "vesafb-class fbdev … which Slint cannot render to" that ADR-0009 attributes to
legacy BIOS. It applies to UEFI on Debian too.

The consequence inverts the ADR: **the native KMS driver (`i915`, `amdgpu`, `radeon`, `nouveau`) is
the requirement, not the optimisation, and there is no fallback.** A UEFI machine with no supported
GPU gets `AOBS-E02` and no screen.

Observed end to end against the built ISO under OVMF + `ramfb`: the appliance starts, measures
entropy, finds no DRM device, prints the §9 diagnostic and halts with it visible — the failure path
works, on the artifact. What does not work is the assumption underneath it.

**This is a ticket, not something to improvise** — [#40](https://github.com/allisson/aobs/issues/40),
which carries the evidence and the options. Each way out reverses a settled decision.

### The claim the whole slice exists to retire

- [ ] **It boots on at least one real UEFI machine and draws the screen.** The claim moved
      with ADR-0016: the fbdev tier — `efifb`, not `simpledrm` — is what serves a machine
      with no native KMS driver, and it has only ever been watched under QEMU + `ramfb`.
      Record the machine: make, model, year, **panel resolution**, GPU, and which tier won
      (the readiness line says `display=fbdev` or `display=drm`).
- [ ] The version string and build date on screen match the ISO that was written to the
      stick (01-boot-layer.md §10).

### Boot menu and RAM

- [ ] Both GRUB entries appear, and only those two (§7).
- [ ] The default entry boots with `toram`, and **the USB stick can be pulled once the
      screen is up** without the session dying.
- [ ] The *low memory: keep the USB inserted* entry boots on a machine below the floor and
      degrades rather than bricking.
- [ ] **Measure the RAM floor against the built image.** Provisional at 2 GiB minimum /
      4 GiB recommended; the real number is owed (`00-overview.md`).

### Entropy

- [ ] Read `AOBS_ENTROPY_MS` off the console on real hardware, on at least one low-end
      machine. Derived as 1–16 s under `random.trust_cpu=off`; **derived, not measured**,
      and this is the measurement (§8).
      *First data point, and it does not discharge the obligation:* **11 695 ms** in QEMU
      under TCG with no `virtio-rng`, inside the derived band. A VM with an idle CPU and no
      devices is close to the worst case for timing jitter, so treat this as an upper
      bound to beat, not as the number.
- [ ] `dmesg | grep -E 'crng init done|RDRAND is not reliable'` — the verification §8
      names.

### No shell escape (§2)

- [ ] Ctrl+Alt+F1 … F6 reach no login prompt.
- [ ] Alt+SysRq+B does nothing.
- [ ] The app restarting leaves a blank signer, not a broken screen. There is no way to
      kill it from the appliance itself, which is the point — provoke it from a
      development build. Crash behaviour is a stated product fact, not an incident.

### No network (§3)

- [ ] With an Ethernet cable plugged in at boot, no interface appears and no link is
      brought up. There is nothing on the image to check this with, so check it from the
      switch or the other end of the cable.
- [ ] The published package manifest lists no `firmware-*` package.

### The failure path (§9)

- [ ] Provoke a startup failure (a development build is the practical way) and confirm the
      block appears and the machine **halts with it visible** rather than rebooting or
      powering off. `Restart=always` must not scroll it away.
- [ ] **Open question, worth answering here rather than guessing.** The image carries
      `grub-efi` only, so a legacy-BIOS machine is refused by its own firmware and never
      reaches any diagnostic of ours. UEFI-only now stands on build-and-test surface rather
      than on "no display path exists" (ADR-0016), which makes this a *product* question
      rather than a technical one. Boot one and record what the user actually sees; if it is
      worse than blackness with no explanation, that is a ticket, not a fix to improvise.
- [ ] The code printed matches `docs/specs/06-codes.md` — `AOBS-E02` for no framebuffer at
      all, `AOBS-E05` for a format outside the renderer's five arms, `AOBS-E06` for a mode
      below 800×600, and `AOBS-E00` only when the wrapper prints it because the binary never
      spoke.
- [ ] The block is a human-written paragraph and a failure code — not a stack trace, and
      **no formatted program state**.

## Reconciled against ADR-0016 and the panel map — [#57](https://github.com/allisson/aobs/issues/57)

Rows that only exist because `image/` was brought back in line with `docs/specs/`. Each one
guards a claim the tree used to contradict.

### The RAM wipe rests on an absence (§5, [#62](https://github.com/allisson/aobs/issues/62))

§5 claims `init_on_free=1` and nothing else, because nothing secret is written to a
filesystem. That is a checkable claim and these rows are the check — a development build is
the practical way to run them, since the shipped image offers no shell.

- [ ] After a **full session** — create a wallet, load it with a passphrase, sign a
      transaction, reach the shutdown screen — the overlayfs upper dir holds **nothing the
      app wrote**. List it and read the list; do not sample it.
- [ ] Nothing in `/run/log/journal` carries secret material: no mnemonic, no passphrase, no
      key, no backup password, no PSBT contents.
- [ ] No file anywhere on the writable layer is owned by `signer` other than an empty home.
- [ ] `swapon --show` is empty and `/proc/swaps` lists nothing (§4, and the wipe assumes it).

### No seat daemon (§2, ADR-0016)

- [ ] `ps` shows no `seatd`, and the published package manifest lists neither `seatd` nor
      `libseat1`. If either is back, the image and the crate's `backend-linuxkms-noseat`
      have drifted apart and the fbdev tier is dead again.
- [ ] On a machine with **no** DRM device, the readiness line says `display=fbdev`. That is
      the whole point of `-noseat`: under the seatd backend the `/dev/fb0` open was
      delegated to a daemon that hands back DRM and evdev nodes only.

### The serial mirror (§2, §9)

- [ ] On a machine **with** a serial port, capture everything that reaches it across a full
      session — boot, wallet load, a signature, shutdown — and confirm it is **only** the
      lines that were also on the panel. Anything serial-only is a channel nobody decided on.
- [ ] No secret material appears there: no mnemonic, no passphrase, no key, no backup
      password, and no PSBT contents.
- [ ] On a machine with **no** serial port, nothing changes and nothing fails — the open is
      allowed to fail silently.

### The console detach (§2, §7, [#52](https://github.com/allisson/aobs/issues/52))

- [ ] On the fbdev tier, provoke kernel output while the app is drawing (an NMI, or a
      `pr_emerg` from a development build) and confirm **the panel is unchanged**.
- [ ] Nothing from `console-detach` or `console-attach` ever appears on the panel. They log
      to the journal; anything written to the unit's stdout after the first frame *stays*
      on screen, because Slint does not repaint it away.
- [ ] Stop the service and confirm the console comes back — that is the channel §9 needs
      exactly when the GUI is gone.
- [ ] `TTYVTDisallocate=yes` is **not** in the unit. #52 watched the service die five times
      behind a black panel with it present. Do not add it back without re-running that probe.

### The keymap ([#54](https://github.com/allisson/aobs/issues/54))

- [ ] On a **non-US** physical keyboard, every printable ASCII character can still be typed
      into the passphrase field — the legends lie, nothing is unreachable, and that
      reachability is the entire argument for offering no layout picker.
- [ ] The passphrase and seed-import screens **name the layout** before the user starts.
- [ ] Dead keys do nothing anywhere: `XKB_DEFAULT_VARIANT` and `XKB_DEFAULT_OPTIONS` are
      unset, not set to an empty string.

### Panel modes ([#55](https://github.com/allisson/aobs/issues/55))

- [ ] On a panel larger than the design size, type is **larger**, not the layout roomier —
      1920×1080 and 3840×2160 should both look like a 1422×800 canvas scaled up.
- [ ] At 800×600 the review panel draws **stacked**, non-scrolling, with a 62-character P2TR
      address complete on screen. The appliance prints
      `AOBS_REVIEW … address-required=… address-available=… address-one-line=yes` on every boot
      and CI asserts it ([#81](https://github.com/allisson/aobs/issues/81)), so what is left for
      a person here is whether it is **legible** at arm's length on a real panel — the numbers
      say it fits, not that it reads.
- [ ] Above the design width the money facts sit **beside** the outputs, and below it **above**
      them, with nothing dropped in either state. **QEMU cannot show this**: `screendump` on the
      DRM tier captures the console plane, not ours, so the rail's drawn form has only ever been
      seen in a forced-wide build at the floor.
- [ ] A mode below 800×600 halts on `AOBS-E06` with the diagnostic on a live console, rather
      than drawing something cramped.

### The output bound ([#58](https://github.com/allisson/aobs/issues/58))

- [ ] Six outputs fit the review panel at 800×600 with nothing clipped and no scroll region.
      **The measurement is discharged** ([#81](https://github.com/allisson/aobs/issues/81)): 447
      logical px against 458, as `AOBS_REVIEW … rows-fit=yes` on every boot, so the bound is
      fixed at six. What a person still checks is that six rows at that density are *readable*
      rather than merely present.
- [ ] A seven-output PSBT is refused with `AOBS-R15` before any review screen is drawn, on a
      screen whose only action is **discard** — no *proceed anyway* anywhere on it, and no way
      to reach the panel from it.

### The review panel and the walk ([#81](https://github.com/allisson/aobs/issues/81))

- [ ] Every character of every **payment** address is on screen, in 4-character groups separated
      by a gap narrower than a monospace cell — compare it against the coordinator's own screen
      character by character, which is the thing this whole appliance is for.
- [ ] Change says it was **re-derived from the seed at its path and matched byte for byte**, and
      the path is written the way the identity screen writes paths (`h`, never `'`).
- [ ] The advisory warning, when it fires, is a full sentence **on the fee row** — no icon, no
      banner, no screen of its own, and no key to press to make it go away.
- [ ] Pressing *sign* shows **one screen per payment address** and no screen for change, with the
      fee statement absent from all of them; Escape from any of them returns to the panel with
      the transaction intact.
- [ ] Escape from the panel itself returns to the identity screen and the transaction is gone —
      pressing *sign a transaction* again starts from the camera, not from where you left off.

### The gate and the outbound animation ([#82](https://github.com/allisson/aobs/issues/82))

- [ ] **A tap on Enter at the gate signs nothing.** Press and release quickly, several times: the
      bar fills a little and empties, and no signature is produced. This is the row the whole
      asymmetry rests on, and the failure it exists for is a backend that stops delivering key
      releases — after which a tap would sign three seconds later.
- [ ] Holding Enter for **three seconds** produces the signature and the animation, and the bar is
      a bar rather than a counting-down number.
- [ ] Moving the cursor off the hold row **mid-hold** abandons it. So does Escape.
- [ ] The gate looks **identical** on a transaction that trips the advisory warning and one that
      does not — same rows, same copy, same hold — and the hold takes the same three seconds.
- [ ] *Do not sign* is a **single press**, and the transaction is gone afterwards: the identity
      screen offers no way back to it.
- [ ] The outbound screen shows the title, the symbol and **one static sentence** naming the part
      count — no counter, no percentage, no amounts, and **no *sign another***.
- [ ] A **single-part** payload says nothing at all about parts. Sign a small transaction to reach
      it; a 1-in/1-out spend is one part.
- [ ] **The animation loops with fresh parts.** Watch a multi-part one for longer than one pass:
      the symbols keep changing rather than cycling through the same four.
- [ ] *Done* returns to the identity screen with **no confirmation prompt**, and the *show the last
      signed transaction again* row is now there.
- [ ] Re-displaying it produces the **same transaction** — hand it to the coordinator and it
      finalizes. Sign a second transaction and the row shows **that** one instead: there is no list
      and nothing to select.
- [ ] **A real coordinator finalizes and broadcasts it.** Sparrow and Specter Desktop, on signet, at
      least once per release — the row `05-testing-and-release.md` §6.3 owes, and the one that would
      catch `03-transport.md` §6a's open interoperability question about the CBOR wrapper ([#112](https://github.com/allisson/aobs/issues/112)).
- [ ] **A phone camera reads the symbol at arm's length**, at 800×600 where the square is 258 px
      (`04-screens.md` §11.5). This is §6.4's owed measurement; if it fails the cap moves to v40 and
      the fragment length is re-derived.

### The taproot key-path declaration ([#113](https://github.com/allisson/aobs/issues/113))

Two crafted PSBTs, the same way the seven-output row is fed one. Both existed before and reached the
review panel, the gate and *Signed. Show this to your wallet.* over a document with nothing added to
it — which is what makes these rows about honesty rather than about money.

- [ ] A taproot PSBT whose `PSBT_IN_TAP_INTERNAL_KEY` **no `tap_key_origins` entry names** is
      refused with `AOBS-R05` before any review screen is drawn, on a discard-only screen.
- [ ] A taproot PSBT whose internal key's own entry declares a path we never scan, while a second
      entry declares the path that really derives the input, is refused with `AOBS-R06` — the
      *no input is ours* screen, naming the passphrase, account 0 and the network. **The copy
      misnames the cause here and that is the accepted cost** (`02-core.md` §8a): what the row
      checks is that the transaction never reaches the panel.
- [ ] And the honest side is unchanged: an ordinary taproot spend from a real coordinator still
      reaches the panel, signs, and finalizes.

### An input arriving pre-signed ([#115](https://github.com/allisson/aobs/issues/115))

The last corner of the shape above, and the same kind of row: this PSBT reached the panel, the gate
and *Signed. Show this to your wallet.* over a document with nothing added to it, because `bitcoin`
0.32's taproot path silently declines an input whose `tap_key_sig` is already set. Crafted PSBTs, fed
the way the seven-output row is.

- [ ] A taproot PSBT of ours carrying **64 arbitrary bytes in `tap_key_sig`** is refused with
      `AOBS-R17` before any review screen is drawn, on a discard-only screen. The copy says the input
      already carries a signature and names the input **one-based**.
- [ ] The same for a P2WPKH PSBT of ours carrying a `partial_sigs` entry, and for one carrying a
      `final_script_witness` — all three are `AOBS-R17`, which is the width the decision took
      (`02-core.md` §7): the finalized encoding is the same signature after a Finalizer moved it.
- [ ] A PSBT whose pre-signed input is **not ours** is refused with `AOBS-R17` too, not with
      `AOBS-R06`. The check needs no key material, so it runs first — that ordering is the row.
- [ ] And the honest side is unchanged: an ordinary spend with no signature fields still reaches the
      panel, signs, and finalizes.

### The message a coordinator actually reads ([#112](https://github.com/allisson/aobs/issues/112))

**The release-gate row**, and the only one on this list that needs another wallet rather than
another PSBT. `03-transport.md` §1's message form was settled against Sparrow's and Specter's own
source and against BCR-2020-006's published vector, all three of which are now assertions in the
suite — but *finalized, and broadcast* is a claim no test in this tree can make, because our
decoder reads our own encoder and symmetry holds whichever convention we picked
(`05-testing-and-release.md` §6.3).

On **signet**, with a wallet loaded from a mnemonic both sides know:

- [ ] **Sparrow, outbound.** Build a spend in Sparrow, show it as a QR, scan it on the appliance,
      sign, and scan the appliance's animation back into Sparrow. Sparrow **finalizes** it and
      **broadcasts** it. Do this once for a single-frame payload and once for a multi-frame one.
- [ ] **Sparrow, inbound, multi-frame.** The animation Sparrow displays for a PSBT above one frame
      is read to completion. The progress fraction advances and the panel draws.
- [ ] **Specter Desktop, outbound.** The same round trip, finalized and broadcast.
- [ ] **Specter Desktop, inbound.** Specter's animation is **uppercase multi-part**
      (`qr-code.html`: `nextPart().toUpperCase()`), which is the exact shape that was silently
      dropped before #112 — every frame reported as a bad scan, with nothing on screen to say why.
      This row is the one that catches it coming back.
- [ ] **The broadcast transaction pays what the panel said.** Compare the txid's outputs and fee
      against the review panel's own numbers, which is the only end-to-end check that
      `04-screens.md` §11.2's mitigation describes the transaction that actually settled.

### Creating a wallet ([#72](https://github.com/allisson/aobs/issues/72))

- [ ] At 800×600, **two columns of 12 words are all on screen at once** — 1–12 left, 13–24
      right — with the banner above and nothing clipped at the foot. The appliance prints
      `AOBS_WORDS required=… available=… fits=yes` on every boot and CI asserts it, but the
      number is a sum of the heights the layout is built from; this row is a person looking
      at the panel it produced.
- [ ] **The fill is column-major.** Word 13 is the top of the right-hand column, not the
      second row of the left one. A row-flow grid renders 1,2 / 3,4 and passes every
      arithmetic check while inverting the reason the shape was chosen.
- [ ] The dice screen shows a **roll count and nothing else** — no bit counter, no progress
      meter, no percentage, and no hash of the rolls anywhere on it.
- [ ] With a **USB webcam plugged in**, creating a wallet is indistinguishable from creating
      one without it: no preview, no message, no extra second of visible wait. That is the
      whole of the observable behaviour, since the frame only ever reaches a hash.
- [ ] With the camera **unplugged mid-gather**, the same holds: the screen says nothing and
      Continue still unlocks.
- [ ] On a machine where the pool is genuinely slow, the wait counts seconds and Continue
      stays locked until it is over — and the screen **never advances on its own**, even
      after the count stops.

### The word-entry component and the creation retype ([#73](https://github.com/allisson/aobs/issues/73))

- [ ] At 800×600 the retype draws **24 slots in two columns of 12**, the banner above them and
      the Done row below, with nothing clipped. The sum is the same 440 px `AOBS_WORDS`
      already asserts — the screen is built from the same heights — so what this row catches is
      the one thing the sum cannot: the banner's live second line wrapping to a third.
- [ ] **The phrase is nowhere on the retype screen.** Not ghosted, not greyed, not in a
      corner: the only words on it are the ones being typed.
- [ ] Four letters and the space bar place a word, and typing the whole word without a space
      places **nothing** — the slot stays empty until the space lands.
- [ ] **Type a wrong word.** The screen goes back to the phrase with that position marked, the
      copy names the number, and pressing on returns to the retype with **every word already
      typed still there** and the cursor on the position that was refused. Nothing on either
      screen offers to start the retype over.
- [ ] **With caps lock on, nothing lands** and the screen names each ignored key. That is
      02-core.md §4's third behaviour applied literally — the wordlist is `a`–`z` — and it is
      the one place a person can judge whether naming the key is enough to be understood.
- [ ] Backspace at an empty slot steps back and **returns the previous word as editable text**,
      not as a re-selected slot: the next backspace deletes a letter of it.
- [ ] The ghosted completion after the caret is legible but plainly dimmer than the letters
      typed, at the settled type size on a real panel.

### Seed import ([#75](https://github.com/allisson/aobs/issues/75))

- [ ] At 800×600 the import screen draws the same **24 slots in two columns of 12**, the banner
      above and the Done row below, with nothing clipped. It is built from the same heights the
      retype is, so `AOBS_WORDS` covers the sum — what this row catches is the banner's live
      second line wrapping to a third, and the Done row's longer note doing the same.
- [ ] **Before a key is pressed, the screen names English and the US keyboard.** This is the
      only warning a person gets, and the failure it warns about is silent from the other side:
      a French or Spanish mnemonic simply will not type.
- [ ] **Try to type a non-English word.** `café` stops at `caf` and every keystroke after it is
      named as ignored — the wall, on a real keyboard, with the legends the machine actually has.
- [ ] **Type twelve words.** Done unlocks; the twelve slots below stay empty and visibly so. Type
      a thirteenth and Done locks again, stating the five lengths.
- [ ] **Type a real phrase with two words swapped.** The screen says the check covers the phrase
      as a whole and cannot say which word is wrong, **every word stays on screen**, and the
      cursor is where it was left. Correcting the two words and pressing Enter reaches the load
      screen.
- [ ] **Walk to slot 20 with eleven words typed and settle one there.** Done stays locked at
      twelve settled slots — the hole is refused, and the word at slot 20 is still there.
- [ ] *Restart or shut down* is reachable from the import screen at every moment, and it is the
      only thing on the appliance that clears the words.

### Verify a receive address ([#83](https://github.com/allisson/aobs/issues/83))

**Not walked on an ISO, and this is where that is paid for.** The two verdict screens are
structural copies of ones [#81](https://github.com/allisson/aobs/issues/81) already walked and
fixed — an `AddressBlock` in a `VerticalLayout`, and a wrapped `Text` in the refusal screen's
crit box — and the pair sums to about 235 logical px against the 458 `AOBS_WORDS` reports at
the floor, so no measurement was at risk. What was not checked is everything below, and reaching
any of it needs a camera, which QEMU has none of (§6.3).

- [ ] **Scan one of your own addresses off a coordinator.** The verdict names the derivation
      path, the branch and the index as three separate statements, and the address is drawn in
      4-character groups at §11.3's larger type — which means it **wraps** at 800×600, in the
      groups and never mid-group.
- [ ] **Scan the same address as an uppercase QR** (Sparrow and Specter both emit bech32 that
      way). It matches, and the address on screen comes back **lowercase** — what is drawn is
      what we derived, not what was scanned.
- [ ] **Scan a `bitcoin:` URI with an amount and a label in it.** It matches, and nothing of the
      query string appears anywhere on the screen.
- [ ] **Scan an address that is not yours.** The headline is *"This address is not yours."* with
      the weight of a refusal and **no code beside it**, and the line under it names all four
      account paths, both branches and indices 0 to 999. The scanned string is nowhere on the
      screen.
- [ ] **Scan a base58 (BIP44 or BIP49) address of yours with its case changed.** It reports *not
      yours*, which is the direction that would otherwise be a false **yes**.
- [ ] **§6.4's owed measurement: read `AOBS_SEARCH` off the serial console on real hardware**,
      on a scan that reports *not yours* — `matched=no` is the only reading that walked the whole
      8,000-derivation window. The dev-machine figure is 246 ms (release, Apple silicon).
- [ ] **And judge the freeze while you are there.** The search is synchronous on the event-loop
      thread and 04-screens.md §12 specifies no wait screen, so between the last camera frame and
      the verdict the appliance draws nothing new. At a few hundred milliseconds that is right; if
      it reads as a hang on the slowest machine tested, that is the open ticket §12 names — and the
      two levers are §6.4's own fallback (narrow the window, and say what was searched) or a wait
      screen, which is a decision the number has to come first for.
- [ ] **Both verdicts return to the wallet screen** on the one row and on Escape, and the hub is
      byte-identical to the one the scan was started from.
