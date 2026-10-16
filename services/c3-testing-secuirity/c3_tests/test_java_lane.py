"""The Java lane: surefire, JaCoCo and PIT, read the way the node lane is read.

Same split as the MERN lane. The parsers run against files the real tools
wrote, so they are fast and still fail when a tool changes shape; the lane
itself runs behind the `sandbox` marker, where the claim that a Maven Wrapper
build actually works is settled.

The Java lane's first end to end run is why `LaneRun.green` exists: it could
not find `./mvnw`, reported no suites at all, and the caller two lines later
called that green and asked for a mutation pass. `all()` over nothing is true.
"""

from pathlib import Path

import pytest
from c3.harness import Sandbox, resolve, stage_copy
from c3.harness import java_lane as lane
from c3.harness.targets import TargetRepo

from . import jdk
from .test_targets import Ref

GOLDEN = Path(__file__).parent / "golden" / "java"

# Version aware, not presence aware. CI had a JDK and it was 17, the sample
# compiles at 21, so nothing skipped and four tests failed inside Maven.
needs_jdk = jdk.needs_jdk


@pytest.fixture
def repo() -> TargetRepo:
    return TargetRepo(root=Path("/workspace"), kind="sample", stack="java", apps=(".",))


def golden(name: str) -> str:
    return (GOLDEN / name).read_text()


class TestReadingWhatSurefireWrote:
    def test_the_cases_come_back_with_the_outcomes_they_had(self, repo) -> None:
        suites = lane.parse_surefire(golden("surefire-TotalsTest.xml"), repo)

        assert len(suites) == 1
        outcomes = sorted(case.outcome for case in suites[0].cases)
        assert outcomes == ["passed", "passed", "passed", "passed", "skipped"]

    def test_a_suite_is_named_by_its_file_and_not_by_its_class(self, repo) -> None:
        """Surefire names a class; every other path in a test report names a
        file, and a reader following the report has to find it."""
        suite = lane.parse_surefire(golden("surefire-TotalsTest.xml"), repo)[0]

        assert suite.path == "src/test/java/com/example/records/TotalsTest.java"
        assert suite.framework == "junit5"

    def test_a_disabled_case_is_skipped_and_never_passed(self, repo) -> None:
        suite = lane.parse_surefire(golden("surefire-TotalsTest.xml"), repo)[0]
        skipped = [case for case in suite.cases if case.outcome == "skipped"]

        assert len(skipped) == 1
        assert "another_currency" in skipped[0].name

    def test_a_failure_carries_its_message(self, repo) -> None:
        raw = (
            '<testsuite name="com.example.records.TotalsTest">'
            '<testcase classname="com.example.records.TotalsTest" name="adds" time="0.01">'
            '<failure message="expected: &lt;667&gt; but was: &lt;670&gt;" '
            'type="org.opentest4j.AssertionFailedError"/>'
            "</testcase></testsuite>"
        )

        case = lane.parse_surefire(raw, repo)[0].cases[0]

        assert case.outcome == "failed"
        assert "667" in case.message

    def test_an_error_is_not_a_failure(self, repo) -> None:
        """A test that threw before it could assert is a different fact from a
        test whose assertion did not hold, and the report keeps both."""
        raw = (
            '<testsuite name="com.example.records.TotalsTest">'
            '<testcase classname="com.example.records.TotalsTest" name="reads">'
            '<error message="java.io.IOException: no such file"/>'
            "</testcase></testsuite>"
        )

        assert lane.parse_surefire(raw, repo)[0].cases[0].outcome == "errored"


class TestReadingTheCoverage:
    def test_every_source_file_is_reported_even_at_zero(self, repo) -> None:
        """The seeded classes have no tests at all. A coverage report that only
        listed what was touched would make the untouched half invisible, which
        is the half a reader most needs to see."""
        entries = {entry.module: entry for entry in lane.parse_jacoco(golden("jacoco.xml"), repo)}

        assert "src/main/java/com/example/records/Accounts.java" in entries
        assert entries["src/main/java/com/example/records/Accounts.java"].lines_covered == 0
        assert entries["src/main/java/com/example/records/Totals.java"].lines_covered > 0

    def test_the_total_is_the_sum_of_missed_and_covered(self, repo) -> None:
        """JaCoCo reports what it missed; the contract wants the total."""
        entry = next(
            entry
            for entry in lane.parse_jacoco(golden("jacoco.xml"), repo)
            if entry.module.endswith("Totals.java")
        )

        assert entry.lines_total > entry.lines_covered
        assert entry.branches_total >= entry.branches_covered


