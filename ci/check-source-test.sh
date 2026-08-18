#!/bin/sh
# The test on the test (05-testing-and-release.md §1).
#
# §1 forbids per-function coverage opt-out attributes in source — "that is how a number
# gets met by editing the denominator instead of writing tests" — and ci/check-source.sh
# is what refuses them. A check nobody exercises is a check that quietly stops working: a
# typo in its regex turns the row green forever and nothing notices, which is the same
# class of defect as Coldcard's linkage. So this plants each forbidden attribute in the
# tree, asserts the check fails, and removes it again.
set -eu

cd "$(dirname "$0")/.."

# Inside aobs-core/src so it lands where check-source.sh greps, and not declared as a
# module so cargo never compiles it.
probe="aobs-core/src/.coverage-optout-probe.rs"
trap 'rm -f "${probe}"' EXIT HUP INT TERM

fail=0
bad() { echo "FAIL  $1" >&2; fail=1; }
good() { echo "ok    $1"; }

# One per arm of the pattern. Both arms in one file would leave a green result meaning
# "at least one of them bit" rather than "each of them bit".
for attr in '#[coverage(off)]' '#[cfg_attr(coverage, coverage(off))]'; do
    printf '%s\nfn probe() {}\n' "${attr}" > "${probe}"
    if ci/check-source.sh > /dev/null 2>&1; then
        bad "ci/check-source.sh passed with ${attr} in the tree"
    else
        good "ci/check-source.sh refuses ${attr}"
    fi
done
rm -f "${probe}"

# Without this row the two above prove nothing: a check that fails on everything would
# pass them both.
if ci/check-source.sh > /dev/null 2>&1; then
    good "ci/check-source.sh passes on the clean tree"
else
    bad "ci/check-source.sh fails on the clean tree"
    ci/check-source.sh >&2 || true
fi

exit "${fail}"
