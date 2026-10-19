"""Checkpoint 2: one heal accepted through the guard, one weakening refused.

The component's headline claim, run end to end against a real runner. The two
cases below are the same failing test, the same classification, the same loop,
and two different model answers. One rewrites the assertion to match the
behaviour the code now has. The other replaces it with `toBeDefined()`, which
makes the test pass just as well and checks nothing.

Every static rule in the repair loop accepts both. That is not a gap: it is the
reason the guard exists, and this file is where it is demonstrated rather than
asserted. The mutant check is what tells them apart.

No model is called. The two answers are written out here, because the point is
what the guard does with them, not whether a provider happens to produce them.
"""

import json
import shutil

import pytest
from c3.eval.repair_proof import (
    HONEST,
    STALE,
    SUITE,
    WEAKENED,
    changed_contract,
    prepare,
)
from c3.eval.repair_proof import failing_report as _report
from c3.generate.criteria import fresh_app_block
from c3.generate.fill import body_spans, written_names
from c3.heal.guard import refusal_for
from c3.heal.referee import build_referee, changes_for
from c3.heal.repair import build_repairer, named_in, repair_problems, splice
from c3.service import C3
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel
from sdlc_contracts import ChangedCode, ContractDiff, EndpointChange, GuardCheck, TestTrace

from .test_targets import Ref

needs_npm = pytest.mark.skipif(shutil.which("npm") is None, reason="needs node and npm")

#: The same stale test, loading `total` afresh before each case the way every
#: generated acceptance test loads its app (`c3.generate.criteria`).
FRESH_STALE = (
    'import { beforeEach, expect, it, vi } from "vitest";\n'
    + fresh_app_block(["total"], "../total")
    + '\nit("totals the basket", () => {\n'
    + "  expect(total([{ price: 333, quantity: 3 }])).toBe(998);\n"
    + "});\n"
)
FRESH_HONEST = FRESH_STALE.replace("toBe(998)", "toBe(999)")

#: The scenario itself lives in `c3.eval.repair_proof`, which is what runs it
#: against a real provider. One definition, so the guard demonstrated here with
#: two hand written answers and the live run that asks a model for one are the
#: same failing test rather than two that look alike.
_changed = changed_contract


def _scripted(answer: str):
    def respond(messages, info):
        return ModelResponse(
            parts=[ToolCallPart(info.output_tools[0].name, json.dumps({"content": answer}))]
        )

    return build_repairer(FunctionModel(respond))


def _prepared(tmp_path):
    """The sample, installed, with the stale test in it and a rounding total."""
    return prepare(tmp_path), None


class _Referee:
    """A scripted referee: it answers as told, citing a line it was given, and
    keeps every prompt so a test can see whether it was asked at all."""

    def __init__(self, classification: str) -> None:
        self.classification = classification
        self.prompts: list[str] = []

    def model(self) -> FunctionModel:
        def respond(messages, info):
            self.prompts.append(str(messages[-1]))
            answer = {
                "classification": self.classification,
                "cited_change": changes_for(_changed(), None)[0].line,
                "reasoning": "scripted",
            }
            return ModelResponse(
                parts=[ToolCallPart(info.output_tools[0].name, json.dumps(answer))]
            )

        return FunctionModel(respond)


class TestTheStaticRulesCannotTellThemApart:
    def test_both_answers_satisfy_every_rule_the_loop_can_read(self) -> None:
        """Stated first, because it is why the guard has three checks.

        The honest repair and the weakened one both keep every name, add
        nothing, delete nothing, assert something, and use nothing forbidden.
        No amount of reading the file separates them.
        """
        assert repair_problems(STALE, HONEST, target="totals the basket") == []
        assert repair_problems(STALE, WEAKENED, target="totals the basket") == []


