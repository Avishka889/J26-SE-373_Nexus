"""Approval gated remediation, and the refusal that matters most in it.

The healing loop refuses a repair that weakens an assertion. This is the same
failure one component over: a model asked to close a security finding can close
it by telling the scanner not to look. `// nosemgrep` passes a re-scan, passes
the suite, and leaves the weakness exactly where it was.

So the tests here are shaped like Checkpoint 2's: the same finding, the same
loop, and two different model answers. One parameterises the query. The other
adds a suppression comment. Every other check accepts both.
"""

from datetime import UTC, datetime

import pytest
from c3.remediate import (
    NotComparable,
    accepts,
    assess,
    build_patcher,
    candidates,
    compare,
    level_of,
    measure,
    proposal_for,
    propose_patch,
    refusal_for,
    rollback_advice,
    worst_first,
)
from c3.remediate.guard import is_test_code, suppressions_in
from c3.remediate.patch import numbered, splice
from c3.remediate.propose import covering_tests, endpoints_in
from sdlc_contracts import (
    ApiContract,
    ApiEndpoint,
    CvssFactors,
    DetectorRun,
    EvidenceSpan,
    PatchHunk,
    SecurityFinding,
    TestCase,
    TestReport,
    TestSuite,
    ValidationReport,
    VerificationSnapshot,
)

VULNERABLE = """package com.example;

public class Accounts {
    public static String findByName(Connection db, String name) throws SQLException {
        Statement statement = db.createStatement();
        return statement.executeQuery("select * from users where name = '" + name + "'");
    }
}
"""

PATH = "src/main/java/com/example/Accounts.java"


def _finding(**overrides) -> SecurityFinding:
    base = {
        "id": "CWE-89:Accounts:6",
        "cwe": "CWE-89",
        "title": "sql injection",
        "origin": "scanner",
        "raised_by": ["scanner"],
        "evidence": EvidenceSpan(path=PATH, start_line=6, end_line=6, snippet="executeQuery"),
        "factors": CvssFactors(
            attack_vector="N",
            attack_complexity="L",
            privileges_required="N",
            user_interaction="N",
            scope="U",
            confidentiality="H",
            integrity="H",
            availability="H",
        ),
        "confidence": 0.5,
        "confidence_source": "scanner-rule",
    }
    return SecurityFinding(**{**base, **overrides})


def _model(answer: dict):
    """A model that returns one scripted answer, spending nothing."""
    import json

    from pydantic_ai.messages import ModelResponse, ToolCallPart
    from pydantic_ai.models.function import FunctionModel

    def respond(messages, info):
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, json.dumps(answer))])

    return FunctionModel(respond)


class TestTheSuppressionRefusal:
    """The contribution of this stage, and the reason it exists.

    A suppression closes the finding, passes every test, and fixes nothing. It
    is the one outcome an automated pipeline must not be able to produce,
    because it is indistinguishable from success while delivering none of it.
    """

    @pytest.mark.parametrize(
        "line",
        [
            "  stmt.execute(sql); // nosemgrep",
            "  stmt.execute(sql)  # nosec B608",
            "  stmt.execute(sql); /* NOSONAR */",
            '  @SuppressWarnings("SQL_INJECTION")',
            "  @SuppressFBWarnings",
            "  // eslint-disable-next-line security/detect-object-injection",
            "  // @ts-ignore",
            "  // codeql[js/sql-injection]",
        ],
    )
    def test_every_way_of_telling_a_tool_to_look_away_is_caught(self, line) -> None:
        hunks = [PatchHunk(path=PATH, diff=f"--- a\n+++ b\n+{line}")]

        refusal = refusal_for(hunks, finding_path=PATH)

        assert refusal is not None
        assert refusal.reason == "suppression-not-fix"

    def test_a_real_fix_is_accepted(self) -> None:
        hunks = [
            PatchHunk(
                path=PATH,
                diff="--- a\n+++ b\n-  statement.executeQuery(sql);\n"
                '+  PreparedStatement s = db.prepareStatement("select * from users where name = ?");',
            )
        ]

        assert accepts(hunks, finding_path=PATH)

    def test_a_fix_that_also_suppresses_is_still_refused(self) -> None:
        """The suppression is then unnecessary, and its presence means the next
        reader cannot tell which of the two closed the finding."""
        hunks = [
            PatchHunk(
                path=PATH,
                diff="--- a\n+++ b\n+  PreparedStatement s = db.prepareStatement(q); // nosemgrep",
            )
        ]

        assert not accepts(hunks, finding_path=PATH)

    def test_a_suppression_already_in_the_file_is_not_this_patch_s_doing(self) -> None:
        """Context lines are the file as it already was. Accusing a patch of a
        suppression it merely sat next to would refuse honest work for
        something somebody else did."""
        hunks = [
            PatchHunk(
                path=PATH,
                diff="--- a\n+++ b\n   // nosemgrep\n+  PreparedStatement s = db.prepareStatement(q);",
            )
        ]

        assert suppressions_in(hunks) == []
        assert accepts(hunks, finding_path=PATH)


