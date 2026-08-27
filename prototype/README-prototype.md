# PROTOTYPE — throwaway, not shipped

Written to resolve [The manifest and verify-release.sh, written out for a hypothetical
v1.0](https://github.com/allisson/aobs/issues/60). **Nothing here is part of the appliance**, nothing
here is on `main`, and every hash in these files except the kernel's is invented.

The `prototype` skill offers two shapes — an HTML state-machine demo or UI variations — and neither
fits. The artifact under discussion *is* plain text and shell, read by a person with `sha256sum` and
`gpg`; rendering that as an HTML demo would lower the fidelity of what is being judged, not raise
it. So the prototype is the real files, and the question it answers is **"is this what a stranger
should be asked to read and run?"**

## What is here

| file | what it is for |
|---|---|
| `release-v1.0/manifest-v1.0.txt` | every field filled in for a hypothetical v1.0 |
| `release-v1.0/verify-release.sh` | the verifier, `sha256sum` and `gpg` and nothing else |
| `release-v1.0/README-section.md` | the section a first-time user reads |

`manifest-v1.0.txt.asc` is **not** committed: a real one needs real signatures, and signing
throwaway content with the release key is the wrong habit to start.

## It was actually run

Not eyeballed — executed, against two scratch Ed25519 keys in a temporary `GNUPGHOME`, with real
random files standing in for the ISO and the archive and their real hashes patched into the
manifest:

| scenario | result |
|---|---|
| builder + witness both signed | both reported by fingerprint, files `OK`, exit 0 |
| builder only | passes, and prints `NOT SIGNED BY THE WITNESS — the manifest names 2 expected signers` |
| one byte appended to the manifest | `FAILED: a signature ... is BAD — the file has been altered`, exit 1 |
| archive not downloaded | exit 1 by default; exit 0 with `--iso-only` |

One empirical finding shaped the manifest format: **`sha256sum -c` cannot read a file with comments
in it.** Pointed at the manifest whole, busybox coreutils reports `comment line: FAILED` and exits
1. That is why the published-files block is a contiguous run of `<sha256>  <name>` lines and why the
documented one-liner pipes through `grep -E '^[0-9a-f]{64}  '` first.

## To run it yourself

```sh
cd prototype/release-v1.0
# you will need to supply your own manifest-v1.0.txt.asc and matching fingerprints
sh verify-release.sh
```
