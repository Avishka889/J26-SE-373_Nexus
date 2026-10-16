"""A person's decision about one failing generated test, made in its file.

One wrong model-written test made a project unreleasable: the review refuses
approval while it fails, healing leaves a regression alone, and the generator
keeps every written body word for word. Quarantining it with a reason, or
sending a test that never passed back to be written again, are the two ways on
real teams take, and both have to change exactly that test and nothing else.
"""

import pytest
from c3.generate.decisions import (
    QUARANTINED_BY,
    WRITE_AGAIN_FOR,
    NoSuchTest,
    quarantine,
    restore,
    skipped_names,
    write_again,
)
from c3.generate.fill import declared_names, written_names

SOURCE = """\
import { describe, expect, it } from "vitest";

describe("US-1 Keep a record", () => {
  it("given a record, when saved, then it is listed", async () => {
    expect(await list()).toContain("Buy milk");
  });

  it("given a record, when deleted, then it is gone", async () => {
    expect(await list()).toEqual([]);
  });
});
"""

#: The first test as the runner reports it: the describe and the it, joined.
NAME = "US-1 Keep a record given a record, when saved, then it is listed"
OTHER = "given a record, when deleted, then it is gone"


class TestQuarantine:
    def test_it_skips_that_test_and_says_who_when_and_why_above_it(self) -> None:
        quarantined = quarantine(
            SOURCE, NAME, by="Ana", reason="asserts a title the design dropped", on="2026-10-05"
        )

        assert skipped_names(quarantined) == ["given a record, when saved, then it is listed"]
        assert written_names(quarantined) == [OTHER], "the other test is untouched"
        assert (
            "  // Quarantined by Ana on 2026-10-05: asserts a title the design dropped\n"
            '  it.skip("given a record, when saved, then it is listed", async () => {'
        ) in quarantined

    def test_restoring_it_puts_the_file_back_exactly(self) -> None:
        quarantined = quarantine(SOURCE, NAME, by="Ana", reason="wrong", on="2026-10-05")

        assert restore(quarantined, NAME) == SOURCE

    def test_a_reason_over_several_lines_stays_one_comment(self) -> None:
        quarantined = quarantine(SOURCE, NAME, by="Ana", reason="one\ntwo", on="2026-10-05")

        assert f"{QUARANTINED_BY} Ana on 2026-10-05: one two\n" in quarantined


class TestWriteAgain:
    def test_it_takes_that_test_back_to_a_todo_with_the_reason_above_it(self) -> None:
        again = write_again(SOURCE, NAME, by="Ana", reason="checks the wrong list", on="2026-10-05")

        assert declared_names(again) == ["given a record, when saved, then it is listed"]
        assert written_names(again) == [OTHER]
        assert (
            f"  {WRITE_AGAIN_FOR} Ana on 2026-10-05: checks the wrong list\n"
            '  it.todo("given a record, when saved, then it is listed");\n'
        ) in again
        assert "Buy milk" not in again, "the old body is gone, so the fill writes it afresh"


class TestTheWrongTestIsNeverChanged:
    def test_a_name_the_file_does_not_hold_changes_nothing(self) -> None:
        with pytest.raises(NoSuchTest):
            quarantine(SOURCE, "US-1 Keep a record no such test", by="Ana", reason="x", on="d")

    def test_restoring_a_test_that_is_not_skipped_changes_nothing(self) -> None:
        with pytest.raises(NoSuchTest):
            restore(SOURCE, NAME)


class TestAQuarantinedTestStaysSetAside:
    """The next run carries the file: a skipped test is not missing, so it is
    neither declared again nor written over by a fill."""

    SKELETON = """\
describe("US-1 Keep a record", () => {
  it.todo("given a record, when saved, then it is listed");
  it.todo("given a record, when deleted, then it is gone");
});
"""

    @staticmethod
    def _carried(tmp_path, content: str) -> str:
        from c3.generate.filling import merge_carried
        from c3.harness.targets import TargetRepo

        path = "apps/api/src/__tests__/us-1.criteria.test.ts"
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(content)
        repo = TargetRepo(root=tmp_path, kind="generated", stack="node")
        return merge_carried(repo, {path: TestAQuarantinedTestStaysSetAside.SKELETON})[path].content

    def test_beside_a_written_test_it_stays_skipped(self, tmp_path) -> None:
        quarantined = quarantine(SOURCE, NAME, by="Ana", reason="wrong", on="2026-10-05")

        carried = self._carried(tmp_path, quarantined)

        assert carried == quarantined, "no todo was declared for it, and nothing moved"

    def test_with_every_test_quarantined_the_file_is_still_kept(self, tmp_path) -> None:
        both = quarantine(SOURCE, NAME, by="Ana", reason="wrong", on="2026-10-05")
        both = quarantine(both, "US-1 Keep a record " + OTHER, by="Ana", reason="also", on="d")

        carried = self._carried(tmp_path, both)

        assert skipped_names(carried) == [
            "given a record, when saved, then it is listed",
            OTHER,
        ]
        assert declared_names(carried) == []


class TestOneDecisionMadeInOneFile:
    def test_a_quarantined_test_asked_for_again_is_restored_then_sent_back(self) -> None:
        from c3.generate.decisions import decide

        quarantined = decide(SOURCE, NAME, "quarantined", by="Ana", reason="wrong", on="d")
        assert quarantined is not None

        again = decide(quarantined, NAME, "rewrite", by="Ana", reason="write it", on="d")

        assert again is not None
        assert QUARANTINED_BY not in again
        assert declared_names(again) == ["given a record, when saved, then it is listed"]

    def test_a_test_the_file_does_not_hold_answers_none_rather_than_a_wrong_edit(self) -> None:
        from c3.generate.decisions import decide

        assert (
            decide(SOURCE, "US-1 Keep a record nothing", "quarantined", by="A", reason="x", on="d")
            is None
        )
        assert decide(SOURCE, NAME, "restored", by="A", reason="", on="d") is None


