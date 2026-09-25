"""Which test killed which mutant, and what that says about the test.

The question a pass rate cannot answer and the source catalogue cannot see:
this test ran that code, would it have noticed if the code were wrong. A test
that covers mutants and kills none is watching nothing, which is the hole the
honesty guard closes at repair time seen from the other end.

Every case here runs against a report a real tool wrote. That matters more than
usual: the rule is only sound if the runner was asked not to stop at the first
kill, and the first version of this file, written against a report where it had
not been, called a perfectly good test weak.
"""

import json
from pathlib import Path

from c3 import quality
from c3.detection import Candidate, DetectionResult, sites
from c3.harness import java_lane, node_lane
from c3.harness.report import TestKills
from c3.harness.targets import TargetRepo
from sdlc_contracts import DetectorRun, MutationResult, TestCase, TestSuite

GOLDEN = Path(__file__).parent / "golden"


def _node_repo() -> TargetRepo:
    return TargetRepo(root=Path("/workspace"), kind="sample", stack="node", apps=("apps/web",))


def _golden(lane: str, name: str) -> str:
    return (GOLDEN / lane / name).read_text()


class TestReadingWhoKilledWhat:
    def test_the_node_runner_names_the_tests_the_report_names(self) -> None:
        """The ids have to be the report's own case ids, or a finding points at
        a test the reader cannot find."""
        raw = _golden("node", "mutation.json")
        repo = _node_repo()

        found = node_lane.attribution(raw, repo, app="apps/web")

        assert found
        assert all(name.startswith("apps/web/src/__tests__/") for name in found)
        suites = node_lane.parse_vitest(_golden("node", "vitest.json"), repo)
        case_ids = {case.id for suite in suites for case in suite.cases}
        assert set(found) <= case_ids, "every attributed test should be a case in the report"

    def test_the_java_runner_names_the_tests_the_report_names(self) -> None:
        raw = _golden("java", "mutations.xml")

        found = java_lane.attribution(raw)

        assert found
        assert all("#" in name for name in found)
        suites = java_lane.parse_surefire(_golden("java", "surefire-TotalsTest.xml"), None)
        case_ids = {case.id for suite in suites for case in suite.cases}
        assert set(found) <= case_ids

    def test_a_test_gets_credit_for_every_mutant_it_kills(self) -> None:
        """Not just the ones it killed first. This is what `--disableBail` and
        `fullMutationMatrix` are for, and without them the rule below misfires.
        """
        found = node_lane.attribution(
            _golden("node", "mutation.json"), _node_repo(), app="apps/web"
        )
        killers = [name for name, kills in found.items() if kills.killed]

        assert len(killers) > 1, (
            "more than one test should have kill credit; if only one does, the "
            "runner stopped at the first kill and the attribution is an artefact "
            "of test ordering"
        )


class TestTheRule:
    def test_covering_nothing_is_not_weak(self) -> None:
        """The mutation run is scoped. A test exercising code outside that
        scope was never asked the question, and accusing it would be reporting
        an absence of evidence as evidence."""
        assert not TestKills().weak
        assert not TestKills(covered=(), killed=()).weak

    def test_covering_and_killing_is_not_weak(self) -> None:
        assert not TestKills(covered=("a", "b"), killed=("a",)).weak

    def test_covering_and_killing_nothing_is_weak(self) -> None:
        assert TestKills(covered=("a", "b"), killed=()).weak

    def test_the_finding_names_the_mutant_that_lived(self) -> None:
        """A reader wants to go and look at it, and a refill has nothing to aim
        at without it."""
        suites = [
            TestSuite(
                path="apps/web/src/a.test.ts",
                framework="vitest",
                cases=[TestCase(id="c1", name="watches nothing", outcome="passed")],
            )
        ]
        attribution = {"c1": TestKills(covered=("apps/web/src/a.ts:4:1:Arithmetic",), killed=())}

        found = quality.mutant_findings(suites, attribution)

        assert [finding.rule for finding in found] == ["kills-no-mutant"]
        assert "apps/web/src/a.ts:4:1:Arithmetic" in found[0].detail
        assert found[0].observed, "this one needed a run, and the report says so"

    def test_a_test_nothing_measured_produces_no_finding(self) -> None:
        suites = [
            TestSuite(
                path="apps/web/src/a.test.ts",
                framework="vitest",
                cases=[TestCase(id="c1", name="outside the scope", outcome="passed")],
            )
        ]

        assert quality.mutant_findings(suites, {}) == []


