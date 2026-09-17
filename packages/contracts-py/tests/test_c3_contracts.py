"""The C3 contracts refuse dishonest shapes, and the arithmetic is checkable.

Contract tests, not producer tests: each one plants a shape a lazy or a
flattering producer might emit and asserts the model refuses it, because the
validator is the last line before a number that is not true gets stored and
later printed in a dissertation.

Three of these carry more weight than the rest. The CVSS scores are checked
against published CVEs, because "severity is rule based" is a claim this
project makes and a wrong formula would make it a false one. The honesty
guard's acceptance is checked to be a conjunction that cannot be short
circuited, because that conjunction is the contribution. And the naive versus
strict convergence gap is checked to be visible, because the gap is the result.
"""

from datetime import UTC, datetime
from typing import ClassVar

import pytest
from pydantic import ValidationError
from sdlc_contracts import (
    ClassificationEvidence,
    CountedFact,
    CoverageEntry,
    CvssFactors,
    DiffSpan,
    EvidenceSpan,
    FixShipsWith,
    GuardCheck,
    HealAttempt,
    HealReport,
    MutationResult,
    PatchHunk,
    RemediationProposal,
    Reverification,
    RiskAssessment,
    SecurityFinding,
    TestCase,
    TestGap,
    TestReport,
    TestSuite,
    TestSummary,
    TestTrace,
    ValidationReport,
    VerificationSnapshot,
    cvss_base_score,
    severity_of,
    still_raised,
    with_standing,
    with_traces_from,
)


def _now() -> datetime:
    return datetime.now(UTC)


def _report(**overrides) -> TestReport:
    base = dict(
        version=1,
        generated_at=_now(),
        target="calculator MERN",
        isolation="a subprocess in a temporary directory",
        mutation_skipped_reason="not requested",
    )
    return TestReport(**{**base, **overrides})


