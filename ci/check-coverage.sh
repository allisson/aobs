#!/bin/sh
# The coverage gates (05-testing-and-release.md §1).
#
# **Region coverage, never line coverage.** Line coverage marks a partially-taken branch
# as covered, which would let the rejection policy report green with half its arms
# untested. Every number below is `regions`, and `--fail-under-lines` is deliberately
# unused.
#
# Two gates: `aobs-core` >= 95% overall, and each of the nine components in
# ci/coverage-components.tsv >= 98%.
#
# This is a *separate* gate from the test run, because §1 says so in its own words:
# coverage is necessary, not sufficient. A repository can sit at 98% and still ship
# Coldcard's linkage defect.
set -eu

cd "$(dirname "$0")/.."

CORE_FLOOR=95
COMPONENT_FLOOR=98
COMPONENTS=ci/coverage-components.tsv
JSON="${AOBS_COVERAGE_JSON:-target/aobs-coverage.json}"

# --- The exclusion list, which is exactly the three §1 allows ------------------
#
# 1. **The shell crate**, and by `--package aobs-core` alone: cargo-llvm-cov derives the
#    excluded member's own absolute path from the manifest, which a regex written here
#    cannot do — a checkout under a directory that happens to contain `aobs/src` would
#    make a hand-rolled pattern swallow `aobs-core` too, and a coverage gate that
#    excludes the crate it is judging fails *silently*. So the exclusion is asserted
#    below against the report instead of hand-rolled into it.
# 2. **`unreachable!()` invariant arms** and 3. **derive-generated code** have no
#    per-region exclusion mechanism in llvm-cov, so nothing here encodes them. That
#    leaves this gate *stricter* than §1 permits, never looser: those regions count
#    against us. If a derive genuinely cannot be exercised, that is a ticket against this
#    file, not an ignore line added quietly — which is the same reason §1 forbids
#    per-function opt-out attributes and ci/check-source.sh refuses them.
#
# cargo-llvm-cov additionally drops `tests/`, `examples/`, `benches/` and `*_tests.rs` by
# default. Those are test code, not production regions, so their absence is not a fourth
# exclusion.
SHELL_RE='/aobs/(src|build\.rs)'

fail=0
bad() { echo "FAIL  $1" >&2; fail=1; }
good() { echo "ok    $1"; }

tab="$(printf '\t')"

# awk rather than bc: the build container has no bc, and `[ ]` cannot compare floats.
#
# `below` compares the exact ratio and never the printed one. Comparing the rounded value
# would let 97.995% print as 98.00% and pass a 98% floor — a gate rounding in the
# direction of green is the whole failure mode §1 is written against.
percent() { awk -v c="$1" -v n="$2" 'BEGIN { printf "%.2f", 100 * c / n }'; }
below() { awk -v c="$1" -v n="$2" -v f="$3" 'BEGIN { exit !(100 * c / n < f) }'; }

judge() {
    label="$1"
    covered="$2"
    count="$3"
    floor="$4"
    if [ "${count}" -eq 0 ]; then
        good "${label}: no regions yet"
        return
    fi
    pct="$(percent "${covered}" "${count}")"
    if below "${covered}" "${count}" "${floor}"; then
        bad "${label}: ${pct}% region < ${floor}% (${covered}/${count})"
    else
        good "${label}: ${pct}% region >= ${floor}% (${covered}/${count})"
    fi
}

# The list is nine. A row lost to a bad merge would otherwise pass as silence.
rows="$(grep -cve '^#' -e '^$' "${COMPONENTS}" || true)"
if [ "${rows}" -ne 9 ]; then
    bad "${COMPONENTS} names ${rows} components, and §1 names nine"
fi

no_regions_at_all() {
    good "aobs-core: no regions yet — the gate is wired and has nothing to judge"
    while IFS="${tab}" read -r name re; do
        case "${name}" in '' | '#'*) continue ;; esac
        good "${name}: no regions yet"
    done < "${COMPONENTS}"
}

log="$(mktemp)"
trap 'rm -f "${log}"' EXIT

mkdir -p "$(dirname "${JSON}")"
if cargo llvm-cov --package aobs-core --locked \
    --json --summary-only --output-path "${JSON}" > "${log}" 2>&1; then
    :
elif grep -q 'no coverage data found' "${log}"; then
    # An empty crate instruments to nothing at all and llvm-cov refuses to export. That
    # is this ticket's own starting state, so it is a pass with the reason printed and
    # not a green tick over an absence.
    no_regions_at_all
    exit "${fail}"
else
    cat "${log}" >&2
    exit 1
fi

# Exclusion 1, asserted rather than assumed. A false positive here fails loudly, which
# is the failure direction a security gate is allowed to have.
if jq -e --arg re "${SHELL_RE}" \
    '[.data[0].files[].filename | select(test($re))] | length > 0' "${JSON}" > /dev/null; then
    bad "the shell crate is in the coverage report; §1 excludes it"
    jq -r --arg re "${SHELL_RE}" '.data[0].files[].filename | select(test($re))' "${JSON}" >&2
else
    good "the shell crate is excluded"
fi

set -- $(jq -r '.data[0].totals.regions | "\(.covered) \(.count)"' "${JSON}")
judge "aobs-core" "$1" "$2" "${CORE_FLOOR}"

while IFS="${tab}" read -r name re; do
    case "${name}" in '' | '#'*) continue ;; esac
    set -- $(jq -r --arg re "${re}" '
        [.data[0].files[] | select(.filename | test($re)) | .summary.regions]
        | (((map(.covered) | add) // 0) | tostring) + " " + (((map(.count) | add) // 0) | tostring)
    ' "${JSON}")
    judge "${name}" "$1" "$2" "${COMPONENT_FLOOR}"
done < "${COMPONENTS}"

exit "${fail}"
