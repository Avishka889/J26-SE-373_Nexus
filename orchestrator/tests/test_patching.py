"""Applying an approved patch, and refusing to when it no longer fits.

The one place a security fix crosses a component boundary. C3 proposes, a
person accepts, and this applies, because the orchestrator owns the version
axis and a component that both found the weakness and edited the code to close
it could mark its own homework.

What is held here is the refusal. A fuzzy apply that slid a hunk to a nearby
offset would write unreviewed code into the one place where being wrong is
worst, and it would do it silently.
"""

import difflib

import pytest
from orchestrator.patching import PatchRefused, apply_all, apply_to, parse, reverse

SOURCE = """package com.example;

public class Accounts {
    public static String findByName(Connection db, String name) throws SQLException {
        Statement statement = db.createStatement();
        return statement.executeQuery("select * from users where name = '" + name + "'");
    }
}
"""


def _diff(before: str, after: str, path: str = "Accounts.java") -> str:
    """C3's own diff writer, not a copy of it.

    A local reimplementation would have kept passing when the real one was
    fixed, which is how a test stops testing the thing it is named after.
    """
    from c3.remediate.patch import unified

    return unified(path, before, after)


class TestApplyingWhatC3Produces:
    def test_a_patch_round_trips(self) -> None:
        """The diffs in this system all come from `difflib.unified_diff`, so
        the parser is tested against what really produces them rather than
        against a hand written diff that happens to be well formed."""
        after = SOURCE.replace(
            'return statement.executeQuery("select * from users where name = \'" + name + "\'");',
            'return safeQuery(db, "select * from users where name = ?", name);',
        )

        assert apply_to(SOURCE, _diff(SOURCE, after)) == after

    def test_several_hunks_in_one_file(self) -> None:
        after = SOURCE.replace("Statement statement", "Statement stmt").replace(
            "statement.executeQuery", "stmt.executeQuery"
        )

        assert apply_to(SOURCE, _diff(SOURCE, after)) == after

    def test_a_file_without_a_trailing_newline_keeps_not_having_one(self) -> None:
        before = "a\nb"
        after = "a\nB"

        assert apply_to(before, _diff(before, after)) == after

    def test_windows_line_endings_survive(self) -> None:
        """A patch that quietly converted a file to unix endings would show as
        a whole file change in the next diff a reviewer reads."""
        before = "a\r\nb\r\nc\r\n"
        patched = apply_to(before, "@@ -2,1 +2,1 @@\n-b\n+B\n")

        assert patched == "a\r\nB\r\nc\r\n"


class TestRefusingRatherThanForcing:
    def test_a_file_that_moved_underneath_is_refused(self) -> None:
        """A proposal is made against one code version and applied against
        whatever is current. If the code regenerated in between, the honest
        answer is that the fix has to be proposed again."""
        after = SOURCE.replace("executeQuery", "safeQuery")
        diff = _diff(SOURCE, after)
        moved = SOURCE.replace("Statement statement", "Statement stmt")

        with pytest.raises(PatchRefused) as refused:
            apply_to(moved, diff, path="Accounts.java")

        assert "has to be proposed again" in str(refused.value)

    def test_the_refusal_names_the_line_and_both_sides(self) -> None:
        """A reviewer needs to know the file moved, not merely that something
        went wrong."""
        moved = SOURCE.replace("Statement statement", "Statement stmt")
        after = SOURCE.replace("executeQuery", "safeQuery")

        with pytest.raises(PatchRefused) as refused:
            apply_to(moved, _diff(SOURCE, after), path="Accounts.java")

        message = str(refused.value)
        assert "Statement statement" in message
        assert "Statement stmt" in message

    def test_a_patch_past_the_end_of_the_file_is_refused(self) -> None:
        with pytest.raises(PatchRefused, match="does not have"):
            apply_to("a\n", "@@ -40,1 +40,1 @@\n-x\n+y\n", path="f")

    def test_a_diff_with_no_hunks_is_refused(self) -> None:
        with pytest.raises(PatchRefused, match="no hunks"):
            apply_to(SOURCE, "--- a/f\n+++ b/f\n", path="f")

    def test_a_patch_naming_a_file_that_is_not_there_is_refused(self) -> None:
        with pytest.raises(PatchRefused, match="does not contain"):
            apply_all({"a.java": "x\n"}, [("b.java", "@@ -1,1 +1,1 @@\n-x\n+y\n")])

    def test_one_bad_hunk_applies_none_of_them(self) -> None:
        """A half applied security fix is worse than none: the finding is
        closed in the report and the weakness is still in the file the second
        hunk was meant to reach."""
        files = {"a.java": "x\n", "b.java": "y\n"}

        with pytest.raises(PatchRefused):
            apply_all(
                files,
                [
                    ("a.java", "@@ -1,1 +1,1 @@\n-x\n+X\n"),
                    ("b.java", "@@ -1,1 +1,1 @@\n-nope\n+Y\n"),
                ],
            )

        assert files == {"a.java": "x\n", "b.java": "y\n"}, "the input is untouched"


class TestTheParser:
    def test_it_reads_the_hunks_difflib_writes(self) -> None:
        hunks = parse(_diff(SOURCE, SOURCE.replace("executeQuery", "safeQuery")))

        assert len(hunks) == 1
        assert hunks[0].start > 0

    def test_it_ignores_the_file_headers(self) -> None:
        """The path travels beside the diff on the patch hunk. Trusting the
        `---` line would let a patch name one file and be applied to another."""
        hunks = parse("--- a/x\n+++ b/y\n@@ -1,1 +1,1 @@\n-a\n+b\n")

        assert len(hunks) == 1
        assert hunks[0].lines == ["-a", "+b"]


class TestTakingAKeptRepairBackOut:
    """A kept test repair is undone by its reverse, held to the same exact match.

    Reverting a kept repair has to put the test back as it was written, and a
    file that moved on since must be refused rather than half restored.
    """

    BEFORE = "".join(f"line {number}\n" for number in range(1, 30))
    # A line more in the first hunk, so the second starts on a different line
    # in each file and a reverse that kept the ranges would land in the wrong place.
    AFTER = BEFORE.replace("line 5\n", "line five\nline five and a half\n").replace(
        "line 20\n", "line twenty\n"
    )

    def test_the_reverse_puts_the_file_back(self) -> None:
        diff = _diff(self.BEFORE, self.AFTER)

        assert apply_to(apply_to(self.BEFORE, diff), reverse(diff)) == self.BEFORE

    def test_it_is_the_diff_written_the_other_way(self) -> None:
        """Hunk for hunk what difflib writes from the repaired file back."""
        forward = _diff(self.BEFORE, self.AFTER)
        backward = "".join(
            difflib.unified_diff(
                self.AFTER.splitlines(keepends=True),
                self.BEFORE.splitlines(keepends=True),
                fromfile="b/Accounts.java",
                tofile="a/Accounts.java",
                n=3,
            )
        )

        assert reverse(forward) == backward

    def test_a_file_that_is_not_the_repaired_one_is_refused(self) -> None:
        diff = _diff(self.BEFORE, self.AFTER)

        with pytest.raises(PatchRefused, match="has to be proposed again"):
            apply_to(self.BEFORE, reverse(diff))