class TestTheTestReport:
    def test_the_counts_are_derived_and_cannot_be_authored(self) -> None:
        """A stored total is a number that starts disagreeing with its source.

        The counts are computed from the cases, and a producer that supplies
        one has it discarded: what comes back is derived from the evidence,
        never the number that was offered. Offering one is not itself an error,
        because a derived key is exactly what a stored artefact carries and the
        report has to be readable again after it is written.
        """
        report = _report(
            suites=[
                TestSuite(
                    path="a.test.ts",
                    framework="vitest",
                    cases=[
                        TestCase(id="1", name="adds", outcome="passed"),
                        TestCase(id="2", name="divides", outcome="failed", message="boom"),
                    ],
                )
            ],
        )
        assert report.total == 2
        assert report.passed == 1 and report.failed == 1

        flattering = _report(
            suites=report.suites,
            total=999,  # type: ignore[call-arg]
            passed=999,  # type: ignore[call-arg]
        )
        assert flattering.total == 2
        assert flattering.passed == 1

    def test_a_written_report_can_be_read_back(self) -> None:
        """The stage after this one reads what this one stored.

        Three stages write `test-report` and two of them read it first, so a
        dump that cannot be validated again would have broken the phase rather
        than one model. It did, once: the quality stage failed with one "Extra
        inputs are not permitted" per derived count.
        """
        report = _report(
            suites=[
                TestSuite(
                    path="a.test.ts",
                    framework="vitest",
                    cases=[TestCase(id="1", name="adds", outcome="not-run")],
                )
            ],
        )
        body = report.model_dump(by_alias=True, mode="json")

        again = TestReport.model_validate(body)

        assert again.model_dump(by_alias=True, mode="json") == body
        # And the drop is scoped to derived keys: a key the contract does not
        # declare at all is still a contract violation.
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            TestReport.model_validate({**body, "flakiness": 0.2})

    def test_a_trace_names_the_criterion_by_id_and_not_by_position(self) -> None:
        """The last positional reference in a trace, and the reason it went.

        A test outlives the design version it was written against, which is the
        healing loop's premise. An index into the story's `acceptance` list does
        not survive that: insert a criterion ahead of another and index 0 names
        something else, so a preserved test traces to a criterion it was never
        written from. C1's criterion ids are carried across design versions and
        never reissued.
        """
        trace = TestTrace(storyId="US-4", criterionId="AC-4-2", requirementIds=["R-1"])

        assert trace.model_dump(by_alias=True)["criterionId"] == "AC-4-2"
        assert not trace.is_empty
        # A trace with only a criterion has still told us something.
        assert not TestTrace(criterionId="AC-4-2").is_empty
        assert TestTrace().is_empty

    def test_a_report_stored_before_the_criterion_had_an_id_still_reads(self) -> None:
        """`extra="forbid"` would otherwise refuse the artefact over a key this
        contract used to declare, and the project would stop opening.

        Dropped rather than converted: turning an index into an id needs the
        sprint plan the test was written against, and the answer would be a guess
        at exactly the thing that turned out not to be reliable. So the older
        report loads with no criterion in its trace, which is true. It recorded a
        position, and this platform no longer trusts one.
        """
        stored = {
            "storyId": "US-4",
            "criterionIndex": 1,
            "requirementIds": ["R-1"],
            "endpointId": "",
        }

        trace = TestTrace.model_validate(stored)

        assert trace.story_id == "US-4"
        assert trace.criterion_id == ""
        assert trace.requirement_ids == ["R-1"]
        # And the drop is scoped to that one retired key.
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            TestTrace.model_validate({**stored, "criterionOrdinal": 1})

    def test_a_report_says_how_many_of_its_own_tests_trace_to_nothing(self) -> None:
        """The count that makes an absence of evidence visible.

        A report full of untraced cases is one the healing classifier can say
        nothing about: every failure comes back `undecided`, which reads like
        caution. Upstream tests are excluded, because they came with the
        repository and were written from nothing this platform holds, so counting
        them would make the number describe the target rather than the platform.
        """
        report = _report(
            suites=[
                TestSuite(
                    path="a.test.ts",
                    framework="vitest",
                    cases=[
                        TestCase(
                            id="1",
                            name="traced",
                            outcome="passed",
                            origin="filled",
                            traces=TestTrace(storyId="US-1", criterionId="AC-1-1"),
                        ),
                        TestCase(id="2", name="not traced", outcome="passed", origin="filled"),
                        TestCase(id="3", name="theirs", outcome="passed", origin="upstream"),
                    ],
                )
            ],
        )

        assert report.untraced == 1
        assert report.total == 3

    def test_an_executed_report_is_given_back_the_traces_the_generator_wrote(self) -> None:
        """Two reports describe the same tests and neither is complete alone.

        The generation stage's says what each test was written from, because the
        rules that wrote it knew. The run stage's says what each did, because the
        runner reported it. The run stage used to replace the first with the
        second at the same artefact version, so the traces were not merely absent
        from the result, they were destroyed, and the classifier answered
        `undecided` on every real failure for want of them.
        """
        declared = _report(
            suites=[
                TestSuite(
                    path="a.test.ts",
                    framework="vitest",
                    cases=[
                        TestCase(
                            id="a.test.ts::US-1 AC-1-1: adds",
                            name="US-1 AC-1-1: adds",
                            outcome="not-run",
                            origin="skeleton",
                            traces=TestTrace(
                                storyId="US-1", criterionId="AC-1-1", requirementIds=["R-2"]
                            ),
                        )
                    ],
                )
            ],
        )
        executed = _report(
            suites=[
                TestSuite(
                    path="a.test.ts",
                    framework="vitest",
                    cases=[
                        TestCase(
                            id="a.test.ts::US-1 AC-1-1: adds",
                            name="US-1 AC-1-1: adds",
                            outcome="failed",
                            origin="skeleton",
                            message="expected 3 to be 4",
                        ),
                        # Came with the repository, so there is nothing to
                        # attach and it must not be handed a neighbour's trace.
                        TestCase(
                            id="a.test.ts::theirs",
                            name="theirs",
                            outcome="passed",
                            origin="upstream",
                        ),
                    ],
                )
            ],
        )
        assert executed.untraced == 1, "the runner's report cannot know any of this"

        merged = with_traces_from(executed, declared)

        cases = {case.id: case for case in merged.cases}
        assert cases["a.test.ts::US-1 AC-1-1: adds"].traces.criterion_id == "AC-1-1"
        assert cases["a.test.ts::US-1 AC-1-1: adds"].traces.requirement_ids == ["R-2"]
        assert cases["a.test.ts::theirs"].traces.is_empty
        assert merged.untraced == 0
        # What ran is the executed report's to say, so nothing is added and
        # nothing is dropped: inventing a case here is the same mistake in the
        # other direction.
        assert merged.total == executed.total
        assert cases["a.test.ts::US-1 AC-1-1: adds"].outcome == "failed"

    def test_not_run_is_not_skipped_and_neither_is_passed(self) -> None:
        """The distinction this whole component exists to keep.

        A framework skipping a test and a run never reaching it are different
        facts, and neither is a pass.
        """
        report = _report(
            suites=[
                TestSuite(
                    path="a.test.ts",
                    framework="vitest",
                    cases=[
                        TestCase(id="1", name="a", outcome="skipped"),
                        TestCase(id="2", name="b", outcome="not-run"),
                    ],
                )
            ]
        )
        assert (report.passed, report.skipped, report.not_run) == (0, 1, 1)

    def test_a_failure_without_a_message_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="failed without a message"):
            TestCase(id="1", name="a", outcome="failed")

    def test_coverage_is_weighted_by_lines_not_averaged(self) -> None:
        """Averaging percentages weights a ten line module like a thousand line
        one, which is how a coverage number ends up describing nothing."""
        report = _report(
            coverage=[
                CoverageEntry(module="small", lines_covered=8, lines_total=10),
                CoverageEntry(module="large", lines_covered=90, lines_total=1000),
            ]
        )
        assert report.line_coverage == 9.7  # not the mean of 80.0 and 9.0

    def test_more_covered_than_exist_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="more lines covered than exist"):
            CoverageEntry(module="m", lines_covered=11, lines_total=10)

    def test_an_absent_mutation_run_must_say_why(self) -> None:
        """Silence reads as a score of zero, and zero is a real result."""
        with pytest.raises(ValidationError, match="does not say why"):
            TestReport(
                version=1,
                generated_at=_now(),
                target="t",
                isolation="a subprocess",
            )

    def test_inconclusive_mutants_are_not_counted_as_survivors(self) -> None:
        """A mutant that could not be evaluated is not evidence a test missed
        it, so it leaves the denominator rather than lowering the score."""
        mutation = MutationResult(
            tool="stryker",
            scope=["src/calc.ts"],
            killed=["m1", "m2"],
            survived=["m3"],
            inconclusive=["m4", "m5"],
        )
        assert mutation.total == 5
        assert mutation.score == 66.67  # 2 of 3 decided, not 2 of 5

    def test_the_mutated_scope_travels_with_the_score(self) -> None:
        """A mutation score means nothing without the set it was measured over,
        and this run deliberately measures a narrow one."""
        with pytest.raises(ValidationError):
            MutationResult(tool="pit", scope=[], killed=["m1"])


