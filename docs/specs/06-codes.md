# 06 — The code registry

Every startup failure and every refusal carries a short code. This file is the registry: the record of
which codes exist, what each one means, and which promises we have therefore made.

## 1. What a code is for

The diagnostic already prints the **typed variant name** beside the code (`01-boot-layer.md` §9), and a
refusal already states its reason in plain language (`02-core.md` §7). So the code is not how anyone
learns what happened. It buys exactly two things:

1. **It is short enough to read off a panel and type into a bug report** without transcription errors —
   which matters on an appliance with no network, no logs the user can export, and no way to copy text
   off the screen. The code is the only thing that crosses the air gap on its way to us.
2. **It is the stable half.** `DisplayUnavailable` is a Rust identifier and a refactor may rename it;
   `AOBS-E02` is a promise. The variant name says what the implementation calls the arm; the code says
   what we told the world it was.

That second point is what makes this a registry rather than a list of names, and it is why the file
belongs to neither `aobs-core` nor the boot layer: both spaces are cited from `01-boot-layer.md`,
`02-core.md`, `04-screens.md`, `05-testing-and-release.md`, `docs/qa-checklist.md` and the code itself.

## 2. Two spaces, and the letter is the information

| Space | Reads as | Reached through | Ends in |
|---|---|---|---|
| `AOBS-E##` | *The appliance could not start.* | The app printing §9's diagnostic on a live kernel console — or, for `E00` alone, the wrapper printing it because the app never got that far | A halt with the text visible |
| `AOBS-R##` | *The appliance refused what you gave it.* | A live GUI, with copy, after §7's validation | Discard, and nothing else |

The two answer different user questions — *is my machine broken?* and *is this transaction bad?* — and
the letter carries that at a glance, which is the only thing a five-character string can usefully do.
A single interleaved space was rejected for exactly that: it throws away the one bit a code can carry
for free, and it makes every support answer begin with a lookup instead of a reading.

**The existing `E0x` codes were not renamed to match some tidier letter.** They are cited in ADR-0016,
`01-boot-layer.md` §7 and §9, `05-testing-and-release.md` §6.2, `docs/qa-checklist.md` and
`aobs/src/fail.rs`; `E` already reads correctly for *the appliance stopped*, and the one free
renumbering this project will ever get was spent on the `E02` correction in §5 instead.

## 3. What stability means when nothing can be updated

There is no update mechanism and ISOs stay in circulation, so **a code is permanent from the moment a
signed ISO carrying it ships** — the same discipline `02-core.md` §11's add-only version registry
already accepted, for the same reason: someone else's copy of the old behaviour never goes away.

- **Until the first signed ISO, this registry is mutable.** Nothing has shipped as this is written, so
  numbers can still move. That window closes exactly once and never reopens; §5's correction is the
  last renumbering.
- **After that, add-only.** A retired code is never reused for a different condition, a gap left by a
  deleted refusal stays a gap, and codes are never renumbered for tidiness. A hole in the sequence is
  cheaper than a code that meant two things in two releases.
- **Sequential within each letter**, with no grouping by tens. Grouped ranges invite an argument about
  which group a new refusal belongs to and then strand the unused half of every range; the letter is
  the only grouping this needs.
- **The code names the refusal, not the copy.** Where one refusal has several renderings — the *no
  input is ours* refusal has four (`02-core.md` §7) — they share one code. A user comparing two
  machines' behaviour is comparing which check tripped, not which sentence was chosen.

## 4. Not in this registry

- **Bytes that never became a PSBT.** `02-core.md` §7: *"failing to decode is not the same as
  rejecting"* — that is overwhelmingly a bad scan, it says so and returns to scanning, and giving it a
  code would file the commonest harmless event under the same heading as an attack.
- **A failed BIP-39 checksum on import.** The words stay on screen and the screen states what the check
  covers (`04-screens.md` §6). Nothing was refused and nothing was discarded.
- **The single advisory warning** on the fee row. A warning is not a refusal (ADR-0005), and coding it
  would invite the reading that it is one.

## 5. Startup failures — `AOBS-E##`

