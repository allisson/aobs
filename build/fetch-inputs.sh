#!/bin/sh
#
# Populate `build/inputs/` with every byte the build consumes. The **only** step that touches a
# network, and it is not part of the build.
#
#     docker run --rm --platform=linux/amd64 -v "$PWD:/src" -w /src \
#         alpine:3.24 sh build/fetch-inputs.sh
#
#     ... sh build/fetch-inputs.sh --refresh      # also rewrites build/inputs.sha256
#
# `docs/reproducible-build.md` and #57 fix the shape, and the shape is the point:
#
# **There is no second build path.** `build/mkiso.sh` always installs from `build/inputs/` and never
# from a network. What differs between today and 2030 is only how that directory gets populated —
# from Alpine's CDN today, from the unpacked release asset then — so the 2030 rebuild walks exactly
# the code path CI walks on every commit, rather than a second one nobody has exercised since it was
# written.
#
# **This script verifies nothing on the build's behalf.** `build/mkiso.sh` checks `build/inputs/`
# against `build/inputs.sha256` on hash *and* on set equality before stage 1 runs. Verification only
# here would be verification a hand-populated directory walks straight past — and a hand-populated
# directory is precisely what the 2030 path is.
#
# **`--refresh` is a maintainer action and CI never runs it.** It re-resolves the closures against
# the live CDN and rewrites `build/inputs.sha256`; a human then commits that diff, because a changed
# hash for an unchanged version is exactly the supply-chain event that should be visible in a pull
# request. CI's witness build fetches from the CDN *against the committed list*, so it stays an
# independent reproduction and fails loudly the day a pin dies.
#
# **Why this runs in an `alpine:3.24` container while the builder does not.** Resolving an apk
# dependency closure needs `apk`, and fetching needs a network — both true of this step and of no
# other. `build/Dockerfile.iso` is `FROM scratch` plus a minirootfs tarball Alpine keeps forever
# (#55), so the *build* acquires no registry dependency. This script is a tool for getting bytes,
# not an input to the artifact, and nothing it does can change the ISO: what reaches the build is
# the directory, and the directory is judged against a list in git.

set -eu

SRC=${SRC:-$(pwd)}
INPUTS=$SRC/build/inputs
LIST=$SRC/build/inputs.sha256

#: Alpine's branch, and the point release whose minirootfs is the root of the build image. Alpine
#: keeps every point release's minirootfs forever, with a `.sha256` and an `.asc` beside it — which
#: is why #55 chose a tarball over a Docker Hub digest whose retention for untagged manifests could
#: not be established.
ALPINE_BRANCH=v3.24
ALPINE_RELEASE=3.24.1
MINIROOTFS=alpine-minirootfs-$ALPINE_RELEASE-x86_64.tar.gz

#: The one input that does not come from Alpine, pinned by version and by SHA-256 against the
#: tarball kernel.org publishes. 6.12 is a longterm line.
#:
#: The checksum was taken from kernel.org's own published `sha256sums.asc` for `v6.x`. That file is
#: PGP-signed and **this script does not verify the signature** — it verifies the tarball against
#: the checksum committed here, which moves the trust to this repository's git history where a
#: reviewer can see it change. Once fetched, the same tarball is pinned a second time by
#: `build/inputs.sha256`, which is the list the build actually enforces.
KERNEL_VERSION=6.12.106
KERNEL_SHA256=0392555761d99c7604503f6178951e2df77e978b92cc96d11e248423e48ed785
KERNEL_TARBALL=linux-$KERNEL_VERSION.tar.xz

CDN=https://dl-cdn.alpinelinux.org/alpine
REFRESH=no
[ "${1:-}" = "--refresh" ] && REFRESH=yes

note() { printf '    %s\n' "$1"; }
stage() { printf '\n=== %s\n' "$1"; }

command -v apk >/dev/null || {
	printf 'fetch-inputs.sh needs apk: run it in an alpine container, see the header.\n' >&2
	exit 2
}

# The appliance group of `build/apk-versions.txt` is read by `build/gather.py` and not by an `awk`
# expression here, because that file has two groups and a naive reader would put a package manager
# in the rootfs — the exact hazard the `# @group` markers were introduced to close, and
# `build/verify.py` raises rather than guesses. So this script needs `python3`, and installs it into
# its own throwaway container rather than making the documented command a two-part incantation.
# Nothing it installs reaches the ISO: what reaches the build is `build/inputs/`.
command -v python3 >/dev/null || apk add --no-cache --quiet python3

rm -rf "$INPUTS"
mkdir -p "$INPUTS/apks/main/x86_64" "$INPUTS/apks/community/x86_64"

# --- The verbatim indexes ------------------------------------------------------------------------
#
# Verbatim is the whole requirement: a locally regenerated index is refused as
# `UNTRUSTED signature`, so only the upstream one installs without `--allow-untrusted` — and
# `--allow-untrusted` in the build that produces a signing appliance is not a trade anyone should
# make. They are also what tells the download step below which of the two repositories each
# package came from, which is read off them rather than guessed.

stage "verbatim indexes"
for repository in main community; do
	wget -q -O "$INPUTS/apks/$repository/x86_64/APKINDEX.tar.gz" \
		"$CDN/$ALPINE_BRANCH/$repository/x86_64/APKINDEX.tar.gz"