class TestTheCvssArithmetic:
    """Severity is computed, and computed correctly.

    Published CVEs rather than invented vectors: an expected value somebody
    made up proves the code agrees with them, not with CVSS.
    """

    @pytest.mark.parametrize(
        ("name", "metrics", "expected", "band"),
        [
            (
                "CVE-2021-44228 Log4Shell",
                dict(
                    attack_vector="N",
                    attack_complexity="L",
                    privileges_required="N",
                    user_interaction="N",
                    scope="C",
                    confidentiality="H",
                    integrity="H",
                    availability="H",
                ),
                10.0,
                "critical",
            ),
            (
                "CVE-2019-0708 BlueKeep",
                dict(
                    attack_vector="N",
                    attack_complexity="L",
                    privileges_required="N",
                    user_interaction="N",
                    scope="U",
                    confidentiality="H",
                    integrity="H",
                    availability="H",
                ),
                9.8,
                "critical",
            ),
            (
                "CVE-2014-0160 Heartbleed",
                dict(
                    attack_vector="N",
                    attack_complexity="L",
                    privileges_required="N",
                    user_interaction="N",
                    scope="U",
                    confidentiality="H",
                    integrity="N",
                    availability="N",
                ),
                7.5,
                "high",
            ),
            (
                "reflected XSS, scope changed",
                dict(
                    attack_vector="N",
                    attack_complexity="L",
                    privileges_required="N",
                    user_interaction="R",
                    scope="C",
                    confidentiality="L",
                    integrity="L",
                    availability="N",
                ),
                6.1,
                "medium",
            ),
            (
                "no impact at all",
                dict(
                    attack_vector="N",
                    attack_complexity="L",
                    privileges_required="N",
                    user_interaction="N",
                    scope="U",
                    confidentiality="N",
                    integrity="N",
                    availability="N",
                ),
                0.0,
                "none",
            ),
        ],
    )
    def test_published_vectors_score_as_published(self, name, metrics, expected, band) -> None:
        factors = CvssFactors(**metrics)
        assert cvss_base_score(factors) == expected, name
        assert severity_of(expected) == band

    def test_the_vector_string_round_trips_the_metrics(self) -> None:
        factors = CvssFactors(
            attack_vector="N",
            attack_complexity="L",
            privileges_required="N",
            user_interaction="N",
            scope="U",
            confidentiality="H",
            integrity="N",
            availability="N",
        )
        assert factors.vector == "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:N/A:N"


def _finding(**overrides) -> SecurityFinding:
    base = dict(
        id="f1",
        cwe="CWE-89",
        title="SQL injection in the search handler",
        origin="scanner",
        raised_by=["scanner"],
        evidence=EvidenceSpan(path="src/search.ts", start_line=10, end_line=14),
        factors=CvssFactors(
            attack_vector="N",
            attack_complexity="L",
            privileges_required="N",
            user_interaction="N",
            scope="U",
            confidentiality="H",
            integrity="H",
            availability="H",
        ),
        confidence=0.8,
        confidence_source="scanner-rule",
    )
    return SecurityFinding(**{**base, **overrides})


