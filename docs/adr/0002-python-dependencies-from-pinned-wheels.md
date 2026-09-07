# Every Python package comes from `pyproject.toml`, not from Debian

`docs/adr/0001` chose Debian so that one pinned distro package set could feed both the image and the
authoritative test tier. That works for the base OS, the kernel, `busybox`, `kbd`, `libsecp256k1` and
the interpreter itself. It does not work for the Python layer, because **Debian stable ships that
layer behind what this application declares** — in two places below the declared floor outright:

| | the app | trixie | |
|---|---|---|---|
| `textual` | 8.2.8 | 2.1.2 | six majors back |
| `cryptography` | 50.0.0, floor `>=44` | 43.0.0 | **below the declared floor** |
| `argon2-cffi` | 25.1.0, floor `>=23.1` | 21.1.0 | **below the declared floor** |
| `zxing-cpp` | 3.1.1 | 2.3.0 | one major back |
| `pillow` | 12.3.0 | 11.1.0 | one major back |
| `rich` | 15.0.0 | 13.9.4 | two majors back |
| `pytest` | 9.1.1 | 8.3.5 | one major back |
| `pytest-asyncio` | 1.4.0, floor `>=1.3` | 0.25.1 | **below the declared floor** |

**So `pyproject.toml` is the appliance's Python manifest.** `uv.lock` resolves it and holds a sha256
for every artifact, `build/wheel-versions.txt` is the reviewable version list derived from both,
`build/fetch-inputs.sh` fetches the wheels in the one networked step, and `pip` installs them with
`--no-index` — so the build still touches no network — then is removed from the rootfs before the
initramfs is packed. `build/apt-versions.txt` pins no `python3-*` package except the interpreter and
`pip`.

## Why all of it, and not the ones Debian happens to serve well

An earlier draft of this decision split the layer: apt for `python3-qrcode`, `python3-zxing-cpp` and
`python3-pil` — whose Debian versions were close enough — and wheels for the rest. That is worse than
either whole answer, for a reason that has nothing to do with the versions. It puts **two unrelated
resolvers in charge of one import graph**. `apt` would resolve `python3-pil` against Debian's Python
and Debian's `zlib`; `uv` would resolve `pillow` against `pyproject.toml`; nothing would reconcile
them, and the first time either side moved, the appliance's `import PIL` and the harness's would be
different code with no mechanism to notice. It also requires a per-package judgment call — "is this
Debian version acceptable?" — re-litigated on every snapshot bump, by whoever happens to be bumping
it.

One rule instead: **if it is imported by Python, it comes from `pyproject.toml`.** No case analysis,
one resolver, one lock file, and a diff that shows every version change in one place.

## Why not move the app down to Debian's versions

That was the plan until the versions were actually read, and it means two things, neither small.
First, porting roughly twenty screens and four widgets **backwards** across six major Textual
releases — not a migration onto something newer, a retreat onto something two years older, with no
upstream guidance because nobody documents how to un-upgrade. Second, lowering two crypto floors:
`wallet_qr.py` builds the encrypted wallet QR out of `ChaCha20Poly1305` and
`argon2.low_level.hash_secret_raw`, and "we accepted an older AEAD and KDF implementation to satisfy
a distro pin" has to be argued, not absorbed.

Debian's security team does backport fixes — `43.0.0-3+deb13u1` is evidence of exactly that — so the
crypto risk is smaller than the raw version gap suggests. It is not zero, and it is not the kind of
risk worth taking to buy tidiness.

`trixie-backports` and testing were the third option, rejected for the reason the snapshot pin
exists: they move.

## What it costs

"Every byte came from Debian" is gone. That was a *means*, never one of the published claims: the
property that made the pinned list load-bearing is **one pinned set feeding both tiers, so skew fails
in CI rather than on the appliance**, and a lock file preserves that exactly. There are now two
lists, `build/apt-versions.txt` and `build/wheel-versions.txt`, and `build/verify.py` parses both —
so "two lists" is a thing the build checks rather than a thing that can quietly drift.

It also means the Python layer no longer gets Debian's security backports for free. What replaces
them is a version bump in `pyproject.toml` and a regenerated lock, which is a visible commit rather
than an invisible one — and `ADVISORIES.txt` is where a bump that matters to a released image gets
said out loud.

## The blob, and the line this draws

Three of these wheels carry prebuilt binaries — `cryptography` most of all, since it bundles its own
Rust and OpenSSL build, plus `pillow` and `zxing-cpp` — and `cffi` and `argon2-cffi-bindings` compile
against `libffi`. That is in visible tension with the predecessor's decision to vendor `embit` from
source *specifically to keep its PyPI wheel's prebuilt `libsecp256k1` blob out of the repository*.

The line is where the blob lives *and what it does*. A binary in the **input archive** is
hash-pinned, published beside the release, and verified byte for byte by an independent rebuild —
indistinguishable in kind from a `.deb`, which is also a prebuilt binary nobody in this project
compiled. A binary in the **repository** is none of those things: carried in the source tree,
reviewed by nobody, diffed by nobody.

**That test alone would license installing `embit` from its wheel, and it must not.** An earlier
draft of this ADR said as much and was wrong. `embit`'s wheel ships
`util/prebuilt/libsecp256k1_*.so`, and the objection to it is not opacity — it is that
`_find_library()` returns the prebuilt path whenever that file merely *exists* and does not fall
through when *loading* it fails. The blob's presence is therefore enough to silently select
`py_secp256k1`, embit's pure-Python elliptic curve arithmetic, defeating the one EC rule this project
has. `aobs/core/vendor/README.md` records that this is precisely how the Alpine predecessor's
authoritative tier signed in pure Python for its entire life, at ~48x, with nothing anywhere saying
so. Hash-pinning that blob would have pinned the failure, not prevented it.

So the rule has a second clause: a prebuilt binary is acceptable in the input archive **unless its
mere presence changes which code runs**. `embit` stays vendored from source, from git rather than
PyPI, and its wheel stays out. `tests/test_structure.py` asserts no binary is in that tree.
