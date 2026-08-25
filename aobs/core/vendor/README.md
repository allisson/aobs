# Vendored code

## `embit/`

[`embit`](https://github.com/diybitcoinhardware/embit) — tag `v0.8.2`, commit
`eb6104fd85d3becabba628756cd5e1b75619f3a1` (2026-08-08). MIT; the upstream `LICENSE` is kept in
the directory. **Upstream byte-for-byte, with no changes at all** — embit uses relative imports
throughout its own tree (112 of them, and not one absolute self-import), so unlike `ur2` it needed
no edit to move. A reviewer diffs `src/embit` at that commit against this directory and expects
nothing.

It is vendored rather than depended on for the reason `docs/boot-pipeline.md` gives — Alpine
packages no `embit`, and the appliance introduces no pip — and it is taken **from git rather than
from the PyPI wheel**, which is the part that matters (#34).

embit's wheel ships `util/prebuilt/libsecp256k1_*.so`, a glibc-linked binary that exists in no
commit of the repository: `MANIFEST.in` prunes `src/embit/util/prebuilt`, and the `.so` is built
at wheel-build time by a toolchain nobody records. Vendoring from source means that blob never
enters this tree at all, rather than entering it and being deleted by a step someone can skip.

It has to stay gone. `embit/util/secp256k1.py` picks its EC implementation inside a bare
`except:`, and `_find_library()` returns the prebuilt path whenever the file merely *exists* —
it does not fall through when *loading* it fails. On musl the glibc-linked blob cannot relocate,
so its presence alone is enough to silently select `py_secp256k1`, embit's pure-Python elliptic
curve arithmetic. That is how the authoritative test tier signed in pure Python for its entire
life, at ~48x, with nothing anywhere saying so.

Two upstream bugs in this ctypes binding are worth knowing before you touch the EC path, both
documented at length in `docs/boot-pipeline.md`:

- **`PublicKey.schnorr_verify` segfaults** against any `libsecp256k1` ≥ 0.3.0. embit binds
  `secp256k1_schnorrsig_verify` with four arguments where the C function takes five, the fourth
  being `msglen`. It is a crash, not an exception. The appliance only signs, so nothing calls it.
- **`libsecp256k1` ≥ 0.8.0 cannot be used**, because upstream removed the deprecated
  `secp256k1_schnorrsig_sign` alias that embit binds. embit's own `except: pass` hides this until
  taproot signing.

Signing itself is correct against Alpine's `libsecp256k1` and was checked independently — the
signature verifies; it merely uses a different BIP340-legal nonce than the bundled blob does.

`tests/test_structure.py` holds all three checks: no binary in this tree, a byte-exact ECDSA vector
plus a Schnorr signature verified by the pure-Python implementation, and — in the authoritative
tier only — the live backend being `ctypes_secp256k1`.

## `ur2/`

Foundation Devices' [`foundation-ur-py`](https://github.com/Foundation-Devices/foundation-ur-py),
the stdlib-only UR v2 implementation SeedSigner vendors — commit
`a371f6355fb3433cc989ad5bf28f87a347b222fe` (2025-09-17). BSD-2-Clause-Patent; the upstream
`LICENSE` is kept in the directory.

It is vendored rather than depended on because it is not published to PyPI, and because
`docs/qr-emit-parameters.md` puts the UR codec in the core, which must import nothing that
performs I/O.

One change from upstream, and it is the only one: `xoshiro256.py` imported `ur.utils` and
`ur.constants` absolutely; both are relative imports here. Anything else in this directory is
upstream byte-for-byte, so a reviewer diffs against that commit.

## `../data/eff_large_wordlist.txt`

The EFF large wordlist, fetched verbatim from
<https://www.eff.org/files/2016/07/18/eff_large_wordlist.txt> — dice-roll column and all, 7,776
lines, `sha256 addd35536511597a02fa0a9ff1e5284677b8883b83e986e43f15a3db996b903e`.

Unmodified on purpose: `docs/export-password.md` requires that anyone can fetch the list from EFF
and check us against it, so this file is not pruned, sorted or reformatted. The parser reads the
second tab-separated column.