class TestWhereAPatchMayReach:
    def test_editing_a_test_is_refused(self) -> None:
        """Tests are the healing loop's territory. A remediation that adjusts a
        test to stop it failing has widened the change into somewhere nobody
        approved."""
        hunks = [PatchHunk(path="src/test/java/com/example/AccountsTest.java", diff="+  assert x;")]

        refusal = refusal_for(hunks, finding_path=PATH)

        assert refusal is not None and refusal.reason == "touched-test-code"

    @pytest.mark.parametrize(
        "path",
        [
            "src/test/java/A.java",
            "apps/web/src/__tests__/total.test.ts",
            "pkg/tests/helper.py",
            "com/example/AccountsTest.java",
            "src/total.spec.ts",
        ],
    )
    def test_test_code_is_recognised_across_both_stacks(self, path) -> None:
        assert is_test_code(path)

    def test_wandering_outside_the_finding_is_refused(self) -> None:
        """The risk was assessed against one file. A change reaching beyond it
        is a change assessed against the wrong thing."""
        hunks = [
            PatchHunk(path=PATH, diff="+  fixed();"),
            PatchHunk(path="src/main/java/com/example/Reports.java", diff="+  alsoChanged();"),
        ]

        refusal = refusal_for(hunks, finding_path=PATH)

        assert refusal is not None and refusal.reason == "outside-the-finding"

    def test_an_empty_patch_is_not_a_proposal(self) -> None:
        refusal = refusal_for([], finding_path=PATH)

        assert refusal is not None and refusal.reason == "no-patch"


class TestRiskCountedRatherThanAsserted:
    def _hunk(self, added: int, removed: int = 0) -> list[PatchHunk]:
        body = "\n".join(f"+  line {n}" for n in range(added))
        body += "\n" + "\n".join(f"-  old {n}" for n in range(removed))
        return [PatchHunk(path=PATH, diff=f"--- a\n+++ b\n{body}")]

    def test_deleted_lines_count_as_changed(self) -> None:
        """A patch that deletes fifteen lines and adds one is not a one line
        change, and calling it one would understate exactly the patches most
        worth reading."""
        blast = measure(self._hunk(added=1, removed=15))

        assert blast.lines_changed == 16

    def test_a_small_covered_change_is_low(self) -> None:
        assert level_of(measure(self._hunk(2), covering_tests=3)) == "low"

    def test_an_uncovered_change_is_never_low(self) -> None:
        """No test will notice if the fix is wrong, and a security fix that is
        wrong is worse than the weakness, because everybody now believes it is
        closed."""
        assert level_of(measure(self._hunk(2), covering_tests=0)) == "medium"

    def test_moving_an_endpoint_contract_is_high(self) -> None:
        """It breaks C2's generated client and C3's own api tests: a blast
        radius well beyond the file being edited."""
        assert level_of(measure(self._hunk(2), covering_tests=9, moved_endpoints=1)) == "high"

    def test_the_sentence_only_restates_the_counts(self) -> None:
        """This is the line most likely to be read and least likely to be
        checked, so it is the line that must contain nothing the numbers do not
        support."""
        found = assess(self._hunk(3), covering_tests=2)

        assert "3 lines" in found.statement
        assert "2 tests cover" in found.statement
        assert {fact.label for fact in found.facts} == {
            "files changed",
            "lines changed",
            "tests covering those lines",
            "endpoints whose contract moves",
        }

    def test_a_high_risk_assessment_carries_more_than_one_number(self) -> None:
        """The contract refuses otherwise, and that refusal is worth keeping
        live rather than trusting."""
        found = assess(self._hunk(30), covering_tests=0)

        assert found.level == "high"
        assert len(found.facts) > 1