@pytest.mark.sandbox
@needs_npm
class TestTheGuard:
    async def test_an_honest_repair_is_accepted_with_its_evidence(self, tmp_path) -> None:
        repo, _ = _prepared(tmp_path)
        target = Ref(kind="generated", code_version=2, path=str(repo.root))

        answer = await C3("scripted", repairer=_scripted(HONEST)).heal(
            target,
            _report(),
            from_code_version=1,
            to_code_version=2,
            contract_diff=_changed(),
            version=2,
        )
        report = answer.artefact

        assert report.healed == 1, [a.checks for a in report.attempts]
        attempt = report.attempts[0]
        assert attempt.accepted
        assert attempt.classification == "brittle"
        assert attempt.classified_by == "trace-changed"
        assert {check.name for check in attempt.checks if check.passed} == {
            "test-code-only",
            "passes-unchanged-code",
            "kills-a-mutant",
        }
        # The proof can be re-read rather than taken on trust.
        assert attempt.killed_mutant_ids
        assert "toBe(999)" in attempt.diff.diff
        assert repo.read(SUITE) == HONEST, "an accepted repair stays in the repository"
        # And the stage says what answered, read from the response itself.
        assert answer.notes["model_use"]["answered_by"] == ["function:respond:"]

    async def test_a_test_that_loads_its_code_afresh_is_checked_where_the_code_changed(
        self, tmp_path
    ) -> None:
        """Every generated acceptance test loads its app with a dynamic import
        before each case. The guard read static imports only, found no code
        under any of them, and refused every honest repair as a caught cheat."""
        repo, _ = _prepared(tmp_path)
        repo.write(SUITE, FRESH_STALE)
        target = Ref(kind="generated", code_version=2, path=str(repo.root))

        answer = await C3("scripted", repairer=_scripted(FRESH_HONEST)).heal(
            target,
            _report(),
            from_code_version=1,
            to_code_version=2,
            contract_diff=_changed(),
            changed_code=[ChangedCode(path="apps/web/src/total.ts", start=6, end=8)],
            version=2,
        )
        attempt = answer.artefact.attempts[0]

        assert attempt.accepted, [check.detail for check in attempt.checks]
        path, line, _operator = attempt.killed_mutant_ids[0].split(":")
        assert path == "apps/web/src/total.ts"
        assert 6 <= int(line) <= 8, "the fault goes into the code that changed"

    async def test_a_test_that_reaches_no_code_is_the_guards_limit_not_a_cheat(
        self, tmp_path
    ) -> None:
        repo, _ = _prepared(tmp_path)
        lone = 'import { expect, it } from "vitest";\n\nit("totals the basket", () => {\n  expect(3 * 333).toBe(998);\n});\n'
        repo.write(SUITE, lone)
        target = Ref(kind="generated", code_version=2, path=str(repo.root))

        answer = await C3("scripted", repairer=_scripted(lone.replace("998", "999"))).heal(
            target,
            _report(),
            from_code_version=1,
            to_code_version=2,
            contract_diff=_changed(),
            version=2,
        )
        attempt = answer.artefact.attempts[0]

        assert attempt.refusal_reason == "no-code-to-check", [c.detail for c in attempt.checks]
        assert repo.read(SUITE) == lone, "a refused repair leaves no trace"

    async def test_a_weakened_assertion_is_refused_and_the_file_put_back(self, tmp_path) -> None:
        """The claim, demonstrated: this repair passes, and it is refused.

        `toBeDefined()` clears `test-code-only` and `passes-unchanged-code`
        comfortably. It fails on the only check a weakened assertion cannot
        pass, and the test is left failing rather than made green by something
        that stopped checking.
        """
        repo, _ = _prepared(tmp_path)
        target = Ref(kind="generated", code_version=2, path=str(repo.root))

        answer = await C3("scripted", repairer=_scripted(WEAKENED)).heal(
            target,
            _report(),
            from_code_version=1,
            to_code_version=2,
            contract_diff=_changed(),
            version=2,
        )
        report = answer.artefact
        attempt = report.attempts[0]

        assert report.healed == 0
        assert report.refused == 1
        assert not attempt.accepted
        assert attempt.refusal_reason == "kills-no-mutant"
        passed = {check.name for check in attempt.checks if check.passed}
        assert passed == {"test-code-only", "passes-unchanged-code"}
        # The refusal keeps its diff, because the refusals are the evidence.
        assert attempt.diff is not None
        assert "toBeDefined" in attempt.diff.diff
        assert repo.read(SUITE) == STALE, "a refused repair leaves no trace in the repository"

    async def test_the_gap_between_the_two_rates_is_the_guard(self, tmp_path) -> None:
        """What a loop without a guard would have claimed, against what this
        one stands behind. On the weakened answer they are 100 and 0."""
        repo, _ = _prepared(tmp_path)
        target = Ref(kind="generated", code_version=2, path=str(repo.root))

        answer = await C3("scripted", repairer=_scripted(WEAKENED)).heal(
            target,
            _report(),
            from_code_version=1,
            to_code_version=2,
            contract_diff=_changed(),
            version=2,
        )
        report = answer.artefact

        assert report.naive_convergence == 100.0
        assert report.strict_convergence == 0.0
        assert answer.notes["naiveConvergence"] == 100.0
        assert answer.notes["strictConvergence"] == 0.0


