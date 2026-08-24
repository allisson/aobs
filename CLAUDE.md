# aobs — Amnesic Offline Bitcoin Signer

A Bitcoin signing **appliance**: a bootable Alpine LiveCD (amd64) run on an offline machine to
review and sign a PSBT, then powered off. Nothing survives the **session**. QR codes are the only
data path in or out. Python, single-sig, [embit](https://github.com/diybitcoinhardware/embit).

## This repo is in design, not build

There is no application code yet, deliberately. The architecture is being closed one decision at
a time on the wayfinder **map**: [issue #1](https://github.com/allisson/aobs/issues/1).

Read the map before writing code that touches entropy, the QR channel, the encrypted wallet QR,
the amnesia guarantee, PSBT review, the boot pipeline, or the test harness. Each is an open
ticket. The map's **Decisions so far** holds what is settled, **Not yet specified** the fog ahead,
**Out of scope** what has been ruled out of this effort.

When a request needs one of those open questions answered, name the ticket that blocks it and
work that ticket — `/wayfinder https://github.com/allisson/aobs/issues/1` — so the answer lands on
the map. A design decision made only inside a code diff is invisible to the next session, which
then decides it differently.

## Issue tracker

GitHub issues on `allisson/aobs`, via `gh`. Wayfinding operations (map, child tickets, native
`blocked_by` dependencies, frontier query, claim, resolve) follow
`~/.agents/skills/setup-matt-pocock-skills/issue-tracker-github.md`.

Labels: `wayfinder:map` on the map; `wayfinder:research` / `wayfinder:prototype` /
`wayfinder:grilling` / `wayfinder:task` on tickets. Claiming a ticket means assigning it to
yourself, as the session's first write.

Research tickets in this effort are worked deliberately, not auto-fired as subagents. Ask before
dispatching them.

## Vocabulary

`CONTEXT.md` is the glossary — *appliance*, *session*, *amnesic*, *no data path*, *QR channel*,
*wallet*, *mnemonic*, *passphrase* vs *export password*, *watch-only wallet*. Read it before
writing prose about the appliance, naming a new concept, or judging a security claim. Add a term
to it the moment one is settled; keep implementation detail and decisions out of it.

## Security claims

This appliance is written for the **publishable** bar: strangers boot the ISO with real funds.

- **State every claim so it can be checked.** "No USB" is false and unverifiable; "no block
  device, no filesystem, and no network interface is ever mounted or brought up; USB is restricted
  to the HID class" is true and testable. When a claim resists that treatment, reword it — the
  vague version protects nobody.
- **Treat the watch-only wallet as an adversary.** Everything shown to the user comes from the
  PSBT plus the appliance's own keys. Change outputs are proven from the appliance's own
  derivation, never from what the PSBT labels as change.
- **Reach for embit and reviewed crypto libraries** for bitcoin primitives, BIP32/39 derivation,
  PSBT parsing, AEAD, and KDFs.
- **Keep test seeds to published BIP39 vectors or testnet/signet/regtest keys**, so a fixture is
  never a live mainnet wallet.
- **The appliance makes no network calls.** Fee rates, UTXO data, and exchange rates arrive in the
  PSBT or not at all.