class TestTheValidationReport:
    def test_a_tool_that_did_not_run_says_why(self) -> None:
        # A failure with no reason reads like a clean run (review item C3-5).
        from sdlc_contracts import ToolOutcome

        with pytest.raises(ValidationError, match="npm audit did not run and does not say why"):
            ToolOutcome(tool="npm audit", ran=False)
        assert ToolOutcome(tool="semgrep", ran=True).detail == ""

    def test_severity_cannot_be_authored_only_computed(self) -> None:
        """The rule based CVSS claim, enforced rather than asserted.

        A model that wanted to call a critical finding low cannot: there is no
        field to write, and anything it offers is discarded. The score comes
        from the metrics and the band comes from the score, whatever the
        producer would have preferred.
        """
        assert _finding().base_score == 9.8
        assert _finding().severity == "critical"

        flattering = _finding(severity="low", base_score=0.1)  # type: ignore[call-arg]
        assert flattering.severity == "critical"
        assert flattering.base_score == 9.8

    def test_a_model_cannot_be_the_source_of_its_own_confidence(self) -> None:
        """There is no `llm` or `trained` option, so the question cannot arise."""
        with pytest.raises(ValidationError):
            _finding(confidence_source="llm")

    def test_merged_means_more_than_one_arm_actually_raised_it(self) -> None:
        with pytest.raises(ValidationError, match="merged but only one arm"):
            _finding(origin="merged", raised_by=["llm"])

    def test_an_origin_that_contradicts_its_arms_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="says llm but was raised by"):
            _finding(origin="llm", raised_by=["scanner"])

    def test_a_span_that_ends_before_it_starts_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="span ends at"):
            EvidenceSpan(path="a.ts", start_line=10, end_line=4)

    def test_a_malformed_cwe_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            _finding(cwe="SQL injection")

    def test_refusals_are_counted_rather_than_dropped(self) -> None:
        """The refusal rate is a result about the arm that produced it."""
        report = ValidationReport(
            version=1,
            generated_at=_now(),
            target="spring-sample",
            findings=[_finding()],
            refused_evidence=[
                {"origin": "llm", "reason": "file-not-found", "claimed_path": "src/nope.java"},
                {"origin": "llm", "reason": "span-out-of-range", "claimed_path": "src/a.java"},
            ],
            tests=TestSummary(run=3, passed=3, failed=0, skipped=0, line_coverage=80.0),
        )
        assert report.refused_count == 2
        assert report.open_findings == 1
        assert report.open_critical_or_high == 1


def _attempt(**overrides) -> HealAttempt:
    base = dict(
        test_id="t1",
        test_name="divides by zero",
        suite_path="a.test.ts",
        failure_message="expected 5, received 6",
        classification="brittle",
        classified_by="trace-changed",
    )
    return HealAttempt(**{**base, **overrides})


def _passing_checks() -> list[GuardCheck]:
    return [
        GuardCheck(name="test-code-only", passed=True, detail="only a.test.ts changed"),
        GuardCheck(name="passes-unchanged-code", passed=True, detail="green against v1"),
        GuardCheck(name="kills-a-mutant", passed=True, detail="killed m3"),
    ]


class TestTheHonestyGuard:
    """The contribution, as a shape.

    The failure this blocks is documented in the wild: a state of the art 2025
    repair method rewrites a failing assertion to match current output, and a
    controlled study found 6 of 8 GPT-4 "successful" repairs were that same
    move. Every test here is one of those moves.
    """

    def test_a_repair_that_clears_all_three_checks_is_accepted(self) -> None:
        attempt = _attempt(
            diff=DiffSpan(path="a.test.ts", diff="- expect(x).toBe(5)\n+ expect(x).toBe(6)"),
            checks=_passing_checks(),
        )
        assert attempt.accepted is True

    @pytest.mark.parametrize(
        "weakened",
        ["test-code-only", "passes-unchanged-code", "kills-a-mutant"],
    )
    def test_missing_any_one_check_is_not_accepted(self, weakened: str) -> None:
        """A conjunction that cannot be short circuited: this is the guard."""
        checks = [
            GuardCheck(name=check.name, passed=check.name != weakened, detail="observed")
            for check in _passing_checks()
        ]
        attempt = _attempt(
            diff=DiffSpan(path="a.test.ts", diff="- toBe(5)\n+ toBeTruthy()"),
            checks=checks,
            refusal_reason="assertion-weakened",
        )
        assert attempt.accepted is False

    def test_assertion_weakening_is_refused_however_green_it_looks(self) -> None:
        """The exact anti pattern: the test passes and kills nothing."""
        attempt = _attempt(
            diff=DiffSpan(path="a.test.ts", diff="- expect(x).toBe(5)\n+ expect(x).toBeDefined()"),
            checks=[
                GuardCheck(name="test-code-only", passed=True, detail="only the test changed"),
                GuardCheck(name="passes-unchanged-code", passed=True, detail="green"),
                GuardCheck(name="kills-a-mutant", passed=False, detail="0 of 4 mutants died"),
            ],
            refusal_reason="kills-no-mutant",
        )
        assert attempt.accepted is False
        assert attempt.refusal_reason == "kills-no-mutant"

    def test_a_regression_may_not_be_repaired_at_all(self) -> None:
        """Healing a regression hides a bug, so the shape forbids it."""
        with pytest.raises(ValidationError, match="repaired rather than flagged"):
            _attempt(
                classification="regression",
                classified_by="trace-unchanged",
                diff=DiffSpan(path="a.test.ts", diff="- toBe(5)\n+ toBe(6)"),
            )

    def test_the_referee_must_cite_the_diff_it_relied_on(self) -> None:
        with pytest.raises(ValidationError, match="without citing a diff span"):
            _attempt(classified_by="model-referee")

    def test_a_referee_that_cites_something_is_accepted(self) -> None:
        attempt = _attempt(
            classified_by="model-referee",
            evidence=ClassificationEvidence(
                traced_to=["R-3", "post-orders"],
                changed_artefacts=["post-orders"],
                cited_diff_span="api-contract v1..v2 post-orders request.total",
            ),
        )
        assert attempt.classification == "brittle"

    def test_a_refused_repair_names_its_reason(self) -> None:
        with pytest.raises(ValidationError, match="refused without a reason"):
            _attempt(
                diff=DiffSpan(path="a.test.ts", diff="- a\n+ b"),
                checks=[GuardCheck(name="kills-a-mutant", passed=False, detail="none died")],
            )