@pytest.mark.sandbox
@needs_npm
class TestWhatIsNeverRepaired:
    async def test_a_regression_is_flagged_and_left_alone(self, tmp_path) -> None:
        """The shape refuses to carry a repaired regression, so this is checked
        by the absence of a diff rather than by a validator firing."""
        repo, _ = _prepared(tmp_path)
        target = Ref(kind="generated", code_version=2, path=str(repo.root))
        # Nothing this test traces to moved between the versions.
        unrelated = ContractDiff(
            from_version=1,
            to_version=2,
            changed=[EndpointChange(endpoint_id="get-something-else", field="response")],
        )

        answer = await C3("scripted", repairer=_scripted(HONEST)).heal(
            target,
            _report(),
            from_code_version=1,
            to_code_version=2,
            contract_diff=unrelated,
            version=2,
        )
        report = answer.artefact
        attempt = report.attempts[0]

        assert attempt.classification == "regression"
        assert attempt.classified_by == "trace-unchanged"
        assert attempt.diff is None, "a regression is flagged, never repaired"
        assert report.flagged_regressions == 1
        assert report.healed == 0
        assert repo.read(SUITE) == STALE

    async def test_a_test_written_after_the_change_is_flagged_not_repaired(self, tmp_path) -> None:
        """E-25. It traces to what changed because it was written from it, and
        the trace alone would have sent it to be repaired."""
        repo, _ = _prepared(tmp_path)
        target = Ref(kind="generated", code_version=3, path=str(repo.root))
        report_in = _report()
        report_in.suites[0].cases[0].since_version = 3

        answer = await C3("scripted", repairer=_scripted(HONEST)).heal(
            target,
            report_in,
            from_code_version=2,
            to_code_version=3,
            contract_diff=_changed(),
            version=3,
            from_test_version=2,
        )
        attempt = answer.artefact.attempts[0]

        assert attempt.classification == "regression"
        assert attempt.classified_by == "written-after-change"
        assert attempt.diff is None, "flagged, never repaired"
        assert repo.read(SUITE) == STALE

    async def test_an_undecided_failure_is_not_repaired_either(self, tmp_path) -> None:
        """The referee could not settle it either, so it stays undecided and
        reaches a person."""
        repo, _ = _prepared(tmp_path)
        target = Ref(kind="generated", code_version=2, path=str(repo.root))
        report_in = _report()
        report_in.suites[0].cases[0].traces = TestTrace()
        undecided = build_referee(_Referee("undecided").model())

        answer = await C3("scripted", repairer=_scripted(HONEST), referee=undecided).heal(
            target,
            report_in,
            from_code_version=1,
            to_code_version=2,
            contract_diff=_changed(),
            version=2,
        )
        attempt = answer.artefact.attempts[0]

        assert attempt.classification == "undecided"
        assert attempt.classified_by == "model-referee"
        assert attempt.diff is None
        assert repo.read(SUITE) == STALE


@pytest.mark.sandbox
@needs_npm
class TestAFailureTheRulesCannotClassify:
    """It goes to the referee, which the component builds from its own model.

    The referee was only ever injected, by these tests, so in the pipeline a
    failure that traced to nothing never reached it: every one stayed
    undecided, and the study's rule-decided share had no model share to be
    measured against.
    """

    async def test_goes_to_a_referee_the_component_builds_from_its_model(self, tmp_path) -> None:
        repo, _ = _prepared(tmp_path)
        target = Ref(kind="generated", code_version=2, path=str(repo.root))
        report_in = _report()
        report_in.suites[0].cases[0].traces = TestTrace()
        scripted = _Referee("regression")

        # No referee given: the component has only its model to build one from.
        answer = await C3(scripted.model()).heal(
            target,
            report_in,
            from_code_version=1,
            to_code_version=2,
            contract_diff=_changed(),
            version=2,
        )
        attempt = answer.artefact.attempts[0]

        assert len(scripted.prompts) == 1, "the referee was never asked"
        assert (attempt.classification, attempt.classified_by) == ("regression", "model-referee")
        assert attempt.evidence.cited_diff_span == changes_for(_changed(), None)[0].line
        assert attempt.diff is None, "a regression is flagged, never repaired"

    async def test_asks_the_model_nothing_when_nothing_changed(self, tmp_path) -> None:
        """With no change to cite there is nothing to judge, and no tokens to spend."""
        repo, _ = _prepared(tmp_path)
        target = Ref(kind="generated", code_version=2, path=str(repo.root))
        report_in = _report()
        report_in.suites[0].cases[0].traces = TestTrace()
        scripted = _Referee("brittle")

        answer = await C3(scripted.model()).heal(
            target,
            report_in,
            from_code_version=1,
            to_code_version=2,
            contract_diff=ContractDiff(from_version=1, to_version=2),
            version=2,
        )
        attempt = answer.artefact.attempts[0]

        assert scripted.prompts == []
        assert attempt.classification == "undecided"
        assert "nothing changed" in attempt.evidence.referee_reasoning


