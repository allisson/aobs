#!/bin/sh
#
# Populate `build/sources/` with the corresponding source for every copyleft-touched package the
# release redistributes. The second step that touches a network, and it is not part of the build.
#
#     docker run --rm --platform=linux/amd64 -v "$PWD:/src" -w /src \
#         alpine:3.24 sh build/fetch-sources.sh
#
#     ... sh build/fetch-sources.sh --refresh     # also rewrites build/sources.sha256
#
# **The build never reads a byte of this.** `build/mkiso.sh` installs from `build/inputs/` and
# checks it on hash *and set equality*, so a source tarball placed there would be a file the build
# is required to have and required never to open — and every witness build and every 2030 rebuild
# would download ~456 MB it does not use. So this is a **second release asset**,
# `aobs-sources-<release>.tar`, with its own list (`build/sources.sha256`) and its own manifest
# field (`sources-list-sha256`). #68's line holds: the input archive is what the build consumes.
#
# --- Why this exists at all (#71, on #70's measurements) ------------------------------------------
#
# #57 said buildable sources were "explicitly not promised", on the premise that Alpine's distfiles
# retention was unverified and plausibly lossy. #70 measured it: the premise was false — the store is
# per-branch, accumulates superseded versions, reaches back to v3.10, and holds all 123 tarballs our
# origins name. What #70 also found is what moved the decision:
#
# - **GPLv2 §3 has no third-party-server route.** GPLv3 §6(d) does; GPLv2 does not, and 9 origins /
#   18 `.apk` files in this archive are GPL-2.0-**only** with no "or later" escape — busybox among
#   them. §3(c) is unavailable too: it passes along an offer *received*, and these `.apk` files came
#   off a CDN with no offer attached. So for those 18, a pointer was not one of the permitted things.
# - **Even where §6(d) permits it, the duty stays here.** "You remain obligated to ensure that it is
#   available" — against a single unmirrored nginx host with no CDN, 0 of 106 official mirrors
#   carrying it, which had eight branch directories deleted at once between 2025-09-06 and
#   2026-01-20 on no published policy.
# - **Upstream is already lossy at t=0.** `ncurses-6.6-20260516.tgz` 404s at its own APKBUILD URL
#   today and survives only on distfiles. "The rebuilder can fetch from upstream" is false on day one.
#
# So the sources are fetched now, while they are all still there, and published as bytes we control.
# As measured on v3.24: 48 origin aports, 306 files, ~456 MB.
#
# --- What "corresponding source" means here -------------------------------------------------------
#
# **The recipe is not the whole of it, and neither is the tarball.** aports carries the patches and
# the build script; the upstream tarball is the other half. So per origin this fetches both:
#
#   build/sources/<origin>/APKBUILD          at the exact commit the package's own .PKGINFO records
#   build/sources/<origin>/<local files>     every non-remote `source=` entry, same commit
#   build/sources/<origin>/<tarballs>        every remote `source=` entry, from Alpine's distfiles
#
# The aports files are fetched **one raw file at a time**, not as a GitLab-generated directory
# archive: a generated `.tar.gz` is not promised to be byte-stable across GitLab versions, and
# `build/sources.sha256` would then rot on somebody else's release schedule.
#
# `edge/` is searched when the branch directory misses. That is not a fallback for breakage: the
# branch directory records what the *branch* builders fetched, and a package built on edge and later
# pulled into the branch leaves its distfile only there. `apk-tools` is exactly that case today.
#
# --- What is verified, and what is not ------------------------------------------------------------
#
# Every fetched file is checked against the `sha512sums` in the APKBUILD that named it, which is the
# same check `abuild` makes — so a tampered distfiles host is caught here, by a hash that came from
# a git history at a pinned commit. What is *not* checked is the APKBUILD itself against anything
# but its commit id, and that is the point of pinning to `.PKGINFO`'s `c:` rather than to a branch.
#
# **The scope is Alpine's declared `L:` field, not an audit.** #70 did not read the packages' own
# COPYING files. A package Alpine mislabels as permissive gets no source archived here.
#
# **This script sources upstream shell.** Expanding `$source` needs the APKBUILD's own variables, so
# each one is `.`-sourced in a subshell. It runs in a throwaway container that is already talking to
# Alpine's CDN with `apk`; it is not run by the build, and nothing it produces reaches the ISO.

set -eu

SRC=${SRC:-$(pwd)}
INPUTS=$SRC/build/inputs
SOURCES=$SRC/build/sources
LIST=$SRC/build/sources.sha256

#: Read from `build/fetch-inputs.sh` rather than declared a second time: the branch whose distfiles
#: directory holds these tarballs is the branch the `.apk` files came from, and two declarations are
#: two things to forget to change together.
ALPINE_BRANCH=$(sed -n 's/^ALPINE_BRANCH=\(.*\)$/\1/p' "$SRC/build/fetch-inputs.sh")

DISTFILES=https://distfiles.alpinelinux.org/distfiles
APORTS=https://gitlab.alpinelinux.org/alpine/aports/-/raw

REFRESH=no
[ "${1:-}" = "--refresh" ] && REFRESH=yes

note() { printf '    %s\n' "$1"; }
stage() { printf '\n=== %s\n' "$1"; }

[ -d "$INPUTS/apks" ] || {
	printf 'build/inputs/ is empty: run build/fetch-inputs.sh first, or unpack an input archive.\n' >&2
	exit 2
}
command -v python3 >/dev/null || apk add --no-cache --quiet python3

