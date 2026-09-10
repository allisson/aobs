# aobs — Amnesic Offline Bitcoin Signer

A bootable Debian image you run on an offline machine to review and sign a PSBT, then power off.
**QR codes are the only data path in or out.** No network driver and no network tool, no storage
driver, nothing writable to persist to, and exactly one userspace process.

If you have been doing air-gapped signing with a Tails stick and Electrum, this is the same idea
taken further: instead of a general-purpose OS with the dangerous parts turned off, the appliance is
one Python program running as **PID 1**, in an image the dangerous parts were removed from.

> This document's job is to help you **distrust this correctly**. Every claim below is labelled with
> the strength it actually has, and with what a stranger does to check it. A claim without a
> strength is not yet a claim.

---

## 🧭 Status — read this before anything else

| | |
|---|---|
| ✅ **Demonstrated** | The image boots on real hardware and signs. One transaction was built in Sparrow, scanned in, reviewed, signed, scanned back out and broadcast on **testnet4** from an appliance booted off a live USB stick on a Chromebook: [`dcdfc90e…6b3a07`](https://mempool.space/testnet4/tx/dcdfc90e38d7299caa00c5c7fb4c01ab73e9d093adee823745d9dbc6466b3a07) |
| ✅ **Demonstrated** | The ISO builds unprivileged in CI, from packages pinned to a `snapshot.debian.org` timestamp, with every build-time assertion passing |
| 🚧 **Not yet** | **No release.** No tag, no signed ISO, no manifest. There is nothing to download — you build it yourself or you don't run it |
| 🚧 **Not yet** | **No threat model published.** `docs/threat-model.md` is written in M3 and does not exist yet |
| 🚧 **Not yet** | **No reproducibility guard.** Byte-identical rebuild is the design intent; two builds on two hosts have never been compared |
| 🚧 **Not yet** | **No boot-checklist run record.** The structural claims below have not been checked *on a booted appliance* and written down where a stranger can read them |

**Do not put mainnet funds behind this yet.** Mainnet is the appliance's default network and it
will happily sign for it — that is deliberate, because the code is written to the bar it must
eventually meet. But the evidence that would justify trusting it (threat model, reproducible
rebuild, signed release, run record) is not published, and until it is, testnet4 and signet are
what this is for. `docs/roadmap.md` is the map of what is left.

---

## 🔒 The claims, and their exact strength

Three of these are **structural**: they cannot be violated because the mechanism does not exist. The
rest are **absence** claims — the mechanism is simply not in the image. An absence claim is weaker:
it is checkable by a stranger with `ls` and `find`, and it can be defeated by an adversary who
already has code execution on the appliance.

| Claim | Strength | How you check it |
|---|---|---|
| Exactly one userspace process exists for the whole session | 🧱 **Structural** — the app is PID 1, there is no init system to start a second | read `build/init`: it ends in `exec python3 -m aobs`, and there is no init binary in the image |
| No filesystem is mounted beyond tmpfs and pseudo-filesystems | 🧱 **Structural** — the whole rootfs *is* the initramfs; there is nothing to mount from | `cat /proc/mounts` |
| The boot medium is never read after boot | 🧱 **Structural** — firmware reads it before Linux starts | pull the stick out and keep signing |
| No network interface, and no tool to configure one | 🚫 **Absence** — no `kernel/net`, no `drivers/net`, no `iproute2` | `ls /lib/modules/*/kernel/net`, `command -v ip` |
| No block device, so nothing can be written to a persistent medium | 🚫 **Absence** — storage drivers are not in the image; the block layer itself is in Debian's kernel | `ls /sys/block`, `ls /lib/modules/*/kernel/drivers/{ata,nvme,scsi}` |
| USB binds nothing but HID and UVC | 🚫 **Absence + policy** — only those modules ship, and PID 1 sets `authorized_default=0` once our own devices have enumerated | `ls /lib/modules/*/kernel/drivers/usb`, and read the write in `build/init` |
| Nothing recoverable from RAM after power-off | ⚠️ **Best-effort, not promised** — there is no byte-zeroing | not checkable; stated as a limit |
| The published ISO is byte-identical to an independent rebuild | 🚧 **Intended, not yet demonstrated** | `sha256sum`, once M4 and a signed manifest exist |

**Why two of those are absence and not structural: the kernel is Debian's, unmodified.** The image
ships stock `linux-image-amd64` — no custom config, no rebuilt kernel — with the modules tree pruned
to an explicit allowlist of seven ([`build/modules.allow`](build/modules.allow): the four USB host
controllers, `usbhid`, `hid_generic`, `uvcvideo`). All of `kernel/net`, `drivers/net` and every
storage driver are deleted from the image, but `CONFIG_NET`, `CONFIG_BLOCK` and `CONFIG_MODULES` are
all `y` in that kernel. So *offline* means "no network module and no network tool is in the image",
not "no network stack exists"; and *nothing is written to a persistent medium* rests on no storage
driver being present, not on there being no block layer. An adversary who already has code execution
on the appliance is inside both. A `modprobe` blacklist ships as a cheap second line and is **never**
cited as the claim — the claim is that the module is not in the image.
[`docs/adr/0001-debian-base-and-stock-kernel.md`](docs/adr/0001-debian-base-and-stock-kernel.md)
records what that traded away and what it bought. Neither may be restated as structural.

**Two things this appliance is honest about:**

- 🐚 **There is a shell in the image** — `/bin/sh` is `dash`, because PID 1 is a shell script — and
  Python, which can `os.execv` anything.
  "No shell" would protect nobody. The claim that is actually enforced is narrower and checked by
  the build: **no getty, no VT with a login, no path from the running app to a prompt.**
- 🙈 **The appliance cannot verify itself.** A compromised image would report itself healthy. Every
  check above is one you run *from outside* — by rebuilding, or by looking at a running machine
  yourself.

---

## 🥷 Coming from Tails + Electrum

Not a "better than" table. These are the axes on which the difference is structural rather than a
matter of configuration.

| | Tails + Electrum | aobs |
|---|---|---|
| **Persistence** | An encrypted persistent volume is an offered feature | The rootfs *is* the initramfs. There is no writable medium to persist to, and no storage driver to reach one |
| **Processes** | A full desktop session: display manager, dbus, dozens of processes | One. The signer is PID 1; there is no init to start a second |
| **Data path** | QR *or* a USB stick — Electrum reads and shows QR codes, and both paths stay available | QR only, because there is no other. No mass storage driver is in the image, so a stick cannot be mounted even if you wanted to |
| **Network** | Tor-by-default, i.e. networking present and constrained | Networking is *removed from the image*: no net modules, no `ip` |
| **Wallet lifetime** | A wallet file that outlives the session | One wallet per session. Making another means powering off and booting again |

The cost is real and worth stating: a QR channel is slower than a file, the appliance does no coin
control and has no wallet history, and you give up everything else Tails is for.

---

## 🎲 Entropy — the part worth reading the code for

The promise is a floor: **the final 256 bits are no weaker than the strongest single contributing
source, and no single source can drag them down.** Three code shapes carry it, and all three are
structural rather than promised.

**1. The kernel CSPRNG is a required argument.** There is no reachable path in which dice
*substitute* for system entropy — the classic trap in dice-seed features. An empty value is a
programming error, not a mode of operation:

```python
# aobs/core/entropy.py:124
if not system:
    raise ValueError("the kernel CSPRNG is not an optional source")
```

**2. Sources are framed, then run through HKDF — never XOR'd.** Each source is encoded as
`label ‖ length ‖ bytes`, with the label's own length prefixed too, so no concatenation of parts can
be read as a different one and no source can shift another's boundary
([`aobs/core/entropy.py:103`](aobs/core/entropy.py)). XOR is disqualified outright: an adversary who
controls one input can cancel the rest. The framed material is the IKM for HKDF-SHA256 with a fixed
salt and info, output 32 bytes ([`aobs/core/entropy.py:143`](aobs/core/entropy.py)).

**3. There is no entropy estimator anywhere.** Krux's one memory-safety failure was a heap overflow
inside one, so this design does not have one to harden
([`aobs/core/entropy.py:13`](aobs/core/entropy.py)). No pixel statistics, no min-entropy
calculation, no strength meter, no progress bar filling toward "secure".

The three sources:

| Source | What is fed in | Where |
|---|---|---|
| **System** | `getrandom()`, `GRND_NONBLOCK` first so an uninitialised pool becomes a visible wait rather than a silent hang | [`aobs/adapters/real/entropy.py:30`](aobs/adapters/real/entropy.py) |
| **Camera** | Whole frames, SHA-256'd. No pixel arithmetic. A frame set that is entirely constant is flagged as a *hardware* sanity check — it cannot lower the floor, because the contribution stays additive | [`aobs/core/entropy.py:112`](aobs/core/entropy.py) |
| **Dice** | The ASCII roll string as typed, never bit-packed — which sidesteps mod-6 bias instead of correcting for it. Any count is accepted; there is no quota | [`aobs/core/entropy.py:157`](aobs/core/entropy.py) |

**How dice are described matters, and the usual framing is a lie.** Under the floor claim, dice do
not make your seed stronger — the kernel CSPRNG already sets the floor. Dice add a *source*. So the
honest reason to roll them is: **dice protect you if you distrust this machine's RNG.** The
appliance reports what you contributed as a fact — `log₂(6) = 2.585` bits per roll
([`aobs/core/constants.py:83`](aobs/core/constants.py)) — and a user who skips dice is never shown a
degraded state, because their guarantee is not degraded.

Full argument: [`docs/entropy-mixing.md`](docs/entropy-mixing.md).

---

## 🧾 What the appliance does with a PSBT

**It reviews first, and it refuses by raising.** There is exactly one signing entry point, and no
parameter, flag or alternate path proceeds past a refusal
([`aobs/core/signing.py`](aobs/core/signing.py)).

**The proof rule.** An output is shown as *proven change* only when the appliance can reproduce that
output's script from its own key, at a path it recognises. A `PSBT_IN_BIP32_DERIVATION` field in the
input is *evidence for* that check, never the answer — so a PSBT that lies about which outputs are
yours cannot talk the appliance into hiding a payment. Everything not proven is money leaving, and
is displayed as such, marked `⚠ NOT PROVEN`.
See [`docs/psbt-review-model.md`](docs/psbt-review-model.md).

**Scope, deliberately narrow:** single-sig **P2WPKH** (BIP84) and **P2TR** key-path (BIP86), account
`0`, not user-selectable. BIP44 and BIP49 are out of scope. Networks: **mainnet** (default),
**testnet4**, **signet**, **regtest** — chosen before the wallet exists and fixed for the session,
with a mismatch causing a refusal ([`docs/network-selection.md`](docs/network-selection.md)).

**Secrets never render.** Not in a screen, not in a log, not in an exception message — the one
carved-out exception is `ImportError`, which names a library, not a secret
([`docs/secret-hygiene.md`](docs/secret-hygiene.md)).

---

## 📷 The QR channel

The only way data moves. Inbound is a webcam decoding QR codes; outbound is QR codes drawn on the
console as half-blocks by the appliance's own renderer — no image library is involved on the way
out.

- PSBTs travel as **`ur:crypto-psbt`, UR v2, multi-part** (never `ur:psbt`).
- Emitted at **QR version 15, ECC L**, ≈340 payload bytes per fragment — sized against what a bare
  VT can actually draw ([`docs/qr-emit-parameters.md`](docs/qr-emit-parameters.md)).
- The scan screen shows a **slot map** — which parts have arrived — not a progress bar. A bar would
  be actively misleading with fountain-coded UR
  ([`docs/scan-feedback.md`](docs/scan-feedback.md)).
- The camera view is a **framing aid**, not a preview: it exists to help you aim, and nothing is
  decided by what it shows.
- Wallet backup travels its own way out — the **encrypted wallet QR**, below.

---

## 🔐 The encrypted wallet QR

A wallet can leave the appliance as **one static QR code**, encrypted, to be scanned back in on a
later boot through *Restore from an encrypted wallet QR*. It is the only thing besides a descriptor
and a signature that ever comes out.

**Two facts decide whether you are using it safely. Neither is the cryptography.**

🔑 **The password is eight words the appliance picks, and you cannot choose your own.** Eight words
from the EFF large wordlist is log₂(7776) × 8 ≈ **103.4 bits**, and that number is the entire
protection. The words go through Argon2id (m = 64 MiB, t = 3, p = 1), but **the stretching is
defence-in-depth, not the protection** — at 103 bits, brute force is infeasible whether derivation
costs a microsecond or a second, and any README that sold you the KDF would be selling theatre.
There is no field to type a password of your own into, which is the point: a self-chosen password
here is not a weaker export password, it is not one.

Before the export completes you type **all eight words back**, not a sampled subset. Sampling three
of eight misses a single mistranscribed word 62% of the time, and that error surfaces months later,
when the QR is the only copy of the wallet. A failed read-back retries **the same password** — a
fresh one would silently invalidate what you already wrote down.

🧠 **What the QR is worth on its own depends on your passphrase, and the appliance tells you which
case you are in.** Encrypted is the BIP39 *entropy* and the word count — **never the passphrase**.

- **Passphrase set.** The QR plus the eight words give back your recovery *words*, not your wallet.
  The passphrase is in neither, so nothing is spendable without what is in your head. That is the
  second factor working as designed.
- **No passphrase.** The QR plus the eight words **are** the wallet. Anyone holding both can spend,
  and keeping the paper away from the QR is the only thing between them and your funds.

The rest is where you would expect it: **ChaCha20-Poly1305** with the full 16-byte tag, chosen over
AES-GCM because the appliance boots on whatever amd64 machine you own, including ones without
AES-NI; an 89-byte binary container at **ECC level H**; and a cleartext-but-authenticated network
byte, so a backup from another chain is refused at the scan screen *before* you type eight words
rather than after. Wrong password and corrupt QR are distinguished by framing, never by
cryptography — a password verifier would hand an offline attacker a cheap oracle — so the appliance
says *wrong password or tampering* and does not claim which.
[`docs/encrypted-wallet-qr.md`](docs/encrypted-wallet-qr.md) fixes the format,
[`docs/export-password.md`](docs/export-password.md) the eight words and their read-back.

**How far this has been checked.** The export/restore round trip is covered in the authoritative
test tier — `tests/test_qr_loopback.py` pins the container and its QR version,
`tests/test_wallet_qr.py` and `tests/test_export_screens.py` the format and the screens. It has
**not** been exercised on a booted appliance: the M3 hardware run (`docs/roadmap.md`) walked keymap,
generate, descriptor export, PSBT review and signing, and stopped there. Green tests are not a run
record.

---

## 🚀 A session, end to end

Power on with the stick in. There is no login, no desktop, no prompt.

1. ⌨️ **Keymap picker** — the first screen. Pick your layout so the words you type are the words you
   mean.
2. 🌐 **Choose the network** if you are not on mainnet. It is a path like any other (`F10`), and it
   is fixed for good once a wallet exists.
3. 🔑 **One of the three ways in**, and only one per session: *Generate a new wallet* (the entropy
   above, optional dice, optional passphrase), *Type a seed in*, or *Restore from an encrypted
   wallet QR*.
4. 🆔 **Check the master fingerprint** against the one your watch-only wallet expects.
5. 📤 **Export the descriptor** by QR and import it into Sparrow (or your coordinator of choice) as a
   watch-only wallet.
6. 📥 **Build the unsigned PSBT there**, show it to the appliance's camera, **review every output** —
   proven change is labelled, everything else is money leaving.
7. ✍️ **Sign.** The signature comes back out as QR; scan it with the coordinator and broadcast.
8. 🔌 **`F12` powers off.** Nothing was written anywhere. The next boot is a stranger.

Every screen prints its own keys. On the home screen: `up`/`down` choose · `F10` opens the path ·
`F12` powers off.

---

## 🛠️ Build it yourself

There is no download, so this is the only way to get one. The build is pinned end to end: Debian 13
(trixie) at a fixed `snapshot.debian.org` timestamp, Python packages resolved and hash-pinned from
`pyproject.toml`/`uv.lock` and installed offline as wheels, and `embit` vendored into the tree
pinned by git SHA.

```sh
sh build/fetch-inputs.sh     # pinned .debs and wheels into build/inputs/, hash-checked
sh build/mkiso.sh            # -> out/bitcoin-signer-amd64.iso
```

`build/mkiso.sh` is **unprivileged, start to finish** (`mmdebstrap --mode=unshare`) — "needs root on
your host" would be a real barrier to the independent rebuilds this project's trust model depends
on. That claim is measured on `ubuntu-24.04` in CI. If your local Docker's kernel refuses the
unprivileged range mapping, `sh build/mkiso-docker.sh` will get you an ISO, but **it hands the
container `--privileged` and its output is not evidence for the unprivileged claim.**

Roughly what comes out: **58.0 MiB ISO**, 38.2 MiB initramfs, 11.6 MiB kernel, 155 MiB unpacked
rootfs, **512 MiB RAM floor** (PID 1 refuses below it, and says so).

Write it to a stick and boot with Secure Boot disabled:

```sh
sudo dd if=out/bitcoin-signer-amd64.iso of=/dev/sdX bs=4M status=progress conv=fsync
```

**On reproducibility:** byte-identical rebuild is the contract this project intends to rest on — the
signature tells you who to blame, the rebuild tells you whether to. It is **not yet demonstrated**.
Two builds on deliberately different hosts have never been compared, and there is no signed manifest
to compare against. That is M4 and M5.

---

## 🔍 Verify the claims yourself

**On a booted appliance.** A normal session gives you no prompt — there is no getty, no VT with a
login, and no path from the running app to a shell; if the app exits, the kernel panics on init
death rather than dropping you anywhere. To inspect the image you boot it *differently*, by typing
`init=/bin/sh` at the bootloader. That is not a backdoor and it is not defended against: a person
standing at the machine with the stick already owns it, and
[`docs/boot-pipeline.md`](docs/boot-pipeline.md) says so rather than papering over it.

```sh
cat /proc/mounts                                  # tmpfs and pseudo-filesystems only
ls /sys/block                                     # no block devices
command -v ip                                     # nothing
ls /lib/modules/*/kernel/net                      # no networking modules
ls /lib/modules/*/kernel/drivers/usb              # HID and UVC hosts only
```

Two claims are **not** checkable that way, and it is worth being exact about why — in that boot
*you* replaced PID 1, so anything PID 1 does never happened:

- **"Exactly one userspace process"** — a process count there describes your own shell. The claim
  follows from PID 1 being the app itself: read [`build/init`](build/init), which ends in
  `exec python3 -m aobs`, and the assertions in [`build/verify.py`](build/verify.py) that every
  command it runs resolves on PID 1's own `PATH` in the built rootfs.
- **`authorized_default=0`** — PID 1 writes it at step 4, after our own devices enumerate, so in a
  shell boot the value is whatever the kernel left. Reading it proves nothing; the write in
  `build/init` and the seven entries in [`build/modules.allow`](build/modules.allow) are the check.

The amnesia claim has a cheaper check that needs no shell at all: **in an ordinary session, pull the
boot medium out and keep signing.** That is the one that makes "the boot medium is not storage"
concrete.

**In the repository**, the build refuses rather than warns at the first stage where a published
claim stops being true. Every build-time assertion is a pure function in
[`build/verify.py`](build/verify.py), and the test suite feeds each one a deliberately broken input
to prove it still bites.

```sh
docker build -f build/Dockerfile.test -t aobs-test . && docker run --rm aobs-test
```

That container is the **authoritative** test tier and the only one a claim about the suite may come
from. A green run on your laptop is not evidence: without a loadable `libsecp256k1` the vendored
embit silently falls back to a pure-Python implementation 50–80× slower — the code path the boot
pipeline forbids on the appliance — and the suite passes anyway.

---

## 📚 Where things are decided

Design decisions live in the repo, in documents, so that a decision is reviewable in the same diff
as the change it authorises.

- [`docs/overview.md`](docs/overview.md) — start here if you are going to change the code
- [`CONTEXT.md`](CONTEXT.md) — the vocabulary, and its terms are load-bearing
- [`docs/roadmap.md`](docs/roadmap.md) — what is settled, what is open, in what order
- [`docs/entropy-mixing.md`](docs/entropy-mixing.md), [`docs/psbt-review-model.md`](docs/psbt-review-model.md), [`docs/seed-entry.md`](docs/seed-entry.md), [`docs/secret-hygiene.md`](docs/secret-hygiene.md), [`docs/address-verification.md`](docs/address-verification.md)
- [`docs/boot-pipeline.md`](docs/boot-pipeline.md), [`docs/test-harness.md`](docs/test-harness.md), [`docs/adr/`](docs/adr/)
- Not yet written, and named here rather than quietly omitted: `docs/threat-model.md`,
  `docs/boot-checklist.md` (both M3), `docs/reproducible-build.md` (M4), `docs/release.md` (M5)

---

## ⚖️ License

MIT. See [`LICENSE`](LICENSE).
