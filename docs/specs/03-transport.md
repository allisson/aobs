# 03 — The QR boundary

QR is the only data channel, both directions. Everything crossing it is hostile input.

Sources: [#2](https://github.com/allisson/aobs/issues/2),
[#13](https://github.com/allisson/aobs/issues/13),
[#19](https://github.com/allisson/aobs/issues/19),
[#21](https://github.com/allisson/aobs/issues/21),
[#27](https://github.com/allisson/aobs/issues/27),
[#30](https://github.com/allisson/aobs/issues/30),
[#31](https://github.com/allisson/aobs/issues/31),
[#5](https://github.com/allisson/aobs/issues/5),
[#67](https://github.com/allisson/aobs/issues/67),
[#94](https://github.com/allisson/aobs/issues/94).

## 1. Format

**BC-UR / UR2 for PSBTs, both directions.** Emit `ur:crypto-psbt`; accept `crypto-psbt`, `psbt` and
`bytes`.

Emit the **deprecated `crypto-psbt` spelling**, not the registry's newer `psbt`/40310: Sparrow
decodes `psbt` but never writes it, and Specter's scanner regexes match only `UR:CRYPTO-*` and
`UR:BYTES/`, so `ur:psbt/…` falls through unhandled.

**The UR message is a CBOR definite-length byte string wrapping the payload**, on every type we
read or write — `crypto-psbt`, `psbt` and `bytes` alike. Decided on coordinator source, not docs
([#112](https://github.com/allisson/aobs/issues/112); `docs/research/02-qr-transport-format.md`
§7): Sparrow's `CryptoPSBT.toCbor()` returns a `ByteString` and its `fromCbor` casts to one,
Specter's `CryptoPSBT.toDataItem()` wraps a `Buffer` and its `fromDataItem` unwraps one, and
**neither accepts a bare document** — a PSBT's first byte `0x70` is a CBOR *text* string of 16, so
Sparrow throws and Specter's `getData()` returns something that is not the PSBT. BCR-2020-006's own
published example is the same shape (`58 A7` and then 167 bytes), and it is a checked-in fixture
because it is the one transport case not written by us.

Three consequences, each load-bearing:

- **It is a property of the type and never of the screen.** `ur:bytes` cannot mean CBOR at the
  signing prompt and raw at the restore prompt, so §7's encrypted backup carries the wrapper too —
  two bytes on a 67-byte payload, nowhere near version 20's budget at ECC H.
- **`messageLen` is the wrapped length**, which is what §3's bounds and every figure in §9 are
  stated over. Nothing in §9 moves: the ceiling charges `messageLen` its `u32` maximum, and §9.2's
  and §9.3's figures were computed this way and reproduce exactly. What moves is which *payload*
  produces each message — §9.3's *"a message of exactly 960 B"* is a 957-byte PSBT.
- **We are strict about shape and permissive about width.** One byte string and nothing else:
  trailing bytes and the indefinite-length form are refused, because the registry says
  *deterministic length* and a payload arriving in chunks is a second parser. A non-minimal header
  is read, because the payload it yields is byte-identical and refusing it would fail an honest
  coordinator to enforce nothing. A message that is not the registry's form is a **discard with no
  code** (§4, `06-codes.md` §4) — the type string was right, so from the screen's side it is
  indistinguishable from a bad scan.

**Emit the uppercase spelling** — `UR:CRYPTO-PSBT/…` — because Specter's scanner regexes match
`UR:CRYPTO-*`, and because it buys QR alphanumeric mode for free (§8). This is the requirement §8
refers back to.

**Accept either case, all the way down**, which is not free: `ur` lowercases before it looks at
anything, and our own `messageLen` pre-reader (§3's ordering) has to do the same or every part of an
**uppercase multi-part animation** fails on the bytewords alphabet. Specter emits exactly that
(`qr-code.html`: `this.encoder.nextPart().toUpperCase()`), so it is the ordinary case rather than an
edge one — and it was a defect until #112, reported to the user as a bad scan with nothing on screen
to distinguish it from one.

BBQr was measured and lost on one fact: **its supported set is a strict subset of BC-UR's.** Nothing
in scope does BBQr and not UR2; Specter Desktop does UR2 and not BBQr. Choosing BBQr subtracts
Specter and adds nobody. Density does not decide it (frames are within one of each other at our
sizes) and neither does fountain coding (at N ≤ 4 the advantage is at most ~1.2 s even at 50% frame
loss) — **do not cite fountain coding as the justification for this decision later.**

Electrum is unreachable by animated QR whatever we chose: no `ur:`, no BBQr, no chunking, and its
`to_qr_data()` deliberately emits an incomplete PSBT.

### The cost we took, stated plainly

`ur` 0.5.x — the crate behind the `dspicher/ur-rs` repository, and **not** the unrelated crates.io
package named `ur-rs` — is the riskier parser, and we adopted it knowingly:

- `Decoder::receive` adopts `sequence_count` from the **first part it sees, unvalidated**. One frame
  declaring `seqLen = 0xFFFFFFFF` asks for a `Vec<usize>` and a `Vec<f64>` of 4.29 billion elements
  — ~34 GB each, on a no-swap LiveCD, **before any key material is touched**.
- Its fountain decoder is **unfuzzed upstream**. Upstream targets cover `bytewords_decode`,
  `bytewords_encode` and `ur_encode` only.

Two obligations fall out and are requirements, not notes: **clamp at our call site** (§3), and
**write the fountain-decoder fuzz target ourselves** (`05-testing-and-release.md`).

### Capacity, for sizing decisions

| Transaction | `witness_utxo` only | + `non_witness_utxo` |
|---|---|---|
| 1-in/2-out P2TR (BIP86 key-path) | 385 B | 634 B |
| 10-in/2-out P2WPKH (BIP84) | 1 494 B | 3 744 B |

Size against the right-hand column: we *require* `non_witness_utxo` on every non-taproot input, and
Core attaches it anyway. Per frame at v40-L, BC-UR carries 2 112 B.

## 2. Payload classes — the scanner only ever accepts what this screen asked for

**No screen can be handed a payload it did not ask for.** This is a smaller surface than one scanner
accepting the union of every type, and it is enforced by construction rather than by a check.

| Class | Caller | Accepted |
|---|---|---|
| `Psbt` | Signing | Multi-part `ur:crypto-psbt` / `psbt` / `bytes`, under §3's bounds. |
| `Address` | Receive verification | **One** QR symbol, single-part **plain text**, ≤ 256 bytes, printable ASCII `0x20–0x7E` or rejected. Multi-part not accepted at all. |
| `Backup` | Encrypted-backup restore | Single-part `ur:bytes` **only**, total length exactly one of `{51, 55, 59, 63, 67}`, `version == 0x01`, reserved bits zero, `entropy_len` in set. |

Two of the three classes therefore **never touch the fountain decoder at all** — the address class
because coordinators emit receive QRs as plain text or a BIP-21 URI and never as a UR, and the backup
class because it is single-part by rule. That is not an accident; it is the second and third path to
remove itself from the reach of the riskiest parser in the tree.

**The class check lives in core, not the shell.** The shell hands core the decoded string **plus the
expected class** and receives a typed outcome; it compares nothing itself. *"Is this the class this
screen asked for"* is a branch on a validation outcome, which the shell is forbidden. This puts the
payload-class guarantee inside the 98% bar instead of in the untested layer.

## 3. The four bounds, enforced at our call site

Before any part reaches `ur`:

| Bound | Value | What it stops |
|---|---|---|
| `messageLen` | ≤ 64 KiB | ~17× the largest realistic payload (3 744 B). Generous enough that no honest user reaches it. The bound is on the **message** — §1's CBOR byte string, which is what the decoder allocates — so the largest PSBT it admits is 65 533 bytes. |
| `seqLen` | ≤ 64 frames | 64 KiB at v40-L density is ~32 frames; 64 leaves room for sparser v27 codes without admitting a four-billion-frame claim. |
| **Total parts accepted** | ≤ 1024, then refuse | `seqLen` bounds the *claim*; this bounds the *work*. Fountain coding lets a hostile animation feed well-formed parts forever without completing, and only a counter on parts actually received stops that. |
| UR type | Checked **before** decoding | Not after. |

**No wall-clock scan timeout.** Cancel stays live at all times, which is what a user with a bad
camera angle actually needs. Bounded *work* is the security property; a timer would add a failure
mode — giving up on a slow but honest scan — to buy nothing the parts cap does not already buy.

## 4. Decoder discipline

- **A fresh decoder on every entry to the scanning screen.** A stale pool from an abandoned scan
  mixing into the next one is a correctness hazard on the path that produces a signature.
- **After the first accepted part, reject any part whose `seqLen`, `messageLen` or message checksum
  disagrees with it.** This pins the stream's identity at our call site — the same move as the
  `seqLen` clamp, applied to a different field.

Both are spec requirements alongside the bounds in §3, not implementation hygiene.

## 4a. What building §2–§4 settled

**The tree carries §2, §3 and §4** as of [#77](https://github.com/allisson/aobs/issues/77):
`aobs-core/src/ur.rs` is one `Scanner`, built for one class, and the whole of those three sections
is its `receive`. Five things the prose above did not answer are recorded here rather than left in
the code for a later reader to rediscover.

**`ur` will not let a part be inspected between parsing and reception.** `fountain::Part` is
constructible only inside the crate — `from_cbor`, `sequence` and `sequence_count` are
`pub(crate)`, and `message_length` and `checksum` have no accessor at all. So *before any part
reaches `ur`* is unimplementable through the dependency's own types, and the clamp reads the
part's four header fields out of its CBOR itself. The `seqLen` clamp needs none of that — it is
the decimal in the URI path, checked with no allocation at all, and it is the one the 34 GB claim
turns on.

**Two readers reading one field is only safe if they cannot disagree**, and this pair cannot: both
take the same byte at the same offset under the same five CBOR width rules, so a non-minimal or
eight-byte encoding reads identically in both. That is what lets the bound checked on the
*declared* `messageLen` stand for the *delivered* message with no second check downstream — the
dependency truncates the reassembly to the same field. Where the two readers do differ is that
ours stops after the fourth field and never looks at the fragment, so it can compute a header for
a part the dependency then refuses. That is handled, and it is the next point.

**§4's *accepted* is load-bearing, and reading it as *received* is an attack.** A header inside
every bound whose fragment the fountain decoder refuses must leave no trace: pinning the stream's
identity on it would let one hostile frame claim the stream and lock the honest animation out of
the scan for as long as the user kept aiming at it. The pin happens after `receive` returns `Ok`,
never before.

**A fifth bound is not added, and the symbol length is not one.** §3 orders the `messageLen` bound
*before* the decoder, and a bound read out of the CBOR has already paid for the bytewords
allocation that produced the CBOR. So the same bound is applied first to the only form the symbol
has before we are allowed to decode it — bytewords minimal is two characters per byte plus a
doubled CRC-32 — and the number is **derived from the 64 KiB bound rather than chosen**. It is
§3's first bound enforced as early as it can be, which is also what makes the fountain fuzz
target's *no allocation above the transport bounds* true of an arbitrary `&str` and not only of
something a QR could carry.

**One dead end is recorded rather than fixed.** A stream that completes into something the
dependency refuses — nonzero padding, or a message failing its own CRC-32 — leaves that scanner
unable to complete ever again: the decoder stays complete and its message stays bad, so the screen
stays live and discards everything after. No honest encoder can produce it and the remedy is
cancel and re-enter. Resetting the decoder mid-scan would be a decision §4 does not make, so it is
named here instead of invented there.

## 5. Capture

- **`v4l` directly** (raw V4L2 ioctls, default features, no `libv4l` on the image), decoded with
  **`rqrr`** via `PreparedImage::prepare_from_greyscale` fed from the frame's luma plane. Not
  `nokhwa` (wraps `image`, `flume` and a `decoding` feature that can pull `mozjpeg`, a C library
  built from source); not `bardecoder` (last released 2023, mandates `image ^0.24`, no raw-buffer
  entry point).
- **Request `GREY` or `YUYV`, never `MJPG`.**
- **Request the largest resolution the device offers up to 1280×720**, falling back to whatever it
  has. A 640×480 frame reading a v40 symbol leaves under 3 px/module before optics and blur. *The
  real floor is unmeasured; the fallback path is what makes an unlucky camera degrade rather than
  fail.*
- **Capture at the camera's native rate with no throttle. Always decode the newest frame; drop any
  that arrived while we were busy.** Queueing is the trap: on floor hardware `rqrr` may not keep up
  at 30 fps, and a queue turns that into growing latency plus a visibly lagging preview — the user
  then aims at where the code *was*. Dropping stale frames degrades capture probability gracefully,
  and capture probability is the variable the transport maths already models.
- V4L2 devices are enumerated **at the point of use**. A camera that disappears mid-scan states so
  plainly and returns to the previous screen, recovering on re-plug.
- **The entropy frame uses the front half of this and none of the loop.** `04-screens.md` §2's
  silent capture opens a node, negotiates `GREY` or `YUYV` the same way, takes one buffer and
  stops; it has no preview, no decode, no drop policy and no resolution preference, because the
  bytes are hashed rather than read. It arrived first, with
  [#72](https://github.com/allisson/aobs/issues/72), which is what puts `v4l` — and, through
  `v4l2-sys-mit`'s bindgen, `libclang-dev` — in the build environment already.

## 5a. What building §5 settled

**The tree carries §5** as of [#78](https://github.com/allisson/aobs/issues/78): `aobs/src/camera.rs`
is the device and the loop, `aobs/src/qr.rs` is `rqrr` on a luma plane, and `aobs/src/scan.rs` is
`04-screens.md` §11.1's one screen. Seven things the prose above did not answer are recorded here
rather than left in the code for a later reader to rediscover.

**`V4L2_CAP_IO_MC` is not a flag `v4l` names**, so the bit is written out at our call site. What
`v4l` does get right is the field: its `Capabilities::capabilities` is built from `device_caps`, not
from the driver-wide `capabilities`, and `device_caps` is the per-node answer `01-boot-layer.md` §7's
distinction is about. A reader checking the struct member name alone would conclude the opposite.

**The drop policy is the buffer count, and nothing else.** §5 asks for *always decode the newest
frame; drop any that arrived while we were busy*, and with **two** mmap buffers there is exactly one
frame in flight while we decode — so a frame arriving behind it has nowhere to be queued and the
driver discards it. The dropping is the kernel's, by construction, rather than a policy we implement
and could get wrong. **Raising the count to smooth things out reintroduces the queue §5 forbids**, and
it will present as a preview that lags rather than as an error.

**`FrameSizeEnum::to_discrete` is unusable for this, and that is worth a sentence in a section about
not allocating on somebody else's numbers.** For a stepwise or continuous device it materialises the
whole cross product — step 1 over 1920×1080 is two million structs and about 16 MB, sized entirely by
the device's answer. §5's *largest resolution up to 1280×720* is therefore arithmetic on the stepwise
grid, and only the discrete arm is enumerated at all.

**The declared height is a claim; the buffer length is the fact.** A driver whose format says 720 rows
and whose buffer carries fewer must cost the rows it did not deliver, not a panic on a slice index —
and a panic on the scanning screen is `AOBS-E04` and the end of the session, with the wallet in it. So
the plane extractor returns the rows it wrote and the decoder and the preview are told *that*.

**The preview is published before the decode, not after, and this is §5's own trap read one level
down.** Capture and decode share one thread, which is what makes *no queue* structural rather than
enforced. But it also means a 200 ms decode would hold the preview 200 ms behind the sensor if the
publish came second — and *the user then aims at where the code was* is exactly the failure §5 names.
So the frame goes to the screen first, with its own wake-up, and the decode runs after it.

**§5's *returns to the previous screen* is delivered by a press.** A sentence the user never reads is
not *states so plainly*, so the screen states the loss, takes the camera down, and offers one row off
it; Escape does the same thing. Nothing on this appliance advances on its own, so this is the
established shape rather than a new one — but it is a reading of §5 rather than something §5 says, and
it is named here instead of only in the code.

**Two capture threads must not race for the node, and the event loop cannot join one.** Leaving the
screen runs on the event loop while the capture thread is blocked in `VIDIOC_DQBUF`, so an Escape
immediately followed by another entry would have the new thread call `STREAMON` while the old one
still owns the device — and the `EBUSY` would be reported as *the camera stopped answering*, which is
a guess rather than a fact. A capture thread therefore holds a mutex for its whole run and the next
one waits, which costs at most the one frame the outgoing thread is already waiting for. **Named
cost:** a driver that never delivers again never releases it, so the next scan waits instead of
reporting a loss — the better silence of the two, and the same wedged-driver case §5's own entropy
frame already accepts.

**`rqrr`'s default feature is the `image` crate.** Taken with `default-features = false`, because the
plane we already hold is exactly what `image` would decode down to: the default would put a second
image stack on the hostile-input path to arrive back where we started. That is the same reason §5
rejects `nokhwa`, applied to the crate §5 chose.

## 6. Outbound: the signed PSBT

**ECC L, capped at version 27, maximum UR fragment length 960 bytes, 4 fps, looping indefinitely
with fresh fountain parts.**

- **ECC L** is the backup QR's decision run in the opposite direction on the same evidence: BBQr's
  ECC-L advice is premised on *"a perfect LCD screen"*, which is false for paper and **exactly true
  here**. For a multi-part payload the fountain code is already the error correction that matters.
- **The version cap is module pitch, not frame count.** On a ~700 px usable square, v40's 177 modules
  plus quiet zone gives ≈3.8 px/module against v27's 133 → ≈5.3. Buying that back costs two extra
  frames on the 3 744 B case, priced at ~1 s even at 50% capture loss. **Always the smallest version
  that fits the part size, never a fixed version.**
- **Maximum UR fragment length 960 bytes** — `Encoder::new`'s second argument, and the number that
  makes *"no outbound size cap"* below true rather than aspirational. The version follows the part
  size, so the part size is the only thing that can make the QR encoder refuse. **The largest part
  960 can ever produce is 2 013 characters against v27's 2 132**, with every CBOR field at its `u32`
  maximum and the sequence number ten digits wide — so the refusal is unreachable by arithmetic, not
  merely unlikely. It costs **no extra frame on any transaction in §1's capacity table**. The
  arithmetic, the rejected candidates and the three traps are §9.
- *Owed measurement: what a phone camera actually reads at arm's length. **v40 is the documented
  fallback** if v27 proves needlessly conservative — and the fragment length is then **re-derived
  from the new cap, never kept**.*
- **4 fps** is the frame rate the recovery-time maths was computed at; keeping it keeps those numbers
  valid.
- **Loop indefinitely.** With no feedback channel, no stop condition can be anything but arbitrary.
- **A single-frame payload is an animation of length one that happens not to move** — same screen,
  same code path. Special-casing it doubles the surface for a difference the user cannot perceive.
  One encoding rule rides with it: **when it fits, emit the single-part UR form with no `seq`
  component**, not `1-1`.
- **No outbound size cap.** The inbound 64 KiB bound already constrains what can arrive, and refusing
  to emit a signature we have already produced would be the worst failure available to this device.
  This holds *because of* the fragment length above, not alongside it: a signed PSBT is larger than
  the one that arrived, so 64 KiB is a floor on what we may have to emit rather than a ceiling, and
  960's bound is stated over every message length a `u32` can describe.

**No ticking counter and no percentage.** BC-UR is **rateless**, so looping properly means generating
*fresh* parts rather than cycling a fixed set — *"part 3 of 4"* becomes a lie on the second pass, and
any percentage would describe our animation rather than their reception. The screen states the size
once and the QR's own flicker carries liveness. Nothing at all in the single-part case.

## 6a. What building §6 settled

Two things this section leaves implicit and one it gets slightly wrong about the dependency
([#82](https://github.com/allisson/aobs/issues/82)).

**What the UR message is, is §1's decision and no longer this section's open question.** #82 left
it as *the PSBT's serialised bytes, with no wrapper charged*, which is what the tree emitted and
accepted and which **no coordinator reads**. [#112](https://github.com/allisson/aobs/issues/112)
settled it on Sparrow's and Specter's own source and moved both halves in one commit:
`aobs_core::ur::wrap` and `::unwrap` are the pair, called from
[`outbound`](../../aobs-core/src/outbound.rs) and [`ur`](../../aobs-core/src/ur.rs) respectively,
and `03-transport.md` §1 is the rule. **The mechanism that let it ship wrong is the part worth
keeping in view**: the two halves each remembered a convention, and every test in the tree asserted
symmetry — which holds whichever one they remembered.

**`ur` 0.5.2 does no CBOR at all**, in either direction: `ur::ur::decode` bytewords-decodes and
returns, `ur::ur::encode` bytewords-encodes what it is given. So the registry's layer is ours to
add, which is why it is one function pair rather than a dependency's behaviour.

**§6's *"same screen, same code path"* costs one branch, in core, on the fragment count.**
`ur::Encoder` emits `ur:crypto-psbt/{seq}-{seqLen}/…` unconditionally, so a one-fragment message
comes out of it as `1-1` — which is a multi-part stream of length one and a different thing on the
wire from a UR that is simply not fragmented. §6 requires the second, so `Animation` reads
`fragment_count()` once at construction and takes `ur::ur::encode` for the single-part case. The
branch is on a count and never on anything about the bytes, and it is the only one in the module.

**`encode_segments_advanced` returns `Result`, not `Option`**, which is what lets §9's *unreachable
by arithmetic* be an `expect` with the reason written next to it rather than an error type the shell
would have to be given a branch for (§8 forbids it one).

## 7. Outbound: the two static QRs

Both are **single-part, always**, at **ECC H**, and both are rendered from a **typed model** rather
than an arbitrary string.

| Artifact | Encoding | Notes |
|---|---|---|
| Encrypted backup | `ur:bytes`, 67 bytes → ~529 alphanumeric chars → **version 20 (97×97) at ECC H** | ECC H because paper creases and fades. Type `bytes` and not `crypto-psbt` is a free confusion-attack guard: a PSBT scanned at the restore prompt is rejected on the type string rather than on a crypto failure. No compression on this path at all; integrity is the AEAD tag, not UR's CRC-32. **§1's CBOR wrapper applies here too** — `ur:bytes` is a registry type and the wrapper is a property of the type, not of the screen — so the message is 69 bytes and the char figure grows by four. It is derived rather than measured either way and the headroom to version 20 absorbs it; the inbound half of this path already reads the wrapper ([#112](https://github.com/allisson/aobs/issues/112)) and the outbound half is [#85](https://github.com/allisson/aobs/issues/85)'s to build against it. |
| Watch-only export | `ur:crypto-account` (registry type 311) | Four output descriptors, one per BIP family, account 0. **Estimated ~460 B CBOR → ~1,000 UR chars — derived, not measured.** If four descriptors ever fail to fit one QR, **the fix is narrowing what we export, never animating it.** |

**`crypto-account`, not `account-descriptor` (40311)** — decided on coordinator source, not docs:
Sparrow accepts both, **Specter Desktop accepts `crypto-account` only**, Nunchuk is **unverified
rather than assumed**. So the 2020 type is the strict superset, exactly as UR2 was the strict
superset over BBQr, and emitting the 2023 type would silently drop Specter. **Named cost: we ship a
superseded encoding**, with a recorded revisit trigger — when Specter accepts `account-descriptor`,
this flips.

The multi-part path is **forbidden by rule** on both prompts, which is what keeps the restore path
out of the fountain decoder entirely.

## 8. The encoder, and where it lives

`qrcodegen` 1.8.x — named, licensed and argued in `02-core.md` §1 alongside every other dependency,
including why its age reads differently on this side of the boundary than `bardecoder`'s did on the
other.

**It lives in `aobs-core`.** ADR-0004's seam is one question — *does this touch hardware* — and a QR
symbol is a matrix of bits. Drawing one touches hardware; **computing one does not**. So core emits
the module matrix and the shell paints it, which is the review-model seam again: *core produces a
model; tests assert on the model, never on pixels.* The consequence is the point — version
selection, the ECC level, the cap and the refusal all sit under core's 95% region gate and all test
from a byte fixture, and the shell keeps no branch on whether a payload fit. It does **not** add a
tenth 98% component: the nine are ADR-0004's and this is not one of them.

**Both of §6's rules are one call**, not a loop we maintain:

```
QrCode::encode_segments_advanced(segs, ecl, Version::MIN, cap, None, false)
```

The smallest version that fits is the library's search; the cap is `maxversion`; exceeding it is
`Err(DataTooLong)` rather than a larger symbol. `boostecl` is pinned **`false`**: it would raise the
ECC level whenever a payload left slack in its version, which costs nothing in density but makes the
emitted level a function of payload size, and §6 and §7 name the level rather than a floor.

**The UR text is uppercased before encoding**, which §1 already requires for a different reason —
Specter's scanner regexes match `UR:CRYPTO-*`. `QrSegment::make_segments` then picks alphanumeric
mode on its own, and that is what §7's sizing in *characters* rather than bytes assumes. Lowercase
would fall to byte mode and cost about a third of the capacity: measured, a v27 symbol at ECC L
carries **2 132 alphanumeric characters** but only **1 465 bytes**.

### Measured, against the acceptance criteria

`qrcodegen` 1.8.0, release build, on an arm64 development machine — **not floor hardware**, so the
timings indicate rather than discharge anything.

| Check | Result |
|---|---|
| §7's backup QR: 529 alphanumeric characters at ECC H | **version 20, 97×97** — reproduces §7's stated figure independently |
| Headroom at that version | 557 characters is the v20-H ceiling, so the largest backup sits 28 below it |
| §6's cap: 2 132 characters at ECC L | **version 27**; 2 133 refuses rather than growing |
| Smallest-that-fits | a 40-character single-part UR lands on **version 2** |
| Encode time, v27 at ECC L, automatic mask | **~2.4 ms**, against the 250 ms that 4 fps allows |

The watch-only export is the one that does not fit the same envelope: **~1 000 alphanumeric
characters at ECC H needs version 29**, past §6's v27 cap. That is not a conflict — the cap is §6's
rule for the animated signing path and §7 states no version limit on the static pair — but it is the
number the owed obligation in `05-testing-and-release.md` §6.4 will be judged against, and the ~460 B
CBOR estimate underneath it is still derived rather than measured, so the obligation stands.

## 9. The maximum UR fragment length: 960 bytes

§6 says the version follows the part size, so the part size is the only thing that can make the
encoder refuse on the signing path — which makes this number, not the v27 cap, what §6's *"no
outbound size cap"* actually rests on ([#94](https://github.com/allisson/aobs/issues/94)).

### 9.1 The arithmetic

A part string is not measured, it is computed. `ur` 0.5.2 emits

```
ur:crypto-psbt/{seq}-{seqLen}/{bytewords_minimal(cbor)}
```

where the CBOR is `[seq, seqLen, messageLen, checksum, fragment]` and bytewords minimal costs
`2n + 8` characters — two per byte, plus a four-byte CRC-32 that is doubled too. So, in characters:

```
15 + digits(seq) + 1 + digits(seqLen) + 1 + 2·(1 + w(seq) + w(seqLen) + w(messageLen) + 5 + h + F) + 8
```

`F` is the fragment length, `h` its CBOR byte-string header (3 for any `F` in 256..65 535), `w` the
minimal CBOR width of a uint, and the `5` is the CRC-32 checksum field. **Every integer field is
written `as u32`** (`fountain::Part`'s `Encode` impl, four `.u32()` calls), so no `w` ever exceeds 5.
That is what turns a sweep into a bound: charge all four fields their `u32` maximum and both decimals
ten digits, and the result is the largest part the animation can *ever* emit.

**`messageLen` is §1's message, not the PSBT** — the payload plus its CBOR byte-string header, which
is three bytes at every size §1's capacity table names. That changes nothing here, because the
ceiling charges the field its `u32` maximum in any case, and it changes nothing in §9.2 or §9.3
either: every figure below was computed over the message and reproduces exactly
([#112](https://github.com/allisson/aobs/issues/112) re-ran them). What it changes is which payload
lands where — the boundary in §9.3 is a **957-byte PSBT**, and 23 017 is the message a 23 014-byte
one produces.

At `F = 960` that ceiling is **2 013 characters against v27-L's 2 132** — 119 spare.

The formula is not asserted, it was checked character-for-character against what `ur` 0.5.2 actually
emits:

- every message size from 1 B to 8 KiB at each candidate below — which covers `w` at 1, 2 and 3 on
  `seqLen` and `messageLen`, and the byte-string header at 2 and 3;
- every sequence number from 1 to 10⁶ (§9.3) — `w` at 1, 2, 3 and **5** on `seq`, and `digits(seq)`
  from 1 to 7;
- one 245 759 B message, emitted at **1 985** characters, which the formula predicts exactly — that is
  `messageLen` at `w = 5` and `seqLen` at `w = 3`.

**Two terms are extrapolated, and are stated rather than hidden.** `seqLen` at `w = 5` needs 65 536
fragments, so a message above 60 MiB. `digits(seq)` past 7 needs 10⁷ parts, a month of animation at
4 fps. Each is the same `.u32()` call, and the same `usize` formatting, already exercised on a
neighbouring field of the same array — and each is charged **against** us in every figure below.

### 9.2 The candidates, and why 960 rather than 1 024

`qrcodegen` 1.8.0 and `ur` 0.5.2, arm64 development machine — but unlike §8's timings these are
character counts against capacity tables, so nothing here is machine-dependent. Measured ECC-L
alphanumeric capacities: **v24 1 704 · v25 1 853 · v26 1 990 · v27 2 132 · v40 4 296.**

| `max_fragment_length` | Worst part, message 1 B..64 KiB, `seq` at `u32::MAX` | Ceiling, every field at its `u32` widest | §1's 3 744 B PSBT |
|---|---|---|---|
| 4 096 (effectively unbounded) | 8 269 → **refuses** | 8 285 → **refuses** | **refuses**, one part of 7 517 chars |
| 1 024 | 2 127 → v27, 5 spare | 2 141 → **refuses** | 4 parts, v26, 1.00 s |
| 1 000 | 2 075 → v27, 57 spare | 2 093 → v27, 39 spare | 4 parts, v26, 1.00 s |
| **960** | **1 995 → v27, 137 spare** | **2 013 → v27, 119 spare** | **4 parts, v26, 1.00 s** |
| 896 | 1 867 → v26 | 1 885 → v26, 247 spare | 5 parts, v23, 1.25 s |

**Leaving it unbounded is §6's forbidden failure on an ordinary transaction**, and worse than a
made-up example: at 4 096 the *witness-only* 10-in/2-out P2WPKH from §1 — 1 494 B, a plain
consolidation — is one part of 3 017 characters and refuses at the cap. So does the 3 744 B row. A
signature we already produced, unemittable.

**1 024 is rejected on measurement, and it is the candidate a reader will reach for**: it is round, and
64 KiB divides into exactly 64 fragments at it, which looks like §3's `seqLen ≤ 64` bound falling out
of the encoder for free. That symmetry is not a property, and would buy nothing if it were — §3 bounds what
*arrives*, sized for a coordinator packing v27 to its ceiling of ~1 040 B per fragment, which we are
deliberately not; nothing we emit ever re-enters our own decoder; and a *signed* 64 KiB PSBT exceeds
64 fragments at 1 024 anyway. What decides it is the headroom: **5 characters** inside §3's bound and
**9 characters short** at the arithmetic ceiling. 1 024 is exactly the number §9.3's traps are about.

The corollary is worth stating so nobody reaches for it later: at 960 a 64 KiB message is **69**
fragments, not 64. That is not a reason to raise §3's inbound bound. The two numbers face opposite
directions, and the clamp is a security property.

**960 clears the ceiling by 119 characters, 5.6% of the budget** — and that, not the roundness, is the
criterion. 1 000 clears it too, by 39; 960 is the choice because it is the largest **64-byte-aligned**
value that clears it at all, which is the tie-break rather than the reason. Its named cost is nothing:
every row of §1's capacity table splits into the same part count and lands on the same version as
1 024 does. The headroom is bought entirely out of the pathological sizes nobody transacts at.

**It also reproduces §6's own price rather than quietly changing it.** §6 says buying v27's module
pitch back from v40 costs *two extra frames on the 3 744 B case*. Run the same formula at v40-L's
4 296 characters and the fragment length it admits is ~2 100 B, which splits that PSBT into 2 parts
against 960's 4. Two extra frames, arrived at from the other direction.

**896 is rejected for going the other way.** It buys another 128 characters of ceiling and pays a
fifth frame on §1's worst realistic PSBT, dropping it three versions below the cap. That is not a
worse trade so much as a *different decision*: §6 caps the version to bound module pitch and spends
the budget up to that cap, and choosing a fragment length that never approaches it re-prices module
pitch against frames a second time. §6.4's owed measurement — a phone camera at arm's length — is
where that gets re-priced, on evidence rather than on caution.

### 9.3 The three traps it had to survive

**The worst case is not the largest message, it is a maximal single fragment.** `ur`'s fragment length
is `ceil(len / ceil(len / max))`, so a full-`F` fragment happens only where the even split lands on
`F` exactly — at 64 KiB and `F = 960` the split gives 950 B, not 960. The worst message inside §3's
bound is **23 017 B**, whose 24-way split leaves exactly 960; §1's 3 744 B row is nowhere near it. The
sibling case is the boundary itself: a message of exactly 960 B is one fragment, and §6 emits it as the
single-part form with no `seq` component, which at **1 943 characters is v26** — the largest single
symbol we ever draw. One byte more splits in two and the symbol collapses to 1 017 characters at v18.
(In PSBTs those two are **957 and 958 bytes**, and 23 014 is the worst one — §1's wrapper, and the
one place in §9 where the payload and the message are worth stating separately.)

**The fragment is not the only field that widens.** `seqLen` and `messageLen` sit in the same CBOR
array, and each crosses a minimal-uint boundary at 24, 256 and 65 536 — two characters, two, then four,
because CBOR has no three-byte uint. This is why the sweep alone is not the argument: §9.1's ceiling,
which charges every field its widest, is.

**The part string grows for as long as the animation runs.** §6 loops indefinitely, so the sequence
number grows in both the CBOR and the decimal prefix. Measured exactly, for **every** sequence number
from 1 to 10⁶ on a 4 000 B message: 14 characters, and §9.1's closed form predicts every one of them.
Past that the CBOR term stops — `Part` writes `self.sequence as u32`, so it never widens beyond five
bytes — and only the decimal prefix keeps growing, one character per decade. **Over the whole `u32`
range the total is 17 characters**, which is 34 years of animation at 4 fps and is charged in full in
every figure above. (Past `u32::MAX` that cast wraps and the parts stop being unambiguous, which is
upstream's problem 34 years in, not a length problem.)

A part **can** cross a version boundary mid-loop — at 960 the 245 KiB pathological case starts at v26
and reaches v27 — and no choice of `F` prevents that, since some message size always sits within 17
characters of some boundary. What 960 guarantees is the only boundary that matters: it can never cross
the **cap**.

### 9.4 Where it lives, and what it owes

**In `aobs-core`, as a parameter to the function that builds the animation** — not a shell constant.
§8's seam answers it and more sharply than it answered the encoder: this number *is* the safety
argument in §9.1, so it belongs where the 95% region gate, the property test and the fuzz corpus can
reach it. Core names it once; the constructor takes it as an argument so
`05-testing-and-release.md` §3's property test can sweep other values and watch this one hold. Nothing
in `aobs/` names it — a shell constant would put the only number that can make the signing path
refuse outside every gate that judges code, and §8 already forbids the shell a branch on whether a
payload fit.

**Nothing is owed.** Every figure here is arithmetic over `ur`'s CBOR shape and `qrcodegen`'s capacity
table; §8's arm64 caveat bites on timings and there are none in this section. The one dependency is
outward: if §6.4's owed measurement flips the cap to **v40** — 4 296 alphanumeric characters — this
number is **re-derived from the new cap rather than kept**, which is that measurement's job and not
this section's.