class TestTheConvergenceGap:
    """The gap between naive and strict convergence is the guard's effect.

    Lee 2026 reports roughly 70% naive against 50% strict and calls the gap the
    real insight; reporting only the naive number is the misleading thing this
    report refuses to do by carrying both.
    """

    def test_both_rates_are_reported_and_differ_when_the_guard_bites(self) -> None:
        healed = _attempt(
            diff=DiffSpan(path="a.test.ts", diff="- toBe(5)\n+ toBe(6)"),
            checks=_passing_checks(),
        )
        cheated = _attempt(
            test_id="t2",
            diff=DiffSpan(path="a.test.ts", diff="- toBe(5)\n+ toBeTruthy()"),
            checks=[
                GuardCheck(name="test-code-only", passed=True, detail="only the test"),
                GuardCheck(name="passes-unchanged-code", passed=True, detail="green"),
                GuardCheck(name="kills-a-mutant", passed=False, detail="nothing died"),
            ],
            refusal_reason="assertion-weakened",
        )
        regression = _attempt(
            test_id="t3", classification="regression", classified_by="trace-unchanged"
        )
        report = HealReport(
            version=1,
            generated_at=_now(),
            target="calculator",
            from_code_version=1,
            to_code_version=2,
            attempts=[healed, cheated, regression],
        )
        assert report.healed == 1
        assert report.refused == 1
        assert report.flagged_regressions == 1
        # Two brittle tests, both of which produced a repair; one survived.
        assert report.naive_convergence == 100.0
        assert report.strict_convergence == 50.0

    def test_a_heal_compares_a_version_against_a_later_one(self) -> None:
        with pytest.raises(ValidationError, match="against a later one"):
            HealReport(
                version=1,
                generated_at=_now(),
                target="t",
                from_code_version=2,
                to_code_version=2,
            )


def _proposal(**overrides) -> RemediationProposal:
    base = dict(
        id="p1",
        finding_id="f1",
        cwe="CWE-89",
        generated_at=_now(),
        summary="Parameterise the query",
        patch=[PatchHunk(path="src/search.ts", diff="- `${q}`\n+ ?")],
        risk=RiskAssessment(
            level="low",
            statement="Two lines change and three tests cover them.",
            facts=[CountedFact(label="lines changed", value=2)],
        ),
    )
    return RemediationProposal(**{**base, **overrides})


class TestTheRemediationProposal:
    def test_a_dismissal_says_why(self) -> None:
        with pytest.raises(ValidationError, match="dismissed without a reason"):
            _proposal(state="dismissed", decided_by="you")

    def test_a_decision_names_its_author(self) -> None:
        with pytest.raises(ValidationError, match="accepted by nobody"):
            _proposal(state="accepted")

    def test_applied_names_the_code_version_that_carries_it(self) -> None:
        """C3 proposes and C2 applies, so "applied" must point at C2's output."""
        with pytest.raises(ValidationError, match="without the code version"):
            _proposal(state="applied", decided_by="you")

    def test_a_high_risk_claim_rests_on_more_than_one_number(self) -> None:
        with pytest.raises(ValidationError, match="more than one number"):
            RiskAssessment(
                level="high",
                statement="This is risky.",
                facts=[CountedFact(label="files touched", value=9)],
            )

    def test_verified_cannot_be_recorded_over_numbers_that_got_worse(self) -> None:
        """A fix that closes its finding and breaks a test has not passed."""
        worse = Reverification(
            before=VerificationSnapshot(open_findings=3, tests_passed=10, tests_failed=0),
            after=VerificationSnapshot(open_findings=2, tests_passed=8, tests_failed=2),
        )
        assert worse.findings_closed == 1
        assert worse.tests_broken == 2
        assert worse.worsened is True
        with pytest.raises(ValidationError, match="over numbers that got worse"):
            _proposal(
                state="verified",
                decided_by="you",
                applied_code_version=3,
                reverification=worse,
            )

    def test_verified_is_allowed_when_the_numbers_improved(self) -> None:
        better = Reverification(
            before=VerificationSnapshot(open_findings=3, tests_passed=10, tests_failed=0),
            after=VerificationSnapshot(open_findings=2, tests_passed=10, tests_failed=0),
            finding_id="f1",
        )
        proposal = _proposal(
            state="verified",
            decided_by="you",
            applied_code_version=3,
            reverification=better,
        )
        assert proposal.reverification is not None
        assert proposal.reverification.worsened is False
        assert proposal.awaiting_decision is False


