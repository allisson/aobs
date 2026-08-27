"""The three assertions that cannot be pure functions, run inside the built rootfs.

`build/verify.py` decides everything that can be decided from text. This file holds what cannot:
whether the libraries in the image actually *work*. It is executed by `build/mkiso.sh` as

    chroot /rootfs /usr/bin/python3 /assert_in_rootfs.py

so what runs is the appliance's own Python, against the appliance's own `libsecp256k1`, with the
app tree exactly where PID 1 will find it. There is no pytest in the rootfs and there never will
be, so this is a plain script that exits non-zero.

**Honest boundary, stated because the phrase "against the built kernel" invites more than is
true.** This runs on the *build container's* kernel — the built one has not booted and cannot be
made to boot here. So it catches everything about the userland: a missing apk, an ABI skew, a
`libsecp256k1` compiled without `schnorrsig`, an import that needs a library nobody pinned. What
it cannot catch is a consequence of the kernel config on Python's runtime behaviour: `CONFIG_NET=n`
removes `AF_UNIX` along with `AF_INET`, and `import socket` still succeeds — it is *using* a socket
that fails. That consequence is checked statically instead, and where it belongs:
`tests/test_structure.py` asserts the app's whole module closure imports no `socket`, `ssl`,
`multiprocessing` or `urllib`, so there is nothing left in the tree to fail at runtime.
`docs/boot-checklist.md` holds the rest, which only a real boot can settle.
"""

from __future__ import annotations

import hashlib
import sys

#: A BIP84 ECDSA signature over the published all-`abandon` BIP39 vector (passphrase `TREZOR`).
#: Byte-exact because ECDSA here is deterministic by spec — RFC6979 plus embit's low-R grinding.
#:
#: The same vector is pinned in `tests/test_structure.py`, and the duplication is deliberate: the
#: rootfs carries no test runner, so the two checks cannot share a module. They must agree, and if
#: they ever disagree one of them is wrong about the appliance.
VECTOR_MESSAGE = b"aobs build-time assertion"
EXPECTED_ECDSA = (
    "30440220647bdba563ce32b34ad13b3d28a5d180e9b24f47e07f7444263b7310066b0ede"
    "02203c83e9e92ace3280d8f4e6506f70714228282eb878f3b5461413d232bd236e57"
)

#: Every third-party module the app imports, checked one by one so a failure names the package that
#: is missing rather than dying inside an `aobs` import chain. Derived from the app tree's imports.
THIRD_PARTY = [
    "textual",
    "rich",
    "PIL",
    "qrcode",
    "zxingcpp",
    "cryptography",
    "argon2",
]

#: The app's own top-level modules, imported for their side-effect-free import graph. Importing
#: `aobs.ui.app` pulls in every screen, which is what turns a missing dependency into a build
#: failure instead of a traceback on an appliance with no recovery path.
APP_MODULES = [
    "aobs",
    "aobs.core.signing",
    "aobs.core.wallet",
    "aobs.core.review",
    "aobs.core.wallet_qr",
    "aobs.core.urcodec",
    "aobs.core.entropy",
    "aobs.adapters.real",
    "aobs.adapters.failure_handler",
    "aobs.ui.app",
    "aobs.__main__",
]

_failures: list[str] = []


def fail(claim: str, saw: str) -> None:
    """Same shape as `build/verify.py`'s `Violation`: the claim, and what was seen."""
    _failures.append(f"  {claim}\n      saw: {saw}")


def check_imports() -> None:
    import importlib

    for name in THIRD_PARTY + APP_MODULES:
        try:
            importlib.import_module(name)
        except BaseException as exception:  # a bad .so can raise anything, including SystemExit
            fail(
                f"every module the app needs imports in the rootfs: {name} does not",
                f"{type(exception).__name__}: {exception}",
            )


def check_the_backend_is_the_apk() -> None:
    """The live EC backend is `embit.util.ctypes_secp256k1`, checked where the claim is made.

    Every EC operation on the appliance is performed by Alpine's `libsecp256k1` and never by
    embit's pure-Python fallback. embit picks between them inside a bare `except:` with no message
    either way, so nothing on a running appliance would ever say which one it got.
    """
    from aobs.core.vendor.embit.util import secp256k1

    backend = secp256k1.ec_pubkey_create.__module__
    if not backend.endswith("ctypes_secp256k1"):
        fail(
            "the live EC backend is `embit.util.ctypes_secp256k1`: the appliance never signs with "
            "the pure-Python fallback",
            f"embit selected {backend}",
        )