class TestWhichRefusalAGuardFailureIs:
    """The name a refusal gets is what the study counts it as, so the order the
    checks are asked in decides the headline number.

    A repair that does not pass cannot kill a mutant either: a test that was
    already failing cannot be shown to notice a fault introduced afterwards. So
    asking the mutant question first labels every ineffective repair
    `kills-no-mutant`, which the study files as a caught cheat. The first live
    healing run on generated code reported six caught cheats where the truth was
    six repairs that did not work, with the guard's own detail saying so on each.
    """

    def test_a_repair_that_does_not_pass_is_not_called_a_caught_cheat(self) -> None:
        """The exact combination of the six live refusals."""
        checks = [
            GuardCheck(name="test-code-only", passed=True, detail="no production file changed"),
            GuardCheck(
                name="passes-unchanged-code", passed=False, detail="the repair did not work"
            ),
            GuardCheck(
                name="kills-a-mutant", passed=False, detail="it was failing before anything broke"
            ),
        ]

        assert refusal_for(checks) == "still-failing"

    def test_a_repair_that_passes_and_notices_nothing_is_the_cheat(self) -> None:
        checks = [
            GuardCheck(name="test-code-only", passed=True, detail="reported"),
            GuardCheck(name="passes-unchanged-code", passed=True, detail="green"),
            GuardCheck(name="kills-a-mutant", passed=False, detail="killed nothing"),
        ]

        assert refusal_for(checks) == "kills-no-mutant"

    def test_editing_production_code_outranks_both(self) -> None:
        checks = [
            GuardCheck(name="test-code-only", passed=False, detail="two files changed"),
            GuardCheck(name="passes-unchanged-code", passed=False, detail="reported"),
            GuardCheck(name="kills-a-mutant", passed=False, detail="reported"),
        ]

        assert refusal_for(checks) == "touched-production-code"

    def test_a_repair_the_guard_found_no_code_for_is_its_limit_not_a_cheat(self) -> None:
        checks = [
            GuardCheck(name="test-code-only", passed=True, detail="reported"),
            GuardCheck(name="passes-unchanged-code", passed=True, detail="green"),
            GuardCheck(name="kills-a-mutant", passed=False, detail="no code it reaches"),
        ]

        assert refusal_for(checks, unchecked=True) == "no-code-to-check"

    def test_a_repair_that_does_not_pass_is_still_failing_whatever_was_found(self) -> None:
        checks = [
            GuardCheck(name="test-code-only", passed=True, detail="reported"),
            GuardCheck(name="passes-unchanged-code", passed=False, detail="red"),
            GuardCheck(name="kills-a-mutant", passed=False, detail="no code it reaches"),
        ]

        assert refusal_for(checks, unchecked=True) == "still-failing"

    def test_all_three_passing_is_no_refusal(self) -> None:
        checks = [
            GuardCheck(name=one, passed=True, detail="green")
            for one in ("test-code-only", "passes-unchanged-code", "kills-a-mutant")
        ]

        assert refusal_for(checks) is None