| Code | Condition | Note |
|---|---|---|
| `AOBS-E00` | **The binary never spoke.** `/usr/lib/aobs/launch` could not execute it at all — status 126 or 127: a missing shared library, a wrong interpreter, an image built wrong. | The wrapper's own code — the only one printed by something other than the app, and the only one whose remedy is *verify the download and write the medium again*. Found in the tree by [#57](https://github.com/allisson/aobs/issues/57) and added here; it predates this registry and is correct. Narrowed to those two statuses by [#69](https://github.com/allisson/aobs/issues/69): the wrapper reached this block on *every* status, including the app's own `exit 42`, so §2's shutdown printed *this image is built wrong* instead of powering the machine off. |
| `AOBS-E01` | The kernel CSPRNG returned no bytes. | Unchanged. |
| `AOBS-E02` | **No display at all**: no DRM device and no firmware framebuffer. | Narrowed here — see below. |
| `AOBS-E03` | The event loop returned. Nothing on this appliance asks it to. | Unchanged. |
| `AOBS-E04` | The program unwound out of an internal error. | Unchanged. |
| `AOBS-E05` | A framebuffer exists, and its pixel format is outside `LinuxFBDisplay`'s five accepted arms (`01-boot-layer.md` §7). | Split out of `E02`. |
| `AOBS-E06` | A framebuffer exists and its mode is below the 800×600 floor (`04-screens.md` §0). | New with [#55](https://github.com/allisson/aobs/issues/55). |

### The `E02` correction, and why it was worth the one free renumbering

`E02` had accumulated four meanings. `aobs/src/fail.rs` assigns it to `DisplayUnavailable`; ADR-0016
cites it for the absent `/dev/dri` node and, separately, for **a pixel format outside the five arms**;
`01-boot-layer.md` §9's table cites it for *"no firmware framebuffer, or one in a format the renderer
cannot negotiate"*; and #55 arrived with a mode below the layout floor.

Those cannot share a code, because §9 fixes the diagnostic's shape as **what failed / what it means /
what to do** and the third sentence differs in every case: *your firmware handed us no framebuffer* has
no remedy on this machine, *your firmware's pixel format is unsupported* is a supportable bug worth
reporting with the format in hand, and *this panel is too small* is neither. One code with four
meanings prints one remedy and is wrong three times.

**`E02`'s copy is also stale and must be rewritten.** `fail.rs` currently says *"This machine most
likely booted in legacy BIOS mode. aobs requires UEFI, which is what guarantees a display without a
graphics driver."* ADR-0016 falsified that reasoning: `vesafb` means a legacy-BIOS machine would in fact
have had a framebuffer, and UEFI-only now stands on build-and-test surface rather than on the display
path. The honest sentence names what was observed — no framebuffer was handed over — and stops guessing
at a cause.

**The tree carries this section** as of [#68](https://github.com/allisson/aobs/issues/68):
`aobs/src/fail.rs` holds six variants for `E01`–`E06`, `E02`'s copy names what was observed rather than
guessing at a cause, and a test asserts the code set is exactly this table's — a variant added later
with an invented code fails it. `E00` is deliberately absent from the enum, because the app cannot
report the case where it never spoke; the wrapper prints it.

**One inference the code makes, stated here because the registry is where it would be missed.** Slint
reports a failed window as a formatted string, which §9 forbids us to print and an upstream reword is
free to change, so `E02` and `E05` are told apart by **device presence**: nothing to draw on at all is
`E02`, and a display device that exists while the window still failed is `E05`. A display we could not
open for some third reason therefore prints `E05`. That is the safe direction — it asks for a bug
report we can act on, where the other direction would tell a user their firmware handed over nothing
when it did.

## 6. Refusals — `AOBS-R##`

Structural, from `02-core.md` §7:

| Code | Condition |
|---|---|
| `AOBS-R01` | Duplicate key in any PSBT map. |
| `AOBS-R02` | An input lacking a `non_witness_utxo` that hashes to its outpoint's txid (taproot excepted). |
| `AOBS-R03` | A sighash other than `SIGHASH_ALL`, or `SIGHASH_DEFAULT` for taproot. |
| `AOBS-R04` | The sum of outputs exceeds the sum of inputs. |
| `AOBS-R05` | An input whose script type is outside BIP44/49/84/86 single-sig — **including a taproot input that does not declare its key path in full** ([#82](https://github.com/allisson/aobs/issues/82), [#113](https://github.com/allisson/aobs/issues/113), `02-core.md` §8a). Widened twice rather than given a code of its own, because BIP-371's declaration that the spend *is* a key path has two halves and an input carrying only one has not declared the script type this row is about: `PSBT_IN_TAP_INTERNAL_KEY` (#82), **and** a `tap_key_origins` entry keyed by that key with no leaf hashes (#113) — an entry with leaf hashes being a script-path key, which is what makes it a declaration of something else. |
| `AOBS-R06` | No input re-derives to our own key material. **Four copy variants, one code** — the passphrase, account 0, the loaded network, and the coin-type mismatch (`02-core.md` §7). |
| `AOBS-R07` | An output we cannot render as an address. |
| `AOBS-R15` | More than six outputs, payment and change counted together — the review panel is non-scrolling and holds six rows in the minimum canvas ([#58](https://github.com/allisson/aobs/issues/58)). Numbered after `R14` rather than beside the other structural refusals, because the registry is sequential and never renumbered for tidiness. |
| `AOBS-R16` | The inputs sum to more than 21 000 000 BTC. Consensus caps the supply, so such a transaction describes UTXOs that cannot exist — and a taproot input carries only its `witness_utxo`, which nothing cross-checks, so two of them claiming `u64::MAX` would overflow every number the review panel is about ([#80](https://github.com/allisson/aobs/issues/80)). Numbered after `R15` for the same reason `R15` is where it is. |

From the derivation check:

| Code | Condition |
|---|---|
| `AOBS-R08` | An output claiming to be ours fails the `scriptPubKey` byte-compare. |
| `AOBS-R09` | Change on a path we would never scan — `path[-2] ∉ {0, 1}`, or a hardened final index. |

From the QR boundary (`03-transport.md` §2, `04-screens.md` §11.1):

| Code | Condition |
|---|---|
| `AOBS-R10` | A wrong-class payload at a prompt expecting another class. |
| `AOBS-R11` | The 1,024-part budget is spent without the stream completing. |

From backup restore (`02-core.md` §11, `04-screens.md` §10):

| Code | Condition |
|---|---|
| `AOBS-R12` | An unknown backup version byte. |
| `AOBS-R13` | A malformed backup header: reserved flag bits set, an `entropy_len` outside {16, 20, 24, 28, 32}, or a total length that disagrees with it. |
| `AOBS-R14` | The Poly1305 tag does not authenticate — a wrong password, or a damaged file, and the copy must not claim to know which. |

#58's output-count refusal landed as `AOBS-R15`, above — the next free number at the time, listed with
the structural refusals it belongs to rather than renumbered into their block, and #80's amount bound
landed as `AOBS-R16` the same way. The sequence records the order decisions were made; the table's
grouping is for reading.

## 7. The registry is enforced by tests, not by discipline

`05-testing-and-release.md` §5 already requires that **every refusal gets a named case** in the
adversarial corpus. The code is that name, so:

- **Each corpus case asserts the code its refusal carries.** A code changed by accident fails a test
  rather than shipping.
- **The registry and the corpus are asserted to be in bijection** — every code in §6 has exactly one
  corpus case and every case names a code in §6. A refusal added in code with an invented code fails
  this, which is the whole reason this file exists.
- **Codes stay distinct within a space**, extending the test `aobs/src/fail.rs` already carries for the
  startup space.
- **`docs/qa-checklist.md` quotes codes** wherever a hand-checked row expects a refusal or a halt, so a
  human runs the same names the tests do.

**The tree carries this section** as of [#79](https://github.com/allisson/aobs/issues/79):
`aobs-core/src/corpus_tests.rs` is the corpus and the bijection, and it reads §6's tables out of
this file with `include_str!` rather than copying them into a constant — a copy is a second place
to forget. Two things it settles, both stated here because a later reader would otherwise take
the prose above literally and find it does not hold:

- **The bijection is between the two *sets of codes*, not between cases and codes one for one.**
  `05-testing-and-release.md` §5's own list of cases names duplicate keys in *each* map and both
  halves of the `non_witness_utxo` rule — four cases carrying two codes — so a
  one-case-per-code reading contradicts the list it sits next to. *Exactly one* above means the
  relation is total in both directions, and the enforced form is: every code a refusal can carry
  has at least one case, and every case names a code this file defines.
- **The direction that needs every code implemented is deferred, not weakened.** A `PENDING`
  list names each code whose refusal does not exist yet and the ticket that owes it — now
  `R12`–`R14`, all to [#85](https://github.com/allisson/aobs/issues/85). `R06`, `R08` and `R09`
  left the list with [#80](https://github.com/allisson/aobs/issues/80), which added `R16` already
  implemented and so never on it, and `R10` and `R11` left it with
  [#77](https://github.com/allisson/aobs/issues/77) — and a test asserts that the implemented
  codes and the pending ones together are **exactly** §6's tables. A code added to §6 that is
  neither implemented nor owed fails it; so does a code left on the pending list after its
  refusal ships. The list only ever shrinks, and it is empty at the release gate.
- **The corpus is two tables, because the QR boundary's cases do not all end in a refusal.**
  `05-testing-and-release.md` §5's transport list includes the 64 KiB boundary *exactly at the
  limit*, which is an **acceptance**, and several bounds that drop the symbol with no code at all
  (§4 above). So a transport case states the outcome it expects rather than only a code, and only
  the refusing ones contribute to the bijection. A table that could express refusals alone would
  have had to leave §5's own cases out.
