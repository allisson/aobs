# Encrypted wallet QR

The format the appliance exports a wallet as, and imports it back from: a single QR, encrypted under
an export password of eight EFF large-wordlist words.

## What is encrypted

**The BIP39 entropy (16–32 bytes) plus the word count. Never the passphrase.**

Entropy rather than the words themselves: it is far smaller, and it regenerates the exact words
deterministically through the BIP39 checksum. Not the derived master seed, which would throw away
both the ability to show the words back and the ability to re-derive under a different passphrase.

**Excluding the passphrase is the load-bearing half of this choice.** It means the QR alone is not
the wallet: someone holding the QR *and* the paper with the eight export words still cannot spend,
because the BIP39 passphrase lives only in the owner's head. That is the realistic theft scenario —
a QR and its password are likely to be stored near each other — and it is what turns the passphrase
into a genuine second factor. Krux makes the same choice.

**The UI must say so plainly:** *the passphrase is not in this QR — you must remember it.* A user who
believes the QR is a complete backup and then forgets the passphrase has lost the wallet, and that
failure is on the wording, not on them.

## Cipher

**ChaCha20-Poly1305, with the full 16-byte Poly1305 tag.**

AES-256-GCM is equally available on Alpine, so the decision turns on hardware the appliance does not
control: it boots on whatever amd64 machine the user has, including older ones without AES-NI, where
software AES is both slower and a timing-attack surface. ChaCha20 is constant-time in software by
design. Nonce reuse is not a concern either way — a fresh salt per export makes every key unique —
but ChaCha's margin here costs nothing.

**The tag is never truncated.** Krux's KEF ships a 3–4 byte tag; Specter-DIY's `aead_encrypt` uses a
full 32-byte HMAC. This format has no size pressure at all, so shortening the one field that
authenticates the payload would be economising in exactly the wrong place.

## Key derivation

**Argon2id, m = 64 MiB, t = 3, p = 1.**

**The word count is what protects this wallet, not the KDF.** Eight EFF large-wordlist words is
log₂(7776) × 8 ≈ **103.4 bits**. Against that, stretching is irrelevant: brute force is infeasible
whether derivation costs a microsecond or a second. Any documentation implying the KDF is the
protection would be theatre.

The KDF is kept anyway, as defence-in-depth and for one forward-looking reason: if a later version
ever allows a user-chosen password, the KDF is what would save them — and retrofitting one into a
deployed container format is precisely the migration that produces unreadable old backups. 64 MiB
transient is trivial against the RAM floor.

**Parameters are encoded exactly in the container, never lossily.** This is a direct lesson from
prior art: Krux shipped a lossy iteration encoding and produced backups that could not be decrypted
(#7). Round-trip fixtures must cover every parameter value the format admits.

## Container layout

Binary QR **byte mode**, no base64 — both ends are our own code, base64 would cost 33% for nothing,
and zxing-cpp (settled in #6) decodes byte mode natively.

| field | bytes |
|---|---|
| magic | 4 |
| version | 1 |
| network | 1 |
| Argon2id parameters (m, t, p — exact) | 6 |
| salt | 16 |
| nonce | 12 |
| ciphertext (32-byte entropy + 1-byte word count, padded) | 33 |
| Poly1305 tag | 16 |
| **total** | **89** |

The **version byte is 2**. There is no version 1 compatibility and none is needed: no ISO has been
published, so no version 1 container exists outside this repository's own tests, and one that turns
up is refused by the framing check that already says *written by a different version*.

The **network byte** names the chain the backup was exported from — `mainnet` `0x00`, `testnet4`
`0x01`, `signet` `0x02`, `regtest` `0x03`, assigned explicitly and never taken from an enum's
ordinal. It sits in the header rather than the plaintext deliberately: the whole 12-byte header is
the AEAD's associated data, so the byte is **authenticated without being encrypted** and can be read
before the password is typed. The network was never a secret, and the appliance holds no
network-dependent secret a cleartext byte could leak.

At 89 bytes there is ample room for **ECC level H**, which is where the size headroom should go: the
reader is a webcam pointed at a screen or a sheet of paper. Note that the size table in #7's research
assumes ECC level L, so it must be recomputed at H for this payload; the spec's own test vectors pin
the resulting QR version rather than this document asserting one — 89 bytes of binary at ECC H is a
**version 9** code, 53×53 modules, well inside the console's 77×77 budget, and it is pinned in
`tests/test_qr_loopback.py`. The network byte cost nothing: 88 bytes was version 9 too.

## Failure behaviour

**Wrong password and corrupt QR are distinguished by framing, not by cryptography.**

An AEAD tag failure cannot tell them apart, and adding a password verifier would actively weaken the
format by handing an offline attacker a cheap oracle.

So: the magic bytes, version byte and network byte are checked first. If they parse, this is one of
our containers and the failure is **authentication** — wrong password or tampering, and the appliance
says exactly that without claiming which. If they do not parse, it is a foreign or corrupt QR, and
the message is different. Physical corruption is mostly caught earlier by the QR's own error
correction, which is the second reason for ECC level H.

**The network byte follows that discipline exactly, in both directions.**

*A byte naming a network this build does not know* is a **framing** failure, told in its own words —
*this is one of our wallet backups, but it names a network this version does not know* — and never
as *wrong password*, which would send the user hunting for a typing mistake they did not make.

*A byte naming a network this session is not on* is not a failure of the format at all: the
container is intact and the words are right. It is a **refusal**, and it happens twice. Once at the
scan screen, from the cleartext header, so the user learns the backup belongs to another chain
before typing eight words in full; and once after the password verifies, from the same byte now
covered by the tag. Only the second is the boundary — anyone who can substitute the QR can flip the
cleartext byte, and flipping it either fails authentication or arrives at the authenticated
comparison. Both checks must exist, and a later simplification that keeps one must keep the second.

*A byte that is physically damaged* fails the tag, and is reported as **wrong password or tampering**
with no claim as to which. The new field does not weaken the format's existing failure discipline
and is not allowed to.

## Out of scope for this document

**How the eight-word password reaches and returns from the human** — display, chunking, read-back,
confirmation. That is a UI flow depending on seed entry and the failure states, and it has its own
ticket.

One constraint this format imposes on that flow: the password is machine-generated at full entropy,
and the flow must **never** let a user substitute a shorter or self-chosen one. Doing so would move
the entire security of the export onto a KDF this document has just said is not load-bearing.
