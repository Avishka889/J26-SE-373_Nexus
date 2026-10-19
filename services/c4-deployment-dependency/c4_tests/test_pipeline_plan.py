"""The deploy plan, and the stage that answers with the configuration, the plan and the layer.

The plan is read by a person before anything is created and executed by the
orchestrator's saga, so what is checked is what the saga depends on: every step
that moves traffic says how traffic is moved back, compensation is written only
where there is something to undo, and the targets name what will exist.
"""

import pytest
from c4.harness.staging import reads_database
from c4.pipeline.plan import deploy_plan
from c4.service import C4
from sdlc_contracts import DeployPlan, PipelineConfig, RiskReport

from .test_pipeline_generation import (
    CONTRACT,
    ROUTER,
    SUPERTEST,
    TRACKER,
    UPDATES,
    _generate,
    _no_linters,
    _scripted,
)

PROJECT = "p_ea2157d82c6a"


def _plan(target: str, **kw) -> DeployPlan:
    return deploy_plan(
        _generate(settings={"project_slug": "p-ea2157d82c6a"}),
        project_id=PROJECT,
        release_target=target,
        github_protection=kw.get("protection"),
        version=2,
        reads_database=kw.get("reads_database", False),
    )


class TestWhatTheRollbackNoteSaysOfTheRecords:
    """The plan's note always said the app keeps its data in memory, whatever
    the code did, while the rollback plan beside it said a database (review
    item C4-12). Both now go by the same rule."""

    def test_code_that_reads_a_database_and_goes_to_the_cloud_is_told_of_it(self) -> None:
        note = _plan("cloud", reads_database=True).rollback.note
        assert "keeps its records in the project's database" in note
        assert "may not read records the newer one wrote" in note
        assert "keeps its data in memory, so any restart" not in note

    def test_code_that_keeps_memory_is_told_a_restart_empties_it(self) -> None:
        note = _plan("cloud").rollback.note
        assert "keeps its data in memory, so any restart" in note

    def test_a_local_release_has_no_database_whatever_the_code_reads(self) -> None:
        note = _plan("local", reads_database=True).rollback.note
        assert "keeps its data in memory, so any restart" in note


class TestTheLocalPlan:
    def test_traffic_moves_once_and_only_a_person_moves_it_back(self) -> None:
        plan = _plan("local")
        assert [step.id for step in plan.steps] == ["start", "check", "switch", "verify"]
        [moving] = [step for step in plan.steps if step.moves_traffic]
        assert moving.id == "switch" and "once a person approves" in (moving.compensation or "")
        assert plan.environment_protection.github == "not-applicable"

    def test_the_target_is_the_one_process_app_in_the_candidates_image(self) -> None:
        [target] = _plan("local").targets
        assert (target.role, target.provider) == ("app", "local-docker")
        assert "sdlc-c4-p-ea2157d82c6a:v2" in target.resource
        assert target.runtime == "node 22.6+ (strip types)"


class TestTheCloudPlan:
    def test_the_commit_is_tested_and_built_before_anything_moves_traffic(self) -> None:
        """The backend went live on Render before the workflow tested the commit or
        built its frontend (review item C4-8): a failing test then needed a rollback."""
        plan = _plan("cloud")
        assert [step.id for step in plan.steps] == [
            "commit",
            "secrets",
            "test",
            "backend",
            "dispatch",
            "verify",
        ]
        test = next(step for step in plan.steps if step.id == "test")
        assert test.provider == "github" and not test.moves_traffic
        assert (test.depends_on, plan.steps[3].depends_on) == ("secrets", "test")
        assert [step.id for step in plan.steps if step.moves_traffic] == ["backend", "dispatch"]
        backend = next(step for step in plan.steps if step.id == "backend")
        assert backend.provider == "render", "the platform deploys it through Render's API"
        commit = plan.steps[0]
        assert commit.compensation is None, "a commit serves nothing and is not rewritten"
        assert {(t.role, t.provider) for t in plan.targets} == {
            ("backend", "render"),
            ("frontend", "vercel"),
        }

    def test_what_github_enforces_is_recorded_and_defaults_to_nothing(self) -> None:
        assert _plan("cloud").environment_protection.github == "unavailable-private-repo"
        assert _plan("cloud", protection="configured").environment_protection.github == (
            "configured"
        )

    def test_an_unsupported_stack_has_no_plan(self) -> None:
        with pytest.raises(ValueError, match="nothing was generated"):
            deploy_plan(
                _generate(stack_id="react-spring-postgres"),
                project_id=PROJECT,
                release_target="local",
                github_protection=None,
                version=2,
            )


class TestTheStage:
    async def test_the_component_answers_with_the_config_the_plan_and_the_layer(self) -> None:
        component = C4("deepseek:deepseek-flash", resolver=_scripted(), validator=_no_linters)
        answer = await component.generate_pipeline(
            TRACKER,
            UPDATES,
            RiskReport.model_construct(),
            stack_id="mern",
            contract=CONTRACT,
            release_target="local",
            included=[SUPERTEST.id, ROUTER.id],
            settings={"project_id": PROJECT, "project_slug": "p-ea2157d82c6a"},
            version=2,
            code_version=3,
        )
        config = answer.artefact
        assert isinstance(config, PipelineConfig) and config.stack.supported
        plan = DeployPlan.model_validate(answer.notes["plan"])
        assert plan.project_id == PROJECT and plan.candidate_hash == config.candidate_hash
        assert set(answer.notes["files"]) >= {f.path for f in config.files} | {"package-lock.json"}
        assert answer.summary.startswith("7 files for the one-process MERN layout")

    async def test_the_plan_s_note_goes_by_what_the_code_reads(self) -> None:
        component = C4("deepseek:deepseek-flash", resolver=_scripted(), validator=_no_linters)

        async def note(files: dict[str, str]) -> str:
            answer = await component.generate_pipeline(
                files,
                UPDATES,
                RiskReport.model_construct(),
                stack_id="mern",
                contract=CONTRACT,
                release_target="cloud",
                included=[SUPERTEST.id, ROUTER.id],
                settings={"project_id": PROJECT, "project_slug": "p-ea2157d82c6a"},
                version=2,
                code_version=3,
            )
            return DeployPlan.model_validate(answer.notes["plan"]).rollback.note

        assert reads_database(TRACKER) is False
        reading = {**TRACKER, "apps/api/src/storage.ts": "const url = process.env.MONGODB_URL;\n"}
        assert reads_database(reading) is True
        assert "keeps its data in memory" in await note(TRACKER)
        assert "keeps its records in the project's database" in await note(reading)

    async def test_an_unsupported_stack_answers_with_no_plan_and_no_files(self) -> None:
        component = C4("deepseek:deepseek-flash", resolver=_scripted(), validator=_no_linters)
        answer = await component.generate_pipeline(
            TRACKER,
            UPDATES,
            RiskReport.model_construct(),
            stack_id="react-spring-postgres",
            contract=None,
            release_target="local",
            included=[],
            settings={"project_id": PROJECT},
            version=2,
            code_version=3,
        )
        assert not answer.artefact.stack.supported
        assert "plan" not in answer.notes and answer.notes["files"] == {}