class TestAskingTheModelForALineSpan:
    def test_the_span_it_must_replace_is_marked(self) -> None:
        shown = numbered(VULNERABLE, 6, 6, around=2)

        assert ">>     6" in shown
        assert "       4" in shown or "  " in shown

    def test_the_replacement_is_spliced_where_the_old_lines_were(self) -> None:
        after = splice(VULNERABLE, 6, 6, "return safeQuery(db, name);")

        assert "executeQuery" not in after
        assert "safeQuery" in after
        assert "public class Accounts" in after, "the rest of the file survives"

    def test_an_unindented_answer_is_indented_to_match(self) -> None:
        """A fix that is correct and unreadable gets rejected by a reviewer for
        the wrong reason."""
        after = splice(VULNERABLE, 6, 6, "return safeQuery(db, name);")

        assert "        return safeQuery" in after

    def test_a_span_outside_the_file_produces_nothing(self) -> None:
        assert splice(VULNERABLE, 900, 900, "x") == ""

    async def test_a_parameterised_fix_becomes_a_patch(self) -> None:
        scripted = _model(
            {
                "replacement": 'return safeQuery(db, "select * from users where name = ?", name);',
                "explanation": "use a prepared statement",
            }
        )

        outcome = await propose_patch(build_patcher(scripted), _finding(), source=VULNERABLE)

        assert outcome.patched
        assert outcome.refusals == []
        assert "safeQuery" in outcome.hunks[0].diff

    async def test_a_suppression_is_refused_and_kept(self) -> None:
        """How often a model answers a security fix with a suppression is a
        result about that model, and dropping those quietly would flatter it in
        exactly the comparison this component runs."""
        scripted = _model({"replacement": "return statement.executeQuery(sql); // nosemgrep"})

        outcome = await propose_patch(build_patcher(scripted), _finding(), source=VULNERABLE)

        assert not outcome.patched
        assert outcome.gave_up == "suppression-not-fix"
        assert len(outcome.refusals) == 2, "both attempts refused, both recorded"

    async def test_a_model_that_declines_is_giving_a_useful_answer(self) -> None:
        scripted = _model({"replacement": "", "cannot_fix": "the sanitiser belongs in the caller"})

        outcome = await propose_patch(build_patcher(scripted), _finding(), source=VULNERABLE)

        assert not outcome.patched
        assert "the sanitiser belongs in the caller" in outcome.gave_up
        assert outcome.attempts == 1, "a considered decline is not retried"

    async def test_an_answer_that_changes_nothing_is_refused(self) -> None:
        scripted = _model(
            {
                "replacement": 'return statement.executeQuery("select * from users where name = \'" + name + "\'");'
            }
        )

        outcome = await propose_patch(build_patcher(scripted), _finding(), source=VULNERABLE)

        assert not outcome.patched


class TestWhichFindingsGetAProposal:
    def _report(self, findings: list[SecurityFinding]) -> ValidationReport:
        from sdlc_contracts import TestSummary

        return ValidationReport(
            version=1,
            generated_at=datetime.now(UTC),
            target="sample",
            findings=findings,
            tests=TestSummary(run=0, passed=0, failed=0, skipped=0, line_coverage=0.0),
        )

    def test_the_worst_comes_first(self) -> None:
        low = _finding(
            id="low",
            cwe="CWE-327",
            factors=CvssFactors(
                attack_vector="N",
                attack_complexity="H",
                privileges_required="N",
                user_interaction="N",
                scope="U",
                confidentiality="H",
                integrity="N",
                availability="N",
            ),
        )
        ordered = worst_first([low, _finding()])

        assert ordered[0].cwe == "CWE-89"

    def test_a_dismissed_finding_is_not_proposed_again(self) -> None:
        """A person has already told the pipeline not to raise it."""
        report = self._report([_finding(status="dismissed"), _finding(id="open-one")])

        chosen, _ = candidates(report)

        assert [finding.id for finding in chosen] == ["open-one"]

    def test_the_list_is_capped_and_says_how_many_it_left(self) -> None:
        """A list of sixty proposals is a list nobody reads, and a reviewer who
        stops at the tenth has stopped at whichever ten the sort put first."""
        report = self._report([_finding(id=f"f{n}") for n in range(15)])

        chosen, not_reached = candidates(report, limit=10)

        assert (len(chosen), not_reached) == (10, 5)


