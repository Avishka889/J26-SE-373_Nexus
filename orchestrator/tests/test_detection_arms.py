"""The detection arms a deployment asked for, and the target it points them at."""

from collections.abc import AsyncIterator

import httpx
import pytest
from orchestrator.api.deps import DEV_OWNER_ID
from orchestrator.config import Settings
from orchestrator.db import store
from orchestrator.main import create_app, lifespan_for_tests

from .conftest import needs_db


@pytest.fixture
async def client(settings: Settings) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(settings, lifespan_factory=lifespan_for_tests)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as one:
            one.app = app  # type: ignore[attr-defined]
            created: list[str] = []
            one.created_projects = created  # type: ignore[attr-defined]
            try:
                yield one
            finally:
                async with app.state.pool.connection() as conn:
                    for project_id in created:
                        await store.delete_project(conn, project_id, owner_id=DEV_OWNER_ID)


async def _a_project(client: httpx.AsyncClient) -> str:
    created = await client.post("/projects", json={"name": "Targets", "description": ""})
    project_id = created.json()["id"]
    client.created_projects.append(project_id)  # type: ignore[attr-defined]
    return project_id


#: pydantic-ai's built in test model, which resolves without a provider key.
#:
#: These three tests are about whether naming an arm builds a detector, and
#: nothing about which provider serves it. Naming a real one made them pass only
#: while that provider's key happened to be in the environment: switching the
#: project from Google to DeepSeek left `test_naming_llm_builds_a_detector`
#: failing on a missing GOOGLE_API_KEY, which says nothing about the arms.
NO_PROVIDER_NEEDED = "test"


class TestTheArmsAreADeploymentsDecision:
    def test_the_default_spends_nothing(self) -> None:
        assert Settings().c3_detection_arms == "scanner"

    def test_an_unknown_arm_is_refused_at_startup(self) -> None:
        with pytest.raises(ValueError, match="not arms"):
            Settings(c3_detection_arms="scanner,llmm")

    def test_dropping_the_scanner_is_refused(self) -> None:
        """The free arm is what the paid ones are measured against."""
        with pytest.raises(ValueError, match="compares nothing"):
            Settings(c3_detection_arms="llm,trained")

    def test_naming_llm_builds_a_detector(self) -> None:
        from orchestrator.clients.c3 import InProcessC3

        client = InProcessC3(NO_PROVIDER_NEEDED, arms="scanner,llm")
        assert client._component._detector is not None

    def test_not_naming_it_leaves_the_stage_free(self) -> None:
        from orchestrator.clients.c3 import InProcessC3

        client = InProcessC3(NO_PROVIDER_NEEDED, arms="scanner")
        assert client._component._detector is None
        assert client._component._trained_model_dir == ""

    def test_trained_needs_its_weights_named(self) -> None:
        """Naming the arm without a directory is not the arm."""
        from orchestrator.clients.c3 import InProcessC3

        client = InProcessC3(NO_PROVIDER_NEEDED, arms="scanner,trained")
        assert client._component._trained_model_dir == ""


