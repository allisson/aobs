# The Python layer comes from hash-pinned wheels, not from Debian

`docs/adr/0001` chose Debian so that one pinned distro package set could feed both the image and the
authoritative test tier. That works for the base OS, the kernel, `busybox`, `kbd`, `libsecp256k1`,
`python3` itself, and — as it happens — `python3-qrcode`, `python3-zxing-cpp` and `python3-pil`. It
does not work for the rest of the Python layer, because **Debian stable ships it below what this
application declares**:

| | the app | trixie | |
|---|---|---|---|
| `textual` | 8.2.7 (the Alpine predecessor's appliance pin) | 2.1.2 | six majors back |
| `rich` | 15.0.0 | 13.9.4 | two majors back |
| `cryptography` | `>=44` in `pyproject.toml` | 43.0.0 | below the declared floor |
| `argon2-cffi` | `>=23.1` | 21.1.0 | below the declared floor |
| `pytest-asyncio` | `>=1.3` | 0.25.1 | below the declared floor |

**So: apt for everything Debian can serve at an acceptable version, and hash-pinned wheels for
`textual`, `rich`, `cryptography`, `argon2-cffi` and `pytest-asyncio`.** `build/fetch-inputs.sh`
fetches them into `build/inputs/` in the one networked step, `pip` installs them with `--no-index`
so the build itself still touches no network, and `pip` is removed from the rootfs before the
initramfs is packed.

## Why not move the app down to Debian's versions

That was the plan until the versions were actually read, and it means two things, neither small.
First, porting roughly twenty screens and four widgets **backwards** across six major Textual
releases — not a migration onto something newer, a retreat onto something two years older, with no
upstream guidance because nobody documents how to un-upgrade. Second, lowering two crypto floors:
`wallet_qr.py` builds the encrypted wallet QR out of `ChaCha20Poly1305` and
`argon2.low_level.hash_secret_raw`, and "we accepted an older AEAD and KDF implementation to satisfy
a distro pin" is a decision that has to be argued, not absorbed.

Debian's security team does backport fixes — `43.0.0-3+deb13u1` is evidence of exactly that — so the
crypto risk is smaller than the raw version gap suggests. It is not zero, and it is not the kind of
risk worth taking to buy tidiness.

## What it costs

"Every byte came from Debian" is gone. That was a *means*, never one of the published claims: the
property that made the pinned list load-bearing is **one pinned set feeding both tiers, so skew fails
in CI rather than on the appliance**, and a hash-pinned wheel set preserves that exactly. There are
now two lists, `build/apt-versions.txt` and `build/wheel-versions.txt`, and `build/verify.py` parses
both — so "two lists" is a thing the build checks, not a thing that can quietly drift.

`trixie-backports` and testing were the third option and are rejected for the reason the snapshot pin
exists: they move.

## The blob, and the line this draws

Three of these wheels carry prebuilt binaries, `cryptography` most of all — it bundles its own Rust
and OpenSSL build. That is in visible tension with the predecessor's decision to vendor `embit` from
source *specifically to keep its PyPI wheel's prebuilt `libsecp256k1` blob out of the repository*.

The line is where the blob lives. A binary in the **input archive** is hash-pinned, published beside
the release, and something an independent rebuild verifies byte for byte — indistinguishable in kind
from a `.deb`, which is also a prebuilt binary nobody in this project compiled. A binary in the
**repository** is none of those things: it is carried in the source tree, reviewed by nobody, and
diffed by nobody. `embit` stays vendored from source, and its wheel stays out.