class TestWhatTheProposalCarries:
    def _outcome(self):
        from c3.remediate import PatchOutcome

        return PatchOutcome(
            hunks=[PatchHunk(path=PATH, diff="--- a\n+++ b\n-  bad();\n+  good();")],
            explanation="use a prepared statement",
        )

    def test_endpoints_are_read_out_of_the_file_a_reader_can_open(self) -> None:
        """C2's generator writes the endpoint id above every route, so the
        answer is confirmable by looking rather than guessed from a name."""
        contract = ApiContract(
            version=1,
            endpoints=[ApiEndpoint(id="get-users-id", method="GET", path="/users/{id}")],
        )
        source = '  // implements get-users-id GET /users/{id}\n  router.get("/:id", handler);'

        assert endpoints_in(source, contract) == ["get-users-id"]

    def test_a_stale_marker_for_a_vanished_endpoint_does_not_count(self) -> None:
        contract = ApiContract(version=1, endpoints=[])
        source = "  // implements get-users-id GET /users/{id}"

        assert endpoints_in(source, contract) == []

    def test_a_hand_written_file_honestly_reports_none(self) -> None:
        contract = ApiContract(
            version=1,
            endpoints=[ApiEndpoint(id="get-users-id", method="GET", path="/users/{id}")],
        )

        assert endpoints_in(VULNERABLE, contract) == []

    def test_the_proposal_starts_awaiting_a_person(self) -> None:
        proposal = proposal_for(_finding(), self._outcome(), at=datetime.now(UTC))

        assert proposal.state == "proposed"
        assert proposal.awaiting_decision
        assert proposal.applied_code_version is None, "c3 proposes, c2 applies"

    def test_covering_tests_are_counted_from_the_report(self) -> None:
        tests = TestReport(
            version=1,
            generated_at=datetime.now(UTC),
            target="sample",
            isolation="sandbox",
            mutation_skipped_reason="not part of this comparison",
            suites=[
                TestSuite(
                    path="src/test/java/com/example/AccountsTest.java",
                    framework="junit5",
                    cases=[
                        TestCase(id="a", name="finds by name", outcome="passed"),
                        TestCase(id="b", name="rejects a quote", outcome="passed"),
                    ],
                )
            ],
        )

        assert covering_tests(_finding(), tests) == 2


