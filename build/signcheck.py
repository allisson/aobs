"""One signature in each scheme, produced by the image, inside the image.

Copied into the chroot by `build/mkiso.sh` stage 1 and run there by an mmdebstrap customize hook,
then deleted. It is the one build-time assertion that cannot be a pure function over a listing.

**A name check on the backend module is not sufficient**, which is why this signs rather than
imports. embit binds `schnorrsig`, `xonly` and `keypair` inside their own bare `except: pass`, so a
library compiled without those modules imports cleanly, reports the native backend, and fails at
taproot signing — mid-session, with a wallet loaded, on BIP86 only.

**And the backend check is not sufficient either**, which is why it is here as well. Measured
during this milestone: an image whose `libsecp256k1.so.2` was present and exported every required
symbol still resolved to `py_secp256k1`, because `ctypes.util.find_library` shells out to
`ldconfig` with `stdin=subprocess.DEVNULL`, the tree had no `/dev/null`, CPython caught the
`FileNotFoundError` under `except OSError: pass`, and embit's own bare `except:` turned the `None`
into the fallback. Two swallowed exceptions and no output anywhere.

That is also why this runs where it does. mmdebstrap's chroot has a working `/dev`; a tree sitting
on the build host's disk does not, because device nodes cannot be created unprivileged.
"""

from __future__ import annotations

import sys

sys.path[:0] = ["/opt/aobs", "/opt/aobs-python"]

from aobs.core.vendor.embit import ec  # noqa: E402
from aobs.core.vendor.embit.util import secp256k1  # noqa: E402

backend = secp256k1.ec_pubkey_create.__module__
if "ctypes" not in backend:
    sys.exit(f"the image's embit resolved to {backend}, not the ctypes binding")

key = ec.PrivateKey(b"\x01" * 32)
digest = b"\x02" * 32

# BIP84's half compares nothing to a vector, it verifies: RFC6979 plus embit's low-R grinding makes
# ECDSA deterministic, so a pinned vector would also be meaningful — but the thing worth proving
# here is that the symbols bound at all, and a round trip proves that without pinning bytes that
# the library is entitled to change.
ecdsa = key.sign(digest)
if not key.get_public_key().verify(ecdsa, digest):
    sys.exit("BIP84: the image could not verify its own ECDSA signature")

# BIP340 does not promise a byte-stable signature — any valid nonce yields a valid one — so a
# pinned Schnorr vector would assert something the spec never said. `PublicKey.schnorr_verify` is
# NOT called: embit binds it with four arguments where C has taken five since 0.3.0, so it passes
# the pubkey pointer where the library reads a length and segfaults. That is a crash no `except:`
# can catch, which is why the length is what is checked.
schnorr = key.schnorr_sign(digest)
if len(schnorr.serialize()) != 64:
    sys.exit("BIP86: schnorr_sign did not return 64 bytes")

# The receipt. A customize hook that silently did not run would leave every other assertion in
# this build passing and the one that matters unchecked, so the check writes down what it found and
# `build/verify.py` refuses an image that does not carry the file. A hook that does not run is then
# a failed build rather than a quiet one.
with open("/etc/aobs-ec-backend", "w", encoding="utf-8") as receipt:
    receipt.write(backend + "\n")

print(f"signing: ok, backend {backend}")
