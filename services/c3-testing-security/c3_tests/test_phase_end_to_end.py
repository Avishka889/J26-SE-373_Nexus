"""Generate, run, measure: the testing phase against a real generated project.

Everything above this file tests one piece. This runs the three stages in the
order the graph runs them, against the application the code generator actually
produced, and asserts the thing the phase exists to make true: what the report
says happened is what happened.

Slow and marked `sandbox`. It installs a monorepo, runs two suites and mutates
a scoped file set, which is the only way to find out whether any of it works.
"""

import shutil

import pytest
from c3.harness import resolve
from c3.service import C3
from sdlc_contracts import (
    AcceptanceCriterion,
    SprintPlan,
    TestReport,
    UserStory,
    VelocityAssumption,
)
from sdlc_contracts.openapi import to_openapi

from .test_generate import Ref

needs_npm = pytest.mark.skipif(shutil.which("npm") is None, reason="needs node and npm")


def _checkout(tmp_path):
    from c2.codegen.monorepo import generate_monorepo
    from c2.contract.rule_arm import generate_rule_contract
    from c2_tests.design_fixture import graph, scope, wireframes

    contract = generate_rule_contract(1, graph(), wireframes(), scope())
    monorepo = generate_monorepo(
        "Phase", contract, wireframes(), scope(), design_version=1, arm="rule"
    )
    checkout = tmp_path / "checkout"
    for generated in monorepo.files:
        target = checkout / generated.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(generated.content)

    story = scope().stories[0]
    sprint = SprintPlan(
        sprint_name="Sprint 1",
        goal="the fixture",
        estimated_points=story.points,
        velocity_assumption=VelocityAssumption(points=10, basis="assumed"),
        proposed=[
            UserStory(
                id=story.id,
                title=story.title,
                epic="Fixture",
                points=story.points,
                priority="must",
                traces=list(story.traces.requirement_ids),
                acceptance=[
                    # `AC-<story number>-<n>`, the shape C1 issues.
                    AcceptanceCriterion(
                        id=f"AC-{story.id.split('-')[1]}-1",
                        given="the API is running",
                        when="the collection is requested",
                        then="it answers with a list",
                    )
                ],
            )
        ],
    )
    return checkout, contract, sprint


@pytest.mark.sandbox
@needs_npm
class TestTheWholePhase:
    async def test_generate_then_run_then_measure(self, tmp_path) -> None:
        checkout, contract, sprint = _checkout(tmp_path)
        target = Ref(kind="generated", code_version=1, path=str(checkout))
        component = C3("no model")

        # ---- generation: files exist, nothing has run
        generated = await component.generate_tests(
            target, sprint, contract, to_openapi(contract, title="app"), version=1
        )
        before = TestReport.model_validate(generated.notes["report"])
        assert before.total > 0
        assert before.not_run == before.total, "generation has run nothing, and says so"
        assert generated.files, "the rules should have written something"

        # ---- execution: the outcomes are what happened
        run = await component.run_tests(target, version=1, declared=before)
        after: TestReport = run.artefact
        assert after.version == 1

        # And what each test was written from survived the stage that replaced
        # the report. A runner reports names and outcomes; it knows nothing about
        # stories or criteria, so this stage used to hand the healing classifier
        # cases with empty traces and the classifier answered `undecided` on
        # every real failure for want of a first signal. Nothing failed, which is
        # why it went unnoticed, and `untraced` is the count that says so.
        assert after.untraced == 0, (
            f"{after.untraced} of this component's own tests reached the report "
            "with nothing to trace to"
        )
        traced = {case.id: case.traces for suite in after.suites for case in suite.cases}
        criteria = [t.criterion_id for t in traced.values() if t.criterion_id]
        assert criteria, "no executed case names the criterion it was written for"
        assert all(one.startswith("AC-") for one in criteria), criteria
        assert after.total >= before.total, "everything generated should have been collected"
        assert after.not_run == 0, "a suite that ran has no unrun cases left"
        assert after.passed > 0
        assert after.coverage, "coverage was asked for and should be there"

        # Both apps ran. A phase that only ever ran one of them would report
        # the other's tests as not existing.
        suites = {suite.path.split("/")[1] for suite in after.suites}
        assert suites == {"api", "web"}

        # And the provenance survived: the oracle files are this component's,
        # the contract tests came with the repository.
        origins = {suite.path: {case.origin for case in suite.cases} for suite in after.suites}
        oracle = [path for path in origins if path.endswith(".oracle.test.ts")]
        assert oracle and all(origins[path] == {"skeleton"} for path in oracle)
        upstream = [path for path in origins if path.endswith(".contract.test.ts")]
        assert upstream and all(origins[path] == {"upstream"} for path in upstream)

        # ---- quality: a real mutation score over the code the tests touched
        scope = sorted({entry.module for entry in after.coverage if entry.lines_covered > 0})
        assert scope, "something should have been covered"
        measured = await component.measure_quality(target, after, scope, version=1)
        report: TestReport = measured.artefact

        assert report.mutation is not None, measured.summary
        assert report.mutation.total > 0
        assert report.mutation_skipped_reason == ""
        assert report.mutation.tool.startswith("stryker")

        # And the run that produced the score also said which tests kill
        # nothing, per arm. This is the detection half of the weak fill gate,
        # and it costs nothing: the same pass answers both questions.
        counts = measured.notes["killsNothing"]
        assert isinstance(counts, dict), counts
        weak = [f for f in report.quality if f.rule == "kills-no-mutant"]
        print(f"\ntests that kill nothing, per arm: {counts}")
        for finding in weak:
            print(f"  {finding.path.split('/')[-1]} :: {finding.test[:60]}")
        assert all(finding.observed for finding in weak)
        # Every accusation names a test the report actually carries.
        names = {case.name for suite in report.suites for case in suite.cases}
        assert {finding.test for finding in weak} <= names
        # The scope travels with the score, because a mutation score without
        # the set it was measured over is not a number anybody can use.
        assert report.mutation.scope == scope

    async def test_a_red_suite_is_reported_and_stops_the_mutation_pass(self, tmp_path) -> None:
        """Both halves of the honest answer in one run: the failure is a
        result, and the missing score has a reason rather than being zero."""
        checkout, contract, sprint = _checkout(tmp_path)
        target = Ref(kind="generated", code_version=1, path=str(checkout))
        component = C3("no model")
        await component.generate_tests(
            target, sprint, contract, to_openapi(contract, title="app"), version=1
        )
        repo = resolve(target)
        repo.write(
            "apps/api/src/__tests__/red.test.ts",
            "\n".join(
                [
                    'import { expect, it } from "vitest";',
                    'import request from "supertest";',
                    'import { app } from "../app.ts";',
                    'it("expects a status the app does not answer", async () => {',
                    '  const answer = await request(app).get("/orders");',
                    "  expect(answer.status).toBe(418);",
                    "});",
                ]
            ),
        )

        run = await component.run_tests(target, version=2)
        after: TestReport = run.artefact

        assert after.failed == 1
        failing = [case for case in after.cases if case.outcome == "failed"]
        assert "418" in failing[0].message

        scope = sorted({entry.module for entry in after.coverage if entry.lines_covered > 0})
        measured = await component.measure_quality(target, after, scope, version=2)
        report: TestReport = measured.artefact

        assert report.mutation is None
        assert "green test red" in report.mutation_skipped_reason
        assert "no mutation score" in measured.summary