class TestReverificationBySubtraction:
    def _report(self, findings: int, arms=("scanner",), files: int = 10) -> ValidationReport:
        from sdlc_contracts import TestSummary

        return ValidationReport(
            version=1,
            generated_at=datetime.now(UTC),
            target="sample",
            findings=[_finding(id=f"f{n}") for n in range(findings)],
            detector_runs=[
                DetectorRun(
                    arm=arm,
                    model_id="x",
                    started_at=datetime.now(UTC),
                    duration_seconds=1.0,
                    offline=True,
                    files_scanned=files,
                )
                for arm in arms
            ],
            tests=TestSummary(run=0, passed=0, failed=0, skipped=0, line_coverage=0.0),
        )

    def _suite(self, outcomes: dict[str, str]) -> TestReport:
        """A report with named cases, so a case can be followed across passes.

        The comparison counts the cases both passes ran, because generation
        runs again on every run: a case only one of them has says nothing about
        the patch.
        """
        return TestReport(
            version=1,
            generated_at=datetime.now(UTC),
            target="sample",
            isolation="sandbox",
            mutation_skipped_reason="not part of this comparison",
            suites=[
                TestSuite(
                    path="t.test.ts",
                    framework="vitest",
                    cases=[
                        TestCase(
                            id=name,
                            name=name,
                            outcome=outcome,  # type: ignore[arg-type]
                            message="boom" if outcome == "failed" else "",
                        )
                        for name, outcome in outcomes.items()
                    ],
                )
            ],
        )

    def _tests(self, passed: int, failed: int) -> TestReport:
        return TestReport(
            version=1,
            generated_at=datetime.now(UTC),
            target="sample",
            isolation="sandbox",
            mutation_skipped_reason="not part of this comparison",
            suites=[
                TestSuite(
                    path="t.test.ts",
                    framework="vitest",
                    cases=[
                        *(
                            TestCase(id=f"p{n}", name=f"p{n}", outcome="passed")
                            for n in range(passed)
                        ),
                        *(
                            TestCase(id=f"f{n}", name=f"f{n}", outcome="failed", message="boom")
                            for n in range(failed)
                        ),
                    ],
                )
            ],
        )

    def test_a_closed_finding_with_nothing_broken_is_kept(self) -> None:
        result = compare(self._report(2), self._tests(5, 0), self._report(1), self._tests(5, 0))

        assert result.findings_closed == 1
        assert not result.worsened
        assert "keep" in rollback_advice(result)

    def test_a_fix_that_breaks_a_test_offers_a_rollback(self) -> None:
        """A fix that closes its finding while breaking a test has not passed,
        and the offer follows from the arithmetic.

        Broken means a case that passed before and fails now, which is why both
        passes name the same cases here.
        """
        green = {"a": "passed", "b": "passed", "c": "passed"}
        result = compare(
            self._report(2),
            self._suite(green),
            self._report(1),
            self._suite({**green, "c": "failed"}),
        )

        assert result.worsened
        assert result.tests_broken == 1
        assert "roll back" in rollback_advice(result)

    def test_a_case_only_the_second_pass_has_is_not_a_broken_test(self) -> None:
        """Generation runs again on every run, so the second pass is not the
        first pass's suite. The first live run of this loop broke a test with
        `expect is not defined`, which was the fill's doing, and counting it
        would have reported the fix as breaking something."""
        result = compare(
            self._report(2),
            self._suite({"a": "passed", "b": "passed"}),
            self._report(1),
            self._suite({"a": "passed", "b": "passed", "written-this-run": "failed"}),
        )

        assert result.tests_broken == 0
        assert not result.worsened
        assert result.findings_closed == 1

    def test_a_case_that_was_not_passing_before_is_not_a_broken_test(self) -> None:
        """A criterion that was an unwritten todo before and a filled failing
        test after is the generator's doing. The first live comparison counted
        exactly that and called a working fix a regression."""
        result = compare(
            self._report(2),
            self._suite({"a": "passed", "todo-one": "skipped"}),
            self._report(1),
            self._suite({"a": "passed", "todo-one": "failed"}),
        )

        assert result.tests_broken == 0
        assert not result.worsened

    def test_two_passes_sharing_no_case_are_not_comparable(self) -> None:
        with pytest.raises(NotComparable) as raised:
            compare(
                self._report(2),
                self._suite({"a": "passed"}),
                self._report(1),
                self._suite({"z": "passed"}),
            )

        assert "nothing can be said" in str(raised.value)

    def test_two_passes_with_different_arms_are_not_comparable(self) -> None:
        """A before pass with three arms and an after pass with one closes
        findings the patch never touched."""
        with pytest.raises(NotComparable) as raised:
            compare(
                self._report(3, arms=("scanner", "llm")),
                self._tests(5, 0),
                self._report(1, arms=("scanner",)),
                self._tests(5, 0),
            )

        assert "says as much about" in str(raised.value)

    def test_a_much_narrower_after_pass_is_not_comparable(self) -> None:
        with pytest.raises(NotComparable):
            compare(
                self._report(3, files=100),
                self._tests(5, 0),
                self._report(1, files=4),
                self._tests(5, 0),
            )

    def test_a_suite_that_did_not_run_is_not_a_suite_that_passed(self) -> None:
        empty = TestReport(
            version=1,
            generated_at=datetime.now(UTC),
            target="sample",
            isolation="sandbox",
            mutation_skipped_reason="not part of this comparison",
            suites=[],
        )

        with pytest.raises(NotComparable) as raised:
            compare(self._report(2), self._tests(5, 0), self._report(1), empty)

        assert "did not run" in str(raised.value)

    def test_mutation_that_did_not_run_is_null_rather_than_zero(self) -> None:
        """Zero is a real score and means every mutant survived, which is the
        opposite of not knowing."""
        from c3.remediate import snapshot_of

        snapshot = snapshot_of(self._report(1), self._tests(5, 0))

        assert isinstance(snapshot, VerificationSnapshot)
        assert snapshot.mutation_score is None


