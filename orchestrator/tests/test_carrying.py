"""The merge a carried fix rests on, without a database.

`merge_file` is git's three-way merge and nothing else, so what is held here is
the reading of git's answer: a clean merge is text, overlapping changes are
None, and git failing to merge at all is an error that names why, never a file
with conflict markers in it.
"""

import pytest
from orchestrator.carrying import MergeUnavailable, merge_file

BASE = "one\ntwo\nthree\nfour\nfive\nsix\nseven\n"


def test_changes_to_different_lines_both_land() -> None:
    fixed = BASE.replace("two", "TWO")
    generated = BASE.replace("seven", "SEVEN")

    assert merge_file(base=BASE, ours=fixed, theirs=generated) == (
        "one\nTWO\nthree\nfour\nfive\nsix\nSEVEN\n"
    )


def test_changes_to_the_same_lines_are_refused_rather_than_marked() -> None:
    fixed = BASE.replace("two", "TWO")
    generated = BASE.replace("two", "deux")

    assert merge_file(base=BASE, ours=fixed, theirs=generated) is None


def test_a_file_that_already_has_the_fix_keeps_it_once() -> None:
    """A page kept from a version the fix was carried into already has it."""
    fixed = BASE.replace("two", "TWO")

    assert merge_file(base=BASE, ours=fixed, theirs=fixed) == fixed


def test_a_generated_file_the_fix_did_not_touch_takes_the_fix() -> None:
    fixed = BASE.replace("two", "TWO")

    assert merge_file(base=BASE, ours=fixed, theirs=BASE) == fixed


def test_a_file_without_a_last_newline_keeps_it_that_way() -> None:
    assert merge_file(base="a\nb", ours="a\nB", theirs="a\nb") == "a\nB"


def test_a_binary_file_is_not_merged() -> None:
    with pytest.raises(MergeUnavailable, match="not a text file"):
        merge_file(base="a\0b\n", ours="a\0B\n", theirs="a\0b\n")


def test_without_git_it_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("orchestrator.carrying.GIT", "git-that-is-not-installed")

    with pytest.raises(MergeUnavailable, match="git is not installed"):
        merge_file(base=BASE, ours=BASE, theirs=BASE)