class TestFindingTheTestTheReportNames:
    """A report names a test as the runner does and a file names it by its `it`
    literal, and the two are not the same string.

    Vitest reports the `describe` and the `it` joined by a space. So looking the
    report's name up among the file's names misses every test inside a
    `describe`, which is every test this platform generates. On the first live
    healing run against generated code all six repairs were refused with "the
    file has no test named ...", after the model had written a repair for each:
    the drafts were fine and the lookup could not find where to put them.

    Checkpoint 2 never showed it. Its scenario writes tests at the top level
    with no `describe` around them, so there the two names are the same string.
    """

    NESTED = (
        'describe("As a user, I can open a task", () => {\n'
        '  it("US-3 AC-3-2: the name is shown", async () => {\n'
        '    expect(shown()).toBe("Buy milk");\n'
        "  });\n"
        "});\n"
    )
    REPORTED = "As a user, I can open a task US-3 AC-3-2: the name is shown"

    def test_the_runners_name_resolves_to_the_files_name(self) -> None:
        assert named_in(self.NESTED, self.REPORTED) == "US-3 AC-3-2: the name is shown"

    def test_a_repair_lands_in_the_body_it_was_written_for(self) -> None:
        spliced = splice(self.NESTED, self.REPORTED, 'expect(shown()).toBe("Milk");')

        assert spliced is not None
        assert 'toBe("Milk")' in spliced
        assert 'toBe("Buy milk")' not in spliced
        assert spliced.count("it(") == 1, "no test was added or lost"

    def test_a_name_with_no_describe_around_it_still_works(self) -> None:
        flat = 'it("totals the basket", async () => {\n  expect(1).toBe(2);\n});\n'

        assert named_in(flat, "totals the basket") == "totals the basket"

    def test_a_test_the_file_really_does_not_have_is_still_refused(self) -> None:
        assert named_in(self.NESTED, "some other suite a different test") is None
        assert splice(self.NESTED, "some other suite a different test", "x;") is None

    def test_a_real_repair_inside_a_describe_is_not_read_as_a_deletion(self) -> None:
        """Every check in `repair_problems` compares names, so resolving the
        target is not a detail: without it, a test that is plainly still there
        reads as deleted and a correct repair is refused for cheating."""
        original = self.NESTED
        repaired = self.NESTED.replace('toBe("Buy milk")', 'toBe("Milk")')

        assert repair_problems(original, repaired, target=self.REPORTED) == []

    def test_and_a_deletion_inside_a_describe_is_still_refused(self) -> None:
        emptied = 'describe("As a user, I can open a task", () => {\n});\n'

        [problem] = repair_problems(self.NESTED, emptied, target=self.REPORTED)

        assert "is gone from the file" in problem

    def test_a_name_with_a_quote_survives_the_round_trip(self) -> None:
        """`body_spans` and `written_names` have to key alike or every lookup
        between them raises. They did not, and the live retry crashed on a
        criterion quoting two task names."""
        quoted = 'US-2 AC-2-2: the names "Buy milk" and "Call plumber"'
        source = (
            'describe("S", () => {\n'
            f"  it({json.dumps(quoted)}, async () => {{ expect(1).toBe(2); }});\n"
            "});\n"
        )

        assert written_names(source) == [quoted]
        assert list(body_spans(source)) == [quoted]
        assert splice(source, f"S {quoted}", "expect(1).toBe(1);") is not None

    def test_two_tests_whose_names_end_alike_are_refused_rather_than_guessed(self) -> None:
        """Splicing a repair into the wrong test is worse than not repairing."""
        ambiguous = (
            'describe("one", () => {\n  it("the name is shown", async () => { expect(1).toBe(1); });\n});\n'
            'describe("two", () => {\n  it("the name is shown", async () => { expect(2).toBe(2); });\n});\n'
        )

        assert named_in(ambiguous, "three the name is shown") is None


class TestWhatTheRepairAddsNotWhatTheFileHad:
    """A skip, a declaration or an `.only` is refused when the repair adds it.

    The check read the whole file. A carried file declares, as `it.todo`, the
    criteria its version has not written yet, and a person's quarantine is an
    `it.skip`, so every draft for such a file was refused however good it was.
    On E-2's second pipeline run that was all 16 drafts for 8 stale tests, and
    the report counted them as the model's silence.
    """

    CARRIED = (
        'describe("As a person, I can open a task", () => {\n'
        '  it("US-4 AC-4-1: the name is shown", async () => {\n'
        '    const response = await request(app).get("/tasks/1");\n'
        "    expect(response.status).toBe(200);\n"
        "  });\n"
        '  it.todo("US-4 AC-4-3: the details carry the name \\"Buy milk\\"");\n'
        "});\n"
    )
    REPORTED = "As a person, I can open a task US-4 AC-4-1: the name is shown"
    BODY = (
        '  it("US-4 AC-4-1: the name is shown", async () => {\n'
        '    const response = await request(app).get("/tasks/1");\n'
        "    expect(response.status).toBe(200);\n"
        "  });\n"
    )
    SWITCHED_OFF = "a skipped or declared test is not a repaired one"

    def test_a_file_that_declares_an_unwritten_criterion_can_be_repaired(self) -> None:
        repaired = self.CARRIED.replace('"/tasks/1"', '"/to-dos/1"')

        assert repair_problems(self.CARRIED, repaired, target=self.REPORTED) == []

    def test_a_quarantined_test_beside_it_does_not_block_the_repair(self) -> None:
        quarantined = self.CARRIED.replace(
            '  it.todo("US-4 AC-4-3: the details carry the name \\"Buy milk\\"");\n',
            '  it.skip("US-4 AC-4-2: another task is not shown", async () => {\n'
            "    expect(shown()).toBe(false);\n"
            "  });\n",
        )
        repaired = quarantined.replace('"/tasks/1"', '"/to-dos/1"')

        assert repair_problems(quarantined, repaired, target=self.REPORTED) == []

    def test_declaring_the_test_instead_of_repairing_it_is_still_refused(self) -> None:
        declared = self.CARRIED.replace(self.BODY, '  it.todo("US-4 AC-4-1: the name is shown");\n')

        assert self.SWITCHED_OFF in repair_problems(self.CARRIED, declared, target=self.REPORTED)

    def test_skipping_the_test_is_still_refused(self) -> None:
        skipped = self.CARRIED.replace('it("US-4 AC-4-1', 'it.skip("US-4 AC-4-1')

        assert self.SWITCHED_OFF in repair_problems(self.CARRIED, skipped, target=self.REPORTED)

    def test_trading_one_declaration_for_another_is_still_refused(self) -> None:
        """The count stays level and the target is declared all the same."""
        traded = self.CARRIED.replace(
            '  it.todo("US-4 AC-4-3: the details carry the name \\"Buy milk\\"");\n', ""
        ).replace(self.BODY, '  it.todo("US-4 AC-4-1: the name is shown");\n')

        assert self.SWITCHED_OFF in repair_problems(self.CARRIED, traded, target=self.REPORTED)

    def test_adding_only_is_still_refused(self) -> None:
        only = self.CARRIED.replace('it("US-4 AC-4-1', 'it.only("US-4 AC-4-1')

        assert "`.only` disables every other test in the file" in repair_problems(
            self.CARRIED, only, target=self.REPORTED
        )