rm -rf "$SOURCES"
mkdir -p "$SOURCES"

# --- Which origins ---------------------------------------------------------------------------
#
# Answered from the archived `.apk` files' own `.PKGINFO`, not from an index — so it answers the
# same way in 2030 from an unpacked release asset with no network (#68), and so the origin set is a
# fact about the bytes being redistributed rather than about a file fetched beside them.

stage "copyleft origins"
ORIGINS=$(python3 "$SRC/build/apkindex.py" "$INPUTS" --copyleft-origins)
note "$(printf '%s\n' "$ORIGINS" | grep -c . || true) origin aports declare a copyleft term"

# `main` or `community` — the aports tree splits by the same two repositories the archive does, and
# the raw URL needs the right one. Tried in order; a miss in both is a hard failure, because an
# origin we cannot fetch a recipe for is an origin we cannot archive source for, and skipping it
# silently would publish an archive that looks complete and is not.
aports_dir() {
	for repository in main community; do
		if wget -q -O "$2" "$APORTS/$1/$repository/$3/APKBUILD" 2>/dev/null; then
			printf '%s\n' "$repository"
			return 0
		fi
	done
	return 1
}

# distfiles first from the branch directory, then from `edge/`. See the header: `edge/` is where a
# package pulled into the branch after being built on edge leaves its tarball.
fetch_distfile() {
	for where in "$ALPINE_BRANCH" edge; do
		if wget -q -O "$2" "$DISTFILES/$where/$1" 2>/dev/null; then
			printf '%s\n' "$where"
			return 0
		fi
	done
	return 1
}

stage "recipes and tarballs"
printf '%s\n' "$ORIGINS" | while IFS="$(printf '\t')" read -r origin commit licence; do
	[ -n "$origin" ] || continue
	mkdir -p "$SOURCES/$origin"
	repository=$(aports_dir "$commit" "$SOURCES/$origin/APKBUILD" "$origin") || {
		printf 'no APKBUILD for %s at %s in main or community\n' "$origin" "$commit" >&2
		exit 1
	}

	# `$source` expanded by a real shell, in a subshell, because the entries interpolate `$pkgver`
	# and friends and a parser written here would be a second parser whose disagreements surface as
	# a source archive missing exactly the packages whose recipes are unusual.
	# `set +eu` inside: an APKBUILD is upstream shell written for `abuild`, which runs it under
	# neither flag. Several read variables `abuild` exports and call helpers that do not exist here,
	# and under `-u` the subshell dies before `source=` is ever assigned — which under `-e` looks
	# from out here like a fetch failure rather than like a recipe we mis-invoked.
	entries=$(
		set +eu
		# shellcheck disable=SC1090
		. "$SOURCES/$origin/APKBUILD" >/dev/null 2>&1
		# Unquoted on purpose: `source=` is a whitespace-separated list and splitting it is the
		# whole operation.
		# shellcheck disable=SC2086,SC2154
		printf '%s\n' $source
	)

	for entry in $entries; do
		# `filename::url` names the saved file; otherwise it is the URL's basename. Alpine uses the
		# first form wherever an upstream URL ends in something useless like `download`.
		name=${entry%%::*}
		url=${entry#*::}
		[ "$name" = "$entry" ] && { url=$entry; name=$(basename "$entry"); }

		case $url in
		*://*)
			where=$(fetch_distfile "$name" "$SOURCES/$origin/$name") || {
				printf '%s: %s is on neither distfiles/%s/ nor distfiles/edge/\n' \
					"$origin" "$name" "$ALPINE_BRANCH" >&2
				exit 1
			}
			[ "$where" = edge ] && note "$origin/$name came from distfiles/edge/"
			;;
		*)
			wget -q -O "$SOURCES/$origin/$name" "$APORTS/$commit/$repository/$origin/$name" || {
				printf '%s: %s is not in aports at %s\n' "$origin" "$name" "$commit" >&2
				exit 1
			}
			;;
		esac
	done

	# The recipe's own `sha512sums` block, applied to what was just fetched. This is `abuild`'s
	# check, made against a list that came out of a git history at a pinned commit — so it catches a
	# distfiles host serving different bytes than the one that built the binary.
	(
		cd "$SOURCES/$origin"
		set +u
		# shellcheck disable=SC1091
		. ./APKBUILD >/dev/null 2>&1
		# shellcheck disable=SC2154
		printf '%s\n' "$sha512sums" | grep -E '^[0-9a-f]{128}  ' | sha512sum -c - >/dev/null
	) || {
		printf '%s: fetched files do not match the sha512sums in its APKBUILD at %s\n' \
			"$origin" "$commit" >&2
		exit 1
	}
	printf '    %-24s %s (%s)\n' "$origin" "$commit" "$licence"
done

# --- The list --------------------------------------------------------------------------------
#
# Same shape and same reasoning as `build/inputs.sha256`: `LC_ALL=C`, paths relative to
# `build/sources/`, so the file is a function of the source set and not of the machine that wrote
# it. Its own sha256 is the manifest's `sources-list-sha256`, which is what binds a published
# `aobs-sources-<release>.tar` to a list a reader can regenerate from a `git checkout` of the tag.

stage "build/sources.sha256"
if [ "$REFRESH" = yes ]; then
	(cd "$SOURCES" && find . -type f | sed 's|^\./||' | LC_ALL=C sort | xargs sha256sum) >"$LIST"
	note "rewritten — $(grep -c . "$LIST") files. Review and commit the diff."
else
	note "left alone. Run with --refresh to re-fetch and rewrite it."
fi
