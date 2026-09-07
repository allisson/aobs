"""The two session gates in `tests/conftest.py`, fed the inputs they exist to refuse.

Both gates are the same kind of thing as `build/verify.py`: a claim that fails the run rather than
warning. So they are checked the same way — each fed an input broken in the exact way it exists to
catch — because a gate nobody has watched fire is a gate nobody has checked, and these two are the
ones standing between a green report and a report that means nothing.
"""

from __future__ import annotations

import conftest


# --- The EC backend -------------------------------------------------------------------------------


def test_the_live_backend_is_read_from_what_embit_actually_bound() -> None:
    """Not from whether a `.so` is on disk. `secp256k1.py` binds inside a bare `except:`, so a
    library that is present but unloadable produces a pure-Python signer and no error."""
    assert conftest.live_ec_backend() in {"ctypes_secp256k1", "py_secp256k1"}


def test_the_header_says_so_when_the_run_is_not_evidence_about_the_appliance() -> None:
    """The dev-machine half of the gate. A run through `py_secp256k1` is not wrong, but it must
    not be mistakable for evidence — `CLAUDE.md` forbids citing one, and this is what makes the
    run itself say which kind it was."""
    header = conftest.pytest_report_header()
    assert header[0].startswith("aobs: python ")
    assert conftest.live_ec_backend() in header[0]
    if conftest.live_ec_backend() != conftest.NATIVE_EC_BACKEND:
        assert "NOT evidence" in header[1]
    else:
        assert len(header) == 1


# --- The skip policy ------------------------------------------------------------------------------

ALLOWED = {"tests/test_x.py::test_a": "arrives at M2"}


def test_a_run_that_skips_exactly_what_is_named_is_clean() -> None:
    assert conftest.skip_policy_violations({"tests/test_x.py::test_a"}, ALLOWED, whole_suite=True) == []


def test_a_skip_nobody_named_fails_the_session() -> None:
    """The failure this exists for: a guard added to a test in passing, and a tier that reports
    the result as green because the count still looked plausible."""
    violations = conftest.skip_policy_violations(
        {"tests/test_x.py::test_a", "tests/test_y.py::test_b"}, ALLOWED, whole_suite=True
    )
    assert violations == ["  UNNAMED SKIP  tests/test_y.py::test_b"]


def test_an_entry_that_no_longer_skips_fails_the_session_too() -> None:
    """A stale entry is a standing exemption nobody will notice has stopped applying, so the next
    skip of that test passes unremarked. It is deleted when its subject arrives, and this is what
    makes deleting it non-optional."""
    violations = conftest.skip_policy_violations(set(), ALLOWED, whole_suite=True)
    assert violations == ["  NO LONGER SKIPS  tests/test_x.py::test_a  (arrives at M2)"]


def test_a_single_file_run_is_not_judged_stale() -> None:
    """The dev loop runs one file in this same container. The other allowlisted ids not appearing
    means "not collected", and reporting that as a violation would make the container unusable for
    the loop it exists to serve."""
    assert conftest.skip_policy_violations(set(), ALLOWED, whole_suite=False) == []


def test_an_unnamed_skip_is_caught_in_a_single_file_run_as_well() -> None:
    """Only the staleness half is relaxed for a partial run. A skip nobody named is a skip nobody
    named however few files were collected."""
    violations = conftest.skip_policy_violations(
        {"tests/test_y.py::test_b"}, ALLOWED, whole_suite=False
    )
    assert violations == ["  UNNAMED SKIP  tests/test_y.py::test_b"]


def test_every_allowlisted_node_id_names_the_milestone_that_removes_it() -> None:
    """`docs/roadmap.md` M1 says no test may be skipped in this tier. These four are tolerated
    because their *subjects* are absent, and each reason must say when that stops being true —
    otherwise the allowlist becomes the permanent skip it was written to prevent."""
    assert conftest.SKIPS_ALLOWED, "an empty allowlist means the tier skips nothing; say so here"
    for nodeid, reason in conftest.SKIPS_ALLOWED.items():
        assert "::" in nodeid, f"{nodeid} is not a node id"
        assert reason.strip(), f"{nodeid} is excused without a reason"