def check_both_signature_schemes() -> None:
    """One BIP84 ECDSA signature and one BIP86 Schnorr signature over a published BIP39 vector.

    **A name check on the backend module is not sufficient and is not substituted for this.** embit
    binds the `schnorrsig`/`xonly`/`keypair` symbols inside their own bare `try:`/`except: pass`, so
    a `libsecp256k1` compiled without those modules imports cleanly, reports the native backend,
    and then fails at taproot signing — mid-session, with a wallet loaded, on BIP86 only. This is
    also the only thing that catches a routine Alpine bump of `libsecp256k1` past 0.8.0, which
    removed the deprecated `secp256k1_schnorrsig_sign` alias embit binds.

    **The ECDSA half compares bytes; the Schnorr half signs and verifies.** A BIP340 signature is
    not required to be byte-stable — any valid nonce yields a valid signature, and implementations
    measurably disagree on the one they pick — so pinning a Schnorr vector would assert something
    BIP340 never promised and would fail against a perfectly good library. Verification is what the
    check is actually for: that the symbols bound at all, the modules were compiled in, and the ABI
    matches. `tests/test_structure.py` makes the same split for the same reason.

    **`PublicKey.schnorr_verify` is never called, here or anywhere.** embit binds
    `secp256k1_schnorrsig_verify` with four arguments where the C function has taken five since
    0.3.0, so it passes the x-only pubkey pointer where C reads a length — a segfault, not an
    exception, which no `except:` can catch. The verification below goes through the pure-Python
    implementation, which has no ABI surface to get wrong and is an independent implementation of
    the same spec.
    """
    from aobs.core.vendor.embit import bip32, bip39
    from aobs.core.vendor.embit.ec import PrivateKey
    from aobs.core.vendor.embit.util import py_secp256k1, secp256k1

    seed = bip39.mnemonic_to_seed("abandon " * 11 + "about", password="TREZOR")
    root = bip32.HDKey.from_seed(seed)
    message = hashlib.sha256(VECTOR_MESSAGE).digest()

    key84 = root.derive("m/84h/0h/0h/0/0").key
    key86 = root.derive("m/86h/0h/0h/0/0").key
    assert isinstance(key84, PrivateKey) and isinstance(key86, PrivateKey)

    try:
        ecdsa = key84.sign(message).serialize().hex()
    except BaseException as exception:
        fail("one BIP84 ECDSA signature is produced in the rootfs", f"{exception!r}")
    else:
        if ecdsa != EXPECTED_ECDSA:
            fail(
                "the BIP84 ECDSA signature matches the published vector byte for byte",
                f"got {ecdsa}",
            )

    try:
        signature = secp256k1.schnorrsig_sign(message, key86._secret)
        xonly, _ = py_secp256k1.xonly_pubkey_from_pubkey(
            py_secp256k1.ec_pubkey_create(key86._secret)
        )
        verified = py_secp256k1.schnorrsig_verify(signature, message, xonly)
    except BaseException as exception:
        fail(
            "one BIP86 Schnorr signature is produced in the rootfs — a libsecp256k1 built without "
            "`schnorrsig`/`extrakeys`, or newer than 0.8.0, fails here and nowhere else",
            f"{type(exception).__name__}: {exception}",
        )
    else:
        if not verified:
            fail(
                "the BIP86 Schnorr signature verifies against an independent implementation",
                "the signature did not verify",
            )


def main() -> int:
    check_imports()
    if _failures:
        # No point signing with a tree that does not import; and the message would be noise on top
        # of the real failure.
        return _verdict()
    check_the_backend_is_the_apk()
    check_both_signature_schemes()
    return _verdict()


def _verdict() -> int:
    """The exit code, and the one line printed when there is nothing to say.

    `main()` calls this twice on purpose: once to stop after a failed import, because signing with
    a tree that does not import produces noise on top of the real failure, and once at the end.
    """
    if _failures:
        sys.stderr.write("the built rootfs violates:\n" + "\n".join(_failures) + "\n")
        return 1
    print("  rootfs assertions: imports, native backend, BIP84 ECDSA, BIP86 Schnorr — all pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())