class TestTheFillLeavesAQuarantineAlone:
    """The next run's fill is handed the file with the quarantined test in it."""

    SKELETON = """\
import { describe, expect, it } from "vitest";

describe("US-1 Keep a record", () => {
  // Quarantined by Ana on 2026-10-05: asserts a title the design dropped
  it.skip("given a record, when saved, then it is listed", async () => {
    expect(await list()).toContain("Buy milk");
  });

  it.todo("given a record, when deleted, then it is gone");
});
"""
    BODY = '  it("given a record, when deleted, then it is gone", async () => {\n'
    WRITTEN = BODY + "    expect(await list()).toEqual([]);\n  });"

    @staticmethod
    def _about_the_quarantine(problems: list[str]) -> list[str]:
        return [one for one in problems if "skip" in one or "quarantined" in one]

    def test_a_fill_that_keeps_it_skipped_is_not_refused_for_it(self) -> None:
        from c3.generate.fill import static_problems

        filled = self.SKELETON.replace(
            '  it.todo("given a record, when deleted, then it is gone");', self.WRITTEN
        )

        assert self._about_the_quarantine(static_problems(self.SKELETON, filled)) == []

    def test_a_fill_that_runs_it_again_is_refused(self) -> None:
        from c3.generate.fill import static_problems

        filled = self.SKELETON.replace("it.skip(", "it(").replace(
            '  it.todo("given a record, when deleted, then it is gone");', self.WRITTEN
        )

        assert self._about_the_quarantine(static_problems(self.SKELETON, filled)) == [
            'the test "given a record, when saved, then it is listed" was quarantined by a '
            "person, with the reason above it, and is no longer skipped; leave it and its "
            "comment exactly as they are"
        ]

    def test_a_fill_that_drops_it_is_refused(self) -> None:
        from c3.generate.fill import static_problems

        start = self.SKELETON.index("  // Quarantined")
        stop = self.SKELETON.index("  it.todo(")
        filled = (self.SKELETON[:start] + self.SKELETON[stop:]).replace(
            '  it.todo("given a record, when deleted, then it is gone");', self.WRITTEN
        )

        assert len(self._about_the_quarantine(static_problems(self.SKELETON, filled))) == 1

    def test_a_fill_that_skips_a_test_itself_is_refused(self) -> None:
        from c3.generate.fill import static_problems

        filled = self.SKELETON.replace(
            '  it.todo("given a record, when deleted, then it is gone");',
            self.WRITTEN.replace("it(", "it.skip(", 1),
        )

        assert (
            'the test "given a record, when deleted, then it is gone" is skipped; skip '
            "nothing yourself"
        ) in static_problems(self.SKELETON, filled)


class TestAContractTestKeepsItsQuarantine:
    """Contract tests are written again from the contract on every run."""

    def test_the_quarantine_and_its_note_come_across(self) -> None:
        from c3.generate.decisions import carry_quarantines

        earlier = quarantine(SOURCE, NAME, by="Ana", reason="wrong", on="2026-10-05")

        assert carry_quarantines(earlier, SOURCE) == earlier

    def test_a_test_the_contract_no_longer_asks_for_takes_its_quarantine_with_it(self) -> None:
        from c3.generate.decisions import carry_quarantines

        earlier = quarantine(SOURCE, NAME, by="Ana", reason="wrong", on="2026-10-05")
        fresh = SOURCE.replace("when saved, then it is listed", "when stored, then it shows")

        assert carry_quarantines(earlier, fresh) == fresh

    def test_a_skip_nobody_recorded_a_reason_for_is_not_carried(self) -> None:
        from c3.generate.decisions import carry_quarantines

        earlier = SOURCE.replace(
            'it("given a record, when saved', 'it.skip("given a record, when saved'
        )

        assert carry_quarantines(earlier, SOURCE) == SOURCE


class TestARequestToWriteATestAgainIsAnswered:
    def test_once_the_test_is_written_the_request_goes(self) -> None:
        from c3.generate.decisions import answered

        again = write_again(SOURCE, NAME, by="Ana", reason="checks the wrong list", on="d")
        filled = again.replace(
            'it.todo("given a record, when saved, then it is listed");',
            'it("given a record, when saved, then it is listed", async () => {\n'
            '    expect(await list()).toContain("Buy bread");\n  });',
        )

        assert WRITE_AGAIN_FOR not in answered(filled)
        assert 'toContain("Buy bread")' in answered(filled)

    def test_while_it_is_still_a_todo_the_request_stays(self) -> None:
        from c3.generate.decisions import answered

        again = write_again(SOURCE, NAME, by="Ana", reason="checks the wrong list", on="d")

        assert answered(again) == again


class TestATestSentBackKeepsItsReason:
    """The next run's fill answers the reviewer's reason, so the file has to
    reach it with the reason still above the todo."""

    ONE = """\
import { describe, expect, it } from "vitest";

describe("US-1 Keep a record", () => {
  it("given a record, when saved, then it is listed", async () => {
    expect(await list()).toContain("Buy milk");
  });
});
"""

    def test_a_file_whose_only_test_was_sent_back_is_carried_with_the_reason(
        self, tmp_path
    ) -> None:
        again = write_again(self.ONE, NAME, by="Ana", reason="checks the wrong list", on="d")

        carried = TestAQuarantinedTestStaysSetAside._carried(tmp_path, again)

        assert f"{WRITE_AGAIN_FOR} Ana on d: checks the wrong list" in carried
        assert declared_names(carried) == [
            "given a record, when saved, then it is listed",
            OTHER,
        ]
