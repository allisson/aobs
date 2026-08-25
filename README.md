# aobs

Amnesic Offline Bitcoin Signer — a Bitcoin signing appliance: a bootable Alpine LiveCD run on an
offline machine to review and sign a PSBT, then powered off. QR codes are the only data path in or
out. Single-sig, BIP84 and BIP86, Python, [embit](https://github.com/diybitcoinhardware/embit).

The design is closed one decision at a time on the wayfinder map,
[issue #1](https://github.com/allisson/aobs/issues/1); `docs/` holds the settled decisions and
`CONTEXT.md` the vocabulary. **Read the document before changing behaviour it fixes** — a design
decision made only inside a code diff is invisible to the next session.

## What exists today

`aobs/core/` — the pure core — the harness around it, and the application shell. There are no real
adapters and no ISO yet, and most screens are still later specs.

| | |
|---|---|
| `aobs/core/` | Bytes in, value objects out. No I/O, no clock, no ambient state. |
| `aobs/ports/` | The four ports: `FrameSource`, `Keymap`, `EntropySource`, `Power`. |
| `aobs/adapters/fake/` | The harness half of each port. The real half is a later spec. |
| `aobs/ui/` | The Textual application: global keys, the failure shape, the keymap picker. |
| `fixtures/` | Every fixture, and the one script that generates them all. |
| `build/` | The authoritative test tier. |

The display is not a port. `SignerApp` **is** the display seam: tests drive the real application
headless through Textual's `run_test()`, and the console adapter will run the very same object.

One rule carries weight and a test enforces it: **`core/` may not import any adapter,
`aobs.ui` or `aobs.ports`.**

## Running the tests

Two tiers.

**Fast local** — the loop a developer lives in:

```sh
uv run pytest
```

**Authoritative** — `alpine:3.24` with the exact apk versions pinned in `build/apk-versions.txt`,
so a `zxing-cpp` or `cryptography` skew fails here rather than on the appliance:

```sh
docker build -f build/Dockerfile.test -t aobs-test . && docker run --rm aobs-test
```

**Regtest, opt-in** — the only instrument that catches a wrong taproot sighash, because a wrong
sighash produces a well-formed signature every appliance-side check accepts. Needs a `bitcoind`
in regtest mode:

```sh
uv run pytest -m regtest
```

`BITCOIN_CLI` and `BITCOIN_CLI_ARGS` say how to reach the node, so a container counts as one and
nothing needs installing on the host — the invocation is in that module's docstring.

Fixtures are generated artifacts, committed next to their generator so a reviewer regenerates and
diffs rather than trusting a blob:

```sh
uv run python fixtures/generate.py
```

Every key in this repository descends from the BIP39 test-vector mnemonic printed in BIP39
itself. A test asserts every fixture's master fingerprint is on a short allow-list, so a PSBT
from a real wallet fails CI rather than quietly committing an xpub.

## Status

Not usable as an appliance yet, and nothing here has been run on real hardware. The claims in
`docs/` state what is checkable and how; `docs/boot-checklist.md` is what only a boot can check
and is published with the ISO.