class TestTheFindingTheFixWasFor:
    """Totals alone called a fix verified whenever they did not worsen, with the
    finding it was for still raised (review item C3-7). The comparison now looks
    for that finding in the after pass, where the fix's own diff left it."""

    # The fix as C3 writes it: an import above, and the query parameterised.
    FIXED = VULNERABLE.replace(
        "package com.example;\n", "package com.example;\nimport x;\n"
    ).replace(
        """return statement.executeQuery("select * from users where name = '" + name + "'");""",
        'return safeQuery(db, "select * from users where name = ?", name);',
    )

    def _patch(self) -> list[PatchHunk]:
        from c3.remediate.patch import unified

        return [PatchHunk(path=PATH, diff=unified(PATH, VULNERABLE, self.FIXED))]

    def _scan(self, *findings: SecurityFinding) -> ValidationReport:
        from sdlc_contracts import TestSummary

        return ValidationReport(
            version=1,
            generated_at=datetime.now(UTC),
            target="sample",
            findings=list(findings),
            detector_runs=[
                DetectorRun(
                    arm="scanner",
                    model_id="x",
                    started_at=datetime.now(UTC),
                    duration_seconds=1.0,
                    offline=True,
                    files_scanned=10,
                )
            ],
            tests=TestSummary(run=0, passed=0, failed=0, skipped=0, line_coverage=0.0),
        )

    def _compare(self, after: ValidationReport, **kw):
        tests = TestReverificationBySubtraction()._tests(5, 0)
        return compare(self._scan(_finding()), tests, after, tests, patch=self._patch(), **kw)

    def test_gone_after_the_fix_is_verified(self) -> None:
        result = self._compare(self._scan(), finding_id="CWE-89:Accounts:6")

        assert result.finding_id == "CWE-89:Accounts:6"
        assert result.still_raised_as == []
        assert result.verified
        assert rollback_advice(result).startswith("keep: the finding it was for is gone")

    def test_still_raised_under_a_new_id_is_not_verified(self) -> None:
        # The import moved the query to line 7, so the id changed; the weakness did not.
        moved = _finding(
            id="CWE-89:Accounts:7",
            evidence=EvidenceSpan(path=PATH, start_line=7, end_line=7, snippet="safeQuery"),
        )

        result = self._compare(self._scan(moved), finding_id="CWE-89:Accounts:6")

        assert not result.worsened, "the totals did not move"
        assert result.still_raised_as == ["CWE-89:Accounts:7"]
        assert not result.verified
        assert rollback_advice(result) == (
            "not verified: the finding it was for is still raised, as CWE-89:Accounts:7, "
            "though nothing broke"
        )

    def test_a_finding_the_before_pass_never_raised_is_not_comparable(self) -> None:
        with pytest.raises(NotComparable) as raised:
            self._compare(self._scan(), finding_id="CWE-89:Accounts:40")

        assert "the before pass does not raise CWE-89:Accounts:40" in str(raised.value)

    async def test_the_service_hands_the_finding_and_the_patch_through(self) -> None:
        from c3.service import C3

        tests = TestReverificationBySubtraction()._tests(5, 0)
        moved = _finding(
            id="CWE-89:Accounts:7",
            evidence=EvidenceSpan(path=PATH, start_line=7, end_line=7, snippet="safeQuery"),
        )

        answer = await C3("no model").reverify(
            self._scan(_finding()),
            tests,
            self._scan(moved),
            tests,
            finding_id="CWE-89:Accounts:6",
            patch=self._patch(),
        )

        assert answer.artefact is not None
        assert answer.artefact.still_raised_as == ["CWE-89:Accounts:7"]
        assert answer.notes["findingClosed"] is False
