"""Named constants of the appliance's core.

Every constant here traces to a closed decision in `docs/`. A change to one of these numbers is
a change to a decision, so the comment naming the document is part of the constant.
"""

# --- The derivation window (docs/psbt-review-model.md) ---------------------------------------

#: How far past the highest index seen in the PSBT's own inputs change may still prove.
CHANGE_WINDOW_LOOKAHEAD = 20

#: Absolute ceiling on that window. `docs/psbt-review-model.md` fixes the shape of the window
#: but not this number; 200 matches the address-verification window, which
#: `docs/address-verification.md` measured at 47 ms for 200 P2WPKH keys.
CHANGE_WINDOW_CEILING = 200

# --- Address verification (docs/address-verification.md) -------------------------------------

#: Addresses searched on each chain by a scan, and the size of each user-requested extension.
ADDRESS_SEARCH_BLOCK = 200

#: How many addresses the browsable list shows at a time.
ADDRESS_PAGE_SIZE = 20

# --- Warnings (docs/psbt-review-model.md) ----------------------------------------------------

#: Fee warned above this share of the amount actually leaving the wallet.
FEE_WARN_SHARE_OF_SENT = 0.10

#: Fee warned above this rate, in satoshis per virtual byte, whatever the share.
FEE_WARN_SAT_PER_VBYTE = 100.0

# --- Encrypted wallet QR (docs/encrypted-wallet-qr.md) ---------------------------------------

WALLET_QR_MAGIC = b"AOBS"
#: Version 2 carries the network byte. There is no version 1 compatibility: no ISO has been
#: published, so no version 1 container exists outside this repository's own tests, and one that
#: turns up meets the framing check that already says *written by a different version*.
WALLET_QR_VERSION = 2

#: The network the container was exported from, one byte in the header — readable before any
#: decryption and covered by the Poly1305 tag. Keyed by `Network.value` and assigned **explicitly**,
#: never taken from the enum's ordinal: reordering `Network` would otherwise be a silent format
#: change that reinterprets every container already written.
WALLET_QR_NETWORK_BYTE = {
    "mainnet": 0x00,
    "testnet4": 0x01,
    "signet": 0x02,
    "regtest": 0x03,
}

#: Argon2id parameters, encoded exactly in the container — never lossily (Krux's mistake).
ARGON2_MEMORY_KIB = 64 * 1024
ARGON2_TIME_COST = 3
ARGON2_PARALLELISM = 1

WALLET_QR_SALT_BYTES = 16
WALLET_QR_NONCE_BYTES = 12
WALLET_QR_PLAINTEXT_BYTES = 33  # 32 entropy bytes, padded, plus one word-count byte
WALLET_QR_TAG_BYTES = 16
#: 4 magic + 1 version + 1 network + 6 params + 16 salt + 12 nonce + 33 ciphertext + 16 tag.
WALLET_QR_TOTAL_BYTES = 89

# --- Export password (docs/export-password.md) -----------------------------------------------

#: Eight words of the EFF large list: log2(7776) * 8 = 103.4 bits.
EXPORT_PASSWORD_WORDS = 8

# --- Entropy mixing (docs/entropy-mixing.md) -------------------------------------------------

#: HKDF salt. A fixed protocol label, not a secret.
ENTROPY_HKDF_SALT = b"aobs/entropy/v1"
ENTROPY_HKDF_INFO = b"aobs/entropy/bip39-entropy/v1"
ENTROPY_OUTPUT_BYTES = 32

#: Whole camera frames handed to `mix()` per generated wallet. A small fixed number, hashed, with
#: no entropy estimate of any kind — `docs/entropy-mixing.md` is explicit that the estimator is
#: the part that produced the one real memory-safety failure in a comparable project, so there is
#: none. Eight is the number the published example report states.
ENTROPY_CAMERA_FRAMES = 8

#: 99 D6 rolls carry 256 bits at log2(6) ≈ 2.585 bits each. Stated as a fact, never as a quota.
DICE_BITS_PER_ROLL = 2.584962500721156

# --- QR emit parameters (docs/qr-emit-parameters.md) -----------------------------------------

#: Payload bytes per UR fragment, and the ladder the user steps down when a wallet will not read
#: the dense code. Computed from the field layouts at version 15 / ECC L, not measured — which
#: is why the ladder exists.
UR_FRAGMENT_LADDER = (340, 200, 120, 50)
UR_FRAGMENT_BYTES = UR_FRAGMENT_LADDER[0]

#: Frames per second alongside each rung of the ladder.
UR_FRAME_RATE_LADDER = (2, 2, 1, 1)

#: The animated stream is re-emitted every cycle, so a lost frame costs latency and not
#: correctness; anything static is read once, off paper, at an unknown angle.
QR_ECC_ANIMATED = "L"
QR_ECC_STATIC = "H"
QR_VERSION_ANIMATED = 15