class TestARepairThatWouldNotParse:
    """Refused before the guard, with where, so the model gets its second try (E-30).

    The guard's refusal is final: a repaired file that does not parse runs no
    test, and was refused as still failing with no second draft. Brackets are
    read outside strings and comments, and only a mismatch the repair made
    counts: a file the reader cannot follow already must not block every
    repair to it, which is what the skip check did (E-27).
    """

    FILE = (
        'import { describe, expect, it } from "vitest";\n'
        'import { total } from "../basket";\n'
        "\n"
        'describe("basket", () => {\n'
        '  it("adds up the lines", () => {\n'
        "    expect(total([1.005, 2])).toBe(3.005);\n"
        "  });\n"
        "});\n"
    )
    TARGET = "basket adds up the lines"

    def test_a_brace_left_open_is_refused_with_where(self) -> None:
        repaired = self.FILE.replace(
            "    expect(total([1.005, 2])).toBe(3.005);\n",
            "    if (total([]) === 0) {\n    expect(total([1.005, 2])).toBe(3.01);\n",
        )

        [problem] = repair_problems(self.FILE, repaired, target=self.TARGET)

        assert "brackets" in problem
        # Where they stop matching: the `});` that should close the test's
        # brace arrives while the `if` block's is still open.
        assert "line 8: `)` where `}` was expected" in problem

    def test_brackets_in_strings_and_comments_do_not_count(self) -> None:
        repaired = self.FILE.replace(
            "    expect(total([1.005, 2])).toBe(3.005);\n",
            "    // a ) or a } in a comment is not code\n"
            "    /* nor ] in this one */\n"
            '    expect(String(total([1.005, 2]))).not.toBe("{[(");\n',
        )

        assert repair_problems(self.FILE, repaired, target=self.TARGET) == []

    def test_a_file_the_reader_cannot_follow_does_not_block_its_repairs(self) -> None:
        """A regular expression is not read as one, so its bracket counts."""
        original = self.FILE + 'it("finds a bracket", () => {\n  expect("(").toMatch(/\\(/);\n});\n'
        repaired = original.replace("toBe(3.005)", "toBe(3.01)")

        assert repair_problems(original, repaired, target=self.TARGET) == []


