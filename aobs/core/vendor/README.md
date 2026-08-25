# Vendored code

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