#: A file whose line 10 is the weakness, and a second one at line 12.
SOURCE = "".join(f"line {number}\n" for number in range(1, 21))


def _diff(path: str, before: str, after: str) -> str:
    """The change as C3 writes it: difflib's unified diff, three lines of context."""
    import difflib

    return "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
            n=3,
        )
    )


def _at(start: int, end: int | None = None, **overrides) -> SecurityFinding:
    """A finding in src/search.ts over the given lines."""
    span = EvidenceSpan(path="src/search.ts", start_line=start, end_line=end or start)
    return _finding(**{"id": f"CWE-89:search:{start}", "evidence": span, **overrides})


class TestTheFindingAFixWasFor:
    """Re-verification compared totals and called a fix verified whenever they did
    not worsen, with the finding it was for still raised (review item C3-7). Ids
    name a line, and a fix that adds an import moves every line under it, so the
    finding is looked for where the fix's own diff left it."""

    # The fix: an import at the top, and line 10 replaced by two lines.
    FIXED = SOURCE.replace("line 1\n", "import a\nline 1\n", 1).replace(
        "line 10\n", "safe 10a\nsafe 10b\n"
    )
    PATCH = (PatchHunk(path="src/search.ts", diff=_diff("src/search.ts", SOURCE, FIXED)),)

    def test_gone_from_the_after_pass_is_closed(self) -> None:
        assert still_raised(_at(10), self.PATCH, []) == []

    def test_the_same_weakness_where_the_fix_left_it_is_still_raised(self) -> None:
        # Line 10 became lines 11 and 12, below the new import: a new id.
        after = [_at(12)]
        assert still_raised(_at(10), self.PATCH, after) == ["CWE-89:search:12"]

    def test_a_weakness_the_fix_did_not_touch_is_another_one(self) -> None:
        # The second weakness, line 12 before, is line 14 after: not this one.
        after = [_at(14)]
        assert still_raised(_at(10), self.PATCH, after) == []

    def test_a_line_the_fix_did_not_change_moves_by_what_it_added_above(self) -> None:
        # A fix that guards the second weakness (line 12) above it, leaving the
        # line itself: the import and the two-line replacement move it to 14.
        assert still_raised(_at(12), self.PATCH, [_at(14)]) == ["CWE-89:search:14"]
        assert still_raised(_at(12), self.PATCH, [_at(12)]) == []

    def test_unchanged_by_a_fix_to_another_file_it_stays_where_it_was(self) -> None:
        elsewhere = [PatchHunk(path="src/db.ts", diff=_diff("src/db.ts", SOURCE, self.FIXED))]
        assert still_raised(_at(10), elsewhere, [_at(10)]) == ["CWE-89:search:10"]

    def test_another_weakness_class_or_file_is_not_this_finding(self) -> None:
        other_class = _at(11, cwe="CWE-79", id="CWE-79:search:11")
        other_file = _at(
            11,
            id="CWE-89:db:11",
            evidence=EvidenceSpan(path="src/db.ts", start_line=11, end_line=11),
        )
        assert still_raised(_at(10), self.PATCH, [other_class, other_file]) == []

    def test_a_fix_that_deleted_the_lines_looks_at_the_seam(self) -> None:
        deleted = [
            PatchHunk(
                path="src/search.ts",
                diff=_diff("src/search.ts", SOURCE, SOURCE.replace("line 10\n", "")),
            )
        ]
        assert still_raised(_at(10), deleted, [_at(10)]) == ["CWE-89:search:10"]
        assert still_raised(_at(10), deleted, [_at(12)]) == []

    def test_verified_needs_the_finding_gone_as_well_as_nothing_worse(self) -> None:
        numbers = dict(
            before=VerificationSnapshot(open_findings=2, tests_passed=4, tests_failed=0),
            after=VerificationSnapshot(open_findings=2, tests_passed=4, tests_failed=0),
        )
        still = Reverification(**numbers, finding_id="f1", still_raised_as=["CWE-89:search:12"])
        gone = Reverification(**numbers, finding_id="f1")
        never_looked = Reverification(**numbers)

        assert (still.finding_closed, still.verified) == (False, False)
        assert (gone.finding_closed, gone.verified) == (True, True)
        # A comparison recorded before it looked for the finding proves nothing about it.
        assert (never_looked.finding_closed, never_looked.verified) == (False, False)

    def test_a_proposal_is_not_verified_while_its_finding_is_still_raised(self) -> None:
        still = Reverification(
            before=VerificationSnapshot(open_findings=2, tests_passed=4, tests_failed=0),
            after=VerificationSnapshot(open_findings=2, tests_passed=4, tests_failed=0),
            finding_id="f1",
            still_raised_as=["CWE-89:search:12"],
        )
        with pytest.raises(ValidationError, match="while the finding it was for is still raised"):
            _proposal(
                state="verified", decided_by="you", applied_code_version=3, reverification=still
            )

    def test_a_comparison_about_another_finding_does_not_verify_this_one(self) -> None:
        other = Reverification(
            before=VerificationSnapshot(open_findings=2, tests_passed=4, tests_failed=0),
            after=VerificationSnapshot(open_findings=1, tests_passed=4, tests_failed=0),
            finding_id="f2",
        )
        with pytest.raises(ValidationError, match="re-verified f2, not f1"):
            _proposal(
                state="verified", decided_by="you", applied_code_version=3, reverification=other
            )