@pytest.mark.sandbox
@needs_npm
async def test_what_the_rules_added_over_what_the_repository_came_with(tmp_path) -> None:
    """The yield of this phase, measured as the delta rather than as a total.

    The generated repository ships one test per endpoint, so a coverage figure
    for the whole suite says nothing about what this component contributed.
    This runs the repository as it arrived, then again with the rule generated
    tests in it, and reports both. The numbers are printed rather than
    asserted at a threshold: what they should be is a research question, and a
    test that pinned them would be measuring the fixture.
    """
    checkout, contract, sprint = _checkout(tmp_path)
    target = Ref(kind="generated", code_version=1, path=str(checkout))
    component = C3("no model")

    baseline: TestReport = (await component.run_tests(target, version=1)).artefact
    # The same scope for both, or the two scores would be measured over
    # different sets and the difference would mean nothing.
    scope = sorted({entry.module for entry in baseline.coverage if entry.lines_covered > 0})
    # Measured before anything is generated. The first version of this test
    # took the baseline score after the generated files were already in the
    # tree, so both passes ran the same suite and the arm looked like it added
    # nothing. Order is the measurement here.
    before = (await component.measure_quality(target, baseline, scope, version=1)).artefact

    await component.generate_tests(
        target, sprint, contract, to_openapi(contract, title="app"), version=2
    )
    with_rules: TestReport = (await component.run_tests(target, version=2)).artefact
    after = (await component.measure_quality(target, with_rules, scope, version=2)).artefact

    added = with_rules.total - baseline.total
    print(
        f"\nyield of the rule arm on this fixture:"
        f"\n  cases      {baseline.total} -> {with_rules.total} (+{added})"
        f"\n  passing    {baseline.passed} -> {with_rules.passed}"
        f"\n  line cover {baseline.line_coverage}% -> {with_rules.line_coverage}%"
        f"\n  mutation   {before.mutation.score}% -> {after.mutation.score}%"
        f" ({len(before.mutation.killed)} -> {len(after.mutation.killed)} killed"
        f" of {before.mutation.total} mutants)"
    )

    assert added > 0, "the rules should have added tests the repository did not have"
    assert with_rules.line_coverage >= baseline.line_coverage
    # Adding tests cannot kill fewer mutants. This is the invariant; the size
    # of the gain is a research question, and a test that pinned it would be
    # measuring the fixture rather than the arm.
    assert after.mutation is not None and before.mutation is not None
    assert len(after.mutation.killed) >= len(before.mutation.killed)
    # The generated files are attributable in the report, which is what makes
    # the delta a delta rather than an anecdote.
    assert {case.origin for case in with_rules.cases} >= {"upstream", "skeleton"}