class TestTheMinimalRepairShape:
    """Asking for one body instead of the whole file.

    Epoch 1 recorded the pinned free model answering a whole file repair with a
    single import line, twice. That is a failure of transcription rather than
    of judgement, and this shape removes the transcription: the model writes a
    body and this component puts it where the old one was, so "change nothing
    else" stops being something a model can get wrong.

    Both shapes are kept and the shape is recorded per repair, because whether
    epoch 1 failed on the model or on the prompt is not knowable in advance and
    the only honest way to answer it is to run both and compare.
    """

    FILE = (
        'import { describe, expect, it } from "vitest";\n'
        'import { total } from "../basket";\n'
        "\n"
        'describe("basket", () => {\n'
        '  it("adds up the lines", () => {\n'
        "    expect(total([1.005, 2])).toBe(3.005);\n"
        "  });\n"
        "\n"
        '  it("is zero when empty", () => {\n'
        "    expect(total([])).toBe(0);\n"
        "  });\n"
        "});\n"
    )

    def _case(self):
        from sdlc_contracts import TestCase

        return TestCase(
            id="basket.test.ts::adds up the lines",
            name="adds up the lines",
            kind="unit",
            origin="filled",
            outcome="failed",
            message="expected 3.01 to be 3.005",
        )

    def test_the_rest_of_the_file_is_unchanged_by_construction(self) -> None:
        """The property the whole shape exists for: not checked afterwards,
        impossible beforehand."""
        from c3.heal.repair import splice

        after = splice(self.FILE, "adds up the lines", "expect(total([1.005, 2])).toBe(3.01);")

        assert after is not None
        assert 'it("is zero when empty"' in after
        assert "expect(total([])).toBe(0);" in after
        assert "toBe(3.005)" not in after
        assert "toBe(3.01)" in after

    def test_a_body_that_arrives_with_its_braces_is_still_a_body(self) -> None:
        """A model told to write the statements between the braces will
        sometimes include them, and refusing that would be refusing a correct
        answer over punctuation."""
        from c3.heal.repair import splice

        with_braces = splice(self.FILE, "is zero when empty", "{ expect(total([])).toBe(0); }")
        without = splice(self.FILE, "is zero when empty", "expect(total([])).toBe(0);")

        assert with_braces == without

    def test_a_body_that_arrives_with_only_its_closing_brace_is_still_a_body(self) -> None:
        """The arrow function's own brace, which the file already has (E-30).
        Every refused repair of epoch 17 ended with one, the file stopped
        parsing, and the guard refused six repairs that were otherwise sound."""
        from c3.heal.repair import splice

        closing_only = splice(self.FILE, "is zero when empty", "expect(total([])).toBe(0);\n}")
        without = splice(self.FILE, "is zero when empty", "expect(total([])).toBe(0);")

        assert closing_only == without

    def test_a_body_that_arrives_with_only_its_opening_brace_is_still_a_body(self) -> None:
        from c3.heal.repair import splice

        opening_only = splice(self.FILE, "is zero when empty", "{\nexpect(total([])).toBe(0);")
        without = splice(self.FILE, "is zero when empty", "expect(total([])).toBe(0);")

        assert opening_only == without

    def test_a_body_that_ends_in_a_block_keeps_its_brace(self) -> None:
        from c3.heal.repair import bracket_problem, splice

        body = "if (total([]) === 0) {\n  expect(total([])).toBe(0);\n}"

        after = splice(self.FILE, "is zero when empty", body)

        assert after is not None
        assert bracket_problem(after) is None
        assert after.count("if (total([]) === 0) {") == 1

    def test_a_brace_in_a_string_is_not_punctuation(self) -> None:
        from c3.heal.repair import splice

        after = splice(self.FILE, "is zero when empty", 'expect(String(total([]))).not.toBe("}");')

        assert after is not None
        assert 'not.toBe("}");' in after

    def test_a_test_the_file_does_not_have_is_refused_rather_than_invented(self) -> None:
        from c3.heal.repair import splice

        assert splice(self.FILE, "a test nobody wrote", "expect(1).toBe(1);") is None

    def test_the_splice_keeps_the_file_readable(self) -> None:
        """A repair a person has to reformat before reading is a repair whose
        diff nobody reads."""
        from c3.heal.repair import splice

        after = splice(self.FILE, "adds up the lines", "expect(total([1.005, 2])).toBe(3.01);")

        assert "    expect(total([1.005, 2])).toBe(3.01);" in after
        assert after.count("{") == after.count("}")

    async def test_the_answer_epoch_17_refused_now_reaches_the_guard_whole(self) -> None:
        """E-30: the body ended with the brace the file already has."""
        from c3.heal.repair import bracket_problem, build_repairer, repair, splice

        scripted = _model({"body": "expect(total([1.005, 2])).toBe(3.01);\n}"})

        outcome = await repair(
            build_repairer(scripted, shape="minimal"),
            self._case(),
            source=self.FILE,
            path=SUITE,
            shape="minimal",
        )

        assert outcome.repaired
        assert bracket_problem(outcome.content or "") is None
        assert outcome.content == splice(
            self.FILE, "adds up the lines", "expect(total([1.005, 2])).toBe(3.01);"
        )

    async def test_a_body_whose_brackets_do_not_match_gets_a_second_try(self) -> None:
        """Refused before the guard, whose refusal is final, so the model is
        told why and answers again."""
        from c3.heal.repair import build_repairer, repair

        scripted = _answers(
            {"body": "if (total([]) === 0) {\nexpect(total([1.005, 2])).toBe(3.01);"},
            {"body": "expect(total([1.005, 2])).toBe(3.01);"},
        )

        outcome = await repair(
            build_repairer(scripted, shape="minimal"),
            self._case(),
            source=self.FILE,
            path=SUITE,
            shape="minimal",
        )

        assert outcome.repaired
        assert outcome.attempts == 2
        assert any("brackets" in problem for problem in outcome.drafts[0].problems)

    async def test_a_weakening_still_gets_past_the_static_checks(self) -> None:
        """This is the property to protect, and it is the opposite of the
        obvious one.

        `toBeDefined()` is deliberately not a static refusal. It is well formed,
        it keeps every test, it asserts something, and it cannot fail: it is the
        exact case the mutant check exists to catch, and the guard catching it
        is the contribution. If changing the prompt shape had quietly moved that
        detection into the static layer, Checkpoint 2 would still pass while
        proving something much weaker than it claims.
        """
        from c3.heal.repair import build_repairer, repair

        scripted = _model({"body": "expect(total([1.005, 2])).toBeDefined();"})

        outcome = await repair(
            build_repairer(scripted, shape="minimal"),
            self._case(),
            source=self.FILE,
            path=SUITE,
            shape="minimal",
        )

        assert outcome.repaired, "the static checks accept it, exactly as they do a whole file"
        assert "toBeDefined" in (outcome.content or "")

    async def test_an_assertion_that_cannot_fail_by_construction_is_refused_here(self) -> None:
        """What the static layer does catch, proven to still run under the new
        shape rather than assumed to."""
        from c3.heal.repair import build_repairer, repair

        scripted = _model({"body": "expect(true).toBe(true);"})

        outcome = await repair(
            build_repairer(scripted, shape="minimal"),
            self._case(),
            source=self.FILE,
            path=SUITE,
            shape="minimal",
        )

        assert not outcome.repaired
        assert outcome.refusal_reason == "assertion-weakened"
        assert outcome.shape == "minimal"

    async def test_a_real_repair_is_accepted_and_says_which_shape_made_it(self) -> None:
        from c3.heal.repair import build_repairer, repair

        scripted = _model({"body": "expect(total([1.005, 2])).toBe(3.01);"})

        outcome = await repair(
            build_repairer(scripted, shape="minimal"),
            self._case(),
            source=self.FILE,
            path=SUITE,
            shape="minimal",
        )

        assert outcome.repaired
        assert outcome.shape == "minimal"
        assert 'it("is zero when empty"' in (outcome.content or "")
        assert "toBe(3.01)" in (outcome.content or "")

    async def test_the_recorded_shape_is_what_answered_not_what_was_asked(self) -> None:
        """A caller can point a whole file agent at a minimal prompt. The
        report carries what arrived, because an acceptance rate filed under the
        wrong shape is worse than none: it will be compared."""
        from c3.heal.repair import build_repairer, repair

        whole_file = _model({"content": self.FILE.replace("3.005", "3.01")})

        outcome = await repair(
            build_repairer(whole_file, shape="whole-file"),
            self._case(),
            source=self.FILE,
            path=SUITE,
            shape="minimal",
        )

        assert outcome.shape == "whole-file"

    def test_the_prompt_never_asks_the_model_to_reproduce_the_file(self) -> None:
        """The single change that separates this shape from the one that
        measured badly."""
        from c3.heal.repair import MINIMAL_INSTRUCTIONS, prompt_for
        from sdlc_contracts import TestCase

        case = TestCase(
            id="x::adds up the lines",
            name="adds up the lines",
            kind="unit",
            origin="filled",
            outcome="failed",
            message="expected 3.01 to be 3.005",
        )

        prompt = prompt_for(case, self.FILE, [], shape="minimal")

        assert "for context only" in prompt
        assert "replacement body only" in prompt
        assert "complete file" not in MINIMAL_INSTRUCTIONS


def _model(answer: dict):
    """A model that returns one scripted answer, spending nothing."""
    import json

    from pydantic_ai.messages import ModelResponse, ToolCallPart
    from pydantic_ai.models.function import FunctionModel

    def respond(messages, info):
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, json.dumps(answer))])

    return FunctionModel(respond)


def _answers(*answers: dict):
    """A model that returns each scripted answer in turn, spending nothing."""
    import json

    from pydantic_ai.messages import ModelResponse, ToolCallPart
    from pydantic_ai.models.function import FunctionModel

    waiting = list(answers)

    def respond(messages, info):
        return ModelResponse(
            parts=[ToolCallPart(info.output_tools[0].name, json.dumps(waiting.pop(0)))]
        )

    return FunctionModel(respond)