done
note "APKINDEX.tar.gz for main and community"

# --- The apk closures ----------------------------------------------------------------------------
#
# Two closures. The **toolchain closure is archived too**, and #57 is emphatic about why: it dies
# first and larger, and a toolchain failure kills the build image before stage 1 ever runs.
# Archiving only the appliance half buys a release that still cannot be rebuilt.
#
# Resolved by **apk itself** against a throwaway root. A solver written here would be a second
# solver, and its disagreements with the real one would surface as an archive that passes its own
# checksum list and cannot build. `add --simulate` prints exactly what a real `add` would install.

closure() {
	root=$(mktemp -d)
	mkdir -p "$root/etc/apk"
	cp "$SRC/build/apk-repositories" "$root/etc/apk/repositories"
	apk --root "$root" --initdb --no-cache --keys-dir /etc/apk/keys add >/dev/null
	# shellcheck disable=SC2086
	apk --root "$root" --no-cache --keys-dir /etc/apk/keys \
		--repositories-file "$SRC/build/apk-repositories" add --simulate $1 |
		# apk right-pads the counter once the total reaches three digits — `( 94/112)`. A pattern
		# that assumed no padding silently matched only the first 99 lines, which is a closure
		# short by everything after it and an archive that cannot build.
		sed -n 's|^( *[0-9]*/ *[0-9]*) Installing \([^ ]*\) (\([^)]*\))$|\1-\2.apk|p' |
		LC_ALL=C sort -u
	rm -rf "$root"
}

stage "apk closures"
APPLIANCE_PINS=$(python3 "$SRC/build/gather.py" pins-of-group appliance "$SRC/build/apk-versions.txt")
TOOLCHAIN_PINS=$(sed -n 's/^\([a-z0-9][^ #]*\)$/\1/p' "$SRC/build/toolchain-versions.txt" | tr '\n' ' ')

APPLIANCE=$(closure "$APPLIANCE_PINS")
TOOLCHAIN=$(closure "$TOOLCHAIN_PINS")
note "appliance closure: $(printf '%s\n' "$APPLIANCE" | grep -c . || true) packages"
note "toolchain closure: $(printf '%s\n' "$TOOLCHAIN" | grep -c . || true) packages"

printf '%s\n%s\n' "$APPLIANCE" "$TOOLCHAIN" | LC_ALL=C sort -u |
	python3 "$SRC/build/apkindex.py" "$INPUTS" |
	while read -r repository package; do
		wget -q -O "$INPUTS/apks/$repository/x86_64/$package" \
			"$CDN/$ALPINE_BRANCH/$repository/x86_64/$package"
	done
note "downloaded into apks/main/x86_64 and apks/community/x86_64"

# --- The minirootfs ------------------------------------------------------------------------------

stage "base rootfs"
wget -q -O "$INPUTS/$MINIROOTFS" "$CDN/$ALPINE_BRANCH/releases/x86_64/$MINIROOTFS"
wget -q -O "$INPUTS/$MINIROOTFS.sha256" "$CDN/$ALPINE_BRANCH/releases/x86_64/$MINIROOTFS.sha256"
(cd "$INPUTS" && sha256sum -c "$MINIROOTFS.sha256")
rm -f "$INPUTS/$MINIROOTFS.sha256"
note "$MINIROOTFS matches Alpine's published .sha256"

# --- The kernel ----------------------------------------------------------------------------------

stage "kernel $KERNEL_VERSION"
wget -q -O "$INPUTS/$KERNEL_TARBALL" \
	"https://cdn.kernel.org/pub/linux/kernel/v6.x/$KERNEL_TARBALL"
echo "$KERNEL_SHA256  $INPUTS/$KERNEL_TARBALL" | sha256sum -c -
note "tarball matches the SHA-256 pinned above"

# --- The NOTICE ----------------------------------------------------------------------------------
#
# In the archive, beside the binaries it is about. #57: the `.apk` files go out unmodified and
# Alpine-signed, several are GPL, and the source obligation is met by locatable recipes — so the
# per-package licence and aports commit travel with the bytes rather than living only in a README a
# redistributor may not have.

stage "NOTICE"
python3 "$SRC/build/apkindex.py" "$INPUTS" --notice >"$INPUTS/NOTICE"
note "$(grep -c '|' "$INPUTS/NOTICE") packages recorded with licence and aports commit"

# --- The list ------------------------------------------------------------------------------------
#
# Sorted with `LC_ALL=C` and paths relative to `build/inputs/`, so the file is a function of the
# input set and not of the machine that wrote it.

stage "build/inputs.sha256"
if [ "$REFRESH" = yes ]; then
	(cd "$INPUTS" && find . -type f | sed 's|^\./||' | LC_ALL=C sort | xargs sha256sum) >"$LIST"
	note "rewritten — $(grep -c . "$LIST") files. Review and commit the diff:"
	note "a changed hash for an unchanged version is the event that should be visible in a PR."
else
	note "left alone. build/mkiso.sh checks build/inputs/ against it, on hash and set equality."
	note "Run with --refresh to re-resolve the closures and rewrite it."
fi
