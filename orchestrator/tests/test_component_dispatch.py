"""The supervisor dispatches by component, and refuses what it cannot run.

Before the registry, `runs.component` was read for one audit line and every
run walked the C1 graph whatever it claimed to be. These tests pin the two
behaviours that replaced that: an unknown component fails its run in plain
words, and the retry route refuses a projection stage instead of stranding it
at generating.
"""

from collections.abc import AsyncIterator

import httpx
import pytest
from orchestrator.api.deps import DEV_OWNER_ID
from orchestrator.components import COMPONENTS, spec_for, spec_for_gate_kind, stale_windows
from orchestrator.config import Settings
from orchestrator.db import store
from orchestrator.errors import DomainError
from orchestrator.graph.runner import RunSupervisor
from orchestrator.main import create_app, lifespan_for_tests

from .conftest import DATABASE_URL, needs_db

pytestmark = needs_db


@pytest.fixture
def settings() -> Settings:
    return Settings(database_url=DATABASE_URL, database_direct_url=DATABASE_URL)


@pytest.fixture
async def client(settings: Settings) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(settings, lifespan_factory=lifespan_for_tests)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            c.app = app  # type: ignore[attr-defined]
            created: list[str] = []
            c.created_projects = created  # type: ignore[attr-defined]
            try:
                yield c
            finally:
                async with app.state.pool.connection() as conn:
                    for project_id in created:
                        await store.delete_project(conn, project_id, owner_id=DEV_OWNER_ID)


async def _project(client: httpx.AsyncClient) -> str:
    created = await client.post("/projects", json={"name": "Dispatch case"})
    project_id = created.json()["id"]
    client.created_projects.append(project_id)  # type: ignore[attr-defined]
    return project_id


class TestTheRegistry:
    def test_the_unknown_component_error_names_the_known_ones(self) -> None:
        with pytest.raises(DomainError) as error:
            spec_for("c9")
        assert "c1" in error.value.message

    def test_the_unknown_gate_kind_error_names_the_known_ones(self) -> None:
        with pytest.raises(DomainError) as error:
            spec_for_gate_kind("c9-review")
        assert "c1-design-review" in error.value.message

    def test_every_component_reclaims_on_its_own_clock(self) -> None:
        windows = stale_windows()
        assert set(windows) == set(COMPONENTS)
        assert windows["c1"] == 90

    def test_the_single_component_spelling_still_constructs(self) -> None:
        supervisor = RunSupervisor(pool=None, graph="the graph", c1="the client")  # type: ignore[arg-type]
        assert supervisor._graphs == {"c1": "the graph"}
        assert supervisor._clients == {"c1": "the client"}


class TestAnUnknownComponentRun:
    async def test_it_fails_in_plain_words_instead_of_running_c1(
        self, client: httpx.AsyncClient
    ) -> None:
        project_id = await _project(client)
        app = client.app  # type: ignore[attr-defined]
        async with app.state.pool.connection() as conn:
            run = await store.create_run(
                conn, project_id=project_id, requirements_version=1, component="c9"
            )

        await app.state.supervisor.advance(run["id"])

        async with app.state.pool.connection() as conn:
            after = await store.get_run(conn, run["id"])
        assert after["state"] == "failed"
        assert "not a component this orchestrator runs" in after["error"]
        # And nothing C1 shaped happened: no stage moved, no artefact appeared.
        async with app.state.pool.connection() as conn:
            artefacts = await store.latest_artefacts(conn, project_id)
        assert artefacts == {}


class TestRetryingAProjection:
    async def test_domain_model_refuses_instead_of_stranding(
        self, client: httpx.AsyncClient
    ) -> None:
        project_id = await _project(client)
        answer = await client.post(f"/projects/{project_id}/design/stages/domain-model/retry")
        assert answer.status_code == 409
        assert "projection" in answer.json()["error"]

        # The stage row was not touched on the way to the refusal. Before the
        # guard, the route flipped it to generating, the runner failed the run,
        # and the row spun forever.
        snapshot = (await client.get(f"/projects/{project_id}/design")).json()
        assert snapshot["stages"]["domain-model"]["status"] == "pending"

    async def test_design_review_refuses_too(self, client: httpx.AsyncClient) -> None:
        project_id = await _project(client)
        answer = await client.post(f"/projects/{project_id}/design/stages/design-review/retry")
        assert answer.status_code == 409

    async def test_an_unknown_stage_is_still_a_404(self, client: httpx.AsyncClient) -> None:
        project_id = await _project(client)
        answer = await client.post(f"/projects/{project_id}/design/stages/nonsense/retry")
        assert answer.status_code == 404


class TestACodeGateIsNotADesignDecision:
    async def test_the_design_routes_refuse_it(self, client: httpx.AsyncClient) -> None:
        import uuid as _uuid

        project_id = await _project(client)
        app = client.app  # type: ignore[attr-defined]
        async with app.state.pool.connection() as conn:
            run = await store.create_run(
                conn, project_id=project_id, requirements_version=1, component="c2"
            )
            gate = await store.open_gate(
                conn,
                run_id=run["id"],
                project_id=project_id,
                requirements_version=1,
                payload={},
                interrupt_id=str(_uuid.uuid4()),
                kind="c2-code-review",
            )

        # The design decision route sees no decision of its own kind waiting.
        decision = await client.post(
            f"/projects/{project_id}/design/decision",
            json={"kind": "approved", "by": "A. Chen"},
        )
        assert decision.status_code == 409
        assert "no decision waiting" in decision.json()["error"]

        # The process route finds the gate by id and refuses it by kind, so a
        # curl of the wrong id cannot resolve another phase's gate through the
        # design funnel.
        approve = await client.post(f"/gates/{gate['id']}/approve", json={"by": "A. Chen"})
        assert approve.status_code == 409
        assert "c2-code-review" in approve.json()["error"]

        # And the gate is still pending: nothing resolved it on the way out.
        pending = await client.get(f"/gates?status=pending&project={project_id}")
        assert [g["kind"] for g in pending.json()] == ["c2-code-review"]
