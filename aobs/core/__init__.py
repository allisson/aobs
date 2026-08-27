"""The core: bytes in, value objects out.

One deep module with a pure interface. It owns wallet derivation, PSBT parse, the proof rule and
output categorisation, signing, entropy mixing, the encrypted-wallet container, the
export-password generator, descriptor strings, address verification and UR encode/decode.

It performs **no I/O**, reads no clock, no environment and no randomness of its own, and takes
everything it needs as arguments. That is the seam `docs/test-harness.md` fixed, and the
consequence that matters is this: the part of the appliance where a bug loses money needs no
camera, no screen and no node to test.

The entry points, in the shape every core function follows:

    review(psbt_bytes, wallet) -> Review
    sign(psbt_bytes, wallet) -> bytes
    mix(system, camera_frames=…, dice_rolls=…) -> Entropy
    verify(scanned, wallet) -> AddressCheck
    export_wallet(entropy, random_bytes, network=…) -> ExportedWallet
"""

from .address import AddressCheck, Verdict, page, verify
from .descriptor import output_descriptor_ur
from .entropy import Entropy, MixingReport, mix
from .entropy import report as mixing_report
from .export_password import ExportPassword, generate
from .failure import describe
from . import mnemonic
from .review import (
    OutputCategory,
    Refusal,
    RefusalReason,
    Review,
    WarningCode,
    WarningScope,
    review,
)
from .secret import SecretBuffer
from .signing import SigningRefused, sign
from .urcodec import (
    DifferentMessage,
    PsbtCollector,
    PsbtStream,
    URError,
    decode_psbt_parts,
    emit_parameters,
)
from .wallet import Network, ScriptType, Wallet
from .wallet_qr import AuthenticationFailed, ForeignContainer, decode, export_wallet

__all__ = [
    "AddressCheck",
    "AuthenticationFailed",
    "DifferentMessage",
    "Entropy",
    "MixingReport",
    "ExportPassword",
    "ForeignContainer",
    "Network",
    "OutputCategory",
    "PsbtCollector",
    "PsbtStream",
    "Refusal",
    "RefusalReason",
    "Review",
    "ScriptType",
    "SecretBuffer",
    "SigningRefused",
    "URError",
    "Verdict",
    "Wallet",
    "WarningCode",
    "WarningScope",
    "decode",
    "decode_psbt_parts",
    "describe",
    "emit_parameters",
    "export_wallet",
    "generate",
    "mix",
    "mixing_report",
    "mnemonic",
    "output_descriptor_ur",
    "page",
    "review",
    "sign",
    "verify",
]
