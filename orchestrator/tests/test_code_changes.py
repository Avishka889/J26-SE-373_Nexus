"""What changed between two code versions, file by file (review item C2-8).

The code review showed the files of the version under review and nothing of
what had changed since the one before, so a reviewer approving version 4 after
asking for changes to version 3 could not see whether they were made.
"""

from orchestrator.code_changes import MAX_DIFF_LINES, changes_between


def test_each_file_says_how_it_changed_with_its_diff() -> None:
    before = {"a.ts": "one\ntwo\n", "gone.ts": "x\n", "same.ts": "s\n"}
    after = {"a.ts": "one\nTWO\nthree\n", "new.ts": "n\nm\n", "same.ts": "s\n"}

    changed = changes_between(before, after)

    assert [
        (one["path"], one["status"], one["additions"], one["deletions"]) for one in changed
    ] == [
        ("a.ts", "changed", 2, 1),
        ("gone.ts", "removed", 0, 1),
        ("new.ts", "added", 2, 0),
    ]
    assert "-two" in changed[0]["diff"] and "+TWO" in changed[0]["diff"]
    assert all(one["truncated"] is False for one in changed)


def test_a_long_diff_is_cut_and_says_so() -> None:
    before = {"big.ts": ""}
    after = {"big.ts": "".join(f"line {n}\n" for n in range(MAX_DIFF_LINES * 2))}

    [big] = changes_between(before, after)

    assert big["truncated"] is True
    assert len(big["diff"].splitlines()) == MAX_DIFF_LINES
    assert big["additions"] == MAX_DIFF_LINES * 2, "the count is of the whole change"