class TestAgainstWhatTheToolsReallyWrote:
    def test_the_java_sample_has_a_test_that_cannot_fail(self) -> None:
        """A true positive, from the real PIT matrix.

        `an_empty_order_is_worth_nothing` asserts `total(List.of()) == 0`. The
        one mutant it covers replaces the return with a constant 0, so the test
        passes on the mutant and on the real code alike: it cannot tell a
        correct sum of nothing from a function that always answers zero.
        """
        found = java_lane.attribution(_golden("java", "mutations.xml"))
        weak = sorted(name for name, kills in found.items() if kills.weak)

        assert weak == ["com.example.records.TotalsTest#an_empty_order_is_worth_nothing"]
        covered = found[weak[0]].covered
        assert len(covered) == 1
        assert "PrimitiveReturnsMutator" in covered[0]

    def test_the_node_sample_has_none_now_that_credit_is_complete(self) -> None:
        """The false positive this file exists to remember.

        Captured with bail on, `total is zero for an empty basket` covered two
        mutants and killed none, because another test killed them first and
        Stryker stopped. It asserts a specific value and would certainly fail
        on a mutant; it was never weak. With `--disableBail` it has kill credit
        and the rule leaves it alone.
        """
        repo = _node_repo()
        found = node_lane.attribution(_golden("node", "mutation.json"), repo, app="apps/web")
        empty_basket = next(name for name in found if "empty basket" in name)

        assert found[empty_basket].killed, (
            "this test kills at least one mutant; if it does not, the golden was "
            "captured with bail on and every rule built on it is measuring test order"
        )
        assert not found[empty_basket].weak

    def test_the_node_golden_was_captured_without_bail(self) -> None:
        """Stated by the report itself, so a re-capture that loses the flag
        fails here rather than quietly changing every number below it."""
        report = json.loads(_golden("node", "mutation.json"))

        assert (report.get("config") or {}).get("disableBail") is True

    def test_the_rule_misfires_on_a_report_captured_with_bail(self) -> None:
        """Kept as evidence, because the flag that prevents this is one word in
        a command line and nothing else would show why it is there.

        `mutation-with-bail.json` is a real Stryker report over the same fixture
        with `disableBail` off. `total is zero for an empty basket` covered two
        mutants and killed none, because another test killed them first and the
        runner stopped. It asserts a specific value; it was never weak.
        """
        repo = _node_repo()
        with_bail = node_lane.attribution(
            _golden("node", "mutation-with-bail.json"), repo, app="apps/web"
        )
        without_bail = node_lane.attribution(_golden("node", "mutation.json"), repo, app="apps/web")

        accused = {name.split("::")[-1] for name, kills in with_bail.items() if kills.weak}
        assert accused == {"total is zero for an empty basket"}
        assert not any(kills.weak for kills in without_bail.values())

    def test_the_java_golden_carries_the_full_matrix(self) -> None:
        """`coveringTests` only appears when PIT is asked for the matrix, and
        without it nothing here can be answered."""
        raw = _golden("java", "mutations.xml")

        assert "<coveringTests>" in raw
        assert "<killingTests>" in raw


class TestWhenTheRunnerItselfIsBroken:
    """A mutation run that killed nothing is not a suite that deserves it.

    Found by doing it: moving the node sample to vitest 5 left Stryker 10's
    runner reporting a green suite, seventeen of twenty one mutants uncovered
    and a score of zero, and the rule promptly accused both tests in the
    fixture. The tests were fine; the runner never activated a mutant.
    """

    def test_a_run_that_killed_nothing_accuses_nobody(self) -> None:
        usable, why = quality.attribution_is_usable(
            MutationResult(tool="stryker", scope=["a.ts"], killed=[], survived=["m1", "m2"])
        )

        assert not usable
        assert "never activated a mutant" in why

    def test_no_run_at_all_says_that_instead(self) -> None:
        """Two different silences, and a reader acts differently on each."""
        usable, why = quality.attribution_is_usable(None)

        assert not usable
        assert "no mutation run" in why

    def test_a_run_that_killed_something_is_believed(self) -> None:
        usable, why = quality.attribution_is_usable(
            MutationResult(tool="stryker", scope=["a.ts"], killed=["m1"], survived=["m2"])
        )

        assert usable and why == ""


