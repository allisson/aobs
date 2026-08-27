#!/bin/sh
# Verify an aobs release. PROTOTYPE — see ../README-prototype.md.
#
# Shells out to `sha256sum` and `gpg` and to nothing else. That constraint is the
# whole point: a verification tool you must first obtain and trust is the regress
# this project exists to escape, so this script must be readable in one sitting by
# someone who does not trust its author. It is ~120 lines, and every one of them is
# meant to be read before it is run.
#
#     ./verify-release.sh                 # verifies the files in this directory
#
# Exit status: 0 only if the signature checks AND every published file matches.

set -eu

MANIFEST=${MANIFEST:-manifest-v1.0.txt}
SIGNATURE=${SIGNATURE:-$MANIFEST.asc}

# Every signer this script will accept, by full fingerprint. Deliberately hardcoded
# and not read from the manifest: the manifest is the thing being verified, so
# trusting its `signer:` lines to decide who may sign it is circular. The manifest's
# list is used for one narrower purpose below — telling "one of two" from "one, and
# no idea whether more were expected".
KNOWN_BUILDER=C8532ED68A596CFBB7F92D04360718E309BEAA9F
KNOWN_WITNESS=1A4B7E90C25D8F3610EBA47D9C0F5182B6E3D74A

say()  { printf '%s\n' "$*"; }
fail() { printf 'FAILED: %s\n' "$*" >&2; exit 1; }

[ -f "$MANIFEST" ]  || fail "no manifest: $MANIFEST"
[ -f "$SIGNATURE" ] || fail "no signature: $SIGNATURE"

# ---------------------------------------------------------------- 1. signatures
#
# `--status-fd=1` because the human-readable output of gpg is not a stable interface
# and parsing it is how verifiers get subtly broken. The status lines are:
#
#   GOODSIG   <keyid> <uid>     a signature that checks out
#   BADSIG    <keyid> <uid>     a signature that does NOT check out
#   ERRSIG    ... 9 ...         could not check — usually key not in your keyring
#   VALIDSIG  <fingerprint> ... the full fingerprint, which GOODSIG does not give
#
# Multiple signers means multiple detached signatures concatenated into one .asc,
# which gpg reports one after another. Bitcoin Core's SHA256SUMS.asc is literally
# `cat *.asc`; nothing here is invented.

say "== signature"

STATUS=$(gpg --status-fd=1 --verify "$SIGNATURE" "$MANIFEST" 2>/dev/null || true)

# A single bad signature condemns the file, whatever else is present.
if printf '%s' "$STATUS" | grep -q '^\[GNUPG:\] BADSIG '; then
	fail "a signature over $MANIFEST is BAD — the file has been altered"
fi

GOOD_FPRS=$(printf '%s\n' "$STATUS" | sed -n 's/^\[GNUPG:\] VALIDSIG \([0-9A-F]*\) .*/\1/p')
UNCHECKABLE=$(printf '%s\n' "$STATUS" | grep -c '^\[GNUPG:\] ERRSIG ' || true)

matched_builder=no
matched_witness=no
unknown=0
for fpr in $GOOD_FPRS; do
	case "$fpr" in
		"$KNOWN_BUILDER") matched_builder=yes; say "  good signature — builder  $fpr" ;;
		"$KNOWN_WITNESS") matched_witness=yes; say "  good signature — witness  $fpr" ;;
		*) unknown=$((unknown + 1)); say "  good signature from an UNKNOWN key, ignored: $fpr" ;;
	esac
done

[ "$UNCHECKABLE" -gt 0 ] && say "  $UNCHECKABLE signature(s) could not be checked — key not in your keyring"

# One good signature from the builder is the bar. The witness is corroboration, and
# its absence is reported rather than fatal: CI not having signed is a fact a reader
# should weigh, not a reason to refuse a release the maintainer stands behind.
if [ "$matched_builder" = no ]; then
	fail "no good signature from the builder key $KNOWN_BUILDER"
fi

EXPECTED=$(grep -c '^signer: ' "$MANIFEST" || true)
if [ "$matched_witness" = no ]; then
	say "  NOT SIGNED BY THE WITNESS — the manifest names $EXPECTED expected signers"
fi

# ------------------------------------------------------------------- 2. hashes
#
# Only the block of `<sha256>  <name>` lines, which is why the manifest keeps its
# published files in that exact format. `sha256sum -c` treats every other line in the
# file as a malformed checksum line and fails on it.

say "== published files"

HASHLINES=$(grep -E '^[0-9a-f]{64}  ' "$MANIFEST")

# `sha256sum -c` already fails on a file it cannot open, so a missing file is caught
# here and needs no separate loop. It is worth being explicit that this is a release
# where not every named file has to be downloaded: a reader who wants only the ISO
# and not the 360 MB input archive gets a hard failure here, which is the wrong
# answer to a reasonable choice. Hence --iso-only, below.
if [ "${1:-}" = "--iso-only" ]; then
	HASHLINES=$(printf '%s\n' "$HASHLINES" | grep '  bitcoin-signer-amd64.iso$')
	say "  checking the ISO only, at your request; the input archive is not checked"
fi

printf '%s\n' "$HASHLINES" | sha256sum -c - || fail "a published file is missing or does not match the manifest"

# ------------------------------------------------------------------ 3. the report
#
# The part most verifiers skip. Saying what was checked is easy; saying what was NOT
# is what stops a green checkmark from meaning more than it should.

cat <<REPORT

== what this checked
   - $MANIFEST carries a good signature by the builder key
   - every published file present here matches the hash in the manifest

== what this did NOT check
   - that the ISO reproduces from source. That is a rebuild, not a hash check:
       git checkout $(sed -n 's/^git-tag: //p' "$MANIFEST") && ./build/fetch-inputs.sh && ./build/mkiso.sh
   - that the archived inputs are what upstream Alpine and kernel.org published.
     Their hashes are recorded in the manifest; nothing here re-derives them.
   - anything about the machine the builder ran. The signature says who vouches,
     never what they ran it on.

== what remains resting on trust
   - that $KNOWN_BUILDER is the maintainer's key. This script hardcodes the
     fingerprint; it cannot tell you the fingerprint is genuine. Confirm it from a
     channel that is not the one that served you this file — see the README.
   - the builder's own computer. The key is a personal key on an ordinary networked
     machine, stated plainly and not engineered away.
REPORT