class TestReadingTheMutants:
    def test_two_mutants_on_one_line_stay_two(self, repo) -> None:
        """PIT puts several mutants of the same mutator on one line, and the
        sample alone has five such pairs. Without PIT's own index they would
        collapse into one another in a set, and the score would move."""
        result = lane.parse_pit(
            golden("mutations.xml"),
            repo,
            scope=["src/main/java/com/example/records/Totals.java"],
            duration=63.39,
        )
        every = result.killed + result.survived + result.inconclusive

        assert len(every) == len(set(every))
        assert result.total == len(every)

    def test_the_statuses_are_sorted_the_way_pit_scores_them(self) -> None:
        """A timeout is a detected mutant; nothing covering it is a survivor;
        a mutant that would not run is neither."""
        raw = (
            "<mutations>"
            + "".join(
                f'<mutation detected="true" status="{status}">'
                f"<mutatedClass>com.example.A</mutatedClass><lineNumber>{line}</lineNumber>"
                "<mutator>org.pitest.M</mutator><indexes><index>1</index></indexes>"
                "</mutation>"
                for line, status in enumerate(
                    ["KILLED", "TIMED_OUT", "SURVIVED", "NO_COVERAGE", "NON_VIABLE"], start=1
                )
            )
            + "</mutations>"
        )
        repo = TargetRepo(root=Path("/workspace"), kind="sample", stack="java")

        result = lane.parse_pit(raw, repo, scope=["src/main/java/com/example/A.java"], duration=0.0)

        assert (len(result.killed), len(result.survived), len(result.inconclusive)) == (2, 2, 1)
        assert result.score == 50.0

    def test_a_mutant_names_a_file_a_reader_can_open(self, repo) -> None:
        result = lane.parse_pit(
            golden("mutations.xml"),
            repo,
            scope=["src/main/java/com/example/records/Totals.java"],
            duration=1.0,
        )

        assert all(
            mutant.startswith("src/main/java/com/example/records/Totals.java:")
            for mutant in result.survived + result.killed
        )


class TestTheNamingConvention:
    def test_a_class_and_its_file_are_the_same_thing_read_two_ways(self) -> None:
        path = "src/main/java/com/example/records/Totals.java"

        assert lane.class_name(path) == "com.example.records.Totals"
        assert lane.source_path("com.example.records.Totals", test=False) == path

    def test_an_inner_class_belongs_to_its_outer_file(self) -> None:
        assert (
            lane.source_path("com.example.records.Totals$Line", test=False)
            == "src/main/java/com/example/records/Totals.java"
        )

    def test_something_that_is_not_java_source_is_not_a_class(self) -> None:
        """So a scope holding a TypeScript file does not become a
        `targetClasses` entry PIT would refuse."""
        assert lane.class_name("apps/web/src/total.ts") == ""


class TestWhatTheLaneRefusesToMeasure:
    def test_mutation_does_not_start_on_a_red_suite(self, repo) -> None:
        outcome = lane.run_mutation(
            repo,
            Sandbox(repo.root),
            ["src/main/java/com/example/records/Totals.java"],
            suite_is_green=False,
        )

        assert (outcome.step.outcome, outcome.result) == ("not-run", None)
        assert "green test red" in outcome.skipped_reason

    def test_a_scope_with_no_java_in_it_is_said_rather_than_scored(self, repo) -> None:
        outcome = lane.run_mutation(
            repo, Sandbox(repo.root), ["apps/web/src/total.ts"], suite_is_green=True
        )

        assert (outcome.step.outcome, outcome.result) == ("not-run", None)
        assert "no Java classes" in outcome.skipped_reason


class TestARunThatNeverStartedIsNotGreen:
    def test_no_suites_is_not_a_clean_bill_of_health(self) -> None:
        """The bug this exists to stop, found in this lane's first real run:
        the wrapper could not be found, no suite was reported, and `all()` over
        an empty list said the suite was green."""
        from c3.harness.report import LaneRun

        empty = LaneRun()

        assert not empty.ran
        assert not empty.green


@pytest.mark.sandbox
@needs_jdk
class TestTheLaneAgainstARealRepository:
    def test_it_builds_tests_covers_and_mutates(self, tmp_path) -> None:
        repo = stage_copy(resolve(Ref(kind="sample", path="java-sample")), tmp_path / "ws")
        box = Sandbox(repo.root)

        run = lane.build_and_test(repo, box)

        assert run.ran, run.steps[0].tail
        assert run.green
        covered = {entry.module: entry for entry in run.coverage}
        assert covered["src/main/java/com/example/records/Totals.java"].lines_covered > 0
        # The seeded classes are never called, and the report says so rather
        # than leaving them out.
        assert covered["src/main/java/com/example/records/Accounts.java"].lines_covered == 0

        outcome = lane.run_mutation(
            repo, box, ["src/main/java/com/example/records/Totals.java"], suite_is_green=run.green
        )

        assert outcome.result is not None, f"{outcome.step.outcome}: {outcome.skipped_reason}"
        mutation = outcome.result
        assert mutation.killed and mutation.survived
        assert 0 < mutation.score < 100