def _case(
    case_id: str, *, story: str = "", criterion: str = "", origin: str = "filled"
) -> TestCase:
    return TestCase(
        id=case_id,
        name=case_id,
        outcome="passed",
        origin=origin,  # type: ignore[arg-type]
        traces=TestTrace(storyId=story or None, criterionId=criterion),
    )


def _suite_of(*cases: TestCase) -> TestSuite:
    return TestSuite(path="a.test.ts", framework="vitest", cases=list(cases))


#: The build's stories and their criteria, as the testing phase hands them over.
_CRITERIA = {"US-1": {"AC-1-1", "AC-1-2"}}


class TestEachCaseSaysWhereItStands:
    """C3-10: the test review could not tell this version's new tests from the
    regression suite carried forward, and a test whose criterion had left the
    plan passed as if it still tested the build."""

    def test_with_no_earlier_report_every_case_is_new_at_this_version(self) -> None:
        report = _report(
            version=3, suites=[_suite_of(_case("a", story="US-1", criterion="AC-1-1"))]
        )

        stood = with_standing(report, previous=None, criteria=_CRITERIA)

        assert stood.cases[0].since_version == 3
        assert stood.cases[0].obsolete == ""

    def test_a_case_the_earlier_report_ran_is_carried_from_when_it_was_written(self) -> None:
        earlier = _report(
            version=2, suites=[_suite_of(_case("a").model_copy(update={"since_version": 1}))]
        )
        report = _report(version=3, suites=[_suite_of(_case("a"), _case("b"))])

        stood = with_standing(report, previous=earlier, criteria=_CRITERIA)

        since = {case.id: case.since_version for case in stood.cases}
        assert since == {"a": 1, "b": 3}

    def test_a_case_from_a_report_stamped_before_this_existed_dates_from_that_report(self) -> None:
        earlier = _report(version=2, suites=[_suite_of(_case("a"))])  # since_version 0: not known
        report = _report(version=3, suites=[_suite_of(_case("a"))])

        stood = with_standing(report, previous=earlier, criteria=_CRITERIA)

        assert stood.cases[0].since_version == 2

    def test_a_case_whose_story_left_the_build_says_so(self) -> None:
        report = _report(suites=[_suite_of(_case("a", story="US-3", criterion="AC-3-1"))])

        stood = with_standing(report, previous=None, criteria=_CRITERIA)

        assert stood.cases[0].obsolete == "US-3 is no longer in the build"

    def test_a_case_whose_criterion_left_its_story_says_so(self) -> None:
        report = _report(suites=[_suite_of(_case("a", story="US-1", criterion="AC-1-9"))])

        stood = with_standing(report, previous=None, criteria=_CRITERIA)

        assert stood.cases[0].obsolete == "AC-1-9 is no longer one of US-1's acceptance criteria"

    def test_a_test_this_platform_did_not_write_is_never_called_obsolete(self) -> None:
        report = _report(
            suites=[_suite_of(_case("a", story="US-3", origin="upstream"), _case("b"))]
        )

        stood = with_standing(report, previous=None, criteria=_CRITERIA)

        assert [case.obsolete for case in stood.cases] == ["", ""]

    def test_the_run_keeps_where_each_case_stands(self) -> None:
        declared = with_standing(
            _report(version=2, suites=[_suite_of(_case("a", story="US-3", criterion="AC-3-1"))]),
            previous=None,
            criteria=_CRITERIA,
        )
        executed = _report(
            version=2,
            suites=[_suite_of(TestCase(id="a", name="a", outcome="failed", message="no"))],
        )

        merged = with_traces_from(executed, declared)

        assert merged.cases[0].since_version == 2
        assert merged.cases[0].obsolete == "US-3 is no longer in the build"
        assert merged.cases[0].outcome == "failed"

    def test_a_report_stored_before_this_still_reads(self) -> None:
        case = TestCase.model_validate({"id": "a", "name": "a", "outcome": "passed"})
        assert (case.since_version, case.obsolete) == (0, "")