class TestTheCountsPerArm:
    def test_it_reports_weak_against_measured_for_each_origin(self) -> None:
        """Three weak out of four measured is not three weak out of forty, and
        a number about the model is not a number about the code generator."""
        suites = [
            TestSuite(
                path="apps/web/src/a.test.ts",
                framework="vitest",
                cases=[
                    TestCase(id="c1", name="filled and weak", outcome="passed", origin="filled"),
                    TestCase(id="c2", name="filled and fine", outcome="passed", origin="filled"),
                    TestCase(id="c3", name="theirs and weak", outcome="passed", origin="upstream"),
                    TestCase(id="c4", name="never measured", outcome="passed", origin="skeleton"),
                ],
            )
        ]
        attribution = {
            "c1": TestKills(covered=("m1",), killed=()),
            "c2": TestKills(covered=("m1",), killed=("m1",)),
            "c3": TestKills(covered=("m2",), killed=()),
            "c4": TestKills(),
        }

        counts = quality.weak_by_origin(suites, attribution)

        assert counts == {
            "filled measured": 2,
            "filled weak": 1,
            "upstream measured": 1,
            "upstream weak": 1,
        }
        assert "skeleton measured" not in counts, "a test nothing measured is not a denominator"


class TestArmsAgreeBySpanRatherThanByLine:
    """The security pillar's claim is that confidence comes from independent
    arms agreeing, and no detector scores itself. Keyed on an exact start line,
    they essentially never agreed: the first live three arm run found one
    injection at lines 33 to 39, 34 and 36 of one file, recorded three findings
    at the lowest confidence each, and merged one of seventeen.
    """

    @staticmethod
    def _result(arm, cwe, start, end, *, path="Accounts.java"):
        return DetectionResult(
            candidates=[
                Candidate(cwe=cwe, title="a weakness", path=path, start_line=start, end_line=end)
            ],
            run=DetectorRun(
                arm=arm,
                model_id=f"{arm}-1",
                started_at="2026-09-25 10:00",
                duration_seconds=1.0,
                offline=arm == "trained",
                files_scanned=1,
            ),
        )

    def test_a_line_inside_another_arms_span_is_the_same_weakness(self) -> None:
        found = sites(
            [
                self._result("trained", "CWE-89", 33, 39),
                self._result("llm", "CWE-89", 34, 34),
                self._result("scanner", "CWE-89", 36, 36),
            ]
        )

        assert len(found) == 1, "one injection, seen three ways"
        assert found[0].arms == ["scanner", "llm", "trained"]

    def test_the_narrowest_span_is_the_evidence(self) -> None:
        """A statement beats a method, whoever produced it: a reader asked to
        confirm a seven line range is being asked to trust most of it."""
        found = sites(
            [
                self._result("trained", "CWE-89", 33, 39),
                self._result("scanner", "CWE-89", 36, 36),
            ]
        )

        assert (found[0].candidate.start_line, found[0].candidate.end_line) == (36, 36)

    def test_spans_that_do_not_touch_stay_apart(self) -> None:
        """Two real weaknesses of one class in one file are two findings."""
        found = sites(
            [
                self._result("scanner", "CWE-89", 10, 10),
                self._result("scanner", "CWE-89", 80, 80),
            ]
        )

        assert len(found) == 2

    def test_a_different_class_at_the_same_place_is_a_different_weakness(self) -> None:
        found = sites(
            [
                self._result("scanner", "CWE-89", 36, 36),
                self._result("llm", "CWE-78", 36, 36),
            ]
        )

        assert len(found) == 2

    def test_a_different_file_never_merges(self) -> None:
        found = sites(
            [
                self._result("scanner", "CWE-89", 36, 36, path="A.java"),
                self._result("llm", "CWE-89", 36, 36, path="B.java"),
            ]
        )

        assert len(found) == 2

    def test_one_arm_twice_is_still_one_arm(self) -> None:
        """Agreement is between arms, not between a chatty arm and itself."""
        found = sites(
            [
                DetectionResult(
                    candidates=[
                        Candidate(
                            cwe="CWE-89", title="a", path="A.java", start_line=33, end_line=39
                        ),
                        Candidate(
                            cwe="CWE-89", title="a", path="A.java", start_line=36, end_line=36
                        ),
                    ],
                    run=DetectorRun(
                        arm="llm",
                        model_id="m",
                        started_at="2026-09-25 10:00",
                        duration_seconds=1.0,
                        offline=False,
                        files_scanned=1,
                    ),
                )
            ]
        )

        assert len(found) == 1
        assert found[0].arms == ["llm"]
