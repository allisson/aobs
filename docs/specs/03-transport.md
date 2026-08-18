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
[#67](https://github.com/allisson/aobs/issues/67).

## 1. Format

**BC-UR / UR2 for PSBTs, both directions.** Emit `ur:crypto-psbt`; accept `crypto-psbt`, `psbt` and
`bytes`.

Emit the **deprecated `crypto-psbt` spelling**, not the registry's newer `psbt`/40310: Sparrow
decodes `psbt` but never writes it, and Specter's scanner regexes match only `UR:CRYPTO-*` and
`UR:BYTES/`, so `ur:psbt/…` falls through unhandled.

BBQr was measured and lost on one fact: **its supported set is a strict subset of BC-UR's.** Nothing
in scope does BBQr and not UR2; Specter Desktop does UR2 and not BBQr. Choosing BBQr subtracts
Specter and adds nobody. Density does not decide it (frames are within one of each other at our
sizes) and neither does fountain coding (at N ≤ 4 the advantage is at most ~1.2 s even at 50% frame
loss) — **do not cite fountain coding as the justification for this decision later.**

Electrum is unreachable by animated QR whatever we chose: no `ur:`, no BBQr, no chunking, and its
`to_qr_data()` deliberately emits an incomplete PSBT.

### The cost we took, stated plainly

`ur-rs` is the riskier parser and we adopted it knowingly:

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

Before any part reaches `ur-rs`:

| Bound | Value | What it stops |
|---|---|---|
| `messageLen` | ≤ 64 KiB | ~17× the largest realistic payload (3 744 B). Generous enough that no honest user reaches it. |
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

## 6. Outbound: the signed PSBT

**ECC L, capped at version 27, 4 fps, looping indefinitely with fresh fountain parts.**

- **ECC L** is the backup QR's decision run in the opposite direction on the same evidence: BBQr's
  ECC-L advice is premised on *"a perfect LCD screen"*, which is false for paper and **exactly true
  here**. For a multi-part payload the fountain code is already the error correction that matters.
- **The version cap is module pitch, not frame count.** On a ~700 px usable square, v40's 177 modules
  plus quiet zone gives ≈3.8 px/module against v27's 133 → ≈5.3. Buying that back costs two extra
  frames on the 3 744 B case, priced at ~1 s even at 50% capture loss. **Always the smallest version
  that fits the part size, never a fixed version.**
- *Owed measurement: what a phone camera actually reads at arm's length. **v40 is the documented
  fallback** if v27 proves needlessly conservative.*
- **4 fps** is the frame rate the recovery-time maths was computed at; keeping it keeps those numbers
  valid.
- **Loop indefinitely.** With no feedback channel, no stop condition can be anything but arbitrary.
- **A single-frame payload is an animation of length one that happens not to move** — same screen,
  same code path. Special-casing it doubles the surface for a difference the user cannot perceive.
  One encoding rule rides with it: **when it fits, emit the single-part UR form with no `seq`
  component**, not `1-1`.
- **No outbound size cap.** The inbound 64 KiB bound already constrains what can arrive, and refusing
  to emit a signature we have already produced would be the worst failure available to this device.

**No ticking counter and no percentage.** BC-UR is **rateless**, so looping properly means generating
*fresh* parts rather than cycling a fixed set — *"part 3 of 4"* becomes a lie on the second pass, and
any percentage would describe our animation rather than their reception. The screen states the size
once and the QR's own flicker carries liveness. Nothing at all in the single-part case.

## 7. Outbound: the two static QRs

Both are **single-part, always**, at **ECC H**, and both are rendered from a **typed model** rather
than an arbitrary string.

| Artifact | Encoding | Notes |
|---|---|---|
| Encrypted backup | `ur:bytes`, 67 bytes → ~529 alphanumeric chars → **version 20 (97×97) at ECC H** | ECC H because paper creases and fades. Type `bytes` and not `crypto-psbt` is a free confusion-attack guard: a PSBT scanned at the restore prompt is rejected on the type string rather than on a crypto failure. No compression on this path at all; integrity is the AEAD tag, not UR's CRC-32. |
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

**Not settled here, and not ours to settle quietly:** the maximum *fragment length* handed to the UR
encoder. §6 says the version follows the part size, so the part size is what decides whether the
encoder can ever refuse on the signing path — and §6's *"no outbound size cap"* holds only if that
length is chosen under the 2 132-character v27 budget. Nothing in `docs/specs/` names it. That is a
ticket.