class TestTheInProcessClientAnswersTheProtocolsShape:
    """The seam, checked against the real component rather than the double.

    Every client here returned `StageOutcome[list[RemediationProposal]]` in its
    annotation and the in process one returned the component's whole artefact,
    so pydantic iterated a model into `('version', 1)` tuples and the stage
    failed on the first live run. The canned client returns an empty list and
    the HTTP client already read `payload["proposals"]`, so no test using
    either could have seen it. This one calls the component.
    """

    async def test_proposals_come_back_as_a_list(self) -> None:
        from dataclasses import dataclass

        from orchestrator.clients.c3 import InProcessC3
        from sdlc_contracts import TestSummary, ValidationReport

        @dataclass
        class Ref:
            kind: str = "sample"
            path: str = "node-sample"
            code_version: int | None = 1

        report = ValidationReport(
            version=1,
            generated_at="2026-09-25 10:00",
            target="the node sample",
            tests=TestSummary(run=1, passed=1, failed=0, skipped=0, line_coverage=80.0),
        )

        outcome = await InProcessC3("google:gemini-3.5-flash-lite").propose_remediation(
            Ref(), report
        )

        assert isinstance(outcome.artefact, list), (
            "the protocol says a list, and a model here iterates into field tuples"
        )
        assert outcome.artefact == [], "no finding, so nothing to propose"

    async def test_the_tests_and_the_contract_reach_the_component(self, monkeypatch) -> None:
        # Every live fix's risk statement said no test covers its lines and no
        # contract moves: neither reached the component (review item C3-11).
        from dataclasses import dataclass
        from datetime import UTC, datetime

        from c3.service import C3
        from orchestrator.clients.c3 import InProcessC3
        from sdlc_contracts import ApiContract, TestReport, TestSummary, ValidationReport

        @dataclass
        class Ref:
            kind: str = "sample"
            path: str = "node-sample"
            code_version: int | None = 1

        seen: dict[str, object] = {}
        original = C3.propose_remediation

        async def recording(self, target, report, *, tests=None, contract=None, **kwargs):
            seen.update(tests=tests, contract=contract)
            return await original(self, target, report, tests=tests, contract=contract, **kwargs)

        monkeypatch.setattr(C3, "propose_remediation", recording)
        report = ValidationReport(
            version=1,
            generated_at="2026-09-25 10:00",
            target="the node sample",
            tests=TestSummary(run=1, passed=1, failed=0, skipped=0, line_coverage=80.0),
        )
        tests = TestReport(
            version=1,
            generated_at=datetime.now(UTC),
            target="the node sample",
            isolation="sandbox",
            mutation_skipped_reason="not this stage's",
        )
        contract = ApiContract(version=1)

        await InProcessC3("google:gemini-3.5-flash-lite").propose_remediation(
            Ref(), report, tests=tests, contract=contract
        )

        assert seen == {"tests": tests, "contract": contract}


@needs_db
class TestChoosingWhatToTest:
    """The choice was in the overlay vocabulary and the graph read it from the
    first day. What was missing was any way for a person to make it, so the one
    target where three detection arms have something to say could be selected
    only by editing the database.
    """

    async def test_the_offer_comes_from_the_component(self, client) -> None:
        project_id = await _a_project(client)

        answer = await client.get(f"/projects/{project_id}/testing/targets")

        assert answer.status_code == 200, answer.text
        offered = {row["id"] for row in answer.json()}
        assert "generated" in offered

    async def test_choosing_one_shows_on_the_snapshot(self, client) -> None:
        project_id = await _a_project(client)

        answer = await client.post(
            f"/projects/{project_id}/testing/target",
            json={"target": "generated", "by": "you"},
        )

        assert answer.status_code == 200, answer.text
        assert answer.json()["target"] == "generated"

    async def test_a_target_nothing_offers_is_refused_here(self, client) -> None:
        """Not three stages into a run, which is where it would otherwise
        surface: a target that does not resolve is a stage that fails after
        somebody chose it."""
        project_id = await _a_project(client)

        answer = await client.post(
            f"/projects/{project_id}/testing/target",
            json={"target": "sample:not-a-sample", "by": "you"},
        )

        assert answer.status_code == 409
        assert "not a target this component offers" in answer.text

    async def test_a_run_waiting_at_its_gate_does_not_block_the_choice(self, client) -> None:
        """It has taken every measurement it is going to take, and this phase's
        gate can stay open for as long as a reader wants to think. The wider
        in flight set blocked the choice until the gate was decided."""
        project_id = await _a_project(client)
        async with client.app.state.pool.connection() as conn:
            await store.create_run(
                conn,
                project_id=project_id,
                requirements_version=1,
                component="c3",
                source_version=1,
            )
            latest = await store.latest_run(conn, project_id, component="c3")
            await store.set_run_state(conn, latest["id"], "awaiting_gate")

        answer = await client.post(
            f"/projects/{project_id}/testing/target",
            json={"target": "generated", "by": "you"},
        )

        assert answer.status_code == 200, answer.text

    async def test_the_default_is_the_generated_application(self, client) -> None:
        project_id = await _a_project(client)

        snapshot = (await client.get(f"/projects/{project_id}/testing")).json()

        assert snapshot["target"] == "generated"


