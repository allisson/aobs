# Frames captured from other wallets

The loopback test in `tests/test_qr_loopback.py` proves **self-consistency**: what this appliance
emits, this appliance reads back. That is not interop. `docs/test-harness.md` asks for the other
half — *a checked-in corpus of frames captured from Sparrow, Green and Blue Wallet* — because
`research/qr-psbt-formats` settled the format decisions from documentation, and a captured frame
is what turns "we read the spec correctly" into "we read their output correctly".

**This directory is currently empty of frames, and that is a gap, not a decision.** Capturing
them needs the three wallets running on real devices; nothing in the harness can synthesise one
without begging the question the corpus exists to answer.

`tests/test_wallet_interop.py` reads whatever is here and skips when there is nothing, so adding
a capture is adding files — no test edit.

## How to add a capture

1. In the wallet, produce a PSBT for a **testnet, signet or regtest** wallet derived from a
   published test-vector mnemonic. Never a live wallet: the fingerprint allow-list in
   `tests/test_structure.py` is the backstop, and a capture that trips it is a capture that
   should not have been made.
2. Photograph or screenshot every animated frame, in order. Any image format Pillow reads.
3. Put them in `fixtures/wallet_frames/<wallet>-<what>/`, named so they sort in emission order —
   `frame-000.png`, `frame-001.png`, …
4. Write `fixtures/wallet_frames/<wallet>-<what>/capture.json` beside them:

   ```json
   {
     "wallet": "Sparrow",
     "version": "2.1.3",
     "network": "signet",
     "what": "unsigned 2-in/2-out BIP84 PSBT, animated at the wallet's default density",
     "expected_psbt_sha256": "…",
     "notes": "captured off a 27-inch display at 1080p"
   }
   ```

   `expected_psbt_sha256` is the digest of the PSBT the frames must reassemble to. Take it from
   the wallet's own file export of the same transaction, so the corpus asserts against the
   wallet's bytes rather than against our reading of them.