class TestWhatNoTestCanAssert:
    """The contract obligations the generator found nothing to test, on the report.

    They were counted in the stage's summary and listed only in the audit
    log's notes. The Test Generation page read the run's totals and said
    "Every criterion in scope has a test" over five of them (the live clinic
    project, 2026-10-13).
    """

    _GAP: ClassVar[dict[str, str]] = {
        "endpointId": "post-doctors-id-manage",
        "kind": "no-way-to-create",
        "detail": "the contract declares POST /doctors/{id}/manage but no POST on /doctors",
    }

    def test_a_report_carries_them_by_endpoint_kind_and_reason(self) -> None:
        report = TestReport.model_validate(
            {**_report().model_dump(by_alias=True), "gaps": [self._GAP]}
        )

        assert report.gaps == [
            TestGap(
                endpoint_id="post-doctors-id-manage",
                kind="no-way-to-create",
                detail="the contract declares POST /doctors/{id}/manage but no POST on /doctors",
            )
        ]
        assert report.model_dump(by_alias=True, mode="json")["gaps"] == [self._GAP]

    def test_a_report_stored_before_this_has_none(self) -> None:
        stored = _report().model_dump(by_alias=True, mode="json")
        stored.pop("gaps")

        assert TestReport.model_validate(stored).gaps == []

    def test_the_run_keeps_them_since_only_the_generator_knows_them(self) -> None:
        declared = _report(suites=[_suite_of(_case("a"))]).model_copy(
            update={"gaps": [TestGap.model_validate(self._GAP)]}
        )
        executed = _report(suites=[_suite_of(TestCase(id="a", name="a", outcome="passed"))])

        assert with_traces_from(executed, declared).gaps == declared.gaps

    def test_they_are_kept_when_the_generator_declared_no_case(self) -> None:
        declared = _report().model_copy(update={"gaps": [TestGap.model_validate(self._GAP)]})
        executed = _report(suites=[_suite_of(TestCase(id="a", name="a", outcome="passed"))])

        assert with_traces_from(executed, declared).gaps == declared.gaps


class TestTheRunKeepsWhatKindOfTestEachIs:
    """A runner reports names and outcomes, and every case it returned was a
    "unit" test. So after the run stage no test was an API test: the server
    refuses to keep a repair to one, or to have one written again, by asking
    the report its kind, and the report had stopped knowing."""

    def test_an_api_test_is_still_one_after_it_ran(self) -> None:
        declared = _report(
            suites=[_suite_of(TestCase(id="a", name="a", outcome="not-run", kind="api"))]
        )
        executed = _report(
            suites=[_suite_of(TestCase(id="a", name="a", outcome="failed", message="no"))]
        )

        merged = with_traces_from(executed, declared)

        assert merged.cases[0].kind == "api"
        assert merged.cases[0].outcome == "failed"

    def test_a_test_the_generator_did_not_declare_keeps_the_runner_s_word(self) -> None:
        declared = _report(
            suites=[_suite_of(TestCase(id="a", name="a", outcome="not-run", kind="api"))]
        )
        executed = _report(
            suites=[_suite_of(TestCase(id="theirs", name="theirs", outcome="passed"))]
        )

        assert with_traces_from(executed, declared).cases[0].kind == "unit"


class TestWhereAFixShips:
    """A fix patches the newest code version. With newer code than may ship
    today, it reaches production only together with that code, once its tests
    are approved (review item C4-13), and the snapshot says where it lands."""

    def test_it_names_the_newer_code_and_the_code_that_may_ship(self) -> None:
        ships = FixShipsWith(
            code_version=3, sprint=2, releasable_code_version=2, releasable_sprint=1
        )
        assert ships.model_dump(by_alias=True) == {
            "codeVersion": 3,
            "sprint": 2,
            "releasableCodeVersion": 2,
            "releasableSprint": 1,
        }

    def test_code_that_may_already_ship_is_not_newer_code(self) -> None:
        with pytest.raises(ValidationError, match="is not newer than code version 2"):
            FixShipsWith(code_version=2, sprint=1, releasable_code_version=2, releasable_sprint=1)