class TestAStageThatDoesNotApply:
    """The component refuses a target it has nothing to do on, and that refusal
    has to reach the graph as a skip rather than a failure. It was a failure
    once, which meant a Java repository could never reach the security stage.
    """

    async def test_the_client_translates_the_components_refusal(self) -> None:
        from dataclasses import dataclass

        from orchestrator.clients.c3 import InProcessC3, StageNotApplicable
        from sdlc_contracts import ApiContract, SprintPlan, VelocityAssumption

        @dataclass
        class Ref:
            kind: str = "sample"
            path: str = "java-sample"
            code_version: int | None = 1

        with pytest.raises(StageNotApplicable) as refused:
            await InProcessC3("google:gemini-3.5-flash-lite").generate_tests(
                Ref(),
                SprintPlan(
                    sprintName="Sprint 1",
                    goal="ship it",
                    velocityAssumption=VelocityAssumption(points=20, basis="assumed"),
                    estimatedPoints=0,
                ),
                ApiContract(version=1, entities=[], endpoints=[]),
                {},
                version=1,
            )

        assert "java target" in str(refused.value)
        assert refused.value.reason, "the reason travels, or the skip cannot say why"


@needs_db
class TestTestsComeForwardWithANewCodeVersion:
    """Files are keyed by version and stage and the code generator writes only
    its own stages, so a regeneration left the new version with no tests at
    all: a suite a reader approved would vanish, and the healing loop could
    never see a stale test because every run would start from a version that
    had none.
    """

    async def test_a_new_version_gets_the_previous_tests(self, client) -> None:
        project_id = await _a_project(client)
        async with client.app.state.pool.connection() as conn:
            await store.put_code_files(
                conn,
                project_id,
                version=1,
                stage_id="backend-code",
                files={"apps/api/src/app.ts": "// the app\n"},
            )
            await store.put_code_files(
                conn,
                project_id,
                version=1,
                stage_id="test-generation",
                files={"apps/api/src/__tests__/US-1.criteria.test.ts": "// a written test\n"},
            )

            carried = await store.carry_tests_forward(conn, project_id, to_version=2)
            files = await store.code_files(conn, project_id, version=2)

        assert carried == 1
        assert files["apps/api/src/__tests__/US-1.criteria.test.ts"] == "// a written test\n"
        assert "apps/api/src/app.ts" not in files, "the code generator writes its own files"

    async def test_a_first_version_has_nothing_to_carry(self, client) -> None:
        project_id = await _a_project(client)
        async with client.app.state.pool.connection() as conn:
            carried = await store.carry_tests_forward(conn, project_id, to_version=1)

        assert carried == 0

    async def test_it_takes_the_newest_version_that_had_tests(self, client) -> None:
        """Not the first one it finds. A version that carried nothing forward
        must not send an older suite back into a newer version."""
        project_id = await _a_project(client)
        async with client.app.state.pool.connection() as conn:
            for version, body in ((1, "// old\n"), (3, "// newer\n")):
                await store.put_code_files(
                    conn,
                    project_id,
                    version=version,
                    stage_id="test-generation",
                    files={"apps/api/src/__tests__/US-1.criteria.test.ts": body},
                )

            await store.carry_tests_forward(conn, project_id, to_version=4)
            files = await store.code_files(conn, project_id, version=4)

        assert files["apps/api/src/__tests__/US-1.criteria.test.ts"] == "// newer\n"
